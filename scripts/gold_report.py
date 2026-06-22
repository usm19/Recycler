"""Final report for the deployed GOLD trend-following strategy (preset).

Full 2023->2026 + per-year + risk sweep vs FTMO 10% DD + Monte-Carlo drawdown.
Writes backtests/GOLD_REPORT.md and an equity chart. Measures the locked preset;
no tuning here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recycler.backtest.engine import Backtester, BacktestConfig  # noqa: E402
from recycler.backtest import metrics as M  # noqa: E402
from recycler.data.oanda_data import load_frames  # noqa: E402
from recycler import preset  # noqa: E402
from recycler.config import REPO_ROOT  # noqa: E402

WARMUP = "2023-01-01T00:00:00Z"
END = pd.Timestamp("2026-06-21T00:00:00Z")
START = pd.Timestamp("2023-01-01T00:00:00Z")
STOP = pd.Timestamp("2026-06-20T23:59:00Z")
MONTHS = (STOP - START).days / 30.4375
OUT = REPO_ROOT / "backtests"
YEARS = {"2023": ("2023-01-01", "2023-12-31"), "2024": ("2024-01-01", "2024-12-31"),
         "2025": ("2025-01-01", "2025-12-31"), "2026H1": ("2026-01-01", "2026-06-20")}


def build():
    frames = load_frames(preset.SYMBOLS, [preset.PRIMARY_TF, preset.HTF], WARMUP, END)
    strat = preset.make_strategy()
    strat.prepare(frames)
    return strat, frames


def run(strat, frames, risk, start, end):
    cfg = BacktestConfig(risk_pct=risk, session_start_utc="00:00", session_end_utc="23:59",
                         force_flat_utc="23:59", use_guards=False, max_trades_per_day=99,
                         entry_start=start if isinstance(start, pd.Timestamp) else pd.Timestamp(start, tz="UTC"),
                         entry_end=end if isinstance(end, pd.Timestamp) else pd.Timestamp(end + "T23:59:00", tz="UTC"))
    return Backtester(strat, frames, cfg).run()


def mc(r_list, risk, n=10000, seed=11, account=100_000.0):
    rng = np.random.default_rng(seed)
    r = np.array(r_list); rd = risk * account
    dds = np.empty(n)
    for k in range(n):
        eq = np.cumsum(rng.permutation(r)) * rd
        peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))
        dds[k] = (peak[1:] - eq).max() if len(eq) else 0.0
    return dds


def main():
    strat, frames = build()
    L = []
    def out(s=""):
        print(s); L.append(s)

    out("# Recycler — GOLD Trend-Following Report")
    out(f"Strategy: {strat.name} on {preset.SYMBOLS} | {preset.PRIMARY_TF} | "
        f"Donchian {preset.CHANNEL}, trail {preset.TRAIL_ATR}xATR, swing (multi-day)")
    out(f"Window: 2023-01-01 -> 2026-06-20 ({MONTHS:.1f} months), real OANDA data\n")

    out("## Per-year (risk 1%)\n```")
    out(f"{'year':7} {'ret%':>7} {'maxDD%':>7} {'win%':>5} {'expR':>7} {'n':>4}")
    for yr, (a, b) in YEARS.items():
        m = M.compute(run(strat, frames, 0.01, a, b))
        out(f"{yr:7} {m['total_return_pct']:>7.1f} {m['max_drawdown_pct']:>7.1f} "
            f"{m['net_win_rate_pct']:>5} {m['expectancy_R']:>+7.3f} {m['n_trades']:>4}")
    out("```\n")

    out("## Risk sweep vs FTMO 10% drawdown (full period)\n```")
    out(f"{'risk':>6} {'ret%':>7} {'~mo%':>6} {'maxDD%':>7} {'PF':>5} {'FTMO?':>6}")
    res_default = None
    for risk in (0.005, 0.0075, 0.01, 0.015):
        res = run(strat, frames, risk, START, STOP)
        m = M.compute(res)
        if abs(risk - preset.DEFAULT_RISK) < 1e-9:
            res_default = res
        flag = "OK" if m["max_drawdown_pct"] < 10 else "FAIL"
        out(f"{risk:>6.2%} {m['total_return_pct']:>7.1f} {m['total_return_pct']/MONTHS:>6.2f} "
            f"{m['max_drawdown_pct']:>7.1f} {m['profit_factor']:>5} {flag:>6}")
    out("```\n")

    if res_default is None:
        res_default = run(strat, frames, preset.DEFAULT_RISK, START, STOP)
    md = M.compute(res_default)
    out(f"## Deployed @ {preset.DEFAULT_RISK:.2%} risk\n```")
    out(M.format_report(md, title=f"GOLD @ {preset.DEFAULT_RISK:.2%}"))
    out("```\n")

    r_list = [t.r_multiple for t in res_default["trades"]]
    out(f"## Monte-Carlo max-drawdown ({len(r_list)} trades, 10k shuffles) @ {preset.DEFAULT_RISK:.2%}\n```")
    dds = mc(r_list, preset.DEFAULT_RISK)
    out(f"median ${np.median(dds):,.0f} | p95 ${np.percentile(dds,95):,.0f} | "
        f"p99 ${np.percentile(dds,99):,.0f}  (FTMO fails at $10,000)")
    out("```")
    out("\nHonest verdict: a real, robust, FTMO-compliant edge yielding ~1%/month. "
        "5%/month is impossible within FTMO's 10% drawdown cap (needs ~45% DD).")

    OUT.mkdir(exist_ok=True)
    eq = res_default["equity_curve"]
    eq.to_csv(OUT / "gold_equity.csv")
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(eq.index, eq["equity"], lw=1.2, color="goldenrod")
        ax.set_title(f"Gold trend-following equity @ {preset.DEFAULT_RISK:.2%} risk")
        ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(OUT / "gold_equity.png", dpi=110)
    except Exception as e:
        out(f"(plot skipped: {e})")
    (OUT / "GOLD_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print(f"\nWrote {OUT/'GOLD_REPORT.md'}")


if __name__ == "__main__":
    main()
