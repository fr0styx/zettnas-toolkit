/** NUX-15: Mission Control's lists drawn by widgets.js use classes, not inline styles. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))));
const { api } = await import('../api.js');
const W = await import('../components/widgets.js');

describe("Mission Control's lists from widgets.js", () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="modal-cal-selected-date-str"></div><div id="modal-cal-selected-sub"></div>
      <div id="modal-calendar-notes" style="display: none;"></div><div id="modal-cal-agenda-list"></div>
      <div id="modal-clock-timezone"><input id="tz-search-input"><div id="tz-items-list" tabindex="0" role="listbox"></div></div>
      <div id="modal-tz-preview-time"></div><div id="modal-tz-preview-date"></div>
      <button id="btn-tz-fmt-12"></button><button id="btn-tz-fmt-24"></button>`;
  });

  it('a day with nothing on it says so', () => {
    W.saveWidgetConfig({ calendarCountry: 'US' });
    W.renderDayAgenda('2026-03-03');
    const list = document.getElementById('modal-cal-agenda-list');
    expect(list.querySelector('.cag-empty .cag-empty-title')).not.toBeNull();
    expect(list.querySelector('[style]')).toBeNull();
  });

  it('notes, synced events and tasks are drawn with classes', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      events: [
        { id: 'n1', date: '2026-03-04', type: 'note', title: 'Dentist', time: '09:30', description: 'Bring the card' },
        { id: 's1', date: '2026-03-04', type: 'event', title: 'School trip', source: 'synced' },
        { id: 't1', date: '2026-03-04', type: 'task', title: 'Pay rent', completed: true },
      ],
    });
    await W.fetchCalendarEvents('2026-03-01', '2026-03-31');
    W.renderDayAgenda('2026-03-04');
    const list = document.getElementById('modal-cal-agenda-list');
    expect(list.querySelector('.cag-time').textContent).toContain('09:30');
    expect(list.querySelector('.cag-badge-warn')).not.toBeNull();
    expect(list.querySelector('.cag-note').textContent).toBe('Bring the card');
    expect(list.querySelector('input.cag-done')).not.toBeNull();
    expect(list.querySelectorAll('.cag-del').length).toBe(2); // the synced one can't be deleted here
  });

  it('a time zone search with no match says so', () => {
    W.saveWidgetConfig({ clockTimezone: 'auto', clockFormat: '24' });
    W.resetTimezoneChoice();
    W.setupTimezoneModalEvents();
    const input = document.getElementById('tz-search-input');
    input.value = 'zzzz-nowhere';
    input.dispatchEvent(new Event('input'));
    const list = document.getElementById('tz-items-list');
    expect(list.querySelector('.tzl-empty')).not.toBeNull();
  });
});
