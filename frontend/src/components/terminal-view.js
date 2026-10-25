/**
 * Shared terminal view for the container shell and the VM serial console.
 *
 * Renders with xterm.js (loaded on first use, so the library stays out of the
 * initial bundle). Until xterm is ready, and in environments where it cannot
 * start, output shows as plain text with ANSI codes stripped; once xterm loads
 * it replays everything written so far.
 *
 * write() accepts strings, ArrayBuffers or Uint8Arrays. Bytes go to xterm
 * as-is, so multi-byte UTF-8 characters split across WebSocket frames still
 * render correctly.
 */

const MAX_REPLAY_BYTES = 512 * 1024;

const THEME = {
  background: '#030712',
  foreground: '#e2e8f0',
  cursor: '#34d399',
  cursorAccent: '#030712',
  selectionBackground: 'rgba(56,189,248,0.35)',
  black: '#1e293b',
  red: '#f87171',
  green: '#34d399',
  yellow: '#fbbf24',
  blue: '#60a5fa',
  magenta: '#c084fc',
  cyan: '#22d3ee',
  white: '#e2e8f0',
  brightBlack: '#64748b',
  brightRed: '#fca5a5',
  brightGreen: '#6ee7b7',
  brightYellow: '#fde68a',
  brightBlue: '#93c5fd',
  brightMagenta: '#d8b4fe',
  brightCyan: '#67e8f9',
  brightWhite: '#f8fafc',
};

let _xtermModules = null;

export function loadXterm() {
  if (!_xtermModules) {
    _xtermModules = Promise.all([
      import('@xterm/xterm'),
      import('@xterm/addon-fit'),
      import('@xterm/xterm/css/xterm.css').catch(() => null),
    ]).then(([xterm, fit]) => ({ Terminal: xterm.Terminal, FitAddon: fit.FitAddon }));
    _xtermModules.catch(() => {
      _xtermModules = null;
    });
  }
  return _xtermModules;
}

// eslint-disable-next-line no-control-regex
const ANSI_RE = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[=>78DEHMc]/g;
// eslint-disable-next-line no-control-regex
const CTRL_RE = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;

export function stripAnsi(text) {
  return String(text).replace(ANSI_RE, '').replace(/\r\n/g, '\n').replace(/\r/g, '').replace(CTRL_RE, '');
}

function toBytes(data) {
  if (data instanceof Uint8Array) return data;
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  return null;
}

export class TerminalView {
  constructor(host, { onData = null, onResize = null, fontSize = 12, theme = {} } = {}) {
    this.host = host;
    this.onData = onData;
    this.onResize = onResize;
    this.term = null;
    this.fit = null;
    this._chunks = [];
    this._chunkBytes = 0;
    this._decoder = typeof TextDecoder !== 'undefined' ? new TextDecoder('utf-8') : null;
    this._disposed = false;
    this._resizeObserver = null;
    this._refitPending = false;

    host.innerHTML = '';
    host.classList.add('zt-terminal');
    // Keys typed into the terminal belong to the shell: Esc must not close the
    // dialog and Tab must not be eaten by its focus trap.
    this._stopKeys = (e) => e.stopPropagation();
    host.addEventListener('keydown', this._stopKeys);

    this.pre = document.createElement('pre');
    this.pre.className = 'zt-terminal-fallback';
    this.pre.style.cssText =
      'margin:0; height:100%; overflow:auto; white-space:pre-wrap; word-break:break-word; font:var(--zn-fs-xs)/1.45 var(--font-mono, monospace); color:#e2e8f0;';
    host.appendChild(this.pre);

    this.ready = loadXterm()
      .then((mods) => this._attachXterm(mods, fontSize, theme))
      .catch(() => false);
  }

  _attachXterm({ Terminal, FitAddon }, fontSize, theme) {
    if (this._disposed) return false;
    let term = null;
    try {
      term = new Terminal({
        cursorBlink: true,
        scrollback: 5000,
        fontSize,
        fontFamily: '"JetBrains Mono", "Fira Code", Menlo, Consolas, "DejaVu Sans Mono", monospace',
        theme: { ...THEME, ...theme },
        allowProposedApi: false,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      const mount = document.createElement('div');
      mount.className = 'zt-terminal-xterm';
      mount.style.cssText = 'width:100%; height:100%;';
      this.host.appendChild(mount);
      term.open(mount);
      this.term = term;
      this.fit = fit;
      this.mount = mount;
    } catch (e) {
      try {
        term?.dispose();
      } catch (_) {}
      this.host.querySelector('.zt-terminal-xterm')?.remove();
      return false; // keep the plain-text view
    }

    this.pre.remove();
    term.onData((d) => this.onData?.(d));
    term.onBinary((d) => this.onData?.(d));
    term.onResize(({ cols, rows }) => this.onResize?.(cols, rows));
    for (const chunk of this._chunks) term.write(chunk);
    this.refit();
    if (typeof ResizeObserver !== 'undefined') {
      this._resizeObserver = new ResizeObserver(() => this._scheduleRefit());
      this._resizeObserver.observe(this.host);
    }
    return true;
  }

  _scheduleRefit() {
    if (this._refitPending) return;
    this._refitPending = true;
    requestAnimationFrame(() => {
      this._refitPending = false;
      this.refit();
    });
  }

  refit() {
    if (!this.term || !this.fit || this._disposed) return;
    if (!this.host.offsetWidth || !this.host.offsetHeight) return; // hidden tab
    try {
      this.fit.fit();
    } catch (_) {}
  }

  _remember(chunk, size) {
    this._chunks.push(chunk);
    this._chunkBytes += size;
    while (this._chunkBytes > MAX_REPLAY_BYTES && this._chunks.length > 1) {
      const old = this._chunks.shift();
      this._chunkBytes -= old.length || old.byteLength || 0;
    }
  }

  write(data) {
    if (this._disposed || data == null) return;
    const bytes = toBytes(data);
    const chunk = bytes ? bytes.slice() : String(data);
    this._remember(chunk, bytes ? bytes.byteLength : chunk.length);
    if (this.term) {
      this.term.write(chunk);
      return;
    }
    const text = bytes ? (this._decoder ? this._decoder.decode(bytes, { stream: true }) : '') : chunk;
    this.pre.textContent += stripAnsi(text);
    this.pre.scrollTop = this.pre.scrollHeight;
  }

  writeln(text) {
    this.write(`${text}\r\n`);
  }

  clear() {
    this._chunks = [];
    this._chunkBytes = 0;
    if (this.term) this.term.reset();
    this.pre.textContent = '';
  }

  focus() {
    if (this.term) this.term.focus();
  }

  size() {
    if (this.term) return { cols: this.term.cols, rows: this.term.rows };
    const cols = Math.max(40, Math.floor((this.host.clientWidth || 600) / 7.5));
    const rows = Math.max(10, Math.floor((this.host.clientHeight || 300) / 18));
    return { cols, rows };
  }

  text() {
    if (!this.term) return this.pre.textContent;
    const buf = this.term.buffer.active;
    const lines = [];
    for (let i = 0; i < buf.length; i++) lines.push(buf.getLine(i)?.translateToString(true) ?? '');
    return lines.join('\n').replace(/\n+$/, '');
  }

  dispose() {
    this._disposed = true;
    this._resizeObserver?.disconnect();
    this.host.removeEventListener('keydown', this._stopKeys);
    try {
      this.term?.dispose();
    } catch (_) {}
    this.term = null;
  }
}

export function createTerminalView(host, options) {
  return new TerminalView(host, options);
}
