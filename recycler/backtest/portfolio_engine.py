"""Multi-position PORTFOLIO backtester.

Holds concurrent positions across many instruments — the structure trend-following
needs, because the edge lives at the portfolio level (any single market is ~break
-even; the diversified basket is what pays). Reuses the Trade model and realistic
cost/stop-priority/mark-to-market-DD logic from the single-position engine.

Risk control suitable for FTMO:
  * risk_per_trade % of current equity, one position per symbol,
  * max_concurrent positions and max_total_open_risk cap,
  * FTMO daily / overall loss halts on total equity (mark-to-market).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

from recycler import instruments
from recycler.backtest.engine import Trade, _value_per_price
from recycler.strategy.base import Signal, Strategy
from recycler.util import cet_day, parse_hm, utc_hm


@dataclass
class PortfolioConfig:
    account_size: float = 100_000.0
    risk_pct: float = 0.005
    max_concurrent: int = 4
    max_total_risk_pct: float = 0.03        # cap sum of open initial risk
    max_new_per_day: int = 99               # entries opened per CET day
    session_start_utc: Optional[str] = None # None = trade any hour (swing)
    session_end_utc: Optional[str] = None
    force_flat_utc: Optional[str] = None    # None = no intraday flat (swing)
    daily_loss_limit: float = 4_000.0
    overall_loss_limit: float = 9_000.0
    use_guards: bool = True
    one_dir_per_symbol: bool = True
    news_blackout: Optional[Callable[[pd.Timestamp, str], bool]] = None
    entry_start: Optional[pd.Timestamp] = None
    entry_end: Optional[pd.Timestamp] = None


class PortfolioBacktester:
    def __init__(self, strategy: Strategy, frames: dict[str, pd.DataFrame],
                 config: PortfolioConfig):
        self.strat = strategy
        self.frames = frames
        self.cfg = config
        self.tf = strategy.primary_tf
        self.symbols = strategy.symbols

    def _signals(self) -> dict[str, dict[pd.Timestamp, Signal]]:
        out: dict[str, dict[pd.Timestamp, Signal]] = {}
        for sym in self.symbols:
            df = self.frames[Strategy.key(sym, self.tf)]
            idx = df.index
            mp: dict[pd.Timestamp, Signal] = {}
            for i in range(len(df) - 1):
                s = self.strat.generate_signal(sym, self.frames, i)
                if s is not None:
                    mp[idx[i + 1]] = s
            out[sym] = mp
        return out

    def run(self) -> dict:
        cfg = self.cfg
        sig = self._signals()
        union = pd.DatetimeIndex(sorted(set().union(
            *[set(self.frames[Strategy.key(s, self.tf)].index) for s in self.symbols])))
        cols = {}
        for sym in self.symbols:
            df = self.frames[Strategy.key(sym, self.tf)].reindex(union)
            cols[sym] = {k: df[k].to_numpy() for k in ("open", "high", "low", "close")}
            cols[sym]["atr"] = (df["atr"].to_numpy() if "atr" in df.columns
                                else np.full(len(df), np.nan))

        sess = (cfg.session_start_utc is not None)
        s0 = parse_hm(cfg.session_start_utc) if sess else 0.0
        s1 = parse_hm(cfg.session_end_utc) if sess else 24.0
        flat_h = parse_hm(cfg.force_flat_utc) if cfg.force_flat_utc else None

        cash = cfg.account_size
        peak = cfg.account_size
        max_dd = 0.0
        day_key = None
        day_anchor = cfg.account_size
        new_today = 0
        daily_halt = global_halt = False
        positions: dict[str, Trade] = {}
        trades: list[Trade] = []
        curve: list[tuple[pd.Timestamp, float]] = []

        def total_open_risk() -> float:
            return sum(t.risk_dollars for t in positions.values())

        for p, t in enumerate(union):
            dk = cet_day(t)
            if dk != day_key:
                day_key, day_anchor, new_today, daily_halt = dk, cash + self._floating(positions, cols, p), 0, False

            # manage open positions
            for sym in list(positions.keys()):
                tr = positions[sym]
                if np.isnan(cols[sym]["open"][p]) or t <= tr.entry_time:
                    continue
                closed = self._manage(tr, t, cols[sym], p, flat_h)
                if closed:
                    cash += tr.pnl
                    trades.append(tr)
                    del positions[sym]

            # mark-to-market equity + DD
            floating = self._floating(positions, cols, p)
            equity = cash + floating
            worst = cash + self._floating(positions, cols, p, adverse=True)
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - worst)
            curve.append((t, equity))

            if cfg.use_guards:
                if cfg.account_size - worst >= cfg.overall_loss_limit:
                    global_halt = True
                if day_anchor - worst >= cfg.daily_loss_limit:
                    daily_halt = True
            if global_halt:
                # close everything and stop opening
                for sym in list(positions.keys()):
                    tr = positions[sym]
                    self._close(tr, t, cols[sym]["close"][p], "global_halt")
                    cash += tr.pnl; trades.append(tr); del positions[sym]
                continue

            in_win = ((cfg.entry_start is None or t >= cfg.entry_start)
                      and (cfg.entry_end is None or t <= cfg.entry_end))
            if daily_halt or not in_win or new_today >= cfg.max_new_per_day:
                continue
            if sess and not (s0 <= utc_hm(t) <= s1):
                continue
            if len(positions) >= cfg.max_concurrent:
                continue

            # consider entries (sorted by score desc for determinism)
            cands = []
            for sym in self.symbols:
                if sym in positions:
                    continue
                s = sig[sym].get(t)
                if s is None or np.isnan(cols[sym]["open"][p]):
                    continue
                if cfg.news_blackout and cfg.news_blackout(t, sym):
                    continue
                cands.append((sym, s))
            cands.sort(key=lambda c: c[1].meta.get("score", 0.0), reverse=True)
            for sym, s in cands:
                if len(positions) >= cfg.max_concurrent or new_today >= cfg.max_new_per_day:
                    break
                tr = self._enter(sym, s, t, cols[sym], p, equity)
                if tr is None:
                    continue
                if (total_open_risk() + tr.risk_dollars) / cfg.account_size > cfg.max_total_risk_pct:
                    continue
                positions[sym] = tr
                new_today += 1
                # process entry bar
                if self._manage(tr, t, cols[sym], p, flat_h):
                    cash += tr.pnl; trades.append(tr); del positions[sym]

        # close dangling
        last = union[-1]
        for sym in list(positions.keys()):
            tr = positions[sym]
            self._close(tr, last, cols[sym]["close"][-1], "eod")
            cash += tr.pnl; trades.append(tr); del positions[sym]

        eq_df = pd.DataFrame(curve, columns=["time", "equity"]).set_index("time")
        return {"trades": trades, "equity_curve": eq_df, "final_equity": cash,
                "max_drawdown": max_dd, "config": cfg}

    # ---- helpers (mirror single-engine, adverse-aware) ----
    def _floating(self, positions, cols, p, adverse: bool = False) -> float:
        tot = 0.0
        for sym, tr in positions.items():
            hi, lo = cols[sym]["high"][p], cols[sym]["low"][p]
            if np.isnan(hi):
                price = tr.entry
            elif adverse:
                price = lo if tr.direction > 0 else hi
            else:
                price = cols[sym]["close"][p]
            tot += tr.direction * (price - tr.entry) * tr.value_per_price * tr.remaining_lots
            tot += tr.realized_pnl
        return tot

    def _enter(self, sym, s: Signal, t, c, p, equity) -> Optional[Trade]:
        spec = instruments.get(sym)
        half = spec.cost_price / 2.0
        entry = c["open"][p] + s.direction * half
        R = abs(entry - s.stop)
        if R <= 0 or np.isnan(R):
            return None
        vpp = _value_per_price(sym, entry)
        size = (self.cfg.risk_pct * equity) / (R * vpp)
        if size <= 0 or np.isnan(size):
            return None
        tr = Trade(symbol=sym, direction=s.direction, entry_time=t, entry=entry,
                   init_stop=s.stop, R_price=R, size_lots=size, value_per_price=vpp,
                   target_R=s.target_R, partial_R=s.partial_R, partial_frac=s.partial_frac,
                   be_after_R=s.breakeven_after_R, be_buffer_R=s.breakeven_buffer_R,
                   trail_atr_mult=s.trail_atr_mult, max_hold_bars=s.max_hold_bars, tag=s.tag)
        tr.stop, tr.remaining_lots = s.stop, size
        return tr

    def _price_at_R(self, tr, r):
        return tr.entry + tr.direction * r * tr.R_price

    def _manage(self, tr: Trade, t, c, p, flat_h) -> bool:
        hi, lo, op, cl, atr = (c["high"][p], c["low"][p], c["open"][p], c["close"][p], c["atr"][p])
        d = tr.direction
        tr.bars_held += 1
        if flat_h is not None and utc_hm(t) >= flat_h:
            self._close(tr, t, op, "force_flat"); return True
        tgt = self._price_at_R(tr, tr.target_R) if tr.target_R else None
        part = self._price_at_R(tr, tr.partial_R) if (tr.partial_R and not tr.partial_done) else None
        stop_hit = (lo <= tr.stop) if d > 0 else (hi >= tr.stop)
        tgt_hit = tgt is not None and ((hi >= tgt) if d > 0 else (lo <= tgt))
        part_hit = part is not None and ((hi >= part) if d > 0 else (lo <= part))
        if stop_hit:
            self._close(tr, t, tr.stop, "stop"); return True
        if part_hit:
            half = instruments.get(tr.symbol).cost_price / 2.0
            fill = part - d * half
            lots = min(tr.size_lots * tr.partial_frac, tr.remaining_lots)
            tr.realized_pnl += d * (fill - tr.entry) * tr.value_per_price * lots
            tr.remaining_lots -= lots
            tr.partial_done = True
            if tr.be_after_R is not None:
                tr.stop = tr.entry + d * tr.be_buffer_R * tr.R_price; tr.be_done = True
        if not tr.be_done and tr.be_after_R is not None:
            bt = self._price_at_R(tr, tr.be_after_R)
            if (hi >= bt) if d > 0 else (lo <= bt):
                tr.stop = tr.entry + d * tr.be_buffer_R * tr.R_price; tr.be_done = True
        if tgt_hit and tr.remaining_lots > 0:
            self._close(tr, t, tgt, "target"); return True
        if tr.trail_atr_mult is not None and not np.isnan(atr):
            if d > 0:
                tr.stop = max(tr.stop, hi - tr.trail_atr_mult * atr)
            else:
                tr.stop = min(tr.stop, lo + tr.trail_atr_mult * atr)
        if tr.max_hold_bars is not None and tr.bars_held >= tr.max_hold_bars:
            self._close(tr, t, cl, "time"); return True
        return False

    def _close(self, tr: Trade, t, price, reason):
        half = instruments.get(tr.symbol).cost_price / 2.0
        fill = price - tr.direction * half
        tr.realized_pnl += tr.direction * (fill - tr.entry) * tr.value_per_price * tr.remaining_lots
        tr.remaining_lots = 0.0
        tr.exit_time, tr.exit_reason, tr.pnl = t, reason, tr.realized_pnl
        tr.r_multiple = tr.pnl / tr.risk_dollars if tr.risk_dollars else 0.0
