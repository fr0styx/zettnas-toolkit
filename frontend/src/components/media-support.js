// What a video file contains (from /api/fs/media/info) and whether this browser can play it.
// Files it can't play are streamed converted to H.264/AAC (/api/fs/stream/compat).
import { t } from '../i18n.js';

const VIDEO_TYPES = {
  h264: ['video/mp4; codecs="avc1.640028"'],
  hevc: ['video/mp4; codecs="hvc1.1.6.L120.90"', 'video/mp4; codecs="hev1.1.6.L120.90"'],
  vp9: ['video/webm; codecs="vp09.00.10.08"', 'video/webm; codecs="vp9"'],
  vp8: ['video/webm; codecs="vp8"'],
  av1: ['video/mp4; codecs="av01.0.08M.08"', 'video/webm; codecs="av01.0.08M.08"'],
  mpeg4: ['video/mp4; codecs="mp4v.20.8"'],
};
const BROWSER_AUDIO = new Set(['aac', 'mp3', 'opus', 'vorbis', 'flac']);
const CODEC_NAMES = {
  h264: 'H.264', hevc: 'HEVC (H.265)', vp9: 'VP9', vp8: 'VP8', av1: 'AV1', mpeg4: 'MPEG-4', prores: 'ProRes',
  mpeg2video: 'MPEG-2', aac: 'AAC', mp3: 'MP3', opus: 'Opus', vorbis: 'Vorbis', flac: 'FLAC', ac3: 'Dolby Digital (AC-3)',
  eac3: 'Dolby Digital Plus', dts: 'DTS', truehd: 'Dolby TrueHD', alac: 'Apple Lossless', pcm_s16le: 'PCM',
};

export const mediaInfoUrl = (path) => `/api/fs/media/info?path=${encodeURIComponent(path)}`;
export const compatStreamUrl = (path, start = 0) =>
  `/api/fs/stream/compat?path=${encodeURIComponent(path)}&start=${Math.max(0, start).toFixed(2)}`;

/** True when this browser can play the file as it is; false means use the converted stream. */
export function canPlayHere(info, name = '', probe = typeof document !== 'undefined' ? document.createElement('video') : null) {
  if (!info || !info.video || !probe || typeof probe.canPlayType !== 'function') return true;
  const container = String(info.container || '');
  const ext = (String(name).split('.').pop() || '').toLowerCase();
  const isMp4 = container.includes('mp4') || container.includes('mov');
  const isWebm = container.includes('webm') && ext === 'webm';
  if (!isMp4 && !isWebm && !probe.canPlayType('video/x-matroska')) return false;
  const v = info.video;
  if (v.codec === 'h264' && v.bit_depth > 8) return false; // 10-bit H.264 doesn't play in browsers
  const types = VIDEO_TYPES[v.codec];
  if (!types || !types.some((ty) => probe.canPlayType(ty) !== '')) return false;
  if (info.audio && !BROWSER_AUDIO.has(info.audio.codec)) return false;
  return true;
}

export function codecName(codec) {
  return CODEC_NAMES[codec] || String(codec || '?').toUpperCase();
}

export function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '—';
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

/** [label, value] rows for the explorer's details panel. */
export function describeMedia(info, playsHere) {
  if (!info) return [];
  const rows = [];
  if (info.duration) rows.push([t('media.duration', 'Duration'), formatDuration(info.duration)]);
  const v = info.video;
  if (v) {
    rows.push([t('media.resolution', 'Resolution'), `${v.width} × ${v.height}${v.fps ? ` · ${Math.round(v.fps * 100) / 100} fps` : ''}`]);
    const extras = [v.profile, v.bit_depth > 8 ? `${v.bit_depth}-bit` : '', v.hdr ? 'HDR' : ''].filter(Boolean).join(', ');
    rows.push([t('media.video', 'Video'), `${codecName(v.codec)}${extras ? ` (${extras})` : ''}`]);
  }
  if (info.audio) {
    const ch = info.audio.channels === 1 ? 'mono' : info.audio.channels === 2 ? 'stereo' : info.audio.channels ? `${info.audio.channels} ch` : '';
    const rate = info.audio.sample_rate ? `${Math.round(info.audio.sample_rate / 100) / 10} kHz` : '';
    rows.push([t('media.audio', 'Audio'), [codecName(info.audio.codec), ch, rate].filter(Boolean).join(' · ')]);
  }
  if (v) {
    rows.push([t('media.plays_here', 'In this browser'), playsHere ? t('media.plays_direct', 'Plays as is') : t('media.plays_converted', 'Converted while playing')]);
  }
  return rows;
}
