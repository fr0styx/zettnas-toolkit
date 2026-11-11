/** SET-05: rename works; one delete, one question; the menu opens on empty space. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { FmContextMenu } from '../components/file-manager-helpers.js';
import { FileManagerWindow, renameBody, shownName, allInBin, binConfirmText } from '../components/file-manager.js';
import { showConfirmToast, showDangerConfirm } from '../toast.js';
import { api } from '../api.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
  showActionToast: vi.fn(),
}));

const src = (p) => readFileSync(resolve(__dirname, '..', p), 'utf8');
const BIN = '/mnt/user/Docs/.RecycleBin/files/1794349636_budget.csv';

describe('rename (SET-05)', () => {
  it('sends what the server takes: the item and its new name', () => {
    expect(renameBody('/mnt/user/Docs/old.txt', ' new.txt ')).toEqual({ path: '/mnt/user/Docs/old.txt', new_name: 'new.txt' });
  });

  it('no rename request carries the old field names', () => {
    const page = src('components/file-manager.js');
    expect(page).not.toContain('old_path');
    expect(page.match(/api\.post\('\/api\/fs\/rename', renameBody\(/g)).toHaveLength(2);
  });
});

describe('one delete, one question (SET-05)', () => {
  let fm;
  beforeEach(() => {
    vi.clearAllMocks();
    fm = Object.create(FileManagerWindow.prototype);
    Object.assign(fm, { selectedPaths: new Set(), fileList: [], clearSelection: vi.fn(), deleteWithProgress: vi.fn() });
  });

  it('outside the bin it asks to move to the Recycle Bin, by name', async () => {
    fm.selectedPaths = new Set(['/mnt/user/Docs/letter.txt']);
    fm.bulkDelete();
    expect(showDangerConfirm).not.toHaveBeenCalled();
    const [title, msg, run, , options] = showConfirmToast.mock.calls[0];
    expect(title).toBe('Delete 1 item?');
    expect(msg).toBe('Move “letter.txt” to the Recycle Bin?');
    expect(options).toEqual({ okText: 'Move to Recycle Bin', destructive: false }); // it can be undone
    await run();
    expect(fm.deleteWithProgress).toHaveBeenCalledWith(['/mnt/user/Docs/letter.txt'], { permanent: false });
  });

  it('in the bin it is red, says "for good", and shows the name the file had', async () => {
    fm.fileList = [{ path: BIN, name: '1794349636_budget.csv', trash_id: 't1', original_path: '/mnt/user/Docs/budget.csv' }];
    fm.askDelete([BIN]);
    expect(showConfirmToast).not.toHaveBeenCalled();
    const [title, msg, run, , options] = showDangerConfirm.mock.calls[0];
    expect(title).toBe('Delete 1 item for good?');
    expect(msg).toBe("“budget.csv” will be deleted for good. This can't be undone.");
    expect(options.okText).toBe('Delete for good');
    await run();
    expect(fm.deleteWithProgress).toHaveBeenCalledWith([BIN], { permanent: true });
  });

  it('the name is found without the list too', () => {
    expect(shownName(BIN)).toBe('budget.csv');
    expect(shownName('/mnt/user/Docs/2024_report.pdf')).toBe('2024_report.pdf'); // not in a bin: untouched
    expect(allInBin([BIN, '/mnt/user/a'])).toBe(false);
    expect(binConfirmText([BIN, BIN])).toContain('2 items will be deleted for good');
  });

  it('the row button and the Delete key ask the same question', () => {
    const page = src('components/file-manager.js');
    expect(page).not.toContain("t('common.confirm', 'Confirm Action'), confirmMsg");
    expect(page).toContain("this.bulkDeleteBtn?.addEventListener('click', () => this.bulkDelete());");
    expect(page).toContain("this.askDelete([path]);");
  });

  it('the request carries no "permanent" field the server never had', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });
    const real = Object.create(FileManagerWindow.prototype);
    Object.assign(real, { currentPath: '/mnt/user', loadPath: vi.fn(), offerUndo: vi.fn() });
    await real.deleteWithProgress([BIN], { permanent: true });
    expect(post).toHaveBeenCalledWith('/api/fs/delete', { path: BIN });
    post.mockRestore();
  });
});

describe('the right-click menu (SET-05)', () => {
  const open = (fm, item = null) => {
    document.body.innerHTML = '';
    const menu = new FmContextMenu({ currentPath: '/mnt/user/Docs', currentSortBy: 'name', currentSortDir: 'asc', ...fm });
    menu.show(new MouseEvent('contextmenu', { clientX: 5, clientY: 5 }), item);
    return document.getElementById('fm-context-menu');
  };
  const acts = (el) => [...el.querySelectorAll('[data-act]')].map((r) => r.dataset.act);

  it('has no "Delete permanently" and no Shift+Delete', () => {
    const el = open({ selectedPaths: new Set(['/mnt/user/Docs/a.txt']) }, { name: 'a.txt', path: '/mnt/user/Docs/a.txt', is_dir: false });
    expect(acts(el)).toContain('trash');
    expect(acts(el)).not.toContain('delete-perm');
    expect(el.textContent).toContain('Move to the Recycle Bin');
    expect(el.textContent).not.toMatch(/permanently|Shift\+Delete/);
  });

  it('opens on empty space while one item is selected', () => {
    const el = open({ selectedPaths: new Set(['/mnt/user/Docs/a.txt']) });
    expect(el.style.display).toBe('block');
    expect(acts(el)).toEqual(expect.arrayContaining(['new-window', 'paste', 'fav-toggle-here', 'trash']));
    // nothing about "the" item: none was clicked
    for (const act of ['rename', 'info', 'share', 'checksum', 'versions', 'ask-kib']) expect(acts(el)).not.toContain(act);
  });

  it('in the bin the delete row says what it does', () => {
    const el = open({ selectedPaths: new Set([BIN]), _inBin: true }, { name: '1794349636_budget.csv', path: BIN, is_dir: false, trash_id: 't1' });
    expect(el.textContent).toContain('Delete for good');
    expect(el.textContent).not.toContain('Move to the Recycle Bin');
  });
});
