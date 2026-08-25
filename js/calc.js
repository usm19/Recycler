// Pure position-sizing engine. No DOM, no I/O — unit-tested in isolation.
import { RULES, SYMBOLS, DEFAULTS, RATE_PAIRS } from './rules.js';

const EPS = 1e-9;

export function floorToStep(value, step) {
  return Math.round(Math.floor(value / step + EPS) * step * 100) / 100;
}

/**
 * Convert an amount between currencies.
 *
 * Builds a small graph of currency edges — the trade's OWN price (exact, no
 * external data) plus whatever reference rates are available — and walks the
 * shortest path. Fewest hops wins, so a trade that directly prices the pair
 * (GBPJPY for GBP<->JPY, AUDUSD for AUD<->USD, ...) always beats a detour
 * through reference rates.
 *
 * ctx: { symbol, entry, rates: { USDJPY, GBPUSD, EURUSD, USDCAD, AUDUSD } }
 * atPrice: which price of ctx.symbol to convert at — losses convert at the stop
 * and profits at the target (the rate that applies when the position closes
 * there); defaults to entry.
 */
export function conversionRate(from, to, ctx, atPrice = null) {
  if (from === to) return { rate: 1, source: 'none' };

  const fin = v => (Number.isFinite(v) && v > 0 ? v : null);
  const { symbol, entry, rates } = ctx || {};
  const price = fin(atPrice) ?? fin(entry);

  const adj = new Map();
  const addEdge = (a, b, mult, source) => {
    if (!fin(mult)) return;
    if (!adj.has(a)) adj.set(a, []);
    if (!adj.has(b)) adj.set(b, []);
    adj.get(a).push({ to: b, mult, source });
    adj.get(b).push({ to: a, mult: 1 / mult, source });
  };

  // the trade's own price first, so it wins ties at equal hop count
  const spec = SYMBOLS[symbol];
  if (spec && price && spec.base !== 'XAU') addEdge(spec.base, spec.quote, price, 'entry');
  for (const p of RATE_PAIRS) addEdge(p.base, p.quote, fin(rates?.[p.key]), 'rates');

  // breadth-first: first arrival is the fewest-hop path
  const seen = new Map([[from, { rate: 1, source: null }]]);
  let frontier = [from];
  while (frontier.length) {
    const next = [];
    for (const cur of frontier) {
      const acc = seen.get(cur);
      for (const e of adj.get(cur) || []) {
        if (seen.has(e.to)) continue;
        const source = acc.source == null || acc.source === e.source ? e.source : 'mixed';
        const hop = { rate: acc.rate * e.mult, source };
        seen.set(e.to, hop);
        if (e.to === to) return { rate: hop.rate, source: hop.source };
        next.push(e.to);
      }
    }
    frontier = next;
  }

  // No path: name the reference rate that would help most — one that bridges
  // the two halves outright, else one that extends either half toward the other.
  const reach = start => {
    const out = new Set([start]);
    const queue = [start];
    while (queue.length) {
      for (const e of adj.get(queue.shift()) || []) {
        if (!out.has(e.to)) { out.add(e.to); queue.push(e.to); }
      }
    }
    return out;
  };
  const A = reach(from), B = reach(to);
  const absent = RATE_PAIRS.filter(p => !fin(rates?.[p.key]));
  const bridges = absent.find(p => (A.has(p.base) && B.has(p.quote)) || (A.has(p.quote) && B.has(p.base)));
  const touches = absent.find(p => A.has(p.base) || A.has(p.quote) || B.has(p.base) || B.has(p.quote));
  const pick = bridges || touches || absent[0];
  return { rate: null, missing: pick ? pick.key : `${from}->${to}`, missingCount: absent.length, missingBridges: !!bridges };
}

/**
 * Drawdown floors and the cash risk actually allowed for the next trade.
 * All amounts in account currency.
 *
 * dayStart is The5ers' daily baseline: the HIGHER of balance or equity at
 * 00:00 server time (shown on the dashboard). The working baseline never
 * drops below current equity, so a stale field is conservative on profitable
 * days and can only tighten the floor, never loosen it.
 *
 * openRiskCash: worst-case loss already committed to open positions. It is
 * subtracted from both headrooms so a new trade plus every open stop hitting
 * together still clears the floors.
 */
