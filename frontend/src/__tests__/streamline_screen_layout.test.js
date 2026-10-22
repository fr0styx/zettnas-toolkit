import { readStyleCss } from './helpers/read-style-css.js';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { state } from '../state.js';
import { api } from '../api.js';
import { ZettEventBus } from '../event-bus.js';
import * as toastModule from '../toast.js';
import {
  setScreenLayoutStyle,
  syncScreenLayoutStyle,
  updateStreamlineLayout,
  updateStreamlineBayChips,
  initDashboardClicks,
  diskTile,
  renderDisks
} from '../components/dashboard.js';
import {
  syncLcdStyleUI,
  initLcdStyleControls
} from '../components/settings.js';
import {
  applyDashboardLayout,
  syncMiniPreviewStructure,
  syncMiniPreviewTelemetry,
  setupMiniPreviewInteractivity
} from '../components/mini-preview.js';
import fs from 'fs';
import path from 'path';

describe('Streamline Minimalist / Big IP Screen Layout Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', layout: { version: 1 } });
    state.screenLayoutStyle = 'classic';
    state.dashOrder = ['metric-storage', 'metric-cpu', 'metric-mem', 'metric-fans', 'metric-net', 'metric-disks'];
    state.currentTimezone = 'UTC';
    state.clockFormat = '24';
    state.latestStats = null;

    document.body.innerHTML = `
      <div id="screen" class="layout-classic">
        <header id="screen-header">
          <div class="h-left"><span id="nasName" class="nas-name">ZETTNEXT</span></div>
          <div id="clock" class="clock">12:00</div>
          <div class="h-right"><span id="ip">10.40.30.249</span></div>
        </header>

        <div id="dashboard-cards-container" class="cards">
          <div class="card card-storage" data-metric-id="metric-storage"></div>
          <div class="card card-cpu" data-metric-id="metric-cpu"></div>
          <div class="card card-mem" data-metric-id="metric-mem"></div>
          <div class="card card-fans" data-metric-id="metric-fans"></div>
          <div class="card card-net" data-metric-id="metric-net"></div>
        </div>

        <div id="diskRow" class="disks"></div>

        <div class="streamline-container" id="streamline-container">
          <div class="sl-header">
            <div class="sl-header-left">
              <span class="sl-status-ring ok" id="sl-status-ring"></span>
              <span class="sl-nas-name" id="sl-nas-name">ZETTNEXT</span>
            </div>
            <div class="sl-clock" id="sl-clock">--:--</div>
          </div>

          <div class="sl-main-deck">
            <div class="card sl-card sl-card-storage" id="sl-zone-storage" data-metric-id="metric-storage">
              <div class="card-title">
                <svg class="ic"><use href="#i-disk"/></svg>
                <span class="card-title-txt">STORAGE</span>
              </div>
              <div class="sl-storage-body">
                <div class="sl-donut-wrap">
                  <svg class="sl-donut-svg" viewBox="0 0 64 64">
                    <circle class="sl-donut-track" cx="32" cy="32" r="26" />
                    <circle class="sl-donut-arc" id="sl-storage-arc" cx="32" cy="32" r="26" />
                  </svg>
                  <span class="sl-donut-pct" id="sl-storage-pct">0%</span>
                </div>
                <div class="sl-storage-meta">
                  <span class="sl-meta-label">CAPACITY</span>
                  <strong class="sl-meta-used" id="sl-storage-used">0TB</strong>
                  <span class="sl-meta-total" id="sl-storage-total">/ 0TB</span>
                </div>
              </div>
            </div>

            <div class="card sl-card sl-card-compute" id="sl-zone-compute" data-metric-id="metric-cpu">
              <div class="card-title">
                <svg class="ic"><use href="#i-cpu"/></svg>
                <span class="card-title-txt">COMPUTE</span>
              </div>
              <div class="sl-compute-body">
                <div class="sl-bar-row" id="sl-cpu-row">
                  <div class="sl-bar-header">
                    <span class="sl-bar-label">CPU</span>
                    <div class="sl-bar-stat">
                      <strong class="sl-bar-val" id="sl-cpu-val">0%</strong>
                      <span class="sl-bar-sub" id="sl-cpu-temp">--°C</span>
                    </div>
                  </div>
                  <div class="sl-bar-track">
                    <div class="sl-bar-fill sl-fill-cpu" id="sl-cpu-bar" style="width: 0%"></div>
                  </div>
                </div>
                <div class="sl-bar-row" id="sl-mem-row">
                  <div class="sl-bar-header">
                    <span class="sl-bar-label">Memory</span>
                    <div class="sl-bar-stat">
                      <strong class="sl-bar-val" id="sl-mem-val">0%</strong>
                      <span class="sl-bar-sub" id="sl-mem-used">--</span>
                    </div>
                  </div>
                  <div class="sl-bar-track">
                    <div class="sl-bar-fill sl-fill-mem" id="sl-mem-bar" style="width: 0%"></div>
                  </div>
                </div>
              </div>
            </div>

            <div class="card sl-card sl-card-ip" id="sl-zone-ip" data-metric-id="metric-net">
              <div class="card-title">
                <svg class="ic"><use href="#i-globe"/></svg>
                <span class="card-title-txt">IP ADDRESS</span>
              </div>
              <div class="sl-ip-body">
                <div class="sl-hero-ip" id="sl-hero-ip">0.0.0.0</div>
                <div class="sl-net-rates" id="sl-net-rates">
                  <span class="sl-net-item"><span class="sl-net-lbl">TX:</span> <strong id="sl-net-tx">0 KB/s</strong></span>
                  <span class="sl-net-sep">•</span>
                  <span class="sl-net-item"><span class="sl-net-lbl">RX:</span> <strong id="sl-net-rx">0 KB/s</strong></span>
                </div>
              </div>
            </div>
          </div>

          <div class="sl-bay-row" id="sl-bay-row" data-metric-id="metric-disks"></div>
        </div>
      </div>

      <div class="mini-preview-inner" id="mini-preview-inner"></div>

      <div class="draggable-card drawer-card" data-layout-card-id="sec-lcd-style" id="sec-lcd-style">
        <div class="card-headline">
          <span id="lcd-style-active-badge" class="preset-state-badge">CLASSIC CARDS</span>
        </div>
        <div class="lcd-style-picker-row">
          <button type="button" class="lcd-style-chip active" data-screen-style="classic">Classic Cards</button>
          <button type="button" class="lcd-style-chip" data-screen-style="streamline">Streamline Big IP</button>
        </div>
      </div>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('toggles layout style between classic and streamline with state and DOM classes', () => {
    const screen = document.getElementById('screen');
    const mini = document.getElementById('mini-preview-inner');
    const eventSpy = vi.fn();
    ZettEventBus.on('screen:layout_style_changed', eventSpy);

    // Switch to streamline
    setScreenLayoutStyle('streamline', false);
    expect(state.screenLayoutStyle).toBe('streamline');
    expect(screen.classList.contains('layout-streamline')).toBe(true);
    expect(screen.classList.contains('layout-classic')).toBe(false);
    expect(mini.classList.contains('layout-streamline')).toBe(true);
    expect(localStorage.getItem('screen_layout_style')).toBe('streamline');
    expect(eventSpy.mock.calls[0][0]).toBe('streamline');

    // Switch back to classic
    setScreenLayoutStyle('classic', false);
    expect(state.screenLayoutStyle).toBe('classic');
    expect(screen.classList.contains('layout-classic')).toBe(true);
    expect(screen.classList.contains('layout-streamline')).toBe(false);
    expect(mini.classList.contains('layout-classic')).toBe(true);
    expect(localStorage.getItem('screen_layout_style')).toBe('classic');
    expect(eventSpy.mock.calls[1][0]).toBe('classic');
  });

  it('updates streamline telemetry deck including donut offset, sliders, and hero IP', () => {
    const stats = {
      name: 'ZETTNEXT-D8U',
      ip: '10.40.30.249',
      status: 'SYSTEM OK',
      storage: { pct: 24, used: '1.4TB', total: '5.8TB' },
      cpu: { util: 4.2, temp: 42 },
      mem: { pct: 18.0, used: '5.7GB', total: '31.1GB' },
      disks: [
        { name: 'sda', dev: '/dev/sda', temp: 35, health: 'ok' },
        { name: 'nvme0n1', dev: '/dev/nvme0n1', temp: 38, health: 'ok' }
      ]
    };

    updateStreamlineLayout(stats, false);

    expect(document.getElementById('sl-nas-name').textContent).toBe('ZETTNEXT-D8U');
    expect(document.getElementById('sl-status-ring').className).toContain('sl-status-ring ok');
    expect(document.getElementById('sl-hero-ip').textContent).toBe('10.40.30.249');

    // Storage Zone
    expect(document.getElementById('sl-storage-pct').textContent).toBe('24%');
    expect(document.getElementById('sl-storage-used').textContent).toBe('1.4TB');
    expect(document.getElementById('sl-storage-total').textContent).toBe('/ 5.8TB');

    const arc = document.getElementById('sl-storage-arc');
    // 163.36 - (163.36 * 0.24) = 124.15
    const expectedOffset = (163.36 - (163.36 * 24) / 100).toFixed(2);
    expect(arc.style.strokeDashoffset).toBe(expectedOffset);

    // Compute Zone
    expect(document.getElementById('sl-cpu-val').textContent).toBe('4%');
    expect(document.getElementById('sl-cpu-temp').textContent).toBe('42°C');
    expect(document.getElementById('sl-cpu-bar').style.width).toBe('4%');

    expect(document.getElementById('sl-mem-val').textContent).toBe('18%');
    expect(document.getElementById('sl-mem-used').textContent).toBe('5.7GB');
    expect(document.getElementById('sl-mem-bar').style.width).toBe('18%');
  });

  it('updates status ring to warn or crit on high temperatures or disk failures', () => {
    const warnStats = {
      name: 'ZETTNEXT',
      ip: '10.0.0.1',
      storage: { pct: 82, used: '8TB', total: '10TB' },
      cpu: { util: 78, temp: 72 },
      mem: { pct: 76 },
      disks: []
    };
    updateStreamlineLayout(warnStats, true);
    expect(document.getElementById('sl-status-ring').className).toContain('sl-status-ring warn');

    const critStats = {
      name: 'ZETTNEXT',
      ip: '10.0.0.1',
      storage: { pct: 95, used: '9.5TB', total: '10TB' },
      cpu: { util: 92, temp: 88 },
      mem: { pct: 92 },
      disks: [{ name: 'sda', health: 'crit' }]
    };
    updateStreamlineLayout(critStats, true);
    expect(document.getElementById('sl-status-ring').className).toContain('sl-status-ring crit');
  });

  it('renders lower deck bay chips formatted with device paths (sda..sdh, nv0, nv1)', () => {
    const disks = [
      { name: '/dev/sda', dev: '/dev/sda', temp: 34, health: 'ok' },
      { name: '/dev/sdb', dev: '/dev/sdb', temp: 36, health: 'ok' },
      { name: '/dev/sdc', dev: '/dev/sdc', temp: 35, health: 'ok' },
      { name: '/dev/sdd', dev: '/dev/sdd', temp: 37, health: 'ok' },
      { name: '/dev/sde', dev: '/dev/sde', temp: 34, health: 'ok' },
      { name: '/dev/sdf', dev: '/dev/sdf', temp: 35, health: 'ok' },
      { name: '/dev/sdg', dev: '/dev/sdg', temp: 36, health: 'ok' },
      { name: '/dev/sdh', dev: '/dev/sdh', temp: 35, health: 'ok' },
      { name: '/dev/nvme0n1', dev: '/dev/nvme0n1', temp: 40, health: 'ok' },
      { name: '/dev/nvme1n1', dev: '/dev/nvme1n1', temp: 42, health: 'ok' }
    ];

    updateStreamlineBayChips(disks);

    const bayRow = document.getElementById('sl-bay-row');
    const chips = bayRow.querySelectorAll('.sl-bay-chip');
    expect(chips.length).toBe(10);

    const labels = Array.from(chips).map(c => c.querySelector('.slot-lbl').textContent);
    expect(labels).toEqual([
      'sda', 'sdb', 'sdc', 'sdd', 'sde', 'sdf', 'sdg', 'sdh', 'nv0', 'nv1'
    ]);
  });

  it('protects sleeping drives: prompts confirmation on standby bay chips before opening SMART', () => {
    const disks = [
      { name: 'sda', dev: '/dev/sda', temp: 35, health: 'ok', standby: false },
      { name: 'sdb', dev: '/dev/sdb', temp: null, health: 'standby', standby: true }
    ];
    state.latestStats = { disks };

    updateStreamlineBayChips(disks);

    const bayRow = document.getElementById('sl-bay-row');
    const chips = bayRow.querySelectorAll('.sl-bay-chip');

    const confirmToastSpy = vi.spyOn(toastModule, 'showConfirmToast').mockImplementation(() => {});
    const smartEventSpy = vi.fn();
    ZettEventBus.on('modal:smart:open', smartEventSpy);

    // Click active disk: opens SMART directly without prompt
    chips[0].click();
    expect(confirmToastSpy).not.toHaveBeenCalled();
    expect(smartEventSpy.mock.calls[0][0]).toBe('/dev/sda');

    // Click standby disk: triggers confirm toast to prevent spinup
    smartEventSpy.mockClear();
    let onConfirmCb = null;
    confirmToastSpy.mockImplementation((title, desc, onConfirm) => {
      onConfirmCb = onConfirm;
    });

    chips[1].click();
    expect(confirmToastSpy).toHaveBeenCalledWith(
      'Drive in Standby Mode',
      expect.stringContaining('currently sleeping'),
      expect.any(Function)
    );
    expect(smartEventSpy).not.toHaveBeenCalled();

    // Invoking confirmation callback triggers modal with forceWake: true
    expect(onConfirmCb).toBeTypeOf('function');
    onConfirmCb();
    expect(smartEventSpy).toHaveBeenCalledWith({ dev: '/dev/sdb', forceWake: true }, expect.anything());
  });

  it('delegates interactive clicks from streamline storage, CPU, Memory, and IP zones to metrics modal', () => {
    initDashboardClicks();

    const metricEventSpy = vi.fn();
    ZettEventBus.on('modal:metric:open', metricEventSpy);

    document.getElementById('sl-zone-storage').click();
    expect(metricEventSpy.mock.calls[0][0]).toBe('storage');

    document.getElementById('sl-cpu-row').click();
    expect(metricEventSpy.mock.calls[1][0]).toBe('cpu');

    document.getElementById('sl-mem-row').click();
    expect(metricEventSpy.mock.calls[2][0]).toBe('mem');

    document.getElementById('sl-zone-ip').click();
    expect(metricEventSpy.mock.calls[3][0]).toBe('net');
  });

  it('syncs Settings Drawer style chips and active badge', () => {
    initLcdStyleControls();

    const classicChip = document.querySelector('.lcd-style-chip[data-screen-style="classic"]');
    const streamlineChip = document.querySelector('.lcd-style-chip[data-screen-style="streamline"]');
    const badge = document.getElementById('lcd-style-active-badge');

    expect(badge.textContent).toBe('CLASSIC CARDS');
    expect(classicChip.classList.contains('active')).toBe(true);
    expect(streamlineChip.classList.contains('active')).toBe(false);

    // User clicks streamline chip
    streamlineChip.click();
    expect(state.screenLayoutStyle).toBe('streamline');
    expect(badge.textContent).toBe('STREAMLINE BIG IP');
    expect(streamlineChip.classList.contains('active')).toBe(true);
    expect(classicChip.classList.contains('active')).toBe(false);

    // User clicks classic chip
    classicChip.click();
    expect(state.screenLayoutStyle).toBe('classic');
    expect(badge.textContent).toBe('CLASSIC CARDS');
    expect(classicChip.classList.contains('active')).toBe(true);
    expect(streamlineChip.classList.contains('active')).toBe(false);
  });

  it('enforces streamline CSS isolation in style.css and lcd-direct.css', () => {
    const styleCss = readStyleCss();
    const lcdDirectCss = fs.readFileSync(path.resolve(__dirname, '../lcd-direct.css'), 'utf-8');

    // In style.css, streamline layout hides classic header, cards, diskRow for screen and mini-preview
    expect(styleCss).toContain('#screen.layout-streamline > header');
    expect(styleCss).toContain('#screen.layout-streamline #dashboard-cards-container');
    expect(styleCss).toContain('#screen.layout-streamline #diskRow');
    expect(styleCss).toContain('#screen.layout-streamline #streamline-container');
    expect(styleCss).toContain('.mini-preview-inner.layout-streamline .cards');
    expect(styleCss).toContain('.mini-preview-inner.layout-streamline .disks');
    expect(styleCss).toContain('.mini-preview-inner:not(.layout-streamline) .streamline-container');

    // In lcd-direct.css, physical 172x640 panel overrides ensure streamline mode is applied with high specificity
    expect(lcdDirectCss).toContain('body.lcd-direct #screen.layout-streamline');
    expect(lcdDirectCss).toContain('body.lcd-direct #console-window #screen.layout-streamline .cards');
    expect(lcdDirectCss).toContain('body.lcd-direct #console-window #screen.layout-streamline .disks');
    expect(lcdDirectCss).toContain('body.lcd-direct #console-window #screen.layout-streamline #streamline-container');
    expect(lcdDirectCss).toContain('body.lcd-direct #console-window #screen:not(.layout-streamline) .streamline-container');
  });

  it('syncs layout classes and isolation between #screen, document.body, and mini-preview-inner', () => {
    document.body.className = '';
    const screen = document.getElementById('screen');
    const mini = document.getElementById('mini-preview-inner') || document.createElement('div');
    mini.className = 'mini-preview-inner';
    if (!mini.parentElement) document.body.appendChild(mini);

    // Switch to streamline mode
    setScreenLayoutStyle('streamline', false);
    expect(state.screenLayoutStyle).toBe('streamline');
    expect(screen.classList.contains('layout-streamline')).toBe(true);
    expect(screen.classList.contains('layout-classic')).toBe(false);
    expect(document.body.classList.contains('layout-streamline')).toBe(true);
    expect(mini.classList.contains('layout-streamline')).toBe(true);
    expect(mini.classList.contains('layout-classic')).toBe(false);

    // Switch back to classic mode
    setScreenLayoutStyle('classic', false);
    expect(state.screenLayoutStyle).toBe('classic');
    expect(screen.classList.contains('layout-classic')).toBe(true);
    expect(screen.classList.contains('layout-streamline')).toBe(false);
    expect(document.body.classList.contains('layout-classic')).toBe(true);
    expect(mini.classList.contains('layout-classic')).toBe(true);
    expect(mini.classList.contains('layout-streamline')).toBe(false);
  });

  describe('Parity Drive Pill & Tag Identification (Classic & Streamline)', () => {
    it('renders clean streamline bay chip with parity role styling, temp, and no redundant small P', () => {
      const disks = [
        { name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: 34, health: 'ok' },
        { name: 'sdc', role: 'parity', is_parity: true, parity_label: 'P2', temp: 35, health: 'ok' },
        { name: 'sda', role: 'data', is_parity: false, temp: 37, health: 'ok' },
      ];

      updateStreamlineBayChips(disks);

      const bayRow = document.getElementById('sl-bay-row');
      const chips = bayRow.querySelectorAll('.sl-bay-chip');
      expect(chips.length).toBe(3);

      // sdb: Parity 1
      expect(chips[0].classList.contains('chip-parity')).toBe(true);
      expect(chips[0].classList.contains('r-parity')).toBe(true);
      expect(chips[0].title).toContain('[PARITY]');
      expect(chips[0].querySelector('.sl-parity-tag')).toBeNull();
      expect(chips[0].querySelector('.sl-chip-role').textContent).toBe('PARITY');
      expect(chips[0].querySelector('.sl-chip-temp').textContent).toBe('34°C');

      // sdc: Parity 2
      expect(chips[1].classList.contains('chip-parity')).toBe(true);
      expect(chips[1].classList.contains('r-parity')).toBe(true);
      expect(chips[1].querySelector('.sl-parity-tag')).toBeNull();
      expect(chips[1].querySelector('.sl-chip-role').textContent).toBe('PARITY 2');
      expect(chips[1].querySelector('.sl-chip-temp').textContent).toBe('35°C');

      // sda: Data drive (no parity tag)
      expect(chips[2].classList.contains('chip-parity')).toBe(false);
      expect(chips[2].classList.contains('r-data')).toBe(true);
      expect(chips[2].querySelector('.sl-parity-tag')).toBeNull();
      expect(chips[2].querySelector('.sl-chip-role').textContent).toBe('DATA');
      expect(chips[2].querySelector('.sl-chip-temp').textContent).toBe('37°C');

      // Test subsequent live updates (non-structural branch)
      const updatedDisks = [
        { name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: 36, health: 'ok' },
        { name: 'sdc', role: 'parity', is_parity: true, parity_label: 'P2', temp: 36, health: 'ok' },
        { name: 'sda', role: 'data', is_parity: false, temp: 38, health: 'ok' },
      ];
      updateStreamlineBayChips(updatedDisks);

      expect(chips[0].querySelector('.sl-chip-role').textContent).toBe('PARITY');
      expect(chips[0].querySelector('.sl-chip-temp').textContent).toBe('36°C');
      expect(chips[1].querySelector('.sl-chip-role').textContent).toBe('PARITY 2');
      expect(chips[1].querySelector('.sl-chip-temp').textContent).toBe('36°C');
      expect(chips[2].querySelector('.sl-chip-role').textContent).toBe('DATA');
      expect(chips[2].querySelector('.sl-chip-temp').textContent).toBe('38°C');
    });

    it('renders clean disk tile in Classic Cards without redundant parity pill', () => {
      const pTile = diskTile({ name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: 34, health: 'ok' });
      expect(pTile.classList.contains('disk-is-parity')).toBe(true);
      expect(pTile.classList.contains('r-parity')).toBe(true);
      expect(pTile.title).toContain('[PARITY]');

      // Parity pill is removed to eliminate visual redundancy with group header and prevent clipping
      expect(pTile.querySelector('.dt .parity-pill')).toBeNull();

      // Parity drive in standby mode displays clean full-width standby badge without pill
      const pStandbyTile = diskTile({ name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: null, health: 'standby', standby: true });
      expect(pStandbyTile.classList.contains('disk-is-parity')).toBe(true);
      expect(pStandbyTile.querySelector('.dt .standby-badge')).not.toBeNull();
      expect(pStandbyTile.querySelector('.dt .parity-pill')).toBeNull();
    });

    it('groups parity drives under dedicated PARITY section ahead of DATA in renderDisks', () => {
      const disks = [
        { name: 'sda', role: 'data', is_parity: false, temp: 37, health: 'ok' },
        { name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: 34, health: 'ok' },
        { name: 'nvme0n1', role: 'cache', is_parity: false, temp: 42, health: 'ok' },
      ];

      renderDisks(disks);

      const row = document.getElementById('diskRow');
      const groups = row.querySelectorAll('.disk-group');
      expect(groups.length).toBe(3);

      // Group 0: PARITY
      expect(groups[0].dataset.role).toBe('parity');
      expect(groups[0].classList.contains('r-parity')).toBe(true);
      expect(groups[0].querySelector('.group-label').textContent).toContain('PARITY');
      expect(groups[0].querySelectorAll('.disk').length).toBe(1);
      expect(groups[0].querySelector('.disk .parity-pill')).toBeNull();

      // Group 1: DATA
      expect(groups[1].dataset.role).toBe('data');
      expect(groups[1].querySelector('.disk .parity-pill')).toBeNull();

      // Group 2: CACHE
      expect(groups[2].dataset.role).toBe('cache');

      // Test subsequent live updates (non-structural branch)
      const updatedDisks = [
        { name: 'sda', role: 'data', is_parity: false, temp: 39, health: 'ok' },
        { name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: 35, health: 'ok' },
        { name: 'nvme0n1', role: 'cache', is_parity: false, temp: 43, health: 'ok' },
      ];
      renderDisks(updatedDisks);

      const updatedParityTile = row.querySelector('[data-dev="sdb"]');
      expect(updatedParityTile.classList.contains('disk-is-parity')).toBe(true);
      expect(updatedParityTile.querySelector('.dt .parity-pill')).toBeNull();
      expect(updatedParityTile.querySelector('.dt-temp').textContent).toContain('35');
    });
  });

  describe('Streamline Drag-and-Drop Layout & In-Place Telemetry Suite', () => {
    it('reorders streamline deck and bay row in #screen and mini-preview when dashOrder changes', () => {
      setScreenLayoutStyle('streamline', false);
      state.dashOrder = ['metric-storage', 'metric-cpu', 'metric-mem', 'metric-fans', 'metric-net', 'metric-disks'];
      state.dashVis = {
        'metric-storage': true,
        'metric-cpu': true,
        'metric-mem': true,
        'metric-fans': true,
        'metric-net': true,
        'metric-disks': true
      };
      state.dashSizes = {};

      applyDashboardLayout();

      const screenDeck = document.querySelector('#screen .sl-main-deck');
      const miniDeck = document.querySelector('#mini-preview-inner .sl-main-deck');
      expect(screenDeck).not.toBeNull();
      expect(miniDeck).not.toBeNull();

      // Default order: storage, compute, ip
      let screenCards = Array.from(screenDeck.querySelectorAll('.sl-card')).map(c => c.dataset.metricId);
      expect(screenCards).toEqual(['metric-storage', 'metric-cpu', 'metric-net']);

      let miniCards = Array.from(miniDeck.querySelectorAll('.sl-card')).map(c => c.dataset.metricId);
      expect(miniCards).toEqual(['metric-storage', 'metric-cpu', 'metric-net']);

      // Change order: IP first, then COMPUTE, then STORAGE
      state.dashOrder = ['metric-net', 'metric-cpu', 'metric-storage', 'metric-disks'];
      applyDashboardLayout();

      screenCards = Array.from(screenDeck.querySelectorAll('.sl-card')).map(c => c.dataset.metricId);
      expect(screenCards).toEqual(['metric-net', 'metric-cpu', 'metric-storage']);

      miniCards = Array.from(miniDeck.querySelectorAll('.sl-card')).map(c => c.dataset.metricId);
      expect(miniCards).toEqual(['metric-net', 'metric-cpu', 'metric-storage']);

      // Change order: Disks first, then IP, COMPUTE, STORAGE
      state.dashOrder = ['metric-disks', 'metric-net', 'metric-cpu', 'metric-storage'];
      applyDashboardLayout();

      const screenBayRow = document.querySelector('#screen #sl-bay-row');
      const miniBayRow = document.querySelector('#mini-preview-inner .sl-bay-row');
      expect(screenBayRow.nextElementSibling).toBe(screenDeck);
      expect(miniBayRow.nextElementSibling).toBe(miniDeck);
    });

    it('supports drag-and-drop reordering of streamline cards and bay row in mini-preview-inner', () => {
      setScreenLayoutStyle('streamline', false);
      state.dashOrder = ['metric-storage', 'metric-cpu', 'metric-mem', 'metric-fans', 'metric-net', 'metric-disks'];
      applyDashboardLayout();

      const mini = document.getElementById('mini-preview-inner');
      const miniCards = mini.querySelectorAll('.sl-main-deck > .sl-card');
      expect(miniCards.length).toBe(3);

      const slStorage = miniCards[0]; // metric-storage
      const slCompute = miniCards[1]; // metric-cpu

      // Drag storage over compute and drop
      const dataStore = {};
      const dragStartEvt = new Event('dragstart', { bubbles: true });
      dragStartEvt.dataTransfer = {
        effectAllowed: '',
        setData: (k, v) => { dataStore[k] = v; },
        getData: (k) => dataStore[k]
      };
      slStorage.dispatchEvent(dragStartEvt);
      expect(slStorage.classList.contains('mini-dragging')).toBe(true);

      const dragOverEvt = new Event('dragover', { bubbles: true, cancelable: true });
      dragOverEvt.dataTransfer = { dropEffect: '' };
      slCompute.dispatchEvent(dragOverEvt);
      expect(slCompute.classList.contains('mini-drag-over')).toBe(true);

      const dropEvt = new Event('drop', { bubbles: true, cancelable: true });
      slCompute.dispatchEvent(dropEvt);

      // Verify state.dashOrder updated (storage swapped with compute)
      expect(state.dashOrder.indexOf('metric-cpu')).toBeLessThan(state.dashOrder.indexOf('metric-storage'));
      expect(api.post).toHaveBeenCalledWith('/api/layout', expect.objectContaining({
        order: state.dashOrder,
        style: 'streamline'
      }));

      // Now drag disk row onto a card to swap disks position
      const miniBayRow = mini.querySelector('.sl-bay-row');
      expect(miniBayRow).not.toBeNull();
      const diskDragStart = new Event('dragstart', { bubbles: true });
      diskDragStart.dataTransfer = {
        effectAllowed: '',
        setData: (k, v) => { dataStore[k] = v; },
        getData: (k) => dataStore[k]
      };
      miniBayRow.dispatchEvent(diskDragStart);
      expect(miniBayRow.classList.contains('mini-dragging')).toBe(true);

      const diskDropOnCard = new Event('drop', { bubbles: true, cancelable: true });
      slCompute.dispatchEvent(diskDropOnCard);

      // Disks should now be first
      expect(state.dashOrder.indexOf('metric-disks')).toBe(0);
      const updatedScreenBayRow = document.querySelector('#screen #sl-bay-row');
      const screenDeck = document.querySelector('#screen .sl-main-deck');
      expect(updatedScreenBayRow.nextElementSibling).toBe(screenDeck);
    });

    it('syncMiniPreviewTelemetry preserves drag listeners and updates streamline cards and bay row in-place', () => {
      setScreenLayoutStyle('streamline', false);
      applyDashboardLayout();

      const mini = document.getElementById('mini-preview-inner');
      const initialCompute = mini.querySelector('.sl-card-compute');
      const initialStorage = mini.querySelector('.sl-card-storage');
      const initialIp = mini.querySelector('.sl-card-ip');
      const slBayRowBefore = mini.querySelector('.sl-bay-row');
      expect(initialCompute).not.toBeNull();
      expect(initialStorage).not.toBeNull();
      expect(initialIp).not.toBeNull();
      expect(slBayRowBefore).not.toBeNull();

      // Trigger telemetry sync
      syncMiniPreviewTelemetry();

      // Crucial: Exact same DOM nodes must be preserved to keep event listeners intact
      expect(mini.querySelector('.sl-card-compute')).toBe(initialCompute);
      expect(mini.querySelector('.sl-card-storage')).toBe(initialStorage);
      expect(mini.querySelector('.sl-card-ip')).toBe(initialIp);
      expect(mini.querySelector('.sl-bay-row')).toBe(slBayRowBefore);

      // Update telemetry on screen
      const stats = {
        name: 'TEST-STREAMLINE',
        ip: '192.168.1.100',
        storage: { pct: 75, used: '3TB', total: '4TB' },
        cpu: { util: 50, temp: 48 },
        mem: { pct: 40, used: '8GB' },
        net: { tx: '1.2 MB/s', rx: '4.5 MB/s' },
        disks: [
          { name: 'sda', dev: '/dev/sda', temp: 33, health: 'ok' }
        ]
      };
      updateStreamlineLayout(stats, false);
      syncMiniPreviewTelemetry();

      // Mini preview inner elements should reflect updated text
      expect(mini.querySelector('.sl-hero-ip').textContent).toBe('192.168.1.100');
      expect(mini.querySelector('#sl-cpu-val, .sl-card-compute .sl-bar-val').textContent).toBe('50%');
      expect(mini.querySelector('#sl-storage-pct, .sl-card-storage .sl-donut-pct').textContent).toBe('75%');

      // Still the exact same DOM node references!
      expect(mini.querySelector('.sl-card-compute')).toBe(initialCompute);
      expect(mini.querySelector('.sl-card-storage')).toBe(initialStorage);
      expect(mini.querySelector('.sl-card-ip')).toBe(initialIp);
      expect(mini.querySelector('.sl-bay-row')).toBe(slBayRowBefore);
    });
  });
});
