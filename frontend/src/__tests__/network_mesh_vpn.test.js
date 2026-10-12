import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fetchAndRenderWireguard } from '../components/management.js';
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
      <button id="btn-download-wg-conf"></button>
      <pre id="wg-conf-preview"></pre>
      <button id="btn-refresh-wireguard"></button>

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

  it('triggers 1-click deploy POST and displays browser auth prompt on auth_url response', async () => {
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

    const deployBtn = document.getElementById('btn-deploy-tailscale');
    await deployBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/deploy', {
      auth_key: null,
      hostname: 'zettnas-appliance',
      accept_routes: true,
    });

    expect(document.getElementById('ts-auth-prompt').style.display).toBe('block');
    expect(document.getElementById('ts-auth-link').href).toBe('https://login.tailscale.com/a/oauth123');
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
});
