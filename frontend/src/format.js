/**
 * The one place that formats dates, times, numbers and sizes for display (FE-14).
 * Everything follows the app's language (not the browser's), so a German UI shows
 * German dates and number separators. Formatters are cached per locale.
 */
import { getLanguage } from './i18n.js';

const LOCALES = { en: 'en', de: 'de-DE', zh: 'zh-CN', fr: 'fr-FR', es: 'es-ES' };
const _cache = new Map();

/** BCP 47 locale for the current app language (English keeps the browser's region). */
export function currentLocale() {
  const lang = getLanguage();
  if (lang === 'en' && typeof navigator !== 'undefined' && /^en(-|$)/i.test(navigator.language || '')) {
    return navigator.language;
  }
  return LOCALES[lang] || 'en';
}

function _fmt(kind, options) {
  const locale = currentLocale();
  const key = `${kind}|${locale}|${JSON.stringify(options || {})}`;
  let f = _cache.get(key);
  if (!f) {
    f = kind === 'number' ? new Intl.NumberFormat(locale, options) : new Intl.DateTimeFormat(locale, options);
    _cache.set(key, f);
  }
  return f;
}

/** Accepts a Date, epoch seconds (backend timestamps), epoch milliseconds or an ISO string. */
export function toDate(value) {
  if (value instanceof Date) return value;
  if (typeof value === 'number') return new Date(value < 1e11 ? value * 1000 : value);
  if (typeof value === 'string' && value) {
    const n = Number(value);
    return Number.isFinite(n) ? toDate(n) : new Date(value);
  }
  return null;
}

function _valid(d) {
  return d instanceof Date && !Number.isNaN(d.getTime());
}

export function formatDateTime(value, options = { dateStyle: 'medium', timeStyle: 'short' }, empty = '--') {
  const d = toDate(value);
  return _valid(d) ? _fmt('date', options).format(d) : empty;
}

export function formatDate(value, options = { dateStyle: 'medium' }, empty = '--') {
  const d = toDate(value);
  return _valid(d) ? _fmt('date', options).format(d) : empty;
}

export function formatTime(value, options = { hour: '2-digit', minute: '2-digit' }, empty = '--') {
  const d = toDate(value);
  return _valid(d) ? _fmt('date', options).format(d) : empty;
}

export function formatNumber(value, options = {}) {
  const n = Number(value);
  return Number.isFinite(n) ? _fmt('number', options).format(n) : '0';
}

export function formatPercent(value, digits = 0) {
  const n = Number(value);
  return Number.isFinite(n)
    ? _fmt('number', { style: 'percent', maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n / 100)
    : '--';
}

/**
 * 1536 -> "1.5 KB". binary (default) divides by 1024, as file sizes are shown elsewhere in the
 * app; si: true divides by 1000, as disk makers label capacity. fixed keeps trailing zeros.
 */
export function formatBytes(bytes, { decimals = 1, si = false, fixed = false } = {}) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return `${formatNumber(0)} B`;
  const k = si ? 1000 : 1024;
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(k)));
  const value = n / Math.pow(k, i);
  const digits = i === 0 ? 0 : decimals;
  return `${formatNumber(value, { maximumFractionDigits: digits, minimumFractionDigits: fixed ? digits : 0 })} ${units[i]}`;
}
