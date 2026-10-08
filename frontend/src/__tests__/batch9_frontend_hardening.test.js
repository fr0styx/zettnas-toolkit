import { describe, it, expect, beforeEach, vi } from 'vitest';
import { enhanceInteractiveElements } from '../a11y.js';
import { ZettEventBus } from '../event-bus.js';
import { applyTheme } from '../components/dashboard.js';
import { bringToFront, activeWindowZIndex } from '../components/dock.js';

describe('Batch 9: Frontend Hardening & Architecture', () => {
  beforeEach(() => {
    document.body.className = '';
  });

  describe('A11y Engine (WCAG 2.1 AA Compliance)', () => {
    it('does not assign raw CSS class names to aria-label', () => {
      const container = document.createElement('div');
      container.innerHTML = `
        <div class="mgmt-card interactive mb-4 os-dock-item"></div>
        <div class="card with-data" data-title="System Health"></div>
        <div class="disk with-action" data-action="eject-disk"></div>
      `;
      document.body.appendChild(container);

      enhanceInteractiveElements(container);

      const emptyClassCard = container.querySelector('.mgmt-card');
      const dataCard = container.querySelector('.with-data');
      const actionDisk = container.querySelector('.with-action');

      // Crucial: Must NEVER equal className!
      expect(emptyClassCard.getAttribute('aria-label')).not.toBe('mgmt-card interactive mb-4 os-dock-item');
      expect(emptyClassCard.getAttribute('aria-hidden')).toBe('true');

      expect(dataCard.getAttribute('aria-label')).toBe('System Health');
      expect(actionDisk.getAttribute('aria-label')).toBe('eject disk');
    });
  });

  describe('Scoped Event Bus Lifecycle', () => {
    it('creates a scope and bulk-unsubscribes on destroy()', () => {
      const scope = ZettEventBus.createScope();
      const fn1 = vi.fn();
      const fn2 = vi.fn();

      scope.on('test:evt1', fn1);
      scope.on('test:evt2', fn2);

      ZettEventBus.emit('test:evt1', { val: 1 });
      ZettEventBus.emit('test:evt2', { val: 2 });

      expect(fn1).toHaveBeenCalledWith({ val: 1 }, expect.anything());
      expect(fn2).toHaveBeenCalledWith({ val: 2 }, expect.anything());

      // Destroy scope
      scope.destroy();

      ZettEventBus.emit('test:evt1', { val: 99 });
      ZettEventBus.emit('test:evt2', { val: 100 });

      // Handlers must NOT be called again
      expect(fn1).toHaveBeenCalledTimes(1);
      expect(fn2).toHaveBeenCalledTimes(1);
    });
  });

  describe('Multi-Theme Switching Engine', () => {
    it('correctly toggles amber, emerald, light, and yak themes', () => {
      applyTheme('amber');
      expect(document.body.classList.contains('theme-amber')).toBe(true);
      expect(document.body.classList.contains('theme-yak')).toBe(false);

      applyTheme('emerald');
      expect(document.body.classList.contains('theme-emerald')).toBe(true);
      expect(document.body.classList.contains('theme-amber')).toBe(false);

      applyTheme('light');
      expect(document.body.classList.contains('theme-light')).toBe(true);
      expect(document.body.classList.contains('theme-emerald')).toBe(false);

      applyTheme('yak');
      expect(document.body.classList.contains('theme-yak')).toBe(true);
      expect(document.body.classList.contains('theme-light')).toBe(false);
    });
  });

  describe('Window Stacking & Modal Protection', () => {
    it('protects modal z-indices and maintains --z-modal layer for true modals', () => {
      const modal = document.createElement('div');
      modal.className = 'smart-modal-window';
      document.body.appendChild(modal);

      bringToFront(modal);
      expect(modal.style.zIndex).toBe('var(--z-modal, 9100)');
    });

    it('assigns dynamic window stacking to Console window and synchronizes its overlay', () => {
      const overlay = document.createElement('div');
      overlay.id = 'console-modal-overlay';
      overlay.className = 'smart-modal-backdrop';

      const win = document.createElement('div');
      win.id = 'console-window';
      win.className = 'chassis-front-panel';
      overlay.appendChild(win);
      document.body.appendChild(overlay);

      bringToFront(win);
      const consoleZ = parseInt(win.style.zIndex, 10);
      expect(consoleZ).toBeGreaterThanOrEqual(1000);
      expect(consoleZ).toBeLessThan(4900);
      expect(overlay.style.zIndex).toBe(win.style.zIndex);
    });

    it('allows File Explorer to stack above Console and Console to stack above File Explorer', () => {
      const consoleOverlay = document.createElement('div');
      consoleOverlay.id = 'console-modal-overlay';
      const consoleWin = document.createElement('div');
      consoleWin.id = 'console-window';
      consoleOverlay.appendChild(consoleWin);
      document.body.appendChild(consoleOverlay);

      const fmWin = document.createElement('div');
      fmWin.id = 'file-manager-window';
      fmWin.className = 'os-window file-manager-window';
      document.body.appendChild(fmWin);

      // Focus console
      bringToFront(consoleWin);
      const z1 = parseInt(consoleWin.style.zIndex, 10);

      // Focus file explorer -> must be in front of console
      bringToFront(fmWin);
      const z2 = parseInt(fmWin.style.zIndex, 10);
      expect(z2).toBeGreaterThan(z1);

      // Focus console again -> must be in front of file explorer
      bringToFront(consoleWin);
      const z3 = parseInt(consoleWin.style.zIndex, 10);
      expect(z3).toBeGreaterThan(z2);
      expect(consoleOverlay.style.zIndex).toBe(z3.toString());
    });

    it('ensures all desktop windows remain strictly below the Hardware Settings drawer layer (7100)', () => {
      const consoleWin = document.createElement('div');
      consoleWin.id = 'console-window';
      document.body.appendChild(consoleWin);

      const mgmtWin = document.createElement('div');
      mgmtWin.id = 'management-window';
      mgmtWin.className = 'smart-modal-window management-window';
      const mgmtOverlay = document.createElement('div');
      mgmtOverlay.id = 'management-modal-overlay';
      mgmtOverlay.appendChild(mgmtWin);
      document.body.appendChild(mgmtOverlay);

      bringToFront(consoleWin);
      bringToFront(mgmtWin);

      const DRAWER_Z = 7100;
      expect(parseInt(consoleWin.style.zIndex, 10)).toBeLessThan(DRAWER_Z);
      expect(parseInt(mgmtWin.style.zIndex, 10)).toBeLessThan(DRAWER_Z);
      expect(parseInt(mgmtOverlay.style.zIndex, 10)).toBeLessThan(DRAWER_Z);
    });
  });
});
