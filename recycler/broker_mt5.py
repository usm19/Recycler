"""MetaTrader5 execution layer for FTMO.

Encodes the gotchas surfaced in research: runtime symbol resolution (FTMO US uses
a `.sim` suffix), filling-mode bitmask detection (avoids retcode 10030), market
orders priced off the live tick, partial close via an opposing deal bound to the
position ticket, and equity/balance polling for the live drawdown guard.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from recycler.config import Settings, load_settings


@dataclass
class Account:
    login: int
    server: str
    balance: float
    equity: float
    currency: str
    leverage: int
    trade_allowed: bool
    fifo_close: bool


class MT5Broker:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or load_settings()
        self.mt5 = None
        self.connected = False
        self._symbol_cache: dict[str, str] = {}

    # ---- connection --------------------------------------------------------
    def connect(self) -> bool:
        import MetaTrader5 as mt5
        self.mt5 = mt5
        kwargs = {}
        if self.s.mt5_terminal_path:
            kwargs["path"] = self.s.mt5_terminal_path
        if not mt5.initialize(**kwargs) and not mt5.initialize():
            print("[mt5] initialize failed:", mt5.last_error())
            return False

        ai = mt5.account_info()
        if ai and int(ai.login) == int(self.s.mt5_login):
            self.connected = True
            print(f"[mt5] attached to {ai.login} @ {ai.server}")
            return True

        servers = [self.s.mt5_server, "FTMO-Demo", "FTMO-Demo2",
                   "FTMO-Server", "FTMO-Server2", "FTMO-Server3"]
        seen = set()
        for server in [x for x in servers if x and not (x in seen or seen.add(x))]:
            for pw in (self.s.mt5_master_password, self.s.mt5_password):
                if pw and mt5.login(int(self.s.mt5_login), password=pw, server=server):
                    self.connected = True
                    print(f"[mt5] logged in @ {server}")
                    return True
        print("[mt5] login failed:", mt5.last_error())
        return False

    def shutdown(self):
        if self.mt5:
            self.mt5.shutdown()
        self.connected = False

    # ---- info --------------------------------------------------------------
    def account(self) -> Optional[Account]:
        ai = self.mt5.account_info()
        if not ai:
            return None
        return Account(int(ai.login), ai.server, ai.balance, ai.equity, ai.currency,
                       ai.leverage, bool(ai.trade_allowed), bool(getattr(ai, "fifo_close", False)))

    def resolve_symbol(self, base: str) -> Optional[str]:
        if base in self._symbol_cache:
            return self._symbol_cache[base]
        syms = self.mt5.symbols_get()
        match = None
        for s in syms or []:
            name = s.name
            if name == base or name.startswith(base + ".") or name.startswith(base + "+") \
               or name.replace("_", "") == base:
                match = name
                break
        if match:
            self.mt5.symbol_select(match, True)
            self._symbol_cache[base] = match
        return match

    def _filling(self, sym: str):
        fm = self.mt5.symbol_info(sym).filling_mode
        if fm & 1:
            return self.mt5.ORDER_FILLING_FOK
        if fm & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def tick(self, sym: str):
        self.mt5.symbol_select(sym, True)
        return self.mt5.symbol_info_tick(sym)

    # ---- orders ------------------------------------------------------------
    def market_order(self, base: str, direction: int, lots: float,
                     sl: float, tp: float, magic: int = 770001,
                     comment: str = "recycler") -> Optional[object]:
        mt5 = self.mt5
        sym = self.resolve_symbol(base)
        if not sym:
            print(f"[mt5] symbol not found for {base}")
            return None
        info = mt5.symbol_info(sym)
        digits = info.digits
        tk = self.tick(sym)
        price = tk.ask if direction > 0 else tk.bid
        lots = max(info.volume_min, round(lots / info.volume_step) * info.volume_step)
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lots),
            "type": mt5.ORDER_TYPE_BUY if direction > 0 else mt5.ORDER_TYPE_SELL,
            "price": price, "sl": round(sl, digits), "tp": round(tp, digits),
            "deviation": 20, "magic": magic, "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(sym),
        }
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            rc = res.retcode if res else mt5.last_error()
            cm = res.comment if res else ""
            print(f"[mt5] order failed: {rc} {cm}")
            return None
        return res

    def modify_sl_tp(self, position, sl: float = None, tp: float = None) -> bool:
        mt5 = self.mt5
        digits = mt5.symbol_info(position.symbol).digits
        req = {"action": mt5.TRADE_ACTION_SLTP, "position": position.ticket,
               "symbol": position.symbol}
        req["sl"] = round(sl, digits) if sl is not None else position.sl
        req["tp"] = round(tp, digits) if tp is not None else position.tp
        res = mt5.order_send(req)
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def close_position(self, position, fraction: float = 1.0) -> bool:
        mt5 = self.mt5
        info = mt5.symbol_info(position.symbol)
        is_buy = position.type == mt5.POSITION_TYPE_BUY
        tk = self.tick(position.symbol)
        vol = position.volume * fraction
        vol = max(info.volume_min, round(vol / info.volume_step) * info.volume_step)
        vol = min(vol, position.volume)
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": position.symbol,
            "position": position.ticket, "volume": float(vol),
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": tk.bid if is_buy else tk.ask, "deviation": 20,
            "magic": position.magic, "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(position.symbol),
        }
        res = mt5.order_send(req)
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def positions(self, magic: int = None):
        ps = self.mt5.positions_get() or []
        if magic is not None:
            ps = [p for p in ps if p.magic == magic]
        return list(ps)
