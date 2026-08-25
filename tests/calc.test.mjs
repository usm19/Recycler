import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computePosition, computeGuardrails, conversionRate, floorToStep } from '../js/calc.js';
import { SYMBOLS } from '../js/rules.js';

const closeTo = (a, b, tol = 1e-6) =>
  assert.ok(Math.abs(a - b) <= tol, `expected ${a} ≈ ${b} (±${tol})`);

const freshGBP = { initial: 10000, currency: 'GBP', equity: 10000, dayStart: 10000 };
const freshUSD = { initial: 10000, currency: 'USD', equity: 10000, dayStart: 10000 };

test('floorToStep rounds down to lot step without float artifacts', () => {
  assert.equal(floorToStep(1.0939, 0.01), 1.09);
  assert.equal(floorToStep(1.1, 0.01), 1.1);
  assert.equal(floorToStep(0.999999999999, 0.01), 1);   // within EPS of the boundary → snaps up
  assert.equal(floorToStep(0.9999, 0.01), 0.99);         // genuinely below → floors down
  assert.equal(floorToStep(0.0099, 0.01), 0);
  assert.equal(floorToStep(2.999999999, 0.01), 2.99);
});

test('conversionRate uses trade entry as the exact cross where possible', () => {
  const r = conversionRate('JPY', 'GBP', { symbol: 'GBPJPY', entry: 195.5, rates: {} });
  closeTo(r.rate, 1 / 195.5);
  assert.equal(r.source, 'entry');

  const r2 = conversionRate('JPY', 'USD', { symbol: 'USDJPY', entry: 148.5, rates: {} });
  closeTo(r2.rate, 1 / 148.5);
  assert.equal(r2.source, 'entry');

  const r3 = conversionRate('JPY', 'GBP', { symbol: 'USDJPY', entry: 148.5, rates: { GBPUSD: 1.27 } });
  closeTo(r3.rate, 1 / (1.27 * 148.5));

  const r4 = conversionRate('USD', 'GBP', { symbol: 'XAUUSD', entry: 3350, rates: {} });
  assert.equal(r4.rate, null);
  assert.equal(r4.missing, 'GBPUSD');
});

test('guardrails: fresh account, 3% requested → 300 allowed, uncapped', () => {
  const g = computeGuardrails({ initial: 10000, equity: 10000, dayStart: 10000, riskPct: 0.03, bufferPct: 0.01 });
  closeTo(g.dailyFloor, 9500);
  closeTo(g.totalFloor, 9000);
  closeTo(g.requestedRiskCash, 300);
  closeTo(g.allowedRiskCash, 300);
  assert.equal(g.capReason, null);
});

test('guardrails: after −300 today, daily headroom caps the trade', () => {
  const g = computeGuardrails({ initial: 10000, equity: 9700, dayStart: 10000, riskPct: 0.03, bufferPct: 0.01 });
  closeTo(g.baseline, 10000);
  closeTo(g.dailyFloor, 9500);
  closeTo(g.headroomDaily, 100);           // 9700 − 9500 − 100 buffer
  closeTo(g.allowedRiskCash, 100);
  assert.equal(g.capReason, 'daily');
});

test('guardrails: overnight floating loss — baseline is the day-start value, not equity', () => {
  // balance £10,000 / equity £9,800 at midnight → dashboard baseline 10,000.
  // The floor must hang off 10,000 even though equity opened at 9,800.
  const g = computeGuardrails({ initial: 10000, equity: 9800, dayStart: 10000, riskPct: 0.04, bufferPct: 0.01 });
  closeTo(g.dailyFloor, 9500);
  closeTo(g.headroomDaily, 200);           // 9800 − 9500 − 100
  closeTo(g.allowedRiskCash, 200);
  assert.equal(g.capReason, 'daily');
});

test('guardrails: profitable day — working baseline rises to equity (conservative)', () => {
  const g = computeGuardrails({ initial: 10000, equity: 10400, dayStart: 10000, riskPct: 0.03, bufferPct: 0.01 });
  closeTo(g.baseline, 10400);              // never below current equity
  closeTo(g.dailyFloor, 9880);             // 0.95 × 10400
  closeTo(g.headroomDaily, 10400 - 9880 - 100);
});

test('guardrails: deep drawdown caps by total floor', () => {
  const g = computeGuardrails({ initial: 10000, equity: 9200, dayStart: 9200, riskPct: 0.04, bufferPct: 0.01 });
  closeTo(g.headroomTotal, 100);           // 9200 − 9000 − 100
  // daily re-bases off day-start: allowance = 5% × 9200 = 460 → floor 8740
  closeTo(g.dailyFloor, 8740);
  closeTo(g.headroomDaily, 9200 - 8740 - 100);
  closeTo(g.allowedRiskCash, 100);
  assert.equal(g.capReason, 'total');
});

