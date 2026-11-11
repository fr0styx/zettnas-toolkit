/** SET-06: "Add a backup job" starts on a choice the server accepts; small truths on the Backup page. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { syncBackupJobForm } from '../components/management/system.js';

const html = readFileSync(resolve(__dirname, '..', 'windows/management-window.html'), 'utf8');
const page = readFileSync(resolve(__dirname, '..', 'components/management/backup.js'), 'utf8');
const form = html.slice(html.indexOf('id="create-backup-job-form"'), html.indexOf('id="backup-job-enabled"'));
const byId = (id) => document.getElementById(id);

describe('the "Add a backup job" form (SET-06)', () => {
  beforeEach(() => {
    document.body.innerHTML = `<form>${form}"></form>`;
  });

  it('a folder job starts on "Snapshots on this server only", the one choice the server takes', () => {
    syncBackupJobForm();
    const dest = byId('backup-job-dest-type');
    expect(dest.value).toBe('local_snapshot');
    expect(dest.querySelector('option[value="remote"]').hidden).toBe(true);
    expect(dest.querySelector('option[value="local_folder"]').hidden).toBe(true);
    expect(byId('backup-dest-cloud-hint').hidden).toBe(false);
    expect(byId('backup-dest-cloud-hint').textContent).toContain('add an off-site backup instead');
    expect(byId('backup-config-fields').hidden).toBe(true); // no passphrase field for a folder
  });

  it('a settings job offers a folder or a cloud, with its passphrase', () => {
    byId('backup-job-kind').value = 'config';
    syncBackupJobForm();
    const dest = byId('backup-job-dest-type');
    expect(dest.value).toBe('local_folder');
    expect(dest.querySelector('option[value="remote"]').hidden).toBe(false);
    expect(dest.querySelector('option[value="local_snapshot"]').hidden).toBe(true);
    expect(byId('backup-dest-cloud-hint').hidden).toBe(true);
    expect(byId('backup-config-fields').hidden).toBe(false);
    dest.value = 'remote';
    syncBackupJobForm();
    expect(dest.value).toBe('remote');
    // and back to a folder: the cloud choice does not stay behind
    byId('backup-job-kind').value = 'data';
    syncBackupJobForm();
    expect(dest.value).toBe('local_snapshot');
  });

  it('the markup itself starts on that choice', () => {
    expect(form).toMatch(/<option value="local_snapshot" selected/);
    expect(form).not.toMatch(/<option value="remote" selected/);
  });
});

describe('small truths on the Backup page (SET-06)', () => {
  it('the empty snapshot list has no button that presses another window’s button', () => {
    expect(page).not.toContain("target: 'btn-take-snapshot-submit'");
    expect(page).toContain('“Scheduled snapshots per share”');
  });

  it('deleting a job asks about its name', () => {
    expect(page).toContain('data-job-name="${escapeHtml(job.name || job.id)}"');
    expect(page).toContain('{ name: btn.dataset.jobName || jobId }');
  });
});
