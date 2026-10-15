import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initContainersManager,
  openContainersManager,
  renderContainersWindowTable,
  loadContainersData
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
  });

  afterEach(() => {
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
});


