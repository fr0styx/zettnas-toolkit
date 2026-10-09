import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import fs from 'fs';
import path from 'path';
import { applyDesktopTheme } from '../components/dashboard.js';
import {
  applyWallpaperReadability,
  initWallpaperReadabilityControls,
  applyGlassSettings,
  initGlassControls
} from '../components/wallpapers.js';
import { bringToFront } from '../components/dock.js';

describe('Batch 2: Glassmorphism, Wallpaper Readability, OLED Theme & Specular Glow', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.className = '';
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('verifies DOM markup in index.html for Wallpaper Readability, Glass pane, and OLED preset', () => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    const html = fs.readFileSync(htmlPath, 'utf8');

    // 1. Wallpaper Readability Dimmer element
    expect(html).toContain('id="desktop-wallpaper-dimmer"');

    // 2. Wallpaper Readability controls in mgmt-pane-wallpaper
    expect(html).toContain('id="wallpaper-dim-slider"');
    expect(html).toContain('id="wallpaper-dim-val"');
    expect(html).toContain('id="wallpaper-blur-slider"');
    expect(html).toContain('id="wallpaper-blur-val"');
    expect(html).toContain('id="wallpaper-readability-reset-btn"');

    // 3. Glass & Effects inner tab button and subpane
    expect(html).toContain('data-tab-target="mgmt-pane-glass"');
    expect(html).toContain('id="mgmt-pane-glass"');
    expect(html).toContain('id="glass-blur-slider"');
    expect(html).toContain('id="glass-blur-val"');
    expect(html).toContain('id="glass-opacity-slider"');
    expect(html).toContain('id="glass-opacity-val"');
    expect(html).toContain('id="window-glow-toggle"');
    expect(html).toContain('id="glass-reset-btn"');
    expect(html).toContain('class="window-radius-selector"');
    expect(html).toContain('data-radius="6px"');
    expect(html).toContain('data-radius="12px"');
    expect(html).toContain('data-radius="20px"');

    // 4. Pure OLED Black theme preset
    expect(html).toContain('data-theme-id="oled"');
    expect(html).toContain('settings.theme_oled');
  });

  it('applyWallpaperReadability updates CSS variables and persists to localStorage', () => {
    document.body.innerHTML = `
      <span id="wallpaper-dim-val"></span>
      <input type="range" id="wallpaper-dim-slider" value="0">
      <span id="wallpaper-blur-val"></span>
      <input type="range" id="wallpaper-blur-slider" value="0">
      <button id="wallpaper-readability-reset-btn"></button>
    `;

    applyWallpaperReadability(35, 10, true);

    expect(document.documentElement.style.getPropertyValue('--wallpaper-dim')).toBe('0.35');
    expect(document.documentElement.style.getPropertyValue('--wallpaper-blur')).toBe('10px');
    expect(document.getElementById('wallpaper-dim-val').textContent).toBe('35%');
    expect(document.getElementById('wallpaper-dim-slider').value).toBe('35');
    expect(document.getElementById('wallpaper-blur-val').textContent).toBe('10px');
    expect(document.getElementById('wallpaper-blur-slider').value).toBe('10');

    expect(localStorage.getItem('zettnas_wallpaper_dim')).toBe('35');
    expect(localStorage.getItem('zettnas_wallpaper_blur')).toBe('10');
  });

  it('initWallpaperReadabilityControls restores saved state and resets on button click', () => {
    localStorage.setItem('zettnas_wallpaper_dim', '40');
    localStorage.setItem('zettnas_wallpaper_blur', '15');

    document.body.innerHTML = `
      <span id="wallpaper-dim-val"></span>
      <input type="range" id="wallpaper-dim-slider" value="0">
      <span id="wallpaper-blur-val"></span>
      <input type="range" id="wallpaper-blur-slider" value="0">
      <button id="wallpaper-readability-reset-btn"></button>
    `;

    initWallpaperReadabilityControls();

    expect(document.documentElement.style.getPropertyValue('--wallpaper-dim')).toBe('0.40');
    expect(document.documentElement.style.getPropertyValue('--wallpaper-blur')).toBe('15px');
    expect(document.getElementById('wallpaper-dim-val').textContent).toBe('40%');
    expect(document.getElementById('wallpaper-blur-val').textContent).toBe('15px');

    // Trigger reset button
    const resetBtn = document.getElementById('wallpaper-readability-reset-btn');
    resetBtn.click();

    expect(document.documentElement.style.getPropertyValue('--wallpaper-dim')).toBe('0.15');
    expect(document.documentElement.style.getPropertyValue('--wallpaper-blur')).toBe('0px');
    expect(localStorage.getItem('zettnas_wallpaper_dim')).toBe('15');
    expect(localStorage.getItem('zettnas_wallpaper_blur')).toBe('0');
  });

  it('applyGlassSettings updates acrylic blur, opacity, window radius, and specular glow', () => {
    document.body.innerHTML = `
      <span id="glass-blur-val"></span>
      <input type="range" id="glass-blur-slider" value="24">
      <span id="glass-opacity-val"></span>
      <input type="range" id="glass-opacity-slider" value="72">
      <input type="checkbox" id="window-glow-toggle" checked>
      <button class="window-radius-btn" data-radius="6px"></button>
      <button class="window-radius-btn active" data-radius="12px"></button>
      <button class="window-radius-btn" data-radius="20px"></button>
      <button id="glass-reset-btn"></button>
    `;

    applyGlassSettings(30, 85, '20px', false, true);

    expect(document.documentElement.style.getPropertyValue('--glass-blur')).toBe('30px');
    expect(document.documentElement.style.getPropertyValue('--glass-opacity')).toBe('0.85');
    expect(document.documentElement.style.getPropertyValue('--window-radius')).toBe('20px');
    expect(document.documentElement.style.getPropertyValue('--window-glow-enabled')).toBe('0');
    expect(document.body.classList.contains('no-specular-glow')).toBe(true);

    const radius20Btn = document.querySelector('.window-radius-btn[data-radius="20px"]');
    expect(radius20Btn.classList.contains('active')).toBe(true);
    expect(document.getElementById('window-glow-toggle').checked).toBe(false);

    expect(localStorage.getItem('zettnas_glass_blur')).toBe('30');
    expect(localStorage.getItem('zettnas_glass_opacity')).toBe('85');
    expect(localStorage.getItem('zettnas_window_radius')).toBe('20px');
    expect(localStorage.getItem('zettnas_window_glow')).toBe('false');
  });

  it('initGlassControls binds interactions and supports reset to defaults', () => {
    document.body.innerHTML = `
      <span id="glass-blur-val"></span>
      <input type="range" id="glass-blur-slider" value="24">
      <span id="glass-opacity-val"></span>
      <input type="range" id="glass-opacity-slider" value="72">
      <input type="checkbox" id="window-glow-toggle">
      <button class="window-radius-btn" data-radius="6px"></button>
      <button class="window-radius-btn active" data-radius="12px"></button>
      <button class="window-radius-btn" data-radius="20px"></button>
      <button id="glass-reset-btn"></button>
    `;

    initGlassControls();

    // Click 6px radius button
    const btn6 = document.querySelector('.window-radius-btn[data-radius="6px"]');
    btn6.click();
    expect(document.documentElement.style.getPropertyValue('--window-radius')).toBe('6px');
    expect(localStorage.getItem('zettnas_window_radius')).toBe('6px');

    // Click reset defaults
    const resetBtn = document.getElementById('glass-reset-btn');
    resetBtn.click();

    expect(document.documentElement.style.getPropertyValue('--glass-blur')).toBe('24px');
    expect(document.documentElement.style.getPropertyValue('--glass-opacity')).toBe('0.72');
    expect(document.documentElement.style.getPropertyValue('--window-radius')).toBe('12px');
    expect(document.documentElement.style.getPropertyValue('--window-glow-enabled')).toBe('0');
    expect(document.body.classList.contains('no-specular-glow')).toBe(true);
  });

  it('applyDesktopTheme supports Pure OLED Black theme and computes dynamic RGB, glow and hover variables', () => {
    // 1. OLED theme application
    applyDesktopTheme('oled');
    expect(document.body.classList.contains('theme-oled')).toBe(true);

    // 2. Custom Accent Hex Color: #ff0055 -> RGB: 255, 0, 85
    applyDesktopTheme('oled', '#ff0055');
    expect(document.documentElement.style.getPropertyValue('--brand')).toBe('#ff0055');
    expect(document.documentElement.style.getPropertyValue('--desktop-accent')).toBe('#ff0055');
    expect(document.documentElement.style.getPropertyValue('--accent-rgb')).toBe('255, 0, 85');
    expect(document.documentElement.style.getPropertyValue('--accent-glow')).toBe('rgba(255, 0, 85, 0.35)');
    expect(document.documentElement.style.getPropertyValue('--accent-hover')).toBe('rgba(255, 0, 85, 0.15)');

    // 3. Reset accent removes variables cleanly
    applyDesktopTheme('oled', '');
    expect(document.documentElement.style.getPropertyValue('--brand')).toBe('');
    expect(document.documentElement.style.getPropertyValue('--accent-rgb')).toBe('');
    expect(document.documentElement.style.getPropertyValue('--accent-glow')).toBe('');
  });

  it('bringToFront manages active-window class on target window for specular glow', () => {
    document.body.innerHTML = `
      <div id="file-manager-window" class="os-window"></div>
      <div id="management-window" class="management-window"></div>
    `;

    const fm = document.getElementById('file-manager-window');
    const mgmt = document.getElementById('management-window');

    bringToFront(fm);
    expect(fm.classList.contains('active-window')).toBe(true);
    expect(mgmt.classList.contains('active-window')).toBe(false);

    bringToFront(mgmt);
    expect(mgmt.classList.contains('active-window')).toBe(true);
    expect(fm.classList.contains('active-window')).toBe(false);
  });
});
