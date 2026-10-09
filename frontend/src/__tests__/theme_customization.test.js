import { describe, it, expect, beforeEach } from 'vitest';
import { state } from '../state.js';
import { applyTheme, applyDesktopTheme, applyLcdTheme } from '../components/dashboard.js';
import { syncDesktopThemeUI, syncLcdThemeUI, syncThemeSettingsUI } from '../components/settings.js';
import { t, TRANSLATIONS } from '../i18n.js';
import fs from 'fs';
import path from 'path';

describe('Desktop Theme & LCD Screen Themer Isolation Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.className = '';
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    state.isLcdDirect = false;
  });

  it('verifies mgmt-pane-theme exists in Mission Control Appearance with 8 presets and custom accent picker', () => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    const html = fs.readFileSync(htmlPath, 'utf8');

    // Subtab button and pane
    expect(html).toContain('data-tab-target="mgmt-pane-theme"');
    expect(html).toContain('id="mgmt-pane-theme"');
    expect(html).toContain('id="desktop-theme-active-badge"');

    // 9 Theme presets in Mission Control
    const themes = ['cyber', 'amber', 'emerald', 'sapphire', 'amethyst', 'crimson', 'oled', 'light', 'yak'];
    themes.forEach((tId) => {
      expect(html).toContain(`desktop-theme-preset theme-preset-card`);
      expect(html).toContain(`data-theme-id="${tId}"`);
    });

    // Custom desktop color picker and chips
    expect(html).toContain('id="desktop-custom-color-picker"');
    expect(html).toContain('id="desktop-custom-hex-val"');
    expect(html).toContain('id="desktop-theme-reset-accent-btn"');
    expect(html).toContain('class="desktop-color-chip color-chip-btn"');
  });

  it('verifies sec-lcd-theme exists in Dashboard Layout drawer with 8 chips, custom color, and text clarity toggle', () => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    const html = fs.readFileSync(htmlPath, 'utf8');

    // Section card
    expect(html).toContain('data-layout-card-id="sec-lcd-theme"');
    expect(html).toContain('id="sec-lcd-theme"');
    expect(html).toContain('id="lcd-theme-active-badge"');

    // 8 LCD Theme chips
    const themes = ['cyber', 'amber', 'emerald', 'sapphire', 'amethyst', 'crimson', 'light', 'yak'];
    themes.forEach((tId) => {
      expect(html).toContain(`class="lcd-theme-chip`);
      expect(html).toContain(`data-lcd-theme="${tId}"`);
    });

    // LCD Custom accent picker and text clarity toggle
    expect(html).toContain('id="lcd-custom-color-picker"');
    expect(html).toContain('id="lcd-custom-hex-val"');
    expect(html).toContain('id="lcd-reset-accent-btn"');
    expect(html).toContain('id="lcd-text-clarity-toggle"');
  });

  it('strictly isolates Desktop Theme: applyDesktopTheme modifies body/desktop, NEVER touches LCD screen or System Console', () => {
    // Setup simulated Console Window, LCD Screen, and Mini Canvas elements
    document.body.innerHTML = `
      <div id="console-window" class="chassis-front-panel">
        <span class="chassis-engraved-text" id="chassis-panel-engraved">ZETTNAS • SYSTEM CONSOLE</span>
        <div id="screen" class="lcd-theme-cyber">
          <div class="card card-storage"><span class="card-title-txt">STORAGE</span></div>
          <div class="card card-cpu"><span class="card-title-txt">CPU</span></div>
          <div class="card card-fans"><span class="card-title-txt">FANS</span></div>
          <div class="card card-net"><span class="card-title-txt">NETWORK I/O</span></div>
          <div class="nas-name">NAS</div>
          <div class="clock">12:00</div>
        </div>
        <div id="virtual-chassis-lightbar"></div>
      </div>
      <div id="mini-lcd-canvas" class="lcd-theme-cyber">
        <div class="mini-preview-inner">
          <div class="nas-name">NAS</div>
          <div class="clock">12:00</div>
        </div>
      </div>
      <span id="suite-brand-title">ZETTNAS</span>
      <span id="suite-brand-badge">NAS WORKBENCH</span>
    `;
    const consoleWin = document.getElementById('console-window');
    const screenEl = document.getElementById('screen');
    const miniCanvas = document.getElementById('mini-lcd-canvas');
    const engraved = document.getElementById('chassis-panel-engraved');
    const storageTitle = document.querySelector('.card-storage .card-title-txt');
    const lightbar = document.getElementById('virtual-chassis-lightbar');

    // 1. Apply Amber Desktop Theme
    applyDesktopTheme('amber', '#ffbe40');

    // Desktop body is themed
    expect(document.body.classList.contains('theme-amber')).toBe(true);
    expect(document.documentElement.style.getPropertyValue('--brand')).toBe('#ffbe40');
    expect(state.desktopTheme).toBe('amber');
    expect(state.desktopCustomAccent).toBe('#ffbe40');

    // LCD screen, mini preview, and console window are UNTOUCHED by desktop theme
    expect(screenEl.classList.contains('theme-amber')).toBe(false);
    expect(screenEl.classList.contains('lcd-theme-amber')).toBe(false);
    expect(screenEl.classList.contains('lcd-theme-cyber')).toBe(true);
    expect(miniCanvas.classList.contains('lcd-theme-amber')).toBe(false);
    expect(consoleWin.classList.contains('lcd-theme-amber')).toBe(false);
    expect(engraved.textContent).toBe('ZETTNAS • SYSTEM CONSOLE');
    expect(storageTitle.textContent).toBe('STORAGE');

    // 2. Apply Yak Desktop Theme
    applyDesktopTheme('yak');
    expect(document.body.classList.contains('theme-yak')).toBe(true);
    // Console window and screen MUST NOT have Yak freight changes
    expect(consoleWin.classList.contains('lcd-theme-yak')).toBe(false);
    expect(engraved.textContent).toBe('ZETTNAS • SYSTEM CONSOLE');
    expect(storageTitle.textContent).toBe('STORAGE');
    expect(lightbar.style.background).toBe('');

    // Stored in desktop preference
    expect(localStorage.getItem('desktop_theme')).toBe('yak');
  });

  it('strictly isolates LCD Screen Theme: applyLcdTheme modifies screen/mini canvas/console window, NEVER touches body', () => {
    document.body.innerHTML = `
      <div id="console-window" class="chassis-front-panel">
        <span class="chassis-engraved-text" id="chassis-panel-engraved">ZETTNAS • SYSTEM CONSOLE</span>
        <div id="screen" class="lcd-theme-cyber">
          <div class="card card-storage"><span class="card-title-txt">STORAGE</span></div>
          <div class="card card-cpu"><span class="card-title-txt">CPU</span></div>
        </div>
        <div id="virtual-chassis-lightbar"></div>
      </div>
      <div id="mini-lcd-canvas" class="lcd-theme-cyber">
        <div class="mini-preview-inner"></div>
      </div>
    `;
    const consoleWin = document.getElementById('console-window');
    const screenEl = document.getElementById('screen');
    const miniCanvas = document.getElementById('mini-lcd-canvas');
    const engraved = document.getElementById('chassis-panel-engraved');
    const storageTitle = document.querySelector('.card-storage .card-title-txt');
    const lightbar = document.getElementById('virtual-chassis-lightbar');

    // Set initial desktop theme
    document.body.classList.add('theme-emerald');

    applyLcdTheme('sapphire', '#38bdf8', true);

    // Screen elements received LCD theme, accent, and clarity
    expect(screenEl.classList.contains('lcd-theme-sapphire')).toBe(true);
    expect(screenEl.classList.contains('text-clarity-on')).toBe(true);
    expect(screenEl.style.getPropertyValue('--brand')).toBe('#38bdf8');

    expect(miniCanvas.classList.contains('lcd-theme-sapphire')).toBe(true);
    expect(miniCanvas.classList.contains('text-clarity-on')).toBe(true);
    expect(miniCanvas.style.getPropertyValue('--brand')).toBe('#38bdf8');

    expect(consoleWin.classList.contains('lcd-theme-sapphire')).toBe(true);

    // Body did NOT change to sapphire or receive LCD theme classes
    expect(document.body.classList.contains('theme-emerald')).toBe(true);
    expect(document.body.classList.contains('theme-sapphire')).toBe(false);
    expect(document.body.classList.contains('lcd-theme-sapphire')).toBe(false);

    // Now test Yak LCD Theme
    applyLcdTheme('yak');
    expect(screenEl.classList.contains('lcd-theme-yak')).toBe(true);
    expect(consoleWin.classList.contains('lcd-theme-yak')).toBe(true);
    expect(engraved.textContent).toBe('YAK EXPRESS • TOASTIE LOGISTICS LAB');
    expect(storageTitle.textContent).toBe('CARGO HOLD');
    expect(lightbar.style.background).toContain('linear-gradient');
    // Body is still emerald!
    expect(document.body.classList.contains('theme-emerald')).toBe(true);
    expect(document.body.classList.contains('theme-yak')).toBe(false);

    // Stored in LCD preference
    expect(localStorage.getItem('lcd_theme')).toBe('yak');
  });

  it('backward compatibility: applyTheme updates both state representations', () => {
    document.body.innerHTML = `
      <div id="screen"></div>
      <div id="mini-lcd-canvas"></div>
    `;
    applyTheme('emerald', '#3bf58b', false);

    expect(state.currentTheme).toBe('emerald');
    expect(document.body.classList.contains('theme-emerald')).toBe(true);
    expect(state.desktopTheme).toBe('emerald');
  });

  it('syncDesktopThemeUI correctly updates desktop controls in Mission Control', () => {
    document.body.innerHTML = `
      <div id="mgmt-pane-theme">
        <span id="desktop-theme-active-badge"></span>
        <button class="desktop-theme-preset" data-theme-id="cyber"></button>
        <button class="desktop-theme-preset" data-theme-id="amethyst"></button>
        <input type="color" id="desktop-custom-color-picker" value="#00f0ff">
        <span id="desktop-custom-hex-val"></span>
        <button class="desktop-color-chip" data-color="#c084fc"></button>
      </div>
    `;

    state.setDesktopTheme('amethyst', '#c084fc');
    syncDesktopThemeUI();

    const activeCard = document.querySelector('.desktop-theme-preset.active');
    expect(activeCard).not.toBeNull();
    expect(activeCard.dataset.themeId).toBe('amethyst');

    const badge = document.getElementById('desktop-theme-active-badge');
    expect(badge.textContent).toBe('AMETHYST VIOLET');

    const picker = document.getElementById('desktop-custom-color-picker');
    expect(picker.value).toBe('#c084fc');

    const chip = document.querySelector('.desktop-color-chip[data-color="#c084fc"]');
    expect(chip.classList.contains('active')).toBe(true);
  });

  it('syncLcdThemeUI correctly updates LCD controls in Dashboard Layout drawer', () => {
    document.body.innerHTML = `
      <div id="sec-lcd-theme" data-layout-card-id="sec-lcd-theme">
        <span id="lcd-theme-active-badge"></span>
        <button class="lcd-theme-chip" data-lcd-theme="cyber"></button>
        <button class="lcd-theme-chip" data-lcd-theme="sapphire"></button>
        <input type="color" id="lcd-custom-color-picker" value="#00f0ff">
        <span id="lcd-custom-hex-val"></span>
        <button id="lcd-reset-accent-btn"></button>
        <input type="checkbox" id="lcd-text-clarity-toggle">
      </div>
    `;

    state.setLcdTheme('sapphire', '#38bdf8', true);
    syncLcdThemeUI();

    const activeChip = document.querySelector('.lcd-theme-chip.active');
    expect(activeChip).not.toBeNull();
    expect(activeChip.dataset.lcdTheme).toBe('sapphire');

    const badge = document.getElementById('lcd-theme-active-badge');
    expect(badge.textContent).toBe('SAPPHIRE ICE');

    const picker = document.getElementById('lcd-custom-color-picker');
    expect(picker.value).toBe('#38bdf8');

    const toggle = document.getElementById('lcd-text-clarity-toggle');
    expect(toggle.checked).toBe(true);
  });

  it('validates theme and lcd translation keys exist across en, de, zh, fr, es', () => {
    const langs = ['en', 'de', 'zh', 'fr', 'es'];
    const requiredKeys = [
      'mgmt.subtab_theme',
      'mgmt.theme_title',
      'mgmt.theme_desc',
      'mgmt.theme_presets_label',
      'settings.lcd_theme_title',
      'settings.lcd_theme_desc',
      'settings.lcd_custom_accent',
      'settings.theme_chip_cyber',
      'settings.theme_chip_amber',
      'settings.theme_chip_emerald',
      'settings.theme_chip_sapphire',
      'settings.theme_chip_amethyst',
      'settings.theme_chip_crimson',
      'settings.theme_chip_light',
      'settings.theme_chip_yak',
      'settings.text_clarity_title',
      'settings.text_clarity_desc'
    ];

    langs.forEach((lang) => {
      const dict = TRANSLATIONS[lang];
      expect(dict).toBeDefined();
      requiredKeys.forEach((k) => {
        expect(dict[k], `Missing translation key "${k}" in language "${lang}"`).toBeDefined();
        expect(dict[k].length).toBeGreaterThan(0);
      });
    });
  });
});
