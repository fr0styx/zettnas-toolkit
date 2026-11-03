/** UX-35: network panel labels keep their icon in the markup, out of the translated words. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fetchAndRenderWireguard, fetchAndRenderReplication } from '../components/management/network.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

const byId = (id) => document.getElementById(id);
const icon = (el) => el.querySelector('span[aria-hidden="true"]')?.textContent;
const mesh = (tailscale) =>
  vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/network/mesh-vpn' ? { tailscale, wireguard: {} } : {}));

describe('network panel icons (UX-35)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    document.body.innerHTML = `
      <span id="ts-key-expiry-display"></span><button id="btn-ts-reauth"></button>
      <table><tbody id="ts-peers-table-body"></tbody></table>`;
  });
  afterEach(() => vi.restoreAllMocks());

  it('an expired node key', async () => {
    mesh({ installed: true, active: true, key_expiry_days: 0 });
    await fetchAndRenderWireguard();
    expect(byId('ts-key-expiry-display').textContent).toBe('❌ Key Expired');
    expect(icon(byId('ts-key-expiry-display'))).toBe('❌');
  });

  it('Re-auth comes back with its icon', async () => {
    mesh({ installed: true, active: true, key_expiry_days: 3 });
    vi.spyOn(api, 'post').mockResolvedValue({});
    await fetchAndRenderWireguard();
    byId('btn-ts-reauth').click();
    await vi.waitFor(() => expect(byId('btn-ts-reauth').disabled).toBe(false));
    expect(byId('btn-ts-reauth').textContent).toBe('⚡ Re-auth');
    expect(icon(byId('btn-ts-reauth'))).toBe('⚡');
  });

  it('a failed and an unreachable ping', async () => {
    mesh({ installed: true, active: true });
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'error' });
    await fetchAndRenderWireguard();
    byId('ts-peers-table-body').innerHTML =
      '<tr><td><button class="btn-ping-peer" data-peer-ip="100.1.1.1"></button><span id="latency-100_1_1_1"></span></td></tr>';
    const btn = document.querySelector('.btn-ping-peer');
    btn.click();
    await vi.waitFor(() => expect(byId('latency-100_1_1_1').textContent).toBe('❌ Failed'));
    await vi.waitFor(() => expect(btn.disabled).toBe(false));
    post.mockRejectedValueOnce(new Error('down'));
    btn.click();
    await vi.waitFor(() => expect(byId('latency-100_1_1_1').textContent).toBe('❌ Error'));
    expect(icon(byId('latency-100_1_1_1'))).toBe('❌');
  });

  it('a replication job: Running..., then Run again', async () => {
    document.body.innerHTML = "<table><tbody id='replication-jobs-tbody'></tbody></table><table><tbody id='replication-history-tbody'></tbody></table>";
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.endsWith('/jobs') ? { jobs: [{ id: 'j1', source: '/mnt/user/a', target: 'backup', schedule: 'daily' }] } : { history: [] },
    );
    let release;
    vi.spyOn(api, 'post').mockImplementation(() => new Promise((r) => { release = r; }));
    await fetchAndRenderReplication();
    const btn = document.querySelector('.btn-run-repl');
    btn.click();
    await vi.waitFor(() => expect(btn.textContent).toBe('⏳ Running...'));
    release({});
    await vi.waitFor(() => expect(btn.textContent).toBe('▶ Run'));
    expect(icon(btn)).toBe('▶');
  });
});
