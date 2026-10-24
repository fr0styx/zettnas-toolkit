import { describe, it, expect } from 'vitest';
import { schedulesHtml, entriesHtml } from '../components/snapshot-browser.js';

describe('snapshot schedules and browser (Batch 6)', () => {
  it('lists schedules with their retention and offers every share', () => {
    document.body.innerHTML = schedulesHtml([{ share: 'family', every: 'daily', keep: 14, immutable_days: 7, last_run: 0 }], ['family', 'media']);
    expect(document.body.textContent).toContain('family');
    expect(document.body.textContent).toContain('keep 14');
    expect(document.body.textContent).toContain('locked 7 days');
    expect([...document.querySelectorAll('select[name=share] option')].map((o) => o.value)).toEqual(['family', 'media']);
  });

  it('shows folders, files and both restore choices', () => {
    document.body.innerHTML = entriesHtml({ path: 'photos', entries: [{ name: '2024', is_dir: true, size: 0 }, { name: 'a.jpg', is_dir: false, size: 2048 }] });
    expect(document.querySelector('[data-snap-open="photos/2024"]')).not.toBeNull();
    expect(document.querySelector('[data-snap-restore="photos/a.jpg"]')).not.toBeNull();
    expect(document.querySelector('[data-snap-replace="photos/a.jpg"]')).not.toBeNull();
    expect(document.querySelector('[data-snap-open=""]')).not.toBeNull(); // up one folder
  });
});
