import { init, getLocale, getSupported, setLocale } from '/static/js/i18n.js';

const STORAGE_KEY = 'atenea-ui-language';
const SERVER_PREF_KEY = 'ui_language';
const BUTTON_ID = 'lang-toggle';
const LABEL_ID = 'lang-toggle-label';

function nextLocale(current, supported) {
  if (!supported || supported.length === 0) return current;
  const i = supported.indexOf(current);
  return supported[(i + 1) % supported.length];
}

function paint(locale) {
  const btn = document.getElementById(BUTTON_ID);
  const lbl = document.getElementById(LABEL_ID);
  if (!btn || !lbl) return;
  lbl.textContent = locale.toUpperCase();
  btn.setAttribute('data-current-locale', locale);
}

async function fetchServerLocale() {
  try {
    const r = await fetch('/api/prefs/' + SERVER_PREF_KEY, { credentials: 'same-origin' });
    if (!r.ok) return null;
    const j = await r.json();
    return j && j.value ? String(j.value) : null;
  } catch (e) { return null; }
}

async function saveServerLocale(locale) {
  try {
    await fetch('/api/prefs/' + SERVER_PREF_KEY, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: locale }),
    });
  } catch (e) { /* best-effort */ }
}

async function wire() {
  const btn = document.getElementById(BUTTON_ID);
  if (!btn) return;
  const serverLocale = await fetchServerLocale();
  await init({ locale: serverLocale || undefined });
  const locale = getLocale();
  paint(locale);
  btn.addEventListener('click', async () => {
    const cur = getLocale();
    const supported = getSupported();
    const next = nextLocale(cur, supported);
    await setLocale(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch (e) {}
    saveServerLocale(next);
    paint(next);
  });
  document.addEventListener('localechange', (ev) => {
    if (ev && ev.detail && ev.detail.locale) paint(ev.detail.locale);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', wire, { once: true });
} else {
  wire();
}
