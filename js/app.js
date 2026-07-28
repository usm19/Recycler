import { computePosition, computeGuardrails } from './calc.js';
import { RULES, SYMBOLS, DEFAULTS } from './rules.js';

/* ---------------- state ---------------- */

const STORE_KEY = 'nebula-v1';

const defaultState = () => ({
  symbol: 'GBPJPY',
  inputs: {
    GBPJPY: { entry: '', sl: '', tp: '' },
    XAUUSD: { entry: '', sl: '', tp: '' },
    USDJPY: { entry: '', sl: '', tp: '' },
  },
  riskPct: DEFAULTS.riskPct,
  account: {
    initial: DEFAULTS.accountSize,
    currency: DEFAULTS.accountCurrency,
    equity: DEFAULTS.accountSize,
    todayPnl: 0,
  },
  bufferPct: DEFAULTS.bufferPct,
  pads: Object.fromEntries(Object.entries(SYMBOLS).map(([k, v]) => [k, v.defaultPadPrice])),
  commissionUSDPerLot: RULES.commissionUSDPerLot.fx,
  rates: { USDJPY: null, GBPUSD: null, ts: null, source: null },
});

function loadState() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return defaultState();
    const saved = JSON.parse(raw);
    const base = defaultState();
    return {
      ...base, ...saved,
      inputs: { ...base.inputs, ...(saved.inputs || {}) },
      account: { ...base.account, ...(saved.account || {}) },
      pads: { ...base.pads, ...(saved.pads || {}) },
      rates: { ...base.rates, ...(saved.rates || {}) },
    };
  } catch { return defaultState(); }
}

const state = loadState();
let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch { /* full/private mode */ }
  }, 150);
}

/* ---------------- helpers ---------------- */

const $ = id => document.getElementById(id);

function parseNum(str) {
  if (typeof str !== 'string') return null;
  let s = str.trim().replace(/\s/g, '').replace(/−/g, '-');
  if (s.includes(',') && s.includes('.')) s = s.replace(/,/g, '');
  else s = s.replace(/,/g, '.');
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : null;
}

function ccySymbol() { return state.account.currency === 'GBP' ? '£' : '$'; }

function fmtMoney(x, decimals = null) {
  if (x == null || !Number.isFinite(x)) return '—';
  const d = decimals ?? (Math.abs(x) >= 100 ? 0 : 2);
  const s = Math.abs(x).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
  return (x < 0 ? '−' : '') + ccySymbol() + s;
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

const SYMBOL_ORDER = ['GBPJPY', 'XAUUSD', 'USDJPY'];
const PLACEHOLDERS = {
  GBPJPY: { entry: '195.500', sl: '195.000', tp: '196.500' },
  XAUUSD: { entry: '3350.00', sl: '3340.00', tp: '3370.00' },
  USDJPY: { entry: '148.500', sl: '148.000', tp: '149.500' },
};

function setSymbol(sym, animate = true) {
  state.symbol = sym;
  const idx = SYMBOL_ORDER.indexOf(sym);
  const puck = $('segPuck');
  if (!animate) puck.style.transition = 'none';
  puck.style.transform = `translateX(${idx * 100}%)`;
  if (!animate) requestAnimationFrame(() => { puck.style.transition = ''; });
  document.querySelectorAll('#symbolSeg button').forEach(b =>
    b.classList.toggle('on', b.dataset.symbol === sym));
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
  breachedDaily: () => ['bad', '✕', `<b>Daily limit hit.</b> Equity is at or below today's ${fmtPct(RULES.dailyLossPct)} floor. No more trades today.`],
  missingRate: m => ['warn', '↺', `<b>Need the ${m === 'GBPUSD' ? 'GBP/USD' : 'USD/JPY'} rate</b> to convert this pair. Tap ⚙ → FX rates (or refresh online).`],
  stopTooWide: w => ['warn', '⚠', `<b>Stop too wide.</b> Even 0.01 lots would risk ${fmtMoney(w.minLotRiskCash)}${w.minLotRiskPct ? ` (${fmtPct(w.minLotRiskPct)})` : ''} — over your safe limit. Tighten the stop or accept the minimum manually.`],
  cap: (r) => ['warn', '⛨', `<b>Risk capped at ${fmtMoney(r.allowedRiskCash)}</b> (asked ${fmtMoney(r.requestedRiskCash)}) to keep your ${fmtPct(state.bufferPct)} buffer before the ${r.capReason === 'daily' ? 'daily-loss' : 'max-loss'} floor.`],
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
  const dailyAllow = guard.dayStart - guard.dailyFloor;
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
    const after = it.room - (tradeRisk || 0);
    $(it.sub).textContent = tradeRisk > 0
      ? `floor ${fmtMoney(it.floor)} · ${fmtMoney(Math.max(0, after))} room if this stop hits`
      : `floor ${fmtMoney(it.floor)}`;
  }
}

