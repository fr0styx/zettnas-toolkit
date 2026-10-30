import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { serverJson, serverStrings, LANGS } from '../../scripts/server-locales.mjs';

describe("the server's copy of its strings (NUX-3)", () => {
  it.each(LANGS)('backend/locales/%s.json matches the interface (run node frontend/scripts/server-locales.mjs)', async (lang) => {
    const all = (await import(`../locales/${lang}.js`)).default;
    expect(readFileSync(`backend/locales/${lang}.json`, 'utf-8')).toBe(serverJson(all));
  });

  it('copies only what the server sends', () => {
    expect(serverStrings({ 'alert.x.title': 'a', 'dh.label.ok': 'b', 'fm.places': 'c' })).toEqual({ 'alert.x.title': 'a', 'dh.label.ok': 'b' });
  });
});
