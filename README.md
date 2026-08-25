# Calculator — The5ers High Stakes lot sizer

A zero-backend PWA that turns *entry / stop / target* into the exact lot size that
fits your risk **and** always leaves breathing room before The5ers High Stakes
Classic breach floors.

**Symbols:** XAUUSD (Gold) · GBPJPY · EURJPY · GBPUSD · USDJPY · USDCAD · AUDUSD
**Stack:** plain HTML/CSS/JS, no build step, service-worker cached → instant loads, works offline.

## How the size is computed

```
riskable   = min( yourRisk% × equity,
                  equity − dailyFloor − buffer,
                  equity − maxLossFloor − buffer )
perLotLoss = stopDistance × contractSize × quote→account rate
             + spread/slippage pad + commission
lots       = round_DOWN( riskable / perLotLoss , 0.01 )
```

- `dailyFloor` = 95% of the day-start value — The5ers' daily rule is 5% of the
  **higher of balance or equity at 00:00 server time**, re-based every day, tested
  against equity intraday, and a hard breach on High Stakes. The app takes this
  value straight from your dashboard and never lets the working baseline drop
  below current equity, so a stale entry can only tighten the floor, never
  loosen it.
- `maxLossFloor` = 90% of initial balance — static, equity-tested, never trails.
- `buffer` (default 1% of account) is *always* kept between a full stop-out and
  either floor — the breathing space.
- Lots are additionally capped so required margin stays under 90% of equity —
  gold runs at **1:25 leverage** (metals cut from 1:33 in March 2026), so margin
  genuinely binds on tight-stop gold trades; FX is 1:100.
- Currency conversion walks a small graph: the **trade's own price** is an edge
  (exact — risk converts at the stop, profit at the target), plus one edge per
  reference rate (USD/JPY, GBP/USD, EUR/USD, USD/CAD, AUD/USD). Fewest hops
  wins, so a pair that prices its own cross never needs external data — GBPUSD
  on a GBP account, USDCAD's CAD leg, USDJPY's JPY leg. Reference rates are
  fetched free (Frankfurter/ECB → open.er-api.com fallback), cached, and
  manually overridable in settings.

All The5ers rule numbers live in [`js/rules.js`](js/rules.js) — one file to edit
if the firm ever changes its terms.

## Trade journal (tracked account)

Tap **Take this trade** after sizing and the trade is logged against a simulated
challenge account that starts at your account size. Resolving trades (target
hit / stopped out / custom close) moves the balance: stop-outs charge the full
padded risk the app sized with, wins convert at the target price net of
commission. The journal then drives the guardrails automatically —

- equity and the day-start baseline sync from realized P&L, re-basing at 00:00
  server time (GMT+2/+3 with EU DST handled),
- risk committed to **open** trades is subtracted from the next trade's
  allowance so stacked positions can't jointly breach,
- the history is scanned for daily-loss and max-loss breaches (intraday running
  P&L, exactly as The5ers would judge it), and Step-1 progress plus the
  3-profitable-days requirement are tracked.

Settings → Tracking switches between Journal (auto) and Manual mode.

## Develop

```
python3 -m http.server 8123     # serve
node --test tests/*.test.mjs    # unit tests for the sizing engine
```

## Deploy

Pushing to `main` (or a `claude/**` branch) runs `.github/workflows/deploy.yml`:
tests → GitHub Pages. The site is 100% static, so there is never a cold start.

## Rule sources (retrieved 2026-07-28)

| Rule | Value | Source |
|---|---|---|
| Daily loss | 5% of max(day-start balance, day-start equity), 00:00 server (GMT+2/+3), equity-tested, hard breach | [help: max & daily loss](https://help.the5ers.com/what-is-the-maximum-loss-and-the-maximum-daily-loss-in-the-high-stakes-program/), [help: drawdown rule](https://help.the5ers.com/what-is-the-drawdown-rule-for-high-stakes/) |
| Max loss | 10% of initial balance, static (absolute), equity-tested | same articles |
| Targets (Classic) | Step 1: 8% · Step 2: 5% · ≥3 profitable days (closed P&L ≥0.5% of initial) | [FAQ: general rules](https://the5ers.com/faqs/what-are-the-general-rules-for-the-high-stakes-program/), [help: profitable day](https://help.the5ers.com/how-do-you-define-a-profitable-day-in-the-high-stakes-program/) |
| Leverage | FX 1:100 · metals/indices 1:25 (all sizes, per official X post 25 Mar 2026) | [@the5erstrading](https://x.com/the5erstrading/status/2036876354411446514) |
| Commission | FX $4/lot round trip; gold conflicted ($4 flat vs ~0.0008% notional) → app defaults to $4, editable | [asset specifications](https://the5ers.com/asset-specifications/) |
| Stop loss | Suggested, not required; if used must be a visible order (no stealth SL) | [help: risk management](https://help.the5ers.com/is-there-anything-else-i-should-know-about-risk-management/) |
| Lot/exposure caps | None (margin-bound only) | [program comparison](https://the5ers.com/challenge-programs-bootcamp-high-stakes-hyper-growth-explained/) |
| News | No open/close ±2 min around high-impact news; holding through OK | program page |
| Misc | No consistency rule · weekend/overnight holding OK · 30-day inactivity expiry · no HFT/tick-scalping, cross-account hedging, third-party copy trading | prohibited-practices FAQ, help center |

*Not affiliated with The5ers. Rules verified via multi-source research on the date
above; always confirm against your dashboard and the live MT5 symbol specification
(The5ers itself says the platform is authoritative over its web pages).*