export function computeGuardrails({ initial, equity, dayStart = null, riskPct, bufferPct, openRiskCash = 0 }) {
  const baseline = Math.max(dayStart ?? equity, equity);
  const dailyAllowance = RULES.dailyLossPct * baseline;
  const dailyFloor = baseline - dailyAllowance;
  const totalFloor = initial * (1 - RULES.maxLossPct);
  const buffer = bufferPct * initial;
  const openRisk = Math.max(0, openRiskCash || 0);

  const dailyRoomNow = equity - dailyFloor;
  const totalRoomNow = equity - totalFloor;
  const headroomDaily = dailyRoomNow - buffer - openRisk;
  const headroomTotal = totalRoomNow - buffer - openRisk;

  const requestedRiskCash = riskPct * equity;
  let allowedRiskCash = Math.min(requestedRiskCash, headroomDaily, headroomTotal);
  let capReason = null;
  if (allowedRiskCash + EPS < requestedRiskCash) {
    capReason = headroomDaily <= headroomTotal ? 'daily' : 'total';
  }
  allowedRiskCash = Math.max(0, allowedRiskCash);

  return {
    baseline, dayStart: baseline, dailyFloor, totalFloor, buffer, openRisk,
    dailyRoomNow, totalRoomNow, headroomDaily, headroomTotal,
    requestedRiskCash, allowedRiskCash, capReason,
    breachedDaily: dailyRoomNow <= 0,
    breachedTotal: totalRoomNow <= 0,
  };
}

/**
 * Main entry point. Returns a complete result object for rendering.
 */
