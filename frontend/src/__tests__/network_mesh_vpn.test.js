/** SET-16 (D3, D5): the Tailscale details under "Use from anywhere": what stays, in plain words. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchAndRenderTailscaleDetails, homeInternetText, keyExpiryText, renderTailscalePeersTable } from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

const byId = (id) => document.getElementById(id);
const PANE = `
  <div id="ts-details" hidden>
    <span id="ts-connection-pill"></span><code id="ts-ipv4-display"></code><button id="btn-copy-ts-ip"></button>
    <code id="ts-tailnet-display"></code><span id="ts-hostname-display"></span><span id="ts-peers-display"></span>
    <span id="ts-key-expiry-display"></span><button id="btn-ts-reauth"></button>
    <input type="checkbox" id="ts-subnet-router-toggle"><button id="btn-ts-save-routes"></button><input id="ts-subnet-routes-input">
    <input type="checkbox" id="ts-exit-node-toggle"><span id="ts-exit-node-pill"></span><div id="ts-exit-node-approval-hint"></div>
    <input id="ts-peer-search"><span id="ts-peer-count-pill"></span><table><tbody id="ts-peers-table-body"></tbody></table>
    <button id="btn-refresh-wireguard"></button>
  </div>`;
const ACTIVE = {
  installed: true, active: true, ipv4: '100.64.0.1', tailnet: 'cat-dog.ts.net', hostname: 'kiboto', peers_count: 2,
  key_expiry_days: 90, key_expiry: '2027-02-10T00:00:00Z', is_subnet_router: false, advertised_routes: [], detected_subnets: ['192.168.1.0/24'],
  advertise_exit_node: false, exit_node_approved: false, is_exit_node: false,
  peers: [{ hostname: 'phone', ip: '100.64.0.2', online: true, cur_addr: '1.2.3.4:41641' }, { hostname: 'laptop', ip: '100.64.0.3', online: false }],
};
const mesh = (tailscale) => vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/network/mesh-vpn' ? { tailscale } : {}));

describe('Tailscale details (SET-16)', () => {
  beforeEach(() => {
    document.body.innerHTML = PANE;
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it('stays hidden until this NAS is connected', async () => {
    mesh({ installed: true, active: false, backend_state: 'NeedsLogin' });
    await fetchAndRenderTailscaleDetails();
    expect(byId('ts-details').hidden).toBe(true);
    vi.restoreAllMocks();
    vi.spyOn(api, 'get').mockRejectedValue(new Error('down'));
    await fetchAndRenderTailscaleDetails();
    expect(byId('ts-details').hidden).toBe(true);
  });

  it('shows this NAS, the key, the two uses and the devices', async () => {
    mesh(ACTIVE);
    await fetchAndRenderTailscaleDetails();
    expect(byId('ts-details').hidden).toBe(false);
    expect(byId('ts-ipv4-display').textContent).toBe('100.64.0.1');
    expect(byId('ts-peers-display').textContent).toBe('2 devices');
    expect(byId('ts-key-expiry-display').textContent).toBe('Expires in 90 days (2027-02-10)');
    expect(byId('ts-subnet-routes-input').value).toBe('192.168.1.0/24');
    expect(byId('ts-exit-node-pill').textContent).toBe('Off');
    expect(byId('ts-peers-table-body').querySelectorAll('tr')).toHaveLength(2);
    expect(byId('ts-peers-table-body').querySelector('.btn-ping-peer')).toBeNull();
  });

  it('saves "reach other things at home" and "home internet when away"', async () => {
    mesh(ACTIVE);
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'success' });
    await fetchAndRenderTailscaleDetails();
    byId('ts-subnet-router-toggle').checked = true;
    byId('ts-subnet-router-toggle').dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/set-routes', { routes: '192.168.1.0/24', enabled: true }));
    byId('ts-exit-node-toggle').checked = true;
    byId('ts-exit-node-toggle').dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/network/mesh-vpn/tailscale/set-exit-node', { enabled: true }));
    post.mockRejectedValueOnce(new Error('nope'));
    byId('btn-ts-save-routes').click();
    await vi.waitFor(() => expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('nope'), 'error'));
  });

  it('signs in again: opens the sign-in page when one is needed', async () => {
    mesh(ACTIVE);
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ auth_url: 'https://login.tailscale.com/a/x' }).mockResolvedValueOnce({});
    await fetchAndRenderTailscaleDetails();
    byId('btn-ts-reauth').click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledWith('https://login.tailscale.com/a/x', '_blank', 'noopener,noreferrer'));
    byId('btn-ts-reauth').click();
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  });

  it('filters the devices and copies the address', async () => {
    mesh(ACTIVE);
    await fetchAndRenderTailscaleDetails();
    byId('ts-peer-search').value = 'lap';
    byId('ts-peer-search').dispatchEvent(new Event('input'));
    expect(byId('ts-peers-table-body').querySelectorAll('tr')).toHaveLength(1);
    expect(byId('ts-peer-count-pill').textContent).toBe('1 online / 2 total');
    renderTailscalePeersTable([], 'x');
    expect(byId('ts-peers-table-body').textContent).toBe('No devices match the search.');
  });

  it('says the key and home internet in words', () => {
    expect(keyExpiryText({ key_expiry_days: null })).toEqual({ text: 'Never expires', tone: 'ok' });
    expect(keyExpiryText({ key_expiry_days: 5 }).tone).toBe('warn');
    expect(keyExpiryText({ key_expiry_days: 0 })).toEqual({ text: 'Expired: sign in again', tone: 'crit' });
    expect(homeInternetText({ is_exit_node: true })).toBe('In use');
    expect(homeInternetText({ exit_node_approved: true })).toContain('Ready');
    expect(homeInternetText({ advertise_exit_node: true })).toContain('approval');
  });

  it('the markup has no WireGuard, SSH, Serve, Taildrop or Ping left', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const html = readFileSync(resolve(__dirname, '../windows/management-window.html'), 'utf8');
    for (const id of ['wg-conf-preview', 'ts-ssh-toggle', 'ts-serve-toggle', 'ts-taildrop-list', 'mesh-service-filter', 'btn-tailscale-up', 'ts-deploy-banner', 'mw.latency_ping']) {
      expect(html).not.toContain(id);
    }
  });
});
