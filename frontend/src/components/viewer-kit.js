/**
 * Helpers for the photo, video and document viewer (file-preview-modal.js).
 *
 * Icons are inline SVG, so they render the same everywhere (the old Unicode symbols
 * showed as empty boxes on systems without those glyphs).
 */

const svg = (body, size = 16) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

export const ICONS = {
  zoomOut: svg('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M8 11h6"/>'),
  zoomIn: svg('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M8 11h6M11 8v6"/>'),
  rotateLeft: svg('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>'),
  rotateRight: svg('<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>'),
  flip: svg('<path d="M12 3v18"/><path d="M8 7L3 12l5 5V7zM16 7l5 5-5 5V7z"/>'),
  info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>'),
  filmstrip: svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4"/>'),
  copy: svg('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>'),
  download: svg('<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 21h16"/>'),
  maximize: svg('<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M16 21h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>'),
  restore: svg('<path d="M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3"/>'),
  close: svg('<path d="M18 6L6 18M6 6l12 12"/>', 18),
  prev: svg('<path d="M15 18l-6-6 6-6"/>', 28),
  next: svg('<path d="M9 18l6-6-6-6"/>', 28),
  eye: svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
};

const IMAGE_RE = /\.(jpe?g|png|webp|gif|svg|bmp|ico|tiff?|heic|heif|avif)$/i;
const MEDIA_RE = /\.(mp4|mkv|webm|mov|avi|m4v|mp3|wav|ogg|flac|aac|m4a|opus)$/i;

export const isImageName = (n) => IMAGE_RE.test(n || '');
export const isPreviewableName = (n) => IMAGE_RE.test(n || '') || MEDIA_RE.test(n || '');

/** URL used to show an image: a screen-sized WebP, except formats that must stay as they are. */
export function displayImageUrl(path, maxDim) {
  const enc = encodeURIComponent(path);
  if (/\.(gif|svg|ico)$/i.test(path)) return `/api/fs/download?path=${enc}`;
  return `/api/fs/preview/image?path=${enc}&max_dim=${Math.max(320, Math.min(4096, Math.round(maxDim)))}`;
}

export const originalImageUrl = (path) =>
  /\.(heic|heif)$/i.test(path) ? `/api/fs/preview/image?path=${encodeURIComponent(path)}` : `/api/fs/download?path=${encodeURIComponent(path)}`;

/** Which files get a server thumbnail: 'image' (photos, HEIC), 'video' (a frame), 'vector' (shown as is), or null. */
export function thumbKind(name) {
  if (/\.(jpe?g|png|webp|bmp|tiff?|avif|heic|heif)$/i.test(name || '')) return 'image';
  if (/\.(mp4|m4v|mov|mkv|webm|avi|3gp|mts|m2ts|wmv|mpe?g)$/i.test(name || '')) return 'video';
  if (/\.(gif|svg|ico)$/i.test(name || '')) return 'vector';
  return null;
}

/** Screen-sized preview (photo or video frame) for panels larger than a thumbnail. */
export const previewUrl = (path, maxDim = 480) => `/api/fs/preview/image?path=${encodeURIComponent(path)}&max_dim=${maxDim}`;

export const thumbUrl = (path) =>
  /\.(gif|svg|ico)$/i.test(path) ? `/api/fs/download?path=${encodeURIComponent(path)}` : `/api/fs/preview/image?path=${encodeURIComponent(path)}&thumb=1`;

/** Longest side to request for the current screen (device pixels, capped). */
export function screenMaxDim(win = window) {
  const dpr = Math.min(2, win.devicePixelRatio || 1);
  return Math.min(3072, Math.max(win.innerWidth || 1280, win.innerHeight || 800) * dpr);
}

/** Previewable siblings of a file, from the folder listing, in name order (for next/previous). */
export async function loadFolderGallery(path, apiGet, { imagesOnly = false } = {}) {
  const dir = path.slice(0, path.lastIndexOf('/')) || '/';
  const res = await apiGet(`/api/browse?path=${encodeURIComponent(dir)}&dirs_only=0`);
  const entries = (res && (res.dirs || res.items)) || [];
  return entries
    .filter((f) => f && !f.is_dir && (imagesOnly ? isImageName(f.name) : isPreviewableName(f.name)))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }))
    .map((f) => ({ path: f.path, name: f.name }));
}

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

function inline(s) {
  let out = esc(s);
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return out;
}

