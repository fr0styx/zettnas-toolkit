/** ARC-26: what the Containers window's row buttons do (update, back up, start/stop, select). */
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
import { showToast, showConfirmToast, showBottomSheet } from '../toast.js';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const byId = (id) => document.getElementById(id);
const lastToast = () => showToast.mock.calls.at(-1);
function rowButton(action, name = 'web', id = 'c1') {
  const btn = document.createElement('button');
  btn.className = 'btn-container-act';
  Object.assign(btn.dataset, { id, name, action });
  btn.innerHTML = '<span>icon</span>';
  const td = document.createElement('td');
  td.appendChild(btn);
  const tr = document.createElement('tr');
  tr.appendChild(td);
  byId('cw-docker-containers-tbody').appendChild(tr);
  return btn;
}

describe('Containers window row actions', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="os-dock-container"><div id="os-dock"></div></div>';
    window._containersManagerInitialized = false;
    window.DockManager = DockManager;
    DockManager.windows = {};
    _resetCwAutoRefreshForTesting();
    vi.clearAllMocks();
    vi.spyOn(api, 'get').mockResolvedValue({ containers: {} });
    initContainersManager();
    renderContainersWindowTable([{ id: 'c1', name: 'web', image: 'nginx', state: 'running', stack: 'site' }]);
  });
  afterEach(() => {
    stopCwAutoRefresh();
    _resetCwAutoRefreshForTesting();
    _setCwUpdatesCacheForTesting(null);
    vi.restoreAllMocks();
  });

  it('updates one container after asking, and puts the button back when it fails', async () => {
    const btn = rowButton('update-single');
    btn.click();
    const onOk = showConfirmToast.mock.calls.at(-1)[2];
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({});
    await onOk();
    expect(post).toHaveBeenCalledWith('/api/docker/containers/c1/update-image');
    expect(showToast.mock.calls.some(([m, k]) => k === 'success' && m.includes('web'))).toBe(true);

    const again = rowButton('update-single');
    again.click();
    post.mockRejectedValueOnce(new Error('pull failed'));
    await showConfirmToast.mock.calls.at(-1)[2]();
    expect(lastToast()).toEqual(['Update failed: pull failed', 'error']);
    expect(again.disabled).toBe(false);
    expect(again.innerHTML).toBe('<span>icon</span>');
  });

  it('backs up an app and names the archive', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ backup: { archive_file: 'web.tar.gz', archive_size_formatted: '3 MB' } });
    const btn = rowButton('backup');
    btn.click();
    await vi.waitFor(() => expect(lastToast()[1]).toBe('success'));
    expect(lastToast()[0]).toContain('web.tar.gz, 3 MB');
    expect(post).toHaveBeenCalledWith('/api/docker/containers/c1/backup');
    post.mockResolvedValueOnce({});
    btn.click();
    await vi.waitFor(() => expect(lastToast()[0]).toContain('archive.tar.gz'));
    post.mockRejectedValueOnce(new Error('disk full'));
    btn.click();
    await vi.waitFor(() => expect(lastToast()).toEqual(['Backup failed: disk full', 'error']));
    expect(btn.disabled).toBe(false);
  });

  it('starts and stops, and says when that fails', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({});
    const btn = rowButton('stop');
    btn.click();
    await vi.waitFor(() => expect(lastToast()[1]).toBe('success'));
    expect(post).toHaveBeenCalledWith('/api/docker/containers/c1/action', { action: 'stop' });
    post.mockRejectedValueOnce(new Error('no such container'));
    const start = rowButton('start');
    start.click();
    await vi.waitFor(() => expect(lastToast()[1]).toBe('error'));
    expect(lastToast()[0]).toContain('no such container');
    expect(start.disabled).toBe(false);
    expect(start.style.opacity).toBe('1');
  });

  it('the more menu items open the right places', () => {
    _setCwUpdatesCacheForTesting({ containers: { web: { has_update: true } } });
    const more = rowButton('more-sheet');
    const update = rowButton('update-single');
    const backup = rowButton('backup');
    more.parentElement.append(update, backup);
    const clicked = [];
    update.addEventListener('click', () => clicked.push('update'));
    backup.addEventListener('click', () => clicked.push('backup'));
    vi.spyOn(api, 'post').mockResolvedValue({});
    more.click();
    const items = showBottomSheet.mock.calls.at(-1)[0].items;
    items.find((i) => i.label === 'Update to the latest image').onClick();
    items.find((i) => i.label === 'Back up app data and settings').onClick();
    expect(clicked).toEqual(['update', 'backup']);
    rowButton('more-sheet', 'ghost', 'cX').click(); // not in the list: nothing to show
    expect(showBottomSheet).toHaveBeenCalledTimes(1);
  });

  it('ticking a row shows the bulk bar with the count', () => {
    const tbody = byId('cw-docker-containers-tbody');
    const box = tbody.querySelector('.docker-row-select');
    expect(box).toBeTruthy();
    box.checked = true;
    box.dispatchEvent(new Event('change', { bubbles: true }));
    expect(box.closest('tr').classList.contains('docker-row-selected')).toBe(true);
    expect(byId('cw-docker-bulk-bar').style.display).toBe('flex');
    box.checked = false;
    box.dispatchEvent(new Event('change', { bubbles: true }));
    expect(byId('cw-docker-bulk-bar').style.display).toBe('none');
  });

  it('ignores a button without an action or id', () => {
    const btn = rowButton('', 'web', '');
    btn.click();
    expect(showToast).not.toHaveBeenCalled();
  });
});
