"""Multi-year robustness test (2023 -> 2026 H1).

Each strategy uses A-PRIORI (textbook) parameters — NOT optimized on this data —
and is run independently per calendar year. A robust edge is positive across
MOST years, not one. This is the honest test of whether a documented edge
survives multiple regimes.
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
RISK = 0.005
YEARS = {
    "2023": ("2023-01-01", "2023-12-31"),
    "2024": ("2024-01-01", "2024-12-31"),
    "2025": ("2025-01-01", "2025-12-31"),
    "2026H1": ("2026-01-01", "2026-06-20"),
}

# (name, factory, tfs, session, flat, swing)
VARIANTS = [
    ("mom_H1", lambda S: MomentumPullback(S, primary_tf="H1", htf="H4", target_R=2.5,
        partial_R=None, breakeven_after_R=None, trail_atr_mult=None, max_hold_bars=8, adx_min=20),
     ["H1", "H4"], ("06:00", "16:00"), "20:00"),
    ("mr_H1", lambda S: MeanReversionRSI2(S, primary_tf="H1", htf="H4", target_R=1.0,
        stop_atr=2.0, trend_ema=100, rsi_buy=10, rsi_sell=90, max_hold_bars=8),
     ["H1", "H4"], ("06:00", "16:00"), "20:00"),
    ("don20_H4_swing", lambda S: DonchianBreakout(S, primary_tf="H4", htf="H4",
        channel=20, stop_atr=2.0, trail_atr_mult=3.0, trend_ema=100, max_hold_bars=None),
     ["H4"], ("00:00", "23:59"), "23:59"),
    ("don55_H4_swing", lambda S: DonchianBreakout(S, primary_tf="H4", htf="H4",
        channel=55, stop_atr=2.0, trail_atr_mult=3.0, trend_ema=100, max_hold_bars=None),
     ["H4"], ("00:00", "23:59"), "23:59"),
    ("don20_H1_swing", lambda S: DonchianBreakout(S, primary_tf="H1", htf="H4",
        channel=40, stop_atr=2.0, trail_atr_mult=3.0, trend_ema=200, max_hold_bars=None),
     ["H1"], ("00:00", "23:59"), "23:59"),
]


def run(strat, frames, session, flat, start, end):
    cfg = BacktestConfig(risk_pct=RISK, session_start_utc=session[0], session_end_utc=session[1],
                         force_flat_utc=flat,
                         entry_start=pd.Timestamp(start, tz="UTC"),
                         entry_end=pd.Timestamp(end + "T23:59:00", tz="UTC"))
    return M.compute(Backtester(strat, frames, cfg).run())


def cell(m):
    if not m.get("n_trades", 0):
        return f"{'·':>22}"
    return (f"n={m['n_trades']:>3} e={m['expectancy_R']:>+5.2f} "
            f"r={m['total_return_pct']:>+6.1f}% DD={m['max_drawdown_pct']:>4.1f}%")


def main():
    end = pd.Timestamp("2026-06-21T00:00:00Z")
    print(f"Risk {RISK:.1%}/trade. e=expectancy R, r=year return, DD=max drawdown %.\n")
    summary = []
    for name, factory, tfs, session, flat in VARIANTS:
        frames = load_frames(SYMBOLS, tfs, WARMUP, end)
        # ensure htf present for strategies that align to H4
        if "H4" not in tfs:
            frames.update(load_frames(SYMBOLS, ["H4"], WARMUP, end))
        strat = factory(SYMBOLS)
        strat.prepare(frames)
        print(f"=== {name} ===")
        yr_results = {}
        for yr, (s, e) in YEARS.items():
            m = run(strat, frames, session, flat, s, e)
            yr_results[yr] = m
            print(f"  {yr:7s} {cell(m)}")
        # overall
        m_all = run(strat, frames, session, flat, "2023-01-01", "2026-06-20")
        print(f"  {'ALL':7s} {cell(m_all)}  PF={m_all.get('profit_factor','-')}")
        summary.append((name, yr_results, m_all))
        print()

    print("=" * 70)
    print("ROBUSTNESS (positive expectancy in how many of 4 years):")
    for name, yr, m_all in summary:
        pos = sum(1 for y in yr.values() if y.get("n_trades", 0) and y["expectancy_R"] > 0)
        tag = "  <-- robust" if pos >= 3 else ""
        print(f"  {name:18s}: {pos}/4 years positive | ALL expR "
              f"{m_all.get('expectancy_R', 0):+.3f} ret {m_all.get('total_return_pct',0):+.1f}%{tag}")


if __name__ == "__main__":
    main()
