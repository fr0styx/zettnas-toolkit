import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { isOpen, pollWhileOpen } from '../poll-while-open.js';

describe('pollWhileOpen (SET-16 stage 2)', () => {
  let el;
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = '<div id="win"><div id="card"></div></div>';
    el = document.getElementById('card');
  });
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('asks until the answer comes', async () => {
    const answers = [false, false, true];
    const check = vi.fn(async () => answers.shift());
    pollWhileOpen(el, check, { ms: 1000, limit: 10 });
    await vi.advanceTimersByTimeAsync(5000);
    expect(check).toHaveBeenCalledTimes(3);
  });

  it('stops after the limit', async () => {
    const check = vi.fn(async () => false);
    pollWhileOpen(el, check, { ms: 1000, limit: 4 });
    await vi.advanceTimersByTimeAsync(10000);
    expect(check).toHaveBeenCalledTimes(4);
  });

  it('stops after an error', async () => {
    const check = vi.fn(async () => {
      throw new Error('offline');
    });
    pollWhileOpen(el, check, { ms: 1000, limit: 10 });
    await vi.advanceTimersByTimeAsync(5000);
    expect(check).toHaveBeenCalledTimes(1);
  });

  it('stops once the window is hidden or the card is gone', async () => {
    const check = vi.fn(async () => false);
    pollWhileOpen(el, check, { ms: 1000, limit: 10 });
    await vi.advanceTimersByTimeAsync(1000);
    document.getElementById('win').hidden = true;
    await vi.advanceTimersByTimeAsync(5000);
    expect(check).toHaveBeenCalledTimes(1);

    const other = document.createElement('div');
    document.body.append(other);
    const check2 = vi.fn(async () => false);
    pollWhileOpen(other, check2, { ms: 1000, limit: 10 });
    other.remove();
    await vi.advanceTimersByTimeAsync(5000);
    expect(check2).not.toHaveBeenCalled();
  });

  it('can be stopped by its caller', async () => {
    const check = vi.fn(async () => false);
    const stop = pollWhileOpen(el, check, { ms: 1000, limit: 10 });
    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(check).not.toHaveBeenCalled();
  });

  it('isOpen uses checkVisibility where the browser has it', () => {
    expect(isOpen(null)).toBe(false);
    const fake = { isConnected: true, checkVisibility: () => false };
    expect(isOpen(/** @type {any} */ (fake))).toBe(false);
    fake.checkVisibility = () => true;
    expect(isOpen(/** @type {any} */ (fake))).toBe(true);
    expect(isOpen(el)).toBe(true);
  });
});
