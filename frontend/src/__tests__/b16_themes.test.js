import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const STYLES = path.resolve(__dirname, '..', 'styles');
const hexes = (body) => Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));
const root = hexes(fs.readFileSync(path.join(STYLES, '00-tokens.css'), 'utf8').split('}')[0]);
const themes = { default: { ...root } };
for (const m of fs.readFileSync(path.join(STYLES, '01-themes.css'), 'utf8').matchAll(/body\.theme-([a-z]+)\s*\{([^}]*)\}/g)) {
  themes[m[1]] = { ...root, ...hexes(m[2]) };
}

function lum(h) {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
function hue(h) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  if (!d) return 0;
  const x = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (x * 60 + 360) % 360;
}
const hueGap = (a, b) => { const d = Math.abs(hue(a) - hue(b)); return Math.min(d, 360 - d); };

describe('UX-33: every theme is readable and its status colours mean the same', () => {
  it('found the themes', () => {
    expect(Object.keys(themes)).toEqual(expect.arrayContaining(['default', 'light', 'crimson', 'sapphire', 'amber']));
  });

  for (const [name, t] of Object.entries(themes)) {
    it(`${name}: text and status colours reach 4.5:1 on the page and on cards`, () => {
      const low = [];
      for (const fg of ['fg', 'muted', 'ok', 'warn', 'crit']) {
        for (const bg of ['bg', 'card']) {
          const r = ratio(t[fg], t[bg]);
          if (r < 4.5) low.push(`${fg} on ${bg}: ${r.toFixed(2)}`);
        }
      }
      expect(low).toEqual([]);
    });

    it(`${name}: OK and critical are clearly different colours`, () => {
      expect(hueGap(t.ok, t.crit)).toBeGreaterThanOrEqual(60);
      expect(hueGap(t.ok2, t.crit)).toBeGreaterThanOrEqual(60); // "healthy" is never red-ish (NUX-4)
      expect(hueGap(t.warn, t.crit)).toBeGreaterThanOrEqual(20);
    });
  }

  it('accent themes keep the standard status colours', () => {
    for (const [name, t] of Object.entries(themes)) {
      if (name === 'light' || name === 'default') continue;
      expect([t.ok, t.ok2, t.warn, t.crit]).toEqual([root.ok, root.ok2, root.warn, root.crit]); // NUX-4: ok2 too
    }
  });

  it('forced-colour mode keeps focus and status dots visible', () => {
    const css = fs.readFileSync(path.join(STYLES, '64-forced-colors.css'), 'utf8');
    expect(css).toContain('@media (forced-colors: active)');
    expect(css).toContain('forced-color-adjust: none');
    expect(fs.readFileSync(path.resolve(__dirname, '..', 'style.css'), 'utf8')).toContain("64-forced-colors.css");
  });
});
