/**
 * UX-21: the translation lint sees the text between tags, ALL-CAPS labels and text around ${},
 * and leaves alone what is the same in every language.
 */
import { describe, it, expect } from 'vitest';
import { readable, textNodes } from '../../scripts/i18n-text.mjs';

describe('i18n text nodes (UX-21)', () => {
  it('finds text between tags in markup', () => {
    const html = '<div><label>Display name</label><span data-i18n="x">Done</span><code>rm -rf</code><b data-sample>Monday</b></div>';
    expect(textNodes(html, 'a.html')).toEqual(['Display name']);
  });

  it('finds text in JS templates and markup strings, holes included', () => {
    const js = [
      "el.innerHTML = `<td>Loading users...</td><td>${n} files selected</td><td>${escapeHtml(t('k', 'ok'))}</td>`;",
      "el.innerHTML = '<span>THIS DEVICE</span>';",
      "el.innerHTML = '<!-- Header --><b>' + name + '</b>';",
      "const x = a > b && c < d;",
    ].join('\n');
    expect(textNodes(js, 'a.js')).toEqual(['Loading users...', '${…} files selected', 'THIS DEVICE']);
  });

  it('does not count names, acronyms, units, ids and paths', () => {
    for (const same of ['ZettNAS', 'SMART', 'CPU', '2FA', '12 GB', 'eth0', '/mnt/user', 'https://x.y', '°C', 'e.g. 8080']) {
      expect(readable(same), same).toBe(false);
    }
    for (const text of ['Save changes', 'SAVE CHANGES', 'Keep \u0000', 'Revoke', 'TWO-FACTOR AUTH']) {
      expect(readable(text), text).toBe(true);
    }
  });
});
