import { computePosition, computeGuardrails } from './calc.js';
import { RULES, SYMBOLS, DEFAULTS, RATE_PAIRS } from './rules.js';
import { computeJournal, resolvePnl } from './journal.js';

/* ---------------- state ---------------- */

const STORE_KEY = 'nebula-v1';

const defaultState = () => ({
  symbol: 'GBPJPY',
  inputs: Object.fromEntries(Object.keys(SYMBOLS).map(k => [k, { entry: '', sl: '', tp: '' }])),
  riskPct: DEFAULTS.riskPct,
  account: {
    initial: DEFAULTS.accountSize,
    currency: DEFAULTS.accountCurrency,
    equity: DEFAULTS.accountSize,
    // The5ers daily baseline: higher of balance/equity at 00:00 server time
    dayStart: DEFAULTS.accountSize,
  },
  bufferPct: DEFAULTS.bufferPct,
  pads: Object.fromEntries(Object.entries(SYMBOLS).map(([k, v]) => [k, v.defaultPadPrice])),
  commissionUSDPerLot: RULES.commissionUSDPerLot.fx,
  rates: { ...Object.fromEntries(RATE_PAIRS.map(p => [p.key, null])), ts: null, source: null },
  tracking: 'journal',                       // 'journal' | 'manual'
  journal: { currency: null, trades: [] },
});

function loadState() {
  const base = defaultState();
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return base;
    const saved = JSON.parse(raw);
    const s = {
      ...base, ...saved,
      inputs: { ...base.inputs },
      account: { ...base.account, ...(saved.account || {}) },
      pads: { ...base.pads },
      rates: { ...base.rates, ...(saved.rates || {}) },
    };
    // sanitize — corrupt/old storage must never break boot or the math
    if (!SYMBOLS[s.symbol]) s.symbol = base.symbol;
    for (const k of Object.keys(SYMBOLS)) {
      const inp = saved.inputs?.[k];
      const cell = v => (typeof v === 'string' || typeof v === 'number') ? String(v) : '';
      if (inp) s.inputs[k] = { entry: cell(inp.entry), sl: cell(inp.sl), tp: cell(inp.tp) };
      const pad = Number(saved.pads?.[k]);
      if (Number.isFinite(pad) && pad >= 0) s.pads[k] = pad;
    }
    const num = (v, fb, min = 0) => (Number.isFinite(v) && v > min ? v : fb);
    s.account.initial = num(s.account.initial, base.account.initial);
    s.account.equity = num(s.account.equity, s.account.initial);
    // migrate old todayPnl-based storage: dayStart = equity − todayPnl
    if (!Number.isFinite(s.account.dayStart) && Number.isFinite(saved.account?.todayPnl)) {
      s.account.dayStart = s.account.equity - saved.account.todayPnl;
    }
    s.account.dayStart = num(s.account.dayStart, s.account.equity);
    delete s.account.todayPnl;
    if (s.account.currency !== 'GBP' && s.account.currency !== 'USD') s.account.currency = base.account.currency;
    // clamp to the UI's actual ranges; anything outside falls back to defaults
    const rawRisk = Math.min(0.02, Math.max(0.0025, num(s.riskPct, base.riskPct)));
    s.riskPct = Math.round(rawRisk * 400) / 400;   // 0.25% grid, matching the slider
    s.bufferPct = Number.isFinite(s.bufferPct) && s.bufferPct >= 0 && s.bufferPct <= 0.03
      ? s.bufferPct : base.bufferPct;
    s.commissionUSDPerLot = Number.isFinite(s.commissionUSDPerLot) && s.commissionUSDPerLot >= 0
      ? s.commissionUSDPerLot : base.commissionUSDPerLot;
    for (const p of RATE_PAIRS) {
      if (!(Number.isFinite(s.rates[p.key]) && s.rates[p.key] > 0)) s.rates[p.key] = null;
    }
    // journal: keep only well-formed trades
    if (s.tracking !== 'journal' && s.tracking !== 'manual') s.tracking = base.tracking;
    const j = saved.journal || {};
    const finPos = v => Number.isFinite(v) && v > 0;
    const usable = t =>
      t && SYMBOLS[t.symbol]
      && (t.direction === 'long' || t.direction === 'short')
      && finPos(t.entry) && finPos(t.sl) && finPos(t.lots) && finPos(t.riskCash)
      && Number.isFinite(t.openedAt)
      && (t.currency === 'GBP' || t.currency === 'USD')
      && ['open', 'won', 'lost', 'closed'].includes(t.status)
      && (t.status === 'open' || (Number.isFinite(t.pnlCash) && Number.isFinite(t.closedAt)))
      && (t.status !== 'closed' || finPos(t.exitPrice));
    const rawTrades = Array.isArray(j.trades) ? j.trades : [];
    const trades = rawTrades.filter(usable).map(t => ({
      ...t,
      id: typeof t.id === 'string' ? t.id : Math.random().toString(36).slice(2),
      tp: finPos(t.tp) ? t.tp : null,
      commissionCashPerLot: Number.isFinite(t.commissionCashPerLot) ? t.commissionCashPerLot : 0,
      rates: t.rates && typeof t.rates === 'object' ? t.rates : {},
    }));
    // Anything unusable is parked, never deleted — a symbol table change or a
    // half-written record must not silently destroy trade history.
    const quarantined = [...(Array.isArray(j.quarantined) ? j.quarantined : []), ...rawTrades.filter(t => !usable(t))];
    s.journal = {
      currency: j.currency === 'GBP' || j.currency === 'USD' ? j.currency : (trades[0]?.currency ?? null),
      trades,
      ...(quarantined.length ? { quarantined } : {}),
    };
    return s;
  } catch { return base; }
}

