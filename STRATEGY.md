# Recycler — Strategy & Honest Findings

> Written for a trader who hates fugazi. Every number here came from real OANDA
> data and reproducible code in this repo. Nothing is fabricated to hit a target.

## 1. The targets you set — and the math

You asked for, simultaneously: **≥7.5%/month**, **max drawdown ≤ $1,200 (1.2%)**,
**≥72% win rate**, **~2–3 trades/week**. An independent adversarial audit
(reproduced in `backtests/` notes and the research transcript) shows this set is
**internally contradictory**, not merely hard:

- **7.5%/mo at 1.2% max DD ⇒ Calmar ratio ≈ 75–115.** Elite hedge funds run
  Calmar ≈ 1.5–3. Renaissance Medallion — the best risk-adjusted record ever —
  is in the single digits. The target asks for **30–75× the best fund in history**.
- **72% win rate + ~2.5 trades/wk ⇒ a 4-loss streak is a 44% annual event, a
  5-loss streak 15%.** To keep a worst-case streak under $1,200 you must risk
  **≤0.2% per trade**. Making 7.5%/mo on 0.2% risk needs **72% wins at 4.4:1
  reward:risk simultaneously** — impossible (break-even for 4.4:1 is an 18.5%
  win rate; real 70%-win systems pay *less* than 1:1).
- **Honest frontier with a hard 1.2% DD cap: ≈ 0.1–0.3%/month (1.5–3.5%/yr).**
  To earn 7.5%/mo you must budget **15–40% drawdowns**. There is no third option.

This is not pessimism — it is the return/risk/win-rate frontier. Anyone showing
you a backtest with all four boxes ticked is showing an overfit curve, a
look-ahead bug, or unmodeled costs.

## 2. The strategy that was built — London Momentum-Continuation Pullback

A real, fully-mechanical trend-continuation method (no SMC/ICT):

| Element | Rule |
|---|---|
| Universe | EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCAD, XAUUSD (USD-quote/base; exact sizing) |
| Trend filter | H4: EMA20 > EMA50 **and** ADX ≥ 20 (trade only with a real trend) |
| Entry (long) | M15/H1 pullback tags the EMA20 while holding above EMA50, then a momentum **reclaim** bar with RSI turning up in (40, 68) |
| Stop | Beyond the recent swing (buffered), clamped to [0.8, 2.5]×ATR |
| Target / mgmt | Fixed **2.5R** (deployed preset). Optional scale-out (50% @ 1R + breakeven + 2×ATR trail) available |
| Discipline | **One trade per CET day**, intraday only, **flat by 20:00 UTC** (before rollover — swap-free, sidesteps FTMO weekend/overnight rules) |
| News | Red-folder blackout for either currency of the pair (ForexFactory feed) |

**Deployed config** (`recycler/preset.py`): H1 entry, H4 trend, ADX≥20, fixed
2.5R, one trade/day, session 06:00–16:00 UTC.

## 3. What the data actually said (Jan 1 → Jun 20 2026, real OANDA)

The research was done with **out-of-sample discipline** (train Jan–Mar, test
Apr–Jun) to avoid curve-fitting:

- **M15 entries lose** (expectancy ≈ −0.14R): transaction cost + noise eat the
  edge, and MAE > MFE (we were buying the tops of dead-cat bounces).
- **H1 entries are far better** (lower noise, better cost ratio) — DD roughly
  halved, expectancy moved to break-even/positive. This was chosen on first
  principles, not test-peeking.
- **An ADX×target grid was uniformly negative in TRAIN and uniformly positive in
  TEST.** Parameters barely mattered; the **market regime** did. This is the
  central finding: **the edge is regime-dependent** — momentum bleeds in chop
  (Jan–Mar) and wins in trend (Apr–May). A macro-trend filter only *amplified*
  the regime split (it overfits the trending half).

### Final, locked-preset results (no tuning, just measurement)

| risk/trade | trades | net-win | expectancy | PF | total return | max DD ($) |
|---|---|---|---|---|---|---|
| 0.10% | 113 | 42.5% | +0.069R | 1.13 | +0.77% | **$1,266** |
| 0.15% | 113 | 42.5% | +0.069R | 1.12 | +1.15% | $1,899 |
| 0.20% | 113 | 42.5% | +0.069R | 1.12 | +1.53% | $2,533 |
| 0.30% | 113 | 42.5% | +0.069R | 1.12 | +2.27% | $3,800 |

Monthly: Jan −0.08, Feb −0.24, Mar −0.33, **Apr +0.93, May +0.96**, Jun −0.08
(at 0.15%). The regime signature is unmistakable.

