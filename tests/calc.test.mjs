import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computePosition, computeGuardrails, conversionRate, floorToStep } from '../js/calc.js';

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
  assert.ok(r.warnings.some(w => w.code === 'commission-unconverted'));
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
