"""Entry-edge diagnostic: MFE/MAE and fixed-R hit rates.

For each raw signal, walk forward up to HORIZON bars and record whether price
reached +T*R (target) before -1R (stop), for several T. Isolates the ENTRY edge
from trade-management noise. If even the best fixed-R has negative expectancy,
the entry itself needs rework — not the management.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recycler.data.oanda_data import load_frames  # noqa: E402
from recycler.strategy.momentum_pullback import MomentumPullback  # noqa: E402
from recycler.strategy.mean_reversion import MeanReversionRSI2  # noqa: E402

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
WARMUP_START = "2025-12-10T00:00:00Z"
TEST_START = pd.Timestamp("2026-01-01T00:00:00Z")
TEST_END = pd.Timestamp("2026-06-21T00:00:00Z")
HORIZON = 24            # bars (6h on M15)
TARGETS = [1.0, 1.5, 2.0, 2.5, 3.0]


def make_strategy(name: str):
    if name == "mr_rsi2":
        return MeanReversionRSI2(SYMBOLS)
    return MomentumPullback(SYMBOLS)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "momentum"
    print(f"STRATEGY: {name}")
    frames = load_frames(SYMBOLS, ["M15", "H4"], WARMUP_START, TEST_END)
    strat = make_strategy(name)
    frames = strat.prepare(frames)

    rows = []
    for sym in SYMBOLS:
        df = frames[f"{sym}@M15"]
        idx = df.index
        o = df["open"].to_numpy(); hi = df["high"].to_numpy()
        lo = df["low"].to_numpy(); cl = df["close"].to_numpy()
        n = len(df)
        for i in range(n - 1):
            if idx[i + 1] < TEST_START or idx[i + 1] > TEST_END:
                continue
            sig = strat.generate_signal(sym, frames, i)
            if sig is None:
                continue
            entry = o[i + 1]
            d = sig.direction
            R = abs(entry - sig.stop)
            if R <= 0:
                continue
            mfe = 0.0; mae = 0.0
            hit = {T: 0 for T in TARGETS}
            stopped_at = None
            first = {T: None for T in TARGETS}
            for k in range(i + 1, min(i + 1 + HORIZON, n)):
                fav = (hi[k] - entry) * d / R      # favorable excursion in R
                adv = (entry - lo[k]) * d / R if d > 0 else (hi[k] - entry) * (-d) / R
                # recompute adverse properly
                if d > 0:
                    fav = (hi[k] - entry) / R
                    adv = (entry - lo[k]) / R
                else:
                    fav = (entry - lo[k]) / R
                    adv = (hi[k] - entry) / R
                mfe = max(mfe, fav)
                mae = max(mae, adv)
                if stopped_at is None and adv >= 1.0:
                    stopped_at = k
                for T in TARGETS:
                    if first[T] is None and fav >= T:
                        first[T] = k
            for T in TARGETS:
                ft = first[T]
                # win if target reached strictly before stop (stop priority on tie)
                won = ft is not None and (stopped_at is None or ft < stopped_at)
                hit[T] = 1 if won else 0
            rows.append({"sym": sym, "dir": d, "mfe": mfe, "mae": mae,
                         **{f"hit_{T}": hit[T] for T in TARGETS}})

    r = pd.DataFrame(rows)
    print(f"signals: {len(r)}")
    print(f"\nMFE (R) quantiles:\n{r['mfe'].describe(percentiles=[.25,.5,.75,.9]).round(2)}")
    print(f"\nMAE (R) quantiles:\n{r['mae'].describe(percentiles=[.25,.5,.75,.9]).round(2)}")
    print(f"\nMedian MFE: {r['mfe'].median():.2f}R   "
          f"% reaching >=1R before stop: {100*r['hit_1.0'].mean():.1f}%")

    print("\nFixed-R target analysis (win=T, loss=-1, stop priority):")
    print(f"{'T':>5} {'winrate%':>9} {'expectancy_R':>13}")
    for T in TARGETS:
        wr = r[f"hit_{T}"].mean()
        exp = wr * T - (1 - wr) * 1.0
        print(f"{T:>5} {100*wr:>9.1f} {exp:>13.3f}")

    print("\nBy symbol (median MFE, %>=1.5R, %>=2R):")
    for sym in SYMBOLS:
        s = r[r["sym"] == sym]
        if len(s) == 0:
            continue
        print(f"  {sym}: n={len(s):3d}  medMFE={s['mfe'].median():.2f}  "
              f">=1.5R={100*s['hit_1.5'].mean():.0f}%  >=2R={100*s['hit_2.0'].mean():.0f}%")


if __name__ == "__main__":
    main()
