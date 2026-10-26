// Where windows were: saved bounds and the open-windows list, restored after a reload.
// Part of dock.js, split out by ARC-5.

import { state } from '../../state.js';
import { KNOWN_APPS } from './apps.js';
import { openConsoleWindow } from './console-window.js';
import { DockManager } from './dock-manager.js';
import { getSnapGeometry } from './snap.js';
import { bringToFront } from './window-drag.js';
import { isCompact } from '../../device.js';

const WIN_BOUNDS_KEY = 'zettnas_window_bounds_v2';
export const OPEN_WINDOWS_KEY = 'zettnas_open_windows_v1';

export function loadSavedWindowBounds() {
  try {
    return JSON.parse(localStorage.getItem(WIN_BOUNDS_KEY) || '{}');
  } catch {
    return {};
  }
}

export function saveWindowBounds(id, bounds) {
  if (!id || isCompact()) return;
  try {
    const all = loadSavedWindowBounds();
    all[id] = { ...(all[id] || {}), ...bounds };
    if (id === 'fm') all['file-manager-window'] = all[id];
    if (id === 'file-manager-window') all['fm'] = all[id];
    if (id === 'management') all['management-window'] = all[id];
    if (id === 'management-window') all['management'] = all[id];
    if (id === 'console') all['console-window'] = all[id];
    if (id === 'console-window') all['console'] = all[id];
    if (id === 'smart') all['smart-modal-window'] = all[id];
    if (id === 'smart-modal-window') all['smart'] = all[id];
    if (id === 'container-inspector') all['container-inspector-window'] = all[id];
    if (id === 'container-inspector-window') all['container-inspector'] = all[id];
    localStorage.setItem(WIN_BOUNDS_KEY, JSON.stringify(all));
  } catch (e) {
    console.warn('Failed to save window bounds', e);
  }
}

export function clearMobileInlineBounds(el) {
  if (!el || !el.style) return;
  el.style.removeProperty('top');
  el.style.removeProperty('left');
  el.style.removeProperty('right');
  el.style.removeProperty('bottom');
  el.style.removeProperty('width');
  el.style.removeProperty('height');
  el.style.removeProperty('margin');
  if (el.style.transform && el.style.transform !== 'translateX(-50%)') {
    el.style.removeProperty('transform');
  }
}

let _wasNarrowScreen = typeof window !== 'undefined'
  && (isCompact());

// Phone layout clears window positions. When the screen widens past it (a narrow browser
// window made wider, a tablet turned), put open windows back where they were saved, or at
// least below the navigation bar.
export function restoreWindowsAfterWiden() {
  const narrow = isCompact();
  const widened = _wasNarrowScreen && !narrow;
  _wasNarrowScreen = narrow;
  if (!widened) return;
  const bar = document.querySelector('.suite-navbar, #suite-navbar');
  const barBottom = bar ? Math.round(bar.getBoundingClientRect().bottom) : 48;
  document.querySelectorAll('.os-window').forEach((win) => {
    if (win.dataset.snapped || win.classList.contains('maximized') || getComputedStyle(win).display === 'none') return;
    if (!win.style.top) applySavedBounds(win, win.dataset.windowId || win.id);
    const r = win.getBoundingClientRect();
    if (r.width === 0 || (r.top >= barBottom && r.left >= 0)) return;
    win.style.left = `${Math.max(24, Math.round((window.innerWidth - r.width) / 2))}px`;
    win.style.top = `${barBottom + 8}px`;
  });
}