const state = loadState();
let saveTimer = null;
function writeState() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch { /* full/private mode */ }
}

function save({ now = false } = {}) {
  clearTimeout(saveTimer);
  if (now) { writeState(); return; }
  saveTimer = setTimeout(writeState, 150);
}

// Another tab wrote the shared state — adopt it rather than clobbering it.
addEventListener('storage', e => {
  if (e.key !== STORE_KEY || e.newValue == null) return;
  Object.assign(state, loadState());
  syncSettingsFields();
  setRisk(state.riskPct * 100);
  setSymbol(state.symbol, false);
});
addEventListener('pagehide', () => { clearTimeout(saveTimer); writeState(); });

/* ---------------- helpers ---------------- */

const $ = id => document.getElementById(id);

function parseNum(str) {
  if (typeof str !== 'string') return null;
  // commas are thousands separators ("10,000"), never decimal points
  const s = str.trim().replace(/\s/g, '').replace(/−/g, '-').replace(/,/g, '');
  // Whole-string match only: "1.2.3" or "195abc" is rejected outright rather
  // than silently truncated to a number the field doesn't show.
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(s)) return null;
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : null;
}

function ccySymbol() { return state.account.currency === 'GBP' ? '£' : '$'; }

function fmtMoneyIn(ccy, x, decimals = null, signed = false) {
  if (x == null || !Number.isFinite(x)) return '—';
  const d = decimals ?? (Math.abs(x) >= 100 ? 0 : 2);
  const s = Math.abs(x).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sym = ccy === 'GBP' ? '£' : '$';
  return (x < 0 ? '−' : signed && x > 0 ? '+' : '') + sym + s;
}

function fmtMoney(x, decimals = null) {
  return fmtMoneyIn(state.account.currency, x, decimals);
}

/** Only the reference rates, snapshotted for the engine / a logged trade. */
function ratesSnapshot() {
  return Object.fromEntries(RATE_PAIRS.map(p => [p.key, state.rates[p.key]]));
}

function fmtPct(x, d = 1) {
  if (x == null || !Number.isFinite(x)) return '—';
  return (x * 100).toFixed(d).replace(/\.0+$/, '') + '%';
}

/* number tween */
function tween(el, target, format, dur = 340) {
  if (el._raf) cancelAnimationFrame(el._raf);
  const from = Number.isFinite(el._shown) ? el._shown : target;
  if (from === target) { el.textContent = format(target); el._shown = target; return; }
  const t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / dur);
    const e = 1 - Math.pow(1 - p, 3);
    const v = from + (target - from) * e;
    el.textContent = format(p === 1 ? target : v);
    el._shown = p === 1 ? target : v;
    if (p < 1) el._raf = requestAnimationFrame(step);
  };
  el._raf = requestAnimationFrame(step);
}

/* ---------------- symbol control ---------------- */

const SYMBOL_ORDER = Object.keys(SYMBOLS);
// Sensible starting prices near current market, so the fields hint the format.
const PLACEHOLDERS = {
  XAUUSD: { entry: '4625.00', sl: '4610.00', tp: '4655.00' },
  GBPJPY: { entry: '217.180', sl: '216.780', tp: '217.980' },
  EURJPY: { entry: '185.770', sl: '185.470', tp: '186.370' },
  GBPUSD: { entry: '1.36450', sl: '1.36150', tp: '1.37050' },
  USDJPY: { entry: '159.160', sl: '158.860', tp: '159.760' },
  USDCAD: { entry: '1.38470', sl: '1.38170', tp: '1.39070' },
  AUDUSD: { entry: '0.71590', sl: '0.71290', tp: '0.72190' },
};

/** Build the symbol buttons from the symbol table. */
function buildSymbolButtons() {
  const seg = $('symbolSeg');
  for (const key of SYMBOL_ORDER) {
    const b = document.createElement('button');
    b.dataset.symbol = key;
    b.textContent = SYMBOLS[key].short;
    b.setAttribute('aria-label', SYMBOLS[key].label);
    seg.appendChild(b);
  }
}

/** Park the puck over the active button — works for any wrapped layout. */
function movePuck(animate = true) {
  const btn = $('symbolSeg').querySelector(`button[data-symbol="${state.symbol}"]`);
  const puck = $('segPuck');
  if (!btn) return;
  if (!animate) puck.style.transition = 'none';
  puck.style.width = `${btn.offsetWidth}px`;
  puck.style.height = `${btn.offsetHeight}px`;
  puck.style.transform = `translate(${btn.offsetLeft}px, ${btn.offsetTop - 4}px)`;
  if (!animate) requestAnimationFrame(() => { puck.style.transition = ''; });
}

function setSymbol(sym, animate = true) {
  state.symbol = sym;
  document.querySelectorAll('#symbolSeg button').forEach(b =>
    b.classList.toggle('on', b.dataset.symbol === sym));
  movePuck(animate);
  const ph = PLACEHOLDERS[sym];
  const vals = state.inputs[sym];
  for (const k of ['entry', 'sl', 'tp']) {
    const el = $('in-' + k);
    el.placeholder = ph[k];
    el.value = vals[k];
  }
  $('set-pad').value = String(state.pads[sym]);
  save();
  render();
}

/* ---------------- risk control ---------------- */

function setRisk(pct, { fromSlider = false } = {}) {
  state.riskPct = pct / 100;
  const slider = $('riskSlider');
  if (!fromSlider) slider.value = String(pct);
  slider.style.setProperty('--fill', `${((pct - slider.min) / (slider.max - slider.min)) * 100}%`);
  $('riskOut').textContent = pct.toFixed(2).replace(/\.?0+$/, '') + '%';
  document.querySelectorAll('#riskChips .chip').forEach(c =>
    c.classList.toggle('on', parseFloat(c.dataset.risk) === pct));
  save();
  render();
}

