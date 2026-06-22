# Recycler — Final Backtest Report
Strategy: london_momentum_pullback  |  H1 entry, H4 trend, session ('06:00', '16:00') UTC, one trade/day
Window: 2026-01-01 -> 2026-06-20  (real OANDA data)

## Full-sample metrics @ default risk 0.15%
```
=== FULL Jan1-Jun20 @ 0.15% ===
Trades: 113  (4.71/week)
Net-positive trade rate: 42.5%   (full-stop losses: 49.6%, scratches: 0.0%)
Expectancy: 0.069 R/trade   Profit factor: 1.12
Avg win: 1.446R   Avg loss: -0.948R
Total return: 1.15%   Final equity: $101,150.84
Avg monthly: 0.16%  (best 0.96%, worst -0.33%)
MAX DRAWDOWN: $1,899.41  (1.9%)
Sharpe (ann.): 0.67
Exit reasons: {'stop': 56, 'time': 31, 'target': 20, 'force_flat': 6}
Monthly returns: {'2025-12-31': 0.0, '2026-01-31': -0.08, '2026-02-28': -0.24, '2026-03-31': -0.33, '2026-04-30': 0.93, '2026-05-31': 0.96, '2026-06-30': -0.08}
```

## Risk sweep vs your $1,200 max-DD cap
```
  risk  trades  netwin%    expR    PF  totret%    maxDD$
 0.10%     113     42.5   0.069  1.13     0.77     1,266
 0.15%     113     42.5   0.069  1.12     1.15     1,899
 0.20%     113     42.5   0.069  1.12     1.53     2,533
 0.30%     113     42.5   0.069  1.12     2.27     3,800
```

## Monte-Carlo drawdown distribution (113 trades, 10k shuffles)
How bad can drawdown get from the SAME trades in a different order?
```
  risk    medDD$    p95DD$    p99DD$    medRet$
 0.10%     1,180     1,884     2,236        778
 0.15%     1,770     2,826     3,355      1,167
 0.20%     2,360     3,768     4,473      1,557
 0.30%     3,541     5,652     6,709      2,335
```

Reading: even at the lowest risk, the 95th-percentile drawdown shows the real tail. A hard $1,200 cap is only safe at very low per-trade risk, and the corresponding return is small — consistent with the feasibility audit.

Saved: equity_curve.png / .csv, trades.csv in C:\Users\shahi\Desktop\Recycler\backtests