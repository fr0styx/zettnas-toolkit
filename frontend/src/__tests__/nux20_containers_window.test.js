/** NUX-20: the Containers window's toolbar, menus and update dialogs read as plain, translatable words. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  initContainersManager,
  renderContainersWindowTable,
  stopCwAutoRefresh,
  _resetCwAutoRefreshForTesting,
  _setCwUpdatesCacheForTesting,
} from '../components/containers-manager.js';
import { DockManager } from '../components/dock.js';
import { api } from '../api.js';
import { showConfirmToast, showBottomSheet } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const byId = (id) => document.getElementById(id);

function rowButton(action, name = 'web', id = 'c1') {
  const btn = document.createElement('button');
  btn.className = 'btn-container-act';
  btn.dataset.id = id;
  btn.dataset.name = name;
  btn.dataset.action = action;
  const wrap = document.createElement('td');
  wrap.appendChild(btn);
  const row = document.createElement('tr');
  row.appendChild(wrap);
  byId('cw-docker-containers-tbody').appendChild(row);
  return btn;
}

describe('Containers window (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="os-dock-container"><div id="os-dock"></div></div>';
    window._containersManagerInitialized = false;
    window.DockManager = DockManager;
    DockManager.windows = {};
    _resetCwAutoRefreshForTesting();
    vi.clearAllMocks();
  });
  afterEach(() => {
    stopCwAutoRefresh();
    _resetCwAutoRefreshForTesting();
    _setCwUpdatesCacheForTesting(null);
    vi.restoreAllMocks();
  });

  it('labels the toolbar, the bulk bar and the catalog filters', () => {
    initContainersManager();
    const text = byId('containers-manager-window').textContent;
    for (const w of ['Docker Socket Active', 'Live Sync', 'Total:', 'Running:', 'Stopped:', 'Updates:', 'Check for updates', 'Update all', 'Compose stacks', 'Clean up', 'selected', 'Pause', 'Resume', 'Smart home', 'Downloaders', 'Loading the app catalog…']) {
      expect(text).toContain(w);
    }
    expect(document.querySelector('[data-bulk="start"]').textContent).toBe('▶ Start');
  });

  it('says it is checking, and asks before updating everything', async () => {
    initContainersManager();
    let done;
    vi.spyOn(api, 'post').mockImplementation(() => new Promise((r) => { done = r; }));
    const check = byId('btn-cw-check-updates');
    check.click();
    expect(check.textContent).toContain('Checking…');
    done({ updates_available_count: 0 });

    byId('btn-cw-update-all').click();
    const [title, msg, , , opts] = showConfirmToast.mock.calls.at(-1);
    expect(title).toBe('Update all containers?');
    expect(msg).toBe('This pulls the latest images and updates every container that has an update.');
    expect(opts).toMatchObject({ okText: '↑ Update all', cancelText: 'Cancel' });
  });

  it('builds the More menu for a container', () => {
    initContainersManager();
    renderContainersWindowTable([
      { id: 'c1', name: 'web', image: 'nginx', state: 'running', stack: 'site' },
      { id: 'c2', name: 'bare', state: '' },
    ]);
    _setCwUpdatesCacheForTesting({ containers: { web: { has_update: true } } });
    rowButton('more-sheet').click();
    let sheet = showBottomSheet.mock.calls.at(-1)[0];
    const labels = sheet.items.map((i) => i.label);
    expect(labels).toEqual(expect.arrayContaining(['Manage stack: site', 'Update to the latest image', 'Back up app data and settings', 'Delete “web”']));
    expect(sheet.subtitle).toBe('State: RUNNING • nginx');

    rowButton('more-sheet', 'bare', 'c2').click();
    sheet = showBottomSheet.mock.calls.at(-1)[0];
    expect(sheet.subtitle).toBe('State:  • Docker container');
    expect(sheet.items.map((i) => i.label)).not.toContain('Update to the latest image');
  });

  it('asks before updating one container, with its name in bold', () => {
    initContainersManager();
    renderContainersWindowTable([{ id: 'c1', name: 'web', image: 'nginx', state: 'running' }]);
    rowButton('update-single').click();
    const [title, msg, , , opts] = showConfirmToast.mock.calls.at(-1);
    expect(title).toBe('Update “web”?');
    expect(msg).toContain('This pulls the latest image and updates <strong>web</strong> to its newest release.');
    expect(msg).toContain('Volumes, folders and environment settings stay as they are.');
    expect(opts).toMatchObject({ okText: '⬆️ Update now', cancelText: 'Cancel', allowHtml: true });
  });
});
