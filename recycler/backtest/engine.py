"""Event-driven, account-level backtest engine.

Design choices that keep results HONEST:
  * Decisions use only bars that have fully closed; entry is the NEXT bar's open.
  * Realistic round-trip cost (spread+slippage) split across entry and EVERY exit
    leg, including partials.
  * Intrabar exits resolved with STOP PRIORITY when a bar straddles both stop and
    target (pessimistic) — never the optimistic assumption.
  * Drawdown is marked-to-market against each bar's ADVERSE extreme, not just
    closed equity, so reported max DD reflects real intraday pain.
  * Portfolio-level: at most ONE open position and ONE trade per CET day across
    ALL symbols (the user's discipline rule), with FTMO daily/overall guards.

Position sizing is exact for USD-quoted pairs (EURUSD, XAUUSD...) and USD-base
pairs (USDJPY, USDCAD via 1/price); crosses are out of scope by default.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

from recycler import instruments
from recycler.strategy.base import Signal, Strategy
from recycler.util import cet_day, parse_hm, tf_minutes, utc_hm


@dataclass
class BacktestConfig:
    account_size: float = 100_000.0
    risk_pct: float = 0.003                # fraction of equity risked per trade
    session_start_utc: str = "07:00"       # earliest entry
    session_end_utc: str = "13:00"         # latest entry
    force_flat_utc: str = "20:00"          # hard flat (well before 21:00 rollover)
    max_trades_per_day: int = 1
    daily_loss_limit: float = 4_000.0      # buffer under FTMO's $5,000
    overall_loss_limit: float = 9_000.0    # buffer under FTMO's $10,000
    use_guards: bool = True
    compound: bool = True
    pick: str = "score"                    # "score" (meta['score']) or "first"
    news_blackout: Optional[Callable[[pd.Timestamp, str], bool]] = None
    entry_start: Optional[pd.Timestamp] = None   # only OPEN trades in [start, end]
    entry_end: Optional[pd.Timestamp] = None


@dataclass
class Trade:
    symbol: str
    direction: int
    entry_time: pd.Timestamp
    entry: float
    init_stop: float
    R_price: float
    size_lots: float
    value_per_price: float
    target_R: Optional[float]
    partial_R: Optional[float]
    partial_frac: float
    be_after_R: Optional[float]
    be_buffer_R: float
    trail_atr_mult: Optional[float]
    max_hold_bars: Optional[int]
    tag: str = ""
    stop: float = 0.0
    remaining_lots: float = 0.0
    partial_done: bool = False
    be_done: bool = False
    realized_pnl: float = 0.0
    bars_held: int = 0
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: str = ""
    pnl: float = 0.0
    r_multiple: float = 0.0

    @property
    def risk_dollars(self) -> float:
        return self.R_price * self.value_per_price * self.size_lots


def _value_per_price(symbol: str, price: float) -> float:
    spec = instruments.get(symbol)
    base, quote = symbol[:3], symbol[3:6]
    if spec.is_metal or quote == "USD":
        return spec.contract_per_price            # USD-quoted: exact
    if base == "USD":
        return spec.contract_per_price / price    # USD-base: 1/price
    return spec.contract_per_price / price        # crosses (approx; excluded by default)


class Backtester:
    def __init__(self, strategy: Strategy, frames: dict[str, pd.DataFrame],
                 config: BacktestConfig):
        self.strat = strategy
        self.frames = frames
        self.cfg = config
        self.tf = strategy.primary_tf
        self.tf_min = tf_minutes(self.tf)
        self.symbols = strategy.symbols

    def _build_signals(self) -> dict[str, dict[pd.Timestamp, Signal]]:
        out: dict[str, dict[pd.Timestamp, Signal]] = {}
        for sym in self.symbols:
            df = self.frames[Strategy.key(sym, self.tf)]
            idx = df.index
            sig_map: dict[pd.Timestamp, Signal] = {}
            for i in range(len(df) - 1):
                s = self.strat.generate_signal(sym, self.frames, i)
                if s is not None:
                    sig_map[idx[i + 1]] = s        # enter at next bar's open
            out[sym] = sig_map
        return out

    def run(self) -> dict:
        cfg = self.cfg
        sig_by_sym = self._build_signals()

        union = pd.DatetimeIndex(sorted(set().union(
            *[set(self.frames[Strategy.key(s, self.tf)].index) for s in self.symbols])))

        cols = {}
        for sym in self.symbols:
            df = self.frames[Strategy.key(sym, self.tf)].reindex(union)
            cols[sym] = {k: df[k].to_numpy() for k in ("open", "high", "low", "close")}
            cols[sym]["atr"] = (df["atr"].to_numpy() if "atr" in df.columns
                                else np.full(len(df), np.nan))

        sess_start, sess_end = parse_hm(cfg.session_start_utc), parse_hm(cfg.session_end_utc)
        flat_h = parse_hm(cfg.force_flat_utc)

        equity = peak = cfg.account_size
        max_dd = 0.0
        day_key = None
        day_anchor = equity
        trades_today = 0
        daily_halt = global_halt = False
        open_trade: Optional[Trade] = None
        trades: list[Trade] = []
        curve: list[tuple[pd.Timestamp, float]] = []

        def apply_guards(eq):
            nonlocal daily_halt, global_halt
            if not cfg.use_guards:
                return
            if day_anchor - eq >= cfg.daily_loss_limit:
                daily_halt = True
            if cfg.account_size - eq >= cfg.overall_loss_limit:
                global_halt = True

        for p, t in enumerate(union):
            dk = cet_day(t)
            if dk != day_key:
                day_key, day_anchor, trades_today, daily_halt = dk, equity, 0, False

            # manage open trade (skip the entry bar; handled at entry)
            if open_trade is not None:
                sym = open_trade.symbol
                if not np.isnan(cols[sym]["open"][p]) and t > open_trade.entry_time:
                    closed, worst_float = self._manage_bar(open_trade, t, cols[sym], p, flat_h)
                    cur_worst = equity + open_trade.realized_pnl + worst_float
                    max_dd = max(max_dd, peak - cur_worst)
                    if closed:
                        equity += open_trade.pnl
                        peak = max(peak, equity)
                        max_dd = max(max_dd, peak - equity)
                        trades.append(open_trade)
                        apply_guards(equity)
                        open_trade = None

            curve.append((t, equity))
            if global_halt:
                continue

            in_window = ((cfg.entry_start is None or t >= cfg.entry_start)
                         and (cfg.entry_end is None or t <= cfg.entry_end))
            if (open_trade is None and not daily_halt and in_window
                    and trades_today < cfg.max_trades_per_day
                    and sess_start <= utc_hm(t) <= sess_end):
                cands: list[tuple[str, Signal]] = []
                for sym in self.symbols:
                    s = sig_by_sym[sym].get(t)
                    if s is None or np.isnan(cols[sym]["open"][p]):
                        continue
                    if cfg.news_blackout and cfg.news_blackout(t, sym):
                        continue
                    cands.append((sym, s))
                if cands:
                    sym, sig = self._pick(cands)
                    tr = self._enter(sym, sig, t, cols[sym], p, equity)
                    if tr is not None:
                        trades_today += 1
                        closed, worst_float = self._manage_bar(tr, t, cols[sym], p, flat_h)
                        cur_worst = equity + tr.realized_pnl + worst_float
                        max_dd = max(max_dd, peak - cur_worst)
                        if closed:
                            equity += tr.pnl
                            peak = max(peak, equity)
                            max_dd = max(max_dd, peak - equity)
                            trades.append(tr)
                            apply_guards(equity)
                        else:
                            open_trade = tr

        if open_trade is not None:
            sym = open_trade.symbol
            self._close_remaining(open_trade, union[-1], cols[sym]["close"][-1], "eod_forced")
            equity += open_trade.pnl
            trades.append(open_trade)

        eq_df = pd.DataFrame(curve, columns=["time", "equity"]).set_index("time")
        return {"trades": trades, "equity_curve": eq_df, "final_equity": equity,
                "max_drawdown": max_dd, "config": cfg}

    def _pick(self, cands):
        if self.cfg.pick == "score":
            return max(cands, key=lambda c: c[1].meta.get("score", 0.0))
        return cands[0]

    def _enter(self, sym, sig: Signal, t, c, p, equity) -> Optional[Trade]:
        spec = instruments.get(sym)
        half = spec.cost_price / 2.0
        entry = c["open"][p] + sig.direction * half
        R_price = abs(entry - sig.stop)
        if R_price <= 0 or np.isnan(R_price):
            return None
        vpp = _value_per_price(sym, entry)
        base_eq = equity if self.cfg.compound else self.cfg.account_size
        size = (self.cfg.risk_pct * base_eq) / (R_price * vpp)
        if size <= 0 or np.isnan(size):
            return None
        tr = Trade(symbol=sym, direction=sig.direction, entry_time=t, entry=entry,
                   init_stop=sig.stop, R_price=R_price, size_lots=size, value_per_price=vpp,
                   target_R=sig.target_R, partial_R=sig.partial_R, partial_frac=sig.partial_frac,
                   be_after_R=sig.breakeven_after_R, be_buffer_R=sig.breakeven_buffer_R,
                   trail_atr_mult=sig.trail_atr_mult, max_hold_bars=sig.max_hold_bars, tag=sig.tag)
        tr.stop, tr.remaining_lots = sig.stop, size
        return tr

    def _price_at_R(self, tr: Trade, r: float) -> float:
        return tr.entry + tr.direction * r * tr.R_price

    def _manage_bar(self, tr: Trade, t, c, p, flat_h):
        hi, lo, op, cl, atr = (c["high"][p], c["low"][p], c["open"][p],
                               c["close"][p], c["atr"][p])
        d = tr.direction
        tr.bars_held += 1
        adverse = lo if d > 0 else hi
        worst_float = d * (adverse - tr.entry) * tr.value_per_price * tr.remaining_lots

        if utc_hm(t) >= flat_h:                       # session hard-flat
            self._close_remaining(tr, t, op, "force_flat")
            return True, worst_float

        tgt = self._price_at_R(tr, tr.target_R) if tr.target_R else None
        part = self._price_at_R(tr, tr.partial_R) if (tr.partial_R and not tr.partial_done) else None

        stop_hit = (lo <= tr.stop) if d > 0 else (hi >= tr.stop)
        tgt_hit = tgt is not None and ((hi >= tgt) if d > 0 else (lo <= tgt))
        part_hit = part is not None and ((hi >= part) if d > 0 else (lo <= part))

        if stop_hit:                                  # stop priority (pessimistic)
            self._close_remaining(tr, t, tr.stop, "stop")
            return True, worst_float

        if part_hit:                                  # partial profit
            half = instruments.get(tr.symbol).cost_price / 2.0
            fill = part - d * half
            lots = min(tr.size_lots * tr.partial_frac, tr.remaining_lots)
            tr.realized_pnl += d * (fill - tr.entry) * tr.value_per_price * lots
            tr.remaining_lots -= lots
            tr.partial_done = True
            if tr.be_after_R is not None:
                tr.stop = tr.entry + d * tr.be_buffer_R * tr.R_price
                tr.be_done = True

        if not tr.be_done and tr.be_after_R is not None:   # breakeven w/o partial
            bt = self._price_at_R(tr, tr.be_after_R)
            if (hi >= bt) if d > 0 else (lo <= bt):
                tr.stop = tr.entry + d * tr.be_buffer_R * tr.R_price
                tr.be_done = True

        if tgt_hit and tr.remaining_lots > 0:         # final target
            self._close_remaining(tr, t, tgt, "target")
            return True, worst_float

        if tr.trail_atr_mult is not None and tr.be_done and not np.isnan(atr):
            if d > 0:
                tr.stop = max(tr.stop, hi - tr.trail_atr_mult * atr)
            else:
                tr.stop = min(tr.stop, lo + tr.trail_atr_mult * atr)

        if tr.max_hold_bars is not None and tr.bars_held >= tr.max_hold_bars:
            self._close_remaining(tr, t, cl, "time")
            return True, worst_float

        return False, worst_float

    def _close_remaining(self, tr: Trade, t, price, reason):
        half = instruments.get(tr.symbol).cost_price / 2.0
        fill = price - tr.direction * half
        tr.realized_pnl += tr.direction * (fill - tr.entry) * tr.value_per_price * tr.remaining_lots
        tr.remaining_lots = 0.0
        tr.exit_time, tr.exit_reason, tr.pnl = t, reason, tr.realized_pnl
        tr.r_multiple = tr.pnl / tr.risk_dollars if tr.risk_dollars else 0.0
