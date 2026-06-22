"""Parameter-robustness grid for H1 momentum pullback.

A genuine edge appears as a CONTIGUOUS region of positive expectancy across the
grid on BOTH train and test. Scattered isolated positives = noise/overfit.
Prepares indicators once; only the decision-thresholds vary per cell.
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

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
WARMUP = "2025-12-10T00:00:00Z"
END = pd.Timestamp("2026-06-21T00:00:00Z")
TRAIN = (pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-03-31T23:59:00Z"))
TEST = (pd.Timestamp("2026-04-01T00:00:00Z"), pd.Timestamp("2026-06-20T23:59:00Z"))

ADX = [15, 20, 25, 30]
TGT = [1.5, 2.0, 2.5, 3.0]


def run(strat, frames, start, end):
    cfg = BacktestConfig(risk_pct=0.003, session_start_utc="06:00",
                         session_end_utc="16:00", force_flat_utc="20:00",
                         entry_start=start, entry_end=end)
    return M.compute(Backtester(strat, frames, cfg).run())


def main():
    frames = load_frames(SYMBOLS, ["H1", "H4"], WARMUP, END)
    base = MomentumPullback(SYMBOLS, primary_tf="H1", htf="H4")
    frames = base.prepare(frames)   # indicators once

    for label, win in (("TRAIN", TRAIN), ("TEST", TEST)):
        print(f"\n=== {label} — expectancy R  (rows=ADX_min, cols=target_R) ===")
        print("        " + "".join(f"{t:>9}" for t in TGT))
        for adx in ADX:
            cells = []
            for tgt in TGT:
                s = MomentumPullback(SYMBOLS, primary_tf="H1", htf="H4",
                                     adx_min=adx, target_R=tgt, partial_R=None,
                                     breakeven_after_R=None, trail_atr_mult=None,
                                     max_hold_bars=8)
                m = run(s, frames, *win)
                e = m.get("expectancy_R", 0.0) if m.get("n_trades", 0) else 0.0
                n = m.get("n_trades", 0)
                cells.append(f"{e:>+6.2f}({n:>2})")
            print(f"ADX{adx:>3}: " + "".join(f"{c:>9}" for c in cells))


if __name__ == "__main__":
    main()
