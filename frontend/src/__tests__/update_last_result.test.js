import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { get: vi.fn() },
  auth: { getToken: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

import { api } from '../api.js';
import { showLastUpdateResult } from '../components/management.js';

describe('Updates panel: last update result (OPS-7)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="update-last-result" hidden></div>';
  });

  it('shows a rollback and its reason', async () => {
    api.get.mockResolvedValueOnce({ result: 'rolled_back', reason: 'timed out waiting for the app to report ok', at: 1700000000 });
    await showLastUpdateResult();
    const box = document.getElementById('update-last-result');
    expect(box.hidden).toBe(false);
    expect(box.textContent).toContain('rolled back');
    expect(box.textContent).toContain('timed out waiting for the app to report ok');
    expect(api.get).toHaveBeenCalledWith('/api/system/updates/last-result');
  });

  it('stays hidden after a successful update', async () => {
    api.get.mockResolvedValueOnce({ result: 'updated', reason: 'ok for 60 s' });
    await showLastUpdateResult();
    expect(document.getElementById('update-last-result').hidden).toBe(true);
  });
});
