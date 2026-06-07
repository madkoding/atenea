// static/js/i18n.js — Lightweight i18n runtime for the Spanish fork.
// Loads /static/js/locales/{lang}.json, exposes t() for JS strings, and
// auto-applies data-i18n* attributes to the DOM. Default language: en.
// Persists selection in localStorage so the choice survives reloads.

const STORAGE_KEY = 'odysseus-ui-language';
const SUPPORTED = ['en', 'es'];
let _locale = 'en';
let _messages = {};
let _pluralRules = null;

function _readStored() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return SUPPORTED.includes(v) ? v : null;
  } catch { return null; }
}

function _store(v) {
  try { localStorage.setItem(STORAGE_KEY, v); } catch {}
}

async function _load(locale) {
  const target = SUPPORTED.includes(locale) ? locale : 'en';
  try {
    const res = await fetch(`/static/js/locales/${target}.json`, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _messages = await res.json();
    _locale = target;
    if (typeof Intl.PluralRules === 'function') {
      _pluralRules = new Intl.PluralRules(_locale === 'es' ? 'es-ES' : 'en-US');
    } else {
      _pluralRules = { select: () => 'other' };
    }
    _store(_locale);
    return true;
  } catch (e) {
    console.error('[i18n] failed to load', target, e);
    if (target !== 'en') {
      // Try English as a last resort
      try {
        const r = await fetch('/static/js/locales/en.json', { cache: 'no-cache' });
        if (r.ok) {
          _messages = await r.json();
          _locale = 'en';
          _store('en');
          return true;
        }
      } catch {}
    }
    return false;
  }
}

function _interpolate(msg, params) {
  if (!params) return msg;
  return msg.replace(/\{(\w+)\}/g, (_, k) => (k in params ? String(params[k]) : `{${k}}`));
}

function t(key, params) {
  let msg = _messages[key];
  if (msg === undefined) return key;
  if (params && typeof msg === 'object' && msg._plural) {
    const cat = _pluralRules.select(params.n || 0);
    msg = msg[cat] || msg.other || key;
  } else if (typeof msg === 'object') {
    msg = msg.other || msg.one || Object.values(msg)[0] || key;
  }
  return _interpolate(msg, params);
}

function tn(key, n, params) {
  return t(key, { ...(params || {}), n });
}

function getLocale() { return _locale; }
function getSupported() { return SUPPORTED.slice(); }

function applyAll(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-i18n]').forEach((el) => {
    const key = el.getAttribute('data-i18n');
    const v = t(key);
    if (v !== key) el.textContent = v;
  });
  scope.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
    const key = el.getAttribute('data-i18n-placeholder');
    const v = t(key);
    if (v !== key) el.setAttribute('placeholder', v);
  });
  scope.querySelectorAll('[data-i18n-aria-label]').forEach((el) => {
    const key = el.getAttribute('data-i18n-aria-label');
    const v = t(key);
    if (v !== key) el.setAttribute('aria-label', v);
  });
  scope.querySelectorAll('[data-i18n-title]').forEach((el) => {
    const key = el.getAttribute('data-i18n-title');
    const v = t(key);
    if (v !== key) el.setAttribute('title', v);
  });
  scope.querySelectorAll('[data-i18n-value]').forEach((el) => {
    const key = el.getAttribute('data-i18n-value');
    const v = t(key);
    if (v !== key) el.setAttribute('value', v);
  });
  scope.querySelectorAll('[data-i18n-target]').forEach((el) => {
    const key = el.getAttribute('data-i18n');
    const v = t(key);
    if (v === key) return;
    const target = el.getAttribute('data-i18n-target');
    if (target === 'text') el.textContent = v;
    else if (target === 'html') el.innerHTML = v;
    else if (target === 'placeholder') el.setAttribute('placeholder', v);
    else if (target === 'aria-label') el.setAttribute('aria-label', v);
    else if (target === 'title') el.setAttribute('title', v);
    else el.textContent = v;
  });
}

async function setLocale(locale) {
  if (!SUPPORTED.includes(locale)) return false;
  await _load(locale);
  document.documentElement.lang = _locale;
  applyAll();
  document.dispatchEvent(new CustomEvent('localechange', { detail: { locale: _locale } }));
  return true;
}

async function init(opts) {
  const stored = _readStored();
  const requested = (opts && opts.locale) || stored || 'en';
  await _load(requested);
  document.documentElement.lang = _locale;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => applyAll(), { once: true });
  } else {
    applyAll();
  }
  return _locale;
}

const i18n = { init, t, tn, setLocale, getLocale, getSupported, applyAll };
if (typeof window !== 'undefined') window.i18n = i18n;
export default i18n;
export { init, t, tn, setLocale, getLocale, getSupported, applyAll };
