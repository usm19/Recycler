"""The win-rate vs monthly-yield FRONTIER on the proven gold edge.

Same gold breakout entry, different management — from "let it all run" (low win,
high payoff) to "book quick" (high win, low payoff). Reports win rate, monthly
yield and drawdown at FTMO-safe 0.5% risk, plus per-year robustness (a config
only counts if it is profitable in MOST years).
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
RISK = 0.005
YEARS = {"2023": ("2023-01-01", "2023-12-31"), "2024": ("2024-01-01", "2024-12-31"),
         "2025": ("2025-01-01", "2025-12-31"), "2026H1": ("2026-01-01", "2026-06-20")}

# management styles, low-win/high-payoff -> high-win/low-payoff
STYLES = [
    ("run_all (trail only)", dict(target_R=None, partial_R=None, breakeven_after_R=None)),
    ("trail + BE@1R", dict(target_R=None, partial_R=None, breakeven_after_R=1.0)),
    ("scale 50%@1.5R+BE+trail", dict(target_R=None, partial_R=1.5, partial_frac=0.5, breakeven_after_R=1.5)),
    ("scale 50%@1R+BE+trail", dict(target_R=None, partial_R=1.0, partial_frac=0.5, breakeven_after_R=1.0)),
    ("scale 60%@0.8R+BE+trail", dict(target_R=None, partial_R=0.8, partial_frac=0.6, breakeven_after_R=0.8)),
    ("scale 70%@0.6R+BE+trail", dict(target_R=None, partial_R=0.6, partial_frac=0.7, breakeven_after_R=0.6)),
    ("fixed 1R target", dict(target_R=1.0, partial_R=None, breakeven_after_R=None)),
    ("fixed 0.7R target", dict(target_R=0.7, partial_R=None, breakeven_after_R=None)),
]


def make(mgmt):
    frames = load_frames(SYM, ["H4"], WARMUP, END)
    s = DonchianBreakout(SYM, primary_tf="H4", htf="H4", channel=30, stop_atr=2.0,
                         trail_atr_mult=3.0, trend_ema=100, max_hold_bars=None, **mgmt)
    s.prepare(frames)
    return s, frames


def run(strat, frames, start, end):
    cfg = BacktestConfig(risk_pct=RISK, session_start_utc="00:00", session_end_utc="23:59",
                         force_flat_utc="23:59", use_guards=False, max_trades_per_day=99,
                         entry_start=start if isinstance(start, pd.Timestamp) else pd.Timestamp(start, tz="UTC"),
                         entry_end=end if isinstance(end, pd.Timestamp) else pd.Timestamp(end + "T23:59:00", tz="UTC"))
    return M.compute(Backtester(strat, frames, cfg).run())


def main():
    print(f"GOLD edge — management frontier @ {RISK:.1%} risk (FTMO-safe). "
          f"window ~{MONTHS:.0f} months.\n")
    print(f"{'management style':<26} {'win%':>5} {'expR':>7} {'~mo%':>6} {'maxDD%':>7} "
          f"{'PF':>5} {'yrs+':>5}")
    for name, mgmt in STYLES:
        s, frames = make(mgmt)
        m = run(s, frames, START, STOP)
        if not m.get("n_trades", 0):
            print(f"{name:<26} no trades"); continue
        yrs_pos = 0
        for _, (a, b) in YEARS.items():
            ym = run(s, frames, a, b)
            if ym.get("n_trades", 0) and ym["total_return_pct"] > 0:
                yrs_pos += 1
        mo = m["total_return_pct"] / MONTHS
        print(f"{name:<26} {m['net_win_rate_pct']:>5} {m['expectancy_R']:>+7.3f} "
              f"{mo:>6.2f} {m['max_drawdown_pct']:>7.1f} {m['profit_factor']:>5} {yrs_pos:>4}/4")


if __name__ == "__main__":
    main()
