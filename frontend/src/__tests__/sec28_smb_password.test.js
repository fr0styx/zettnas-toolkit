// SEC-28: a separate shared folders password for two-step accounts
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ apiFetch: vi.fn() }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../utils.js', () => ({ copyText: vi.fn() }));
import { apiFetch } from '../api.js';
import { showToast, showPromptToast } from '../toast.js';
import { copyText } from '../utils.js';
import { renderSmbPassword, makeSmbPassword, askForSmbPassword } from '../components/smb-password.js';

const reply = (status, body) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

describe('shared folders password', () => {
  beforeEach(() => {
    apiFetch.mockReset();
    showToast.mockReset();
    showPromptToast.mockReset();
    copyText.mockReset();
  });

  it('shows the password once with the username, and copies it', async () => {
    const box = document.createElement('div');
    box.hidden = true;
    renderSmbPassword(box, { username: 'ann', password: 'abcde-fghjk-mnpqr-stuvw' });
    expect(box.hidden).toBe(false);
    expect(box.querySelector('.smb-pw-value').textContent).toBe('abcde-fghjk-mnpqr-stuvw');
    expect(box.textContent).toContain('ann');
    copyText.mockResolvedValue(undefined);
    box.querySelector('button').click();
    await vi.waitFor(() => expect(box.querySelector('button').textContent).toBe('Copied'));
    expect(copyText).toHaveBeenCalledWith('abcde-fghjk-mnpqr-stuvw');
  });

  it('selects the password when copying is refused', async () => {
    const box = document.createElement('div');
    document.body.append(box);
    renderSmbPassword(box, { username: 'ann', password: 'p' });
    copyText.mockRejectedValue(new Error('no'));
    box.querySelector('button').click();
    await vi.waitFor(() => expect(window.getSelection().toString()).toBe('p'));
    box.remove();
  });

  it('sends the account password and shows the result', async () => {
    const box = document.createElement('div');
    apiFetch.mockReturnValue(reply(200, { username: 'ann', password: 'x-y' }));
    const data = await makeSmbPassword('secret', box);
    expect(data.password).toBe('x-y');
    const [url, opts] = apiFetch.mock.calls[0];
    expect(url).toBe('/api/auth/me/smb-password');
    expect(JSON.parse(opts.body)).toEqual({ current_password: 'secret' });
    expect(box.querySelector('.smb-pw-value').textContent).toBe('x-y');
  });

  it('says why when it is refused or the server is unreachable', async () => {
    apiFetch.mockReturnValue(reply(403, { detail: 'Enter your current password.' }));
    expect(await makeSmbPassword('bad', null)).toBeNull();
    expect(showToast).toHaveBeenCalledWith('Enter your current password.', 'error');
    apiFetch.mockReturnValue(reply(500, null));
    expect(await makeSmbPassword('x', null)).toBeNull();
    expect(showToast).toHaveBeenLastCalledWith('The password could not be made.', 'error');
    apiFetch.mockRejectedValue(new Error('offline'));
    expect(await makeSmbPassword('x', null)).toBeNull();
    expect(showToast).toHaveBeenCalledTimes(3);
  });

  it('asks for the account password first, as a password field', () => {
    askForSmbPassword(null);
    const [, , , onConfirm, , options] = showPromptToast.mock.calls[0];
    expect(options.inputType).toBe('password');
    expect(onConfirm('')).toBeUndefined();
    apiFetch.mockReturnValue(reply(200, { username: 'a', password: 'b' }));
    onConfirm('pw');
    expect(apiFetch).toHaveBeenCalled();
  });
});
