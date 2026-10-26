// The front-panel console window: open and maximise.
// Part of dock.js, split out by ARC-5.

import { state } from '../../state.js';
import { t } from '../../i18n.js';
import { bringToFront } from './window-drag.js';

export function openConsoleWindow() {
  const consoleOverlay = document.getElementById('console-modal-overlay');
  const consoleModal = document.getElementById('console-window');
  if (consoleOverlay) {
    if (window.DockManager && !window.DockManager.windows['console']) {
      window.DockManager.register('console', consoleOverlay, '#i-screen', t('dock.zettnas', 'ZettNAS'), false);
    }
    if (window.DockManager) {
      window.DockManager.restore('console');
    }
    consoleOverlay.style.removeProperty('display');
    consoleOverlay.classList.remove('window-minimized');
    consoleOverlay.classList.add('open');
    if (consoleModal) {
      consoleModal.classList.remove('window-minimized');
      consoleModal.style.removeProperty('display');
      bringToFront(consoleModal);
      consoleModal.classList.remove('window-focus-pulse');
      void consoleModal.offsetWidth; // trigger reflow
      consoleModal.classList.add('window-focus-pulse');
      setTimeout(() => consoleModal.classList.remove('window-focus-pulse'), 850);
    }
    if (window.updateLcdPages && state.latestStats) {
      window.updateLcdPages(state.latestStats);
    }
  } else {
    document.getElementById('chassis-desktop-icon')?.click();
  }
}
window.openConsoleWindow = openConsoleWindow;

export let _isConsoleMaximized = false;
let _consolePreMaxBounds = null;
let _lastConsoleTouchTs = 0;

export function toggleConsoleMaximize(e) {
  if (e) {
    if (e.type === 'click' && Date.now() - _lastConsoleTouchTs < 450) {
      if (e.preventDefault) { e.preventDefault(); e.stopPropagation(); }
      return;
    }
    if (e.type === 'touchend') {
      _lastConsoleTouchTs = Date.now();
    }
    if (e.preventDefault) { e.preventDefault(); e.stopPropagation(); }
  }
  const consoleModal = document.getElementById('console-window');
  if (!consoleModal) return;
  const consoleMax = document.getElementById('console-max');

  if (!_isConsoleMaximized) {
    _consolePreMaxBounds = {
      left: consoleModal.style.left,
      top: consoleModal.style.top,
      transform: consoleModal.style.transform,
      width: consoleModal.style.width,
      height: consoleModal.style.height
    };
    const availW = Math.max(320, window.innerWidth - 64);
    const availH = Math.max(200, window.innerHeight - 150);
    const scale = Math.max(1, Math.min(availW / 712, availH / 270));
    consoleModal.style.transition = 'transform 0.25s cubic-bezier(0.16, 1, 0.3, 1), left 0.25s ease, top 0.25s ease';
    consoleModal.style.position = 'fixed';
    consoleModal.style.left = '50%';
    consoleModal.style.top = 'calc(50% - 20px)';
    consoleModal.style.transform = `translate(-50%, -50%) scale(${scale.toFixed(3)})`;
    consoleModal.style.transformOrigin = 'center center';
    consoleModal.dataset.maximized = 'true';
    if (consoleMax) consoleMax.setAttribute('title', 'Restore');
    _isConsoleMaximized = true;
    setTimeout(() => { if (consoleModal) consoleModal.style.transition = ''; }, 260);
  } else {
    consoleModal.style.transition = 'transform 0.25s cubic-bezier(0.16, 1, 0.3, 1), left 0.25s ease, top 0.25s ease';
    if (_consolePreMaxBounds && _consolePreMaxBounds.left && _consolePreMaxBounds.left !== '50%') {
      consoleModal.style.left = _consolePreMaxBounds.left;
      consoleModal.style.top = _consolePreMaxBounds.top;
      consoleModal.style.transform = _consolePreMaxBounds.transform || 'none';
      consoleModal.style.width = _consolePreMaxBounds.width || '';
      consoleModal.style.height = _consolePreMaxBounds.height || '';
    } else {
      consoleModal.style.left = '50%';
      consoleModal.style.top = '50%';
      consoleModal.style.transform = 'translate(-50%, -50%)';
      consoleModal.style.width = '';
      consoleModal.style.height = '';
    }
    delete consoleModal.dataset.maximized;
    if (consoleMax) consoleMax.setAttribute('title', 'Maximize');
    _isConsoleMaximized = false;
    setTimeout(() => { if (consoleModal) consoleModal.style.transition = ''; }, 260);
  }
}
if (typeof window !== 'undefined') {
  window.toggleConsoleMaximize = toggleConsoleMaximize;
}
