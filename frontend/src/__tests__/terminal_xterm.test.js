import { describe, it, expect, vi, beforeEach } from 'vitest';

const instances = [];
let failOpen = false;

vi.mock('@xterm/xterm', () => {
  class FakeTerminal {
    constructor(opts) {
      this.opts = opts;
      this.writes = [];
      this.cols = 100;
      this.rows = 30;
      this._data = [];
      this._resize = [];
      this.disposed = false;
      instances.push(this);
    }
    loadAddon(a) { this.addon = a; }
    open(el) {
      if (failOpen) throw new Error('matchMedia missing');
      this.el = el;
    }
    write(d) { this.writes.push(d); }
    onData(cb) { this._data.push(cb); }
    onBinary() {}
    onResize(cb) { this._resize.push(cb); }
    reset() { this.writes = []; }
    focus() { this.focused = true; }
    dispose() { this.disposed = true; }
    emitData(d) { this._data.forEach((cb) => cb(d)); }
    emitResize(cols, rows) { this.cols = cols; this.rows = rows; this._resize.forEach((cb) => cb({ cols, rows })); }
  }
  return { Terminal: FakeTerminal };
});
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }));
vi.mock('@xterm/xterm/css/xterm.css', () => ({}));

import { createTerminalView, stripAnsi } from '../components/terminal-view.js';

const host = () => {
  const el = document.createElement('div');
  document.body.appendChild(el);
  return el;
};

describe('terminal-view', () => {
  beforeEach(() => {
    instances.length = 0;
    failOpen = false;
    document.body.innerHTML = '';
  });

  it('shows text immediately, then replays it into xterm once loaded', async () => {
    const el = host();
    const view = createTerminalView(el);
    view.write('hello \x1b[32mworld\x1b[0m\r\n');
    expect(el.textContent).toContain('hello world');
    expect(await view.ready).toBe(true);
    const term = instances[0];
    expect(term.el).toBeTruthy();
    expect(term.writes).toEqual(['hello \x1b[32mworld\x1b[0m\r\n']);
    expect(el.querySelector('.zt-terminal-fallback')).toBeNull();
  });

  it('passes bytes straight to xterm and forwards input and resizes', async () => {
    const onData = vi.fn();
    const onResize = vi.fn();
    const view = createTerminalView(host(), { onData, onResize });
    await view.ready;
    const bytes = new TextEncoder().encode('é');
    view.write(bytes.buffer);
    expect(instances[0].writes.at(-1)).toBeInstanceOf(Uint8Array);
    expect(Array.from(instances[0].writes.at(-1))).toEqual(Array.from(bytes));
    instances[0].emitData('ls\r');
    instances[0].emitResize(120, 40);
    expect(onData).toHaveBeenCalledWith('ls\r');
    expect(onResize).toHaveBeenCalledWith(120, 40);
    expect(view.size()).toEqual({ cols: 120, rows: 40 });
  });

  it('keeps key events inside the terminal (Esc/Tab must not reach dialogs)', () => {
    const el = host();
    const outer = vi.fn();
    document.body.addEventListener('keydown', outer);
    createTerminalView(el);
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(outer).not.toHaveBeenCalled();
  });

  it('falls back to plain text when xterm cannot start, decoding split UTF-8', async () => {
    failOpen = true;
    const el = host();
    const view = createTerminalView(el);
    expect(await view.ready).toBe(false);
    const bytes = new TextEncoder().encode('ok ✓');
    view.write(bytes.slice(0, 4));
    view.write(bytes.slice(4));
    expect(el.textContent).toBe('ok ✓');
    expect(instances[0].disposed).toBe(true);
  });

  it('strips ANSI and control codes for the plain-text view', () => {
    expect(stripAnsi('\x1b[1;31mred\x1b[0m\r\nnext\x07\x1b]0;title\x07')).toBe('red\nnext');
  });
});

describe('container terminal over WebSocket', () => {
  let sockets;

  beforeEach(() => {
    instances.length = 0;
    failOpen = false;
    sockets = [];
    class FakeWs {
      constructor(url) {
        this.url = url;
        this.readyState = 1;
        this.sent = [];
        sockets.push(this);
      }
      send(d) { this.sent.push(d); }
      close() { this.readyState = 3; }
    }
    FakeWs.OPEN = 1;
    vi.stubGlobal('WebSocket', FakeWs);
  });

  it('uses binary frames, sends its size, and pipes keystrokes as bytes', async () => {
    const mod = await import('../components/container-modal.js');
    mod.initContainerModal();
    mod.connectContainerTerminalWs('abc123');
    const ws = sockets[0];
    expect(ws.url).toContain('/api/docker/containers/abc123/terminal/ws');
    expect(ws.binaryType).toBe('arraybuffer');

    await new Promise((r) => setTimeout(r, 0));
    const term = instances.at(-1);
    ws.onopen();
    expect(JSON.parse(ws.sent[0])).toEqual({ type: 'resize', cols: term.cols, rows: term.rows });

    ws.onmessage({ data: new TextEncoder().encode('root@abc:/# ').buffer });
    expect(new TextDecoder().decode(term.writes.at(-1))).toBe('root@abc:/# ');

    term.emitData('\x1b');
    expect(ws.sent.at(-1)).toBeInstanceOf(Uint8Array);
    expect(new TextDecoder().decode(ws.sent.at(-1))).toBe('\x1b');
  });
});

describe('VM serial key mapping', () => {
  it('maps keys forwarded by the console key guard', async () => {
    const { serialKeyToData } = await import('../components/vm-manager.js');
    expect(serialKeyToData({ key: 'Enter' })).toBe('\r');
    expect(serialKeyToData({ key: 'Backspace' })).toBe('\x7f');
    expect(serialKeyToData({ key: 'ArrowUp' })).toBe('\x1b[A');
    expect(serialKeyToData({ key: 'c', ctrlKey: true })).toBe('\x03');
    expect(serialKeyToData({ key: 'x' })).toBe('x');
    expect(serialKeyToData({ key: 'Shift' })).toBeNull();
  });
});
