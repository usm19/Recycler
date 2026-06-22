"""The single source of truth for the deployed strategy configuration.

Both the backtester and the live bot import from here so research and production
can never diverge. Chosen by out-of-sample research (see backtests/REPORT.md):
H1 momentum-continuation pullback, ADX>=20, fixed 2.5R, intraday, one trade/day.

HONEST NOTE: this is a marginal, regime-dependent edge (full-sample expectancy
~+0.07R, not statistically significant). It is NOT a 72%-win / 7.5%-per-month
system — no such system exists at a 1.2% drawdown cap (see feasibility audit).
Default risk is set low to respect the $1,200 drawdown preference.
"""
from __future__ import annotations

from recycler.strategy.momentum_pullback import MomentumPullback

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
PRIMARY_TF = "H1"
HTF = "H4"
SESSION = ("06:00", "16:00")   # UTC entry window
FORCE_FLAT_UTC = "20:00"       # flat before 21:00 rollover (swap-free, no overnight)
DEFAULT_RISK = 0.0015          # ~0.15%/trade; see risk sweep in the report

# News blackout window (minutes) around red-folder events for either currency.
NEWS_BEFORE_MIN = 30
NEWS_AFTER_MIN = 120


def make_strategy(symbols=None) -> MomentumPullback:
    return MomentumPullback(
        symbols or SYMBOLS, primary_tf=PRIMARY_TF, htf=HTF,
        adx_min=20.0, target_R=2.5,
        partial_R=None, breakeven_after_R=None, trail_atr_mult=None,
        max_hold_bars=8, macro_filter=False,
    )
