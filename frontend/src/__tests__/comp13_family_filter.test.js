import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { splitDevices, familyFilterBody, renderFamilyFilter } from '../components/family-filter.js';

const INFO = {
  url: 'http://adguardhome:3000',
  user: 'admin',
  has_password: true,
  people: { mia: { devices: ['192.168.1.20'], blocked: ['tiktok'] } },
  accounts: [{ username: 'mia', display_name: 'Mia' }, { username: 'leo', display_name: 'Leo' }],
  services: ['tiktok', 'youtube'],
};

describe('filter for the kids\' devices (COMP-13)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('splits a device list', () => {
    expect(splitDevices(' 192.168.1.20, aa:bb:cc:dd:ee:ff;\n tablet ')).toEqual(['192.168.1.20', 'aa:bb:cc:dd:ee:ff', 'tablet']);
    expect(splitDevices('')).toEqual([]);
  });

  it('shows the connection without the password and one row per account', () => {
    const box = familyFilterBody(INFO);
    expect(/** @type {HTMLInputElement} */ (box.querySelector('[name="password"]')).value).toBe('');
    expect(/** @type {HTMLInputElement} */ (box.querySelector('[name="password"]')).placeholder).toContain('saved');
    const rows = box.querySelectorAll('.ff-person');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('1 device filtered');
    expect(rows[1].textContent).toContain('Not filtered');
    expect(familyFilterBody({ ...INFO, accounts: [] }).textContent).toContain('No family or guest accounts yet.');
  });

  it('saves the connection, a person and checks AdGuard Home', async () => {
    api.get.mockResolvedValue(INFO);
    api.put.mockResolvedValue({});
    api.post.mockResolvedValue({ ok: true, version: 'v0.107.60' });
    const mount = document.createElement('div');
    await renderFamilyFilter(mount);

    /** @type {HTMLElement} */ (mount.querySelector('[data-ff="check"]')).click();
    await vi.waitFor(() => expect(mount.querySelector('.ff-check').textContent).toBe('AdGuard Home v0.107.60 answers.'));

    /** @type {HTMLElement} */ (mount.querySelector('[data-ff="connect"]')).click();
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/family-filter/connection', { url: 'http://adguardhome:3000', user: 'admin' }));

    const leo = /** @type {HTMLElement} */ (mount.querySelectorAll('.ff-person')[1]);
    /** @type {HTMLInputElement} */ (leo.querySelector('[name="devices"]')).value = '192.168.1.30';
    /** @type {HTMLInputElement} */ (leo.querySelector('input[value="youtube"]')).checked = true;
    /** @type {HTMLElement} */ (leo.querySelector('[data-ff="person"]')).click();
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/family-filter/people/leo', { devices: ['192.168.1.30'], blocked: ['youtube'] }));
    expect(showToast).toHaveBeenCalledWith('Their devices are filtered now.', 'success');
  });

  it('shows errors', async () => {
    api.get.mockResolvedValueOnce(INFO);
    api.put.mockRejectedValue(new Error('AdGuard Home refused the user name or password.'));
    const mount = document.createElement('div');
    await renderFamilyFilter(mount);
    const mia = /** @type {HTMLElement} */ (mount.querySelector('.ff-person'));
    /** @type {HTMLInputElement} */ (mia.querySelector('[name="devices"]')).value = '';
    /** @type {HTMLElement} */ (mia.querySelector('[data-ff="person"]')).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('AdGuard Home refused the user name or password.', 'error'));
    api.get.mockRejectedValueOnce(new Error('forbidden'));
    await renderFamilyFilter(mount);
    expect(mount.textContent).toContain("forbidden"); // with a sentence and Retry (NUX-14)
    expect(mount.querySelector(".zn-load-error button")).not.toBeNull();
    await renderFamilyFilter(null);
  });
});