test('guardrails: breach flags fire', () => {
  const g = computeGuardrails({ initial: 10000, equity: 8990, dayStart: 8990, riskPct: 0.02, bufferPct: 0.01 });
  assert.equal(g.breachedTotal, true);
  closeTo(g.allowedRiskCash, 0);
});

test('GBPJPY long on fresh £10k, 3%: full worked example', () => {
  const r = computePosition({
    symbol: 'GBPJPY', entry: 195.5, sl: 195.0, tp: 196.5,
    riskPct: 0.03, account: freshGBP, rates: { GBPUSD: 1.27 },
  });
  assert.equal(r.ok, true);
  assert.equal(r.direction, 'long');
  closeTo(r.stopPips, 50);
  // losses realize at the STOP price → convert at 195.0, not entry
  const conv = 1 / 195.0;
  const perLotRisk = 0.5 * 100000 * conv;
  const perLotPad = 0.03 * 100000 * conv;
  const perLotComm = 4 / 1.27;
  closeTo(r.perLotRisk, perLotRisk, 1e-9);
  closeTo(r.perLotPad, perLotPad, 1e-9);
  closeTo(r.perLotCommission, perLotComm, 1e-9);
  const total = perLotRisk + perLotPad + perLotComm;
  closeTo(r.perLotRiskTotal, total, 1e-9);
  assert.equal(r.lots, floorToStep(300 / total, 0.01));
  assert.equal(r.lots, 1.09);
  assert.ok(r.actualRiskCash <= 300 + 1e-9, 'never exceeds allowed risk');
  closeTo(r.rr, 2);
  assert.equal(r.tpValid, true);
  // profits realize at the TARGET price
  closeTo(r.profitCash, 1.0 * 100000 / 196.5 * 1.09 - (4 / 1.27) * 1.09, 1e-6);
  // margin: 100,000 GBP notional per lot on a GBP account @1:100
  closeTo(r.marginRequired, 100000 * 1.09 / 100, 1e-6);
});

test('GBPJPY works on a GBP account with NO external rates (entry is the cross)', () => {
  const r = computePosition({
    symbol: 'GBPJPY', entry: 195.5, sl: 195.0,
    riskPct: 0.03, account: freshGBP, rates: {},
  });
  assert.equal(r.ok, true);
  assert.ok(r.lots > 0);
  // commission can't be converted without GBPUSD → info warning, commission = 0
  assert.ok(r.warnings.some(w => w.code === 'commission-estimated'));
  closeTo(r.perLotCommission, 4, 1e-9);   // charged at par, the conservative side
});

test('XAUUSD short on fresh $10k, 2%', () => {
  const r = computePosition({
    symbol: 'XAUUSD', entry: 3350, sl: 3360, tp: 3330,
    riskPct: 0.02, account: freshUSD, rates: {},
  });
  assert.equal(r.ok, true);
  assert.equal(r.direction, 'short');
  const total = 10 * 100 + 0.5 * 100 + 4;      // 1054 USD per lot
  closeTo(r.perLotRiskTotal, total, 1e-9);
  assert.equal(r.lots, 0.18);
  closeTo(r.actualRiskCash, 0.18 * total, 1e-9);
  closeTo(r.rr, 2);
  // gold margin at 1:25
  closeTo(r.marginRequired, 3350 * 100 * 0.18 / 25, 1e-6);
  assert.equal(r.marginCapped, false);
});

test('XAUUSD tight stop: 1:25 leverage caps the lots by margin', () => {
  const r = computePosition({
    symbol: 'XAUUSD', entry: 3350, sl: 3347,       // $3 stop
    riskPct: 0.03, account: freshUSD, rates: {},
  });
  assert.equal(r.ok, true);
  // risk alone would allow floor(300 / (3*100 + 50 + 4)) = 0.84 lots,
  // but margin/lot = 3350*100/25 = 13,400 → 90% of equity allows only 0.67
  assert.equal(r.marginCapped, true);
  assert.equal(r.lots, floorToStep(10000 * 0.9 / 13400, 0.01));
  assert.equal(r.lots, 0.67);
  assert.ok(r.warnings.some(w => w.code === 'margin-capped'));
  assert.ok(r.marginRequired <= 10000 * 0.9 + 1e-9);
});

