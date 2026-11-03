/** ARC-26: sign-in (auth.js): the people chooser, password and two-step sign-in, lock screen, logout. */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';

const me = { current: { id: 'u1', username: 'alice' } };
vi.mock('../api.js', () => ({ auth: { setToken: vi.fn(), clearToken: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/session.js', () => ({
  fetchCurrentProfile: vi.fn(async () => {}),
  getCurrentUser: () => me.current,
  setCurrentUser: vi.fn(),
}));
vi.mock('../components/setup-wizard-gate.js', () => ({ openSetupWizard: vi.fn() }));
vi.mock('../components/sso.js', () => ({ initSsoLogin: vi.fn() }));

const { auth } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { setCurrentUser } = await import('../components/session.js');
const { openSetupWizard } = await import('../components/setup-wizard-gate.js');
const { ZettEventBus } = await import('../event-bus.js');
const A = await import('../components/auth.js');

const byId = (id) => document.getElementById(id);
const res = (data, status = 200, headers = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
  headers: { get: (k) => headers[k] ?? null },
});
const shown = (id) => byId(id).style.display;

const DOM = `
  <div id="login-overlay" style="display:none">
    <form id="login-step-credentials">
      <div id="login-users-chooser"></div>
      <div id="login-user-selected-card" tabindex="0"><span id="login-selected-initial"></span><span id="login-selected-name"></span>
        <button id="login-change-user-btn" type="button"></button></div>
      <div id="login-manual-fields"><input id="login-username"></div>
      <input id="login-password" type="password"><input id="login-remember-me" type="checkbox" checked>
      <p id="login-error" hidden></p>
      <button id="login-btn" type="button">Sign in</button>
      <a id="login-toggle-manual" href="#"></a><a id="login-toggle-chooser" href="#"></a>
    </form>
    <div id="login-step-mfa" style="display:none"><span id="mfa-user-target"></span>
      <form id="form-mfa-challenge"><input id="mfa-challenge-code"><button id="btn-submit-mfa">Verify</button></form>
      <a id="mfa-toggle-recovery" href="#"></a><a id="mfa-back-btn" href="#"></a></div>
  </div>
  <div id="os-dock-container"></div>
  <div id="lock-overlay" style="display:none"><span id="lock-clock"></span><span id="lock-date"></span>
    <input id="lock-password"><p id="lock-error"></p><button id="lock-unlock-btn"></button><button id="lock-switch-btn"></button>
    <select id="lock-timeout-select"><option value="14400000">4h</option><option value="1000">1s</option><option value="0">never</option></select></div>`;

let fetchMock;
const PEOPLE = [{ username: 'alice', display_name: 'Alice' }, { username: 'bob' }];

