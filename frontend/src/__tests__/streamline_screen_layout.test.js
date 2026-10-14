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
import fs from 'fs';
import path from 'path';

describe('Streamline Minimalist / Big IP Screen Layout Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', layout: { version: 1 } });
    state.screenLayoutStyle = 'classic';
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
            <div class="sl-zone-storage" id="sl-zone-storage">
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

            <div class="sl-zone-compute">
              <div class="sl-bar-row" id="sl-cpu-row">
                <div class="sl-bar-header">
                  <span class="sl-bar-label">CPU</span>
                  <span class="sl-bar-val" id="sl-cpu-val">0%</span>
                </div>
                <div class="sl-bar-track">
                  <div class="sl-bar-fill sl-fill-cpu" id="sl-cpu-bar" style="width: 0%"></div>
                </div>
              </div>
              <div class="sl-bar-row" id="sl-mem-row">
                <div class="sl-bar-header">
                  <span class="sl-bar-label">Memory</span>
                  <span class="sl-bar-val" id="sl-mem-val">0%</span>
                </div>
                <div class="sl-bar-track">
                  <div class="sl-bar-fill sl-fill-mem" id="sl-mem-bar" style="width: 0%"></div>
                </div>
              </div>
            </div>

            <div class="sl-zone-ip">
              <span class="sl-ip-label">IP:</span>
              <div class="sl-hero-ip" id="sl-hero-ip">0.0.0.0</div>
            </div>
          </div>

          <div class="sl-bay-row" id="sl-bay-row"></div>
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
    expect(document.getElementById('sl-cpu-bar').style.width).toBe('4%');

    expect(document.getElementById('sl-mem-val').textContent).toBe('18%');
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
    chips[1].click();
    expect(confirmToastSpy).toHaveBeenCalledWith(
      'Drive in Standby Mode',
      expect.stringContaining('currently sleeping'),
      expect.any(Function)
    );
    expect(smartEventSpy).not.toHaveBeenCalled();
  });

  it('delegates interactive clicks from streamline storage, CPU, and Memory zones to metrics modal', () => {
    initDashboardClicks();

    const metricEventSpy = vi.fn();
    ZettEventBus.on('modal:metric:open', metricEventSpy);

    document.getElementById('sl-zone-storage').click();
    expect(metricEventSpy.mock.calls[0][0]).toBe('storage');

    document.getElementById('sl-cpu-row').click();
    expect(metricEventSpy.mock.calls[1][0]).toBe('cpu');

    document.getElementById('sl-mem-row').click();
    expect(metricEventSpy.mock.calls[2][0]).toBe('mem');
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
    const styleCss = fs.readFileSync(path.resolve(__dirname, '../style.css'), 'utf-8');
    const lcdDirectCss = fs.readFileSync(path.resolve(__dirname, '../lcd-direct.css'), 'utf-8');

    // In style.css, streamline layout hides classic header, cards, diskRow
    expect(styleCss).toContain('#screen.layout-streamline > header');
    expect(styleCss).toContain('#screen.layout-streamline #dashboard-cards-container');
    expect(styleCss).toContain('#screen.layout-streamline #diskRow');
    expect(styleCss).toContain('#screen.layout-streamline #streamline-container');

    // In lcd-direct.css, physical 172x640 panel overrides ensure streamline mode is applied
    expect(lcdDirectCss).toContain('body.lcd-direct #screen.layout-streamline');
    expect(lcdDirectCss).toContain('body.lcd-direct #screen.layout-streamline #streamline-container');
  });

  describe('Parity Drive Pill & Tag Identification (Classic & Streamline)', () => {
    it('renders orange parity tag [P] or [P2] inside streamline bay chips', () => {
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
      const tag0 = chips[0].querySelector('.sl-parity-tag');
      expect(tag0).not.toBeNull();
      expect(tag0.textContent).toBe('P');
      expect(chips[0].title).toContain('[PARITY]');

      // sdc: Parity 2
      expect(chips[1].classList.contains('chip-parity')).toBe(true);
      const tag1 = chips[1].querySelector('.sl-parity-tag');
      expect(tag1).not.toBeNull();
      expect(tag1.textContent).toBe('P2');

      // sda: Data drive (no parity tag)
      expect(chips[2].classList.contains('chip-parity')).toBe(false);
      expect(chips[2].querySelector('.sl-parity-tag')).toBeNull();

      // Test subsequent live updates (non-structural branch)
      const updatedDisks = [
        { name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: 36, health: 'ok' },
        { name: 'sdc', role: 'parity', is_parity: true, parity_label: 'P2', temp: 36, health: 'ok' },
        { name: 'sda', role: 'data', is_parity: false, temp: 38, health: 'ok' },
      ];
      updateStreamlineBayChips(updatedDisks);

      expect(chips[0].querySelector('.sl-parity-tag').textContent).toBe('P');
      expect(chips[1].querySelector('.sl-parity-tag').textContent).toBe('P2');
      expect(chips[2].querySelector('.sl-parity-tag')).toBeNull();
    });

    it('renders orange parity pill [P] at lower end of disk tile in Classic Cards', () => {
      const pTile = diskTile({ name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: 34, health: 'ok' });
      expect(pTile.classList.contains('disk-is-parity')).toBe(true);
      expect(pTile.classList.contains('r-parity')).toBe(true);
      expect(pTile.title).toContain('[PARITY]');

      const pill = pTile.querySelector('.dt .parity-pill');
      expect(pill).not.toBeNull();
      expect(pill.textContent).toBe('P');

      // Parity drive in standby mode still shows parity pill alongside standby badge
      const pStandbyTile = diskTile({ name: 'sdb', role: 'parity', is_parity: true, parity_label: 'P', temp: null, health: 'standby', standby: true });
      expect(pStandbyTile.classList.contains('disk-is-parity')).toBe(true);
      expect(pStandbyTile.querySelector('.dt .standby-badge')).not.toBeNull();
      expect(pStandbyTile.querySelector('.dt .parity-pill').textContent).toBe('P');
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
      expect(groups[0].querySelector('.disk .parity-pill').textContent).toBe('P');

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
      expect(updatedParityTile.querySelector('.dt .parity-pill').textContent).toBe('P');
      expect(updatedParityTile.querySelector('.dt-temp').textContent).toContain('35');
    });
  });
});
