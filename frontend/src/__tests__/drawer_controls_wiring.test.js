// The LED and fan controls live in the settings drawer, whose markup is inserted after the first
// paint (B6). They must be wired once it arrives: wired at start-up they found no buttons and
// the LED strip and fan buttons did nothing.
import { describe, expect, it, vi } from 'vitest';

vi.mock('../api.js', () => {
  const api = {
    get: vi.fn(async (url) => (url === '/api/led' ? { power: 'on', mode: 'gradient', color: '00ffff', color2: 'ff0055', brightness: 40, speed: 47 } : {})),
    post: vi.fn(async () => ({ status: 'ok' })),
    put: vi.fn(async () => ({ status: 'ok' })),
    delete: vi.fn(async () => ({ status: 'ok' })),
  };
  return { api, default: api, auth: { getToken: () => 'test-token' } };
});

import { api } from '../api.js';
import { ensureDrawerDom, isDrawerDomReady, whenDrawerDom } from '../drawer-dom.js';
import { initFanControl } from '../components/fan-control.js';
import { initLedControl } from '../components/led-control.js';

const settle = () => new Promise((r) => setTimeout(r, 0));

describe('drawer controls are wired when the drawer arrives', () => {
  it('LED buttons and fan profiles reach the API after a late drawer', async () => {
    const warn = vi.spyOn(console, 'warn');
    document.body.innerHTML = '<div id="led-drawer-slot"></div>';
    expect(isDrawerDomReady()).toBe(false);
    const wired = vi.fn(() => {
      initFanControl();
      initLedControl();
    });
    whenDrawerDom(wired);
    expect(wired).not.toHaveBeenCalled();

    await ensureDrawerDom();
    expect(wired).toHaveBeenCalledTimes(1);
    await settle();

    // the saved state shows (not the markup's defaults), all of it
    expect(document.querySelector('#tab-led .effect-btn.active').dataset.effect).toBe('gradient');
    expect(document.querySelector('#tab-led .color-chip.active').dataset.hex).toBe('00ffff');
    expect(document.querySelector('#tab-led .profile-pill.active').dataset.profile).toBe('cyberpunk');
    expect(warn).not.toHaveBeenCalled();

    api.post.mockClear();
    document.querySelector('#tab-led .color-chip[data-hex="ff0000"]').click();
    document.querySelector('#tab-led .effect-btn[data-effect="breathe"]').click();
    await settle();
    const led = api.post.mock.calls.filter(([url]) => url === '/api/led').map(([, body]) => body);
    expect(led.at(-1)).toMatchObject({ power: 'on', color: 'ff0000', mode: 'breathe' });

    // a profile sets mode, colours and brightness in one go
    api.post.mockClear();
    document.querySelector('#tab-led .profile-pill[data-profile="stealth"]').click();
    await settle();
    expect(api.post).toHaveBeenLastCalledWith('/api/led', expect.objectContaining({ mode: 'solid', color: '001428', brightness: 8 }));

    // the Custom swatch never sends an empty colour
    api.post.mockClear();
    document.getElementById('custom-chip-label').click();
    await settle();
    for (const [, body] of api.post.mock.calls) expect(body.color).toMatch(/^[0-9a-f]{6}$/i);
    expect(warn).not.toHaveBeenCalled();

    api.post.mockClear();
    document.querySelector('.fan-profile-btn[data-fan-profile="quiet"]').click();
    await settle();
    expect(api.post.mock.calls.length + api.put.mock.calls.length).toBeGreaterThan(0);

    // a second registration once the drawer is there runs straight away
    const late = vi.fn();
    whenDrawerDom(late);
    expect(late).toHaveBeenCalledTimes(1);
  });
});
