# Recycler

A disciplined, FTMO-compliant, autonomous FX bot — **real strategy, honest
numbers, no SMC/ICT, no fabricated backtests.**

👉 Read **[STRATEGY.md](STRATEGY.md)** first. It contains the feasibility math,
the strategy, and the *honest* backtest results (including why your exact
72%/7.5%/1.2%-DD targets are mathematically impossible as a set).

## TL;DR
- Strategy: **H1 momentum-continuation pullback** (H4 trend filter, ADX≥20,
  fixed 2.5R), one trade/day, intraday, red-folder news blackout.
- Backtest Jan 1–Jun 20 2026 (real OANDA data): **+0.069R/trade, PF 1.12,
  +1.15% at 0.15% risk, max DD $1,899** — marginal and **regime-dependent**, not
  a money-printer. See `backtests/REPORT.md`.
- Runs **paper** today (OANDA only). **Live MT5/FTMO** needs a one-time terminal
  setup (below).

## Setup
```powershell
# deps already installed in .venv; if recreating:
.venv\Scripts\python.exe -m pip install pandas numpy requests oandapyV20 MetaTrader5 holidays pytz matplotlib python-dotenv

# secrets live in .env (gitignored). See .env.example for the keys.
```

## Run
```powershell
$env:PYTHONUTF8='1'
# 1) verify all integrations
.venv\Scripts\python.exe scripts\check_connections.py
# 2) download history (cached under data/cache)
.venv\Scripts\python.exe scripts\fetch_data.py
# 3) final backtest + Monte-Carlo + equity chart -> backtests/
.venv\Scripts\python.exe scripts\final_backtest.py
# research tooling
.venv\Scripts\python.exe scripts\research.py      # out-of-sample variant comparison
.venv\Scripts\python.exe scripts\diagnose.py mr_rsi2   # MFE/MAE entry diagnostic
.venv\Scripts\python.exe scripts\grid_h1.py       # parameter robustness grid

# 4) run the bot
.venv\Scripts\python.exe -m recycler.live.bot paper          # paper (no MT5 needed)
.venv\Scripts\python.exe -m recycler.live.bot paper --once   # single iteration
.venv\Scripts\python.exe -m recycler.live.bot live           # live MT5 (after setup)
```

## ⚠️ MT5 / FTMO one-time setup (required for LIVE)
The connection check currently fails with IPC timeout `-10005` because the FTMO
server isn't registered in the terminal yet. Do this once:
1. Open `C:\Program Files\MetaTrader 5\terminal64.exe`.
2. File → Login to Trade Account → enter the FTMO demo login/password/server
   (so `servers.dat` learns the server). Note the exact server name.
3. Tools → Options → Expert Advisors → **enable "Allow algorithmic trading"**.
4. Put the exact server name in `.env` as `MT5_SERVER`, then re-run
   `scripts\check_connections.py` — it will confirm login and tell you which
   password is the master (trading) one and the real symbol suffix.

## 🔐 Security — rotate these
You shared live secrets in chat. After this project, rotate: the **Supabase
service key**, **OANDA token**, **Telegram bot token**, and the **FTMO password**.
`.env` is gitignored; never commit it.

## Architecture
```
recycler/
  config.py            settings + .env loader
  instruments.py       symbol specs, sizing (USD value-per-price, lot sizing)
  indicators.py        EMA/RSI/ATR/ADX/Bollinger/Donchian/VWAP (vectorized)
  util.py              timeframe math, look-ahead-safe HTF alignment, sessions
  news.py              ForexFactory red-folder blackout (live + CSV)
  notify.py            Telegram alerts
  storage.py           Supabase logging (+ schema bootstrap)
  broker_mt5.py        MT5 execution (login, symbol resolve, orders, partial close)
  preset.py            the single deployed-strategy source of truth
  strategy/
    base.py            Strategy + Signal contract (shared by backtest & live)
    momentum_pullback.py
    mean_reversion.py  (RSI2 — researched, not deployed)
  backtest/
    engine.py          event-driven, account-level, realistic costs, FTMO guards
    metrics.py         honest metrics (two win-rate definitions, etc.)
  live/
    risk.py            RiskGuard — all discipline rules
    bot.py             autonomous loop (paper + MT5 executors)
scripts/               check_connections, fetch_data, final_backtest, research,
                       diagnose, grid_h1, test_macro
backtests/             REPORT.md, equity_curve.(csv|png), trades.csv
```

## What's proven vs. not
- ✅ OANDA data, Telegram, Supabase, news feed, backtester, paper bot — all run.
- ✅ Backtest results are real and reproducible (no curve-fitting).
- ⚠️ MT5 live execution: code complete, **needs the terminal setup above**, then
  paper-test before any real capital.
- ⚠️ The strategy edge is marginal/regime-dependent — paper-trade and consider
  porting your own proven strategy into the framework (see STRATEGY.md §5).
