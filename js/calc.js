// Pure position-sizing engine. No DOM, no I/O — unit-tested in isolation.
import { RULES, SYMBOLS, DEFAULTS } from './rules.js';

const EPS = 1e-9;

export function floorToStep(value, step) {
  return Math.round(Math.floor(value / step + EPS) * step * 100) / 100;
}

/**
 * Convert an amount between currencies using the trade's own entry price where it
 * IS the needed rate (exact), falling back to externally supplied rates.
 * ctx: { symbol, entry, rates: { USDJPY, GBPUSD } }
 */
export function conversionRate(from, to, ctx) {
  if (from === to) return { rate: 1, source: 'none' };

  const { symbol, entry, rates } = ctx;
  const usdjpy = symbol === 'USDJPY' && entry > 0 ? entry : rates?.USDJPY;
  const usdjpySrc = symbol === 'USDJPY' && entry > 0 ? 'entry' : 'rates';
  const gbpjpy = symbol === 'GBPJPY' && entry > 0 ? entry : null;
  const gbpusd = rates?.GBPUSD;

  const pair = `${from}->${to}`;
  switch (pair) {
    case 'JPY->USD':
      if (!usdjpy) return { rate: null, missing: 'USDJPY' };
      return { rate: 1 / usdjpy, source: usdjpySrc };
    case 'USD->JPY':
      if (!usdjpy) return { rate: null, missing: 'USDJPY' };
      return { rate: usdjpy, source: usdjpySrc };
    case 'JPY->GBP': {
      if (gbpjpy) return { rate: 1 / gbpjpy, source: 'entry' };
      if (gbpusd && usdjpy) return { rate: 1 / (gbpusd * usdjpy), source: 'rates' };
      return { rate: null, missing: !gbpusd ? 'GBPUSD' : 'USDJPY' };
    }
    case 'GBP->JPY': {
      if (gbpjpy) return { rate: gbpjpy, source: 'entry' };
      if (gbpusd && usdjpy) return { rate: gbpusd * usdjpy, source: 'rates' };
      return { rate: null, missing: !gbpusd ? 'GBPUSD' : 'USDJPY' };
    }
    case 'USD->GBP':
      if (!gbpusd) return { rate: null, missing: 'GBPUSD' };
      return { rate: 1 / gbpusd, source: 'rates' };
    case 'GBP->USD':
      if (!gbpusd) return { rate: null, missing: 'GBPUSD' };
      return { rate: gbpusd, source: 'rates' };
    default:
      return { rate: null, missing: pair };
  }
}

/**
 * Drawdown floors and the cash risk actually allowed for the next trade.
 * All amounts in account currency.
 */
export function computeGuardrails({ initial, equity, todayPnl, riskPct, bufferPct }) {
  const dayStart = equity - todayPnl;
  const dailyAllowance = RULES.dailyPctBasis === 'initial'
    ? RULES.dailyLossPct * initial
    : RULES.dailyLossPct * dayStart;
  const dailyFloor = dayStart - dailyAllowance;
  const totalFloor = initial * (1 - RULES.maxLossPct);
  const buffer = bufferPct * initial;

  const dailyRoomNow = equity - dailyFloor;
  const totalRoomNow = equity - totalFloor;
  const headroomDaily = dailyRoomNow - buffer;
  const headroomTotal = totalRoomNow - buffer;

  const requestedRiskCash = riskPct * equity;
  let allowedRiskCash = Math.min(requestedRiskCash, headroomDaily, headroomTotal);
  let capReason = null;
  if (allowedRiskCash + EPS < requestedRiskCash) {
    capReason = headroomDaily <= headroomTotal ? 'daily' : 'total';
  }
  allowedRiskCash = Math.max(0, allowedRiskCash);

  return {
    dayStart, dailyFloor, totalFloor, buffer,
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

  const acctCcy = account.currency;
  const initial = account.initial;
  const equity = account.equity;
  const todayPnl = account.todayPnl || 0;

  if (!(entry > 0)) { out.error = 'need-entry'; return out; }
  if (!(sl > 0)) { out.error = 'need-sl'; return out; }
  if (Math.abs(entry - sl) < Math.pow(10, -spec.priceDecimals) / 2) {
    out.error = 'sl-equals-entry'; return out;
  }
  if (!(initial > 0) || !(equity > 0)) { out.error = 'need-account'; return out; }

  const direction = sl < entry ? 'long' : 'short';
  const stopDistance = Math.abs(entry - sl);
  const stopPips = stopDistance / spec.pipSize;

  const ctx = { symbol, entry, rates };
  const quoteToAcct = conversionRate(spec.quote, acctCcy, ctx);
  if (quoteToAcct.rate == null) { out.error = 'missing-rate'; out.missingRate = quoteToAcct.missing; return out; }
  const usdToAcct = conversionRate('USD', acctCcy, ctx);

  // Per-lot cash figures (account currency)
  const perLotRisk = stopDistance * spec.contractSize * quoteToAcct.rate;
  const pad = padPrice == null ? spec.defaultPadPrice : padPrice;
  const perLotPad = pad * spec.contractSize * quoteToAcct.rate;
  const commUSD = commissionUSDPerLot == null
    ? RULES.commissionUSDPerLot[spec.assetClass]
    : commissionUSDPerLot;
  const perLotCommission = usdToAcct.rate == null ? 0 : commUSD * usdToAcct.rate;
  if (usdToAcct.rate == null && commUSD > 0) {
    warnings.push({ code: 'commission-unconverted', level: 'info' });
  }
  const perLotRiskTotal = perLotRisk + perLotPad + perLotCommission;

  // Guardrails
  const guard = computeGuardrails({
    initial, equity, todayPnl, riskPct,
    bufferPct: input.bufferPct ?? DEFAULTS.bufferPct,
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
    if (!marginCapped) {
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
  let profitCash = null, rr = null, tpValid = null;
  if (tp != null && tp > 0) {
    tpValid = direction === 'long' ? tp > entry : tp < entry;
    if (!tpValid) warnings.push({ code: 'tp-wrong-side', level: 'warning' });
    const tpDistance = Math.abs(tp - entry);
    profitCash = tpDistance * spec.contractSize * quoteToAcct.rate * lots - perLotCommission * lots;
    rr = tpDistance / stopDistance;
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

  const pipValuePerLot = spec.pipSize * spec.contractSize * quoteToAcct.rate;

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
    profitCash, rr, tpValid,
    marginRequired, marginPctOfEquity, marginPerLot, marginCapped, leverage,
    guard,
    conversion: { quoteToAcct, usdToAcct },
  });
  return out;
}
