import { describe, it, expect, beforeEach, vi } from 'vitest';
import { reconcileKeyedTable } from '../utils.js';
import { fetchAndRenderDockerContainers, _resetDockerStateForTesting } from '../components/management.js';
import { renderStructuredPoolsTopology } from '../components/chassis-visualizer.js';
import { api } from '../api.js';

describe('Batch 2: High-Performance Keyed Table Reconciler (Zero-Flicker Telemetry)', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.innerHTML = '';
    document.body.appendChild(container);
  });

  describe('reconcileKeyedTable Core Engine', () => {
    it('creates initial rows and assigns data-key correctly', () => {
      const items = [
        { id: 'item-1', name: 'Alpha' },
        { id: 'item-2', name: 'Beta' },
      ];

      reconcileKeyedTable(
        container,
        items,
        (i) => i.id,
        (i) => {
          const el = document.createElement('div');
          el.className = 'test-row';
          el.textContent = i.name;
          return el;
        }
      );

      expect(container.children.length).toBe(2);
      expect(container.children[0].dataset.key).toBe('item-1');
      expect(container.children[0].textContent).toBe('Alpha');
      expect(container.children[1].dataset.key).toBe('item-2');
      expect(container.children[1].textContent).toBe('Beta');
    });

    it('updates existing nodes in-place without destroying DOM elements (reference equality)', () => {
      const initialItems = [
        { id: 'row-a', val: '10%' },
        { id: 'row-b', val: '20%' },
      ];

      reconcileKeyedTable(
        container,
        initialItems,
        (i) => i.id,
        (i) => {
          const el = document.createElement('div');
          el.className = 'test-row';
          el.innerHTML = `<span class="val">${i.val}</span>`;
          return el;
        },
        (el, i) => {
          el.querySelector('.val').textContent = i.val;
        }
      );

      const firstNodeBefore = container.children[0];
      const secondNodeBefore = container.children[1];

      // Second telemetry tick: updated values
      const updatedItems = [
        { id: 'row-a', val: '45%' },
        { id: 'row-b', val: '65%' },
      ];

      reconcileKeyedTable(
        container,
        updatedItems,
        (i) => i.id,
        (i) => {
          const el = document.createElement('div');
          el.className = 'test-row';
          el.innerHTML = `<span class="val">${i.val}</span>`;
          return el;
        },
        (el, i) => {
          el.querySelector('.val').textContent = i.val;
        }
      );

      expect(container.children.length).toBe(2);
      // DOM Reference identity MUST be preserved
      expect(container.children[0]).toBe(firstNodeBefore);
      expect(container.children[1]).toBe(secondNodeBefore);
      expect(container.children[0].querySelector('.val').textContent).toBe('45%');
      expect(container.children[1].querySelector('.val').textContent).toBe('65%');
    });

    it('preserves focused elements and input state across rapid reconciliations', () => {
      const initialItems = [
        { id: 'dev-1', label: 'Disk 1' },
        { id: 'dev-2', label: 'Disk 2' },
      ];

      reconcileKeyedTable(
        container,
        initialItems,
        (i) => i.id,
        (i) => {
          const el = document.createElement('div');
          el.className = 'interactive-row';
          el.innerHTML = `<input type="text" class="row-input" value="${i.label}"><button class="btn-action">Act</button>`;
          return el;
        }
      );

      const input = container.children[0].querySelector('.row-input');
      input.focus();
      input.value = 'User Typing Something...';
      expect(document.activeElement).toBe(input);

      // Incoming telemetry update with same keys
      reconcileKeyedTable(
        container,
        initialItems,
        (i) => i.id,
        (i) => document.createElement('div'),
        (el, i) => {
          // Telemetry only updates non-input fields
        }
      );

      // Focus must remain on the user's active input and not be stolen or reset
      expect(document.activeElement).toBe(input);
      expect(input.value).toBe('User Typing Something...');
    });

    it('reorders existing nodes in-place when sort order changes', () => {
      const itemsInitial = [
        { id: 'A', name: 'Alpha' },
        { id: 'B', name: 'Beta' },
        { id: 'C', name: 'Gamma' },
      ];

      reconcileKeyedTable(
        container,
        itemsInitial,
        (i) => i.id,
        (i) => {
          const el = document.createElement('div');
          el.textContent = i.name;
          return el;
        }
      );

      const nodeA = container.children[0];
      const nodeB = container.children[1];
      const nodeC = container.children[2];

      // Reorder items: C, A, B
      const itemsReordered = [
        { id: 'C', name: 'Gamma' },
        { id: 'A', name: 'Alpha' },
        { id: 'B', name: 'Beta' },
      ];

      reconcileKeyedTable(
        container,
        itemsReordered,
        (i) => i.id,
        (i) => document.createElement('div'),
        (el, i) => {}
      );

      expect(container.children[0]).toBe(nodeC);
      expect(container.children[1]).toBe(nodeA);
      expect(container.children[2]).toBe(nodeB);
    });

    it('removes obsolete keys and inserts new keys at correct positions', () => {
      const initial = [
        { id: 'keep', name: 'Keep Me' },
        { id: 'remove', name: 'To Be Removed' },
      ];

      reconcileKeyedTable(
        container,
        initial,
        (i) => i.id,
        (i) => {
          const el = document.createElement('div');
          el.textContent = i.name;
          return el;
        }
      );

      const keepNode = container.children[0];
      expect(container.children.length).toBe(2);

      // Update: remove 'remove', add 'new-item'
      const updated = [
        { id: 'new-item', name: 'Newly Added' },
        { id: 'keep', name: 'Keep Me' },
      ];

      reconcileKeyedTable(
        container,
        updated,
        (i) => i.id,
        (i) => {
          const el = document.createElement('div');
          el.textContent = i.name;
          return el;
        },
        (el, i) => {}
      );

      expect(container.children.length).toBe(2);
      expect(container.children[0].dataset.key).toBe('new-item');
      expect(container.children[0].textContent).toBe('Newly Added');
      expect(container.children[1]).toBe(keepNode);
    });
  });

  describe('Zero-Flicker Telemetry in Docker Containers Table', () => {
    beforeEach(() => {
      _resetDockerStateForTesting();
      document.body.innerHTML = `
        <div id="mgmt-pane-docker">
          <input type="text" id="docker-search-input" value="">
          <button class="docker-filter-btn active" data-filter="all"></button>
          <span id="docker-count-all">0</span>
          <span id="docker-count-running">0</span>
          <span id="docker-count-stopped">0</span>
          <span id="docker-count-compose">0</span>
          <span id="docker-count-standalone">0</span>
          <span id="mgmt-hub-docker-pill">0</span>
          <span id="mgmt-sidebar-docker-badge">0</span>
          <table>
            <tbody id="docker-containers-tbody"></tbody>
          </table>
        </div>
      `;
    });

    it('updates container CPU and Memory without re-creating <tr> elements', async () => {
      const tbody = document.getElementById('docker-containers-tbody');
      const c1 = {
        id: 'cnt-1',
        name: 'plex',
        state: 'running',
        status: 'Up 2 hours',
        cpu_pct: 1.5,
        mem_used: 104857600, // 100MB
        ports: [{ public_port: 32400, type: 'tcp' }],
        hardware_badges: [],
      };

      vi.spyOn(api, 'get').mockResolvedValue([c1]);
      await fetchAndRenderDockerContainers();

      expect(tbody.children.length).toBe(1);
      const rowRef = tbody.children[0];
      expect(rowRef.querySelector('.telem-cpu').textContent).toBe('1.5%');

      // Next tick: CPU spikes to 18.2%
      const c1Updated = {
        ...c1,
        cpu_pct: 18.2,
        mem_used: 209715200, // 200MB
      };

      vi.spyOn(api, 'get').mockResolvedValue([c1Updated]);
      await fetchAndRenderDockerContainers();

      expect(tbody.children.length).toBe(1);
      // DOM reference MUST be identical (no flicker / zero re-render)
      expect(tbody.children[0]).toBe(rowRef);
      expect(tbody.children[0].querySelector('.telem-cpu').textContent).toBe('18.2%');
    });
  });

  describe('Zero-Flicker Structured Storage Topology Tree', () => {
    it('reconciles storage pools and preserves pool blocks without replacing parent container', () => {
      const topoContainer = document.createElement('div');
      document.body.appendChild(topoContainer);

      const mockData1 = {
        is_observer_mode: true,
        pools: [
          {
            id: 'pool-data',
            name: 'Array Pool',
            fs_type: 'btrfs',
            fs_profile: 'raid1',
            status: 'HEALTHY',
            used_bytes: 500000000000,
            total_bytes: 1000000000000,
            free_bytes: 500000000000,
            used_pct: 50,
            parity_protected: true,
            members: [
              { device: 'sdb', role: 'data', temp_c: 32, num_reads: 100, num_writes: 50 },
            ],
          },
        ],
      };

      renderStructuredPoolsTopology(topoContainer, mockData1);
      const poolsContainer = topoContainer.querySelector('.topo-pools-container');
      expect(poolsContainer).not.toBeNull();
      expect(poolsContainer.children.length).toBe(1);
      const poolBlock = poolsContainer.children[0];

      // Second telemetry update
      const mockData2 = {
        is_observer_mode: true,
        pools: [
          {
            ...mockData1.pools[0],
            used_pct: 52,
          },
        ],
      };

      renderStructuredPoolsTopology(topoContainer, mockData2);
      expect(poolsContainer.children.length).toBe(1);
      // In-place reconciliation preserves the block element
      expect(poolsContainer.children[0]).toBe(poolBlock);
      expect(topoContainer.textContent).toContain('52%');
    });
  });
});
