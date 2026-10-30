import { describe, it, expect, vi, afterEach } from 'vitest';
import { desktopUser, forDesktopUser } from '../load-when.js';

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  document.documentElement.classList.remove('auth-required');
  document.body.classList.remove('phone-shell');
});

describe('fetching the big windows ahead of use (NPERF-5)', () => {
  it('runs at once for someone signed in at the desktop', () => {
    const fn = vi.fn();
    forDesktopUser(fn);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('waits on the sign-in screen and runs once after signing in', async () => {
    document.documentElement.classList.add('auth-required');
    const fn = vi.fn();
    forDesktopUser(fn);
    await flush();
    expect(fn).not.toHaveBeenCalled();
    document.documentElement.classList.remove('auth-required');
    await flush();
    document.documentElement.classList.add('x');
    await flush();
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('never runs in the phone layout, the front screen or a console page', async () => {
    document.body.classList.add('phone-shell');
    const fn = vi.fn();
    const stop = forDesktopUser(fn);
    await flush();
    expect(fn).not.toHaveBeenCalled();
    stop();
    document.body.classList.remove('phone-shell');
    await flush();
    expect(fn).not.toHaveBeenCalled();
    forDesktopUser(fn, document, { lcd: true });
    forDesktopUser(fn, document, { console: true });
    expect(fn).not.toHaveBeenCalled();
    expect(desktopUser(document, { lcd: true })).toBe(false);
  });
});
