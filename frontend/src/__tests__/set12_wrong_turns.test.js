// SET-12, Overview stage 1: the wrong turns in Settings' navigation.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { enablePhoneShell, onPhoneBack, launcherHtml, tabsHtml } from '../components/phone-shell.js';
import { installWindowFocus } from '../window-focus.js';
import { entryFor, highlightEntry, mayNotOpen } from '../components/management/sidebar-current.js';
import { forgetWindows, isMine, ownerName } from '../components/dock/whose-windows.js';
import { OPEN_WINDOWS_KEY, restoreOpenWindowsState } from '../components/dock/window-state.js';
import { DockManager } from '../components/dock/dock-manager.js';
import { initSpotlight, openSpotlight, closeSpotlight, registerSpotlightItem, relabelSpotlight } from '../components/spotlight.js';
import { applyAdvancedEverywhere, setServerAdvanced } from '../advanced.js';
import { NO_ACCESS, ADVANCED_OFF, leavePage, mark } from '../hide-marks.js';
import { installAdvancedSwitch, leaveAdvancedPage } from '../components/management/overview.js';

const tick = () => new Promise((r) => setTimeout(r, 40));

/** Settings as the page builds it: a frame that calls itself a modal dialog around the window. */
function settings() {
  const overlay = document.createElement('div');
  overlay.id = 'management-modal-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.innerHTML = '<div id="management-window" class="smart-modal-window" style="z-index:1000"><button id="management-close">x</button></div>';
  document.body.appendChild(overlay);
  const close = vi.fn(() => {
    overlay.style.display = 'none';
    overlay.querySelector('#management-window').style.display = 'none';
  });
  overlay.querySelector('#management-close').addEventListener('click', close);
  return { overlay, close };
}

describe('Back and Escape close Settings', () => {
  afterEach(() => enablePhoneShell(false));

  it("the phone's Back closes Settings instead of sending it Escape", async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const { close } = settings();
    const esc = vi.fn();
    document.addEventListener('keydown', esc);
    await tick();
    onPhoneBack();
    expect(close).toHaveBeenCalledTimes(1);
    expect(esc).not.toHaveBeenCalled();
    document.removeEventListener('keydown', esc);
  });

  it('a question on top of Settings still closes first', async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const { close } = settings();
    const question = document.createElement('div');
    question.setAttribute('role', 'dialog');
    question.setAttribute('aria-modal', 'true');
    document.body.appendChild(question);
    const esc = vi.fn();
    document.addEventListener('keydown', esc);
    await tick();
    onPhoneBack();
    expect(esc).toHaveBeenCalledWith(expect.objectContaining({ key: 'Escape' }));
    expect(close).not.toHaveBeenCalled();
    document.removeEventListener('keydown', esc);
  });

  it('Escape closes Settings, and a window under it once Settings is gone', () => {
    document.body.innerHTML = '<div id="w" class="os-window" style="z-index:10"><button id="bw">w</button></div>';
    const { overlay } = settings();
    const dock = {
      windows: {},
      register(id, el) { this.windows[id] = { el, minimized: false, closed: false }; },
      closeWindow(id) { this.windows[id].el.style.display = 'none'; delete this.windows[id]; },
    };
    installWindowFocus(dock);
    dock.register('w', document.getElementById('w'));
    dock.register('management', overlay);
    const press = (el) => el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    press(document.getElementById('management-close'));
    expect(dock.windows.management).toBeUndefined(); // it stopped every Escape while it was open
    expect(dock.windows.w).toBeTruthy();
    press(document.getElementById('bw'));
    expect(dock.windows.w).toBeUndefined();
  });

  it('Escape still belongs to a question that is open', () => {
    document.body.innerHTML = '<div id="w" class="os-window"><button id="bw">w</button></div><div role="dialog" aria-modal="true" id="q"></div>';
    const dock = { windows: {}, closeWindow: vi.fn() };
    installWindowFocus(dock);
    dock.windows.w = { el: document.getElementById('w') };
    document.getElementById('bw').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(dock.closeWindow).not.toHaveBeenCalled();
  });
});

