import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn() } }));
const { api } = await import('../api.js');
const ov = await import('../components/management/overview.js');
const { ROUTES } = await import('../router.js');

const SIDEBAR = `
  <div id="management-hub-view"><div class="mgmt-app-card" data-mgmt-target="mgmt-sec-vms"></div><div class="mgmt-app-card" data-mgmt-target="mgmt-sec-storage"></div></div>
  <nav class="mgmt-sidebar-nav">
    <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-storage"></button>
    <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-vms"></button>
    <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-network"></button>
  </nav>`;

describe('Overview and Advanced (UX-1, UX-2)', () => {
  beforeEach(() => {
    document.body.innerHTML = SIDEBAR;
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('keeps every place for existing setups; switched off it hides advanced cards, never a sidebar page', () => {
    ov.installAdvancedSwitch();
    const sw = document.getElementById('mgmt-advanced-switch');
    expect(sw.checked).toBe(true);
    expect(document.querySelector('[data-mgmt-target="mgmt-sec-vms"].mgmt-sidebar-item').hidden).toBe(false);
    sw.checked = false;
    sw.dispatchEvent(new Event('change'));
    expect(localStorage.getItem('kiboto_advanced')).toBe('0');
    // X1 (SET-18): the sidebar's Advanced group stays; the switch hides tools and Overview cards, not pages
    expect(document.querySelector('.mgmt-sidebar-item[data-mgmt-target="mgmt-sec-vms"]').hidden).toBe(false);
    expect(document.querySelector('.mgmt-sidebar-item[data-mgmt-target="mgmt-sec-network"]').hidden).toBe(false);
    expect(document.querySelector('.mgmt-app-card[data-mgmt-target="mgmt-sec-vms"]').hidden).toBe(true);
    expect(document.querySelector('.mgmt-sidebar-item[data-mgmt-target="mgmt-sec-storage"]').hidden).toBe(false);
    ov.installAdvancedSwitch(); // a second call only re-applies
    expect(document.querySelectorAll('#mgmt-advanced-switch').length).toBe(1);
    expect(ov.advancedOn()).toBe(false);
  });

  it('says everything is fine, or lists what needs attention with a way to it', async () => {
    api.get.mockResolvedValueOnce({ ok: true, items: [] });
    await ov.renderStatusSummary();
    expect(document.getElementById('mgmt-status-summary').textContent).toContain('Everything is fine');
    api.get.mockResolvedValueOnce({ ok: false, items: [
      { id: 'drive:sdb', level: 'critical', kind: 'drive_failing', subject: 'sdb', open: 'storage' },
      { id: 'x', level: 'warning', kind: 'something_new', subject: '', open: 'nowhere' },
    ] });
    await ov.renderStatusSummary();
    const box = document.getElementById('mgmt-status-summary');
    expect(box.textContent).toContain('Drive sdb is failing');
    expect(box.querySelectorAll('.ov-crit').length).toBe(1);
    const spy = vi.spyOn(ROUTES, 'storage').mockImplementation(() => {});
    box.querySelector('[data-ov-open="storage"]').click();
    expect(spy).toHaveBeenCalled();
    expect(box.querySelector('[data-ov-open="nowhere"]')).toBeNull();
  });

  it('says that the status is not known when it cannot be read, and offers to try again (SET-12)', async () => {
    api.get.mockRejectedValueOnce(new Error('Change your password first.'));
    expect(await ov.renderStatusSummary()).toBeNull();
    const box = document.getElementById('mgmt-status-summary');
    expect(box.hidden).toBe(false); // no box read as "nothing wrong"
    expect(box.textContent).toContain('Kiboto could not check how things are');
    expect(box.textContent).toContain('Change your password first.');
    expect(box.textContent).not.toContain('Everything is fine');
    api.get.mockResolvedValue({ ok: true, items: [] });
    box.querySelector('[data-ov-retry]').click();
    await vi.waitFor(() => expect(box.textContent).toContain('Everything is fine'));
    document.body.innerHTML = '';
    expect(await ov.renderStatusSummary()).toBeNull();
  });
});
