// NVID-1: how the viewer plays a video this browser can't play as it is.
import { describe, it, expect } from 'vitest';
import { compatMode, compatStreamUrl, convertedPlan, convertedUrl } from '../components/media-support.js';

const probe = (playable) => ({ canPlayType: (ty) => (playable.some((p) => ty.includes(p)) ? 'probably' : '') });
const hevcPcm = { duration: 2, video: { codec: 'hevc', bit_depth: 8 }, audio: { codec: 'pcm_s16le' } };

describe('converted videos (NVID-1)', () => {
  it('keeps the video when only the audio is the problem', () => {
    expect(compatMode(hevcPcm, probe(['hvc1']))).toBe('copy');
    expect(compatMode(hevcPcm, probe(['avc1']))).toBe('full');
    expect(compatMode({ video: { codec: 'h264', bit_depth: 10 } }, probe(['avc1']))).toBe('full');
    expect(compatMode({}, probe(['avc1']))).toBe('full');
  });

  it('plays a short or kept clip as a plain file and streams a long one while it is kept', () => {
    expect(convertedPlan(hevcPcm, '/v/a.MOV', probe(['hvc1']))).toEqual({ src: convertedUrl('/v/a.MOV', 'copy'), live: false, mode: 'copy' });
    const long = { ...hevcPcm, duration: 900 };
    expect(convertedPlan(long, '/v/a.MOV', probe(['hvc1']))).toEqual({
      src: compatStreamUrl('/v/a.MOV', 0, 'copy'), live: true, mode: 'copy', prepare: convertedUrl('/v/a.MOV', 'copy'),
    });
    expect(convertedPlan({ ...long, converted: { copy: true } }, '/v/a.MOV', probe(['hvc1'])).live).toBe(false);
    expect(compatStreamUrl('/v/a b.MOV', 3)).toBe('/api/fs/stream/compat?path=%2Fv%2Fa%20b.MOV&start=3.00&mode=full');
  });
});