const SIDEBAR = `
  <button class="mgmt-sidebar-item" data-mgmt-target="management-hub-view" id="e-overview"></button>
  <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-system" data-mgmt-pane="mgmt-pane-users" data-route="users" id="e-users"></button>
  <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-system" data-mgmt-pane="mgmt-pane-backups" data-route="backup" id="e-backup"></button>
  <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-network" data-route="network" id="e-network"></button>
  <button class="mgmt-sidebar-item active" data-mgmt-target="mgmt-sec-system" id="e-settings"></button>`;

describe('the sidebar entry of the open page', () => {
  beforeEach(() => {
    document.body.innerHTML = SIDEBAR;
  });

  it('a tab with an entry of its own highlights that entry', () => {
    expect(entryFor('mgmt-sec-system', 'mgmt-pane-users').id).toBe('e-users');
    expect(entryFor('mgmt-sec-system', 'mgmt-pane-security').id).toBe('e-settings');
    expect(entryFor('mgmt-sec-nowhere', null)).toBeNull();
    highlightEntry('mgmt-sec-system', 'mgmt-pane-users'); // "Settings" stayed highlighted
    expect(document.querySelector('.mgmt-sidebar-item.active').id).toBe('e-users');
    expect(document.getElementById('e-users').getAttribute('aria-current')).toBe('page');
    expect(document.getElementById('e-settings').hasAttribute('aria-current')).toBe(false);
  });

  it('a page the rights hide is not opened, and an open one is left when the account is known', () => {
    expect(mayNotOpen('mgmt-sec-system', 'mgmt-pane-users')).toBe(false);
    highlightEntry('mgmt-sec-system', 'mgmt-pane-users');
    const overview = vi.fn();
    document.getElementById('e-overview').addEventListener('click', overview);
    ZettEventBus.emit('session:user', { username: 'kim', scopes: ['files:read'] });
    expect(mayNotOpen('mgmt-sec-system', 'mgmt-pane-users')).toBe(true);
    expect(mayNotOpen('mgmt-sec-system', 'mgmt-pane-security')).toBe(false); // their own password lives there
    expect(overview).toHaveBeenCalledTimes(1);
    expect(leavePage(NO_ACCESS)).toBe(true);
    highlightEntry('mgmt-sec-system', null);
    expect(leavePage(NO_ACCESS)).toBe(false);
    ZettEventBus.emit('session:user', { username: 'ana', scopes: ['*'] });
    expect(mayNotOpen('mgmt-sec-system', 'mgmt-pane-users')).toBe(false);
  });

  it('switching Advanced off on one of its pages goes back to the Overview', () => {
    highlightEntry('mgmt-sec-network', null);
    const overview = vi.fn();
    document.getElementById('e-overview').addEventListener('click', overview);
    expect(leaveAdvancedPage()).toBe(false);
    mark(document.getElementById('e-network'), ADVANCED_OFF, true);
    expect(leaveAdvancedPage()).toBe(true);
    expect(overview).toHaveBeenCalledTimes(1);
  });
});

describe('whose windows come back', () => {
  beforeEach(() => {
    localStorage.clear();
    ZettEventBus.emit('session:user', null);
    DockManager.windows = {};
  });

  it('a list with another name is not this person’s', () => {
    expect(ownerName()).toBe('');
    expect(isMine({ who: 'ana' })).toBe(true); // not known yet: a reload keeps the same session
    ZettEventBus.emit('session:user', { username: 'ben', scopes: ['*'] });
    expect(ownerName()).toBe('ben');
    expect(isMine({ who: 'ana' })).toBe(false);
    expect(isMine({ who: 'ben' })).toBe(true);
    expect(isMine({})).toBe(true);
    expect(isMine(null)).toBe(true);
  });

  it('signing out closes every window and drops the list', () => {
    const closed = vi.fn();
    DockManager.windows = { a: { onClose: closed }, b: { closed: true, onClose: closed }, c: { onClose: () => { throw new Error('stuck'); } } };
    localStorage.setItem(OPEN_WINDOWS_KEY, '{"who":"ana","windows":{}}');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    ZettEventBus.emit('auth:logout');
    expect(closed).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalled();
    expect(localStorage.getItem(OPEN_WINDOWS_KEY)).toBeNull();
    warn.mockRestore();
    forgetWindows(null, OPEN_WINDOWS_KEY, { removeItem: () => { throw new Error('private'); } });
  });

  it('the next person to sign in does not get the last person’s windows', () => {
    const closed = vi.fn();
    DockManager.windows = { a: { onClose: closed } };
    localStorage.setItem(OPEN_WINDOWS_KEY, '{"who":"ana","windows":{"management":{"open":true,"activePane":"mgmt-pane-users"}}}');
    ZettEventBus.emit('session:user', { username: 'ana', scopes: ['*'] });
    expect(closed).not.toHaveBeenCalled();
    ZettEventBus.emit('session:user', { username: 'ben', scopes: ['*'] }); // the session ran out, ben signed in
    expect(closed).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(OPEN_WINDOWS_KEY)).toBeNull();
    localStorage.setItem(OPEN_WINDOWS_KEY, '{"who":"ana","windows":{"management":{"open":true,"activePane":"mgmt-pane-users"}}}');
    window.openManagementWindow = vi.fn();
    restoreOpenWindowsState();
    expect(window.openManagementWindow).not.toHaveBeenCalled();
    expect(localStorage.getItem(OPEN_WINDOWS_KEY)).toBeNull();
    localStorage.setItem(OPEN_WINDOWS_KEY, 'not json');
    ZettEventBus.emit('session:user', { username: 'ben', scopes: ['*'] });
  });
});