/* ---------------- render ---------------- */

const BANNERS = {
  breachedTotal: () => ['bad', '✕', `<b>Max-loss breached.</b> Equity is at or below the ${fmtPct(RULES.maxLossPct)} overall floor. Do not trade — check your dashboard.`],
  breachedDaily: () => ['bad', '✕', `<b>Daily limit breached.</b> Equity is at or below today's ${fmtPct(RULES.dailyLossPct)} floor — on High Stakes this terminates the account. Check your dashboard before doing anything.`],
  missingRate: r => {
    const label = (RATE_PAIRS.find(p => p.key === r.missingRate) || {}).label || r.missingRate;
    return ['warn', '↺', r.missingBridges === false
      ? `<b>Need FX rates</b> to convert this pair into ${state.account.currency} — ${label} plus at least one more. Tap ⚙ → FX rates and refresh, or type them in.`
      : `<b>Need the ${label} rate</b> to convert this pair into ${state.account.currency}. Tap ⚙ → FX rates (or refresh online).`];
  },
  stopTooWide: w => ['warn', '⚠', `<b>Stop too wide.</b> Even 0.01 lots would risk ${fmtMoney(w.minLotRiskCash)}${w.minLotRiskPct ? ` (${fmtPct(w.minLotRiskPct)})` : ''} — over your safe limit. Tighten the stop or skip this trade.`],
  cap: (r) => ['warn', '⛨', `<b>Risk capped at ${fmtMoney(r.allowedRiskCash)}</b> (asked ${fmtMoney(r.requestedRiskCash)}) to keep your ${fmtPct(state.bufferPct)} buffer before the ${r.capReason === 'daily' ? 'daily-loss' : 'max-loss'} floor.`],
  marginCapped: (r) => ['warn', '◍', `<b>Lots capped by margin.</b> At 1:${r.leverage} leverage your equity supports ${r.lots.toFixed(2)} lots max (margin ${fmtMoney(r.marginRequired)}). Risk is ${fmtMoney(r.actualRiskCash)} — below your target.`],
  noHeadroom: w => ['bad', '⛔', w.openRisk > 0
    ? `<b>No room for another trade.</b> ${fmtMoney(w.openRisk)} of your drawdown headroom is already committed to open trades — only ${fmtMoney(Math.max(0, w.allowedRiskCash))} is left and the smallest position (0.01 lots) would risk ${fmtMoney(w.minLotRiskCash)}. Close or resolve a position first.`
    : `<b>No risk room left.</b> Only ${fmtMoney(Math.max(0, w.allowedRiskCash))} of headroom remains before your ${fmtPct(state.bufferPct)} buffer, and 0.01 lots would risk ${fmtMoney(w.minLotRiskCash)}. Sit out, or lower the buffer in settings if you accept less breathing space.`],
  tpWrongSide: () => ['warn', '⚠', `<b>Target is on the wrong side</b> for a ${state.lastDir || 'long'} — check entry / stop / target.`],
  highMargin: () => ['warn', '◍', `<b>Heavy margin use.</b> This position uses over half your equity as margin — a small adverse move could trigger a margin call.`],
};

function showBanner(kind, arg) {
  const b = $('banner');
  if (!kind) { b.className = 'banner'; return; }
  const [cls, ico, html] = BANNERS[kind](arg);
  b.className = `banner show ${cls}`;
  $('bannerIco').textContent = ico;
  $('bannerText').innerHTML = html;
}

function renderMeters(guard, tradeRisk) {
  const dailyAllow = guard.baseline - guard.dailyFloor;
  const totalAllow = state.account.initial * RULES.maxLossPct;

  const items = [
    { room: guard.dailyRoomNow, allow: dailyAllow, floor: guard.dailyFloor, fill: 'dailyFill', val: 'dailyVal', sub: 'dailySub' },
    { room: guard.totalRoomNow, allow: totalAllow, floor: guard.totalFloor, fill: 'totalFill', val: 'totalVal', sub: 'totalSub' },
  ];
  for (const it of items) {
    const frac = Math.max(0, Math.min(1, it.room / it.allow));
    const el = $(it.fill);
    el.style.width = `${frac * 100}%`;
    el.className = 'meter-fill ' + (frac > 0.5 ? 'ok' : frac > 0.2 ? 'warn' : 'bad');
    $(it.val).textContent = fmtMoney(Math.max(0, it.room));
    const after = it.room - (tradeRisk || 0) - guard.openRisk;
    const open = guard.openRisk > 0 ? ` · ${fmtMoney(guard.openRisk)} committed to open trades` : '';
    $(it.sub).textContent = tradeRisk > 0
      ? `floor ${fmtMoney(it.floor)} · ${fmtMoney(Math.max(0, after))} room if every stop hits${open}`
      : `floor ${fmtMoney(it.floor)}${open}`;
  }
}

