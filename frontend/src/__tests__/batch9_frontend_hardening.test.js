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
    it('protects modal z-indices and maintains --z-modal layer', () => {
      const modal = document.createElement('div');
      modal.className = 'smart-modal-window';
      document.body.appendChild(modal);

      bringToFront(modal);
      expect(modal.style.zIndex).toBe('var(--z-modal, 9100)');
    });
  });
});
