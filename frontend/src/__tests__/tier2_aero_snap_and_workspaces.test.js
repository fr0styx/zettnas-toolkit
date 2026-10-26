import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getSnapGeometry,
  evaluateSnapZone,
  applyWindowSnap,
  restoreWindowSnap,
  getActiveWindowElement,
  getCurrentWorkspace,
  switchWorkspace,
  initWorkspaceSwitcher,
  initDockSystem,
  DockManager,
  NAVBAR_OFFSET,
  DOCK_MARGIN,
} from '../components/dock.js';
import {
  initSpotlight,
  openSpotlight,
  closeSpotlight,
  filterSpotlightResults,
  parseNaturalLanguageAction,
} from '../components/spotlight.js';
import {
  applyWidgetConfig,
  syncWidgetSettingsUI,
  initWidgets,
  loadWidgetConfig,
} from '../components/widgets.js';
import { ZettEventBus } from '../event-bus.js';

describe('Tier 2: Aero Snap 2.0, Single Desktop Invariant, Spotlight Actions & Modular Widgets', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <header class="suite-navbar">
        <div class="suite-brand">
          <div id="topbar-user-pill"></div>
        </div>
      </header>

      <div id="desktop-widgets-container" class="pos-top-right glass-standard scale-normal">
        <div class="desktop-widget" id="widget-clock" style="display:block;"></div>
        <div class="desktop-widget" id="widget-calendar" style="display:none;"></div>
        <div class="desktop-widget" id="widget-weather" style="display:block;"></div>
        <div class="desktop-widget" id="widget-system" style="display:block;"></div>
        <div class="desktop-widget" id="widget-network" style="display:block;"></div>
        <div class="desktop-widget" id="widget-storage" style="display:block;"></div>
        <div class="desktop-widget" id="widget-uptime" style="display:none;"></div>
        <div class="desktop-widget" id="widget-drive-temp" style="display:block;">
          <div class="widget-badge" id="w-drive-temp-summary">-- Disks</div>
          <div class="widget-drive-temp-grid" id="w-drive-temp-grid"></div>
        </div>
        <div class="desktop-widget" id="widget-net-dial" style="display:block;">
          <span class="widget-badge" id="w-net-dial-speed">2.5G</span>
          <path id="w-net-dial-arc" stroke-dasharray="0, 100"></path>
          <div id="w-net-dial-pct">0%</div>
          <span id="w-net-dial-rx">0 B/s</span>
          <span id="w-net-dial-tx">0 B/s</span>
        </div>
        <div class="desktop-widget" id="widget-ups-gauge" style="display:block;">
          <span class="widget-badge" id="w-ups-badge">ONLINE</span>
          <span id="w-ups-battery">100%</span>
          <div id="w-ups-bar" style="width:100%;"></div>
          <strong id="w-ups-load">-- W</strong>
          <strong id="w-ups-runtime">-- min</strong>
        </div>
      </div>

      <div id="widget-sortable-list">
        <div class="widget-sortable-item" data-widget-id="clock"><input type="checkbox" id="w-cfg-clock" checked></div>
        <div class="widget-sortable-item" data-widget-id="weather"><input type="checkbox" id="w-cfg-weather" checked></div>
        <div class="widget-sortable-item" data-widget-id="calendar"><input type="checkbox" id="w-cfg-calendar"></div>
        <div class="widget-sortable-item" data-widget-id="system"><input type="checkbox" id="w-cfg-system" checked></div>
        <div class="widget-sortable-item" data-widget-id="network"><input type="checkbox" id="w-cfg-network" checked></div>
        <div class="widget-sortable-item" data-widget-id="storage"><input type="checkbox" id="w-cfg-storage" checked></div>
        <div class="widget-sortable-item" data-widget-id="uptime"><input type="checkbox" id="w-cfg-uptime"></div>
        <div class="widget-sortable-item" data-widget-id="drive_temp"><input type="checkbox" id="w-cfg-drive-temp" checked></div>
        <div class="widget-sortable-item" data-widget-id="net_dial"><input type="checkbox" id="w-cfg-net-dial" checked></div>
        <div class="widget-sortable-item" data-widget-id="ups_gauge"><input type="checkbox" id="w-cfg-ups-gauge" checked></div>
      </div>

      <!-- Mock Windows across workspaces -->
      <div id="console-modal-overlay" class="modal-overlay">
        <div id="console-window" class="smart-modal-window active-window" data-window-id="console" style="z-index:1001;"></div>
      </div>
      <div id="management-modal-overlay" class="modal-overlay">
        <div id="management-window" class="mgmt-app-window" data-window-id="management" style="z-index:1000;"></div>
      </div>

      <div id="os-dock-container"><div id="os-dock"></div></div>
    `;

    window.innerWidth = 1440;
    window.innerHeight = 900;
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('1. Aero Snap 2.0 & Magnetic Window Tiling', () => {
    it('calculates 4-quadrant corner snap geometries correctly', () => {
      const quadrants = ['top-left', 'top-right', 'bottom-left', 'bottom-right'];
      quadrants.forEach((q) => {
        const geom = getSnapGeometry(q);
        expect(geom).not.toBeNull();
        expect(geom.width).toBeGreaterThan(300);
        expect(geom.height).toBeGreaterThan(200);
      });

      const tl = getSnapGeometry('top-left');
      const tr = getSnapGeometry('top-right');
      const bl = getSnapGeometry('bottom-left');
      const br = getSnapGeometry('bottom-right');

      expect(tl.top).toBe(tr.top);
      expect(bl.top).toBe(br.top);
      expect(tr.left).toBeGreaterThan(tl.left);
      expect(br.left).toBeGreaterThan(bl.left);
    });

    it('applies and restores window snaps cleanly', () => {
      const win = document.getElementById('console-window');
      applyWindowSnap(win, 'top-left', 'console');
      expect(win.dataset.snapped).toBe('top-left');

      restoreWindowSnap(win, 'console');
      expect(win.dataset.snapped).toBe('');
    });

    it('remembers the restored size after a maximize, not the maximized one', () => {
      const win = document.createElement('div');
      win.id = 'snap-size-test';
      document.body.appendChild(win);
      win._preSnapWidth = '520px';
      win._preSnapHeight = '320px';
      applyWindowSnap(win, 'maximize', 'snap-size-test');
      restoreWindowSnap(win, 'snap-size-test');
      const saved = JSON.parse(localStorage.getItem('zettnas_window_bounds_v2') || '{}')['snap-size-test'] || {};
      expect(saved.snapped).toBe('');
      expect(saved.width).toBe(520);
      expect(saved.height).toBe(320);
      expect(win._preSnapWidth).toBeNull();
      win.remove();
    });

    it('identifies the active frontmost window element', () => {
      const activeEl = getActiveWindowElement();
      expect(activeEl).toBeTruthy();
      expect(activeEl.id).toBe('console-window');
    });

    it('triggers keyboard shortcuts for Aero Snap 2.0', () => {
      initDockSystem();
      const win = document.getElementById('console-window');

      // Cmd+Option+Left -> Snap Left
      const evtLeft = new KeyboardEvent('keydown', {
        key: 'ArrowLeft',
        metaKey: true,
        altKey: true,
        bubbles: true,
      });
      window.dispatchEvent(evtLeft);
      expect(win.dataset.snapped).toBe('left');

      // Cmd+Option+Right -> Snap Right
      const evtRight = new KeyboardEvent('keydown', {
        key: 'ArrowRight',
        metaKey: true,
        altKey: true,
        bubbles: true,
      });
      window.dispatchEvent(evtRight);
      expect(win.dataset.snapped).toBe('right');

      // Cmd+Option+1 -> Top Left quadrant
      const evt1 = new KeyboardEvent('keydown', {
        key: '1',
        metaKey: true,
        altKey: true,
        bubbles: true,
      });
      window.dispatchEvent(evt1);
      expect(win.dataset.snapped).toBe('top-left');

      // Cmd+Option+Down -> Restore snap
      const evtDown = new KeyboardEvent('keydown', {
        key: 'ArrowDown',
        metaKey: true,
        altKey: true,
        bubbles: true,
      });
      window.dispatchEvent(evtDown);
      expect(win.dataset.snapped).toBe('');
    });
  });

  describe('2. Single Desktop Invariant & Removal of Workspaces', () => {
    it('ensures workspace switcher is absent and getCurrentWorkspace returns 1', () => {
      initWorkspaceSwitcher();
      expect(getCurrentWorkspace()).toBe(1);

      // Workspace switcher pills should not exist in the DOM
      const switcher = document.getElementById('desktop-workspace-switcher');
      expect(switcher).toBeNull();
      const pills = document.querySelectorAll('.workspace-pill');
      expect(pills.length).toBe(0);
    });

    it('switchWorkspace is a safe no-op that never hides open windows', () => {
      const consoleOverlay = document.getElementById('console-modal-overlay');
      const mgmtOverlay = document.getElementById('management-modal-overlay');

      switchWorkspace(2);
      expect(getCurrentWorkspace()).toBe(1);
      expect(consoleOverlay.classList.contains('workspace-hidden')).toBe(false);
      expect(mgmtOverlay.classList.contains('workspace-hidden')).toBe(false);

      switchWorkspace(3);
      expect(getCurrentWorkspace()).toBe(1);
      expect(consoleOverlay.classList.contains('workspace-hidden')).toBe(false);
      expect(mgmtOverlay.classList.contains('workspace-hidden')).toBe(false);

      switchWorkspace(1);
      expect(getCurrentWorkspace()).toBe(1);
      expect(consoleOverlay.classList.contains('workspace-hidden')).toBe(false);
      expect(mgmtOverlay.classList.contains('workspace-hidden')).toBe(false);
    });

    it('does not capture or hijack Ctrl+1..3 or Ctrl+Arrows navigation', () => {
      initDockSystem();

      const evtCtrl2 = new KeyboardEvent('keydown', {
        key: '2',
        ctrlKey: true,
        cancelable: true,
        bubbles: true,
      });
      window.dispatchEvent(evtCtrl2);
      expect(evtCtrl2.defaultPrevented).toBe(false);
      expect(getCurrentWorkspace()).toBe(1);

      const evtCtrlRight = new KeyboardEvent('keydown', {
        key: 'ArrowRight',
        ctrlKey: true,
        cancelable: true,
        bubbles: true,
      });
      window.dispatchEvent(evtCtrlRight);
      expect(evtCtrlRight.defaultPrevented).toBe(false);
      expect(getCurrentWorkspace()).toBe(1);
    });

    it('ensures modal dialogs like replication pipelines are never hidden by workspace switching', () => {
      const replBackdrop = document.createElement('div');
      replBackdrop.id = 'modal-create-replication-pipeline';
      replBackdrop.className = 'smart-modal-backdrop';
      const replWindow = document.createElement('div');
      replWindow.className = 'smart-modal-window';
      replBackdrop.appendChild(replWindow);
      document.body.appendChild(replBackdrop);

      // Attempting to switch workspaces does not affect visibility
      switchWorkspace(2);
      expect(replBackdrop.classList.contains('workspace-hidden')).toBe(false);
      expect(replWindow.classList.contains('workspace-hidden')).toBe(false);

      switchWorkspace(3);
      expect(replBackdrop.classList.contains('workspace-hidden')).toBe(false);
      expect(replWindow.classList.contains('workspace-hidden')).toBe(false);

      switchWorkspace(1);
      expect(replBackdrop.classList.contains('workspace-hidden')).toBe(false);
      expect(replWindow.classList.contains('workspace-hidden')).toBe(false);
    });
  });

  describe('3. Spotlight Natural Language Actions', () => {
    it('parses natural language snapshot commands (>snap pool <id>)', () => {
      const action = parseNaturalLanguageAction('>snap pool ark');
      expect(action).not.toBeNull();
      expect(action.title).toContain('Snapshot Pool: ark');
      expect(action.category).toBe('action');
    });

    it('parses natural language fan overrides (>fan quiet / turbo / <pct>%)', () => {
      const quietAction = parseNaturalLanguageAction('>fan quiet');
      expect(quietAction).not.toBeNull();
      expect(quietAction.title).toContain('Fan Acoustic Override: QUIET');

      const pctAction = parseNaturalLanguageAction('>fan 75%');
      expect(pctAction).not.toBeNull();
      expect(pctAction.title).toContain('75% PWM');
    });

    it('parses natural language drive locate and trash purge commands', () => {
      const locateAction = parseNaturalLanguageAction('>locate drive sda');
      expect(locateAction).not.toBeNull();
      expect(locateAction.title).toContain('Locate Drive: sda');

      const trashAction = parseNaturalLanguageAction('>trash empty');
      expect(trashAction).not.toBeNull();
      expect(trashAction.title).toBe('Empty the Recycle Bin');

      const isolateAction = parseNaturalLanguageAction('>isolate container jellyfin');
      expect(isolateAction).not.toBeNull();
      expect(isolateAction.title).toContain('Isolate Container: jellyfin');
    });

    it('integrates dynamic actions into filterSpotlightResults', () => {
      initSpotlight();
      openSpotlight();

      filterSpotlightResults('>fan 85%');
      const results = document.getElementById('spotlight-results');
      expect(results.textContent).toContain('85% PWM');
    });
  });

  describe('4. Modular Desktop Canvas Widgets (Drive Thermals, Net Dial, UPS)', () => {
    it('applies configuration visibility for all 3 new widgets', () => {
      const config = loadWidgetConfig();
      expect(config.widgets.drive_temp).toBe(true);
      expect(config.widgets.net_dial).toBe(true);
      expect(config.widgets.ups_gauge).toBe(true);

      applyWidgetConfig();
      expect(document.getElementById('widget-drive-temp').style.display).toBe('block');
      expect(document.getElementById('widget-net-dial').style.display).toBe('block');
      expect(document.getElementById('widget-ups-gauge').style.display).toBe('block');
    });

    it('syncs widget settings checkboxes accurately', () => {
      syncWidgetSettingsUI();
      expect(document.getElementById('w-cfg-drive-temp').checked).toBe(true);
      expect(document.getElementById('w-cfg-net-dial').checked).toBe(true);
      expect(document.getElementById('w-cfg-ups-gauge').checked).toBe(true);
    });

    it('renders real-time telemetry into drive heatmap, net dial, and UPS gauge', async () => {
      initWidgets();

      const mockStats = {
        disks: [
          { name: 'sda', bay: 1, temp: 32, standby: false },
          { name: 'sdb', bay: 2, temp: 42, standby: false },
          { name: 'sdc', bay: 3, temp: null, standby: true },
        ],
        net: {
          rx_rate: 10485760, // 10 MB/s
          tx_rate: 5242880,  // 5 MB/s
          speed: 2500,       // 2.5 Gbps
        },
        ups: {
          battery_charge: 98,
          load_wattage: 54,
          runtime_seconds: 3600,
          status: 'OL',
        },
      };

      ZettEventBus.emit('stats:updated', mockStats);
      await new Promise((resolve) => requestAnimationFrame(resolve));

      // Check Drive Heatmap
      const grid = document.getElementById('w-drive-temp-grid');
      expect(grid.children.length).toBe(3);
      expect(grid.innerHTML).toContain('Bay 1');
      expect(grid.innerHTML).toContain('32°C');
      expect(grid.innerHTML).toContain('Bay 3');
      expect(grid.innerHTML).toContain('SLEEP');

      // Check Net Dial
      const pct = document.getElementById('w-net-dial-pct');
      expect(pct.textContent).not.toBe('0%');
      const rx = document.getElementById('w-net-dial-rx');
      expect(rx.textContent).toContain('MB/s');

      // Check UPS Gauge
      const upsBat = document.getElementById('w-ups-battery');
      expect(upsBat.textContent).toBe('98%');
      const upsLoad = document.getElementById('w-ups-load');
      expect(upsLoad.textContent).toBe('54 W');
      const upsRuntime = document.getElementById('w-ups-runtime');
      expect(upsRuntime.textContent).toBe('60 min');
      const upsBadge = document.getElementById('w-ups-badge');
      expect(upsBadge.textContent).toBe('ONLINE');
    });
  });
});
