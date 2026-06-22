"""Autonomous trading bot.

Signals come from OANDA data (identical to the backtest); execution is either a
PAPER simulator (default, no MT5 needed) or live MT5/FTMO. Enforces the risk
guard, red-folder news blackout, one-trade-per-day, intraday flat-before-rollover,
Telegram alerts and Supabase logging.

Run paper:  .venv\\Scripts\\python.exe -m recycler.live.bot paper
Run once:   .venv\\Scripts\\python.exe -m recycler.live.bot paper --once
Run live:   .venv\\Scripts\\python.exe -m recycler.live.bot live   (needs MT5 login working)
"""
from __future__ import annotations

import sys
import time
import traceback
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from recycler import instruments, preset
from recycler.config import load_settings
from recycler.data.oanda_data import get_candles, get_last_price, get_recent_frames
from recycler.live.risk import RiskConfig, RiskGuard
from recycler.news import NewsCalendar
from recycler.notify import Telegram, fmt_trade_close, fmt_trade_open
from recycler.storage import Supabase
from recycler.strategy.base import Signal
from recycler.util import cet_day, parse_hm, utc_hm

POLL_SECONDS = 20
TARGET_R = 2.5         # preset uses fixed 2.5R
MAX_HOLD_H1 = 8


@dataclass
class Position:
    symbol: str
    direction: int
    entry_time: pd.Timestamp
    entry: float
    stop: float
    tp: float
    lots: float
    R_price: float
    bars_held: int = 0
    broker_ref: object = None


class PaperExecutor:
    """Virtual fills against OANDA mid price. One position at a time."""
    def __init__(self, account_size: float):
        self.cash = account_size
        self.pos: Optional[Position] = None

    def equity(self) -> float:
        if not self.pos:
            return self.cash
        price = get_last_price(instruments.get(self.pos.symbol).oanda) or self.pos.entry
        vpp = instruments.usd_value_per_price(self.pos.symbol, price)
        floating = self.pos.direction * (price - self.pos.entry) * vpp * self.pos.lots
        return self.cash + floating

    def place(self, sym, direction, lots, entry, stop, tp, R_price) -> Position:
        self.pos = Position(sym, direction, pd.Timestamp.now(tz="UTC"), entry, stop, tp,
                            lots, R_price)
        return self.pos

    def close(self, price: float, reason: str) -> float:
        p = self.pos
        vpp = instruments.usd_value_per_price(p.symbol, price)
        spec = instruments.get(p.symbol)
        fill = price - p.direction * spec.cost_price / 2.0
        pnl = p.direction * (fill - p.entry) * vpp * p.lots
        self.cash += pnl
        self.pos = None
        return pnl


class MT5Executor:
    def __init__(self, account_size: float):
        from recycler.broker_mt5 import MT5Broker
        self.broker = MT5Broker()
        self.account_size = account_size
        self.pos: Optional[Position] = None
        if not self.broker.connect():
            raise RuntimeError("MT5 connect failed — set up the FTMO terminal first")

    def equity(self) -> float:
        a = self.broker.account()
        return a.equity if a else self.account_size

    def place(self, sym, direction, lots, entry, stop, tp, R_price) -> Optional[Position]:
        res = self.broker.market_order(sym, direction, lots, stop, tp)
        if not res:
            return None
        self.pos = Position(sym, direction, pd.Timestamp.now(tz="UTC"),
                            getattr(res, "price", entry), stop, tp, lots, R_price,
                            broker_ref=res)
        return self.pos

    def close(self, price: float, reason: str) -> float:
        # find and close the live position by magic
        ps = self.broker.positions(magic=770001)
        for p in ps:
            self.broker.close_position(p, 1.0)
        self.pos = None
        return 0.0  # realized P&L is reflected in account equity

    def broker_position_open(self) -> bool:
        return len(self.broker.positions(magic=770001)) > 0


