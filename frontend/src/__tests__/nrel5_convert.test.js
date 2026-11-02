import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { convertShare, renderSnapshotSchedules, schedulesHtml } from '../components/snapshot-browser.js';

const flush = () => new Promise((r) => setTimeout(r, 0));
const sched = [{ share: 'photos', every: 'hourly', keep: 24 }, { share: 'docs', every: 'daily', keep: 7 }];

describe('making a folder share snapshot-ready (NREL-5)', () => {
  it('offers it only for the shares that need it', () => {
    const box = document.createElement('div');
    box.innerHTML = schedulesHtml(sched, ['photos', 'docs'], ['docs']);
    const btns = box.querySelectorAll('[data-snap-convert]');
    expect(btns.length).toBe(1);
    expect(btns[0].dataset.snapConvert).toBe('docs');
    expect(box.textContent).toContain("Its snapshots can't work yet");
    box.innerHTML = schedulesHtml(sched, ['photos']);
    expect(box.querySelector('[data-snap-convert]')).toBeNull();
  });

  it('converts from the schedule list and says where to follow it', async () => {
    api.get.mockImplementation((url) => Promise.resolve(url.includes('schedules') ? { schedules: sched, convertible: ['docs'] } : { shares: [] }));
    api.post.mockResolvedValue({ share: 'docs', job_id: 'job:1' });
    const mount = document.createElement('div');
    await renderSnapshotSchedules(mount);
    mount.querySelector('[data-snap-convert]').click();
    await flush();
    expect(api.post).toHaveBeenCalledWith('/api/snapshots/shares/docs/convert', {});
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Jobs centre'), 'success');
  });

  it('says why when it fails, and nothing when the person cancels', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('Lock the encrypted folders first'), {}));
    await convertShare('docs');
    expect(showToast).toHaveBeenLastCalledWith('Lock the encrypted folders first', 'error');
    showToast.mockClear();
    api.post.mockRejectedValue({ error: 'cancelled' });
    await convertShare('docs');
    expect(showToast).not.toHaveBeenCalled();
  });
});
