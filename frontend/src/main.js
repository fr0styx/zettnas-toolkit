/**
 * ZettNAS Toolkit - Main Frontend Entrypoint (v0.8.0)
 * Modular architecture orchestrating telemetry streaming, layout management, and desktop widgets.
 */
import './style.css';
import './lcd-direct.css';
import './vm-console-direct.css';

import { initClientLogger } from './client-logger.js';
import { installDomActions } from './dom-actions.js';

installDomActions();
initClientLogger();

import { ZettEventBus } from './event-bus.js';
import { auth, api, setConfirmationHandler } from './api.js';
import { state } from './state.js';
import { showToast, showConfirmToast } from './toast.js';

// Server-required confirmation for destructive actions (backend/confirmations.py).
setConfirmationHandler((info) => new Promise((resolve) => {
  showConfirmToast('Confirm action', `${info.summary || 'This action cannot be undone'}?`, () => resolve(true), () => resolve(false));
}));
import './folder-browser.js';
import './modals.js';

import { initDockSystem, DockManager, makeDraggable, bringToFront, restoreOpenWindowsState, setWindowRestorationComplete } from './components/dock.js';
import { initAuth } from './components/auth.js';
import { initUsersManagement } from './components/users.js';
import { applyStats, applyTheme, applyDesktopTheme, applyLcdTheme, initDashboardClicks } from './components/dashboard.js';
import { initFanControl } from './components/fan-control.js';
import { initLedControl } from './components/led-control.js';
import { fetchDashboardLayout, fitMiniPreviewScale } from './components/mini-preview.js';
import { initWallpapers, loadWallpapers } from './components/wallpapers.js';
import { initEvents } from './components/events.js';
import { initSettings, openDrawer, closeDrawer } from './components/settings.js';
import { initMetricsChart, fetchAndRenderMetrics } from './components/metrics-chart.js';
import { initSetupWizard } from './components/setup-wizard.js';
import { initManagement } from './components/management.js';
import { initCommandPalette } from './components/command-palette.js';
import { initWidgets } from './components/widgets.js';
import { initFileManager } from './components/file-manager.js';
import { initVmManager, openVmConsole } from './components/vm-manager.js';
import { initContainersManager } from './components/containers-manager.js';
import { initContainerModal } from './components/container-modal.js';
import { initStackModal } from './components/stack-modal.js';
import { initDesktopContextMenu } from './components/desktop-context-menu.js';
import { initDesktopDragAndDrop } from './components/desktop-drag-drop.js';
import { initScreensaverSystem } from './components/screensaver.js';
import { initI18n } from './i18n.js';
import { initA11y } from './a11y.js';
import { initGlassTimePickers } from './components/time-picker.js';

let _sseRetryCount = 0;
let _sse = null;
let _sseReconnectTimer = null;
let _pollingTimer = null;
let _pollAbortController = null;

async function checkLcdStatus() {
  if (state.isLcdDirect) return;
  if (state.latestStats?.hardware?.has_lcd === false) return;
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
      } else if (data.screen_off || data.power === false) {
        badge.textContent = 'LCD: SCREEN OFF';
        badge.className = 'lcd-status-badge lcd-status-disabled';
        badge.title = 'Physical LCD display is turned off (0 FPS).';
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
  if (!auth.hasToken() && !state.isLcdDirect) {
    return;
  }
  if (_pollAbortController) {
    _pollAbortController.abort();
  }
  _pollAbortController = new AbortController();
  try {
    const s = await api.get('/api/stats', { signal: _pollAbortController.signal });
    applyStats(s);
  } catch (e) {
    if (e.name !== 'AbortError') {
      console.warn('Polling stats failed', e);
    }
  }
}

export function stopSSE() {
  if (_sseReconnectTimer) {
    clearTimeout(_sseReconnectTimer);
    _sseReconnectTimer = null;
  }
  if (_pollingTimer) {
    clearInterval(_pollingTimer);
    _pollingTimer = null;
  }
  if (_pollAbortController) {
    _pollAbortController.abort();
    _pollAbortController = null;
  }
  if (_sse) {
    _sse.close();
    _sse = null;
  }
}

