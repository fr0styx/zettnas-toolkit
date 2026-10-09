import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initDesktopContextMenu,
  showDesktopContextMenu,
  hideDesktopContextMenu,
  executeContextAction
} from '../components/desktop-context-menu.js';
import {
  initDesktopDragAndDrop,
  hideDropZone
} from '../components/desktop-drag-drop.js';
import {
  initScreensaverSystem,
  activateScreensaver,
  deactivateScreensaver,
  getScreensaverSettings,
  applyScreensaverSettings,
  initScreensaverSettingsControls
} from '../components/screensaver.js';
import * as wallpapersModule from '../components/wallpapers.js';
import { SUBPANE_MAP } from '../components/management.js';
import { ZettEventBus } from '../event-bus.js';

describe('Batch 4: Desktop Context Menu, Drag & Drop Ingestion & Screensaver Engine', () => {
  let contextMenuEl;
  let dropZoneEl;
  let screensaverEl;
  let canvasEl;
  let clockDisplayEl;
  let mgmtPaneScreensaver;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    document.body.innerHTML = '';

    window.innerWidth = 1280;
    window.innerHeight = 800;

    // Mock HTMLCanvasElement.getContext for jsdom
    HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
      fillRect: vi.fn(),
      fillText: vi.fn(),
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn()
    });

    // 1. Context Menu DOM
    contextMenuEl = document.createElement('div');
    contextMenuEl.id = 'desktop-context-menu';
    contextMenuEl.className = 'desktop-context-menu';
    contextMenuEl.style.display = 'none';
    contextMenuEl.innerHTML = `
      <div class="context-menu-item" tabindex="0" data-action="wallpaper">Wallpaper</div>
      <div class="context-menu-item" tabindex="0" data-action="theme">Theme</div>
      <div class="context-menu-item" tabindex="0" data-action="glass">Glass</div>
      <div class="context-menu-item" tabindex="0" data-action="dock">Dock</div>
      <div class="context-menu-item" tabindex="0" data-action="screensaver">Screensaver</div>
      <div class="context-menu-divider"></div>
      <div class="context-menu-item" tabindex="0" data-action="fullscreen">Fullscreen</div>
      <div class="context-menu-item" tabindex="0" data-action="activity">Activity</div>
      <div class="context-menu-item" tabindex="0" data-action="lock">Lock</div>
    `;
    document.body.appendChild(contextMenuEl);

    // 2. Drop Zone DOM
    dropZoneEl = document.createElement('div');
    dropZoneEl.id = 'desktop-drop-zone';
    dropZoneEl.className = 'desktop-drop-zone';
    dropZoneEl.style.display = 'none';
    dropZoneEl.innerHTML = `
      <div class="desktop-drop-card">
        <div class="desktop-drop-title">Drop image to set as wallpaper</div>
      </div>
    `;
    document.body.appendChild(dropZoneEl);

    // 3. Screensaver DOM
    screensaverEl = document.createElement('div');
    screensaverEl.id = 'desktop-screensaver';
    screensaverEl.className = 'desktop-screensaver';
    screensaverEl.style.display = 'none';

    canvasEl = document.createElement('canvas');
    canvasEl.id = 'screensaver-canvas';
    screensaverEl.appendChild(canvasEl);

    clockDisplayEl = document.createElement('div');
    clockDisplayEl.id = 'screensaver-clock-display';
    clockDisplayEl.innerHTML = `
      <div id="screensaver-time">12:00:00</div>
      <div id="screensaver-date">Friday, October 9, 2026</div>
    `;
    screensaverEl.appendChild(clockDisplayEl);

    document.body.appendChild(screensaverEl);

    // 4. Mission Control Screensaver Tab Pane DOM
    mgmtPaneScreensaver = document.createElement('div');
    mgmtPaneScreensaver.id = 'mgmt-pane-screensaver';
    mgmtPaneScreensaver.innerHTML = `
      <input type="checkbox" id="screensaver-enable-toggle" checked />
      <select id="screensaver-timeout-select">
        <option value="1">1 Minute</option>
        <option value="5">5 Minutes</option>
        <option value="10" selected>10 Minutes</option>
        <option value="30">30 Minutes</option>
      </select>
      <input type="checkbox" id="screensaver-lock-toggle" />
      <div class="screensaver-style-card active" data-mode="matrix_rain">Matrix Rain</div>
      <div class="screensaver-style-card" data-mode="retro_clock">Retro Clock</div>
      <div class="screensaver-style-card" data-mode="starfield">Starfield</div>
      <button id="screensaver-preview-btn">Preview</button>
      <button id="screensaver-reset-btn">Reset</button>
    `;
    document.body.appendChild(mgmtPaneScreensaver);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('Desktop Context Menu displays and clamps within viewport boundaries', () => {
    initDesktopContextMenu();

    // Show at 100, 100
    showDesktopContextMenu(100, 100);
    expect(contextMenuEl.style.display).toBe('flex');
    expect(contextMenuEl.getAttribute('aria-hidden')).toBe('false');
    expect(contextMenuEl.style.left).toBe('100px');
    expect(contextMenuEl.style.top).toBe('100px');

    // Show near right/bottom edge (1250, 780): should be clamped within window (1280x800)
    showDesktopContextMenu(1250, 780);
    const leftNum = parseInt(contextMenuEl.style.left, 10);
    const topNum = parseInt(contextMenuEl.style.top, 10);
    expect(leftNum).toBeLessThan(1250);
    expect(topNum).toBeLessThan(780);

    // Hide context menu
    hideDesktopContextMenu();
    expect(contextMenuEl.style.display).toBe('none');
    expect(contextMenuEl.getAttribute('aria-hidden')).toBe('true');
  });

  it('Desktop Context Menu intercepts desktop right-click but ignores inputs and window contents', () => {
    initDesktopContextMenu();

    // 1. Right click on desktop background
    const bgEvent = new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      clientX: 200,
      clientY: 300
    });
    document.body.dispatchEvent(bgEvent);
    expect(bgEvent.defaultPrevented).toBe(true);
    expect(contextMenuEl.style.display).toBe('flex');

    hideDesktopContextMenu();

    // 2. Right click inside an input element -> should NOT be intercepted
    const inputEl = document.createElement('input');
    document.body.appendChild(inputEl);
    const inputEvent = new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      clientX: 200,
      clientY: 300
    });
    inputEl.dispatchEvent(inputEvent);
    expect(inputEvent.defaultPrevented).toBe(false);
    expect(contextMenuEl.style.display).toBe('none');

    // 3. Right click inside an open window -> should NOT be intercepted
    const winEl = document.createElement('div');
    winEl.className = 'os-window';
    document.body.appendChild(winEl);
    const winEvent = new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      clientX: 200,
      clientY: 300
    });
    winEl.dispatchEvent(winEvent);
    expect(winEvent.defaultPrevented).toBe(false);
    expect(contextMenuEl.style.display).toBe('none');
  });

  it('executeContextAction routes correctly to wallpaper, theme, dock, and lock commands', () => {
    window.openManagementSection = vi.fn();
    window.lockDesktopScreen = vi.fn();

    executeContextAction('wallpaper');
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-wallpaper');

    executeContextAction('theme');
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-theme');

    executeContextAction('glass');
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-glass');

    executeContextAction('dock');
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-dock');

    executeContextAction('screensaver');
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-screensaver');

    executeContextAction('activity');
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-sec-activity', 'mgmt-pane-metrics');

    executeContextAction('lock');
    expect(window.lockDesktopScreen).toHaveBeenCalled();
  });

  it('Desktop Drag and Drop reveals drop zone and processes image file uploads', async () => {
    initDesktopDragAndDrop();

    // 1. Drag enter with Files reveals drop zone
    const dragEnterEv = new Event('dragenter');
    dragEnterEv.dataTransfer = { types: ['Files'] };
    window.dispatchEvent(dragEnterEv);

    expect(dropZoneEl.style.display).toBe('flex');
    expect(dropZoneEl.classList.contains('active')).toBe(true);

    // 2. Drag leave hides drop zone
    const dragLeaveEv = new Event('dragleave');
    dragLeaveEv.dataTransfer = { types: ['Files'] };
    window.dispatchEvent(dragLeaveEv);
    expect(dropZoneEl.style.display).toBe('none');

    // 3. Drop image file calls uploadAndApplyWallpaper
    const uploadSpy = vi.spyOn(wallpapersModule, 'uploadAndApplyWallpaper').mockResolvedValue({ success: true, filename: 'my_bg.png' });

    const dropEv = new Event('drop');
    const mockFile = new File(['mock data'], 'my_bg.png', { type: 'image/png' });
    dropEv.dataTransfer = {
      types: ['Files'],
      files: [mockFile]
    };
    dropEv.preventDefault = vi.fn();

    window.dispatchEvent(dropEv);

    expect(dropEv.preventDefault).toHaveBeenCalled();
    expect(uploadSpy).toHaveBeenCalledWith(mockFile);
    expect(dropZoneEl.style.display).toBe('none');
  });

  it('Screensaver Engine manages state, persistence, and activation modes', () => {
    // 1. Initial defaults
    applyScreensaverSettings(true, 10, 'matrix_rain', false, true);
    let settings = getScreensaverSettings();
    expect(settings.enabled).toBe(true);
    expect(settings.timeoutMinutes).toBe(10);
    expect(settings.mode).toBe('matrix_rain');
    expect(settings.requireLock).toBe(false);

    expect(localStorage.getItem('zettnas_screensaver_enabled')).toBe('true');
    expect(localStorage.getItem('zettnas_screensaver_timeout')).toBe('10');
    expect(localStorage.getItem('zettnas_screensaver_mode')).toBe('matrix_rain');
    expect(localStorage.getItem('zettnas_screensaver_require_lock')).toBe('false');

    // 2. Activate screensaver in matrix_rain mode
    activateScreensaver(true);
    expect(screensaverEl.style.display).toBe('block');
    expect(screensaverEl.classList.contains('active')).toBe(true);
    expect(canvasEl.style.display).toBe('block');
    expect(clockDisplayEl.style.display).toBe('none');

    // 3. Deactivate screensaver
    deactivateScreensaver();
    expect(screensaverEl.classList.contains('active')).toBe(false);

    // 4. Activate in retro_clock mode
    applyScreensaverSettings(true, 5, 'retro_clock', true, true);
    activateScreensaver(false);
    expect(clockDisplayEl.style.display).toBe('block');
    expect(canvasEl.style.display).toBe('none');

    window.lockDesktopScreen = vi.fn();
    deactivateScreensaver();
    // Since requireLock is true and was not preview, lockDesktopScreen should be invoked
    expect(window.lockDesktopScreen).toHaveBeenCalled();
  });

  it('Screensaver UI controls bind inputs, style card selection, and reset defaults', () => {
    initScreensaverSettingsControls();

    const enableToggle = document.getElementById('screensaver-enable-toggle');
    const timeoutSelect = document.getElementById('screensaver-timeout-select');
    const lockToggle = document.getElementById('screensaver-lock-toggle');
    const clockCard = document.querySelector('.screensaver-style-card[data-mode="retro_clock"]');
    const resetBtn = document.getElementById('screensaver-reset-btn');

    // Change timeout to 30 min
    timeoutSelect.value = '30';
    timeoutSelect.dispatchEvent(new Event('change'));
    expect(getScreensaverSettings().timeoutMinutes).toBe(30);

    // Toggle require lock
    lockToggle.checked = true;
    lockToggle.dispatchEvent(new Event('change'));
    expect(getScreensaverSettings().requireLock).toBe(true);

    // Click retro clock card
    clockCard.click();
    expect(clockCard.classList.contains('active')).toBe(true);
    expect(getScreensaverSettings().mode).toBe('retro_clock');

    // Click Reset Defaults button
    resetBtn.click();
    expect(getScreensaverSettings().enabled).toBe(true);
    expect(getScreensaverSettings().timeoutMinutes).toBe(10);
    expect(getScreensaverSettings().mode).toBe('matrix_rain');
    expect(getScreensaverSettings().requireLock).toBe(false);
    expect(enableToggle.checked).toBe(true);
    expect(timeoutSelect.value).toBe('10');
    expect(lockToggle.checked).toBe(false);
  });

  it('Mission Control SUBPANE_MAP seamlessly routes mgmt-pane-screensaver', () => {
    expect(SUBPANE_MAP['mgmt-pane-screensaver']).toEqual({
      section: 'mgmt-sec-wallpaper',
      pane: 'mgmt-pane-screensaver'
    });
    expect(SUBPANE_MAP['mgmt-sec-screensaver']).toEqual({
      section: 'mgmt-sec-wallpaper',
      pane: 'mgmt-pane-screensaver'
    });
  });
});
