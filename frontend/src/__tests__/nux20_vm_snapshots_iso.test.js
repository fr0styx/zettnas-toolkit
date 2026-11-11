/** NUX-20: the VM snapshots and backups dialog and the ISO library read as plain, translatable words. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { openVmSnapshotsModal, openIsoManagerModal, OFFICIAL_ISO_CATALOG } from '../components/vm-manager.js';
import { vmState } from '../components/vm/state.js';
import { api } from '../api.js';
import { showConfirmToast } from '../toast.js';

vi.mock('../api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  auth: { hasToken: vi.fn().mockReturnValue(true), getToken: vi.fn(() => 'x') },
}));

// showDangerConfirm is the same question, marked destructive (SET-00): one mock records both
vi.mock('../toast.js', () => {
  const ask = vi.fn();
  return {
    showToast: vi.fn(),
    showConfirmToast: ask,
    showDangerConfirm: ask,
    showPromptToast: vi.fn(),
    showBottomSheet: vi.fn(),
  };
});

const flush = () => new Promise((r) => setTimeout(r, 0));
const VM = { id: 'vm1', name: 'files', state: 'stopped' }; // snapshot actions are open only while it is off

describe('snapshots and backups (NUX-20)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('lists snapshots by type and asks before going back or deleting', async () => {
    api.get.mockResolvedValue([
        { name: 'before-update', date: '2026-11-01 10:00', size_formatted: '1 GB', is_live: true },
        { name: 'clean', created_at: '2026-10-01', is_live: false },
      ]);
    await openVmSnapshotsModal('vm1', VM);
    await flush();
    const modal = document.getElementById('modal-vm-snapshots');
    const text = modal.textContent;
    for (const w of ['Snapshots (QCOW2)', 'Backups (.tar.gz)', 'Snapshots of this VM', 'New snapshot', 'Taken', 'Type', 'Memory and disk', 'Disk only', 'Full VM backups']) {
      expect(text).toContain(w);
    }
    expect(modal.querySelector('#btn-cancel-take-snapshot').textContent).toBe('Cancel');
    expect(modal.querySelector('#btn-submit-take-snapshot').textContent).toBe('Save Snapshot');

    modal.querySelector('.btn-snap-revert').click();
    expect(showConfirmToast.mock.calls.at(-1)[0]).toBe('Go back to the snapshot “before-update” of files? Changes made since then are lost.');
    modal.querySelector('.btn-snap-del').click();
    expect(showConfirmToast.mock.calls.at(-1)[0]).toBe('Delete the snapshot “before-update”? This can’t be undone.');
  });

  it('says when the snapshots could not be loaded', async () => {
    api.get.mockRejectedValueOnce(new Error('disk busy'));
    await openVmSnapshotsModal('vm1', VM);
    await flush();
    expect(document.getElementById('vm-snapshots-container').textContent).toBe('Could not load the snapshots: disk busy');
    api.get.mockRejectedValueOnce({ detail: 'no qemu-img' });
    await openVmSnapshotsModal('vm1', VM);
    await flush();
    expect(document.getElementById('vm-snapshots-container').textContent).toBe('Could not load the snapshots: no qemu-img');
  });

  it('lists backups, says when there are none, and asks before restoring or deleting', async () => {
    api.get.mockResolvedValue([]);
    await openVmSnapshotsModal('vm1', VM);
    await flush();
    const modal = document.getElementById('modal-vm-snapshots');

    api.get.mockResolvedValueOnce({ backups: [] });
    modal.querySelector('#tab-btn-backups').click();
    await flush();
    expect(modal.querySelector('#vm-backups-container').textContent.trim()).toContain('No backups of this VM yet. “Back up now” saves');

    api.get.mockResolvedValueOnce({ backups: [{ id: 'bk-1', filename: 'files.tar.gz', created_at_iso: '2026-11-02', size_formatted: '3 GB' }] });
    modal.querySelector('#tab-btn-backups').click();
    await flush();
    const box = modal.querySelector('#vm-backups-container');
    expect(box.textContent).toContain('Backup / file');
    expect(box.textContent).toContain('Created');
    expect(box.querySelector('.btn-bk-restore').textContent.trim()).toBe('Restore');
    expect(box.querySelector('.btn-bk-del').textContent.trim()).toBe('Delete');
    box.querySelector('.btn-bk-restore').click();
    expect(showConfirmToast.mock.calls.at(-1)[0]).toBe('Restore files from the backup “bk-1”? Its disks and settings are replaced by the backup’s.');
    box.querySelector('.btn-bk-del').click();
    expect(showConfirmToast.mock.calls.at(-1)[0]).toBe('Delete the backup “bk-1”? This can’t be undone.');

    api.get.mockRejectedValueOnce(new Error('offline'));
    modal.querySelector('#tab-btn-backups').click();
    await flush();
    expect(box.textContent).toBe('Could not load the backups: offline');
    api.get.mockRejectedValueOnce({ detail: 'gone' });
    modal.querySelector('#tab-btn-backups').click();
    await flush();
    expect(box.textContent).toBe('Could not load the backups: gone');
  });
});

describe('ISO library (NUX-20)', () => {
  const first = OFFICIAL_ISO_CATALOG[0];

  beforeEach(() => {
    vi.clearAllMocks();
    document.getElementById('modal-iso-manager')?.remove();
    document.body.innerHTML = '';
    delete window.DockManager;
    api.get.mockReset();
    api.get.mockResolvedValue([]);
  });
  afterEach(() => {
    vi.useRealTimers();
    vmState.isos = [];
  });

  it('names the tabs, the upload area and an empty folder', async () => {
    vmState.isos = [];
    await openIsoManagerModal('local');
    const modal = document.getElementById('modal-iso-manager');
    const text = modal.textContent;
    for (const w of ['ISO library', 'Download catalog', 'On this NAS (/mnt/user/isos)', 'Drag ISO files here to upload them', 'Saved to:', '.iso and .img files up to 50 GB', 'Choose an ISO file…', 'Images in /mnt/user/isos', 'Refresh']) {
      expect(text).toContain(w);
    }
    expect(modal.querySelector('#local-iso-list').textContent).toBe('No ISO images in /mnt/user/isos yet.');
    expect(modal.querySelector(`#prog-stat-${first.id}`).textContent).toBe('Ready');
    expect(modal.querySelector(`.btn-dl-catalog[data-id="${first.id}"]`).textContent.trim()).toBe('⬇ Download');
  });

  it('marks an image already on the NAS and asks before deleting it', async () => {
    vmState.isos = [{ name: first.filename, path: `/mnt/user/isos/${first.filename}`, size_formatted: '2.6 GB' }];
    await openIsoManagerModal('local');
    const modal = document.getElementById('modal-iso-manager');
    const card = modal.querySelector(`.btn-dl-catalog[data-id="${first.id}"]`).closest('.catalog-card');
    expect(card.textContent).toContain('✓ On this NAS');
    expect(card.textContent).toContain('Downloaded to /mnt/user/isos');
    expect(card.querySelector('.btn-boot-catalog-iso').textContent.trim()).toBe('▶ Create VM');
    expect(card.querySelector('.btn-dl-catalog').textContent.trim()).toBe('✓ Ready');
    expect(modal.querySelector('.btn-boot-iso').textContent).toBe('▶ Create VM');
    modal.querySelector('.btn-delete-iso').click();
    expect(showConfirmToast.mock.calls.at(-1)[1]).toBe(`Delete “${first.filename}” from storage? This can’t be undone.`);
  });

  it('shows a download’s progress and why it failed', async () => {
    vi.useFakeTimers();
    vmState.isos = [];
    await openIsoManagerModal('catalog');
    const modal = document.getElementById('modal-iso-manager');
    const stat = () => modal.querySelector(`#prog-stat-${first.id}`).textContent;

    api.post.mockResolvedValueOnce({ task_id: 'tk1' });
    modal.querySelector(`.btn-dl-catalog[data-id="${first.id}"]`).click();
    await vi.advanceTimersByTimeAsync(0);
    api.get.mockResolvedValueOnce([{ catalog_id: first.id, status: 'downloading', speed_mb_s: 12, progress_pct: 40 }]);
    await vi.advanceTimersByTimeAsync(800);
    expect(stat()).toBe('Downloading… 12 MB/s (40%)');
    api.get.mockResolvedValueOnce([{ catalog_id: first.id, status: 'downloading' }]);
    await vi.advanceTimersByTimeAsync(800);
    expect(stat()).toBe('Downloading… 0 MB/s (0%)');
    api.get.mockResolvedValueOnce([{ catalog_id: first.id, status: 'checksum_mismatch' }]);
    await vi.advanceTimersByTimeAsync(800);
    expect(stat()).toBe('Failed: the checksum did not match');

    api.post.mockResolvedValueOnce({ task_id: 'tk2' });
    modal.querySelector(`.btn-dl-catalog[data-id="${first.id}"]`).click();
    await vi.advanceTimersByTimeAsync(0);
    api.get.mockResolvedValueOnce([{ task_id: 'tk2', status: 'failed', error: 'mirror down' }]);
    await vi.advanceTimersByTimeAsync(800);
    expect(stat()).toBe('Failed: mirror down');

    api.post.mockRejectedValueOnce(new Error('no route'));
    modal.querySelector(`.btn-dl-catalog[data-id="${first.id}"]`).click();
    await vi.advanceTimersByTimeAsync(0);
    expect(stat()).toBe('Error: no route');
  });
});