export function applySavedBounds(dragEl, winId) {
  if (!dragEl || dragEl.id === 'global-toast-container') return;
  if (isCompact()) {
    clearMobileInlineBounds(dragEl);
    return;
  }
  const id = winId || dragEl.id || dragEl.dataset.windowId;
  if (!id) return;
  const all = loadSavedWindowBounds();
  const saved = all[id]
    || (id === 'file-manager-window' ? all['fm'] : (id === 'fm' ? all['file-manager-window'] : null))
    || (id === 'management-window' ? all['management'] : (id === 'management' ? all['management-window'] : null))
    || (id === 'console-window' ? all['console'] : (id === 'console' ? all['console-window'] : null))
    || (id === 'smart-modal-window' ? all['smart'] : (id === 'smart' ? all['smart-modal-window'] : null))
    || (id === 'container-inspector-window' ? all['container-inspector'] : (id === 'container-inspector' ? all['container-inspector-window'] : null))
    || (id === 'app-deploy-modal-window' ? all['app-deploy'] : (id === 'app-deploy' ? all['app-deploy-modal-window'] : null));
  if (!saved || saved.left == null || saved.top == null) return;

  const targetW = saved.width || dragEl.offsetWidth || 500;
  const targetH = saved.height || dragEl.offsetHeight || 400;
  const maxL = Math.max(24, window.innerWidth - targetW - 10);
  const maxT = Math.max(48, window.innerHeight - targetH - 70);
  const clampedLeft = Math.max(24, Math.min(maxL, saved.left));
  const clampedTop = Math.max(48, Math.min(maxT, saved.top));

  dragEl.style.position = 'fixed';
  dragEl.style.left = `${clampedLeft}px`;
  dragEl.style.top = `${clampedTop}px`;
  dragEl.style.transform = 'none';

  if (id === 'console' || id === 'console-window' || dragEl.id === 'console-window' || id === 'copy-toast' || dragEl.id === 'copy-toast') {
    dragEl.style.removeProperty('width');
    dragEl.style.removeProperty('height');
    if (saved && (saved.width || saved.height)) {
      delete saved.width;
      delete saved.height;
      try {
        localStorage.setItem(WIN_BOUNDS_KEY, JSON.stringify(all));
      } catch (_) {}
    }
  } else {
    if (saved.width) {
      dragEl.style.width = `${Math.min(window.innerWidth - 20, Math.max(320, saved.width))}px`;
    }
    if (saved.height) {
      dragEl.style.height = `${Math.min(window.innerHeight - 80, Math.max(200, saved.height))}px`;
    }
  }
  if (saved.snapped) {
    dragEl.dataset.snapped = saved.snapped;
    if (saved.snapped === 'maximize') {
      dragEl.style.left = '8px';
      dragEl.style.top = '48px';
      dragEl.style.width = 'calc(100vw - 16px)';
      dragEl.style.height = 'calc(100vh - 48px - 76px)';
    } else if (saved.snapped === 'left') {
      dragEl.style.left = '8px';
      dragEl.style.top = '48px';
      dragEl.style.width = 'calc(50vw - 12px)';
      dragEl.style.height = 'calc(100vh - 48px - 76px)';
    } else if (saved.snapped === 'right') {
      dragEl.style.left = 'calc(50vw + 4px)';
      dragEl.style.top = '48px';
      dragEl.style.width = 'calc(50vw - 12px)';
      dragEl.style.height = 'calc(100vh - 48px - 76px)';
    } else {
      const geom = getSnapGeometry(saved.snapped);
      if (geom) {
        dragEl.style.left = `${geom.left}px`;
        dragEl.style.top = `${geom.top}px`;
        dragEl.style.width = `${geom.width}px`;
        dragEl.style.height = `${geom.height}px`;
      }
    }
  }
}

let isWindowRestorationComplete = true;

export function setWindowRestorationComplete(val = true) {
  isWindowRestorationComplete = !!val;
}