function render() {
  const sym = state.symbol;
  const spec = SYMBOLS[sym];
  const vals = state.inputs[sym];
  const entry = parseNum(vals.entry);
  const sl = parseNum(vals.sl);
  const tp = parseNum(vals.tp);

  const jrnl = computeJournal(state.journal.trades, state.account.initial, Date.now());
  // journal drives the account only when its currency matches the account's
  const journalActive = state.tracking === 'journal'
    && (state.journal.currency == null || state.journal.currency === state.account.currency);

  const account = journalActive
    ? {
      initial: state.account.initial,
      currency: state.account.currency,
      equity: jrnl.balance,
      dayStart: jrnl.dayStart,
    }
    : {
      initial: state.account.initial,
      currency: state.account.currency,
      equity: state.account.equity ?? state.account.initial,
      dayStart: state.account.dayStart ?? state.account.initial,
    };
  const openRiskCash = journalActive ? jrnl.openRisk : 0;

  const guardOnly = computeGuardrails({
    initial: account.initial, equity: account.equity, dayStart: account.dayStart,
    riskPct: state.riskPct, bufferPct: state.bufferPct, openRiskCash,
  });

  const lotsEl = $('lotsValue');
  const dirChip = $('dirChip');

  const incomplete = entry == null || sl == null;
  let result = null;
  if (!incomplete) {
    result = computePosition({
      symbol: sym, entry, sl, tp,
      riskPct: state.riskPct, account,
      rates: ratesSnapshot(),
      padPrice: state.pads[sym],
      commissionUSDPerLot: state.commissionUSDPerLot,
      bufferPct: state.bufferPct,
      openRiskCash,
    });
  }
  lastSized = result?.ok && result.lots > 0
    ? { result, entry, sl, tp, symbol: sym, currency: account.currency }
    : null;
  updateTakeBtn();

  /* direction chip */
  if (result?.ok) {
    state.lastDir = result.direction;
    dirChip.textContent = result.direction.toUpperCase();
    dirChip.className = `dir-chip show ${result.direction}`;
  } else {
    dirChip.className = 'dir-chip';
  }

  /* hero */
  const setDim = hint => {
    if (lotsEl._raf) cancelAnimationFrame(lotsEl._raf);
    lotsEl._shown = NaN;
    lotsEl.textContent = '—.—';
    lotsEl.className = 'lots-value dim';
    $('heroHint').textContent = hint;
    $('riskCash').textContent = '—'; $('riskSub').innerHTML = '&nbsp;';
    $('rewardCash').textContent = '—'; $('rewardSub').innerHTML = '&nbsp;';
    $('heroFine').textContent = '';
  };

  // A breach outranks everything: it must stay on screen even when the inputs
  // are incomplete or the account is too far gone to size a trade at all.
  const breachBanner = guardOnly.breachedTotal ? 'breachedTotal' : guardOnly.breachedDaily ? 'breachedDaily' : null;

  if (incomplete) {
    setDim('Enter your entry and stop');
    showBanner(breachBanner);
  } else if (!result.ok) {
    if (breachBanner) { setDim('Account breached'); showBanner(breachBanner); }
    else if (result.error === 'sl-equals-entry') { setDim('Stop can’t equal entry'); showBanner(null); }
    else if (result.error === 'missing-rate') { setDim('Missing FX rate'); showBanner('missingRate', result); tryFetchRates(); }
    else { setDim('Check your numbers'); showBanner(null); }
  } else {
    const r = result;
    const w = code => r.warnings.find(x => x.code === code);
    const prevTarget = lotsEl._target;
    lotsEl._target = r.lots;
    lotsEl.className = 'lots-value' + (r.lots === 0 ? ' zero' : '');
    tween(lotsEl, r.lots, v => v.toFixed(2));
    if (prevTarget !== r.lots) {
      const line = $('lotsLine');
      line.classList.remove('pop'); void line.offsetWidth; line.classList.add('pop');
    }

    $('heroHint').textContent =
      `${r.direction === 'long' ? 'Long' : 'Short'} ${spec.label} · stop ${r.stopPips.toFixed(1).replace(/\.0$/, '')} pips`;

    $('riskCash').textContent = fmtMoney(r.actualRiskCash);
    $('riskSub').textContent = r.lots > 0
      ? `${fmtPct(r.actualRiskPct)} of equity · ${w('commission-estimated') ? 'commission est. 1:1' : 'incl. costs'}`
      : 'no position';
    if (tp != null && r.profitCash != null && r.tpValid) {
      $('rewardCash').textContent = fmtMoney(r.profitCash);
      // cash-based ratio so it always matches the two numbers on screen
      const cashRR = r.actualRiskCash > 0 ? r.profitCash / r.actualRiskCash : r.rr;
      $('rewardSub').textContent = `R:R 1 : ${cashRR.toFixed(2).replace(/\.?0+$/, '')}`;
    } else {
      $('rewardCash').textContent = '—';
      $('rewardSub').textContent = tp == null ? 'add a target' : 'target on wrong side';
    }

    const fine = [];
    fine.push(`<span>per pip <b>${fmtMoney(r.pipValueActual, 2)}</b></span>`);
    if (r.marginRequired != null) {
      fine.push(`<span>margin <b>${fmtMoney(r.marginRequired)}</b>${r.marginPctOfEquity != null ? ` (${fmtPct(r.marginPctOfEquity, 0)})` : ''}</span>`);
    }
    fine.push(`<span>1:${r.leverage}</span>`);
    $('heroFine').innerHTML = fine.join('');

    /* banner priority */
    if (w('breached-total')) showBanner('breachedTotal');
    else if (w('breached-daily')) showBanner('breachedDaily');
    else if (w('no-headroom')) showBanner('noHeadroom', w('no-headroom'));
    else if (w('stop-too-wide')) showBanner('stopTooWide', w('stop-too-wide'));
    else if (r.marginCapped) showBanner('marginCapped', r);
    else if (r.capReason) showBanner('cap', r);
    else if (w('tp-wrong-side')) showBanner('tpWrongSide');
    else if (w('high-margin')) showBanner('highMargin');
    else showBanner(null);
  }

  renderMeters(guardOnly, result?.ok ? result.actualRiskCash : 0);
  renderJournal(jrnl, journalActive);

  $('footNote').innerHTML =
    `${RULES.program} · daily loss ${fmtPct(RULES.dailyLossPct)} · max loss ${fmtPct(RULES.maxLossPct)} · buffer ${fmtPct(state.bufferPct)}<br>` +
    `Sizing always rounds down and keeps your buffer clear of both floors. Verify on your The5ers dashboard.`;
}

