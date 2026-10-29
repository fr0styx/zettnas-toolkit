/**
 * Phone mode (UX-13): on a phone, a launcher of big tiles, one full-screen page at a time with
 * a Back button, and tabs at the bottom instead of desktop windows and a dock.
 *
 * The launcher is the layer under every page and the desktop (widgets, icons, dock) is hidden,
 * so closing a page never shows the desktop, however long its close animation takes. Back and
 * the tabs follow the open pages through a MutationObserver (no polling).
 *
 * The launcher opens with how the server is doing (UX-15): the same summary as the Overview
 * ("Everything is fine", or what needs attention with a button to open it), then the live
 * numbers and the tiles.
 */
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { ROUTES } from '../router.js';
import { ZettEventBus } from '../event-bus.js';
import { watchDom } from '../dom-watch.js';
import { PHONE_QUERY } from '../device.js';
import { api } from '../api.js';
import { statusHtml as healthHtml } from './management/overview.js';
import { advancedOn, isAdvancedRoute } from '../advanced.js';
import { announceChange } from '../a11y.js';

const PAGE_SELECTOR = '.os-window, .file-manager-window, #management-window, #notif-center-panel, #containers-manager-window';
// A page on its way out is not open any more
const CLOSING = /\b(window-closing|closing|window-minimized|is-closing|minimized)\b/;

export const TILES = () => [
  ['files', t('mgmt.sidebar_files', 'Files'), '#i-storage'],
  ['apps', t('dock.containers', 'Apps'), '#i-chip'],
  ['storage', t('mgmt.sidebar_storage', 'Storage'), '#i-disk'],
  ['shares', t('mgmt.sidebar_shares', 'Shares'), '#i-net'],
  ['backup', t('mgmt.sidebar_backup', 'Backup'), '#i-save'],
  ['users', t('mgmt.sidebar_users', 'Users'), '#i-users'],
  ['ai', t('mgmt.sidebar_ai', 'AI'), '#i-search'],
  ['power', t('mgmt.sidebar_ups', 'Power'), '#i-bolt'],
  ['network', t('mgmt.sidebar_network', 'Network'), '#i-globe'],
  ['vms', t('mgmt.sidebar_vms', 'Virtual machines'), '#i-vm'],
  ['activity', t('mgmt.sidebar_activity', 'Activity'), '#i-clock'],
  ['settings', t('mgmt.sidebar_system', 'Settings'), '#i-shield'],
];

const TABS = () => [
  ['home', t('phone.home', 'Home'), '#i-grid'],
  ['files', t('mgmt.sidebar_files', 'Files'), '#i-storage'],
  ['apps', t('dock.containers', 'Apps'), '#i-chip'],
  ['alerts', t('phone.alerts', 'Alerts'), '#i-bell'],
  ['settings', t('mgmt.sidebar_system', 'Settings'), '#i-shield'],
];

// What each tab opens (alerts: the activity log, a full page like the others)
const TAB_ROUTES = { files: 'files', apps: 'apps', alerts: 'activity', settings: 'settings' };

export function statusHtml() {
  const cell = (key, label) =>
    `<div class="phone-stat"><span class="phone-stat-label">${escapeHtml(label)}</span><span class="phone-stat-val" data-phone-stat="${key}">–</span></div>`;
  return `<section class="phone-status" aria-label="${escapeHtml(t('phone.status', 'System status'))}">${[
    cell('cpu', t('phone.cpu', 'CPU')),
    cell('ram', t('phone.ram', 'Memory')),
    cell('storage', t('mgmt.sidebar_storage', 'Storage')),
    cell('net', t('phone.network_now', 'Network')),
  ].join('')}</section>`;
}

export function launcherHtml() {
  const health = `<section class="phone-health" aria-label="${escapeHtml(t('overview.status_label', 'Status'))}" hidden></section>`;
  return `${health}${statusHtml()}<nav class="phone-launcher-grid" aria-label="${escapeHtml(t('phone.home', 'Home'))}">${TILES()
    .map(
      ([route, name, icon]) =>
        `<button type="button" class="phone-tile" data-phone-open="${route}"${isAdvancedRoute(route) && !advancedOn() ? ' hidden' : ''}><svg class="ic" aria-hidden="true"><use href="${icon}"/></svg><span>${escapeHtml(name)}</span></button>`,
    )
    .join('')}</nav>`;
}

