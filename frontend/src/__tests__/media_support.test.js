import { describe, it, expect } from 'vitest';
import { canPlayHere, compatStreamUrl, describeMedia } from '../components/media-support.js';

const browser = (types) => ({ canPlayType: (ty) => (types.some((x) => ty.includes(x)) ? 'probably' : '') });
const iphone = { container: 'mov,mp4,m4a,3gp,3g2,mj2', duration: 31.5, video: { codec: 'hevc', profile: 'Main', width: 1080, height: 1920, fps: 30, bit_depth: 8, hdr: false }, audio: { codec: 'aac', channels: 1, sample_rate: 48000 } };

describe('which videos this browser plays as they are', () => {
  it('iPhone HEVC: direct where HEVC plays, converted elsewhere', () => {
    expect(canPlayHere(iphone, 'IMG_1.MOV', browser(['avc1', 'hvc1']))).toBe(true);
    expect(canPlayHere(iphone, 'IMG_1.MOV', browser(['avc1']))).toBe(false);
  });
  it('MKV, 10-bit H.264 and AC-3 audio are converted', () => {
    const h264 = { ...iphone, video: { ...iphone.video, codec: 'h264' } };
    expect(canPlayHere(h264, 'a.mp4', browser(['avc1']))).toBe(true);
    expect(canPlayHere({ ...h264, container: 'matroska,webm' }, 'a.mkv', browser(['avc1']))).toBe(false);
    expect(canPlayHere({ ...h264, video: { ...h264.video, bit_depth: 10 } }, 'a.mp4', browser(['avc1']))).toBe(false);
    expect(canPlayHere({ ...h264, audio: { codec: 'ac3', channels: 6 } }, 'a.mp4', browser(['avc1']))).toBe(false);
  });
  it('details rows and the converted stream URL', () => {
    const rows = Object.fromEntries(describeMedia(iphone, false));
    expect(rows.Duration).toBe('0:32');
    expect(rows.Resolution).toBe('1080 × 1920 · 30 fps');
    expect(rows.Video).toBe('HEVC (H.265) (Main)');
    expect(rows.Audio).toBe('AAC · mono · 48 kHz');
    expect(rows['In this browser']).toBe('Converted while playing');
    expect(compatStreamUrl('/mnt/user/a b.mov', 12.345)).toBe('/api/fs/stream/compat?path=%2Fmnt%2Fuser%2Fa%20b.mov&start=12.35');
  });
});
