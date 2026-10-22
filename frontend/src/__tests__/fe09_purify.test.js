import { describe, it, expect } from 'vitest';
import { sanitizeModalHtml } from '../utils.js';

// FE-09: payloads the old regex filter let through
describe('sanitizeModalHtml (DOMPurify)', () => {
  it.each([
    ['<img src=x onerror=alert(1)>', ''],
    ['<svg><script>alert(1)</script></svg>', ''],
    ['<a href="jav&#x09;ascript:alert(1)">x</a>', '<a>x</a>'],
    ['<b onclick="alert(1)">bold</b>', '<b>bold</b>'],
    ['<div style="background:url(javascript:alert(1))">x</div>', null],
    ['<scr<script>ipt>alert(1)</script>', null],
  ])('neutralises %s', (input, expected) => {
    const out = sanitizeModalHtml(input);
    if (expected !== null) expect(out).toBe(expected);
    const host = document.createElement('div');
    host.innerHTML = out;
    expect(host.querySelector('script, img, svg, iframe')).toBeNull();
    expect(out.toLowerCase()).not.toMatch(/on\w+=|javascript:/);
  });

  it('keeps the formatting toasts use', () => {
    expect(sanitizeModalHtml('<strong>Delete</strong> <code>vm1</code>?<br><ul><li>a</li></ul>')).toBe(
      '<strong>Delete</strong> <code>vm1</code>?<br><ul><li>a</li></ul>'
    );
  });
});
