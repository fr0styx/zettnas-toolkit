import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  initSpotlight,
  openSpotlight,
  closeSpotlight,
  toggleSpotlight,
  filterSpotlightResults,
  registerSpotlightItem,
} from '../components/spotlight.js';
import { initDesktopLasso, initDraggableDesktopIcons } from '../components/dock.js';

describe('Phase 4: Spotlight Universal Command Palette & Desktop Workspace', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="os-dock-container"><div id="os-dock"></div></div>
      <div id="desktop-icons-container">
        <div class="chassis-hero-box" id="management-desktop-icon" style="position:fixed; left:50px; top:50px; width:100px; height:100px;"></div>
        <div class="chassis-hero-box" id="fm-desktop-icon" style="position:fixed; left:200px; top:50px; width:100px; height:100px;"></div>
      </div>
      <div class="os-context-menu" id="desktop-ctx-menu" style="display:none;"></div>
    `;
    vi.restoreAllMocks();
  });

  it('initializes and toggles Spotlight command palette', () => {
    initSpotlight();
    const overlay = document.getElementById('spotlight-palette-overlay');
    const input = document.getElementById('spotlight-input');
    expect(overlay).toBeTruthy();
    expect(input).toBeTruthy();

    openSpotlight();
    expect(overlay.style.display).toBe('flex');

    closeSpotlight();
    expect(overlay.style.display).toBe('none');

    toggleSpotlight();
    expect(overlay.style.display).toBe('flex');
    closeSpotlight();
  });

  it('filters spotlight items by keyword, title, and prefix syntax', () => {
    initSpotlight();
    openSpotlight();

    filterSpotlightResults('quiet');
    const results = document.getElementById('spotlight-results');
    expect(results.textContent).toContain('Fan Mode: Quiet');

    filterSpotlightResults('>turbo');
    expect(results.textContent).toContain('Fan Mode: Performance');

    filterSpotlightResults('oled');
    expect(results.textContent).toContain('Theme: OLED Pure Black');
  });

  it('registers custom spotlight items and executes them', () => {
    initSpotlight();
    const customFn = vi.fn();
    registerSpotlightItem({
      id: 'custom-backup-run',
      title: 'Run Cloud Backup',
      subtitle: 'Trigger offsite snapshot sync',
      category: 'action',
      keywords: ['backup', 'sync'],
      run: customFn,
    });

    openSpotlight();
    filterSpotlightResults('Cloud Backup');
    const itemEl = document.querySelector('.spotlight-result-item[data-idx="0"]');
    expect(itemEl).toBeTruthy();
    itemEl.click();
    expect(customFn).toHaveBeenCalled();
  });

  it('initializes desktop lasso marquee selection engine', () => {
    initDesktopLasso();
    // Simulate pointerdown on empty wallpaper area
    const downEvt = new PointerEvent('pointerdown', {
      bubbles: true,
      cancelable: true,
      clientX: 20,
      clientY: 20,
      button: 0,
    });
    document.body.dispatchEvent(downEvt);

    const lasso = document.getElementById('desktop-lasso-rect');
    expect(lasso).toBeTruthy();

    // Move pointer over management icon (left: 50, top: 50)
    const moveEvt = new PointerEvent('pointermove', {
      bubbles: true,
      clientX: 120,
      clientY: 120,
    });
    document.dispatchEvent(moveEvt);

    const upEvt = new PointerEvent('pointerup', { bubbles: true });
    document.dispatchEvent(upEvt);

    expect(document.getElementById('desktop-lasso-rect')).toBeNull();
  });

  it('desktop context menu contains Command Palette, Mission Control, and Refresh', () => {
    initDraggableDesktopIcons();
    const evt = new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      pageX: 300,
      pageY: 300,
    });
    document.body.dispatchEvent(evt);

    const menu = document.getElementById('desktop-ctx-menu');
    expect(menu.style.display).toBe('block');
    expect(menu.querySelector('#ctx-spotlight')).toBeTruthy();
    expect(menu.querySelector('#ctx-open-mc')).toBeTruthy();
    expect(menu.querySelector('#ctx-open-fm')).toBeTruthy();
    expect(menu.querySelector('#ctx-refresh-telemetry')).toBeTruthy();
  });
});
