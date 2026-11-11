// SET-14: the alert settings save themselves when a field changes.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/my-alerts.js', () => ({ renderMyAlerts: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const n = await import('../components/management/notifications.js');

describe('alert settings are saved at once', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    document.body.innerHTML = `
      <input type="checkbox" id="notif-master-enabled">
      <input type="checkbox" id="notif-toggle-smart" checked>
      <input type="number" id="notif-input-cooldown" value="30">`;
    api.post.mockImplementation((_url, cfg) => Promise.resolve({ config: cfg }));
  });
  afterEach(() => vi.useRealTimers());

  it('a changed switch is saved without "Save Settings", once typing has paused', async () => {
    n.installSaveAtOnce(document, 300);
    n.installSaveAtOnce(document, 300); // twice wires each field once
    const master = document.getElementById('notif-master-enabled');
    master.checked = true;
    master.dispatchEvent(new Event('change'));
    const cooldown = document.getElementById('notif-input-cooldown');
    cooldown.value = '45';
    cooldown.dispatchEvent(new Event('change'));
    expect(api.post).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(350);
    expect(api.post).toHaveBeenCalledTimes(1);
    const [, cfg] = api.post.mock.calls[0];
    expect(cfg).toMatchObject({ enabled: true, notify_on_smart: true, cooldown_seconds: 2700 });
    expect(cfg.notify_on_container).toBeUndefined(); // the box no code sends
    expect(showToast).toHaveBeenCalledWith('Saved.', 'success');
  });

  it('a save that fails is said', async () => {
    api.post.mockRejectedValueOnce(new Error('offline'));
    await n.saveNotificationsConfig({ quiet: true });
    expect(showToast).toHaveBeenCalledWith('offline', 'error');
    expect(n.SAVED_AT_ONCE).toContain('notif-master-enabled');
  });
});
