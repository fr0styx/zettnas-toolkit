// Window stacking, dragging and resizing.
// Part of dock.js, split out by ARC-5.

import { DockManager } from './dock-manager.js';
import { applyWindowSnap, evaluateSnapZone, getSnapGeometry } from './snap.js';
import { applySavedBounds, saveOpenWindowsState, saveWindowBounds } from './window-state.js';

/**
 * ZettNAS Toolkit Dock & Window Manager
 * Handles floating modal registration, minimize/restore, dragging, and z-index depth stacking.
 */

export let activeWindowZIndex = 1000;

export function bringToFront(windowEl) {
  if (!windowEl) return;
  // Confirmations and prompts sit in their own layer above their backdrop
  if (windowEl.dataset?.dialogChrome === 'alert') return;

  const isDesktopApp = Boolean(
    windowEl.id === 'console-window' ||
    windowEl.id === 'console-modal-overlay' ||
    windowEl.id === 'management-window' ||
    windowEl.id === 'management-modal-overlay' ||
    windowEl.id === 'file-manager-window' ||
    windowEl.id === 'notif-center-panel' ||
    windowEl.id === 'container-inspector-window' ||
    windowEl.id === 'container-inspector-overlay' ||
    windowEl.id === 'stack-inspector-window' ||
    windowEl.id === 'stack-inspector-overlay' ||
    windowEl.id === 'stack-picker-window' ||
    windowEl.id === 'stack-picker-overlay' ||
    windowEl.id === 'app-deploy-modal-window' ||
    windowEl.id === 'app-deploy-modal-overlay' ||
    windowEl.id === 'modal-new-cloud-remote' ||
    windowEl.id === 'cloud-remote-window' ||
    windowEl.id === 'modal-vm-edit' ||
    windowEl.id === 'modal-vm-create' ||
    windowEl.id === 'modal-vm-snapshots' ||
    windowEl.classList?.contains('chassis-front-panel') ||
    windowEl.classList?.contains('management-window') ||
    windowEl.classList?.contains('mgmt-app-window') ||
    windowEl.classList?.contains('file-manager-window') ||
    windowEl.classList?.contains('container-inspector-window') ||
    windowEl.classList?.contains('stack-inspector-window') ||
    windowEl.classList?.contains('app-deploy-window') ||
    windowEl.classList?.contains('cloud-remote-window') ||
    windowEl.classList?.contains('vm-modal-window') ||
    windowEl.classList?.contains('os-window') ||
    windowEl.closest?.('#console-modal-overlay, #management-modal-overlay, #file-manager-window, #notif-center-panel, #container-inspector-window, #container-inspector-overlay, #stack-inspector-window, #stack-inspector-overlay, #stack-picker-window, #stack-picker-overlay, #app-deploy-modal-window, #app-deploy-modal-overlay, #modal-new-cloud-remote, #modal-vm-edit, #modal-vm-create, #modal-vm-snapshots')
  );

  // Protect standalone modal backdrops & modal dialogs from being demoted into window z-index layer
  if (
    !isDesktopApp && (
      windowEl.classList.contains('smart-modal-window') ||
      windowEl.closest('.smart-modal-backdrop') ||
      windowEl.classList.contains('modal-container') ||
      windowEl.closest('.modal-backdrop')
    )
  ) {
    const backdrop = windowEl.closest('.smart-modal-backdrop') || windowEl.closest('.modal-backdrop');
    if (backdrop) {
      backdrop.style.zIndex = 'var(--z-modal-backdrop, 9000)';
    }
    windowEl.style.zIndex = 'var(--z-modal, 9100)';
    return;
  }

  let foundId = null;
  if (window.DockManager) {
    Object.keys(window.DockManager.windows).forEach((id) => {
      const wEl = window.DockManager.windows[id].el;
      if (wEl === windowEl || (wEl && wEl.contains && wEl.contains(windowEl)) || (windowEl && windowEl.contains && windowEl.contains(wEl))) {
        foundId = id;
      }
    });
  }

  // Fast-path guard: if already at top z-index and active, do not churn DOM or GPU layers
  const curZ = parseInt(windowEl.style.zIndex || '0', 10);
  const targetWin = windowEl.querySelector?.('#console-window, #management-window, .chassis-front-panel, .mgmt-app-window, .container-inspector-window, #container-inspector-window, #app-deploy-modal-window, #cloud-remote-window, .cloud-remote-window, .vm-modal-window') || windowEl;
  const isAlreadyActive = targetWin?.classList?.contains('active-window');
  const isTopZ = curZ === activeWindowZIndex;

  if (isTopZ && isAlreadyActive && (!window.DockManager || window.DockManager.activeId === foundId)) {
    return;
  }

  activeWindowZIndex++;
  if (activeWindowZIndex >= 4900) {
    // Linear re-normalization: sort open windows by their existing z-index and re-index from base 1000
    const openWins = Object.values(window.DockManager?.windows || {})
      .map((w) => w.el)
      .filter(Boolean)
      .sort((a, b) => parseInt(a.style.zIndex || '1000', 10) - parseInt(b.style.zIndex || '1000', 10));

    let baseZ = 1000;
    openWins.forEach((el) => {
      const curZ = (baseZ++).toString();
      el.style.zIndex = curZ;
      const inner = el.querySelector?.('#console-window, #management-window, .chassis-front-panel, .mgmt-app-window, .container-inspector-window, #container-inspector-window, .smart-modal-window, #smart-modal-window, #stack-inspector-window, #stack-picker-window, #app-deploy-modal-window, #cloud-remote-window, .cloud-remote-window');
      if (inner) inner.style.zIndex = curZ;
    });
    activeWindowZIndex = baseZ;
  }

  const zStr = activeWindowZIndex.toString();
  windowEl.style.zIndex = zStr;

  // Elevate parent overlay wrapper if applicable
  const parentOverlay = windowEl.closest?.('#console-modal-overlay, #management-modal-overlay, #container-inspector-overlay, #smart-modal-overlay, #stack-inspector-overlay, #stack-picker-overlay, #app-deploy-modal-overlay, #modal-new-cloud-remote, #vm-console-overlay, #vm-iso-manager-overlay');
  if (parentOverlay && parentOverlay !== windowEl) {
    parentOverlay.style.zIndex = zStr;
  }
  // Elevate child window if applicable
  const childWin = windowEl.querySelector?.('#console-window, #management-window, .chassis-front-panel, .mgmt-app-window, .container-inspector-window, #container-inspector-window, .smart-modal-window, #smart-modal-window, #stack-inspector-window, #stack-picker-window, #app-deploy-modal-window, #cloud-remote-window, .cloud-remote-window');
  if (childWin && childWin !== windowEl) {
    childWin.style.zIndex = zStr;
  }

  if (window.DockManager) {
    if (foundId) {
      if (typeof window.DockManager.setActiveId === 'function') {
        window.DockManager.setActiveId(foundId);
      } else {
        window.DockManager.activeId = foundId;
      }
      saveOpenWindowsState();
    }
  }

  // Update active-window class for specular border highlight
  try {
    document.querySelectorAll('.active-window').forEach((w) => {
      w.classList.remove('active-window');
    });
    if (targetWin && targetWin.classList) targetWin.classList.add('active-window');
  } catch (e) {}
}

