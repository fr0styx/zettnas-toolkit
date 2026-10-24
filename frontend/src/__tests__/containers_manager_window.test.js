import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initContainersManager,
  openContainersManager,
  renderContainersWindowTable,
  loadContainersData,
  startCwAutoRefresh,
  stopCwAutoRefresh,
  _resetCwAutoRefreshForTesting,
  CW_WATCHDOG_MS
} from '../components/containers-manager.js';
import { DockManager } from '../components/dock.js';
import { ZettEventBus } from '../event-bus.js';
import { api } from '../api.js';

describe('Dedicated Containers Window & Desktop Icon Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="os-dock-container">
        <div id="os-dock"></div>
      </div>
      <div class="desktop-icons-container" id="desktop-icons-container">
        <div class="chassis-hero-box chassis-desktop-icon containers-desktop-icon" id="containers-desktop-icon" role="button" tabindex="0" title="Click to open Containers">
          <div class="console-hero-box"><svg class="console-hero-icon"></svg></div>
          <div class="desktop-icon-label">
            <span class="icon-dot-status icon-dot-containers"></span>
            <span class="icon-text">Containers</span>
          </div>
        </div>
      </div>
      <div id="mgmt-pane-docker">
        <button class="btn-pill-toggle" id="btn-mgmt-docker-launch-window">Open Window</button>
      </div>
    `;
    window._containersManagerInitialized = false;
    window.DockManager = DockManager;
    DockManager.windows = {};
    _resetCwAutoRefreshForTesting();
  });

  afterEach(() => {
    stopCwAutoRefresh();
    _resetCwAutoRefreshForTesting();
    vi.restoreAllMocks();
  });

  it('initContainersManager injects #containers-manager-window and attaches desktop icon listeners', () => {
    initContainersManager();
    const win = document.getElementById('containers-manager-window');
    expect(win).not.toBeNull();
    expect(win.classList.contains('containers-manager-window')).toBe(true);
    expect(win.style.display).toBe('none');

    // Desktop icon click launches window
    const openSpy = vi.fn();
    ZettEventBus.on('window:open', (data) => openSpy(data));

    const icon = document.getElementById('containers-desktop-icon');
    icon.click();

    expect(win.style.display).toBe('flex');
    expect(openSpy).toHaveBeenCalledWith(expect.objectContaining({ id: 'containers-manager-window' }));
  });

  it('registers "containers" in DockManager on open and allows minimize/restore', () => {
    initContainersManager();
    const win = document.getElementById('containers-manager-window');

    openContainersManager();
    expect(win.style.display).toBe('flex');
    expect(DockManager.windows['containers']).toBeDefined();

    // Minimize via header button
    const minBtn = document.getElementById('containers-min');
    expect(minBtn).not.toBeNull();
    minBtn.click();

    expect(win.style.display).toBe('none');
    expect(win.classList.contains('window-minimized')).toBe(true);

    // Restore via DockManager
    DockManager.restore('containers');
    expect(win.style.display).not.toBe('none');
    expect(win.classList.contains('window-minimized')).toBe(false);
  });

  it('window close button closes window and hides it', () => {
    initContainersManager();
    const win = document.getElementById('containers-manager-window');

    openContainersManager();
    expect(win.style.display).toBe('flex');

    const closeBtn = document.getElementById('containers-close');
    expect(closeBtn).not.toBeNull();
    closeBtn.click();

    expect(win.style.display).toBe('none');
    expect(win.classList.contains('window-minimized')).toBe(true);
  });

  it('window maximize button toggles full screen bounds', () => {
    initContainersManager();
    const win = document.getElementById('containers-manager-window');
    openContainersManager();

    const maxBtn = document.getElementById('containers-max');
    expect(maxBtn).not.toBeNull();

    maxBtn.click();
    expect(win.style.width).toBe('100vw');
    expect(win.style.left).toBe('0px');

    maxBtn.click();
    expect(win.style.width).not.toBe('100vw');
  });

  it('renders container telemetry badges and container table rows correctly', () => {
    initContainersManager();
    const sampleContainers = [
      {
        id: 'c123456789012',
        name: 'plex',
        image: 'lscr.io/linuxserver/plex:latest',
        state: 'running',
        status: 'Up 4 days',
        cpu_pct: 1.5,
        mem_used: 512 * 1024 * 1024,
        primary_port: 32400,
        webui_url: 'http://[HOST]:32400/web',
        managed_by: 'standalone',
        hardware_badges: [{ id: 'gpu', label: 'Intel QSV' }],
        ports: [{ public_port: 32400, private_port: 32400 }]
      },
      {
        id: 'c987654321098',
        name: 'nextcloud',
        image: 'nextcloud:apache',
        state: 'exited',
        status: 'Exited (0) 2 hours ago',
        cpu_pct: 0,
        mem_used: 0,
        primary_port: 8080,
        managed_by: 'compose',
        stack: 'cloud-suite',
        ports: [{ public_port: 8080, private_port: 80 }]
      }
    ];

    renderContainersWindowTable(sampleContainers);

    const countAll = document.getElementById('cw-count-all');
    const countRunning = document.getElementById('cw-count-running');
    const countStopped = document.getElementById('cw-count-stopped');
    expect(countAll.textContent).toBe('2');
    expect(countRunning.textContent).toBe('1');
    expect(countStopped.textContent).toBe('1');

    const tbody = document.getElementById('cw-docker-containers-tbody');
    expect(tbody.querySelectorAll('tr').length).toBe(2);
    expect(tbody.textContent).toContain('plex');
    expect(tbody.textContent).toContain('nextcloud');
    expect(tbody.textContent).toContain('cloud-suite');
  });

  it('filters containers when filter pills are clicked', () => {
    initContainersManager();
    const sampleContainers = [
      { id: '1', name: 'app-running', state: 'running', status: 'Up 1 day', ports: [] },
      { id: '2', name: 'app-stopped', state: 'exited', status: 'Exited', ports: [] },
      { id: '3', name: 'app-compose', state: 'running', status: 'Up', managed_by: 'compose', stack: 'my-stack', ports: [] },
    ];

    renderContainersWindowTable(sampleContainers);
    const tbody = document.getElementById('cw-docker-containers-tbody');
    expect(tbody.querySelectorAll('tr').length).toBe(3);

    // Click 'Running' filter
    const runBtn = document.querySelector('.cw-filter-btn[data-filter="running"]');
    runBtn.click();
    expect(tbody.querySelectorAll('tr').length).toBe(2);
    expect(tbody.textContent).not.toContain('app-stopped');

    // Click 'Stopped' filter
    const stopBtn = document.querySelector('.cw-filter-btn[data-filter="stopped"]');
    stopBtn.click();
    expect(tbody.querySelectorAll('tr').length).toBe(1);
    expect(tbody.textContent).toContain('app-stopped');

    // Click 'Stacks' filter
    const stackBtn = document.querySelector('.cw-filter-btn[data-filter="compose"]');
    stackBtn.click();
    expect(tbody.querySelectorAll('tr').length).toBe(1);
    expect(tbody.textContent).toContain('app-compose');

    // Click 'All'
    const allBtn = document.querySelector('.cw-filter-btn[data-filter="all"]');
    allBtn.click();
    expect(tbody.querySelectorAll('tr').length).toBe(3);
  });

  it('searches containers via search input', () => {
    initContainersManager();
    const sampleContainers = [
      { id: '1', name: 'vaultwarden', image: 'vaultwarden/server:latest', state: 'running', ports: [{ public_port: 8000 }] },
      { id: '2', name: 'heimdall', image: 'linuxserver/heimdall', state: 'running', ports: [{ public_port: 8081 }] }
    ];

    renderContainersWindowTable(sampleContainers);
    const tbody = document.getElementById('cw-docker-containers-tbody');
    const searchInput = document.getElementById('cw-docker-search-input');

    searchInput.value = 'vault';
    searchInput.dispatchEvent(new Event('input'));

    expect(tbody.querySelectorAll('tr').length).toBe(1);
    expect(tbody.textContent).toContain('vaultwarden');
    expect(tbody.textContent).not.toContain('heimdall');

    // Clear search
    searchInput.value = '';
    searchInput.dispatchEvent(new Event('input'));
    expect(tbody.querySelectorAll('tr').length).toBe(2);
  });

  it('loadContainersData fetches containers from /api/docker/containers', async () => {
    initContainersManager();
    const mockContainers = [
      { id: '101', name: 'nginx-proxy', state: 'running', status: 'Up 3 days', ports: [] }
    ];
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockContainers);

    await loadContainersData();
    expect(api.get).toHaveBeenCalledWith('/api/docker/containers');

    const tbody = document.getElementById('cw-docker-containers-tbody');
    expect(tbody.textContent).toContain('nginx-proxy');
  });

  it('keyboard Enter / Space on desktop icon opens dedicated window', () => {
    initContainersManager();
    const win = document.getElementById('containers-manager-window');
    const icon = document.getElementById('containers-desktop-icon');

    expect(win.style.display).toBe('none');

    icon.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(win.style.display).toBe('flex');

    win.style.display = 'none';
    icon.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }));
    expect(win.style.display).toBe('flex');
  });

  it('btn-mgmt-docker-launch-window opens dedicated containers window', () => {
    initContainersManager();
    const win = document.getElementById('containers-manager-window');
    expect(win.style.display).toBe('none');

    const launchBtn = document.getElementById('btn-mgmt-docker-launch-window');
    launchBtn.addEventListener('click', () => {
      if (typeof window.openContainersManager === 'function') window.openContainersManager();
    });

    launchBtn.click();
    expect(win.style.display).toBe('flex');
  });

  it('app catalog button toggles between containers table and in-window app catalog', () => {
    initContainersManager();

    const catalogBtn = document.getElementById('btn-cw-catalog');
    const tableWrap = document.querySelector('.cw-docker-table-wrap');
    const catalogWrap = document.getElementById('cw-docker-catalog-wrap');

    expect(catalogWrap.style.display).toBe('none');
    catalogBtn.click();
    expect(tableWrap.style.display).toBe('none');
    expect(catalogWrap.style.display).toBe('flex');

    catalogBtn.click();
    expect(tableWrap.style.display).toBe('block');
    expect(catalogWrap.style.display).toBe('none');
  });

  it('renders live sync status chip and has no manual refresh button in toolbar', () => {
    initContainersManager();
    const refreshBtn = document.getElementById('btn-cw-refresh');
    expect(refreshBtn).toBeNull();

    const statusChip = document.querySelector('.cw-docker-status-chip');
    expect(statusChip).not.toBeNull();
    expect(statusChip.textContent).toContain('Docker Socket Active');
    expect(statusChip.textContent).toContain('Live Sync');
  });

  it('btn-cw-stacks handles direct array response from /api/docker/stacks and opens picker modal', async () => {
    initContainersManager();
    const mockStacks = [
      { name: 'arr', origin: 'compose', working_dir: '/mnt/user/appdata/arr', total_count: 5, running_count: 5, services: ['radarr', 'sonarr'] },
      { name: 'immich', origin: 'compose', working_dir: '/mnt/user/appdata/immich', total_count: 2, running_count: 2, services: ['web', 'db'] }
    ];

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/docker/stacks') return mockStacks;
      return [];
    });

    const btnStacks = document.getElementById('btn-cw-stacks');
    expect(btnStacks).not.toBeNull();

    await btnStacks.onclick();

    const overlay = document.getElementById('stack-picker-overlay');
    expect(overlay).not.toBeNull();
    expect(overlay.style.display).toBe('flex');
    expect(overlay.querySelector('#stack-picker-badge').textContent).toBe('2 Stacks');
    const cards = overlay.querySelectorAll('.stack-picker-card');
    expect(cards.length).toBe(2);
    expect(cards[0].textContent).toContain('arr');
    expect(cards[1].textContent).toContain('immich');
  });

  it('does not poll /api/docker/containers while the SSE stream is live', async () => {
    vi.useFakeTimers();
    _resetCwAutoRefreshForTesting();
    initContainersManager();
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue([]);
    openContainersManager();
    const containerCalls = () => getSpy.mock.calls.filter((c) => c[0] === '/api/docker/containers').length;
    const afterOpen = containerCalls();

    // Real SSE ticks every 1-2 s; simulate a minute of live stream.
    for (let i = 0; i < 30; i++) {
      ZettEventBus.emit('stats:updated', { docker: [] });
      await vi.advanceTimersByTimeAsync(2000);
    }
    expect(containerCalls()).toBe(afterOpen);

    stopCwAutoRefresh();
    vi.useRealTimers();
  });

  it('falls back to HTTP when the SSE stream goes quiet, and pauses on minimize', async () => {
    vi.useFakeTimers();
    _resetCwAutoRefreshForTesting();
    initContainersManager();
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue([]);
    openContainersManager();
    const containerCalls = () => getSpy.mock.calls.filter((c) => c[0] === '/api/docker/containers').length;
    const afterOpen = containerCalls();

    await vi.advanceTimersByTimeAsync(CW_WATCHDOG_MS);
    expect(containerCalls()).toBe(afterOpen + 1);

    document.getElementById('containers-min').click();
    const beforeMin = containerCalls();
    await vi.advanceTimersByTimeAsync(CW_WATCHDOG_MS * 3);
    expect(containerCalls()).toBe(beforeMin);

    stopCwAutoRefresh();
    vi.useRealTimers();
  });

  it('fetches update status on open and then about once a minute', async () => {
    vi.useFakeTimers();
    _resetCwAutoRefreshForTesting();
    initContainersManager();
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ updates_available_count: 0 });
    openContainersManager();
    const statusCalls = () => getSpy.mock.calls.filter((c) => c[0] === '/api/docker/updates/status').length;
    expect(statusCalls()).toBe(1);

    for (let i = 0; i < 4; i++) {
      ZettEventBus.emit('stats:updated', { docker: [] });
      await vi.advanceTimersByTimeAsync(CW_WATCHDOG_MS);
    }
    expect(statusCalls()).toBe(2);

    stopCwAutoRefresh();
    vi.useRealTimers();
  });
});




describe("Apps window update badges", () => {
  it("drops an updated container from the Updates list at once", async () => {
    const mod = await import("../components/containers-manager.js");
    document.body.innerHTML = `<span id="cw-count-updates-wrap"><span id="cw-count-updates">2</span></span>
      <button id="btn-cw-filter-updates"><span id="cw-pill-updates">2</span></button>
      <button id="btn-cw-update-all"><span id="cw-updates-count-badge">2</span></button>`;
    const dozzle = { name: "dozzle", id: "8b7b", has_update: true };
    mod._setCwUpdatesCacheForTesting({ updates_available_count: 2, containers: { dozzle, "8b7b": dozzle, other: { has_update: true } } });
    mod.markCwContainerUpdated("dozzle", "8b7b");
    expect(dozzle.has_update).toBe(false);
    expect(document.getElementById("cw-pill-updates").textContent).toBe("1");
    mod.markCwContainerUpdated("dozzle", "8b7b"); // already up to date: no change
    expect(document.getElementById("cw-pill-updates").textContent).toBe("1");
    mod.markCwContainerUpdated("other");
    expect(document.getElementById("btn-cw-filter-updates").style.display).toBe("none");
    mod._setCwUpdatesCacheForTesting(null);
    expect(() => mod.markCwContainerUpdated("x")).not.toThrow();
  });
});
