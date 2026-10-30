import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '../api.js';
import { renderShareFolders, shareFolderPicks } from '../components/share-folder-picker.js';

describe('an app folder on a share (FEAT-06)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('offers each share for the folders that can live on one', async () => {
    api.get.mockResolvedValue({
      folders: [{ key: 'data', label: 'Synced folders', target: '/data1' }, { key: 'x', label: 'Odd name', target: '/x' }],
      shares: [{ name: 'Family', path: '/mnt/user/Family' }, { name: 'Music', path: '/mnt/user/Music' }],
    });
    const mount = document.createElement('div');
    const changed = vi.fn();
    await renderShareFolders(mount, 'syncthing', changed);
    expect(api.get).toHaveBeenCalledWith('/api/docker/catalog/syncthing/share-folders');
    expect(mount.hidden).toBe(false);
    expect(mount.textContent).toContain('Synced folders');
    expect(mount.textContent).toContain('Odd name');
    expect(mount.textContent).toContain('The app sees everything');
    const sel = /** @type {HTMLSelectElement} */ (mount.querySelector('select[data-share-folder="data"]'));
    expect([...sel.options].map((o) => o.value)).toEqual(['', 'Family', 'Music']);
    expect(shareFolderPicks(mount)).toEqual({});
    sel.value = 'Family';
    sel.onchange(new Event('change'));
    expect(changed).toHaveBeenCalled();
    expect(shareFolderPicks(mount)).toEqual({ data: 'Family' });
  });

  it('says how to make a share when there is none', async () => {
    api.get.mockResolvedValue({ folders: [{ key: 'data', label: 'Files', target: '/data' }], shares: [] });
    const mount = document.createElement('div');
    await renderShareFolders(mount, 'nextcloud');
    expect(mount.textContent).toContain('No shares yet');
    expect(/** @type {HTMLSelectElement} */ (mount.querySelector('select')).disabled).toBe(true);
  });

  it('stays hidden for apps without such folders, or when the list fails', async () => {
    const mount = document.createElement('div');
    api.get.mockResolvedValue({ folders: [], shares: [] });
    await renderShareFolders(mount, 'adguardhome');
    expect(mount.hidden).toBe(true);
    api.get.mockRejectedValue(new Error('down'));
    await renderShareFolders(mount, 'syncthing');
    expect(mount.hidden).toBe(true);
    expect(mount.childElementCount).toBe(0);
    await renderShareFolders(null, 'syncthing');
    expect(shareFolderPicks(null)).toEqual({});
  });
});
