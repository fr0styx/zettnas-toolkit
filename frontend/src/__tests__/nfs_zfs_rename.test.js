
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  openCreateStoragePoolModal,
  openCreateNetworkShareModal,
  openRenameStoragePoolModal,
  renderStructuredPoolsTopology,
} from '../components/chassis-visualizer.js';
import { api } from '../api.js';

describe('NFS Exports, OpenZFS RAIDZ Provisioning & Storage Pool Renaming', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <!-- Create Storage Pool Modal -->
      <div id="modal-create-storage-pool" class="smart-modal-backdrop" style="display:none;">
        <div class="smart-modal-window">
          <div class="smart-modal-header">
            <button id="modal-create-pool-close-btn"></button>
          </div>
          <form id="create-pool-form">
            <input id="create-pool-name" value="tank" />
            <select id="create-pool-fs">
              <option value="btrfs">Btrfs</option>
              <option value="zfs">OpenZFS</option>
            </select>
            <select id="create-pool-profile">
              <option value="raid1">RAID 1</option>
            </select>
            <div id="create-pool-disks-container"></div>
            <input id="create-pool-mountpoint" value="/mnt/storage/tank" />
            <div id="create-pool-error-box" style="display:none;"></div>
            <button type="button" id="modal-create-pool-cancel-btn">Cancel</button>
            <button type="submit" id="create-pool-submit-btn">Submit</button>
          </form>
        </div>
      </div>

      <!-- Rename Storage Pool Modal -->
      <div id="modal-rename-storage-pool" class="smart-modal-backdrop" style="display:none;">
        <div class="smart-modal-window">
          <div class="smart-modal-header">
            <button id="modal-rename-pool-close-btn"></button>
          </div>
          <form id="rename-pool-form">
            <input id="rename-pool-current-name" disabled />
            <input id="rename-pool-new-name" />
            <div id="rename-pool-error-box" style="display:none;"></div>
            <button type="button" id="modal-rename-pool-cancel-btn">Cancel</button>
            <button type="submit" id="rename-pool-submit-btn">Apply Rename</button>
          </form>
        </div>
      </div>

      <!-- Create Network Share Modal -->
      <div id="modal-create-network-share" class="smart-modal-backdrop" style="display:none;">
        <div class="smart-modal-window">
          <div class="smart-modal-header">
            <button id="modal-create-share-close-btn"></button>
          </div>
          <form id="create-share-form">
            <input id="create-share-name" value="k8s_sql" />
            <input id="create-share-path" value="/mnt/storage/k8s_sql" />
            <input id="create-share-comment" value="Kubernetes SQL PVC" />
            <select id="create-share-security"><option value="public">Public</option></select>
            <input type="checkbox" id="create-share-readonly" />
            <input type="checkbox" id="create-share-export-smb" checked />
            <input type="checkbox" id="create-share-export-nfs" />
            <input type="checkbox" id="create-share-timemachine" />

            <div id="create-share-nfs-opts" style="display:none;">
              <select id="create-share-nfs-squash">
                <option value="no_root_squash">no_root_squash</option>
                <option value="root_squash">root_squash</option>
              </select>
              <select id="create-share-nfs-sync">
                <option value="sync">sync</option>
                <option value="async">async</option>
              </select>
              <input id="create-share-nfs-anonuid" value="999" />
              <input id="create-share-nfs-anongid" value="999" />
              <input id="create-share-nfs-clients" value="10.244.0.0/16" />
            </div>

            <div id="create-share-error-box" style="display:none;"></div>
            <button type="button" id="modal-create-share-cancel-btn">Cancel</button>
            <button type="submit" id="create-share-submit-btn">Submit</button>
          </form>
        </div>
      </div>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('updates profile options dynamically when OpenZFS is selected', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([
      { dev: 'sda', size: '2 TB', model: 'WD Red' },
      { dev: 'sdb', size: '2 TB', model: 'WD Red' },
      { dev: 'sdc', size: '2 TB', model: 'WD Red' },
      { dev: 'sdd', size: '2 TB', model: 'WD Red' },
    ]);

    await openCreateStoragePoolModal();

    const fsSelect = document.getElementById('create-pool-fs');
    const profileSelect = document.getElementById('create-pool-profile');

    // Switch to zfs
    fsSelect.value = 'zfs';
    fsSelect.dispatchEvent(new Event('change'));

    expect(profileSelect.innerHTML).toContain('raidz2');
    expect(profileSelect.innerHTML).toContain('raidz1');
    expect(profileSelect.innerHTML).toContain('raidz3');
    expect(profileSelect.innerHTML).toContain('mirror');
  });

  it('toggles NFS options section and submits granular root squash parameters', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'created' });

    openCreateNetworkShareModal();

    const nfsCheckbox = document.getElementById('create-share-export-nfs');
    const nfsOpts = document.getElementById('create-share-nfs-opts');

    expect(nfsOpts.style.display).toBe('none');

    // Check NFS
    nfsCheckbox.checked = true;
    nfsCheckbox.dispatchEvent(new Event('change'));
    expect(nfsOpts.style.display).toBe('flex');

    // Submit form
    const form = document.getElementById('create-share-form');
    form.dispatchEvent(new Event('submit'));

    expect(postSpy).toHaveBeenCalledWith('/api/storage/shares', {
      name: 'k8s_sql',
      path: '/mnt/storage/k8s_sql',
      comment: 'Kubernetes SQL PVC',
      security: 'public',
      read_only: false,
      export_smb: true,
      export_nfs: true,
      quota_gb: 0,
      user_permissions: {},
      nfs_squash: 'no_root_squash',
      nfs_anonuid: 999,
      nfs_anongid: 999,
      nfs_sync: true,
      nfs_clients: '10.244.0.0/16',
    });
  });

  it('opens Rename Storage Pool modal and dispatches rename API request', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'renamed', old_name: 'old_tank', new_name: 'vault_tank' });
    const successCb = vi.fn();

    openRenameStoragePoolModal('old_tank', 'Old Tank Pool', successCb);

    const currentNameInput = document.getElementById('rename-pool-current-name');
    const newNameInput = document.getElementById('rename-pool-new-name');
    const form = document.getElementById('rename-pool-form');

    expect(currentNameInput.value).toBe('Old Tank Pool');

    // Fill new name and submit
    newNameInput.value = 'vault_tank';
    form.dispatchEvent(new Event('submit'));

    await Promise.resolve();

    expect(postSpy).toHaveBeenCalledWith('/api/storage/pools/old_tank/rename', {
      new_name: 'vault_tank',
    });
    expect(successCb).toHaveBeenCalled();
  });

  it('renders Rename button in pool action controls when not in observer mode', () => {
    const container = document.createElement('div');
    const mockData = {
      platform: 'generic_linux',
      is_observer_mode: false,
      pools: [
        {
          id: 'tank',
          name: 'OpenZFS Tank',
          fs_type: 'zfs',
          fs_profile: 'raidz2',
          status: 'HEALTHY',
          used_bytes: 4000000000000,
          total_bytes: 8000000000000,
          free_bytes: 4000000000000,
          used_pct: 50.0,
          parity_protected: true,
          members: [],
        },
      ],
    };

    renderStructuredPoolsTopology(container, mockData);

    const renameBtn = container.querySelector('.btn-pool-rename');
    expect(renameBtn).not.toBeNull();
    expect(renameBtn.textContent).toContain('Rename');
    expect(renameBtn.dataset.poolId).toBe('tank');
  });
});
