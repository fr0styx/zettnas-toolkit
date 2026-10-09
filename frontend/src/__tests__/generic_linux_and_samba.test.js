import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  renderStructuredPoolsTopology,
  fetchAndRenderStorageTopology,
  fetchAndRenderNetworkShares,
  openCreateStoragePoolModal,
  openCreateNetworkShareModal,
  openSnapshotsModal,
} from '../components/chassis-visualizer.js';
import { api } from '../api.js';

describe('Sprint 5: Generic Linux Active Provisioner & Samba Engine (Frontend)', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    container?.remove();
    document.querySelectorAll('.smart-modal-backdrop').forEach((m) => m.remove());
    vi.restoreAllMocks();
  });

  it('renders Active Provisioner Mode banner and pool action controls', () => {
    const mockData = {
      platform: 'generic_linux',
      is_observer_mode: false,
      pools: [
        {
          id: 'vault',
          name: 'Vault Storage Pool',
          fs_type: 'btrfs',
          fs_profile: 'raid1',
          status: 'HEALTHY',
          used_bytes: 500000000000,
          total_bytes: 1000000000000,
          free_bytes: 500000000000,
          used_pct: 50.0,
          parity_protected: true,
          members: [
            { name: 'sdb', device: 'sdb', role: 'data', size_bytes: 500000000000, spundown: false, temp_c: 32 },
            { name: 'sdc', device: 'sdc', role: 'data', size_bytes: 500000000000, spundown: false, temp_c: 33 },
          ],
        },
      ],
    };

    renderStructuredPoolsTopology(container, mockData);

    expect(container.textContent).toContain('Active Provisioner Mode');
    expect(container.textContent).toContain('Vault Storage Pool');
    expect(container.textContent).toContain('BTRFS · RAID1');
    expect(container.textContent).toContain('Parity Protected');

    // Action buttons
    const scrubBtn = container.querySelector('.btn-pool-scrub');
    expect(scrubBtn).not.toBeNull();
    expect(scrubBtn.textContent).toContain('Scrub Pool');

    const snapsBtn = container.querySelector('.btn-pool-snaps');
    expect(snapsBtn).not.toBeNull();
    expect(snapsBtn.textContent).toContain('Snapshots');

    const destroyBtn = container.querySelector('.btn-pool-destroy');
    expect(destroyBtn).not.toBeNull();
    expect(destroyBtn.textContent).toContain('Destroy');
  });

  it('shows create pool and snapshots buttons when can_create_pools capability is true', async () => {
    // Setup header buttons in DOM
    const btnCreatePool = document.createElement('button');
    btnCreatePool.id = 'btn-create-storage-pool';
    btnCreatePool.style.display = 'none';
    document.body.appendChild(btnCreatePool);

    const btnSnapshots = document.createElement('button');
    btnSnapshots.id = 'btn-manage-snapshots';
    btnSnapshots.style.display = 'none';
    document.body.appendChild(btnSnapshots);

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/storage/pools') {
        return Promise.resolve({
          platform: 'generic_linux',
          is_observer_mode: false,
          pools: [],
        });
      }
      if (url === '/api/storage/platform') {
        return Promise.resolve({
          platform: 'generic_linux',
          capabilities: {
            is_observer_mode: false,
            can_create_pools: true,
            can_manage_shares: true,
          },
        });
      }
      return Promise.resolve({});
    });

    await fetchAndRenderStorageTopology(container);

    expect(btnCreatePool.style.display).toBe('inline-flex');
    expect(btnSnapshots.style.display).toBe('inline-flex');

    btnCreatePool.remove();
    btnSnapshots.remove();
  });

  it('renders network shares with delete action in active mode and binds delete event', async () => {
    const badge = document.createElement('span');
    badge.id = 'mgmt-shares-platform-badge';
    document.body.appendChild(badge);

    const btnCreateShare = document.createElement('button');
    btnCreateShare.id = 'btn-create-network-share';
    btnCreateShare.style.display = 'none';
    document.body.appendChild(btnCreateShare);

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/storage/shares') {
        return Promise.resolve({
          platform: 'generic_linux',
          is_observer_mode: false,
          shares: [
            {
              name: 'vault',
              comment: 'Linux Share',
              security: 'public',
              export_smb: true,
              mountpoint: '/mnt/storage/vault',
              used_bytes: 1000,
              free_bytes: 2000,
              total_bytes: 3000,
              used_pct: 33.3,
            },
          ],
        });
      }
      if (url === '/api/storage/platform') {
        return Promise.resolve({
          platform: 'generic_linux',
          capabilities: {
            is_observer_mode: false,
            can_manage_shares: true,
          },
        });
      }
      return Promise.resolve({});
    });

    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValue({ status: 'deleted' });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    await fetchAndRenderNetworkShares(container);

    expect(btnCreateShare.style.display).toBe('inline-flex');
    expect(badge.textContent).toContain('Active Provisioner');

    const delBtn = container.querySelector('.btn-share-delete');
    expect(delBtn).not.toBeNull();
    delBtn.click();

    expect(deleteSpy).toHaveBeenCalledWith('/api/storage/shares/vault');

    badge.remove();
    btnCreateShare.remove();
  });

  it('populates available member disks and provisions storage pool via modal', async () => {
    // Inject modal markup
    const modalHtml = `
      <div id="modal-create-storage-pool" class="smart-modal-backdrop" style="display:none;">
        <div class="smart-modal-window">
          <div class="smart-modal-header"></div>
          <form id="create-pool-form">
            <input type="text" id="create-pool-name" value="vault" />
            <select id="create-pool-fs"><option value="btrfs" selected>Btrfs</option></select>
            <select id="create-pool-profile"><option value="raid1" selected>RAID 1</option></select>
            <input type="text" id="create-pool-mountpoint" value="/mnt/storage/vault" />
            <div id="create-pool-disks-container"></div>
            <div id="create-pool-error-box" style="display:none;"></div>
            <button type="submit" id="create-pool-submit-btn">Submit</button>
            <button type="button" id="modal-create-pool-close-btn">Close</button>
            <button type="button" id="modal-create-pool-cancel-btn">Cancel</button>
          </form>
        </div>
      </div>
    `;
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = modalHtml;
    document.body.appendChild(tempDiv.firstElementChild);

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/system/disks') {
        return Promise.resolve([
          { name: 'sdb', dev: 'sdb', size: '1.0 TB', model: 'WDC_RED' },
          { name: 'sdc', dev: 'sdc', size: '1.0 TB', model: 'WDC_RED' },
        ]);
      }
      return Promise.resolve({});
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'provisioned', name: 'vault' });

    let successCalled = false;
    await openCreateStoragePoolModal(() => {
      successCalled = true;
    });

    const modal = document.getElementById('modal-create-storage-pool');
    expect(modal.style.display).toBe('flex');

    const checkboxes = modal.querySelectorAll('input[name="pool-disk"]');
    expect(checkboxes.length).toBe(2);
    checkboxes[0].checked = true;
    checkboxes[1].checked = true;

    const form = document.getElementById('create-pool-form');
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

    await new Promise((r) => setTimeout(r, 20));

    expect(postSpy).toHaveBeenCalledWith('/api/storage/pools', {
      name: 'vault',
      fs_type: 'btrfs',
      profile: 'raid1',
      disks: ['sdb', 'sdc'],
      mountpoint: '/mnt/storage/vault',
    });
    expect(successCalled).toBe(true);
  });
});
