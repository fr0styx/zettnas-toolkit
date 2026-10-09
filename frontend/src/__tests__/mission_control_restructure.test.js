import { describe, it, expect, beforeEach, vi } from 'vitest';
import { SUBPANE_MAP, updateManagementTelemetry, initManagementWindow } from '../components/management.js';

describe('Mission Control Navigation Restructure & Hardware Agnosticism', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="management-modal-overlay" class="open">
        <div id="management-hub-view" class="mgmt-detail-card" style="display:block;">
          <div class="mgmt-app-card" data-mgmt-target="mgmt-sec-docker">
            <span id="mgmt-hub-docker-pill">0 Active</span>
          </div>
          <div class="mgmt-app-card" data-mgmt-target="mgmt-sec-hardware">
            <span class="mgmt-app-pill">Acoustics</span>
          </div>
        </div>

        <!-- Sidebar Navigation -->
        <button class="mgmt-sidebar-item active" data-mgmt-target="management-hub-view">HUB</button>
        <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-docker">
          <span class="mgmt-sidebar-text">Containers</span>
          <span class="mgmt-sidebar-badge" id="mgmt-sidebar-docker-badge" style="display:none;">0 Active</span>
        </button>
        <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-storage">Storage</button>
        <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-hardware">
          <span class="mgmt-sidebar-text">Hardware & Profiles</span>
        </button>

        <!-- Apps & Containers Section -->
        <div id="mgmt-sec-docker" class="mgmt-detail-card" style="display:none;">
          <div id="mgmt-pane-docker" class="mgmt-tab-pane" style="display:block;">
            <button id="btn-view-docker-containers" class="active">Active Containers</button>
            <button id="btn-view-docker-catalog">App Catalog</button>
            <div id="docker-view-containers-wrap">
              <tbody id="docker-containers-tbody"></tbody>
            </div>
            <div id="docker-view-catalog-wrap" style="display:none;"></div>
          </div>
        </div>

        <!-- Hardware & Profiles Section -->
        <div id="mgmt-sec-hardware" class="mgmt-detail-card" style="display:none;">
          <div id="mgmt-pane-unraid" class="mgmt-tab-pane" style="display:block;">
            <span id="unraid-profile-current-pill">ACTIVE: AUTO DYNAMIC</span>
            <div class="unraid-details-grid" style="display:none;">
              <span id="mgmt-unraid-state">-</span>
              <span id="mgmt-unraid-server">-</span>
              <span id="mgmt-unraid-version">-</span>
              <span id="mgmt-unraid-disks">-</span>
              <span id="mgmt-unraid-parity">-</span>
              <span id="mgmt-unraid-mover">-</span>
            </div>
            <div class="generic-details-grid" style="display:none;">
              <span id="mgmt-generic-os">-</span>
              <span id="mgmt-generic-host">-</span>
              <span id="mgmt-generic-uptime">-</span>
              <span id="mgmt-generic-cpu">-</span>
              <span id="mgmt-generic-load">-</span>
              <span id="mgmt-generic-engine">-</span>
            </div>
          </div>
        </div>
      </div>
    `;
  });

  it('preserves 100% backward compatibility for SUBPANE_MAP lookups', () => {
    // Containers
    expect(SUBPANE_MAP['mgmt-sec-docker']).toEqual({
      section: 'mgmt-sec-docker',
      pane: 'mgmt-pane-docker'
    });
    expect(SUBPANE_MAP['mgmt-pane-docker']).toEqual({
      section: 'mgmt-sec-docker',
      pane: 'mgmt-pane-docker'
    });
    expect(SUBPANE_MAP['mgmt-sec-catalog']).toEqual({
      section: 'mgmt-sec-docker',
      pane: 'mgmt-pane-docker'
    });

    // Hardware & Profiles (including backward compatibility aliases)
    expect(SUBPANE_MAP['mgmt-sec-hardware']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-unraid'
    });
    expect(SUBPANE_MAP['mgmt-pane-hardware']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-unraid'
    });
    expect(SUBPANE_MAP['mgmt-sec-services']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-unraid'
    });
    expect(SUBPANE_MAP['mgmt-sec-unraid']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-unraid'
    });
    expect(SUBPANE_MAP['mgmt-pane-unraid']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-unraid'
    });
  });

  it('updates live Docker container counts on Hub pill and sidebar badge', () => {
    const mockStats = {
      docker: [
        { id: '1', name: 'immich', state: 'running' },
        { id: '2', name: 'plex', state: 'running' },
        { id: '3', name: 'vaultwarden', state: 'running' },
        { id: '4', name: 'stopped_app', state: 'exited' }
      ]
    };

    updateManagementTelemetry(mockStats);

    const hubPill = document.getElementById('mgmt-hub-docker-pill');
    const sideBadge = document.getElementById('mgmt-sidebar-docker-badge');

    expect(hubPill.textContent).toBe('3 Active');
    expect(sideBadge.textContent).toBe('3 Active');
    expect(sideBadge.style.display).toBe('inline-block');
  });

  it('renders Unraid grid when running on Unraid OS host', () => {
    const mockStats = {
      unraid: {
        available: true,
        state: 'STARTED',
        color: 'green-on',
        server_name: 'Tower',
        model: 'D6U',
        version: '6.12.10',
        disks: { total: 6, disabled: 0, invalid: 0 },
        parity_check: { active: false, errors: 0 },
        mover: { active: false }
      }
    };

    updateManagementTelemetry(mockStats);

    const unraidGrid = document.querySelector('.unraid-details-grid');
    const genericGrid = document.querySelector('.generic-details-grid');
    const stateEl = document.getElementById('mgmt-unraid-state');
    const srvEl = document.getElementById('mgmt-unraid-server');

    expect(unraidGrid.style.display).toBe('grid');
    expect(genericGrid.style.display).toBe('none');
    expect(stateEl.textContent).toBe('STARTED');
    expect(srvEl.textContent).toBe('Tower (D6U)');
  });

  it('renders Generic Linux grid when running on non-Unraid host (OS & Hardware Agnostic)', () => {
    const mockStats = {
      unraid: { available: false },
      os: { distro: 'Ubuntu 24.04 LTS' },
      system: { hostname: 'zettnas-homelab', uptime_str: '14 days' },
      cpu: { model: 'AMD Ryzen 7 5700X 8-Core', load_avg: ['0.42', '0.38', '0.29'] },
      storage: { engine: 'Btrfs Native Subvolumes' }
    };

    updateManagementTelemetry(mockStats);

    const unraidGrid = document.querySelector('.unraid-details-grid');
    const genericGrid = document.querySelector('.generic-details-grid');
    const osEl = document.getElementById('mgmt-generic-os');
    const hostEl = document.getElementById('mgmt-generic-host');
    const uptimeEl = document.getElementById('mgmt-generic-uptime');
    const engineEl = document.getElementById('mgmt-generic-engine');

    expect(unraidGrid.style.display).toBe('none');
    expect(genericGrid.style.display).toBe('grid');
    expect(osEl.textContent).toBe('Ubuntu 24.04 LTS');
    expect(hostEl.textContent).toBe('zettnas-homelab');
    expect(uptimeEl.textContent).toBe('14 days');
    expect(engineEl.textContent).toBe('Btrfs Native Subvolumes');
  });
});
