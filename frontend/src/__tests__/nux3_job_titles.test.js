import { describe, it, expect } from 'vitest';
import { jobTitle, jobRowHtml } from '../components/jobs-centre.js';

describe('job titles in the reader\'s language (NUX-3)', () => {
  it('builds the title from its key, with the English as it came otherwise', () => {
    expect(jobTitle({ title: 'Move 2 item(s) to /mnt/user/a', title_id: 'jobs.t.move', title_params: { n: 2, dest: '/mnt/user/a' } })).toBe('Move 2 items to /mnt/user/a');
    expect(jobTitle({ title: 'Something old' })).toBe('Something old');
    expect(jobTitle(null)).toBe('');
  });

  it('is what the row shows', () => {
    const html = jobRowHtml({ id: 'j1', kind: 'backup', status: 'running', title: 'Offsite backup: Fotos', title_id: 'jobs.t.offsite', title_params: { name: 'Fotos' } }, true);
    expect(html).toContain('Offsite backup: Fotos');
  });
});
