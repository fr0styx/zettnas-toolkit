/** The apps the dock knows, the File Explorer window switcher and the dock item menu. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../components/dock/console-window.js', () => ({ openConsoleWindow: vi.fn() }));
vi.mock('../components/dock/window-drag.js', () => ({ bringToFront: vi.fn() }));
vi.mock('../components/dock/dock-manager.js', () => ({
  DockManager: { activeId: null, windows: {}, restore: vi.fn(), closeWindow: vi.fn(), togglePin: vi.fn(), register: vi.fn() },
}));

const { KNOWN_APPS, toggleFmWindowSwitcher, showDockItemContextMenu } = await import('../components/dock/apps.js');
const { DockManager } = await import('../components/dock/dock-manager.js');
const { bringToFront } = await import('../components/dock/window-drag.js');
const { openConsoleWindow } = await import('../components/dock/console-window.js');
const { ZettEventBus } = await import('../event-bus.js');
const { setLanguage } = await import('../i18n.js');

const $ = (id) => document.getElementById(id);
const GLOBALS = ['openFileManager', 'openManagementWindow', 'openContainerInspector', 'openContainersManager', 'openContainersWindow',
  'openVmManager', 'toggleNotificationCenter', 'openNewCloudRemoteModal', 'openPersonalizationWindow', 'DockManager',
  'openNewFileManagerWindow', 'closeAllFileManagerWindows'];
const fakeDock = () => ({ windows: {}, register: vi.fn(), restore: vi.fn() });
const fmWindow = (id, path) => {
  const el = document.createElement('div');
  el.innerHTML = `<div class="file-manager-window"><input class="fm-path-input" value="${path}"><button class="close-btn"></button></div>`;
  return el;
};

let emit;
beforeEach(() => {
  document.body.innerHTML = '';
  emit = vi.spyOn(ZettEventBus, 'emit');
  DockManager.activeId = null;
  DockManager.windows = {};
});
afterEach(async () => {
  for (const g of GLOBALS) delete window[g];
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.useRealTimers();
  await setLanguage('en');
});

describe('known apps', () => {
  it('every app has a title in the reader\'s language', async () => {
    expect(Object.values(KNOWN_APPS).map((a) => a.getTitle())).toEqual([
      'File Explorer', 'Settings', 'ZettNAS', 'Drive Health', 'Container Inspector', 'Apps', 'Virtual Machines',
      'App Deployment', 'Notification Center', 'Cloud Remotes', 'Desktop & Personalization', 'Ask Zetty',
    ]);
    await setLanguage('de');
    expect(KNOWN_APPS['container-inspector'].getTitle()).toBe('Container-Inspektor');
    expect(KNOWN_APPS['app-deploy'].getTitle()).toBe('App-Bereitstellung');
    expect(KNOWN_APPS['cloud-remote'].getTitle()).toBe('Cloud-Speicher');
  });

  it('opens each app through its own opener when the page has one', () => {
    for (const g of GLOBALS) window[g] = vi.fn();
    KNOWN_APPS.fm.launch('/mnt/user');
    expect(window.openFileManager).toHaveBeenCalledWith('/mnt/user');
    KNOWN_APPS.management.launch('hub');
    KNOWN_APPS.management.launch('mgmt-pane-ups');
    expect(window.openManagementWindow.mock.calls).toEqual([[null], ['mgmt-pane-ups']]);
    KNOWN_APPS.zettai.launch();
    expect(window.openManagementWindow).toHaveBeenLastCalledWith('mgmt-sec-ai-rag', 'mgmt-pane-ai-rag');
    KNOWN_APPS.console.launch();
    expect(openConsoleWindow).toHaveBeenCalled();
    KNOWN_APPS.smart.launch('sda');
    expect(emit).toHaveBeenCalledWith('modal:smart:open', 'sda');
    KNOWN_APPS['container-inspector'].launch();
    KNOWN_APPS['container-inspector'].launch({ cname: 'x' });
    KNOWN_APPS['container-inspector'].launch({ cid: 'c1', cname: 'plex' });
    expect(window.openContainerInspector.mock.calls).toEqual([['c1', 'plex']]);
    KNOWN_APPS.containers.launch();
    expect(window.openContainersManager).toHaveBeenCalled();
    delete window.openContainersManager;
    KNOWN_APPS.containers.launch();
    expect(window.openContainersWindow).toHaveBeenCalled();
    KNOWN_APPS.vm.launch();
    expect(window.openVmManager).toHaveBeenCalled();
    KNOWN_APPS['cloud-remote'].launch();
    expect(window.openNewCloudRemoteModal).toHaveBeenCalled();
    KNOWN_APPS.personalization.launch('wallpaper');
    expect(window.openPersonalizationWindow).toHaveBeenCalledWith('wallpaper');
  });

  it('without an opener, restores the app\'s window and registers it once', () => {
    document.body.innerHTML = '<div id="file-manager-window"></div><div id="containers-manager-window"></div><div id="vm-manager-window"></div>';
    window.DockManager = fakeDock();
    KNOWN_APPS.fm.launch('/mnt');
    KNOWN_APPS.containers.launch();
    KNOWN_APPS.vm.launch();
    expect(window.DockManager.register.mock.calls.map((c) => [c[0], c[1].id])).toEqual([
      ['fm', 'file-manager-window'], ['containers', 'containers-manager-window'], ['vm', 'vm-manager-window'],
    ]);
    expect(emit).toHaveBeenCalledWith('window:open', { id: 'file-manager-window', path: '/mnt' });
    expect(emit).toHaveBeenCalledWith('window:open', { id: 'vm-manager-window' });
    window.DockManager.windows = { fm: {}, containers: {}, vm: {} };
    KNOWN_APPS.fm.launch();
    KNOWN_APPS.containers.launch();
    KNOWN_APPS.vm.launch();
    expect(window.DockManager.register).toHaveBeenCalledTimes(3);
    expect(window.DockManager.restore).toHaveBeenCalledTimes(6);
    expect(emit).toHaveBeenCalledWith('window:open', { id: 'file-manager-window', path: undefined });
    delete window.DockManager;
    KNOWN_APPS.fm.launch();
    KNOWN_APPS.containers.launch();
    KNOWN_APPS.vm.launch();
  });

  it('without a window either, clicks the desktop icon', () => {
    const clicks = [];
    document.body.innerHTML = ['fm', 'management', 'containers', 'vm'].map((a) => `<button id="${a}-desktop-icon"></button>`).join('');
    document.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => clicks.push(b.id)));
    KNOWN_APPS.fm.launch();
    KNOWN_APPS.management.launch();
    KNOWN_APPS.zettai.launch();
    KNOWN_APPS.containers.launch();
    KNOWN_APPS.vm.launch();
    expect(clicks).toEqual(['fm-desktop-icon', 'management-desktop-icon', 'management-desktop-icon', 'containers-desktop-icon', 'vm-desktop-icon']);
    KNOWN_APPS.personalization.launch();
  });

  it('app deployment, cloud remotes and the notification center come forward', () => {
    KNOWN_APPS['app-deploy'].launch();
    KNOWN_APPS['cloud-remote'].launch();
    KNOWN_APPS.notif.launch();
    expect(DockManager.restore).not.toHaveBeenCalled();
    document.body.innerHTML = `<div id="app-deploy-modal-overlay"></div><div id="app-deploy-modal-window"></div>
      <div id="modal-new-cloud-remote"></div><div id="cloud-remote-window"></div><div id="notif-center-panel"></div>`;
    window.DockManager = fakeDock();
    window.toggleNotificationCenter = vi.fn();
    KNOWN_APPS['app-deploy'].launch();
    expect(DockManager.restore).toHaveBeenCalledWith('app-deploy');
    expect(bringToFront).toHaveBeenCalledWith($('app-deploy-modal-window'));
    KNOWN_APPS['cloud-remote'].launch();
    expect(window.DockManager.restore).toHaveBeenCalledWith('cloud-remote');
    expect(bringToFront).toHaveBeenLastCalledWith($('cloud-remote-window'));
    KNOWN_APPS.notif.launch();
    $('notif-center-panel').style.display = 'block';
    KNOWN_APPS.notif.launch();
    $('notif-center-panel').style.display = 'none';
    KNOWN_APPS.notif.launch();
    expect(window.toggleNotificationCenter).toHaveBeenCalledTimes(2);
    $('app-deploy-modal-window').remove();
    $('cloud-remote-window').remove();
    KNOWN_APPS['app-deploy'].launch();
    KNOWN_APPS['cloud-remote'].launch();
    expect(bringToFront).toHaveBeenCalledTimes(2);
  });
});

describe('File Explorer window switcher', () => {
  const anchor = () => {
    const a = document.createElement('button');
    document.body.appendChild(a);
    return a;
  };

  it('lists the open windows with their folder and path, and opens one', () => {
    const a = anchor();
    toggleFmWindowSwitcher(a, []);
    expect($('dock-fm-switcher')).toBeNull();
    const w1 = { id: 'fm', title: 'File Explorer (Photos)', el: fmWindow('fm', '/mnt/user/photos') };
    const w2 = { id: 'fm-2', title: '', el: { querySelector: () => null } };
    const w3 = { id: 'fm-3', minimized: true, el: null };
    DockManager.activeId = 'fm';
    toggleFmWindowSwitcher(a, [w1, w2, w3]);
    const items = [...document.querySelectorAll('.dock-switcher-item')];
    expect(document.querySelector('.dock-switcher-header').textContent).toContain('File Explorer Windows (3)');
    expect(items.map((i) => i.querySelector('.dock-switcher-name').textContent)).toEqual(['Photos', 'File Explorer', 'File Explorer']);
    expect(items[0].querySelector('.dock-switcher-path').textContent).toBe('/mnt/user/photos');
    expect(items[1].querySelector('.dock-switcher-path')).toBeNull();
    expect(items.map((i) => i.classList.contains('active'))).toEqual([true, false, false]);
    items[0].click();
    expect(DockManager.restore).toHaveBeenCalledWith('fm');
    expect(bringToFront).toHaveBeenCalledWith(w1.el.querySelector('.file-manager-window'));
    expect($('dock-fm-switcher')).toBeNull();
    toggleFmWindowSwitcher(a, [w3]);
    document.querySelector('.dock-switcher-item').click();
    expect(bringToFront).toHaveBeenCalledTimes(1);
  });

  it('closes a window from the list, through its own close button when it has one', () => {
    const a = anchor();
    const w1 = { id: 'fm', el: fmWindow('fm', '/a') };
    const closed = vi.fn();
    w1.el.querySelector('.close-btn').addEventListener('click', closed);
    const w2 = { id: 'fm-2', el: null };
    toggleFmWindowSwitcher(a, [w1, w2]);
    document.querySelectorAll('.dock-switcher-close')[0].click();
    expect(closed).toHaveBeenCalled();
    expect(DockManager.restore).not.toHaveBeenCalled();
    toggleFmWindowSwitcher(a, [w1, w2]);
    document.querySelectorAll('.dock-switcher-close')[1].click();
    expect(DockManager.closeWindow).toHaveBeenCalledWith('fm-2');
  });

  it('closes from its close button, a second click on the dock, or a click elsewhere', () => {
    vi.useFakeTimers();
    const a = anchor();
    const ws = [{ id: 'fm', el: null }];
    toggleFmWindowSwitcher(a, ws);
    document.querySelector('.dock-switcher-header .close-btn').click();
    expect($('dock-fm-switcher')).toBeNull();
    toggleFmWindowSwitcher(a, ws);
    toggleFmWindowSwitcher(a, ws);
    expect($('dock-fm-switcher')).toBeNull();
    toggleFmWindowSwitcher(a, ws);
    vi.advanceTimersByTime(60);
    $('dock-fm-switcher').dispatchEvent(new Event('pointerdown', { bubbles: true }));
    a.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    expect($('dock-fm-switcher')).not.toBeNull();
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    expect($('dock-fm-switcher')).toBeNull();
  });

  it('sits above the dock, or below the anchor when there is no room', () => {
    const a = anchor();
    a.getBoundingClientRect = () => ({ left: 5, width: 40, top: 900, bottom: 940 });
    toggleFmWindowSwitcher(a, [{ id: 'fm' }]);
    expect($('dock-fm-switcher').style.left).toBe('12px');
    expect($('dock-fm-switcher').style.top).toBe(`${900 - 180 - 12}px`);
    toggleFmWindowSwitcher(a, []);
    a.getBoundingClientRect = () => ({ left: 300, width: 40, top: 20, bottom: 60 });
    toggleFmWindowSwitcher(a, [{ id: 'fm' }]);
    expect($('dock-fm-switcher').style.top).toBe('72px');
  });
});

describe('dock item menu', () => {
  const items = () => [...document.querySelectorAll('#dock-item-ctx-menu .ctx-item')].map((i) => i.id || i.dataset.winId);

  it('has no menu for home and the notification center', () => {
    showDockItemContextMenu(0, 0, 'home', 'Home', true, false);
    showDockItemContextMenu(0, 0, 'notif', 'N', true, false);
    showDockItemContextMenu(0, 0, '', 'N', true, false);
    expect($('dock-item-ctx-menu')).toBeNull();
  });

  it('offers pin, open or close for an ordinary app', async () => {
    showDockItemContextMenu(100, 500, 'vm', 'VMs', false, false);
    expect(items()).toEqual(['dock-ctx-pin', 'dock-ctx-open']);
    expect($('dock-item-ctx-menu').textContent).toContain('Pin to Dock');
    window.openVmManager = vi.fn();
    $('dock-ctx-open').click();
    expect(window.openVmManager).toHaveBeenCalled();
    expect($('dock-item-ctx-menu').style.display).toBe('none');
    showDockItemContextMenu(100, 500, 'vm', 'VMs', true, true);
    expect(items()).toEqual(['dock-ctx-pin', 'dock-ctx-close']);
    expect($('dock-item-ctx-menu').textContent).toContain('Unpin from Dock');
    $('dock-ctx-close').click();
    expect(DockManager.closeWindow).toHaveBeenCalledWith('vm');
    showDockItemContextMenu(100, 500, 'stack-x', 'X', true, false);
    $('dock-ctx-open').click();
    $('dock-ctx-pin').click();
    expect(DockManager.togglePin).toHaveBeenCalledWith('stack-x');
  });

  it('File Explorer lists its windows, opens a new one and closes them all', () => {
    const w1 = { id: 'fm', title: 'Photos', el: fmWindow('fm', '/p') };
    DockManager.windows = { fm: w1 };
    DockManager.activeId = 'fm';
    showDockItemContextMenu(100, 500, 'fm', 'Files', true, true, [w1, { id: 'fm-2' }]);
    expect(items()).toEqual(['dock-ctx-pin', 'dock-ctx-new-window', 'fm', 'fm-2', 'dock-ctx-close-all']);
    expect($('dock-item-ctx-menu').textContent).toContain('✓');
    expect(document.querySelector('[data-win-id="fm-2"]').textContent).toContain('File Explorer');
    window.openNewFileManagerWindow = vi.fn();
    $('dock-ctx-new-window').click();
    expect(window.openNewFileManagerWindow).toHaveBeenCalled();
    document.querySelector('[data-win-id="fm"]').click();
    expect(DockManager.restore).toHaveBeenCalledWith('fm');
    expect(bringToFront).toHaveBeenCalledWith(w1.el.querySelector('.file-manager-window'));
    document.querySelector('[data-win-id="fm-2"]').click();
    expect(DockManager.restore).toHaveBeenCalledTimes(1);
    $('dock-ctx-close-all').click();
    expect(DockManager.closeWindow.mock.calls).toEqual([['fm'], ['fm-2']]);
    window.closeAllFileManagerWindows = vi.fn();
    showDockItemContextMenu(100, 500, 'fm-3', 'Files', true, true, [w1]);
    $('dock-ctx-close-all').click();
    expect(window.closeAllFileManagerWindows).toHaveBeenCalled();
    delete window.openNewFileManagerWindow;
    showDockItemContextMenu(100, 500, 'file-manager-window-2', 'Files', true, true);
    expect(items()).toEqual(['dock-ctx-pin', 'dock-ctx-new-window', 'dock-ctx-close']);
    $('dock-ctx-new-window').click();
    showDockItemContextMenu(100, 500, 'fm', 'Files', false, false, []);
    expect(items()).toEqual(['dock-ctx-pin', 'dock-ctx-new-window', 'dock-ctx-open']);
  });

  it('hides on a click outside, not inside', () => {
    vi.useFakeTimers();
    showDockItemContextMenu(100, 500, 'vm', 'VMs', false, false);
    vi.advanceTimersByTime(150);
    $('dock-item-ctx-menu').dispatchEvent(new Event('pointerdown', { bubbles: true }));
    expect($('dock-item-ctx-menu').style.display).toBe('block');
    document.body.dispatchEvent(new Event('click', { bubbles: true }));
    expect($('dock-item-ctx-menu').style.display).toBe('none');
  });
});
