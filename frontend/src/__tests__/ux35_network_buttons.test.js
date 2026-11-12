/** UX-35: network panel labels keep their icon in the markup, out of the translated words. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fetchAndRenderTailscaleDetails, fetchAndRenderReplication } from '../components/management/network.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

const byId = (id) => document.getElementById(id);
const icon = (el) => el.querySelector('span[aria-hidden="true"]')?.textContent;
const mesh = (tailscale) =>
  vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/network/mesh-vpn' ? { tailscale } : {}));

describe('network panel icons (UX-35)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    document.body.innerHTML = `
      <span id="ts-key-expiry-display"></span><button id="btn-ts-reauth"></button>
      <table><tbody id="ts-peers-table-body"></tbody></table>`;
  });
  afterEach(() => vi.restoreAllMocks());

  it('an expired node key says what to do, without an icon in the words', async () => {
    mesh({ installed: true, active: true, key_expiry_days: 0 });
    await fetchAndRenderTailscaleDetails();
    expect(byId('ts-key-expiry-display').textContent).toBe('Expired: sign in again');
    expect(byId('ts-key-expiry-display').dataset.tone).toBe('crit');
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