/* ---------------- trade journal ---------------- */

let lastSized = null;      // the currently displayed valid sizing, if any
let closingId = null;      // trade id showing the custom-close input
let confirmingDeleteId = null;

function updateTakeBtn() {
  const btn = $('takeBtn');
  if (btn.classList.contains('taken')) return;   // mid-confirmation flash
  const ccyMismatch = state.journal.currency && state.journal.currency !== state.account.currency;
  btn.disabled = !lastSized || ccyMismatch;
  btn.textContent = ccyMismatch
    ? `Journal is in ${state.journal.currency} — switch currency back to log trades`
    : 'Take this trade';
}

function takeTrade() {
  if (!lastSized) return;
  const { result: r, entry, sl, tp, symbol, currency } = lastSized;
  state.journal.trades.push({
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    symbol, currency,
    direction: r.direction,
    entry, sl,
    tp: tp != null && Number.isFinite(tp) && tp > 0 && r.tpValid ? tp : null,
    lots: r.lots,
    riskCash: r.actualRiskCash,
    commissionCashPerLot: r.perLotCommission,
    rates: ratesSnapshot(),
    openedAt: Date.now(),
    status: 'open',
  });
  state.journal.currency = state.journal.currency ?? currency;
  save({ now: true });
  const btn = $('takeBtn');
  btn.classList.add('taken');
  btn.textContent = '✓ Logged to journal';
  setTimeout(() => { btn.classList.remove('taken'); updateTakeBtn(); }, 1400);
  render();
}

function resolveTrade(id, outcome, exitPrice = null) {
  const t = state.journal.trades.find(x => x.id === id);
  if (!t || t.status !== 'open') return;
  const pnl = resolvePnl(t, outcome, exitPrice);
  if (pnl == null) return;
  t.status = outcome;
  t.closedAt = Date.now();
  if (outcome === 'closed') t.exitPrice = exitPrice;
  t.pnlCash = pnl;
  closingId = null;
  save({ now: true }); render();
}

function deleteTrade(id) {
  state.journal.trades = state.journal.trades.filter(t => t.id !== id);
  if (state.journal.trades.length === 0) state.journal.currency = null;
  confirmingDeleteId = null;
  closingId = null;
  save({ now: true }); render();
}

