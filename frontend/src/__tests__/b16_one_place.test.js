/**
 * UX-25: one home per job. One control changes the time zone (desktop clock, front screen and,
 * for an administrator, the server); people, sign-ins and two-step sign-in are one page; a backup
 * job reads what → where → when; the photos card sends a phone backup to Backups.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (p) => readFileSync(resolve(__dirname, '..', p), 'utf8');

describe('one place for each job (UX-25)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('the hardware drawer has no time-zone control of its own, only a way to the one in Settings', () => {
    const drawer = read('windows/drawer.html');
    expect(drawer).not.toMatch(/id="tz-select"/);
    expect(drawer).not.toMatch(/id="clock-format-btn"/);
    expect(drawer).toMatch(/id="btn-clock-open-settings"/);
    const all = read('windows/management-window.html') + drawer + readFileSync(resolve(__dirname, '../../index.html'), 'utf8');
    expect(all.match(/id="tz-custom-input"/g)).toHaveLength(1); // the id was twice on the page before
  });

  it('saving the time zone moves the front screen clock and, when ticked, the server', async () => {
    const { api } = await import('../api.js');
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    const { state } = await import('../state.js');
    const { applyClockEverywhere } = await import('../components/widgets.js');
    document.body.innerHTML = '<label id="tz-server-row"><input type="checkbox" id="tz-apply-server" checked></label>';

    await applyClockEverywhere('Asia/Tokyo', '12');
    expect(state.currentTimezone).toBe('Asia/Tokyo');
    expect(state.clockFormat).toBe('12');
    expect(put).toHaveBeenCalledWith('/api/system/identity', { timezone: 'Asia/Tokyo' });

    put.mockClear();
    document.getElementById('tz-apply-server').checked = false;
    await applyClockEverywhere('Europe/Berlin', '24');
    expect(state.currentTimezone).toBe('Europe/Berlin');
    expect(put).not.toHaveBeenCalled();

    document.getElementById('tz-apply-server').checked = true;
    document.getElementById('tz-server-row').hidden = true; // not an administrator
    await applyClockEverywhere('auto', '24');
    expect(state.currentTimezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
    expect(put).not.toHaveBeenCalled();
  });

  it('people, sign-ins and two-step sign-in have no tabs inside the tab', () => {
    const mw = read('windows/management-window.html');
    expect(mw).not.toMatch(/users-nav-btn/);
    const pane = mw.slice(mw.indexOf('id="mgmt-pane-users"'), mw.indexOf('id="mgmt-pane-notifications"'));
    expect(pane).not.toMatch(/users-subpane" style="display: none/);
  });

  it('a backup job asks what, then where to, then when', () => {
    const mw = read('windows/management-window.html');
    const form = mw.slice(mw.indexOf('id="create-backup-job-form"'), mw.indexOf('</form>', mw.indexOf('id="create-backup-job-form"')));
    const at = (id) => form.indexOf(`id="${id}"`);
    expect(form.indexOf('backup.step_what')).toBeLessThan(at('backup-job-subvolume'));
    expect(at('backup-job-subvolume')).toBeLessThan(form.indexOf('backup.step_where'));
    expect(form.indexOf('backup.step_where')).toBeLessThan(at('backup-job-dest-type'));
    expect(at('backup-job-remote-name')).toBeLessThan(form.indexOf('backup.step_when'));
    expect(form.indexOf('backup.step_when')).toBeLessThan(at('backup-job-schedule'));
  });

  it('the photos card sends a phone backup to the one place, under Backups', async () => {
    const { settingsHtml, openPhoneBackup } = await import('../components/immich-settings.js');
    expect(settingsHtml({}, false)).toContain('data-immich-phone-backup');
    window.openManagementWindow = vi.fn();
    openPhoneBackup();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-pane-backups');
  });
});