describe('sign-in and lock screen (auth.js)', () => {
  beforeAll(() => {
    document.body.innerHTML = DOM;
    fetchMock = vi.fn(async () => res(PEOPLE));
    window.fetch = fetchMock;
    A.initAuth();
  });
  beforeEach(async () => {
    vi.clearAllMocks();
    fetchMock.mockImplementation(async () => res(PEOPLE));
    await A.logout(); // a known state: signed out, not locked, chooser shown
    vi.clearAllMocks();
  });
  afterEach(() => vi.useRealTimers());

  it('tells recovery codes from authenticator codes', () => {
    expect(A.isRecoveryCode({ dataset: {} }, '123 456')).toBe(false);
    expect(A.isRecoveryCode({ dataset: {} }, 'abcd-1234')).toBe(true);
    expect(A.isRecoveryCode({ dataset: { mode: 'recovery' } }, '123456')).toBe(true);
  });

  it('offers each person, or one person straight away', async () => {
    await A.renderLoginChooser();
    expect(byId('login-users-chooser').querySelectorAll('.login-user-card')).toHaveLength(2);
    expect(shown('login-users-chooser')).toBe('flex');
    const card = byId('login-users-chooser').querySelector('[data-username="bob"]');
    card.dispatchEvent(new Event('mouseenter'));
    card.dispatchEvent(new Event('mouseleave'));
    card.click();
    expect(byId('login-selected-name').textContent).toBe('bob');
    expect(byId('login-selected-initial').textContent).toBe('B');
    expect(byId('login-username').value).toBe('bob');

    fetchMock.mockResolvedValueOnce(res([PEOPLE[0]]));
    await A.renderLoginChooser();
    expect(byId('login-selected-name').textContent).toBe('Alice');
    fetchMock.mockResolvedValueOnce(res([PEOPLE[0]]));
    await A.renderLoginChooser({ forceChooser: true });
    expect(shown('login-manual-fields')).toBe('block');
    fetchMock.mockResolvedValueOnce(res([]));
    await A.renderLoginChooser();
    expect(byId('login-username').value).toBe('admin');
    fetchMock.mockResolvedValueOnce(res({}, 500));
    await A.renderLoginChooser();
    expect(shown('login-manual-fields')).toBe('block');
  });

  it('switches between the chooser, the chosen person and typing a name', async () => {
    await A.renderLoginChooser();
    byId('login-users-chooser').querySelector('.login-user-card').click();
    const sel = byId('login-user-selected-card');
    sel.dispatchEvent(new Event('mouseenter'));
    sel.dispatchEvent(new Event('mouseleave'));
    sel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(shown('login-users-chooser')).toBe('flex');
    byId('login-users-chooser').querySelector('.login-user-card').click();
    byId('login-change-user-btn').click();
    expect(shown('login-users-chooser')).toBe('flex');
    byId('login-toggle-manual').click();
    expect(shown('login-manual-fields')).toBe('block');
    byId('login-toggle-chooser').click();
    expect(shown('login-users-chooser')).toBe('flex');

    byId('login-users-chooser').innerHTML = '<div class="login-user-card"></div>';
    sel.click();
    expect(shown('login-manual-fields')).toBe('block');
    byId('login-username').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(document.activeElement).toBe(byId('login-password'));
  });

  it('signs in and asks for a new password when the default one was used', async () => {
    vi.useFakeTimers();
    byId('login-toggle-manual').click();
    byId('login-username').value = ' carol ';
    byId('login-password').value = 'pw';
    fetchMock.mockResolvedValueOnce(res({ status: 'ok', token: 'T', user: { id: 'u3' }, must_change_password: true }));
    byId('login-btn').click();
    await vi.advanceTimersByTimeAsync(400);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ username: 'carol', password: 'pw', remember_me: true });
    expect(auth.setToken).toHaveBeenCalledWith('T');
    expect(setCurrentUser).toHaveBeenCalledWith({ id: 'u3' });
    expect(shown('login-overlay')).toBe('none');
    expect(document.documentElement.classList.contains('has-auth-session')).toBe(true);
    expect(openSetupWizard).toHaveBeenCalled();
    expect(byId('login-password').value).toBe('');
  });

  it('says why a sign-in failed', async () => {
    byId('login-password').value = 'bad';
    fetchMock.mockResolvedValueOnce(res({}, 401));
    byId('login-password').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await vi.waitFor(() => expect(byId('login-error').textContent).toBe('Wrong username or password.'));
    expect(byId('login-error').hidden).toBe(false);
    fetchMock.mockResolvedValueOnce(res({}, 429, { 'Retry-After': '30' }));
    byId('login-btn').click();
    await vi.waitFor(() => expect(byId('login-error').textContent).toBe('Too many attempts. Try again in 30 s.'));
    fetchMock.mockResolvedValueOnce(res({ detail: 'Account turned off' }, 403));
    byId('login-btn').click();
    await vi.waitFor(() => expect(byId('login-error').textContent).toBe('Account turned off'));
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    byId('login-btn').click();
    await vi.waitFor(() => expect(byId('login-error').textContent).toContain("Couldn't reach ZettNAS"));
  });

  it('asks for the second step, with a code or a recovery code', async () => {
    byId('login-password').value = 'pw';
    fetchMock.mockResolvedValueOnce(res({ status: 'mfa_required', mfa_token: 'M' }));
    byId('login-btn').click();
    await vi.waitFor(() => expect(shown('login-step-mfa')).toBe('block'));
    expect(byId('mfa-user-target').textContent).toContain('@');

    const form = byId('form-mfa-challenge');
    const code = byId('mfa-challenge-code');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(fetchMock).toHaveBeenCalledTimes(1); // nothing typed: nothing sent

    code.value = '123456';
    fetchMock.mockResolvedValueOnce(res({ detail: 'Invalid code' }, 401));
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('2FA Verification Failed: Invalid code', 'error'));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ mfa_token: 'M', code: '123456' });

    byId('mfa-toggle-recovery').click();
    expect(code.dataset.mode).toBe('recovery');
    expect(code.maxLength).toBe(10);
    byId('mfa-toggle-recovery').click();
    expect(code.dataset.mode).toBe('totp');
    byId('mfa-toggle-recovery').click();

    code.value = 'abcd-efgh';
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Verification error: offline', 'error'));

    code.value = 'abcd-efgh';
    fetchMock.mockResolvedValueOnce(res({ status: 'ok', token: 'T2', user: { id: 'u1' } }));
    const loggedIn = vi.fn();
    ZettEventBus.on('auth:login', loggedIn);
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(loggedIn).toHaveBeenCalled());
    expect(JSON.parse(fetchMock.mock.calls.at(-1)[1].body)).toEqual({ mfa_token: 'M', recovery_code: 'abcd-efgh' });
    expect(auth.setToken).toHaveBeenCalledWith('T2');
  });

  it('goes back from the second step to the password', async () => {
    fetchMock.mockResolvedValueOnce(res({ status: 'mfa_required', mfa_token: 'M' }));
    byId('login-password').value = 'pw';
    byId('login-btn').click();
    await vi.waitFor(() => expect(shown('login-step-mfa')).toBe('block'));
    byId('mfa-back-btn').click();
    expect(shown('login-step-credentials')).toBe('block');
    expect(shown('login-step-mfa')).toBe('none');
  });

  it('locks, refuses a wrong password, and unlocks', async () => {
    const locked = vi.fn();
    ZettEventBus.on('auth:locked', locked);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'L', ctrlKey: true, altKey: true }));
    expect(A.isDesktopLocked()).toBe(true);
    expect(shown('lock-overlay')).toBe('flex');
    expect(sessionStorage.getItem('zettnas_desktop_locked')).toBe('true');
    expect(byId('lock-clock').textContent).not.toBe('');
    expect(locked).toHaveBeenCalled();

    await A.unlockDesktop(); // no password: nothing happens
    expect(fetchMock).not.toHaveBeenCalled();
    byId('lock-password').value = 'bad';
    fetchMock.mockResolvedValueOnce(res({}, 401));
    byId('lock-unlock-btn').click();
    await vi.waitFor(() => expect(byId('lock-error').textContent).toBe('Incorrect password'));
    fetchMock.mockRejectedValueOnce(new Error('x'));
    byId('lock-password').value = 'pw';
    await A.unlockDesktop();
    expect(byId('lock-error').textContent).toBe('Connection error');

    byId('lock-password').value = 'pw';
    fetchMock.mockResolvedValueOnce(res({ status: 'ok', token: 'T3' }));
    byId('lock-password').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await vi.waitFor(() => expect(A.isDesktopLocked()).toBe(false));
    expect(JSON.parse(fetchMock.mock.calls.at(-1)[1].body)).toMatchObject({ username: 'alice', password: 'pw' });
    expect(sessionStorage.getItem('zettnas_desktop_locked')).toBeNull();
  });

  it('unlocking with two-step sign-in finishes on the second step', async () => {
    A.lockDesktop();
    byId('lock-password').value = 'pw';
    fetchMock.mockResolvedValueOnce(res({ status: 'mfa_required', mfa_token: 'L' }));
    await A.unlockDesktop();
    expect(shown('lock-overlay')).toBe('none');
    expect(shown('login-overlay')).toBe('flex');
    expect(shown('login-step-mfa')).toBe('block');
    byId('mfa-challenge-code').value = '654321';
    fetchMock.mockResolvedValueOnce(res({ status: 'ok' }));
    const unlocked = vi.fn();
    ZettEventBus.on('auth:unlocked', unlocked);
    byId('form-mfa-challenge').dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(unlocked).toHaveBeenCalled());
    expect(A.isDesktopLocked()).toBe(false);
  });

  it('switch user from the lock screen shows the chooser', async () => {
    A.lockDesktop();
    byId('lock-switch-btn').click();
    expect(A.isDesktopLocked()).toBe(false);
    expect(shown('login-overlay')).toBe('flex');
    expect(document.documentElement.classList.contains('auth-required')).toBe(true);
    await vi.waitFor(() => expect(shown('login-users-chooser')).toBe('flex'));
  });

  it('remembers the auto-lock time and locks after it', async () => {
    const sel = byId('lock-timeout-select');
    sel.value = '1000';
    sel.dispatchEvent(new Event('change'));
    expect(localStorage.getItem('zettnas_auto_lock_timeout_ms')).toBe('1000');
    expect(fetchMock).toHaveBeenCalledWith('/api/system/client-preferences', expect.objectContaining({ method: 'POST' }));

    vi.useFakeTimers();
    document.documentElement.classList.remove('auth-required');
    window.dispatchEvent(new Event('mousemove'));
    await vi.advanceTimersByTimeAsync(1100);
    expect(A.isDesktopLocked()).toBe(true);
    localStorage.removeItem('zettnas_auto_lock_timeout_ms');
  });

  it('a lock survives going back in history', () => {
    A.lockDesktop();
    byId('lock-overlay').style.display = 'none';
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(shown('lock-overlay')).toBe('flex');
    byId('lock-overlay').style.display = 'none';
    window.dispatchEvent(new Event('pageshow'));
    expect(shown('lock-overlay')).toBe('flex');
  });

  it('logs out and shows the sign-in screen', async () => {
    const out = vi.fn();
    ZettEventBus.on('auth:logout', out);
    fetchMock.mockRejectedValueOnce(new Error('offline')); // logging out works offline too
    await A.logout();
    expect(auth.clearToken).toHaveBeenCalled();
    expect(setCurrentUser).toHaveBeenCalledWith(null);
    expect(shown('login-overlay')).toBe('flex');
    expect(shown('os-dock-container')).toBe('none');
    expect(out).toHaveBeenCalled();
  });

  it('a request that needs sign-in brings the sign-in screen back', () => {
    byId('login-overlay').style.display = 'none';
    ZettEventBus.emit('auth:required');
    expect(shown('login-overlay')).toBe('flex');
  });

  it('the front LCD never signs in or locks', async () => {
    const { state } = await import('../state.js');
    state.isLcdDirect = true;
    try {
      expect(A.isLcdMode()).toBe(true);
      sessionStorage.setItem('zettnas_desktop_locked', 'true');
      A.initAuth();
      expect(sessionStorage.getItem('zettnas_desktop_locked')).toBeNull();
      A.lockDesktop();
      expect(A.isDesktopLocked()).toBe(false);
    } finally {
      state.isLcdDirect = false;
    }
  });
});
