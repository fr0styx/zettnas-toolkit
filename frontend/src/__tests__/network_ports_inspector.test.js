import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchListeningPorts, renderListeningPortsTable, initNetworkPortsInspector } from '../components/network-manager.js';
import { api } from '../api.js';

describe('Network Manager - Listening Ports Inspector', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="mgmt-pane-network-ports">
        <input type="text" id="net-ports-search">
        <button id="btn-refresh-net-ports">Refresh</button>
        <table id="table-net-listening-ports">
          <tbody id="net-listening-ports-tbody"></tbody>
        </table>
      </div>
    `;
    vi.restoreAllMocks();
  });

  it('renders listening ports and formats protocol and container badges correctly', () => {
    const mockPorts = [
      { port: 8082, protocol: 'tcp', bind_address: '0.0.0.0', service: 'ZettNAS Web Desktop', container: 'zettnas-toolkit', state: 'LISTEN' },
      { port: 5353, protocol: 'udp', bind_address: '0.0.0.0', service: 'mDNS / Bonjour', container: '', state: 'ACTIVE' },
    ];

    renderListeningPortsTable(mockPorts);

    const tbody = document.getElementById('net-listening-ports-tbody');
    const rows = tbody.querySelectorAll('tr');
    expect(rows.length).toBe(2);

    expect(rows[0].textContent).toContain(':8082');
    expect(rows[0].textContent).toContain('TCP');
    expect(rows[0].textContent).toContain('ZettNAS Web Desktop');
    expect(rows[0].textContent).toContain('zettnas-toolkit');

    expect(rows[1].textContent).toContain(':5353');
    expect(rows[1].textContent).toContain('UDP');
    expect(rows[1].textContent).toContain('mDNS / Bonjour');
    expect(rows[1].textContent).toContain('Host System / Kernel');
  });

  it('filters listening ports by search query', () => {
    const mockPorts = [
      { port: 22, protocol: 'tcp', bind_address: '127.0.0.1', service: 'SSH', container: '', state: 'LISTEN' },
      { port: 8096, protocol: 'tcp', bind_address: '0.0.0.0', service: 'Jellyfin Media Server', container: 'jellyfin', state: 'LISTEN' },
    ];

    renderListeningPortsTable(mockPorts, 'jelly');

    const tbody = document.getElementById('net-listening-ports-tbody');
    const rows = tbody.querySelectorAll('tr');
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toContain(':8096');
    expect(rows[0].textContent).toContain('Jellyfin Media Server');
  });

  it('fetches listening ports from API and updates table', async () => {
    const mockResponse = {
      ports: [
        { port: 445, protocol: 'tcp', bind_address: '0.0.0.0', service: 'SMB / CIFS', container: 'zettnas-samba', state: 'LISTEN' }
      ]
    };
    vi.spyOn(api, 'get').mockResolvedValue(mockResponse);

    const ports = await fetchListeningPorts();
    expect(ports.length).toBe(1);

    const tbody = document.getElementById('net-listening-ports-tbody');
    expect(tbody.innerHTML).toContain(':445');
    expect(tbody.innerHTML).toContain('SMB / CIFS');
  });
});
