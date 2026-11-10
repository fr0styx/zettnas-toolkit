import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/remote-access.js', () => ({ qrSvg: vi.fn(async () => '<svg id="qr"></svg>') }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { familyAccessHtml, inviteMessage, loadFamilyAccessCard } = await import('../components/management/family-access.js');

const tick = () => new Promise((r) => setTimeout(r, 0));
// a made-up key, built in pieces so secret scanning doesn't take it for a real one
const FAKE_KEY = ['tskey', 'api', 'k', 'secret'].join('-');
const USERS = [
  { id: 'u1', username: 'gran', display_name: 'Gran', status: 'active' },
  { id: 'u2', username: 'kid', display_name: '', status: 'active' },
  { id: 'u3', username: 'gone', status: 'disabled' },
];
const BASE = { tailscale: true, headscale: false, has_key: true, key_days_left: 60, key_expiring: false, keys_page: 'https://login.tailscale.com/admin/settings/keys', public_page: true, people: [] };
const INVITED = { user_id: 'u1', username: 'gran', name: 'Gran', state: 'invited', login: '', page_url: 'https://a.ts.net:8443/api/fs/shared/join/tok', invite_url: 'https://login.tailscale.com/admin/invite/c1' };

describe('family from anywhere (NFEAT-1)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="network-services-grid"></div>';
  });

  it('says what it needs, asks for the key once and lists the active users', () => {
    expect(familyAccessHtml({ ...BASE, tailscale: false }, USERS)).toContain('Needs Tailscale');
    expect(familyAccessHtml({ ...BASE, headscale: true }, USERS)).toContain('Headscale');
    const noKey = familyAccessHtml({ ...BASE, has_key: false }, USERS);
    expect(noKey).toContain('tskey-api-');
    expect(noKey).toContain('admin/settings/keys');
    expect(noKey).not.toContain('data-fa-invite'); // no invites without a key
    const html = familyAccessHtml(BASE, USERS);
    expect(html).toContain('runs out in 60 days');
    expect(html).toContain('data-fa-invite="u1"');
    expect(html).toContain('<strong>kid</strong>');
    expect(html).not.toContain('gone');
    expect(familyAccessHtml({ ...BASE, key_days_left: 5, key_expiring: true }, USERS)).toContain('Make a new one');
    expect(familyAccessHtml({ ...BASE, public_page: false }, USERS)).toContain('Share links from anywhere');
  });

  it('shows each state and builds the message', () => {
    const invited = familyAccessHtml({ ...BASE, people: [INVITED] }, USERS);
    expect(invited).toContain('Invited, not joined yet');
    expect(invited).toContain('data-fa-copy="u1"');
    const online = familyAccessHtml({ ...BASE, people: [{ ...INVITED, state: 'online', login: 'gran@example.com', page_url: '', invite_url: '' }] }, USERS);
    expect(online).toContain('online now');
    expect(online).toContain('gran@example.com');
    expect(online).toContain('Remove access');
    expect(familyAccessHtml({ ...BASE, people: [{ ...INVITED, state: 'expired' }] }, USERS)).toContain('Invite expired');
    expect(inviteMessage(INVITED)).toContain('/join/tok');
    const plain = inviteMessage({ ...INVITED, page_url: '' });
    expect(plain).toContain('install the Tailscale app');
    expect(plain).toContain('admin/invite/c1');
  });

  it('saves the key, invites, copies, shows the QR code and removes', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/users' ? { users: USERS } : { ...BASE, has_key: false }));
    await loadFamilyAccessCard();
    const card = document.getElementById('fa-card');
    expect(card).toBeTruthy();
    api.put.mockResolvedValue(BASE);
    const form = /** @type {HTMLFormElement} */ (card.querySelector('[data-fa-key]'));
    /** @type {HTMLInputElement} */ (form.elements.namedItem('key')).value = ` ${FAKE_KEY} `;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    expect(api.put).toHaveBeenCalledWith('/api/network/family-access/key', { key: FAKE_KEY });

    api.post.mockResolvedValue({ ...BASE, people: [INVITED] });
    /** @type {HTMLElement} */ (card.querySelector('[data-fa-invite="u1"]')).click();
    await tick();
    expect(api.post).toHaveBeenCalledWith('/api/network/family-access/invites', { user_id: 'u1' });

    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    /** @type {HTMLElement} */ (card.querySelector('[data-fa-copy="u1"]')).click();
    await tick();
    expect(writeText.mock.calls[0][0]).toContain('/join/tok');
    expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('Copied'), 'success');

    /** @type {HTMLElement} */ (card.querySelector('[data-fa-qr="u1"]')).click();
    await tick();
    await tick();
    const box = /** @type {HTMLElement} */ (card.querySelector('[data-fa-qrbox="u1"]'));
    expect(box.hidden).toBe(false);
    expect(box.innerHTML).toContain('qr');

    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    api.delete.mockResolvedValue({ ...BASE, remove_share_at: 'https://login.tailscale.com/admin/machines' });
    /** @type {HTMLElement} */ (card.querySelector('[data-fa-revoke="u1"]')).click();
    await tick();
    expect(api.delete).toHaveBeenCalledWith('/api/network/family-access/invites/u1');
    expect(open).toHaveBeenCalledWith('https://login.tailscale.com/admin/machines', '_blank', 'noopener');
  });

  it('keeps quiet on a confirmation and shows other errors', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/users' ? { users: USERS } : BASE));
    await loadFamilyAccessCard();
    const card = document.getElementById('fa-card');
    api.post.mockRejectedValueOnce(Object.assign(new Error('confirm'), { status: 428 }));
    /** @type {HTMLElement} */ (card.querySelector('[data-fa-invite="u1"]')).click();
    await tick();
    expect(toast.showToast).not.toHaveBeenCalled();
    api.post.mockRejectedValueOnce(Object.assign(new Error('Tailscale said no'), { status: 400 }));
    /** @type {HTMLElement} */ (card.querySelector('[data-fa-invite="u1"]')).click();
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('Tailscale said no', 'error');
    api.get.mockRejectedValue(new Error('offline'));
    await loadFamilyAccessCard();
    expect(document.getElementById('fa-body').textContent).toBe('offline');
  });
});
