import { describe, it, expect, vi } from 'vitest';
import {
  ICONS, renderMarkdown, srtToVtt, getResume, setResume, loadFolderGallery, displayImageUrl, attachGestures,
} from '../components/viewer-kit.js';

function memStore() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v) };
}

describe('viewer kit', () => {
  it('uses SVG icons, never bare Unicode glyphs', () => {
    for (const html of Object.values(ICONS)) expect(html.startsWith('<svg')).toBe(true);
  });

  it('renders Markdown safely', () => {
    const html = renderMarkdown('# Title\n\nSome **bold** and `code`.\n\n- a\n- b\n\n[x](javascript:alert(1)) [ok](https://example.com)\n\n<script>alert(1)</script>');
    expect(html).toContain('<h1>Title</h1>');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<ul>\n<li>a</li>');
    expect(html).toContain('<a href="https://example.com"');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('href="javascript');
  });

  it('converts SRT to VTT', () => {
    expect(srtToVtt('1\n00:00:01,500 --> 00:00:03,000\nHello')).toBe('WEBVTT\n\n1\n00:00:01.500 --> 00:00:03.000\nHello\n');
  });

  it('remembers where a video stopped, but not the start or the end', () => {
    const s = memStore();
    setResume('/v.mp4', 125, 600, s);
    expect(getResume('/v.mp4', 600, s)).toBe(125);
    setResume('/v.mp4', 595, 600, s);
    expect(getResume('/v.mp4', 600, s)).toBe(0);
    setResume('/w.mp4', 5, 600, s);
    expect(getResume('/w.mp4', 600, s)).toBe(0);
  });

  it('builds next/previous from the folder, in natural order', async () => {
    const apiGet = vi.fn(async () => ({ dirs: [
      { name: 'IMG_10.jpg', path: '/p/IMG_10.jpg' }, { name: 'IMG_2.jpg', path: '/p/IMG_2.jpg' },
      { name: 'notes.txt', path: '/p/notes.txt' }, { name: 'clip.mp4', path: '/p/clip.mp4' }, { name: 'sub', path: '/p/sub', is_dir: true },
    ] }));
    const g = await loadFolderGallery('/p/IMG_2.jpg', apiGet, { imagesOnly: true });
    expect(apiGet).toHaveBeenCalledWith('/api/browse?path=%2Fp&dirs_only=0');
    expect(g.map((x) => x.name)).toEqual(['IMG_2.jpg', 'IMG_10.jpg']);
  });

  it('shows big photos as screen-sized WebP but keeps GIFs as they are', () => {
    expect(displayImageUrl('/p/a.jpg', 2000)).toBe('/api/fs/preview/image?path=%2Fp%2Fa.jpg&max_dim=2000');
    expect(displayImageUrl('/p/a.gif', 2000)).toBe('/api/fs/download?path=%2Fp%2Fa.gif');
  });

  it('turns a horizontal swipe into next/previous only when not zoomed', () => {
    const el = document.createElement('div');
    const swipes = [];
    let zoom = 1;
    attachGestures(el, { get: () => ({ zoom }), onSwipe: (d) => swipes.push(d), onPinch: () => {} });
    const ev = (type, x, y) => {
      const e = new Event(type);
      Object.assign(e, { pointerId: 1, pointerType: 'touch', clientX: x, clientY: y });
      el.dispatchEvent(e);
    };
    ev('pointerdown', 300, 200);
    ev('pointerup', 150, 210);
    expect(swipes).toEqual([1]);
    zoom = 2;
    ev('pointerdown', 300, 200);
    ev('pointerup', 150, 210);
    expect(swipes).toEqual([1]);
  });
});
