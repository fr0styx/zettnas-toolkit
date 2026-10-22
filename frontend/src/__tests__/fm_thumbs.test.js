import { describe, it, expect } from 'vitest';
import { thumbKind, thumbUrl, previewUrl } from '../components/viewer-kit.js';

describe('explorer thumbnails', () => {
  it('asks the server for photos, iPhone HEIC and videos', () => {
    expect(thumbKind('IMG_7149.HEIC')).toBe('image');
    expect(thumbKind('lp_image_2.heic')).toBe('image');
    expect(thumbKind('IMG_7307.PNG')).toBe('image');
    expect(thumbKind('RenderedImage.MOV')).toBe('video');
    expect(thumbKind('28108C20.mp4')).toBe('video');
    expect(thumbKind('logo.svg')).toBe('vector');
    expect(thumbKind('notes.txt')).toBe(null);
  });

  it('uses small server thumbnails, never the whole file', () => {
    expect(thumbUrl('/mnt/user/a b/IMG_1.HEIC')).toBe('/api/fs/preview/image?path=%2Fmnt%2Fuser%2Fa%20b%2FIMG_1.HEIC&thumb=1');
    expect(thumbUrl('/mnt/user/clip.MOV')).toContain('&thumb=1');
    expect(previewUrl('/mnt/user/clip.MOV', 480)).toBe('/api/fs/preview/image?path=%2Fmnt%2Fuser%2Fclip.MOV&max_dim=480');
  });
});
