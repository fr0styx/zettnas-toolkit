import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import {
  initContainerModal,
  openContainerInspector,
  switchContainerTab,
  _resetContainerModalForTesting,
} from '../components/container-modal.js';
import {
  fetchAndRenderDockerContainers,
  renderDockerContainersTable,
  refreshDockerUpdatesStatus,
  updateDockerUpdatesToolbarUI,
  _resetDockerStateForTesting,
} from '../components/management.js';

describe('Container Edit & Docker Update System', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="mgmt-sec-docker" class="mgmt-detail-card" style="display: block;">
        <div id="mgmt-pane-docker" class="mgmt-tab-pane" style="display: block;">
          <div id="docker-view-containers-wrap">
            <div class="docker-toolbar">
              <div class="docker-filter-pills">
                <button class="btn-pill-toggle docker-filter-btn active" data-filter="all">All <span id="docker-count-all">0</span></button>
              </div>
              <div>
                <button class="btn-pill-toggle" id="btn-docker-check-updates">Check for updates</button>
                <button class="btn-pill-toggle" id="btn-docker-update-all" style="display:none;">Update all (<span id="docker-updates-count-badge">0</span>)</button>
                <input type="text" id="docker-search-input">
              </div>
            </div>
            <table>
              <tbody id="docker-containers-tbody"></tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    _resetContainerModalForTesting();
    _resetDockerStateForTesting();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    _resetContainerModalForTesting();
    _resetDockerStateForTesting();
    vi.restoreAllMocks();
  });

  it('renders container edit form and submits recreate request', async () => {
    const mockDetails = {
      overview: {
        id: 'c12345678901',
        full_id: 'c1234567890123456789',
        name: 'jellyfin',
        image: 'lscr.io/linuxserver/jellyfin:latest',
        network_mode: 'bridge',
        restart_policy: 'unless-stopped',
        state: 'running',
        running: true,
      },
      ports: [
        { private_port: 8096, public_port: 8096, type: 'tcp', ip: '0.0.0.0' },
      ],
      mounts: [
        { source: '/mnt/user/appdata/jellyfin', destination: '/config', mode: 'rw', rw: true },
      ],
      env: [
        { key: 'PUID', value: '1000' },
        { key: 'PGID', value: '100' },
      ],
      resources: {
        memory_limit: 1024 * 1024 * 1024,
        nano_cpus: 2000000000,
      },
    };

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/details')) return mockDetails;
      return {};
    });

    const postSpy = vi.spyOn(api, 'post').mockImplementation(async (url, body) => {
      if (url.includes('/recreate')) {
        return {
          status: 'success',
          message: 'Container recreated',
          new_id: 'newid999full',
          target_name: body.name || 'jellyfin',
        };
      }
      return {};
    });

    // Open inspector on edit tab
    await openContainerInspector('c12345678901', 'jellyfin', 'edit');

    const nameInput = document.getElementById('cie-input-name');
    const imageInput = document.getElementById('cie-input-image');
    expect(nameInput).not.toBeNull();
    expect(nameInput.value).toBe('jellyfin');
    expect(imageInput.value).toBe('lscr.io/linuxserver/jellyfin:latest');

    // Check pre-populated ports and mounts
    const portRows = document.querySelectorAll('.cie-port-row');
    expect(portRows.length).toBe(1);
    const mountRows = document.querySelectorAll('.cie-mount-row');
    expect(mountRows.length).toBe(1);

    // Modify container name and submit
    nameInput.value = 'jellyfin-modified';
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    const saveBtn = document.getElementById('cie-btn-save');
    await saveBtn.click();

    expect(postSpy).toHaveBeenCalled();
    const [callUrl, callPayload] = postSpy.mock.calls.find((c) => c[0].includes('/recreate'));
    expect(callUrl).toContain('c12345678901');
    expect(callPayload.name).toBe('jellyfin-modified');
    expect(callPayload.image).toBe('lscr.io/linuxserver/jellyfin:latest');
    expect(callPayload.network_mode).toBe('bridge');
  });

  it('updates toolbar UI when updates are available and triggers batch update', async () => {
    const postSpy = vi.spyOn(api, 'post').mockImplementation(async (url) => {
      if (url.includes('/updates/check')) {
        return {
          checked_at: 1728518800,
          total_containers: 2,
          updates_available_count: 2,
          containers: {
            immich_server: { name: 'immich_server', has_update: true },
            dockhand: { name: 'dockhand', has_update: true },
          },
        };
      }
      if (url.includes('/updates/apply-all')) {
        return {
          status: 'completed',
          total_updated: 2,
          updated: [{ name: 'immich_server' }, { name: 'dockhand' }],
        };
      }
      return {};
    });

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/docker/containers')) {
        return [
          { id: 'c1', name: 'immich_server', state: 'running', status: 'Up 2 days' },
          { id: 'c2', name: 'dockhand', state: 'running', status: 'Up 5 hours' },
        ];
      }
      if (url.includes('/docker/updates/status')) {
        return {
          updates_available_count: 2,
          containers: {
            immich_server: { name: 'immich_server', has_update: true },
            dockhand: { name: 'dockhand', has_update: true },
          },
        };
      }
      return {};
    });

    await fetchAndRenderDockerContainers();

    // Check updates button clicked
    const checkBtn = document.getElementById('btn-docker-check-updates');
    await checkBtn.click();

    const updateAllBtn = document.getElementById('btn-docker-update-all');
    const badge = document.getElementById('docker-updates-count-badge');
    expect(updateAllBtn.style.display).toBe('inline-flex');
    expect(badge.textContent).toBe('2');

    // Confirm and click Update All using custom UI dialog
    await updateAllBtn.click();
    const okBtn = document.getElementById('confirm-toast-ok');
    if (okBtn) okBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/docker/updates/apply-all');
  });

  it('allows individually updating a container by clicking the UPDATE badge next to its name', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/docker/containers')) {
        return [
          { id: 'c9fa84f9db51', name: 'immich_server', state: 'running', status: 'Up 46 hours (healthy)' },
        ];
      }
      if (url.includes('/docker/updates/status')) {
        return {
          updates_available_count: 1,
          containers: {
            immich_server: { name: 'immich_server', has_update: true },
          },
        };
      }
      return {};
    });

    const postSpy = vi.spyOn(api, 'post').mockImplementation(async (url) => {
      if (url.includes('/update-image')) {
        return { success: true, message: 'Container updated' };
      }
      return {};
    });

    await fetchAndRenderDockerContainers();

    // Check updates button clicked to load updates cache
    const checkBtn = document.getElementById('btn-docker-check-updates');
    await checkBtn.click();

    // Re-render table so update badge appears
    await fetchAndRenderDockerContainers();

    const tbody = document.getElementById('docker-containers-tbody');
    const updateBadgeBtn = tbody.querySelector('.btn-docker-update-badge');
    expect(updateBadgeBtn).not.toBeNull();
    expect(updateBadgeBtn.tagName).toBe('BUTTON');
    expect(updateBadgeBtn.textContent).toContain('UPDATE');
    expect(updateBadgeBtn.dataset.action).toBe('update-single');

    // Click the UPDATE badge
    await updateBadgeBtn.click();

    // Confirm toast should appear with custom UI
    const okBtn = document.getElementById('confirm-toast-ok');
    expect(okBtn).not.toBeNull();
    expect(okBtn.textContent).toContain('Update');
    await okBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/docker/containers/c9fa84f9db51/update-image');
  });
});
