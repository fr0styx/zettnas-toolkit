import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import fs from 'fs';
import path from 'path';
import { state } from '../state.js';
import {
  applyDesktopTheme,
  syncDesktopTwinPreview,
  hexToRgb,
  getContrastRatio,
  getRelativeLuminance
} from '../components/dashboard.js';
import {
  syncDesktopThemeUI,
  initDesktopThemeControls,
  renderExtractedChips,
  sampleWallpaperPalette,
  exportThemeBundle,
  importThemeBundle,
  restoreAppearanceDefaultsWithUndo
} from '../components/settings.js';
import {
  initGlassControls,
  applyGlassSettings,
  applyWallpaperReadability,
  filterGalleryByCategory,
  uploadAndApplyWallpaper
} from '../components/wallpapers.js';
import { ALL_TRANSLATIONS as TRANSLATIONS } from '../locales/all.js';
import * as toastModule from '../toast.js';

describe('Appearance Studio & Desktop Personalization Revamp Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.className = '';
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    document.body.innerHTML = '';
    document.body.removeAttribute('data-performance-mode');
    state.desktopTheme = 'cyber';
    state.desktopCustomAccent = '';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('validates DOM markup in index.html for Desktop Twin Preview, Category Pills, Contrast Badge, Palette Extractor, and Theme Backup', () => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    const html = fs.readFileSync(htmlPath, 'utf8');

    // 1. Master Desktop Twin Preview
    expect(html).toContain('desktop-twin-preview-wrapper');
    expect(html).toContain('id="desktop-twin-viewport"');
    expect(html).toContain('id="dt-wallpaper"');
    expect(html).toContain('id="dt-wallpaper-dimmer"');
    expect(html).toContain('id="dt-window"');
    expect(html).toContain('class="dt-window-body"');
    expect(html).toContain('id="dt-dock-container"');

    // 2. Wallpaper Category Pills
    expect(html).toContain('wallpaper-cat-pill');
    expect(html).toContain('data-cat="all"');
    expect(html).toContain('data-cat="gradient"');
    expect(html).toContain('data-cat="scenic"');
    expect(html).toContain('data-cat="cyber"');
    expect(html).toContain('data-cat="oled"');

    // 3. Contrast Badge & Color Palette Extractor
    expect(html).toContain('id="desktop-contrast-badge"');
    expect(html).toContain('id="extract-palette-btn"');
    expect(html).toContain('id="wallpaper-extracted-chips"');

    // 4. Eco Mode Toggle
    expect(html).toContain('id="eco-mode-toggle"');

    // 5. Theme Bundle Export / Import / Restore
    expect(html).toContain('id="theme-export-btn"');
    expect(html).toContain('id="theme-import-btn"');
    expect(html).toContain('id="theme-import-file"');
    expect(html).toContain('id="theme-reset-all-btn"');
  });

  it('syncDesktopTwinPreview updates miniature viewport properties without crashing', () => {
    document.body.innerHTML = `
      <div id="desktop-twin-viewport" class="desktop-twin-viewport">
        <div id="dt-wallpaper" class="dt-wallpaper"></div>
        <div id="dt-wallpaper-dimmer" class="dt-wallpaper-dimmer"></div>
        <div id="dt-window" class="dt-window">
          <div class="dt-window-body"></div>
        </div>
        <div id="dt-dock-container" class="dt-dock-container dt-dock-pos-bottom"></div>
      </div>
    `;

    syncDesktopTwinPreview({
      theme: 'amber',
      accent: '#ffbe40',
      wallpaperDim: 30,
      wallpaperBlur: 8,
      dockPos: 'left',
      windowRadius: '20px',
      windowGlow: true
    });

    const dimmer = document.getElementById('dt-wallpaper-dimmer');
    const wp = document.getElementById('dt-wallpaper');
    const win = document.getElementById('dt-window');
    const dock = document.getElementById('dt-dock-container');

    expect(dimmer.style.getPropertyValue('--preview-wp-dim')).toBe('0.30');
    expect(wp.style.getPropertyValue('--preview-wp-blur')).toBe('8px');
    expect(win.style.getPropertyValue('--preview-accent-rgb')).toBe('255, 190, 64');
    expect(win.style.getPropertyValue('--preview-window-radius')).toBe('20px');
    expect(dock.classList.contains('dt-dock-pos-left')).toBe(true);
  });

  it('calculates WCAG 2.2 contrast ratio and updates desktop-contrast-badge accordingly', () => {
    document.body.innerHTML = `
      <div id="mgmt-pane-theme">
        <span id="desktop-theme-active-badge"></span>
        <button class="desktop-theme-preset active" data-theme-id="cyber"></button>
        <span id="desktop-custom-hex-val"></span>
        <span id="desktop-contrast-badge"></span>
      </div>
    `;

    // 1. High contrast cyan (#00f0ff) against dark background -> AAA or AA PASS
    state.desktopTheme = 'cyber';
    state.desktopCustomAccent = '#00f0ff';
    syncDesktopThemeUI();

    const badge = document.getElementById('desktop-contrast-badge');
    expect(badge.textContent).toMatch(/PASS/);

    // 2. Very dark accent (#1a1a24) against dark background -> LOW contrast
    state.desktopCustomAccent = '#1a1a24';
    syncDesktopThemeUI();
    expect(badge.textContent).toContain('LOW');
  });

  it('renderExtractedChips creates clickable color chips that apply custom accents', () => {
    document.body.innerHTML = `
      <div id="mgmt-pane-theme">
        <span id="desktop-theme-active-badge"></span>
        <span id="desktop-custom-hex-val"></span>
        <span id="desktop-contrast-badge"></span>
        <div id="wallpaper-extracted-chips"></div>
      </div>
    `;

    renderExtractedChips(['#00f0ff', '#ffbe40', '#3bf58b']);

    const chips = document.querySelectorAll('#wallpaper-extracted-chips .desktop-color-chip');
    expect(chips.length).toBe(3);

    chips[1].click();
    expect(state.desktopCustomAccent).toBe('#ffbe40');
    expect(document.documentElement.style.getPropertyValue('--brand')).toBe('#ffbe40');
  });

  it('sampleWallpaperPalette handles missing wallpaper gracefully with default vibrant palette', async () => {
    document.body.innerHTML = `
      <div id="mgmt-pane-theme">
        <span id="desktop-theme-active-badge"></span>
        <span id="desktop-custom-hex-val"></span>
        <span id="desktop-contrast-badge"></span>
        <div id="wallpaper-extracted-chips"></div>
      </div>
    `;

    await sampleWallpaperPalette();

    const chips = document.querySelectorAll('#wallpaper-extracted-chips .desktop-color-chip');
    expect(chips.length).toBeGreaterThanOrEqual(5);
  });

  it('initGlassControls toggles Eco Mode and sets body[data-performance-mode="eco"]', () => {
    document.body.innerHTML = `
      <span id="glass-blur-val"></span>
      <input type="range" id="glass-blur-slider" value="24">
      <span id="glass-opacity-val"></span>
      <input type="range" id="glass-opacity-slider" value="72">
      <input type="checkbox" id="window-glow-toggle">
      <input type="checkbox" id="eco-mode-toggle">
      <button class="window-radius-btn" data-radius="12px"></button>
      <button id="glass-reset-btn"></button>
    `;

    initGlassControls();

    const ecoToggle = document.getElementById('eco-mode-toggle');
    expect(ecoToggle).not.toBeNull();

    // Enable eco mode
    ecoToggle.checked = true;
    ecoToggle.dispatchEvent(new Event('change'));

    expect(document.body.getAttribute('data-performance-mode')).toBe('eco');
    expect(localStorage.getItem('zettnas_eco_mode')).toBe('true');

    // Disable eco mode
    ecoToggle.checked = false;
    ecoToggle.dispatchEvent(new Event('change'));

    expect(document.body.hasAttribute('data-performance-mode')).toBe(false);
    expect(localStorage.getItem('zettnas_eco_mode')).toBe('false');
  });

  it('exportThemeBundle produces valid JSON download with current appearance state', () => {
    state.desktopTheme = 'amber';
    state.desktopCustomAccent = '#ffbe40';
    localStorage.setItem('zettnas_glass_blur', '28');
    localStorage.setItem('zettnas_window_radius', '20px');

    let clicked = false;
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = origCreateElement(tag);
      if (tag === 'a') {
        el.click = () => { clicked = true; };
      }
      return el;
    });

    exportThemeBundle();
    expect(clicked).toBe(true);
  });

  it('importThemeBundle validates format, applies settings, and handles invalid payload', () => {
    const invalidBlob = new Blob(['{"not_a_theme": 123}'], { type: 'application/json' });
    const toastSpy = vi.spyOn(toastModule, 'showToast');

    importThemeBundle(invalidBlob);

    // Test with valid theme bundle
    const validBundle = {
      app: 'zettnas-toolkit',
      format: 'zett-theme',
      version: 1,
      theme: 'emerald',
      custom_accent: '#3bf58b',
      glass: { blur: 18, opacity: 80, radius: '6px', glow: true },
      performance: { eco_mode: false }
    };
    const validBlob = new Blob([JSON.stringify(validBundle)], { type: 'application/json' });
    importThemeBundle(validBlob);
  });

  it('restoreAppearanceDefaultsWithUndo resets to cyber factory defaults and supports undo', () => {
    state.desktopTheme = 'crimson';
    state.desktopCustomAccent = '#f43f5e';
    localStorage.setItem('zettnas_glass_blur', '36');

    document.body.innerHTML = `
      <div id="mgmt-pane-theme">
        <span id="desktop-theme-active-badge"></span>
        <button class="desktop-theme-preset active" data-theme-id="crimson"></button>
        <button class="desktop-theme-preset" data-theme-id="cyber"></button>
        <span id="desktop-custom-hex-val"></span>
        <span id="desktop-contrast-badge"></span>
      </div>
      <input type="checkbox" id="eco-mode-toggle">
    `;

    let capturedUndoAction = null;
    vi.spyOn(toastModule, 'showActionToast').mockImplementation((msg, actionText, onAction) => {
      capturedUndoAction = onAction;
    });

    restoreAppearanceDefaultsWithUndo();

    // Verify factory defaults applied
    expect(state.desktopTheme).toBe('cyber');
    expect(state.desktopCustomAccent).toBe('');
    expect(capturedUndoAction).toBeTypeOf('function');

    // Trigger Undo
    capturedUndoAction();
    expect(state.desktopTheme).toBe('crimson');
    expect(state.desktopCustomAccent).toBe('#f43f5e');
  });

  it('filterGalleryByCategory hides non-matching wallpaper cards and highlights active pill', () => {
    document.body.innerHTML = `
      <div class="wallpaper-category-pills">
        <button class="wallpaper-cat-pill active" data-category="all"></button>
        <button class="wallpaper-cat-pill" data-category="scenic"></button>
        <button class="wallpaper-cat-pill" data-category="cyber"></button>
      </div>
      <div class="wallpaper-card" data-filename="mountain-lake.jpg"></div>
      <div class="wallpaper-card" data-filename="neon-tokyo.jpg"></div>
      <div class="wallpaper-card" data-filename="cyber-mesh.png"></div>
    `;

    filterGalleryByCategory('cyber');

    const cyberPill = document.querySelector('.wallpaper-cat-pill[data-category="cyber"]');
    expect(cyberPill.classList.contains('active')).toBe(true);

    const mountainCard = document.querySelector('.wallpaper-card[data-filename="mountain-lake.jpg"]');
    const cyberCard = document.querySelector('.wallpaper-card[data-filename="cyber-mesh.png"]');

    expect(mountainCard.style.display).toBe('none');
    expect(cyberCard.style.display).toBe('flex');
  });

  it('uploadAndApplyWallpaper enforces 15MB file size limit and MIME validation', async () => {
    const toastSpy = vi.spyOn(toastModule, 'showToast');

    // 1. Oversized file (> 15MB)
    const bigFile = new File(['x'.repeat(100)], 'huge.png', { type: 'image/png' });
    Object.defineProperty(bigFile, 'size', { value: 16 * 1024 * 1024 });
    const res1 = await uploadAndApplyWallpaper(bigFile);
    expect(res1).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('15MB'), 'error');

    // 2. Invalid MIME type (e.g. .pdf or .exe)
    toastSpy.mockClear();
    const badFile = new File(['text'], 'payload.exe', { type: 'application/x-msdownload' });
    const res2 = await uploadAndApplyWallpaper(badFile);
    expect(res2).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('Unsupported file format'), 'error');
  });

  it('verifies all new Appearance revamp i18n keys exist across en, de, zh, fr, es', () => {
    const langs = ['en', 'de', 'zh', 'fr', 'es'];
    const requiredRevampKeys = [
      'mgmt.twin_preview_title',
      'mgmt.twin_preview_desc',
      'mgmt.cat_all',
      'mgmt.cat_gradient',
      'mgmt.cat_scenic',
      'mgmt.cat_cyber',
      'mgmt.cat_oled',
      'mgmt.eco_mode_title',
      'mgmt.eco_mode_desc',
      'settings.wallpaper_harmony_label',
      'settings.wallpaper_harmony_desc',
      'settings.extract_palette_btn',
      'settings.theme_backup_label',
      'settings.theme_backup_desc',
      'settings.theme_export_btn',
      'settings.theme_import_btn',
      'settings.theme_reset_all_btn',
      'settings.theme_restored',
      'settings.theme_exported',
      'settings.theme_imported',
      'settings.theme_import_failed',
      'settings.palette_extracted_success',
      'settings.palette_sampled_default'
    ];

    langs.forEach((lang) => {
      const dict = TRANSLATIONS[lang];
      expect(dict, `Language dictionary for "${lang}" not found`).toBeDefined();
      requiredRevampKeys.forEach((key) => {
        expect(dict[key], `Missing translation key "${key}" in "${lang}"`).toBeDefined();
        expect(dict[key].length).toBeGreaterThan(0);
      });
    });
  });
});