/** Small, safe Markdown renderer: everything is escaped first, only http(s) links. */
export function renderMarkdown(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  const html = [];
  let list = null;
  let para = [];
  let code = null;
  const flushPara = () => {
    if (para.length) html.push(`<p>${inline(para.join(' '))}</p>`);
    para = [];
  };
  const flushList = () => {
    if (list) html.push(`</${list}>`);
    list = null;
  };
  for (const line of lines) {
    if (code !== null) {
      if (/^```/.test(line)) {
        html.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
        code = null;
      } else code.push(line);
      continue;
    }
    if (/^```/.test(line)) {
      flushPara();
      flushList();
      code = [];
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (h) {
      flushPara();
      flushList();
      html.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);
    } else if (ul || ol) {
      flushPara();
      const kind = ul ? 'ul' : 'ol';
      if (list !== kind) {
        flushList();
        html.push(`<${kind}>`);
        list = kind;
      }
      html.push(`<li>${inline((ul || ol)[1])}</li>`);
    } else if (/^\s*>\s?/.test(line)) {
      flushPara();
      flushList();
      html.push(`<blockquote>${inline(line.replace(/^\s*>\s?/, ''))}</blockquote>`);
    } else if (/^\s*(---|\*\*\*)\s*$/.test(line)) {
      flushPara();
      flushList();
      html.push('<hr>');
    } else if (!line.trim()) {
      flushPara();
      flushList();
    } else {
      flushList();
      para.push(line.trim());
    }
  }
  if (code !== null) html.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
  flushPara();
  flushList();
  return html.join('\n');
}

/** SubRip (.srt) to WebVTT, so the browser can show it as a subtitle track. */
export function srtToVtt(srt) {
  const body = String(srt || '')
    .replace(/\r\n?/g, '\n')
    .replace(/^\uFEFF/, '')
    .replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, '$1.$2');
  return `WEBVTT\n\n${body.trim()}\n`;
}

const RESUME_KEY = 'zettnas_video_resume';

/** Where to continue a video, or 0 (only between 15 s in and 15 s before the end). */
export function getResume(path, duration, storage = globalThis.localStorage) {
  try {
    const all = JSON.parse(storage.getItem(RESUME_KEY) || '{}');
    const at = Number(all[path] && all[path].t) || 0;
    return at > 15 && (!duration || at < duration - 15) ? at : 0;
  } catch (e) {
    return 0;
  }
}

export function setResume(path, t, duration, storage = globalThis.localStorage) {
  try {
    const all = JSON.parse(storage.getItem(RESUME_KEY) || '{}');
    if (!t || (duration && t > duration - 15)) delete all[path];
    else all[path] = { t: Math.round(t), at: Date.now() };
    const keys = Object.keys(all);
    if (keys.length > 200) {
      keys.sort((a, b) => all[a].at - all[b].at).slice(0, keys.length - 200).forEach((k) => delete all[k]);
    }
    storage.setItem(RESUME_KEY, JSON.stringify(all));
  } catch (e) {
    // private mode or storage full: resume is a convenience
  }
}

/**
 * Touch gestures on the image viewport: swipe left/right (when not zoomed), pinch to
 * zoom. Returns a cleanup function. `get()` gives {zoom}; `onPinch(scale, cx, cy)`,
 * `onSwipe(dir)`.
 */
export function attachGestures(el, { get, onSwipe, onPinch }) {
  const pts = new Map();
  let start = null;
  let pinchStart = null;
  const down = (e) => {
    if (e.pointerType === 'mouse') return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) start = { x: e.clientX, y: e.clientY, t: Date.now() };
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      pinchStart = { d: Math.hypot(a.x - b.x, a.y - b.y), zoom: get().zoom };
      start = null;
    }
  };
  const move = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2 && pinchStart && pinchStart.d > 0) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      onPinch(Math.max(0.5, Math.min(10, (pinchStart.zoom * d) / pinchStart.d)), (a.x + b.x) / 2, (a.y + b.y) / 2);
    }
  };
  const up = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    if (pts.size < 2) pinchStart = null;
    if (start && pts.size === 0) {
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      if (get().zoom <= 1.05 && Math.abs(dx) > 60 && Math.abs(dy) < 50 && Date.now() - start.t < 600) {
        onSwipe(dx < 0 ? 1 : -1);
      }
      start = null;
    }
  };
  el.addEventListener('pointerdown', down);
  el.addEventListener('pointermove', move);
  el.addEventListener('pointerup', up);
  el.addEventListener('pointercancel', up);
  return () => {
    el.removeEventListener('pointerdown', down);
    el.removeEventListener('pointermove', move);
    el.removeEventListener('pointerup', up);
    el.removeEventListener('pointercancel', up);
  };
}
