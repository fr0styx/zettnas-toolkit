// Window snapping: zones, geometry and applying a snap.
// Part of dock.js, split out by ARC-5.

import { announceA11y } from '../../a11y.js';
import { _dockAutohide, _dockPosition, _dockSize } from './dock-settings.js';
import { DESKTOP_WINDOW_SELECTOR } from './window-drag.js';
import { saveOpenWindowsState, saveWindowBounds } from './window-state.js';

export const NAVBAR_OFFSET = 48;
export const DOCK_MARGIN = 76;

export function getSnapGeometry(snapZone) {
  const winW = typeof window !== 'undefined' ? window.innerWidth : 1440;
  const winH = typeof window !== 'undefined' ? window.innerHeight : 900;

  let leftInset = 8;
  let topInset = NAVBAR_OFFSET;
  let availW = winW - 16;
  let availH = winH - NAVBAR_OFFSET - DOCK_MARGIN;

  if (_dockPosition === 'left' && !_dockAutohide) {
    const dockW = _dockSize === 'large' ? 84 : (_dockSize === 'small' ? 60 : 70);
    leftInset = dockW + 12;
    availW = winW - leftInset - 8;
    availH = winH - NAVBAR_OFFSET - 16;
  } else if (_dockPosition === 'top' && !_dockAutohide) {
    const dockH = _dockSize === 'large' ? 76 : (_dockSize === 'small' ? 56 : 64);
    topInset = NAVBAR_OFFSET + dockH + 8;
    availH = winH - topInset - 16;
  } else if (_dockAutohide) {
    availH = winH - NAVBAR_OFFSET - 16;
  }

  availH = Math.max(200, availH);
  const halfW = Math.round(availW / 2);
  const halfH = Math.round((availH - 8) / 2);

  switch (snapZone) {
    case 'top-left':
      return {
        left: leftInset,
        top: topInset,
        width: halfW,
        height: halfH,
        label: 'Top Left (1/4)'
      };
    case 'top-right':
      return {
        left: leftInset + halfW + 8,
        top: topInset,
        width: halfW,
        height: halfH,
        label: 'Top Right (1/4)'
      };
    case 'bottom-left':
      return {
        left: leftInset,
        top: topInset + halfH + 8,
        width: halfW,
        height: halfH,
        label: 'Bottom Left (1/4)'
      };
    case 'bottom-right':
      return {
        left: leftInset + halfW + 8,
        top: topInset + halfH + 8,
        width: halfW,
        height: halfH,
        label: 'Bottom Right (1/4)'
      };
    case 'left':
      return {
        left: leftInset,
        top: topInset,
        width: halfW,
        height: availH,
        label: 'Left Half (1/2)'
      };
    case 'right':
      return {
        left: leftInset + halfW + 8,
        top: topInset,
        width: halfW,
        height: availH,
        label: 'Right Half (1/2)'
      };
    case 'maximize':
      return {
        left: leftInset,
        top: topInset,
        width: availW,
        height: availH,
        label: 'Maximize (Full)'
      };
    default:
      return null;
  }
}

export function evaluateSnapZone(clientX, clientY) {
  if (typeof window === 'undefined') return null;
  const cornerThreshold = 48;
  const edgeThreshold = 25;
  const bottomEdge = window.innerHeight - DOCK_MARGIN;

  // Check 4 corners first
  if (clientX <= cornerThreshold && clientY <= NAVBAR_OFFSET + cornerThreshold) {
    return 'top-left';
  }
  if (clientX >= window.innerWidth - cornerThreshold && clientY <= NAVBAR_OFFSET + cornerThreshold) {
    return 'top-right';
  }
  if (clientX <= cornerThreshold && clientY >= bottomEdge - cornerThreshold) {
    return 'bottom-left';
  }
  if (clientX >= window.innerWidth - cornerThreshold && clientY >= bottomEdge - cornerThreshold) {
    return 'bottom-right';
  }

  // Check edges
  if (clientY <= NAVBAR_OFFSET + 12 || clientY <= edgeThreshold) {
    return 'maximize';
  }
  if (clientX <= edgeThreshold) {
    return 'left';
  }
  if (clientX >= window.innerWidth - edgeThreshold) {
    return 'right';
  }

  return null;
}

