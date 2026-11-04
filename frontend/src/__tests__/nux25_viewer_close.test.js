// NUX-25: a second open while a big folder loads leaves one viewer, and closing never leaves one behind.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { openFilePreviewModal, closeFilePreviewModal } from '../components/file-preview-modal.js';
import { api } from '../api.js';

describe('the viewer opens once and always closes (NUX-25)', () => {
  afterEach(() => {
    closeFilePreviewModal();
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('keeps only the newer viewer when two opens overlap', async () => {
    let release;
    const slow = new Promise((r) => { release = r; });
    vi.spyOn(api, 'get').mockImplementation(() => slow);
    const first = openFilePreviewModal('/mnt/user/p/a.jpg', 'a.jpg');
    const second = openFilePreviewModal('/mnt/user/p/b.jpg', 'b.jpg');
    release({ current: '/mnt/user/p', dirs: [{ name: 'a.jpg', path: '/mnt/user/p/a.jpg' }, { name: 'b.jpg', path: '/mnt/user/p/b.jpg' }] });
    await Promise.all([first, second]);
    const overlays = document.querySelectorAll('.quicklook-modal-overlay');
    expect(overlays.length).toBe(1);
    expect(overlays[0].querySelector('#quicklook-title-text').textContent).toBe('b.jpg');
    overlays[0].querySelector('#quicklook-close-btn').click();
    expect(document.querySelectorAll('.quicklook-modal-overlay').length).toBe(0);
  });

  it('closing removes a viewer left from an earlier open', () => {
    const stray = document.createElement('div');
    stray.className = 'quicklook-modal-overlay';
    document.body.appendChild(stray);
    closeFilePreviewModal();
    expect(document.querySelectorAll('.quicklook-modal-overlay').length).toBe(0);
  });
});
