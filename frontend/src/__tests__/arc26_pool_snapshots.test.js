/** ARC-26 / NUX-20: a pool's snapshot window: list, take, go back, delete; its dialogs translated. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));
const { api } = await import('../api.js');
const { showToast, showConfirmToast } = await import('../toast.js');
const { openSnapshotsModal } = await import('../components/chassis-visualizer.js');

const byId = (id) => document.getElementById(id);
const SNAPS = [{ name: 'daily-1', path: '/mnt/pool/.snapshots/daily-1', created_at: 1767225600 }];
const lastToast = () => showToast.mock.calls.at(-1);

describe('pool snapshots window', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="modal-btrfs-snapshots"><div class="smart-modal-window"><div class="smart-modal-header"></div>
        <button id="modal-snapshots-close-btn"></button><input id="snap-name-input">
        <button id="btn-take-snapshot-submit"></button><div id="snapshots-list-mount"></div></div></div>`;
  });

  it('lists the snapshots, or says there are none or why not', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValueOnce([]);
    await openSnapshotsModal('p1');
    await vi.waitFor(() => expect(byId('snapshots-list-mount').textContent).toContain('No snapshots yet.'));
    get.mockRejectedValueOnce(new Error('pool offline'));
    await openSnapshotsModal('p1');
    await vi.waitFor(() => expect(byId('snapshots-list-mount').textContent).toContain('pool offline'));
    byId('modal-snapshots-close-btn').click();
    expect(byId('modal-btrfs-snapshots').style.display).toBe('none');
  });

  it('goes back to a snapshot after asking', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(SNAPS);
    await openSnapshotsModal('p1');
    await vi.waitFor(() => expect(document.querySelector('.btn-snap-restore')).toBeTruthy());
    document.querySelector('.btn-snap-restore').click();
    const [title, msg, onOk, , opts] = showConfirmToast.mock.calls.at(-1);
    expect(title).toBe('Go back to snapshot');
    expect(msg).toBe('Roll back to snapshot "daily-1"? The current state is saved first.');
    expect(opts.okText).toBe('Go back to snapshot');
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({});
    await onOk();
    expect(post).toHaveBeenCalledWith('/api/storage/pools/p1/snapshots/restore', { snapshot_name: 'daily-1' }, { confirmed: true });
    expect(lastToast()[1]).toBe('success');
    post.mockRejectedValueOnce(new Error(''));
    await onOk();
    expect(lastToast()).toEqual(['Could not go back to the snapshot', 'error']);
  });

  it('deletes a snapshot after asking', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(SNAPS);
    await openSnapshotsModal('p1');
    await vi.waitFor(() => expect(document.querySelector('.btn-snap-del')).toBeTruthy());
    document.querySelector('.btn-snap-del').click();
    const [title, msg, onOk] = showConfirmToast.mock.calls.at(-1);
    expect(title).toBe('Delete Snapshot');
    expect(msg).toBe('Delete snapshot "daily-1"?');
    const del = vi.spyOn(api, 'delete').mockResolvedValueOnce({});
    await onOk();
    expect(del).toHaveBeenCalledWith('/api/storage/pools/p1/snapshots/daily-1', { confirmed: true });
    del.mockRejectedValueOnce(new Error('busy'));
    await onOk();
    expect(lastToast()).toEqual(['busy', 'error']);
    del.mockRejectedValueOnce(new Error(''));
    await onOk();
    expect(lastToast()).toEqual(['Could not delete the snapshot', 'error']);
    document.querySelector('tbody').click(); // a click beside the buttons does nothing
  });

  it('takes a snapshot with a name or a made-up one', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(SNAPS);
    await openSnapshotsModal('p1');
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    byId('snap-name-input').value = 'before-update';
    await byId('btn-take-snapshot-submit').onclick();
    expect(post).toHaveBeenCalledWith('/api/storage/pools/p1/snapshots', { subvolume: '@shares', snapshot_name: 'before-update', readonly: true });
    expect(byId('snap-name-input').value).toBe('');
    await byId('btn-take-snapshot-submit').onclick();
    expect(post.mock.calls.at(-1)[1].snapshot_name).toMatch(/^snap-\d+$/);
    post.mockRejectedValueOnce(new Error(''));
    await byId('btn-take-snapshot-submit').onclick();
    expect(lastToast()).toEqual(['Could not take the snapshot', 'error']);
    post.mockRejectedValueOnce(new Error('no space'));
    await byId('btn-take-snapshot-submit').onclick();
    expect(lastToast()).toEqual(['no space', 'error']);
  });
});
