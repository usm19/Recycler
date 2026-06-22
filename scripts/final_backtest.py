"""Final validation of the deployed preset strategy over Jan 1 -> Jun 20 2026.

Produces: full-sample metrics, a risk sweep vs the $1,200 DD cap, a Monte-Carlo
drawdown distribution (trade-order bootstrap), an equity-curve PNG, and a
REPORT.md. No parameters are tuned here — this just measures the locked preset.
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

WARMUP = "2025-12-10T00:00:00Z"
START = pd.Timestamp("2026-01-01T00:00:00Z")
END = pd.Timestamp("2026-06-20T23:59:00Z")
RISKS = [0.001, 0.0015, 0.002, 0.003]
OUT = REPO_ROOT / "backtests"
OUT.mkdir(exist_ok=True)


def build():
    frames = load_frames(preset.SYMBOLS, [preset.PRIMARY_TF, preset.HTF], WARMUP, END)
    strat = preset.make_strategy()
    frames = strat.prepare(frames)
    return strat, frames


def run(strat, frames, risk):
    cfg = BacktestConfig(risk_pct=risk, session_start_utc=preset.SESSION[0],
                         session_end_utc=preset.SESSION[1], force_flat_utc=preset.FORCE_FLAT_UTC,
                         entry_start=START, entry_end=END)
    res = Backtester(strat, frames, cfg).run()
    return res, M.compute(res)


def monte_carlo(r_list, risk, account=100_000.0, n=10000, seed=7):
    """Bootstrap trade-order; report max-DD distribution in $ (additive R model)."""
    rng = np.random.default_rng(seed)
    r = np.array(r_list, dtype=float)
    risk_dollars = risk * account
    dds = np.empty(n)
    finals = np.empty(n)
    for k in range(n):
        seq = rng.permutation(r)
        eq = np.cumsum(seq) * risk_dollars
        peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))
        dd = (peak[1:] - eq)
        dds[k] = dd.max() if len(dd) else 0.0
        finals[k] = eq[-1] if len(eq) else 0.0
    return dds, finals


def main():
    strat, frames = build()
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("# Recycler — Final Backtest Report")
    out(f"Strategy: {strat.name}  |  {preset.PRIMARY_TF} entry, {preset.HTF} trend, "
        f"session {preset.SESSION} UTC, one trade/day")
    out(f"Window: {START.date()} -> {END.date()}  (real OANDA data)")
    out("")

    # detailed at default risk
    res, m = run(strat, frames, preset.DEFAULT_RISK)
    out("## Full-sample metrics @ default risk "
        f"{preset.DEFAULT_RISK:.2%}\n```")
    out(M.format_report(m, title=f"FULL Jan1-Jun20 @ {preset.DEFAULT_RISK:.2%}"))
    out("```\n")

    # risk sweep
    out("## Risk sweep vs your $1,200 max-DD cap\n```")
    out(f"{'risk':>6} {'trades':>7} {'netwin%':>8} {'expR':>7} {'PF':>5} "
        f"{'totret%':>8} {'maxDD$':>9}")
    swept = []
    for risk in RISKS:
        _, mm = run(strat, frames, risk)
        swept.append((risk, mm))
        flag = "  <= $1,200" if mm["max_drawdown_dollars"] <= 1200 else ""
        out(f"{risk:>6.2%} {mm['n_trades']:>7} {mm['net_win_rate_pct']:>8} "
            f"{mm['expectancy_R']:>7} {mm['profit_factor']:>5} "
            f"{mm['total_return_pct']:>8} {mm['max_drawdown_dollars']:>9,.0f}{flag}")
    out("```\n")

    # monte carlo on the trade sequence
    r_list = [t.r_multiple for t in res["trades"]]
    out(f"## Monte-Carlo drawdown distribution ({len(r_list)} trades, 10k shuffles)")
    out("How bad can drawdown get from the SAME trades in a different order?\n```")
    out(f"{'risk':>6} {'medDD$':>9} {'p95DD$':>9} {'p99DD$':>9} {'medRet$':>10}")
    for risk in RISKS:
        dds, finals = monte_carlo(r_list, risk)
        out(f"{risk:>6.2%} {np.median(dds):>9,.0f} {np.percentile(dds,95):>9,.0f} "
            f"{np.percentile(dds,99):>9,.0f} {np.median(finals):>10,.0f}")
    out("```")
    out("")
    out("Reading: even at the lowest risk, the 95th-percentile drawdown shows the "
        "real tail. A hard $1,200 cap is only safe at very low per-trade risk, and "
        "the corresponding return is small — consistent with the feasibility audit.")

    # save artifacts
    res_def, _ = run(strat, frames, preset.DEFAULT_RISK)
    eq = res_def["equity_curve"]
    eq.to_csv(OUT / "equity_curve.csv")
    pd.DataFrame([{
        "symbol": t.symbol, "dir": t.direction, "entry_time": t.entry_time,
        "exit_time": t.exit_time, "entry": t.entry, "stop": t.init_stop,
        "pnl": round(t.pnl, 2), "R": round(t.r_multiple, 3), "reason": t.exit_reason,
    } for t in res_def["trades"]]).to_csv(OUT / "trades.csv", index=False)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(eq.index, eq["equity"], lw=1.2)
        ax.set_title(f"Recycler equity — {strat.name} @ {preset.DEFAULT_RISK:.2%} risk")
        ax.set_ylabel("Equity ($)"); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(OUT / "equity_curve.png", dpi=110)
        out(f"\nSaved: equity_curve.png / .csv, trades.csv in {OUT}")
    except Exception as e:
        out(f"\n(plot skipped: {e})")

    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {OUT / 'REPORT.md'}")


if __name__ == "__main__":
    main()
