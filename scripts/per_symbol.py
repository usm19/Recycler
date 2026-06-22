"""Per-instrument edge breakdown (2023->2026).

Averaging across 7 instruments hides any single one that genuinely trends. This
runs each strategy on EACH instrument alone so we can see whether gold (XAUUSD)
or specific pairs carry a real edge worth building around.
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
from recycler.strategy.momentum_pullback import MomentumPullback  # noqa: E402

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
WARMUP = "2023-01-01T00:00:00Z"
END = pd.Timestamp("2026-06-21T00:00:00Z")
START = pd.Timestamp("2023-01-01T00:00:00Z")
STOP = pd.Timestamp("2026-06-20T23:59:00Z")


def run_one(strat_factory, sym, tfs, session, flat):
    frames = load_frames([sym], tfs, WARMUP, END)
    if "H4" not in tfs:
        frames.update(load_frames([sym], ["H4"], WARMUP, END))
    strat = strat_factory([sym])
    strat.prepare(frames)
    cfg = BacktestConfig(risk_pct=0.005, session_start_utc=session[0], session_end_utc=session[1],
                         force_flat_utc=flat, use_guards=False, max_trades_per_day=99,
                         entry_start=START, entry_end=STOP)
    return M.compute(Backtester(strat, frames, cfg).run())


STRATS = {
    "donchian_H4_swing": (lambda S: DonchianBreakout(S, primary_tf="H4", htf="H4", channel=20,
                          stop_atr=2.0, trail_atr_mult=3.0, trend_ema=100, max_hold_bars=None),
                          ["H4"], ("00:00", "23:59"), "23:59"),
    "donchian_H1_swing": (lambda S: DonchianBreakout(S, primary_tf="H1", htf="H4", channel=40,
                          stop_atr=2.0, trail_atr_mult=3.0, trend_ema=200, max_hold_bars=None),
                          ["H1"], ("00:00", "23:59"), "23:59"),
    "momentum_H1": (lambda S: MomentumPullback(S, primary_tf="H1", htf="H4", target_R=2.5,
                    partial_R=None, breakeven_after_R=None, trail_atr_mult=None, max_hold_bars=8, adx_min=20),
                    ["H1", "H4"], ("06:00", "16:00"), "20:00"),
}


def main():
    for name, (factory, tfs, session, flat) in STRATS.items():
        print(f"\n=== {name} — per instrument (risk 0.5%, full 2023->2026) ===")
        print(f"{'symbol':<8} {'trades':>7} {'win%':>5} {'expR':>7} {'ret%':>8} {'maxDD%':>7} {'PF':>5}")
        for sym in SYMBOLS:
            m = run_one(factory, sym, tfs, session, flat)
            if not m.get("n_trades", 0):
                print(f"{sym:<8} no trades")
                continue
            print(f"{sym:<8} {m['n_trades']:>7} {m['net_win_rate_pct']:>5} "
                  f"{m['expectancy_R']:>+7.3f} {m['total_return_pct']:>8.1f} "
                  f"{m['max_drawdown_pct']:>7.1f} {m['profit_factor']:>5}")


if __name__ == "__main__":
    main()
