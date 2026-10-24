/**
 * Phone mode (UX-13): on a phone, a launcher of big tiles, one full-screen page at a time with
 * a Back button, and tabs at the bottom instead of desktop windows and a dock.
 */
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { ROUTES } from '../router.js';

const PHONE_QUERY = '(max-width: 600px)';
const PAGE_SELECTOR = '.os-window, .file-manager-window, #management-window, #notif-center-panel, #containers-manager-window';

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
  ['settings', t('mgmt.sidebar_system', 'Settings'), '#i-shield'],
];

export function launcherHtml() {
  return `<nav class="phone-launcher-grid" aria-label="${escapeHtml(t('phone.home', 'Home'))}">${TILES()
    .map(
      ([route, name, icon]) =>
        `<button type="button" class="phone-tile" data-phone-open="${route}"><svg class="ic" aria-hidden="true"><use href="${icon}"/></svg><span>${escapeHtml(name)}</span></button>`,
    )
    .join('')}</nav>`;
}

export function tabsHtml() {
  const tabs = [
    ['home', t('phone.home', 'Home'), '#i-grid'],
    ['files', t('mgmt.sidebar_files', 'Files'), '#i-storage'],
    ['apps', t('dock.containers', 'Apps'), '#i-chip'],
    ['alerts', t('phone.alerts', 'Alerts'), '#i-bell'],
    ['settings', t('mgmt.sidebar_system', 'Settings'), '#i-shield'],
  ];
  return tabs
    .map(
      ([id, name, icon]) =>
        `<button type="button" class="phone-tab" data-phone-tab="${id}"><svg class="ic" aria-hidden="true"><use href="${icon}"/></svg><span>${escapeHtml(name)}</span></button>`,
    )
    .join('');
}

/** The page on top: the visible window with the highest z-index. */
export function topPage(root = document) {
  let top = null;
  let z = -1;
  root.querySelectorAll(PAGE_SELECTOR).forEach((el) => {
    const st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || el.classList.contains('window-minimized')) return;
    const zi = parseInt(st.zIndex, 10) || 0;
    if (zi >= z) {
      z = zi;
      top = el;
    }
  });
  return top;
}

function closePage(el) {
  if (!el) return;
  const close = el.querySelector('.close-btn, [data-action="close"], .win-close, .notif-center-close');
  if (close) close.click();
  else el.style.display = 'none';
}

function openTab(id) {
  if (id === 'home') {
    let el = topPage();
    let guard = 0;
    while (el && guard++ < 10) {
      closePage(el);
      el = topPage();
    }
  } else if (id === 'alerts') {
    const panel = document.getElementById('notif-center-panel');
    if (panel) panel.style.display = 'flex';
  } else if (ROUTES[id]) {
    ROUTES[id]();
  }
  setTimeout(syncBack, 50);
}

function syncBack() {
  const back = document.getElementById('phone-back');
  const launcher = document.getElementById('phone-launcher');
  const page = topPage();
  if (back) back.hidden = !page;
  if (launcher) launcher.hidden = Boolean(page);
  document.querySelectorAll('[data-phone-tab]').forEach((b) => {
    const id = b.dataset.phoneTab;
    const on = (id === 'home' && !page) || (page && ((id === 'files' && page.matches('.file-manager-window')) || (id === 'apps' && page.id === 'containers-manager-window') || (id === 'alerts' && page.id === 'notif-center-panel') || (id === 'settings' && page.id === 'management-window')));
    b.classList.toggle('is-current', Boolean(on));
    if (on) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
}

export function enablePhoneShell(on) {
  document.body.classList.toggle('phone-shell', on);
  let shell = document.getElementById('phone-shell');
  if (!on) {
    shell?.remove();
    return;
  }
  if (shell) return;
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
      closePage(topPage());
      setTimeout(syncBack, 50);
    } else if (tab) openTab(tab.dataset.phoneTab);
    else if (tile && ROUTES[tile.dataset.phoneOpen]) {
      ROUTES[tile.dataset.phoneOpen]();
      setTimeout(syncBack, 80);
    }
  });
  syncBack();
}

export function initPhoneShell() {
  const mq = window.matchMedia ? window.matchMedia(PHONE_QUERY) : null;
  const apply = () => enablePhoneShell(Boolean(mq && mq.matches) && !document.documentElement.classList.contains('auth-required'));
  apply();
  mq?.addEventListener?.('change', apply);
  // signing in and out, and pages opening from many places: keep the shell, Back and tabs in step
  setInterval(() => {
    apply();
    if (document.body.classList.contains('phone-shell')) syncBack();
  }, 1000);
}