export const DESKTOP_WINDOW_SELECTOR = '#console-window, #management-window, #file-manager-window, .file-manager-window, #notif-center-panel, .container-inspector-window, #container-inspector-window, #stack-inspector-window, #stack-picker-window, #app-deploy-modal-window, #cloud-remote-window, .cloud-remote-window, .os-window, .vm-modal-window';

export const handleWindowActivation = (e) => {
  // If the click directly targeted an overlay backdrop, do not activate it as a window
  if (e.target && (
    e.target.id === 'app-deploy-modal-overlay' ||
    e.target.id === 'management-modal-overlay' ||
    e.target.id === 'console-modal-overlay' ||
    e.target.id === 'smart-modal-overlay' ||
    e.target.id === 'modal-new-cloud-remote' ||
    e.target.id === 'modal-vm-edit' ||
    e.target.id === 'modal-vm-create'
  )) {
    return;
  }
  const windowEl = e.target.closest?.(DESKTOP_WINDOW_SELECTOR);
  if (windowEl) {
    bringToFront(windowEl);
    document.querySelectorAll('.chassis-hero-box').forEach((el) => {
      try { el.blur(); } catch (_) {}
    });
  } else if (e.target.closest?.('#desktop') && !e.target.closest?.(DESKTOP_WINDOW_SELECTOR)) {
    // User clicked on empty desktop wallpaper or desktop icons/widgets
    document.querySelectorAll('.active-window').forEach((w) => w.classList.remove('active-window'));
    if (window.DockManager) {
      if (typeof window.DockManager.setActiveId === 'function') {
        window.DockManager.setActiveId(null);
      } else {
        window.DockManager.activeId = null;
      }
    }
  }
};

