import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fetchAndRenderWireguard, renderTailscalePeersTable } from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('Zero-Trust Mesh VPN Suite (WireGuard & Tailscale)', () => {
  let container;

  beforeEach(() => {
    vi.restoreAllMocks();
    container = document.createElement('div');
    container.innerHTML = `
      <div id="section-header-tailscale"></div>
      <div id="network-tailscale-container"></div>
      <div id="section-header-wireguard"></div>
      <div id="network-wireguard-container"></div>

      <span id="tailscale-status-badge"></span>
      <span id="ts-connection-pill"></span>
      <code id="ts-ipv4-display">--</code>
      <button id="btn-copy-ts-ip" style="display:none;"></button>
      <code id="ts-tailnet-display">--</code>
      <span id="ts-hostname-display">--</span>
      <span id="ts-peers-display">0 peers</span>

      <div id="ts-deploy-banner" style="display:none;"></div>
      <button id="btn-deploy-tailscale"></button>
      <div id="ts-auth-prompt" style="display:none;"></div>
      <a id="ts-auth-link" href="#"></a>
      <button id="btn-copy-ts-auth-url"></button>

      <div id="ts-connect-form"></div>
      <div id="ts-connected-view" style="display:none;"></div>
      <div id="ts-form-intro"></div>
      <input id="ts-auth-key-input" value="" />
      <input id="ts-hostname-input" value="" />
      <input type="checkbox" id="ts-accept-routes-input" checked />
      <button id="btn-tailscale-up">🚀 Connect Tailscale</button>
      <button id="btn-tailscale-down" style="display:none;">🔌 Disconnect</button>

      <span id="wg-tunnel-status-badge"></span>
      <span id="wg-forwarding-pill"></span>
      <span id="wg-ip-forward-status"></span>
      <code id="wg-pubkey-display">--</code>
      <button id="btn-toggle-wg-subnet-nat"></button>
      <button id="btn-wg-gen-client-config"></button>
      <button id="btn-copy-wg-conf"></button>
      <button id="btn-download-wg-conf"></button>
      <pre id="wg-conf-preview"></pre>
      <div id="wg-qr-box" style="display:none;">
        <div id="wg-qr-canvas-wrap"></div>
      </div>
      <button id="btn-refresh-wireguard"></button>

      <!-- Capability 7: Key Expiry & Re-auth -->
      <span id="ts-key-expiry-display">--</span>
      <button id="btn-ts-reauth" style="display:none;"></button>

      <!-- Capability 1: Subnet Router -->
      <input type="checkbox" id="ts-subnet-router-toggle" />
      <input type="text" id="ts-subnet-routes-input" value="" />
      <button id="btn-ts-save-routes"></button>

      <!-- Capability 2: Exit Node -->
      <input type="checkbox" id="ts-exit-node-toggle" />
      <span id="ts-exit-node-pill"></span>

      <!-- Capability 3: SSH -->
      <input type="checkbox" id="ts-ssh-toggle" />
      <span id="ts-ssh-pill"></span>

      <!-- Capability 4 & 5: Extended Grid -->
      <div id="network-tailscale-extended" style="display:none;"></div>
      <span id="ts-serve-pill"></span>
      <input type="checkbox" id="ts-serve-toggle" />
      <div id="ts-serve-url-box" style="display:none;"></div>
      <a id="ts-serve-url-link" href="#"></a>
      <input type="checkbox" id="ts-funnel-toggle" />
      <span id="ts-funnel-pill"></span>

      <span id="ts-taildrop-badge"></span>
      <button id="btn-ts-taildrop-fetch"></button>
      <button id="btn-ts-taildrop-open"></button>
      <div id="ts-taildrop-list"></div>

      <!-- Capability 6: Peer directory -->
      <div id="tailscale-peers-card" style="display:none;"></div>
      <input type="text" id="ts-peer-search" />
      <span id="ts-peer-count-pill"></span>
      <table id="ts-peers-table">
        <tbody id="ts-peers-table-body"></tbody>
      </table>

      <div id="mesh-service-filter">
        <button data-mesh-filter="all" class="active">All</button>
        <button data-mesh-filter="tailscale">Tailscale</button>
        <button data-mesh-filter="wireguard">WireGuard</button>
      </div>
    `;
    document.body.appendChild(container);
  });

  it('renders Tailscale active connection telemetry correctly', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/network/mesh-vpn') {
        return {
          tailscale: {
            installed: true,
            active: true,
            backend_state: 'Running',
            ipv4: '100.80.20.10',
            tailnet: 'zettnas.ts.net',
            hostname: 'zettnas-host',
            peers_count: 3,
          },
          wireguard: {
            installed: true,
            active: true,
            interfaces: ['wg0'],
          },
        };
      }
      if (url === '/api/network/mesh-vpn/wireguard/subnet-routing') {
        return { ip_forwarding: true, enabled: true };
      }
      return null;
    });

    await fetchAndRenderWireguard();

    expect(document.getElementById('tailscale-status-badge').textContent).toBe('Active (Connected)');
    expect(document.getElementById('ts-connection-pill').textContent).toBe('Connected');
    expect(document.getElementById('ts-ipv4-display').textContent).toBe('100.80.20.10');
    expect(document.getElementById('ts-tailnet-display').textContent).toBe('zettnas.ts.net');
    expect(document.getElementById('ts-hostname-display').textContent).toBe('zettnas-host');
    expect(document.getElementById('ts-peers-display').textContent).toBe('3 peer(s)');
    expect(document.getElementById('ts-connected-view').style.display).toBe('flex');
    expect(document.getElementById('ts-connect-form').style.display).toBe('none');
    expect(document.getElementById('btn-tailscale-down').style.display).toBe('inline-block');
    expect(document.getElementById('ts-deploy-banner').style.display).toBe('none');
  });

  it('handles Tailscale when disconnected with pre-auth form', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/network/mesh-vpn') {
        return {
          tailscale: {
            installed: true,
            active: false,
            backend_state: 'NeedsLogin',
            ipv4: '',
            tailnet: '',
            hostname: 'zettnas-box',
            peers_count: 0,
          },
          wireguard: { installed: true, active: false, interfaces: [] },
        };
      }
      return { ip_forwarding: true, enabled: false };
    });

    await fetchAndRenderWireguard();

    expect(document.getElementById('tailscale-status-badge').textContent).toBe('Needs Login');
    expect(document.getElementById('ts-connection-pill').textContent).toBe('Login Required');
    expect(document.getElementById('ts-connect-form').style.display).toBe('flex');
    expect(document.getElementById('ts-connected-view').style.display).toBe('none');
    expect(document.getElementById('btn-tailscale-down').style.display).toBe('none');
    expect(document.getElementById('ts-deploy-banner').style.display).toBe('none');
  });

  it('triggers Tailscale up POST on connect button click', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      tailscale: { installed: true, active: false, backend_state: 'Stopped' },
      wireguard: { installed: true, active: false },
    });
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'success' });
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});

    await fetchAndRenderWireguard();

    const authInput = document.getElementById('ts-auth-key-input');
    const hostInput = document.getElementById('ts-hostname-input');
    authInput.value = 'tskey-auth-sample123';
    hostInput.value = 'my-custom-node';

    const connectBtn = document.getElementById('btn-tailscale-up');
    connectBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/up', {
      auth_key: 'tskey-auth-sample123',
      hostname: 'my-custom-node',
      accept_routes: true,
    });
  });

  it('surfaces 1-click deployment when Tailscale is not installed', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      tailscale: { installed: false, active: false },
      wireguard: { installed: true, active: false },
    });

    await fetchAndRenderWireguard();

    expect(document.getElementById('ts-deploy-banner').style.display).toBe('block');
    expect(document.getElementById('btn-tailscale-up').textContent).toBe('⚡ 1-Click Deploy Tailscale');
    expect(document.getElementById('tailscale-status-badge').textContent).toBe('Not Installed');
  });

  it('triggers 1-click deploy POST via single button btn-tailscale-up and opens browser auth prompt', async () => {
    const windowOpenSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    vi.spyOn(api, 'get').mockResolvedValue({
      tailscale: { installed: false, active: false },
      wireguard: { installed: true, active: false },
    });
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      status: 'success',
      container_id: 'c12345678901',
      auth_url: 'https://login.tailscale.com/a/oauth123',
    });
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});

    await fetchAndRenderWireguard();

    const hostInput = document.getElementById('ts-hostname-input');
    hostInput.value = 'zettnas-appliance';

    const upBtn = document.getElementById('btn-tailscale-up');
    expect(upBtn.textContent).toBe('⚡ 1-Click Deploy Tailscale');
    await upBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/deploy', {
      auth_key: null,
      hostname: 'zettnas-appliance',
      accept_routes: true,
    });

    expect(windowOpenSpy).toHaveBeenCalledWith('https://login.tailscale.com/a/oauth123', '_blank', 'noopener,noreferrer');
    expect(document.getElementById('ts-auth-prompt').style.display).toBe('block');
    expect(document.getElementById('ts-auth-link').href).toBe('https://login.tailscale.com/a/oauth123');
    expect(upBtn.textContent).toBe('🔗 Log in to Tailscale');
    windowOpenSpy.mockRestore();
  });

  it('renders NeedsLogin state with auth URL automatically and streamlines login action', async () => {
    const windowOpenSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    vi.spyOn(api, 'get').mockResolvedValue({
      tailscale: {
        installed: true,
        active: false,
        backend_state: 'NeedsLogin',
        auth_url: 'https://login.tailscale.com/a/resume456',
      },
      wireguard: { installed: true, active: false },
    });
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});

    await fetchAndRenderWireguard();

    expect(document.getElementById('tailscale-status-badge').textContent).toBe('Needs Login');
    expect(document.getElementById('ts-auth-prompt').style.display).toBe('block');
    expect(document.getElementById('ts-auth-link').href).toBe('https://login.tailscale.com/a/resume456');

    const upBtn = document.getElementById('btn-tailscale-up');
    expect(upBtn.textContent).toBe('🔗 Log in to Tailscale');

    await upBtn.click();
    expect(windowOpenSpy).toHaveBeenCalledWith('https://login.tailscale.com/a/resume456', '_blank', 'noopener,noreferrer');
    windowOpenSpy.mockRestore();
  });

  it('filters services between all, tailscale, and wireguard', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      tailscale: { installed: true, active: true },
      wireguard: { installed: true, active: true },
    });

    await fetchAndRenderWireguard();

    const tsBtn = document.querySelector('button[data-mesh-filter="tailscale"]');
    tsBtn.click();

    const tsHeader = document.getElementById('section-header-tailscale');
    const wgHeader = document.getElementById('section-header-wireguard');

    expect(tsHeader.style.display).toBe('flex');
    expect(wgHeader.style.display).toBe('none');

    const wgBtn = document.querySelector('button[data-mesh-filter="wireguard"]');
    wgBtn.click();

    expect(tsHeader.style.display).toBe('none');
    expect(wgHeader.style.display).toBe('flex');
  });

  it('generates WireGuard client config with formatted .conf text, export button, and QR code SVG', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      tailscale: { installed: true, active: true },
      wireguard: { installed: true, active: true },
    });

    const mockConf = `[Interface]\nPrivateKey = privkey123\nAddress = 10.13.13.2/32\n\n[Peer]\nPublicKey = pubkey456\nEndpoint = 10.40.30.249:51820\nAllowedIPs = 0.0.0.0/0\n`;
    vi.spyOn(api, 'post').mockImplementation(async (url) => {
      if (url === '/api/network/mesh-vpn/wireguard/client-config') {
        return {
          client_name: 'test-client',
          private_key: 'privkey123',
          public_key: 'pubkey456',
          config_text: mockConf,
          config_content: mockConf,
        };
      }
      return {};
    });

    await fetchAndRenderWireguard();

    const genBtn = document.getElementById('btn-wg-gen-client-config');
    genBtn.click();

    await vi.waitFor(() => {
      expect(document.getElementById('wg-conf-preview').textContent).toBe(mockConf);
    });

    const dlBtn = document.getElementById('btn-download-wg-conf');
    expect(dlBtn.style.display).toBe('inline-block');

    const copyBtn = document.getElementById('btn-copy-wg-conf');
    expect(copyBtn.style.display).toBe('inline-block');

    const qrBox = document.getElementById('wg-qr-box');
    expect(qrBox.style.display).toBe('flex');
    const qrWrap = document.getElementById('wg-qr-canvas-wrap');
    expect(qrWrap.innerHTML).toContain('<svg');
  });

  it('renders and interacts with Tailscale extended capabilities (Key Expiry, Subnet Router, Exit Node, SSH, Serve, Funnel, Taildrop)', async () => {
    const mockTsData = {
      installed: true,
      active: true,
      backend_state: 'Running',
      ipv4: '100.80.20.10',
      tailnet: 'zettnas.ts.net',
      hostname: 'zettnas-host',
      peers_count: 2,
      key_expiry_days: 179,
      key_expiry: '2027-04-10T12:00:00Z',
      key_expired: false,
      is_subnet_router: true,
      advertised_routes: '10.40.30.0/24',
      detected_subnets: ['10.40.30.0/24'],
      is_exit_node: true,
      advertise_exit_node: true,
      ssh_enabled: true,
      serve_enabled: true,
      serve_url: 'https://ark.ts.net',
      funnel_enabled: false,
      taildrop_files: [{ name: 'test-backup.tar.gz', size: 2048, size_human: '2.0 KB' }],
      peers: [
        { id: 'p1', hostname: 'macbook-pro', os: 'macOS', ip: '100.80.20.11', online: true, direct: true },
      ],
    };

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/network/mesh-vpn') {
        return {
          tailscale: mockTsData,
          wireguard: { installed: true, active: true },
        };
      }
      return null;
    });

    const postSpy = vi.spyOn(api, 'post').mockImplementation(async (url) => {
      if (url === '/api/network/mesh-vpn/tailscale/set-routes') {
        return { status: 'ok', routes: '192.168.1.0/24', enabled: true };
      }
      if (url === '/api/network/mesh-vpn/tailscale/set-exit-node') {
        return { status: 'ok', enabled: false };
      }
      if (url === '/api/network/mesh-vpn/tailscale/set-ssh') {
        return { status: 'ok', enabled: false };
      }
      if (url === '/api/network/mesh-vpn/tailscale/set-serve') {
        return { status: 'ok', serve_url: 'https://ark.ts.net' };
      }
      if (url === '/api/network/mesh-vpn/tailscale/taildrop/receive') {
        return { status: 'success', count: 1, files: [] };
      }
      if (url === '/api/network/mesh-vpn/tailscale/reauth') {
        return { status: 'needs_login', auth_url: 'https://login.tailscale.com/a/reauth_test' };
      }
      return {};
    });

    vi.spyOn(toast, 'showToast').mockImplementation(() => {});

    await fetchAndRenderWireguard();

    // 1. Key expiry telemetry
    const keyExpiryDisplay = document.getElementById('ts-key-expiry-display');
    expect(keyExpiryDisplay.textContent).toContain('179 days');
    const reauthBtn = document.getElementById('btn-ts-reauth');
    expect(reauthBtn.style.display).toBe('inline-block');

    // 2. Subnet Router
    const subnetToggle = document.getElementById('ts-subnet-router-toggle');
    expect(subnetToggle.checked).toBe(true);
    const subnetInput = document.getElementById('ts-subnet-routes-input');
    expect(subnetInput.value).toBe('10.40.30.0/24');

    // 3. Exit Node
    const exitToggle = document.getElementById('ts-exit-node-toggle');
    expect(exitToggle.checked).toBe(true);
    const exitPill = document.getElementById('ts-exit-node-pill');
    expect(exitPill.textContent).toBe('Active Exit Node');

    // 4. SSH
    const sshToggle = document.getElementById('ts-ssh-toggle');
    expect(sshToggle.checked).toBe(true);
    const sshPill = document.getElementById('ts-ssh-pill');
    expect(sshPill.textContent).toBe('Enabled');

    // 5. Serve & Funnel
    const extGrid = document.getElementById('network-tailscale-extended');
    expect(extGrid.style.display).toBe('grid');
    const serveToggle = document.getElementById('ts-serve-toggle');
    expect(serveToggle.checked).toBe(true);
    const serveUrlLink = document.getElementById('ts-serve-url-link');
    expect(serveUrlLink.href).toBe('https://ark.ts.net/');

    // 6. Taildrop
    const taildropBadge = document.getElementById('ts-taildrop-badge');
    expect(taildropBadge.textContent).toBe('1 file(s)');
    const taildropList = document.getElementById('ts-taildrop-list');
    expect(taildropList.innerHTML).toContain('test-backup.tar.gz');

    // Test Action: Save subnets
    subnetInput.value = '192.168.1.0/24';
    const saveRoutesBtn = document.getElementById('btn-ts-save-routes');
    await saveRoutesBtn.click();
    expect(postSpy).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/set-routes', {
      routes: '192.168.1.0/24',
      enabled: true,
    });

    // Test Action: Exit Node toggle
    exitToggle.checked = false;
    exitToggle.dispatchEvent(new Event('change'));
    expect(postSpy).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/set-exit-node', {
      enabled: false,
    });

    // Test Action: SSH toggle
    sshToggle.checked = false;
    sshToggle.dispatchEvent(new Event('change'));
    expect(postSpy).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/set-ssh', {
      enabled: false,
    });

    // Test Action: Taildrop fetch
    const fetchBtn = document.getElementById('btn-ts-taildrop-fetch');
    await fetchBtn.click();
    expect(postSpy).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/taildrop/receive');
  });

  it('renders interactive peer directory table, filters peers, and handles peer ping latency', async () => {
    const peers = [
      {
        id: 'peer-1',
        hostname: 'macbook-pro',
        os: 'macOS',
        ip: '100.80.20.15',
        online: true,
        direct: true,
        cur_addr: '192.168.1.50:41641',
        connection_type: 'Direct P2P',
      },
      {
        id: 'peer-2',
        hostname: 'windows-workstation',
        os: 'Windows',
        ip: '100.80.20.16',
        online: true,
        direct: false,
        relay: 'fra',
        cur_addr: '',
        connection_type: 'DERP Relay (fra)',
      },
    ];

    renderTailscalePeersTable(peers);

    const tbody = document.getElementById('ts-peers-table-body');
    expect(tbody.innerHTML).toContain('macbook-pro');
    expect(tbody.innerHTML).toContain('windows-workstation');
    expect(tbody.innerHTML).toContain('🍏'); // macOS icon
    expect(tbody.innerHTML).toContain('🪟'); // Windows icon
    expect(tbody.innerHTML).toContain('Direct P2P');
    expect(tbody.innerHTML).toContain('DERP (fra)');

    // Test peer search filter
    renderTailscalePeersTable(peers, 'macbook');
    expect(tbody.innerHTML).toContain('macbook-pro');
    expect(tbody.innerHTML).not.toContain('windows-workstation');

    // Test ping peer
    vi.spyOn(api, 'get').mockResolvedValue({
      tailscale: { installed: true, active: true, peers },
      wireguard: { installed: true, active: true },
    });
    vi.spyOn(api, 'post').mockResolvedValue({
      status: 'success',
      peer: '100.80.20.15',
      latency: '12.4 ms',
      latency_ms: 12.4,
      is_direct: true,
    });

    await fetchAndRenderWireguard();
    renderTailscalePeersTable(peers);

    const pingBtn = tbody.querySelector('.btn-ping-peer');
    expect(pingBtn).toBeTruthy();
    await pingBtn.click();

    await vi.waitFor(() => {
      const resSpan = document.getElementById('latency-100_80_20_15');
      expect(resSpan.textContent).toContain('12.4 ms');
    });
  });
});

