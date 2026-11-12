/** APP-C: Effects as three window looks (Glass, Soft, Solid), corners in plain words, fine controls folded. */
import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const P = await import('../components/wallpaper-pane.js');
const { applyGlassSettings } = await import('../components/wallpapers.js');

function pane() {
  document.body.removeAttribute('data-performance-mode');
  document.body.innerHTML = `
    <span id="glass-blur-val"></span><input type="range" id="glass-blur-slider" min="0" max="40" value="24">
    <span id="glass-opacity-val"></span><input type="range" id="glass-opacity-slider" min="30" max="95" value="72">
    <input type="checkbox" id="window-glow-toggle">
    <div role="radiogroup">
      <button data-window-style="glass"></button><button data-window-style="soft"></button><button data-window-style="solid"></button>
    </div>
    <div id="effects-custom-note" hidden></div>
    <button class="window-radius-btn active" data-radius="12px"></button><button class="window-radius-btn" data-radius="20px"></button>
    <button id="glass-reset-btn"></button>`;
  P.initGlassControls();
}
const look = (n) => document.querySelector(`[data-window-style="${n}"]`);
const checked = () => [...document.querySelectorAll('[data-window-style][aria-checked="true"]')].map((b) => b.dataset.windowStyle);

describe('Effects: window looks', () => {
  beforeEach(() => {
    localStorage.clear();
    pane();
  });

  it('names a look from its settings', () => {
    expect(P.windowStyleOf({ blur: 24, opacity: 72, eco: false })).toBe('glass');
    expect(P.windowStyleOf({ blur: 12, opacity: 88, eco: false })).toBe('soft');
    expect(P.windowStyleOf({ blur: 3, opacity: 40, eco: true })).toBe('solid');
    expect(P.windowStyleOf({ blur: 30, opacity: 72, eco: false })).toBe('');
  });

  it('starts on Glass, one Tab stop', () => {
    expect(checked()).toEqual(['glass']);
    expect(look('glass').getAttribute('tabindex')).toBe('0');
    expect(look('soft').getAttribute('tabindex')).toBe('-1');
  });

  it('Soft sets its blur and opacity and keeps the corners and glow', () => {
    document.getElementById('window-glow-toggle').checked = true;
    document.querySelector('[data-radius="20px"]').click?.();
    applyGlassSettings(24, 72, '20px', true, true);
    look('soft').click();
    expect(document.getElementById('glass-blur-slider').value).toBe('12');
    expect(localStorage.getItem('kiboto_glass_opacity')).toBe('88');
    expect(localStorage.getItem('kiboto_window_radius')).toBe('20px');
    expect(localStorage.getItem('kiboto_window_glow')).toBe('true');
    expect(checked()).toEqual(['soft']);
  });

  it('a slider moved to a mix of your own unchecks every look and shows the note', () => {
    const blur = document.getElementById('glass-blur-slider');
    blur.value = '30';
    blur.dispatchEvent(new Event('input'));
    expect(checked()).toEqual([]);
    expect(document.getElementById('effects-custom-note').hidden).toBe(false);
    expect(look('glass').getAttribute('tabindex')).toBe('0');
  });

  it('moving a slider while Solid lets go of Eco mode, so the change shows', () => {
    look('solid').click();
    expect(checked()).toEqual(['solid']);
    const op = document.getElementById('glass-opacity-slider');
    op.value = '88';
    op.dispatchEvent(new Event('input'));
    expect(document.body.hasAttribute('data-performance-mode')).toBe(false);
  });

  it('arrow keys move through the looks and wrap', () => {
    look('glass').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(checked()).toEqual(['soft']);
    expect(document.activeElement).toBe(look('soft'));
    look('soft').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    look('glass').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    expect(checked()).toEqual(['solid']);
    look('solid').dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    expect(checked()).toEqual(['solid']);
  });

  it('a saved Eco mode opens on Solid; Reset goes back to Glass', () => {
    localStorage.setItem('kiboto_eco_mode', 'true');
    pane();
    expect(checked()).toEqual(['solid']);
    document.getElementById('glass-reset-btn').click();
    expect(checked()).toEqual(['glass']);
    expect(localStorage.getItem('kiboto_eco_mode')).toBe(null);
  });

  it('an unknown look does nothing', () => {
    P.chooseWindowStyle('neon');
    expect(checked()).toEqual(['glass']);
  });
});

describe('Effects: the markup', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');
  it('three looks, corners in words, fine controls folded, no Eco switch', () => {
    for (const n of ['glass', 'soft', 'solid']) expect(html).toContain(`data-window-style="${n}"`);
    expect(html).toContain('data-i18n="effects.extra_round"');
    expect(html).toMatch(/<details class="drawer-card gls-box effects-fine">[\s\S]*id="glass-blur-slider"[\s\S]*id="window-glow-toggle"[\s\S]*<\/details>/);
    expect(html).not.toContain('eco-mode-toggle');
    expect(html).not.toContain('Sharp (6px)');
  });
});
