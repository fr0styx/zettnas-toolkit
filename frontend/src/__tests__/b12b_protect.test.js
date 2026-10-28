import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
vi.mock('../components/offsite-backup.js', () => ({ offerRecoveryKit: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const offsite = await import('../components/offsite-backup.js');
const guide = await import('../components/protect-nas.js');
const ov = await import('../components/management/overview.js');

const DEST = { usb: ['/mnt/disks/usb1'], nas: [], cloud: ['b2'] };
const SHARES = { shares: [{ name: 'Photos', mountpoint: '/mnt/user/photos' }, { name: 'Docs', mountpoint: '/mnt/user/docs' }, { name: 'nowhere' }] };

describe('B12b (FEAT-01): Protect this NAS', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('puts the backup in its own folder of the chosen place', () => {
    expect(guide.locationFor('cloud', 'b2')).toBe('rclone:b2:zettnas-backup');
    expect(guide.locationFor('usb', '/mnt/disks/usb1/')).toBe('/mnt/disks/usb1/zettnas-backup');
  });

  it('offers what is there, says what is missing, and protects every share by default', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/offsite/destinations' ? DEST : SHARES));
    api.put.mockResolvedValue({});
    api.post.mockResolvedValue({});
    const dlg = await guide.openProtectGuide();
    expect(dlg.textContent).toContain('No other NAS is mounted here');
    expect([...dlg.querySelectorAll('input[name="paths"]')].map((i) => i.checked)).toEqual([true, true]);
    dlg.querySelector('input[value="cloud|b2"]').checked = true;
    dlg.querySelector('[data-protect-form]').dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(offsite.offerRecoveryKit).toHaveBeenCalled());
    const body = api.put.mock.calls[0][1];
    expect(body.location).toBe('rclone:b2:zettnas-backup');
    expect(body.paths).toEqual(['/mnt/user/photos', '/mnt/user/docs']);
    expect(body.hour).toBe(2);
    const id = body.id;
    expect(api.post).toHaveBeenCalledWith(`/api/offsite/repos/${id}/init`, {});
    expect(api.post).toHaveBeenCalledWith(`/api/offsite/repos/${id}/backup`, {});
  });

  it('needs a place and a share', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/offsite/destinations' ? DEST : SHARES));
    const dlg = await guide.openProtectGuide();
    const form = dlg.querySelector('[data-protect-form]');
    await expect(guide.protect(form)).rejects.toThrow('Pick where the copy goes.');
    dlg.querySelector('input[value="usb|/mnt/disks/usb1"]').checked = true;
    dlg.querySelectorAll('input[name="paths"]').forEach((i) => { i.checked = false; });
    await expect(guide.protect(form)).rejects.toThrow('Pick at least one share.');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(toast.showToast).toHaveBeenCalledWith('Pick at least one share.', 'error'));
  });

  it('opens as a centered window with the usual title bar, and closes', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/offsite/destinations' ? DEST : SHARES));
    const host = await guide.openProtectGuide();
    expect(host.classList.contains('smart-modal-backdrop') && host.classList.contains('open')).toBe(true);
    const win = host.querySelector('.smart-modal-window');
    expect(win.querySelector('.smart-modal-header .os-window-controls .close-btn')).not.toBeNull();
    expect(win.dataset.dockIcon).toBe('#i-shield');
    host.querySelector('[data-close]').click();
    expect(host.classList.contains('open')).toBe(false);
    await guide.openProtectGuide();
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(host.classList.contains('open')).toBe(false);
    await guide.openProtectGuide();
    host.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(host.classList.contains('open')).toBe(false);
    expect(document.querySelectorAll('#protect-nas').length).toBe(1);
  });


  it('gets the drag handle, minimize and maximize from the shared window frame', async () => {
    const { upgradeDialog } = await import('../dialog-chrome.js');
    api.get.mockImplementation(async (url) => (url === '/api/offsite/destinations' ? DEST : SHARES));
    const host = await guide.openProtectGuide();
    const win = host.querySelector('.smart-modal-window');
    upgradeDialog(win);
    const controls = win.querySelector('.os-window-controls');
    expect(controls.querySelector('.min-btn')).not.toBeNull();
    expect(controls.querySelector('.max-btn')).not.toBeNull();
    expect(controls.querySelector('.close-btn')).not.toBeNull();
    expect(win.querySelector('.smart-modal-header').classList.contains('dialog-chrome-header')).toBe(true);
  });

  it('says why when the places cannot be read', async () => {
    api.get.mockRejectedValue(new Error('forbidden'));
    const dlg = await guide.openProtectGuide();
    expect(dlg.textContent).toContain('forbidden');
  });

  it('the Overview says how protected this NAS is', () => {
    expect(ov.protectionHtml(null)).toBe('');
    const good = String(ov.protectionHtml({ level: 'good', copies: 2, last_good: 1793091600 }));
    expect(good).toContain('2 current copies outside this NAS');
    const none = String(ov.protectionHtml({ level: 'none', copies: 0 }));
    expect(none).toContain('No copy of your files outside this NAS yet.');
    expect(none).toContain('data-ov-protect');
    expect(String(ov.protectionHtml({ level: 'stale', copies: 0, last_good: null }))).toContain('from ?');
  });

  it('the Overview shows it under the status and opens the guide', async () => {
    document.body.innerHTML = '<div id="management-hub-view"></div>';
    api.get.mockImplementation(async (url) => (url === '/api/system/status-summary' ? { ok: true, items: [] } : url === '/api/system/protection' ? { level: 'none', copies: 0 } : DEST));
    await ov.renderStatusSummary();
    const box = document.getElementById('mgmt-status-summary');
    expect(box.textContent).toContain('No copy of your files outside this NAS yet.');
    box.querySelector('[data-ov-protect]').click();
    await vi.waitFor(() => expect(document.getElementById('protect-nas')).not.toBeNull());
  });
});
