import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock dependencies
vi.mock('../api.js', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
  auth: {
    getToken: vi.fn(() => 'test-token'),
  },
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn((msg, onConfirm) => onConfirm()),
}));

import { api } from '../api.js';
import { openVmSnapshotsModal } from '../components/vm-manager.js';

describe('VM Snapshots & Hyper-Backup UI Modal', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('renders modal with QCOW2 snapshots and takes a new snapshot', async () => {
    api.get.mockResolvedValueOnce({
      snapshots: [
        {
          name: 'snap-clean-install',
          date: '2026-10-19 12:00:00',
          size_formatted: '512 MB',
          is_live: false,
          description: 'Baseline OS installation',
        },
      ],
    });

    const targetVm = { id: 'vm-test-1', name: 'Ubuntu Test Server', state: 'stopped' };
    await openVmSnapshotsModal('vm-test-1', targetVm);

    const modal = document.getElementById('modal-vm-snapshots');
    expect(modal).not.toBeNull();
    expect(modal.innerHTML).toContain('Ubuntu Test Server');
    expect(modal.innerHTML).toContain('snap-clean-install');
    expect(modal.innerHTML).toContain('Baseline OS installation');

    // Trigger take snapshot form
    const btnTake = modal.querySelector('#btn-take-snapshot');
    const form = modal.querySelector('#vm-snap-create-form');
    expect(btnTake).not.toBeNull();
    btnTake.click();
    expect(form.style.display).not.toBe('none');

    // Submit new snapshot
    const nameInput = modal.querySelector('#vm-snap-name-input');
    const descInput = modal.querySelector('#vm-snap-desc-input');
    const btnSubmit = modal.querySelector('#btn-submit-take-snapshot');

    nameInput.value = 'snap-pre-upgrade';
    descInput.value = 'Before kernel upgrade';

    api.post.mockResolvedValueOnce({ success: true, name: 'snap-pre-upgrade' });
    api.get.mockResolvedValueOnce({ snapshots: [] });

    await btnSubmit.click();
    expect(api.post).toHaveBeenCalledWith('/api/vms/vm-test-1/snapshots', {
      name: 'snap-pre-upgrade',
      description: 'Before kernel upgrade',
    });
  });

  it('handles revert and delete snapshot actions', async () => {
    api.get.mockResolvedValueOnce({
      snapshots: [
        {
          name: 'snap-test-delete',
          date: '2026-10-19 12:30:00',
          size_formatted: '128 MB',
          is_live: true,
        },
      ],
    });

    const targetVm = { id: 'vm-test-2', name: 'Debian Worker', state: 'running' };
    await openVmSnapshotsModal('vm-test-2', targetVm);

    const modal = document.getElementById('modal-vm-snapshots');
    const revertBtn = modal.querySelector('.btn-snap-revert');
    const delBtn = modal.querySelector('.btn-snap-del');

    expect(revertBtn).not.toBeNull();
    expect(delBtn).not.toBeNull();

    // Revert
    api.post.mockResolvedValueOnce({ success: true });
    api.get.mockResolvedValueOnce({ snapshots: [] });
    revertBtn.click();
    expect(api.post).toHaveBeenCalledWith('/api/vms/vm-test-2/snapshots/snap-test-delete/revert');

    // Delete
    api.delete.mockResolvedValueOnce({ success: true });
    api.get.mockResolvedValueOnce({ snapshots: [] });
    delBtn.click();
    expect(api.delete).toHaveBeenCalledWith('/api/vms/vm-test-2/snapshots/snap-test-delete');
  });

  it('switches to Hyper-Backups tab and triggers backup creation', async () => {
    api.get.mockResolvedValueOnce({ snapshots: [] }); // initial snapshot load
    api.get.mockResolvedValueOnce({ backups: [] }); // tab switch backup load

    const targetVm = { id: 'vm-test-3', name: 'Alpine Micro', state: 'stopped' };
    await openVmSnapshotsModal('vm-test-3', targetVm);

    const modal = document.getElementById('modal-vm-snapshots');
    const tabBackups = modal.querySelector('#tab-btn-backups');
    const paneBackups = modal.querySelector('#vm-pane-backups');

    tabBackups.click();
    expect(paneBackups.style.display).toBe('flex');
    expect(api.get).toHaveBeenCalledWith('/api/vms/vm-test-3/backups');

    const btnCreateBackup = modal.querySelector('#btn-create-hyper-backup');
    api.post.mockResolvedValueOnce({ status: 'ok', backup: { id: 'vbk_123' } });
    api.get.mockResolvedValueOnce({ backups: [{ id: 'vbk_123', filename: 'Alpine_test.tar.gz' }] });

    await btnCreateBackup.click();
    expect(api.post).toHaveBeenCalledWith('/api/vms/vm-test-3/backup', { reason: 'on-demand' });
  });

  it('opens snapshots modal from Edit VM modal and verifies open class, z-index and SVG icons', async () => {
    const { openVmEditModal } = await import('../components/vm-manager.js');
    api.get.mockImplementation((url) => {
      if (url.includes('/budget')) return Promise.resolve({ safe_slider_max_gb: 16 });
      if (url.includes('/snapshots')) return Promise.resolve({ snapshots: [] });
      if (url.includes('/api/vms/vm-test-4')) return Promise.resolve({ id: 'vm-test-4', name: 'Server Four', ram_gb: 4 });
      return Promise.resolve({});
    });

    const targetVm = { id: 'vm-test-4', name: 'Server Four', state: 'stopped', ram_gb: 4 };
    await openVmEditModal('vm-test-4', targetVm);

    const editModal = document.getElementById('modal-vm-edit');
    expect(editModal).not.toBeNull();
    expect(editModal.classList.contains('open')).toBe(true);

    const btnManage = editModal.querySelector('#vm-edit-open-snapshots');
    expect(btnManage).not.toBeNull();
    expect(btnManage.classList.contains('btn-vm-action')).toBe(true);
    expect(btnManage.classList.contains('btn-vm-snapshots')).toBe(true);
    expect(btnManage.querySelector('svg')).not.toBeNull();
    expect(btnManage.textContent).toContain('Manage Snapshots');

    // Click Manage Snapshots
    btnManage.click();

    const snapModal = document.getElementById('modal-vm-snapshots');
    expect(snapModal).not.toBeNull();
    expect(snapModal.classList.contains('open')).toBe(true);
    expect(snapModal.style.display).toBe('flex');
    expect(snapModal.style.zIndex).toBe('9600');
    expect(snapModal.querySelector('.smart-modal-title svg')).not.toBeNull();
  });
});

