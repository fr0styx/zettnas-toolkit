import { describe, it, expect, vi, afterEach } from 'vitest';
import { prefersReducedMotion, onReducedMotionChange } from '../motion.js';

function fakeMedia(matches) {
  const listeners = [];
  window.matchMedia = vi.fn(() => ({ matches, addEventListener: (_, f) => listeners.push(f), removeEventListener: vi.fn() }));
  return listeners;
}

describe('reduced motion in JS (UX-19)', () => {
  const original = window.matchMedia;
  afterEach(() => { window.matchMedia = original; });

  it('reads the setting and follows changes', () => {
    const listeners = fakeMedia(true);
    expect(prefersReducedMotion()).toBe(true);
    const cb = vi.fn();
    const stop = onReducedMotionChange(cb);
    listeners[0]({ matches: false });
    expect(cb).toHaveBeenCalledWith(false);
    stop();
    window.matchMedia = () => { throw new Error('old browser'); };
    expect(prefersReducedMotion()).toBe(false);
    window.matchMedia = undefined;
    expect(onReducedMotionChange(cb)()).toBeUndefined();
  });

  it('the screensaver shows the still clock instead of moving pictures', async () => {
    fakeMedia(true);
    document.body.innerHTML = '<div id="desktop-screensaver"><canvas id="screensaver-canvas"></canvas><div id="screensaver-clock-display" style="display:none"><span id="screensaver-time"></span><span id="screensaver-date"></span></div></div>';
    const ss = await import('../components/screensaver.js');
    ss.applyScreensaverSettings(true, 5, 'starfield', false, false);
    ss.activateScreensaver(true);
    expect(document.getElementById('screensaver-clock-display').style.display).toBe('block');
    expect(document.getElementById('screensaver-canvas').style.display).toBe('none');
    ss.deactivateScreensaver();
  });
});
