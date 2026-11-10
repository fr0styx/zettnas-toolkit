import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() }, apiFetch: vi.fn(), setSessionUserProvider: vi.fn(), auth: {} }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/users.js', () => ({ start2FASetup: vi.fn() }));

const { api } = await import('../api.js');
const toast = await import('../toast.js');
const users = await import('../components/users.js');
const { mfaPolicyHtml, selectedRoles, renderMfaPolicy } = await import('../components/management/mfa-policy.js');
const { promptRequiredMfa } = await import('../components/session.js');

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('Two-step sign-in required by role', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="sec-advisor-card"></div>';
  });

  it('lists the roles, ticks the required ones and says who is still without it', () => {
    const html = mfaPolicyHtml({ required_roles: ['superadmin'], without_two_step: { share_user: 2 } });
    document.body.innerHTML = `<div id="x">${html}</div>`;
    const root = document.getElementById('x');
    expect(selectedRoles(root)).toEqual(['superadmin']);
    expect(html).toContain('2 without it');
    expect(root.querySelectorAll('input[data-mfa-role]').length).toBe(8);
  });

  it('saves a change, and puts the box back when the server refuses it', async () => {
    api.get.mockResolvedValue({ required_roles: [], without_two_step: {} });
    await renderMfaPolicy();
    const box = document.getElementById('sec-mfa-policy');
    const kid = box.querySelector('input[data-mfa-role="kid"]');
    api.put.mockResolvedValueOnce({ required_roles: ['kid'], without_two_step: {} });
    kid.checked = true;
    kid.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    expect(api.put).toHaveBeenCalledWith('/api/security/mfa-policy', { required_roles: ['kid'] });
    const admin = box.querySelector('input[data-mfa-role="superadmin"]');
    api.put.mockRejectedValueOnce(new Error('Turn on two-step sign-in for yourself first'));
    admin.checked = true;
    admin.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    expect(admin.checked).toBe(false);
    expect(toast.showToast).toHaveBeenLastCalledWith('Turn on two-step sign-in for yourself first', 'error');
  });

  it('hides itself for someone who may not read the policy', async () => {
    api.get.mockRejectedValue(new Error('forbidden'));
    await renderMfaPolicy();
    expect(document.getElementById('sec-mfa-policy').hidden).toBe(true);
  });

  it('opens the setup once when the role requires it', async () => {
    expect(promptRequiredMfa({ mfa_setup_required: false })).toBe(false);
    expect(promptRequiredMfa({ mfa_setup_required: true })).toBe(true);
    expect(promptRequiredMfa({ mfa_setup_required: true })).toBe(false);
    await tick();
    await tick();
    expect(users.start2FASetup).toHaveBeenCalledTimes(1);
  });
});
