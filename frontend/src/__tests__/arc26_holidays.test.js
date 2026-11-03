/** Public holidays in the calendar's day view, per country, and the day in the app's language. */
import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from 'vitest';

vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))));
const { setLanguage } = await import('../i18n.js');
const W = await import('../components/widgets.js');

const agenda = () => document.getElementById('modal-cal-agenda-list').textContent;
const day = (country, key) => {
  W.saveWidgetConfig({ calendarCountry: country });
  W.renderDayAgenda(key);
  return agenda();
};

describe('holidays in the day view', () => {
  beforeAll(() => localStorage.clear());
  afterAll(() => vi.unstubAllGlobals());
  beforeEach(() => {
    document.body.innerHTML = '<div id="modal-cal-selected-date-str"></div><div id="modal-cal-selected-sub"></div><div id="modal-cal-agenda-list"></div>';
  });

  it.each([
    ['US', '2026-01-19', 'Martin Luther King'],
    ['US', '2026-05-25', 'Memorial Day'],
    ['US', '2026-11-26', 'Thanksgiving'],
    ['DE', '2026-04-03', 'Good Friday'],
    ['GB', '2026-08-31', 'Summer Bank Holiday'],
    ['GB', '2026-12-26', 'Boxing Day'],
    ['FR', '2026-05-14', 'Ascension'],
    ['FR', '2026-07-14', 'Bastille Day'],
    ['ES', '2026-10-12', 'National Day of Spain'],
    ['CA', '2026-07-01', 'Canada Day'],
    ['CA', '2026-10-12', 'Thanksgiving'],
    ['AU', '2026-06-08', "King's Birthday"],
    ['JP', '2026-01-12', 'Coming of Age Day'],
  ])('%s %s is %s', (country, key, name) => {
    expect(day(country, key)).toContain(name);
  });

  it('an ordinary day has none; another country gets the common ones', () => {
    expect(day('US', '2026-03-03')).not.toContain('Public holiday');
    expect(day('ZZ', '2026-12-25')).toContain('Christmas Day');
    expect(day('ZZ', '2026-05-01')).toContain("International Workers' Day");
    expect(day('ZZ', '2026-07-04')).not.toContain('Public holiday');
  });

  it('China has its built-in holidays too', () => {
    expect(day('CN', '2026-10-01')).toContain('Public holiday');
  });

  it('writes the day in the app language', async () => {
    await setLanguage('de');
    try {
      day('DE', '2026-04-03');
      expect(document.getElementById('modal-cal-selected-date-str').textContent).toContain('April 2026');
      expect(document.getElementById('modal-cal-selected-date-str').textContent).toContain('Freitag');
    } finally {
      await setLanguage('en');
    }
  });
});
