import { describe, it, expect } from 'vitest';
import { lockLine, isLockable, formHtml, reposHtml } from '../components/offsite-backup.js';

// FEAT-03: a locked cloud copy says until when it is locked and whether the bucket was checked.
describe('locked cloud copies', () => {
  const base = { id: 'c', name: 'Cloud', location: 'rclone:b2:locked/z', paths: ['/mnt/user/a'], keep: { daily: 7, weekly: 4, monthly: 12 } };

  it('offers the lock only for cloud remotes', () => {
    expect(isLockable('rclone:b2:bucket')).toBe(true);
    expect(isLockable('/mnt/disks/usb')).toBe(false);
    expect(isLockable('rest:http://x:8000/a/')).toBe(false);
    const div = document.createElement('div');
    div.innerHTML = formHtml([]);
    expect(div.querySelector('[data-off-lock] input[name="lock_days"]')).not.toBeNull();
    expect(div.querySelector('[data-off-lock]').hidden).toBe(true);
  });

  it('says nothing for an unlocked backup', () => {
    expect(lockLine(base)).toBe('');
  });

  it('shows the lock end and the check', () => {
    const until = Date.UTC(2026, 10, 28) / 1000;
    expect(lockLine({ ...base, lock_days: 30 })).toContain('Each copy is locked for 30 days');
    expect(lockLine({ ...base, lock_days: 30 })).toContain('not checked yet');
    const ok = lockLine({ ...base, lock_days: 30, locked_until: until, lock_check: { ok: true, mode: 'COMPLIANCE', days: 30, at: until - 86400 } });
    expect(ok).toContain('Cloud copy locked until');
    expect(ok).toContain('COMPLIANCE, 30 days');
    expect(ok).not.toContain('<strong>');
  });

  it('warns when the bucket is not locked or locks for less', () => {
    const failed = lockLine({ ...base, lock_days: 30, lock_check: { ok: false, error: 'Backblaze refused the application key.' } });
    expect(failed).toContain('<strong>');
    expect(failed).toContain('refused the application key');
    expect(lockLine({ ...base, lock_days: 30, lock_check: { ok: false } })).toContain('Object Lock is off');
    expect(lockLine({ ...base, lock_days: 30, lock_check: { ok: true, days: 7, mode: 'COMPLIANCE' } })).toContain('only 7 days');
  });

  it('puts a Check the lock button on locked backups only', () => {
    const html = reposHtml({ available: true, repos: [{ ...base, lock_days: 30 }, { ...base, id: 'u' }] });
    expect((html.match(/data-off="lockcheck"/g) || []).length).toBe(1);
  });
});
