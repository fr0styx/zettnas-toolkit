import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }, auth: { setToken: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn((msg, ok) => ok()) }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const pk = await import('../passkeys.js');
const { passkeysHtml, loadPasskeysCard } = await import('../components/passkeys-card.js');

const tick = () => new Promise((r) => setTimeout(r, 0));
const bytes = (...n) => new Uint8Array(n).buffer;
const SECURE = { PublicKeyCredential: function PKC() {}, isSecureContext: true, location: { hostname: 'attic.example.ts.net' } };

describe('passkeys in the browser (RES-3)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('only on a secure page with a name', () => {
    expect(pk.passkeysAvailable(SECURE)).toBe(true);
    expect(pk.passkeysAvailable({ ...SECURE, isSecureContext: false })).toBe(false);
    expect(pk.passkeysAvailable({ ...SECURE, location: { hostname: '192.168.50.10' } })).toBe(false);
    expect(pk.passkeysAvailable({ ...SECURE, location: { hostname: '[::1]' } })).toBe(false);
    expect(pk.passkeysAvailable({ ...SECURE, PublicKeyCredential: undefined })).toBe(false);
    expect(pk.passkeysAvailable(null)).toBe(false);
  });

  it('turns base64url into bytes and back', () => {
    const b = pk.fromB64('AQID_w');
    expect([...new Uint8Array(b)]).toEqual([1, 2, 3, 255]);
    expect(pk.toB64(b)).toBe('AQID_w');
    expect(pk.toB64(new Uint8Array([1, 2, 3, 255]))).toBe('AQID_w');
  });

  it('prepares the options the browser wants', () => {
    const c = pk.creationOptions({ challenge: 'AQID', user: { id: 'dTE', name: 'ann' }, excludeCredentials: [{ id: 'AQ', type: 'public-key' }], rp: { id: 'x' } });
    expect(c.challenge).toBeInstanceOf(ArrayBuffer);
    expect(c.user.id).toBeInstanceOf(ArrayBuffer);
    expect(c.excludeCredentials[0].id).toBeInstanceOf(ArrayBuffer);
    const r = pk.requestOptions({ challenge: 'AQID', allowCredentials: [{ id: 'AQ', type: 'public-key' }] });
    expect(r.allowCredentials[0].id).toBeInstanceOf(ArrayBuffer);
    expect(pk.requestOptions({ challenge: 'AQID' }).allowCredentials).toBeUndefined();
  });

  it('turns an answer into JSON, with or without the browser\'s toJSON', () => {
    expect(pk.credentialJSON({ toJSON: () => ({ id: 'native' }) })).toEqual({ id: 'native' });
    const j = pk.credentialJSON({
      id: 'Aw', rawId: bytes(3), type: 'public-key',
      response: { clientDataJSON: bytes(1), authenticatorData: bytes(2), signature: bytes(4), userHandle: bytes(5), attestationObject: bytes(6) },
      getClientExtensionResults: () => ({ credProps: { rk: true } }),
    });
    expect(j).toEqual({
      id: 'Aw', rawId: 'Aw', type: 'public-key',
      response: { clientDataJSON: 'AQ', authenticatorData: 'Ag', signature: 'BA', userHandle: 'BQ', attestationObject: 'Bg' },
      clientExtensionResults: { credProps: { rk: true } },
    });
    expect(pk.credentialJSON({ id: 'A', rawId: bytes(0), type: 'public-key', response: { clientDataJSON: bytes(1) } }).clientExtensionResults).toEqual({});
  });

  it('signs in: options, the device, then the check', async () => {
    const calls = [];
    const fetchImpl = vi.fn(async (url, init) => {
      calls.push([url, JSON.parse(init.body)]);
      if (url.endsWith('/options')) return { ok: true, json: async () => ({ ticket: 't1', options: { publicKey: { challenge: 'AQID' } } }) };
      return { ok: true, json: async () => ({ status: 'ok', token: 'tok' }) };
    });
    const credentials = { get: vi.fn(async () => ({ toJSON: () => ({ id: 'cred' }) })) };
    const out = await pk.passkeySignIn({ mfaToken: 'mfa_x', rememberMe: false, fetchImpl, credentials });
    expect(out.token).toBe('tok');
    expect(calls[0]).toEqual(['/api/auth/passkey/login/options', { mfa_token: 'mfa_x', remember_me: false }]);
    expect(calls[1]).toEqual(['/api/auth/passkey/login', { ticket: 't1', credential: { id: 'cred' } }]);
    await expect(pk.passkeySignIn({ fetchImpl, credentials: { get: async () => null } })).rejects.toThrow('No passkey');
    const failing = async () => ({ ok: false, status: 400, json: async () => ({ detail: 'not an IP address' }) });
    await expect(pk.passkeySignIn({ fetchImpl: failing, credentials })).rejects.toThrow('not an IP address');
    const broken = async () => ({ ok: false, status: 500, json: async () => { throw new Error('x'); } });
    await expect(pk.passkeySignIn({ fetchImpl: broken, credentials })).rejects.toThrow('HTTP 500');
  });

  it('adds a passkey for the signed-in person', async () => {
    api.post.mockResolvedValueOnce({ ticket: 't2', options: { publicKey: { challenge: 'AQID', user: { id: 'dTE' } } } }).mockResolvedValueOnce({ added: { id: 'p1' } });
    const credentials = { create: vi.fn(async () => ({ toJSON: () => ({ id: 'new' }) })) };
    await pk.addPasskey(api, 'Phone', credentials);
    expect(api.post).toHaveBeenLastCalledWith('/api/auth/passkeys', { ticket: 't2', credential: { id: 'new' }, name: 'Phone' });
    api.post.mockResolvedValueOnce({ ticket: 't3', options: { publicKey: { challenge: 'AQID', user: { id: 'dTE' } } } });
    await expect(pk.addPasskey(api, 'x', { create: async () => null })).rejects.toThrow('No passkey');
  });
});

