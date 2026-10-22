import { describe, it, expect } from 'vitest';
import { enhanceInteractiveElements } from '../a11y.js';

describe('a11y naming (FE-10)', () => {
  it('names icon-only controls from their title and never hides them', () => {
    document.body.innerHTML = `
      <div id="a" class="win-btn" title="Close window"><svg></svg></div>
      <div id="b" class="win-btn"><svg></svg></div>
      <div id="c" class="mgmt-card">Storage pools</div>`;
    enhanceInteractiveElements(document.body);
    const a = document.getElementById('a');
    const b = document.getElementById('b');
    const c = document.getElementById('c');
    expect(a.getAttribute('aria-label')).toBe('Close window');
    expect(b.hasAttribute('aria-hidden')).toBe(false);
    expect(c.hasAttribute('aria-label')).toBe(false); // its visible text is its name
    expect(a.getAttribute('role')).toBe('button');
    expect(a.getAttribute('tabindex')).toBe('0');
  });
});
