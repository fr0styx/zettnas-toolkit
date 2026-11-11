import { describe, it, expect, vi, afterEach } from 'vitest';
import { idleLoad, MISSION_CONTROL_WARMUP_MS } from '../load-when.js';

afterEach(() => vi.useRealTimers());

describe('idleLoad: windows warm up once the page has settled (NPERF-5)', () => {
  it('waits for the delay, then for an idle moment', () => {
    vi.useFakeTimers();
    const idle = [];
    const win = { setTimeout, requestIdleCallback: (cb, opts) => idle.push([cb, opts]) };
    const fn = vi.fn();
    idleLoad(fn, 3000, win);
    vi.advanceTimersByTime(2999);
    expect(idle).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(idle).toHaveLength(1);
    expect(idle[0][1]).toEqual({ timeout: 5000 });
    expect(fn).not.toHaveBeenCalled();
    idle[0][0]();
    expect(fn).toHaveBeenCalledOnce();
  });

  it('without requestIdleCallback it runs a second after the delay', () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    idleLoad(fn, 3000, { setTimeout });
    vi.advanceTimersByTime(3999);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledOnce();
  });

  it('Mission Control warms up after the first 10 s, not inside them', () => {
    expect(MISSION_CONTROL_WARMUP_MS).toBeGreaterThan(10000);
  });
});
