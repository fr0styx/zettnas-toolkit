import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, auth: {}, ApiError: class extends Error {} }));
vi.mock('../components/dock.js', () => ({
  // the real window manager shows a window with an inline display: flex
  bringToFront: vi.fn((el) => { el.style.display = 'flex'; }),
  makeDraggable: vi.fn(),
  applyWindowSnap: vi.fn((el, zone) => { el.dataset.snapped = zone; }),
  restoreWindowSnap: vi.fn((el) => { el.dataset.snapped = ''; }),
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { applyWindowSnap, restoreWindowSnap } from '../components/dock.js';
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

  it('closes for real even after the window manager showed it inline', () => {
    openJobsCentre();
    const win = document.getElementById('jobs-centre-window');
    expect(win.style.display).toBe('flex');
    document.getElementById('jobs-centre-close').click();
    expect(win.hidden).toBe(true);
    expect(win.style.display).toBe('none');
    openJobsCentre();
    expect(win.hidden).toBe(false);
    expect(win.style.display).toBe('flex');
  });

  it('minimizes to the dock, comes back from the top-bar button and closes from the dock', () => {
    const windows = {};
    window.DockManager = {
      windows,
      register: vi.fn((id, el) => { windows[id] = { el, minimized: false }; el.style.display = 'flex'; }),
      minimize: vi.fn((id) => { windows[id].minimized = true; windows[id].el.style.setProperty('display', 'none', 'important'); }),
      unregister: vi.fn((id) => { delete windows[id]; }),
    };
    try {
      openJobsCentre();
      const win = document.getElementById('jobs-centre-window');
      document.getElementById('jobs-centre-min').click();
      expect(window.DockManager.minimize).toHaveBeenCalledWith('jobs');
      expect(win.style.display).toBe('none');
      openJobsCentre();
      expect(win.style.display).toBe('flex');
      windows.jobs.onClose(); // the dock's Close
      expect(window.DockManager.unregister).toHaveBeenCalledWith('jobs');
      expect(win.hidden).toBe(true);
    } finally {
      delete window.DockManager;
    }
  });

  it('maximizes and restores', () => {
    openJobsCentre();
    const win = document.getElementById('jobs-centre-window');
    document.getElementById('jobs-centre-max').click();
    expect(applyWindowSnap).toHaveBeenCalledWith(win, 'maximize', 'jobs');
    document.getElementById('jobs-centre-max').click();
    expect(restoreWindowSnap).toHaveBeenCalledWith(win, 'jobs');
  });
});

describe('Clearing finished jobs', () => {
  beforeEach(() => {
    _resetJobsCentreForTesting();
    document.body.innerHTML = '<div class="suite-telemetry-pills"></div>';
    api.post.mockResolvedValue({ cleared: 1 });
  });

  it('a Clear button empties Recent and keeps running jobs', async () => {
    api.get.mockResolvedValueOnce(DATA).mockResolvedValue({ active: DATA.active, history: [] });
    openJobsCentre();
    const clear = document.getElementById('jobs-history-clear');
    await vi.waitFor(() => expect(clear.hidden).toBe(false));
    clear.click();
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/jobs/history/clear', {}));
    await vi.waitFor(() => expect(clear.hidden).toBe(true));
    expect(document.getElementById('jobs-history-list').textContent).toContain('No finished jobs yet');
    expect(document.getElementById('jobs-active-list').querySelectorAll('.jobs-row').length).toBe(2);
  });

  it('says so when clearing fails, and shows a detail in the reader\'s words', async () => {
    const { showToast } = await import('../toast.js');
    const { jobRowHtml, clearJobHistory } = await import('../components/jobs-centre.js');
    api.post.mockRejectedValueOnce(new Error('offline'));
    api.get.mockResolvedValue(DATA);
    await clearJobHistory();
    expect(showToast).toHaveBeenCalledWith('The list could not be cleared.', 'error');
    const row = jobRowHtml({ id: 'storage:parity', kind: 'storage_check', title: 'Parity check', status: 'running', detail: 'x', detail_id: 'jobs.d.parity_corrected', detail_params: { n: 1 } }, true);
    expect(row).toContain('1 error corrected so far');
  });
});

describe('Job progress', () => {
  it('keeps the decimal the source gives, like Unraid does', async () => {
    const { jobPercent, jobRowHtml } = await import('../components/jobs-centre.js');
    expect(jobPercent(66.7)).toBe('66.7%');
    expect(jobPercent(42)).toBe('42%');
    expect(jobPercent(66.749)).toBe('66.7%');
    const row = jobRowHtml({ id: 'storage:parity', kind: 'storage_check', title: 'Parity check', status: 'running', percent: 66.7 }, true);
    expect(row).toContain('66.7%');
  });
});
