import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  fetchAndRenderDockerContainers,
  renderDockerContainersTable,
  _resetDockerStateForTesting,
  setDockerSort,
  getDockerSort,
  sortDockerContainers,
  getContainerPortSortValue,
  getContainerStatusRank,
} from '../components/management.js';
import { api } from '../api.js';

describe('Docker Container Table Column Sorting Suite', () => {
  const mockContainers = [
    {
      id: 'c_jellyfin',
      name: 'jellyfin',
      image: 'lscr.io/linuxserver/jellyfin:latest',
      state: 'running',
      status: 'Up 3 days',
      cpu_pct: 24.5,
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
      id: 'c_dockhand',
      name: 'dockhand',
      image: 'finsys/dockhand:latest',
      state: 'running',
      status: 'Up 1 day',
      cpu_pct: 1.2,
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
      id: 'c_qbittorrent',
      name: 'qbittorrent',
      image: 'lscr.io/linuxserver/qbittorrent:latest',
      state: 'running',
      status: 'Up 5 hours',
      cpu_pct: 12.0,
      mem_used: 524288000, // 500 MB
      stack: 'arr',
      service: 'qbittorrent',
      managed_by: 'compose',
      primary_port: 8080,
      webui_url: 'http://[HOST]:8080/',
      ports: [{ public_port: 8080, private_port: 8080, type: 'tcp' }],
      hardware_badges: [],
    },
    {
      id: 'c_unraid_builder',
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
    },
    {
      id: 'c_immich_ml',
      name: 'immich_machine_learning',
      image: 'ghcr.io/immich-app/immich-machine-learning:latest',
      state: 'exited',
      status: 'Exited (143) 25 hours ago',
      cpu_pct: 0.0,
      mem_used: 0,
      stack: 'immich-prod',
      service: 'immich-machine-learning',
      managed_by: 'compose',
      primary_port: null,
      webui_url: null,
      ports: [],
      hardware_badges: [{ id: 'nvidia', label: 'NVIDIA' }],
    }
  ];

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
        <table class="copy-history-table docker-table responsive-cards">
          <thead>
            <tr>
              <th class="sortable-th" data-sort-col="name" role="columnheader" aria-sort="none" tabindex="0">
                <span>Name / Stack</span><span class="docker-sort-indicator"></span>
              </th>
              <th class="sortable-th" data-sort-col="hardware" role="columnheader" aria-sort="none" tabindex="0">
                <span>Hardware</span><span class="docker-sort-indicator"></span>
              </th>
              <th class="sortable-th" data-sort-col="cpu" role="columnheader" aria-sort="none" tabindex="0">
                <span>CPU / RAM</span><span class="docker-sort-indicator"></span>
              </th>
              <th class="sortable-th" data-sort-col="ports" role="columnheader" aria-sort="none" tabindex="0">
                <span>Ports & Web UI</span><span class="docker-sort-indicator"></span>
              </th>
              <th class="sortable-th" data-sort-col="status" role="columnheader" aria-sort="none" tabindex="0">
                <span>Status & Uptime</span><span class="docker-sort-indicator"></span>
              </th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody id="docker-containers-tbody"></tbody>
        </table>
      </div>
    `;
    vi.restoreAllMocks();
  });

  it('helper functions extract correct port and status rank values', () => {
    expect(getContainerPortSortValue(mockContainers[0])).toBe(8096);
    expect(getContainerPortSortValue(mockContainers[1])).toBe(3000);
    expect(getContainerPortSortValue(mockContainers[3])).toBe(0);

    expect(getContainerStatusRank(mockContainers[0])).toBe(3); // running
    expect(getContainerStatusRank(mockContainers[3])).toBe(0); // exited
    expect(getContainerStatusRank({ state: 'restarting' })).toBe(2);
    expect(getContainerStatusRank({ state: 'paused' })).toBe(1);
  });

  describe('sortDockerContainers pure sorting comparator', () => {
    it('sorts by Name / Stack ascending and descending', () => {
      const items = [...mockContainers];
      sortDockerContainers(items, 'name', 'asc');
      const namesAsc = items.map((c) => c.name);
      expect(namesAsc).toEqual([
        'dockhand',
        'immich_machine_learning',
        'jellyfin',
        'qbittorrent',
        'unraid-kernel-builder'
      ]);

      sortDockerContainers(items, 'name', 'desc');
      const namesDesc = items.map((c) => c.name);
      expect(namesDesc).toEqual([
        'unraid-kernel-builder',
        'qbittorrent',
        'jellyfin',
        'immich_machine_learning',
        'dockhand'
      ]);
    });

    it('sorts by Hardware descending (hardware-accelerated containers first)', () => {
      const items = [...mockContainers];
      sortDockerContainers(items, 'hardware', 'desc');
      // Containers with hardware badges (jellyfin: GPU NVIDIA, immich_ml: NVIDIA) must come first
      expect(items[0].hardware_badges.length).toBeGreaterThan(0);
      expect(items[1].hardware_badges.length).toBeGreaterThan(0);
      // Containers without hardware badges must come after
      expect(items[2].hardware_badges.length).toBe(0);
      expect(items[3].hardware_badges.length).toBe(0);
      expect(items[4].hardware_badges.length).toBe(0);
    });

    it('sorts by CPU / RAM descending (highest CPU% on top)', () => {
      const items = [...mockContainers];
      sortDockerContainers(items, 'cpu', 'desc');
      const cpuList = items.map((c) => c.cpu_pct);
      expect(cpuList).toEqual([24.5, 12.0, 1.2, 0.0, 0.0]);
      expect(items[0].name).toBe('jellyfin');
      expect(items[1].name).toBe('qbittorrent');
      expect(items[2].name).toBe('dockhand');
    });

    it('sorts by CPU / RAM ascending (lowest CPU% on top)', () => {
      const items = [...mockContainers];
      sortDockerContainers(items, 'cpu', 'asc');
      const cpuList = items.map((c) => c.cpu_pct);
      expect(cpuList[0]).toBe(0.0);
      expect(cpuList[cpuList.length - 1]).toBe(24.5);
    });

    it('sorts by Ports & Web UI ascending (lowest port first, portless at end)', () => {
      const items = [...mockContainers];
      sortDockerContainers(items, 'ports', 'asc');
      const portList = items.map((c) => getContainerPortSortValue(c));
      expect(portList).toEqual([3000, 8080, 8096, 0, 0]);
      expect(items[0].name).toBe('dockhand'); // 3000
      expect(items[1].name).toBe('qbittorrent'); // 8080
      expect(items[2].name).toBe('jellyfin'); // 8096
    });

    it('sorts by Ports & Web UI descending (highest port first, portless at end)', () => {
      const items = [...mockContainers];
      sortDockerContainers(items, 'ports', 'desc');
      const portList = items.map((c) => getContainerPortSortValue(c));
      expect(portList).toEqual([8096, 8080, 3000, 0, 0]);
      expect(items[0].name).toBe('jellyfin'); // 8096
      expect(items[1].name).toBe('qbittorrent'); // 8080
      expect(items[2].name).toBe('dockhand'); // 3000
    });

    it('sorts by Status & Uptime ascending (Running first) and descending (Stopped first)', () => {
      const items = [...mockContainers];
      sortDockerContainers(items, 'status', 'asc');
      expect(items[0].state).toBe('running');
      expect(items[1].state).toBe('running');
      expect(items[2].state).toBe('running');
      expect(items[3].state).toBe('exited');
      expect(items[4].state).toBe('exited');

      sortDockerContainers(items, 'status', 'desc');
      expect(items[0].state).toBe('exited');
      expect(items[1].state).toBe('exited');
      expect(items[2].state).toBe('running');
      expect(items[3].state).toBe('running');
      expect(items[4].state).toBe('running');
    });
  });

  describe('Interactive Header Clicking & DOM Reconciliation', () => {
    it('clicking Name header sorts alphabetically and toggles ascending/descending', async () => {
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
      await fetchAndRenderDockerContainers();

      const thName = document.querySelector('th[data-sort-col="name"]');
      expect(thName).not.toBeNull();

      // Click 1: sort by Name asc
      thName.click();

      expect(thName.classList.contains('active-sort')).toBe(true);
      expect(thName.getAttribute('aria-sort')).toBe('ascending');
      expect(thName.querySelector('.docker-sort-indicator').textContent).toBe('▲');

      let rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
      expect(rows[0].innerHTML).toContain('dockhand');
      expect(rows[4].innerHTML).toContain('unraid-kernel-builder');

      // Click 2: toggle Name desc
      thName.click();

      expect(thName.getAttribute('aria-sort')).toBe('descending');
      expect(thName.querySelector('.docker-sort-indicator').textContent).toBe('▼');

      rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
      expect(rows[0].innerHTML).toContain('unraid-kernel-builder');
      expect(rows[4].innerHTML).toContain('dockhand');
    });

    it('clicking CPU/RAM header sorts highest CPU on top by default', async () => {
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
      await fetchAndRenderDockerContainers();

      const thCpu = document.querySelector('th[data-sort-col="cpu"]');
      thCpu.click();

      expect(thCpu.classList.contains('active-sort')).toBe(true);
      expect(thCpu.getAttribute('aria-sort')).toBe('descending');
      expect(thCpu.querySelector('.docker-sort-indicator').textContent).toBe('▼');

      const rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
      expect(rows[0].innerHTML).toContain('jellyfin'); // 24.5%
      expect(rows[1].innerHTML).toContain('qbittorrent'); // 12.0%
      expect(rows[2].innerHTML).toContain('dockhand'); // 1.2%
    });

    it('clicking Hardware header sorts hardware-accelerated containers to top', async () => {
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
      await fetchAndRenderDockerContainers();

      const thHw = document.querySelector('th[data-sort-col="hardware"]');
      thHw.click();

      expect(thHw.classList.contains('active-sort')).toBe(true);
      expect(thHw.getAttribute('aria-sort')).toBe('descending');

      const rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
      // jellyfin and immich_machine_learning have hardware badges
      const firstTwoNames = [rows[0].innerHTML, rows[1].innerHTML].join(' ');
      expect(firstTwoNames).toContain('jellyfin');
      expect(firstTwoNames).toContain('immich_machine_learning');
    });

    it('keyboard accessibility: pressing Enter on header triggers sorting', async () => {
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
      await fetchAndRenderDockerContainers();

      const thPorts = document.querySelector('th[data-sort-col="ports"]');
      thPorts.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

      expect(thPorts.classList.contains('active-sort')).toBe(true);
      expect(thPorts.getAttribute('aria-sort')).toBe('ascending');

      const rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
      expect(rows[0].innerHTML).toContain('dockhand'); // port 3000
      expect(rows[1].innerHTML).toContain('qbittorrent'); // port 8080
      expect(rows[2].innerHTML).toContain('jellyfin'); // port 8096
    });

    it('preserves sorting order across search input filtering', async () => {
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
      await fetchAndRenderDockerContainers();

      // Sort by Name asc
      const thName = document.querySelector('th[data-sort-col="name"]');
      thName.click();

      // Filter with search input
      const searchInput = document.getElementById('docker-search-input');
      searchInput.value = 'arr'; // matches jellyfin and qbittorrent
      searchInput.dispatchEvent(new Event('input'));

      const rows = document.getElementById('docker-containers-tbody').querySelectorAll('tr');
      expect(rows.length).toBe(2);
      expect(rows[0].innerHTML).toContain('jellyfin');
      expect(rows[1].innerHTML).toContain('qbittorrent');
    });
  });
});
