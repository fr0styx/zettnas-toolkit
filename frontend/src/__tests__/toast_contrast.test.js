import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { showToast } from '../toast.js';

// relative luminance contrast, WCAG 2
function lum(hex) {
  const c = hex.match(/[0-9a-f]{2}/gi).map((h) => parseInt(h, 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

describe('toast headings are readable on the light theme (UX-27)', () => {
  it('uses theme colours, and the light ones reach 4.5:1 on the light toast', () => {
    document.body.innerHTML = '';
    showToast('Could not save.', 'error');
    expect(document.querySelector('.top-toast-item').innerHTML).toContain('var(--zn-toast-err)');
    const css = fs.readFileSync(path.resolve(__dirname, '..', 'styles', '18-toasts-dialogs.css'), 'utf8');
    const light = css.match(/body\.theme-light \{([^}]*)\}/)[1];
    for (const m of light.matchAll(/--zn-toast-\w+:\s*(#[0-9a-f]{6})/gi)) {
      expect(ratio(m[1], '#f6f7f9')).toBeGreaterThanOrEqual(4.5);
    }
  });
});
