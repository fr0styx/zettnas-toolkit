/** NUX-20: the VM console's status pill, reconnect banner and toolbar read as plain, translatable words. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { openVmConsole, setConsoleFocus, cancelConsoleReconnect } from '../components/vm-manager.js';
import { setConsoleStatus, _scheduleConsoleReconnect } from '../components/vm/console.js';

vi.mock('../api.js', () => ({
  api: { get: vi.fn().mockResolvedValue({}), post: vi.fn().mockResolvedValue({}), delete: vi.fn() },
  auth: { hasToken: vi.fn().mockReturnValue(true), getToken: vi.fn(() => 'x') },
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const pill = () => document.getElementById('vm-console-status-pill');
const bannerText = () => document.getElementById('vm-console-banner').textContent;
const button = (label) => [...document.querySelectorAll('#vm-console-banner .btn-banner-act')].find((b) => b.textContent === label);

describe('console status pill (NUX-20)', () => {
  it('names every state with its colour, and skips a missing pill', () => {
    const el = document.createElement('span');
    const cases = [
      ['live', 'Live', 'ok'],
      ['connecting', 'Connecting…', 'warn'],
      ['disconnected', 'Disconnected', 'crit'],
      ['tty_connecting', 'Terminal connecting…', 'warn'],
      ['tty_live', 'Terminal live', 'ok'],
      ['tty_closed', 'Terminal closed', 'crit'],
      ['tty_error', 'Terminal error', 'crit'],
    ];
    for (const [kind, words, tone] of cases) {
      setConsoleStatus(el, kind);
      expect(el.textContent).toBe(`● ${words}`);
      expect(el.style.color).toBe(`var(--kb-text-${tone})`);
    }
    setConsoleStatus(el, 'reconnecting', { s: 3 });
    expect(el.textContent).toBe('● Reconnecting (3 s)…');
    expect(() => setConsoleStatus(null, 'live')).not.toThrow();
  });
});

describe('console window (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.body.className = '';
  });
  afterEach(() => {
    cancelConsoleReconnect();
    vi.useRealTimers();
  });

  it('labels the toolbar and the keyboard state', () => {
    openVmConsole('vc1', 'files', 'gui');
    const win = document.getElementById('vm-console-window');
    expect(win.querySelector('#vm-console-title-text').textContent).toContain('VM Console: files');
    expect(win.querySelector('#btn-vnc-keys').textContent.trim()).toBe('Send key ▾');
    expect(win.querySelector('[data-key="Super"]').textContent).toBe('Super / Windows key');
    expect(win.querySelector('[data-key="F12"]').textContent).toBe('F12 (boot menu)');
    expect(win.querySelector('#btn-vnc-clipboard').textContent.trim()).toBe('📋 Paste text');
    expect(win.querySelector('#btn-vnc-reconnect').textContent.trim()).toBe('↻ Reconnect');
    expect(win.querySelector('#btn-vnc-fullscreen').textContent.trim()).toBe('⛶ Full screen');
    setConsoleFocus(false);
    expect(win.querySelector('#vm-console-kbd-pill').getAttribute('title')).toBe('Keyboard released to the desktop. Click the console to capture it.');
    setConsoleFocus(true);
    expect(win.querySelector('#vm-console-kbd-pill').getAttribute('title')).toMatch(/^Keyboard captured/);
  });

  it('counts down, lets you cancel, and gives up after five tries', async () => {
    vi.useFakeTimers();
    openVmConsole('vc2', 'files', 'gui');
    const box = document.getElementById('vm-vnc-container');

    _scheduleConsoleReconnect(box, 'vc2', 'files', 'gui');
    expect(pill().textContent).toBe('● Reconnecting (5 s)…');
    expect(bannerText()).toContain('Connection lost. Reconnecting in 5 s (try 1 of 5)…');
    await vi.advanceTimersByTimeAsync(1000);
    expect(pill().textContent).toBe('● Reconnecting (4 s)…');
    expect(bannerText()).toContain('Reconnecting in 4 s');

    button('Cancel').click();
    expect(pill().textContent).toBe('● Disconnected');
    expect(bannerText()).toContain('Disconnected from the VM console');
    button('Reconnect now').click();
    expect(bannerText()).toContain('Reconnecting to files (try 1 of 5)…');

    for (let i = 0; i < 4; i++) {
      _scheduleConsoleReconnect(box, 'vc2', 'files', 'gui');
      button('Reconnect now').click();
    }
    _scheduleConsoleReconnect(box, 'vc2', 'files', 'gui');
    expect(pill().textContent).toBe('● Disconnected');
    expect(bannerText()).toContain('Lost the connection to files after 5 tries.');
    button('Reconnect now').click();
    expect(pill().textContent).toBe('● Reconnecting (5 s)…');
  });
});
