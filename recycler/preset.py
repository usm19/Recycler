"""The single source of truth for the deployed strategy configuration.

Both the backtester and the live bot import from here so research and production
can never diverge.

DEPLOYED EDGE (found via exhaustive 3.5yr search — see backtests/GOLD_REPORT.md):
Gold (XAUUSD) trend-following — Donchian breakout, ATR trailing stop, SWING
(multi-day holds). Gold is the ONLY instrument in the FX+gold universe with a
real, year-after-year trend edge (PF ~1.6, positive 2023/24/25/26). FX majors
were all break-even-to-negative and are not traded.

HONEST EXPECTATIONS: ~1%/month (~12-15%/yr) at ~1% risk/trade with ~6-9% max
drawdown — FTMO-compliant. 5%/month is NOT achievable within FTMO's 10% drawdown
limit (it would require ~45% drawdown); the two constraints are mutually
exclusive. See STRATEGY.md.

Requires the FTMO SWING account variant (swap-free + weekend holding allowed),
since trades are held multiple days.
"""
from __future__ import annotations

from recycler.strategy.breakout import DonchianBreakout

# Gold-centric. USDCAD was marginally positive and may be added as a small
# satellite, but gold is the engine.
SYMBOLS = ["XAUUSD"]
PRIMARY_TF = "H4"
HTF = "H4"                      # Donchian uses the primary frame only
SWING = True                    # multi-day holds; no intraday force-flat
SESSION = ("00:00", "23:59")   # gold trades ~23h; no session restriction
FORCE_FLAT_UTC = None           # swing: do not flatten intraday
DEFAULT_RISK = 0.005            # FTMO-safe: backtest DD ~4.3%, Monte-Carlo p95 ~$7k.
# 0.0075 -> ~0.7%/mo but MC p95 DD ~$10.7k (nicks FTMO's $10k); 0.01 -> ~1.1%/mo, riskier.

# Donchian parameters (a robust plateau 10-55 all work; 30 = best expectancy/DD)
CHANNEL = 30
STOP_ATR = 2.0
TRAIL_ATR = 3.0
TREND_EMA = 100

# News blackout window (minutes) around red-folder events for either currency.
NEWS_BEFORE_MIN = 30
NEWS_AFTER_MIN = 120


def make_strategy(symbols=None) -> DonchianBreakout:
    return DonchianBreakout(
        symbols or SYMBOLS, primary_tf=PRIMARY_TF, htf=HTF,
        channel=CHANNEL, stop_atr=STOP_ATR, trail_atr_mult=TRAIL_ATR,
        trend_ema=TREND_EMA, max_hold_bars=None,
    )
