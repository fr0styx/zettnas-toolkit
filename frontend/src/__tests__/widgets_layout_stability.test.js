import { describe, it, expect, beforeEach } from 'vitest';
import { applyWidgetConfig, saveWidgetConfig } from '../components/widgets.js';

describe('Desktop Widgets Layout Stability & Positioning', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="desktop-widgets-container" class="pos-top-right glass-standard scale-normal">
        <div class="desktop-widget" id="widget-clock"></div>
        <div class="desktop-widget" id="widget-weather"></div>
        <div class="desktop-widget" id="widget-calendar" style="display: none;"></div>
        <div class="desktop-widget" id="widget-system"></div>
        <div class="desktop-widget" id="widget-network"></div>
        <div class="desktop-widget" id="widget-storage"></div>
        <div class="desktop-widget" id="widget-uptime" style="display: none;"></div>
      </div>
    `;
  });

  it('maintains default DOM order without thrashing child nodes if order matches', () => {
    const container = document.getElementById('desktop-widgets-container');
    const firstChildBefore = container.children[0];
    
    applyWidgetConfig();

    // The first child should still be the exact same DOM node (no unnecessary re-append)
    expect(container.children[0]).toBe(firstChildBefore);
    expect(container.children[0].id).toBe('widget-clock');
    expect(container.children[1].id).toBe('widget-weather');
    expect(container.children[2].id).toBe('widget-calendar');
    expect(container.children[3].id).toBe('widget-system');
  });

  it('updates position classes correctly without leaving obsolete classes', () => {
    const container = document.getElementById('desktop-widgets-container');
    
    saveWidgetConfig({ position: 'pos-top-left', scale: 'scale-compact', opacity: 'glass-subtle' });

    expect(container.classList.contains('pos-top-left')).toBe(true);
    expect(container.classList.contains('pos-top-right')).toBe(false);
    expect(container.classList.contains('scale-compact')).toBe(true);
    expect(container.classList.contains('glass-subtle')).toBe(true);
  });

  it('reorders DOM nodes only when custom order is specified', () => {
    const container = document.getElementById('desktop-widgets-container');
    
    saveWidgetConfig({
      order: ['system', 'storage', 'clock', 'weather', 'calendar', 'network', 'uptime']
    });

    expect(container.children[0].id).toBe('widget-system');
    expect(container.children[1].id).toBe('widget-storage');
    expect(container.children[2].id).toBe('widget-clock');
  });
});
