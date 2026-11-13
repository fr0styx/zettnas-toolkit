import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
const post = vi.fn();
vi.mock('../api.js', () => ({ api: { get, post, delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

const inv = await import('../components/invites-admin.js');
const SHARES = [{ name: 'family' }, { name: 'media' }];

describe('an invite carries folders and sign-in hours (SET-19, Users decision 11)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="m"></div>';
  });

  it('one choice per folder, No access first; the box is hidden without folders', () => {
    document.body.innerHTML = inv.invitesHtml([], SHARES);
    const sels = document.querySelectorAll('[data-share]');
    expect([...sels].map((s) => /** @type {HTMLSelectElement} */ (s).value)).toEqual(['', '']);
    expect(document.querySelector('.invite-shares')?.hasAttribute('hidden')).toBe(false);
    document.body.innerHTML = inv.invitesHtml([]);
    expect(document.querySelector('.invite-shares')?.hasAttribute('hidden')).toBe(true);
  });

  it('reads only the folders given access, and hours only when on', () => {
    document.body.innerHTML = `<form>${inv.inviteSharesHtml(SHARES)}</form>`;
    /** @type {HTMLSelectElement} */ (document.querySelector('[data-share="media"]')).value = 'read';
    expect(inv.readInviteShares(document.querySelector('form'))).toEqual({ media: 'read' });
    expect(inv.hoursOrNull({})).toBeNull();
    expect(inv.hoursOrNull(null)).toBeNull();
    expect(inv.hoursOrNull({ days: [0], start: '07:00', end: '20:00' })).toEqual({ days: [0], start: '07:00', end: '20:00' });
  });

  it('a row says what comes with the role', () => {
    expect(inv.inviteExtrasText({ shares: { family: 'write', media: 'read' }, signin_hours: { days: [0] } })).toBe('2 folders · with sign-in hours');
    expect(inv.inviteExtrasText({ shares: {} })).toBe('');
    const html = inv.invitesHtml([{ id: 'a', role_id: 'kid', note: 'Mia', uses: 0, max_uses: 1, expires_at: 2e9, active: true, shares: { family: 'read' } }]);
    expect(html).toContain('1 folder');
  });

  it('creating an invite sends the folders and the hours', async () => {
    get.mockImplementation((url) => Promise.resolve(url === '/api/storage/share-access' ? { shares: SHARES } : { invites: [] }));
    post.mockResolvedValue({ link: '/#/invite/abc' });
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    await inv.renderInvites(mount);
    /** @type {HTMLSelectElement} */ (mount.querySelector('[data-share="family"]')).value = 'write';
    const on = /** @type {HTMLInputElement} */ (mount.querySelector('[data-hours-on]'));
    on.checked = true;
    on.dispatchEvent(new Event('change'));
    mount.querySelector('form')?.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(post).toHaveBeenCalled());
    const body = post.mock.calls[0][1];
    expect(body.shares).toEqual({ family: 'write' });
    expect(body.signin_hours?.days?.length).toBeGreaterThan(0);
  });

  it('without the right to manage folders, the form has none and still works', async () => {
    get.mockImplementation((url) => (url === '/api/storage/share-access' ? Promise.reject(new Error('403')) : Promise.resolve({ invites: [] })));
    post.mockResolvedValue({ link: '/#/invite/abc' });
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    await inv.renderInvites(mount);
    expect(mount.querySelector('.invite-shares')?.hasAttribute('hidden')).toBe(true);
    mount.querySelector('form')?.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1].shares).toEqual({});
    expect(post.mock.calls[0][1].signin_hours).toBeNull();
  });
});
