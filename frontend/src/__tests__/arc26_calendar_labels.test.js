/** The calendar's month titles and weekday heads in the app's language. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))));
const { setLanguage } = await import('../i18n.js');
const W = await import('../components/widgets.js');

describe('calendar labels', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('English stays as it was', () => {
    expect(W.monthTitle(2026, 10)).toBe('November 2026');
    expect(W.monthTitle(2026, 10, 'short').toUpperCase()).toBe('NOV 2026');
    expect(W.weekdayInitials()).toEqual(['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']);
  });

  it('German, French and Chinese', async () => {
    await setLanguage('de');
    expect(W.monthTitle(2026, 2)).toBe('März 2026');
    expect(W.weekdayInitials()).toEqual(['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']);
    await setLanguage('fr');
    expect(W.monthTitle(2026, 7)).toBe('août 2026');
    await setLanguage('zh');
    expect(W.weekdayInitials()[0]).toBe('周日');
  });

  it('the widget and the calendar window use them', async () => {
    document.body.innerHTML = `
      <div id="widget-calendar"><span id="w-cal-month"></span><span id="w-cal-country-badge"></span><div id="w-calendar-grid"></div></div>
      <div id="modal-calendar-notes"><span id="modal-cal-month-title"></span><div id="modal-cal-grid"></div>
        <div id="modal-cal-selected-date-str"></div><div id="modal-cal-selected-sub"></div><div id="modal-cal-agenda-list"></div></div>`;
    W.saveWidgetConfig({ calendarCountry: 'DE' });
    await setLanguage('de');
    W.renderCalendar();
    expect(document.getElementById('w-cal-month').textContent).toMatch(/2026|2027/);
    expect([...document.querySelectorAll('#w-calendar-grid .cal-weekday')].map((e) => e.textContent)[0]).toBe('So');
    W.initCalendarView('2026-03-10');
    expect(document.getElementById('modal-cal-month-title').textContent).toBe('März 2026');
    expect(document.querySelector('#modal-cal-grid .cal-weekday').textContent).toBe('So');
  });
});
