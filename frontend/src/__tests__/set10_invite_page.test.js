// SET-10: the invite page waits for the language and names the role in it.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { initInviteLanding, inviteRoleName } from '../components/invites.js';

describe('the invite page', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    window.location.hash = '';
    vi.restoreAllMocks();
  });

  it('names the role in words, not by its code name', () => {
    expect(inviteRoleName({ role: 'ShareUser', role_id: 'share_user' })).toBe('Family member');
    expect(inviteRoleName({ role: 'Kid', role_id: 'kid' })).toBe('Kid');
    expect(inviteRoleName({ role: 'Storage Admin', role_id: 'storage_admin' })).toBe('Storage Admin');
    expect(inviteRoleName(null)).toBe('');
  });

  it('draws nothing until the texts are loaded', async () => {
    window.location.hash = '#/invite/abcdefghijklmnop12';
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ valid: true, role: 'ShareUser', role_id: 'share_user' }) })));
    let loaded;
    const texts = new Promise((resolve) => { loaded = resolve; });
    const drawn = initInviteLanding(texts);
    await new Promise((r) => setTimeout(r, 0));
    expect(document.querySelector('dialog.invite-landing')).toBeNull();
    loaded();
    expect(await drawn).toBe(true);
    const page = document.querySelector('dialog.invite-landing');
    expect(page.textContent).toContain('Your account will be: Family member');
    expect(page.textContent).not.toContain('ShareUser');
    vi.unstubAllGlobals();
  });

  it('is still drawn when the texts fail to load, and does nothing without an invite', async () => {
    expect(await initInviteLanding(Promise.resolve())).toBe(false);
    window.location.hash = '#/invite/abcdefghijklmnop12';
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));
    expect(await initInviteLanding(Promise.reject(new Error('offline')))).toBe(true);
    expect(document.querySelector('dialog.invite-landing').textContent).toContain('expired');
    vi.unstubAllGlobals();
  });
});
