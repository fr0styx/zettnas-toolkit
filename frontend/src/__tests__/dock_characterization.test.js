// ARC-5: the dock and window manager keeps its exports, globals, geometry and rendered pieces
// while the 4,600-line module is split up. Snapshots in __snapshots__/dock/ were recorded
// before the split; update them only for an intended change (npx vitest run -u <this file>).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api.js', () => {
  const api = { get: vi.fn(async () => ({})), post: vi.fn(async () => ({})), put: vi.fn(async () => ({})), delete: vi.fn(async () => ({})) };
  return { api, default: api, auth: { getToken: () => 'test-token', getUser: () => ({ username: 'admin', display_name: 'Admin', role: 'superadmin' }) } };
});

// the user menu loads these lazily; stubs keep the test from outliving its imports
vi.mock('../components/users.js', () => ({ updateUserInterfaceElements: vi.fn() }));
vi.mock('../components/session.js', () => ({ updateUserInterfaceElements: vi.fn() }));
vi.mock('../components/auth.js', () => ({ lockDesktop: vi.fn(), switchUser: vi.fn(), logout: vi.fn() }));

import * as dock from '../components/dock.js';
import { state } from '../state.js';

const SNAP = './__snapshots__/dock';
const DOCK_HTML = `
  <div id="os-dock-container" class="os-dock-container dock-pos-bottom"><div id="os-dock" class="os-dock active"></div></div>
  <div id="topbar-user-pill"><span id="topbar-user-name">admin</span></div>
  <div id="notification-center"><div id="notif-center-list"></div><span id="dock-notif-badge"></span></div>
  <div class="desktop-icons-container"></div>`;

const clean = (html) =>
  html
    .replace(/\b1[6-9]\d{11}\b/g, '<ts>')
    .replace(/>\s+</g, '><')
    .replace(/(left|top|width|height): -?\d+(\.\d+)?px/g, '$1: <px>');

describe('Dock characterization (ARC-5)', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.className = '';
    document.body.innerHTML = DOCK_HTML;
    vi.useFakeTimers({ now: new Date('2026-10-26T12:00:00Z') });
  });
  afterEach(async () => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    await new Promise((r) => setTimeout(r, 20)); // let lazy imports settle
    document.body.innerHTML = '';
  });

  it('exports and registers the same names', async () => {
    const surface = Object.keys(dock)
      .sort()
      .map((k) => `${k}: ${typeof dock[k]}${typeof dock[k] === 'function' ? `(${dock[k].length})` : ''}`);
    const globals = [
      'DockManager', 'bringToFront', 'openConsoleWindow', 'toggleNotificationCenter', 'renderNotificationCenter',
      'resetCheckedEventsState', 'markEventChecked', 'isEventChecked', 'saveWindowBounds', 'loadSavedWindowBounds',
      'saveOpenWindowsState', 'restoreOpenWindowsState', 'setWindowRestorationComplete', 'applyDockSettings',
      'initDockSettingsControls', 'getDockSettings', 'initParabolicDockMagnification', 'getActiveWindowElement',
      'restoreWindowSnap', 'getCurrentWorkspace', 'switchWorkspace', 'initWorkspaceSwitcher',
    ].map((g) => `window.${g}: ${typeof window[g]}`);
    await expect([...surface, '', ...globals].join('\n') + '\n').toMatchFileSnapshot(`${SNAP}/exports.txt`);
  });

  it('computes the same geometry and event keys', async () => {
    const zones = ['left', 'right', 'top', 'bottom', 'top-left', 'top-right', 'bottom-left', 'bottom-right', 'maximize', 'center', 'nonsense'];
    const geometry = Object.fromEntries(zones.map((z) => [z, dock.getSnapGeometry(z)]));
    const points = [[2, 300], [1020, 300], [500, 50], [500, 760], [3, 52], [1020, 52], [3, 760], [1020, 760], [500, 400]];
    const snapZones = points.map(([x, y]) => dock.evaluateSnapZone(x, y));
    const events = [
      { ts: 1790000000, title: 'Disk sdb hot', level: 'warning' },
      { ts: 1790000100, title: 'Backup done', level: 'info', message: 'nightly' },
    ];
    const keys = events.map((e) => dock.getEventKey(e));
    const before = events.map((e) => dock.isEventChecked(e));
    dock.markEventChecked(events[0], false);
    const after = events.map((e) => dock.isEventChecked(e));
    dock.resetCheckedEventsState();
    const reset = events.map((e) => dock.isEventChecked(e));
    const apps = JSON.parse(JSON.stringify(dock.KNOWN_APPS));
    const out = { geometry, snapZones, keys, before, after, reset, apps, settings: dock.getDockSettings() };
    await expect(JSON.stringify(out, null, 1) + '\n').toMatchFileSnapshot(`${SNAP}/geometry.json`);
  });

  it('renders the dock, its menus and the notification centre the same', async () => {
    const pieces = {};
    const mk = (id, title) => {
      const el = document.createElement('div');
      el.id = id;
      el.className = 'os-window';
      el.innerHTML = `<div class="os-window-header"><span class="os-window-title">${title}</span></div>`;
      document.body.appendChild(el);
      return el;
    };
    dock.DockManager.register('file-manager-window', mk('file-manager-window', 'Files'), 'folder', 'File Explorer');
    dock.DockManager.register('vm', mk('vm', 'VMs'), 'screen', 'Virtual Machines', true);
    dock.DockManager.pinApp('management');
    dock.DockManager.render();
    pieces.dock = clean(document.getElementById('os-dock').outerHTML);

    dock.showDockItemContextMenu(100, 700, 'file-manager-window', 'File Explorer', false, true, []);
    pieces.contextMenu = clean([...document.querySelectorAll('.dock-context-menu, [class*=context-menu]')].map((m) => m.outerHTML).join('\n'));

    dock.applyDockSettings('left', true, 1.6, 'large', true, false);
    pieces.settings = `${document.body.className} | ${document.getElementById('os-dock-container').className} | ${JSON.stringify(dock.getDockSettings())}`;

    state.latestStats = {
      events: [
        { ts: 1790000000, title: 'Disk sdb hot', level: 'warning', message: '52 C' },
        { ts: 1790000100, title: 'Backup done', level: 'info', message: 'nightly' },
        { ts: 1790000200, title: 'Pool degraded', level: 'error', message: 'sdc missing' },
      ],
    };
    dock.renderNotificationCenter();
    pieces.notifications = clean(document.getElementById('notification-center')?.outerHTML || '');

    const anchor = document.getElementById('topbar-user-pill');
    dock.toggleUserProfileFlyout(anchor);
    pieces.userFlyout = clean([...document.querySelectorAll('[id*=flyout], [class*=flyout]')].map((m) => m.outerHTML).join('\n'));

    for (const [name, html] of Object.entries(pieces)) {
      await expect(html + '\n').toMatchFileSnapshot(`${SNAP}/${name}.html`);
    }
  });
});
