import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchAndRenderNetworkTopology } from '../components/management.js';
import { api } from '../api.js';

describe('Batch 5: the Network page layout', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.innerHTML = `
      <div id="net-home"></div>
      <ul id="net-port-rows"></ul>
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
      primary_ip: '192.168.1.50',
      default_gateway: '192.168.1.1',
      dns_servers: ['192.168.1.1', '1.1.1.1'],
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
        ip_address: '192.168.1.50/24',
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

  it('says where the NAS answers at home, with the router and name servers under Details (SET-24 m)', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const home = document.getElementById('net-home');
    expect(home.querySelector('.net-home-line').textContent).toContain('At home, this NAS answers at 192.168.1.50.');
    expect(home.querySelector('[data-copy]').dataset.copy).toBe('192.168.1.50');
    const details = home.querySelector('.net-home-details').textContent;
    expect(details).toContain('192.168.1.1, 1.1.1.1');
    expect(details).toContain('br0');
    expect(home.querySelector('#btn-open-host-ip-modal')).not.toBeNull();
  });

  it('one row per port, with Connected or Not connected in words and the speed (SET-24 m)', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const rows = document.querySelectorAll('#net-port-rows .net-port-row');
    expect(rows.length).toBe(2);
    const eth1 = document.querySelector('.net-port-row[data-iface="eth1"]');
    expect(eth1.classList.contains('is-up')).toBe(true);
    expect(eth1.querySelector('.net-port-state').textContent).toBe('Connected');
    expect(eth1.querySelector('.net-port-speed').textContent).toBe('10 Gbps');
    const eth0 = document.querySelector('.net-port-row[data-iface="eth0"]');
    expect(eth0.querySelector('.net-port-state').textContent).toBe('Not connected');
    expect(eth0.querySelector('.net-port-speed').textContent).toBe(''); // not the host's English "Disconnected"
  });

  it('a port\'s details carry its hardware address, driver, bond and traffic', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const details = document.querySelector('.net-port-row[data-iface="eth1"] .net-port-details').textContent;
    expect(details).toContain('04:a1:6f:d0:13:59');
    expect(details).toContain('r8169');
    expect(details).toContain('bond0');
    expect(details).toContain('Received / sent');
    expect(document.querySelector('.net-port-row[data-iface="eth0"] .net-port-details').textContent).not.toContain('Received / sent');
  });

  it('renders host bridges and bonding groups card grid', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

    await fetchAndRenderNetworkTopology();

    const bridgesContainer = document.getElementById('network-bridges-container');
    expect(bridgesContainer.textContent).toContain('Bridge: br0');
    expect(bridgesContainer.textContent).toContain('192.168.1.50/24');
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

    expect(document.getElementById('net-home').textContent).toBe('Could not load the network layout: Connection lost');
    expect(document.querySelector('#net-port-rows > li .state-block.is-failed')).not.toBeNull();
  });
});
