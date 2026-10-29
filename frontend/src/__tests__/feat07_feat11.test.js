import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));

import { api } from '../api.js';
import { showConfirmToast, showToast } from '../toast.js';
import { offersFor, handlePendingUsb, resetUsbOffer } from '../components/usb-offer.js';
import { nutServerBody, renderNutServer } from '../components/nut-server.js';

describe('USB disk offers (FEAT-07)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetUsbOffer();
  });

  it('offers a backup first, then the photo import', () => {
    expect(offersFor(null)).toEqual([]);
    expect(offersFor({ path: '/mnt/disks/a', backups: [{ id: 'b' }], media: true })).toEqual(['backup', 'import']);
    expect(offersFor({ path: '/mnt/disks/a', backups: [], media: true })).toEqual(['import']);
    expect(offersFor({ path: '/mnt/disks/a', backups: [] })).toEqual([]);
  });

  it('asks once per plug-in and runs what was chosen', async () => {
    api.post.mockResolvedValue({});
    const disk = { path: '/mnt/disks/cam', name: 'cam', backups: [{ id: 'n', name: 'Nightly' }], media: true, ts: 5 };
    handlePendingUsb(disk);
    handlePendingUsb(disk);
    expect(showConfirmToast).toHaveBeenCalledTimes(1);
    const [title, msg, onOk] = showConfirmToast.mock.calls[0];
    expect(title).toContain('Back up');
    expect(msg).toContain('Nightly');
    await onOk();
    expect(api.post).toHaveBeenCalledWith('/api/usb/backup', { path: '/mnt/disks/cam' });
    expect(showConfirmToast).toHaveBeenCalledTimes(2); // then the photo import
    const [, , onImport, onDismiss] = showConfirmToast.mock.calls[1];
    await onImport();
    expect(api.post).toHaveBeenCalledWith('/api/usb/import', { path: '/mnt/disks/cam' });
    await onDismiss();
    expect(api.post).toHaveBeenCalledWith('/api/usb/dismiss');
  });

  it('shows an error when starting fails', async () => {
    api.post.mockRejectedValue(new Error('No backup goes to this disk yet.'));
    handlePendingUsb({ path: '/mnt/disks/x', name: 'x', backups: [{ id: 'a' }], ts: 9 });
    await showConfirmToast.mock.calls[0][2]();
    expect(showToast).toHaveBeenCalledWith('No backup goes to this disk yet.', 'error');
  });
});

describe('the NUT server panel (FEAT-11)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows the state', () => {
    const on = nutServerBody({ enabled: true, running: true, logins: 2, port: 3493, user: 'monuser' });
    expect(on.textContent).toContain('2 computers watching');
    expect(nutServerBody({ enabled: true, running: false }).textContent).toContain('not running');
    expect(nutServerBody({ enabled: false }).textContent).toContain('Off');
  });

  it('saves, renews and shows the PC setup', async () => {
    api.get.mockImplementation((url) => Promise.resolve(url.endsWith('/client') ? { upsmon: 'MONITOR ups@NAS-ADDRESS:3493 1 monuser pw secondary' } : { enabled: false, port: 3493, user: 'monuser' }));
    api.put.mockResolvedValue({});
    const mount = document.createElement('div');
    await renderNutServer(mount);
    /** @type {HTMLInputElement} */ (mount.querySelector('[name="enabled"]')).checked = true;
    mount.querySelector('[data-nut="save"]').click();
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/ups/nut-server', { enabled: true, port: 3493, user: 'monuser' }));
    mount.querySelector('[data-nut="renew"]').click();
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/ups/nut-server', { new_password: true }));
    await vi.waitFor(() => expect(mount.querySelector('[data-nut="client"]')).not.toBeNull());
    mount.querySelector('[data-nut="client"]').click();
    await vi.waitFor(() => expect(mount.querySelector('.nut-server-client').textContent).toContain('MONITOR ups@NAS-ADDRESS'));
  });

  it('shows a load error', async () => {
    api.get.mockRejectedValue(new Error('forbidden'));
    const mount = document.createElement('div');
    await renderNutServer(mount);
    expect(mount.textContent).toBe('forbidden');
  });
});
