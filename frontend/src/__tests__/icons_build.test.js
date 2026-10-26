// PERF-8: emoji in index.html and the window templates become icons when the app is built.
// The result must be what the page's own converter makes of the same markup, and the page
// must not walk that markup again.
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { iconizeDocument, iconizeFragment } from '../../scripts/icons-build.mjs';
import { iconizeTree, startIconizer, stopIconizer } from '../icons.js';
import { BUILT_ATTR } from '../icons-rules.js';

const FRONTEND = path.resolve(__dirname, '..', '..');
const read = (rel) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

/** The DOM as markup, with the run wrappers and build marks taken out (they only group). */
function normalise(root) {
  root.querySelectorAll('span.zi-run').forEach((s) => s.replaceWith(...s.childNodes));
  root.querySelectorAll(`[${BUILT_ATTR}]`).forEach((el) => el.removeAttribute(BUILT_ATTR));
  root.removeAttribute?.(BUILT_ATTR);
  return root.innerHTML;
}

function bodyOf(html) {
  return new DOMParser().parseFromString(html, 'text/html').body;
}

describe('icons at build time', () => {
  afterEach(() => {
    stopIconizer();
    document.body.innerHTML = '';
  });

  it.each([['src/windows/drawer.html'], ['src/windows/management-window.html']])(
    '%s converts the same as in the page',
    (rel) => {
      const src = read(rel);
      const inPage = document.createElement('div');
      inPage.innerHTML = src;
      iconizeTree(inPage);
      const built = document.createElement('div');
      built.innerHTML = iconizeFragment(src);
      expect(built.querySelectorAll('svg.zi, span.zi-dot').length).toBeGreaterThan(5);
      expect(normalise(built)).toBe(normalise(inPage));
    },
    20000, // the management window is 500 kB, converted twice: slow when the whole suite runs in parallel
  );

  it('index.html converts the same as in the page', () => {
    const src = read('index.html');
    const inPage = bodyOf(src);
    document.adoptNode(inPage);
    iconizeTree(inPage);
    const built = bodyOf(iconizeDocument(src));
    expect(built.hasAttribute(BUILT_ATTR)).toBe(true);
    expect(normalise(built)).toBe(normalise(inPage));
  });

  it('changes only the emoji: the rest of the source stays as written', () => {
    const src = '<div class="a">\n  <button title="🗑️ Delete">🗑️</button>\n  <pre>📁 kept</pre>\n  <span>📁 Shares &amp; more</span>\n</div>\n';
    const out = iconizeFragment(src);
    expect(out).toContain('<div data-icons-built class="a">\n  <button title="Delete" aria-label="Delete">');
    expect(out).toContain('<pre>📁 kept</pre>');
    expect(out).toContain('<span class="zi-run"><svg class="zi" data-zi="folder"');
    expect(out).toContain(' Shares &amp; more</span></span>\n</div>\n');
  });

  it('the page does not walk markup converted at build time, but converts what is added to it later', async () => {
    document.body.innerHTML = '<div id="w" data-icons-built><span id="s">📁 left as built</span></div>';
    startIconizer();
    expect(document.querySelectorAll('svg.zi').length).toBe(0);
    const added = document.createElement('span');
    added.textContent = '📁 Shares';
    document.getElementById('w').appendChild(added);
    await Promise.resolve();
    expect(added.querySelector('svg.zi')?.dataset.zi).toBe('folder');
  });
});