test('USDJPY short on £10k: JPY converted via GBPUSD × entry', () => {
  const r = computePosition({
    symbol: 'USDJPY', entry: 148.5, sl: 149.0, tp: 147.5,
    riskPct: 0.03, account: freshGBP, rates: { GBPUSD: 1.27 },
  });
  assert.equal(r.ok, true);
  assert.equal(r.direction, 'short');
  const conv = 1 / (1.27 * 149.0);   // JPY→GBP at the stop price
  closeTo(r.perLotRisk, 0.5 * 100000 * conv, 1e-9);
  closeTo(r.rr, 2);
  assert.equal(r.tpValid, true);
  // margin: $100k notional → GBP @1:100
  closeTo(r.marginRequired, (100000 / 1.27) * r.lots / 100, 1e-6);
});

test('missing rate surfaces as a typed error', () => {
  const r = computePosition({
    symbol: 'XAUUSD', entry: 3350, sl: 3340,
    riskPct: 0.02, account: freshGBP, rates: {},
  });
  assert.equal(r.ok, false);
  assert.equal(r.error, 'missing-rate');
  assert.equal(r.missingRate, 'GBPUSD');
});

test('stop too wide for min lot → 0 lots + serious warning', () => {
  const r = computePosition({
    symbol: 'GBPJPY', entry: 195.5, sl: 185.5,   // 1000-pip stop
    riskPct: 0.02, account: { ...freshGBP, equity: 400, initial: 400, dayStart: 400 }, rates: { GBPUSD: 1.27 },
  });
  assert.equal(r.ok, true);
  assert.equal(r.lots, 0);
  const w = r.warnings.find(w => w.code === 'stop-too-wide');
  assert.ok(w);
  assert.ok(w.minLotRiskCash > 0);
});

test('headroom inside the buffer → 0 lots with no-headroom (not stop-too-wide)', () => {
  const r = computePosition({
    symbol: 'USDJPY', entry: 148.5, sl: 148.0,
    riskPct: 0.02,
    account: { initial: 10000, currency: 'USD', equity: 9050, dayStart: 9050 },  // $50 above max-loss floor, buffer $100
    rates: {},
  });
  assert.equal(r.ok, true);
  assert.equal(r.lots, 0);
  assert.ok(r.warnings.some(w => w.code === 'no-headroom'));
  assert.ok(!r.warnings.some(w => w.code === 'stop-too-wide'));
});

test('TP on the wrong side warns but still sizes the trade', () => {
  const r = computePosition({
    symbol: 'USDJPY', entry: 148.5, sl: 148.0, tp: 147.0,  // long with TP below entry
    riskPct: 0.02, account: freshUSD, rates: {},
  });
  assert.equal(r.ok, true);
  assert.equal(r.direction, 'long');
  assert.equal(r.tpValid, false);
  assert.ok(r.warnings.some(w => w.code === 'tp-wrong-side'));
  assert.ok(r.lots > 0);
});

test('missing/null account returns typed error instead of throwing', () => {
  const r1 = computePosition({ symbol: 'GBPJPY', entry: 192, sl: 191, riskPct: 0.02, rates: { USDJPY: 155, GBPUSD: 1.27 } });
  assert.equal(r1.ok, false);
  assert.equal(r1.error, 'need-account');
  const r2 = computePosition({ symbol: 'GBPJPY', entry: 192, sl: 191, riskPct: 0.02, account: null, rates: {} });
  assert.equal(r2.error, 'need-account');
});

test('non-finite inputs are rejected, never NaN/Infinity outputs', () => {
  const inf = computePosition({ symbol: 'GBPJPY', entry: Infinity, sl: 191, riskPct: 0.02, account: freshGBP, rates: {} });
  assert.equal(inf.ok, false);
  assert.equal(inf.error, 'need-entry');

  const nan = computePosition({ symbol: 'USDJPY', entry: 148.5, sl: NaN, riskPct: 0.02, account: freshUSD, rates: {} });
  assert.equal(nan.error, 'need-sl');

  // Infinity as an external rate must be ignored, never treated as rate 0.
  // The graph still routes JPY->GBP (trade entry) ->USD (GBPUSD), so this is
  // a valid sizing — the point is that no NaN/Infinity reaches the output.
  const r = computePosition({
    symbol: 'GBPJPY', entry: 192, sl: 191, riskPct: 0.02,
    account: freshUSD, rates: { USDJPY: Infinity, GBPUSD: 1.27 },
  });
  assert.equal(r.ok, true);
  closeTo(r.perLotRisk, 1 * 100000 / 191 * 1.27, 1e-9);
  for (const v of [r.lots, r.actualRiskCash, r.postLossEquity, r.marginRequired]) {
    assert.ok(Number.isFinite(v), `expected finite, got ${v}`);
  }

  // genuinely unreachable: EURJPY on a GBP account with no reference rates
  const noPath = computePosition({
    symbol: 'EURJPY', entry: 185.77, sl: 185.47, riskPct: 0.02,
    account: freshGBP, rates: {},
  });
  assert.equal(noPath.ok, false);
  assert.equal(noPath.error, 'missing-rate');

  const tpInf = computePosition({ symbol: 'XAUUSD', entry: 3350, sl: 3340, tp: Infinity, riskPct: 0.02, account: freshUSD, rates: {} });
  assert.equal(tpInf.ok, true);
  assert.equal(tpInf.profitCash, null);   // non-finite TP is ignored
});

