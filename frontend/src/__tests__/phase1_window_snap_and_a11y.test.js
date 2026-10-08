import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getSnapGeometry,
  evaluateSnapZone,
  applyWindowSnap,
  initSnapAssistFlyout,
  NAVBAR_OFFSET,
  DOCK_MARGIN
} from '../components/dock.js';
import { initA11yAnnouncer, announceA11y, enhanceInteractiveElements } from '../a11y.js';

describe('Phase 1: 8-Zone Aero Snap Geometry Engine', () => {
  beforeEach(() => {
    window.innerWidth = 1200;
    window.innerHeight = 800;
  });

  it('calculates pixel-perfect geometry for all 7 snap zones', () => {
    const zones = ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'left', 'right', 'maximize'];
    const availH = 800 - NAVBAR_OFFSET - DOCK_MARGIN; // 800 - 48 - 76 = 676
    const halfW = Math.round((1200 - 16) / 2); // 592
    const halfH = Math.round((availH - 8) / 2); // 334

    zones.forEach((zone) => {
      const geom = getSnapGeometry(zone);
      expect(geom).not.toBeNull();
      expect(geom.top).toBeGreaterThanOrEqual(NAVBAR_OFFSET);
      expect(geom.left).toBeGreaterThanOrEqual(8);
      expect(geom.label).toBeTruthy();
    });

    const topLeft = getSnapGeometry('top-left');
    expect(topLeft.left).toBe(8);
    expect(topLeft.top).toBe(NAVBAR_OFFSET);
    expect(topLeft.width).toBe(halfW);
    expect(topLeft.height).toBe(halfH);

    const topRight = getSnapGeometry('top-right');
    expect(topRight.left).toBe(8 + halfW + 8);
    expect(topRight.top).toBe(NAVBAR_OFFSET);
    expect(topRight.width).toBe(halfW);
    expect(topRight.height).toBe(halfH);

    const leftHalf = getSnapGeometry('left');
    expect(leftHalf.left).toBe(8);
    expect(leftHalf.top).toBe(NAVBAR_OFFSET);
    expect(leftHalf.width).toBe(halfW);
    expect(leftHalf.height).toBe(availH);

    const max = getSnapGeometry('maximize');
    expect(max.left).toBe(8);
    expect(max.top).toBe(NAVBAR_OFFSET);
    expect(max.width).toBe(1200 - 16);
    expect(max.height).toBe(availH);
  });

  it('evaluates drag coordinates against 8-zone thresholds', () => {
    // Top-left corner
    expect(evaluateSnapZone(15, 60)).toBe('top-left');
    // Top-right corner
    expect(evaluateSnapZone(1185, 60)).toBe('top-right');
    // Bottom-left corner
    expect(evaluateSnapZone(15, 710)).toBe('bottom-left');
    // Bottom-right corner
    expect(evaluateSnapZone(1185, 710)).toBe('bottom-right');

    // Left edge
    expect(evaluateSnapZone(10, 300)).toBe('left');
    // Right edge
    expect(evaluateSnapZone(1190, 300)).toBe('right');
    // Top edge (Maximize)
    expect(evaluateSnapZone(500, 15)).toBe('maximize');

    // Center area (no snap)
    expect(evaluateSnapZone(600, 400)).toBeNull();
  });

  it('applies snap coordinates to window element and saves bounds', () => {
    const win = document.createElement('div');
    win.id = 'test-window';
    win.style.width = '500px';
    win.style.height = '400px';
    document.body.appendChild(win);

    applyWindowSnap(win, 'left', 'test-window');

    expect(win.dataset.snapped).toBe('left');
    expect(win.style.position).toBe('fixed');
    expect(win.style.left).toBe('8px');
    expect(win.style.top).toBe(`${NAVBAR_OFFSET}px`);

    const savedBounds = JSON.parse(localStorage.getItem('zettnas_window_bounds_v2') || '{}');
    expect(savedBounds['test-window']).toBeDefined();
    expect(savedBounds['test-window'].snapped).toBe('left');

    win.remove();
  });
});

describe('Phase 1: Snap Assist Flyout & WCAG 2.2 AA A11y', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('creates snap assist flyout with interactive template slots', () => {
    initSnapAssistFlyout();
    const flyout = document.getElementById('snap-assist-flyout');
    expect(flyout).not.toBeNull();
    expect(flyout.getAttribute('role')).toBe('dialog');

    const slots = flyout.querySelectorAll('.snap-slot');
    expect(slots.length).toBe(6); // 2 halves + 4 quarters
  });

  it('initializes a11y live announcer and announces state changes', async () => {
    initA11yAnnouncer();
    const announcer = document.getElementById('a11y-live-announcer');
    expect(announcer).not.toBeNull();
    expect(announcer.getAttribute('aria-live')).toBe('polite');

    announceA11y('Window snapped to Left Half');
    await new Promise((r) => setTimeout(r, 40));
    expect(announcer.textContent).toBe('Window snapped to Left Half');
  });

  it('enhances .win-btn and .snap-slot elements with keyboard access attributes', () => {
    const container = document.createElement('div');
    container.innerHTML = `
      <div class="snap-slot" data-snap="left" data-title="Snap Left"></div>
      <div class="win-btn max-btn" data-title="Maximize"></div>
    `;
    document.body.appendChild(container);

    enhanceInteractiveElements(container);

    const slot = container.querySelector('.snap-slot');
    const winBtn = container.querySelector('.win-btn');

    expect(slot.getAttribute('role')).toBe('button');
    expect(slot.getAttribute('tabindex')).toBe('0');
    expect(slot.getAttribute('aria-label')).toBe('Snap Left');

    expect(winBtn.getAttribute('role')).toBe('button');
    expect(winBtn.getAttribute('tabindex')).toBe('0');
  });
});
