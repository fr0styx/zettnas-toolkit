import { describe, it, expect, beforeEach, vi } from 'vitest';
import { triggerHaptic } from '../haptics.js';
import { showToast, showConfirmToast } from '../toast.js';

describe('Phase 5: Mobile PWA, Responsive Touch & Haptics', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="top-toast-container"></div>
    `;
    vi.restoreAllMocks();
  });

  it('triggers haptic vibrations safely when navigator.vibrate is available', () => {
    const vibrateSpy = vi.fn();
    Object.defineProperty(navigator, 'vibrate', {
      value: vibrateSpy,
      configurable: true,
      writable: true,
    });

    const lightRes = triggerHaptic('light');
    expect(lightRes).toBe(true);
    expect(vibrateSpy).toHaveBeenCalledWith(12);

    const successRes = triggerHaptic('success');
    expect(successRes).toBe(true);
    expect(vibrateSpy).toHaveBeenCalledWith([15, 30, 20]);

    const warnRes = triggerHaptic('warning');
    expect(warnRes).toBe(true);
    expect(vibrateSpy).toHaveBeenCalledWith([30, 50, 30]);
  });

  it('handles missing navigator.vibrate gracefully without error', () => {
    Object.defineProperty(navigator, 'vibrate', {
      value: undefined,
      configurable: true,
      writable: true,
    });

    const res = triggerHaptic('light');
    expect(res).toBe(false);
  });

  it('triggers appropriate tactile haptics on toast notifications', () => {
    const vibrateSpy = vi.fn();
    Object.defineProperty(navigator, 'vibrate', {
      value: vibrateSpy,
      configurable: true,
      writable: true,
    });

    showToast('Deployment successful', 'success');
    expect(vibrateSpy).toHaveBeenCalledWith([15, 30, 20]);

    showConfirmToast('Warning', 'Are you sure?', () => {}, () => {});
    expect(vibrateSpy).toHaveBeenCalledWith([30, 50, 30]);
  });
});
