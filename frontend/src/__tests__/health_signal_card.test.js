import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
import { api } from '../api.js';
import { installHealthSignal, renderHealthSignal } from '../components/management/health-signal.js';

const STATUS = {
  enabled: false,
  available: true,
  last_sent: 0,
  preview: { schema: 1, id: '(a random id)', version: '1.10.3', platform: '<b>unraid</b>', features: [] },
};

describe('Help improve ZettNAS card', () => {
  beforeEach(() => {
    document.body.innerHTML =
      '<div class="drawer-card"><div id="update-status-box"></div></div><div id="after"></div>';
    vi.clearAllMocks();
  });

  it('shows the exact report, escaped, and starts off', () => {
    const card = document.createElement('div');
    renderHealthSignal(card, STATUS);
    const sw = card.querySelector('#health-signal-switch');
    expect(sw.checked).toBe(false);
    expect(sw.disabled).toBe(false);
    expect(card.querySelector('.hs-preview').textContent).toContain('"<b>unraid</b>"');
    expect(card.querySelector('.hs-preview b')).toBeNull();
  });

  it('is disabled when no receiver is configured', () => {
    const card = document.createElement('div');
    renderHealthSignal(card, { ...STATUS, available: false });
    expect(card.querySelector('#health-signal-switch').disabled).toBe(true);
  });

  it('turns on through the API and lands under Software Updates', async () => {
    api.get.mockResolvedValue(STATUS);
    api.put.mockResolvedValue({ ...STATUS, enabled: true, last_sent: 0 });
    await installHealthSignal();
    const card = document.getElementById('health-signal-card');
    expect(card.previousElementSibling.classList.contains('drawer-card')).toBe(true);
    const sw = card.querySelector('#health-signal-switch');
    sw.checked = true;
    sw.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/system/health-signal', { enabled: true }));
    await vi.waitFor(() => expect(card.querySelector('#health-signal-switch').checked).toBe(true));
    await installHealthSignal(); // only once
    expect(document.querySelectorAll('#health-signal-card').length).toBe(1);
  });
});
