import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import {
  initContainerModal,
  openContainerInspector,
  closeContainerInspector,
  switchContainerTab,
  _resetContainerModalForTesting
} from '../components/container-modal.js';
import {
  fetchAndRenderDockerContainers,
  _resetDockerStateForTesting
} from '../components/management.js';
import { api } from '../api.js';
import { ZettEventBus } from '../event-bus.js';

describe('Container Inspector & Docker Compose Viewer - Phase 2', () => {
  const mockContainerDetails = {
    cid: 'c111222333444555666777888',
    overview: {
      id: 'c11122233344',
      full_id: 'c111222333444555666777888',
      name: 'jellyfin',
      image: 'lscr.io/linuxserver/jellyfin:latest',
      state: 'running',
      running: true,
      started_at: '2026-10-01T12:00:00.000Z',
      platform: 'linux/amd64',
      restart_policy: 'unless-stopped',
      command: '/init',
      ip_address: '172.17.0.4',
      network_mode: 'bridge'
    },
    resources: {
      memory_limit: 4294967296, // 4096 MB
      cpu_quota: 0
    },
    primary_port: 8096,
    webui_url: 'http://[HOST]:8096/',
    stack: 'arr',
    service: 'jellyfin',
    managed_by: 'compose',
    hardware_badges: [
      { id: 'gpu', label: 'GPU' },
      { id: 'nvidia', label: 'NVIDIA' }
    ],
    ports: [
      { public_port: 8096, private_port: 8096, type: 'tcp', ip: '0.0.0.0' },
      { public_port: 8920, private_port: 8920, type: 'tcp', ip: '0.0.0.0' }
    ],
    mounts: [
      {
        source: '/mnt/user/appdata/jellyfin',
        destination: '/config',
        mode: 'rw',
        rw: true,
        type: 'bind',
        is_appdata: true
      },
      {
        source: '/mnt/user/media',
        destination: '/media',
        mode: 'ro',
        rw: false,
        type: 'bind',
        is_appdata: false
      }
    ],
    env: [
      {
        key: 'PUID',
        value: '1000',
        masked_value: '1000',
        is_secret: false
      },
      {
        key: 'JELLYFIN_API_KEY',
        value: 'secret_api_token_xyz999',
        masked_value: '••••••••',
        is_secret: true
      }
    ]
  };

  const mockComposeData = {
    source: 'synthesized',
    spec: {
      version: '3.8',
      services: {
        jellyfin: {
          image: 'lscr.io/linuxserver/jellyfin:latest',
          container_name: 'jellyfin',
          restart: 'unless-stopped'
        }
      }
    },
    compose_yaml: `version: "3.8"\nservices:\n  jellyfin:\n    image: lscr.io/linuxserver/jellyfin:latest\n    container_name: jellyfin\n    environment:\n      - JELLYFIN_API_KEY=secret_api_token_xyz999\n`,
    masked_yaml: `version: "3.8"\nservices:\n  jellyfin:\n    image: lscr.io/linuxserver/jellyfin:latest\n    container_name: jellyfin\n    environment:\n      - JELLYFIN_API_KEY=••••••••\n`
  };

  const mockLogsData = {
    cid: 'c11122233344',
    count: 3,
    lines: [
      { stream: 'stdout', ts: '2026-10-08T12:00:01.000000000Z', msg: '[INF] Core service initialized.' },
      { stream: 'stdout', ts: '2026-10-08T12:00:02.000000000Z', msg: '[INF] Listening on 0.0.0.0:8096.' },
      { stream: 'stderr', ts: '2026-10-08T12:00:03.000000000Z', msg: '[WRN] Slow query detected on database.' }
    ]
  };

  beforeEach(() => {
    _resetContainerModalForTesting();
    _resetDockerStateForTesting();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    _resetContainerModalForTesting();
  });

  it('initializes container inspector DOM markup and tabs cleanly', () => {
    initContainerModal();
    const overlay = document.getElementById('container-inspector-overlay');
    expect(overlay).not.toBeNull();
    const win = document.getElementById('container-inspector-window');
    expect(win).not.toBeNull();

    // Check tabs exist
    const tabs = overlay.querySelectorAll('.ci-tab-btn');
    expect(tabs.length).toBe(6);
    expect(tabs[0].dataset.tab).toBe('overview');
    expect(tabs[1].dataset.tab).toBe('ports');
    expect(tabs[2].dataset.tab).toBe('mounts');
    expect(tabs[3].dataset.tab).toBe('env');
    expect(tabs[4].dataset.tab).toBe('compose');
    expect(tabs[5].dataset.tab).toBe('logs');
  });

  it('opens inspector, fetches container details, and populates Overview, Ports, Mounts, and Env tabs', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/details')) return mockContainerDetails;
      return {};
    });

    await openContainerInspector('c11122233344', 'jellyfin');

    const overlay = document.getElementById('container-inspector-overlay');
    expect(overlay.style.display).toBe('flex');
    expect(overlay.classList.contains('open')).toBe(true);

    const titleEl = document.getElementById('ci-header-title');
    expect(titleEl.textContent).toBe('jellyfin');

    const stateEl = document.getElementById('ci-header-state');
    expect(stateEl.textContent).toBe('RUNNING');

    // 1. Overview Tab verification
    const overviewContent = document.getElementById('ci-overview-content');
    expect(overviewContent.style.display).toBe('block');
    expect(overviewContent.innerHTML).toContain('lscr.io/linuxserver/jellyfin:latest');
    expect(overviewContent.innerHTML).toContain('172.17.0.4');
    expect(overviewContent.innerHTML).toContain('unless-stopped');
    expect(overviewContent.innerHTML).toContain('4096 MB');
    expect(overviewContent.innerHTML).toContain('docker-hw-gpu');
    expect(overviewContent.innerHTML).toContain('docker-hw-nvidia');
    expect(overviewContent.innerHTML).toContain('arr');

    // 2. Ports Tab verification
    const portsContent = document.getElementById('ci-ports-content');
    expect(portsContent.innerHTML).toContain('Web Interface Detected');
    expect(portsContent.innerHTML).toContain(':8096');
    expect(portsContent.innerHTML).toContain('Primary Web UI');
    expect(portsContent.innerHTML).toContain(':8920');

    // 3. Mounts Tab verification & File Explorer deep-link
    const mountsContent = document.getElementById('ci-mounts-content');
    expect(mountsContent.innerHTML).toContain('/mnt/user/appdata/jellyfin');
    expect(mountsContent.innerHTML).toContain('APPDATA');
    expect(mountsContent.innerHTML).toContain('/mnt/user/media');

    // Test File Explorer event emission on click
    const emitSpy = vi.spyOn(ZettEventBus, 'emit');
    const revealBtn = mountsContent.querySelector('.btn-reveal-fm[data-path="/mnt/user/appdata/jellyfin"]');
    expect(revealBtn).not.toBeNull();
    revealBtn.click();
    expect(emitSpy).toHaveBeenCalledWith('window:open', {
      id: 'file-manager-window',
      path: '/mnt/user/appdata/jellyfin'
    });

    // 4. Environment Tab verification & secret reveal toggle
    const envContent = document.getElementById('ci-env-content');
    expect(envContent.innerHTML).toContain('PUID');
    expect(envContent.innerHTML).toContain('JELLYFIN_API_KEY');
    expect(envContent.innerHTML).toContain('SECRET');

    // Default masked
    const secretSpan = document.getElementById('env-val-1');
    expect(secretSpan.textContent).toBe('••••••••');

    // Toggle reveal
    const toggleSecretBtn = envContent.querySelector('.btn-toggle-secret');
    expect(toggleSecretBtn).not.toBeNull();
    toggleSecretBtn.click();
    expect(secretSpan.textContent).toBe('secret_api_token_xyz999');
    toggleSecretBtn.click();
    expect(secretSpan.textContent).toBe('••••••••');
  });

  it('switches to Compose tab, fetches compose data, and toggles secret masking', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/details')) return mockContainerDetails;
      if (url.includes('/compose')) return mockComposeData;
      return {};
    });

    await openContainerInspector('c11122233344', 'jellyfin');

    await switchContainerTab('compose');

    // Check pane is displayed
    const composePane = document.getElementById('ci-pane-compose');
    expect(composePane.style.display).toBe('block');

    const codeEl = document.getElementById('ci-compose-code');
    // Default masked
    expect(codeEl.textContent).toContain('JELLYFIN_API_KEY=••••••••');

    // Toggle mask checkbox
    const maskCb = document.getElementById('ci-compose-mask-toggle');
    expect(maskCb.checked).toBe(true);
    maskCb.checked = false;
    maskCb.dispatchEvent(new Event('change'));

    // Should now show unmasked
    expect(codeEl.textContent).toContain('JELLYFIN_API_KEY=secret_api_token_xyz999');
  });

  it('switches to Live Logs tab, fetches logs, and filters lines', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/details')) return mockContainerDetails;
      if (url.includes('/logs')) return mockLogsData;
      return {};
    });

    await openContainerInspector('c11122233344', 'jellyfin');

    await switchContainerTab('logs');

    const logsPane = document.getElementById('ci-pane-logs');
    expect(logsPane.style.display).toBe('block');

    const terminal = document.getElementById('ci-logs-terminal');
    expect(terminal.innerHTML).toContain('Listening on 0.0.0.0:8096');
    expect(terminal.innerHTML).toContain('Slow query detected');

    // Filter logs
    const filterInput = document.getElementById('ci-logs-filter-input');
    filterInput.value = 'Slow query';
    filterInput.dispatchEvent(new Event('input'));

    expect(terminal.innerHTML).toContain('Slow query detected');
    expect(terminal.innerHTML).not.toContain('Listening on 0.0.0.0:8096');
  });

  it('closes inspector when close button is clicked', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockContainerDetails);
    await openContainerInspector('c11122233344', 'jellyfin');

    const overlay = document.getElementById('container-inspector-overlay');
    expect(overlay.style.display).toBe('flex');

    closeContainerInspector();
    expect(overlay.style.display).toBe('none');
    expect(overlay.classList.contains('open')).toBe(false);
  });

  it('integrates with container table in management window to open inspector', async () => {
    document.body.innerHTML = `
      <div id="mgmt-pane-docker">
        <input type="text" id="docker-search-input" value="">
        <table>
          <tbody id="docker-containers-tbody"></tbody>
        </table>
      </div>
    `;

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.endsWith('/api/docker/containers')) {
        return [
          {
            id: 'c11122233344',
            name: 'jellyfin',
            image: 'jellyfin/jellyfin',
            state: 'running',
            status: 'Up 2 hours',
            ports: [{ public_port: 8096, private_port: 8096 }],
            primary_port: 8096,
            webui_url: 'http://[HOST]:8096/'
          }
        ];
      }
      if (url.includes('/details')) return mockContainerDetails;
      return {};
    });

    await fetchAndRenderDockerContainers();

    const tbody = document.getElementById('docker-containers-tbody');
    expect(tbody).not.toBeNull();

    // Verify inspect button exists
    const inspectBtn = tbody.querySelector('.btn-docker-inspect');
    expect(inspectBtn).not.toBeNull();
    expect(inspectBtn.dataset.id).toBe('c11122233344');
    expect(inspectBtn.dataset.action).toBe('inspect');

    // Click inspect button
    inspectBtn.click();

    // Modal overlay should open
    const overlay = document.getElementById('container-inspector-overlay');
    expect(overlay).not.toBeNull();
    expect(overlay.classList.contains('open')).toBe(true);

    const titleEl = document.getElementById('ci-header-title');
    expect(titleEl.textContent).toBe('jellyfin');
  });

  it('submits live resource tuning with zero downtime via API', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockContainerDetails);
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      status: 'success',
      message: 'Container resource limits updated'
    });

    await openContainerInspector('c11122233344', 'jellyfin');

    const memInput = document.getElementById('ci-res-mem');
    const cpuInput = document.getElementById('ci-res-cpu');
    const restartInput = document.getElementById('ci-res-restart');
    const applyBtn = document.getElementById('ci-btn-apply-resources');

    expect(memInput).not.toBeNull();
    expect(cpuInput).not.toBeNull();
    expect(restartInput).not.toBeNull();
    expect(applyBtn).not.toBeNull();

    // Modify values
    memInput.value = '2048';
    cpuInput.value = '4.0';
    restartInput.value = 'always';

    applyBtn.click();

    await vi.waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        '/api/docker/containers/c11122233344/resources',
        {
          memory_mb: 2048,
          nano_cpus: 4.0,
          restart_policy: 'always'
        }
      );
    });
    await new Promise((r) => setTimeout(r, 30));
  });

  it('pre-checks port availability and submits atomic port reconfiguration', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/details')) return mockContainerDetails;
      if (url.includes('/check_port')) return { port: 8097, proto: 'tcp', available: true };
      return {};
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      status: 'success',
      message: 'Container recreated with updated ports'
    });

    // Mock confirm dialog
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    await openContainerInspector('c11122233344', 'jellyfin');
    await switchContainerTab('ports');

    const portInputs = document.querySelectorAll('.ci-port-input');
    expect(portInputs.length).toBeGreaterThan(0);

    // Edit first port
    const firstInput = portInputs[0];
    firstInput.value = '8097';
    firstInput.dispatchEvent(new window.Event('input', { bubbles: true }));

    // Wait for pre-check
    const statusEl = document.getElementById('ci-port-check-0');
    await vi.waitFor(() => {
      expect(statusEl.textContent).toBe('✓ Available');
    });

    // Click Apply Ports button
    const applyPortsBtn = document.getElementById('ci-btn-apply-ports');
    expect(applyPortsBtn).not.toBeNull();
    applyPortsBtn.click();

    await vi.waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        `/api/docker/containers/${mockContainerDetails.cid}/ports`,
        expect.objectContaining({
          ports: expect.arrayContaining([
            expect.objectContaining({ container_port: 8096, host_port: 8097, proto: 'tcp' })
          ]),
          keep_backup: false
        })
      );
    });
    await new Promise((r) => setTimeout(r, 30));
  });
});