export function applyWindowSnap(dragEl, snapZone, winId) {
  if (!dragEl || !snapZone) return;
  const geom = getSnapGeometry(snapZone);
  if (!geom) return;

  if (!dragEl._preSnapWidth) {
    const curW = dragEl.offsetWidth || 640;
    const curH = dragEl.offsetHeight || 400;
    dragEl._preSnapWidth = `${curW}px`;
    dragEl._preSnapHeight = `${curH}px`;
  }

  dragEl.style.transition = 'all 0.22s cubic-bezier(0.16, 1, 0.3, 1)';
  dragEl.dataset.snapped = snapZone;
  dragEl.style.position = 'fixed';
  dragEl.style.transform = 'none';

  if (snapZone === 'maximize') {
    dragEl.style.left = '8px';
    dragEl.style.top = '48px';
    dragEl.style.width = 'calc(100vw - 16px)';
    dragEl.style.height = 'calc(100vh - 48px - 76px)';
  } else if (snapZone === 'left') {
    dragEl.style.left = '8px';
    dragEl.style.top = '48px';
    dragEl.style.width = 'calc(50vw - 12px)';
    dragEl.style.height = 'calc(100vh - 48px - 76px)';
  } else if (snapZone === 'right') {
    dragEl.style.left = 'calc(50vw + 4px)';
    dragEl.style.top = '48px';
    dragEl.style.width = 'calc(50vw - 12px)';
    dragEl.style.height = 'calc(100vh - 48px - 76px)';
  } else {
    dragEl.style.left = `${geom.left}px`;
    dragEl.style.top = `${geom.top}px`;
    dragEl.style.width = `${geom.width}px`;
    dragEl.style.height = `${geom.height}px`;
  }

  setTimeout(() => {
    dragEl.style.transition = 'none';
  }, 250);

  if (winId) {
    saveWindowBounds(winId, {
      left: geom.left,
      top: geom.top,
      width: geom.width,
      height: geom.height,
      snapped: snapZone
    });
    saveOpenWindowsState();
  }

  if (typeof announceA11y === 'function') {
    announceA11y(`Window snapped to ${geom.label}`);
  }
}

export function getActiveWindowElement() {
  const activeWin = document.querySelector('.active-window');
  if (activeWin) return activeWin;
  if (window.DockManager && window.DockManager.activeId) {
    const w = window.DockManager.windows[window.DockManager.activeId];
    if (w && w.el) {
      return w.el.querySelector?.('#console-window, #management-window, .chassis-front-panel, .mgmt-app-window, .container-inspector-window, #container-inspector-window, #app-deploy-modal-window, .os-window, #file-manager-window, #notif-center-panel') || w.el;
    }
  }
  const allWins = Array.from(document.querySelectorAll(DESKTOP_WINDOW_SELECTOR))
    .filter((el) => {
      const parent = el.closest?.('#console-modal-overlay, #management-modal-overlay, #container-inspector-overlay, #smart-modal-overlay, #stack-inspector-overlay, #stack-picker-overlay, #app-deploy-modal-overlay') || el;
      return parent.style.display !== 'none' && !parent.classList.contains('hidden');
    })
    .sort((a, b) => parseInt(b.style.zIndex || '0', 10) - parseInt(a.style.zIndex || '0', 10));
  return allWins[0] || null;
}

export function restoreWindowSnap(dragEl, winId) {
  if (!dragEl) return;
  dragEl.dataset.snapped = '';
  dragEl.style.transition = 'all 0.22s cubic-bezier(0.16, 1, 0.3, 1)';
  const width = parseFloat(dragEl._preSnapWidth) || 0;
  const height = parseFloat(dragEl._preSnapHeight) || 0;
  if (dragEl._preSnapWidth) dragEl.style.width = dragEl._preSnapWidth;
  if (dragEl._preSnapHeight) dragEl.style.height = dragEl._preSnapHeight;
  // the next snap remembers the size the window has then
  dragEl._preSnapWidth = null;
  dragEl._preSnapHeight = null;
  setTimeout(() => {
    dragEl.style.transition = 'none';
  }, 250);

  const id = winId || dragEl.dataset.windowId || dragEl.id;
  if (id) {
    // the restored size, not the snapped one: otherwise the window comes back snapped-size
    // from the dock or after a reload
    const bounds = { snapped: '', left: Math.round(parseFloat(dragEl.style.left) || 0), top: Math.round(parseFloat(dragEl.style.top) || 0) };
    if (width) bounds.width = width;
    if (height) bounds.height = height;
    saveWindowBounds(id, bounds);
    saveOpenWindowsState();
  }
  if (typeof announceA11y === 'function') {
    announceA11y('Window restored to normal size');
  }
}
