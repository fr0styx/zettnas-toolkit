import { describe, it, expect } from 'vitest';
import { withoutComments, withoutIndent } from '../../../vite.config.mjs';

describe('index.html is trimmed at build time (FE-01 budget)', () => {
  it('drops comments, even nested ones, but keeps conditional comments', () => {
    expect(withoutComments('a<!-- note -->\nb')).toBe('ab');
    expect(withoutComments('<!<!-- x -->-- y -->z')).toBe('z');
    expect(withoutComments('<!--[if IE]>x<![endif]-->')).toBe('<!--[if IE]>x<![endif]-->');
  });

  it('drops leading indentation but not where whitespace matters', () => {
    const html = '<div>\n    <span>a</span>\n\t<b>b</b>\n  <pre>\n  keep\n    this</pre>\n  <textarea>\n  x</textarea>\n  <script>\n  const s = `\n    y`;</script>\n  </div>';
    expect(withoutIndent(html)).toBe('<div>\n<span>a</span>\n<b>b</b>\n<pre>\n  keep\n    this</pre>\n<textarea>\n  x</textarea>\n<script>\n  const s = `\n    y`;</script>\n</div>');
    expect(withoutIndent('<PRE>\n  x</PRE>')).toBe('<PRE>\n  x</PRE>');
  });
});
