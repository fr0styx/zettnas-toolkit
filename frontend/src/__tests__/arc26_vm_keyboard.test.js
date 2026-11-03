/** ARC-26: keys and paste reach the VM through the console's VNC client. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const rfbs = [];
vi.mock('@novnc/novnc', () => {
  class FakeRfb extends EventTarget {
    constructor(target, url) {
      super();
      this.target = target;
      this.url = url;
      this.keys = [];
      this.pasted = [];
      rfbs.push(this);
    }
    sendKey(keysym, code, down) { this.keys.push([keysym, code, down]); }
    clipboardPasteFrom(text) { this.pasted.push(text); }
    disconnect() { this.gone = true; }
    focus() { this.focused = true; }
  }
  return { default: FakeRfb };
});
vi.mock('../api.js', () => ({
  api: { get: vi.fn().mockResolvedValue({}), post: vi.fn().mockResolvedValue({}), delete: vi.fn() },
  auth: { hasToken: vi.fn().mockReturnValue(true), getToken: vi.fn(() => 'x') },
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const { showToast } = await import('../toast.js');
const { openVmConsole } = await import('../components/vm-manager.js');
const C = await import('../components/vm/console.js');

const key = (k, extra = {}) => {
  const e = new KeyboardEvent('keydown', { key: k, cancelable: true, ...extra });
  C._handleRfbKeyFallback(e);
  return e;
};

describe('VM console keyboard and paste', () => {
  let rfb;
  beforeEach(async () => {
    vi.useRealTimers();
    document.body.innerHTML = '';
    vi.clearAllMocks();
    openVmConsole('vm1', 'files', 'gui');
    await vi.waitFor(() => expect(C._activeRfb).toBeTruthy());
    rfb = C._activeRfb;
    rfb.keys.length = 0;
  });
  afterEach(() => {
    document.getElementById('vm-console-window')?.remove();
  });

  it('special keys go as key presses with their codes', async () => {
    vi.useFakeTimers();
    const e = key('Enter');
    expect(e.defaultPrevented).toBe(true);
    expect(rfb.keys[0]).toEqual([0xff0d, 'Enter', true]);
    vi.advanceTimersByTime(50);
    expect(rfb.keys[1]).toEqual([0xff0d, 'Enter', false]);
    key('F12');
    key(' ');
    expect(rfb.keys.map((k) => k[1])).toEqual(expect.arrayContaining(['F12', 'Space']));
  });

  it('Ctrl+C and other Ctrl combinations hold Control around the key', () => {
    vi.useFakeTimers();
    key('c', { ctrlKey: true });
    expect(rfb.keys.slice(0, 2)).toEqual([[0xffe3, 'ControlLeft', true], [0x63, 'KeyC', true]]);
    vi.advanceTimersByTime(50);
    expect(rfb.keys.at(-1)).toEqual([0xffe3, 'ControlLeft', false]);
    rfb.keys.length = 0;
    key('x', { ctrlKey: true, code: 'KeyX' });
    vi.advanceTimersByTime(50);
    expect(rfb.keys).toEqual([[0xffe3, 'ControlLeft', true], [120, 'KeyX', true], [120, 'KeyX', false], [0xffe3, 'ControlLeft', false]]);
    rfb.keys.length = 0;
    key('z', { ctrlKey: true });
    expect(rfb.keys[1]).toEqual([122, 'KeyZ', true]);
  });

  it('printable characters go as themselves; Alt and Cmd combinations are left alone', () => {
    key('a', { code: 'KeyA' });
    expect(rfb.keys[0]).toEqual([97, 'KeyA', true]);
    rfb.keys.length = 0;
    expect(key('a', { metaKey: true }).defaultPrevented).toBe(false);
    expect(key('a', { altKey: true }).defaultPrevented).toBe(false);
    expect(key('Shift').defaultPrevented).toBe(false);
    expect(rfb.keys).toEqual([]);
  });

  it('paste types the text, with Enter and Tab for line breaks and tabs', async () => {
    vi.useFakeTimers();
    const done = C.pasteTextToGuestConsole('a\tb\r\n');
    await vi.runAllTimersAsync();
    await done;
    expect(rfb.pasted).toEqual(['a\tb\r\n']);
    const downs = rfb.keys.filter((k) => k[2]).map((k) => k[1] ?? String.fromCharCode(k[0]));
    expect(downs).toEqual(['a', 'Tab', 'b', 'Enter']);
    expect(showToast.mock.calls.at(-1)[1]).toBe('success');
    await C.pasteTextToGuestConsole('');
  });

  it('the console reacts to the client connecting and dropping', () => {
    rfb.dispatchEvent(new Event('connect'));
    expect(document.getElementById('vm-console-window')).toBeTruthy();
    const drop = new Event('disconnect');
    drop.detail = { clean: false };
    rfb.dispatchEvent(drop);
    const sec = new Event('securityfailure');
    sec.detail = { reason: 'bad password' };
    rfb.dispatchEvent(sec);
    expect(document.getElementById('vm-console-banner')).toBeTruthy();
  });
});
