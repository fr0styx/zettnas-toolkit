/**
 * "Can't reach ZettNAS" banner (FE-16). Shown when a request can't reach the server or
 * the browser goes offline; it checks /api/health every 5 s and hides itself once the
 * server answers again.
 */
import { t } from './i18n.js';

const BANNER_ID = 'zn-offline-banner';
let _probe = null;
let _offline = false;

function banner() {
  let el = document.getElementById(BANNER_ID);
  if (!el && document.body) {
    el = document.createElement('div');
    el.id = BANNER_ID;
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.className = 'zn-offline-banner';
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}

export function isOffline() {
  return _offline;
}

export function reportOffline() {
  if (typeof document === 'undefined') return;
  _offline = true;
  const el = banner();
  if (el) {
    el.textContent = t('net.offline_banner', "Can't reach ZettNAS. Reconnecting…");
    el.hidden = false;
  }
  if (!_probe) {
    _probe = setInterval(async () => {
      try {
        const res = await window.fetch('/api/health', { cache: 'no-store' });
        if (res.status === 200 || res.status === 503) reportOnline();
      } catch (e) {
        /* still offline */
      }
    }, 5000);
  }
}

export function reportOnline() {
  if (!_offline) return;
  _offline = false;
  if (_probe) {
    clearInterval(_probe);
    _probe = null;
  }
  const el = document.getElementById(BANNER_ID);
  if (el) el.hidden = true;
  window.dispatchEvent(new CustomEvent('zettnas:online'));
}

if (typeof window !== 'undefined') {
  window.addEventListener('offline', reportOffline);
  window.addEventListener('online', () => {
    window.fetch('/api/health', { cache: 'no-store' }).then(reportOnline, () => {});
  });
}
