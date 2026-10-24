import { describe, it, expect, beforeEach } from 'vitest';
import { syncBackupJobForm } from '../components/management.js';

describe('Backup job form: ZettNAS settings backups (OPS-8)', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <select id="backup-job-kind"><option value="data" selected>data</option><option value="config">config</option></select>
      <div id="backup-config-fields" hidden><input id="backup-job-passphrase"></div>
      <div id="backup-subvolume-wrap"><input id="backup-job-subvolume" required></div>
      <select id="backup-job-dest-type">
        <option value="remote" selected>remote</option>
        <option value="local_snapshot">snapshot</option>
        <option value="local_folder" hidden>folder</option>
      </select>
      <div id="backup-local-fields" hidden></div>
      <div id="backup-remote-fields"></div>`;
  });

  it('asks for a passphrase and a folder instead of a source share', () => {
    document.getElementById('backup-job-kind').value = 'config';
    document.getElementById('backup-job-dest-type').value = 'local_folder';
    syncBackupJobForm();
    expect(document.getElementById('backup-config-fields').hidden).toBe(false);
    expect(document.getElementById('backup-subvolume-wrap').hidden).toBe(true);
    expect(document.getElementById('backup-job-subvolume').required).toBe(false);
    expect(document.getElementById('backup-local-fields').hidden).toBe(false);
    expect(document.getElementById('backup-remote-fields').style.display).toBe('none');
  });

  it('switching back restores the data backup fields', () => {
    document.getElementById('backup-job-kind').value = 'config';
    syncBackupJobForm();
    document.getElementById('backup-job-kind').value = 'data';
    syncBackupJobForm();
    expect(document.getElementById('backup-config-fields').hidden).toBe(true);
    expect(document.getElementById('backup-job-subvolume').required).toBe(true);
    expect(document.getElementById('backup-job-dest-type').value).not.toBe('local_folder');
  });
});
