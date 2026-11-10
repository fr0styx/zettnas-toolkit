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

  it('finds text in code: UI properties, ternaries, fallbacks and setAttribute (NUX-20)', () => {
    const js = [
      "const b = { title: 'Open Folder', label: t('k', 'Translated'), id: 'save-btn', text: busy ? 'Saving…' : 'Save' };",
      "el.textContent = ok ? 'Turned on' : 'Turned off';",
      "el.title = msg || 'No details';",
      "el.textContent = 'Plain';", // counted by the textContent check, not twice
      "btn.setAttribute('aria-label', 'Close window'); btn.setAttribute('data-x', 'Not text');",
      "const u = { label: `${n} MHz`, hint: `${a} • ${b} vCPU • ${c} MB` };",
      "const h = { message: '<b>Bold</b>' };", // markup: the markup check counts it
    ].join('\n');
    expect(textNodes(js, 'a.js')).toEqual(['Open Folder', 'Saving…', 'Save', 'Turned on', 'Turned off', 'No details', 'Close window', 'Bold']);
  });

  it('does not count names, acronyms, units, ids and paths', () => {
    for (const same of ['Kiboto', 'SMART', 'CPU', '2FA', '12 GB', 'eth0', '/mnt/user', 'https://x.y', '°C', 'e.g. 8080']) {
      expect(readable(same), same).toBe(false);
    }
    for (const text of ['Save changes', 'SAVE CHANGES', 'Keep \u0000', 'Revoke', 'TWO-FACTOR AUTH']) {
      expect(readable(text), text).toBe(true);
    }
  });
});
