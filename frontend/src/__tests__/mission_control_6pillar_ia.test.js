import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  SUBPANE_MAP,
  updateManagementTelemetry
} from '../components/management.js';
import { openDrawer } from '../components/settings.js';
import {
  initPersonalization,
  openPersonalizationWindow,
  switchPersonalizationTab
} from '../components/personalization.js';
import { DockManager } from '../components/dock.js';

describe('Mission Control 6-Pillar Information Architecture & Hardware Agnosticism', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="os-dock-container"><div id="os-dock"></div></div>
      <div id="management-modal-overlay" class="open" style="display: flex;">
        <div id="management-modal-window">
          <div class="mgmt-inner-tab" data-tab-target="mgmt-pane-hardware-fans">Fans</div>
          <div class="mgmt-inner-tab" data-tab-target="mgmt-pane-hardware-led">LED Strip</div>
          <div class="mgmt-inner-tab" data-tab-target="mgmt-pane-hardware-lcd">LCD Framebuffer</div>
          <div id="mgmt-pane-wallpaper">Wallpaper Content</div>
          <div id="mgmt-pane-theme">Theme Content</div>
          <div id="mgmt-pane-glass">Glass Content</div>
          <div id="mgmt-pane-dock">Dock Content</div>
          <div id="mgmt-pane-screensaver">Screensaver Content</div>
          <div id="mgmt-pane-widgets">Widgets Content</div>
        </div>
      </div>
      <div id="led-drawer" class="slide-drawer">
        <button class="drawer-tab-btn active" data-tab="tab-layout">Dashboard Layout</button>
        <button class="drawer-tab-btn" data-tab="tab-led">LED Strip bar</button>
        <button class="drawer-tab-btn" data-tab="tab-fans">Fans</button>
        <button class="drawer-tab-btn" data-tab="tab-buttons">Copy Button</button>
        <div id="tab-layout" class="drawer-tab-content active">Console Content</div>
        <div id="tab-led" class="drawer-tab-content">LED Content</div>
        <div id="tab-fans" class="drawer-tab-content">Fans Content</div>
        <div id="tab-buttons" class="drawer-tab-content">Buttons Content</div>
      </div>
      <div id="drawer-overlay" class="drawer-backdrop"></div>
    `;
    window._personalizationInitialized = false;
    window.DockManager = DockManager;
    DockManager.windows = {};
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('SUBPANE_MAP has at least 35 entries resolving in <= 2 clicks with valid target sections', () => {
    const keys = Object.keys(SUBPANE_MAP);
    expect(keys.length).toBeGreaterThanOrEqual(35);

    const validSections = new Set([
      'mgmt-sec-activity',
      'mgmt-sec-overview',
      'mgmt-sec-storage',
      'mgmt-sec-docker',
      'mgmt-sec-vms',
      'mgmt-sec-network',
      'mgmt-sec-hardware',
      'mgmt-sec-ups',
      'mgmt-sec-system-group',
      'mgmt-sec-wallpaper',
      'mgmt-sec-ai'
    ]);

    keys.forEach((key) => {
      const mapping = SUBPANE_MAP[key];
      expect(mapping).toBeDefined();
      expect(typeof mapping.section).toBe('string');
      expect(validSections.has(mapping.section)).toBe(true);
      // Ensure pane target is either null or string
      if (mapping.pane !== null) {
        expect(typeof mapping.pane).toBe('string');
      }
    });
  });

  it('openDrawer opens sliding drawer with tabs and falls back gracefully when drawer is missing', () => {
    const drawer = document.getElementById('led-drawer');
    const overlay = document.getElementById('drawer-overlay');

    openDrawer('tab-fans');
    expect(drawer.classList.contains('open')).toBe(true);
    expect(overlay.classList.contains('open')).toBe(true);
    expect(document.body.classList.contains('drawer-is-open')).toBe(true);

    // Fallback when drawer is removed
    drawer.remove();
    overlay.remove();
    window.openManagementWindow = vi.fn();
    window.openPersonalizationWindow = vi.fn();

    openDrawer('tab-fans');
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-pane-hardware-fans');

    openDrawer('tab-led');
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-pane-hardware-led');

    openDrawer('tab-buttons');
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-pane-copy');

    openDrawer('tab-layout');
    expect(window.openPersonalizationWindow).toHaveBeenCalledWith('console');
  });

  it('automatically hides appliance-only LED & LCD hardware tabs on headless hosts (AGENTS.md §1.1)', () => {
    const ledTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-hardware-led"]');
    const lcdTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-hardware-lcd"]');

    // Scenario A: Headless host (No LCD, No LED)
    const headlessStats = {
      peripherals: { fb_active: false, led_ready: false, led_port: null },
      hardware: { has_lcd: false, has_mcu: false }
    };
    updateManagementTelemetry(headlessStats);

    expect(ledTab.style.display).toBe('none');
    expect(lcdTab.style.display).toBe('none');

    // Scenario B: Appliance hardware detected
    const applianceStats = {
      peripherals: { fb_active: true, led_ready: true, led_port: '/dev/ttyACM0' },
      hardware: { has_lcd: true, has_mcu: true }
    };
    updateManagementTelemetry(applianceStats);

    expect(ledTab.style.display).toBe('');
    expect(lcdTab.style.display).toBe('');
  });

  it('dedicated Personalization window opens and switches sub-tabs correctly', () => {
    initPersonalization();
    const win = document.getElementById('personalization-window');
    expect(win).not.toBeNull();
    expect(win.style.display).toBe('none');

    openPersonalizationWindow('theme');
    expect(win.style.display).toBe('flex');

    const themeNavBtn = document.querySelector('.personalization-nav-item[data-tab="theme"]');
    expect(themeNavBtn.classList.contains('active')).toBe(true);

    const themePane = document.getElementById('p-pane-theme');
    const wallpaperPane = document.getElementById('p-pane-wallpaper');
    expect(themePane.style.display).toBe('block');
    expect(wallpaperPane.style.display).toBe('none');

    // Switch to console sub-tab
    switchPersonalizationTab('console');
    const consolePane = document.getElementById('p-pane-console');
    expect(consolePane.style.display).toBe('block');
    expect(themePane.style.display).toBe('none');
  });
});
