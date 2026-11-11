import { describe, it, expect, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { setLanguage } from '../i18n.js';
import { formatUptime } from '../format.js';

afterEach(async () => {
  await setLanguage('en');
});

const html = readFileSync('frontend/src/windows/management-window.html', 'utf8');

describe('the four Settings tabs carry no fixed English (SET-14)', () => {
  it('the 2FA button and the uptime heading are translated', () => {
    expect(html).toMatch(/id="btn-jump-to-2fa"[^>]*data-i18n="sec.configure_2fa"/);
    expect(html).toContain('data-i18n="mw.uptime_caps"');
    expect(html).not.toContain('>Configure 2FA');
  });

  it('uptime is written in the reader\'s language', async () => {
    await setLanguage('de');
    const de = formatUptime(3 * 86400 + 4 * 3600 + 12 * 60);
    expect(de).toMatch(/^3\s?T/);
    expect(de).not.toMatch(/3d 4h/);
    await setLanguage('en');
    expect(formatUptime(2 * 3600 + 5 * 60)).toMatch(/^2\s?h 5\s?m(in)?$/);
  });
});