test('SL equal to entry is rejected', () => {
  const r = computePosition({
    symbol: 'USDJPY', entry: 148.5, sl: 148.5,
    riskPct: 0.02, account: freshUSD, rates: {},
  });
  assert.equal(r.ok, false);
  assert.equal(r.error, 'sl-equals-entry');
});

test('rounding down means actual risk never exceeds allowed risk (sweep)', () => {
  for (let pips = 5; pips <= 300; pips += 7) {
    for (const riskPct of [0.02, 0.025, 0.03, 0.035, 0.04]) {
      const r = computePosition({
        symbol: 'GBPJPY', entry: 195.5, sl: 195.5 - pips * 0.01,
        riskPct, account: freshGBP, rates: { GBPUSD: 1.27 },
      });
      assert.equal(r.ok, true);
      assert.ok(r.actualRiskCash <= r.allowedRiskCash + 1e-9,
        `pips=${pips} risk=${riskPct}: ${r.actualRiskCash} > ${r.allowedRiskCash}`);
      assert.ok(r.postLossEquity >= r.guard.dailyFloor - 1e-9, 'stays above daily floor');
      assert.ok(r.postLossEquity >= r.guard.totalFloor - 1e-9, 'stays above total floor');
    }
  }
});

/* ---- the seven watchlist pairs ---- */

const WATCHLIST_RATES = { USDJPY: 159.165, GBPUSD: 1.36457, EURUSD: 1.16716, USDCAD: 1.38471, AUDUSD: 0.71598 };

test('all seven pairs size correctly on a £10k account at 1.5%', () => {
  // expected lots hand-computed from the spec, independent of the engine
  const cases = [
    ['XAUUSD', 4625.00, 4610.00, 4655.00, 0.13, 1138.82],
    ['GBPJPY', 217.180, 216.780, 217.980, 0.74, 201.29],
    ['EURJPY', 185.770, 185.470, 186.370, 0.99, 150.27],
    ['GBPUSD', 1.36450, 1.36150, 1.37050, 0.63, 237.97],
    ['USDJPY', 159.160, 158.860, 159.760, 1.01, 148.24],
    ['USDCAD', 1.38470, 1.38170, 1.39070, 0.86, 172.65],
    ['AUDUSD', 0.71590, 0.71290, 0.72190, 0.63, 237.44],
  ];
  for (const [symbol, entry, sl, tp, lots, perLot] of cases) {
    const r = computePosition({
      symbol, entry, sl, tp, riskPct: 0.015, account: freshGBP, rates: WATCHLIST_RATES,
    });
    assert.equal(r.ok, true, `${symbol} should size`);
    closeTo(r.perLotRiskTotal, perLot, 0.01);
    assert.equal(r.lots, lots, `${symbol} lots`);
    assert.ok(r.actualRiskCash <= 150 + 1e-9, `${symbol} risk within allowance`);
    assert.ok(r.marginRequired <= 9000 + 1e-9, `${symbol} margin within cap`);
    assert.equal(r.direction, 'long');
    assert.ok(r.profitCash > 0, `${symbol} profit positive`);
  }
});

test('conversion paths: own price beats reference rates, multi-hop when needed', () => {
  // GBPUSD trade prices GBP<->USD itself: the stop price wins over the GBPUSD rate
  const own = conversionRate('USD', 'GBP', { symbol: 'GBPUSD', entry: 1.3645, rates: WATCHLIST_RATES }, 1.3615);
  closeTo(own.rate, 1 / 1.3615);
  assert.equal(own.source, 'entry');

  // USDCAD prices CAD<->USD itself, then USD->GBP needs one reference hop
  const cad = conversionRate('CAD', 'GBP', { symbol: 'USDCAD', entry: 1.3847, rates: WATCHLIST_RATES }, 1.3817);
  closeTo(cad.rate, (1 / 1.3817) / 1.36457);
  assert.equal(cad.source, 'mixed');

  // EURJPY can't price JPY->GBP: two reference hops (JPY->USD->GBP)
  const eur = conversionRate('JPY', 'GBP', { symbol: 'EURJPY', entry: 185.77, rates: WATCHLIST_RATES }, 185.47);
  closeTo(eur.rate, (1 / 159.165) / 1.36457);
  assert.equal(eur.source, 'rates');

  // AUD notional for margin: own price to USD, reference hop to GBP
  const aud = conversionRate('AUD', 'GBP', { symbol: 'AUDUSD', entry: 0.7159, rates: WATCHLIST_RATES });
  closeTo(aud.rate, 0.7159 / 1.36457);
});

