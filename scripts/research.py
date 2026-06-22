"""Out-of-sample research harness.

Each variant is run on TRAIN (Jan-Mar 2026) and TEST (Apr-Jun 2026) separately.
A variant is only interesting if it shows positive expectancy on BOTH halves
(robust), not just one (likely overfit / luck). Reports the key stats side by side.
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

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
WARMUP = "2025-12-10T00:00:00Z"
END = pd.Timestamp("2026-06-21T00:00:00Z")
TRAIN = (pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-03-31T23:59:00Z"))
TEST = (pd.Timestamp("2026-04-01T00:00:00Z"), pd.Timestamp("2026-06-20T23:59:00Z"))
RISK = 0.003


def variant(name, factory, primary_tf, htf, session, flat="20:00", maxhold=None):
    return dict(name=name, factory=factory, primary_tf=primary_tf, htf=htf,
                session=session, flat=flat, maxhold=maxhold)


VARIANTS = [
    variant("mom_M15_scaleout",
            lambda S: MomentumPullback(S, primary_tf="M15", htf="H4"),
            "M15", "H4", ("07:00", "13:00")),
    variant("mom_M15_pure2R",
            lambda S: MomentumPullback(S, primary_tf="M15", htf="H4", target_R=2.0,
                                       partial_R=None, breakeven_after_R=None, trail_atr_mult=None),
            "M15", "H4", ("07:00", "13:00")),
    variant("mom_H1_pure2R",
            lambda S: MomentumPullback(S, primary_tf="H1", htf="H4", target_R=2.0,
                                       partial_R=None, breakeven_after_R=None, trail_atr_mult=None,
                                       max_hold_bars=8),
            "H1", "H4", ("06:00", "16:00")),
    variant("mom_H1_scaleout",
            lambda S: MomentumPullback(S, primary_tf="H1", htf="H4", max_hold_bars=8),
            "H1", "H4", ("06:00", "16:00")),
    variant("mr_M15_smalltgt",
            lambda S: MeanReversionRSI2(S, primary_tf="M15", htf="H4", target_R=0.7,
                                        stop_atr=2.0, rsi_buy=5, rsi_sell=95, max_hold_bars=12),
            "M15", "H4", ("07:00", "16:00")),
    variant("mr_H1",
            lambda S: MeanReversionRSI2(S, primary_tf="H1", htf="H4", target_R=1.0,
                                        stop_atr=2.0, trend_ema=100, rsi_buy=10, rsi_sell=90,
                                        max_hold_bars=8),
            "H1", "H4", ("06:00", "16:00")),
]


def run_window(strat, frames, session, flat, start, end):
    cfg = BacktestConfig(risk_pct=RISK, session_start_utc=session[0],
                         session_end_utc=session[1], force_flat_utc=flat,
                         entry_start=start, entry_end=end)
    res = Backtester(strat, frames, cfg).run()
    return M.compute(res)


def fmt(m):
    if m.get("n_trades", 0) == 0:
        return f"{'-':>4} trades"
    return (f"n={m['n_trades']:>3} win={m['net_win_rate_pct']:>4}% "
            f"expR={m['expectancy_R']:>+6.3f} PF={m['profit_factor']:>4} "
            f"DD=${m['max_drawdown_dollars']:>7,.0f}")


def main():
    print(f"{'VARIANT':<20} | TRAIN (Jan-Mar) | TEST (Apr-Jun)")
    print("-" * 100)
    results = []
    for v in VARIANTS:
        frames = load_frames(SYMBOLS, [v["primary_tf"], v["htf"]], WARMUP, END)
        strat = v["factory"](SYMBOLS)
        frames = strat.prepare(frames)
        tr = run_window(strat, frames, v["session"], v["flat"], *TRAIN)
        te = run_window(strat, frames, v["session"], v["flat"], *TEST)
        results.append((v["name"], tr, te))
        print(f"{v['name']:<20} | {fmt(tr)}")
        print(f"{'':<20} | {'':>33} | {fmt(te)}")
        print("-" * 100)

    print("\nROBUST = positive expectancy on BOTH train and test:")
    for name, tr, te in results:
        if tr.get("n_trades", 0) and te.get("n_trades", 0):
            if tr["expectancy_R"] > 0 and te["expectancy_R"] > 0:
                print(f"  ✓ {name}: train {tr['expectancy_R']:+.3f}R / test {te['expectancy_R']:+.3f}R")
    print("(none listed above = no variant survived out-of-sample)")


if __name__ == "__main__":
    main()
