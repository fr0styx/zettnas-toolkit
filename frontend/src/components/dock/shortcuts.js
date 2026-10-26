// Window keyboard shortcuts (and the retired workspace switcher's no-op API).
// Part of dock.js, split out by ARC-5.

import { applyWindowSnap, getActiveWindowElement, getSnapGeometry, restoreWindowSnap } from './snap.js';
import { getOrCreateSnapGhost } from './window-drag.js';
import { saveOpenWindowsState } from './window-state.js';

export const WORKSPACES = [];

export function getCurrentWorkspace() {
  return 1;
}

export function switchWorkspace() {}

export function initWorkspaceSwitcher() {}

let _keyboardShortcutsInitialized = false;
export function initWindowKeyboardShortcuts() {
  if (_keyboardShortcutsInitialized) return;
  _keyboardShortcutsInitialized = true;

  window.addEventListener('keydown', (e) => {
    // 1. Aero Snap 2.0: (Cmd/Win or Ctrl) + Option + [Arrow / 1-4]
    if ((e.metaKey || e.ctrlKey) && e.altKey) {
      const activeWin = getActiveWindowElement();
      if (activeWin) {
        let snapZone = null;
        if (e.key === 'ArrowLeft') snapZone = 'left';
        else if (e.key === 'ArrowRight') snapZone = 'right';
        else if (e.key === 'ArrowUp') snapZone = 'maximize';
        else if (e.key === 'ArrowDown') {
          e.preventDefault();
          restoreWindowSnap(activeWin);
          return;
        } else if (e.key === '1') snapZone = 'top-left';
        else if (e.key === '2') snapZone = 'top-right';
        else if (e.key === '3') snapZone = 'bottom-left';
        else if (e.key === '4') snapZone = 'bottom-right';

        if (snapZone) {
          e.preventDefault();
          const geom = getSnapGeometry(snapZone);
          if (geom) {
            const ghost = getOrCreateSnapGhost();
            ghost.style.display = 'flex';
            ghost.style.left = `${geom.left}px`;
            ghost.style.top = `${geom.top}px`;
            ghost.style.width = `${geom.width}px`;
            ghost.style.height = `${geom.height}px`;
            const badge = ghost.querySelector('.snap-ghost-indicator');
            if (badge) badge.textContent = geom.label;
            setTimeout(() => {
              ghost.style.display = 'none';
            }, 180);
          }
          const winId = activeWin.dataset.windowId || activeWin.id;
          applyWindowSnap(activeWin, snapZone, winId);
          return;
        }
      }
    }

    if (e.key === 'Escape') {
      const diagOverlay = document.getElementById('diagnostics-preview-modal-overlay');
      if (diagOverlay && diagOverlay.classList.contains('open')) {
        diagOverlay.classList.remove('open');
        diagOverlay.style.display = 'none';
        return;
      }
      const detailOverlay = document.getElementById('event-detail-modal-overlay');
      if (detailOverlay && detailOverlay.classList.contains('open')) {
        if (window.closeEventDetailModal) window.closeEventDetailModal();
        return;
      }
      const panel = document.getElementById('notif-center-panel');
      if (panel && panel.style.display !== 'none') {
        panel.style.display = 'none';
        saveOpenWindowsState();
      }
    }
  });
}