describe('the passkeys card', () => {
  const LIST = [{ id: 'p1', name: 'Phone', rp_id: 'attic.example.ts.net', created_at: 1762700000, last_used_at: null }];

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="users-pane-2fa"><div id="mfa-status-card"></div></div>';
  });

  it('lists, and says when this address can\'t use passkeys', () => {
    expect(passkeysHtml([], true)).toContain('No passkeys yet');
    const off = passkeysHtml(LIST, false);
    expect(off).toContain('not at an IP address');
    expect(off).toContain('disabled');
    expect(passkeysHtml(LIST, true)).toContain('Phone');
  });

  it('adds, renames and removes', async () => {
    api.get.mockResolvedValue({ passkeys: LIST });
    const win = { ...SECURE, prompt: vi.fn(() => 'Laptop') };
    await loadPasskeysCard(win);
    const card = document.getElementById('passkeys-card');
    expect(document.getElementById('mfa-status-card').nextElementSibling).toBe(card);
    const add = vi.spyOn(pk, 'addPasskey');
    api.post.mockResolvedValueOnce({ ticket: 't', options: { publicKey: { challenge: 'AQID', user: { id: 'dTE' } } } });
    Object.defineProperty(globalThis.navigator, 'credentials', { value: { create: async () => ({ toJSON: () => ({ id: 'c' }) }) }, configurable: true });
    api.post.mockResolvedValueOnce({ added: { id: 'p2' } });
    card.querySelector('[data-pk-add]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick(); await tick();
    expect(api.post).toHaveBeenCalledWith('/api/auth/passkeys', expect.objectContaining({ name: 'Laptop' }));
    expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('Passkey added'), 'success');
    add.mockRestore();
    card.querySelector('[data-pk-rename]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(api.patch).toHaveBeenCalledWith('/api/auth/passkeys/p1', { name: 'Laptop' });
    card.querySelector('[data-pk-remove]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(api.delete).toHaveBeenCalledWith('/api/auth/passkeys/p1');
  });

  it('stays quiet when the person closes the passkey window, and shows other errors', async () => {
    api.get.mockResolvedValue({ passkeys: LIST });
    const win = { ...SECURE, prompt: vi.fn(() => 'Key') };
    await loadPasskeysCard(win);
    const card = document.getElementById('passkeys-card');
    api.post.mockRejectedValueOnce(Object.assign(new Error('closed'), { name: 'NotAllowedError' }));
    card.querySelector('[data-pk-add]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(toast.showToast).not.toHaveBeenCalled();
    api.post.mockRejectedValueOnce(new Error('Passkeys need a name'));
    card.querySelector('[data-pk-add]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('Passkeys need a name', 'error');
    win.prompt = vi.fn(() => null);
    card.querySelector('[data-pk-add]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    card.querySelector('[data-pk-rename]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(api.patch).not.toHaveBeenCalled();
    api.delete.mockRejectedValueOnce(new Error('Your role requires two-step sign-in'));
    card.querySelector('[data-pk-remove]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('Your role requires two-step sign-in', 'error');
    api.get.mockRejectedValueOnce(new Error('offline'));
    await loadPasskeysCard(win);
    expect(document.getElementById('passkeys-body').textContent).toBe('offline');
  });

  it('does nothing without the two-step pane', async () => {
    document.body.innerHTML = '';
    await loadPasskeysCard(SECURE);
    expect(api.get).not.toHaveBeenCalled();
  });
});

describe('an administrator removes someone\'s passkeys', () => {
  beforeEach(() => vi.clearAllMocks());

  it('adds the button to the dialog once and removes on confirm', async () => {
    const { installPasskeyResetFor } = await import('../components/passkeys-card.js');
    document.body.innerHTML = '<div id="modal-edit-user"><form></form></div>';
    const modal = document.getElementById('modal-edit-user');
    expect(installPasskeyResetFor(null, {})).toBeNull();
    installPasskeyResetFor(modal, { id: 'u1', username: 'ann' });
    installPasskeyResetFor(modal, { id: 'u1', username: 'ann' });
    expect(modal.querySelectorAll('#passkeys-reset')).toHaveLength(1);
    api.delete.mockResolvedValueOnce({ removed: 2 });
    modal.querySelector('[data-pk-reset]').click();
    await tick();
    expect(api.delete).toHaveBeenCalledWith('/api/users/u1/passkeys');
    expect(toast.showToast).toHaveBeenCalledWith('Removed 2 passkeys of ann.', 'success');
    api.delete.mockRejectedValueOnce(new Error('That account can do more than you can.'));
    modal.querySelector('[data-pk-reset]').click();
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('That account can do more than you can.', 'error');
  });
});
