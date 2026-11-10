import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { familySigninHtml, connectedHtml, renderFamilySignin } = await import('../components/family-signin.js');

const tick = () => new Promise((r) => setTimeout(r, 0));
const USERS = [
  { id: 'u1', username: 'gran', display_name: 'Gran', status: 'active' },
  { id: 'u3', username: 'old', status: 'disabled' },
];
const OFF = { enabled: false, running: false, url: '', https_ready: true, people: 0, apps: [] };
const ON = {
  enabled: true, running: true, url: 'https://attic.x.ts.net:11411', https_ready: true, people: 2,
  apps: [{ key: 'immich', name: 'Immich', connected: false, url: 'https://attic.x.ts.net:8443/' }, { key: 'nextcloud', name: 'Nextcloud', connected: true, url: '' }],
};
const CONNECTED = { app: 'immich', name: 'Immich', issuer: 'https://attic.x.ts.net:11411', client_id: 'c1', client_secret: 'sek', where: 'Immich → Administration' };

describe('family sign-in (NFEAT-6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="m"></div>';
  });

  it('asks for https first, then shows people and apps', () => {
    const noHttps = familySigninHtml({ ...OFF, https_ready: false }, USERS);
    expect(noHttps).toContain('Passkeys need https');
    expect(noHttps).toContain('disabled');
    expect(familySigninHtml(OFF, USERS)).toContain('Turn on family sign-in');
    const on = familySigninHtml(ON, USERS);
    expect(on).toContain('2 people');
    expect(on).toContain('Open Pocket ID');
    expect(on).toContain('data-fs-link="u1"');
    expect(on).not.toContain('data-fs-link="u3"');
    expect(on).toContain('data-fs-connect="immich"');
    expect(on).toContain('data-fs-disconnect="nextcloud"');
    expect(familySigninHtml({ ...ON, running: false, apps: [] }, USERS)).toContain('None of the apps');
    const r = connectedHtml(CONNECTED);
    expect(r).toContain('sek');
    expect(r).toContain('shown only now');
  });

  it('turns on, sends a link, connects an app and turns off', async () => {
    const m = /** @type {HTMLElement} */ (document.getElementById('m'));
    api.get.mockImplementation(async (url) => (url === '/api/users' ? { users: USERS } : OFF));
    await renderFamilySignin(m);
    api.put.mockResolvedValueOnce(ON);
    /** @type {HTMLElement} */ (m.querySelector('[data-fs="on"]')).click();
    await tick();
    expect(api.put).toHaveBeenCalledWith('/api/family-signin', { enabled: true });
    expect(m.textContent).toContain('People');

    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    api.post.mockResolvedValueOnce({ url: 'https://attic.x.ts.net:11411/lc/Tok' });
    /** @type {HTMLElement} */ (m.querySelector('[data-fs-link="u1"]')).click();
    await tick();
    await tick();
    expect(writeText).toHaveBeenCalledWith('https://attic.x.ts.net:11411/lc/Tok');

    api.post.mockResolvedValueOnce(CONNECTED);
    api.get.mockImplementation(async () => ON);
    /** @type {HTMLElement} */ (m.querySelector('[data-fs-connect="immich"]')).click();
    await tick();
    await tick();
    expect(api.post).toHaveBeenLastCalledWith('/api/family-signin/apps/immich', {});
    expect(m.querySelector('[data-fs-result]').textContent).toContain('c1');

    api.delete.mockResolvedValueOnce(ON);
    /** @type {HTMLElement} */ (m.querySelector('[data-fs-disconnect="nextcloud"]')).click();
    await tick();
    expect(api.delete).toHaveBeenCalledWith('/api/family-signin/apps/nextcloud');
    api.post.mockResolvedValueOnce(ON);
    /** @type {HTMLElement} */ (m.querySelector('[data-fs="sync"]')).click();
    await tick();
    expect(api.post).toHaveBeenLastCalledWith('/api/family-signin/sync', {});
    api.put.mockResolvedValueOnce(OFF);
    /** @type {HTMLElement} */ (m.querySelector('[data-fs="off"]')).click();
    await tick();
    expect(api.put).toHaveBeenLastCalledWith('/api/family-signin', { enabled: false });
  });

  it('stays quiet on a confirmation and reports errors', async () => {
    const m = /** @type {HTMLElement} */ (document.getElementById('m'));
    api.get.mockImplementation(async (url) => (url === '/api/users' ? { users: USERS } : ON));
    await renderFamilySignin(m);
    api.post.mockRejectedValueOnce(Object.assign(new Error('confirm'), { status: 428 }));
    /** @type {HTMLElement} */ (m.querySelector('[data-fs-connect="immich"]')).click();
    await tick();
    expect(toast.showToast).not.toHaveBeenCalled();
    api.post.mockRejectedValueOnce(new Error('Pocket ID isn\'t answering yet'));
    /** @type {HTMLElement} */ (m.querySelector('[data-fs-link="u1"]')).click();
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith("Pocket ID isn't answering yet", 'error');
    api.get.mockRejectedValue(new Error('offline'));
    await renderFamilySignin(m);
    expect(m.textContent).toBe('offline');
  });
});
