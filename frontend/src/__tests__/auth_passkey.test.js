import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../passkeys.js', () => ({ passkeySignIn: vi.fn(), passkeysAvailable: vi.fn(() => true) }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/setup-wizard-gate.js', () => ({ openSetupWizard: vi.fn() }));
vi.mock('../components/session.js', () => ({
  fetchCurrentProfile: vi.fn(), getCurrentUser: vi.fn(), setCurrentUser: vi.fn(), promptRequiredMfa: vi.fn(),
}));
const pk = await import('../passkeys.js');
const toast = await import('../toast.js');
const wizard = await import('../components/setup-wizard-gate.js');
const session = await import('../components/session.js');
const { finishSignIn, signInWithPasskey, showSecondStepChoices } = await import('../components/auth.js');

const DOM = `<div id="login-overlay"></div><div id="os-dock-container" style="display:none"></div>
  <input type="checkbox" id="login-remember-me" checked><p id="login-error" hidden></p>
  <form id="form-mfa-challenge"></form><a id="mfa-toggle-recovery"></a><a id="mfa-use-passkey" hidden></a>`;

describe('signing in with a passkey (RES-3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    document.body.innerHTML = DOM;
    document.documentElement.classList.add('auth-required');
  });

  it('finishes a sign-in and opens what the account still needs', () => {
    finishSignIn({ token: 't', user: { id: 'u' }, must_change_password: true });
    expect(document.documentElement.classList.contains('has-auth-session')).toBe(true);
    expect(session.setCurrentUser).toHaveBeenCalledWith({ id: 'u' });
    vi.advanceTimersByTime(400);
    expect(wizard.openSetupWizard).toHaveBeenCalled();
    finishSignIn({ mfa_setup_required: true });
    vi.advanceTimersByTime(400);
    expect(session.promptRequiredMfa).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('signs in alone or as the second step', async () => {
    vi.useRealTimers();
    pk.passkeySignIn.mockResolvedValueOnce({ status: 'ok', token: 'tok' });
    expect(await signInWithPasskey('')).toBe(true);
    expect(pk.passkeySignIn).toHaveBeenCalledWith({ mfaToken: '', rememberMe: true });
    pk.passkeySignIn.mockRejectedValueOnce(Object.assign(new Error('closed'), { name: 'NotAllowedError' }));
    expect(await signInWithPasskey('mfa_x')).toBe(false);
    expect(toast.showToast).not.toHaveBeenCalled();
    pk.passkeySignIn.mockRejectedValueOnce(new Error('This passkey isn\'t known here.'));
    await signInWithPasskey('mfa_x');
    expect(toast.showToast).toHaveBeenCalledWith('This passkey isn\'t known here.', 'error');
    pk.passkeySignIn.mockRejectedValueOnce(new Error('not an IP address'));
    await signInWithPasskey('');
    expect(document.getElementById('login-error').textContent).toContain('not an IP address');
  });

  it('offers the passkey, and the code only when the account has one', () => {
    showSecondStepChoices({ passkey: true, code: false }, true);
    expect(document.getElementById('mfa-use-passkey').hidden).toBe(false);
    expect(document.getElementById('form-mfa-challenge').hidden).toBe(true);
    expect(document.getElementById('mfa-toggle-recovery').hidden).toBe(true);
    showSecondStepChoices({ passkey: true, code: true }, false);
    expect(document.getElementById('mfa-use-passkey').hidden).toBe(true);
    expect(document.getElementById('form-mfa-challenge').hidden).toBe(false);
    vi.useRealTimers();
  });
});
