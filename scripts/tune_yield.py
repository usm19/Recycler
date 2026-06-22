"""Yield/risk tuner for the archetype(s) that survived the walk-forward.

For each chosen strategy, sweep per-trade risk x max-trades-per-day over the full
2023->2026 history and report monthly yield, win rate, and max drawdown vs FTMO's
10%. Answers: can this reach ~5%/month while staying FTMO-legal, and at what win
rate? Edit CHOICES after seeing walkforward.py results.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recycler.backtest.engine import Backtester, BacktestConfig  # noqa: E402
from recycler.backtest import metrics as M  # noqa: E402
from recycler.data.oanda_data import load_frames  # noqa: E402
from recycler.strategy.momentum_pullback import MomentumPullback  # noqa: E402
from recycler.strategy.mean_reversion import MeanReversionRSI2  # noqa: E402
from recycler.strategy.breakout import DonchianBreakout  # noqa: E402

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
WARMUP = "2023-01-01T00:00:00Z"
END = pd.Timestamp("2026-06-21T00:00:00Z")
START = pd.Timestamp("2023-01-01T00:00:00Z")
STOP = pd.Timestamp("2026-06-20T23:59:00Z")

RISKS = [0.005, 0.0075, 0.010]
FREQS = [1, 2, 3]

# Filled in after walkforward.py — placeholder defaults span all archetypes.
CHOICES = [
    ("mom_H1", lambda S: MomentumPullback(S, primary_tf="H1", htf="H4", target_R=2.5,
        partial_R=None, breakeven_after_R=None, trail_atr_mult=None, max_hold_bars=8, adx_min=20),
     ["H1", "H4"], ("06:00", "16:00"), "20:00"),
    ("mr_H1", lambda S: MeanReversionRSI2(S, primary_tf="H1", htf="H4", target_R=1.0,
        stop_atr=2.0, trend_ema=100, rsi_buy=10, rsi_sell=90, max_hold_bars=8),
     ["H1", "H4"], ("06:00", "16:00"), "20:00"),
    ("don20_H4", lambda S: DonchianBreakout(S, primary_tf="H4", htf="H4", channel=20,
        stop_atr=2.0, trail_atr_mult=3.0, trend_ema=100, max_hold_bars=None),
     ["H4"], ("00:00", "23:59"), "23:59"),
]

MONTHS = 41.5 / 12 * 12  # ~41.5 months in window; use real count below


def run(strat, frames, session, flat, risk, freq):
    cfg = BacktestConfig(risk_pct=risk, session_start_utc=session[0], session_end_utc=session[1],
                         force_flat_utc=flat, max_trades_per_day=freq,
                         entry_start=START, entry_end=STOP)
    return M.compute(Backtester(strat, frames, cfg).run())


def main():
    months = (STOP - START).days / 30.4375
    for name, factory, tfs, session, flat in CHOICES:
        frames = load_frames(SYMBOLS, tfs, WARMUP, END)
        if "H4" not in tfs:
            frames.update(load_frames(SYMBOLS, ["H4"], WARMUP, END))
        strat = factory(SYMBOLS)
        strat.prepare(frames)
        print(f"\n=== {name} ===  (window ~{months:.1f} months)")
        print(f"{'risk':>6} {'freq':>4} {'trades':>7} {'win%':>5} {'expR':>6} "
              f"{'totRet%':>8} {'~mo%':>6} {'maxDD%':>7} {'FTMO?':>6}")
        for risk in RISKS:
            for freq in FREQS:
                m = run(strat, frames, session, flat, risk, freq)
                if not m.get("n_trades", 0):
                    continue
                mo = m["total_return_pct"] / months
                ftmo = "OK" if m["max_drawdown_pct"] < 10 else "FAIL"
                print(f"{risk:>6.2%} {freq:>4} {m['n_trades']:>7} "
                      f"{m['net_win_rate_pct']:>5} {m['expectancy_R']:>+6.2f} "
                      f"{m['total_return_pct']:>8.1f} {mo:>6.2f} "
                      f"{m['max_drawdown_pct']:>7.1f} {ftmo:>6}")


if __name__ == "__main__":
    main()
