import { describe, it, expect, afterEach, vi } from 'vitest';

vi.mock('../i18n.js', () => ({
  getLanguage: () => 'de',
  t: (key, fallback, params = {}) => String(fallback).replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)),
}));

const { formatDateTime, formatTime, setClockPrefs, clockPrefs } = await import('../format.js');
const { ZettEventBus } = await import('../event-bus.js');
const { serverTimeHint } = await import('../components/signin-hours.js');

const NOON_UTC = Date.UTC(2026, 0, 15, 12, 0);

describe("dates follow the person's clock (NUX-10)", () => {
  afterEach(() => setClockPrefs('', ''));

  it('uses their time zone and 12/24-hour choice', () => {
    setClockPrefs('Asia/Tokyo', '24');
    expect(formatTime(NOON_UTC)).toBe('21:00');
    setClockPrefs('America/New_York', '12');
    expect(formatTime(NOON_UTC)).toMatch(/^0?7:00\s?(AM|am|vorm\.)/i);
    expect(formatDateTime(NOON_UTC, { hour: 'numeric', timeZone: 'UTC', hour12: false })).toContain('12'); // a caller's own choice wins
  });

  it('ignores an unknown zone and follows clock:changed', () => {
    setClockPrefs('Not/AZone', '24');
    expect(clockPrefs().timeZone).toBe('');
    ZettEventBus.emit('clock:changed', { zone: 'Asia/Tokyo', format: '24' });
    expect(clockPrefs()).toEqual({ timeZone: 'Asia/Tokyo', hour12: false });
  });

  it("names the server's zone and time in the sign-in hours hint", () => {
    expect(serverTimeHint('UTC', NOON_UTC)).toContain('Server time (UTC, now 12:00)');
    expect(serverTimeHint('', NOON_UTC)).toMatch(/^Server time\. /);
  });
});
