import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { renderMyAlerts } = await import('../components/my-alerts.js');

const SERVED = '/api/notifications/notifications/me';
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('"My alerts" loads and saves (SET-00)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="mount"></div>';
  });

  it('asks the address the server serves and draws the form', async () => {
    api.get.mockResolvedValue({ route: { ntfy_topic: 'dad-phone', email: '', events: ['ups'], min_level: 'warning' }, events: ['ups', 'backup'] });
    const mount = document.getElementById('mount');
    await renderMyAlerts(mount);
    expect(api.get).toHaveBeenCalledWith(SERVED);
    expect(mount.hidden).toBe(false);
    expect(mount.querySelector('input[name=ntfy_topic]').value).toBe('dad-phone');
  });

  it('saves to the same address', async () => {
    api.get.mockResolvedValue({ route: { ntfy_topic: '', email: '', events: [], min_level: 'warning' }, events: ['ups'] });
    api.put.mockResolvedValue({ route: {} });
    const mount = document.getElementById('mount');
    await renderMyAlerts(mount);
    mount.querySelector('input[value=ups]').checked = true;
    mount.querySelector('[data-my-alerts]').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await flush();
    expect(api.put).toHaveBeenCalledWith(SERVED, expect.objectContaining({ events: ['ups'] }));
    expect(showToast).toHaveBeenCalledWith(expect.any(String), 'success');
  });

  it('hides the card when the answer does not come', async () => {
    api.get.mockRejectedValue(new Error('no'));
    const mount = document.getElementById('mount');
    await renderMyAlerts(mount);
    expect(mount.hidden).toBe(true);
  });
});
