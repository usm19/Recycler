// The5ers — High Stakes Classic ruleset.
// Verified against official The5ers sources (help.the5ers.com, the5ers.com FAQ,
// asset-specifications, official X post of 25 Mar 2026 for metals leverage).
// See README for citations. If The5ers changes terms, this is the only file to edit.

export const RULES = {
  program: 'The5ers High Stakes Classic',

  // Daily loss: HARD BREACH if equity falls 5% below the day-start baseline.
  // Baseline = the HIGHER of balance or equity at 00:00 server time (GMT+2 winter /
  // GMT+3 summer), so the allowance re-bases every day and grows with the account.
  dailyLossPct: 0.05,
  dailyPctBasis: 'daystart',   // % of the day-start baseline, NOT of initial balance
  dailyResetNote: 'Resets 00:00 server time (GMT+3 summer / GMT+2 winter). Baseline = higher of balance/equity at that moment.',

  // Overall max loss: HARD BREACH if equity falls below initial × (1 − 10%).
  // Static/absolute — anchored to initial balance, never trails.
  maxLossPct: 0.10,
  maxLossStatic: true,

  // Classic variant: Step 1 = 8%, Step 2 = 5% (the "New" variant is 10%/5%).
  targets: { step1: 0.08, step2: 0.05 },

  // FX 1:100; metals & indices 1:25 on all account sizes (official change, 25 Mar 2026).
  leverage: { fx: 100, metals: 25 },

  // Round-turn commission, USD per standard lot. FX officially $4/lot round trip.
  // Gold sources conflict ($4 vs ~0.0008% of notional ≈ $2.7) — we take the
  // conservative $4; editable in settings.
  commissionUSDPerLot: { fx: 4, metals: 4 },

  // Stop loss is SUGGESTED, not required, on High Stakes (Bootcamp is the program
  // with a mandatory SL). If used it must be a visible platform order — hidden
  // "stealth" stop losses are prohibited. The5ers suggests ≤1% risk per position
  // (suggestion only, not enforced).
  stopLossMandatory: false,
  suggestedMaxRiskPct: 0.01,

  minProfitableDays: 3,
  profitableDayPct: 0.005,     // closed profit ≥ 0.5% of INITIAL balance

  // Other conduct rules that matter (informational):
  // - News: no opening/closing trades from 2 min before to 2 min after
  //   high-impact news; holding through is allowed.
  // - Overnight & weekend holding allowed.
  // - Inactivity: account expires after 30 consecutive days without a trade.
  // - Prohibited: HFT/tick-scalping (seconds-long trades), cross-account hedging,
  //   third-party copy trading, latency arbitrage, account sharing.
  newsRule: 'No open/close ±2 min around high-impact news (holding through is fine)',
};

// Display order matches the trader's TradingView watchlist.
// pipSize/priceDecimals follow the broker quote convention; defaultPadPrice is a
// spread+slippage cushion in price units, added to every stop when sizing.
export const SYMBOLS = {
  XAUUSD: {
    label: 'GOLD', short: 'GOLD',
    contractSize: 100, base: 'XAU', quote: 'USD',
    assetClass: 'metals', pipSize: 0.1, priceDecimals: 2,
    defaultPadPrice: 0.5,
  },
  GBPJPY: {
    label: 'GBP/JPY', short: 'GBPJPY',
    contractSize: 100000, base: 'GBP', quote: 'JPY',
    assetClass: 'fx', pipSize: 0.01, priceDecimals: 3,
    defaultPadPrice: 0.03,
  },
  EURJPY: {
    label: 'EUR/JPY', short: 'EURJPY',
    contractSize: 100000, base: 'EUR', quote: 'JPY',
    assetClass: 'fx', pipSize: 0.01, priceDecimals: 3,
    defaultPadPrice: 0.02,
  },
  GBPUSD: {
    label: 'GBP/USD', short: 'GBPUSD',
    contractSize: 100000, base: 'GBP', quote: 'USD',
    assetClass: 'fx', pipSize: 0.0001, priceDecimals: 5,
    defaultPadPrice: 0.0002,
  },
  USDJPY: {
    label: 'USD/JPY', short: 'USDJPY',
    contractSize: 100000, base: 'USD', quote: 'JPY',
    assetClass: 'fx', pipSize: 0.01, priceDecimals: 3,
    defaultPadPrice: 0.015,
  },
  USDCAD: {
    label: 'USD/CAD', short: 'USDCAD',
    contractSize: 100000, base: 'USD', quote: 'CAD',
    assetClass: 'fx', pipSize: 0.0001, priceDecimals: 5,
    defaultPadPrice: 0.0002,
  },
  AUDUSD: {
    label: 'AUD/USD', short: 'AUDUSD',
    contractSize: 100000, base: 'AUD', quote: 'USD',
    assetClass: 'fx', pipSize: 0.0001, priceDecimals: 5,
    defaultPadPrice: 0.0002,
  },
};

// Reference FX pairs used to convert between currencies the trade itself
// doesn't price. Each is an edge base->quote in the conversion graph.
export const RATE_PAIRS = [
  { key: 'USDJPY', base: 'USD', quote: 'JPY', label: 'USD/JPY' },
  { key: 'GBPUSD', base: 'GBP', quote: 'USD', label: 'GBP/USD' },
  { key: 'EURUSD', base: 'EUR', quote: 'USD', label: 'EUR/USD' },
  { key: 'USDCAD', base: 'USD', quote: 'CAD', label: 'USD/CAD' },
  { key: 'AUDUSD', base: 'AUD', quote: 'USD', label: 'AUD/USD' },
];

export const DEFAULTS = {
  accountSize: 10000,
  accountCurrency: 'GBP',      // user's stated £10k; switchable to USD in settings
  riskPct: 0.015,
  // Safety buffer kept between the worst-case post-loss equity and any breach floor,
  // as a fraction of initial account size.
  bufferPct: 0.01,
  minLot: 0.01,
  lotStep: 0.01,
  // Never let required margin exceed this share of equity when sizing
  // (The5ers lets you use full margin; we keep 10% headroom so orders can't be
  // rejected and a small adverse move can't margin-call you at entry).
  maxMarginUseOfEquity: 0.9,
};
