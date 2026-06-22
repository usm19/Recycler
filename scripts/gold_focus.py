"""Gold-centric trend-following: robustness + max yield within FTMO 10% DD.

XAUUSD is the one instrument with a real trend edge. Here we (1) check it holds
every year (not just the 2023-24 rally), (2) sweep Donchian length, (3) sweep
risk to find the most yield while keeping max drawdown under FTMO's 10%.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recycler.backtest.engine import Backtester, BacktestConfig  # noqa: E402
from recycler.backtest import metrics as M  # noqa: E402
from recycler.data.oanda_data import load_frames  # noqa: E402
from recycler.strategy.breakout import DonchianBreakout  # noqa: E402

SYM = ["XAUUSD"]
WARMUP = "2023-01-01T00:00:00Z"
END = pd.Timestamp("2026-06-21T00:00:00Z")
START = pd.Timestamp("2023-01-01T00:00:00Z")
STOP = pd.Timestamp("2026-06-20T23:59:00Z")
MONTHS = (STOP - START).days / 30.4375
YEARS = {"2023": ("2023-01-01", "2023-12-31"), "2024": ("2024-01-01", "2024-12-31"),
         "2025": ("2025-01-01", "2025-12-31"), "2026H1": ("2026-01-01", "2026-06-20")}


def make(channel, trail=3.0, stop=2.0):
    frames = load_frames(SYM, ["H4"], WARMUP, END)
    s = DonchianBreakout(SYM, primary_tf="H4", htf="H4", channel=channel, stop_atr=stop,
                         trail_atr_mult=trail, trend_ema=100, max_hold_bars=None)
    s.prepare(frames)
    return s, frames


def run(strat, frames, risk, start, end, guards=False):
    cfg = BacktestConfig(risk_pct=risk, session_start_utc="00:00", session_end_utc="23:59",
                         force_flat_utc="23:59", use_guards=guards, max_trades_per_day=99,
                         entry_start=pd.Timestamp(start, tz="UTC") if isinstance(start, str) else start,
                         entry_end=(pd.Timestamp(end + "T23:59:00", tz="UTC") if isinstance(end, str) else end))
    return M.compute(Backtester(strat, frames, cfg).run())


def main():
    print("== 1) Robustness: Donchian-20 H4 gold, per year (risk 1%) ==")
    s, frames = make(20)
    for yr, (a, b) in YEARS.items():
        m = run(s, frames, 0.01, a, b)
        if m.get("n_trades", 0):
            print(f"  {yr}: ret {m['total_return_pct']:+6.1f}%  maxDD {m['max_drawdown_pct']:4.1f}%  "
                  f"win {m['net_win_rate_pct']}%  expR {m['expectancy_R']:+.3f}  n={m['n_trades']}")

    print("\n== 2) Donchian length sweep (full period, risk 1%) ==")
    print(f"{'chan':>4} {'trades':>7} {'win%':>5} {'expR':>7} {'ret%':>7} {'~mo%':>6} {'maxDD%':>7} {'PF':>5}")
    for ch in (10, 20, 30, 40, 55):
        s, frames = make(ch)
        m = run(s, frames, 0.01, START, STOP)
        if m.get("n_trades", 0):
            print(f"{ch:>4} {m['n_trades']:>7} {m['net_win_rate_pct']:>5} {m['expectancy_R']:>+7.3f} "
                  f"{m['total_return_pct']:>7.1f} {m['total_return_pct']/MONTHS:>6.2f} "
                  f"{m['max_drawdown_pct']:>7.1f} {m['profit_factor']:>5}")

    print("\n== 3) Risk sweep on Donchian-20 (full period): yield vs FTMO 10% DD ==")
    s, frames = make(20)
    print(f"{'risk':>6} {'ret%':>7} {'~mo%':>6} {'maxDD%':>7} {'FTMO?':>6}")
    for risk in (0.005, 0.01, 0.015, 0.02, 0.03):
        m = run(s, frames, risk, START, STOP)
        ftmo = "OK" if m["max_drawdown_pct"] < 10 else "FAIL"
        print(f"{risk:>6.2%} {m['total_return_pct']:>7.1f} {m['total_return_pct']/MONTHS:>6.2f} "
              f"{m['max_drawdown_pct']:>7.1f} {ftmo:>6}")


if __name__ == "__main__":
    main()
