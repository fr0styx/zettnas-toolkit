import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
const confirmed = vi.fn((title, msg, ok) => ok()); // Remove and "I saved it" ask first (NUX-11)
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: (...a) => confirmed(...a) }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { encryptedFoldersBody, renderEncryptedFolders } from '../components/encrypted-folders.js';

const INFO = {
  available: true,
  can_manage: true,
  shares: ['Family', 'Media'],
  folders: [
    { name: 'Taxes', share: 'Family', path: '/mnt/encrypted/Taxes', unlocked: false, unlock_at_start: false },
    { name: 'Photos', share: 'Family', path: '/mnt/encrypted/Photos', unlocked: true, unlock_at_start: true },
  ],
};

const flush = () => new Promise((r) => setTimeout(r, 0));
const row = (mount, name) => /** @type {HTMLElement} */ (mount.querySelector(`.ef-row[data-name="${name}"]`));
const click = (root, action) => /** @type {HTMLElement} */ (root.querySelector(`[data-ef="${action}"]`)).click();

describe('encrypted folders (FEAT-13)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('lists folders with what can be done to each', () => {
    const box = encryptedFoldersBody(INFO);
    expect(box.querySelectorAll('.ef-row').length).toBe(2);
    expect(row(box, 'Taxes').querySelector('[data-ef="unlock"]')).not.toBeNull();
    expect(row(box, 'Taxes').querySelector('[data-ef="forget"]')).not.toBeNull();
    expect(row(box, 'Photos').querySelector('[data-ef="lock"]')).not.toBeNull();
    expect(/** @type {HTMLInputElement} */ (row(box, 'Photos').querySelector('[name="keep"]')).checked).toBe(true);
    expect(box.querySelector('.ef-create select').textContent).toBe('FamilyMedia');
  });

  it('says why when it cannot, and shows less to people who only use the folders', () => {
    expect(encryptedFoldersBody({ ...INFO, available: false }).textContent).toContain("tool that encrypts them"); // plain words (NUX-11)
    const user = encryptedFoldersBody({ ...INFO, can_manage: false, shares: [] });
    expect(user.querySelector('.ef-create')).toBeNull();
    expect(user.querySelector('[name="keep"]')).toBeNull();
    expect(encryptedFoldersBody({ ...INFO, folders: [], shares: [] }).textContent).toContain('Create a share first');
    expect(encryptedFoldersBody({ ...INFO, folders: [] }).textContent).toContain('No encrypted folders yet.');
  });

  it('opens, locks, shows in Files and takes off a folder', async () => {
    api.get.mockResolvedValue(INFO);
    api.post.mockResolvedValue({});
    api.delete.mockResolvedValue({});
    const mount = document.createElement('div');
    await renderEncryptedFolders(mount);

    /** @type {HTMLInputElement} */ (row(mount, 'Taxes').querySelector('[name="password"]')).value = 'pw one two three';
    click(row(mount, 'Taxes'), 'unlock');
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/encrypted-folders/Taxes/unlock', { password: 'pw one two three' }));
    await flush();
    click(row(mount, 'Photos'), 'lock');
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/encrypted-folders/Photos/lock', {}));
    await flush();
    window.openFileManager = vi.fn();
    click(row(mount, 'Photos'), 'files');
    expect(window.openFileManager).toHaveBeenCalledWith('/mnt/encrypted/Photos');
    click(row(mount, 'Taxes'), 'forget');
    await vi.waitFor(() => expect(api.delete).toHaveBeenCalledWith('/api/encrypted-folders/Taxes'));
    expect(confirmed.mock.calls.at(-1)[0]).toBe('Remove Taxes from the list');
  });

  it('makes a folder and shows its recovery key once', async () => {
    api.get.mockResolvedValue(INFO);
    api.post.mockResolvedValue({ name: 'New', recovery_key: 'aaaa-bbbb' });
    const mount = document.createElement('div');
    document.body.append(mount); // so focus can move to the key
    await renderEncryptedFolders(mount);
    const form = mount.querySelector('.ef-create');
    const set = (n, v) => {
      /** @type {HTMLInputElement} */ (form.querySelector(`[name="${n}"]`)).value = v;
    };
    set('name', ' New ');
    set('new', 'one long passphrase');
    set('again', 'not the same');
    click(form, 'create');
    expect(api.post).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith('The two passwords are not the same.', 'error');

    set('again', 'one long passphrase');
    /** @type {HTMLInputElement} */ (form.querySelector('[name="start"]')).checked = true;
    click(form, 'create');
    await vi.waitFor(() => expect(mount.querySelector('.ef-key').textContent).toBe('aaaa-bbbb'));
    expect(api.post).toHaveBeenCalledWith('/api/encrypted-folders', { share: 'Family', name: 'New', password: 'one long passphrase', unlock_at_start: true });
    expect(document.activeElement).toBe(mount.querySelector('.ef-key')); // focus on the key
    const leave = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(true); // leaving asks first
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    click(mount, 'copy');
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('aaaa-bbbb');
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining('copied'), 'success'));
    click(mount, 'saved');
    expect(confirmed.mock.calls.at(-1)[0]).toBe('Is the recovery key saved?');
    await vi.waitFor(() => expect(mount.querySelector('.ef-row')).not.toBeNull());
    const later = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(later);
    expect(later.defaultPrevented).toBe(false); // saved: leaving is free again
  });

  it('adds one back, and keeps a password only after it is typed', async () => {
    api.get.mockResolvedValue(INFO);
    api.post.mockResolvedValue({});
    api.put.mockResolvedValue({});
    const mount = document.createElement('div');
    await renderEncryptedFolders(mount);
    const form = mount.querySelector('.ef-adopt'); // its own fields (NUX-11)
    /** @type {HTMLInputElement} */ (form.querySelector('[name="name"]')).value = 'Old';
    /** @type {HTMLInputElement} */ (form.querySelector('[name="password"]')).value = 'its password here';
    click(mount, 'adopt');
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/encrypted-folders/adopt', { share: 'Family', name: 'Old', password: 'its password here' }));
    await flush();

    const keep = /** @type {HTMLInputElement} */ (row(mount, 'Taxes').querySelector('[name="keep"]'));
    keep.checked = true;
    keep.dispatchEvent(new Event('change', { bubbles: true }));
    await flush();
    expect(api.put).not.toHaveBeenCalled();
    expect(keep.checked).toBe(false);
    /** @type {HTMLInputElement} */ (row(mount, 'Taxes').querySelector('[name="password"]')).value = 'pw one two three';
    keep.checked = true;
    keep.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/encrypted-folders/Taxes/unlock-at-start', { password: 'pw one two three' }));
    await flush();
    const off = /** @type {HTMLInputElement} */ (row(mount, 'Photos').querySelector('[name="keep"]'));
    off.checked = false;
    off.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/encrypted-folders/Photos/unlock-at-start', { password: null }));
  });

  it('shows errors', async () => {
    api.get.mockResolvedValueOnce(INFO);
    api.post.mockRejectedValue(new Error('That password is wrong.'));
    const mount = document.createElement('div');
    await renderEncryptedFolders(mount);
    click(row(mount, 'Taxes'), 'unlock');
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('That password is wrong.', 'error'));
    api.get.mockRejectedValueOnce(new Error('forbidden'));
    await renderEncryptedFolders(mount);
    expect(mount.textContent).toContain("forbidden"); // with a sentence and Retry (NUX-14)
    expect(mount.querySelector(".zn-load-error button")).not.toBeNull();
    await renderEncryptedFolders(null);
  });

  it('unlocks with Enter in a labelled field, and names the state and the button apart', async () => {
    api.get.mockResolvedValue(INFO);
    api.post.mockResolvedValue({});
    const mount = document.createElement('div');
    await renderEncryptedFolders(mount);
    const taxes = row(mount, 'Taxes');
    expect(taxes.querySelector('.ef-state').textContent).toBe('Locked');
    expect(row(mount, 'Photos').querySelector('.ef-state').textContent).toBe('Unlocked');
    expect(taxes.querySelector('[data-ef="unlock"]').textContent).toBe('Unlock');
    expect(taxes.querySelector('label.ef-field').textContent).toContain('Password');
    /** @type {HTMLInputElement} */ (taxes.querySelector('[name="password"]')).value = 'pw one two three';
    taxes.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/encrypted-folders/Taxes/unlock', { password: 'pw one two three' }));
  });

  it('copy failures say what to do instead', async () => {
    api.get.mockResolvedValue(INFO);
    api.post.mockResolvedValue({ name: 'New', recovery_key: 'cccc-dddd' });
    const mount = document.createElement('div');
    await renderEncryptedFolders(mount);
    const form = mount.querySelector('.ef-create');
    for (const [n, v] of [['name', 'Fotos Großeltern'], ['new', 'one long passphrase'], ['again', 'one long passphrase']]) {
      /** @type {HTMLInputElement} */ (form.querySelector(`[name="${n}"]`)).value = v;
    }
    click(form, 'create');
    await vi.waitFor(() => expect(mount.querySelector('.ef-key')).not.toBeNull());
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    click(mount, 'copy');
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining('download it as a file'), 'error'));
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
    click(mount, 'download');
    expect(URL.createObjectURL).toHaveBeenCalled();
  });
});