export function tabsHtml() {
  return TABS()
    .map(
      ([id, name, icon]) =>
        `<button type="button" class="phone-tab" data-phone-tab="${id}"><svg class="ic" aria-hidden="true"><use href="${icon}"/></svg><span>${escapeHtml(name)}</span></button>`,
    )
    .join('');
}

function isOpen(el) {
  if (CLOSING.test(el.className?.toString() || '') || el.getAttribute('aria-hidden') === 'true') return false;
  const st = window.getComputedStyle(el);
  if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) < 0.05) return false;
  return true;
}

/** The page on top: the open window with the highest z-index. */
export function topPage(root = document) {
  let top = null;
  let z = -1;
  root.querySelectorAll(PAGE_SELECTOR).forEach((el) => {
    if (!isOpen(el)) return;
    const zi = parseInt(window.getComputedStyle(el).zIndex, 10) || 0;
    if (zi >= z) {
      z = zi;
      top = el;
    }
  });
  return top;
}

function closePage(el) {
  if (!el) return;
  const close = el.querySelector('.close-btn, [data-action="close"], .win-close, .notif-center-close, #management-close');
  if (close) close.click();
  else el.style.display = 'none';
}

// The tab a page belongs to: the one it was opened from, else by what the page is
let openedFrom = 'home';

export function tabForPage(page) {
  if (!page) return 'home';
  if (page.matches('.file-manager-window')) return 'files';
  if (page.id === 'containers-manager-window') return 'apps';
  if (page.id === 'notif-center-panel') return 'alerts';
  if (page.id === 'management-window') return ['settings', 'alerts'].includes(openedFrom) ? openedFrom : 'home';
  return 'home';
}

function closeAllPages() {
  let el = topPage();
  let guard = 0;
  while (el && guard++ < 10) {
    closePage(el);
    // a page that closes with an animation still looks open: hide it right away
    if (topPage() === el) el.style.display = 'none';
    el = topPage();
  }
}

function openTab(id) {
  openedFrom = id;
  if (id === 'home') {
    closeAllPages();
  } else {
    closeAllPages();
    ROUTES[TAB_ROUTES[id]]?.();
  }
  schedule();
}

// UX-15: one history entry stands for "a page is open", so the phone's own Back closes it
const DIALOGS = '#confirm-toast-modal, [role="dialog"][aria-modal="true"], [role="alertdialog"]';
let backEntry = false;
let ignorePop = false;

function dialogOpen() {
  // checkVisibility also sees a hidden ancestor (a dialog inside a closed overlay)
  return Array.from(document.querySelectorAll(DIALOGS)).some((el) =>
    typeof el.checkVisibility === 'function'
      ? el.checkVisibility({ opacityProperty: true, visibilityProperty: true }) && isOpen(el)
      : isOpen(el),
  );
}

function followBackEntry(page) {
  if (page && !backEntry) {
    history.pushState({ zettPhonePage: true }, '');
    backEntry = true;
  } else if (!page && backEntry) {
    backEntry = false;
    if (history.state?.zettPhonePage) {
      ignorePop = true; // closed on screen: take our entry back off the history
      history.back();
    }
  }
}

export function onPhoneBack() {
  if (ignorePop) {
    ignorePop = false;
    return;
  }
  if (!document.body.classList.contains('phone-shell')) return;
  backEntry = false; // the browser just used it
  if (dialogOpen()) {
    // Back closes the dialog first, as on any phone app
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  } else {
    const page = topPage();
    closePage(page);
    if (page && topPage() === page) page.style.display = 'none';
  }
  schedule();
}