export function startSSE() {
  if (!auth.hasToken() && !state.isLcdDirect) {
    return;
  }
  if (_sseReconnectTimer) {
    clearTimeout(_sseReconnectTimer);
    _sseReconnectTimer = null;
  }
  if (_sse) {
    _sse.close();
    _sse = null;
  }

  // EventSource can't send headers: the browser UI uses its session cookie; only the LCD
  // renderer (in-memory internal token) identifies itself in the URL.
  const token = auth.getToken();
  const url = token ? `/api/stats/stream?lcd_token=${encodeURIComponent(token)}` : '/api/stats/stream';
  _sse = new EventSource(url);

  _sse.onopen = () => {
    _sseRetryCount = 0;
    if (_pollingTimer) {
      clearInterval(_pollingTimer);
      _pollingTimer = null;
    }
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
    if (_sse) {
      _sse.close();
      _sse = null;
    }
    const streamBadge = document.getElementById('stream-status-badge');
    if (streamBadge) {
      streamBadge.textContent = 'POLLING';
      streamBadge.className = 'header-badge warning';
    }
    if (!auth.hasToken() && !state.isLcdDirect) {
      return;
    }
    if (!_pollingTimer) {
      tick();
      _pollingTimer = setInterval(tick, 3000);
    }
    const delay = Math.min(10000, 2000 * Math.pow(1.5, _sseRetryCount));
    _sseReconnectTimer = setTimeout(() => {
      startSSE();
    }, delay);
  };
}

document.addEventListener('DOMContentLoaded', () => {
  if (window.location.search.includes('mode=lcd') || document.body.classList.contains('lcd-direct')) {
    state.isLcdDirect = true;
    document.body.classList.add('lcd-direct');
    try {
      sessionStorage.removeItem('zettnas_desktop_locked');
      localStorage.removeItem('zettnas_desktop_locked');
    } catch (e) {}
    const overlay = document.getElementById('console-modal-overlay');
    const win = document.getElementById('console-window');
    const screen = document.getElementById('screen');
    if (overlay) {
      overlay.style.removeProperty('display');
      overlay.classList.remove('window-minimized');
      overlay.classList.add('open');
    }
    if (win) {
      win.style.removeProperty('display');
      win.classList.remove('window-minimized');
    }
    if (screen) {
      screen.style.visibility = 'visible';
    }
  }

  if (window.location.search.includes('mode=vm-console') || document.body.classList.contains('vm-console-direct')) {
    state.isVmConsoleDirect = true;
    document.body.classList.add('vm-console-direct');
  }

  // Optimized Direct Modes: Avoid booting desktop window manager & apps
  if (state.isVmConsoleDirect) {
    setWindowRestorationComplete(true);
    initI18n();
    initAuth();
    initVmManager();
    initA11y();
    if (auth.hasToken()) {
      const params = new URLSearchParams(window.location.search);
      const vmId = params.get('vm') || '1';
      const vmName = params.get('name') || 'Virtual Machine';
      const consoleMode = params.get('consoleMode') || 'gui';
      openVmConsole(vmId, vmName, consoleMode);
    } else {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.style.removeProperty('opacity');
        overlay.style.display = 'flex';
      }
    }
    return;
  }

  if (state.isLcdDirect) {
    setWindowRestorationComplete(true);
    initI18n();
    initDashboardClicks();
    initFanControl();
    initLedControl();
    applyLcdTheme(state.lcdTheme, state.lcdCustomAccent, state.lcdTextClarity);
    applyDashboardLayout();
    fetchDashboardLayout();
    tick();
    startSSE();
    return;
  }

  setWindowRestorationComplete(false);
  initI18n();
  initDockSystem();
  initAuth();
  initUsersManagement();
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
  initVmManager();
  initContainersManager();
  initContainerModal();
  initStackModal();
  initDesktopContextMenu();
  initDesktopDragAndDrop();
  initScreensaverSystem();
  initA11y();
  initGlassTimePickers();

  applyDesktopTheme(state.desktopTheme, state.desktopCustomAccent);
  applyLcdTheme(state.lcdTheme, state.lcdCustomAccent, state.lcdTextClarity);

  const hasAuth = auth.hasToken() || state.isLcdDirect;
  if (hasAuth) {
    restoreOpenWindowsState();
    fetchDashboardLayout();
    tick();
    startSSE();
    checkLcdStatus();
    loadWallpapers();
  } else {
    setWindowRestorationComplete(true);
    const overlay = document.getElementById('login-overlay');
    if (overlay) {
      overlay.style.removeProperty('opacity');
      overlay.style.display = 'flex';
    }
  }

  setInterval(() => {
    if (!state.isVmConsoleDirect && (auth.hasToken() || state.isLcdDirect)) {
      checkLcdStatus();
    }
  }, 10000);

  window.addEventListener('resize', fitMiniPreviewScale);

  ZettEventBus.on('auth:required', () => {
    stopSSE();
  });

  ZettEventBus.on('auth:locked', () => {
    stopSSE();
  });

  ZettEventBus.on('auth:unlocked', () => {
    if (auth.hasToken() || state.isLcdDirect) {
      tick();
      startSSE();
    }
  });

  ZettEventBus.on('auth:login', () => {
    fetchDashboardLayout();
    tick();
    startSSE();
    checkLcdStatus();
    loadWallpapers();
    DockManager.render();
    restoreOpenWindowsState();
  });
});
