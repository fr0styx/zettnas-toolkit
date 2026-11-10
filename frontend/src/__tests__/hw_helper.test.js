import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { hwHelperStatus, hwHelperHtml, loadHwHelperCard } = await import('../components/management/hw-helper.js');

const tick = () => new Promise((r) => setTimeout(r, 0));
const BASE = { enabled: false, running: false, answering: false, applies: true, kept_until_update: false, app_without_raw_access: false, error: '' };

describe('the hardware helper card (SEC-24)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="mgmt-pane-hardware-fans"><div class="mgmt-card-intro"></div></div>';
  });

  it('says how it stands', () => {
    expect(hwHelperStatus({ ...BASE, error: 'Docker didn\'t answer' })).toContain('Docker');
    expect(hwHelperStatus({ ...BASE, applies: false })).toContain('no fan or button registers');
    expect(hwHelperStatus({ ...BASE, kept_until_update: true })).toContain('until the next update');
    expect(hwHelperStatus(BASE)).toContain('Kiboto reaches');
    expect(hwHelperStatus({ ...BASE, enabled: true })).toContain('Starting');
    expect(hwHelperStatus({ ...BASE, enabled: true, running: true })).toContain('doesn\'t answer');
    expect(hwHelperStatus({ ...BASE, enabled: true, running: true, answering: true })).toContain('next update takes');
    expect(hwHelperStatus({ ...BASE, enabled: true, running: true, answering: true, app_without_raw_access: true })).toContain('no longer can');
    expect(hwHelperHtml({ ...BASE, applies: false })).toContain('disabled');
  });

  it('turns on and off, and shows errors but not the confirmation step', async () => {
    api.get.mockResolvedValue(BASE);
    await loadHwHelperCard();
    const card = document.getElementById('hwh-card');
    expect(document.querySelector('.mgmt-card-intro').nextElementSibling).toBe(card);
    api.put.mockResolvedValueOnce({ ...BASE, enabled: true, running: true, answering: true });
    card.querySelector('#hwh-toggle').click();
    await tick();
    expect(api.put).toHaveBeenCalledWith('/api/hardware/helper', { enabled: true });
    expect(card.querySelector('#hwh-toggle').getAttribute('aria-pressed')).toBe('true');
    api.put.mockRejectedValueOnce(Object.assign(new Error('confirm'), { status: 428 }));
    card.querySelector('#hwh-toggle').click();
    await tick();
    expect(toast.showToast).not.toHaveBeenCalled();
    api.put.mockRejectedValueOnce(new Error('could not be started'));
    card.querySelector('#hwh-toggle').click();
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('could not be started', 'error');
    api.get.mockRejectedValueOnce(new Error('offline'));
    await loadHwHelperCard();
    expect(card.textContent).toBe('offline');
  });

  it('does nothing outside the Fans pane', async () => {
    document.body.innerHTML = '';
    await loadHwHelperCard();
    expect(api.get).not.toHaveBeenCalled();
  });
});
