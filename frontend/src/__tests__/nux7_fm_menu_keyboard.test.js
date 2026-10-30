import { describe, it, expect, vi } from 'vitest';
import { ctxItem, modKey, onMenuKeys, FmContextMenu } from '../components/file-manager-helpers.js';
import { FileManagerWindow } from '../components/file-manager.js';

describe('File Explorer menu by keyboard (NUX-7)', () => {
  it('shows Ctrl or ⌘ by platform', () => {
    expect(modKey({ platform: 'MacIntel', userAgent: '' })).toBe('⌘');
    expect(modKey({ platform: 'Win32', userAgent: '' })).toBe('Ctrl');
    expect(modKey(null)).toBe('Ctrl');
  });

  it('rows are menu items with their label and key', () => {
    const box = document.createElement('div');
    box.innerHTML = ctxItem('copy', '📋', 'Copy', 'Ctrl+C');
    const row = box.firstElementChild;
    expect(row.getAttribute('role')).toBe('menuitem');
    expect(row.getAttribute('tabindex')).toBe('-1');
    expect(row.textContent).toContain('Copy');
  });

  it('opens with focus inside, moves with arrows, picks with Enter and gives focus back', () => {
    document.body.innerHTML = '<button id="before">x</button>';
    const before = document.getElementById('before');
    before.focus();
    const fm = { selectedPaths: new Set(['/mnt/user/a.txt']), currentPath: '/mnt/user', currentSortBy: 'name', currentSortDir: 'asc' };
    const menu = new FmContextMenu(fm);
    menu.handleAction = vi.fn();
    menu.show(new MouseEvent('contextmenu', { clientX: 5, clientY: 5 }), { name: 'a.txt', path: '/mnt/user/a.txt', is_dir: false });
    const el = document.getElementById('fm-context-menu');
    expect(el.getAttribute('role')).toBe('menu');
    expect(document.activeElement.dataset.act).toBe('preview');
    expect(el.textContent).toContain('Move to the Recycle Bin');
    expect(el.textContent).not.toMatch(/Trash|QuickLook|Cmd\+/);
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement.dataset.act).toBe('new-window');
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    expect(document.activeElement.dataset.act).toBe('delete-perm'); // wraps round
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    expect(menu.handleAction).toHaveBeenCalledWith('preview');
    expect(el.style.display).toBe('none');
    expect(document.activeElement).toBe(before);
  });

  it('Tab closes the menu; other keys do nothing', () => {
    const menu = document.createElement('div');
    menu.innerHTML = ctxItem('a', '', 'A');
    const hide = vi.fn();
    onMenuKeys(menu, new KeyboardEvent('keydown', { key: 'Tab' }), hide);
    expect(hide).toHaveBeenCalled();
    onMenuKeys(menu, new KeyboardEvent('keydown', { key: 'x' }), hide);
    expect(hide).toHaveBeenCalledTimes(1);
  });

  it('column headers say how the folder is sorted', () => {
    const fm = Object.create(FileManagerWindow.prototype);
    const make = () => {
      const d = document.createElement('div');
      d.innerHTML = 'Name <span class="fm-sort-icon"></span>';
      return d;
    };
    Object.assign(fm, { colName: make(), colType: make(), colSize: make(), colMtime: make(), currentSortBy: 'size', currentSortDir: 'desc' });
    fm.updateSortHeaderUI();
    expect(fm.colSize.getAttribute('aria-label')).toBe('Name (Descending)');
    expect(fm.colSize.getAttribute('aria-pressed')).toBe('true');
    expect(fm.colName.getAttribute('aria-label')).toBe('Name');
    expect(fm.colName.getAttribute('role')).toBe('button');
    expect(fm.colName.getAttribute('tabindex')).toBe('0');
    expect(fm.colSize.querySelector('.fm-sort-icon').getAttribute('aria-hidden')).toBe('true');
  });
});
