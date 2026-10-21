import { describe, it, expect, beforeEach, vi } from 'vitest';
import { applyWidgetConfig, initWidgets, setupWidgetSettingsEvents } from '../components/widgets.js';

describe('Desktop Widgets Interactive Navigation & Deep Linking', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="desktop-widgets-container" class="pos-top-right glass-standard scale-normal">
        <div class="desktop-widget" id="widget-clock"></div>
        <div class="desktop-widget" id="widget-ai-accelerator"></div>
        <div class="desktop-widget" id="widget-weather">
          <div class="widget-header">
            <span class="widget-title">Local Weather</span>
            <span class="widget-badge" id="w-weather-city">New York</span>
          </div>
          <span id="w-weather-temp">57°F</span>
          <span id="w-weather-desc">Clear Sky</span>
        </div>
        <div class="desktop-widget" id="widget-calendar" style="display: none;"></div>
        <div class="desktop-widget" id="widget-system">
          <span id="w-cpu-val">12%</span>
        </div>
        <div class="desktop-widget" id="widget-network">
          <div class="widget-header">
            <span class="widget-title">Network IO</span>
            <span class="widget-badge" id="w-net-iface">bond0</span>
          </div>
          <span id="w-net-rx">1.2 MB/s</span>
          <span id="w-net-tx">450 KB/s</span>
        </div>
        <div class="desktop-widget" id="widget-storage">
          <div class="widget-header">
            <span class="widget-title">Storage Pool</span>
            <span class="widget-badge" id="w-storage-status">ONLINE</span>
          </div>
          <span id="w-storage-val">15 TB / 23 TB</span>
        </div>
        <div class="desktop-widget" id="widget-uptime" style="display: none;"></div>
        <div class="desktop-widget" id="widget-drive-temp"></div>
        <div class="desktop-widget" id="widget-net-dial"></div>
        <div class="desktop-widget" id="widget-ups-gauge"></div>
      </div>
      <input type="text" id="widget-weather-city-input" />
      <select id="widget-weather-unit-select">
        <option value="c">Celsius</option>
        <option value="f" selected>Fahrenheit</option>
      </select>
    `;

    window.openManagementWindow = vi.fn();
  });

  it('makes Network IO widget clickable and routes to mgmt-sec-network / mgmt-pane-network', () => {
    applyWidgetConfig();

    const wNetwork = document.getElementById('widget-network');
    expect(wNetwork).toBeTruthy();
    expect(wNetwork.style.cursor).toBe('pointer');
    expect(wNetwork.getAttribute('role')).toBe('button');
    expect(wNetwork.getAttribute('tabindex')).toBe('0');

    wNetwork.click();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-network', 'mgmt-pane-network');
  });

  it('supports keyboard navigation (Enter and Space) on Network IO widget', () => {
    applyWidgetConfig();

    const wNetwork = document.getElementById('widget-network');
    wNetwork.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-network', 'mgmt-pane-network');

    window.openManagementWindow.mockClear();
    wNetwork.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-network', 'mgmt-pane-network');
  });

  it('makes Storage Pool widget clickable and routes to mgmt-sec-storage / mgmt-pane-storage-topo', () => {
    applyWidgetConfig();

    const wStorage = document.getElementById('widget-storage');
    expect(wStorage).toBeTruthy();
    expect(wStorage.style.cursor).toBe('pointer');
    expect(wStorage.getAttribute('role')).toBe('button');
    expect(wStorage.getAttribute('tabindex')).toBe('0');

    wStorage.click();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-storage', 'mgmt-pane-storage-topo');
  });

  it('supports keyboard navigation (Enter and Space) on Storage Pool widget', () => {
    applyWidgetConfig();

    const wStorage = document.getElementById('widget-storage');
    wStorage.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-storage', 'mgmt-pane-storage-topo');

    window.openManagementWindow.mockClear();
    wStorage.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-storage', 'mgmt-pane-storage-topo');
  });

  it('makes Local Weather widget clickable and routes to mgmt-sec-wallpaper / mgmt-pane-widgets', () => {
    applyWidgetConfig();

    const wWeather = document.getElementById('widget-weather');
    expect(wWeather).toBeTruthy();
    expect(wWeather.style.cursor).toBe('pointer');
    expect(wWeather.getAttribute('role')).toBe('button');
    expect(wWeather.getAttribute('tabindex')).toBe('0');

    wWeather.click();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-widgets');
  });

  it('supports keyboard navigation (Enter and Space) on Local Weather widget', () => {
    applyWidgetConfig();

    const wWeather = document.getElementById('widget-weather');
    wWeather.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-widgets');

    window.openManagementWindow.mockClear();
    wWeather.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-widgets');
  });

  it('stops propagation when clicking weather temp toggle to avoid opening Mission Control', () => {
    applyWidgetConfig();
    setupWidgetSettingsEvents();

    const wWeather = document.getElementById('widget-weather');
    const wTemp = document.getElementById('w-weather-temp');

    wTemp.click();
    // Clicking the temperature value toggles unit (°C/°F) and does NOT trigger the parent widget navigation
    expect(window.openManagementWindow).not.toHaveBeenCalled();

    // Clicking elsewhere on the weather widget does trigger navigation
    const wCity = document.getElementById('w-weather-city');
    wCity.click();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-widgets');
  });

  it('makes System Status widget clickable and routes to mgmt-sec-activity / mgmt-pane-metrics', () => {
    applyWidgetConfig();

    const wSystem = document.getElementById('widget-system');
    expect(wSystem).toBeTruthy();
    expect(wSystem.style.cursor).toBe('pointer');

    wSystem.click();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-activity', 'mgmt-pane-metrics');
  });
});