test('every pair works on a USD account, and shorts mirror longs', () => {
  for (const symbol of Object.keys(SYMBOLS)) {
    const mid = { XAUUSD: 4625, GBPJPY: 217.18, EURJPY: 185.77, GBPUSD: 1.3645, USDJPY: 159.16, USDCAD: 1.3847, AUDUSD: 0.7159 }[symbol];
    const step = mid * 0.002;
    const long = computePosition({ symbol, entry: mid, sl: mid - step, tp: mid + 2 * step, riskPct: 0.02, account: freshUSD, rates: WATCHLIST_RATES });
    const short = computePosition({ symbol, entry: mid, sl: mid + step, tp: mid - 2 * step, riskPct: 0.02, account: freshUSD, rates: WATCHLIST_RATES });
    assert.equal(long.ok, true, `${symbol} long`);
    assert.equal(short.ok, true, `${symbol} short`);
    assert.equal(long.direction, 'long');
    assert.equal(short.direction, 'short');
    for (const r of [long, short]) {
      assert.ok(r.lots > 0, `${symbol} sizes above zero`);
      assert.ok(r.actualRiskCash <= 200 + 1e-9, `${symbol} within 2% allowance`);
      assert.ok(r.postLossEquity >= r.guard.dailyFloor - 1e-9, `${symbol} clears daily floor`);
      assert.ok(Number.isFinite(r.marginRequired), `${symbol} margin computable`);
    }
  }
});

test('EURJPY sizes from GBPUSD + EURUSD alone, with no USDJPY rate', () => {
  // regression: all five reference rates must reach the engine, and the graph
  // must route JPY->EUR (trade) ->USD (EURUSD) ->GBP (GBPUSD) when USDJPY is absent
  const r = computePosition({
    symbol: 'EURJPY', entry: 185.770, sl: 185.470, tp: 186.370,
    riskPct: 0.015, account: freshGBP, rates: { GBPUSD: 1.36457, EURUSD: 1.16716 },
  });
  assert.equal(r.ok, true);
  const jpyToGbp = (1 / 185.470) * 1.16716 / 1.36457;   // EURJPY stop -> EUR -> USD -> GBP
  closeTo(r.perLotRisk, 0.30 * 100000 * jpyToGbp, 1e-9);
  assert.ok(r.lots > 0);
  assert.ok(r.actualRiskCash <= 150 + 1e-9);
});

test('USDCAD and AUDUSD need only GBPUSD on a GBP account', () => {
  for (const [symbol, entry, sl] of [['USDCAD', 1.38470, 1.38170], ['AUDUSD', 0.71590, 0.71290]]) {
    const r = computePosition({ symbol, entry, sl, riskPct: 0.015, account: freshGBP, rates: { GBPUSD: 1.36457 } });
    assert.equal(r.ok, true, `${symbol} should size from its own price + GBPUSD`);
    assert.ok(r.lots > 0);
    assert.ok(Number.isFinite(r.marginRequired));
  }
});

test('rr is the price ratio; rrCash is what the money does', () => {
  const r = computePosition({
    symbol: 'GBPJPY', entry: 217.180, sl: 216.780, tp: 217.980,
    riskPct: 0.02, account: freshGBP, rates: WATCHLIST_RATES,
  });
  closeTo(r.rr, 2);                                    // price distance, before costs
  closeTo(r.rrCash, r.profitCash / r.actualRiskCash);  // after pad, commission and FX legs
  assert.ok(r.rrCash < r.rr, 'costs must drag the cash ratio below the price ratio');

  // no position → no cash ratio to report
  const zero = computePosition({
    symbol: 'XAUUSD', entry: 4625, sl: 4425, tp: 5025,
    riskPct: 0.01, account: freshGBP, rates: WATCHLIST_RATES,
  });
  assert.equal(zero.lots, 0);
  assert.equal(zero.rrCash, null);
  closeTo(zero.rr, 2);
});
