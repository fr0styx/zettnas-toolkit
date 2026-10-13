import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  initFileManager,
  openNewFileManagerWindow,
  openFileManager,
  closeAllFileManagerWindows,
  getActiveFmInstance,
  handleFmKeydown,
} from '../components/file-manager.js';
import { DockManager, toggleFmWindowSwitcher, showDockItemContextMenu } from '../components/dock.js';
import { ZettEventBus } from '../event-bus.js';

vi.mock('../api.js', () => ({
  api: {
    post: vi.fn().mockResolvedValue({ status: 'ok', transferred: 1 }),
    get: vi.fn().mockImplementation((url) => {
      const decoded = decodeURIComponent(url);
      if (decoded.includes('/api/fs/search')) {
        return Promise.resolve({
          items: [
            { name: 'found-receipt.pdf', path: '/mnt/user/docs/found-receipt.pdf', is_dir: false, size: 1024 },
          ],
        });
      }
      const match = url.match(/[?&]path=([^&]+)/);
      const reqPath = match ? decodeURIComponent(match[1]) : '/mnt/user';
      if (reqPath.includes('/mnt/remotes/google-drive')) {
        return Promise.resolve({
          current: reqPath,
          dirs: [
            { name: '..', path: '/mnt/remotes', is_dir: true, size: 0 },
            { name: 'gdrive-file.doc', path: '/mnt/remotes/google-drive/gdrive-file.doc', is_dir: false, size: 2048 },
          ],
          roots: ['/mnt/user', '/mnt/remotes/google-drive'],
        });
      }
      return Promise.resolve({
        current: reqPath,
        dirs: [
          { name: '..', path: '/mnt/user', is_dir: true, size: 0 },
          { name: 'archive.zip', path: reqPath + '/archive.zip', is_dir: false, size: 10485760 },
          { name: 'iso-image.iso', path: reqPath + '/iso-image.iso', is_dir: false, size: 524288000 },
        ],
        roots: ['/mnt/user', '/mnt/remotes/google-drive'],
      });
    }),
  },
  auth: {
    getToken: vi.fn().mockReturnValue('test-token-123'),
  },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
}));

vi.mock('../components/file-preview-modal.js', () => ({
  openFilePreviewModal: vi.fn(),
}));

