import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { initDraggableDesktopIcons } from '../components/dock.js';
import { initDesktopContextMenu, showDesktopContextMenu, hideDesktopContextMenu } from '../components/desktop-context-menu.js';
import {
  SYSTEM_SHORTCUTS,
  addDesktopShortcut,
  removeDesktopShortcut,
  getCustomShortcuts,
  openAddDesktopShortcutModal,
  closeAddDesktopShortcutModal,
  createShortcutElement,
  _resetShortcutsForTesting,
  SHORTCUTS_STORAGE_KEY
} from '../components/desktop-shortcuts.js';

describe('Desktop Shortcuts & Unified Context Menu Integration', () => {
  beforeEach(() => {
    localStorage.clear();
    _resetShortcutsForTesting();

    document.body.innerHTML = `
      <div id="os-dock-container">
        <div id="os-dock"></div>
      </div>
      <div id="desktop" class="chassis-workbench-stage" style="width:1200px; height:800px; position:relative;">
        <div id="desktop-icons-container">
          <div id="management-desktop-icon" class="chassis-hero-box chassis-desktop-icon" style="position:fixed; left:24px; top:77px; width:136px; height:87px;">
            <div class="console-hero-box"></div>
            <div class="desktop-icon-label"><span class="icon-text">Mission Control</span></div>
          </div>
          <div id="fm-desktop-icon" class="chassis-hero-box chassis-desktop-icon" style="position:fixed; left:24px; top:189px; width:136px; height:87px;">
            <div class="console-hero-box"></div>
            <div class="desktop-icon-label"><span class="icon-text">File Explorer</span></div>
          </div>
        </div>
      </div>

      <!-- Unified Desktop Context Menu -->
      <div id="desktop-context-menu" class="desktop-context-menu" style="display:none; position:fixed;">
        <div class="context-menu-item" data-action="add-shortcut">Add Desktop Shortcut…</div>
        <div class="context-menu-item" data-action="align-grid">Align to Grid</div>
        <div class="context-menu-item" data-action="sort-name">Sort by Name</div>
        <div class="context-menu-item" data-action="wallpaper">Change Wallpaper & Style…</div>
      </div>
    `;

    initDesktopContextMenu();
    initDraggableDesktopIcons();
  });

  afterEach(() => {
    _resetShortcutsForTesting();
    document.body.innerHTML = '';
  });

  describe('Context Menu De-duplication', () => {
    it('right-clicking empty desktop shows ONLY unified #desktop-context-menu and NOT #desktop-ctx-menu', () => {
      const desktopCtxMenu = document.getElementById('desktop-context-menu');
      const iconCtxMenu = document.getElementById('desktop-ctx-menu');

      expect(desktopCtxMenu.style.display).toBe('none');
      if (iconCtxMenu) expect(iconCtxMenu.style.display).toBe('none');

      // Right-click empty desktop
      const desktop = document.getElementById('desktop');
      const evt = new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true,
        clientX: 400,
        clientY: 300
      });
      desktop.dispatchEvent(evt);

      expect(desktopCtxMenu.style.display).toBe('flex');
      if (iconCtxMenu) {
        expect(iconCtxMenu.style.display).not.toBe('block');
      }
    });

    it('right-clicking a desktop icon shows ONLY #desktop-ctx-menu and keeps #desktop-context-menu hidden', () => {
      const desktopCtxMenu = document.getElementById('desktop-context-menu');
      const iconCtxMenu = document.getElementById('desktop-ctx-menu');
      const icon = document.getElementById('management-desktop-icon');

      const evt = new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true,
        clientX: 50,
        clientY: 90
      });
      icon.dispatchEvent(evt);

      expect(iconCtxMenu).not.toBeNull();
      expect(iconCtxMenu.style.display).toBe('block');
      expect(desktopCtxMenu.style.display).toBe('none');
      expect(iconCtxMenu.innerHTML).toContain('Mission Control');
      expect(iconCtxMenu.innerHTML).toContain('Align to Grid');
    });

    it('clicking outside dismisses context menus cleanly', () => {
      showDesktopContextMenu(300, 300);
      const desktopCtxMenu = document.getElementById('desktop-context-menu');
      expect(desktopCtxMenu.style.display).toBe('flex');

      document.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 10, clientY: 10 }));
      expect(desktopCtxMenu.style.display).toBe('none');
    });
  });

  describe('Desktop Shortcuts Management', () => {
    it('SYSTEM_SHORTCUTS catalog has definitions for Containers, Storage, Activity Monitor, and Notifications', () => {
      const ids = SYSTEM_SHORTCUTS.map(s => s.id);
      expect(ids).toContain('containers-desktop-icon');
      expect(ids).toContain('storage-desktop-icon');
      expect(ids).toContain('activity-desktop-icon');
      expect(ids).toContain('hardware-desktop-icon');
      expect(ids).toContain('ups-desktop-icon');
      expect(ids).toContain('settings-desktop-icon');
      expect(ids).toContain('notifications-desktop-icon');
    });

    it('adds a system shortcut (Containers) to DOM and persists to localStorage', () => {
      const scDef = SYSTEM_SHORTCUTS.find(s => s.id === 'containers-desktop-icon');
      expect(scDef).toBeDefined();

      const success = addDesktopShortcut(scDef);
      expect(success).toBe(true);

      // Verify DOM element rendered in container
      const iconEl = document.getElementById('containers-desktop-icon');
      expect(iconEl).not.toBeNull();
      expect(iconEl.classList.contains('custom-desktop-shortcut')).toBe(true);
      expect(iconEl.querySelector('.icon-text').textContent).toBe('Containers');

      // Verify localStorage persistence
      const saved = getCustomShortcuts();
      expect(saved.length).toBe(1);
      expect(saved[0].id).toBe('containers-desktop-icon');
      expect(saved[0].name).toBe('Containers');
    });

    it('custom shortcut right-click displays "Remove from Desktop" action', () => {
      const scDef = SYSTEM_SHORTCUTS.find(s => s.id === 'activity-desktop-icon');
      addDesktopShortcut(scDef);

      const iconEl = document.getElementById('activity-desktop-icon');
      expect(iconEl).not.toBeNull();

      // Right-click custom icon
      const evt = new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true,
        clientX: 50,
        clientY: 200
      });
      iconEl.dispatchEvent(evt);

      const iconCtxMenu = document.getElementById('desktop-ctx-menu');
      expect(iconCtxMenu.style.display).toBe('block');
      expect(iconCtxMenu.querySelector('#ctx-remove-shortcut')).not.toBeNull();
      expect(iconCtxMenu.textContent).toContain('Remove from Desktop');
    });

    it('removes a desktop shortcut from DOM and localStorage', () => {
      const scDef = SYSTEM_SHORTCUTS.find(s => s.id === 'storage-desktop-icon');
      addDesktopShortcut(scDef);

      expect(document.getElementById('storage-desktop-icon')).not.toBeNull();
      expect(getCustomShortcuts().length).toBe(1);

      removeDesktopShortcut('storage-desktop-icon');

      expect(getCustomShortcuts().length).toBe(0);
      const el = document.getElementById('storage-desktop-icon');
      // Element should have .removing class while waiting for removal timeout
      if (el) {
        expect(el.classList.contains('removing')).toBe(true);
      }
    });

    it('adds and persists custom URL / bookmark shortcut', () => {
      const customUrlShortcut = {
        id: 'url-shortcut-12345',
        type: 'url',
        name: 'Home Assistant',
        title: 'Home Assistant (http://10.40.30.50:8123)',
        url: 'http://10.40.30.50:8123',
        icon: '🏠',
        svg: false,
        color: '#38bdf8'
      };

      const success = addDesktopShortcut(customUrlShortcut);
      expect(success).toBe(true);

      const iconEl = document.getElementById('url-shortcut-12345');
      expect(iconEl).not.toBeNull();
      expect(iconEl.textContent).toContain('Home Assistant');

      const saved = getCustomShortcuts();
      expect(saved.some(s => s.id === 'url-shortcut-12345')).toBe(true);
    });

    it('openAddDesktopShortcutModal opens modal and close button closes it', () => {
      openAddDesktopShortcutModal();
      const modal = document.getElementById('add-desktop-shortcut-overlay');
      expect(modal).not.toBeNull();
      expect(modal.style.display).toBe('flex');

      // System apps list should be populated
      const systemPane = document.getElementById('pane-system-shortcuts');
      expect(systemPane).not.toBeNull();
      expect(systemPane.children.length).toBeGreaterThan(0);

      // Close modal
      const closeBtn = document.getElementById('btn-close-add-shortcut');
      closeBtn.click();
      expect(modal.style.display).toBe('none');
    });
  });
});
