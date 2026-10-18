import { describe, it, expect, beforeEach } from 'vitest';
import { applyWidgetConfig, saveWidgetConfig, loadWidgetConfig } from '../components/widgets.js';

describe('Desktop Widgets Layout Stability & Positioning', () => {
  beforeEach(() => {
    localStorage.clear();
    loadWidgetConfig();
    document.body.innerHTML = `
      <div id="desktop-widgets-container" class="pos-top-right glass-standard scale-normal">
        <div class="desktop-widget" id="widget-clock"></div>
        <div class="desktop-widget" id="widget-ai-accelerator"></div>
        <div class="desktop-widget" id="widget-weather"></div>
        <div class="desktop-widget" id="widget-calendar" style="display: none;"></div>
        <div class="desktop-widget" id="widget-system"></div>
        <div class="desktop-widget" id="widget-network"></div>
        <div class="desktop-widget" id="widget-storage"></div>
        <div class="desktop-widget" id="widget-uptime" style="display: none;"></div>
        <div class="desktop-widget" id="widget-drive-temp"></div>
        <div class="desktop-widget" id="widget-net-dial"></div>
        <div class="desktop-widget" id="widget-ups-gauge"></div>
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
    expect(container.children[1].id).toBe('widget-ai-accelerator');
    expect(container.children[2].id).toBe('widget-weather');
    expect(container.children[3].id).toBe('widget-calendar');
    expect(container.children[4].id).toBe('widget-system');
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
      order: ['system', 'storage', 'clock', 'ai_accelerator', 'weather', 'calendar', 'network', 'uptime', 'drive_temp', 'net_dial', 'ups_gauge']
    });

    expect(container.children[0].id).toBe('widget-system');
    expect(container.children[1].id).toBe('widget-storage');
    expect(container.children[2].id).toBe('widget-clock');
  });

  it('supports toggling visibility for all 11 desktop widgets including Drive Thermals, Network Dial, and UPS Power', () => {
    const wDriveTemp = document.getElementById('widget-drive-temp');
    const wNetDial = document.getElementById('widget-net-dial');
    const wUpsGauge = document.getElementById('widget-ups-gauge');

    saveWidgetConfig({
      widgets: {
        drive_temp: true,
        net_dial: true,
        ups_gauge: true,
      }
    });

    expect(wDriveTemp.style.display).toBe('block');
    expect(wNetDial.style.display).toBe('block');
    expect(wUpsGauge.style.display).toBe('block');

    saveWidgetConfig({
      widgets: {
        drive_temp: false,
        net_dial: false,
        ups_gauge: false,
      }
    });

    expect(wDriveTemp.style.display).toBe('none');
    expect(wNetDial.style.display).toBe('none');
    expect(wUpsGauge.style.display).toBe('none');
  });

  it('updates position classes cleanly across pos-bottom-right and pos-bottom-left', () => {
    const container = document.getElementById('desktop-widgets-container');

    saveWidgetConfig({ position: 'pos-bottom-right' });
    expect(container.classList.contains('pos-bottom-right')).toBe(true);
    expect(container.classList.contains('pos-top-right')).toBe(false);

    saveWidgetConfig({ position: 'pos-bottom-left' });
    expect(container.classList.contains('pos-bottom-left')).toBe(true);
    expect(container.classList.contains('pos-bottom-right')).toBe(false);
  });
});
