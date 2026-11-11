import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), delete: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showDangerConfirm: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyTextToClipboard: vi.fn() }));

const { api } = await import('../api.js');
const { showToast, showDangerConfirm } = await import('../toast.js');
const { copyTextToClipboard } = await import('../utils.js');
const { renderSharedLinks, openSharedLinks, linkState } = await import('../components/shared-links.js');

const flush = () => new Promise((r) => setTimeout(r, 0));
const LINKS = [
  { token: 'aaa', label: 'Holiday photos', url: '/api/fs/shared/aaa', public_url: null, created_by: 'anna', expires_at: 1900000000, has_password: true, download_count: 3, is_active: true },
  { token: 'bbb', filename: 'inbox', url: '/api/fs/shared/bbb', public_url: 'https://nas.example/s/bbb', created_by: 'ben', expires_at: null, has_password: true, kind: 'upload', received_count: 2, is_active: true },
  { token: 'ccc', filename: 'old.pdf', url: '/api/fs/shared/ccc', created_by: 'anna', expires_at: 1, has_password: false, download_count: 0, is_expired: true, is_active: false },
];

describe('Links I shared (SET-01)', () => {
  let mount;
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<button id="opener">open</button><div id="mount"></div>';
    mount = document.getElementById('mount');
  });

  it('says in words whether a link still works', () => {
    expect(linkState({ is_expired: true })).toBe('Ended');
    expect(linkState({ limit_reached: true })).toBe('All downloads used');
    expect(linkState({ expires_at: null })).toBe('Never ends');
    expect(linkState({ expires_at: 1900000000 })).toMatch(/^Works until /);
  });

  it('lists each link with what it is, how long it works and who made it', async () => {
    api.get.mockResolvedValue(LINKS);
    await renderSharedLinks(mount, { me: 'anna' });
    expect(api.get).toHaveBeenCalledWith('/api/fs/share-links');
    const rows = [...mount.querySelectorAll('.shared-link')];
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain('Holiday photos');
    expect(rows[0].textContent).toContain('Password');
    expect(rows[0].textContent).toContain('Downloads: 3');
    expect(rows[0].textContent).not.toContain('Made by'); // their own
    expect(rows[1].textContent).toContain('Send me files');
    expect(rows[1].textContent).toContain('Never ends');
    expect(rows[1].textContent).toContain('Files received: 2');
    expect(rows[1].textContent).toContain('Made by ben');
    expect(rows[2].classList.contains('is-ended')).toBe(true);
    expect(rows[2].textContent).toContain('No password');
    expect(rows[2].querySelector('[data-link-copy]')).toBeNull(); // nothing to copy once it ended
    expect(rows[2].querySelector('[data-link-stop]')).not.toBeNull();
  });

  it('copies the address that works from outside when there is one', async () => {
    api.get.mockResolvedValue(LINKS);
    await renderSharedLinks(mount);
    mount.querySelectorAll('[data-link-copy]')[1].click();
    expect(copyTextToClipboard).toHaveBeenCalledWith('https://nas.example/s/bbb');
    mount.querySelectorAll('[data-link-copy]')[0].click();
    expect(copyTextToClipboard).toHaveBeenLastCalledWith(`${window.location.origin}/api/fs/shared/aaa`);
  });

  it('asks before stopping a link, then stops it and draws the list again', async () => {
    api.get.mockResolvedValue(LINKS);
    api.delete.mockResolvedValue({ status: 'ok' });
    await renderSharedLinks(mount);
    mount.querySelector('[data-link-stop]').click();
    expect(api.delete).not.toHaveBeenCalled();
    const [title, question, onOk] = showDangerConfirm.mock.calls[0];
    expect(title).toBe('Stop sharing');
    expect(question).toContain('Holiday photos');
    expect(question).toContain('The file stays where it is');
    api.get.mockResolvedValue(LINKS.slice(1));
    await onOk();
    await flush();
    expect(api.delete).toHaveBeenCalledWith('/api/fs/share-links/aaa');
    expect(showToast).toHaveBeenCalledWith('The link no longer works.', 'success');
    expect(mount.querySelectorAll('.shared-link')).toHaveLength(2);
  });

  it('tells when a stop failed', async () => {
    api.get.mockResolvedValue(LINKS);
    api.delete.mockRejectedValue(new Error('not allowed'));
    await renderSharedLinks(mount);
    mount.querySelector('[data-link-stop]').click();
    await showDangerConfirm.mock.calls[0][2]();
    expect(showToast).toHaveBeenCalledWith('not allowed', 'error');
  });

  it('has an empty state, and an error state with a way to try again', async () => {
    api.get.mockResolvedValue([]);
    await renderSharedLinks(mount);
    expect(mount.textContent).toContain('No shared links.');
    api.get.mockRejectedValue(new Error('offline'));
    await renderSharedLinks(mount);
    expect(mount.textContent).toContain('The links could not be loaded.');
    api.get.mockResolvedValue(LINKS);
    mount.querySelector('#shared-links-retry').click();
    await flush();
    expect(mount.querySelectorAll('.shared-link')).toHaveLength(3);
  });

  it('opens as a dialog that takes focus, closes on Escape and gives focus back', async () => {
    api.get.mockResolvedValue(LINKS);
    const opener = document.getElementById('opener');
    opener.focus();
    await openSharedLinks({ everyone: true });
    const dialog = document.querySelector('#shared-links-modal [role=dialog]');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.getElementById('shared-links-title').textContent).toContain('Links shared from this NAS');
    expect(document.activeElement.id).toBe('shared-links-close');
    expect(dialog.querySelectorAll('.shared-link')).toHaveLength(3);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.getElementById('shared-links-modal')).toBeNull();
    expect(document.activeElement).toBe(opener);
    await openSharedLinks();
    expect(document.getElementById('shared-links-title').textContent).toContain('Links I shared');
    document.getElementById('shared-links-close').click();
    expect(document.getElementById('shared-links-modal')).toBeNull();
  });
});