if (typeof document !== 'undefined') {
  document.addEventListener('pointerdown', handleWindowActivation, { capture: true });
}

export function getOrCreateSnapGhost() {
  let ghost = document.getElementById('window-snap-ghost');
  if (!ghost) {
    ghost = document.createElement('div');
    ghost.id = 'window-snap-ghost';
    ghost.className = 'window-snap-ghost';
    ghost.setAttribute('aria-hidden', 'true');
    const badge = document.createElement('div');
    badge.className = 'snap-ghost-indicator';
    ghost.appendChild(badge);
    document.body.appendChild(ghost);
  } else if (!ghost.querySelector('.snap-ghost-indicator')) {
    const badge = document.createElement('div');
    badge.className = 'snap-ghost-indicator';
    ghost.appendChild(badge);
  }
  return ghost;
}

export /** True when focus came from the keyboard; previews then open on focus, never when the app moves focus. */
function keyboardFocused(el) {
  try {
    return el.matches(':focus-visible');
  } catch (_) {
    return true; // a browser without :focus-visible: keep the old behaviour
  }
}

export function makeDraggable(dragEl, handleEl, customId) {
  if (!dragEl) return;
  handleEl = handleEl || dragEl;
  handleEl.style.cursor = 'move';

  const winId = customId || (dragEl.id === 'file-manager-window' || dragEl.classList.contains('file-manager-window') ? 'fm' : null)
                         || (dragEl.id === 'management-window' || dragEl.classList.contains('mgmt-app-window') ? 'management' : null)
                         || (dragEl.id === 'console-window' || dragEl.classList.contains('chassis-front-panel') ? 'console' : null)
                         || (dragEl.id === 'smart-modal-window' ? 'smart' : null)
                         || (dragEl.id === 'notif-center-panel' ? 'notif-center' : null)
                         || dragEl.id
                         || dragEl.dataset.windowId;

  if (winId) {
    applySavedBounds(dragEl, winId);
  }

  if (dragEl._draggableInitialized) {
    return dragEl._cleanupDraggable;
  }
  dragEl._draggableInitialized = true;

  // Observe resizing to persist dimensions
  let ro = null;
  if (window.ResizeObserver && winId) {
    let resizeTimer = null;
    ro = new ResizeObserver(() => {
      if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
      if (dragEl.dataset.snapped) return;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        const rect = dragEl.getBoundingClientRect();
        if (rect.width > 50 && rect.height > 50 && winId !== 'copy-toast') {
          saveWindowBounds(winId, {
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          });
          saveOpenWindowsState();
        }
      }, 250);
    });
    ro.observe(dragEl);
    dragEl._resizeObserver = ro;
  }

  let startX = 0, startY = 0, initialMouseX = 0, initialMouseY = 0;
  let activeSnap = null;

  handleEl.style.touchAction = 'none';
  const onPointerDown = (e) => {
    if (e.button !== 0 || e.target.closest('button') || e.target.closest('input') || e.target.closest('.modal-ctrl-btn')) return;
    bringToFront(dragEl);
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) {
      // Mobile & touch swipe-to-dismiss gesture
      const touchStartY = e.clientY;
      let currentDy = 0;
      const pointerId = e.pointerId;
      try {
        handleEl.setPointerCapture?.(pointerId);
      } catch (_) {}

      const isLeftPinnedMobile = dragEl.classList.contains('os-window') ||
        dragEl.classList.contains('file-manager-window') ||
        dragEl.classList.contains('vm-manager-window') ||
        dragEl.classList.contains('containers-manager-window') ||
        (window.innerWidth <= 768 && !dragEl.style.left?.includes('50%'));
      const hasTranslateX50 = !isLeftPinnedMobile && Boolean((dragEl.style.transform || '').includes('translateX(-50%)') || dragEl.style.left === '50%');
      const xPrefix = hasTranslateX50 ? 'translateX(-50%) ' : '';

      dragEl.classList.add('window-dragging');

      const onTouchMove = (eMove) => {
        const dy = eMove.clientY - touchStartY;
        if (dy > 0) {
          currentDy = dy;
          dragEl.style.transition = 'none';
          dragEl.style.transform = `${xPrefix}translateY(${Math.round(dy * 0.75)}px)`;
          dragEl.style.opacity = String(Math.max(0.3, 1 - (dy / 300)));
        }
      };

      const onTouchEnd = () => {
        window.removeEventListener('pointermove', onTouchMove);
        window.removeEventListener('pointerup', onTouchEnd);
        window.removeEventListener('pointercancel', onTouchEnd);
        try {
          if (handleEl.hasPointerCapture && handleEl.hasPointerCapture(pointerId)) {
            handleEl.releasePointerCapture(pointerId);
          }
        } catch (_) {}

        if (currentDy >= 70) {
          // Threshold passed: smooth spring exit & dismissal
          dragEl.style.transition = 'transform 0.22s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.22s ease';
          dragEl.style.transform = `${xPrefix}translateY(260px)`;
          dragEl.style.opacity = '0';
          setTimeout(() => {
            dragEl.classList.remove('window-dragging');
            dragEl.style.removeProperty('transform');
            dragEl.style.removeProperty('opacity');
            dragEl.style.removeProperty('transition');
            if (winId && DockManager.windows[winId]) {
              DockManager.minimize(winId);
            } else {
              const closeBtn = dragEl.querySelector('.close-btn, .modal-close, .modal-ctrl-btn, #console-close, #management-close');
              if (closeBtn) closeBtn.click();
              else dragEl.style.setProperty('display', 'none', 'important');
            }
          }, 220);
        } else if (currentDy > 0) {
          // Snap back to resting position
          dragEl.style.transition = 'transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease';
          dragEl.style.transform = hasTranslateX50 ? 'translateX(-50%) translateY(0)' : 'translateY(0)';
          dragEl.style.opacity = '1';
          setTimeout(() => {
            dragEl.classList.remove('window-dragging');
            dragEl.style.removeProperty('transform');
            dragEl.style.removeProperty('opacity');
            dragEl.style.removeProperty('transition');
          }, 200);
        } else {
          dragEl.classList.remove('window-dragging');
        }
      };

      window.addEventListener('pointermove', onTouchMove);
      window.addEventListener('pointerup', onTouchEnd);
      window.addEventListener('pointercancel', onTouchEnd);
      return;
    }
    e.preventDefault();

    const ghost = getOrCreateSnapGhost();
    activeSnap = null;

    if (dragEl.dataset.maximized) {
      const cMax = document.getElementById('console-max');
      if (cMax) cMax.click();
    }

    if (dragEl.dataset.snapped) {
      dragEl.dataset.snapped = '';
      if (dragEl._preSnapWidth) dragEl.style.width = dragEl._preSnapWidth;
      if (dragEl._preSnapHeight) dragEl.style.height = dragEl._preSnapHeight;
      const targetW = parseFloat(dragEl._preSnapWidth) || dragEl.offsetWidth || 500;
      dragEl.style.left = Math.max(24, Math.min(window.innerWidth - targetW - 10, e.clientX - targetW / 2)) + 'px';
      dragEl.style.top = Math.max(56, e.clientY - 20) + 'px';
    }

    const rect = dragEl.getBoundingClientRect();
    dragEl.style.transition = 'none';
    dragEl.style.position = 'fixed';
    dragEl.style.transform = 'none';
    dragEl.style.margin = '0';
    dragEl.style.bottom = 'auto';
    dragEl.style.right = 'auto';
    dragEl.style.left = rect.left + 'px';
    dragEl.style.top = rect.top + 'px';
    dragEl.classList.add('window-dragging');

    startX = rect.left;
    startY = rect.top;
    initialMouseX = e.clientX;
    initialMouseY = e.clientY;

    const pointerId = e.pointerId;
    try {
      handleEl.setPointerCapture?.(pointerId);
    } catch (_) {}

    const drag = (eMove) => {
      eMove.preventDefault();
      const dx = eMove.clientX - initialMouseX;
      const dy = eMove.clientY - initialMouseY;
      dragEl.style.left = `${Math.round(startX + dx)}px`;
      dragEl.style.top = `${Math.round(startY + dy)}px`;

      const zone = evaluateSnapZone(eMove.clientX, eMove.clientY);
      if (zone) {
        activeSnap = zone;
        const geom = getSnapGeometry(activeSnap);
        if (geom) {
          ghost.style.display = 'flex';
          ghost.style.left = `${geom.left}px`;
          ghost.style.top = `${geom.top}px`;
          ghost.style.width = `${geom.width}px`;
          ghost.style.height = `${geom.height}px`;
          const badge = ghost.querySelector('.snap-ghost-indicator');
          if (badge) badge.textContent = geom.label;
        }
      } else {
        activeSnap = null;
        ghost.style.display = 'none';
      }
    };

    const stopDrag = (eUp) => {
      dragEl.classList.remove('window-dragging');
      ghost.style.display = 'none';
      window.removeEventListener('pointermove', drag);
      window.removeEventListener('pointerup', stopDrag);
      window.removeEventListener('pointercancel', stopDrag);
      try {
        if (handleEl.hasPointerCapture && handleEl.hasPointerCapture(pointerId)) {
          handleEl.releasePointerCapture(pointerId);
        }
      } catch (_) {}

      if (activeSnap) {
        applyWindowSnap(dragEl, activeSnap, winId);
      } else if (winId) {
        dragEl.dataset.snapped = '';
        const finalRect = dragEl.getBoundingClientRect();
        saveWindowBounds(winId, {
          left: Math.round(finalRect.left),
          top: Math.round(finalRect.top),
          width: Math.round(finalRect.width),
          height: Math.round(finalRect.height),
          snapped: ''
        });
        saveOpenWindowsState();
      }
    };

    window.addEventListener('pointermove', drag);
    window.addEventListener('pointerup', stopDrag);
    window.addEventListener('pointercancel', stopDrag);
  };

  const onDblClick = (e) => {
    if (e.target.closest('button') || e.target.closest('input') || e.target.closest('.modal-ctrl-btn')) return;
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    if (dragEl.id === 'console-window') {
      const cMax = document.getElementById('console-max');
      if (cMax) { cMax.click(); return; }
    }
    if (dragEl.dataset.snapped) {
      dragEl.dataset.snapped = '';
      dragEl.style.transition = 'all 0.22s cubic-bezier(0.16, 1, 0.3, 1)';
      if (dragEl._preSnapWidth) dragEl.style.width = dragEl._preSnapWidth;
      if (dragEl._preSnapHeight) dragEl.style.height = dragEl._preSnapHeight;
      const targetW = parseFloat(dragEl._preSnapWidth) || 640;
      const targetH = parseFloat(dragEl._preSnapHeight) || 400;
      dragEl.style.left = Math.max(24, Math.round((window.innerWidth - targetW) / 2)) + 'px';
      dragEl.style.top = Math.max(50, Math.round((window.innerHeight - targetH) / 2)) + 'px';
      setTimeout(() => { dragEl.style.transition = 'none'; }, 250);
    } else {
      dragEl._preSnapWidth = dragEl.offsetWidth + 'px';
      dragEl._preSnapHeight = dragEl.offsetHeight + 'px';
      dragEl.dataset.snapped = 'maximize';
      dragEl.style.transition = 'all 0.22s cubic-bezier(0.16, 1, 0.3, 1)';
      dragEl.style.left = '8px';
      dragEl.style.top = '48px';
      dragEl.style.width = 'calc(100vw - 16px)';
      dragEl.style.height = 'calc(100vh - 48px - 76px)';
      setTimeout(() => { dragEl.style.transition = 'none'; }, 250);
    }

    if (winId) {
      const finalRect = dragEl.getBoundingClientRect();
      saveWindowBounds(winId, {
        left: Math.round(finalRect.left),
        top: Math.round(finalRect.top),
        width: Math.round(finalRect.width),
        height: Math.round(finalRect.height),
        snapped: dragEl.dataset.snapped || ''
      });
      saveOpenWindowsState();
    }
  };

  handleEl.addEventListener('pointerdown', onPointerDown);
  handleEl.addEventListener('dblclick', onDblClick);

  const cleanup = () => {
    handleEl.removeEventListener('pointerdown', onPointerDown);
    handleEl.removeEventListener('dblclick', onDblClick);
    if (ro) {
      try { ro.disconnect(); } catch (_) {}
      ro = null;
    }
    dragEl._draggableInitialized = false;
    dragEl._cleanupDraggable = null;
  };
  dragEl._cleanupDraggable = cleanup;
  return cleanup;
}

