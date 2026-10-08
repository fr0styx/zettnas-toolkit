import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fetchAndRenderDockerContainers, renderDockerContainersTable, _resetDockerStateForTesting } from '../components/management.js';
import { api } from '../api.js';

describe('Docker Container Subsystem - Phase 1 Frontend', () => {
  beforeEach(() => {
    _resetDockerStateForTesting();
    document.body.innerHTML = `
      <div id="mgmt-pane-docker">
        <button class="btn-pill-toggle docker-filter-btn active" data-filter="all">All <span id="docker-count-all">0</span></button>
        <button class="btn-pill-toggle docker-filter-btn" data-filter="running">Running <span id="docker-count-running">0</span></button>
        <button class="btn-pill-toggle docker-filter-btn" data-filter="stopped">Stopped <span id="docker-count-stopped">0</span></button>
        <button class="btn-pill-toggle docker-filter-btn" data-filter="compose">Compose <span id="docker-count-compose">0</span></button>
        <button class="btn-pill-toggle docker-filter-btn" data-filter="standalone">Standalone <span id="docker-count-standalone">0</span></button>
        <input type="text" id="docker-search-input" value="">
        <span id="mgmt-hub-docker-pill">0 Active</span>
        <span id="mgmt-sidebar-docker-badge">0 Active</span>
        <table>
          <tbody id="docker-containers-tbody"></tbody>
        </table>
      </div>
    `;
    vi.restoreAllMocks();
  });

  const mockContainers = [
    {
      id: 'c11122233344',
      name: 'jellyfin',
      image: 'lscr.io/linuxserver/jellyfin:latest',
      state: 'running',
      status: 'Up 3 days',
      cpu_pct: 2.4,
      mem_used: 1153433600, // ~1100 MB
      stack: 'arr',
      service: 'jellyfin',
      managed_by: 'compose',
      primary_port: 8096,
      webui_url: 'http://[HOST]:8096/',
      ports: [{ public_port: 8096, private_port: 8096, type: 'tcp' }],
      hardware_badges: [{ id: 'gpu', label: 'GPU' }, { id: 'nvidia', label: 'NVIDIA' }],
    },
    {
      id: 'c55566677788',
      name: 'dockhand',
      image: 'finsys/dockhand:latest',
      state: 'running',
      status: 'Up 1 day',
      cpu_pct: 0.5,
      mem_used: 209715200, // 200 MB
      stack: null,
      service: null,
      managed_by: 'standalone',
      primary_port: 3000,
      webui_url: 'http://[HOST]:3000/',
      ports: [{ public_port: 3000, private_port: 3000, type: 'tcp' }],
      hardware_badges: [],
    },
    {
      id: 'c99900011122',
      name: 'unraid-kernel-builder',
      image: 'custom/builder:latest',
      state: 'exited',
      status: 'Exited (0) 5 hours ago',
      cpu_pct: 0.0,
      mem_used: 0,
      stack: null,
      service: null,
      managed_by: 'standalone',
      primary_port: null,
      webui_url: null,
      ports: [],
      hardware_badges: [],
    }
  ];

  it('renders all containers with WebUI button, hardware badges, telemetry, and stack badge', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockContainers);

    await fetchAndRenderDockerContainers();

    const tbody = document.getElementById('docker-containers-tbody');
    expect(tbody).not.toBeNull();
    const rows = tbody.querySelectorAll('tr');
    expect(rows.length).toBe(3);

    // Check counts
    expect(document.getElementById('docker-count-all').textContent).toBe('3');
    expect(document.getElementById('docker-count-running').textContent).toBe('2');
    expect(document.getElementById('docker-count-stopped').textContent).toBe('1');
    expect(document.getElementById('docker-count-compose').textContent).toBe('1');
    expect(document.getElementById('docker-count-standalone').textContent).toBe('2');

    // Jellyfin row checks
    const jellyfinRow = rows[0];
    expect(jellyfinRow.innerHTML).toContain('jellyfin');
    expect(jellyfinRow.innerHTML).toContain('📁 arr');
    expect(jellyfinRow.innerHTML).toContain('docker-hw-gpu');
    expect(jellyfinRow.innerHTML).toContain('docker-hw-nvidia');
    expect(jellyfinRow.innerHTML).toContain('2.4%');
    expect(jellyfinRow.innerHTML).toContain('1100 MB');
    expect(jellyfinRow.innerHTML).toContain('btn-webui-badge');
    expect(jellyfinRow.innerHTML).toContain(':8096');
  });

  it('filters containers when clicking filter pills', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
    await fetchAndRenderDockerContainers();

    // Click "Running"
    const btnRunning = document.querySelector('.docker-filter-btn[data-filter="running"]');
    btnRunning.click();

    let rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
    expect(rows.length).toBe(2);
    expect(rows[0].innerHTML).toContain('jellyfin');
    expect(rows[1].innerHTML).toContain('dockhand');

    // Click "Stopped"
    const btnStopped = document.querySelector('.docker-filter-btn[data-filter="stopped"]');
    btnStopped.click();

    rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
    expect(rows.length).toBe(1);
    expect(rows[0].innerHTML).toContain('unraid-kernel-builder');

    // Click "Compose"
    const btnCompose = document.querySelector('.docker-filter-btn[data-filter="compose"]');
    btnCompose.click();

    rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
    expect(rows.length).toBe(1);
    expect(rows[0].innerHTML).toContain('jellyfin');
  });

  it('searches and filters containers by text input', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
    await fetchAndRenderDockerContainers();

    const searchInput = document.getElementById('docker-search-input');

    // Search by port number '3000'
    searchInput.value = '3000';
    searchInput.dispatchEvent(new Event('input'));

    let rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
    expect(rows.length).toBe(1);
    expect(rows[0].innerHTML).toContain('dockhand');

    // Search by stack name 'arr'
    searchInput.value = 'arr';
    searchInput.dispatchEvent(new Event('input'));

    rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
    expect(rows.length).toBe(1);
    expect(rows[0].innerHTML).toContain('jellyfin');

    // Search for non-existent container
    searchInput.value = 'nonexistent_service';
    searchInput.dispatchEvent(new Event('input'));

    rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toContain('No containers match your search or filter.');
  });
});
