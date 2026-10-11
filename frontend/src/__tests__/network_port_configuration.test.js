import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  fetchAndRenderNetworkTopology,
  openNetworkPortModal,
  closeNetworkPortModal,
  saveNetworkPortConfig,
  openDockerNetworkCreateModal,
  closeDockerNetworkCreateModal,
  submitDockerNetworkCreate,
  initNetworkControls,
} from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('Network Port Configuration & Docker Network Fleet Management', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.innerHTML = `
      <div id="net-kpi-ip">--</div>
      <div id="net-kpi-iface">--</div>
      <div id="net-kpi-gw">--</div>
      <div id="net-kpi-dns">--</div>
      <div id="net-kpi-speed">--</div>
      <div id="net-kpi-carrier">--</div>
      <div id="net-kpi-docker">--</div>
      <div id="net-kpi-containers">--</div>
      <div id="net-active-ports-badge">--</div>
      <div id="network-switch-faceplate"></div>
      <table><tbody id="network-physical-tbody"></tbody></table>
      <div id="network-bridges-container"></div>
      <div id="network-docker-container"></div>
      <button id="btn-create-docker-net"></button>
      <button id="btn-refresh-network-topology"></button>

      <!-- Port Config Modal -->
      <div id="network-port-config-overlay" style="display: none;">
        <span id="net-port-cfg-dot"></span>
        <strong id="net-port-cfg-iface"></strong>
        <input id="net-port-alias-input" />
        <button class="net-mtu-preset" data-mtu="1500" id="net-mtu-preset-1500"></button>
        <button class="net-mtu-preset" data-mtu="9000" id="net-mtu-preset-9000"></button>
        <input id="net-port-mtu-input" value="1500" />
        <input type="checkbox" id="net-port-wol-toggle" />
        <div id="net-port-wol-desc"></div>
        <select id="net-port-speed-select">
          <option value="auto">Auto</option>
          <option value="10000">10G</option>
          <option value="2500">2.5G</option>
          <option value="1000">1G</option>
        </select>
        <span id="net-port-ro-mac"></span>
        <span id="net-port-ro-driver"></span>
        <span id="net-port-ro-pci"></span>
        <span id="net-port-ro-link"></span>
        <button id="net-port-cfg-close-btn"></button>
        <button id="net-port-cfg-cancel-btn"></button>
        <button id="net-port-cfg-save-btn"></button>
      </div>

      <!-- Docker Create Modal -->
      <div id="network-docker-create-overlay" style="display: none;">
        <input id="net-docker-name-input" />
        <select id="net-docker-driver-select">
          <option value="bridge">bridge</option>
          <option value="macvlan">macvlan</option>
        </select>
        <input id="net-docker-subnet-input" />
        <input id="net-docker-gateway-input" />
        <button id="net-docker-create-close-btn"></button>
        <button id="net-docker-create-cancel-btn"></button>
        <button id="net-docker-create-submit-btn"></button>
      </div>
    `;
    document.body.appendChild(container);
    initNetworkControls();
  });

  afterEach(() => {
    container?.remove();
    vi.restoreAllMocks();
  });

  const mockTopology = {
    status: 'ok',
    summary: {
      primary_ip: '10.40.30.249',
      default_gateway: '10.40.30.1',
      total_physical: 2,
      active_physical: 1,
      max_speed: '10 Gbps',
    },
    physical_interfaces: [
      {
        name: 'eth1',
        alias: 'Direct 10G to Workstation',
        state: 'up',
        carrier: 1,
        is_up: true,
        speed_mbps: 10000,
        speed_human: '10 Gbps',
        duplex: 'full',
        mtu: 1500,
        mac: '04:a1:6f:d0:13:59',
        master: 'bond0',
        pci_slot: '0000:5a:00.0',
        driver: 'r8169',
      },
    ],
    bonds: [],
    bridges: [],
    docker_networks: [
      {
        id: 'cust12345678',
        name: 'custom_iot_net',
        driver: 'bridge',
        subnet: '172.30.0.0/16',
        gateway: '172.30.0.1',
        is_custom: true,
        containers: [],
      },
    ],
  };

  it('renders port alias tag and clickable jack on faceplate and inventory table', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const faceplate = document.getElementById('network-switch-faceplate');
    const jack = faceplate.querySelector('.switch-port-jack');
    expect(jack).toBeTruthy();
    expect(jack.classList.contains('clickable')).toBe(true);
    expect(jack.dataset.iface).toBe('eth1');
    expect(jack.textContent).toContain('Direct 10G to Workstation');

    const tbody = document.getElementById('network-physical-tbody');
    expect(tbody.textContent).toContain('Direct 10G to Workstation');
    const configBtn = tbody.querySelector('.btn-config-port');
    expect(configBtn).toBeTruthy();
    expect(configBtn.dataset.iface).toBe('eth1');
  });

  it('opens port configuration modal and populates port settings and hardware attributes', async () => {
    const mockPortData = {
      status: 'ok',
      interface: {
        name: 'eth1',
        mac: '04:a1:6f:d0:13:59',
        driver: 'r8169',
        pci_slot: '0000:5a:00.0',
        is_up: true,
        speed_human: '10 Gbps',
        duplex: 'full',
        mtu: 1500,
      },
      alias: 'Direct 10G to Workstation',
      mtu: 1500,
      wol_supported: true,
      wol_enabled: true,
      autoneg: true,
      supported_speeds: [10000, 2500, 1000],
    };

    vi.spyOn(api, 'get').mockResolvedValueOnce(mockPortData);

    await openNetworkPortModal('eth1');

    const overlay = document.getElementById('network-port-config-overlay');
    expect(overlay.style.display).toBe('flex');
    expect(document.getElementById('net-port-cfg-iface').textContent).toBe('ETH1');
    expect(document.getElementById('net-port-alias-input').value).toBe('Direct 10G to Workstation');
    expect(document.getElementById('net-port-mtu-input').value).toBe('1500');
    expect(document.getElementById('net-port-wol-toggle').checked).toBe(true);
    expect(document.getElementById('net-port-wol-toggle').disabled).toBe(false);
    expect(document.getElementById('net-port-speed-select').value).toBe('auto');
    expect(document.getElementById('net-port-ro-mac').textContent).toBe('04:a1:6f:d0:13:59');
    expect(document.getElementById('net-mtu-preset-1500').classList.contains('active')).toBe(true);
  });

  it('saves updated port configuration and triggers refresh', async () => {
    const mockPortData = {
      status: 'ok',
      interface: { name: 'eth1', mtu: 1500, is_up: true },
      alias: 'Workstation Link',
      mtu: 1500,
      wol_supported: true,
      wol_enabled: false,
      autoneg: true,
    };

    vi.spyOn(api, 'get').mockResolvedValueOnce(mockPortData);
    await openNetworkPortModal('eth1');

    // Make edits
    document.getElementById('net-port-alias-input').value = 'Workstation Direct 10G';
    document.getElementById('net-port-mtu-input').value = '9000';
    document.getElementById('net-port-wol-toggle').checked = true;
    document.getElementById('net-port-speed-select').value = '10000';

    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'ok' });
    const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await saveNetworkPortConfig();

    expect(postSpy).toHaveBeenCalledWith('/api/network/port/eth1', {
      alias: 'Workstation Direct 10G',
      mtu: 9000,
      wol_enabled: true,
      autoneg: false,
      speed: 10000,
      duplex: 'full',
    });

    expect(toastSpy).toHaveBeenCalledWith(expect.any(String), 'success');
    expect(document.getElementById('network-port-config-overlay').style.display).toBe('none');
  });

  it('manages Docker network creation modal lifecycle and submission', async () => {
    openDockerNetworkCreateModal();
    const overlay = document.getElementById('network-docker-create-overlay');
    expect(overlay.style.display).toBe('flex');

    document.getElementById('net-docker-name-input').value = 'isolated_dmz';
    document.getElementById('net-docker-driver-select').value = 'bridge';
    document.getElementById('net-docker-subnet-input').value = '172.29.0.0/16';
    document.getElementById('net-docker-gateway-input').value = '172.29.0.1';

    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'ok', id: 'dmz123' });
    const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await submitDockerNetworkCreate();

    expect(postSpy).toHaveBeenCalledWith('/api/network/docker/create', {
      name: 'isolated_dmz',
      driver: 'bridge',
      subnet: '172.29.0.0/16',
      gateway: '172.29.0.1',
    });

    expect(toastSpy).toHaveBeenCalledWith(expect.any(String), 'success');
    expect(overlay.style.display).toBe('none');
  });

  it('renders delete button for custom Docker networks and confirms deletion', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const dockerContainer = document.getElementById('network-docker-container');
    const deleteBtn = dockerContainer.querySelector('.net-docker-delete-btn');
    expect(deleteBtn).toBeTruthy();
    expect(deleteBtn.dataset.netId).toBe('cust12345678');
    expect(deleteBtn.dataset.netName).toBe('custom_iot_net');

    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValueOnce({ status: 'ok' });
    const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    vi.spyOn(toast, 'showConfirmToast').mockImplementation((msg, cb) => cb());
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    deleteBtn.click();

    expect(deleteSpy).toHaveBeenCalledWith('/api/network/docker/cust12345678');
  });
});
