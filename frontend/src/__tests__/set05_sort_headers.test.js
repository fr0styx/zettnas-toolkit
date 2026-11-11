/** SET-05: the sort survives a refresh, the headers keep their arrows and words, Escape closes Organize Media. */
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { FileManagerWindow, openMediaOrganizerModal } from '../components/file-manager.js';
import { binColumns } from '../components/fm-bin-view.js';
import { versionsHtml } from '../components/file-versions.js';

const page = readFileSync(resolve(__dirname, '..', 'components/file-manager.js'), 'utf8');
const header = (word) => {
  const d = document.createElement('div');
  d.innerHTML = `${word} <span class="fm-sort-icon"></span>`;
  return d;
};
const FILES = [
  { name: 'b.txt', path: '/p/b.txt', mtime: 300 },
  { name: 'a.txt', path: '/p/a.txt', mtime: 100 },
  { name: 'Zeta', path: '/p/Zeta', is_dir: true, mtime: 50 },
  { name: 'c.txt', path: '/p/c.txt', mtime: 200 },
];

describe('sorting in the File Explorer (SET-05)', () => {
  it('sorts by Modified, newest first, folders on top', () => {
    const fm = Object.create(FileManagerWindow.prototype);
    Object.assign(fm, { fileList: [...FILES], currentSortBy: 'mtime', currentSortDir: 'desc' });
    fm.applySorting();
    expect(fm.fileList.map((f) => f.name)).toEqual(['Zeta', 'b.txt', 'c.txt', 'a.txt']);
  });

  it('a refresh uses the same sort as a click on a header, and no other', () => {
    const load = page.slice(page.indexOf('  async loadPath('), page.indexOf('  /** The folder wasn\'t opened because its disk is asleep'));
    expect(load).toContain('this.applySorting();');
    expect(load).toContain('this.updateSortHeaderUI();');
    expect(load).not.toContain('.sort((a, b) =>');
    expect(page).not.toContain("'Type' + getArrow");
    expect(page).not.toContain('fm-sort-indicator');
  });

  it('the arrow is on the column that sorts, and the bin keeps "From" and "Deleted"', () => {
    const fm = Object.create(FileManagerWindow.prototype);
    Object.assign(fm, {
      colName: header('Name'), colType: header('Type'), colSize: header('Size'), colMtime: header('Modified'),
      currentSortBy: 'mtime', currentSortDir: 'desc',
    });
    binColumns(fm, true);
    fm.updateSortHeaderUI();
    expect(fm.colMtime.querySelector('.fm-sort-icon').textContent).toBe(' ▼');
    expect(fm.colName.querySelector('.fm-sort-icon').textContent).toBe('');
    expect(fm.colType.textContent.trim()).toBe('From');
    expect(fm.colMtime.getAttribute('aria-label')).toBe('Deleted (Descending)');
    binColumns(fm, false);
    expect(fm.colType.textContent.trim()).toBe('Type');
  });
});

describe('small truths (SET-05)', () => {
  it('Escape closes Organize Media', () => {
    document.body.innerHTML = `
      <div id="modal-media-organizer" style="display:none">
        <button id="modal-media-org-close-btn"></button><button id="btn-media-org-apply"></button>
        <input id="media-org-source-input" /><input id="media-org-dest-input" />
      </div>`;
    const modal = document.getElementById('modal-media-organizer');
    openMediaOrganizerModal('/mnt/user/downloads');
    modal.style.display = 'flex';
    const bubbled = vi.fn();
    document.addEventListener('keydown', bubbled);
    modal.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    expect(modal.style.display).toBe('flex');
    modal.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(modal.style.display).toBe('none');
    expect(bubbled).toHaveBeenCalledTimes(1); // the Escape stays in the dialog: nothing behind it closes
    document.removeEventListener('keydown', bubbled);
  });

  it('"no earlier versions" points to the page that has the Snapshots card', () => {
    const html = versionsHtml('letter.txt', []);
    expect(html).toContain('Backup → Snapshots');
    expect(html).not.toContain('Storage → Snapshots');
  });
});