export function computePosition(input) {
  const {
    symbol, entry, sl, tp = null,
    riskPct = DEFAULTS.riskPct,
    account,                       // { initial, currency, equity, todayPnl }
    rates = {},                    // { USDJPY, GBPUSD }
    padPrice = null,               // spread+slippage pad in price units; null → symbol default
    commissionUSDPerLot = null,    // null → rules default for asset class
  } = input;

  const spec = SYMBOLS[symbol];
  const warnings = [];
  const out = { ok: false, error: null, warnings, symbol };
  if (!spec) { out.error = 'unknown-symbol'; return out; }

  const acctCcy = account?.currency;
  const initial = account?.initial;
  const equity = account?.equity;
  const dayStart = account?.dayStart ?? equity;

  const fin = v => Number.isFinite(v) && v > 0;
  if (!fin(entry)) { out.error = 'need-entry'; return out; }
  if (!fin(sl)) { out.error = 'need-sl'; return out; }
  if (Math.abs(entry - sl) < Math.pow(10, -spec.priceDecimals) / 2) {
    out.error = 'sl-equals-entry'; return out;
  }
  if (!fin(initial) || !fin(equity)) { out.error = 'need-account'; return out; }

  const direction = sl < entry ? 'long' : 'short';
  const stopDistance = Math.abs(entry - sl);
  const stopPips = stopDistance / spec.pipSize;

  const ctx = { symbol, entry, rates };
  // Losses realize at the stop price, so convert the risk leg at the stop —
  // exact for the entry-derived crosses, and correct in both directions.
  const quoteToAcct = conversionRate(spec.quote, acctCcy, ctx, sl);
  if (quoteToAcct.rate == null) {
    out.error = 'missing-rate';
    out.missingRate = quoteToAcct.missing;
    out.missingBridges = quoteToAcct.missingBridges;
    return out;
  }
  const quoteToAcctNow = conversionRate(spec.quote, acctCcy, ctx);
  const usdToAcct = conversionRate('USD', acctCcy, ctx);

  // Per-lot cash figures (account currency)
  const perLotRisk = stopDistance * spec.contractSize * quoteToAcct.rate;
  const pad = padPrice == null ? spec.defaultPadPrice : padPrice;
  const perLotPad = pad * spec.contractSize * quoteToAcct.rate;
  const commUSD = commissionUSDPerLot == null
    ? RULES.commissionUSDPerLot[spec.assetClass]
    : commissionUSDPerLot;
  // If USD can't be converted (GBP account with no GBP/USD rate), charge the
  // commission at par rather than dropping it — 1.0 over-states the true cost
  // while GBPUSD >= 1, so sizing stays conservative instead of drifting large.
  const commRate = usdToAcct.rate == null ? 1 : usdToAcct.rate;
  const perLotCommission = commUSD * commRate;
  if (usdToAcct.rate == null && commUSD > 0) {
    warnings.push({ code: 'commission-estimated', level: 'info' });
  }
  const perLotRiskTotal = perLotRisk + perLotPad + perLotCommission;

  // Guardrails
  const guard = computeGuardrails({
    initial, equity, dayStart, riskPct,
    bufferPct: input.bufferPct ?? DEFAULTS.bufferPct,
    openRiskCash: input.openRiskCash ?? 0,
  });

  if (guard.breachedTotal) warnings.push({ code: 'breached-total', level: 'critical' });
  else if (guard.breachedDaily) warnings.push({ code: 'breached-daily', level: 'critical' });

  // Margin per lot (needed before sizing — leverage can bind, esp. gold at 1:25)
  const leverage = RULES.leverage[spec.assetClass];
  let notionalPerLotAcct = null;
  if (spec.base === 'XAU') {
    notionalPerLotAcct = usdToAcct.rate == null ? null : entry * spec.contractSize * usdToAcct.rate;
  } else {
    const baseToAcct = conversionRate(spec.base, acctCcy, ctx);
    notionalPerLotAcct = baseToAcct.rate == null ? null : spec.contractSize * baseToAcct.rate;
  }
  const marginPerLot = notionalPerLotAcct == null ? null : notionalPerLotAcct / leverage;

  // Lot size: bounded by allowed risk, then by usable margin
  let lots = floorToStep(guard.allowedRiskCash / perLotRiskTotal, DEFAULTS.lotStep);
  let marginCapped = false;
  if (marginPerLot != null && marginPerLot > 0) {
    const maxByMargin = floorToStep(equity * DEFAULTS.maxMarginUseOfEquity / marginPerLot, DEFAULTS.lotStep);
    if (lots > maxByMargin) {
      lots = Math.max(0, maxByMargin);
      marginCapped = true;
      warnings.push({ code: 'margin-capped', level: 'warning' });
    }
  } else {
    warnings.push({ code: 'margin-unknown', level: 'info' });
  }
  const minLotRiskCash = DEFAULTS.minLot * perLotRiskTotal;
  if (lots < DEFAULTS.minLot) {
    lots = 0;
    // If even the full un-capped request couldn't cover 0.01 lots, the stop
    // really is too wide; otherwise the allowance is what ran out.
    const stopGenuinelyWide = minLotRiskCash > guard.requestedRiskCash;
    const noRoom = !stopGenuinelyWide && !guard.breachedDaily && !guard.breachedTotal
      && (guard.allowedRiskCash <= 0 || guard.capReason != null);
    if (noRoom) {
      // Headroom exhausted (buffer zone, or reserved by open trades) — the
      // stop is fine, there is simply no allowance left to spend on it.
      warnings.push({
        code: 'no-headroom', level: 'serious',
        allowedRiskCash: guard.allowedRiskCash,
        minLotRiskCash,
        openRisk: guard.openRisk,
      });
    } else if (!marginCapped) {
      warnings.push({
        code: 'stop-too-wide', level: 'serious',
        minLotRiskCash,
        minLotRiskPct: equity > 0 ? minLotRiskCash / equity : null,
      });
    }
  }

  const actualRiskCash = lots * perLotRiskTotal;
  const actualRiskStopOnly = lots * (perLotRisk + perLotCommission);
  const actualRiskPct = equity > 0 ? actualRiskCash / equity : 0;
  const postLossEquity = equity - actualRiskCash;

  // Take profit / reward
  let profitCash = null, rr = null, rrCash = null, tpValid = null;
  if (tp != null && Number.isFinite(tp) && tp > 0) {
    tpValid = direction === 'long' ? tp > entry : tp < entry;
    if (!tpValid) warnings.push({ code: 'tp-wrong-side', level: 'warning' });
    const tpDistance = Math.abs(tp - entry);
    // Profits realize at the target price
    const quoteToAcctTp = conversionRate(spec.quote, acctCcy, ctx, tp);
    const tpRate = quoteToAcctTp.rate ?? quoteToAcct.rate;
    profitCash = tpDistance * spec.contractSize * tpRate * lots - perLotCommission * lots;
    rr = tpDistance / stopDistance;   // price distance only, before costs/FX legs
  }

  // Margin totals for the sized position
  let marginRequired = null, marginPctOfEquity = null;
  if (marginPerLot != null) {
    marginRequired = marginPerLot * lots;
    marginPctOfEquity = equity > 0 ? marginRequired / equity : null;
    if (!marginCapped && marginPctOfEquity != null && marginPctOfEquity > 0.5) {
      warnings.push({ code: 'high-margin', level: 'warning' });
    }
  }

  const pipValuePerLot = spec.pipSize * spec.contractSize * quoteToAcctNow.rate;

  // Cash reward-per-unit-risk: what the two money figures on screen actually do.
  rrCash = actualRiskCash > 0 && profitCash != null ? profitCash / actualRiskCash : null;

  Object.assign(out, {
    ok: true,
    direction, stopDistance, stopPips,
    perLotRisk, perLotPad, perLotCommission, perLotRiskTotal,
    pipValuePerLot, pipValueActual: pipValuePerLot * lots,
    lots,
    requestedRiskCash: guard.requestedRiskCash,
    allowedRiskCash: guard.allowedRiskCash,
    capReason: guard.capReason,
    actualRiskCash, actualRiskStopOnly, actualRiskPct, postLossEquity,
    profitCash, rr, rrCash, tpValid,
    marginRequired, marginPctOfEquity, marginPerLot, marginCapped, leverage,
    guard,
    conversion: { quoteToAcct, usdToAcct },
  });
  return out;
}
