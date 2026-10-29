import { describe, it, expect, vi } from 'vitest';
import { sortMenuHtml } from '../components/file-manager-helpers.js';
import { FileManagerWindow } from '../components/file-manager.js';

describe('Sort by in the folder right-click menu', () => {
  it('lists each field and direction with the current ones ticked', () => {
    const box = document.createElement('div');
    box.innerHTML = sortMenuHtml('size', 'desc');
    const rows = [...box.querySelectorAll('.fm-ctx-item')].map((r) => [r.dataset.act, r.getAttribute('aria-checked')]);
    expect(rows).toEqual([
      ['sort-name', 'false'],
      ['sort-size', 'true'],
      ['sort-type', 'false'],
      ['sort-mtime', 'false'],
      ['sort-asc', 'false'],
      ['sort-desc', 'true'],
    ]);
    expect(box.textContent).toContain('Sort by');
    expect(box.textContent).toContain('Date modified');
  });

  it('setSort sorts the folder and refreshes the view', () => {
    const fm = Object.create(FileManagerWindow.prototype);
    fm.fileList = [
      { name: 'b.txt', size: 5, is_dir: false },
      { name: 'a.jpg', size: 50, is_dir: false },
      { name: 'z', size: 0, is_dir: true },
    ];
    fm.updateSortHeaderUI = vi.fn();
    fm.renderViewport = vi.fn();
    fm.setSort('size', 'desc');
    expect(fm.fileList.map((f) => f.name)).toEqual(['z', 'a.jpg', 'b.txt']); // folders first
    fm.setSort('name', 'asc');
    expect(fm.fileList.map((f) => f.name)).toEqual(['z', 'a.jpg', 'b.txt']);
    fm.setSort('bogus', 'sideways');
    expect([fm.currentSortBy, fm.currentSortDir]).toEqual(['name', 'asc']);
    expect(fm.renderViewport).toHaveBeenCalledTimes(3);
  });
});

describe('Restore from the Recycle Bin view', () => {
  it('restores the selected items by their bin ids', async () => {
    const { api } = await import('../api.js');
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    const fm = Object.create(FileManagerWindow.prototype);
    fm.currentPath = '/mnt/user/.RecycleBin';
    fm.fileList = [
      { name: 'a.jpg', path: '/mnt/user/vault/.RecycleBin/files/a.jpg', trash_id: 'vault::a.jpg' },
      { name: 'b.txt', path: '/mnt/user/b.txt' },
    ];
    fm.loadPath = vi.fn();
    expect(await fm.restoreFromBin(['/mnt/user/vault/.RecycleBin/files/a.jpg', '/mnt/user/b.txt'])).toBe(1);
    expect(post).toHaveBeenCalledWith('/api/fs/trash/restore', { item_id: 'vault::a.jpg' });
    expect(fm.loadPath).toHaveBeenCalledWith('/mnt/user/.RecycleBin');
    post.mockRejectedValueOnce(new Error('gone'));
    expect(await fm.restoreFromBin(['/mnt/user/vault/.RecycleBin/files/a.jpg'])).toBe(0);
    post.mockRestore();
  });
});