**Monte-Carlo (10k trade-order shuffles):** at 0.10% risk the median max-DD is
$1,180 but the **95th-percentile is $1,884**. A hard "never exceed $1,200" is
therefore not physically guaranteed in live FX — slippage/gaps make any hard DD
ceiling probabilistic, exactly as the audit warned.

### Honest verdict on the edge

Full-sample expectancy **+0.069R ± ~0.12 SE on 113 trades is not statistically
significant** — it is consistent with zero plus a favorable second-half regime.
**This is not a proven, fund-it-now edge.** It is a disciplined, FTMO-compliant
trend-continuation system that is roughly break-even-to-slightly-positive over a
full regime cycle, and whose realistic return at your DD cap is ~0.1–0.2%/month.

## 4. Win rate: the honest two numbers

Net-positive trade rate ≈ **42.5%** for the fixed-2.5R preset (not 72%). A
scale-out variant (book 50% at +1R, breakeven the rest) raises the *net-win
rate* into the ~60s but **lowers expectancy** — booking winners early caps the
runners that pay for the losers. The preset optimizes expectancy/DD, not a
vanity win-rate. Both variants are in the code; pick per your preference.

## 5. Where the real value is, and how to extend

The durable deliverable is the **framework**: a look-ahead-safe backtester with
realistic costs and stop-priority fills, exact FTMO-compliant risk management, a
red-folder news blackout, an autonomous executor (paper + MT5), and full logging.
Any strategy — including **your own proven one** — can be dropped into it via the
`Strategy` interface (`recycler/strategy/base.py`) and validated the same honest
way.

## 6. UPDATE — exhaustive multi-year search (2023→2026)

After the drawdown constraint was relaxed to FTMO's real limits (5% daily / 10%
total) and the target set to "max yield, ~50%+ win rate OK", I ran a far wider,
longer search on real OANDA data (3.5 years, 7 instruments: EURUSD, GBPUSD,
AUDUSD, NZDUSD, USDJPY, USDCAD, XAUUSD).

**Full-period (2023→2026), risk 0.5%/trade, guards off:**

| strategy | trades | win% | expectancy | PF | return | maxDD |
|---|---|---|---|---|---|---|
| momentum H1 | 818 | 36% | −0.099R | 0.82 | −34% | 40% |
| momentum + scale-out | 818 | 42% | −0.080R | 0.82 | −29% | 32% |
| mean-reversion H1 | 785 | 47% | −0.064R | 0.86 | −23% | 34% |
| mean-rev high-win (tight) | 595 | **61%** | −0.092R | 0.75 | −24% | 27% |
| Donchian breakout H4 | 233 | 36% | −0.003R | 0.99 | −0.8% | 9% |
| Donchian breakout H1 | 771 | 34% | −0.049R | 0.88 | −19% | 39% |

**Diversified swing trend PORTFOLIO** (all 7 instruments held concurrently, the
structure trend-following actually needs): also negative at every setting
(expectancy −0.05 to −0.09R, returns −20% to −58%, win 31–34%). Reason: FX
majors+gold are dominated by the USD factor, so they are highly correlated —
there is no real diversification benefit to harvest (effectively ~2 bets, not 7).

**Two proven facts from this search:**
1. **No textbook mechanical edge on FX majors + gold is profitable** over a full
   multi-year cycle. The best is break-even. Apparent "good years" are the
   favorable half of a regime, exactly offset by losing years.
2. **Chasing a high win rate makes it worse:** the 61%-win variant had the most
   *negative* expectancy. The win-rate/payoff law, confirmed on real data.

**Conclusion:** a mechanical bot yielding ~5%/month on FX majors + gold is not
supported by 3.5 years of data, at any win rate. The realistic path to a
yielding bot is to **automate the user's own discretionary edge** (the only
approach in this project that makes money) inside this framework. Indices were
explicitly excluded by the user.

## Next steps (all supported by the code):
1. **Run it in paper mode** for weeks and compare live behavior to the backtest.
2. **Port your existing strategy** into a `Strategy` subclass and out-of-sample
   test it here — far more likely to carry a real edge than a one-night search.
3. **Regime gating**: only enable momentum when a regime detector says "trend"
   (and consider a mean-reversion module for chop) — but validate out-of-sample,
   it is easy to fool yourself.
4. Keep risk at **≤0.15%/trade** while the edge is unproven; treat the $1,200 cap
   as "≈1.2% in ~95% of months," never as a guarantee.
