import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));
vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn((title, msg, ok) => ok()),
}));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { openPreviousVersions, versionsHtml, versionUrl } = await import('../components/file-versions.js');

const flush = () => new Promise((r) => setTimeout(r, 0));
const V = [
  { id: 'zfs:auto-2', label: 'auto-2', created: 2000, size: 11, mtime: 2000 },
  { id: 'zfs:auto-1', label: 'auto-1', created: 1000, size: 11, mtime: 1000 },
];

describe('Previous versions (missing feature 7)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<button id="opener">x</button>';
    vi.clearAllMocks();
  });

  it('lists versions or explains how to get them', () => {
    expect(versionsHtml('plan.txt', [])).toContain('snapshots');
    const html = versionsHtml('plan.txt', V);
    expect((html.match(/data-version=/g) || []).length).toBe(2);
    expect(versionUrl('/mnt/user/a b.txt', 'zfs:x')).toBe('/api/fs/versions/download?path=%2Fmnt%2Fuser%2Fa%20b.txt&version=zfs%3Ax');
  });

  it('restores a copy, or replaces the file after confirming, then refreshes', async () => {
    api.get.mockResolvedValue({ versions: V });
    api.post.mockResolvedValue({ path: '/mnt/user/plan (version 2026-01-01 0000).txt' });
    const onChange = vi.fn();
    document.getElementById('opener').focus();
    let dialog = await openPreviousVersions('/mnt/user/plan.txt', 'plan.txt', onChange);
    expect(dialog.getAttribute('role')).toBe('dialog');
    dialog.querySelector('[data-version="zfs:auto-1"] [data-act="copy"]').click();
    await flush();
    expect(api.post).toHaveBeenCalledWith('/api/fs/versions/restore', { path: '/mnt/user/plan.txt', version: 'zfs:auto-1', overwrite: false });
    expect(onChange).toHaveBeenCalled();
    expect(document.getElementById('fm-versions-dialog')).toBeNull();
    expect(document.activeElement.id).toBe('opener');

    dialog = await openPreviousVersions('/mnt/user/plan.txt', 'plan.txt', onChange);
    dialog.querySelector('[data-version="zfs:auto-2"] [data-act="replace"]').click();
    await flush();
    expect(api.post).toHaveBeenLastCalledWith('/api/fs/versions/restore', { path: '/mnt/user/plan.txt', version: 'zfs:auto-2', overwrite: true });
  });

  it('opens a version in a new tab and closes on Escape', async () => {
    api.get.mockResolvedValue({ versions: V });
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const dialog = await openPreviousVersions('/mnt/user/plan.txt', 'plan.txt');
    dialog.querySelector('[data-act="open"]').click();
    expect(open).toHaveBeenCalledWith(versionUrl('/mnt/user/plan.txt', 'zfs:auto-2'), '_blank', 'noopener');
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.getElementById('fm-versions-dialog')).toBeNull();
    open.mockRestore();
  });

  it('says so when the lookup or the restore fails', async () => {
    api.get.mockRejectedValueOnce(new Error('boom'));
    const dialog = await openPreviousVersions('/mnt/user/plan.txt', 'plan.txt');
    expect(dialog.textContent).toContain('boom');
    api.get.mockResolvedValue({ versions: V });
    api.post.mockRejectedValueOnce(new Error('disk full'));
    const d2 = await openPreviousVersions('/mnt/user/plan.txt', 'plan.txt');
    d2.querySelector('[data-act="copy"]').click();
    await flush();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('disk full'), 'error');
    d2.querySelector('[data-act="close"]').click();
    expect(document.getElementById('fm-versions-dialog')).toBeNull();
  });
});
