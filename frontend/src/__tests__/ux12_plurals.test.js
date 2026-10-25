import { describe, it, expect } from 'vitest';
import { formatPlurals, t } from '../i18n.js';

describe('ICU plurals (UX-12)', () => {
  const s = '{count, plural, =0 {Nothing} one {# item} other {# items}} left';
  it('picks the form the language asks for', () => {
    expect(formatPlurals(s, { count: 0 }, 'en')).toBe('Nothing left');
    expect(formatPlurals(s, { count: 1 }, 'en')).toBe('1 item left');
    expect(formatPlurals(s, { count: 5 }, 'en')).toBe('5 items left');
    expect(formatPlurals('{n, plural, one {# fichier} other {# fichiers}}', { n: 0 }, 'fr')).toBe('0 fichier'); // French: 0 is singular
    expect(formatPlurals('{n, plural, other {# 个}}', { n: 3 }, 'zh')).toBe('3 个');
    expect(formatPlurals('{a, plural, one {# a} other {# as}} and {b, plural, one {# b} other {# bs}}', { a: 1, b: 2 }, 'en')).toBe('1 a and 2 bs');
    expect(formatPlurals('plain {count}', { count: 2 })).toBe('plain {count}');
  });

  it('t() uses them', () => {
    expect(t('fm.moved_to_bin', '', { count: 1 })).toBe('Moved 1 item to the Recycle Bin');
    expect(t('fm.moved_to_bin', '', { count: 3 })).toBe('Moved 3 items to the Recycle Bin');
    expect(t('overview.attention', '', { n: 1 })).toBe('1 thing needs your attention');
  });
});
