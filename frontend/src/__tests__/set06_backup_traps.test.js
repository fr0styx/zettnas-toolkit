/** SET-06: the recovery-kit window, the app-backup table and the snapshot schedule form. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), downloadBlob: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showDangerConfirm: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { offerRecoveryKit } = await import('../components/offsite-backup.js');
const { schedulesHtml, fillScheduleForm } = await import('../components/snapshot-browser.js');
const { fetchAndRenderAppBackups } = await import('../components/management/backup.js');

describe('the recovery-kit window (SET-06)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({ filename: 'kiboto-recovery-usb.txt', text: 'Recovery key: abc' });
    api.post.mockResolvedValue({});
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue() } });
  });

  it('closing it saves nothing and marks nothing', async () => {
    const onSaved = vi.fn();
    await offerRecoveryKit({ id: 'usb' }, onSaved);
    const [, , , onCancel, options] = toast.showConfirmToast.mock.calls[0];
    expect(onCancel).toBeNull(); // Cancel, Escape, the × and a click outside run nothing
    expect(options.cancelText).toBe('Not now');
    expect(options.destructive).toBe(false);
    expect(api.post).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('"Copy the kit" is its own button, and copying marks the kit saved', async () => {
    const onSaved = vi.fn();
    await offerRecoveryKit({ id: 'usb' }, onSaved);
    const [, , , , options] = toast.showConfirmToast.mock.calls[0];
    expect(options.ejectText).toBe('Copy the kit');
    expect(options.ejectClass).not.toContain('is-danger');
    await options.onEject();
    expect(api.post).toHaveBeenCalledWith('/api/offsite/repos/usb/kit-saved', {});
    expect(onSaved).toHaveBeenCalledTimes(1);
  });
});

describe('the app-backup table (SET-06)', () => {
  const record = {
    id: 'app_plex_20261010_130000',
    app_name: 'plex',
    container_name: 'plex',
    reason: 'on_demand',
    filename: 'app_plex_20261010_130000.tar.gz',
    filepath: '/mnt/user/backups/app_plex_20261010_130000.tar.gz',
    size_bytes: 2202009,
    size_human: '2.1 MB',
    created_at: 1791653600,
    image: 'linuxserver/plex:latest',
    mounts_count: 2,
    missing: false,
  };

  it('shows the file name, the size and the date the server keeps', async () => {
    api.get.mockResolvedValueOnce({ backups: [record] });
    const mount = document.createElement('div');
    await fetchAndRenderAppBackups(mount);
    expect(mount.textContent).toContain('app_plex_20261010_130000.tar.gz');
    expect(mount.textContent).toContain('2.1 MB');
    expect(mount.textContent).not.toContain('N/A');
    expect(mount.querySelector('.btn-download-app-backup').dataset.file).toBe('app_plex_20261010_130000.tar.gz');
    expect(mount.querySelector('.btn-download-app-backup').disabled).toBe(false);
  });

  it('a virtual machine backup has its name too', async () => {
    api.get.mockResolvedValueOnce({ backups: [{ id: 'vm_win11_1', type: 'vm', app_name: 'win11', vm_name: 'Windows 11', filename: 'vm_win11_1.tar.gz', size_formatted: '40 GB', created_at: 1791653600, reason: 'on_demand' }] });
    const mount = document.createElement('div');
    await fetchAndRenderAppBackups(mount);
    expect(mount.textContent).toContain('Windows 11');
    expect(mount.textContent).toContain('40 GB');
  });

  it('a backup whose file is not there right now stays in the list, and says so', async () => {
    api.get.mockResolvedValueOnce({ backups: [{ ...record, missing: true }] });
    const mount = document.createElement('div');
    await fetchAndRenderAppBackups(mount);
    expect(mount.textContent).toContain('The file is not there right now');
    expect(mount.querySelector('.btn-download-app-backup').disabled).toBe(true);
    expect(mount.querySelector('.btn-restore-app-backup').disabled).toBe(true);
    expect(mount.querySelector('.btn-delete-app-backup').disabled).toBe(false);
  });
});

describe('the snapshot schedule form (SET-06)', () => {
  const schedules = [{ share: 'photos', every: 'hourly', keep: 24, keep_daily: 30, immutable_days: 7 }];

  it('the list shows the daily tier', () => {
    const html = schedulesHtml(schedules, ['photos', 'docs']);
    expect(html).toContain('keep 24');
    expect(html).toContain('plus one a day for 30 days');
    expect(schedulesHtml([{ share: 'docs', every: 'daily', keep: 14, keep_daily: 0 }], ['docs'])).not.toContain('plus one a day');
  });

  it('the form shows the chosen share’s schedule, and the defaults for a share without one', () => {
    document.body.innerHTML = schedulesHtml(schedules, ['photos', 'docs']);
    const form = document.querySelector('[data-snap-form]');
    const value = (name) => form.elements.namedItem(name).value;
    fillScheduleForm(form, schedules);
    expect([value('every'), value('keep'), value('keep_daily'), value('immutable_days')]).toEqual(['hourly', '24', '30', '7']);
    form.elements.namedItem('share').value = 'docs';
    fillScheduleForm(form, schedules);
    expect([value('every'), value('keep'), value('keep_daily'), value('immutable_days')]).toEqual(['daily', '14', '0', '0']);
    fillScheduleForm(null, schedules); // no form on screen: nothing to do
  });
});
