import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { state } from '../state.js';
import { initAuth, lockDesktop, isLcdMode, isDesktopLocked } from '../components/auth.js';
import { initScreensaverSystem, activateScreensaver } from '../components/screensaver.js';
import { restoreOpenWindowsState } from '../components/dock.js';

describe('LCD Direct Hardware Display Isolation', () => {
  beforeEach(() => {
    document.body.className = '';
    state.isLcdDirect = false;
    sessionStorage.clear();
    localStorage.clear();

    document.body.innerHTML = `
      <div id="login-overlay" style="display: none;"></div>
      <div id="lock-overlay" style="display: none;"></div>
      <div id="desktop-screensaver" style="display: none;"></div>
      <div id="console-modal-overlay"></div>
      <div id="console-window"></div>
      <div id="screen"></div>
      <div id="os-dock-container"></div>
    `;
  });

  afterEach(() => {
    state.isLcdDirect = false;
    document.body.className = '';
    vi.restoreAllMocks();
  });

  it('correctly detects LCD mode via state.isLcdDirect and body.lcd-direct', () => {
    expect(isLcdMode()).toBe(false);

    state.isLcdDirect = true;
    expect(isLcdMode()).toBe(true);

    state.isLcdDirect = false;
    document.body.classList.add('lcd-direct');
    expect(isLcdMode()).toBe(true);
  });

  it('prevents lockDesktop from locking or showing lock overlay when in LCD mode', () => {
    state.isLcdDirect = true;
    const lockOverlay = document.getElementById('lock-overlay');

    lockDesktop();

    expect(lockOverlay.style.display).toBe('none');
    expect(isDesktopLocked()).toBe(false);
    expect(sessionStorage.getItem('zettnas_desktop_locked')).toBeNull();
  });

  it('initAuth clears existing lock flags and exits early when in LCD mode', () => {
    sessionStorage.setItem('zettnas_desktop_locked', 'true');
    localStorage.setItem('zettnas_desktop_locked', 'true');
    state.isLcdDirect = true;

    initAuth();

    expect(sessionStorage.getItem('zettnas_desktop_locked')).toBeNull();
    expect(localStorage.getItem('zettnas_desktop_locked')).toBeNull();
    expect(document.getElementById('lock-overlay').style.display).toBe('none');
  });

  it('prevents activateScreensaver from engaging when in LCD mode', () => {
    state.isLcdDirect = true;
    const screensaver = document.getElementById('desktop-screensaver');

    activateScreensaver(false);

    expect(screensaver.style.display).toBe('none');
    expect(screensaver.classList.contains('active')).toBe(false);
  });

  it('restoreOpenWindowsState exits early and does not restore windows in LCD mode', () => {
    state.isLcdDirect = true;
    localStorage.setItem('zettnas_open_windows_v1', JSON.stringify({
      windows: {
        'mgmt-window': { x: 100, y: 100, w: 800, h: 600, z: 1001, minimized: false }
      }
    }));

    restoreOpenWindowsState();

    // No windows should be opened or created
    expect(document.getElementById('mgmt-window')).toBeNull();
  });
});
