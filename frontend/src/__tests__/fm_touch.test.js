import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ current: '/mnt/user', dirs: [], roots: ['/mnt/user'] }),
    post: vi.fn().mockResolvedValue({ success: true }),
    postRaw: vi.fn().mockResolvedValue({ ok: true }),
  },
  auth: { getToken: vi.fn().mockReturnValue('') },
  ApiError: class ApiError extends Error {},
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

function pointer(el, type, pointerType) {
  const ev = new Event(type, { bubbles: true });
  Object.defineProperty(ev, 'pointerType', { value: pointerType });
  el.dispatchEvent(ev);
}
function click(el) {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
}

async function makeExplorer() {
  const { FileManagerWindow } = await import('../components/file-manager.js');
  const fm = new FileManagerWindow('fm-touch', 'fm-touch', '/mnt/user/Photos');
  fm.loadPath = vi.fn();
  fm.handleAction = vi.fn();
  fm.updateRowSelectionUI = vi.fn();
  fm.updateSelectionToolbar = vi.fn();
  fm.renderViewport = vi.fn();
  fm.init();
  fm.fileList = [
    { name: '..', path: '/mnt/user', is_dir: true },
    { name: 'Trips', path: '/mnt/user/Photos/Trips', is_dir: true },
    { name: 'beach.jpg', path: '/mnt/user/Photos/beach.jpg', is_dir: false },
  ];
  fm.list.innerHTML = fm.fileList.map((f) => `<div class="fm-row" data-path="${f.path}"><span class="fm-col-check"><input type="checkbox" class="fm-checkbox"></span><span class="fm-name">${f.name}</span></div>`).join('');
  const row = (name) => fm.list.querySelector(`[data-path="${fm.fileList.find((f) => f.name === name).path}"] .fm-name`);
  return { fm, row };
}

describe('explorer on touch screens', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('a tap opens a photo, a folder, and the parent folder', async () => {
    const { fm, row } = await makeExplorer();
    pointer(row('beach.jpg'), 'pointerdown', 'touch');
    click(row('beach.jpg'));
    expect(fm.handleAction).toHaveBeenCalledWith('preview', '/mnt/user/Photos/beach.jpg', 'beach.jpg');
    fm._touchOpenAt = 0;
    pointer(row('Trips'), 'pointerdown', 'touch');
    click(row('Trips'));
    expect(fm.loadPath).toHaveBeenCalledWith('/mnt/user/Photos/Trips');
    fm._touchOpenAt = 0;
    pointer(row('..'), 'pointerdown', 'touch');
    click(row('..'));
    expect(fm.loadPath).toHaveBeenCalledWith('/mnt/user');
  });

  it('the second tap of a double-tap does not open the row that took its place', async () => {
    const { fm, row } = await makeExplorer();
    pointer(row('Trips'), 'pointerdown', 'touch');
    click(row('Trips'));
    click(row('beach.jpg'));
    row('beach.jpg').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    expect(fm.loadPath).toHaveBeenCalledTimes(1);
    expect(fm.handleAction).not.toHaveBeenCalled();
  });

  it('while items are selected, a tap adds or removes one instead of opening', async () => {
    const { fm, row } = await makeExplorer();
    fm.selectedPaths.add('/mnt/user/Photos/Trips');
    pointer(row('beach.jpg'), 'pointerdown', 'touch');
    click(row('beach.jpg'));
    expect(fm.handleAction).not.toHaveBeenCalled();
    expect([...fm.selectedPaths]).toEqual(['/mnt/user/Photos/Trips', '/mnt/user/Photos/beach.jpg']);
    click(row('Trips'));
    expect([...fm.selectedPaths]).toEqual(['/mnt/user/Photos/beach.jpg']);
  });

  it('the mouse keeps click to select and double-click to open', async () => {
    const { fm, row } = await makeExplorer();
    pointer(row('beach.jpg'), 'pointerdown', 'mouse');
    click(row('beach.jpg'));
    expect(fm.handleAction).not.toHaveBeenCalled();
    expect([...fm.selectedPaths]).toEqual(['/mnt/user/Photos/beach.jpg']);
    row('beach.jpg').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    expect(fm.handleAction).toHaveBeenCalledWith('preview', '/mnt/user/Photos/beach.jpg', 'beach.jpg');
  });
});

describe('windows after the screen widens', () => {
  it('a window left without a position goes back below the navigation bar', async () => {
    document.body.innerHTML = '<nav class="suite-navbar"></nav><div class="os-window" id="vm-window" style="display:block"></div>';
    const bar = document.querySelector('.suite-navbar');
    const win = document.getElementById('vm-window');
    bar.getBoundingClientRect = () => ({ top: 0, bottom: 52, left: 0, right: 1280, width: 1280, height: 52 });
    win.getBoundingClientRect = () => ({ top: Number.parseInt(win.style.top || '0', 10), left: 0, width: 600, height: 400, bottom: 400, right: 600 });
    const dock = await import('../components/dock.js');
    window.innerWidth = 375;
    dock.restoreWindowsAfterWiden();
    expect(win.style.top).toBe('');
    window.innerWidth = 1280;
    dock.restoreWindowsAfterWiden();
    expect(win.style.top).toBe('60px');
    expect(win.style.left).toBe('340px');
  });
});

describe('viewer toolbar on a phone', () => {
  it('fades the cut-off edge and offers a chevron while more tools are off screen', async () => {
    const { bindToolbarScrollHint } = await import('../components/file-preview-modal.js');
    document.body.innerHTML = '<div id="tb"></div><button id="more" hidden></button>';
    const tb = document.getElementById('tb');
    const more = document.getElementById('more');
    Object.defineProperty(tb, 'scrollWidth', { value: 320, configurable: true });
    Object.defineProperty(tb, 'clientWidth', { value: 200, configurable: true });
    tb.scrollBy = vi.fn();
    bindToolbarScrollHint(tb, more);
    expect(tb.classList.contains('ql-more-right')).toBe(true);
    expect(more.hidden).toBe(false);
    more.click();
    expect(tb.scrollBy).toHaveBeenCalledWith({ left: 160, behavior: 'smooth' });
    tb.scrollLeft = 120;
    tb.dispatchEvent(new Event('scroll'));
    expect(tb.classList.contains('ql-more-right')).toBe(false);
    expect(tb.classList.contains('ql-more-left')).toBe(true);
    expect(more.classList.contains('is-back')).toBe(true);
    Object.defineProperty(tb, 'scrollWidth', { value: 200, configurable: true });
    tb.scrollLeft = 0;
    tb.dispatchEvent(new Event('scroll'));
    expect(more.hidden).toBe(true);
  });
});
