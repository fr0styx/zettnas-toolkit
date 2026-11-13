/** Network report F1: a failed layout read is said on every part of the Network page. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showActionToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const net = await import('../components/management/network.js');

const PAGE = `
  <div id="net-home">Loading…</div><ul id="net-port-rows"><li>Loading…</li></ul><div id="network-bridges-container">Loading…</div>
  <div id="network-docker-container">Loading…</div>`;

describe('Network page when the layout cannot be read', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('says so everywhere, and Try again reads it again', async () => {
    document.body.innerHTML = PAGE;
    const get = vi.spyOn(api, 'get').mockRejectedValue(new Error('timed out'));
    await net.fetchAndRenderNetworkTopology();
    expect(document.getElementById('net-home').textContent).toBe('Could not load the network layout: timed out');
    expect(document.querySelector('#net-port-rows > li > .state-block.is-failed')).not.toBeNull(); // a list holds only items
    for (const id of ['net-port-rows', 'network-bridges-container', 'network-docker-container']) {
      expect(document.querySelector(`#${id} .state-block.is-failed`)).not.toBeNull();
    }
    expect(document.body.textContent).not.toContain('Loading…');
    get.mockClear();
    /** @type {HTMLElement} */ (document.querySelector('#network-docker-container [data-try-again]')).click();
    expect(get).toHaveBeenCalledWith('/api/system/network-topology');
  });

  it('an answer that is not ok is a failure too', async () => {
    document.body.innerHTML = PAGE;
    vi.spyOn(api, 'get').mockResolvedValue({ status: 'error', message: 'no access' });
    await net.fetchAndRenderNetworkTopology();
    expect(document.getElementById('net-home').textContent).toContain('no access');
    vi.spyOn(api, 'get').mockResolvedValue(null);
    await net.fetchAndRenderNetworkTopology();
    expect(document.getElementById('net-home').textContent).toContain('Unknown error');
    document.body.innerHTML = '';
    expect(() => net.showTopologyFailed('x')).not.toThrow();
  });
});
