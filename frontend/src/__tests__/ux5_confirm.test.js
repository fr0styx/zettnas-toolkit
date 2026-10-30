import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showConfirmToast, confirmButtonFor } from '../toast.js';

const modal = () => document.getElementById('confirm-toast-modal');
const ok = () => document.getElementById('confirm-toast-ok');
const cancel = () => document.getElementById('confirm-toast-cancel');
const key = (k, opts = {}) => document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, ...opts }));

describe('confirm dialog (UX-5, UX-6)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<button id="opener">Open</button>';
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it('names the action on its button and is red only when destructive', () => {
    expect(confirmButtonFor('Delete User', '')).toEqual({ label: 'Delete User', destructive: true });
    expect(confirmButtonFor('Restart Samba', '')).toEqual({ label: 'Restart Samba', destructive: false });
    expect(confirmButtonFor('Confirm Action', 'Delete snapshot x?')).toEqual({ label: 'Continue', destructive: true });
    expect(confirmButtonFor('Benutzer löschen', '')).toMatchObject({ destructive: true });
    expect(confirmButtonFor('Apply', '', { okText: 'Save', destructive: false })).toEqual({ label: 'Save', destructive: false });
  });

  it('takes focus, keeps Tab inside, and gives focus back', () => {
    const opener = document.getElementById('opener');
    opener.focus();
    showConfirmToast('Restart Samba', 'Clients reconnect.', vi.fn());
    vi.advanceTimersByTime(20);
    expect(document.activeElement).toBe(ok()); // not destructive: starts on the action
    key('Tab');
    expect(modal().contains(document.activeElement)).toBe(true);
    for (let i = 0; i < 5; i++) key('Tab', { shiftKey: i % 2 === 0 });
    expect(modal().contains(document.activeElement)).toBe(true);
    key('Escape');
    expect(document.activeElement).toBe(opener);
  });

  it('starts on Cancel for a destructive action', () => {
    showConfirmToast('Delete VM', 'Gone for good.', vi.fn());
    vi.advanceTimersByTime(20);
    expect(document.activeElement).toBe(cancel());
    expect(ok().style.background).toContain("zn-confirm-danger"); // red, at 4.5:1 with white (NUX-16)
  });

  it('asks to type the name before a big delete', () => {
    const onConfirm = vi.fn();
    showConfirmToast('Remove Share', 'The share goes away.', onConfirm, null, { typeToConfirm: 'media', destructive: true });
    vi.advanceTimersByTime(20);
    const input = document.getElementById('confirm-toast-type-input');
    expect(document.activeElement).toBe(input);
    expect(ok().disabled).toBe(true);
    ok().click();
    expect(onConfirm).not.toHaveBeenCalled();
    input.value = 'medi';
    input.dispatchEvent(new Event('input'));
    expect(ok().disabled).toBe(true);
    input.value = 'media';
    input.dispatchEvent(new Event('input'));
    expect(ok().disabled).toBe(false);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('drops the name field for the next, ordinary confirm', () => {
    showConfirmToast('Remove Share', 'x', vi.fn(), null, { typeToConfirm: 'media' });
    key('Escape');
    showConfirmToast('Restart Samba', 'y', vi.fn());
    expect(document.getElementById('confirm-toast-type-input')).toBeNull();
    expect(ok().disabled).toBe(false);
  });
});
