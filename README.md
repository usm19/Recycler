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

- `dailyFloor` = day-start value − daily-loss allowance (The5ers daily rule)
- `maxLossFloor` = initial balance − max-loss allowance (static)
- `buffer` (default 1% of account) is *always* kept between a full stop-out and
  either floor — the breathing space.
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

*Not affiliated with The5ers. Always confirm limits on your dashboard.*