describe('a change of language reaches what is built once', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('the phone tiles, the tabs and the Advanced switch carry the key of their text', async () => {
    document.body.innerHTML = `<div id="l">${launcherHtml()}</div><div id="t">${tabsHtml()}</div><nav class="mgmt-sidebar-nav"></nav>`;
    installAdvancedSwitch();
    const tile = document.querySelector('[data-phone-open="users"] span');
    const caption = document.querySelector('.mgmt-advanced-row strong');
    expect(tile.textContent).toBe('People'); // the sidebar's name (SET-18, X2)
    expect(document.querySelector('.mgmt-advanced-row .mgmt-advanced-icon')).toBeTruthy(); // what a narrow sidebar shows
    await setLanguage('de');
    expect(tile.textContent).toBe('Personen');
    expect(caption.textContent).toBe('Erweiterte Werkzeuge');
    expect(document.querySelector('.mgmt-advanced-row').title).toBe('Auf dem Schreibtisch, im Dock und auf dem Telefon sowie Expertendetails in Fenstern');
    expect(document.querySelector('[data-phone-tab="home"] span').getAttribute('data-i18n')).toBe('phone.home');
    document.querySelectorAll('#l [data-i18n], #t [data-i18n]').forEach((el) => expect(el.textContent).not.toBe(el.getAttribute('data-i18n')));
  });

  it('a tile that Advanced hid at first comes back when it is switched on', () => {
    setServerAdvanced(false);
    document.body.innerHTML = launcherHtml();
    const vms = document.querySelector('[data-phone-open="vms"]');
    expect(vms.hidden).toBe(true);
    setServerAdvanced(true);
    expect(vms.hidden).toBe(false);
  });

  it('the Virtual Machines desktop icon follows the switch and the rights', () => {
    document.body.innerHTML = '<div id="vm-desktop-icon" data-route="vms" data-advanced-section="mgmt-sec-vms"></div>';
    const icon = document.getElementById('vm-desktop-icon');
    applyAdvancedEverywhere(false);
    expect(icon.hidden).toBe(true); // it was never hidden
    applyAdvancedEverywhere(true);
    expect(icon.hidden).toBe(false);
    ZettEventBus.emit('session:user', { username: 'kim', scopes: ['files:read'] });
    expect(icon.hidden).toBe(true);
    ZettEventBus.emit('session:user', null);
    expect(icon.hidden).toBe(false);
  });

  it('Spotlight speaks the new language and keeps what other code added', async () => {
    document.body.innerHTML = '';
    initSpotlight();
    registerSpotlightItem({ id: 'extra-one', title: 'Extra one', subtitle: '', icon: '', category: 'app', keywords: ['extra'], run: () => {} });
    await setLanguage('de');
    openSpotlight('');
    const results = document.getElementById('spotlight-results').textContent;
    expect(results).toContain('Extra one');
    expect(results).toContain('Papierkorb'); // the entries were built once, in the first language
    expect(document.getElementById('spotlight-input').getAttribute('placeholder')).not.toBe('Search apps, folders and actions');
    closeSpotlight();
    relabelSpotlight();
  });
});
