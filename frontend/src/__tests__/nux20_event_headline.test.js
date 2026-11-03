/** NUX-20: an event without a title is headed in translatable words. */
import { describe, it, expect } from 'vitest';
import { openEventDetailModal } from '../modals.js';

describe('event detail headline (NUX-20)', () => {
  it('falls back to a plain heading', () => {
    document.body.innerHTML = '<div id="event-detail-modal-overlay"><div class="smart-modal-window"><h3 id="event-detail-event-title"></h3></div></div>';
    openEventDetailModal({ ts: 1700000000 });
    expect(document.getElementById('event-detail-event-title').textContent).toBe('System Notification');
    openEventDetailModal({ ts: 1700000000, title: 'Disk 3 is hot' });
    expect(document.getElementById('event-detail-event-title').textContent).toBe('Disk 3 is hot');
  });
});
