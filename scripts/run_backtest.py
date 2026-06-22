"""Run the backtest over Jan 1 -> Jun 20 2026 and print honest metrics.

Sweeps several per-trade risk levels so the return-vs-drawdown frontier is
visible on real data (the user's hard constraint is max DD <= $1,200).

Run:  .venv\\Scripts\\python.exe scripts\\run_backtest.py
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
WARMUP_START = "2025-12-10T00:00:00Z"
TEST_START = pd.Timestamp("2026-01-01T00:00:00Z")
TEST_END = pd.Timestamp("2026-06-21T00:00:00Z")
RISK_LEVELS = [0.002, 0.003, 0.005, 0.010]


def build_frames():
    frames = load_frames(SYMBOLS, ["M15", "H4"], WARMUP_START, TEST_END)
    strat = MomentumPullback(SYMBOLS)
    frames = strat.prepare(frames)
    # trim primary frames to the test window AFTER indicators are computed on full history
    for sym in SYMBOLS:
        k = f"{sym}@M15"
        df = frames[k]
        frames[k] = df.loc[df.index >= TEST_START]
    return frames, strat


def main():
    frames, strat = build_frames()
    bars = {s: len(frames[f"{s}@M15"]) for s in SYMBOLS}
    print("M15 bars in test window:", bars)

    print("\n" + "=" * 64)
    print("RISK SWEEP — same strategy, different per-trade risk")
    print("=" * 64)
    summary = []
    for risk in RISK_LEVELS:
        cfg = BacktestConfig(risk_pct=risk)
        # rebuild strategy each run is unnecessary; frames already prepared
        bt = Backtester(strat, frames, cfg)
        res = bt.run()
        m = M.compute(res)
        if m.get("n_trades", 0) == 0:
            print(f"\nrisk {risk:.1%}: NO TRADES")
            continue
        print("\n" + M.format_report(m, title=f"risk {risk:.2%}"))
        summary.append((risk, m))

    print("\n" + "=" * 64)
    print("FRONTIER (your hard cap: max DD <= $1,200)")
    print("=" * 64)
    print(f"{'risk':>6} {'trades':>7} {'net_win%':>9} {'exp_R':>7} "
          f"{'PF':>5} {'tot_ret%':>9} {'avg_mo%':>8} {'maxDD$':>10}")
    for risk, m in summary:
        flag = "  <-- within $1,200" if m["max_drawdown_dollars"] <= 1200 else ""
        print(f"{risk:>6.2%} {m['n_trades']:>7} {m['net_win_rate_pct']:>9} "
              f"{m['expectancy_R']:>7} {m['profit_factor']:>5} "
              f"{m['total_return_pct']:>9} {m['avg_monthly_return_pct']:>8} "
              f"{m['max_drawdown_dollars']:>10,.0f}{flag}")


if __name__ == "__main__":
    main()