function render() {
  const sym = state.symbol;
  const spec = SYMBOLS[sym];
  const vals = state.inputs[sym];
  const entry = parseNum(vals.entry);
  const sl = parseNum(vals.sl);
  const tp = parseNum(vals.tp);

  const account = {
    initial: state.account.initial,
    currency: state.account.currency,
    equity: state.account.equity ?? state.account.initial,
    todayPnl: state.account.todayPnl || 0,
  };

  const guardOnly = computeGuardrails({
    initial: account.initial, equity: account.equity, todayPnl: account.todayPnl,
    riskPct: state.riskPct, bufferPct: state.bufferPct,
  });

  const lotsEl = $('lotsValue');
  const dirChip = $('dirChip');

  const incomplete = entry == null || sl == null;
  let result = null;
  if (!incomplete) {
    result = computePosition({
      symbol: sym, entry, sl, tp,
      riskPct: state.riskPct, account,
      rates: { USDJPY: state.rates.USDJPY, GBPUSD: state.rates.GBPUSD },
      padPrice: state.pads[sym],
      commissionUSDPerLot: state.commissionUSDPerLot,
      bufferPct: state.bufferPct,
    });
  }

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

  if (incomplete) {
    setDim('Enter your entry and stop');
    showBanner(guardOnly.breachedTotal ? 'breachedTotal' : guardOnly.breachedDaily ? 'breachedDaily' : null);
  } else if (!result.ok) {
    if (result.error === 'sl-equals-entry') { setDim('Stop can’t equal entry'); showBanner(null); }
    else if (result.error === 'missing-rate') { setDim('Missing FX rate'); showBanner('missingRate', result.missingRate); tryFetchRates(); }
    else { setDim('Check your numbers'); showBanner(null); }
  } else {
    const r = result;
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
      ? `${fmtPct(r.actualRiskPct)} of equity · incl. costs`
      : 'no position';
    if (tp != null && r.profitCash != null && r.tpValid) {
      $('rewardCash').textContent = fmtMoney(r.profitCash);
      $('rewardSub').textContent = `R:R 1 : ${r.rr.toFixed(2).replace(/0$/, '')}`;
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
    const w = code => r.warnings.find(x => x.code === code);
    if (w('breached-total')) showBanner('breachedTotal');
    else if (w('breached-daily')) showBanner('breachedDaily');
    else if (w('stop-too-wide')) showBanner('stopTooWide', w('stop-too-wide'));
    else if (r.capReason) showBanner('cap', r);
    else if (w('tp-wrong-side')) showBanner('tpWrongSide');
    else if (w('high-margin')) showBanner('highMargin');
    else showBanner(null);
  }

  renderMeters(guardOnly, result?.ok ? result.actualRiskCash : 0);

  $('footNote').innerHTML =
    `${RULES.program} · daily loss ${fmtPct(RULES.dailyLossPct)} · max loss ${fmtPct(RULES.maxLossPct)} · buffer ${fmtPct(state.bufferPct)}<br>` +
    `Sizing always rounds down and keeps your buffer clear of both floors. Verify on your The5ers dashboard.`;
}

/* ---------------- FX rates ---------------- */

const RATE_SOURCES = [
  { url: 'https://api.frankfurter.dev/v1/latest?base=USD&symbols=JPY,GBP', pick: d => d.rates },
  { url: 'https://api.frankfurter.app/latest?from=USD&to=JPY,GBP', pick: d => d.rates },
  { url: 'https://open.er-api.com/v6/latest/USD', pick: d => d.rates },
];

let fetching = false;
async function fetchRates(force = false) {
  if (fetching) return false;
  const age = state.rates.ts ? Date.now() - state.rates.ts : Infinity;
  const have = state.rates.USDJPY && state.rates.GBPUSD;
  if (!force && have && age < 6 * 3600e3) return true;
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
        const rates = src.pick(await res.json());
        if (!rates?.JPY || !rates?.GBP) continue;
        state.rates = {
          USDJPY: Math.round(rates.JPY * 1000) / 1000,
          GBPUSD: Math.round((1 / rates.GBP) * 100000) / 100000,
          ts: Date.now(), source: 'live',
        };
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

function syncRateFields() {
  $('set-usdjpy').value = state.rates.USDJPY ?? '';
  $('set-gbpusd').value = state.rates.GBPUSD ?? '';
  const note = $('rateNote');
  if (state.rates.ts) {
    const mins = Math.round((Date.now() - state.rates.ts) / 60000);
    const when = mins < 2 ? 'just now' : mins < 120 ? `${mins} min ago` : `${Math.round(mins / 60)} h ago`;
    note.textContent = state.rates.source === 'manual'
      ? `Manual rates · set ${when}. GBPJPY trades use your entry price directly — exact.`
      : `Live reference rates · updated ${when}. GBPJPY trades use your entry price directly — exact.`;
  } else {
    note.textContent = 'No rates yet — refresh online or type them in. Rates only convert JPY/USD amounts into your account currency; small deviations barely move the lot size.';
  }
}

/* ---------------- settings sheet ---------------- */

function openSheet() {
  syncRateFields();
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

  const bindNum = (id, fn) => {
    $(id).addEventListener('input', e => { fn(parseNum(e.target.value)); save(); render(); });
  };
  bindNum('set-initial', v => {
    if (v != null && v > 0) {
      const wasFresh = state.account.equity === state.account.initial;
      state.account.initial = v;
      if (wasFresh) { state.account.equity = v; $('set-equity').value = String(v); }
    }
  });
  bindNum('set-equity', v => { if (v != null && v > 0) state.account.equity = v; });
  bindNum('set-pnl', v => { state.account.todayPnl = v ?? 0; });
  bindNum('set-pad', v => { if (v != null && v >= 0) state.pads[state.symbol] = v; });
  bindNum('set-comm', v => { if (v != null && v >= 0) state.commissionUSDPerLot = v; });
  bindNum('set-usdjpy', v => { if (v != null && v > 0) { state.rates.USDJPY = v; state.rates.ts = Date.now(); state.rates.source = 'manual'; } });
  bindNum('set-gbpusd', v => { if (v != null && v > 0) { state.rates.GBPUSD = v; state.rates.ts = Date.now(); state.rates.source = 'manual'; } });

  $('resetAccount').addEventListener('click', () => {
    state.account.equity = state.account.initial;
    state.account.todayPnl = 0;
    $('set-equity').value = String(state.account.equity);
    $('set-pnl').value = '0';
    save(); render();
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

  /* initial values */
  $('set-initial').value = String(state.account.initial);
  $('set-equity').value = String(state.account.equity);
  $('set-pnl').value = String(state.account.todayPnl);
  $('set-comm').value = String(state.commissionUSDPerLot);
  syncMiniSegByData('ccySeg', 'ccy', state.account.currency);
  syncMiniSegByData('bufSeg', 'buf', String(state.bufferPct * 100));
  syncRateFields();

  /* rules list */
  $('rulesList').innerHTML = [
    `Daily loss limit: ${fmtPct(RULES.dailyLossPct)} of starting balance, measured from the day-start value — resets at midnight server time`,
    `Maximum loss: ${fmtPct(RULES.maxLossPct)} of initial balance (${RULES.maxLossStatic ? 'static floor' : 'trailing'})`,
    `Profit targets: Step 1 ${fmtPct(RULES.targets.step1)} · Step 2 ${fmtPct(RULES.targets.step2)}`,
    `Stop loss ${RULES.stopLossMandatory ? 'required on every trade' : 'recommended'}`,
    `Leverage 1:${RULES.leverage.fx} FX · 1:${RULES.leverage.metals} metals`,
    `Min ${RULES.minProfitableDays} profitable days (≥ ${fmtPct(RULES.profitableDayPct)}) per step`,
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
  addEventListener('resize', resize);
  if (reduced) { draw(0); return; }
  raf = requestAnimationFrame(frame);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = null; }
    else if (!raf) { last = 0; raf = requestAnimationFrame(frame); }
  });
}

/* ---------------- boot ---------------- */

bindTradeInputs();
bindSettings();
setRisk(state.riskPct * 100);
setSymbol(state.symbol, false);
startStars();
tryFetchRates();
addEventListener('online', tryFetchRates);

if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
  addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}