describe('File Manager True Multi-Instance Advanced Suite', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="desktop">
        <div id="os-dock-container">
          <div id="os-dock"></div>
        </div>
      </div>
    `;
    window._fmInitialized = false;
    delete document._fmDocKbBound;
    DockManager.windows = {};
    DockManager.activeId = null;
    initFileManager();
  });

  afterEach(() => {
    closeAllFileManagerWindows();
    document.body.innerHTML = '';
  });

  it('groups multiple File Explorer windows under a single fm dock item with dynamic count badge', async () => {
    const primary = getActiveFmInstance();
    primary.open('/mnt/user/downloads');
    await primary.loadPath('/mnt/user/downloads');

    // Open second and third windows
    const win2 = openNewFileManagerWindow('/mnt/remotes/google-drive');
    await win2.loadPath('/mnt/remotes/google-drive');

    const win3 = openNewFileManagerWindow('/mnt/user/downloads');
    await win3.loadPath('/mnt/user/downloads');

    DockManager.render();

    const dock = document.getElementById('os-dock');
    const fmItems = dock.querySelectorAll('.dock-item[data-window-id="fm"]');
    // Must be grouped under exactly 1 dock item
    expect(fmItems.length).toBe(1);

    const badge = fmItems[0].querySelector('.dock-count-badge');
    expect(badge).not.toBeNull();
    expect(badge.textContent).toBe('3');
  });

  it('provides a window switcher popover listing all open instances with paths', async () => {
    const primary = getActiveFmInstance();
    await primary.loadPath('/mnt/user/downloads');

    const win2 = openNewFileManagerWindow('/mnt/remotes/google-drive');
    await win2.loadPath('/mnt/remotes/google-drive');

    const fmWindows = [
      { id: 'fm', title: primary.getTitle(), el: primary.windowEl },
      { id: win2.dockId, title: win2.getTitle(), el: win2.windowEl },
    ];

    const anchor = document.createElement('div');
    document.body.appendChild(anchor);

    toggleFmWindowSwitcher(anchor, fmWindows);

    const popover = document.getElementById('dock-fm-switcher');
    expect(popover).not.toBeNull();

    const items = popover.querySelectorAll('.dock-switcher-item');
    expect(items.length).toBe(2);

    // Close switcher
    popover.remove();
  });

  it('lists open windows in dock item context menu with 1-click focus and close all action', async () => {
    const primary = getActiveFmInstance();
    await primary.loadPath('/mnt/user/downloads');

    const win2 = openNewFileManagerWindow('/mnt/remotes/google-drive');
    await win2.loadPath('/mnt/remotes/google-drive');

    const openWindows = [
      { id: 'file-manager-window', title: primary.getTitle() },
      { id: win2.id, title: win2.getTitle() },
    ];

    showDockItemContextMenu(200, 300, 'fm', 'File Explorer', true, true, openWindows);

    const menu = document.getElementById('dock-item-ctx-menu');
    expect(menu).not.toBeNull();
    expect(menu.style.display).toBe('block');

    const winEntries = menu.querySelectorAll('.dock-ctx-fm-win');
    expect(winEntries.length).toBe(2);

    const closeAllBtn = menu.querySelector('#dock-ctx-close-all');
    expect(closeAllBtn).not.toBeNull();

    menu.remove();
  });

  it('maintains independent navigation history stacks with Back, Forward, and Up buttons', async () => {
    const primary = getActiveFmInstance();
    await primary.loadPath('/mnt/user');
    await primary.loadPath('/mnt/user/downloads');

    expect(primary.historyIndex).toBe(1);
    expect(primary.history[0]).toBe('/mnt/user');
    expect(primary.history[1]).toBe('/mnt/user/downloads');

    // Back button
    await primary.goBack();
    expect(primary.historyIndex).toBe(0);
    expect(primary.currentPath).toBe('/mnt/user');

    // Forward button
    await primary.goForward();
    expect(primary.historyIndex).toBe(1);
    expect(primary.currentPath).toBe('/mnt/user/downloads');

    // Up button
    await primary.goUp();
    expect(primary.currentPath).toBe('/mnt/user');
  });

  it('supports instant client-side filter and recursive backend search via Enter', async () => {
    const primary = getActiveFmInstance();
    await primary.loadPath('/mnt/user/downloads');

    expect(primary.fileList.length).toBe(3); // .., archive.zip, iso-image.iso

    // Filter for archive
    primary.handleSearchInput('archive');
    expect(primary.fileList.some((f) => f.name === 'archive.zip')).toBe(true);
    expect(primary.fileList.some((f) => f.name === 'iso-image.iso')).toBe(false);

    // Clear search
    primary.handleSearchInput('');
    expect(primary.fileList.length).toBe(3);

    // Recursive search
    await primary.executeBackendSearch('receipt');
    expect(primary.fileList.some((f) => f.name === 'found-receipt.pdf')).toBe(true);
  });

  it('triggers Universal Quick Look modal on Spacebar keydown', async () => {
    const { openFilePreviewModal } = await import('../components/file-preview-modal.js');
    const primary = getActiveFmInstance();
    await primary.loadPath('/mnt/user/downloads');
    primary.open();

    // Select archive.zip
    primary.selectedPaths.add('/mnt/user/downloads/archive.zip');

    const spaceEv = new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true, cancelable: true });
    handleFmKeydown(spaceEv);

    expect(openFilePreviewModal).toHaveBeenCalledWith(
      '/mnt/user/downloads/archive.zip',
      'archive.zip'
    );
  });

  it('applies modulo cascade geometry to newly spawned windows', () => {
    const win1 = openNewFileManagerWindow('/mnt/user');
    const win2 = openNewFileManagerWindow('/mnt/user');

    const left1 = parseInt(win1.windowEl.style.left, 10);
    const left2 = parseInt(win2.windowEl.style.left, 10);

    expect(left2).toBeGreaterThan(left1);
  });

  it('closes all windows cleanly with closeAllFileManagerWindows', () => {
    const win1 = openNewFileManagerWindow('/mnt/user');
    const win2 = openNewFileManagerWindow('/mnt/user');

    expect(document.getElementById(win1.id)).not.toBeNull();
    expect(document.getElementById(win2.id)).not.toBeNull();

    closeAllFileManagerWindows();

    expect(document.getElementById(win1.id)).toBeNull();
    expect(document.getElementById(win2.id)).toBeNull();
  });
});
