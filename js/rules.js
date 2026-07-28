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
  accountCurrency: 'GBP',      // user's stated £10k; switchable to USD in settings
  riskPct: 0.03,
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
