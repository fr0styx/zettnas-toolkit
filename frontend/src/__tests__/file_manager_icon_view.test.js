import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  initFileManager,
  handleFmKeydown,
  ensureFmFocus,
  getFmSelectedPaths,
  getFmSelectionState,
  getFmViewMode,
  setFmStateForTesting,
  openNewFileManagerWindow,
  getActiveFmInstance,
} from '../components/file-manager.js';

vi.mock('../api.js', () => ({
  api: {
    post: vi.fn().mockResolvedValue({}),
    get: vi.fn().mockResolvedValue({ current: '/mnt/user', dirs: [], roots: ['/mnt/user'] }),
  },
  auth: {
    getToken: vi.fn().mockReturnValue('mock-token-xyz'),
  },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
}));

describe('File Manager Icon View & Grid Mode', () => {
  const sampleFiles = [
    { name: '..', path: '/mnt', is_dir: true, size: 0 },
    { name: 'Photos', path: '/mnt/user/Photos', is_dir: true, size: 0 },
    { name: 'vacation.jpg', path: '/mnt/user/vacation.jpg', is_dir: false, size: 1048576 },
    { name: 'screenshot.png', path: '/mnt/user/screenshot.png', is_dir: false, size: 524288 },
    { name: 'report.pdf', path: '/mnt/user/report.pdf', is_dir: false, size: 204800 },
    { name: 'notes.txt', path: '/mnt/user/notes.txt', is_dir: false, size: 4096 },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    document.body.innerHTML = `
      <div id="desktop"></div>
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

  it('renders view toggle buttons in File Explorer toolbar', () => {
    const btnList = document.getElementById('fm-btn-view-list');
    const btnIcon = document.getElementById('fm-btn-view-icon');

    expect(btnList).not.toBeNull();
    expect(btnIcon).not.toBeNull();
    expect(btnList.classList.contains('active')).toBe(true);
    expect(btnIcon.classList.contains('active')).toBe(false);
  });

  it('switches to icon view and updates DOM classes and localStorage', () => {
    const inst = getActiveFmInstance();
    const btnIcon = document.getElementById('fm-btn-view-icon');
    const btnList = document.getElementById('fm-btn-view-list');
    const fmWin = document.getElementById('file-manager-window');

    btnIcon.click();

    expect(inst.viewMode).toBe('icon');
    expect(getFmViewMode()).toBe('icon');
    expect(localStorage.getItem('zettnas_fm_view_mode')).toBe('icon');
    expect(fmWin.classList.contains('fm-mode-icon')).toBe(true);
    expect(btnIcon.classList.contains('active')).toBe(true);
    expect(btnList.classList.contains('active')).toBe(false);

    // Switching back to list view
    btnList.click();
    expect(inst.viewMode).toBe('list');
    expect(getFmViewMode()).toBe('list');
    expect(localStorage.getItem('zettnas_fm_view_mode')).toBe('list');
    expect(fmWin.classList.contains('fm-mode-icon')).toBe(false);
    expect(btnList.classList.contains('active')).toBe(true);
    expect(btnIcon.classList.contains('active')).toBe(false);
  });

  it('renders cards in icon view with image thumbnails and metadata', () => {
    const inst = getActiveFmInstance();
    inst.setViewMode('icon');

    const cards = document.querySelectorAll('.fm-grid-card');
    expect(cards.length).toBe(sampleFiles.length);

    // Card 0 is '..' parent directory
    expect(cards[0].dataset.name).toBe('..');

    // Card 1 is 'Photos' directory
    expect(cards[1].dataset.name).toBe('Photos');
    expect(cards[1].querySelector('.fm-card-meta').textContent).toBe('Folder');

    // Card 2 is 'vacation.jpg' image
    expect(cards[2].dataset.name).toBe('vacation.jpg');
    const imgEl = cards[2].querySelector('img.fm-thumb-img');
    expect(imgEl).not.toBeNull();
    expect(imgEl.getAttribute('loading')).toBe('lazy');
    expect(imgEl.src).toContain('/api/fs/download?path=%2Fmnt%2Fuser%2Fvacation.jpg');
    expect(imgEl.src).toContain('token=mock-token-xyz');

    // Card 4 is 'report.pdf' non-image
    expect(cards[4].dataset.name).toBe('report.pdf');
    expect(cards[4].querySelector('img.fm-thumb-img')).toBeNull();
    expect(cards[4].querySelector('svg')).not.toBeNull();
  });

  it('supports single click selection and checkbox toggle on cards in icon view', () => {
    const inst = getActiveFmInstance();
    inst.setViewMode('icon');

    const cards = document.querySelectorAll('.fm-grid-card');
    // Click on vacation.jpg card
    cards[2].click();
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/vacation.jpg']);
    expect(cards[2].classList.contains('selected')).toBe(true);

    // Toggle checkbox on report.pdf
    const pdfCheckbox = cards[4].querySelector('.fm-card-checkbox');
    pdfCheckbox.checked = true;
    pdfCheckbox.dispatchEvent(new Event('click', { bubbles: true }));

    const selected = getFmSelectedPaths();
    expect(selected).toContain('/mnt/user/vacation.jpg');
    expect(selected).toContain('/mnt/user/report.pdf');
  });

  it('supports Shift+Click multi-selection range across grid cards', () => {
    const inst = getActiveFmInstance();
    inst.setViewMode('icon');

    const cards = document.querySelectorAll('.fm-grid-card');
    // First select Photos (index 1)
    cards[1].click();
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Photos']);

    // Shift-click report.pdf (index 4)
    cards[4].dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));

    const selected = getFmSelectedPaths();
    expect(selected).toEqual([
      '/mnt/user/Photos',
      '/mnt/user/vacation.jpg',
      '/mnt/user/screenshot.png',
      '/mnt/user/report.pdf',
    ]);
  });

  it('navigates grid with ArrowRight and ArrowLeft in icon view', () => {
    const inst = getActiveFmInstance();
    inst.setViewMode('icon');

    // Initial ArrowRight starts at first selectable file (Photos, idx 1)
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Photos']);

    // Step next with ArrowRight -> vacation.jpg (idx 2)
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/vacation.jpg']);

    // Step previous with ArrowLeft -> Photos (idx 1)
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Photos']);
  });

  it('expands multi-selection with Shift+ArrowRight in icon view', () => {
    const inst = getActiveFmInstance();
    inst.setViewMode('icon');

    // Start at Photos (idx 1)
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Photos']);

    // Shift + ArrowRight expands to vacation.jpg
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowRight', shiftKey: true, bubbles: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Photos', '/mnt/user/vacation.jpg']);

    // Shift + ArrowRight expands to screenshot.png
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowRight', shiftKey: true, bubbles: true }));
    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Photos',
      '/mnt/user/vacation.jpg',
      '/mnt/user/screenshot.png',
    ]);
  });

  it('synchronizes view mode across multiple open File Explorer windows', () => {
    const primary = getActiveFmInstance();
    expect(primary.viewMode).toBe('list');

    // Open second window
    openNewFileManagerWindow('/mnt/user/Photos');
    const secWinEl = document.getElementById('file-manager-window-2');
    expect(secWinEl).not.toBeNull();

    // Primary window switches to icon view
    primary.setViewMode('icon');
    expect(primary.viewMode).toBe('icon');

    // Second window reflects icon view as well
    expect(secWinEl.classList.contains('fm-mode-icon')).toBe(true);
  });
});
