"""Does an a-priori macro-trend (H4 50/200) confluence filter help BOTH halves?"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recycler.backtest.engine import Backtester, BacktestConfig  # noqa: E402
from recycler.backtest import metrics as M  # noqa: E402
from recycler.data.oanda_data import load_frames  # noqa: E402
from recycler.strategy.momentum_pullback import MomentumPullback  # noqa: E402

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
WARMUP = "2025-12-10T00:00:00Z"
END = pd.Timestamp("2026-06-21T00:00:00Z")
TRAIN = (pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-03-31T23:59:00Z"))
TEST = (pd.Timestamp("2026-04-01T00:00:00Z"), pd.Timestamp("2026-06-20T23:59:00Z"))
FULL = (pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-06-20T23:59:00Z"))


def run(strat, frames, win):
    cfg = BacktestConfig(risk_pct=0.003, session_start_utc="06:00", session_end_utc="16:00",
                         force_flat_utc="20:00", entry_start=win[0], entry_end=win[1])
    return M.compute(Backtester(strat, frames, cfg).run())


def line(tag, m):
    if not m.get("n_trades", 0):
        return f"{tag:<10} no trades"
    return (f"{tag:<10} n={m['n_trades']:>3} win={m['net_win_rate_pct']:>4}% "
            f"expR={m['expectancy_R']:>+6.3f} PF={m['profit_factor']:>4} "
            f"DD=${m['max_drawdown_dollars']:>7,.0f} ret={m['total_return_pct']:>+6.2f}%")


def main():
    frames = load_frames(SYMBOLS, ["H1", "H4"], WARMUP, END)
    MomentumPullback(SYMBOLS, primary_tf="H1", htf="H4").prepare(frames)
    for macro in (False, True):
        print(f"\n--- macro_filter={macro} (H1, target 2.5R, ADX>=20) ---")
        s = MomentumPullback(SYMBOLS, primary_tf="H1", htf="H4", target_R=2.5,
                             partial_R=None, breakeven_after_R=None, trail_atr_mult=None,
                             max_hold_bars=8, macro_filter=macro)
        for tag, win in (("TRAIN", TRAIN), ("TEST", TEST), ("FULL", FULL)):
            print("  " + line(tag, run(s, frames, win)))


if __name__ == "__main__":
    main()
