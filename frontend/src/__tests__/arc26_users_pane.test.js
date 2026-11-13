/** ARC-26: the People pane (users.js): the list, its dialogs, sign-ins and two-step sign-in. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const me = { current: { id: 'u1', username: 'alice' } };
vi.mock('../api.js', () => ({ api: { get: vi.fn() }, auth: {}, apiFetch: vi.fn() }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../components/session.js', () => ({
  setCurrentUser: vi.fn(),
  getCurrentUser: () => me.current,
  fetchCurrentProfile: vi.fn(async () => {}),
  updateUserInterfaceElements: vi.fn(),
  formatRole: (r) => `role:${r}`,
}));
vi.mock('../components/dock.js', () => ({ initTopbarUserPill: vi.fn() }));
vi.mock('../components/share-access.js', () => ({
  grantShares: vi.fn(async () => {}),
  openShareAccessModal: vi.fn(),
  shareChoicesHtml: (shares) => shares.map((s) => `<select data-add-user-share="${s.name}"><option value="read" selected>r</option></select>`).join(''),
}));
vi.mock('../components/invites-admin.js', () => ({ renderInvites: vi.fn() }));
vi.mock('../management-dom.js', () => ({ onManagementDom: (fn) => fn() }));
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText: vi.fn() }));

const { api, apiFetch } = await import('../api.js');
const { showToast, showConfirmToast, showPromptToast } = await import('../toast.js');
const { grantShares } = await import('../components/share-access.js');
const { copyText } = await import('../utils.js');
const users = await import('../components/users.js');

const reply = (data, ok = true, status = ok ? 200 : 400) => ({ ok, status, json: async () => data });
const byId = (id) => document.getElementById(id);
const flush = () => new Promise((r) => setTimeout(r, 0));
const submit = async (form) => {
  form.dispatchEvent(new Event('submit', { cancelable: true }));
  await vi.waitFor(() => expect(form.querySelector('button[type="submit"]').disabled).toBe(false));
};

const DOM = `
  <button id="btn-add-user"></button><button id="btn-refresh-users"></button><button id="btn-share-access"></button>
  <button id="btn-refresh-sessions"></button><button id="btn-revoke-all-sessions"></button>
  <button id="btn-enable-2fa"></button><button id="btn-disable-2fa"></button>
  <button id="btn-jump-to-security"></button><button id="btn-jump-to-2fa"></button>
  <table><tbody id="users-table-body"></tbody></table><div id="invites-mount"></div>
  <table><tbody id="sessions-table-body"></tbody></table>
  <div id="mfa-status-card"><span id="mfa-status-badge"></span><p id="mfa-status-desc"></p></div>
  <div id="modal-add-user" class="os-modal"><div class="modal-window">
    <button class="modal-close-btn">x</button>
    <form id="form-add-user">
      <input id="add-user-username"><input id="add-user-display"><input id="add-user-email">
      <input id="add-user-password"><select id="add-user-role"><option value="user">u</option></select>
      <input id="add-user-quota"><div id="add-user-shares-wrap"><div id="add-user-shares"></div></div>
      <button type="submit">Add</button>
    </form></div></div>
  <div id="modal-edit-user" class="os-modal"><form id="form-edit-user">
    <input id="edit-user-id"><input id="edit-user-username"><input id="edit-user-display"><input id="edit-user-email">
    <select id="edit-user-role"><option value="user">u</option><option value="superadmin">s</option></select>
    <input id="edit-user-quota"><button type="submit">Save</button></form></div>
  <div id="modal-reset-password" class="os-modal"><span id="reset-pwd-username"></span><form id="form-reset-password">
    <div id="reset-pwd-current-wrap"><input id="reset-pwd-current"></div>
    <div id="reset-pwd-tokens-wrap"><input type="checkbox" id="reset-pwd-revoke-tokens"></div>
    <input id="reset-pwd-input"><input id="reset-pwd-confirm"><button type="submit">Change</button></form></div>
  <div id="modal-setup-2fa" class="os-modal">
    <div id="mfa-step-verify"><div id="mfa-qr-container"></div><code id="mfa-secret-key"></code>
      <form id="form-verify-2fa"><input id="mfa-verify-code"><input id="mfa-current-password"><button type="submit">Verify</button></form></div>
    <div id="mfa-step-success"><div id="mfa-recovery-codes-list"></div><button id="btn-copy-recovery-codes"></button></div>
  </div>`;

const PEOPLE = [
  { id: 'u1', username: 'alice', display_name: 'Alice', role_id: 'superadmin', status: 'active', mfa_enabled: true, storage_quota_bytes: 0 },
  { id: 'u2', username: 'bob', email: 'b@x', role_id: 'user', status: 'disabled', storage_quota_bytes: 5 * 1024 ** 3, quota_enforcement: { enforced: true } },
];

describe('People pane (users.js)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    me.current = { id: 'u1', username: 'alice' };
    document.body.innerHTML = DOM;
    users.initUsersManagement();
  });

  it('says how a limit is held', () => {
    expect(users.quotaHow(null)).toBe('');
    expect(users.quotaHow({ enforced: true })).toContain('held by the disk');
    expect(users.quotaHow({ enforced: false })).toContain('checked on uploads only');
  });

  it('lists people, with no actions against yourself', async () => {
    apiFetch.mockResolvedValue(reply({ users: PEOPLE }));
    await users.loadUsersList();
    const rows = byId('users-table-body').querySelectorAll('tr');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('You');
    expect(rows[0].querySelector('.btn-delete-user')).toBeNull();
    expect(rows[1].textContent).toContain('5 GB · held by the disk');
    expect(rows[1].textContent).toContain('Turned off');
  });

  it('shows the admin-only note, a failure and the empty state', async () => {
    apiFetch.mockResolvedValueOnce(reply({}, false, 403));
    await users.loadUsersList();
    expect(byId('users-table-body').textContent).toContain('Only administrators');
    apiFetch.mockResolvedValueOnce(reply({}, false, 500));
    await users.loadUsersList();
    expect(byId('users-table-body').textContent).toContain('Server returned 500');
    apiFetch.mockResolvedValueOnce(reply({ users: [] }));
    await users.loadUsersList();
    expect(byId('users-table-body').textContent).toContain('Only you so far');
  });

  it('row buttons: edit, reset password, turn on, delete', async () => {
    apiFetch.mockResolvedValue(reply({ users: PEOPLE }));
    await users.loadUsersList();
    const row = byId('users-table-body').querySelectorAll('tr')[1];
    row.querySelector('.btn-edit-user').click();
    expect(byId('modal-edit-user').classList.contains('open')).toBe(true);
    expect(byId('edit-user-quota').value).toBe('5');
    row.querySelector('.btn-pwd-user').click();
    expect(byId('reset-pwd-username').textContent).toBe('@bob');
    expect(byId('reset-pwd-current-wrap').style.display).toBe('none');

    row.querySelector('.btn-toggle-user').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('User status updated.', 'success'));
    expect(JSON.parse(apiFetch.mock.calls.find((c) => c[1]?.method === 'PUT')[1].body)).toEqual({ status: 'active' });

    apiFetch.mockResolvedValueOnce(reply({ detail: 'nope' }, false));
    byId('users-table-body').querySelectorAll('tr')[1].querySelector('.btn-toggle-user').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Could not change status: nope', 'error'));
    apiFetch.mockRejectedValueOnce(new Error('offline'));
    byId('users-table-body').querySelectorAll('tr')[1].querySelector('.btn-toggle-user').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Request failed: offline', 'error'));

    byId('users-table-body').querySelectorAll('tr')[1].querySelector('.btn-delete-user').click();
    const [, msg, onOk, , opts] = showConfirmToast.mock.calls.at(-1);
    expect(msg).toContain('@bob');
    expect(opts).toMatchObject({ destructive: true, typeToConfirm: 'bob' });
    apiFetch.mockResolvedValueOnce(reply({}));
    await onOk();
    expect(showToast).toHaveBeenCalledWith('User @bob deleted.', 'success');
    apiFetch.mockResolvedValueOnce(reply({ detail: 'last admin' }, false));
    await onOk();
    expect(showToast).toHaveBeenCalledWith('Could not delete user: last admin', 'error');
    apiFetch.mockRejectedValueOnce(new Error('down'));
    await onOk();
    expect(showToast).toHaveBeenCalledWith('Request failed: down', 'error');
  });

  it('adds a person and gives them the chosen shared folders', async () => {
    api.get.mockResolvedValue({ shares: [{ name: 'Photos' }] });
    byId('btn-add-user').click();
    await vi.waitFor(() => expect(byId('add-user-shares-wrap').hidden).toBe(false));
    byId('add-user-username').value = 'carol';
    byId('add-user-password').value = 'pw';
    byId('add-user-quota').value = '2';
    apiFetch.mockResolvedValueOnce(reply({ id: 'u3' })).mockResolvedValue(reply({ users: [] }));
    await submit(byId('form-add-user'));
    const body = JSON.parse(apiFetch.mock.calls[0][1].body);
    expect(body).toMatchObject({ username: 'carol', display_name: 'carol', storage_quota_bytes: 2 * 1024 ** 3 });
    expect(grantShares).toHaveBeenCalledWith('carol', { Photos: 'read' });
    expect(showToast).toHaveBeenCalledWith('User created successfully.', 'success');

    grantShares.mockRejectedValueOnce(new Error('no right'));
    await users.grantChosenShares('dan');
    expect(showToast.mock.calls.at(-1)[0]).toContain('dan was added');

    byId('btn-add-user').click();
    apiFetch.mockResolvedValueOnce(reply({ detail: 'taken' }, false));
    await submit(byId('form-add-user'));
    expect(showToast).toHaveBeenCalledWith('Error: taken', 'error');
    apiFetch.mockRejectedValueOnce(new Error('offline'));
    await submit(byId('form-add-user'));
    expect(showToast).toHaveBeenCalledWith('Request failed: offline', 'error');

    api.get.mockRejectedValueOnce(new Error('403'));
    await users.loadAddUserShares();
    expect(byId('add-user-shares-wrap').hidden).toBe(true);
  });

  it('edits a person', async () => {
    users.showEditUserModal(PEOPLE[1]);
    byId('edit-user-display').value = 'Bobby';
    apiFetch.mockResolvedValueOnce(reply({})).mockResolvedValue(reply({ users: [] }));
    await submit(byId('form-edit-user'));
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toMatchObject({ display_name: 'Bobby', storage_quota_bytes: 5 * 1024 ** 3 });
    expect(showToast).toHaveBeenCalledWith('User updated successfully.', 'success');
    apiFetch.mockResolvedValueOnce(reply({}, false));
    await submit(byId('form-edit-user'));
    expect(showToast).toHaveBeenCalledWith('Error: Failed to update user', 'error');
    apiFetch.mockRejectedValueOnce(new Error('x'));
    await submit(byId('form-edit-user'));
    expect(showToast).toHaveBeenCalledWith('Request failed: x', 'error');
  });

  it('changes a password: yours needs the current one', async () => {
    users.showResetPasswordModal('u1', 'alice');
    expect(byId('reset-pwd-current').required).toBe(true);
    expect(byId('reset-pwd-tokens-wrap').hidden).toBe(false);
    byId('reset-pwd-input').value = 'a';
    byId('reset-pwd-confirm').value = 'b';
    byId('form-reset-password').dispatchEvent(new Event('submit', { cancelable: true }));
    expect(showToast).toHaveBeenCalledWith('Passwords do not match.', 'error');

    byId('reset-pwd-confirm').value = 'a';
    byId('reset-pwd-current').value = 'old';
    apiFetch.mockResolvedValueOnce(reply({}));
    await submit(byId('form-reset-password'));
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ new_password: 'a', current_password: 'old', revoke_tokens: false });
    expect(showToast.mock.calls.at(-1)[0]).toContain('Your other sessions were signed out');

    users.showResetPasswordModal('u2', 'bob');
    byId('reset-pwd-input').value = 'z';
    byId('reset-pwd-confirm').value = 'z';
    apiFetch.mockResolvedValueOnce(reply({}));
    await submit(byId('form-reset-password'));
    expect(JSON.parse(apiFetch.mock.calls.at(-1)[1].body)).toEqual({ new_password: 'z' });
    expect(showToast.mock.calls.at(-1)[0]).toContain('They were signed out everywhere');
    apiFetch.mockResolvedValueOnce(reply({ detail: 'weak' }, false));
    await submit(byId('form-reset-password'));
    expect(showToast).toHaveBeenCalledWith('Error: weak', 'error');
    apiFetch.mockRejectedValueOnce(new Error('gone'));
    await submit(byId('form-reset-password'));
    expect(showToast).toHaveBeenCalledWith('Request failed: gone', 'error');
  });

  it('lists sign-ins and signs one or all others out', async () => {
    apiFetch.mockResolvedValueOnce(reply({ sessions: [
      { id: 's1', is_current: true, user_agent: 'Firefox', ip_address: '10.0.0.2' },
      { id: 's2', is_current: false },
    ] }));
    await users.loadSessionsList();
    const rows = byId('sessions-table-body').querySelectorAll('tr');
    expect(rows[0].textContent).toContain('This browser');
    expect(rows[1].textContent).toContain('Unknown browser');
    apiFetch.mockResolvedValue(reply({ sessions: [] }));
    rows[1].querySelector('.btn-revoke-session').click();
    await vi.waitFor(() => expect(byId('sessions-table-body').textContent).toContain('No other sign-ins.'));
    expect(apiFetch).toHaveBeenCalledWith('/api/auth/sessions/s2', expect.objectContaining({ method: 'DELETE' }));

    apiFetch.mockResolvedValueOnce(reply({}, false, 500));
    await users.loadSessionsList();
    expect(byId('sessions-table-body').textContent).toContain('HTTP 500');

    byId('btn-revoke-all-sessions').click();
    const onOk = showConfirmToast.mock.calls.at(-1)[2];
    apiFetch.mockResolvedValueOnce(reply({}));
    await onOk();
    expect(showToast).toHaveBeenCalledWith('All other sessions revoked.', 'success');
    apiFetch.mockResolvedValueOnce(reply({}, false));
    await onOk();
    expect(showToast).toHaveBeenCalledWith('Failed to revoke other sessions.', 'error');
    apiFetch.mockRejectedValueOnce(new Error('x'));
    await onOk();
    expect(showToast).toHaveBeenCalledWith('Failed: x', 'error');
  });

  it('shows whether two-step sign-in is on', async () => {
    apiFetch.mockResolvedValueOnce(reply({ mfa_enabled: true }));
    await users.load2FAStatus();
    expect(byId('mfa-status-badge').textContent).toBe('On');
    expect(byId('btn-disable-2fa').style.display).toBe('inline-flex');
    apiFetch.mockResolvedValueOnce(reply({ mfa_enabled: false }));
    await users.load2FAStatus();
    expect(byId('mfa-status-desc').textContent).toContain('is off');
    expect(byId('btn-enable-2fa').style.display).toBe('inline-flex');
    apiFetch.mockResolvedValueOnce(reply({}, false));
    await users.load2FAStatus();
    expect(byId('mfa-status-badge').textContent).toBe('Off');
  });

  it('sets up two-step sign-in and shows the recovery codes', async () => {
    apiFetch.mockResolvedValueOnce(reply({ qr_svg: '<svg id="qr"></svg>', secret: 'ABC', recovery_codes: ['r1'] }));
    byId('btn-enable-2fa').click();
    await vi.waitFor(() => expect(byId('mfa-secret-key').textContent).toBe('ABC'));
    byId('mfa-verify-code').value = '123456';
    apiFetch.mockResolvedValueOnce(reply({ detail: 'Invalid code' }, false));
    await submit(byId('form-verify-2fa'));
    expect(showToast).toHaveBeenCalledWith('Verification failed: Invalid code', 'error');
    apiFetch.mockRejectedValueOnce(new Error('x'));
    await submit(byId('form-verify-2fa'));
    expect(showToast).toHaveBeenCalledWith('Error: x', 'error');
    apiFetch.mockResolvedValueOnce(reply({ recovery_codes: ['aaa-111', 'bbb-222'] })).mockResolvedValue(reply({ mfa_enabled: true }));
    await submit(byId('form-verify-2fa'));
    expect(byId('mfa-step-success').style.display).toBe('block');
    expect(byId('mfa-recovery-codes-list').textContent).toContain('bbb-222');
    byId('btn-copy-recovery-codes').click();
    expect(byId('btn-copy-recovery-codes').textContent).toBe('Copied');
    expect(copyText).toHaveBeenCalledWith('aaa-111\nbbb-222');

    apiFetch.mockResolvedValueOnce(reply({}, false));
    byId('btn-enable-2fa').click();
    await vi.waitFor(() => expect(byId('mfa-qr-container').textContent).toContain("couldn't be set up"));
  });

  it('turns two-step sign-in off with the password and a code', async () => {
    byId('btn-disable-2fa').click();
    const askPassword = showPromptToast.mock.calls.at(-1)[3];
    askPassword('');
    expect(showPromptToast).toHaveBeenCalledTimes(1);
    askPassword('pw');
    const askCode = showPromptToast.mock.calls.at(-1)[3];
    expect(askCode('')).toBeUndefined();
    apiFetch.mockResolvedValue(reply({}));
    await askCode(' 123456 ');
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ password: 'pw', code: '123456' });
    expect(showToast).toHaveBeenCalledWith('Two-Factor Authentication has been disabled.', 'success');
    apiFetch.mockResolvedValueOnce(reply({}, false));
    await askCode('1');
    expect(showToast).toHaveBeenCalledWith('Could not disable 2FA: Invalid password', 'error');
    apiFetch.mockRejectedValueOnce(new Error('x'));
    await askCode('1');
    expect(showToast).toHaveBeenCalledWith('Request failed: x', 'error');
  });

  it('closes dialogs with the close button, the backdrop and Escape', () => {
    const modal = byId('modal-add-user');
    users.openModal(modal);
    modal.querySelector('.modal-close-btn').click();
    expect(modal.classList.contains('open')).toBe(false);
    users.openModal(modal);
    modal.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(modal.style.display).toBe('none');
    users.openModal(modal);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(modal.classList.contains('open')).toBe(false);
    users.openModal(null);
    users.closeModal(null);
  });

  it('jump buttons open Mission Control at the right place', () => {
    window.openManagementWindow = vi.fn();
    byId('btn-jump-to-security').click();
    byId('btn-jump-to-2fa').click();
    expect(window.openManagementWindow.mock.calls).toEqual([['mgmt-pane-account'], ['mgmt-pane-account']]); // My account (SET-19)
    delete window.openManagementWindow;
  });

  it('opens the pane at a part', async () => {
    const part = document.createElement('div');
    part.id = 'users-pane-2fa';
    part.scrollIntoView = vi.fn();
    document.body.append(part);
    apiFetch.mockResolvedValue(reply({ users: [], sessions: [], mfa_enabled: false }));
    await users.loadUsersPane('users-pane-2fa');
    await flush();
    expect(part.scrollIntoView).toHaveBeenCalled();
  });
});
