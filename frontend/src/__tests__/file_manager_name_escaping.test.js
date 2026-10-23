import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { initFileManager, getActiveFmInstance, setFmStateForTesting } from '../components/file-manager.js';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ current: '/mnt/user', dirs: [], roots: ['/mnt/user'] }),
    post: vi.fn().mockResolvedValue({ success: true }),
    postRaw: vi.fn().mockResolvedValue({ ok: true }),
  },
  auth: { getToken: vi.fn().mockReturnValue('test-token') },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

// Another user can choose any file name; the list view must show it as text.
describe('File manager shows file names as text', () => {
  const evil = 'report.<img src=x data-probe=1>';

  beforeEach(() => {
    document.body.innerHTML = '<div id="desktop"></div>';
    window._fmInitialized = false;
    delete document._fmDocKbBound;
    initFileManager();
    setFmStateForTesting({
      fileList: [{ name: evil, path: `/mnt/user/${evil}`, is_dir: false, size: 1, mtime: 1700000000, mode: '0644' }],
      selectedPaths: [],
      lastSelectedIndex: -1,
      selectionAnchorIndex: -1,
      currentPath: '/mnt/user',
      viewMode: 'list',
    });
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('escapes the extension in the Type column', () => {
    const inst = getActiveFmInstance();
    inst.renderViewport();
    const typeCells = [...inst.windowEl.querySelectorAll('.fm-row .fm-col-type')];
    expect(typeCells.length).toBeGreaterThan(0);
    expect(inst.windowEl.querySelector('[data-probe]')).toBeNull();
    expect(typeCells.some((c) => c.textContent.includes('<IMG'))).toBe(true);
  });
});
