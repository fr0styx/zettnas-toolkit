/** Network report F1: a failed layout read is said on every part of the Network page. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showActionToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const net = await import('../components/management/network.js');

const PAGE = `
  <span id="net-kpi-ip">--</span><span id="net-kpi-gw">--</span><span id="net-kpi-speed">--</span>
  <div id="network-switch-faceplate">Loading…</div><div id="network-bridges-container">Loading…</div>
  <div id="network-docker-container">Loading…</div><table><tbody id="network-physical-tbody"></tbody></table>`;

describe('Network page when the layout cannot be read', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('says so everywhere, and Try again reads it again', async () => {
    document.body.innerHTML = PAGE;
    const get = vi.spyOn(api, 'get').mockRejectedValue(new Error('timed out'));
    await net.fetchAndRenderNetworkTopology();
    expect(document.getElementById('network-physical-tbody').textContent).toBe('Could not load the network layout: timed out');
    for (const id of ['network-switch-faceplate', 'network-bridges-container', 'network-docker-container']) {
      expect(document.querySelector(`#${id} .state-block.is-failed`)).not.toBeNull();
    }
    expect(document.getElementById('net-kpi-ip').textContent).toBe('Unknown');
    expect(document.body.textContent).not.toContain('Loading…');
    get.mockClear();
    /** @type {HTMLElement} */ (document.querySelector('#network-docker-container [data-try-again]')).click();
    expect(get).toHaveBeenCalledWith('/api/system/network-topology');
  });

  it('an answer that is not ok is a failure too', async () => {
    document.body.innerHTML = PAGE;
    vi.spyOn(api, 'get').mockResolvedValue({ status: 'error', message: 'no access' });
    await net.fetchAndRenderNetworkTopology();
    expect(document.getElementById('network-physical-tbody').textContent).toContain('no access');
    vi.spyOn(api, 'get').mockResolvedValue(null);
    await net.fetchAndRenderNetworkTopology();
    expect(document.getElementById('network-physical-tbody').textContent).toContain('Unknown error');
    document.body.innerHTML = '';
    expect(() => net.showTopologyFailed('x')).not.toThrow();
  });
});
