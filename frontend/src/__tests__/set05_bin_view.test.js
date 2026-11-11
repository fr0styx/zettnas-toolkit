/** SET-05: the Recycle Bin's screen: Restore where a hand finds it, both rules said, what goes soon. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { mayEmpty, goesSoon, goesLabel, binNote } from '../components/fm-bin-view.js';
import { FmContextMenu } from '../components/file-manager-helpers.js';
import { FileManagerWindow } from '../components/file-manager.js';
import { showDangerConfirm, showBottomSheet } from '../toast.js';
import { api, ApiError } from '../api.js';
import { transferCenter } from '../components/transfer-center.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
  showActionToast: vi.fn(),
}));

const DAY = 86400;
const NOW = 1_800_000_000;
const BIN = '/mnt/user/Docs/.RecycleBin/files/1794349636_budget.csv';
const page = readFileSync(resolve(__dirname, '..', 'components/file-manager.js'), 'utf8');

describe('the Recycle Bin in the File Explorer (SET-05)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('the storage administrator may empty the bins', () => {
    expect(mayEmpty({ scopes: ['shares:*', 'storage:read'] })).toBe(true); // that role holds "shares:*"
    expect(mayEmpty({ scopes: ['*'] })).toBe(true);
    expect(mayEmpty({ scopes: ['storage:admin'] })).toBe(true);
    expect(mayEmpty({ scopes: ['shares:read', 'shares:user_write'] })).toBe(false);
    expect(mayEmpty(null)).toBe(false);
  });

  it('says both rules, and how many items go in the next 7 days', () => {
    const rules = { keep_days: 30, max_percent_of_disk: 10, min_days: 1, soon_days: 7 };
    expect(binNote(rules, 0)).toBe('Items stay here for 30 days after they are deleted, then they go for good. A bin that grows past 10% of its drive lets its oldest items go sooner, but never within a day.');
    expect(binNote(rules, 3)).toMatch(/never within a day\. 3 items go in the next 7 days\.$/);
    expect(binNote(rules, 1)).toMatch(/1 item goes in the next 7 days\.$/);
    expect(binNote()).toContain('30 days'); // an older server that sends no rules
  });

  it('knows which items go soon, and says when', () => {
    expect(goesSoon({ leaves_at: NOW + 6 * DAY }, 7, NOW)).toBe(true);
    expect(goesSoon({ leaves_at: NOW + 8 * DAY }, 7, NOW)).toBe(false);
    expect(goesSoon({ leaves_at: 0 }, 7, NOW)).toBe(false);
    expect(goesSoon({}, 7, NOW)).toBe(false);
    expect(goesLabel({ leaves_at: NOW + 3600 }, NOW)).toBe('Goes within a day');
    expect(goesLabel({ leaves_at: NOW + 3 * DAY }, NOW)).toMatch(/^Goes .*\d/);
  });

  it('the menu on a deleted item is short: Restore, Get info, Delete for good', () => {
    const menu = new FmContextMenu({ selectedPaths: new Set([BIN]), currentPath: '/mnt/user/.RecycleBin', currentSortBy: 'name', currentSortDir: 'asc', _inBin: true });
    menu.show(new MouseEvent('contextmenu', { clientX: 5, clientY: 5 }), { name: 'budget.csv', path: BIN, is_dir: false, trash_id: 't1' });
    const acts = [...document.querySelectorAll('#fm-context-menu [data-act]')].map((r) => r.dataset.act);
    expect(acts).toEqual(['restore', 'info', 'trash']);
    expect(document.getElementById('fm-context-menu').textContent).toContain('Delete for good');
  });

  it('a row and a card in the bin offer Restore and "Delete for good", and nothing else', () => {
    for (const act of ['download', 'share', 'rename', 'delete']) {
      expect(page.match(new RegExp(`\\$\\{!this\\._inBin && [^\`]*\`<button class="fm-act-btn" data-act="${act}"`, 'g')), act).toHaveLength(2);
    }
    expect(page.match(/\$\{this\._inBin \? binRowActions\(escPath\) : ''\}/g)).toHaveLength(2);
    expect(page).toContain('data-act="restore"');
  });

  it('the row button and the phone’s "···" restore', async () => {
    const fm = Object.create(FileManagerWindow.prototype);
    Object.assign(fm, { _inBin: true, fileList: [], restoreFromBin: vi.fn(), askDelete: vi.fn() });
    await fm.handleAction('restore', BIN, 'budget.csv');
    expect(fm.restoreFromBin).toHaveBeenCalledWith([BIN]);
    await fm.handleAction('more-sheet', BIN, 'budget.csv');
    const sheet = showBottomSheet.mock.calls[0][0];
    expect(sheet.items.map((i) => i.label)).toEqual(['Restore', 'Delete for good']);
    sheet.items[0].onClick();
    expect(fm.restoreFromBin).toHaveBeenCalledTimes(2);
    sheet.items[1].onClick();
    expect(fm.askDelete).toHaveBeenCalledWith([BIN]);
  });

  it('the selection bar in the bin: Restore and "Delete for good" only', () => {
    const el = (cls) => { const b = document.createElement('button'); b.className = cls; b.innerHTML = '<span class="fm-sel-label">Delete</span>'; return b; };
    const fm = Object.create(FileManagerWindow.prototype);
    Object.assign(fm, {
      selectionBar: document.createElement('div'), selectedCount: document.createElement('span'),
      selectedPaths: new Set([BIN]), fileList: [], _inBin: true,
      bulkRestoreBtn: el('r'), bulkZipBtn: el('z'), bulkMoveBtn: el('m'), bulkShareBtn: el('s'), bulkDeleteBtn: el('d'),
    });
    fm.bulkRestoreBtn.hidden = true;
    fm.updateSelectionToolbar();
    expect([fm.bulkRestoreBtn.hidden, fm.bulkZipBtn.hidden, fm.bulkMoveBtn.hidden, fm.bulkShareBtn.hidden]).toEqual([false, true, true, true]);
    expect(fm.bulkDeleteBtn.getAttribute('aria-label')).toBe('Delete for good');
    expect(fm.bulkDeleteBtn.textContent).toBe('Delete for good');
    fm._inBin = false;
    fm.updateSelectionToolbar();
    expect([fm.bulkRestoreBtn.hidden, fm.bulkZipBtn.hidden, fm.bulkMoveBtn.hidden, fm.bulkShareBtn.hidden]).toEqual([true, false, false, false]);
    expect(fm.bulkDeleteBtn.textContent).toBe('Delete');
  });

  it('a delete larger than the bin keeps asks first, and "no" leaves the folder where it is', async () => {
    const job = { progress: vi.fn(), finish: vi.fn() };
    vi.spyOn(transferCenter, 'startLocal').mockReturnValue(job);
    const tooLarge = () => new ApiError('This is larger than the Recycle Bin keeps.', { status: 409, error: 'too_large_for_bin' });
    const post = vi.spyOn(api, 'post').mockRejectedValueOnce(tooLarge()).mockResolvedValueOnce({ status: 'ok', trash_id: 't9' });
    const fm = Object.create(FileManagerWindow.prototype);
    Object.assign(fm, { currentPath: '/mnt/user', loadPath: vi.fn(), offerUndo: vi.fn() });
    showDangerConfirm.mockImplementationOnce((title, msg, yes) => yes());
    expect(await fm.deleteWithProgress(['/mnt/user/Videos'])).toEqual({ success: 1, failed: 0 });
    const [title, msg, , , options] = showDangerConfirm.mock.calls[0];
    expect(title).toBe('Larger than the Recycle Bin keeps');
    expect(msg).toContain('“Videos” is larger than a Recycle Bin keeps');
    expect(msg).toContain('stays for one day');
    expect(options.okText).toBe('Move to Recycle Bin');
    expect(post.mock.calls).toEqual([['/api/fs/delete', { path: '/mnt/user/Videos' }], ['/api/fs/delete', { path: '/mnt/user/Videos', large_ok: true }]]);
    expect(fm.offerUndo).toHaveBeenCalledWith(['t9']);

    post.mockReset().mockRejectedValueOnce(tooLarge());
    showDangerConfirm.mockImplementationOnce((title, msg, yes, no) => no());
    expect(await fm.deleteWithProgress(['/mnt/user/Videos'])).toEqual({ success: 0, failed: 0 });
    expect(post).toHaveBeenCalledTimes(1);
    expect(job.finish).toHaveBeenLastCalledWith('cancelled');
  });
});
