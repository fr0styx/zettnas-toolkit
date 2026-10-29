import { describe, it, expect, vi, beforeEach } from 'vitest';
import { initA11y, onMenuKey } from '../a11y.js';
import { installDomActions } from '../dom-actions.js';
import { trapFocus, isEscSafeField } from '../utils.js';
import { focusStep } from '../components/setup-wizard.js';

describe('UX-31: Enter fires a data-action element once', () => {
  it('one activation path', () => {
    initA11y();
    installDomActions();
    document.body.innerHTML = '<div id="act" role="button" tabindex="0" data-action="click-target" data-target="tgt">Go</div><button id="tgt">t</button>';
    const tgt = document.getElementById('tgt');
    const clicks = vi.fn();
    tgt.addEventListener('click', clicks);
    const act = document.getElementById('act');
    act.focus();
    act.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    expect(clicks).toHaveBeenCalledTimes(1);
  });
});

describe('UX-29: Shift+F10 opens the focused thing\'s menu', () => {
  it('sends a contextmenu event to the focused element', () => {
    document.body.innerHTML = '<div id="row" tabindex="0">file.txt</div>';
    const row = document.getElementById('row');
    const opened = vi.fn((e) => e.preventDefault());
    row.addEventListener('contextmenu', opened);
    row.focus();
    const e = new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true });
    onMenuKey(e);
    expect(opened).toHaveBeenCalledTimes(1);
    expect(e.defaultPrevented).toBe(true);
    const f = new KeyboardEvent('keydown', { key: 'F10', bubbles: true, cancelable: true });
    onMenuKey(f);
    expect(opened).toHaveBeenCalledTimes(1);
  });
});

describe('UX-30: windows and fields', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('Esc in a field leaves the field first, a second Esc closes', () => {
    document.body.innerHTML = '<div id="win"><input id="name" value="half typed"><button id="b">ok</button></div>';
    const win = document.getElementById('win');
    const close = vi.fn();
    trapFocus(win, close);
    const input = document.getElementById('name');
    input.focus();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    expect(close).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(win);
    win.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    expect(close).toHaveBeenCalledTimes(1);
  });

  it('a window does not trap Tab', () => {
    document.body.innerHTML = '<div id="win"><button id="a">a</button><button id="z">z</button></div>';
    const win = document.getElementById('win');
    trapFocus(win, null, { trap: false });
    const z = document.getElementById('z');
    z.focus();
    const e = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    z.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(false);
  });

  it('search boxes keep Esc for closing', () => {
    document.body.innerHTML = '<input id="s" role="combobox"><input id="q" type="search"><input id="c" type="checkbox"><textarea id="t"></textarea>';
    expect(isEscSafeField(document.getElementById('s'))).toBe(false);
    expect(isEscSafeField(document.getElementById('q'))).toBe(false);
    expect(isEscSafeField(document.getElementById('c'))).toBe(false);
    expect(isEscSafeField(document.getElementById('t'))).toBe(true);
  });
});

describe('UX-34: the wizard moves focus to each step', () => {
  it('focuses the step heading and says which step', () => {
    vi.useFakeTimers();
    document.body.innerHTML = '<section id="s2"><h3>Password</h3><input></section>';
    focusStep([document.getElementById('s2')], 2, 6);
    expect(document.activeElement.tagName).toBe('H3');
    vi.advanceTimersByTime(50);
    expect(document.getElementById('a11y-live-announcer').textContent).toBe('Step 2 of 6');
    vi.useRealTimers();
  });
});

describe('UX-30: dialogs that must be answered have no Minimize', () => {
  it('modal: no minimize; a guide that opts in keeps it', async () => {
    const { upgradeDialog } = await import('../dialog-chrome.js');
    const make = (attrs) => {
      const host = document.createElement('div');
      host.className = 'smart-modal-backdrop';
      host.innerHTML = `<div class="smart-modal-window" role="dialog" ${attrs}><div class="smart-modal-header"><span>T</span></div><div class="smart-modal-body"></div></div>`;
      document.body.appendChild(host);
      const win = host.querySelector('.smart-modal-window');
      upgradeDialog(win);
      return win;
    };
    expect(make('aria-modal="true"').querySelector('.min-btn')).toBeNull();
    expect(make('aria-modal="true" data-minimizable').querySelector('.min-btn')).not.toBeNull();
    expect(make('').querySelector('.min-btn')).not.toBeNull();
  });
});
