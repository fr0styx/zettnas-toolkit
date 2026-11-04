// NPERF-8: versioned thumbnail addresses and the folder prefetch request.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { thumbUrl } from '../components/viewer-kit.js';
import { prefetchThumbs } from '../components/file-manager.js';
import { api } from '../api.js';

describe('thumbnails ahead of time (NPERF-8)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('names the file version in the thumbnail address when it is known', () => {
    expect(thumbUrl('/mnt/user/a b.jpg')).toBe('/api/fs/preview/image?path=%2Fmnt%2Fuser%2Fa%20b.jpg&thumb=1');
    expect(thumbUrl('/mnt/user/a.jpg', 1793000000.5)).toBe('/api/fs/preview/image?path=%2Fmnt%2Fuser%2Fa.jpg&thumb=1&v=1793000000.5');
    expect(thumbUrl('/mnt/user/a.gif', 5)).toBe('/api/fs/download?path=%2Fmnt%2Fuser%2Fa.gif');
  });

  it('asks for a folder only when it holds photos or videos', () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', queued: 2 });
    expect(prefetchThumbs({ current: '/mnt/user/docs', dirs: [{ name: 'a.pdf', is_dir: false }, { name: 'x.mov', is_dir: true }] })).toBe(false);
    expect(post).not.toHaveBeenCalled();
    expect(prefetchThumbs({ current: '/mnt/user/clips', dirs: [{ name: 'IMG_1.MOV', is_dir: false }] })).toBe(true);
    expect(post).toHaveBeenCalledWith('/api/fs/thumbs/prefetch', { path: '/mnt/user/clips' });
    expect(prefetchThumbs(null)).toBe(false);
  });

  it('ignores a failed prefetch request', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(new Error('offline'));
    expect(prefetchThumbs({ current: '/p', dirs: [{ name: 'a.jpg', is_dir: false }] })).toBe(true);
    await new Promise((r) => setTimeout(r, 0));
  });
});
