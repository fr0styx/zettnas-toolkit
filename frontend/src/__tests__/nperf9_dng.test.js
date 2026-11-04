// NPERF-9: a DNG (RAW) is a picture in the explorer and the viewer, shown from the server's preview.
import { describe, it, expect } from 'vitest';
import { isImageName, isPreviewableName, originalImageUrl, thumbKind } from '../components/viewer-kit.js';

describe('DNG files (NPERF-9)', () => {
  it('gets a thumbnail and opens as a picture', () => {
    expect(thumbKind('IMG_7150.DNG')).toBe('image');
    expect(isImageName('IMG_7150.dng')).toBe(true);
    expect(isPreviewableName('IMG_7150.DNG')).toBe(true);
  });

  it('shows the server-made picture instead of the RAW file', () => {
    expect(originalImageUrl('/mnt/user/a.DNG')).toBe('/api/fs/preview/image?path=%2Fmnt%2Fuser%2Fa.DNG');
    expect(originalImageUrl('/mnt/user/a.jpg')).toBe('/api/fs/download?path=%2Fmnt%2Fuser%2Fa.jpg');
  });
});
