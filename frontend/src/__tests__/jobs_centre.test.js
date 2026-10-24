import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, auth: {}, ApiError: class extends Error {} }));
vi.mock('../components/dock.js', () => ({ bringToFront: vi.fn(), makeDraggable: vi.fn() }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { initJobsCentre, openJobsCentre, closeJobsCentre, _resetJobsCentreForTesting } from '../components/jobs-centre.js';

const DATA = {
  active: [
    { id: 'transfer:t1', kind: 'transfer', title: 'Copy 3 item(s) to /mnt/user/photos', status: 'running', percent: 42, detail: 'IMG_1.jpg', can_cancel: true },
    { id: 'reindex:ai', kind: 'ai_reindex', title: 'Re-embedding the AI index', status: 'running', percent: null, can_cancel: false },
  ],
  history: [{ id: 'job:x', kind: 'backup', title: 'Backup: photos', status: 'error', error: 'remote unreachable', finished_at: 1700000000 }],
};

describe('Jobs centre', () => {
  beforeEach(() => {
    _resetJobsCentreForTesting();
    document.body.innerHTML = '<div class="suite-telemetry-pills"></div>';
    api.get.mockResolvedValue(DATA);
    api.post.mockResolvedValue({ status: 'cancelling' });
  });

  it('shows how many jobs are running in the top bar', async () => {
    initJobsCentre();
    await vi.waitFor(() => expect(document.getElementById('topbar-jobs-count').textContent).toBe('2'));
    expect(document.getElementById('topbar-jobs-count').hidden).toBe(false);
  });

  it('lists running jobs with progress and history with errors, and cancels', async () => {
    openJobsCentre();
    await vi.waitFor(() => expect(document.querySelectorAll('#jobs-active-list .jobs-row').length).toBe(2));
    const bar = document.querySelector('#jobs-active-list [role="progressbar"]');
    expect(bar.getAttribute('aria-valuenow')).toBe('42');
    expect(document.querySelectorAll('[data-job-cancel]').length).toBe(1); // the AI index can't be cancelled
    expect(document.getElementById('jobs-history-list').textContent).toContain('remote unreachable');
    document.querySelector('[data-job-cancel]').click();
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/jobs/transfer%3At1/cancel', {}));
    closeJobsCentre();
    expect(document.getElementById('jobs-centre-window').hidden).toBe(true);
  });
});
