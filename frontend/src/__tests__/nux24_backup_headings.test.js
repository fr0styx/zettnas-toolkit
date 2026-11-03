/** NUX-24: the Backups pane's headings go down one level at a time, for screen-reader navigation. */
import { describe, it, expect } from 'vitest';
import markup from '../windows/management-window.html?raw';

const levels = (root) =>
  [...root.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]')].map((h) => Number(h.getAttribute('aria-level') || h.tagName.slice(1)));

describe('Backups pane headings', () => {
  it('start at 2 and never skip a level', () => {
    const doc = new DOMParser().parseFromString(markup, 'text/html');
    const pane = doc.getElementById('mgmt-pane-backups');
    const seen = levels(pane);
    expect(seen[0]).toBe(2);
    expect(seen.length).toBeGreaterThan(4);
    seen.forEach((lvl, i) => {
      if (i) expect(lvl - seen[i - 1]).toBeLessThanOrEqual(1);
    });
  });
});
