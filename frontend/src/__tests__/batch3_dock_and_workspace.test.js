import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  applyDockSettings,
  getDockSettings,
  initDockSettingsControls,
  initParabolicDockMagnification,
  getSnapGeometry,
  showDockToast,
  NAVBAR_OFFSET,
  DOCK_MARGIN
} from '../components/dock.js';

describe('Batch 3: Dock Magnification, Spatial Placement & Workspace Insets', () => {
  let containerEl;
  let dockEl;

  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="os-dock-container" class="os-dock-container dock-pos-bottom">
        <div id="os-dock" class="os-dock active">
          <button class="dock-item" data-window-id="home" style="width: 48px; height: 48px;"></button>
          <button class="dock-item" data-window-id="spotlight" style="width: 48px; height: 48px;"></button>
          <button class="dock-item" data-window-id="mgmt" style="width: 48px; height: 48px;"></button>
          <button class="dock-item" data-window-id="notif" style="width: 48px; height: 48px;"></button>
        </div>
      </div>

      <div id="mgmt-pane-dock">
        <div class="dock-position-selector">
          <button type="button" class="btn-pill-toggle dock-pos-btn active" data-pos="bottom">Bottom (Default)</button>
          <button type="button" class="btn-pill-toggle dock-pos-btn" data-pos="left">Left (Widescreen)</button>
          <button type="button" class="btn-pill-toggle dock-pos-btn" data-pos="top">Top (Status Bar)</button>
        </div>

        <div class="dock-size-selector">
          <button type="button" class="btn-pill-toggle dock-size-btn" data-size="small">Small</button>
          <button type="button" class="btn-pill-toggle dock-size-btn active" data-size="medium">Medium</button>
          <button type="button" class="btn-pill-toggle dock-size-btn" data-size="large">Large</button>
        </div>

        <input type="checkbox" id="dock-magnification-toggle" checked>
        <input type="range" id="dock-magnification-slider" min="1.1" max="1.8" step="0.05" value="1.45">
        <span id="dock-magnification-val">1.45x</span>

        <input type="checkbox" id="dock-autohide-toggle">
        <button id="dock-reset-btn">↺ Reset Dock Defaults</button>
      </div>

      <div class="desktop-icons-container"></div>
      <div id="desktop-widgets-container" class="pos-top-right"></div>
    `;

    containerEl = document.getElementById('os-dock-container');
    dockEl = document.getElementById('os-dock');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('applyDockSettings updates CSS variables, classes, and workspace insets for bottom dock', () => {
    applyDockSettings('bottom', true, 1.45, 'medium', false, true);

    const root = document.documentElement;
    expect(root.style.getPropertyValue('--dock-position')).toBe('bottom');
    expect(root.style.getPropertyValue('--dock-height')).toBe('52px');
    expect(root.style.getPropertyValue('--dock-icon-size')).toBe('48px');
    expect(root.style.getPropertyValue('--workspace-inset-bottom')).toBe('calc(52px + 16px)');
    expect(root.style.getPropertyValue('--workspace-inset-left')).toBe('0px');
    expect(root.style.getPropertyValue('--workspace-inset-top')).toBe('0px');

    expect(containerEl.classList.contains('dock-pos-bottom')).toBe(true);
    expect(containerEl.classList.contains('dock-pos-left')).toBe(false);
    expect(dockEl.classList.contains('dock-size-medium')).toBe(true);
    expect(dockEl.classList.contains('dock-magnify-enabled')).toBe(true);

    expect(localStorage.getItem('zettnas_dock_position')).toBe('bottom');
    expect(localStorage.getItem('zettnas_dock_magnification')).toBe('true');
    expect(localStorage.getItem('zettnas_dock_scale')).toBe('1.45');
    expect(localStorage.getItem('zettnas_dock_size')).toBe('medium');
    expect(localStorage.getItem('zettnas_dock_autohide')).toBe('false');
  });

  it('applyDockSettings updates workspace insets and classes for left and top dock positions', () => {
    // Left widescreen dock
    applyDockSettings('left', true, 1.5, 'large', false, true);

    const root = document.documentElement;
    expect(root.style.getPropertyValue('--dock-position')).toBe('left');
    expect(root.style.getPropertyValue('--dock-height')).toBe('64px');
    expect(root.style.getPropertyValue('--dock-icon-size')).toBe('60px');
    expect(root.style.getPropertyValue('--workspace-inset-bottom')).toBe('0px');
    expect(root.style.getPropertyValue('--workspace-inset-left')).toBe('calc(64px + 16px)');
    expect(root.style.getPropertyValue('--workspace-inset-top')).toBe('0px');

    expect(containerEl.classList.contains('dock-pos-left')).toBe(true);
    expect(dockEl.classList.contains('dock-size-large')).toBe(true);

    // Top status bar dock
    applyDockSettings('top', false, 1.2, 'small', true, true);

    expect(root.style.getPropertyValue('--dock-position')).toBe('top');
    expect(root.style.getPropertyValue('--dock-height')).toBe('44px');
    expect(root.style.getPropertyValue('--dock-icon-size')).toBe('42px');
    // When autohide is true, insets are zero
    expect(root.style.getPropertyValue('--workspace-inset-top')).toBe('0px');
    expect(containerEl.classList.contains('dock-pos-top')).toBe(true);
    expect(containerEl.classList.contains('dock-autohide')).toBe(true);
    expect(dockEl.classList.contains('dock-size-small')).toBe(true);
    expect(dockEl.classList.contains('dock-magnify-enabled')).toBe(false);
  });

  it('initDockSettingsControls reads persisted settings and updates control elements', () => {
    localStorage.setItem('zettnas_dock_position', 'left');
    localStorage.setItem('zettnas_dock_magnification', 'true');
    localStorage.setItem('zettnas_dock_scale', '1.6');
    localStorage.setItem('zettnas_dock_size', 'large');
    localStorage.setItem('zettnas_dock_autohide', 'true');

    initDockSettingsControls();

    const leftBtn = document.querySelector('.dock-pos-btn[data-pos="left"]');
    const largeBtn = document.querySelector('.dock-size-btn[data-size="large"]');
    const magToggle = document.getElementById('dock-magnification-toggle');
    const magSlider = document.getElementById('dock-magnification-slider');
    const magVal = document.getElementById('dock-magnification-val');
    const autohideToggle = document.getElementById('dock-autohide-toggle');

    expect(leftBtn.classList.contains('active')).toBe(true);
    expect(leftBtn.getAttribute('aria-checked')).toBe('true');
    expect(largeBtn.classList.contains('active')).toBe(true);
    expect(magToggle.checked).toBe(true);
    expect(magSlider.value).toBe('1.6');
    expect(magVal.textContent).toBe('1.60x');
    expect(autohideToggle.checked).toBe(true);
  });

  it('initDockSettingsControls binds user interactions and supports reset to defaults', () => {
    initDockSettingsControls();

    const topBtn = document.querySelector('.dock-pos-btn[data-pos="top"]');
    const smallBtn = document.querySelector('.dock-size-btn[data-size="small"]');
    const magToggle = document.getElementById('dock-magnification-toggle');
    const magSlider = document.getElementById('dock-magnification-slider');
    const autohideToggle = document.getElementById('dock-autohide-toggle');
    const resetBtn = document.getElementById('dock-reset-btn');

    // Click Top position
    topBtn.click();
    expect(getDockSettings().position).toBe('top');
    expect(localStorage.getItem('zettnas_dock_position')).toBe('top');

    // Click Small size
    smallBtn.click();
    expect(getDockSettings().size).toBe('small');
    expect(localStorage.getItem('zettnas_dock_size')).toBe('small');

    // Toggle magnification off
    magToggle.checked = false;
    magToggle.dispatchEvent(new Event('change'));
    expect(getDockSettings().magnification).toBe(false);
    expect(dockEl.classList.contains('dock-magnify-enabled')).toBe(false);

    // Adjust magnification slider
    magSlider.value = '1.75';
    magSlider.dispatchEvent(new Event('input'));
    expect(document.getElementById('dock-magnification-val').textContent).toBe('1.75x');
    magSlider.dispatchEvent(new Event('change'));
    expect(getDockSettings().scale).toBe(1.75);

    // Toggle autohide on
    autohideToggle.checked = true;
    autohideToggle.dispatchEvent(new Event('change'));
    expect(getDockSettings().autohide).toBe(true);
    expect(containerEl.classList.contains('dock-autohide')).toBe(true);

    // Click reset to defaults
    resetBtn.click();
    const current = getDockSettings();
    expect(current.position).toBe('bottom');
    expect(current.magnification).toBe(true);
    expect(current.scale).toBe(1.45);
    expect(current.size).toBe('medium');
    expect(current.autohide).toBe(false);
  });

  it('initParabolicDockMagnification computes smooth cosine magnification curve on pointermove', () => {
    applyDockSettings('bottom', true, 1.45, 'medium', false, false);
    initParabolicDockMagnification(dockEl);

    const items = dockEl.querySelectorAll('.dock-item');
    items.forEach((item, index) => {
      // Mock getBoundingClientRect: 48px wide items spaced every 60px
      vi.spyOn(item, 'getBoundingClientRect').mockReturnValue({
        left: 100 + index * 60,
        right: 148 + index * 60,
        top: 800,
        bottom: 848,
        width: 48,
        height: 48
      });
    });

    // Move pointer right over item 1 center (left: 160, center: 184)
    dockEl.dispatchEvent(new MouseEvent('pointermove', {
      clientX: 184,
      clientY: 824
    }));

    // Item 1 should have maximum scale ~1.45
    const item1Scale = parseFloat(items[1].style.getPropertyValue('--dock-item-scale'));
    expect(item1Scale).toBeGreaterThanOrEqual(1.44);

    // Item 0 is 60px away (< 130px radius), so it should have intermediate scale > 1 and < 1.45
    const item0Scale = parseFloat(items[0].style.getPropertyValue('--dock-item-scale'));
    expect(item0Scale).toBeGreaterThan(1.0);
    expect(item0Scale).toBeLessThan(item1Scale);

    // On pointerleave, all items should reset scale to 1
    dockEl.dispatchEvent(new MouseEvent('pointerleave'));
    items.forEach((item) => {
      expect(item.style.getPropertyValue('--dock-item-scale')).toBe('1');
    });
  });

  it('getSnapGeometry adapts dynamically to dock position and autohide state', () => {
    // 1. Bottom Dock (Default)
    applyDockSettings('bottom', true, 1.45, 'medium', false, false);
    const snapBottom = getSnapGeometry('maximize');
    expect(snapBottom).not.toBeNull();
    expect(snapBottom.left).toBe(8);
    expect(snapBottom.top).toBe(NAVBAR_OFFSET);
    // availH = winH - NAVBAR_OFFSET - DOCK_MARGIN
    expect(snapBottom.height).toBe(window.innerHeight - NAVBAR_OFFSET - DOCK_MARGIN);

    // 2. Left Dock
    applyDockSettings('left', true, 1.45, 'medium', false, false);
    const snapLeft = getSnapGeometry('left');
    expect(snapLeft.left).toBeGreaterThan(8); // padded by dock width
    expect(snapLeft.top).toBe(NAVBAR_OFFSET);

    // 3. Autohide Dock gives full workspace height
    applyDockSettings('bottom', true, 1.45, 'medium', true, false);
    const snapAutohide = getSnapGeometry('maximize');
    expect(snapAutohide.height).toBe(window.innerHeight - NAVBAR_OFFSET - 16);
  });

  it('showDockToast positions toast appropriately for left and top dock layouts', () => {
    // Left dock
    applyDockSettings('left', true, 1.45, 'medium', false, false);
    showDockToast('Test Left Toast');
    const toastContainer = document.getElementById('global-toast-container');
    expect(toastContainer).not.toBeNull();
    expect(toastContainer.style.bottom).toBe('32px');

    // Top dock
    applyDockSettings('top', true, 1.45, 'medium', false, false);
    showDockToast('Test Top Toast');
    expect(toastContainer.style.top).toBeDefined();
  });
});
