import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { put: vi.fn(() => Promise.resolve({ ok: true })) } }));
import { api } from '../api.js';
import {
  DEFAULT_LOOK, applyLook, clearLook, fromLegacy, hasOwnLook, loadLook, lookColour, lookFromAccount,
  normalizeLook, saveLookToAccount, storeLook, tintFactor, _resetForTests,
} from '../look.js';

function memoryStorage(init = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), _m: m };
}

beforeEach(() => {
  _resetForTests();
  document.body.className = '';
  document.body.removeAttribute('style');
  document.head.innerHTML = '<meta name="theme-color" content="#000000">';
});
afterEach(() => vi.useRealTimers());

describe('the look (APP-B)', () => {
  it('keeps valid fields and replaces the rest with the default', () => {
    expect(normalizeLook({ mode: 'auto', theme: 'moss', tint: 0.333, trueBlack: true, accent: '#AABBCC' }))
      .toEqual({ mode: 'auto', theme: 'moss', tint: 0.33, trueBlack: true, accent: '#aabbcc' });
    expect(normalizeLook({ mode: 'sepia', theme: 'sapphire', tint: 7, trueBlack: 'yes', accent: 'red' }))
      .toEqual({ mode: 'dark', theme: 'lagoon', tint: 1, trueBlack: false, accent: '' });
    expect(normalizeLook(null)).toEqual({ ...DEFAULT_LOOK });
  });

  it('translates the theme names saved before APP-B, keeping the rest of the look', () => {
    const base = normalizeLook({ mode: 'light', theme: 'fjord', tint: 0.5 });
    expect(fromLegacy('sapphire', base)).toMatchObject({ theme: 'fjord', mode: 'light', tint: 0.5 });
    expect(fromLegacy('amber', base).theme).toBe('canyon');
    expect(fromLegacy('crimson', base).theme).toBe('canyon');
    expect(fromLegacy('emerald', base).theme).toBe('moss');
    expect(fromLegacy('amethyst', base).theme).toBe('heather');
    expect(fromLegacy('cyber', base)).toMatchObject({ theme: 'lagoon', mode: 'light' });
    expect(fromLegacy('light')).toMatchObject({ theme: 'lagoon', mode: 'light' });
    expect(fromLegacy('oled')).toMatchObject({ mode: 'dark', trueBlack: true });
    expect(fromLegacy('system').mode).toBe('auto');
    expect(fromLegacy('heather', base)).toMatchObject({ theme: 'heather', mode: 'light' });
    expect(fromLegacy('nonsense', base)).toEqual(base);
  });

  it('reads the saved look, else the old theme and accent, without writing the old keys', () => {
    expect(loadLook(memoryStorage({ kiboto_look: JSON.stringify({ theme: 'heather', mode: 'auto' }) }))).toMatchObject({ theme: 'heather', mode: 'auto' });
    const old = memoryStorage({ desktop_theme: 'amethyst', desktop_custom_accent: '#123456' });
    expect(loadLook(old)).toMatchObject({ theme: 'heather', accent: '#123456' });
    expect(hasOwnLook(old)).toBe(false);
    storeLook({ theme: 'canyon' }, old);
    expect(hasOwnLook(old)).toBe(true);
    expect(old.getItem('desktop_theme')).toBe('amethyst');
    expect(loadLook(memoryStorage({ desktop_theme: 'yak' })).theme).toBe('lagoon');
    expect(loadLook(memoryStorage({ kiboto_look: '{not json' }))).toEqual({ ...DEFAULT_LOOK });
    expect(loadLook(null)).toEqual({ ...DEFAULT_LOOK });
  });

  it('puts the theme, the mode, True black and the tint on the page', () => {
    expect(applyLook({ theme: 'fjord', mode: 'light', tint: 0.5, trueBlack: true })).toBe('light');
    const c = document.body.classList;
    expect(c.contains('kb-theme-fjord') && c.contains('theme-light') && c.contains('kb-tinted')).toBe(true);
    expect(c.contains('theme-oled')).toBe(false); // True black is for dark mode only
    expect(document.body.style.getPropertyValue('--kb-tint')).toBe('2');
    expect(document.querySelector('meta[name="theme-color"]').getAttribute('content')).toBe('#f2f6fa');

    document.body.classList.add('theme-yak');
    expect(applyLook({ theme: 'canyon', mode: 'dark', tint: 1, trueBlack: true })).toBe('dark');
    expect(c.contains('kb-theme-fjord') || c.contains('theme-yak') || c.contains('theme-light')).toBe(false);
    expect(c.contains('kb-theme-canyon') && c.contains('theme-oled')).toBe(true);
    expect(document.body.style.getPropertyValue('--kb-tint')).toBe('2'); // Canyon stops at Medium

    applyLook({ theme: 'lagoon' });
    expect(c.contains('kb-tinted')).toBe(false);
    expect(document.body.style.getPropertyValue('--kb-tint')).toBe('');
    clearLook();
    expect([...c].some((x) => x.startsWith('kb-'))).toBe(false);
  });

  it('Auto follows the device', () => {
    let listener = null;
    const mq = { matches: false, addEventListener: (_e, fn) => { listener = fn; } };
    const win = { matchMedia: () => mq };
    expect(applyLook({ mode: 'auto' }, document, win)).toBe('light');
    mq.matches = true;
    listener();
    expect(document.body.classList.contains('theme-light')).toBe(false);
    expect(applyLook({ mode: 'auto' }, document, {})).toBe('dark'); // no media queries: dark
  });

  it('works out the tint and the controls colour', () => {
    expect(tintFactor({ theme: 'fjord', tint: 0 })).toBe(1);
    expect(tintFactor({ theme: 'fjord', tint: 1 })).toBe(3);
    expect(tintFactor({ theme: 'canyon', tint: 1 })).toBe(2);
    expect(lookColour({ theme: 'moss' })).toBe('#98c275');
    expect(lookColour({ theme: 'moss' }, false)).toBe('#52762f');
    expect(lookColour({ theme: 'moss', accent: '#112233' })).toBe('#112233');
  });

  it('saves the look on the account once the slider stops, and reads it back', async () => {
    vi.useFakeTimers();
    api.put.mockClear();
    saveLookToAccount({ theme: 'fjord', tint: 0.2 });
    const done = saveLookToAccount({ theme: 'fjord', tint: 0.4 });
    vi.advanceTimersByTime(400);
    await done;
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(api.put.mock.calls[0][1].look).toMatchObject({ theme: 'fjord', tint: 0.4 });
    expect(lookFromAccount({ preferences: { look: { theme: 'moss' } } })).toMatchObject({ theme: 'moss', mode: 'dark' });
    expect(lookFromAccount({ preferences: {} })).toBeNull();
    expect(lookFromAccount(null)).toBeNull();
  });

  it('a failed save never throws', async () => {
    vi.useFakeTimers();
    api.put.mockImplementationOnce(() => Promise.reject(new Error('offline')));
    const done = saveLookToAccount({ theme: 'moss' }, 0);
    vi.advanceTimersByTime(0);
    await expect(done).resolves.toBeNull();
  });
});
