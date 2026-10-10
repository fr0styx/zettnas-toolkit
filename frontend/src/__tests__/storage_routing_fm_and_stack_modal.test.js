import { describe, it, expect, beforeEach, vi } from 'vitest';
import { SYSTEM_SHORTCUTS, launchShortcut } from '../components/desktop-shortcuts.js';
import { SUBPANE_MAP } from '../components/management.js';
import { openStackModal, initStackModal, closeStackModal, _resetStackModalForTesting } from '../components/stack-modal.js';
import { bringToFront, DockManager } from '../components/dock.js';
import fs from 'fs';
import path from 'path';

describe('Storage Routing, File Manager Solid Styling, and Stack Inspector Elevation', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    _resetStackModalForTesting();
    vi.restoreAllMocks();
  });

  describe('Issue 1: Storage & Pools Desktop Shortcut Routing', () => {
    it('defines storage-desktop-icon with targetSection mgmt-sec-storage and targetPane mgmt-pane-storage-topo', () => {
      const storageDef = SYSTEM_SHORTCUTS.find((s) => s.id === 'storage-desktop-icon');
      expect(storageDef).toBeDefined();
      expect(storageDef.targetSection).toBe('mgmt-sec-storage');
      expect(storageDef.targetPane).toBe('mgmt-pane-storage-topo');
    });

    it('SUBPANE_MAP resolves legacy aliases and pools aliases to mgmt-pane-storage-topo', () => {
      expect(SUBPANE_MAP['mgmt-pane-chassis']).toEqual({
        section: 'mgmt-sec-storage',
        pane: 'mgmt-pane-storage-topo'
      });
      expect(SUBPANE_MAP['mgmt-sec-pools']).toEqual({
        section: 'mgmt-sec-storage',
        pane: 'mgmt-pane-storage-topo'
      });
      expect(SUBPANE_MAP['mgmt-pane-pools']).toEqual({
        section: 'mgmt-sec-storage',
        pane: 'mgmt-pane-storage-topo'
      });
      expect(SUBPANE_MAP['storage-pools']).toEqual({
        section: 'mgmt-sec-storage',
        pane: 'mgmt-pane-storage-topo'
      });
      expect(SUBPANE_MAP['mgmt-pane-storage-topo']).toEqual({
        section: 'mgmt-sec-storage',
        pane: 'mgmt-pane-storage-topo'
      });
    });

    it('launchShortcut normalizes legacy targetPane mgmt-pane-chassis to mgmt-pane-storage-topo', () => {
      const mockOpenMgmt = vi.fn();
      window.openManagementSection = mockOpenMgmt;

      const legacyShortcut = {
        id: 'storage-desktop-icon',
        targetSection: 'mgmt-sec-storage',
        targetPane: 'mgmt-pane-chassis'
      };

      launchShortcut(legacyShortcut);
      expect(mockOpenMgmt).toHaveBeenCalledWith('mgmt-sec-storage', 'mgmt-pane-storage-topo');
      delete window.openManagementSection;
    });

    it('launchShortcut calls openManagementSection when defined on window', () => {
      const mockOpenMgmt = vi.fn();
      window.openManagementSection = mockOpenMgmt;

      const shortcut = {
        id: 'storage-desktop-icon',
        targetSection: 'mgmt-sec-storage',
        targetPane: 'mgmt-pane-storage-topo'
      };

      launchShortcut(shortcut);
      expect(mockOpenMgmt).toHaveBeenCalledWith('mgmt-sec-storage', 'mgmt-pane-storage-topo');
      delete window.openManagementSection;
    });
  });

  describe('Issue 2: File Explorer Window Solid Background', () => {
    it('verifies style.css applies solid opaque background to file manager window and viewport', () => {
      const cssPath = path.resolve(__dirname, '../style.css');
      const cssContent = fs.readFileSync(cssPath, 'utf8');

      expect(cssContent).toContain('#file-manager-window.file-manager-window');
      expect(cssContent).toContain('rgba(15, 23, 42, 0.98) !important');
      expect(cssContent).toContain('.fm-content');
      expect(cssContent).toContain('.fm-viewport');
      expect(cssContent).toContain('.fm-list');
      expect(cssContent).toContain('background: #0b111a');
    });
  });

  describe('Issue 3: Stack Inspector Window Z-Index & Elevation', () => {
    it('verifies style.css includes #stack-inspector-overlay and #stack-picker-overlay in z-index 10030 rule', () => {
      const cssPath = path.resolve(__dirname, '../style.css');
      const cssContent = fs.readFileSync(cssPath, 'utf8');

      expect(cssContent).toContain('#stack-inspector-overlay');
      expect(cssContent).toContain('#stack-picker-overlay');
      expect(cssContent).toMatch(/#stack-inspector-overlay[\s\S]*?z-index:\s*10030\s*!important/);
      expect(cssContent).toContain('#stack-inspector-overlay .stack-inspector-window');
      expect(cssContent).toContain('background: #0d141e !important');
    });

    it('openStackModal properly removes display:none, removes window-minimized, adds open, and calls bringToFront', async () => {
      // Mock API call
      const { api } = await import('../api.js');
      vi.spyOn(api, 'get').mockResolvedValue({
        name: 'arr',
        origin: 'compose',
        status: 'running',
        running_count: 3,
        total_count: 3,
        compose_yaml: 'services:\n  sonarr:\n    image: sonarr\n',
        env_content: 'TZ=America/New_York\n',
        containers: []
      });

      await openStackModal('arr');

      const overlay = document.getElementById('stack-inspector-overlay');
      const win = document.getElementById('stack-inspector-window');

      expect(overlay).not.toBeNull();
      expect(win).not.toBeNull();

      expect(overlay.classList.contains('open')).toBe(true);
      expect(overlay.classList.contains('window-minimized')).toBe(false);
      expect(overlay.style.display).toBe('flex');

      expect(win.classList.contains('window-minimized')).toBe(false);
      expect(win.style.display).not.toBe('none');

      // Verify title is set
      expect(document.getElementById('stack-header-title').textContent).toBe('Stack: arr');
    });

    it('closeStackModal hides the overlay and win with important display none', async () => {
      const { api } = await import('../api.js');
      vi.spyOn(api, 'get').mockResolvedValue({
        name: 'arr',
        containers: []
      });

      await openStackModal('arr');
      closeStackModal();

      const overlay = document.getElementById('stack-inspector-overlay');
      const win = document.getElementById('stack-inspector-window');

      expect(overlay.classList.contains('open')).toBe(false);
      expect(overlay.style.display).toBe('none');
      expect(win.style.display).toBe('none');
    });

    it('bringToFront recognizes stack-inspector-window and stack-inspector-overlay as desktop apps', () => {
      const overlay = document.createElement('div');
      overlay.id = 'stack-inspector-overlay';
      const win = document.createElement('div');
      win.id = 'stack-inspector-window';
      win.className = 'smart-modal-window stack-inspector-window';
      overlay.appendChild(win);
      document.body.appendChild(overlay);

      bringToFront(win);

      // It should not be demoted to standalone modal z-index 9100
      expect(parseInt(win.style.zIndex || '0', 10)).toBeGreaterThan(1000);
      expect(parseInt(win.style.zIndex || '0', 10)).toBeLessThan(5000);
      expect(overlay.style.zIndex).toBe(win.style.zIndex);

      overlay.remove();
    });
  });
});
