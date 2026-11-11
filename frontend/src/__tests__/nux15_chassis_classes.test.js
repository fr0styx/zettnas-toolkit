// NUX-15: the storage panes and dialogs drawn by chassis-visualizer.js use classes from
// Mission Control's sheet instead of inline styles; each state still renders with them.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  fetchAndRenderStorageTopology,
  fetchAndRenderRemoteStorage,
  openSftpUsersModal,
  openCreateStoragePoolModal,
} from '../components/chassis-visualizer.js';
import { api } from '../api.js';

let mount;
beforeEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '<div id="mount"></div>';
  mount = document.getElementById('mount');
});
afterEach(() => {
  document.body.innerHTML = '';
});

describe('chassis-visualizer markup on classes (NUX-15)', () => {
  it('shows external pools found on the drives, with and without a status', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/storage/pools') return { pools: [], platform: 'generic_linux' };
      if (url === '/api/storage/pools/discover') return { discovered_pools: [{ pool_id: 'old', fs_type: 'btrfs', status: 'ONLINE' }, { pool_id: 'usb' }] };
      if (url === '/api/storage/platform') return { can_look_for_pools: true };
      return {};
    });
    await fetchAndRenderStorageTopology(mount);
    expect(mount.querySelector('.external-pools-banner')).toBeNull(); // looked for on a press of the button (SET-09)
    mount.querySelector('[data-look-for-pools]').click();
    await new Promise((r) => setTimeout(r, 0));
    const notes = [...mount.querySelectorAll('.external-pools-banner .cv-xs-muted-2')].map((n) => n.textContent);
    expect(notes).toEqual(['(BTRFS · ONLINE)', '(ZFS)']);
  });

  it('marks a read-only WebDAV server', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/webdav/status') return { enabled: true, running: true, pid: 1, port: 8084, root_path: '/srv', read_only: true, quick_connect: {} };
      if (url === '/api/remotes') return [];
      return url.startsWith('/api/sftp/users') ? [] : { running: false, port: 2222 };
    });
    await fetchAndRenderRemoteStorage(mount);
    expect([...mount.querySelectorAll('strong.cv-strong')].map((n) => n.textContent)).toContain('Read-Only');
  });

  it('shows a stopped SFTP service in its dialog', async () => {
    document.body.insertAdjacentHTML('beforeend', `<div id="modal-sftp-users" style="display:none;"><div class="smart-modal-window">
      <div class="smart-modal-header"></div><button id="modal-sftp-close-btn"></button><button id="modal-sftp-close-bottom-btn"></button>
      <div id="sftp-status-text"></div><button id="btn-sftp-toggle-service"></button><span id="sftp-quick-connect-hint"></span>
      <button id="btn-copy-sftp-cmd"></button><div id="sftp-users-list"></div>
      <form id="sftp-add-user-form"><input id="sftp-new-username"><input id="sftp-new-password"><input type="checkbox" id="sftp-new-readonly"></form></div></div>`);
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/sftp/users' ? [] : { running: false, port: 2200 }));
    await openSftpUsersModal(() => {});
    await new Promise((r) => setTimeout(r, 10));
    const status = document.getElementById('sftp-status-text');
    expect(status.querySelector('.cv-muted').textContent).toContain('Stopped');
    expect(status.textContent).toContain('2200');
  });

  it('lists the free drives for a new pool', async () => {
    document.body.insertAdjacentHTML('beforeend', `<div id="modal-create-storage-pool" style="display:none;"><div class="smart-modal-window">
      <div class="smart-modal-header"></div><form id="create-pool-form"><input id="create-pool-name"><select id="create-pool-fs"><option value="btrfs" selected>Btrfs</option></select>
      <select id="create-pool-profile"><option value="raid1" selected>RAID 1</option></select><input id="create-pool-mountpoint">
      <div id="create-pool-disks-container"></div><div id="create-pool-error-box" style="display:none;"></div>
      <button type="submit" id="create-pool-submit-btn"></button><button type="button" id="modal-create-pool-close-btn"></button>
      <button type="button" id="modal-create-pool-cancel-btn"></button></form></div></div>`);
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url === '/api/storage/overview' ? { unassigned_disks: [{ dev: 'sdb', name: 'sdb', size: '1 TB', model: 'WD' }, { dev: 'loop0' }] } : {});
    await openCreateStoragePoolModal(() => {});
    await new Promise((r) => setTimeout(r, 10));
    const boxes = document.querySelectorAll('#create-pool-disks-container input[name="pool-disk"]');
    expect([...boxes].map((b) => b.value)).toEqual(['sdb']);
  });
});
