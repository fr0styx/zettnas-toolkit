import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { startLogStream, stopLogStream } from '../components/container-modal.js';

class FakeSource {
  static all = [];
  constructor(url) {
    this.url = url;
    this.handlers = {};
    this.closed = false;
    FakeSource.all.push(this);
  }
  addEventListener(name, fn) {
    this.handlers[name] = fn;
  }
  close() {
    this.closed = true;
  }
  line(msg) {
    this.onmessage({ data: JSON.stringify({ stream: 'stdout', ts: '', msg }) });
  }
}

beforeEach(() => {
  FakeSource.all = [];
  vi.stubGlobal('EventSource', FakeSource);
  document.body.innerHTML = '<select id="ci-logs-tail-select"><option value="100" selected>100</option></select><div id="ci-logs-terminal"></div>';
});
afterEach(() => {
  stopLogStream();
  vi.unstubAllGlobals();
});

const shown = () => document.getElementById('ci-logs-terminal').textContent;

describe('the live log (SET-14, Apps 26)', () => {
  it('the next app starts with an empty log', () => {
    startLogStream('app-a');
    FakeSource.all[0].line('from A');
    startLogStream('app-b');
    FakeSource.all[1].line('from B');
    expect(shown()).toContain('from B');
    expect(shown()).not.toContain('from A');
    expect(FakeSource.all[0].closed).toBe(true);
  });

  it('a line from the previous stream is ignored', () => {
    startLogStream('app-a');
    const a = FakeSource.all[0];
    startLogStream('app-b');
    a.line('late from A');
    expect(shown()).not.toContain('late from A');
  });

  it('when the log ends the stream closes and says so, instead of reconnecting', () => {
    startLogStream('app-a');
    const a = FakeSource.all[0];
    a.line('last line');
    a.handlers.done({});
    expect(a.closed).toBe(true);
    expect(shown()).toContain('last line');
    expect(shown()).toContain('The live log has ended');
  });

  it('a server error closes the stream; a dropped connection does not', () => {
    startLogStream('app-a');
    const a = FakeSource.all[0];
    a.handlers.error({});
    expect(a.closed).toBe(false);
    a.handlers.error({ data: JSON.stringify({ error: 'no such container' }) });
    expect(a.closed).toBe(true);
    expect(shown()).toContain('no such container');
  });
});