const fmtWhen = ts => (Number.isFinite(ts)
  ? new Date(ts).toLocaleString('en-GB', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
  : '—');

function renderJournal(jrnl, journalActive) {
  const jCcy = state.journal.currency ?? state.account.currency;
  const fmtJ = (x, d = null, signed = false) => fmtMoneyIn(jCcy, x, d, signed);
  const spec = s => SYMBOLS[s] || { priceDecimals: 2 };

  $('jrnlMode').textContent = state.tracking === 'journal'
    ? (journalActive ? 'driving the sizing above' : `in ${jCcy} — currency mismatch`)
    : 'display only · manual mode';

  const balEl = $('jrnlBalance');
  balEl.textContent = fmtJ(jrnl.balance);
  balEl.className = 's-value' + (jrnl.realizedTotal > 0 ? ' pos' : jrnl.realizedTotal < 0 ? ' neg' : '');
  const pnlEl = $('jrnlPnl');
  pnlEl.textContent = fmtJ(jrnl.realizedTotal, null, true);
  pnlEl.className = 's-value' + (jrnl.realizedTotal > 0 ? ' pos' : jrnl.realizedTotal < 0 ? ' neg' : '');
  $('jrnlCount').textContent = String(jrnl.tradeCount);
  $('jrnlWl').textContent = jrnl.wins + jrnl.losses > 0
    ? `${jrnl.wins}W · ${jrnl.losses}L${jrnl.openCount ? ` · ${jrnl.openCount} open` : ''}`
    : (jrnl.openCount ? `${jrnl.openCount} open` : ' ');

  $('jrnlStepVal').textContent = `${Math.round(jrnl.stepProgress * 100)}%`;
  const stepFill = $('jrnlStepFill');
  stepFill.style.width = `${jrnl.stepProgress * 100}%`;
  stepFill.className = 'meter-fill ' + (jrnl.realizedTotal < 0 ? 'warn' : 'ok');
  $('jrnlDays').textContent =
    `profitable days ${Math.min(jrnl.profitableDays, RULES.minProfitableDays)}/${RULES.minProfitableDays}` +
    ` (≥ ${fmtJ(RULES.profitableDayPct * state.account.initial)}) · target ${fmtJ(RULES.targets.step1 * state.account.initial)}`;

  const jb = $('jrnlBanner');
  if (jrnl.breaches.length) {
    const b = jrnl.breaches[0];
    jb.className = 'banner show bad';
    $('jrnlBannerText').innerHTML =
      `<b>This account would have breached.</b> On ${b.day} equity hit ${fmtJ(b.equity)}, below the ${b.kind === 'daily' ? 'daily-loss' : 'max-loss'} floor of ${fmtJ(b.floor)}. On the real challenge that ends the account.`;
  } else {
    jb.className = 'banner';
  }

  const list = $('jrnlList');
  const rows = [...state.journal.trades].sort((a, b) => b.openedAt - a.openedAt);
  $('jrnlEmpty').style.display = rows.length ? 'none' : '';
  list.innerHTML = rows.map(t => {
    const d = spec(t.symbol).priceDecimals;
    const head =
      `<b>${t.symbol}</b><span class="jr-dir ${t.direction}">${t.direction.toUpperCase()}</span>` +
      `<span>${t.lots.toFixed(2)} @ ${t.entry.toFixed(d)}</span>`;
    if (t.status === 'open') {
      const closeUI = closingId === t.id
        ? `<input class="jr-close-input" id="close-in-${t.id}" type="text" inputmode="decimal" placeholder="exit price" autocomplete="off">` +
          `<button class="jr-btn win" data-act="close-ok" data-id="${t.id}">OK</button>` +
          `<button class="jr-btn" data-act="close-cancel" data-id="${t.id}">Cancel</button>`
        : (t.tp != null ? `<button class="jr-btn win" data-act="won" data-id="${t.id}">🎯 Target hit</button>` : '') +
          `<button class="jr-btn loss" data-act="lost" data-id="${t.id}">Stopped out</button>` +
          `<button class="jr-btn" data-act="close" data-id="${t.id}">Close @…</button>`;
      return `<li class="jrnl-row">
        <div class="jr-main">${head}<span class="jr-status open">OPEN</span></div>
        <div class="jr-sub">SL ${t.sl.toFixed(d)}${t.tp != null ? ` · TP ${t.tp.toFixed(d)}` : ''} · risk ${fmtJ(t.riskCash)} · ${fmtWhen(t.openedAt)}</div>
        <div class="jr-actions">${closeUI}<button class="jr-btn del" data-act="del" data-id="${t.id}">${confirmingDeleteId === t.id ? 'Sure?' : '✕'}</button></div>
      </li>`;
    }
    const cls = t.pnlCash > 0 ? 'pos' : 'neg';
    const px = v => (Number.isFinite(v) ? v.toFixed(d) : '—');
    const how = t.status === 'won' ? `target ${px(t.tp)}`
      : t.status === 'lost' ? `stopped ${px(t.sl)}`
      : `closed ${px(t.exitPrice)}`;
    return `<li class="jrnl-row">
      <div class="jr-main">${head}<span class="jr-pnl ${cls}">${fmtJ(t.pnlCash, null, true)}</span></div>
      <div class="jr-sub">${how} · ${fmtWhen(t.closedAt)}<button class="jr-btn del" data-act="del" data-id="${t.id}" style="float:right;padding:2px 8px">${confirmingDeleteId === t.id ? 'Sure?' : '✕'}</button></div>
    </li>`;
  }).join('');
}

function bindJournal() {
  $('takeBtn').addEventListener('click', takeTrade);
  $('jrnlList').addEventListener('click', e => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const { act, id } = btn.dataset;
    if (act === 'won' || act === 'lost') { resolveTrade(id, act); return; }
    if (act === 'close') { closingId = id; confirmingDeleteId = null; render(); $(`close-in-${id}`)?.focus(); return; }
    if (act === 'close-cancel') { closingId = null; render(); return; }
    if (act === 'close-ok') {
      const input = $(`close-in-${id}`);
      const v = parseNum(input?.value ?? '');
      const t = state.journal.trades.find(x => x.id === id);
      // Reject anything that isn't a plausible price for this instrument
      // instead of silently swallowing it.
      const sane = v != null && v > 0 && t && v > t.entry / 5 && v < t.entry * 5;
      if (!sane) {
        if (input) {
          input.style.borderColor = 'rgba(248,113,113,0.7)';
          input.placeholder = 'price near ' + t?.entry;
          input.value = '';
          input.focus();
        }
        return;
      }
      resolveTrade(id, 'closed', v);
      return;
    }
    if (act === 'del') {
      if (confirmingDeleteId === id) deleteTrade(id);
      else { confirmingDeleteId = id; render(); setTimeout(() => { if (confirmingDeleteId === id) { confirmingDeleteId = null; render(); } }, 2500); }
    }
  });
}

/* ---------------- FX rates ---------------- */

const RATE_SOURCES = [
  { url: 'https://api.frankfurter.dev/v1/latest?base=USD&symbols=JPY,GBP,EUR,CAD,AUD', pick: d => d.rates },
  { url: 'https://api.frankfurter.app/latest?from=USD&to=JPY,GBP,EUR,CAD,AUD', pick: d => d.rates },
  { url: 'https://open.er-api.com/v6/latest/USD', pick: d => d.rates },
];

/** USD-based quotes → the pair conventions the graph expects. */
function ratesFromUSDBase(q) {
  const inv = v => (Number.isFinite(v) && v > 0 ? 1 / v : null);
  const dp = (v, n) => (Number.isFinite(v) && v > 0 ? Math.round(v * 10 ** n) / 10 ** n : null);
  return {
    USDJPY: dp(q.JPY, 3),
    GBPUSD: dp(inv(q.GBP), 5),
    EURUSD: dp(inv(q.EUR), 5),
    USDCAD: dp(q.CAD, 5),
    AUDUSD: dp(inv(q.AUD), 5),
  };
}

let fetching = false;
async function fetchRates(force = false) {
  if (fetching) return false;
  const age = state.rates.ts ? Date.now() - state.rates.ts : Infinity;
  const have = RATE_PAIRS.every(p => Number.isFinite(state.rates[p.key]) && state.rates[p.key] > 0);
  if (!force && have && age < 6 * 3600e3) return true;
  if (!force && have && state.rates.source === 'manual') return true; // never clobber manual rates silently
  if (!navigator.onLine) return false;
  fetching = true;
  try {
    for (const src of RATE_SOURCES) {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 6000);
        const res = await fetch(src.url, { signal: ctrl.signal });
        clearTimeout(t);
        if (!res.ok) continue;
        const quotes = src.pick(await res.json());
        if (!quotes) continue;
        const mapped = ratesFromUSDBase(quotes);
        if (RATE_PAIRS.some(p => mapped[p.key] == null)) continue;
        state.rates = { ...mapped, ts: Date.now(), source: 'live' };
        save();
        syncRateFields();
        render();
        return true;
      } catch { /* try next source */ }
    }
    return false;
  } finally { fetching = false; }
}

