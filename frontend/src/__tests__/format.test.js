import { describe, it, expect, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { currentLocale, formatBytes, formatDateTime, formatNumber, formatPercent, toDate } from '../format.js';

describe('format.js follows the app language (FE-14)', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('formats numbers and sizes with the language separators', async () => {
    await setLanguage('de');
    expect(currentLocale()).toBe('de-DE');
    expect(formatNumber(1234567.5)).toBe('1.234.567,5');
    expect(formatBytes(1536)).toBe('1,5 KB');
    expect(formatBytes(1500, { si: true, fixed: true })).toBe('1,5 KB');
    expect(formatPercent(42)).toMatch(/^42\s?%$/);
    await setLanguage('fr');
    expect(formatBytes(1536)).toBe('1,5 KB');
  });

  it('formats backend timestamps (seconds) and shows a placeholder for missing ones', async () => {
    await setLanguage('de');
    const s = formatDateTime(1767225600, { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'UTC' });
    expect(s).toBe('01.01.2026');
    expect(formatDateTime(null)).toBe('--');
    expect(formatDateTime(undefined, undefined, 'N/A')).toBe('N/A');
    expect(toDate(1767225600).getTime()).toBe(toDate(1767225600000).getTime());
  });

  it('keeps 0 B and binary units', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1024 ** 3 * 2)).toBe('2 GB');
  });
});
