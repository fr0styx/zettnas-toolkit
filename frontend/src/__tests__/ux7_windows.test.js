import { describe, it, expect } from 'vitest';
import { labelWindow } from '../window-focus.js';

describe('window semantics (UX-7)', () => {
  it('a window is a region named by its title, which is a heading', () => {
    document.body.innerHTML = '<div id="fm" class="os-window"><div class="os-window-header"><div class="os-window-title"><span>File Explorer</span></div></div></div>';
    const win = document.getElementById('fm');
    labelWindow(win);
    const title = win.querySelector('.os-window-title');
    expect(win.getAttribute('role')).toBe('region');
    expect(win.getAttribute('aria-labelledby')).toBe(title.id);
    expect(title.getAttribute('role')).toBe('heading');
    expect(title.getAttribute('aria-level')).toBe('2');
    labelWindow(win); // once only
    expect(win.getAttribute('aria-labelledby')).toBe(title.id);
  });

  it('keeps what a window already says about itself', () => {
    document.body.innerHTML = '<div id="d" role="dialog" aria-label="Setup"><h2 class="smart-modal-title" id="t">Setup</h2></div><div id="bare"></div>';
    labelWindow(document.getElementById('d'));
    expect(document.getElementById('d').getAttribute('role')).toBe('dialog');
    expect(document.getElementById('d').hasAttribute('aria-labelledby')).toBe(false);
    expect(document.getElementById('t').hasAttribute('role')).toBe(false);
    labelWindow(document.getElementById('bare'));
    expect(document.getElementById('bare').getAttribute('role')).toBe('region');
    labelWindow(null);
  });

  it('the app has one main landmark', async () => {
    const fs = await import('node:fs');
    const html = fs.readFileSync('frontend/index.html', 'utf8') + fs.readFileSync('frontend/src/windows/management-window.html', 'utf8');
    expect((html.match(/<main\b/g) || []).length).toBe(1);
  });
});

describe('opening a window moves focus into it (UX-8)', () => {
  it('skips SVG icons, which have an href but cannot take focus', async () => {
    const { focusWindow } = await import('../window-focus.js');
    document.body.innerHTML = '<button id="opener">open</button><div id="w" class="os-window"><svg><use href="#i-x"></use></svg><button id="first">Go</button></div>';
    document.getElementById('opener').focus();
    focusWindow(document.getElementById('w'));
    expect(document.activeElement.id).toBe('first');
  });

  it('the focus trap does the same', async () => {
    const { trapFocus } = await import('../utils.js');
    document.body.innerHTML = '<div id="d"><button id="a">a</button><svg><use href="#i-y"></use></svg><button id="b">b</button></div>';
    const d = document.getElementById('d');
    trapFocus(d);
    document.getElementById('b').focus();
    d.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    expect(document.activeElement.id).toBe('a');
  });
});

describe('a window without a place opens below the top bar', () => {
  it('centres an unplaced desktop window and leaves placed ones alone', async () => {
    const { placeIfUnplaced } = await import('../window-focus.js');
    document.body.className = '';
    document.body.innerHTML = '<div id="a" class="os-window"></div><div id="b" class="os-window" style="top: 120px; left: 40px"></div><div id="c"></div>';
    Object.defineProperty(window, 'innerWidth', { value: 1440, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 900, configurable: true });
    placeIfUnplaced(document.getElementById('a'));
    expect(parseInt(document.getElementById('a').style.top, 10)).toBeGreaterThanOrEqual(56);
    placeIfUnplaced(document.getElementById('b'));
    expect(document.getElementById('b').style.top).toBe('120px');
    placeIfUnplaced(document.getElementById('c'));
    expect(document.getElementById('c').style.top).toBe('');
    document.body.classList.add('mobile-mode');
    const d = document.createElement('div'); d.className = 'os-window'; document.body.appendChild(d);
    placeIfUnplaced(d);
    expect(d.style.top).toBe('');
  });
});