let fetchQueued = false;
function tryFetchRates() {
  if (fetchQueued) return;
  fetchQueued = true;
  fetchRates().finally(() => setTimeout(() => { fetchQueued = false; }, 30000));
}

function buildRateRows() {
  $('rateCard').innerHTML = RATE_PAIRS.map(p => `
    <div class="set-row">
      <label>${p.label}</label>
      <input type="text" inputmode="decimal" id="set-rate-${p.key}" aria-label="${p.key} rate">
    </div>`).join('');
}

function syncRateFields() {
  const active = document.activeElement;
  for (const p of RATE_PAIRS) {
    const el = $(`set-rate-${p.key}`);
    if (el && active !== el) el.value = state.rates[p.key] ?? '';
  }
  const note = $('rateNote');
  if (state.rates.ts) {
    const mins = Math.round((Date.now() - state.rates.ts) / 60000);
    const when = mins < 2 ? 'just now' : mins < 120 ? `${mins} min ago` : `${Math.round(mins / 60)} h ago`;
    note.textContent = state.rates.source === 'manual'
      ? `Manual rates · set ${when}. Rates only convert into your account currency; a pair that prices its own cross uses the trade's own prices for that leg.`
      : `Live reference rates · updated ${when}. Rates only convert into your account currency; a pair that prices its own cross uses the trade's own prices for that leg.`;
  } else {
    note.textContent = 'No rates yet — refresh online or type them in. Rates only convert JPY/USD amounts into your account currency; small deviations barely move the lot size.';
  }
}

/* ---------------- settings sheet ---------------- */

function syncTrackUI() {
  syncMiniSegByData('trackSeg', 'track', state.tracking);
  const jrnl = computeJournal(state.journal.trades, state.account.initial, Date.now());
  const active = state.tracking === 'journal'
    && (state.journal.currency == null || state.journal.currency === state.account.currency);
  const vals = [
    ['set-equity', active ? jrnl.balance : state.account.equity],
    ['set-daystart', active ? jrnl.dayStart : state.account.dayStart],
  ];
  for (const [id, val] of vals) {
    const input = $(id);
    input.closest('.set-row').classList.toggle('locked', active);
    if (document.activeElement !== input) input.value = String(Math.round(val * 100) / 100);
  }
}

/** Push current state into every settings control. */
function syncSettingsFields() {
  const set = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = String(v); };
  set('set-initial', state.account.initial);
  set('set-equity', state.account.equity);
  set('set-daystart', state.account.dayStart);
  set('set-comm', state.commissionUSDPerLot);
  syncMiniSegByData('ccySeg', 'ccy', state.account.currency);
  syncMiniSegByData('bufSeg', 'buf', String(state.bufferPct * 100));
  syncTrackUI();
  syncRateFields();
}

function openSheet() {
  syncRateFields();
  syncTrackUI();
  $('set-pad').value = String(state.pads[state.symbol]);
  $('sheet').classList.add('show');
  $('backdrop').classList.add('show');
}
function closeSheet() {
  $('sheet').classList.remove('show');
  $('backdrop').classList.remove('show');
  render();
}

function bindSettings() {
  $('gearBtn').addEventListener('click', openSheet);
  $('backdrop').addEventListener('click', closeSheet);
  $('doneBtn').addEventListener('click', closeSheet);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });

  // Each field writes valid values into state on input, and on blur snaps its
  // display back to the effective state so garbage can never linger on screen.
  const bindNum = (id, fn, getter) => {
    const el = $(id);
    el.addEventListener('input', e => { fn(parseNum(e.target.value)); save(); render(); });
    el.addEventListener('blur', () => { const v = getter(); el.value = v == null ? '' : String(v); });
  };
  bindNum('set-initial', v => {
    if (v != null && v > 0) {
      const wasFresh = state.account.equity === state.account.initial
        && state.account.dayStart === state.account.initial;
      state.account.initial = v;
      if (wasFresh) {
        state.account.equity = v;
        state.account.dayStart = v;
        $('set-equity').value = String(v);
        $('set-daystart').value = String(v);
      }
    }
  }, () => state.account.initial);
  bindNum('set-equity', v => { if (v != null && v > 0) state.account.equity = v; }, () => state.account.equity);
  bindNum('set-daystart', v => { if (v != null && v > 0) state.account.dayStart = v; }, () => state.account.dayStart);
  bindNum('set-pad', v => { if (v != null && v >= 0) state.pads[state.symbol] = v; }, () => state.pads[state.symbol]);
  bindNum('set-comm', v => { if (v != null && v >= 0) state.commissionUSDPerLot = v; }, () => state.commissionUSDPerLot);
  for (const p of RATE_PAIRS) {
    bindNum(`set-rate-${p.key}`, v => {
      if (v != null && v > 0) { state.rates[p.key] = v; state.rates.ts = Date.now(); state.rates.source = 'manual'; }
    }, () => state.rates[p.key]);
  }

  let resetArmed = false;
  $('resetAccount').addEventListener('click', e => {
    if (!resetArmed && state.journal.trades.length) {
      resetArmed = true;
      e.target.textContent = 'This clears all journal trades — tap again to confirm';
      setTimeout(() => { resetArmed = false; e.target.textContent = 'Reset account & clear journal'; }, 3000);
      return;
    }
    resetArmed = false;
    e.target.textContent = 'Reset account & clear journal';
    state.journal.trades = [];
    state.journal.currency = null;
    state.account.equity = state.account.initial;
    state.account.dayStart = state.account.initial;
    save(); syncTrackUI(); render();
  });

  $('trackSeg').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    state.tracking = b.dataset.track;
    save(); syncTrackUI(); render();
  });

  $('ccySeg').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    state.account.currency = b.dataset.ccy;
    syncMiniSeg('ccySeg', b);
    save(); render();
  });
  $('bufSeg').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    state.bufferPct = parseFloat(b.dataset.buf) / 100;
    syncMiniSeg('bufSeg', b);
    save(); render();
  });

  $('rateRefresh').addEventListener('click', () => fetchRates(true));

  syncSettingsFields();

  /* rules list */
  $('rulesList').innerHTML = [
    `Daily loss: ${fmtPct(RULES.dailyLossPct)} of the day-start value (the <b>higher</b> of balance or equity at 00:00 server time, GMT+3 summer). Equity-based, floating losses count — breach terminates the account`,
    `Maximum loss: ${fmtPct(RULES.maxLossPct)} of initial balance — static equity floor, never trails`,
    `Targets (Classic): Step 1 ${fmtPct(RULES.targets.step1)} · Step 2 ${fmtPct(RULES.targets.step2)} · min ${RULES.minProfitableDays} profitable days (closed P&amp;L ≥ ${fmtPct(RULES.profitableDayPct)} of initial)`,
    `Stop loss: suggested, not required — but if used it must be a visible order (no hidden/stealth SL)`,
    `Leverage 1:${RULES.leverage.fx} FX · 1:${RULES.leverage.metals} gold (metals cut to 1:25 in Mar 2026 — margin can cap gold lots)`,
    `News: ${RULES.newsRule}`,
    `No lot-size or exposure caps · overnight &amp; weekend holding allowed · no consistency rule`,
    `30 days without a trade expires the account · no HFT/tick-scalping · no cross-account hedging or third-party copy trading`,
  ].map(t => `<li><span class="dot">◆</span><span>${t}</span></li>`).join('');
}

