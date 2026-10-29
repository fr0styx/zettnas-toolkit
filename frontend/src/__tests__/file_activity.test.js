import { describe, it, expect } from 'vitest';
import { activityRow, activityQuery, actionLabel } from '../components/file-activity.js';

describe('file activity (FEAT-12)', () => {
  it('builds the query from the filters', () => {
    expect(activityQuery({ q: ' tax ', user: 'kim', action: 'delete', before: 42 })).toBe('/api/fs/activity?q=tax&user=kim&action=delete&before=42&limit=100');
    expect(activityQuery()).toBe('/api/fs/activity?limit=100');
  });

  it('shows who, what and where, as text', () => {
    const row = activityRow({ id: 1, ts: 1761700000, username: 'kim', ip: '10.0.0.5', via: 'api token', action: 'rename', path: '/mnt/user/a<b>.pdf', target: '/mnt/user/b.pdf', detail: '' });
    expect(row.querySelectorAll('td')).toHaveLength(4);
    expect(row.textContent).toContain('kim');
    expect(row.textContent).toContain('10.0.0.5 · api token');
    expect(row.textContent).toContain('Renamed');
    expect(row.textContent).toContain('→ /mnt/user/b.pdf');
    expect(row.innerHTML).toContain('a&lt;b&gt;.pdf');
  });

  it('marks deletes for good in red', () => {
    expect(activityRow({ action: 'delete_permanent', path: '/x' }).querySelector('.zn-tag--crit')).not.toBeNull();
    expect(activityRow({ action: 'copy', path: '/x' }).querySelector('.zn-tag--crit')).toBeNull();
    expect(actionLabel('unknown')).toBe('unknown');
  });
});
