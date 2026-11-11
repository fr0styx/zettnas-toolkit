/** NUX-20: the network settings panel's empty, partial and failed states read as plain words. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { api } from '../api.js';
import {
  fetchAndRenderCopyHistory,
  fetchAndRenderReplication,
  renderTailscalePeersTable,
  fetchAndRenderWireguard,
  fetchAndRenderNetworkTopology,
  openNetworkPortModal,
  openBondConfigModal,
  openBridgeConfigModal,
} from '../components/management.js';

const byId = (id) => document.getElementById(id);

describe('network settings states (NUX-20)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('says when there is no history or replication yet, and when it could not load', async () => {
    document.body.innerHTML = `
      <table><tbody id="copy-history-tbody"></tbody></table>
      <table><tbody id="replication-jobs-tbody"></tbody></table>
      <table><tbody id="replication-history-tbody"></tbody></table>`;
    const get = vi.spyOn(api, 'get').mockResolvedValue([]);
    await fetchAndRenderCopyHistory();
    expect(byId('copy-history-tbody').textContent).toBe('No imports recorded yet.');
    get.mockResolvedValue({ jobs: [], history: [] });
    await fetchAndRenderReplication();
    expect(byId('replication-jobs-tbody').textContent).toContain('No replication jobs yet.');
    expect(byId('replication-history-tbody').textContent).toBe('No replication runs yet.');

    get.mockRejectedValue(new Error('timeout'));
    await fetchAndRenderCopyHistory();
    expect(byId('copy-history-tbody').textContent).toBe('Could not load the history: timeout');
    get.mockResolvedValue(null); // a request that fails is answered empty; an empty answer is the failure left
    await fetchAndRenderReplication();
    expect(byId('replication-jobs-tbody').textContent).toMatch(/^Could not load the replication jobs: /);
  });

  it('lists tailnet devices, with ping only for those with an address', () => {
    document.body.innerHTML = '<span id="ts-peer-count-pill"></span><table><tbody id="ts-peers-table-body"></tbody></table>';
    renderTailscalePeersTable([
      { hostname: 'phone', ip: '100.64.0.2', online: true, direct: true },
      { hostname: 'laptop', ip: '', online: false },
    ]);
    expect(byId('ts-peer-count-pill').textContent).toBe('1 online / 2 total');
    const rows = byId('ts-peers-table-body').querySelectorAll('tr');
    expect(rows[0].textContent).toContain('Online');
    expect(rows[1].textContent).toContain('Offline');
    expect(rows[1].querySelector('.btn-ping-peer').disabled).toBe(true);
    expect(rows[0].querySelector('.btn-ping-peer').textContent).toContain('Ping');
    renderTailscalePeersTable([{ hostname: 'phone', ip: '100.64.0.2' }], 'nothing-like-this');
    expect(byId('ts-peers-table-body').textContent).toBe('No devices match the search.');
  });

  it('shows a sign-in about to expire, and no switch for a public Funnel (SET-02)', async () => {
    document.body.innerHTML = `
      <span id="tailscale-status-badge"></span><span id="ts-connection-pill"></span>
      <span id="ts-key-expiry-display"></span><button id="btn-ts-reauth"></button>
      <span id="ts-ssh-pill"></span><span id="ts-serve-pill"></span>`;
    const ts = { installed: true, active: true, backend_state: 'Running', ipv4: '100.64.0.1', key_expiry_days: 5, funnel_enabled: true, ssh_enabled: false, serve_enabled: false };
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/network/mesh-vpn' ? { tailscale: ts, wireguard: {} } : {}));
    await fetchAndRenderWireguard();
    expect(byId('ts-key-expiry-display').textContent).toBe('⚠️ Expires in 5 days');
    expect(byId('ts-ssh-pill').textContent).toBe('Disabled');
    get.mockImplementation(async (url) => (url === '/api/network/mesh-vpn' ? { tailscale: { ...ts, key_expiry_days: 1, funnel_enabled: false, ssh_enabled: true, serve_enabled: true }, wireguard: {} } : {}));
    await fetchAndRenderWireguard();
    expect(byId('ts-key-expiry-display').textContent).toBe('⚠️ Expires in 1 day');
    expect(byId('ts-ssh-pill').textContent).toBe('Enabled');
    expect(byId('ts-serve-pill').textContent).toBe('Active');
  });
});

describe('network layout with missing parts (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="net-kpi-ip"></div><div id="net-kpi-iface"></div><div id="net-kpi-gw"></div><div id="net-kpi-dns"></div>
      <div id="net-kpi-speed"></div><div id="net-kpi-carrier"></div><div id="net-kpi-docker"></div><div id="net-kpi-containers"></div>
      <div id="net-active-ports-badge"></div><div id="network-switch-faceplate"></div>
      <table><tbody id="network-physical-tbody"></tbody></table>
      <div id="network-bridges-container"></div><div id="network-docker-container"></div>
      <table><tbody id="network-vlan-tbody"></tbody></table>`;
  });
  afterEach(() => vi.restoreAllMocks());

  it('falls back to plain words when the host says little', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ status: 'ok', summary: {}, physical_interfaces: [], bonds: [], bridges: [], docker_networks: [], vlans: [] });
    await fetchAndRenderNetworkTopology();
    expect(byId('net-kpi-iface').textContent).toBe('Via eth0');
    expect(byId('net-kpi-carrier').textContent).toBe('0 of 0 ports online');
    expect(byId('net-kpi-docker').textContent).toBe('0 networks');
    expect(byId('net-kpi-containers').textContent).toBe('0 containers attached');
    expect(byId('net-active-ports-badge').textContent).toBe('0 active');
    expect(byId('network-switch-faceplate').textContent).toBe('No network ports found.');
    expect(byId('network-physical-tbody').textContent).toBe('No network ports found.');
    expect(byId('network-bridges-container').textContent).toBe('No virtual bridges or bonds yet.');
    expect(byId('network-vlan-tbody').textContent).toBe('No VLANs yet. Add one to tag a port.');
    expect(byId('network-docker-container').textContent).toBe('No Docker bridge networks in use.');
  });

  it('names ports, bridges and bonds without their optional details', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      status: 'ok',
      summary: { primary_interface: 'br0', active_physical: 1, total_physical: 1, docker_networks_count: 1, docker_containers_count: 1 },
      physical_interfaces: [{ name: 'eth0', is_up: true }, { name: 'eth1', is_up: false, master: 'br0', driver: 'igc', speed_human: '1 Gbps' }],
      bridges: [{ name: 'br0', interfaces: [] }],
      bonds: [{ name: 'bond0' }],
      docker_networks: [{ name: 'apps', subnet: '172.30.0.0/16', containers: [] }],
      vlans: [],
    });
    await fetchAndRenderNetworkTopology();
    const face = byId('network-switch-faceplate').textContent;
    expect(face).toContain('Connected');
    expect(face).toContain('Master: br0');
    expect(byId('network-switch-faceplate').querySelector('[data-iface="eth0"]').getAttribute('title')).toBe('Set up eth0');
    const table = byId('network-physical-tbody').textContent;
    expect(table).toContain('Standalone');
    expect(table).toContain('Generic');
    const virt = byId('network-bridges-container').textContent;
    expect(virt).toContain('Bridge: br0');
    expect(virt).toContain('No members');
    expect(virt).toContain('Bond: bond0');
    expect(virt).toContain('Active port: None');
    expect(virt).toContain('Forward delay: 0 s');
    const docker = byId('network-docker-container').textContent;
    expect(docker).toContain('Subnet: 172.30.0.0/16');
    expect(docker).not.toContain('Gateway:');
    expect(docker).toContain('No containers attached');
    expect(byId('net-kpi-containers').textContent).toBe('1 container attached');
  });

  it('says when the layout could not be read', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ status: 'error' });
    await fetchAndRenderNetworkTopology();
    expect(byId('network-physical-tbody').textContent).toBe('Could not load the network layout: Unknown error');
    get.mockRejectedValue(new Error('no route'));
    await fetchAndRenderNetworkTopology();
    expect(byId('network-physical-tbody').textContent).toBe('Could not load the network layout: no route');
  });
});

describe('port, bond and bridge settings (NUX-20)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('describes a port that is down or has no Wake-on-LAN', async () => {
    document.body.innerHTML = `
      <div id="network-port-config-overlay"></div><span id="net-port-cfg-iface"></span><span id="net-port-cfg-dot"></span>
      <span id="net-port-wol-desc"></span><span id="net-port-ro-driver"></span><span id="net-port-ro-link"></span>`;
    const get = vi.spyOn(api, 'get').mockResolvedValue({ interface: { is_up: false }, wol_supported: false });
    await openNetworkPortModal('eth0');
    expect(byId('net-port-wol-desc').textContent).toBe('This network card can’t wake the NAS (no Wake-on-LAN).');
    expect(byId('net-port-ro-driver').textContent).toBe('Generic');
    expect(byId('net-port-ro-link').textContent).toBe('Down (disconnected)');
    get.mockResolvedValue({ interface: { is_up: true, driver: 'igc' }, wol_supported: true });
    await openNetworkPortModal('eth0');
    expect(byId('net-port-ro-link').textContent).toBe('Connected (full)');
  });

  it('says when no port can join a bond or a bridge', async () => {
    document.body.innerHTML = `
      <div id="network-bond-config-overlay"></div><div id="net-bond-slaves-container"></div>
      <div id="network-bridge-config-overlay"></div><div id="net-bridge-members-container"></div>`;
    const get = vi.spyOn(api, 'get').mockResolvedValue({ candidate_slaves: [], candidate_members: [] });
    await openBondConfigModal('bond0');
    expect(byId('net-bond-slaves-container').textContent).toBe('No Ethernet adapters found.');
    await openBridgeConfigModal('br0');
    expect(byId('net-bridge-members-container').textContent).toBe('No ports available to bridge.');
    get.mockResolvedValue({ candidate_slaves: [{ name: 'eth0', is_up: true }, { name: 'eth1', is_up: false }] });
    await openBondConfigModal('bond0');
    const text = byId('net-bond-slaves-container').textContent;
    expect(text).toContain('Connected');
    expect(text).toContain('Disconnected');
  });
});
