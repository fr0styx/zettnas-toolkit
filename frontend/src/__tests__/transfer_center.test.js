import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../api.js', () => ({ api: { post: vi.fn(), delete: vi.fn() } }));

import { transferCenter, taskLabel, taskStatus, formatDuration } from '../components/transfer-center.js';
import { showToast } from '../toast.js';
import { api } from '../api.js';
import { ZettEventBus } from '../event-bus.js';

const running = {
  id: 'a', status: 'running', action: 'copy', sources: ['/mnt/user/x', '/mnt/user/y'], destination: '/mnt/user/Movies',
  total_files: 40, processed_files: 12, total_bytes: 4 * 1024 ** 3, processed_bytes: 1024 ** 3, percent: 25, speed_bps: 50 * 1024 ** 2, eta_seconds: 80,
};

describe('transfer center', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = '';
    transferCenter.tasks.clear();
    transferCenter.watch.clear();
    transferCenter.host = null;
    showToast.mockClear();
    api.post.mockReset();
  });

  it('describes a running copy in words', () => {
    expect(taskLabel(running)).toBe('Copying 2 items to Movies');
    expect(taskLabel({ ...running, action: 'move' })).toBe('Moving 2 items to Movies');
    const s = taskStatus(running);
    expect(s).toContain('12 of 40 files');
    expect(s).toContain('1 GB of 4 GB');
    expect(s).toContain('1:20 left');
    expect(taskStatus({ ...running, total_files: 0, total_bytes: 0 })).toBe('Counting files… · 50 MB/s · 1:20 left');
    expect(taskStatus({ ...running, status: 'completed', result: { skipped: 3 } })).toBe('Done, 3 skipped');
    expect(taskStatus({ ...running, status: 'failed', error: 'disk full' })).toBe('Failed: disk full');
    expect(formatDuration(3725)).toBe('1:02:05');
  });

  it('starts a background transfer, opens the panel if it takes a while, and reports the end', async () => {
    api.post.mockResolvedValue({ status: 'ok', task_id: 't1', task: { ...running, id: 't1', percent: 0 } });
    const refresh = vi.fn();
    ZettEventBus.on('fm:refresh', refresh);
    const onDone = vi.fn();
    await transferCenter.startTransfer({ sources: ['/mnt/user/x'], destinationDir: '/mnt/user/Movies', action: 'copy', onDone });
    expect(api.post).toHaveBeenCalledWith('/api/fs/transfer/async', {
      sources: ['/mnt/user/x'], destination_dir: '/mnt/user/Movies', action: 'copy', collision_policy: 'merge',
    });
    expect(transferCenter.isOpen).toBe(false);
    vi.advanceTimersByTime(800);
    expect(transferCenter.isOpen).toBe(true);

    transferCenter.render();
    const bar = document.querySelector('[data-task-id="t1"] [role="progressbar"]');
    expect(bar.getAttribute("aria-valuenow")).toBe("25");

    transferCenter.update({ id: 't1', status: 'completed', percent: 100, result: { skipped: 0 } });
    expect(showToast).toHaveBeenCalledWith('Copying 2 items to Movies: done', 'success');
    expect(refresh).toHaveBeenCalled();
    expect(onDone).toHaveBeenCalled();
  });

  it('does not pop up for quick operations', async () => {
    api.post.mockResolvedValue({ status: 'ok', task_id: 't2', task: { ...running, id: 't2' } });
    await transferCenter.startTransfer({ sources: ['/a'], destinationDir: '/b' });
    transferCenter.update({ id: 't2', status: 'completed', percent: 100 });
    vi.advanceTimersByTime(800);
    expect(transferCenter.isOpen).toBe(false);
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('done'), 'success');
  });

  it('tracks browser-side work such as uploads, with cancel', () => {
    const cancel = vi.fn();
    const job = transferCenter.startLocal({ kind: 'upload', label: 'Uploading 2 file(s) to Movies', totalFiles: 2, totalBytes: 2000, cancel });
    job.progress({ files: 1, bytes: 1000, current: 'a.mkv' });
    transferCenter.toggle(true);
    transferCenter.render();
    const card = document.querySelector(`[data-task-id="${job.id}"]`);
    expect(card.textContent).toContain('a.mkv');
    expect(card.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')).toBe('50');
    card.querySelector('button[data-act="cancel"]').click();
    expect(cancel).toHaveBeenCalled();
    job.finish('failed', 'network error');
    expect(showToast).toHaveBeenCalledWith('Uploading 2 file(s) to Movies failed: network error', 'error');
  });

  it('pause and resume go to the server', async () => {
    api.post.mockResolvedValue({});
    transferCenter.update({ ...running, id: 't3' });
    transferCenter.toggle(true);
    transferCenter.render();
    document.querySelector('[data-task-id="t3"] button[data-act="pause"]').click();
    expect(api.post).toHaveBeenCalledWith('/api/fs/transfers/t3/pause', {});
  });
});
