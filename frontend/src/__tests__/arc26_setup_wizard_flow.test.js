/** ARC-26: the first-run wizard: who may skip it, what it shows, and saving the password. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() }, auth: { setToken: vi.fn(), getToken: vi.fn() }, ApiError: class extends Error {} }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/dock.js', () => ({ bringToFront: vi.fn() }));
vi.mock('../management-dom.js', () => ({ onManagementDom: (fn) => fn() }));
vi.mock('../components/share-access.js', () => ({ grantShares: vi.fn(async () => {}) }));

const byId = (id) => document.getElementById(id);
const DOM = `
  <div id="setup-wizard-modal" class="open">
    <button id="setup-wizard-close"></button>
    <div class="smart-modal-body">
      <div data-setup-step="1"><h3>Welcome</h3>
        <span id="setup-hw-chassis"></span><span id="setup-hw-fb"></span><span id="setup-hw-fans"></span><span id="setup-hw-leds"></span></div>
      <div data-setup-step="2"><h3>Password</h3>
        <input id="setup-current-pwd"><input id="setup-new-pwd"><input id="setup-confirm-pwd"></div>
      <div data-setup-step="3"><h3>Alerts</h3><input id="setup-notif-url"></div>
      <div class="footer"><button id="setup-wizard-skip"></button><button id="setup-wizard-submit"></button></div>
    </div>
  </div>
  <div id="setup-wizard-err" style="display:none"></div>
  <div id="sec-default-pwd-warning"></div>
  <button id="btn-launch-setup-wizard"></button>`;

let W, api, auth, showToast, state;
async function load() {
  vi.resetModules();
  ({ api, auth } = await import('../api.js'));
  ({ showToast } = await import('../toast.js'));
  ({ state } = await import('../state.js'));
  W = await import('../components/setup-wizard.js');
}
const fill = (cur = 'admin', pwd = 'Chosen-Pass-1') => {
  byId('setup-current-pwd').value = cur;
  byId('setup-new-pwd').value = pwd;
  byId('setup-confirm-pwd').value = pwd;
};

describe('first-run wizard', () => {
  beforeEach(async () => {
    document.body.innerHTML = DOM;
    sessionStorage.clear();
    localStorage.clear();
    await load();
    vi.clearAllMocks();
    api.get.mockResolvedValue({});
    api.post.mockResolvedValue({});
    api.put.mockResolvedValue({});
  });
  afterEach(() => vi.useRealTimers());

  it('cannot be skipped while the default password is in use', () => {
    state.stats = { security: { is_default_password: true } };
    W.initSetupWizard();
    byId('setup-wizard-skip').click();
    expect(showToast.mock.calls.at(-1)[1]).toBe('warning');
    expect(byId('setup-wizard-modal').classList.contains('open')).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    expect(showToast).toHaveBeenCalledTimes(2);
    byId('setup-wizard-modal').click();
    expect(byId('setup-wizard-modal').classList.contains('open')).toBe(true);
  });

  it('can be closed otherwise, and remembers that for the session', () => {
    state.stats = { security: { is_default_password: false } };
    W.initSetupWizard();
    byId('setup-wizard-close').click();
    expect(byId('setup-wizard-modal').classList.contains('open')).toBe(false);
    expect(sessionStorage.getItem('zettnas_wizard_dismissed')).toBe('1');
    byId('setup-wizard-modal').classList.add('open');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(byId('setup-wizard-modal').classList.contains('open')).toBe(false);
    byId('btn-launch-setup-wizard').click();
    expect(byId('setup-wizard-modal').classList.contains('open')).toBe(true);
  });

  it('shows the hardware it found', () => {
    W.openSetupWizard({ security: { is_default_password: true }, chassis: 'd4', peripherals: { fb_active: true, led_ready: true, led_port: '/dev/ttyS1' }, fans: [900, 0] });
    expect(byId('setup-wizard-skip').style.display).toBe('none');
    expect(byId('setup-hw-chassis').textContent).toBe('Zettlab D4 (4-Bay)');
    expect(byId('setup-hw-fb').textContent).toBe('Working');
    expect(byId('setup-hw-fans').textContent).toBe('1 of 2 fans running');
    expect(byId('setup-hw-leds').title).toBe('WS2812B (/dev/ttyS1)');

    W.openSetupWizard({ chassis: 'x9', fans: [0, 0], peripherals: {} }, true);
    expect(byId('setup-wizard-skip').style.display).toBe('inline-block');
    expect(byId('setup-hw-chassis').textContent).toBe('X9');
    expect(byId('setup-hw-fans').textContent).toBe('2 fans, all stopped for now');
    expect(byId('setup-hw-leds').textContent).toBe('None found');
    W.openSetupWizard({ model: 'Box', fans: 'n/a' });
    expect(byId('setup-hw-chassis').textContent).toBe('Box');
    expect(byId('setup-hw-fans').textContent).toBe('Fan speeds cannot be read on this machine');
    expect(byId('setup-hw-fb').textContent).toContain('None found');
  });

  it('opens by itself once when the default password is in use', async () => {
    vi.useFakeTimers();
    W.checkAndTriggerSetupWizard({ security: { is_default_password: true } });
    byId('setup-wizard-modal').classList.remove('open');
    await vi.advanceTimersByTimeAsync(700);
    expect(byId('setup-wizard-modal').classList.contains('open')).toBe(true);
    await load();
    sessionStorage.setItem('zettnas_wizard_dismissed', '1');
    byId('setup-wizard-modal').classList.remove('open');
    W.checkAndTriggerSetupWizard({ security: { is_default_password: true } });
    await vi.advanceTimersByTimeAsync(700);
    expect(byId('setup-wizard-modal').classList.contains('open')).toBe(false);
  });

  it('the owner sets the password, signs in again and adds an alert channel', async () => {
    state.stats = { security: { is_default_password: true } };
    state.latestStats = { security: { is_default_password: true } };
    window.openGettingStarted = vi.fn();
    W.initSetupWizard();
    fill();
    byId('setup-notif-url').value = 'ntfy://alerts';
    api.get.mockImplementation(async (url) => (url === '/api/auth/me' ? { id: 'u1', role: 'superadmin', username: 'admin' } : { apprise_urls: ['mailto://a'] }));
    api.post.mockImplementation(async (url) => (url === '/api/auth/login' ? { token: 'NEW' } : {}));
    byId('setup-wizard-submit').click();
    await vi.waitFor(() => expect(window.openGettingStarted).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith('/api/security', { current_password: 'admin', new_password: 'Chosen-Pass-1' });
    expect(api.post).toHaveBeenCalledWith('/api/auth/login', { username: 'admin', password: 'Chosen-Pass-1' });
    expect(auth.setToken).toHaveBeenCalledWith('NEW');
    const cfg = api.post.mock.calls.find((c) => c[0] === '/api/notifications/config')[1];
    expect(cfg).toMatchObject({ enabled: true, apprise_urls: ['mailto://a', 'ntfy://alerts'] });
    expect(state.stats.security.is_default_password).toBe(false);
    expect(localStorage.getItem('zettnas_advanced')).toBe('0');
    expect(byId('sec-default-pwd-warning').style.display).toBe('none');
    expect(byId('setup-wizard-modal').classList.contains('open')).toBe(false);
    delete window.openGettingStarted;
  });

  it('another administrator changes their own password; failures along the way are survivable', async () => {
    W.initSetupWizard();
    fill('old-pass-1', 'Another-Pass-2');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    api.get.mockImplementation(async (url) => (url === '/api/auth/me' ? { id: 'u 2', role: 'storage_admin', username: 'sam' } : Promise.reject(new Error('no config'))));
    api.post.mockImplementation(async (url) => {
      if (url === '/api/auth/login') throw new Error('signed out');
      if (url === '/api/notifications/config') throw new Error('locked');
      return {};
    });
    byId('setup-notif-url').value = 'ntfy://x';
    byId('setup-wizard-submit').click();
    await vi.waitFor(() => expect(showToast.mock.calls.at(-1)?.[1]).toBe('success'));
    expect(api.post).toHaveBeenCalledWith('/api/users/u%202/password', { current_password: 'old-pass-1', new_password: 'Another-Pass-2' });
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('a refused password stays on the password step with the reason', async () => {
    W.initSetupWizard();
    fill('wrong');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    api.get.mockRejectedValue(new Error('no session'));
    api.post.mockRejectedValueOnce(new Error('Current password is wrong'));
    byId('setup-wizard-submit').click();
    await vi.waitFor(() => expect(byId('setup-wizard-err').textContent).toBe('Current password is wrong'));
    expect(byId('setup-wizard-submit').disabled).toBe(false);
    api.post.mockRejectedValueOnce(new Error(''));
    byId('setup-wizard-submit').click();
    await vi.waitFor(() => expect(byId('setup-wizard-err').textContent).toContain('Failed to update password'));
    warn.mockRestore();
  });
});
