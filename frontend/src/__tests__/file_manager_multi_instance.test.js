import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  initFileManager,
  openNewFileManagerWindow,
  openFileManager,
  handleFmKeydown,
  ensureFmFocus,
  isFmActive,
  getFmSelectedPaths,
  getFmSelectionState,
  setFmStateForTesting,
  getActiveFmInstance,
} from '../components/file-manager.js';
import { ZettEventBus } from '../event-bus.js';

vi.mock('../api.js', () => ({
  api: {
    post: vi.fn().mockResolvedValue({ status: 'ok', transferred: 1 }),
    get: vi.fn().mockImplementation((url) => {
      const decoded = decodeURIComponent(url);
      if (decoded.includes('/mnt/remotes/onedrive')) {
        return Promise.resolve({
          current: '/mnt/remotes/onedrive',
          dirs: [
            { name: '..', path: '/mnt/remotes', is_dir: true, size: 0 },
            { name: 'cloud-doc1.pdf', path: '/mnt/remotes/onedrive/cloud-doc1.pdf', is_dir: false, size: 2048 },
            { name: 'cloud-doc2.pdf', path: '/mnt/remotes/onedrive/cloud-doc2.pdf', is_dir: false, size: 4096 },
          ],
          roots: ['/mnt/user', '/mnt/remotes/onedrive'],
        });
      }
      return Promise.resolve({
        current: '/mnt/user/vault',
        dirs: [
          { name: '..', path: '/mnt/user', is_dir: true, size: 0 },
          { name: 'local-file1.jpg', path: '/mnt/user/vault/local-file1.jpg', is_dir: false, size: 1024 },
          { name: 'local-file2.jpg', path: '/mnt/user/vault/local-file2.jpg', is_dir: false, size: 2048 },
        ],
        roots: ['/mnt/user'],
      });
    }),
  },
  auth: {
    getToken: vi.fn().mockReturnValue('test-token'),
  },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
}));

describe('File Manager Multi-Instance & Multi-Selection Protection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="desktop">
        <div class="chassis-hero-box management-desktop-icon" id="management-desktop-icon" tabindex="0"></div>
        <div class="chassis-hero-box fm-desktop-icon" id="fm-desktop-icon" tabindex="0"></div>
      </div>
    `;
    window._fmInitialized = false;
    delete document._fmDocKbBound;
    initFileManager();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('initializes primary window and allows opening a second independent instance', async () => {
    const primaryWin = document.getElementById('file-manager-window');
    expect(primaryWin).not.toBeNull();

    // Open second instance pointing to OneDrive remote
    const secInst = openNewFileManagerWindow('/mnt/remotes/onedrive');
    expect(secInst).not.toBeNull();
    expect(secInst.isPrimary).toBe(false);

    const secWin = document.getElementById(secInst.id);
    expect(secWin).not.toBeNull();
    expect(secWin.classList.contains('file-manager-window')).toBe(true);
    expect(secWin.id).not.toBe('file-manager-window');

    // Verify both windows exist in DOM simultaneously
    expect(document.querySelectorAll('.file-manager-window').length).toBe(2);
  });

  it('maintains independent paths, file lists, and selections across instances', async () => {
    const primaryInst = getActiveFmInstance();
    await primaryInst.loadPath('/mnt/user/vault');

    const secInst = openNewFileManagerWindow('/mnt/remotes/onedrive');
    await secInst.loadPath('/mnt/remotes/onedrive');

    expect(primaryInst.currentPath).toBe('/mnt/user/vault');
    expect(secInst.currentPath).toBe('/mnt/remotes/onedrive');

    expect(primaryInst.fileList.some((f) => f.name === 'local-file1.jpg')).toBe(true);
    expect(secInst.fileList.some((f) => f.name === 'cloud-doc1.pdf')).toBe(true);

    // Select file in primary instance
    primaryInst.selectedPaths.add('/mnt/user/vault/local-file1.jpg');
    // Select file in secondary instance
    secInst.selectedPaths.add('/mnt/remotes/onedrive/cloud-doc1.pdf');

    expect(Array.from(primaryInst.selectedPaths)).toEqual(['/mnt/user/vault/local-file1.jpg']);
    expect(Array.from(secInst.selectedPaths)).toEqual(['/mnt/remotes/onedrive/cloud-doc1.pdf']);
  });

  it('blurs desktop icons when clicking or opening File Explorer to prevent outline theft', () => {
    const desktopIcon = document.getElementById('fm-desktop-icon');
    desktopIcon.focus();
    expect(document.activeElement).toBe(desktopIcon);

    const primaryInst = getActiveFmInstance();
    primaryInst.open();

    // Desktop icon must have been blurred
    expect(document.activeElement).not.toBe(desktopIcon);
  });

  it('handles checkbox click without letting focus leak to desktop icons', async () => {
    const primaryInst = getActiveFmInstance();
    await primaryInst.loadPath('/mnt/user/vault');

    const checkbox = primaryInst.viewport.querySelector('.fm-row-checkbox');
    expect(checkbox).not.toBeNull();

    // Simulate clicking checkbox
    checkbox.click();

    // Checkbox is toggled and focus is held inside viewport, not on desktop icons
    expect(primaryInst.selectedPaths.size).toBe(1);
    expect(document.activeElement).not.toBe(document.getElementById('fm-desktop-icon'));
  });

  it('executes Shift + ArrowDown range multi-selection in active window', async () => {
    const primaryInst = getActiveFmInstance();
    await primaryInst.loadPath('/mnt/user/vault');
    primaryInst.open();

    // Select first item via initial ArrowDown
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    expect(Array.from(primaryInst.selectedPaths)).toEqual(['/mnt/user/vault/local-file1.jpg']);

    // Expand with Shift + ArrowDown
    handleFmKeydown(
      new KeyboardEvent('keydown', { key: 'ArrowDown', shiftKey: true, bubbles: true, cancelable: true })
    );
    expect(Array.from(primaryInst.selectedPaths)).toEqual([
      '/mnt/user/vault/local-file1.jpg',
      '/mnt/user/vault/local-file2.jpg',
    ]);
  });

  it('handles inter-window file drop and triggers cross-window refresh', async () => {
    const primaryInst = getActiveFmInstance();
    await primaryInst.loadPath('/mnt/user/vault');

    const secInst = openNewFileManagerWindow('/mnt/remotes/onedrive');
    await secInst.loadPath('/mnt/remotes/onedrive');

    const refreshSpy = vi.fn();
    ZettEventBus.on('fm:refresh', refreshSpy);

    // Simulate dropping files from primary instance into secondary instance viewport
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true });
    dropEvent.dataTransfer = {
      getData: (format) => {
        if (format === 'application/json') {
          return JSON.stringify({
            paths: ['/mnt/user/vault/local-file1.jpg'],
            action: 'move',
            sourcePath: '/mnt/user/vault',
            sourceInstanceId: primaryInst.id,
          });
        }
        return '';
      },
      files: [],
    };

    secInst.viewport.dispatchEvent(dropEvent);

    // Wait microtasks for transfer
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(refreshSpy).toHaveBeenCalled();
  });

  it('destroys secondary instance cleanly removing it from DOM and unregistering from DockManager', () => {
    const secInst = openNewFileManagerWindow('/mnt/remotes/onedrive');
    const secWinId = secInst.id;
    expect(document.getElementById(secWinId)).not.toBeNull();

    secInst.destroy();
    expect(document.getElementById(secWinId)).toBeNull();
  });
});