export function saveOpenWindowsState() {
  if (!isWindowRestorationComplete) return;
  if (state.isVmConsoleDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=vm-console')) || (typeof document !== 'undefined' && document.body && document.body.classList.contains('vm-console-direct'))) return;
  if (isCompact()) return;
  try {
    const stateObj = {
      activeId: DockManager.activeId,
      windows: {}
    };

    if (DockManager && DockManager.windows) {
      Object.keys(DockManager.windows).forEach((id) => {
        const win = DockManager.windows[id];
        if (win && !win.closed && !win.transient) {
          stateObj.windows[id] = {
            minimized: !!win.minimized,
            open: true
          };
          if (id === 'management') {
            const hubView = document.getElementById('management-hub-view');
            const detailContainer = document.getElementById('management-detail-container');
            const isDetailVisible = detailContainer && detailContainer.style.display !== 'none' && (!hubView || hubView.style.display === 'none');
            if (isDetailVisible) {
              const visibleCard = Array.from(document.querySelectorAll('.mgmt-detail-card')).find(
                (c) => c.style.display === 'block' || (c.style.display !== 'none' && c.style.display !== '')
              );
              if (visibleCard) {
                const activeTab = visibleCard.querySelector('.mgmt-inner-tab.active');
                stateObj.windows[id].activePane = (activeTab && activeTab.dataset.tabTarget)
                  ? activeTab.dataset.tabTarget
                  : visibleCard.id;
              } else {
                stateObj.windows[id].activePane = 'hub';
              }
            } else {
              stateObj.windows[id].activePane = 'hub';
            }
          } else if (id === 'fm') {
            const pathInput = document.getElementById('fm-path-input');
            if (pathInput && pathInput.value) {
              stateObj.windows[id].activePath = pathInput.value;
            }
          } else if (id === 'container-inspector') {
            const titleId = document.getElementById('ci-header-id');
            const titleName = document.getElementById('ci-header-title');
            if (titleId && titleId.textContent && titleId.textContent !== '--') {
              stateObj.windows[id].containerData = {
                cid: titleId.textContent.trim(),
                cname: titleName ? titleName.textContent.trim() : ''
              };
            }
          } else if (id === 'smart') {
            const title = document.getElementById('smart-modal-title');
            const match = title ? title.textContent.match(/\b(sd[a-z]|nvme\d+n\d+)\b/) : null;
            if (match) {
              stateObj.windows[id].devName = match[1];
            }
          }
        }
      });
    }

    const notifPanel = document.getElementById('notif-center-panel');
    if (notifPanel && notifPanel.style.display !== 'none' && notifPanel.style.display !== '') {
      stateObj.windows['notif'] = {
        open: true,
        minimized: false
      };
    }

    localStorage.setItem(OPEN_WINDOWS_KEY, JSON.stringify(stateObj));
  } catch (e) {
    console.warn('Failed to save open windows state', e);
  }
}

export function restoreOpenWindowsState() {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (typeof document !== 'undefined' && document.body && document.body.classList.contains('lcd-direct')) || state.isVmConsoleDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=vm-console')) || (typeof document !== 'undefined' && document.body && document.body.classList.contains('vm-console-direct')) || isCompact()) {
    isWindowRestorationComplete = true;
    return;
  }
  try {
    const raw = localStorage.getItem(OPEN_WINDOWS_KEY);
    if (!raw) return;
    const stateObj = JSON.parse(raw);
    if (!stateObj || !stateObj.windows) return;

    const windowIds = Object.keys(stateObj.windows);
    if (windowIds.length === 0) return;

    windowIds.forEach((id) => {
      const entry = stateObj.windows[id];
      if (!entry || !entry.open) return;

      if (id === 'notif') {
        const notifPanel = document.getElementById('notif-center-panel');
        if (notifPanel && (notifPanel.style.display === 'none' || notifPanel.style.display === '')) {
          if (window.toggleNotificationCenter) {
            window.toggleNotificationCenter();
          }
        }
      } else if (id === 'management') {
        if (KNOWN_APPS['management']?.launch) {
          KNOWN_APPS['management'].launch(entry.activePane === 'hub' ? null : entry.activePane);
        } else if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow(entry.activePane === 'hub' ? null : entry.activePane);
        }
        if (entry.minimized) {
          setTimeout(() => {
            if (DockManager.windows['management']) {
              DockManager.minimize('management');
            }
          }, 60);
        }
      } else if (id === 'fm') {
        if (KNOWN_APPS['fm']?.launch) {
          KNOWN_APPS['fm'].launch(entry.activePath);
        } else if (typeof window.openFileManager === 'function') {
          window.openFileManager(entry.activePath);
        }
        if (entry.minimized) {
          setTimeout(() => {
            if (DockManager.windows['fm']) {
              DockManager.minimize('fm');
            }
          }, 60);
        }
      } else if (id === 'console') {
        if (KNOWN_APPS['console']?.launch) {
          KNOWN_APPS['console'].launch();
        } else {
          openConsoleWindow();
        }
        if (entry.minimized) {
          setTimeout(() => {
            if (DockManager.windows['console']) {
              DockManager.minimize('console');
            }
          }, 60);
        }
      } else if (id === 'smart') {
        KNOWN_APPS['smart']?.launch?.(entry.devName);
        if (entry.minimized) {
          setTimeout(() => {
            if (DockManager.windows['smart']) {
              DockManager.minimize('smart');
            }
          }, 60);
        }
      } else if (id === 'container-inspector') {
        if (KNOWN_APPS['container-inspector']?.launch) {
          KNOWN_APPS['container-inspector'].launch(entry.containerData);
        } else if (entry.containerData?.cid && typeof window.openContainerInspector === 'function') {
          window.openContainerInspector(entry.containerData.cid, entry.containerData.cname);
        }
        if (entry.minimized) {
          setTimeout(() => {
            if (DockManager.windows['container-inspector']) {
              DockManager.minimize('container-inspector');
            }
          }, 60);
        }
      } else if (KNOWN_APPS[id] && typeof KNOWN_APPS[id].launch === 'function') {
        KNOWN_APPS[id].launch(entry.activePane);
        if (entry.minimized) {
          setTimeout(() => {
            if (DockManager.windows[id]) {
              DockManager.minimize(id);
            }
          }, 60);
        }
      }
    });

    if (stateObj.activeId) {
      setTimeout(() => {
        const activeWin = DockManager.windows[stateObj.activeId];
        if (activeWin && activeWin.el && !activeWin.minimized) {
          const el = activeWin.el;
          const winEl = el.classList.contains('smart-modal-window') || el.classList.contains('chassis-front-panel') || el.classList.contains('os-window') || el.classList.contains('file-manager-window') || el.classList.contains('mgmt-app-window') || el.classList.contains('container-inspector-window')
            ? el
            : el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .file-manager-window, .mgmt-app-window, .container-inspector-window') || el;
          bringToFront(winEl);
          DockManager.activeId = stateObj.activeId;
          DockManager.render();
        }
      }, 120);
    }
  } catch (e) {
    console.warn('Failed to restore open windows', e);
  } finally {
    isWindowRestorationComplete = true;
    setTimeout(() => {
      saveOpenWindowsState();
    }, 200);
  }
}
