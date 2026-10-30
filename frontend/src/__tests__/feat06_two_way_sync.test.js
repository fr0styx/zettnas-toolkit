import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { previewText, pairRow, renderTwoWaySync } from '../components/two-way-sync.js';

describe('two-way sync (FEAT-06)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('says what a dry run would do', () => {
    expect(previewText(null)).toBe('No preview yet.');
    expect(previewText({ ok: false, error: 'remote not found' })).toContain('remote not found');
    const text = previewText({ ok: true, first_run: true, to_remote: 2, to_local: 1, delete_remote: 1, conflicts: 1 });
    expect(text).toContain('First run');
    expect(text).toContain('2 files to the cloud');
    expect(text).toContain('1 file to this NAS');
    expect(text).toContain('1 deletion');
    expect(text).toContain('kept twice');
  });

  it('offers Turn on only after a good preview, and Sync now once on', () => {
    const base = { id: 'p', name: 'Photos', local: '/a', remote: 'r:b', every_hours: 6 };
    const acts = (p) => [...pairRow(p).querySelectorAll('[data-sync]')].map((b) => b.dataset.sync);
    expect(acts({ ...base, state: 'new' })).toEqual(['preview', 'delete']);
    expect(acts({ ...base, state: 'previewed', preview: { ok: true } })).toEqual(['preview', 'approve', 'delete']);
    expect(acts({ ...base, state: 'active', last_run: 1, last_result: 'Stopped: too many' })).toEqual(['preview', 'run', 'delete']);
    expect(pairRow({ ...base, state: 'active', last_result: 'Stopped: too many' }).textContent).toContain('Stopped');
  });

  it('adds, previews and shows errors', async () => {
    api.get.mockResolvedValue({ pairs: [] });
    api.put.mockResolvedValue({});
    const mount = document.createElement('div');
    await renderTwoWaySync(mount);
    expect(mount.textContent).toContain('No two-way sync yet.');
    const form = mount.querySelector('form');
    form.querySelector('[name="name"]').value = 'My Docs';
    form.querySelector('[name="local"]').value = '/mnt/user/docs';
    form.querySelector('[name="remote"]').value = 'gdrive:docs';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/sync/pairs', { id: 'my-docs', new: true, name: 'My Docs', local: '/mnt/user/docs', remote: 'gdrive:docs', every_hours: 6 }));
    api.get.mockResolvedValue({ pairs: [{ id: 'my-docs', new: true, name: 'My Docs', local: '/a', remote: 'r:b', state: 'new' }] });
    await renderTwoWaySync(mount);
    api.post.mockRejectedValue(new Error('remote not found'));
    mount.querySelector('[data-sync="preview"]').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('remote not found', 'error'));
    api.delete.mockResolvedValue({});
    mount.querySelector('[data-sync="delete"]').click();
    await vi.waitFor(() => expect(api.delete).toHaveBeenCalledWith('/api/sync/pairs/my-docs'));
  });
});
