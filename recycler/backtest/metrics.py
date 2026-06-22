"""Honest performance metrics from a Backtester.run() result."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute(result: dict) -> dict:
    trades = result["trades"]
    eq = result["equity_curve"]
    cfg = result["config"]
    acct = cfg.account_size

    if not trades:
        return {"n_trades": 0, "note": "no trades"}

    df = pd.DataFrame([{
        "symbol": t.symbol, "dir": t.direction, "entry_time": t.entry_time,
        "exit_time": t.exit_time, "pnl": t.pnl, "R": t.r_multiple,
        "reason": t.exit_reason, "bars": t.bars_held, "tag": t.tag,
    } for t in trades])

    wins = df[df["pnl"] > 0]
    losses = df[df["pnl"] < 0]
    scratches = df[df["pnl"] == 0]
    full_stops = df[(df["reason"] == "stop") & (df["pnl"] < 0)]

    gross_win = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    n = len(df)

    # monthly returns from the equity curve (month-end equity)
    monthly = eq["equity"].resample("ME").last()
    monthly_ret = monthly.pct_change().dropna()
    # first month vs starting account
    if len(monthly) > 0:
        first = monthly.iloc[0] / acct - 1.0
        monthly_ret = pd.concat([pd.Series([first], index=[monthly.index[0]]), monthly_ret])

    # daily returns for Sharpe
    daily = eq["equity"].resample("D").last().dropna()
    daily_ret = daily.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)
              if daily_ret.std() > 0 else 0.0)

    span_days = (df["exit_time"].max() - df["entry_time"].min()).days or 1
    weeks = span_days / 7.0

    out = {
        "n_trades": n,
        "trades_per_week": round(n / weeks, 2),
        # two honest win-rate definitions
        "net_win_rate_pct": round(100 * len(wins) / n, 1),
        "full_stop_loss_rate_pct": round(100 * len(full_stops) / n, 1),
        "scratch_rate_pct": round(100 * len(scratches) / n, 1),
        "loss_rate_pct": round(100 * len(losses) / n, 1),
        # R stats
        "avg_R": round(df["R"].mean(), 3),
        "avg_win_R": round(wins["R"].mean(), 3) if len(wins) else 0.0,
        "avg_loss_R": round(losses["R"].mean(), 3) if len(losses) else 0.0,
        "expectancy_R": round(df["R"].mean(), 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        # money
        "net_pnl": round(df["pnl"].sum(), 2),
        "total_return_pct": round(100 * df["pnl"].sum() / acct, 2),
        "final_equity": round(result["final_equity"], 2),
        "max_drawdown_dollars": round(result["max_drawdown"], 2),
        "max_drawdown_pct": round(100 * result["max_drawdown"] / acct, 2),
        # monthly
        "avg_monthly_return_pct": round(100 * monthly_ret.mean(), 2) if len(monthly_ret) else 0.0,
        "best_month_pct": round(100 * monthly_ret.max(), 2) if len(monthly_ret) else 0.0,
        "worst_month_pct": round(100 * monthly_ret.min(), 2) if len(monthly_ret) else 0.0,
        "sharpe_annualized": round(float(sharpe), 2),
        "exit_reasons": df["reason"].value_counts().to_dict(),
        "by_symbol": df.groupby("symbol")["R"].agg(["count", "mean", "sum"]).round(3).to_dict("index"),
        "monthly_returns_pct": {str(k.date()): round(100 * v, 2) for k, v in monthly_ret.items()},
        "_trades_df": df,
    }
    return out


def format_report(m: dict, title: str = "Backtest") -> str:
    if m.get("n_trades", 0) == 0:
        return f"{title}: no trades."
    lines = [
        f"=== {title} ===",
        f"Trades: {m['n_trades']}  ({m['trades_per_week']}/week)",
        f"Net-positive trade rate: {m['net_win_rate_pct']}%   "
        f"(full-stop losses: {m['full_stop_loss_rate_pct']}%, scratches: {m['scratch_rate_pct']}%)",
        f"Expectancy: {m['expectancy_R']} R/trade   Profit factor: {m['profit_factor']}",
        f"Avg win: {m['avg_win_R']}R   Avg loss: {m['avg_loss_R']}R",
        f"Total return: {m['total_return_pct']}%   Final equity: ${m['final_equity']:,}",
        f"Avg monthly: {m['avg_monthly_return_pct']}%  "
        f"(best {m['best_month_pct']}%, worst {m['worst_month_pct']}%)",
        f"MAX DRAWDOWN: ${m['max_drawdown_dollars']:,}  ({m['max_drawdown_pct']}%)",
        f"Sharpe (ann.): {m['sharpe_annualized']}",
        f"Exit reasons: {m['exit_reasons']}",
        f"Monthly returns: {m['monthly_returns_pct']}",
    ]
    return "\n".join(lines)
