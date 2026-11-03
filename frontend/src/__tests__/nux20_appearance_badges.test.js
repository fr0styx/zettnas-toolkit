/** NUX-20: the contrast badge, extracted colour chips and palette sampling read as translatable words. */
import { describe, it, expect, beforeEach } from 'vitest';
import { syncDesktopThemeUI, renderExtractedChips, sampleWallpaperPalette } from '../components/settings.js';
import { state } from '../state.js';

const byId = (id) => document.getElementById(id);

describe('appearance badges (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<span id="desktop-theme-active-badge"></span><span id="desktop-custom-hex-val"></span><span id="desktop-contrast-badge"></span><div id="wallpaper-extracted-chips"></div><div id="desktop-wallpaper"></div>';
    state.desktopTheme = 'cyber';
  });

  it('grades the accent colour against the dark surface', () => {
    state.desktopCustomAccent = '#ffffff';
    syncDesktopThemeUI();
    expect(byId('desktop-contrast-badge').textContent).toBe('AAA PASS');
    state.desktopCustomAccent = '#1e293b';
    syncDesktopThemeUI();
    expect(byId('desktop-contrast-badge').textContent).toMatch(/^LOW \(\d+\.\d:1\)$/);
    state.desktopCustomAccent = '';
  });

  it('names extracted colours and says when it samples the wallpaper', () => {
    renderExtractedChips(['#00f0ff']);
    expect(document.querySelector('.desktop-color-chip').title).toBe('Extracted: #00F0FF');
    byId('desktop-wallpaper').style.backgroundImage = 'url("/wp/a.jpg")';
    sampleWallpaperPalette();
    expect(byId('wallpaper-extracted-chips').textContent.trim()).toBe('Sampling wallpaper pixels...');
  });
});