function sync() {
  const page = topPage();
  followBackEntry(page);
  const back = document.getElementById('phone-back');
  // only real changes: rewriting the same value would wake the observer again
  if (back && back.hidden !== !page) back.hidden = !page;
  document.body.classList.toggle('phone-page-open', Boolean(page));
  if (!page) {
    openedFrom = 'home';
    refreshHealth(); // back on the launcher: the summary is at most a minute old
  }
  const current = tabForPage(page);
  document.querySelectorAll('[data-phone-tab]').forEach((b) => {
    const on = b.dataset.phoneTab === current;
    b.classList.toggle('is-current', on);
    if (on) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
}

let pending = false;
function schedule() {
  if (pending) return;
  pending = true;
  (window.requestAnimationFrame || ((fn) => setTimeout(fn, 16)))(() => {
    pending = false;
    if (document.body.classList.contains('phone-shell')) sync();
  });
}

function fmtRate(bytes) {
  const b = Number(bytes) || 0;
  if (b >= 1048576) return `${(b / 1048576).toFixed(1)} MB/s`;
  if (b >= 1024) return `${Math.round(b / 1024)} KB/s`;
  return `${Math.round(b)} B/s`;
}

export function updateStatus(stats, root = document) {
  if (!stats) return;
  const set = (key, text) => {
    const el = root.querySelector(`[data-phone-stat="${key}"]`);
    if (el && text != null) el.textContent = text;
  };
  if (stats.cpu?.util != null) set('cpu', `${Math.round(stats.cpu.util)}%${stats.cpu.temp ? ` · ${Math.round(stats.cpu.temp)}°C` : ''}`);
  if (stats.mem?.pct != null) set('ram', `${Math.round(stats.mem.pct)}%`);
  if (stats.storage?.used) set('storage', `${stats.storage.used} / ${stats.storage.total}`);
  if (stats.net) set('net', `↓ ${fmtRate(stats.net.rx_bytes_sec)} ↑ ${fmtRate(stats.net.tx_bytes_sec)}`);
}

// The health summary: when the launcher appears and at most once a minute while it is up
const HEALTH_EVERY_MS = 60000;
let healthAt = 0;

export async function refreshHealth(force = false, root = document) {
  const box = root.querySelector('#phone-shell .phone-health');
  if (!box || (!force && Date.now() - healthAt < HEALTH_EVERY_MS)) return null;
  healthAt = Date.now();
  try {
    const summary = await api.get('/api/system/status-summary');
    box.innerHTML = healthHtml(summary);
    box.hidden = false;
    import('./management/overview.js').then((m) => announceChange('phone-health', m.statusSentence(summary)), () => {});
    return summary;
  } catch {
    box.hidden = true; // not allowed or not reachable: the launcher still works
    return null;
  }
}

let unwatch = null;

export function enablePhoneShell(on) {
  document.body.classList.toggle('phone-shell', on);
  let shell = document.getElementById('phone-shell');
  if (!on) {
    shell?.remove();
    unwatch?.();
    unwatch = null;
    document.body.classList.remove('phone-page-open');
    window.removeEventListener('popstate', onPhoneBack);
    backEntry = false;
    return;
  }
  if (shell) return;
  window.addEventListener('popstate', onPhoneBack);
  shell = document.createElement('div');
  shell.id = 'phone-shell';
  shell.innerHTML = `<button type="button" id="phone-back" class="phone-back" hidden>‹ ${escapeHtml(t('setup.back', 'Back'))}</button>
    <div id="phone-launcher" class="phone-launcher">${launcherHtml()}</div>
    <nav id="phone-tabs" class="phone-tabs" aria-label="${escapeHtml(t('phone.tabs', 'Main sections'))}">${tabsHtml()}</nav>`;
  document.body.appendChild(shell);
  shell.addEventListener('click', (e) => {
    const tab = e.target.closest('[data-phone-tab]');
    const tile = e.target.closest('[data-phone-open]');
    if (e.target.closest('#phone-back')) {
      const page = topPage();
      closePage(page);
      if (page && topPage() === page) page.style.display = 'none';
      schedule();
    } else if (e.target.closest('[data-ov-open]')) {
      const route = e.target.closest('[data-ov-open]').dataset.ovOpen;
      if (ROUTES[route]) ROUTES[route]();
      schedule();
    } else if (tab) {
      openTab(tab.dataset.phoneTab);
    } else if (tile && ROUTES[tile.dataset.phoneOpen]) {
      openedFrom = tile.dataset.phoneOpen === 'settings' ? 'settings' : 'home';
      ROUTES[tile.dataset.phoneOpen]();
      schedule();
    }
  });
  // pages open and close from many places: follow their style and class changes
  unwatch = watchDom({ attributes: ['style', 'class', 'hidden', 'aria-hidden'], onRecords: schedule });
  sync();
  refreshHealth(true);
}

export function initPhoneShell() {
  const mq = window.matchMedia ? window.matchMedia(PHONE_QUERY) : null;
  const apply = () => enablePhoneShell(Boolean(mq && mq.matches) && !document.documentElement.classList.contains('auth-required'));
  apply();
  mq?.addEventListener?.('change', apply);
  // signing in or out switches the shell at once (the desktop never shows in between)
  new MutationObserver(apply).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
  ZettEventBus.on('stats:updated', (stats) => {
    if (!document.body.classList.contains('phone-shell')) return;
    updateStatus(stats);
    if (!document.body.classList.contains('phone-page-open')) refreshHealth();
  });
}
