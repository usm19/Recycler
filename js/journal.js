// Trade journal — simulates the challenge account from taken trades.
// Pure functions only; no DOM, unit-tested in isolation.
import { RULES, SYMBOLS } from './rules.js';
import { conversionRate } from './calc.js';

/* The5ers MT5 server runs EET: GMT+2 winter, GMT+3 summer (EU DST:
   last Sunday of March 01:00 UTC → last Sunday of October 01:00 UTC). */
export function serverOffsetHours(ts) {
  const d = new Date(ts);
  const y = d.getUTCFullYear();
  const lastSunday = month => {
    const last = new Date(Date.UTC(y, month + 1, 0));
    return last.getUTCDate() - last.getUTCDay();
  };
  const dstStart = Date.UTC(y, 2, lastSunday(2), 1);
  const dstEnd = Date.UTC(y, 9, lastSunday(9), 1);
  return ts >= dstStart && ts < dstEnd ? 3 : 2;
}

/** Calendar day key (YYYY-MM-DD) in The5ers server time. */
export function serverDayKey(ts) {
  return new Date(ts + serverOffsetHours(ts) * 3600e3).toISOString().slice(0, 10);
}

/**
 * Realized P&L (account currency) for resolving a trade.
 * outcome: 'won' (exit at tp) | 'lost' (exit at sl) | 'closed' (exit at exitPrice)
 * Stop-outs charge the full padded risk the app sized with — the honest worst
 * case. Wins/custom closes convert at the exit price and net off commission.
 */
export function resolvePnl(trade, outcome, exitPrice = null) {
  const spec = SYMBOLS[trade.symbol];
  if (!spec) return null;
  const ctx = { symbol: trade.symbol, entry: trade.entry, rates: trade.rates || {} };

  if (outcome === 'lost') return -trade.riskCash;

  const exit = outcome === 'won' ? trade.tp : exitPrice;
  if (!(Number.isFinite(exit) && exit > 0)) return null;
  const conv = conversionRate(spec.quote, trade.currency, ctx, exit);
  if (conv.rate == null) return null;
  const dist = trade.direction === 'long' ? exit - trade.entry : trade.entry - exit;
  return dist * spec.contractSize * conv.rate * trade.lots
    - (trade.commissionCashPerLot || 0) * trade.lots;
}

/**
 * Aggregate the journal into the simulated account state.
 * Returns balance, day-start baseline, open risk, per-day stats and any
 * The5ers-rule breaches the recorded history implies.
 */
export function computeJournal(trades, initial, now) {
  const resolved = trades
    .filter(t => t.status !== 'open' && Number.isFinite(t.pnlCash))
    .sort((a, b) => (a.closedAt || 0) - (b.closedAt || 0));
  const open = trades.filter(t => t.status === 'open');

  const realizedTotal = resolved.reduce((s, t) => s + t.pnlCash, 0);
  const balance = initial + realizedTotal;
  const todayKey = serverDayKey(now);
  const realizedToday = resolved
    .filter(t => serverDayKey(t.closedAt) === todayKey)
    .reduce((s, t) => s + t.pnlCash, 0);
  const dayStart = balance - realizedToday;
  const openRisk = open.reduce((s, t) => s + (t.riskCash || 0), 0);

  // walk day by day, in close order, to find historical rule breaches
  const byDay = new Map();
  for (const t of resolved) {
    const k = serverDayKey(t.closedAt);
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k).push(t);
  }
  const days = [...byDay.keys()].sort();
  const totalFloor = initial * (1 - RULES.maxLossPct);
  let cursor = initial;
  let profitableDays = 0;
  const breaches = [];
  for (const k of days) {
    const dayTrades = byDay.get(k);
    const dayStartBal = cursor;
    const dailyFloor = dayStartBal * (1 - RULES.dailyLossPct);
    let running = dayStartBal;
    for (const t of dayTrades) {
      running += t.pnlCash;
      if (running < dailyFloor && !breaches.some(b => b.day === k && b.kind === 'daily')) {
        breaches.push({ day: k, kind: 'daily', equity: running, floor: dailyFloor });
      }
      if (running < totalFloor && !breaches.some(b => b.kind === 'total')) {
        breaches.push({ day: k, kind: 'total', equity: running, floor: totalFloor });
      }
    }
    const dayPnl = running - dayStartBal;
    if (dayPnl >= RULES.profitableDayPct * initial) profitableDays += 1;
    cursor = running;
  }

  const wins = resolved.filter(t => t.pnlCash > 0).length;
  const losses = resolved.filter(t => t.pnlCash <= 0).length;

  return {
    balance, dayStart, openRisk,
    realizedTotal, realizedToday,
    tradeCount: trades.length, openCount: open.length, wins, losses,
    profitableDays,
    stepProgress: Math.max(0, Math.min(1, realizedTotal / (RULES.targets.step1 * initial))),
    breaches,
  };
}
