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

export const state = {
  isLcdDirect: typeof window !== 'undefined' && (window.location.search.includes('mode=lcd') || (typeof document !== 'undefined' && document.body && document.body.classList.contains('lcd-direct'))),
  currentTheme: localStorage.getItem('lcd_theme') || 'cyber',
  clockFormat: '24',
  currentTimezone: 'America/New_York',
  latestStats: null,
  activeLayoutVersion: 0,
  dashOrder: [...defaultDashOrder],
  dashVis: { ...defaultVis },
  dashSizes: { ...defaultSizes },
  isLayoutLocked: localStorage.getItem('lcd_dash_cards_locked') !== 'false',
  currentZoomIdx: 2,
  selectedZoneFilter: 'all',
  curvePoints: [[30, 32], [37, 32], [50, 100], [60, 100]],
  lastCurveSaveTime: 0,
  copyToastMinimized: false,

  setStats(s) {
    if (!s) return;
    if (!this.latestStats) {
      this.latestStats = s;
    } else {
      this.latestStats = { ...this.latestStats, ...s };
    }
    ZettEventBus.emit('stats:updated', this.latestStats);
  },

  setTheme(theme) {
    this.currentTheme = theme;
    localStorage.setItem('lcd_theme', theme);
    ZettEventBus.emit('theme:changed', theme);
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
