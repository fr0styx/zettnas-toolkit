import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  initFileManager,
  getActiveFmInstance,
} from '../components/file-manager.js';
import { api } from '../api.js';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ current: '/mnt/remotes/onedrive-personal', dirs: [], roots: ['/mnt/user', '/mnt/remotes'] }),
    post: vi.fn().mockResolvedValue({ success: true, has_conflict: false, transferred: 2 }),
    postRaw: vi.fn().mockResolvedValue({ ok: true }),
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
  showBottomSheet: vi.fn(),
}));

describe('File Manager Drag and Drop Comprehensive Suite', () => {
  const sampleFiles = [
    { name: '..', path: '/mnt/remotes', is_dir: true, size: 0 },
    { name: 'Documents', path: '/mnt/remotes/onedrive-personal/Documents', is_dir: true, size: 0 },
    { name: 'Desktop', path: '/mnt/remotes/onedrive-personal/Desktop', is_dir: true, size: 0 },
    { name: 'Book.xlsx', path: '/mnt/remotes/onedrive-personal/Book.xlsx', is_dir: false, size: 7988 },
    { name: 'Document 1.docx', path: '/mnt/remotes/onedrive-personal/Document 1.docx', is_dir: false, size: 11009 },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="desktop"><div class="chassis-hero-box fm-desktop-icon" id="fm-desktop-icon"></div></div>';
    window._fmInitialized = false;
    delete document._fmDocKbBound;
    initFileManager();

    const inst = getActiveFmInstance();
    inst.fileList = [...sampleFiles];
    inst.currentPath = '/mnt/remotes/onedrive-personal';
    inst.renderViewport();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    window._activeDragPayload = null;
  });

  it('sets window._activeDragPayload and dataTransfer on dragstart, and clears on dragend', () => {
    const inst = getActiveFmInstance();
    const row = inst.list.querySelector('.fm-row[data-path="/mnt/remotes/onedrive-personal/Book.xlsx"]');
    expect(row).not.toBeNull();

    const dtData = {};
    const mockDataTransfer = {
      setData: vi.fn((type, val) => { dtData[type] = val; }),
      effectAllowed: '',
      setDragImage: vi.fn(),
    };

    const dragStartEvent = new Event('dragstart', { bubbles: true, cancelable: true });
    Object.defineProperty(dragStartEvent, 'dataTransfer', { value: mockDataTransfer });
    Object.defineProperty(dragStartEvent, 'target', { value: row });

    inst.list.dispatchEvent(dragStartEvent);

    expect(window._activeDragPayload).not.toBeNull();
    expect(window._activeDragPayload.paths).toEqual(['/mnt/remotes/onedrive-personal/Book.xlsx']);
    expect(mockDataTransfer.setData).toHaveBeenCalledWith('application/json', expect.any(String));

    // Test dragend cleanup
    const dragEndEvent = new Event('dragend', { bubbles: true });
    inst.list.dispatchEvent(dragEndEvent);
    expect(window._activeDragPayload).toBeNull();
  });

  it('drops into currentPath when dragging files over whitespace or non-folder rows', async () => {
    const inst = getActiveFmInstance();
    window._activeDragPayload = {
      paths: ['/mnt/user/homes/alice/Document.docx', '/mnt/user/homes/alice/photo.jpg'],
      action: 'move',
      sourcePath: '/mnt/user/homes/alice',
    };

    api.post.mockImplementation((url) => {
      if (url === '/api/fs/conflict-check') return Promise.resolve({ has_conflict: false, conflicts: [] });
      if (url === '/api/fs/transfer') return Promise.resolve({ status: 'ok', transferred: 2 });
      return Promise.resolve({});
    });

    const fileRow = inst.list.querySelector('.fm-row[data-path="/mnt/remotes/onedrive-personal/Book.xlsx"]');

    const dropEvent = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, 'dataTransfer', {
      value: { getData: vi.fn(() => '') },
    });
    Object.defineProperty(dropEvent, 'target', { value: fileRow });

    await inst.viewport.dispatchEvent(dropEvent);

    expect(api.post).toHaveBeenCalledWith('/api/fs/transfer', {
      sources: ['/mnt/user/homes/alice/Document.docx', '/mnt/user/homes/alice/photo.jpg'],
      destination_dir: '/mnt/remotes/onedrive-personal',
      action: 'move',
      collision_policy: 'merge',
    });
  });

  it('drops into specific subfolder when dragging over a directory row', async () => {
    const inst = getActiveFmInstance();
    window._activeDragPayload = {
      paths: ['/mnt/user/homes/alice/Doc1.docx'],
      action: 'move',
      sourcePath: '/mnt/user/homes/alice',
    };

    api.post.mockImplementation((url) => {
      if (url === '/api/fs/conflict-check') return Promise.resolve({ has_conflict: false, conflicts: [] });
      if (url === '/api/fs/transfer') return Promise.resolve({ status: 'ok', transferred: 1 });
      return Promise.resolve({});
    });

    const folderRow = inst.list.querySelector('.fm-row[data-path="/mnt/remotes/onedrive-personal/Documents"]');
    expect(folderRow).not.toBeNull();

    // Trigger dragover on the folder row
    const dragOverEvent = new Event('dragover', { bubbles: true, cancelable: true });
    Object.defineProperty(dragOverEvent, 'dataTransfer', { value: { dropEffect: '' } });
    Object.defineProperty(dragOverEvent, 'target', { value: folderRow });
    inst.viewport.dispatchEvent(dragOverEvent);

    expect(folderRow.classList.contains('fm-drop-hover')).toBe(true);

    // Trigger drop
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, 'dataTransfer', {
      value: { getData: vi.fn(() => '') },
    });
    Object.defineProperty(dropEvent, 'target', { value: folderRow });

    await inst.viewport.dispatchEvent(dropEvent);

    expect(api.post).toHaveBeenCalledWith('/api/fs/transfer', {
      sources: ['/mnt/user/homes/alice/Doc1.docx'],
      destination_dir: '/mnt/remotes/onedrive-personal/Documents',
      action: 'move',
      collision_policy: 'merge',
    });
  });

  it('allows dropping files onto Left Sidebar Tree items', async () => {
    const inst = getActiveFmInstance();
    const tree = inst.sidebarTree;
    tree.render();

    window._activeDragPayload = {
      paths: ['/mnt/remotes/onedrive-personal/Book.xlsx'],
      action: 'move',
      sourcePath: '/mnt/remotes/onedrive-personal',
    };

    api.post.mockImplementation((url) => {
      if (url === '/api/fs/conflict-check') return Promise.resolve({ has_conflict: false, conflicts: [] });
      if (url === '/api/fs/transfer') return Promise.resolve({ status: 'ok', transferred: 1 });
      return Promise.resolve({});
    });

    const userSharesItem = tree.container.querySelector('.fm-tree-item[data-path="/mnt/user"]');
    expect(userSharesItem).not.toBeNull();

    // Dragover on sidebar item
    const dragOverEvent = new Event('dragover', { bubbles: true, cancelable: true });
    Object.defineProperty(dragOverEvent, 'dataTransfer', { value: { dropEffect: '' } });
    userSharesItem.dispatchEvent(dragOverEvent);
    expect(userSharesItem.classList.contains('fm-tree-drop-hover')).toBe(true);

    // Drop on sidebar item
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, 'dataTransfer', { value: { getData: vi.fn(() => '') } });
    await userSharesItem.dispatchEvent(dropEvent);

    expect(userSharesItem.classList.contains('fm-tree-drop-hover')).toBe(false);
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/fs/transfer', {
        sources: ['/mnt/remotes/onedrive-personal/Book.xlsx'],
        destination_dir: '/mnt/user',
        action: 'move',
        collision_policy: 'merge',
      });
    });
  });

  it('allows dropping files onto breadcrumbs to move to parent folder', async () => {
    const inst = getActiveFmInstance();
    inst.renderBreadcrumbs();

    window._activeDragPayload = {
      paths: ['/mnt/remotes/onedrive-personal/Book.xlsx'],
      action: 'move',
      sourcePath: '/mnt/remotes/onedrive-personal',
    };

    api.post.mockImplementation((url) => {
      if (url === '/api/fs/conflict-check') return Promise.resolve({ has_conflict: false, conflicts: [] });
      if (url === '/api/fs/transfer') return Promise.resolve({ status: 'ok', transferred: 1 });
      return Promise.resolve({});
    });

    const crumbs = inst.breadcrumbs.querySelectorAll('.fm-crumb');
    expect(crumbs.length).toBeGreaterThan(0);
    let remotesCrumb = null;
    crumbs.forEach((c) => {
      if (c.textContent === 'remotes') remotesCrumb = c;
    });
    expect(remotesCrumb).not.toBeNull();

    // Drop on 'remotes' crumb
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, 'dataTransfer', { value: { getData: vi.fn(() => '') } });
    await remotesCrumb.dispatchEvent(dropEvent);

    expect(api.post).toHaveBeenCalledWith('/api/fs/transfer', {
      sources: ['/mnt/remotes/onedrive-personal/Book.xlsx'],
      destination_dir: '/mnt/remotes',
      action: 'move',
      collision_policy: 'merge',
    });
  });
});
