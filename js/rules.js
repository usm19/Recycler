// The5ers — High Stakes (Classic) ruleset.
// Every number here was verified against official The5ers sources; see README for citations.
// PENDING-RESEARCH markers are finalized from the live-site research pass before release.

export const RULES = {
  program: 'The5ers High Stakes Classic',

  // Daily loss: breach if equity falls this % of INITIAL balance below the day-start baseline.
  dailyLossPct: 0.05,               // PENDING-RESEARCH
  // 'initial' = % is measured on initial account size; 'daystart' = % of day-start value.
  dailyPctBasis: 'initial',         // PENDING-RESEARCH
  // Baseline the daily floor hangs from: day-start balance, equity, or max of the two.
  dailyBaseline: 'balance',         // PENDING-RESEARCH
  dailyResetNote: 'Resets at midnight server time (GMT+3 DST / GMT+2 winter).', // PENDING-RESEARCH

  // Overall max loss: breach if equity falls below initial × (1 − maxLossPct). Static, not trailing.
  maxLossPct: 0.10,                 // PENDING-RESEARCH
  maxLossStatic: true,              // PENDING-RESEARCH

  targets: { step1: 0.08, step2: 0.05 },  // PENDING-RESEARCH

  leverage: { fx: 100, metals: 100 },     // PENDING-RESEARCH
  marginCallLevel: 1.0,             // 100% — informational
  stopOutLevel: 0.5,                // 50% — PENDING-RESEARCH

  // Round-turn commission, USD per standard lot.
  commissionUSDPerLot: { fx: 4, metals: 4 },  // PENDING-RESEARCH

  stopLossMandatory: true,          // PENDING-RESEARCH
  minProfitableDays: 3,             // PENDING-RESEARCH
  profitableDayPct: 0.005,          // a day counts as profitable at ≥ this % — PENDING-RESEARCH
};

export const SYMBOLS = {
  GBPJPY: {
    label: 'GBP/JPY',
    contractSize: 100000,
    quote: 'JPY',
    base: 'GBP',
    assetClass: 'fx',
    pipSize: 0.01,
    priceDecimals: 3,
    // Combined spread+slippage pad applied to the stop, in price units (editable in settings).
    defaultPadPrice: 0.03,
  },
  XAUUSD: {
    label: 'GOLD',
    contractSize: 100,
    quote: 'USD',
    base: 'XAU',
    assetClass: 'metals',
    pipSize: 0.1,
    priceDecimals: 2,
    defaultPadPrice: 0.5,
  },
  USDJPY: {
    label: 'USD/JPY',
    contractSize: 100000,
    quote: 'JPY',
    base: 'USD',
    assetClass: 'fx',
    pipSize: 0.01,
    priceDecimals: 3,
    defaultPadPrice: 0.015,
  },
};

export const DEFAULTS = {
  accountSize: 10000,
  accountCurrency: 'GBP',      // £10k challenge; switchable to USD in settings
  riskPct: 0.03,
  // Safety buffer kept between the worst-case post-loss equity and any breach floor,
  // as a fraction of initial account size.
  bufferPct: 0.01,
  minLot: 0.01,
  lotStep: 0.01,
};
