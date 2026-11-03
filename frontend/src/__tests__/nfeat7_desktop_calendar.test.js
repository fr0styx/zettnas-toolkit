/** NFEAT-7: the desktop calendar shows the family calendar as a feed, and the family card says how to add it. */
import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));

import { api } from '../api.js';
import { fetchCalendarFeeds, feedMeta } from '../components/widgets.js';
import { familyCalendarBody } from '../components/family-calendar.js';

describe('the family calendar on the desktop (NFEAT-7)', () => {
  it('names the family calendar in the feed list and counts events with a plural', async () => {
    document.body.innerHTML = '<div id="cal-feeds-list"></div>';
    api.get.mockResolvedValue({ feeds: [
      { id: 'a', name: 'Familie', provider: 'family', event_count: 1 },
      { id: 'b', name: 'Work', provider: 'google', event_count: 3 },
    ] });
    await fetchCalendarFeeds();
    const rows = [...document.querySelectorAll('[data-feed-id]')].map((r) => r.textContent.replace(/\s+/g, ' ').trim());
    expect(rows[0]).toContain('1 event · Family calendar');
    expect(rows[1]).toContain('3 events · iCal');
    expect(feedMeta({ provider: 'family' })).toBe('0 events · Family calendar');
  });

  it('tells how to show it on the desktop', () => {
    const box = familyCalendarBody({ installed: true, running: true, server: 's:8093', caldav: 'http://s:8093/remote.php/dav' }, () => {});
    expect(box.textContent).toContain('copy the subscription link and paste it under Calendar Feeds with + Add Feed');
  });
});
