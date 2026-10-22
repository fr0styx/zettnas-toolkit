import { describe, it, expect, vi } from 'vitest';
import { lazyWindow } from '../lazy-windows.js';
import { OPEN_WINDOWS_KEY } from '../components/dock.js';

describe('lazy windows (FE-02)', () => {
  it('loads the module on first click, then forwards to the real opener', async () => {
    document.body.innerHTML = '<div id="x-icon"></div>';
    const real = vi.fn();
    const init = vi.fn(() => {
      window.openX = real;
    });
    const load = vi.fn(() => Promise.resolve({ initX: init }));
    lazyWindow({ id: 'x', iconId: 'x-icon', load, init: 'initX', globals: ['openX'], openGlobal: 'openX' });
    expect(load).not.toHaveBeenCalled();
    document.getElementById('x-icon').click();
    await vi.waitFor(() => expect(real).toHaveBeenCalledTimes(1));
    await window.openX();
    expect(load).toHaveBeenCalledTimes(1);
    expect(init).toHaveBeenCalledTimes(1);
  });

  it('restores a window that was open before the reload', async () => {
    localStorage.setItem(OPEN_WINDOWS_KEY, JSON.stringify({ windows: { y: { x: 1 } } }));
    const real = vi.fn();
    lazyWindow({
      id: 'y',
      load: () => Promise.resolve({ initY: () => { window.openY = real; } }),
      init: 'initY',
      globals: ['openY'],
      openGlobal: 'openY',
    });
    await vi.waitFor(() => expect(real).toHaveBeenCalled());
    localStorage.removeItem(OPEN_WINDOWS_KEY);
  });
});
