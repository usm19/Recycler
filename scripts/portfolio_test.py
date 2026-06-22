"""Diversified swing trend-following portfolio (FX majors + XAUUSD).

Tests the portfolio-level trend edge: hold many instruments at once, ride with
trailing stops, multi-day holds. Guards OFF for the headline run so a multi-year
backtest is not truncated by the FTMO halt; max DD is reported so FTMO viability
is visible directly. Sweeps Donchian length x risk x concurrency.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recycler.backtest.portfolio_engine import PortfolioBacktester, PortfolioConfig  # noqa
from recycler.backtest import metrics as M  # noqa: E402
from recycler.data.oanda_data import load_frames  # noqa: E402
from recycler.strategy.breakout import DonchianBreakout  # noqa: E402

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
WARMUP = "2023-01-01T00:00:00Z"
END = pd.Timestamp("2026-06-21T00:00:00Z")
START = pd.Timestamp("2023-01-01T00:00:00Z")
STOP = pd.Timestamp("2026-06-20T23:59:00Z")
MONTHS = (STOP - START).days / 30.4375

CHANNELS = [20, 55]
RISKS = [0.005, 0.010]
CONC = [4, 7]


def build(channel):
    frames = load_frames(SYMBOLS, ["H4"], WARMUP, END)
    strat = DonchianBreakout(SYMBOLS, primary_tf="H4", htf="H4", channel=channel,
                             stop_atr=2.0, trail_atr_mult=3.0, trend_ema=100, max_hold_bars=None)
    strat.prepare(frames)
    return strat, frames


def run(strat, frames, risk, conc, guards=False):
    cfg = PortfolioConfig(risk_pct=risk, max_concurrent=conc, max_total_risk_pct=0.10,
                          session_start_utc=None, force_flat_utc=None, use_guards=guards,
                          entry_start=START, entry_end=STOP)
    return M.compute(PortfolioBacktester(strat, frames, cfg).run())


def main():
    print(f"Diversified swing Donchian portfolio | window ~{MONTHS:.1f} months\n")
    print(f"{'chan':>4} {'risk':>6} {'conc':>4} {'trades':>7} {'win%':>5} {'expR':>6} "
          f"{'totRet%':>8} {'~mo%':>6} {'maxDD%':>7} {'PF':>5}")
    best = None
    for ch in CHANNELS:
        strat, frames = build(ch)
        for risk in RISKS:
            for conc in CONC:
                m = run(strat, frames, risk, conc)
                if not m.get("n_trades", 0):
                    continue
                mo = m["total_return_pct"] / MONTHS
                print(f"{ch:>4} {risk:>6.2%} {conc:>4} {m['n_trades']:>7} {m['net_win_rate_pct']:>5} "
                      f"{m['expectancy_R']:>+6.2f} {m['total_return_pct']:>8.1f} {mo:>6.2f} "
                      f"{m['max_drawdown_pct']:>7.1f} {m['profit_factor']:>5}")
                score = m["total_return_pct"] / max(m["max_drawdown_pct"], 1)
                if best is None or score > best[0]:
                    best = (score, ch, risk, conc, m)

    if best:
        _, ch, risk, conc, m = best
        print(f"\nBest risk-adjusted: channel {ch}, risk {risk:.2%}, conc {conc} "
              f"-> {m['total_return_pct']:.1f}% over {MONTHS:.0f}mo, maxDD {m['max_drawdown_pct']:.1f}%")
        print("Per-year:")
        strat, frames = build(ch)
        for yr, (s, e) in {"2023": ("2023-01-01", "2023-12-31"),
                           "2024": ("2024-01-01", "2024-12-31"),
                           "2025": ("2025-01-01", "2025-12-31"),
                           "2026H1": ("2026-01-01", "2026-06-20")}.items():
            cfg = PortfolioConfig(risk_pct=risk, max_concurrent=conc, max_total_risk_pct=0.10,
                                  session_start_utc=None, force_flat_utc=None, use_guards=False,
                                  entry_start=pd.Timestamp(s, tz="UTC"),
                                  entry_end=pd.Timestamp(e + "T23:59:00", tz="UTC"))
            ym = M.compute(PortfolioBacktester(strat, frames, cfg).run())
            if ym.get("n_trades", 0):
                print(f"  {yr}: ret {ym['total_return_pct']:+6.1f}%  maxDD {ym['max_drawdown_pct']:4.1f}%  "
                      f"win {ym['net_win_rate_pct']}%  n={ym['n_trades']}")


if __name__ == "__main__":
    main()
