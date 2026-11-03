/** The console's light bar shows what the real bar does: the settings, or an alert, a copy or the night. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(async () => ({})), post: vi.fn(async () => ({})) }, auth: { hasToken: () => true } }));

const { renderLightbar } = await import('../components/led-control.js');
const { applyStats } = await import('../components/dashboard.js');
const { state } = await import('../state.js');

const bar = () => document.getElementById('virtual-chassis-lightbar');

describe('light bar picture', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="virtual-chassis-lightbar"></div>';
  });

  it('paints each effect', () => {
    const cases = [
      [{ mode: 'solid', color: '25c2a0', brightness: 50 }, 'none', '0.5'],
      [{ mode: 'breathe', color: 'ff7800', brightness: 100, speed: 85 }, 'barBreathe', '1'],
      [{ mode: 'flow', color: '0064ff', brightness: 100 }, 'barFlow', '1'],
      [{ mode: 'chase', color: '0064ff' }, 'barFlow', '0.25'],
      [{ mode: 'gradient', color: '00ffff', color2: 'ff0055', brightness: 40 }, 'barFlow', '0.4'],
      [{ mode: 'rainbow', brightness: 35 }, 'barRainbow', '0.35'],
      [{ mode: 'flashing', color: 'ff0000', brightness: 100, speed: 90 }, 'barFlash', '1'],
      [{ color: '#001428', brightness: 8 }, 'none', '0.2'],
    ];
    for (const [look, anim, opacity] of cases) {
      const el = document.createElement('div');
      renderLightbar(el, look);
      expect(el.style.animation.split(' ')[0] || 'none').toBe(anim);
      expect(el.style.opacity).toBe(opacity);
    }
  });

  it('is dark when off, and keeps a running animation when nothing changed', () => {
    const el = bar();
    renderLightbar(el, { power: 'off' }, { offOpacity: 0.15 });
    expect([el.style.opacity, el.style.animation]).toEqual(['0.15', 'none']);
    renderLightbar(el, { power: 'on', brightness: 0 });
    expect(el.style.opacity).toBe('0.2');
    renderLightbar(el, { mode: 'breathe', color: 'ff7800', brightness: 100 });
    el.style.animation = 'kept';
    renderLightbar(el, { mode: 'breathe', color: 'ff7800', brightness: 100 });
    expect(el.style.animation).toBe('kept');
    renderLightbar(el, { mode: 'breathe', color: 'ff7800', brightness: 100 }, { force: true });
    expect(el.style.animation).toContain('barBreathe');
    renderLightbar(null, { power: 'on' });
    renderLightbar(el, null);
  });

  it('follows the stats, but not under the Yak theme', () => {
    state.lcdTheme = 'cyber';
    applyStats({ lightbar: { power: 'on', mode: 'flashing', color: 'ff0000', brightness: 100, speed: 90, why: 'alert' } });
    expect(bar().style.animation).toContain('barFlash');
    applyStats({ lightbar: { power: 'off', why: 'night' } });
    expect(bar().style.opacity).toBe('0.15');
    state.lcdTheme = 'yak';
    bar().style.background = 'rgb(1, 2, 3)';
    applyStats({ lightbar: { power: 'on', mode: 'solid', color: '25c2a0', brightness: 50, why: 'settings' } });
    expect(bar().style.background).toBe('rgb(1, 2, 3)');
    state.lcdTheme = 'cyber';
  });
});
