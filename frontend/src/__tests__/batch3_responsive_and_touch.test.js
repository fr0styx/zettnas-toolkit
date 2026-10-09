import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { makeDraggable, DockManager } from '../components/dock.js';
import fs from 'fs';
import path from 'path';

describe('Batch 3: Responsive Layout Overhaul & Touch Navigation (<1024px & Mobile)', () => {
  let modalOverlay;
  let modalWindow;
  let modalHeader;

  beforeEach(() => {
    vi.useFakeTimers();
    document.body.className = '';
    document.body.innerHTML = `
      <div id="test-overlay" class="modal-overlay open">
        <div id="test-modal" class="smart-modal-window" style="position:fixed; left:50%; transform:translateX(-50%);">
          <div id="test-header" class="smart-modal-header" style="height:40px;">
            <span class="modal-title">Responsive Modal</span>
            <button class="close-btn modal-ctrl-btn">✕</button>
          </div>
          <div class="smart-modal-body">
            <table class="copy-history-table docker-table responsive-cards">
              <thead><tr><th>Name</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody id="test-tbody">
                <tr data-key="c1">
                  <td>Container A</td>
                  <td>Running</td>
                  <td class="docker-actions-cell"><button class="btn-container-act">⏹</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    modalOverlay = document.getElementById('test-overlay');
    modalWindow = document.getElementById('test-modal');
    modalHeader = document.getElementById('test-header');

    // Register with DockManager
    DockManager.windows = {};
    DockManager.register('test-modal', modalOverlay, '#i-chip', 'Test App', false);
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.className = '';
    document.body.innerHTML = '';
  });

  describe('Mobile Swipe-to-Dismiss Gesture Interaction', () => {
    it('triggers window dismissal when downward touch swipe exceeds the 70px threshold', () => {
      document.body.classList.add('mobile-mode');
      const minimizeSpy = vi.spyOn(DockManager, 'minimize');

      makeDraggable(modalWindow, modalHeader, 'test-modal');

      // 1. Pointer down on header at Y = 100
      const downEv = new PointerEvent('pointerdown', {
        clientX: 150,
        clientY: 100,
        button: 0,
        pointerId: 1,
        bubbles: true,
      });
      modalHeader.dispatchEvent(downEv);

      // 2. Drag downwards to Y = 210 (dy = 110px > 70px)
      const moveEv = new PointerEvent('pointermove', {
        clientX: 150,
        clientY: 210,
        pointerId: 1,
        bubbles: true,
      });
      window.dispatchEvent(moveEv);

      expect(modalWindow.style.transform).toContain('translateY(');

      // 3. Pointer up to release
      const upEv = new PointerEvent('pointerup', {
        clientX: 150,
        clientY: 210,
        pointerId: 1,
        bubbles: true,
      });
      window.dispatchEvent(upEv);

      // Fast-forward animation timer
      vi.advanceTimersByTime(250);

      expect(minimizeSpy).toHaveBeenCalledWith('test-modal');
    });

    it('snaps back to resting position without dismissing if downward swipe is below 70px threshold', () => {
      document.body.classList.add('mobile-mode');
      const minimizeSpy = vi.spyOn(DockManager, 'minimize');

      makeDraggable(modalWindow, modalHeader, 'test-modal');

      // 1. Pointer down on header at Y = 100
      const downEv = new PointerEvent('pointerdown', {
        clientX: 150,
        clientY: 100,
        button: 0,
        pointerId: 1,
        bubbles: true,
      });
      modalHeader.dispatchEvent(downEv);

      // 2. Drag downwards slightly to Y = 135 (dy = 35px < 70px)
      const moveEv = new PointerEvent('pointermove', {
        clientX: 150,
        clientY: 135,
        pointerId: 1,
        bubbles: true,
      });
      window.dispatchEvent(moveEv);

      // 3. Pointer up to release
      const upEv = new PointerEvent('pointerup', {
        clientX: 150,
        clientY: 135,
        pointerId: 1,
        bubbles: true,
      });
      window.dispatchEvent(upEv);

      // Fast-forward animation timer
      vi.advanceTimersByTime(250);

      expect(minimizeSpy).not.toHaveBeenCalled();
    });

    it('ignores clicks on buttons or control icons in the header so action clicks work cleanly', () => {
      document.body.classList.add('mobile-mode');
      const closeBtn = modalHeader.querySelector('.close-btn');
      let closeClicked = false;
      closeBtn.addEventListener('click', () => { closeClicked = true; });

      makeDraggable(modalWindow, modalHeader, 'test-modal');

      // Pointerdown on close button directly
      const downEv = new PointerEvent('pointerdown', {
        clientX: 200,
        clientY: 110,
        button: 0,
        pointerId: 1,
        bubbles: true,
      });
      closeBtn.dispatchEvent(downEv);

      // No drag transform applied to modal
      expect(modalWindow.style.transform).toBe('translateX(-50%)');
    });
  });

  describe('CSS Architecture & Responsive Rules Audit', () => {
    let cssContent;

    beforeEach(() => {
      const cssPath = path.resolve(__dirname, '../style.css');
      cssContent = fs.readFileSync(cssPath, 'utf8');
    });

    it('contains tablet media query (769px - 1024px) with collapsed 64px icon-only sidebar rail', () => {
      expect(cssContent).toContain('@media (min-width: 769px) and (max-width: 1024px)');
      expect(cssContent).toMatch(/width:\s*64px\s*!important/);
      expect(cssContent).toMatch(/\.mgmt-sidebar-text\s*\{\s*display:\s*none\s*!important/);
      expect(cssContent).toMatch(/grid-template-columns:\s*repeat\(2,\s*1fr\)\s*!important/);
    });

    it('contains mobile stacked card rules for docker and disk tables', () => {
      expect(cssContent).toMatch(/\.docker-table\s+thead[^{]*\{[^}]*display:\s*none\s*!important/);
      expect(cssContent).toMatch(/\.docker-table\s+tbody[^{]*\{[^}]*display:\s*flex\s*!important;\s*flex-direction:\s*column\s*!important/);
      expect(cssContent).toMatch(/\.docker-table\s+tbody\s+tr[^{]*\{[^}]*display:\s*flex\s*!important;\s*flex-direction:\s*column\s*!important/);
    });

    it('enforces 44px minimum hit targets for touch elements on mobile', () => {
      expect(cssContent).toMatch(/min-height:\s*44px\s*!important/);
      expect(cssContent).toMatch(/min-width:\s*44px\s*!important/);
      expect(cssContent).toMatch(/touch-action:\s*manipulation\s*!important/);
    });

    it('enforces zero horizontal overflow on mission control window and panes on mobile', () => {
      expect(cssContent).toMatch(/#management-modal-overlay\s+#management-window[^{]*\{[^}]*max-width:\s*100%\s*!important/);
      expect(cssContent).toMatch(/#management-modal-overlay\s+\.mgmt-content-pane[^{]*\{[^}]*overflow-x:\s*hidden\s*!important/);
    });
  });
});
