/** SET-24 l: old links into Network's tabs land on the right page and section. */
import { describe, it, expect, vi, beforeAll } from 'vitest';
import { initManagement } from '../components/management.js';
import { api } from '../api.js';

const shown = (id) => /** @type {HTMLElement} */ (document.getElementById(id)).style.display;

describe('links into the old Network tabs (SET-24 l)', () => {
  /** @type {import('vitest').MockInstance} */
  let get;
  beforeAll(() => {
    get = vi.spyOn(api, 'get').mockResolvedValue({});
    vi.spyOn(api, 'post').mockResolvedValue({});
    Element.prototype.scrollIntoView = vi.fn();
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"><span id="management-header-title-text"></span></div>
        <div class="mgmt-content-pane">
          <div id="mgmt-sec-network" class="mgmt-detail-card">
            <div id="mgmt-pane-network" class="mgmt-tab-pane">
              <section id="mgmt-pane-network-services"></section>
              <section id="mgmt-pane-network-ports"><table><tbody id="net-listening-ports-tbody"></tbody></table></section>
            </div>
          </div>
          <div id="mgmt-sec-away" class="mgmt-detail-card">
            <div id="mgmt-pane-network-wireguard" class="mgmt-tab-pane"><div id="remote-access-mount"></div></div>
          </div>
        </div></div></div>`;
    try { initManagement(); } catch (_) { /* parts of the window this test doesn't build */ }
  });

  it('a link to What answers opens Network and scrolls to that section, loading the page', async () => {
    get.mockClear();
    window.openManagementWindow('mgmt-sec-network', 'mgmt-pane-network-ports');
    expect(shown('mgmt-sec-network')).toBe('block');
    expect(shown('mgmt-pane-network')).toBe('block');
    expect(shown('mgmt-sec-away')).toBe('none');
    expect(document.getElementById('mgmt-pane-network-ports')?.scrollIntoView).toHaveBeenCalled();
    await vi.waitFor(() => expect(get).toHaveBeenCalledWith('/api/network/ports/listening'));
    expect(document.getElementById('management-header-title-text')?.textContent).not.toBe('Away from home');
  });

  it('a link to the old Remote access tab opens Away from home, with its title', () => {
    window.openManagementWindow('mgmt-sec-network', 'mgmt-pane-network-wireguard');
    expect(shown('mgmt-sec-away')).toBe('block');
    expect(shown('mgmt-sec-network')).toBe('none');
    expect(shown('mgmt-pane-network-wireguard')).toBe('block');
    expect(document.getElementById('management-header-title-text')?.textContent).toBe('Away from home');
  });
});
