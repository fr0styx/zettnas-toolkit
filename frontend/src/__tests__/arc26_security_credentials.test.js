/** ARC-26: Mission Control's sign-in credentials card (settings.js): checks before saving, and saving. */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';

vi.mock('../management-dom.js', () => ({ onManagementDom: (fn) => fn(), ensureManagementDom: async () => {} }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showActionToast: vi.fn(), showPromptToast: vi.fn(), showConfirmToast: vi.fn() }));

const { api } = await import('../api.js');
const { showToast, showConfirmToast } = await import('../toast.js');
const { initSettings } = await import('../components/settings.js');

const byId = (id) => document.getElementById(id);
const type = (id, value) => {
  byId(id).value = value;
  byId(id).dispatchEvent(new Event('input'));
};

describe('credentials card', () => {
  beforeAll(() => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    document.body.innerHTML = `
      <input id="sec-cur-pwd">
      <input id="sec-new-pwd"><input id="sec-confirm-pwd"><div id="sec-pwd-mismatch-msg" style="display:none"></div>
      <button id="sec-save-btn"><span aria-hidden="true">💾</span> <span>Save</span></button>
      <button id="btn-disable-default-admin"></button>`;
    initSettings();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(api, 'get').mockResolvedValue({});
    for (const id of ['sec-cur-pwd', 'sec-new-pwd', 'sec-confirm-pwd']) byId(id).value = '';
  });
  afterEach(() => vi.useRealTimers());

  it('marks a confirmation that does not match while typing', () => {
    type('sec-new-pwd', 'correct horse');
    expect(byId('sec-confirm-pwd').style.borderColor).toBe('rgba(255, 255, 255, 0.12)');
    type('sec-confirm-pwd', 'correct');
    expect(byId('sec-pwd-mismatch-msg').style.display).toBe('flex');
    type('sec-confirm-pwd', 'correct horse');
    expect(byId('sec-pwd-mismatch-msg').style.display).toBe('none');
    expect(byId('sec-confirm-pwd').style.borderColor).toContain('--ok2');
    type('sec-new-pwd', '');
    type('sec-confirm-pwd', '');
    expect(byId('sec-new-pwd').style.borderColor).toBe('rgba(255, 255, 255, 0.12)');
  });

  it('refuses to save without the current password, a confirmation, a match or a real password', () => {
    const save = () => byId('sec-save-btn').click();
    const last = () => showToast.mock.calls.at(-1);
    save();
    expect(last()[0]).toMatch(/current password is required/i);
    byId('sec-cur-pwd').value = 'old';
    byId('sec-new-pwd').value = 'newpassword';
    save();
    expect(last()[0]).toMatch(/confirm/i);
    byId('sec-confirm-pwd').value = 'other';
    save();
    expect(last()[0]).toMatch(/do not match/i);
    expect(byId('sec-pwd-mismatch-msg').style.display).toBe('flex');
    byId('sec-new-pwd').value = 'short';
    byId('sec-confirm-pwd').value = 'short';
    save();
    expect(last()[0]).toMatch(/8 characters/);
    expect(last()[1]).toBe('error');
  });

  it('changes the signed-in person\'s own password and keeps this browser signed in (SET-10)', async () => {
    localStorage.setItem('kiboto_signed_in', '1');
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/auth/me' ? { id: 'usr_anna', username: 'anna', role: 'superadmin' } : {}));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });
    byId('sec-cur-pwd').value = 'old';
    byId('sec-new-pwd').value = 'a long new password';
    byId('sec-confirm-pwd').value = 'a long new password';
    byId('sec-save-btn').click();
    await vi.waitFor(() => expect(showToast.mock.calls.some(([m, k]) => k === 'success' && /updated/i.test(m))).toBe(true));
    // her own account, not the built-in administrator's form
    expect(post).toHaveBeenCalledWith('/api/users/usr_anna/password', { current_password: 'old', new_password: 'a long new password' });
    expect(post.mock.calls.map((c) => c[0])).not.toContain('/api/security');
    expect(byId('sec-save-btn').textContent).toBe('💾 Save');
    expect(byId('sec-cur-pwd').value).toBe('');
    expect(byId('sec-new-pwd').value).toBe('');
    expect(localStorage.getItem('kiboto_signed_in')).toBe('1');

    byId('sec-cur-pwd').value = 'old';
    byId('sec-new-pwd').value = 'a long new password';
    byId('sec-confirm-pwd').value = 'a long new password';
    post.mockRejectedValueOnce(new Error('Wrong current password'));
    byId('sec-save-btn').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Wrong current password', 'error'));
    expect(byId('sec-save-btn').textContent).toBe('💾 Save');
  });

  it('asks for a new password: the form saves nothing else any more', () => {
    byId('sec-cur-pwd').value = 'old';
    byId('sec-save-btn').click();
    expect(showToast.mock.calls.at(-1)).toEqual(['Enter a new password.', 'error']);
  });

  it('turning off the default admin asks first', async () => {
    byId('btn-disable-default-admin').click();
    const onOk = showConfirmToast.mock.calls.at(-1)[2];
    vi.spyOn(api, 'post').mockResolvedValueOnce({ is_self: false });
    await onOk();
    expect(showToast.mock.calls.at(-1)[1]).toBe('success');
    vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('last admin'));
    await onOk();
    expect(showToast).toHaveBeenCalledWith('last admin', 'error');
  });
});
