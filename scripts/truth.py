"""Definitive full-period picture (2023->2026), guards OFF so the FTMO halt does
not truncate the multi-year run. Reports win rate (for the 72% question),
expectancy, profit factor, total return and max drawdown for each archetype.
"""
from __future__ import annotations

import sys
from pathlib import Path

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

VARIANTS = [
    ("mom_H1", lambda S: MomentumPullback(S, primary_tf="H1", htf="H4", target_R=2.5,
        partial_R=None, breakeven_after_R=None, trail_atr_mult=None, max_hold_bars=8, adx_min=20),
     ["H1", "H4"], ("06:00", "16:00"), "20:00"),
    ("mom_H1_scaleout", lambda S: MomentumPullback(S, primary_tf="H1", htf="H4", max_hold_bars=8),
     ["H1", "H4"], ("06:00", "16:00"), "20:00"),
    ("mr_H1", lambda S: MeanReversionRSI2(S, primary_tf="H1", htf="H4", target_R=1.0,
        stop_atr=2.0, trend_ema=100, rsi_buy=10, rsi_sell=90, max_hold_bars=8),
     ["H1", "H4"], ("06:00", "16:00"), "20:00"),
    ("mr_H1_tight", lambda S: MeanReversionRSI2(S, primary_tf="H1", htf="H4", target_R=0.5,
        stop_atr=1.5, trend_ema=100, rsi_buy=5, rsi_sell=95, max_hold_bars=8),
     ["H1", "H4"], ("06:00", "16:00"), "20:00"),
    ("don55_H4", lambda S: DonchianBreakout(S, primary_tf="H4", htf="H4", channel=55,
        stop_atr=2.0, trail_atr_mult=3.0, trend_ema=100, max_hold_bars=None),
     ["H4"], ("00:00", "23:59"), "23:59"),
    ("don20_H1", lambda S: DonchianBreakout(S, primary_tf="H1", htf="H4", channel=40,
        stop_atr=2.0, trail_atr_mult=3.0, trend_ema=200, max_hold_bars=None),
     ["H1"], ("00:00", "23:59"), "23:59"),
]


def main():
    print(f"Full 2023->2026 (guards OFF), risk 0.5%/trade.\n")
    print(f"{'strategy':<16} {'trades':>7} {'win%':>6} {'expR':>7} {'PF':>5} "
          f"{'totRet%':>8} {'maxDD%':>7}")
    for name, factory, tfs, session, flat in VARIANTS:
        frames = load_frames(SYMBOLS, tfs, WARMUP, END)
        if "H4" not in tfs:
            frames.update(load_frames(SYMBOLS, ["H4"], WARMUP, END))
        strat = factory(SYMBOLS)
        strat.prepare(frames)
        cfg = BacktestConfig(risk_pct=0.005, session_start_utc=session[0],
                             session_end_utc=session[1], force_flat_utc=flat,
                             use_guards=False, entry_start=START, entry_end=STOP)
        m = M.compute(Backtester(strat, frames, cfg).run())
        if not m.get("n_trades", 0):
            print(f"{name:<16} no trades")
            continue
        print(f"{name:<16} {m['n_trades']:>7} {m['net_win_rate_pct']:>6} "
              f"{m['expectancy_R']:>+7.3f} {m['profit_factor']:>5} "
              f"{m['total_return_pct']:>8.1f} {m['max_drawdown_pct']:>7.1f}")


if __name__ == "__main__":
    main()
