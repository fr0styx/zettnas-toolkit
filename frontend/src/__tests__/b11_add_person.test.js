import { describe, it, expect, afterEach, vi } from 'vitest';
import { grantShares, shareChoicesHtml } from '../components/share-access.js';
import { loadAddUserShares, grantChosenShares } from '../components/users.js';
import { confirmOpenShare } from '../components/chassis-visualizer.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

const access = {
  shares: [
    { name: 'Family', path: '/mnt/user/Family', users: { bob: 'read' } },
    { name: 'media', path: '/mnt/user/media', users: {}, default: 'read' },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '';
});

describe('B11: a new person gets only the folders chosen for them', () => {
  it('grantShares merges the chosen levels and skips "none"', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(access);
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    expect(await grantShares('Ann', { Family: 'write', media: 'none' })).toBe(true);
    expect(put).toHaveBeenCalledWith('/api/storage/share-access', {
      shares: { Family: { users: { bob: 'read', ann: 'write' } }, media: { users: {}, default: 'read' } },
    });
  });

  it('grantShares does nothing when no folder was chosen', async () => {
    const get = vi.spyOn(api, 'get');
    expect(await grantShares('Ann', { Family: 'none' })).toBe(false);
    expect(get).not.toHaveBeenCalled();
  });

  it('the dialog lists every share, starting at no access', async () => {
    document.body.innerHTML = '<div id="add-user-shares-wrap" hidden><div id="add-user-shares"></div></div>';
    vi.spyOn(api, 'get').mockResolvedValue(access);
    await loadAddUserShares();
    const selects = [...document.querySelectorAll('#add-user-shares select')];
    expect(selects.map((s) => [s.dataset.addUserShare, s.value])).toEqual([['Family', 'none'], ['media', 'none']]);
    expect(document.getElementById('add-user-shares-wrap').hidden).toBe(false);
  });

  it('the dialog hides the list for someone who cannot manage share access', async () => {
    document.body.innerHTML = '<div id="add-user-shares-wrap" hidden><div id="add-user-shares"></div></div>';
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    await loadAddUserShares();
    expect(document.getElementById('add-user-shares-wrap').hidden).toBe(true);
  });

  it('grantChosenShares sends what was picked and warns when it fails', async () => {
    document.body.innerHTML = `<div id="add-user-shares">${shareChoicesHtml(access.shares)}</div>`;
    document.querySelector('select[data-add-user-share="media"]').value = 'read';
    vi.spyOn(api, 'get').mockResolvedValue(access);
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    await grantChosenShares('ann');
    expect(put.mock.calls[0][1].shares.media.users).toEqual({ ann: 'read' });

    const warn = vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    put.mockRejectedValue(new Error('offline'));
    await grantChosenShares('ann');
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('offline'), 'warning');
  });
});

describe('B11: guest access and NFS for every host are confirmed', () => {
  it('a private share needs no confirmation', async () => {
    const spy = vi.spyOn(toast, 'showConfirmToast');
    expect(await confirmOpenShare(false, false)).toBe(true);
    expect(spy).not.toHaveBeenCalled();
  });

  it('cancelling stops the share from being created', async () => {
    vi.spyOn(toast, 'showConfirmToast').mockImplementation((title, msg, ok, cancel) => cancel());
    expect(await confirmOpenShare(false, true)).toBe(false);
  });

  it('names both risks when both apply', async () => {
    const spy = vi.spyOn(toast, 'showConfirmToast').mockImplementation((title, msg, ok) => ok());
    expect(await confirmOpenShare(true, true)).toBe(true);
    expect(spy.mock.calls[0][1]).toContain('without a password');
    expect(spy.mock.calls[0][1]).toContain('NFS');
  });
});
