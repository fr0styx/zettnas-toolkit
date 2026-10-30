/**
 * The one place that formats dates, times, numbers and sizes for display (FE-14).
 * Everything follows the app's language (not the browser's), so a German UI shows
 * German dates and number separators. Formatters are cached per locale.
 * Dates and times also follow the person's own clock: their time zone and 12/24-hour choice
 * (NUX-10), so a file's date, a backup's last run and the desktop clock agree.
 */
import { getLanguage } from './i18n.js';
import { ZettEventBus } from './event-bus.js';

const LOCALES = { en: 'en', de: 'de-DE', zh: 'zh-CN', fr: 'fr-FR', es: 'es-ES' };
const _cache = new Map();
const _clock = { timeZone: '', hour12: /** @type {boolean | undefined} */ (undefined) };

/** The person's clock: an IANA zone ('' = the browser's) and '12' / '24' (other = the locale's). */
export function setClockPrefs(zone, format) {
  let tz = '';
  if (zone) {
    try {
      new Intl.DateTimeFormat('en', { timeZone: zone });
      tz = zone;
    } catch {
      tz = ''; // an unknown zone: the browser's
    }
  }
  const hour12 = format === '12' ? true : format === '24' ? false : undefined;
  if (tz === _clock.timeZone && hour12 === _clock.hour12) return;
  _clock.timeZone = tz;
  _clock.hour12 = hour12;
  _cache.clear();
}

export function clockPrefs() {
  return { ..._clock };
}

ZettEventBus.on?.('clock:changed', (d) => setClockPrefs(d && d.zone, d && d.format));

function _withClock(options) {
  const o = { ...(options || {}) };
  if (_clock.timeZone && !o.timeZone) o.timeZone = _clock.timeZone;
  const hasTime = o.timeStyle || o.hour !== undefined;
  if (hasTime && _clock.hour12 !== undefined && o.hour12 === undefined && o.hourCycle === undefined) o.hour12 = _clock.hour12;
  return o;
}

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
    f = kind === 'number' ? new Intl.NumberFormat(locale, options) : new Intl.DateTimeFormat(locale, _withClock(options));
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
