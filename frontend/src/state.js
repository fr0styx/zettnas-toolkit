/**
 * ZettNAS Toolkit Reactive State Store
 * Centralizes UI configuration, hardware telemetry caches, and layout preferences.
 */
import { ZettEventBus } from './event-bus.js';

export const defaultDashOrder = [
  'metric-storage',
  'metric-cpu',
  'metric-mem',
  'metric-fans',
  'metric-net',
  'metric-disks'
];

export const defaultVis = {
  'metric-storage': true,
  'metric-cpu': true,
  'metric-mem': true,
  'metric-fans': true,
  'metric-net': true,
  'metric-disks': true
};

export const defaultSizes = {
  'metric-storage': 'normal',
  'metric-cpu': 'normal',
  'metric-mem': 'normal',
  'metric-fans': 'normal',
  'metric-net': 'normal',
  'metric-disks': 'normal'
};

export const ZOOM_PROFILES = [0.75, 0.85, 1.0, 1.15, 1.25, 1.5];

export function fastEqual(a, b) {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (!fastEqual(a[i], b[i])) return false;
    }
    return true;
  }
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) return false;
  for (let i = 0; i < keysA.length; i++) {
    const k = keysA[i];
    if (!(k in b) || !fastEqual(a[k], b[k])) return false;
  }
  return true;
}

// The server sends container CPU/RAM/network changes as a compact `docker_tel`
// map ({ id: { field: value } }) instead of the full list (backend/services/stats_delta.py).
// Fold it into the container list we already hold; only changed containers get new objects.
export function mergeDockerTelemetry(s, current) {
  if (!s || !s.docker_tel) return s;
  const { docker_tel: tel, ...rest } = s;
  const base = Array.isArray(rest.docker)
    ? rest.docker
    : current && Array.isArray(current.docker)
    ? current.docker
    : null;
  if (base) rest.docker = base.map((c) => (c && tel[c.id] ? { ...c, ...tel[c.id] } : c));
  return rest;
}

