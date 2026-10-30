import { describe, it, expect, vi } from 'vitest';
import { FmContextMenu, FmInspector } from '../components/file-manager-helpers.js';
import { api } from '../api.js';

function inspectorWith(item) {
  const pane = document.createElement('div');
  pane.innerHTML = '<div class="fm-inspector-content"></div>';
  document.body.append(pane);
  const fm = { selectedPaths: new Set([item.path]), fileList: [item], currentPath: '/mnt/user', currentSortBy: 'name', currentSortDir: 'asc' };
  fm.inspector = new FmInspector(fm, pane);
  return fm;
}

describe('Get info (folder size, files, folders)', () => {
  it('is in the menu for one item', () => {
    const fm = inspectorWith({ name: 'Photos', path: '/mnt/user/Photos', is_dir: true });
    const menu = new FmContextMenu(fm);
    menu.show(new MouseEvent('contextmenu', { clientX: 1, clientY: 1 }), fm.fileList[0]);
    expect(document.querySelector('#fm-context-menu [data-act="info"]').textContent).toContain('Get info');
    menu.hide();
  });

  it('opens the panel and counts a folder at once', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ size: 2048, files_count: 3, dirs_count: 1, is_standby: false });
    vi.spyOn(api, 'get').mockResolvedValue({});
    const fm = inspectorWith({ name: 'Photos', path: '/mnt/user/Photos', is_dir: true, mtime: 1 });
    const menu = new FmContextMenu(fm);
    menu.targetItem = fm.fileList[0];
    menu.handleAction('info');
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/fs/folder-size', { path: '/mnt/user/Photos', force_wake: false }));
    const out = fm.inspector.container.querySelector('#fm-insp-folder-sz-res');
    await vi.waitFor(() => expect(out.textContent).toMatch(/3 files · 1 folder/));
    post.mockRestore();
  });

  it('a sleeping disk is counted only when asked, and says "at least" when cut short', async () => {
    const fm = inspectorWith({ name: 'Old', path: '/mnt/user/Old', is_dir: true });
    const content = fm.inspector.container.querySelector('.fm-inspector-content');
    content.innerHTML = '<button id="fm-btn-calc-folder-sz"></button><div id="fm-insp-folder-sz-res"></div>';
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ is_standby: true });
    await fm.inspector.countFolder(content, '/mnt/user/Old');
    const out = content.querySelector('#fm-insp-folder-sz-res');
    expect(out.textContent).toContain('asleep');
    post.mockResolvedValueOnce({ size: 10, files_count: 1, dirs_count: 0, at_least: true });
    out.querySelector('button').click();
    await vi.waitFor(() => expect(post).toHaveBeenLastCalledWith('/api/fs/folder-size', { path: '/mnt/user/Old', force_wake: true }));
    await vi.waitFor(() => expect(out.textContent).toMatch(/^At least /));
    post.mockRestore();
  });
});
