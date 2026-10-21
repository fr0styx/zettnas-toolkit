import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  initFileManager,
  handleFmKeydown,
  ensureFmFocus,
  scrollIndexIntoView,
  isFmActive,
  getFmSelectedPaths,
  getFmSelectionState,
  setFmStateForTesting,
} from '../components/file-manager.js';

vi.mock('../api.js', () => ({
  api: {
    post: vi.fn().mockResolvedValue({}),
    get: vi.fn().mockResolvedValue({ current: '/mnt/user', dirs: [], roots: ['/mnt/user'] }),
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

describe('File Manager Keyboard Navigation & Multi-Selection', () => {
  const sampleFiles = [
    { name: '..', path: '/mnt', is_dir: true, size: 0 },
    { name: 'Document 1.docx', path: '/mnt/user/Document 1.docx', is_dir: false, size: 1024 },
    { name: 'Document 2.docx', path: '/mnt/user/Document 2.docx', is_dir: false, size: 2048 },
    { name: 'Document 3.docx', path: '/mnt/user/Document 3.docx', is_dir: false, size: 3072 },
    { name: 'Document 4.docx', path: '/mnt/user/Document 4.docx', is_dir: false, size: 4096 },
    { name: 'Document 5.docx', path: '/mnt/user/Document 5.docx', is_dir: false, size: 5120 },
  ];

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
    });
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('declares tabindex="-1" on #file-manager-window and tabindex="0" on #fm-viewport', () => {
    const fmWin = document.getElementById('file-manager-window');
    const viewport = document.getElementById('fm-viewport');

    expect(fmWin).not.toBeNull();
    expect(fmWin.getAttribute('tabindex')).toBe('-1');
    expect(viewport).not.toBeNull();
    expect(viewport.getAttribute('tabindex')).toBe('0');
  });

  it('ensures focus is directed into #fm-viewport without stealing from text inputs', () => {
    const viewport = document.getElementById('fm-viewport');
    const pathInput = document.getElementById('fm-path-input');

    ensureFmFocus();
    expect(document.activeElement).toBe(viewport);

    // If an input is focused, ensureFmFocus must not steal focus
    pathInput.focus();
    expect(document.activeElement).toBe(pathInput);
    ensureFmFocus();
    expect(document.activeElement).toBe(pathInput);
  });

  it('selects the first selectable item (skipping parent folder ..) on initial ArrowDown', () => {
    const event = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true });
    const preventSpy = vi.spyOn(event, 'preventDefault');
    const stopSpy = vi.spyOn(event, 'stopPropagation');

    handleFmKeydown(event);

    expect(preventSpy).toHaveBeenCalled();
    expect(stopSpy).toHaveBeenCalled();
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Document 1.docx']);
    const state = getFmSelectionState();
    expect(state.lastSelectedIndex).toBe(1);
    expect(state.selectionAnchorIndex).toBe(1);
  });

  it('steps single selection down on consecutive plain ArrowDown presses', () => {
    // Select first item
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Document 1.docx']);

    // Step to second item
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Document 2.docx']);
    expect(getFmSelectionState().lastSelectedIndex).toBe(2);

    // Step to third item
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Document 3.docx']);
    expect(getFmSelectionState().lastSelectedIndex).toBe(3);
  });

  it('performs multi-selection expansion with Shift + ArrowDown', () => {
    // Start at Document 1 (index 1)
    setFmStateForTesting({
      selectedPaths: ['/mnt/user/Document 1.docx'],
      lastSelectedIndex: 1,
      selectionAnchorIndex: 1,
    });

    const shiftDownEvent = new KeyboardEvent('keydown', {
      key: 'ArrowDown',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    const preventSpy = vi.spyOn(shiftDownEvent, 'preventDefault');
    const stopSpy = vi.spyOn(shiftDownEvent, 'stopPropagation');

    handleFmKeydown(shiftDownEvent);

    expect(preventSpy).toHaveBeenCalled();
    expect(stopSpy).toHaveBeenCalled();
    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Document 1.docx',
      '/mnt/user/Document 2.docx',
    ]);
    expect(getFmSelectionState().lastSelectedIndex).toBe(2);
    expect(getFmSelectionState().selectionAnchorIndex).toBe(1);

    // Press Shift + ArrowDown again -> selects Document 1, 2, 3
    handleFmKeydown(
      new KeyboardEvent('keydown', { key: 'ArrowDown', shiftKey: true, bubbles: true, cancelable: true })
    );
    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Document 1.docx',
      '/mnt/user/Document 2.docx',
      '/mnt/user/Document 3.docx',
    ]);
    expect(getFmSelectionState().lastSelectedIndex).toBe(3);
    expect(getFmSelectionState().selectionAnchorIndex).toBe(1);
  });

  it('contracts selection when reversing direction with Shift + ArrowUp', () => {
    // Range is currently Document 1 to Document 3 (anchor 1, cursor 3)
    setFmStateForTesting({
      selectedPaths: [
        '/mnt/user/Document 1.docx',
        '/mnt/user/Document 2.docx',
        '/mnt/user/Document 3.docx',
      ],
      lastSelectedIndex: 3,
      selectionAnchorIndex: 1,
    });

    // Press Shift + ArrowUp -> should contract to Document 1 & 2
    handleFmKeydown(
      new KeyboardEvent('keydown', { key: 'ArrowUp', shiftKey: true, bubbles: true, cancelable: true })
    );
    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Document 1.docx',
      '/mnt/user/Document 2.docx',
    ]);
    expect(getFmSelectionState().lastSelectedIndex).toBe(2);
    expect(getFmSelectionState().selectionAnchorIndex).toBe(1);

    // Press Shift + ArrowUp again -> should contract to just Document 1
    handleFmKeydown(
      new KeyboardEvent('keydown', { key: 'ArrowUp', shiftKey: true, bubbles: true, cancelable: true })
    );
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Document 1.docx']);
    expect(getFmSelectionState().lastSelectedIndex).toBe(1);
  });

  it('inverts and expands selection upwards past anchor with Shift + ArrowUp', () => {
    // Start at Document 3 (index 3)
    setFmStateForTesting({
      selectedPaths: ['/mnt/user/Document 3.docx'],
      lastSelectedIndex: 3,
      selectionAnchorIndex: 3,
    });

    // Press Shift + ArrowUp -> selects Document 2 & Document 3
    handleFmKeydown(
      new KeyboardEvent('keydown', { key: 'ArrowUp', shiftKey: true, bubbles: true, cancelable: true })
    );
    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Document 2.docx',
      '/mnt/user/Document 3.docx',
    ]);
    expect(getFmSelectionState().lastSelectedIndex).toBe(2);
    expect(getFmSelectionState().selectionAnchorIndex).toBe(3);

    // Press Shift + ArrowUp again -> selects Document 1, 2, 3
    handleFmKeydown(
      new KeyboardEvent('keydown', { key: 'ArrowUp', shiftKey: true, bubbles: true, cancelable: true })
    );
    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Document 1.docx',
      '/mnt/user/Document 2.docx',
      '/mnt/user/Document 3.docx',
    ]);
    expect(getFmSelectionState().lastSelectedIndex).toBe(1);
  });

  it('clears selection and resets indices on Escape', () => {
    setFmStateForTesting({
      selectedPaths: ['/mnt/user/Document 1.docx', '/mnt/user/Document 2.docx'],
      lastSelectedIndex: 2,
      selectionAnchorIndex: 1,
    });

    const escEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    handleFmKeydown(escEvent);

    expect(getFmSelectedPaths()).toEqual([]);
    expect(getFmSelectionState().lastSelectedIndex).toBe(-1);
    expect(getFmSelectionState().selectionAnchorIndex).toBe(-1);
  });

  it('selects all selectable files with Ctrl+A / Cmd+A excluding parent folder ..', () => {
    const ctrlAEvent = new KeyboardEvent('keydown', {
      key: 'a',
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });

    handleFmKeydown(ctrlAEvent);

    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Document 1.docx',
      '/mnt/user/Document 2.docx',
      '/mnt/user/Document 3.docx',
      '/mnt/user/Document 4.docx',
      '/mnt/user/Document 5.docx',
    ]);
    expect(getFmSelectedPaths()).not.toContain('/mnt');
  });

  it('handles Home and End keys for jumping to first and last items', () => {
    setFmStateForTesting({
      selectedPaths: ['/mnt/user/Document 3.docx'],
      lastSelectedIndex: 3,
      selectionAnchorIndex: 3,
    });

    // Home jumps to first selectable item (Document 1 at index 1)
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'Home', bubbles: true, cancelable: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Document 1.docx']);
    expect(getFmSelectionState().lastSelectedIndex).toBe(1);

    // End jumps to last item (Document 5 at index 5)
    handleFmKeydown(new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }));
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Document 5.docx']);
    expect(getFmSelectionState().lastSelectedIndex).toBe(5);
  });

  it('does not intercept keyboard events when user is typing in an input element', () => {
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    const arrowDownOnInput = new KeyboardEvent('keydown', {
      key: 'ArrowDown',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    const preventSpy = vi.spyOn(arrowDownOnInput, 'preventDefault');

    // Dispatch directly to the input element
    input.dispatchEvent(arrowDownOnInput);

    expect(preventSpy).not.toHaveBeenCalled();
    input.remove();
  });

  it('selects first two items when Shift + ArrowDown is pressed with no prior selection', () => {
    setFmStateForTesting({
      fileList: [...sampleFiles],
      selectedPaths: [],
      lastSelectedIndex: -1,
      selectionAnchorIndex: -1,
    });

    const shiftDownEvt = new KeyboardEvent('keydown', {
      key: 'ArrowDown',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    handleFmKeydown(shiftDownEvt);

    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Document 1.docx',
      '/mnt/user/Document 2.docx',
    ]);
    expect(getFmSelectionState().selectionAnchorIndex).toBe(1);
    expect(getFmSelectionState().lastSelectedIndex).toBe(2);
  });

  it('reclaims focus from desktop icons when Shift + ArrowDown is pressed', () => {
    const desktopIcon = document.getElementById('management-desktop-icon');
    desktopIcon.focus();
    expect(document.activeElement).toBe(desktopIcon);

    const shiftDownEvt = new KeyboardEvent('keydown', {
      key: 'ArrowDown',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    handleFmKeydown(shiftDownEvt);

    // Desktop icon must have been blurred and focus brought into viewport
    expect(document.activeElement).not.toBe(desktopIcon);
    const viewport = document.getElementById('fm-viewport');
    expect(document.activeElement).toBe(viewport);
    expect(getFmSelectedPaths().length).toBeGreaterThan(0);
  });

  it('does not bail out when closed modals without inline styles exist in DOM (regression)', () => {
    // Mimic production index.html where smart-modal-overlay has no inline style attribute
    const smartModal = document.createElement('div');
    smartModal.id = 'smart-modal-overlay';
    smartModal.className = 'smart-modal-backdrop';
    document.body.appendChild(smartModal);

    setFmStateForTesting({
      fileList: [...sampleFiles],
      selectedPaths: ['/mnt/user/Document 1.docx'],
      lastSelectedIndex: 1,
      selectionAnchorIndex: 1,
    });

    const shiftDownEvt = new KeyboardEvent('keydown', {
      key: 'ArrowDown',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    const preventSpy = vi.spyOn(shiftDownEvt, 'preventDefault');

    handleFmKeydown(shiftDownEvt);

    expect(preventSpy).toHaveBeenCalled();
    expect(getFmSelectedPaths()).toEqual([
      '/mnt/user/Document 1.docx',
      '/mnt/user/Document 2.docx',
    ]);

    smartModal.remove();
  });

  it('correctly respects open modal dialogs and blocks keydown navigation', () => {
    const smartModal = document.createElement('div');
    smartModal.id = 'smart-modal-overlay';
    smartModal.className = 'smart-modal-backdrop open';
    document.body.appendChild(smartModal);

    setFmStateForTesting({
      fileList: [...sampleFiles],
      selectedPaths: ['/mnt/user/Document 1.docx'],
      lastSelectedIndex: 1,
      selectionAnchorIndex: 1,
    });

    const shiftDownEvt = new KeyboardEvent('keydown', {
      key: 'ArrowDown',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    const preventSpy = vi.spyOn(shiftDownEvt, 'preventDefault');

    handleFmKeydown(shiftDownEvt);

    // Modal is open, so keydown navigation must be skipped
    expect(preventSpy).not.toHaveBeenCalled();
    expect(getFmSelectedPaths()).toEqual(['/mnt/user/Document 1.docx']);

    smartModal.remove();
  });
});
