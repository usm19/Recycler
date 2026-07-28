# Nebula — The5ers High Stakes lot sizer

A zero-backend PWA that turns *entry / stop / target* into the exact lot size that
fits your risk **and** always leaves breathing room before The5ers High Stakes
Classic breach floors.

**Symbols:** GBPJPY · XAUUSD (Gold) · USDJPY
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
- JPY pairs convert via USD/JPY, gold is native USD. When you trade GBPJPY or
  USDJPY the **entry price itself** is used as the conversion rate — exact, no
  external data needed. Reference rates for the rest are fetched free
  (Frankfurter/ECB → open.er-api.com fallback), cached, and manually overridable.

All The5ers rule numbers live in [`js/rules.js`](js/rules.js) — one file to edit
if the firm ever changes its terms.

## Develop

```
python3 -m http.server 8123     # serve
node --test tests/              # unit tests for the sizing engine
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
