/** NUX-20: the wallpaper gallery's counts and titles come from the locale strings. */
import { describe, it, expect, beforeEach } from 'vitest';
import { renderWallpaperGallery, filterGalleryByCategory } from '../components/wallpapers.js';

describe('wallpaper gallery text (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<span id="wallpaper-count-badge"></span><div id="wallpaper-gallery-grid"></div>';
  });

  it('counts backgrounds with a plural and titles each card', () => {
    renderWallpaperGallery(['fjord-sunset.jpg', 'neon-city.png'], 'neon-city.png', 3);
    expect(document.getElementById('wallpaper-count-badge').textContent).toBe('3 backgrounds');
    const cards = document.querySelectorAll('.wallpaper-card');
    expect(cards[0].getAttribute('title')).toBe('Use the theme gradient');
    expect(cards[1].getAttribute('title')).toBe('Use fjord-sunset.jpg as the wallpaper');
    filterGalleryByCategory('scenic');
    expect(document.getElementById('wallpaper-count-badge').textContent).toBe('1 background');
  });
});
