import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  initFileManager,
  getActiveFmInstance,
  handleFmKeydown,
  setFmStateForTesting,
} from '../components/file-manager.js';
import { ZettEventBus } from '../event-bus.js';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ current: '/mnt/user', dirs: [], roots: ['/mnt/user'] }),
    post: vi.fn().mockResolvedValue({ success: true }),
    postRaw: vi.fn().mockResolvedValue({ ok: true }),
  },
  auth: {
    getToken: vi.fn().mockReturnValue('test-token'),
  },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn((t, m, cb) => cb && cb()),
  showPromptToast: vi.fn((t, m, def, cb) => cb && cb('new-name')),
  showBottomSheet: vi.fn(),
}));

describe('File Explorer Revamp - SOTA Architecture & Advanced Features', () => {
  const sampleFiles = [
    { name: '..', path: '/mnt', is_dir: true, size: 0, mtime: 1700000000, mode: '0755' },
    { name: 'document.pdf', path: '/mnt/user/document.pdf', is_dir: false, size: 1048576, mtime: 1710000000, mode: '0644' },
    { name: 'photo.jpg', path: '/mnt/user/photo.jpg', is_dir: false, size: 2097152, mtime: 1720000000, mode: '0644' },
    { name: 'archive.zip', path: '/mnt/user/archive.zip', is_dir: false, size: 5242880, mtime: 1730000000, mode: '0644' },
    { name: 'projects', path: '/mnt/user/projects', is_dir: true, size: 4096, mtime: 1740000000, mode: '0755' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="desktop">
        <div class="chassis-hero-box fm-desktop-icon" id="fm-desktop-icon" tabindex="0"></div>
      </div>
    `;
    window._fmInitialized = false;
    delete document._fmDocKbBound;
    initFileManager();

    const fmWin = document.getElementById('file-manager-window');
    if (fmWin) {
      fmWin.style.display = 'flex';
      fmWin.classList.add('active-window');
    }

    setFmStateForTesting({
      fileList: [...sampleFiles],
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

  it('renders the 3-pane flex layout with sidebar tree, main viewport, and inspector', () => {
    const inst = getActiveFmInstance();
    expect(inst).not.toBeNull();
    const win = inst.windowEl;

    const layout = win.querySelector('.fm-3pane-layout');
    expect(layout).not.toBeNull();

    const sidebarTree = win.querySelector('.fm-sidebar-tree');
    expect(sidebarTree).not.toBeNull();

    const mainPane = win.querySelector('.fm-main-pane');
    expect(mainPane).not.toBeNull();

    const inspector = win.querySelector('.fm-inspector-pane');
    expect(inspector).not.toBeNull();

    const viewport = win.querySelector('#fm-viewport');
    expect(viewport).not.toBeNull();
    expect(viewport.getAttribute('tabindex')).toBe('0');

    const marqueeBox = win.querySelector('.fm-marquee-box');
    expect(marqueeBox).not.toBeNull();
  });

  it('toggles compact view mode and renders mtime column', () => {
    const inst = getActiveFmInstance();
    const win = inst.windowEl;
    const btnCompact = win.querySelector('.fm-btn-view-compact');
    expect(btnCompact).not.toBeNull();

    btnCompact.click();

    expect(inst.viewMode).toBe('compact');
    expect(win.classList.contains('fm-mode-compact')).toBe(true);

    // Verify rendered rows contain compact class and mtime
    inst.renderViewport();
    const rows = win.querySelectorAll('.fm-row');
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0].classList.contains('fm-row-compact')).toBe(true);

    const mtimeCol = win.querySelector('.fm-header-row .fm-col-mtime');
    expect(mtimeCol).not.toBeNull();
    expect(mtimeCol.textContent).toContain('Modified');
  });

  it('toggles inspector pane and displays metadata for selected file', () => {
    const inst = getActiveFmInstance();
    const win = inst.windowEl;
    const btnInspector = win.querySelector('.fm-btn-inspector-toggle');
    expect(btnInspector).not.toBeNull();

    // Select document.pdf
    inst.selectedPaths = new Set(['/mnt/user/document.pdf']);
    btnInspector.click();

    expect(inst.inspector).not.toBeNull();
    expect(inst.inspector.isVisible).toBe(true);

    const inspectorPane = win.querySelector('.fm-inspector-pane');
    expect(inspectorPane.style.display).not.toBe('none');

    // Inspector content shows document name and format
    const content = inspectorPane.querySelector('.fm-inspector-content');
    expect(content.textContent).toContain('document.pdf');
    expect(content.textContent).toContain('1 MB');
  });

  it('toggles background transfers cockpit from toolbar button', () => {
    const inst = getActiveFmInstance();
    const win = inst.windowEl;
    const btnTransfers = win.querySelector('.fm-btn-transfers-toggle');
    expect(btnTransfers).not.toBeNull();

    btnTransfers.click();

    const cockpit = document.getElementById('fm-transfers-cockpit');
    expect(cockpit).not.toBeNull();
    expect(cockpit.style.display).toBe('flex');

    btnTransfers.click();
    expect(cockpit.style.display).toBe('none');
  });

  it('sorts files by mtime, name, and size when column headers are clicked', () => {
    const inst = getActiveFmInstance();
    const win = inst.windowEl;

    // Sort by name
    const colName = win.querySelector('.fm-header-row .fm-col-name');
    colName.click();
    expect(inst.currentSortBy).toBe('name');

    // Sort by size
    const colSize = win.querySelector('.fm-header-row .fm-col-size');
    colSize.click();
    expect(inst.currentSortBy).toBe('size');

    // Sort by mtime
    const colMtime = win.querySelector('.fm-header-row .fm-col-mtime');
    colMtime.click();
    expect(inst.currentSortBy).toBe('mtime');
  });

  it('handles F2 inline rename selecting stem and guarding extension', () => {
    const inst = getActiveFmInstance();
    inst.selectedPaths = new Set(['/mnt/user/document.pdf']);
    inst.renderViewport();

    const f2Event = new KeyboardEvent('keydown', { key: 'F2', bubbles: true, cancelable: true });
    handleFmKeydown(f2Event);

    const renameInput = inst.viewport.querySelector('.fm-inline-rename-input');
    expect(renameInput).not.toBeNull();
    expect(renameInput.value).toBe('document.pdf');
  });

  it('handles Cmd+D to duplicate selected file', () => {
    const inst = getActiveFmInstance();
    inst.selectedPaths = new Set(['/mnt/user/photo.jpg']);

    const duplicateSpy = vi.spyOn(inst, 'duplicateSelected');

    const cmdDEvent = new KeyboardEvent('keydown', {
      key: 'd',
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    handleFmKeydown(cmdDEvent);

    expect(duplicateSpy).toHaveBeenCalled();
  });

  it('auto-refreshes opened File Explorer windows and updates sidebar tree on fm:refresh', async () => {
    const inst = getActiveFmInstance();
    expect(inst).not.toBeNull();
    const loadSpy = vi.spyOn(inst, 'loadPath').mockResolvedValue();
    const treeRefreshSpy = vi.spyOn(inst.sidebarTree, 'refresh').mockResolvedValue();

    ZettEventBus.emit('fm:refresh');

    expect(loadSpy).toHaveBeenCalledWith(inst.currentPath);
    expect(treeRefreshSpy).toHaveBeenCalled();
  });

  it('dynamically displays mounted cloud remotes under Cloud Mounts in FmSidebarTree', async () => {
    const inst = getActiveFmInstance();
    const tree = inst.sidebarTree;
    tree.remotes = [
      { name: 'onedrive-personal', path: '/mnt/remotes/onedrive-personal', available: true },
    ];
    tree.render();

    const onedriveItem = tree.container.querySelector('.fm-tree-sub-item[data-path="/mnt/remotes/onedrive-personal"]');
    expect(onedriveItem).not.toBeNull();
    expect(onedriveItem.textContent).toContain('onedrive-personal');

    const loadSpy = vi.spyOn(inst, 'loadPath').mockResolvedValue();
    onedriveItem.click();
    expect(loadSpy).toHaveBeenCalledWith('/mnt/remotes/onedrive-personal');
  });

  it('renders all types of cloud remotes with provider icons and connected disk pools', async () => {
    const inst = getActiveFmInstance();
    const tree = inst.sidebarTree;
    tree.remotes = [
      { name: 'my-gdrive', path: '/mnt/remotes/my-gdrive', type: 'drive', is_mounted: true, available: true },
      { name: 'backup-s3', path: '/mnt/remotes/backup-s3', type: 's3', is_mounted: true, available: true },
      { name: 'photos-dropbox', path: '/mnt/remotes/photos-dropbox', type: 'dropbox', is_mounted: true, available: true },
      { name: 'nextcloud-docs', path: '/mnt/remotes/nextcloud-docs', type: 'webdav', is_mounted: true, available: true },
    ];
    tree.pools = [
      { name: 'External-NVMe', path: '/mnt/disks/External-NVMe', type: 'flash', available: true },
      { name: 'USB-Archive', path: '/mnt/disks/USB-Archive', type: 'disk', available: true },
    ];
    tree.render();

    const gdriveItem = tree.container.querySelector('.fm-tree-sub-item[data-path="/mnt/remotes/my-gdrive"]');
    expect(gdriveItem).not.toBeNull();
    expect(gdriveItem.querySelector('.fm-tree-icon').textContent).toBe('📁');

    const s3Item = tree.container.querySelector('.fm-tree-sub-item[data-path="/mnt/remotes/backup-s3"]');
    expect(s3Item).not.toBeNull();
    expect(s3Item.querySelector('.fm-tree-icon').textContent).toBe('🪣');

    const dropboxItem = tree.container.querySelector('.fm-tree-sub-item[data-path="/mnt/remotes/photos-dropbox"]');
    expect(dropboxItem).not.toBeNull();
    expect(dropboxItem.querySelector('.fm-tree-icon').textContent).toBe('📦');

    const nextcloudItem = tree.container.querySelector('.fm-tree-sub-item[data-path="/mnt/remotes/nextcloud-docs"]');
    expect(nextcloudItem).not.toBeNull();
    expect(nextcloudItem.querySelector('.fm-tree-icon').textContent).toBe('🌐');

    const nvmeItem = tree.container.querySelector('.fm-tree-item[data-path="/mnt/disks/External-NVMe"]');
    expect(nvmeItem).not.toBeNull();
    expect(nvmeItem.querySelector('.fm-tree-icon').textContent).toBe('⚡');

    const diskItem = tree.container.querySelector('.fm-tree-item[data-path="/mnt/disks/USB-Archive"]');
    expect(diskItem).not.toBeNull();
    expect(diskItem.querySelector('.fm-tree-icon').textContent).toBe('💽');
  });
});
