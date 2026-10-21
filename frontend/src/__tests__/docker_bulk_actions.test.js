import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getSelectedContainerIds,
  isContainerSelected,
  toggleContainerSelected,
  clearSelectedContainers,
  selectAllContainers,
  createContainerRow,
  updateContainerRow,
} from '../components/docker-table.js';
import {
  updateCwBulkBar,
  executeBulkContainerAction,
  renderContainersWindowTable,
  initContainersManager,
} from '../components/containers-manager.js';
import {
  updateDockerBulkBar,
  executeBulkContainerAction as executeMgmtBulkContainerAction,
  fetchAndRenderDockerContainers,
  renderDockerContainersTable,
  _resetDockerStateForTesting,
} from '../components/management.js';
import { api } from '../api.js';

describe('Docker Multi-Select & Floating Bulk Action Subsystem', () => {
  beforeEach(() => {
    clearSelectedContainers();
    document.body.innerHTML = `
      <div id="containers-manager-window">
        <input type="text" id="cw-docker-search-input" value="">
        <div class="cw-docker-table-wrap">
          <table class="docker-table">
            <thead>
              <tr>
                <th class="cw-sortable-th" data-sort-col="name">
                  <input type="checkbox" id="cw-docker-select-all">
                  <span>Name</span>
                </th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="cw-docker-containers-tbody"></tbody>
          </table>
        </div>
        <div id="cw-docker-bulk-bar" class="docker-floating-bulk-bar" style="display: none;">
          <span id="cw-docker-bulk-count" class="bulk-bar-count">0</span>
          <div class="bulk-bar-actions">
            <button class="btn-bulk-action" data-bulk="start">Start</button>
            <button class="btn-bulk-action" data-bulk="stop">Stop</button>
            <button class="btn-bulk-action" data-bulk="restart">Restart</button>
            <button class="btn-bulk-action" data-bulk="pause">Pause</button>
            <button class="btn-bulk-action" data-bulk="unpause">Resume</button>
            <button class="btn-bulk-action btn-bulk-delete" data-bulk="delete">Delete</button>
            <button class="btn-bulk-action btn-bulk-cancel" data-bulk="cancel">Cancel</button>
          </div>
        </div>
      </div>
    `;
    vi.restoreAllMocks();
  });

  const mockContainers = [
    {
      id: 'c1',
      name: 'c-one',
      image: 'nginx:alpine',
      state: 'running',
      status: 'Up 2 hours',
      ports: [{ public_port: 8080, private_port: 80 }],
    },
    {
      id: 'c2',
      name: 'c-two',
      image: 'redis:latest',
      state: 'stopped',
      status: 'Exited (0)',
      ports: [],
    },
    {
      id: 'c3',
      name: 'c-three',
      image: 'postgres:16',
      state: 'running',
      status: 'Up 1 day',
      ports: [],
    },
  ];

  it('manages container selection set correctly', () => {
    expect(getSelectedContainerIds()).toEqual([]);
    toggleContainerSelected('c1', true);
    expect(isContainerSelected('c1')).toBe(true);
    expect(getSelectedContainerIds()).toEqual(['c1']);

    toggleContainerSelected('c2', true);
    expect(getSelectedContainerIds().sort()).toEqual(['c1', 'c2']);

    toggleContainerSelected('c1', false);
    expect(isContainerSelected('c1')).toBe(false);
    expect(getSelectedContainerIds()).toEqual(['c2']);

    selectAllContainers(['c1', 'c3']);
    expect(getSelectedContainerIds().sort()).toEqual(['c1', 'c2', 'c3']);

    clearSelectedContainers();
    expect(getSelectedContainerIds()).toEqual([]);
  });

  it('renders container row with selection checkbox and selected class', () => {
    toggleContainerSelected('c1', true);
    const row = createContainerRow(mockContainers[0], 'localhost');
    const chk = row.querySelector('.docker-row-select');
    expect(chk).not.toBeNull();
    expect(chk.checked).toBe(true);
    expect(row.classList.contains('docker-row-selected')).toBe(true);

    const unselectedRow = createContainerRow(mockContainers[1], 'localhost');
    const unchk = unselectedRow.querySelector('.docker-row-select');
    expect(unchk.checked).toBe(false);
    expect(unselectedRow.classList.contains('docker-row-selected')).toBe(false);
  });

  it('synchronizes selection state in updateContainerRow', () => {
    const row = createContainerRow(mockContainers[0], 'localhost');
    expect(row.classList.contains('docker-row-selected')).toBe(false);

    toggleContainerSelected('c1', true);
    updateContainerRow(row, mockContainers[0], 'localhost');

    const chk = row.querySelector('.docker-row-select');
    expect(chk.checked).toBe(true);
    expect(row.classList.contains('docker-row-selected')).toBe(true);

    toggleContainerSelected('c1', false);
    updateContainerRow(row, mockContainers[0], 'localhost');
    expect(chk.checked).toBe(false);
    expect(row.classList.contains('docker-row-selected')).toBe(false);
  });

  it('updates floating bulk action bar and select-all state', () => {
    renderContainersWindowTable(mockContainers);

    const bulkBar = document.getElementById('cw-docker-bulk-bar');
    const countEl = document.getElementById('cw-docker-bulk-count');
    const selectAll = document.getElementById('cw-docker-select-all');

    expect(bulkBar.style.display).toBe('none');
    expect(selectAll.checked).toBe(false);

    toggleContainerSelected('c1', true);
    updateCwBulkBar();
    expect(bulkBar.style.display).toBe('flex');
    expect(countEl.textContent).toBe('1');
    expect(selectAll.indeterminate).toBe(true);

    selectAllContainers(['c1', 'c2', 'c3']);
    updateCwBulkBar();
    expect(bulkBar.style.display).toBe('flex');
    expect(countEl.textContent).toBe('3');
    expect(selectAll.checked).toBe(true);
    expect(selectAll.indeterminate).toBe(false);

    clearSelectedContainers();
    updateCwBulkBar();
    expect(bulkBar.style.display).toBe('none');
    expect(selectAll.checked).toBe(false);
  });

  it('dispatches bulk action to backend API', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      action: 'start',
      total: 2,
      successful: 2,
      results: { c1: { success: true }, c2: { success: true } },
    });
    vi.spyOn(api, 'get').mockResolvedValue(mockContainers);

    selectAllContainers(['c1', 'c2']);
    await executeBulkContainerAction('start');

    expect(postSpy).toHaveBeenCalledWith('/api/docker/containers/bulk-action', {
      action: 'start',
      container_ids: ['c1', 'c2'],
      force: false,
    });
    expect(getSelectedContainerIds()).toEqual([]);
  });

  describe('Mission Control Containers 1:1 Parity Suite', () => {
    beforeEach(() => {
      _resetDockerStateForTesting();
      clearSelectedContainers();
      document.body.innerHTML = `
        <div id="management-window">
          <div id="mgmt-sec-docker" style="display: block;">
            <div id="mgmt-pane-docker">
              <div id="docker-view-containers-wrap">
                <input type="text" id="docker-search-input" value="">
                <button class="docker-filter-btn active" data-filter="all">All</button>
                <button class="docker-filter-btn" data-filter="running">Running</button>
                <button class="docker-filter-btn" data-filter="stopped">Stopped</button>
                <div class="docker-table-container">
                  <table class="docker-table">
                    <thead>
                      <tr>
                        <th class="sortable-th" data-sort-col="name">
                          <input type="checkbox" id="docker-select-all">
                          <span>Name</span>
                        </th>
                        <th class="sortable-th" data-sort-col="stack"><span>Stack / Type</span></th>
                        <th class="sortable-th" data-sort-col="hardware"><span>Hardware</span></th>
                        <th class="sortable-th" data-sort-col="cpu"><span>CPU / RAM</span></th>
                        <th class="sortable-th" data-sort-col="ports"><span>Ports</span></th>
                        <th class="sortable-th" data-sort-col="status"><span>Status</span></th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody id="docker-containers-tbody"></tbody>
                  </table>
                </div>
                <div id="docker-bulk-bar" class="docker-floating-bulk-bar" style="display: none;">
                  <span id="docker-bulk-count" class="bulk-bar-count">0</span>
                  <div class="bulk-bar-actions">
                    <button class="btn-bulk-action" data-bulk="start">Start</button>
                    <button class="btn-bulk-action" data-bulk="stop">Stop</button>
                    <button class="btn-bulk-action" data-bulk="restart">Restart</button>
                    <button class="btn-bulk-action" data-bulk="pause">Pause</button>
                    <button class="btn-bulk-action" data-bulk="unpause">Resume</button>
                    <button class="btn-bulk-action btn-bulk-delete" data-bulk="delete">Delete</button>
                    <button class="btn-bulk-action btn-bulk-cancel" data-bulk="cancel">Cancel</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
    });

    it('updates floating bulk action bar and select-all state in Mission Control', async () => {
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
      await fetchAndRenderDockerContainers();

      const bulkBar = document.getElementById('docker-bulk-bar');
      const countEl = document.getElementById('docker-bulk-count');
      const selectAll = document.getElementById('docker-select-all');

      expect(bulkBar.style.display).toBe('none');
      expect(selectAll.checked).toBe(false);

      toggleContainerSelected('c1', true);
      updateDockerBulkBar();
      expect(bulkBar.style.display).toBe('flex');
      expect(countEl.textContent).toBe('1');
      expect(selectAll.indeterminate).toBe(true);

      selectAllContainers(['c1', 'c2', 'c3']);
      updateDockerBulkBar();
      expect(bulkBar.style.display).toBe('flex');
      expect(countEl.textContent).toBe('3');
      expect(selectAll.checked).toBe(true);
      expect(selectAll.indeterminate).toBe(false);

      clearSelectedContainers();
      updateDockerBulkBar();
      expect(bulkBar.style.display).toBe('none');
      expect(selectAll.checked).toBe(false);
    });

    it('interacts with select-all checkbox to toggle all containers in Mission Control', async () => {
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
      await fetchAndRenderDockerContainers();

      const selectAll = document.getElementById('docker-select-all');
      const tbody = document.getElementById('docker-containers-tbody');

      selectAll.checked = true;
      selectAll.dispatchEvent(new Event('change', { bubbles: true }));

      expect(getSelectedContainerIds().sort()).toEqual(['c1', 'c2', 'c3']);
      tbody.querySelectorAll('.docker-row-select').forEach((chk) => {
        expect(chk.checked).toBe(true);
      });

      selectAll.checked = false;
      selectAll.dispatchEvent(new Event('change', { bubbles: true }));

      expect(getSelectedContainerIds()).toEqual([]);
      tbody.querySelectorAll('.docker-row-select').forEach((chk) => {
        expect(chk.checked).toBe(false);
      });
    });

    it('dispatches bulk action to backend API from Mission Control', async () => {
      const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
        action: 'restart',
        total: 2,
        successful: 2,
        results: { c1: { success: true }, c3: { success: true } },
      });
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);

      selectAllContainers(['c1', 'c3']);
      await executeMgmtBulkContainerAction('restart');

      expect(postSpy).toHaveBeenCalledWith('/api/docker/containers/bulk-action', {
        action: 'restart',
        container_ids: ['c1', 'c3'],
        force: false,
      });
      expect(getSelectedContainerIds()).toEqual([]);
    });

    it('clicking row checkbox updates selection and bulk bar in Mission Control', async () => {
      vi.spyOn(api, 'get').mockResolvedValue(mockContainers);
      await fetchAndRenderDockerContainers();

      const tbody = document.getElementById('docker-containers-tbody');
      const firstChk = tbody.querySelector('.docker-row-select[data-id="c1"]');
      expect(firstChk).not.toBeNull();

      firstChk.checked = true;
      firstChk.dispatchEvent(new Event('change', { bubbles: true }));

      expect(isContainerSelected('c1')).toBe(true);
      const bulkBar = document.getElementById('docker-bulk-bar');
      const countEl = document.getElementById('docker-bulk-count');
      expect(bulkBar.style.display).toBe('flex');
      expect(countEl.textContent).toBe('1');
    });
  });
});
