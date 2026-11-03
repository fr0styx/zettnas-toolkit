/** ARC-26: the preview window's toolbar and keys (file-preview-modal.js). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText: vi.fn(async () => {}) }));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { copyText } = await import('../utils.js');
const { openFilePreviewModal, closeFilePreviewModal } = await import('../components/file-preview-modal.js');

const q = (sel) => document.querySelector(sel);
const click = (id) => q(`#${id}`).click();
const key = (k, extra = {}) => document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...extra }));
const PHOTOS = [
  { name: 'a.jpg', path: '/mnt/user/Photos/a.jpg', is_dir: false, size: 1000 },
  { name: 'b.jpg', path: '/mnt/user/Photos/b.jpg', is_dir: false, size: 1000 },
];

describe('preview toolbar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('notes.txt')) return { status: 'ok', type: 'text', name: 'notes.txt', content: 'hello', size: 5, ext: '.txt' };
      const name = decodeURIComponent(url).split('/').pop();
      return { status: 'ok', type: 'image', name, size: 1000, ext: '.jpg', dimensions: '10 × 10', exif: { camera: 'X' } };
    });
  });
  afterEach(() => closeFilePreviewModal());

  it('zooms, rotates, flips and goes back to fit', async () => {
    await openFilePreviewModal(PHOTOS[0].path, PHOTOS[0].name, null, PHOTOS);
    const img = await vi.waitFor(() => {
      const el = q('#quicklook-img');
      if (!el) throw new Error('no image yet');
      return el;
    });
    click('ql-zoom-in');
    expect(q('#quicklook-zoom-pill').textContent).toBe('125%');
    click('ql-zoom-out');
    expect(q('#quicklook-zoom-pill').textContent).toBe('Fit');
    click('ql-rotate-cw');
    expect(img.style.transform).toContain('rotate(90deg)');
    click('ql-rotate-ccw');
    expect(img.style.transform).toContain('rotate(0deg)');
    click('ql-flip-h');
    expect(img.style.transform).toContain('scaleX(-1)');
    click('quicklook-zoom-pill'); // fit -> actual size
    click('ql-actual-size');
    click('quicklook-zoom-pill'); // back to fit
    expect(q('#quicklook-zoom-pill').textContent).toBe('Fit');
  });

  it('fullscreen, details and filmstrip toggle', async () => {
    await openFilePreviewModal(PHOTOS[0].path, PHOTOS[0].name, null, PHOTOS);
    click('ql-maximize-btn');
    expect(q('#quicklook-modal-dialog').classList.contains('maximized')).toBe(true);
    click('ql-maximize-btn');
    expect(q('#quicklook-modal-dialog').classList.contains('maximized')).toBe(false);
    click('ql-info-toggle');
    expect(q('#quicklook-inspector').classList.contains('open')).toBe(true);
    click('ql-inspector-close');
    expect(q('#quicklook-inspector').classList.contains('open')).toBe(false);
    const strip = q('#quicklook-filmstrip');
    click('ql-filmstrip-toggle');
    if (strip) expect(strip.classList.contains('collapsed')).toBe(true);
  });

  it('downloads the file and copies text', async () => {
    await openFilePreviewModal(PHOTOS[0].path, PHOTOS[0].name, null, PHOTOS);
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    click('ql-download-btn');
    expect(clicked).toHaveBeenCalled();
    clicked.mockRestore();
    closeFilePreviewModal();

    await openFilePreviewModal('/mnt/user/notes.txt', 'notes.txt');
    await vi.waitFor(() => expect(q('#quicklook-meta').textContent).not.toBe('Loading preview…'));
    click('quicklook-copy-btn');
    await vi.waitFor(() => expect(copyText).toHaveBeenCalledWith('hello'));
    expect(showToast.mock.calls.at(-1)[1]).toBe('success');
    copyText.mockRejectedValueOnce(new Error('denied'));
    click('quicklook-copy-btn');
    await vi.waitFor(() => expect(showToast.mock.calls.at(-1)[1]).toBe('error'));
  });

  it('closes with the button, the backdrop and Escape, also from a text field', async () => {
    await openFilePreviewModal(PHOTOS[0].path, PHOTOS[0].name);
    click('quicklook-close-btn');
    expect(q('#quicklook-modal-overlay')).toBeNull();

    await openFilePreviewModal(PHOTOS[0].path, PHOTOS[0].name);
    q('#quicklook-modal-overlay').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(q('#quicklook-modal-overlay')).toBeNull();

    await openFilePreviewModal(PHOTOS[0].path, PHOTOS[0].name);
    key('Escape');
    expect(q('#quicklook-modal-overlay')).toBeNull();

    await openFilePreviewModal(PHOTOS[0].path, PHOTOS[0].name);
    const field = document.createElement('input');
    document.body.append(field);
    field.focus();
    key('x'); // typing is left alone
    expect(q('#quicklook-modal-overlay')).not.toBeNull();
    key('Escape');
    expect(q('#quicklook-modal-overlay')).toBeNull();
  });
});