class LiveBot:
    def __init__(self, mode: str = "paper"):
        self.s = load_settings()
        self.mode = mode
        self.acct = self.s.account_size
        self.strat = preset.make_strategy()
        self.guard = RiskGuard(RiskConfig(
            account_size=self.acct, dd_day_limit=self.s.max_drawdown_dollars,
            session_start_utc=preset.SESSION[0], session_end_utc=preset.SESSION[1]))
        self.tg = Telegram(self.s)
        self.db = Supabase(self.s)
        self.exec = PaperExecutor(self.acct) if mode == "paper" else MT5Executor(self.acct)
        self.news: Optional[NewsCalendar] = None
        self.news_day = None
        self.last_h1_time = None
        self.risk_pct = preset.DEFAULT_RISK

    def _refresh_news(self, now):
        if cet_day(now) != self.news_day:
            try:
                self.news = NewsCalendar.live()
                self.news_day = cet_day(now)
                print(f"[news] refreshed: {len(self.news.high)} high-impact events")
            except Exception as e:
                print("[news] refresh failed:", e)
                if self.news is None:
                    self.news = NewsCalendar([])

    def _new_h1_bar(self) -> Optional[pd.Timestamp]:
        df = get_candles(instruments.get("EURUSD").oanda, "H1", count=2)
        if df.empty:
            return None
        t = df.index[-1]
        if t != self.last_h1_time:
            return t
        return None

    def _manage(self, now):
        p = self.exec.pos
        if not p:
            return
        price = get_last_price(instruments.get(p.symbol).oanda) or p.entry
        # SL / TP (paper simulates; live relies on broker but we double-check)
        hit_sl = (price <= p.stop) if p.direction > 0 else (price >= p.stop)
        hit_tp = (price >= p.tp) if p.direction > 0 else (price <= p.tp)
        reason = None
        if self.mode == "live" and not self.exec.broker_position_open():
            reason = "broker_closed"
        elif hit_sl:
            reason = "stop"; price = p.stop
        elif hit_tp:
            reason = "target"; price = p.tp
        elif utc_hm(now) >= parse_hm(preset.FORCE_FLAT_UTC):
            reason = "force_flat"
        elif p.bars_held >= MAX_HOLD_H1:
            reason = "time"
        if reason:
            self._close(now, price, reason)

    def _close(self, now, price, reason):
        p = self.exec.pos
        pnl = self.exec.close(price, reason)
        equity = self.exec.equity()
        r_mult = pnl / (p.R_price * instruments.usd_value_per_price(p.symbol, p.entry) * p.lots) \
            if p.lots else 0.0
        msg = fmt_trade_close(p.symbol, reason, pnl, r_mult, equity)
        print(msg)
        self.tg.send(msg)
        self.db.log_trade(mode=self.mode, symbol=p.symbol, direction=p.direction,
                          entry_time=str(p.entry_time), exit_time=str(now), entry=p.entry,
                          exit_price=price, stop=p.stop, size_lots=p.lots, pnl=round(pnl, 2),
                          r_multiple=round(r_mult, 3), reason=reason, risk_pct=self.risk_pct,
                          equity_after=round(equity, 2), tag=self.strat.name)

    def _try_enter(self, now):
        equity = self.exec.equity()
        ok, why = self.guard.can_open(now, equity)
        if not ok:
            return
        frames = get_recent_frames(preset.SYMBOLS, preset.PRIMARY_TF, preset.HTF)
        try:
            self.strat.prepare(frames)
        except Exception as e:
            print("[prepare] error:", e)
            return
        cands: list[tuple[str, Signal]] = []
        for sym in preset.SYMBOLS:
            df = frames[f"{sym}@{preset.PRIMARY_TF}"]
            if len(df) < 5:
                continue
            sig = self.strat.generate_signal(sym, frames, len(df) - 1)
            if sig is None:
                continue
            if self.news and self.news.is_blackout(now, sym, preset.NEWS_BEFORE_MIN,
                                                    preset.NEWS_AFTER_MIN):
                print(f"[news] blackout skip {sym}")
                continue
            cands.append((sym, sig))
        if not cands:
            return
        sym, sig = max(cands, key=lambda c: c[1].meta.get("score", 0.0))
        price = get_last_price(instruments.get(sym).oanda)
        if not price:
            return
        R = abs(price - sig.stop)
        if R <= 0:
            return
        risk_dollars = self.risk_pct * equity
        lots = instruments.lots_for_risk(sym, risk_dollars, R, price)
        if lots <= 0:
            return
        tp = price + sig.direction * TARGET_R * R
        pos = self.exec.place(sym, sig.direction, round(lots, 2), price, sig.stop, tp, R)
        if not pos:
            return
        self.guard.register_open()
        msg = fmt_trade_open(sym, sig.direction, price, sig.stop, tp, round(lots, 2), risk_dollars)
        print(msg)
        self.tg.send(msg)
        self.db.log_event("info", "entry", f"{sym} {'LONG' if sig.direction>0 else 'SHORT'}",
                          {"lots": round(lots, 2), "stop": sig.stop, "tp": tp})

    def loop_once(self):
        now = pd.Timestamp.now(tz="UTC")
        self._refresh_news(now)
        equity = self.exec.equity()
        self.guard.on_tick(now, equity)
        new_bar = self._new_h1_bar()
        if new_bar is not None:
            if self.exec.pos:
                self.exec.pos.bars_held += 1
            self.last_h1_time = new_bar
        self._manage(now)
        if not self.exec.pos and new_bar is not None:
            self._try_enter(now)

    def run(self, once: bool = False):
        start = (f"🤖 <b>Recycler bot online</b> ({self.mode})\n"
                 f"Strategy: {self.strat.name} | risk {self.risk_pct:.2%}/trade\n"
                 f"Account: ${self.acct:,.0f} | DD guard ${self.s.max_drawdown_dollars:,.0f}")
        print(start)
        self.tg.send(start)
        self.db.log_event("info", "start", f"bot online ({self.mode})")
        while True:
            try:
                self.loop_once()
            except Exception as e:
                print("[loop] error:", e)
                traceback.print_exc()
                self.db.log_event("error", "loop", str(e))
            if once:
                break
            time.sleep(POLL_SECONDS)


def main():
    mode = "paper"
    once = "--once" in sys.argv
    for a in sys.argv[1:]:
        if a in ("paper", "live"):
            mode = a
    LiveBot(mode).run(once=once)


if __name__ == "__main__":
    main()