export const state = {
  isLcdDirect: typeof window !== 'undefined' && (window.location.search.includes('mode=lcd') || (typeof document !== 'undefined' && document.body && document.body.classList.contains('lcd-direct'))),
  isVmConsoleDirect: typeof window !== 'undefined' && (window.location.search.includes('mode=vm-console') || (typeof document !== 'undefined' && document.body && document.body.classList.contains('vm-console-direct'))),
  desktopTheme: (typeof localStorage !== 'undefined' && localStorage.getItem('desktop_theme')) || 'cyber',
  desktopCustomAccent: (typeof localStorage !== 'undefined' && localStorage.getItem('desktop_custom_accent')) || '',
  lcdTheme: (typeof localStorage !== 'undefined' && localStorage.getItem('lcd_theme')) || 'cyber',
  lcdCustomAccent: (typeof localStorage !== 'undefined' && localStorage.getItem('lcd_custom_accent')) || '',
  lcdTextClarity: typeof localStorage !== 'undefined' ? localStorage.getItem('lcd_text_clarity') !== 'false' : true,

  // Compatibility accessors
  get currentTheme() { return this.desktopTheme; },
  set currentTheme(v) { this.desktopTheme = v; },
  get customAccentColor() { return this.desktopCustomAccent; },
  set customAccentColor(v) { this.desktopCustomAccent = v; },
  get textClarity() { return this.lcdTextClarity; },
  set textClarity(v) { this.lcdTextClarity = v; },

  clockFormat: '24',
  currentTimezone: 'America/New_York',
  screenLayoutStyle: (typeof localStorage !== 'undefined' && localStorage.getItem('screen_layout_style')) || 'classic',
  latestStats: null,
  activeLayoutVersion: 0,
  dashOrder: [...defaultDashOrder],
  dashVis: { ...defaultVis },
  dashSizes: { ...defaultSizes },
  isLayoutLocked: localStorage.getItem('lcd_dash_cards_locked') !== 'false',
  currentZoomIdx: 2,
  selectedZoneFilter: 'all',
  curvePoints: [[30, 0], [36, 32], [42, 48], [48, 65], [54, 85], [60, 100]],
  lastCurveSaveTime: 0,
  copyToastMinimized: false,

  setStats(s) {
    if (!s) return false;
    s = mergeDockerTelemetry(s, this.latestStats);
    if (!this.latestStats) {
      this.latestStats = s;
      ZettEventBus.emit('stats:updated', this.latestStats);
      return true;
    }

    // Fast diff metrics without heap JSON allocations to prevent unnecessary UI renders
    let changed = false;
    for (const key of Object.keys(s)) {
      const newVal = s[key];
      const oldVal = this.latestStats[key];
      if (newVal !== oldVal) {
        if (typeof newVal === 'object' && newVal !== null && typeof oldVal === 'object' && oldVal !== null) {
          if (!fastEqual(newVal, oldVal)) {
            changed = true;
            break;
          }
        } else {
          changed = true;
          break;
        }
      }
    }

    if (!changed) return false;

    this.latestStats = { ...this.latestStats, ...s };
    ZettEventBus.emit('stats:updated', this.latestStats);
    return true;
  },

  setDesktopTheme(theme, customAccent = null) {
    this.desktopTheme = theme;
    if (typeof localStorage !== 'undefined') localStorage.setItem('desktop_theme', theme);
    if (customAccent !== null) {
      this.desktopCustomAccent = customAccent;
      if (typeof localStorage !== 'undefined') localStorage.setItem('desktop_custom_accent', customAccent);
    }
    ZettEventBus.emit('desktop_theme:changed', {
      theme: this.desktopTheme,
      accent: this.desktopCustomAccent
    });
    ZettEventBus.emit('theme:changed', {
      theme: this.desktopTheme,
      accent: this.desktopCustomAccent
    });
  },

  setLcdTheme(theme, customAccent = null, textClarity = null) {
    this.lcdTheme = theme;
    if (typeof localStorage !== 'undefined') localStorage.setItem('lcd_theme', theme);
    if (customAccent !== null) {
      this.lcdCustomAccent = customAccent;
      if (typeof localStorage !== 'undefined') localStorage.setItem('lcd_custom_accent', customAccent);
    }
    if (textClarity !== null) {
      this.lcdTextClarity = Boolean(textClarity);
      if (typeof localStorage !== 'undefined') localStorage.setItem('lcd_text_clarity', this.lcdTextClarity ? 'true' : 'false');
    }
    ZettEventBus.emit('lcd_theme:changed', {
      theme: this.lcdTheme,
      accent: this.lcdCustomAccent,
      textClarity: this.lcdTextClarity
    });
  },

  setTheme(theme, customAccent = null, textClarity = null) {
    this.setDesktopTheme(theme, customAccent);
    if (textClarity !== null) {
      this.setLcdTheme(theme, customAccent, textClarity);
    }
  },

  setLayout(order, vis, sizes, version = null) {
    if (order) this.dashOrder = [...order];
    if (vis) this.dashVis = { ...vis };
    if (sizes) this.dashSizes = { ...sizes };
    if (version !== null) this.activeLayoutVersion = version;
    ZettEventBus.emit('layout:updated', {
      order: this.dashOrder,
      vis: this.dashVis,
      sizes: this.dashSizes,
      version: this.activeLayoutVersion
    });
  },

  setCurvePoints(points, updateTimestamp = false) {
    this.curvePoints = points;
    if (updateTimestamp) {
      this.lastCurveSaveTime = Date.now();
    }
    ZettEventBus.emit('curve:updated', this.curvePoints);
  },

  setZoneFilter(filter) {
    this.selectedZoneFilter = filter;
    ZettEventBus.emit('zone_filter:changed', filter);
  },

  setZoomIdx(idx) {
    if (idx >= 0 && idx < ZOOM_PROFILES.length) {
      this.currentZoomIdx = idx;
      ZettEventBus.emit('zoom:changed', ZOOM_PROFILES[idx]);
    }
  }
};

export default state;
