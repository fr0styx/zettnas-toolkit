/**
 * ZettNAS Toolkit - Main Frontend Entrypoint (v0.8.0)
 * Modular architecture orchestrating telemetry streaming, layout management, and desktop widgets.
 */
import './style.css';
import './lcd-direct.css';

import { ZettEventBus } from './event-bus.js';
import { auth, api } from './api.js';
import { state } from './state.js';
import { showToast, showConfirmToast } from './toast.js';
import './folder-browser.js';
import './modals.js';

import { initDockSystem, DockManager, makeDraggable, bringToFront } from './components/dock.js';
import { initAuth } from './components/auth.js';
import { applyStats, applyTheme, initDashboardClicks } from './components/dashboard.js';
import { initFanControl } from './components/fan-control.js';
import { initLedControl } from './components/led-control.js';
import { fetchDashboardLayout, fitMiniPreviewScale } from './components/mini-preview.js';
import { initWallpapers } from './components/wallpapers.js';
import { initEvents } from './components/events.js';
import { initSettings, openDrawer, closeDrawer } from './components/settings.js';
import { initMetricsChart, fetchAndRenderMetrics } from './components/metrics-chart.js';
import { initSetupWizard } from './components/setup-wizard.js';
import { initManagement } from './components/management.js';
import { initCommandPalette } from './components/command-palette.js';
import { initWidgets } from './components/widgets.js';
import { initFileManager } from './components/file-manager.js';
import { initI18n } from './i18n.js';

let _sseRetryCount = 0;
let _sse = null;

async function checkLcdStatus() {
  if (state.isLcdDirect) return;
  try {
    const data = await api.get('/api/lcd_status');
    const badge = document.getElementById('lcd-renderer-badge');
    if (badge) {
      if (!data.enabled) {
        badge.textContent = 'LCD: DISABLED';
        badge.className = 'lcd-status-badge lcd-status-disabled';
        badge.title = 'LCD direct output is disabled in configuration.';
      } else if (!data.fb_present) {
        badge.textContent = 'LCD: NO /dev/fb0';
        badge.className = 'lcd-status-badge lcd-status-offline';
        badge.title = 'No framebuffer device detected at /dev/fb0.';
      } else if (data.active) {
        badge.textContent = `LCD: ${data.fps} FPS ACTIVE`;
        badge.className = 'lcd-status-badge lcd-status-active';
        badge.title = `LCD direct output is actively streaming at ${data.fps} FPS.`;
      } else {
        badge.textContent = 'LCD: IDLE';
        badge.className = 'lcd-status-badge lcd-status-offline';
        badge.title = 'LCD renderer process is offline or initializing.';
      }
    }
  } catch (e) {
    console.warn('Failed to query LCD status', e);
  }
}

export async function tick() {
  try {
    const s = await api.get('/api/stats');
    applyStats(s);
  } catch (e) {
    console.warn('Polling stats failed', e);
  }
}

export function startSSE() {
  const token = auth.getToken();
  const url = token ? `/api/stats/stream?token=${encodeURIComponent(token)}` : '/api/stats/stream';
  _sse = new EventSource(url);

  _sse.onopen = () => {
    _sseRetryCount = 0;
    const streamBadge = document.getElementById('stream-status-badge');
    if (streamBadge) {
      streamBadge.textContent = 'LIVE SSE';
      streamBadge.className = 'header-badge active';
    }
  };

  _sse.onmessage = (e) => {
    try {
      const s = JSON.parse(e.data);
      applyStats(s);
    } catch (err) {
      console.error('Failed to parse SSE payload:', err);
    }
  };

  _sse.onerror = () => {
    _sseRetryCount++;
    if (_sse) _sse.close();
    const streamBadge = document.getElementById('stream-status-badge');
    if (streamBadge) {
      streamBadge.textContent = 'POLLING';
      streamBadge.className = 'header-badge warning';
    }
    const delay = Math.min(10000, 2000 * Math.pow(1.5, _sseRetryCount));
    setTimeout(startSSE, delay);
    tick();
  };
}

document.addEventListener('DOMContentLoaded', () => {
  if (window.location.search.includes('mode=lcd') || document.body.classList.contains('lcd-direct')) {
    state.isLcdDirect = true;
    document.body.classList.add('lcd-direct');
  }
  initI18n();
  initDockSystem();
  initAuth();
  initDashboardClicks();
  initFanControl();
  initLedControl();
  initWallpapers();
  initEvents();
  initSettings();
  initMetricsChart();
  initSetupWizard();
  initManagement();
  initCommandPalette();
  initWidgets();
  initFileManager();

  applyTheme(state.currentTheme);
  fetchDashboardLayout();

  tick();
  startSSE();

  checkLcdStatus();
  setInterval(checkLcdStatus, 10000);

  window.addEventListener('resize', fitMiniPreviewScale);

  // Prevent background drag/bounce from scrolling the page and losing the navbar on mobile
  document.addEventListener('touchmove', (e) => {
    const isMobile = document.body.classList.contains('mobile-mode') || window.innerWidth <= 768;
    if (!isMobile) return;

    // Allow scrolling only within designated scrollable containers
    const scrollable = e.target.closest(
      '.mgmt-content-pane, .fm-viewport, #console-window, .smart-modal-body, ' +
      '.smart-modal-window, .slide-drawer, #desktop-widgets-container, .os-dock, ' +
      'input, select, textarea, .mgmt-sidebar, .mgmt-inner-tabs, .drawer-tabs-nav, .smart-raw-pre'
    );
    if (!scrollable) {
      e.preventDefault();
    }
  }, { passive: false });
});
