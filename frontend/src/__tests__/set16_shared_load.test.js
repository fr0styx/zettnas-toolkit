/** Network report C4: opening the Network page read the same things twice. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showActionToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const net = await import('../components/management/network.js');

describe('one load at a time', () => {
  afterEach(() => vi.restoreAllMocks());

  it('a second call while one runs shares it; the next call loads again', async () => {
    let calls = 0;
    let release;
    const load = net.sharedLoad(() => {
      calls += 1;
      return new Promise((r) => (release = r));
    });
    const a = load();
    const b = load();
    expect(a).toBe(b);
    release('done');
    expect(await a).toBe('done');
    expect(calls).toBe(1);
    load();
    expect(calls).toBe(2);
    release();
  });

  it('a failed load is not kept', async () => {
    let n = 0;
    const load = net.sharedLoad(async () => {
      n += 1;
      throw new Error('x');
    });
    await expect(load()).rejects.toThrow('x');
    await expect(load()).rejects.toThrow('x');
    expect(n).toBe(2);
  });

  it('the section and its tab opening together read the layout once', async () => {
    document.body.innerHTML = '<table><tbody id="network-physical-tbody"></tbody></table>';
    const get = vi.spyOn(api, 'get').mockResolvedValue({ status: 'ok', summary: {}, physical_interfaces: [], bonds: [], bridges: [], docker_networks: [] });
    await Promise.all([net.fetchAndRenderNetworkTopology(), net.fetchAndRenderNetworkTopology()]);
    expect(get.mock.calls.filter(([url]) => url === '/api/system/network-topology')).toHaveLength(1);
    expect(get.mock.calls.some(([url]) => url === '/api/network/mesh-vpn')).toBe(false);
    document.body.innerHTML = '';
  });
});
