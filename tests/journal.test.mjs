import { test } from 'node:test';
import assert from 'node:assert/strict';
import { serverOffsetHours, serverDayKey, resolvePnl, computeJournal } from '../js/journal.js';
import { computeGuardrails } from '../js/calc.js';

const closeTo = (a, b, tol = 1e-6) =>
  assert.ok(Math.abs(a - b) <= tol, `expected ${a} ≈ ${b} (±${tol})`);

/* fixed timestamps (UTC) */
const T = iso => Date.parse(iso);

test('server timezone: GMT+3 in summer, GMT+2 in winter, EU DST boundaries', () => {
  assert.equal(serverOffsetHours(T('2026-07-15T12:00:00Z')), 3);
  assert.equal(serverOffsetHours(T('2026-01-15T12:00:00Z')), 2);
  // DST starts last Sunday of March 2026 (29th) at 01:00 UTC
  assert.equal(serverOffsetHours(T('2026-03-29T00:59:00Z')), 2);
  assert.equal(serverOffsetHours(T('2026-03-29T01:01:00Z')), 3);
  // DST ends last Sunday of October 2026 (25th) at 01:00 UTC
  assert.equal(serverOffsetHours(T('2026-10-25T00:59:00Z')), 3);
  assert.equal(serverOffsetHours(T('2026-10-25T01:01:00Z')), 2);
});

test('serverDayKey rolls the day at 00:00 server time (21:00 UTC in summer)', () => {
  assert.equal(serverDayKey(T('2026-07-28T20:59:00Z')), '2026-07-28');
  assert.equal(serverDayKey(T('2026-07-28T21:01:00Z')), '2026-07-29');
});

const gbpjpyLong = {
  symbol: 'GBPJPY', currency: 'GBP', direction: 'long',
  entry: 195.5, sl: 195.0, tp: 196.5, lots: 1.09,
  riskCash: 299.0, commissionCashPerLot: 3.15,
  rates: { USDJPY: 148.5, GBPUSD: 1.27 },
};

test('resolvePnl: stop-out charges the full padded risk', () => {
  closeTo(resolvePnl(gbpjpyLong, 'lost'), -299.0);
});

test('resolvePnl: win converts at the target price, net of commission', () => {
  const pnl = resolvePnl(gbpjpyLong, 'won');
  closeTo(pnl, 1.0 * 100000 / 196.5 * 1.09 - 3.15 * 1.09, 1e-6);
});

test('resolvePnl: custom close, both directions, gold in USD', () => {
  const t = { symbol: 'XAUUSD', currency: 'USD', direction: 'short', entry: 3350, sl: 3360, tp: null, lots: 0.18, riskCash: 190, commissionCashPerLot: 4, rates: {} };
  closeTo(resolvePnl(t, 'closed', 3341), (3350 - 3341) * 100 * 0.18 - 4 * 0.18);
  closeTo(resolvePnl(t, 'closed', 3355), (3350 - 3355) * 100 * 0.18 - 4 * 0.18); // losing close
  assert.equal(resolvePnl(t, 'closed', NaN), null);
});

test('computeJournal: balance, day-start rollover, open risk, profitable days', () => {
  const now = T('2026-07-28T12:00:00Z');           // server day 2026-07-28
  const yesterday = T('2026-07-27T12:00:00Z');     // server day 2026-07-27
  const trades = [
    { status: 'won', pnlCash: 200, closedAt: yesterday, openedAt: yesterday, riskCash: 100 },
    { status: 'lost', pnlCash: -150, closedAt: now, openedAt: now, riskCash: 150 },
    { status: 'open', riskCash: 120, openedAt: now },
  ];
  const j = computeJournal(trades, 10000, now);
  closeTo(j.balance, 10050);                        // 10000 + 200 − 150
  closeTo(j.realizedToday, -150);
  closeTo(j.dayStart, 10200);                       // balance − today's P&L
  closeTo(j.openRisk, 120);
  assert.equal(j.wins, 1);
  assert.equal(j.losses, 1);
  assert.equal(j.openCount, 1);
  assert.equal(j.profitableDays, 1);                // +200 ≥ 0.5% of 10k
  assert.equal(j.breaches.length, 0);
});

test('computeJournal: detects an intraday daily breach in the recorded history', () => {
  const d = T('2026-07-27T10:00:00Z');
  const trades = [
    { status: 'lost', pnlCash: -300, closedAt: d, openedAt: d, riskCash: 300 },
    { status: 'lost', pnlCash: -250, closedAt: d + 3600e3, openedAt: d, riskCash: 250 },
    { status: 'won', pnlCash: 400, closedAt: d + 7200e3, openedAt: d, riskCash: 100 },
  ];
  const j = computeJournal(trades, 10000, d + 86400e3);
  // running: 9700 → 9450 < 9500 floor → daily breach, even though the day recovered
  assert.equal(j.breaches.length, 1);
  assert.equal(j.breaches[0].kind, 'daily');
  closeTo(j.breaches[0].floor, 9500);
});

test('computeJournal: max-loss breach flagged when balance crosses 90% of initial', () => {
  const d = T('2026-07-27T10:00:00Z');
  const trades = [
    { status: 'lost', pnlCash: -400, closedAt: d, openedAt: d, riskCash: 400 },
    { status: 'lost', pnlCash: -400, closedAt: d + 86400e3, openedAt: d, riskCash: 400 },
    { status: 'lost', pnlCash: -400, closedAt: d + 2 * 86400e3, openedAt: d, riskCash: 400 },
  ];
  const j = computeJournal(trades, 10000, d + 3 * 86400e3);
  closeTo(j.balance, 8800);
  assert.ok(j.breaches.some(b => b.kind === 'total'));
});

test('guardrails: open-trade risk shrinks the next trade allowance', () => {
  const base = { initial: 10000, equity: 10000, dayStart: 10000, riskPct: 0.03, bufferPct: 0.01 };
  const g0 = computeGuardrails({ ...base, openRiskCash: 0 });
  closeTo(g0.allowedRiskCash, 300);
  const g1 = computeGuardrails({ ...base, openRiskCash: 250 });
  closeTo(g1.headroomDaily, 400 - 250);            // 500 room − 100 buffer − 250 open
  closeTo(g1.allowedRiskCash, 150);
  assert.equal(g1.capReason, 'daily');
  const g2 = computeGuardrails({ ...base, openRiskCash: 500 });
  closeTo(g2.allowedRiskCash, 0);                  // fully committed
});
