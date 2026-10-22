import { describe, it, expect } from 'vitest';
import { installWindowFocus } from '../window-focus.js';

function makeDock() {
  const dock = {
    windows: {},
    register(id, el) { this.windows[id] = { el, minimized: false, closed: false }; el.style.display = 'flex'; },
    restore(id) { this.windows[id].minimized = false; this.windows[id].el.style.display = 'flex'; },
    minimize(id) { this.windows[id].minimized = true; this.windows[id].el.style.display = 'none'; },
    unregister(id) { this.windows[id].el.style.display = 'none'; delete this.windows[id]; },
    closeWindow(id) { this.unregister(id); },
  };
  installWindowFocus(dock);
  return dock;
}
const frame = () => new Promise((r) => setTimeout(r, 20));

describe('window focus (FE-11)', () => {
  it('moves focus into a window on open and back to the opener on close', async () => {
    document.body.innerHTML = `<button id="opener">Open</button>
      <div id="w" class="os-window" style="display:none"><div class="os-window-header"><button>x</button></div>
      <div class="os-window-body"><input id="first"></div></div>`;
    const dock = makeDock();
    document.getElementById('opener').focus();
    dock.register('w', document.getElementById('w'));
    await frame();
    expect(document.activeElement.id).toBe('first');
    dock.minimize('w');
    expect(document.activeElement.id).toBe('opener');
  });

  it('Esc closes the top window but not while typing', async () => {
    document.body.innerHTML = `<div id="w" class="os-window"><div class="os-window-body"><input id="i"><button id="b">b</button></div></div>`;
    const dock = makeDock();
    dock.register('w', document.getElementById('w'));
    await frame();
    document.getElementById('i').focus();
    document.getElementById('i').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(dock.windows.w).toBeTruthy();
    document.getElementById('b').focus();
    document.getElementById('b').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(dock.windows.w).toBeUndefined();
  });
});

describe('window focus: Esc handled elsewhere', () => {
  it('does not close the window underneath when another handler already closed one', async () => {
    document.body.innerHTML = `<div id="a" class="os-window" style="z-index:10"><button id="ba">a</button></div>
      <div id="b" class="os-window" style="z-index:20"><button id="bb">b</button></div>`;
    const dock = makeDock();
    dock.register('a', document.getElementById('a'));
    dock.register('b', document.getElementById('b'));
    await frame();
    // window b closes itself on Esc (without preventDefault), like some existing windows do
    document.getElementById('b').addEventListener('keydown', (e) => {
      if (e.key === 'Escape') dock.unregister('b');
    });
    document.getElementById('bb').focus();
    document.getElementById('bb').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(dock.windows.b).toBeUndefined();
    expect(dock.windows.a).toBeTruthy();
  });
});
