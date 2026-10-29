import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
const { api } = await import('../api.js');
const { isRestLocation, restSignIn, reposHtml, renderOffsite } = await import('../components/offsite-backup.js');

const form = (values) => {
  const f = new FormData();
  for (const [k, v] of Object.entries(values)) f.append(k, v);
  return f;
};

describe('FEAT-08: back up to a restic REST server', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('sends the sign-in only for a rest: destination', () => {
    expect(isRestLocation(' rest:http://friend:8000/backup/')).toBe(true);
    expect(isRestLocation('rclone:b2:x')).toBe(false);
    expect(restSignIn(form({ location: 'rest:http://friend:8000/backup/', rest_user: ' backup ', rest_password: 'pw' }))).toEqual({
      rest_user: 'backup',
      rest_password: 'pw',
    });
    expect(restSignIn(form({ location: '/mnt/disks/usb', rest_user: 'backup', rest_password: 'pw' }))).toEqual({});
  });

  it('says when the server keeps every version', () => {
    const repo = { id: 'f', name: 'Friend', location: 'rest:http://friend:8000/backup/', paths: ['/mnt/user/a'], keep: { daily: 7, weekly: 4, monthly: 12 }, append_only: true };
    document.body.innerHTML = reposHtml({ available: true, repos: [repo] });
    expect(document.body.textContent).toContain('append-only');
  });

  it('shows the user and password fields once the address is a REST server, and sends them', async () => {
    api.get.mockImplementation((url) => Promise.resolve(url === '/api/offsite' ? { available: true, repos: [] } : { shares: [{ name: 'a', mountpoint: '/mnt/user/a' }] }));
    api.put.mockResolvedValue({});
    api.post.mockResolvedValue({});
    const mount = document.createElement('div');
    document.body.appendChild(mount);
    await renderOffsite(mount);
    const box = /** @type {HTMLElement} */ (mount.querySelector('[data-off-rest]'));
    expect(box.hidden).toBe(true);
    const loc = /** @type {HTMLInputElement} */ (mount.querySelector('[name="location"]'));
    loc.value = 'rest:http://friend:8000/backup/';
    loc.dispatchEvent(new Event('input', { bubbles: true }));
    expect(box.hidden).toBe(false);
    /** @type {HTMLInputElement} */ (mount.querySelector('[name="name"]')).value = 'Friend';
    /** @type {HTMLInputElement} */ (mount.querySelector('[name="rest_user"]')).value = 'backup';
    /** @type {HTMLInputElement} */ (mount.querySelector('[name="rest_password"]')).value = 'pw';
    mount.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(api.put).toHaveBeenCalled());
    expect(api.put.mock.calls[0][1]).toMatchObject({ location: 'rest:http://friend:8000/backup/', rest_user: 'backup', rest_password: 'pw' });
    loc.value = '/mnt/disks/usb';
    loc.dispatchEvent(new Event('input', { bubbles: true }));
    expect(box.hidden).toBe(true);
  });
});
