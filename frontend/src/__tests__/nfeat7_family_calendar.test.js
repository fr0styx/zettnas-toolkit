import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { familyCalendarBody, renderFamilyCalendar } from '../components/family-calendar.js';

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('the family calendar and contacts (NFEAT-7)', () => {
  it('points to the office suite when there is none, or it is stopped', () => {
    expect(familyCalendarBody({ installed: false }).textContent).toContain('Install the office suite');
    expect(familyCalendarBody({ installed: true, running: false }).textContent).toContain('stopped');
  });

  it('shows the address and how to add it on phones', () => {
    const box = familyCalendarBody({ installed: true, running: true, server: 'nas.local:8093', caldav: 'http://nas.local:8093/remote.php/dav' }, () => {});
    expect(box.querySelector('code').textContent).toBe('http://nas.local:8093/remote.php/dav');
    expect(box.textContent).toContain('server nas.local:8093');
    expect(box.textContent).toContain('DAVx⁵');
  });

  it('adds the apps to an older office suite', async () => {
    api.get.mockResolvedValue({ installed: true, running: true, server: 's', caldav: 'http://s/remote.php/dav' });
    api.post.mockResolvedValue({ added: ['a', 'b'], failed: [] });
    const mount = document.createElement('div');
    await renderFamilyCalendar(mount);
    [...mount.querySelectorAll('button')].find((b) => b.textContent.startsWith('Add calendar')).click();
    await flush();
    expect(api.post).toHaveBeenCalledWith('/api/docker/catalog/office-suite/family', {});
    expect(showToast).toHaveBeenCalledWith('The calendar and contacts are in the office suite.', 'success');
    api.post.mockResolvedValue({ added: [], failed: ['Adding the family calendar'] });
    await renderFamilyCalendar(mount);
    [...mount.querySelectorAll('button')].find((b) => b.textContent.startsWith('Add calendar')).click();
    await flush();
    expect(showToast).toHaveBeenLastCalledWith(expect.stringContaining('Adding the family calendar'), 'warn');
    api.get.mockRejectedValue(new Error('forbidden'));
    await renderFamilyCalendar(mount);
    expect(mount.textContent).toBe('forbidden');
  });
});