function syncMiniSeg(segId, activeBtn) {
  document.querySelectorAll(`#${segId} button`).forEach(b => b.classList.toggle('on', b === activeBtn));
}
function syncMiniSegByData(segId, attr, value) {
  document.querySelectorAll(`#${segId} button`).forEach(b =>
    b.classList.toggle('on', b.dataset[attr] === value || parseFloat(b.dataset[attr]) === parseFloat(value)));
}

/* ---------------- trade inputs ---------------- */

function bindTradeInputs() {
  for (const k of ['entry', 'sl', 'tp']) {
    const el = $('in-' + k);
    const row = $('f-' + k);
    el.addEventListener('input', () => {
      state.inputs[state.symbol][k] = el.value;
      save(); render();
    });
    el.addEventListener('focus', () => { row.classList.add('focus'); el.select(); });
    el.addEventListener('blur', () => row.classList.remove('focus'));
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        const order = ['in-entry', 'in-sl', 'in-tp'];
        const next = order[order.indexOf(el.id) + 1];
        next ? $(next).focus() : el.blur();
      }
    });
  }

  $('symbolSeg').addEventListener('click', e => {
    const b = e.target.closest('button[data-symbol]'); if (!b) return;
    setSymbol(b.dataset.symbol);
  });

  $('riskChips').addEventListener('click', e => {
    const c = e.target.closest('.chip'); if (!c) return;
    setRisk(parseFloat(c.dataset.risk));
  });
  $('riskSlider').addEventListener('input', e => setRisk(parseFloat(e.target.value), { fromSlider: true }));
}

/* ---------------- starfield ---------------- */

function startStars() {
  const canvas = $('stars');
  const ctx = canvas.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let stars = [], w = 0, h = 0, dpr = 1, raf = null, last = 0;

  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    w = innerWidth; h = innerHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.min(150, Math.round((w * h) / 6500));
    stars = Array.from({ length: count }, () => ({
      x: Math.random() * w, y: Math.random() * h,
      r: 0.4 + Math.random() * 1.1,
      ph: Math.random() * Math.PI * 2,
      tw: 0.4 + Math.random() * 1.2,
      sp: 0.06 + Math.random() * 0.22,
      hue: Math.random() < 0.75 ? null : (Math.random() < 0.5 ? '167,139,250' : '103,232,249'),
    }));
  }

  function draw(t) {
    ctx.clearRect(0, 0, w, h);
    for (const s of stars) {
      const a = reduced ? 0.6 : 0.35 + 0.4 * (0.5 + 0.5 * Math.sin(s.ph + t * 0.001 * s.tw));
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${s.hue || '226,229,255'},${a.toFixed(3)})`;
      ctx.fill();
    }
  }

  function frame(t) {
    raf = requestAnimationFrame(frame);
    if (t - last < 33) return;   // ~30fps is plenty
    const dt = Math.min(100, t - last) / 1000;
    last = t;
    for (const s of stars) {
      s.y += s.sp * dt * 10; s.x += s.sp * dt * 3;
      if (s.y > h + 2) { s.y = -2; s.x = Math.random() * w; }
      if (s.x > w + 2) s.x = -2;
    }
    draw(t);
  }

  resize();
  addEventListener('resize', () => { resize(); if (reduced) draw(0); });
  if (reduced) { draw(0); return; }
  raf = requestAnimationFrame(frame);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = null; }
    else if (!raf) { last = 0; raf = requestAnimationFrame(frame); }
  });
}

/* ---------------- boot ---------------- */

buildSymbolButtons();
buildRateRows();
bindTradeInputs();
bindSettings();
bindJournal();
addEventListener('resize', () => movePuck(false));
setRisk(state.riskPct * 100);
setSymbol(state.symbol, false);
startStars();
tryFetchRates();
addEventListener('online', tryFetchRates);

if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
  addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}
