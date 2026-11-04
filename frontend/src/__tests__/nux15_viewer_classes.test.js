/** NUX-15: the viewer's markup carries classes instead of inline styles (74-viewer-markup.css). */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const { openFilePreviewModal, closeFilePreviewModal } = await import('../components/file-preview-modal.js');

const q = (s) => document.querySelector(s);

describe('viewer markup classes (NUX-15)', () => {
  afterEach(() => {
    closeFilePreviewModal();
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('the asleep-disk preview shows its thumbnail, excerpt and path with classes', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    await openFilePreviewModal('/mnt/user/photos/IMG_1.jpg', 'IMG_1.jpg', {
      standbySafe: true,
      thumbnailUrl: '/api/fs/thumb?path=x',
      excerpt: 'a beach at sunset',
    });
    await vi.waitFor(() => expect(q('#btn-quicklook-wake-load')).toBeTruthy());
    expect(q('#quicklook-body .qlv-col')).toBeTruthy();
    expect(q('#quicklook-body img.quicklook-img.qlv-box').getAttribute('src')).toBe('/api/fs/thumb?path=x');
    expect(q('#quicklook-body pre.quicklook-code.qlv-size').textContent).toBe('a beach at sunset');
    expect(q('#quicklook-body .qlv-xs-muted-mono').textContent).toBe('/mnt/user/photos/IMG_1.jpg');
    expect(q('#quicklook-body .qlv-col [style*="font-family"]')).toBeNull();
  });

  it('an error shows its message with classes', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('Permission denied'));
    await openFilePreviewModal('/mnt/user/docs/secret.txt', 'secret.txt');
    await vi.waitFor(() => expect(q('#quicklook-body .qlv-xs-semi')).toBeTruthy());
    expect(q('#quicklook-body .qlv-xs-semi').textContent).toBe('Permission denied');
    expect(q('#quicklook-body .qlv-fs32').textContent).toBe('⚠️');
  });

  it('an error without a message still says the preview failed', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error(''));
    await openFilePreviewModal('/mnt/user/docs/odd.bin', 'odd.bin');
    await vi.waitFor(() => expect(q('#quicklook-body .qlv-xs-semi')).toBeTruthy());
    expect(q('#quicklook-body .qlv-xs-semi').textContent).toBe('Unable to preview file');
  });
});
