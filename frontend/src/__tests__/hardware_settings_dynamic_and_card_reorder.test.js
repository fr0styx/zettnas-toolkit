import { readIndexHtml } from './helpers/read-index-html.js';
import { readStyleCss } from './helpers/read-style-css.js';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { api } from '../api.js';
import { state } from '../state.js';
import { applyDesktopTheme, updateHardwareTelemetry } from '../components/dashboard.js';
import { initSettings } from '../components/settings.js';
import fs from 'fs';
import path from 'path';

describe('Yak Wallpaper Switch, Card Reordering, and Dynamic Hardware Settings Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.className = '';
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    state.isLcdDirect = false;
  });

  describe('Requirement 1: Yak Theme Background Image Immediate Switch', () => {
    it('immediately sets desktop wallpaper to Yak artwork when Yak theme is selected, and restores previous on switch', () => {
      document.body.innerHTML = `
        <div id="desktop">
          <div id="desktop-wallpaper" style="background-image: url('/wallpapers/bahia.jpg');"></div>
        </div>
      `;
      const wp = document.getElementById('desktop-wallpaper');
      expect(wp.style.backgroundImage).toContain('/wallpapers/bahia.jpg');

      // 1. Apply Yak Theme
      applyDesktopTheme('yak');
      expect(document.body.classList.contains('theme-yak')).toBe(true);
      expect(wp.style.backgroundImage).toContain('/img/yak.webp');
      expect(wp.style.backgroundSize).toBe('contain');
      expect(wp.style.display).toBe('block');

      // 2. Switch away from Yak Theme to Amber
      applyDesktopTheme('amber');
      expect(document.body.classList.contains('theme-yak')).toBe(false);
      expect(document.body.classList.contains('theme-amber')).toBe(true);
      expect(wp.style.backgroundImage).toContain('/wallpapers/bahia.jpg');
      expect(wp.style.backgroundSize).toBe('');
    });

    it('verifies CSS rules in style.css for body.theme-yak #desktop-wallpaper', () => {
      const css = readStyleCss();

      expect(css).toContain('body.theme-yak #desktop-wallpaper');
      expect(css).toContain('url("/img/yak.webp")');
      expect(css).toContain('background-size: contain !important;');
    });
  });

  describe('Requirement 2: Hardware Settings Card Lock & Re-arrangement across Layout, LED, Fans, and Copy tabs', () => {
    beforeEach(() => {
      document.body.innerHTML = `
        <button id="drawer-toggle-btn" class="suite-toolkit-btn">⚙ HARDWARE SETTINGS</button>
        <div id="led-drawer" class="slide-drawer">
          <button id="drawer-close-btn"></button>

          <!-- Tab Layout -->
          <div id="tab-layout" class="drawer-tab-content">
            <button id="layout-cards-lock-btn" class="btn-lock-toggle">🔒 Locked</button>
            <div id="layout-sections-container" class="layout-sections-flow locked">
              <div class="draggable-card" data-layout-card-id="card-layout-preview"><span class="drag-handle">⋮⋮</span></div>
              <div class="draggable-card" data-layout-card-id="card-layout-screens"><span class="drag-handle">⋮⋮</span></div>
              <div class="draggable-card" data-layout-card-id="card-layout-theme"><span class="drag-handle">⋮⋮</span></div>
            </div>
          </div>

          <!-- Tab LED -->
          <div id="tab-led" class="drawer-tab-content">
            <button id="drawer-lock-btn" class="btn-lock-toggle">🔒 Locked</button>
            <div id="drawer-cards-container" class="drawer-cards-flow locked">
              <div class="draggable-card" data-card-id="card-preview"><span class="drag-handle">⋮⋮</span></div>
              <div class="draggable-card" data-card-id="card-reactive"><span class="drag-handle">⋮⋮</span></div>
              <div class="draggable-card" data-card-id="card-brightness"><span class="drag-handle">⋮⋮</span></div>
              <div class="draggable-card" data-card-id="card-led-schedule"><span class="drag-handle">⋮⋮</span></div>
            </div>
          </div>

          <!-- Tab Fans -->
          <div id="tab-fans" class="drawer-tab-content">
            <button id="fan-cards-lock-btn" class="btn-lock-toggle">🔒 Locked</button>
            <div id="fan-cards-container" class="drawer-cards-flow locked">
              <div class="draggable-card" data-fan-card-id="fan-card-tach"><span class="drag-handle">⋮⋮</span></div>
              <div class="draggable-card" data-fan-card-id="fan-card-zones"><span class="drag-handle">⋮⋮</span></div>
            </div>
          </div>

          <!-- Tab Copy -->
          <div id="tab-buttons" class="drawer-tab-content">
            <button id="btn-cards-lock-btn" class="btn-lock-toggle">🔒 Locked</button>
            <div id="btn-sections-container" class="drawer-cards-flow locked">
              <div class="draggable-card" data-btn-card-id="sec-copybtn"><span class="drag-handle">⋮⋮</span></div>
              <div class="draggable-card" data-btn-card-id="sec-autoingest"><span class="drag-handle">⋮⋮</span></div>
            </div>
          </div>
        </div>
      `;
    });

    it('initializes all 4 tabs with locked state and allows unlocking', () => {
      initSettings();

      const ledLockBtn = document.getElementById('drawer-lock-btn');
      const fanLockBtn = document.getElementById('fan-cards-lock-btn');
      const copyLockBtn = document.getElementById('btn-cards-lock-btn');
      const layoutLockBtn = document.getElementById('layout-cards-lock-btn');

      const ledContainer = document.getElementById('drawer-cards-container');
      const fanContainer = document.getElementById('fan-cards-container');
      const copyContainer = document.getElementById('btn-sections-container');
      const layoutContainer = document.getElementById('layout-sections-container');

      expect(ledLockBtn.textContent).toContain('Locked');
      expect(fanLockBtn.textContent).toContain('Locked');
      expect(copyLockBtn.textContent).toContain('Locked');
      expect(layoutLockBtn.textContent).toContain('Locked');

      expect(ledContainer.classList.contains('locked')).toBe(true);
      expect(fanContainer.classList.contains('locked')).toBe(true);
      expect(copyContainer.classList.contains('locked')).toBe(true);
      expect(layoutContainer.classList.contains('locked')).toBe(true);

      // Unlock LED tab
      ledLockBtn.click();
      expect(ledLockBtn.textContent).toContain('Reorder');
      expect(ledContainer.classList.contains('locked')).toBe(false);
      expect(localStorage.getItem('lcd_led_cards_locked')).toBe('false');

      // Unlock Fans tab
      fanLockBtn.click();
      expect(fanLockBtn.textContent).toContain('Reorder');
      expect(fanContainer.classList.contains('locked')).toBe(false);
      expect(localStorage.getItem('lcd_fans_cards_locked')).toBe('false');

      // Unlock Copy tab
      copyLockBtn.click();
      expect(copyLockBtn.textContent).toContain('Reorder');
      expect(copyContainer.classList.contains('locked')).toBe(false);
      expect(localStorage.getItem('lcd_copy_cards_locked')).toBe('false');
    });

    it('restores custom card arrangement from localStorage across LED, Fans, and Copy tabs', () => {
      localStorage.setItem('lcd_led_card_order', JSON.stringify(['card-brightness', 'card-preview', 'card-reactive', 'card-led-schedule']));
      localStorage.setItem('lcd_fans_card_order', JSON.stringify(['fan-card-zones', 'fan-card-tach']));
      localStorage.setItem('lcd_copy_card_order', JSON.stringify(['sec-autoingest', 'sec-copybtn']));

      initSettings();

      const ledCards = Array.from(document.querySelectorAll('#drawer-cards-container .draggable-card')).map(c => c.dataset.cardId);
      expect(ledCards).toEqual(['card-brightness', 'card-preview', 'card-reactive', 'card-led-schedule']);

      const fanCards = Array.from(document.querySelectorAll('#fan-cards-container .draggable-card')).map(c => c.dataset.fanCardId);
      expect(fanCards).toEqual(['fan-card-zones', 'fan-card-tach']);

      const copyCards = Array.from(document.querySelectorAll('#btn-sections-container .draggable-card')).map(c => c.dataset.btnCardId);
      expect(copyCards).toEqual(['sec-autoingest', 'sec-copybtn']);
    });
  });

  describe('Requirement 3: Dynamic Hardware Settings Button & MCU/FB Badges', () => {
    beforeEach(() => {
      document.body.innerHTML = `
        <div id="mcu-status-pill" class="suite-pill hidden"><span class="pulse-dot"></span> MCU: <strong id="mcu-status-text">/dev/ttyACM0</strong></div>
        <div id="fb-status-pill" class="suite-pill hidden"><span class="pulse-dot"></span> FB: <strong id="fb-status-text">/dev/fb0 (640x172)</strong></div>
        <button id="drawer-toggle-btn" class="suite-toolkit-btn hidden">⚙ HARDWARE SETTINGS</button>
        <div id="chassis-desktop-icon" class="chassis-hero-box chassis-desktop-icon" title="ZettNAS"></div>
        <div class="chassis-front-panel" id="console-window">
          <span class="chassis-screen-spec">640 × 172 IPS</span>
          <div id="screen" class="hardware-screen-canvas" style="width: 640px; height: 172px;"></div>
        </div>
      `;
    });

    it('shows MCU pill, FB pill, Hardware Settings button, and ZettNAS desktop icon on ZETTLABS D6U / custom hardware equipment', () => {
      const stats = {
        hardware: {
          sys_vendor: 'Zettlab',
          product_name: 'D6 Ultra',
          is_zettlabs: true,
          is_custom_appliance: true,
          has_lcd: true,
          has_mcu: true,
          has_copy_button: true,
          has_sd_slot: true,
          has_custom_hardware: true,
          lcd_resolution: {
            width: 640,
            height: 172,
            stride: 704,
            spec: '640 × 172 IPS',
          },
        },
        peripherals: {
          fb_active: true,
          led_port: '/dev/ttyACM0',
          led_ready: true,
          has_custom_hardware: true,
        },
      };

      updateHardwareTelemetry(stats);

      const mcuPill = document.getElementById('mcu-status-pill');
      const fbPill = document.getElementById('fb-status-pill');
      const drawerBtn = document.getElementById('drawer-toggle-btn');
      const mcuText = document.getElementById('mcu-status-text');
      const chassisIcon = document.getElementById('chassis-desktop-icon');
      const fbText = document.getElementById('fb-status-text');

      expect(mcuPill.classList.contains('hidden')).toBe(false);
      expect(mcuText.textContent).toBe('/dev/ttyACM0');
      expect(fbPill.classList.contains('hidden')).toBe(false);
      expect(fbText.textContent).toBe('/dev/fb0 (640x172)');
      expect(drawerBtn.classList.contains('hidden')).toBe(false);
      expect(drawerBtn.style.display).not.toBe('none');

      // ZettNAS icon visible on Zettlabs D6U
      expect(chassisIcon.style.display).not.toBe('none');
      expect(chassisIcon.classList.contains('hidden')).toBe(false);
      expect(chassisIcon.getAttribute('title')).toContain('640 × 172 IPS');
    });

    it('hides MCU pill, FB pill, Hardware Settings button, and ZettNAS desktop icon on generic PC, Dell/HP servers, or VMs', () => {
      const stats = {
        hardware: {
          sys_vendor: 'Dell Inc.',
          product_name: 'PowerEdge R730',
          is_zettlabs: false,
          is_custom_appliance: false,
          has_lcd: false,
          has_mcu: false,
          has_copy_button: false,
          has_sd_slot: false,
          has_custom_hardware: false,
          lcd_resolution: {
            spec: 'N/A',
          },
        },
        peripherals: {
          fb_active: false,
          led_port: null,
          led_ready: false,
          has_custom_hardware: false,
        },
      };

      updateHardwareTelemetry(stats);

      const mcuPill = document.getElementById('mcu-status-pill');
      const fbPill = document.getElementById('fb-status-pill');
      const drawerBtn = document.getElementById('drawer-toggle-btn');
      const chassisIcon = document.getElementById('chassis-desktop-icon');

      expect(mcuPill.classList.contains('hidden')).toBe(true);
      expect(fbPill.classList.contains('hidden')).toBe(true);
      expect(drawerBtn.classList.contains('hidden')).toBe(true);
      expect(drawerBtn.style.display).toBe('none');

      // ZettNAS icon hidden on generic hardware without physical LCD
      expect(chassisIcon.style.display).toBe('none');
      expect(chassisIcon.classList.contains('hidden')).toBe(true);
    });

    it('shows ZettNAS desktop icon and adapts display resolution when non-Zettlabs hardware has a physical LCD', () => {
      const stats = {
        hardware: {
          sys_vendor: 'Supermicro',
          product_name: 'Super Server',
          is_zettlabs: false,
          is_custom_appliance: false,
          has_lcd: true,
          has_mcu: false,
          has_custom_hardware: true,
          lcd_resolution: {
            width: 480,
            height: 320,
            stride: 512,
            spec: '480 × 320 IPS',
          },
        },
        peripherals: {
          fb_active: true,
        },
      };

      updateHardwareTelemetry(stats);

      const chassisIcon = document.getElementById('chassis-desktop-icon');
      const fbText = document.getElementById('fb-status-text');
      const specEl = document.querySelector('.chassis-screen-spec');
      const screenEl = document.getElementById('screen');

      // Visible because physical LCD is present
      expect(chassisIcon.style.display).not.toBe('none');
      expect(chassisIcon.getAttribute('title')).toContain('480 × 320 IPS');

      // Adaptive display resolution for perfect display of data
      expect(fbText.textContent).toBe('/dev/fb0 (480x320)');
      expect(specEl.textContent).toBe('480 × 320 IPS');
      expect(screenEl.style.width).toBe('480px');
      expect(screenEl.style.height).toBe('320px');
    });

    it('verifies MCU and FB pills are removed from the top bar in production index.html', () => {
      const indexHtml = readIndexHtml();
      expect(indexHtml).not.toContain('id="mcu-status-pill"');
      expect(indexHtml).not.toContain('id="fb-status-pill"');
    });
  });

  describe('Requirement 4: Physical LCD Screen Power Toggle & 0% Backlight', () => {
    it('toggles physical LCD screen off and back on, preserving brightness and updating badge', async () => {
      document.body.innerHTML = `
        <span id="lcd-renderer-badge" class="lcd-status-badge lcd-status-active">LCD: 10 FPS ACTIVE</span>
        <span id="screen-bri-val" class="card-head-val">100%</span>
        <button id="btn-toggle-screen-power" type="button" class="btn-pill-toggle">Turn Off</button>
        <input type="range" id="screen-bri-slider" min="0" max="100" value="100" step="1">
        <input type="checkbox" id="screen-night-toggle">
        <input type="time" id="screen-night-start" value="23:00">
        <input type="time" id="screen-night-end" value="07:00">
        <input type="number" id="screen-night-bri" value="10">
      `;

      const getSpy = vi.spyOn(api, 'get').mockImplementation(async (url) => {
        if (url === '/api/screen') {
          return { power: true, brightness: 80, night_mode: false, night_start: '23:00', night_end: '07:00', night_brightness: 10 };
        }
        return {};
      });
      const postSpy = vi.spyOn(api, 'post').mockResolvedValue({});

      initSettings();
      await new Promise((r) => setTimeout(r, 20));

      const briVal = document.getElementById('screen-bri-val');
      const powerBtn = document.getElementById('btn-toggle-screen-power');
      const slider = document.getElementById('screen-bri-slider');
      const badge = document.getElementById('lcd-renderer-badge');

      expect(slider.getAttribute('min')).toBe('0');
      expect(briVal.textContent).toBe('80%');
      expect(powerBtn.textContent).toBe('Turn Off');

      // Click Turn Off
      powerBtn.click();
      await new Promise((r) => setTimeout(r, 20));

      expect(briVal.textContent).toBe('OFF');
      expect(powerBtn.textContent).toBe('Turn On');
      expect(badge.textContent).toBe('LCD: SCREEN OFF');
      expect(postSpy).toHaveBeenCalledWith(
        '/api/screen',
        expect.objectContaining({ power: false, brightness: 80 })
      );

      // Click Turn On -> restores 80%
      powerBtn.click();
      await new Promise((r) => setTimeout(r, 20));

      expect(briVal.textContent).toBe('80%');
      expect(powerBtn.textContent).toBe('Turn Off');
      expect(badge.textContent).toBe('LCD: 10 FPS ACTIVE');
      expect(postSpy).toHaveBeenCalledWith(
        '/api/screen',
        expect.objectContaining({ power: true, brightness: 80 })
      );

      getSpy.mockRestore();
      postSpy.mockRestore();
    });
  });
});
