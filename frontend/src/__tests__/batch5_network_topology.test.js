import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchAndRenderNetworkTopology } from '../components/management.js';
import { api } from '../api.js';

describe('Batch 5: Interactive Visual Network & Virtual Switch Inspector UI', () => {
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
    `;
    document.body.appendChild(container);
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
      dns_servers: ['10.40.30.1', '1.1.1.1'],
      primary_interface: 'br0',
      total_physical: 2,
      active_physical: 1,
      max_speed: '10 Gbps',
      docker_networks_count: 3,
      docker_containers_count: 5,
    },
    physical_interfaces: [
      {
        name: 'eth1',
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
        rx_bytes: 36190051705,
        tx_bytes: 32924064038,
        rx_packets: 68043585,
        tx_packets: 41880143,
      },
      {
        name: 'eth0',
        state: 'down',
        carrier: 0,
        is_up: false,
        speed_mbps: null,
        speed_human: 'Disconnected',
        duplex: 'unknown',
        mtu: 1500,
        mac: '04:a1:6f:d0:13:59',
        master: 'bond0',
        pci_slot: '0000:59:00.0',
        driver: 'r8169',
        rx_bytes: 0,
        tx_bytes: 0,
        rx_packets: 0,
        tx_packets: 0,
      },
    ],
    bonds: [
      {
        name: 'bond0',
        mode: 'active-backup 1',
        slaves: ['eth0', 'eth1'],
        active_slave: 'eth1',
        carrier: 1,
        is_up: true,
        speed_human: '10 Gbps',
      },
    ],
    bridges: [
      {
        name: 'br0',
        interfaces: ['bond0'],
        carrier: 1,
        is_up: true,
        ip_address: '10.40.30.249/24',
      },
    ],
    docker_networks: [
      {
        id: '7ba745ce7428',
        name: 'arr_default',
        driver: 'bridge',
        subnet: '172.20.0.0/16',
        gateway: '172.20.0.1',
        bridge_device: 'br-7ba745ce7428',
        containers: [
          {
            name: 'prowlarr',
            id: '531649d805ab',
            ipv4: '172.20.0.7',
            mac: 'fe:45:2d:4d:fe:10',
            ports: ['9696:9696/tcp'],
          },
          {
            name: 'radarr',
            id: 'b0dedb6a15d7',
            ipv4: '172.20.0.8',
            mac: '96:93:12:ec:6b:1f',
            ports: ['7878:7878/tcp'],
          },
        ],
      },
    ],
  };

  it('updates 4-KPI metric cards correctly from summary', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    expect(document.getElementById('net-kpi-ip').textContent).toBe('10.40.30.249');
    expect(document.getElementById('net-kpi-iface').textContent).toBe('Via br0');
    expect(document.getElementById('net-kpi-gw').textContent).toBe('10.40.30.1');
    expect(document.getElementById('net-kpi-dns').textContent).toContain('10.40.30.1');
    expect(document.getElementById('net-kpi-speed').textContent).toBe('10 Gbps');
    expect(document.getElementById('net-kpi-carrier').textContent).toBe('1 of 2 Ports Online');
    expect(document.getElementById('net-kpi-docker').textContent).toBe('3 Networks');
    expect(document.getElementById('net-active-ports-badge').textContent).toBe('1 Active');
  });

  it('renders front-panel visual switch jack matrix with active LEDs and speed pills', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const faceplate = document.getElementById('network-switch-faceplate');
    const jacks = faceplate.querySelectorAll('.switch-port-jack');
    expect(jacks.length).toBe(2);

    // First jack (eth1 - active 10G)
    const eth1Jack = Array.from(jacks).find((j) => j.textContent.includes('ETH1'));
    expect(eth1Jack).toBeTruthy();
    expect(eth1Jack.classList.contains('is-active')).toBe(true);
    expect(eth1Jack.querySelector('.led-link-on')).toBeTruthy();
    expect(eth1Jack.querySelector('.led-speed-10g')).toBeTruthy();
    expect(eth1Jack.querySelector('.speed-10g').textContent).toBe('10 Gbps');
    expect(eth1Jack.textContent).toContain('Master: bond0');

    // Second jack (eth0 - disconnected)
    const eth0Jack = Array.from(jacks).find((j) => j.textContent.includes('ETH0'));
    expect(eth0Jack).toBeTruthy();
    expect(eth0Jack.classList.contains('is-active')).toBe(false);
    expect(eth0Jack.querySelector('.speed-down').textContent).toBe('Disconnected');
  });

  it('renders physical interfaces detailed table with MAC and throughput counters', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const tbody = document.getElementById('network-physical-tbody');
    const rows = tbody.querySelectorAll('tr');
    expect(rows.length).toBe(2);

    expect(tbody.textContent).toContain('eth1');
    expect(tbody.textContent).toContain('04:a1:6f:d0:13:59');
    expect(tbody.textContent).toContain('UP / CARRIER');
    expect(tbody.textContent).toContain('r8169');
    expect(tbody.textContent).toContain('0000:5a:00.0');
  });

  it('renders host bridges and bonding groups card grid', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const bridgesContainer = document.getElementById('network-bridges-container');
    expect(bridgesContainer.textContent).toContain('Bridge: br0');
    expect(bridgesContainer.textContent).toContain('10.40.30.249/24');
    expect(bridgesContainer.textContent).toContain('Bond: bond0');
    expect(bridgesContainer.textContent).toContain('active-backup 1');
    expect(bridgesContainer.textContent).toContain('eth1');
  });

  it('renders Docker bridge networks and attached container allocation chips', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const dockerContainer = document.getElementById('network-docker-container');
    expect(dockerContainer.textContent).toContain('arr_default');
    expect(dockerContainer.textContent).toContain('172.20.0.0/16');
    expect(dockerContainer.textContent).toContain('prowlarr');
    expect(dockerContainer.textContent).toContain('172.20.0.7');
    expect(dockerContainer.textContent).toContain('radarr');
    expect(dockerContainer.textContent).toContain('172.20.0.8');
    expect(dockerContainer.textContent).toContain('9696:9696/tcp');
  });

  it('handles API network failure gracefully', async () => {
    vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('Connection lost'));

    await fetchAndRenderNetworkTopology();

    const tbody = document.getElementById('network-physical-tbody');
    expect(tbody.textContent).toContain('Failed to load network topology');
    expect(tbody.textContent).toContain('Connection lost');
  });
});
