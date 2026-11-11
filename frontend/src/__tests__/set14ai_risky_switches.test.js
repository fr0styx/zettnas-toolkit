import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showDangerConfirm: vi.fn() }));
import { api } from '../api.js';
import * as toast from '../toast.js';
import { renderGuardPanel } from '../components/guard-panel.js';
import { renderMfaPolicy } from '../components/management/mfa-policy.js';

beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe('risky switches ask first (SET-14, Settings finding 23)', () => {
  it('turning the ransomware guard off asks; nothing is saved before the answer', async () => {
    document.body.innerHTML = '<div id="sec-guard-card"></div>';
    vi.spyOn(api, 'get').mockImplementation(async (u) => (u.includes('ip-blocks') ? [] : { enabled: true, canaries: true, canary_count: 2 }));
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    await renderGuardPanel();
    const box = document.querySelector('#sec-guard-card input[type=checkbox]');
    box.checked = false;
    box.dispatchEvent(new Event('change'));
    expect(toast.showDangerConfirm).toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
    toast.showDangerConfirm.mock.calls.at(-1)[2]();
    await vi.waitFor(() => expect(put).toHaveBeenCalledWith('/api/security/ransomware', { enabled: false }));
  });

  it('a failed unblock says so', async () => {
    document.body.innerHTML = '<div id="sec-guard-card"></div>';
    vi.spyOn(api, 'get').mockImplementation(async (u) => (u.includes('ip-blocks') ? [{ ip: '10.0.0.9', reason: 'x' }] : { enabled: true }));
    vi.spyOn(api, 'delete').mockRejectedValue(new Error('down'));
    await renderGuardPanel();
    [...document.querySelectorAll('#sec-guard-card button')].find((b) => b.textContent === 'Unblock').click();
    await vi.waitFor(() => expect(toast.showToast).toHaveBeenCalledWith('10.0.0.9 is still blocked: down', 'error'));
  });

  it('requiring two-step sign-in for a role with people who lack it asks first', async () => {
    document.body.innerHTML = '<div id="sec-advisor-card"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ required_roles: [], without_two_step: { kid: 2 } });
    const put = vi.spyOn(api, 'put').mockResolvedValue({ required_roles: ['kid'], without_two_step: { kid: 2 } });
    await renderMfaPolicy();
    const kid = document.querySelector('input[data-mfa-role="kid"]');
    kid.checked = true;
    kid.dispatchEvent(new Event('change', { bubbles: true }));
    expect(toast.showConfirmToast).toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
    toast.showConfirmToast.mock.calls.at(-1)[3]();
    expect(kid.checked).toBe(false);
  });
});
