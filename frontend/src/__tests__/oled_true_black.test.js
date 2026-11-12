/** True black (owner, 12 Nov): it changed only the tab strip; now windows, bars and cards go black. */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const css = readFileSync(resolve(__dirname, '../styles/01-themes.css'), 'utf8');

describe('True black', () => {
  it('sets the surface colours the panels read since APP-A', () => {
    const block = css.slice(css.indexOf('body.theme-oled {'), css.indexOf('}', css.indexOf('body.theme-oled {')));
    for (const v of ['--c-bg:', '--c-raised:', '--c-neutral-soft:']) expect(block).toContain(v);
  });

  it('draws windows, bars, the dock, widgets and window headers solid, with no glass', () => {
    const rule = css.slice(css.indexOf('body.theme-oled:not(.theme-light) :is(.os-window'));
    for (const sel of ['.management-window', '.suite-navbar', '.os-dock', '.desktop-widget', '.smart-modal-header']) expect(rule.split('{')[0]).toContain(sel);
    expect(rule).toContain('background: var(--c-bg) !important');
    expect(rule).toContain('backdrop-filter: none !important');
    expect(css).toContain('body.theme-oled:not(.theme-light) :is(.drawer-card, .network-card, .mgmt-app-card)');
  });
});
