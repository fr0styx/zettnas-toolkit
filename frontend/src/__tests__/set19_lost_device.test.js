import { describe, it, expect, vi, beforeEach } from 'vitest';

const post = vi.fn();
vi.mock('../api.js', () => ({ api: { post } }));
const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast, showConfirmToast: vi.fn() }));

const { installLostDeviceFor, submitLostDevice, lostDoneText } = await import('../components/management/lost-device.js');
const lea = { id: 'u-lea', username: 'lea' };

describe('Lost phone or tablet? (SET-19, Users decision 8)', () => {
  /** @type {HTMLElement} */
  let modal;
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="m"><form></form><div id="passkeys-reset"></div></div>';
    modal = /** @type {HTMLElement} */ (document.getElementById('m'));
  });

  it('sits closed under the passkeys, and not for the own account', () => {
    const box = /** @type {HTMLDetailsElement} */ (installLostDeviceFor(modal, lea, { id: 'u-mum' }));
    expect(box.previousElementSibling?.id).toBe('passkeys-reset');
    expect(box.open).toBe(false);
    expect(box.hidden).toBe(false);
    expect(box.querySelector('summary')?.textContent).toBe('Lost phone or tablet?');
    expect(installLostDeviceFor(modal, lea, { id: 'u-lea' })?.hidden).toBe(true);
    expect(modal.querySelectorAll('#lost-device').length).toBe(1); // reused, not added again
    expect(installLostDeviceFor(null, lea)).toBeNull();
    document.body.innerHTML = '<div id="bare"></div>';
    expect(installLostDeviceFor(/** @type {HTMLElement} */ (document.getElementById('bare')), lea)?.parentElement).toBe(document.body); // after a dialog with no form
  });

  it('sends the own password and the two choices, and empties the password', async () => {
    const box = /** @type {HTMLElement} */ (installLostDeviceFor(modal, lea));
    /** @type {HTMLInputElement} */ (box.querySelector('[data-lost-pw]')).value = 'Mum-Pass-123';
    /** @type {HTMLInputElement} */ (box.querySelector('[data-lost-two-step]')).checked = true;
    post.mockResolvedValue({ sessions_ended: 2, two_step_off: true, told: true });
    /** @type {HTMLElement} */ (box.querySelector('[data-lost-go]')).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith('/api/users/u-lea/lost-device', { current_password: 'Mum-Pass-123', sign_out: true, turn_off_two_step: true });
    expect(/** @type {HTMLInputElement} */ (box.querySelector('[data-lost-pw]')).value).toBe('');
    expect(showToast).toHaveBeenCalledWith('Ended 2 sessions of lea. Two-step sign-in is off for lea. They were told.', 'success');
  });

  it('asks for a choice before sending anything', async () => {
    const box = /** @type {HTMLElement} */ (installLostDeviceFor(modal, lea));
    /** @type {HTMLInputElement} */ (box.querySelector('[data-lost-sign-out]')).checked = false;
    expect(await submitLostDevice(box, lea)).toBeNull();
    expect(post).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith('Choose at least one of the two.', 'error');
  });

  it('a refusal (a wrong password) is said as the server says it', async () => {
    const box = /** @type {HTMLElement} */ (installLostDeviceFor(modal, lea));
    post.mockRejectedValue(new Error('Enter your own password to do this.'));
    expect(await submitLostDevice(box, lea)).toBeNull();
    expect(showToast).toHaveBeenCalledWith('Enter your own password to do this.', 'error');
  });

  it('says plainly when there was nothing to end, or nobody could be told', () => {
    expect(lostDoneText({ sessions_ended: 0, two_step_off: false, told: false }, 'lea', true)).toBe('lea was not signed in anywhere.');
    expect(lostDoneText({ sessions_ended: 1, two_step_off: false, told: false }, 'lea', true)).toBe('Ended 1 session of lea. Kiboto could not tell them: they have no alerts or email set up.');
    expect(lostDoneText({ sessions_ended: 0, two_step_off: true, told: true }, 'lea', false)).toBe('Two-step sign-in is off for lea. They were told.');
  });
});
