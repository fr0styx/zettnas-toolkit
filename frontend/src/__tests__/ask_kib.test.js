import { describe, it, expect, vi } from 'vitest';
import { FmContextMenu } from '../components/file-manager-helpers.js';

describe('Ask Kib about a file, from the file menu', () => {
  it('hands the file to Kib, and does nothing without a file or before Kib has loaded', () => {
    const fm = { selectedPaths: new Set(['/mnt/user/a.pdf']), fileList: [], currentPath: '/mnt/user' };
    const menu = new FmContextMenu(fm);
    const ask = vi.fn();
    window.askKibAbout = ask;
    menu.targetItem = { path: '/mnt/user/a.pdf', name: 'a.pdf' };
    menu.handleAction('ask-kib');
    expect(ask).toHaveBeenCalledWith('/mnt/user/a.pdf', 'a.pdf');
    menu.targetItem = null;
    menu.handleAction('ask-kib');
    expect(ask).toHaveBeenCalledTimes(1);
    delete window.askKibAbout;
    menu.targetItem = { path: '/mnt/user/b.pdf', name: 'b.pdf' };
    expect(() => menu.handleAction('ask-kib')).not.toThrow();
  });
});
