import { describe, it, expect } from 'vitest';
import { reposHtml, formHtml, filesHtml } from '../components/offsite-backup.js';

describe('offsite backup UI (Batch 6)', () => {
  it('lists backups with retention, last run and actions', () => {
    document.body.innerHTML = reposHtml({ available: true, repos: [{ id: 'usb', name: 'USB disk', location: '/mnt/disks/usb', paths: ['/mnt/user/family'], keep: { daily: 7, weekly: 4, monthly: 12 }, last_backup: 0, last_check: 0, last_result: 'failed: disk full' }] });
    expect(document.body.textContent).toContain('keeps 7 daily, 4 weekly, 12 monthly');
    expect(document.body.textContent).toContain('failed: disk full');
    expect(document.querySelectorAll('[data-off]').length).toBe(5);
  });

  it('says when restic is missing', () => {
    document.body.innerHTML = reposHtml({ available: false, repos: [] });
    expect(document.body.textContent).toContain('no restic');
  });

  it('offers the shares as folders and lists files with restore', () => {
    document.body.innerHTML = formHtml([{ name: 'family', path: '/mnt/user/family' }]);
    expect(document.querySelector('input[name=paths][value="/mnt/user/family"]')).not.toBeNull();
    document.body.innerHTML = filesHtml([{ name: 'taxes.txt', path: '/mnt/user/family/taxes.txt', is_dir: false, size: 10 }], '/mnt/user/family');
    expect(document.querySelector('[data-restore="/mnt/user/family/taxes.txt"]')).not.toBeNull();
    expect(document.querySelector('[data-open="/mnt/user"]')).not.toBeNull();
  });
});
