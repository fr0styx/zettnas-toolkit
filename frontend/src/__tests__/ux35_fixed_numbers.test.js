import { describe, it, expect, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { formatFixed } from '../format.js';
import { formatNumber as shortCount } from '../components/chassis-visualizer.js';

describe('numbers people read use the language separators (UX-35)', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('formatFixed keeps toFixed digits in English and switches separators elsewhere', async () => {
    expect(formatFixed(1.25, 1)).toMatch(/^1\.[23]$/);
    expect(formatFixed(3, 2)).toBe('3.00');
    expect(formatFixed(12.6, 0)).toBe('13');
    expect(formatFixed(0.5)).toBe('0.5');
    await setLanguage('de');
    expect(formatFixed(1.5, 1)).toBe('1,5');
    expect(formatFixed(1234.5, 1)).toBe('1234,5');
    await setLanguage('fr');
    expect(formatFixed(2.25, 2)).toBe('2,25');
  });

  it('short counts on the storage page (1.5K / 2.0M / 3.1B)', async () => {
    expect(shortCount(1500)).toBe('1.5K');
    expect(shortCount(2e6)).toBe('2.0M');
    expect(shortCount(3.1e9)).toBe('3.1B');
    await setLanguage('de');
    expect(shortCount(1500)).toBe('1,5K');
  });
});
