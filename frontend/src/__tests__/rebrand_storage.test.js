// R1-3: settings saved under zettnas* keys before the Kiboto rebrand move to kiboto* keys on the
// first load, before anything reads them; a backup made before restores under the new names.
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const html = fs.readFileSync(path.resolve(__dirname, '../../index.html'), 'utf8');
const early = html.match(/<script>([\s\S]*?)<\/script>/)[1];

describe('Rebrand storage move', () => {
  it('moves zettnas keys to kiboto keys and keeps a newer value', () => {
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('zettnas_dock_size', 'large');
    localStorage.setItem('zettnas_weather_cache_Berlin', '{"t":1}');
    localStorage.setItem('zettnas_language', 'de');
    localStorage.setItem('kiboto_language', 'fr'); // already set under the new name: it wins
    localStorage.setItem('lcd_theme', 'dark');
    sessionStorage.setItem('zettnas_fm_last_path', '/mnt/user');
    new Function(early)(); // eslint-disable-line no-new-func
    expect(localStorage.getItem('kiboto_dock_size')).toBe('large');
    expect(localStorage.getItem('kiboto_weather_cache_Berlin')).toBe('{"t":1}');
    expect(localStorage.getItem('kiboto_language')).toBe('fr');
    expect(localStorage.getItem('lcd_theme')).toBe('dark');
    expect(sessionStorage.getItem('kiboto_fm_last_path')).toBe('/mnt/user');
    const left = [...Array(localStorage.length).keys()].map((i) => localStorage.key(i)).filter((k) => k.startsWith('zettnas'));
    expect(left).toEqual([]);
    new Function(early)(); // a second load changes nothing
    expect(localStorage.getItem('kiboto_dock_size')).toBe('large');
  });

  it('restores a backup made before under the new names', async () => {
    localStorage.clear();
    const { applyClientPreferences } = await import('../components/settings.js');
    applyClientPreferences({ zettnas_dock_size: 'small', zettnas_token: 'x', kiboto_eco_mode: '1' });
    expect(localStorage.getItem('kiboto_dock_size')).toBe('small');
    expect(localStorage.getItem('kiboto_eco_mode')).toBe('1');
    expect(localStorage.getItem('kiboto_token')).toBeNull();
    expect(localStorage.getItem('zettnas_dock_size')).toBeNull();
  });
});
