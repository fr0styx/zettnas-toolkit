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

describe('window focus: Esc closes the top window only when nothing else used it', () => {
  const press = (el) => el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  async function oneWindow(extra = '') {
    document.body.innerHTML = `<div id="w" class="os-window"><div class="os-window-body"><button id="b">b</button>
      <div id="menu" class="ctx-menu">menu</div></div></div>${extra}`;
    const dock = makeDock();
    dock.register('w', document.getElementById('w'));
    await frame();
    document.getElementById('b').focus();
    return dock;
  }

  it('a menu that closes on Esc (handled on the document, no preventDefault) keeps its window open', async () => {
    const dock = await oneWindow();
    const onKey = (e) => {
      if (e.key === 'Escape') document.getElementById('menu').classList.add('hidden');
    };
    document.addEventListener('keydown', onKey); // added after the closer, as the File Explorer's is
    press(document.getElementById('b'));
    document.removeEventListener('keydown', onKey);
    expect(document.getElementById('menu').classList.contains('hidden')).toBe(true);
    expect(dock.windows.w).toBeTruthy();
    // the next Esc, with nothing left to close, closes the window
    press(document.getElementById('b'));
    expect(dock.windows.w).toBeUndefined();
  });

  it('a handler that only moves focus used the key too', async () => {
    const dock = await oneWindow('<button id="out">out</button>');
    const onKey = (e) => {
      if (e.key === 'Escape') document.getElementById('out').focus();
    };
    document.addEventListener('keydown', onKey);
    press(document.getElementById('b'));
    document.removeEventListener('keydown', onKey);
    expect(dock.windows.w).toBeTruthy();
  });

  it('a dialog inside a hidden overlay (Spotlight keeps one) does not switch Esc off', async () => {
    const dock = await oneWindow('<div style="display:none"><div role="dialog" aria-modal="true">search</div></div>');
    press(document.getElementById('b'));
    expect(dock.windows.w).toBeUndefined();
  });

  it('a dialog on screen keeps Esc for itself', async () => {
    const dock = await oneWindow('<div role="dialog" aria-modal="true">question</div>');
    press(document.getElementById('b'));
    expect(dock.windows.w).toBeTruthy();
  });

  it('a key marked as handled closes nothing', async () => {
    const dock = await oneWindow();
    const onKey = (e) => e.preventDefault();
    document.addEventListener('keydown', onKey);
    press(document.getElementById('b'));
    document.removeEventListener('keydown', onKey);
    expect(dock.windows.w).toBeTruthy();
  });
});
