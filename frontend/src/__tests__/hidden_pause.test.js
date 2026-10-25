import { describe, it, expect, vi } from 'vitest';
import { installHiddenPause } from '../hidden-pause.js';

function fakeDoc() {
  const listeners = [];
  return {
    hidden: false,
    addEventListener: (_t, fn) => listeners.push(fn),
    removeEventListener: () => {},
    fire() {
      listeners.forEach((fn) => fn());
    },
  };
}

describe('hidden tabs stop listening (PERF-3)', () => {
  it('closes the stream after 30 s hidden and reconnects when shown', () => {
    vi.useFakeTimers();
    const doc = fakeDoc();
    const start = vi.fn();
    const stop = vi.fn();
    const ctl = installHiddenPause({ start, stop, doc, delayMs: 30000 });
    doc.hidden = true;
    doc.fire();
    vi.advanceTimersByTime(29000);
    expect(stop).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2000);
    expect(stop).toHaveBeenCalledTimes(1);
    expect(ctl.isPaused()).toBe(true);
    doc.hidden = false;
    doc.fire();
    expect(start).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('a quick look away changes nothing', () => {
    vi.useFakeTimers();
    const doc = fakeDoc();
    const start = vi.fn();
    const stop = vi.fn();
    installHiddenPause({ start, stop, doc });
    doc.hidden = true;
    doc.fire();
    vi.advanceTimersByTime(5000);
    doc.hidden = false;
    doc.fire();
    vi.advanceTimersByTime(60000);
    expect(stop).not.toHaveBeenCalled();
    expect(start).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('the LCD page keeps its stream', () => {
    vi.useFakeTimers();
    const doc = fakeDoc();
    const stop = vi.fn();
    installHiddenPause({ start: vi.fn(), stop, doc, enabled: () => false });
    doc.hidden = true;
    doc.fire();
    vi.advanceTimersByTime(60000);
    expect(stop).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
