// SET-12: the person's rights and the Advanced switch no longer undo each other; the Overview's
// cards follow the rights; a heading with nothing under it goes.
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { ADVANCED_OFF, NO_ACCESS, mark, tidyHeadings } = await import('../hide-marks.js');
const { CARD_ROUTES, hideUnusable, routeOf } = await import('../route-access.js');
const ov = await import('../components/management/overview.js');

const PAGE = `
  <nav class="mgmt-sidebar-nav">
    <button class="mgmt-sidebar-item" data-mgmt-target="management-hub-view" id="e-overview"></button>
    <div class="mgmt-sidebar-category" id="cat-apps">Apps & AI</div>
    <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-docker" data-route="apps"></button>
    <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-vms" data-route="vms"></button>
    <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-ai" data-route="ai"></button>
    <div class="mgmt-sidebar-category" id="cat-system">System</div>
    <button class="mgmt-sidebar-item active" data-mgmt-target="mgmt-sec-network" data-route="network"></button>
    <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-wallpaper"></button>
  </nav>
  <div id="management-hub-view">
    <div class="mgmt-app-card" data-mgmt-target="mgmt-sec-storage"></div>
    <div class="mgmt-app-card" data-mgmt-target="mgmt-sec-docker"></div>
    <div class="mgmt-app-card" data-mgmt-target="mgmt-sec-vms"></div>
    <div class="mgmt-app-card" data-mgmt-target="mgmt-sec-wallpaper"></div>
  </div>`;
const family = { scopes: ['files:read'] };
const owner = { scopes: ['*'] };
const item = (target) => document.querySelector(`.mgmt-sidebar-item[data-mgmt-target="${target}"]`);
const card = (target) => document.querySelector(`.mgmt-app-card[data-mgmt-target="${target}"]`);

describe('rights and the Advanced switch', () => {
  beforeEach(() => {
    document.body.innerHTML = PAGE;
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('switching Advanced on does not show what the person may not open', () => {
    hideUnusable(document, family);
    expect(item('mgmt-sec-vms').hidden).toBe(true);
    ov.applyAdvanced(false);
    ov.applyAdvanced(true); // it wrote hidden = false here, over the rights
    expect(item('mgmt-sec-vms').hidden).toBe(true);
    expect(item('mgmt-sec-network').hidden).toBe(true);
    expect(card('mgmt-sec-vms').hidden).toBe(true);
    hideUnusable(document, owner); // the same browser, another person
    expect(item('mgmt-sec-vms').hidden).toBe(false);
    ov.applyAdvanced(false);
    // X1 (SET-18): Advanced is a sidebar group that is always there; the switch hides no page
    expect(item('mgmt-sec-vms').hidden).toBe(false);
    expect(card('mgmt-sec-vms').hidden).toBe(true); // the Overview's advanced cards still follow it
    expect(item('mgmt-sec-docker').hidden).toBe(false);
  });

  it('the Overview cards follow the rights, and a heading with nothing under it goes', () => {
    hideUnusable(document, family);
    expect(card('mgmt-sec-storage').hidden).toBe(true); // it led to a page the sidebar hides
    expect(card('mgmt-sec-docker').hidden).toBe(true);
    expect(card('mgmt-sec-wallpaper').hidden).toBe(false);
    expect(document.getElementById('cat-apps').hidden).toBe(true); // "Apps & AI" stood over nothing
    expect(document.getElementById('cat-system').hidden).toBe(false);
    hideUnusable(document, owner);
    expect(document.getElementById('cat-apps').hidden).toBe(false);
    expect(routeOf(card('mgmt-sec-storage'))).toBe('storage');
    expect(routeOf(card('mgmt-sec-wallpaper'))).toBe('');
    expect(Object.keys(CARD_ROUTES)).toHaveLength(8);
  });

  it('what other code hid stays hidden', () => {
    const el = document.createElement('div');
    el.hidden = true;
    mark(el, NO_ACCESS, true);
    expect(el.hasAttribute(NO_ACCESS)).toBe(false);
    mark(el, NO_ACCESS, false);
    expect(el.hidden).toBe(true);
    mark(null, NO_ACCESS, true);
    const two = document.createElement('div');
    mark(two, NO_ACCESS, true);
    mark(two, ADVANCED_OFF, true);
    mark(two, ADVANCED_OFF, false);
    expect(two.hidden).toBe(true);
    mark(two, NO_ACCESS, false);
    expect(two.hidden).toBe(false);
    tidyHeadings(document);
  });

  it('switching Advanced off keeps the page that is open (X1), and a failed save is said', async () => {
    const overview = vi.fn();
    document.getElementById('e-overview').addEventListener('click', overview);
    api.put.mockRejectedValueOnce(new Error('offline'));
    await ov.setAdvanced(false);
    expect(overview).not.toHaveBeenCalled(); // X1: the page stays in the sidebar, so nobody is moved off it
    expect(showToast).toHaveBeenCalledWith('That choice could not be saved to your account. It holds in this browser for now.', 'error');
    api.put.mockResolvedValueOnce({});
    vi.clearAllMocks();
    await ov.setAdvanced(true);
    expect(showToast).not.toHaveBeenCalled();
    expect(overview).not.toHaveBeenCalled();
    item('mgmt-sec-network').classList.remove('active');
    expect(ov.leaveAdvancedPage()).toBe(false);
  });
});