export function makeResizable(dragEl, resizerEl, customId, options = {}) {
  if (!dragEl || !resizerEl) return;
  const winId = customId || dragEl.id || dragEl.dataset.windowId;
  const minW = options.minWidth || 320;
  const minH = options.minHeight || 240;

  resizerEl.style.touchAction = 'none';

  resizerEl.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    e.preventDefault();
    e.stopPropagation();
    bringToFront(dragEl);

    const startX = e.clientX;
    const startY = e.clientY;
    const rect = dragEl.getBoundingClientRect();
    const startW = rect.width;
    const startH = rect.height;
    const maxW = Math.max(minW, window.innerWidth - rect.left - 12);
    const maxH = Math.max(minH, window.innerHeight - rect.top - 70);

    dragEl.style.transition = 'none';
    const prevUserSelect = document.body.style.userSelect;
    document.body.style.userSelect = 'none';

    const pointerId = e.pointerId;
    try {
      resizerEl.setPointerCapture?.(pointerId);
    } catch (_) {}

    const onPointerMove = (eMove) => {
      eMove.preventDefault();
      const dx = eMove.clientX - startX;
      const dy = eMove.clientY - startY;
      const newW = Math.max(minW, Math.min(maxW, startW + dx));
      const newH = Math.max(minH, Math.min(maxH, startH + dy));
      dragEl.style.width = `${Math.round(newW)}px`;
      dragEl.style.height = `${Math.round(newH)}px`;
    };

    const onPointerUp = () => {
      document.body.style.userSelect = prevUserSelect;
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
      try {
        if (resizerEl.hasPointerCapture && resizerEl.hasPointerCapture(pointerId)) {
          resizerEl.releasePointerCapture(pointerId);
        }
      } catch (_) {}

      if (winId) {
        const finalRect = dragEl.getBoundingClientRect();
        saveWindowBounds(winId, {
          left: Math.round(finalRect.left),
          top: Math.round(finalRect.top),
          width: Math.round(finalRect.width),
          height: Math.round(finalRect.height)
        });
        saveOpenWindowsState();
      }
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
  });
}
