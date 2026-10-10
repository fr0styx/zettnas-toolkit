import { escapeHtml } from '../utils.js';
import { state } from '../state.js';
import { t } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { announceA11y } from '../a11y.js';
import { openSpotlight, initSpotlight } from './spotlight.js';
import {
  initDesktopShortcuts,
  removeDesktopShortcut,
  openAddDesktopShortcutModal
} from './desktop-shortcuts.js';
import { hideDesktopContextMenu } from './desktop-context-menu.js';
/**
 * ZettNAS Toolkit Dock & Window Manager
 * Handles floating modal registration, minimize/restore, dragging, and z-index depth stacking.
 */

export let activeWindowZIndex = 1000;
let lastReadEventTs = parseFloat(localStorage.getItem('zettnas_last_read_event_ts_v2') || '0');
let clearedEventsTs = parseFloat(localStorage.getItem('zettnas_cleared_events_ts') || '0');
let currentNotifFilter = 'all';

let _magnificationEnabled = true;
let _magnificationScale = 1.45;
let _dockPosition = 'bottom';
let _dockSize = 'medium';
let _dockAutohide = false;
let _parabolicInitialized = false;

try {
  localStorage.removeItem('zettnas_last_read_event_ts');
} catch {}

export const CHECKED_EVENTS_KEY = 'zettnas_checked_events_v1';
export const DOCK_PINNED_KEY = 'zettnas_dock_pinned_apps_v1';

let checkedEventKeys = new Set();
try {
  const saved = localStorage.getItem(CHECKED_EVENTS_KEY);
  if (saved) {
    checkedEventKeys = new Set(JSON.parse(saved));
  }
} catch {
  checkedEventKeys = new Set();
}

export function resetCheckedEventsState() {
  checkedEventKeys.clear();
  lastReadEventTs = 0;
  clearedEventsTs = 0;
  try {
    localStorage.removeItem(CHECKED_EVENTS_KEY);
    localStorage.removeItem('zettnas_last_read_event_ts');
    localStorage.removeItem('zettnas_last_read_event_ts_v2');
    localStorage.removeItem('zettnas_cleared_events_ts');
  } catch {}
}

export function getEventKey(e) {
  if (!e) return '';
  return e.id || `${e.ts || 0}_${e.title || ''}_${e.level || ''}`;
}

export function isEventChecked(e) {
  if (!e) return false;
  const key = getEventKey(e);
  if (checkedEventKeys.has(key)) return true;
  if (lastReadEventTs > 0 && e.ts && e.ts <= lastReadEventTs) return true;
  return false;
}

export function saveCheckedEvents() {
  try {
    const arr = Array.from(checkedEventKeys).slice(-500);
    localStorage.setItem(CHECKED_EVENTS_KEY, JSON.stringify(arr));
  } catch (err) {
    console.warn('Failed to save checked events', err);
  }
}

export function markEventChecked(e, persist = true) {
  if (!e) return;
  const key = getEventKey(e);
  checkedEventKeys.add(key);
  if (persist) {
    saveCheckedEvents();
  }
}

export function showDockToast(msg, targetId = null) {
  let container = document.getElementById('global-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'global-toast-container';
    document.body.appendChild(container);
  }

  const dock = document.getElementById('os-dock');
  let bottomPos = 84;
  let leftPos = null;

  if (targetId) {
    const item = document.querySelector(`#os-dock [data-window-id="${targetId}"]`);
    if (item) {
      const rect = item.getBoundingClientRect();
      if (rect.top > 0) {
        bottomPos = Math.max(76, Math.round(window.innerHeight - rect.top + 14));
        leftPos = Math.max(120, Math.min(window.innerWidth - 120, Math.round(rect.left + (rect.width / 2))));
      }
    }
  }

  if (leftPos == null && dock) {
    const dockRect = dock.getBoundingClientRect();
    if (dockRect.top > 0) {
      bottomPos = Math.max(76, Math.round(window.innerHeight - dockRect.top + 14));
    }
  }

  if (_dockPosition === 'left') {
    const dockRect = dock ? dock.getBoundingClientRect() : null;
    const lPos = dockRect ? Math.round(dockRect.right + 24) : 90;
    container.style.position = 'fixed';
    container.style.bottom = '32px';
    container.style.top = 'auto';
    container.style.left = `${lPos}px`;
    container.style.transform = 'none';
  } else if (_dockPosition === 'top') {
    const dockRect = dock ? dock.getBoundingClientRect() : null;
    const tPos = dockRect ? Math.round(dockRect.bottom + 16) : 90;
    container.style.position = 'fixed';
    container.style.top = `${tPos}px`;
    container.style.bottom = 'auto';
    container.style.left = '50%';
    container.style.transform = 'translateX(-50%)';
  } else {
    container.style.position = 'fixed';
    container.style.bottom = `${bottomPos}px`;
    container.style.top = 'auto';
    container.style.left = leftPos != null ? `${leftPos}px` : '50%';
    container.style.transform = 'translateX(-50%)';
  }
  container.style.zIndex = 'var(--z-toast, 10000)';
  container.style.display = 'flex';
  container.style.flexDirection = 'column';
  container.style.alignItems = 'center';
  container.style.gap = '8px';
  container.style.pointerEvents = 'none';

  const toast = document.createElement('div');
  toast.className = 'dock-pin-toast';
  toast.style.cssText = 'background:rgba(18,25,35,0.92); border:1px solid rgba(255,255,255,0.22); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px); color:#fff; font-size:11.5px; font-weight:600; padding:6px 14px; border-radius:18px; box-shadow:0 8px 24px rgba(0,0,0,0.6), 0 0 1px rgba(255,255,255,0.2) inset; pointer-events:none; transition:opacity 0.22s cubic-bezier(0.16, 1, 0.3, 1), transform 0.22s cubic-bezier(0.16, 1, 0.3, 1); transform:translateY(8px) scale(0.96); opacity:0; white-space:nowrap;';
  toast.textContent = msg;
  container.appendChild(toast);

  requestAnimationFrame(() => {
    toast.style.transform = 'translateY(0) scale(1)';
    toast.style.opacity = '1';
  });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-6px) scale(0.96)';
    setTimeout(() => toast.remove(), 250);
  }, 2200);
}

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
  if (!id || document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
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

export function applySavedBounds(dragEl, winId) {
  if (!dragEl || dragEl.id === 'global-toast-container' || document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
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

  if (saved.width) {
    dragEl.style.width = `${Math.min(window.innerWidth - 20, Math.max(320, saved.width))}px`;
  }
  if (saved.height) {
    dragEl.style.height = `${Math.min(window.innerHeight - 80, Math.max(200, saved.height))}px`;
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
  if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
  try {
    const stateObj = {
      activeId: DockManager.activeId,
      windows: {}
    };

    if (DockManager && DockManager.windows) {
      Object.keys(DockManager.windows).forEach((id) => {
        const win = DockManager.windows[id];
        if (win && !win.closed) {
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
  if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) {
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
        if (KNOWN_APPS['smart']?.launch) {
          KNOWN_APPS['smart'].launch(entry.devName);
        } else if (typeof window.openSmartModal === 'function') {
          window.openSmartModal(entry.devName);
        }
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

export function bringToFront(windowEl) {
  if (!windowEl) return;

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
    windowEl.classList?.contains('chassis-front-panel') ||
    windowEl.classList?.contains('management-window') ||
    windowEl.classList?.contains('mgmt-app-window') ||
    windowEl.classList?.contains('file-manager-window') ||
    windowEl.classList?.contains('container-inspector-window') ||
    windowEl.classList?.contains('stack-inspector-window') ||
    windowEl.classList?.contains('app-deploy-window') ||
    windowEl.classList?.contains('os-window') ||
    windowEl.closest?.('#console-modal-overlay, #management-modal-overlay, #file-manager-window, #notif-center-panel, #container-inspector-window, #container-inspector-overlay, #stack-inspector-window, #stack-inspector-overlay, #stack-picker-window, #stack-picker-overlay, #app-deploy-modal-window, #app-deploy-modal-overlay')
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
      const inner = el.querySelector?.('#console-window, #management-window, .chassis-front-panel, .mgmt-app-window, .container-inspector-window, #container-inspector-window, .smart-modal-window, #smart-modal-window, #stack-inspector-window, #stack-picker-window, #app-deploy-modal-window');
      if (inner) inner.style.zIndex = curZ;
    });
    activeWindowZIndex = baseZ;
  }

  const zStr = activeWindowZIndex.toString();
  windowEl.style.zIndex = zStr;

  // Elevate parent overlay wrapper if applicable
  const parentOverlay = windowEl.closest?.('#console-modal-overlay, #management-modal-overlay, #container-inspector-overlay, #smart-modal-overlay, #stack-inspector-overlay, #stack-picker-overlay, #app-deploy-modal-overlay');
  if (parentOverlay && parentOverlay !== windowEl) {
    parentOverlay.style.zIndex = zStr;
  }
  // Elevate child window if applicable
  const childWin = windowEl.querySelector?.('#console-window, #management-window, .chassis-front-panel, .mgmt-app-window, .container-inspector-window, #container-inspector-window, .smart-modal-window, #smart-modal-window, #stack-inspector-window, #stack-picker-window, #app-deploy-modal-window');
  if (childWin && childWin !== windowEl) {
    childWin.style.zIndex = zStr;
  }

  if (window.DockManager) {
    let foundId = null;
    Object.keys(window.DockManager.windows).forEach((id) => {
      const wEl = window.DockManager.windows[id].el;
      if (wEl === windowEl || (wEl && wEl.contains && wEl.contains(windowEl)) || (windowEl && windowEl.contains && windowEl.contains(wEl))) {
        foundId = id;
      }
    });
    if (foundId) {
      window.DockManager.activeId = foundId;
      window.DockManager.render();
      saveOpenWindowsState();
    }
  }

  // Update active-window class for specular border highlight
  try {
    document.querySelectorAll('.active-window').forEach((w) => {
      w.classList.remove('active-window');
    });
    const targetWin = windowEl.querySelector?.('#console-window, #management-window, .chassis-front-panel, .mgmt-app-window, .container-inspector-window, #container-inspector-window, #app-deploy-modal-window') || windowEl;
    if (targetWin && targetWin.classList) targetWin.classList.add('active-window');
  } catch (e) {}
}

export const DESKTOP_WINDOW_SELECTOR = '.smart-modal-window, #console-window, #management-window, #file-manager-window, .file-manager-window, .os-window, #notif-center-panel, .container-inspector-window, #container-inspector-window, #stack-inspector-window, #stack-picker-window, #app-deploy-modal-window';

export const handleWindowActivation = (e) => {
  // If the click directly targeted an overlay backdrop, do not activate it as a window
  if (e.target && (
    e.target.id === 'app-deploy-modal-overlay' ||
    e.target.id === 'management-modal-overlay' ||
    e.target.id === 'console-modal-overlay' ||
    e.target.id === 'smart-modal-overlay'
  )) {
    return;
  }
  const windowEl = e.target.closest?.(DESKTOP_WINDOW_SELECTOR);
  if (windowEl) {
    bringToFront(windowEl);
  } else if (e.target.closest?.('#desktop') && !e.target.closest?.(DESKTOP_WINDOW_SELECTOR)) {
    // User clicked on empty desktop wallpaper or desktop icons/widgets
    document.querySelectorAll('.active-window').forEach((w) => w.classList.remove('active-window'));
    if (window.DockManager) {
      window.DockManager.activeId = null;
      window.DockManager.render();
    }
  }
};

if (typeof document !== 'undefined') {
  document.addEventListener('pointerdown', handleWindowActivation, { capture: true });
  document.addEventListener('mousedown', handleWindowActivation);
}

function getOrCreateSnapGhost() {
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

  // Observe resizing to persist dimensions
  if (window.ResizeObserver && winId) {
    let resizeTimer = null;
    const ro = new ResizeObserver(() => {
      if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
      if (dragEl.dataset.snapped) return;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        const rect = dragEl.getBoundingClientRect();
        if (rect.width > 50 && rect.height > 50) {
          saveWindowBounds(winId, {
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          });
          saveOpenWindowsState();
        }
      }, 250);
    });
    ro.observe(dragEl);
  }

  let startX = 0, startY = 0, initialMouseX = 0, initialMouseY = 0;
  let activeSnap = null;

  dragEl.addEventListener('pointerdown', () => {
    bringToFront(dragEl);
  }, { capture: true });

  handleEl.style.touchAction = 'none';
  handleEl.addEventListener('pointerdown', (e) => {
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

      const onTouchMove = (eMove) => {
        const dy = eMove.clientY - touchStartY;
        if (dy > 0) {
          currentDy = dy;
          dragEl.style.transition = 'none';
          dragEl.style.transform = `translateX(-50%) translateY(${Math.round(dy * 0.75)}px)`;
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
          dragEl.style.transform = 'translateX(-50%) translateY(260px)';
          dragEl.style.opacity = '0';
          setTimeout(() => {
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
          dragEl.style.transform = 'translateX(-50%) translateY(0)';
          dragEl.style.opacity = '1';
          setTimeout(() => {
            dragEl.style.removeProperty('transform');
            dragEl.style.removeProperty('opacity');
            dragEl.style.removeProperty('transition');
          }, 220);
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
      dragEl.style.left = (startX + dx) + 'px';
      dragEl.style.top = (startY + dy) + 'px';

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
  });

  handleEl.addEventListener('dblclick', (e) => {
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
  });
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

export const KNOWN_APPS = {
  fm: {
    id: 'fm',
    icon: '#i-storage',
    getTitle: () => t('dock.file_manager', 'File Explorer'),
    launch: (path = null) => {
      if (typeof window.openFileManager === 'function') {
        window.openFileManager(path);
      } else {
        const fmWin = document.getElementById('file-manager-window');
        if (fmWin) {
          if (window.DockManager && !window.DockManager.windows['fm']) {
            window.DockManager.register('fm', fmWin, '#i-storage', t('dock.file_manager', 'File Explorer'), false);
          }
          if (window.DockManager) window.DockManager.restore('fm');
          ZettEventBus.emit('window:open', { id: 'file-manager-window', path: path || undefined });
        } else {
          document.getElementById('fm-desktop-icon')?.click();
        }
      }
    }
  },
  management: {
    id: 'management',
    icon: '#i-management',
    getTitle: () => t('dock.management', 'Mission Control'),
    launch: (pane = null) => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow(pane === 'hub' ? null : pane);
      } else {
        document.getElementById('management-desktop-icon')?.click();
      }
    }
  },
  console: {
    id: 'console',
    icon: '#i-screen',
    getTitle: () => t('dock.zettnas', 'ZettNAS'),
    launch: () => {
      openConsoleWindow();
    }
  },
  smart: {
    id: 'smart',
    icon: '#i-disk',
    getTitle: () => 'Diagnostics',
    launch: (devName = null) => {
      if (typeof window.openSmartModal === 'function') {
        window.openSmartModal(devName);
      }
    }
  },
  'container-inspector': {
    id: 'container-inspector',
    icon: '#i-chip',
    getTitle: () => 'Container Inspector',
    launch: (data = null) => {
      if (data && data.cid && typeof window.openContainerInspector === 'function') {
        window.openContainerInspector(data.cid, data.cname);
      }
    }
  },
  'app-deploy': {
    id: 'app-deploy',
    icon: '#i-chip',
    getTitle: () => 'App Deployment',
    launch: () => {
      const overlay = document.getElementById('app-deploy-modal-overlay');
      const win = document.getElementById('app-deploy-modal-window');
      if (overlay) {
        if (DockManager) DockManager.restore('app-deploy');
        if (win) bringToFront(win);
      }
    }
  },
  notif: {
    id: 'notif',
    icon: '#i-bell',
    getTitle: () => t('dock.notifications', 'Notification Center'),
    launch: () => {
      const panel = document.getElementById('notif-center-panel');
      if (panel && (panel.style.display === 'none' || panel.style.display === '')) {
        if (window.toggleNotificationCenter) window.toggleNotificationCenter();
      }
    }
  }
};

export function showDockItemContextMenu(x, y, id, title, isPinned, isRunning) {
  const isApp = id && id !== 'home' && id !== 'notif';
  if (!isApp) return;

  let menu = document.getElementById('dock-item-ctx-menu');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = 'dock-item-ctx-menu';
    menu.className = 'os-context-menu dock-context-menu';
    document.body.appendChild(menu);
  }

  const pinLabel = isPinned ? t('dock.unpin', 'Unpin from Dock') : t('dock.pin', 'Pin to Dock');
  const pinIcon = isPinned ? '📌' : '📍';
  const openLabel = t('dock.open_app', 'Open');
  const closeLabel = t('dock.close_window', 'Close Window');

  let html = `
    <div class="ctx-item" id="dock-ctx-pin">
      <span style="font-size:12px; margin-right:6px;">${pinIcon}</span>
      <span>${escapeHtml(pinLabel)}</span>
    </div>
    ${isRunning ? `
      <div class="ctx-item" id="dock-ctx-close" style="color:var(--crit, #ff5c5c);">
        <span style="font-size:11px; margin-right:6px;">✕</span>
        <span>${escapeHtml(closeLabel)}</span>
      </div>
    ` : `
      <div class="ctx-item" id="dock-ctx-open" style="color:var(--ok2, #25c2a0);">
        <span style="font-size:11px; margin-right:6px;">▶</span>
        <span>${escapeHtml(openLabel)}</span>
      </div>
    `}
  `;

  menu.innerHTML = html;
  menu.style.display = 'block';
  const menuW = 160;
  const menuH = menu.offsetHeight || 72;
  const left = Math.max(10, Math.min(window.innerWidth - menuW - 10, x - (menuW / 2)));
  const top = Math.max(10, Math.min(window.innerHeight - menuH - 60, y - menuH - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;

  const hideMenu = (ev) => {
    if (ev && ev.target && ev.target.closest('#dock-item-ctx-menu')) return;
    menu.style.display = 'none';
    document.removeEventListener('pointerdown', hideMenu);
    document.removeEventListener('click', hideMenu);
  };
  setTimeout(() => {
    document.addEventListener('pointerdown', hideMenu);
    document.addEventListener('click', hideMenu);
  }, 100);

  document.getElementById('dock-ctx-pin')?.addEventListener('click', (e) => {
    e.stopPropagation();
    DockManager.togglePin(id);
    hideMenu();
  });

  document.getElementById('dock-ctx-close')?.addEventListener('click', (e) => {
    e.stopPropagation();
    DockManager.closeWindow(id);
    hideMenu();
  });

  document.getElementById('dock-ctx-open')?.addEventListener('click', (e) => {
    e.stopPropagation();
    if (KNOWN_APPS[id]?.launch) {
      KNOWN_APPS[id].launch();
    }
    hideMenu();
  });
}

export const DockManager = {
  windows: {},
  activeId: null,

  getPinnedApps() {
    try {
      const raw = localStorage.getItem(DOCK_PINNED_KEY);
      if (raw) {
        const list = JSON.parse(raw);
        if (Array.isArray(list)) return list;
      }
    } catch (e) {
      console.warn('Failed to load pinned apps', e);
    }
    return [];
  },

  isPinned(id) {
    if (!id || id === 'home' || id === 'notif') return false;
    return this.getPinnedApps().includes(id);
  },

  pinApp(id) {
    if (!id || id === 'home' || id === 'notif') return;
    const list = this.getPinnedApps();
    if (!list.includes(id)) {
      list.push(id);
      localStorage.setItem(DOCK_PINNED_KEY, JSON.stringify(list));
      this.render();
      const appName = KNOWN_APPS[id]?.getTitle ? KNOWN_APPS[id].getTitle() : (this.windows[id]?.title || '');
      const toastMsg = appName ? `${appName}: ${t('dock.pinned_toast', 'Pinned to Dock')}` : t('dock.pinned_toast', 'Pinned to Dock');
      showDockToast(toastMsg, id);
    }
  },

  unpinApp(id) {
    if (!id) return;
    let list = this.getPinnedApps();
    if (list.includes(id)) {
      list = list.filter((item) => item !== id);
      localStorage.setItem(DOCK_PINNED_KEY, JSON.stringify(list));
      if (this.windows[id] && this.windows[id].closed) {
        delete this.windows[id];
      }
      this.render();
      const appName = KNOWN_APPS[id]?.getTitle ? KNOWN_APPS[id].getTitle() : (this.windows[id]?.title || '');
      const toastMsg = appName ? `${appName}: ${t('dock.unpinned_toast', 'Unpinned from Dock')}` : t('dock.unpinned_toast', 'Unpinned from Dock');
      showDockToast(toastMsg, id);
    }
  },

  togglePin(id) {
    if (this.isPinned(id)) {
      this.unpinApp(id);
    } else {
      this.pinApp(id);
    }
  },

  closeWindow(id) {
    if (id === 'fm') {
      const fmClose = document.getElementById('fm-close');
      if (fmClose) { fmClose.click(); return; }
    } else if (id === 'management') {
      const mgmtClose = document.getElementById('management-close');
      if (mgmtClose) { mgmtClose.click(); return; }
    } else if (id === 'console') {
      const consoleOverlay = document.getElementById('console-modal-overlay');
      const consoleModal = document.getElementById('console-window');
      if (consoleOverlay) {
        consoleOverlay.classList.remove('open');
        consoleOverlay.style.setProperty('display', 'none', 'important');
      }
      if (consoleModal) {
        consoleModal.classList.add('window-minimized');
        consoleModal.style.setProperty('display', 'none', 'important');
      }
      this.unregister('console');
      return;
    } else if (id === 'smart') {
      const smartClose = document.getElementById('smart-modal-close');
      if (smartClose) { smartClose.click(); return; }
    } else if (id === 'container-inspector') {
      const ciClose = document.getElementById('ci-close-btn');
      if (ciClose) { ciClose.click(); return; }
    } else if (id === 'app-deploy') {
      const deployClose = document.getElementById('adm-close-btn');
      if (deployClose) { deployClose.click(); return; }
    }
    this.unregister(id);
  },

  register(id, el, icon, title, initialMinimized = false) {
    if (!this.windows[id]) {
      this.windows[id] = { el, icon, title, minimized: initialMinimized, closed: initialMinimized };
    } else {
      this.windows[id].el = el;
      if (icon) this.windows[id].icon = icon;
      if (title) this.windows[id].title = title;
      this.windows[id].closed = initialMinimized;
    }
    const innerWin = el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .mgmt-app-window, .file-manager-window');
    if (!initialMinimized) {
      this.windows[id].minimized = false;
      this.windows[id].closed = false;
      el.classList.remove('window-minimized');
      el.classList.add('open');
      if (el.classList.contains('smart-modal-backdrop') || el.classList.contains('os-window') || el.classList.contains('file-manager-window')) {
        el.style.display = 'flex';
      } else {
        el.style.removeProperty('display');
      }
      if (innerWin) {
        innerWin.classList.remove('window-minimized');
        innerWin.style.removeProperty('display');
      }
    } else {
      this.windows[id].minimized = true;
      this.windows[id].closed = true;
      el.classList.add('window-minimized');
      el.classList.remove('open');
      el.style.setProperty('display', 'none', 'important');
      if (innerWin) {
        innerWin.classList.add('window-minimized');
        innerWin.style.setProperty('display', 'none', 'important');
      }
    }
    this.render();
    if (!initialMinimized) {
      saveOpenWindowsState();
    }
  },

  unregister(id) {
    if (this.windows[id]) {
      if (this.isPinned(id)) {
        this.windows[id].minimized = true;
        this.windows[id].closed = true;
        if (this.windows[id].el) {
          this.windows[id].el.classList.add('window-minimized');
          this.windows[id].el.classList.remove('open');
          this.windows[id].el.style.setProperty('display', 'none', 'important');
          const innerWin = this.windows[id].el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .mgmt-app-window');
          if (innerWin) {
            innerWin.classList.add('window-minimized');
            innerWin.style.setProperty('display', 'none', 'important');
          }
        }
      } else {
        delete this.windows[id];
      }
      if (this.activeId === id) this.activeId = null;
      this.render();
      saveOpenWindowsState();
    }
  },

  minimize(id) {
    if (this.windows[id]) {
      this.windows[id].minimized = true;
      this.windows[id].el.classList.add('window-minimized');
      this.windows[id].el.classList.remove('open');
      this.windows[id].el.style.setProperty('display', 'none', 'important');
      const innerWin = this.windows[id].el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .mgmt-app-window');
      if (innerWin) {
        innerWin.classList.add('window-minimized');
        innerWin.style.setProperty('display', 'none', 'important');
      }
      this.render();
      saveOpenWindowsState();
    }
  },

  restore(id) {
    if (this.windows[id]) {
      this.windows[id].minimized = false;
      this.windows[id].closed = false;
      this.windows[id].el.classList.remove('window-minimized');
      this.windows[id].el.classList.add('open');
      this.windows[id].el.style.removeProperty('display');

      const el = this.windows[id].el;
      if (el.classList.contains('os-window') || el.classList.contains('file-manager-window') || el.classList.contains('smart-modal-backdrop')) {
        el.style.setProperty('display', 'flex', 'important');
      }

      const winEl = el.classList.contains('smart-modal-window') || el.classList.contains('chassis-front-panel') || el.classList.contains('os-window') || el.classList.contains('file-manager-window') || el.classList.contains('mgmt-app-window')
        ? el
        : el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .file-manager-window, .mgmt-app-window') || el;
      if (winEl) {
        winEl.classList.remove('window-minimized');
        winEl.style.removeProperty('display');
        bringToFront(winEl);
        applySavedBounds(winEl, id);
      }
      if (id === 'console' && window.updateLcdPages && state.latestStats) {
        window.updateLcdPages(state.latestStats);
      }
      this.render();
      saveOpenWindowsState();
    }
  },

  toggle(id) {
    if (this.windows[id]) {
      if (this.windows[id].minimized) {
        this.restore(id);
      } else {
        const el = this.windows[id].el;
        const winEl = el.classList.contains('smart-modal-window') || el.classList.contains('chassis-front-panel') || el.classList.contains('os-window') || el.classList.contains('file-manager-window') || el.classList.contains('mgmt-app-window')
          ? el
          : el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .file-manager-window, .mgmt-app-window') || el;
        if (winEl) {
          bringToFront(winEl);
        }
      }
    }
  },

  render() {
    const dockContainer = document.getElementById('os-dock-container');
    const dock = document.getElementById('os-dock');
    if (!dock || !dockContainer) return;

    dock.classList.add('active');
    dock.innerHTML = '';

    let hoverTimeout = null;

    function ensureDockTooltip() {
      let tooltip = document.getElementById('dock-hover-tooltip');
      if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'dock-hover-tooltip';
        tooltip.className = 'dock-hover-tooltip';
        tooltip.innerHTML = `
          <div class="dock-tooltip-header">
            <div class="dock-tooltip-title">
              <svg class="ic ic-sm" id="dock-tooltip-icon"><use href="#i-chip"/></svg>
              <span id="dock-tooltip-text">Window</span>
            </div>
            <span class="dock-tooltip-status" id="dock-tooltip-badge">Active</span>
          </div>
          <div class="dock-tooltip-preview" id="dock-tooltip-preview-content"></div>
        `;
        document.body.appendChild(tooltip);

        tooltip.addEventListener('mouseenter', () => clearTimeout(hoverTimeout));
        tooltip.addEventListener('mouseleave', () => hideDockTooltip());
      }
      return tooltip;
    }

    function generatePreviewForWindow(id) {
      if (id === 'console') {
        const screenEl = document.getElementById('screen');
        if (screenEl) {
          const container = document.createElement('div');
          container.className = 'mini-screen-scaler';
          const clone = screenEl.cloneNode(true);
          clone.removeAttribute('id');
          clone.querySelectorAll('[id]').forEach((el) => el.removeAttribute('id'));
          container.appendChild(clone);
          return container;
        }
      } else if (id === 'smart') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        const model = escapeHtml(document.getElementById('smart-meta-model')?.textContent || 'Drive Health');
        const health = escapeHtml(document.getElementById('smart-meta-health')?.textContent || 'PASSED');
        const hours = escapeHtml(document.getElementById('smart-meta-hours')?.textContent || '--');
        const devTitle = escapeHtml(document.getElementById('smart-modal-title')?.textContent || 'Diagnostics');
        container.innerHTML = `
          <div style="font-size:10px; font-weight:700; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${devTitle}</div>
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:9px;">
            <span style="color:var(--muted);">Status:</span>
            <strong style="color:${health.includes('PASS') ? 'var(--ok)' : 'var(--crit)'}; font-weight:800;">${health}</strong>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:9px;">
            <span style="color:var(--muted);">Power-on:</span>
            <span style="color:#cbd5e1;">${hours} hrs</span>
          </div>
        `;
        return container;
      } else if (id === 'management') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        container.style.cssText = 'display:flex; align-items:center; gap:8px; height:100%;';
        container.innerHTML = `
          <img src="img/chassis-d6u.webp" style="width:38px; height:auto; border-radius:4px; filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5));" alt="Chassis">
          <div style="display:flex; flex-direction:column; gap:2px; overflow:hidden;">
            <div style="font-size:10px; font-weight:700; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Mission Control</div>
            <div style="font-size:8px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Profiles • Containers • Storage</div>
          </div>
        `;
        return container;
      } else if (id === 'copy') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        const status = escapeHtml(document.getElementById('copy-toast-status')?.textContent || 'Ingest');
        const pct = escapeHtml(document.getElementById('copy-toast-pct')?.textContent || '0%');
        const file = escapeHtml(document.getElementById('copy-toast-file')?.textContent || 'Preparing...');
        container.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:9px;">
            <strong style="color:#fff;">${status}</strong>
            <strong style="color:var(--ok2);">${pct}</strong>
          </div>
          <div style="background:rgba(255,255,255,0.12); height:4px; border-radius:2px; overflow:hidden; margin:4px 0;">
            <div style="background:var(--ok2); height:100%; width:${pct};"></div>
          </div>
          <div style="font-size:8px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${file}</div>
        `;
        return container;
      } else if (id === 'fb' || id === 'folder') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        const path = escapeHtml(document.getElementById('fb-current-path')?.textContent || '/mnt/user');
        container.innerHTML = `
          <div style="font-size:9px; font-weight:700; color:#fff;">Folder Destination</div>
          <div style="font-family:monospace; font-size:8px; color:var(--ok2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:3px;">${path}</div>
        `;
        return container;
      } else if (id === 'fm') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        const pathInput = document.getElementById('fm-path-input');
        const path = pathInput ? pathInput.value : '/mnt/user';
        container.innerHTML = `
          <div style="font-size:10px; font-weight:700; color:#fff;">File Explorer</div>
          <div style="font-family:monospace; font-size:9px; color:var(--accent-cyan, #0ea5e9); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:3px;">${path.replace(/</g, '&lt;')}</div>
        `;
        return container;
      } else if (id === 'home') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        container.style.cssText = 'display:flex; align-items:center; gap:8px; height:100%;';
        container.innerHTML = `
          <img src="img/chassis-d6u.webp" style="width:42px; height:auto; border-radius:4px; filter:drop-shadow(0 2px 5px rgba(0,0,0,0.5));" alt="Chassis">
          <div style="display:flex; flex-direction:column; gap:2px;">
            <span style="font-size:10px; font-weight:700; color:#fff;">Desktop Home</span>
            <span style="font-size:8px; color:var(--muted);">Click to clear / minimize all</span>
          </div>
        `;
        return container;
      } else if (id === 'notif') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        container.style.cssText = 'cursor:pointer;';
        container.addEventListener('click', () => {
          hideDockTooltip();
          if (window.toggleNotificationCenter) window.toggleNotificationCenter();
        });

        const events = (state.latestStats && Array.isArray(state.latestStats.events))
          ? [...state.latestStats.events].filter((e) => e.ts > clearedEventsTs).sort((a, b) => b.ts - a.ts)
          : [];

        if (events.length === 0) {
          container.innerHTML = `
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:12px;">🔔</span>
              <strong style="font-size:10px; color:#fff;">Notification Center</strong>
            </div>
            <div style="font-size:8.5px; color:var(--muted); margin-top:2px;">No recent system notifications</div>
          `;
          return container;
        }

        const unread = events.filter((e) => !isEventChecked(e) && e.ts > clearedEventsTs);
        const topEvent = unread.length > 0 ? unread[0] : events[0];

        let icon = 'ℹ️';
        let color = '#93c5fd';
        if (topEvent.level === 'error') { icon = '❌'; color = 'var(--crit, #ff5c5c)'; }
        else if (topEvent.level === 'warning') { icon = '⚠️'; color = 'var(--warn, #f5a623)'; }
        else if (topEvent.level === 'success') { icon = '✅'; color = 'var(--ok2, #25c2a0)'; }

        const title = escapeHtml(topEvent.title || 'Notification');
        const msg = escapeHtml(topEvent.message || '');
        const timeStr = topEvent.ts
          ? new Date(topEvent.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          : '';

        container.innerHTML = `
          <div style="display:flex; align-items:center; justify-content:space-between; gap:6px;">
            <div style="display:flex; align-items:center; gap:5px; min-width:0; overflow:hidden;">
              <span style="font-size:11px; line-height:1; flex-shrink:0;">${icon}</span>
              <strong style="font-size:10px; color:${color}; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${title}</strong>
            </div>
            <span style="font-size:8px; color:var(--muted); flex-shrink:0;">${timeStr}</span>
          </div>
          <div style="display:flex; align-items:center; justify-content:space-between; gap:4px; margin-top:2px;">
            <span style="font-size:9px; color:#cbd5e1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1;">${msg}</span>
            ${unread.length > 1 ? `<span style="font-size:8px; color:var(--accent-cyan, #0ea5e9); font-weight:700; white-space:nowrap; flex-shrink:0;">+${unread.length - 1} more</span>` : ''}
          </div>
        `;
        return container;
      } else if (KNOWN_APPS[id]) {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        const title = KNOWN_APPS[id].getTitle();
        container.innerHTML = `
          <div style="font-size:10px; font-weight:700; color:#fff;">${escapeHtml(title)}</div>
          <div style="font-size:8.5px; color:var(--muted); margin-top:2px;">Click to open application</div>
        `;
        return container;
      }
      return null;
    }

    function showDockTooltip(dockItem, id, title, icon, isMinimized, isClosed = false) {
      clearTimeout(hoverTimeout);
      const tooltip = ensureDockTooltip();
      const textEl = document.getElementById('dock-tooltip-text');
      const iconEl = document.getElementById('dock-tooltip-icon');
      const badgeEl = document.getElementById('dock-tooltip-badge');
      const previewEl = document.getElementById('dock-tooltip-preview-content');

      if (textEl) textEl.textContent = title;
      if (iconEl) iconEl.innerHTML = `<use href="${icon}"/>`;
      if (badgeEl) {
        if (id === 'home') {
          badgeEl.textContent = 'Workspace';
          badgeEl.className = 'dock-tooltip-status active';
        } else if (id === 'notif') {
          const events = (state.latestStats && Array.isArray(state.latestStats.events)) ? state.latestStats.events : [];
          const unreadCount = events.filter((e) => !isEventChecked(e) && e.ts > clearedEventsTs).length;
          if (unreadCount > 0) {
            badgeEl.textContent = `${unreadCount > 99 ? '99+' : unreadCount} UNREAD`;
            badgeEl.className = 'dock-tooltip-status alert';
          } else {
            badgeEl.textContent = 'ALL CAUGHT UP';
            badgeEl.className = 'dock-tooltip-status active';
          }
        } else if (isClosed) {
          badgeEl.textContent = 'Pinned';
          badgeEl.className = 'dock-tooltip-status';
        } else {
          badgeEl.textContent = isMinimized ? 'Minimized' : 'Active';
          badgeEl.className = 'dock-tooltip-status ' + (isMinimized ? 'minimized' : 'active');
        }
      }

      if (previewEl) {
        const previewContent = generatePreviewForWindow(id);
        if (previewContent) {
          if (typeof previewEl.replaceChildren === 'function') {
            previewEl.replaceChildren(previewContent);
          } else {
            previewEl.innerHTML = '';
            previewEl.appendChild(previewContent);
          }
          previewEl.style.display = 'flex';
        } else {
          previewEl.style.display = 'none';
          if (typeof previewEl.replaceChildren === 'function') {
            previewEl.replaceChildren();
          } else {
            previewEl.innerHTML = '';
          }
        }
      }

      const isAlreadyVisibleForThisItem = tooltip.classList.contains('visible') && tooltip.dataset.currentWindowId === id;
      tooltip.dataset.currentWindowId = id;

      if (!isAlreadyVisibleForThisItem) {
        const dockEl = document.getElementById('os-dock');
        const dockRect = dockEl ? dockEl.getBoundingClientRect() : null;
        const rect = dockItem.getBoundingClientRect();
        const tooltipW = tooltip.offsetWidth || 210;
        const tooltipH = tooltip.offsetHeight || 50;

        if (_dockPosition === 'left') {
          const leftPos = dockRect ? Math.round(dockRect.right + 12) : Math.round(rect.right + 12);
          let topPos = Math.round(rect.top + (rect.height / 2) - (tooltipH / 2));
          topPos = Math.max(56, Math.min(window.innerHeight - tooltipH - 16, topPos));
          tooltip.style.left = `${leftPos}px`;
          tooltip.style.top = `${topPos}px`;
          tooltip.style.bottom = 'auto';
        } else if (_dockPosition === 'top') {
          const centerX = (dockEl && dockRect && typeof dockItem.offsetLeft === 'number')
            ? (dockRect.left + dockItem.offsetLeft - (dockEl.scrollLeft || 0) + (dockItem.offsetWidth / 2))
            : (rect.left + (rect.width / 2));
          let leftPos = Math.round(centerX - (tooltipW / 2));
          leftPos = Math.max(24, Math.min(window.innerWidth - tooltipW - 10, leftPos));
          const topPos = dockRect ? Math.round(dockRect.bottom + 12) : Math.round(rect.bottom + 12);
          tooltip.style.left = `${leftPos}px`;
          tooltip.style.top = `${topPos}px`;
          tooltip.style.bottom = 'auto';
        } else {
          // Bottom (Default)
          const centerX = (dockEl && dockRect && typeof dockItem.offsetLeft === 'number')
            ? (dockRect.left + dockItem.offsetLeft - (dockEl.scrollLeft || 0) + (dockItem.offsetWidth / 2))
            : (rect.left + (rect.width / 2));

          let leftPos = Math.round(centerX - (tooltipW / 2));
          leftPos = Math.max(24, Math.min(window.innerWidth - tooltipW - 10, leftPos));
          const bottomPos = dockRect
            ? Math.max(10, Math.round(window.innerHeight - dockRect.top + 14))
            : Math.max(10, Math.round(window.innerHeight - rect.top + 10));

          tooltip.style.left = `${leftPos}px`;
          tooltip.style.bottom = `${bottomPos}px`;
          tooltip.style.top = 'auto';
        }

        tooltip.classList.add('visible');
      }
    }

    this.showTooltip = showDockTooltip;

    function hideDockTooltip() {
      clearTimeout(hoverTimeout);
      hoverTimeout = setTimeout(() => {
        const tooltip = document.getElementById('dock-hover-tooltip');
        if (tooltip) tooltip.classList.remove('visible');
      }, 120);
    }

    const dashItem = document.createElement('button');
    dashItem.type = 'button';
    dashItem.className = 'dock-item';
    dashItem.setAttribute('aria-label', t('dock.home', 'Dashboard Home'));
    dashItem.innerHTML = `<svg><use href="#i-globe"/></svg>`;
    dashItem.addEventListener('mouseenter', () => showDockTooltip(dashItem, 'home', t('dock.home', 'Dashboard Home'), '#i-globe', false));
    dashItem.addEventListener('focus', () => showDockTooltip(dashItem, 'home', t('dock.home', 'Dashboard Home'), '#i-globe', false));
    dashItem.addEventListener('mouseleave', hideDockTooltip);
    dashItem.addEventListener('blur', hideDockTooltip);
    dashItem.addEventListener('click', () => {
      hideDockTooltip();
      const winIds = Object.keys(this.windows);
      const anyOpen = winIds.some((id) => !this.windows[id].minimized);
      if (anyOpen) {
        winIds.forEach((id) => this.minimize(id));
      } else {
        winIds.forEach((id) => this.restore(id));
      }
    });
    dock.appendChild(dashItem);

    // Spotlight Quick Launcher
    const spotItem = document.createElement('button');
    spotItem.type = 'button';
    spotItem.className = 'dock-item dock-item-spotlight';
    spotItem.setAttribute('aria-label', 'Spotlight Command Palette (Cmd+K)');
    spotItem.innerHTML = `<span style="font-size:15px; line-height:1;">🔍</span>`;
    spotItem.addEventListener('mouseenter', () => showDockTooltip(spotItem, 'spotlight', 'Command Palette (Cmd+K)', '', false));
    spotItem.addEventListener('focus', () => showDockTooltip(spotItem, 'spotlight', 'Command Palette (Cmd+K)', '', false));
    spotItem.addEventListener('mouseleave', hideDockTooltip);
    spotItem.addEventListener('blur', hideDockTooltip);
    spotItem.addEventListener('click', () => {
      hideDockTooltip();
      openSpotlight();
    });
    dock.appendChild(spotItem);

    // Dynamic apps (pinned + running)
    const pinned = this.getPinnedApps();
    const runningIds = Object.keys(this.windows).filter((id) => !this.windows[id].closed);
    const displayedIds = [...pinned];
    runningIds.forEach((id) => {
      if (!displayedIds.includes(id)) {
        displayedIds.push(id);
      }
    });

    displayedIds.forEach((id) => {
      const isRunning = !!(this.windows[id] && !this.windows[id].closed);
      const isPinned = this.isPinned(id);
      const win = this.windows[id] || (KNOWN_APPS[id] ? {
        icon: KNOWN_APPS[id].icon,
        title: KNOWN_APPS[id].getTitle(),
        minimized: true,
        closed: true,
      } : null);

      if (!win) return;

      const item = document.createElement('button');
      item.type = 'button';
      let cls = 'dock-item';
      if (!isRunning) cls += ' pinned-closed';
      else if (win.minimized) cls += ' minimized';
      if (this.activeId === id && isRunning && !win.minimized) cls += ' active-window';
      item.className = cls;
      item.setAttribute('aria-label', win.title);
      item.dataset.windowId = id;
      item.innerHTML = `<svg><use href="${win.icon}"/></svg>`;

      item.addEventListener('mousedown', (e) => e.stopPropagation());
      item.addEventListener('mouseenter', () => showDockTooltip(item, id, win.title, win.icon, win.minimized, !isRunning));
      item.addEventListener('focus', () => showDockTooltip(item, id, win.title, win.icon, win.minimized, !isRunning));
      item.addEventListener('mouseleave', hideDockTooltip);
      item.addEventListener('blur', hideDockTooltip);
      item.addEventListener('click', () => {
        hideDockTooltip();
        if (!isRunning) {
          if (KNOWN_APPS[id]?.launch) {
            KNOWN_APPS[id].launch();
          }
        } else {
          this.toggle(id);
        }
      });
      item.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        hideDockTooltip();
        showDockItemContextMenu(e.pageX, e.pageY, id, win.title, isPinned, isRunning);
      });

      dock.appendChild(item);
    });

    // Notification Center Button
    const notifItem = document.createElement('button');
    notifItem.type = 'button';
    notifItem.className = 'dock-item dock-notif-btn';
    notifItem.setAttribute('aria-label', t('dock.notifications', 'Notification Center'));
    notifItem.innerHTML = `<svg><use href="#i-bell"/></svg><span class="dock-badge" id="dock-notif-badge" style="display:none; position:absolute; top:-2px; right:-2px; background:var(--crit); color:#fff; font-size:9px; font-weight:800; padding:1px 4px; border-radius:8px; border:1px solid #000; box-shadow:0 1px 2px rgba(0,0,0,0.5); pointer-events:none;">0</span>`;
    notifItem.addEventListener('mouseenter', () => showDockTooltip(notifItem, 'notif', t('dock.notifications', 'Notification Center'), '#i-bell', false));
    notifItem.addEventListener('focus', () => showDockTooltip(notifItem, 'notif', t('dock.notifications', 'Notification Center'), '#i-bell', false));
    notifItem.addEventListener('mouseleave', hideDockTooltip);
    notifItem.addEventListener('blur', hideDockTooltip);
    notifItem.addEventListener('click', () => {
      hideDockTooltip();
      if (window.toggleNotificationCenter) window.toggleNotificationCenter();
    });
    dock.appendChild(notifItem);

    if (dock.classList.contains('dock-magnify-enabled')) {
      dock.querySelectorAll('.dock-item').forEach((item) => {
        item.style.setProperty('--dock-item-scale', '1');
      });
    }

  }
};

export function initParabolicDockMagnification(dockEl) {
  if (!dockEl) dockEl = document.getElementById('os-dock');
  if (!dockEl) return;
  if (dockEl._parabolicBound) return;
  dockEl._parabolicBound = true;

  const radius = 130;

  dockEl.addEventListener('pointermove', (e) => {
    if (!_magnificationEnabled) return;
    if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const items = Array.from(dockEl.querySelectorAll('.dock-item'));
    if (!items.length) return;

    const isVertical = _dockPosition === 'left';
    const pointerPos = isVertical ? (e.clientY ?? 0) : (e.clientX ?? 0);

    items.forEach((item) => {
      const rect = item.getBoundingClientRect();
      const center = isVertical
        ? (rect.top + rect.height / 2)
        : (rect.left + rect.width / 2);
      const distance = Math.abs(pointerPos - center);

      let scale = 1;
      if (distance < radius) {
        const cosFactor = Math.cos((distance / radius) * (Math.PI / 2));
        scale = 1 + (_magnificationScale - 1) * cosFactor;
      }
      item.style.setProperty('--dock-item-scale', scale.toFixed(3));
    });
  });

  dockEl.addEventListener('pointerleave', () => {
    const items = dockEl.querySelectorAll('.dock-item');
    items.forEach((item) => {
      item.style.setProperty('--dock-item-scale', '1');
    });
  });
}

export function applyDockSettings(position = 'bottom', magnification = true, maxScale = 1.45, iconSize = 'medium', autohide = false, persist = true) {
  _dockPosition = ['bottom', 'left', 'top'].includes(position) ? position : 'bottom';
  _magnificationEnabled = Boolean(magnification);
  _magnificationScale = Math.max(1.1, Math.min(1.8, parseFloat(maxScale) || 1.45));
  _dockSize = ['small', 'medium', 'large'].includes(iconSize) ? iconSize : 'medium';
  _dockAutohide = Boolean(autohide);

  if (typeof document !== 'undefined') {
    const root = document.documentElement;
    const dockContainer = document.getElementById('os-dock-container');
    const dock = document.getElementById('os-dock');

    let heightVal = '52px';
    let iconPx = '48px';
    if (_dockSize === 'small') {
      heightVal = '44px';
      iconPx = '42px';
    } else if (_dockSize === 'large') {
      heightVal = '64px';
      iconPx = '60px';
    }

    if (root) {
      root.style.setProperty('--dock-position', _dockPosition);
      root.style.setProperty('--dock-height', heightVal);
      root.style.setProperty('--dock-icon-size', iconPx);

      if (_dockPosition === 'bottom') {
        root.style.setProperty('--workspace-inset-bottom', _dockAutohide ? '0px' : `calc(${heightVal} + 16px)`);
        root.style.setProperty('--workspace-inset-left', '0px');
        root.style.setProperty('--workspace-inset-top', '0px');
      } else if (_dockPosition === 'left') {
        root.style.setProperty('--workspace-inset-bottom', '0px');
        root.style.setProperty('--workspace-inset-left', _dockAutohide ? '0px' : `calc(${heightVal} + 16px)`);
        root.style.setProperty('--workspace-inset-top', '0px');
      } else if (_dockPosition === 'top') {
        root.style.setProperty('--workspace-inset-bottom', '0px');
        root.style.setProperty('--workspace-inset-left', '0px');
        root.style.setProperty('--workspace-inset-top', _dockAutohide ? '0px' : `calc(${heightVal} + 16px)`);
      }
    }

    if (dockContainer) {
      dockContainer.classList.remove('dock-pos-bottom', 'dock-pos-left', 'dock-pos-top');
      dockContainer.classList.add(`dock-pos-${_dockPosition}`);
      dockContainer.classList.toggle('dock-autohide', _dockAutohide);
    }

    if (dock) {
      dock.classList.remove('dock-size-small', 'dock-size-medium', 'dock-size-large');
      dock.classList.add(`dock-size-${_dockSize}`);
      dock.classList.toggle('dock-magnify-enabled', _magnificationEnabled);

      if (!_magnificationEnabled) {
        dock.querySelectorAll('.dock-item').forEach((item) => {
          item.style.setProperty('--dock-item-scale', '1');
        });
      }
    }

    const posBtns = document.querySelectorAll('.dock-pos-btn');
    posBtns.forEach((btn) => {
      const isMatch = btn.dataset.pos === _dockPosition;
      btn.classList.toggle('active', isMatch);
      btn.setAttribute('aria-checked', isMatch ? 'true' : 'false');
    });

    const sizeBtns = document.querySelectorAll('.dock-size-btn');
    sizeBtns.forEach((btn) => {
      const isMatch = btn.dataset.size === _dockSize;
      btn.classList.toggle('active', isMatch);
      btn.setAttribute('aria-checked', isMatch ? 'true' : 'false');
    });

    const magToggle = document.getElementById('dock-magnification-toggle');
    if (magToggle) magToggle.checked = _magnificationEnabled;

    const magSlider = document.getElementById('dock-magnification-slider');
    if (magSlider && parseFloat(magSlider.value) !== _magnificationScale) {
      magSlider.value = _magnificationScale.toString();
    }

    const magVal = document.getElementById('dock-magnification-val');
    if (magVal) magVal.textContent = `${_magnificationScale.toFixed(2)}x`;

    const autohideToggle = document.getElementById('dock-autohide-toggle');
    if (autohideToggle) autohideToggle.checked = _dockAutohide;
  }

  if (persist) {
    try {
      localStorage.setItem('zettnas_dock_position', _dockPosition);
      localStorage.setItem('zettnas_dock_magnification', _magnificationEnabled ? 'true' : 'false');
      localStorage.setItem('zettnas_dock_scale', _magnificationScale.toString());
      localStorage.setItem('zettnas_dock_size', _dockSize);
      localStorage.setItem('zettnas_dock_autohide', _dockAutohide ? 'true' : 'false');
    } catch (e) {}
  }
}

export function getDockSettings() {
  return {
    position: _dockPosition,
    magnification: _magnificationEnabled,
    scale: _magnificationScale,
    size: _dockSize,
    autohide: _dockAutohide
  };
}

export function initDockSettingsControls() {
  let savedPos = 'bottom';
  let savedMag = true;
  let savedScale = 1.45;
  let savedSize = 'medium';
  let savedAutohide = false;

  try {
    const p = localStorage.getItem('zettnas_dock_position');
    if (p) savedPos = p;
    const m = localStorage.getItem('zettnas_dock_magnification');
    if (m !== null) savedMag = (m === 'true');
    const s = localStorage.getItem('zettnas_dock_scale');
    if (s !== null) savedScale = parseFloat(s) || 1.45;
    const sz = localStorage.getItem('zettnas_dock_size');
    if (sz) savedSize = sz;
    const ah = localStorage.getItem('zettnas_dock_autohide');
    if (ah !== null) savedAutohide = (ah === 'true');
  } catch (e) {}

  applyDockSettings(savedPos, savedMag, savedScale, savedSize, savedAutohide, false);

  const dockEl = document.getElementById('os-dock');
  if (dockEl) {
    initParabolicDockMagnification(dockEl);
  }

  const posBtns = document.querySelectorAll('.dock-pos-btn');
  posBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const pos = btn.dataset.pos;
      applyDockSettings(pos, _magnificationEnabled, _magnificationScale, _dockSize, _dockAutohide, true);
    });
  });

  const sizeBtns = document.querySelectorAll('.dock-size-btn');
  sizeBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const sz = btn.dataset.size;
      applyDockSettings(_dockPosition, _magnificationEnabled, _magnificationScale, sz, _dockAutohide, true);
    });
  });

  const magToggle = document.getElementById('dock-magnification-toggle');
  if (magToggle) {
    magToggle.addEventListener('change', (e) => {
      applyDockSettings(_dockPosition, e.target.checked, _magnificationScale, _dockSize, _dockAutohide, true);
    });
  }

  const magSlider = document.getElementById('dock-magnification-slider');
  if (magSlider) {
    magSlider.addEventListener('input', (e) => {
      applyDockSettings(_dockPosition, _magnificationEnabled, parseFloat(e.target.value), _dockSize, _dockAutohide, false);
    });
    magSlider.addEventListener('change', (e) => {
      applyDockSettings(_dockPosition, _magnificationEnabled, parseFloat(e.target.value), _dockSize, _dockAutohide, true);
    });
  }

  const autohideToggle = document.getElementById('dock-autohide-toggle');
  if (autohideToggle) {
    autohideToggle.addEventListener('change', (e) => {
      applyDockSettings(_dockPosition, _magnificationEnabled, _magnificationScale, _dockSize, e.target.checked, true);
    });
  }

  const resetBtn = document.getElementById('dock-reset-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      applyDockSettings('bottom', true, 1.45, 'medium', false, true);
      showDockToast(t('mgmt.dock_reset_toast', 'Dock settings restored to defaults'));
    });
  }
}

export function initTopbarUserPill() {
  const topbarPill = document.getElementById('topbar-user-pill');
  if (!topbarPill || topbarPill.dataset.userPillBound === 'true') return;
  topbarPill.dataset.userPillBound = 'true';

  topbarPill.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleUserProfileFlyout(topbarPill);
  });

  topbarPill.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      toggleUserProfileFlyout(topbarPill);
    }
  });
}

export function toggleUserProfileFlyout(anchorEl) {
  let flyout = document.getElementById('user-profile-flyout');
  if (!flyout) {
    flyout = document.createElement('div');
    flyout.id = 'user-profile-flyout';
    flyout.className = 'user-profile-flyout glassmorphic-panel';
    flyout.innerHTML = `
      <div class="user-flyout-header" style="display:flex; align-items:center; gap:12px; padding:16px; border-bottom:1px solid rgba(255,255,255,0.08);">
        <div id="user-flyout-avatar" style="width:42px; height:42px; border-radius:50%; background:linear-gradient(135deg, #0284c7, #0369a1); display:flex; align-items:center; justify-content:center; font-weight:800; color:#fff; font-size:16px; border:1px solid rgba(255,255,255,0.3); box-shadow:0 4px 12px rgba(2,132,199,0.3);">
          A
        </div>
        <div style="flex:1; min-width:0;">
          <div id="user-flyout-name" style="font-weight:700; color:#fff; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Administrator</div>
          <div id="user-flyout-username" style="font-size:11.5px; color:var(--muted);">@admin</div>
          <span id="user-flyout-role" style="font-size:10px; font-weight:700; color:var(--accent-cyan, #38bdf8); background:rgba(56,189,248,0.12); padding:2px 6px; border-radius:4px; display:inline-block; margin-top:4px;">SuperAdmin 👑</span>
        </div>
      </div>
      <div class="user-flyout-actions" style="padding:8px;">
        <button class="user-flyout-btn" id="btn-flyout-lock" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:#fff; font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">🔒</span> <span>Lock Screen</span>
          <span style="margin-left:auto; font-size:10px; color:var(--muted); font-family:monospace;">Cmd+L</span>
        </button>
        <button class="user-flyout-btn" id="btn-flyout-users" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:#fff; font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">👥</span> <span>Users & Permissions</span>
        </button>
        <button class="user-flyout-btn" id="btn-flyout-security" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:#fff; font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">🛡️</span> <span>Account Security & 2FA</span>
        </button>
        <div style="height:1px; background:rgba(255,255,255,0.06); margin:6px 0;"></div>
        <button class="user-flyout-btn" id="btn-flyout-switch" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:#cbd5e1; font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">🔄</span> <span>Switch User</span>
        </button>
        <button class="user-flyout-btn" id="btn-flyout-logout" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:var(--crit, #ff6b6b); font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">🚪</span> <span>Sign Out</span>
        </button>
      </div>
    `;
    document.body.appendChild(flyout);

    // Hover effect for buttons
    flyout.querySelectorAll('.user-flyout-btn').forEach((btn) => {
      btn.addEventListener('mouseenter', () => { btn.style.background = 'rgba(255,255,255,0.08)'; });
      btn.addEventListener('mouseleave', () => { btn.style.background = 'transparent'; });
    });

    const resetFlyoutTrigger = () => {
      if (anchorEl) {
        anchorEl.setAttribute('aria-expanded', 'false');
        anchorEl.classList.remove('active');
      }
      const topbarPill = document.getElementById('topbar-user-pill');
      if (topbarPill) {
        topbarPill.setAttribute('aria-expanded', 'false');
        topbarPill.classList.remove('active');
      }
    };

    // Actions
    document.getElementById('btn-flyout-lock').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('./auth.js').then((m) => m.lockDesktop());
    });

    const openMgmtPane = (pane) => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow(pane);
      } else {
        import('./management.js').then(() => {
          if (typeof window.openManagementWindow === 'function') {
            window.openManagementWindow(pane);
          } else {
            document.getElementById('management-desktop-icon')?.click();
          }
        }).catch(() => {
          document.getElementById('management-desktop-icon')?.click();
        });
      }
      ZettEventBus.emit('window:open', { id: 'management', pane: pane });
    };

    document.getElementById('btn-flyout-users').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      openMgmtPane('mgmt-pane-users');
    });

    document.getElementById('btn-flyout-security').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      openMgmtPane('mgmt-pane-security');
    });

    document.getElementById('btn-flyout-switch').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('./auth.js').then((m) => m.switchUser());
    });

    document.getElementById('btn-flyout-logout').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('./auth.js').then((m) => m.logout());
    });

    // Click outside to close
    document.addEventListener('click', (evt) => {
      if (flyout.style.display !== 'none' && !flyout.contains(evt.target)) {
        const topbarPill = document.getElementById('topbar-user-pill');
        if ((!anchorEl || !anchorEl.contains(evt.target)) && (!topbarPill || !topbarPill.contains(evt.target))) {
          flyout.style.display = 'none';
          resetFlyoutTrigger();
        }
      }
    });

    document.addEventListener('keydown', (evt) => {
      if (evt.key === 'Escape' && flyout.style.display === 'block') {
        flyout.style.display = 'none';
        resetFlyoutTrigger();
      }
    });
  }

  // Toggle display
  if (flyout.style.display === 'block') {
    flyout.style.display = 'none';
    if (anchorEl) {
      anchorEl.setAttribute('aria-expanded', 'false');
      anchorEl.classList.remove('active');
    }
    const topbarPill = document.getElementById('topbar-user-pill');
    if (topbarPill) {
      topbarPill.setAttribute('aria-expanded', 'false');
      topbarPill.classList.remove('active');
    }
    return;
  }

  // Refresh current user info
  import('./users.js').then((m) => m.updateUserInterfaceElements());

  const rect = anchorEl ? anchorEl.getBoundingClientRect() : { top: 0, bottom: 48, left: 16, width: 30 };
  const flyoutW = 250;
  const isTopBar = rect.top < (typeof window !== 'undefined' ? window.innerHeight / 2 : 400);

  if (isTopBar) {
    const topPos = rect.bottom + 8;
    const leftPos = Math.max(12, Math.min((typeof window !== 'undefined' ? window.innerWidth : 1200) - flyoutW - 12, rect.left));
    flyout.style.position = 'fixed';
    flyout.style.top = `${topPos}px`;
    flyout.style.bottom = 'auto';
    flyout.style.left = `${leftPos}px`;
    flyout.style.animation = 'flyoutSlideDown 0.18s cubic-bezier(0.16, 1, 0.3, 1)';
  } else {
    const bottomPos = (typeof window !== 'undefined' ? window.innerHeight : 900) - rect.top + 12;
    const leftPos = Math.max(16, Math.min((typeof window !== 'undefined' ? window.innerWidth : 1200) - flyoutW - 16, rect.left + (rect.width / 2) - (flyoutW / 2)));
    flyout.style.position = 'fixed';
    flyout.style.top = 'auto';
    flyout.style.bottom = `${bottomPos}px`;
    flyout.style.left = `${leftPos}px`;
    flyout.style.animation = 'flyoutSlideUp 0.18s cubic-bezier(0.16, 1, 0.3, 1)';
  }

  flyout.style.width = `${flyoutW}px`;
  flyout.style.zIndex = '99999';
  flyout.style.display = 'block';

  if (anchorEl) {
    anchorEl.setAttribute('aria-expanded', 'true');
    anchorEl.classList.add('active');
  }
}

window.DockManager = DockManager;
window.bringToFront = bringToFront;

let _isConsoleMaximized = false;
let _consolePreMaxBounds = null;

export function toggleConsoleMaximize(e) {
  if (e && e.preventDefault) { e.preventDefault(); e.stopPropagation(); }
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

export function initSnapAssistFlyout() {
  if (typeof document === 'undefined') return;
  let flyout = document.getElementById('snap-assist-flyout');
  if (!flyout && document.body) {
    flyout = document.createElement('div');
    flyout.id = 'snap-assist-flyout';
    flyout.className = 'snap-assist-flyout';
    flyout.setAttribute('role', 'dialog');
    flyout.setAttribute('aria-label', 'Snap Layouts');
    flyout.setAttribute('aria-hidden', 'true');
    flyout.innerHTML = `
      <div class="snap-layout-title">Snap Layouts</div>
      <div class="snap-templates-grid">
        <div class="snap-card" title="Split Screen (1/2)">
          <button class="snap-slot" data-snap="left" aria-label="Snap Left Half"></button>
          <button class="snap-slot" data-snap="right" aria-label="Snap Right Half"></button>
        </div>
        <div class="snap-card snap-card-quad" title="Quarter Grid (1/4)">
          <button class="snap-slot" data-snap="top-left" aria-label="Snap Top Left"></button>
          <button class="snap-slot" data-snap="top-right" aria-label="Snap Top Right"></button>
          <button class="snap-slot" data-snap="bottom-left" aria-label="Snap Bottom Left"></button>
          <button class="snap-slot" data-snap="bottom-right" aria-label="Snap Bottom Right"></button>
        </div>
      </div>
    `;
    document.body.appendChild(flyout);
  }

  if (!flyout) return;

  let activeTargetWindow = null;
  let activeTargetWinId = null;
  let hideTimer = null;
  let showTimer = null;

  const showFlyout = (btn) => {
    clearTimeout(hideTimer);
    clearTimeout(showTimer);
    showTimer = setTimeout(() => {
      const win = btn.closest('.win-box, .modal-container, .chassis-front-panel, .mgmt-app-window, .file-manager-window, .smart-modal-window, .container-inspector-window') ||
                  btn.closest('[id$="-window"]');
      if (!win) return;
      activeTargetWindow = win;
      activeTargetWinId = win.id === 'file-manager-window' ? 'fm' :
                         (win.id === 'management-window' ? 'management' :
                         (win.id === 'console-window' ? 'console' :
                         (win.id === 'smart-modal-window' ? 'smart' : win.id)));

      const rect = btn.getBoundingClientRect();
      flyout.style.top = `${rect.bottom + 6}px`;
      flyout.style.left = `${Math.min(window.innerWidth - 230, Math.max(10, rect.left - 100))}px`;
      flyout.classList.add('visible');
      flyout.setAttribute('aria-hidden', 'false');
    }, 180);
  };

  const scheduleHide = () => {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      flyout.classList.remove('visible');
      flyout.setAttribute('aria-hidden', 'true');
    }, 220);
  };

  flyout.addEventListener('mouseenter', () => clearTimeout(hideTimer));
  flyout.addEventListener('mouseleave', scheduleHide);

  flyout.querySelectorAll('.snap-slot').forEach((slot) => {
    slot.addEventListener('click', (e) => {
      e.stopPropagation();
      const zone = slot.dataset.snap;
      if (zone && activeTargetWindow) {
        applyWindowSnap(activeTargetWindow, zone, activeTargetWinId);
      }
      flyout.classList.remove('visible');
      flyout.setAttribute('aria-hidden', 'true');
    });
  });

  const attachToMaxButtons = () => {
    const maxButtons = document.querySelectorAll('.win-btn.max-btn, #console-max, #management-max, #fb-max, #smart-modal-max, #copy-toast-max, #setup-wizard-max');
    maxButtons.forEach((btn) => {
      if (btn._snapAssistBound) return;
      btn._snapAssistBound = true;
      btn.addEventListener('mouseenter', () => showFlyout(btn));
      btn.addEventListener('mouseleave', scheduleHide);
      btn.addEventListener('focus', () => showFlyout(btn));
      btn.addEventListener('blur', scheduleHide);
    });
  };

  attachToMaxButtons();

  if (window.MutationObserver && document.body) {
    const observer = new MutationObserver(() => {
      attachToMaxButtons();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && flyout.classList.contains('visible')) {
      flyout.classList.remove('visible');
      flyout.setAttribute('aria-hidden', 'true');
    }
  });
}

export function initDockSystem() {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  initSnapAssistFlyout();
  initTopbarUserPill();
  initDockSettingsControls();
  const consoleModal = document.getElementById('console-window');
  const consoleHeader = document.querySelector('#console-window .chassis-panel-header');
  if (consoleModal) makeDraggable(consoleModal, consoleHeader, 'console');

  const consoleOverlay = document.getElementById('console-modal-overlay');
  if (consoleOverlay && DockManager.isPinned('console')) {
    DockManager.register('console', consoleOverlay, '#i-screen', t('dock.zettnas', 'ZettNAS'), true);
  } else {
    DockManager.render();
  }

  window.addEventListener('zettnas:lang-changed', () => {
    if (DockManager.windows['console']) {
      DockManager.windows['console'].title = t('dock.zettnas', 'ZettNAS');
    }
    if (DockManager.windows['management']) {
      DockManager.windows['management'].title = t('dock.management', 'Mission Control');
    }
    DockManager.render();
  });

  const consoleMin = document.getElementById('console-min');
  if (consoleMin) {
    const handleMin = (e) => {
      if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
      DockManager.minimize('console');
    };
    consoleMin.addEventListener('click', handleMin);
    consoleMin.addEventListener('touchend', handleMin);
  }

  const consoleMax = document.getElementById('console-max');
  if (consoleMax) {
    consoleMax.addEventListener('click', toggleConsoleMaximize);
    consoleMax.addEventListener('touchend', toggleConsoleMaximize);
  }

  window.addEventListener('resize', () => {
    const consoleModal = document.getElementById('console-window');
    if (consoleModal && consoleModal.dataset.maximized === 'true' && _isConsoleMaximized) {
      const availW = Math.max(320, window.innerWidth - 64);
      const availH = Math.max(200, window.innerHeight - 150);
      const scale = Math.max(1, Math.min(availW / 712, availH / 270));
      consoleModal.style.transform = `translate(-50%, -50%) scale(${scale.toFixed(3)})`;
    }
  });

  const consoleClose = document.getElementById('console-close');
  if (consoleClose) {
    const handleClose = (e) => {
      if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
      DockManager.closeWindow('console');
    };
    consoleClose.addEventListener('click', handleClose);
    consoleClose.addEventListener('touchend', handleClose);
  }

  const chassisDesktopIcon = document.getElementById('chassis-desktop-icon');
  if (chassisDesktopIcon) {
    const handleOpen = (e) => {
      if (e && e.type === 'touchend') {
        e.preventDefault();
      }
      openConsoleWindow();
    };
    chassisDesktopIcon.addEventListener('click', handleOpen);
    chassisDesktopIcon.addEventListener('touchend', handleOpen);
    chassisDesktopIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openConsoleWindow();
      }
    });
  }

  initDraggableDesktopIcons();

  const smartModal = document.querySelector('#smart-modal-overlay .smart-modal-window');
  const smartHeader = document.querySelector('#smart-modal-overlay .smart-modal-header');
  if (smartModal) makeDraggable(smartModal, smartHeader, 'smart');

  const fbModal = document.querySelector('#folder-browser-modal .smart-modal-window');
  const fbHeader = document.querySelector('#folder-browser-modal .smart-modal-header');
  if (fbModal) makeDraggable(fbModal, fbHeader, 'folder-browser');

  const copyToast = document.getElementById('copy-toast');
  const copyToastHeader = document.querySelector('#copy-toast .smart-modal-header');
  if (copyToast) makeDraggable(copyToast, copyToastHeader, 'copy-toast');

  let toastContainer = document.getElementById('global-toast-container');
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.id = 'global-toast-container';
    toastContainer.style.cssText = 'position:fixed;bottom:84px;left:50%;transform:translateX(-50%);z-index:var(--z-toast, 10000);display:flex;flex-direction:column;align-items:center;gap:8px;pointer-events:none;';
    document.body.appendChild(toastContainer);
  }

  const notifPanel = document.getElementById('notif-center-panel');
  const notifHeader = document.getElementById('notif-center-header');
  const notifResizer = document.getElementById('notif-center-resizer');
  if (notifPanel && notifHeader) {
    makeDraggable(notifPanel, notifHeader, 'notif-center');
  }
  if (notifPanel && notifResizer) {
    makeResizable(notifPanel, notifResizer, 'notif-center', { minWidth: 320, minHeight: 240 });
  }

  // Mobile / Stacked Mode Toggle & Auto-detection
  const mobileToggleBtn = document.getElementById('mobile-view-toggle-btn');
  const storedMobile = localStorage.getItem('zettnas_mobile_mode');
  const isMobileInitial = storedMobile === '1' || (storedMobile === null && window.innerWidth <= 768);
  if (isMobileInitial) {
    document.body.classList.add('mobile-mode');
    if (mobileToggleBtn) mobileToggleBtn.classList.add('active');
    // On mobile load, start with a clean mobile desktop by minimizing the heavy console window
    if (consoleOverlay) {
      DockManager.minimize('console');
    }
  }

  if (mobileToggleBtn) {
    mobileToggleBtn.addEventListener('click', () => {
      const isMobile = document.body.classList.toggle('mobile-mode');
      mobileToggleBtn.classList.toggle('active', isMobile);
      mobileToggleBtn.title = isMobile ? 'Mobile / Stacked View Active [Click for Desktop Windows]' : 'Toggle Mobile / Stacked Mode';
      localStorage.setItem('zettnas_mobile_mode', isMobile ? '1' : '0');
      if (window.refreshDesktopIconPositions) {
        window.refreshDesktopIconPositions();
      }
    });
  }

  // Keyboard navigation for OS dock
  const dock = document.getElementById('os-dock');
  if (dock) {
    dock.setAttribute('role', 'toolbar');
    dock.setAttribute('aria-label', 'System Running Applications Dock');
    dock.addEventListener('keydown', (e) => {
      const items = Array.from(dock.querySelectorAll('.dock-item'));
      const activeIdx = items.indexOf(document.activeElement);
      if (activeIdx === -1) return;

      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        const next = items[(activeIdx + 1) % items.length];
        next?.focus();
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = items[(activeIdx - 1 + items.length) % items.length];
        prev?.focus();
      }
    });
  }

  // Update dock window titles on language change
  window.addEventListener('zettnas:lang-changed', () => {
    if (DockManager.windows['console']) {
      DockManager.windows['console'].title = t('dock.zettnas', 'ZettNAS');
    }
    if (DockManager.windows['management']) {
      DockManager.windows['management'].title = t('dock.management', 'Mission Control');
    }
    DockManager.render();
  });

  // Always render the dock and update notification badge on startup
  DockManager.render();
  updateNotificationBadge();
}

export function initDraggableDesktopIcons() {
  const storageKey = 'zettnas_desktop_icon_positions_v3';
  let savedPositions = {};
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw) savedPositions = JSON.parse(raw) || {};
  } catch (e) {
    savedPositions = {};
  }

  // Initialize stored custom shortcuts into DOM
  initDesktopShortcuts();

  // Desktop icons arranged vertically with equal spacing (25px top navbar gap, 25px gap between icons, pitch = 112px)
  const defaultIconConfigs = [
    { id: 'management-desktop-icon', defaultLeft: 24, defaultTop: 77 },
    { id: 'fm-desktop-icon', defaultLeft: 24, defaultTop: 189 },
    { id: 'rb-desktop-icon', defaultLeft: 24, defaultTop: 301 },
    { id: 'chassis-desktop-icon', defaultLeft: 24, defaultTop: 413 },
  ];

  const getAllIconElements = () => {
    const defaultIds = ['management-desktop-icon', 'fm-desktop-icon', 'rb-desktop-icon', 'chassis-desktop-icon'];
    const elements = [];
    const seen = new Set();
    defaultIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        elements.push({ id, el });
        seen.add(id);
      }
    });
    document.querySelectorAll('#desktop-icons-container .chassis-hero-box, .chassis-workbench-stage .chassis-hero-box').forEach((el) => {
      if (el.id && !seen.has(el.id)) {
        elements.push({ id: el.id, el });
        seen.add(el.id);
      }
    });
    return elements;
  };

  // Desktop Icon Context Menu
  let ctxMenu = document.getElementById('desktop-ctx-menu');
  if (!ctxMenu) {
    ctxMenu = document.createElement('div');
    ctxMenu.id = 'desktop-ctx-menu';
    ctxMenu.className = 'os-context-menu desktop-context-menu';
    ctxMenu.style.display = 'none';
    document.body.appendChild(ctxMenu);
  }

  const hideMenu = (ev) => {
    if (ev && ev.target && ev.target.closest('#desktop-ctx-menu')) return;
    if (ctxMenu) ctxMenu.style.display = 'none';
    document.removeEventListener('pointerdown', hideMenu);
    document.removeEventListener('click', hideMenu);
  };

  const wireHide = () => {
    setTimeout(() => {
      document.addEventListener('pointerdown', hideMenu);
      document.addEventListener('click', hideMenu);
    }, 100);
  };

  const alignGrid = () => {
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    const GRID_X = 140;
    const GRID_Y = 112;
    const OFFSET_X = 24;
    const OFFSET_Y = 77;
    const icons = getAllIconElements();
    icons.forEach(({ id, el }) => {
      const rect = el.getBoundingClientRect();
      let snapLeft = OFFSET_X + Math.round((rect.left - OFFSET_X) / GRID_X) * GRID_X;
      let snapTop = OFFSET_Y + Math.round((rect.top - OFFSET_Y) / GRID_Y) * GRID_Y;

      if (snapLeft < OFFSET_X) snapLeft = OFFSET_X;
      if (snapTop < OFFSET_Y) snapTop = OFFSET_Y;

      el.style.left = snapLeft + 'px';
      el.style.top = snapTop + 'px';
      savedPositions[id] = { left: snapLeft, top: snapTop };
    });
    localStorage.setItem(storageKey, JSON.stringify(savedPositions));
    hideMenu();
  };
  window.alignDesktopGrid = alignGrid;

  const sortByName = () => {
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    const icons = getAllIconElements();
    let items = icons.map(({ id, el }) => {
      const nameEl = el.querySelector('.icon-text');
      const name = (nameEl ? (nameEl.innerText || nameEl.textContent) : '') || id;
      return { id, el, name: String(name || '').trim() };
    });
    // Keep Mission Control anchored as first top icon, sort others alphabetically
    items.sort((a, b) => {
      if (a.id === 'management-desktop-icon') return -1;
      if (b.id === 'management-desktop-icon') return 1;
      return a.name.localeCompare(b.name);
    });
    let currentY = 77;
    let currentX = 24;
    const GAP = 25;
    const maxH = typeof window !== 'undefined' ? window.innerHeight - 100 : 700;
    items.forEach((item) => {
      const rect = item.el.getBoundingClientRect();
      const height = rect.height > 0 ? rect.height : 87;
      if (currentY + height > maxH) {
        currentX += 140;
        currentY = 77;
      }
      item.el.style.left = `${currentX}px`;
      item.el.style.top = `${currentY}px`;
      savedPositions[item.id] = { left: currentX, top: currentY };
      currentY += height + GAP;
    });
    localStorage.setItem(storageKey, JSON.stringify(savedPositions));
    hideMenu();
  };
  window.sortDesktopIcons = sortByName;
  window.openAddDesktopShortcutModal = openAddDesktopShortcutModal;

  const wireGridAndSort = () => {
    document.getElementById('ctx-align-grid')?.addEventListener('click', alignGrid);
    document.getElementById('ctx-sort-name')?.addEventListener('click', sortByName);
  };

  document.body.addEventListener('contextmenu', (e) => {
    if (typeof e.target?.closest !== 'function') return;
    if (e.target.closest('.smart-modal-window') ||
        e.target.closest('.os-window') ||
        e.target.closest('#console-window') ||
        e.target.closest('.os-context-menu') ||
        e.target.closest('#os-dock-container') ||
        e.target.closest('.suite-navbar') ||
        e.target.closest('.slide-drawer')) {
      return;
    }

    const iconEl = e.target.closest('.chassis-hero-box');
    if (iconEl) {
      e.preventDefault();
      // Ensure the background desktop context menu is closed
      hideDesktopContextMenu();

      let iconAppId = null;
      if (iconEl.id === 'management-desktop-icon') iconAppId = 'management';
      else if (iconEl.id === 'chassis-desktop-icon') iconAppId = 'console';
      else if (iconEl.id === 'fm-desktop-icon' || iconEl.id === 'rb-desktop-icon') iconAppId = 'fm';

      const openLabel = t('dock.open_app', 'Open');
      const nameEl = iconEl.querySelector('.icon-text');
      const iconName = nameEl ? (nameEl.innerText || nameEl.textContent || '').trim() : '';
      const isCustom = iconEl.classList.contains('custom-desktop-shortcut') || !!iconEl.dataset.shortcutId;

      ctxMenu.innerHTML = `
        <div class="ctx-item" id="ctx-open-app">
          <span style="font-size:11px; margin-right:6px;">▶</span>
          <span>${escapeHtml(openLabel)}${iconName ? ` ${escapeHtml(iconName)}` : ''}</span>
        </div>
        <div style="height:1px; background:rgba(255,255,255,0.08); margin:4px 0;"></div>
        <div class="ctx-item" id="ctx-align-grid">📐 ${t('desktop.align_grid', 'Align to Grid')}</div>
        <div class="ctx-item" id="ctx-sort-name">🔤 ${t('desktop.sort_name', 'Sort by Name')}</div>
        ${isCustom ? `
          <div style="height:1px; background:rgba(255,255,255,0.08); margin:4px 0;"></div>
          <div class="ctx-item" id="ctx-remove-shortcut" style="color:#f87171;">
            <span style="font-size:11px; margin-right:6px;">🗑️</span>
            <span>Remove from Desktop</span>
          </div>
        ` : ''}
      `;

      document.getElementById('ctx-open-app')?.addEventListener('click', (ev) => {
        ev.stopPropagation();
        hideMenu();
        if (iconAppId && KNOWN_APPS[iconAppId]?.launch) {
          KNOWN_APPS[iconAppId].launch();
        } else {
          iconEl.click();
        }
      });

      if (isCustom) {
        document.getElementById('ctx-remove-shortcut')?.addEventListener('click', (ev) => {
          ev.stopPropagation();
          hideMenu();
          removeDesktopShortcut(iconEl.id);
        });
      }

      wireGridAndSort();
      wireHide();

      ctxMenu.style.display = 'block';
      const menuW = 190;
      const menuH = ctxMenu.offsetHeight || 100;
      const left = Math.max(10, Math.min(window.innerWidth - menuW - 10, e.pageX));
      const top = Math.max(10, Math.min(window.innerHeight - menuH - 20, e.pageY));
      ctxMenu.style.left = `${left}px`;
      ctxMenu.style.top = `${top}px`;
      return;
    }

    // Right-clicked on empty desktop space:
    // If the unified desktop context menu element is present in the DOM, let desktop-context-menu.js handle it!
    if (document.getElementById('desktop-context-menu')) {
      return;
    }

    // Fallback for tests/environments where #desktop-context-menu is not present:
    e.preventDefault();
    ctxMenu.innerHTML = `
      <div class="ctx-item" id="ctx-spotlight">
        <span style="font-size:11px; margin-right:6px;">⚡</span>
        <span>Command Palette</span>
        <kbd style="margin-left:auto; font-size:9px; opacity:0.6;">⌘K</kbd>
      </div>
      <div class="ctx-item" id="ctx-open-mc">
        <span style="font-size:11px; margin-right:6px;">🖥️</span>
        <span>Mission Control</span>
      </div>
      <div class="ctx-item" id="ctx-open-fm">
        <span style="font-size:11px; margin-right:6px;">📁</span>
        <span>File Explorer</span>
      </div>
      <div style="height:1px; background:rgba(255,255,255,0.08); margin:4px 0;"></div>
      <div class="ctx-item" id="ctx-align-grid">📐 ${t('desktop.align_grid', 'Align to Grid')}</div>
      <div class="ctx-item" id="ctx-sort-name">🔤 ${t('desktop.sort_name', 'Sort by Name')}</div>
      <div style="height:1px; background:rgba(255,255,255,0.08); margin:4px 0;"></div>
      <div class="ctx-item" id="ctx-refresh-telemetry">
        <span style="font-size:11px; margin-right:6px;">🔄</span>
        <span>Refresh Desktop</span>
      </div>
    `;

    document.getElementById('ctx-spotlight')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      if (typeof openSpotlight === 'function') openSpotlight();
    });
    document.getElementById('ctx-open-mc')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      document.getElementById('management-desktop-icon')?.click();
    });
    document.getElementById('ctx-open-fm')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      document.getElementById('fm-desktop-icon')?.click();
    });
    document.getElementById('ctx-refresh-telemetry')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      window.location.reload();
    });

    wireGridAndSort();
    wireHide();
    ctxMenu.style.display = 'block';
    ctxMenu.style.left = `${e.pageX}px`;
    ctxMenu.style.top = `${e.pageY}px`;
  });

  const refreshIconPositions = () => {
    const isMobile = document.body.classList.contains('mobile-mode') || window.innerWidth <= 768;
    defaultIconConfigs.forEach(({ id, defaultLeft, defaultTop }) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (isMobile) {
        el.style.removeProperty('position');
        el.style.removeProperty('left');
        el.style.removeProperty('top');
      } else {
        const saved = savedPositions[id];
        const curLeft = (saved && typeof saved.left === 'number') ? saved.left : defaultLeft;
        const curTop = (saved && typeof saved.top === 'number') ? saved.top : defaultTop;
        const maxLeft = Math.max(24, window.innerWidth - (el.offsetWidth || 136) - 10);
        const maxTop = Math.max(77, window.innerHeight - (el.offsetHeight || 136) - 70);
        const clampedLeft = Math.max(24, Math.min(maxLeft, curLeft));
        const clampedTop = Math.max(77, Math.min(maxTop, curTop));
        el.style.position = 'fixed';
        el.style.left = `${clampedLeft}px`;
        el.style.top = `${clampedTop}px`;
      }
    });

    // Also handle clamping for any custom desktop shortcuts
    getAllIconElements().forEach(({ id, el }) => {
      if (defaultIconConfigs.some((d) => d.id === id)) return;
      if (isMobile) {
        el.style.removeProperty('position');
        el.style.removeProperty('left');
        el.style.removeProperty('top');
      } else {
        const saved = savedPositions[id];
        if (saved && typeof saved.left === 'number' && typeof saved.top === 'number') {
          const maxLeft = Math.max(24, window.innerWidth - (el.offsetWidth || 136) - 10);
          const maxTop = Math.max(77, window.innerHeight - (el.offsetHeight || 136) - 70);
          const clampedLeft = Math.max(24, Math.min(maxLeft, saved.left));
          const clampedTop = Math.max(77, Math.min(maxTop, saved.top));
          el.style.position = 'fixed';
          el.style.left = `${clampedLeft}px`;
          el.style.top = `${clampedTop}px`;
        }
      }
    });
  };
  window.refreshDesktopIconPositions = refreshIconPositions;

  // Apply initial positions
  refreshIconPositions();

  const makeIconDraggable = (el, id) => {
    if (!el || el._draggableBound) return;
    el._draggableBound = true;

    let startX = 0, startY = 0, initLeft = 0, initTop = 0;
    let didDrag = false;
    let dragThresholdPassed = false;

    const onMouseDown = (e) => {
      if (e.button !== 0) return;
      if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;

      startX = e.clientX;
      startY = e.clientY;
      const rect = el.getBoundingClientRect();
      initLeft = rect.left;
      initTop = rect.top;
      didDrag = false;
      dragThresholdPassed = false;

      const onMouseMove = (mEvt) => {
        const dx = mEvt.clientX - startX;
        const dy = mEvt.clientY - startY;
        if (!dragThresholdPassed && Math.hypot(dx, dy) > 5) {
          dragThresholdPassed = true;
          didDrag = true;
          el.classList.add('dragging');
        }
        if (dragThresholdPassed) {
          mEvt.preventDefault();
          const curMaxLeft = Math.max(24, window.innerWidth - (el.offsetWidth || 136) - 10);
          const curMaxTop = Math.max(77, window.innerHeight - (el.offsetHeight || 136) - 70);
          const newLeft = Math.max(24, Math.min(curMaxLeft, initLeft + dx));
          const newTop = Math.max(77, Math.min(curMaxTop, initTop + dy));
          el.style.left = `${newLeft}px`;
          el.style.top = `${newTop}px`;
        }
      };

      const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);

        if (dragThresholdPassed) {
          el.classList.remove('dragging');
          const finalRect = el.getBoundingClientRect();
          savedPositions[id] = { left: Math.round(finalRect.left), top: Math.round(finalRect.top) };
          try {
            localStorage.setItem(storageKey, JSON.stringify(savedPositions));
          } catch (err) {
            console.error('Failed to save desktop icon position', err);
          }
          setTimeout(() => { didDrag = false; dragThresholdPassed = false; }, 60);
        }
      };

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    };

    el.addEventListener('mousedown', onMouseDown);

    // Capture phase click interceptor to stop modal opening on drag drop
    el.addEventListener('click', (e) => {
      if (didDrag || dragThresholdPassed) {
        e.stopImmediatePropagation();
        e.preventDefault();
        didDrag = false;
        dragThresholdPassed = false;
      }
    }, true);
  };
  window.makeDesktopIconDraggable = makeIconDraggable;

  // Bind draggable to all existing desktop icons
  getAllIconElements().forEach(({ el, id }) => makeIconDraggable(el, id));

  window.addEventListener('resize', () => {
    refreshIconPositions();
  });

  initDesktopLasso();
  initSpotlight();
}

export function initDesktopLasso() {
  if (typeof window === 'undefined' || document._desktopLassoInitialized) return;

  let isLassoing = false;
  let startX = 0, startY = 0;
  let lassoEl = null;

  document.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    if (
      typeof e.target?.closest === 'function' &&
      e.target.closest(
        '.smart-modal-window, .smart-modal-backdrop, .os-window, #console-window, #console-modal-overlay, ' +
        '#notif-center-panel, .notif-center-window, #management-window, .management-window, #management-modal-overlay, ' +
        '#file-manager-window, .file-manager-window, #container-inspector-window, .container-inspector-window, ' +
        '#container-inspector-overlay, #user-profile-flyout, .user-profile-flyout, .os-context-menu, ' +
        '#os-dock-container, .suite-navbar, .slide-drawer, .chassis-hero-box, .desktop-widget, ' +
        '#spotlight-palette-overlay, .window-resizer-grip, [data-window-id]'
      )
    ) {
      if (typeof e.target?.closest === 'function' && !e.target.closest('.chassis-hero-box')) {
        document.querySelectorAll('.desktop-icon-selected').forEach((el) => el.classList.remove('desktop-icon-selected'));
      }
      return;
    }

    document.querySelectorAll('.desktop-icon-selected').forEach((el) => el.classList.remove('desktop-icon-selected'));

    isLassoing = true;
    startX = e.clientX;
    startY = e.clientY;

    lassoEl = document.createElement('div');
    lassoEl.id = 'desktop-lasso-rect';
    lassoEl.style.left = `${startX}px`;
    lassoEl.style.top = `${startY}px`;
    lassoEl.style.width = '0px';
    lassoEl.style.height = '0px';
    document.body.appendChild(lassoEl);

    const onPointerMove = (mEvt) => {
      if (!isLassoing || !lassoEl) return;
      const currentX = mEvt.clientX;
      const currentY = mEvt.clientY;

      const left = Math.min(startX, currentX);
      const top = Math.min(startY, currentY);
      const width = Math.abs(currentX - startX);
      const height = Math.abs(currentY - startY);

      lassoEl.style.left = `${left}px`;
      lassoEl.style.top = `${top}px`;
      lassoEl.style.width = `${width}px`;
      lassoEl.style.height = `${height}px`;

      const lassoRect = { left, top, right: left + width, bottom: top + height };
      document.querySelectorAll('.chassis-hero-box').forEach((icon) => {
        const iRect = icon.getBoundingClientRect();
        const overlaps = !(
          lassoRect.right < iRect.left ||
          lassoRect.left > iRect.right ||
          lassoRect.bottom < iRect.top ||
          lassoRect.top > iRect.bottom
        );
        icon.classList.toggle('desktop-icon-selected', overlaps);
      });
    };

    const onPointerUp = () => {
      isLassoing = false;
      if (lassoEl) {
        lassoEl.remove();
        lassoEl = null;
      }
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', onPointerUp);
    };

    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
  });

  document._desktopLassoInitialized = true;
}

function updateNotificationBadge() {
  const badge = document.getElementById('dock-notif-badge');
  if (!badge || !state.latestStats || !state.latestStats.events) return;
  
  const events = state.latestStats.events;
  const unreadCount = events.filter((e) => !isEventChecked(e) && e.ts > clearedEventsTs).length;
  
  if (unreadCount > 0) {
    badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
    badge.style.display = 'block';
  } else {
    badge.style.display = 'none';
  }
}

window.toggleNotificationCenter = function() {
  const panel = document.getElementById('notif-center-panel');
  if (!panel) return;
  if (panel.style.display === 'none' || panel.style.display === '') {
    panel.style.display = 'flex';

    // Position window if bounds not yet saved
    const saved = loadSavedWindowBounds()['notif-center'];
    if (!saved || saved.left == null || saved.top == null) {
      const panelW = 380;
      const panelH = 500;
      const defaultLeft = Math.max(20, window.innerWidth - panelW - 24);
      const defaultTop = Math.max(56, window.innerHeight - panelH - 80);
      panel.style.position = 'fixed';
      panel.style.margin = '0';
      panel.style.bottom = 'auto';
      panel.style.right = 'auto';
      panel.style.left = `${defaultLeft}px`;
      panel.style.top = `${defaultTop}px`;
      panel.style.width = `${panelW}px`;
      panel.style.height = `${panelH}px`;
    } else {
      applySavedBounds(panel, 'notif-center');
    }

    bringToFront(panel);
    renderNotificationCenter();
    saveOpenWindowsState();
  } else {
    panel.style.display = 'none';
    saveOpenWindowsState();
  }
};

export function renderNotificationCenter() {
  const list = document.getElementById('notif-center-list');
  if (!list || !state.latestStats || !state.latestStats.events) return;
  
  let events = [...state.latestStats.events]
    .filter(e => e.ts > clearedEventsTs)
    .sort((a,b) => b.ts - a.ts);

  if (currentNotifFilter === 'error') {
    events = events.filter(e => e.level === 'error');
  } else if (currentNotifFilter === 'warning') {
    events = events.filter(e => e.level === 'warning');
  } else if (currentNotifFilter === 'info') {
    events = events.filter(e => e.level === 'info' || e.level === 'success' || !e.level);
  }
  
  if (events.length === 0) {
    const emptyMsg = currentNotifFilter === 'all'
      ? t('notif.empty', 'No recent notifications.')
      : t('notif.no_matching', 'No notifications matching filter.');
    const emptySig = `empty_${currentNotifFilter}_${clearedEventsTs}`;
    if (list._lastRenderedSignature === emptySig) return;
    list._lastRenderedSignature = emptySig;
    list.innerHTML = `<div style="padding:28px 16px; text-align:center; color:var(--muted); font-size:11px;">${escapeHtml(emptyMsg)}</div>`;
    return;
  }
  
  const visibleEvents = events.slice(0, 50);
  const sigParts = visibleEvents.map(e => `${getEventKey(e)}:${isEventChecked(e) ? '1' : '0'}`);
  const currentSignature = `${currentNotifFilter}_${clearedEventsTs}_${visibleEvents.length}_${sigParts.join(';')}`;

  // If signature has not changed, do not touch innerHTML so hover state, transitions, and active clicks aren't lost
  if (list._lastRenderedSignature === currentSignature) {
    return;
  }
  list._lastRenderedSignature = currentSignature;

  // Set up event delegation once on list to ensure single-click always works reliably
  if (!list._clickDelegated) {
    list._clickDelegated = true;
    list.addEventListener('click', (ev) => {
      const row = ev.target.closest('.notif-center-item');
      if (!row) return;
      const eventKey = row.dataset.eventKey;
      if (!eventKey) return;
      const eventObj = row._eventData || (state.latestStats?.events || []).find(e => getEventKey(e) === eventKey);
      if (!eventObj) return;

      markEventChecked(eventObj, true);
      updateNotificationBadge();
      renderNotificationCenter();
      
      if (window.openEventDetailModal) {
        window.openEventDetailModal(eventObj);
      }
    });
  }

  list.innerHTML = '';
  visibleEvents.forEach(e => {
    const isChecked = isEventChecked(e);
    const dt = new Date(e.ts * 1000);
    let color = '#cbd5e1';
    let icon = 'ℹ️';
    if (e.level === 'error') { color = 'var(--crit)'; icon = '❌'; }
    else if (e.level === 'warning') { color = 'var(--warn)'; icon = '⚠️'; }
    else if (e.level === 'success') { color = 'var(--ok2)'; icon = '✅'; }
    
    const row = document.createElement('div');
    row.className = 'notif-center-item' + (isChecked ? ' notif-event-checked' : '');
    row.dataset.eventKey = getEventKey(e);
    row._eventData = e;
    row.style.cssText = `padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; gap: 8px; align-items: flex-start; cursor:pointer; transition: background 0.15s ease; ${isChecked ? 'opacity: 0.45; filter: grayscale(0.5); background: transparent;' : 'background: rgba(255,255,255,0.05);'}`;
    row.innerHTML = `
      <span class="notif-center-icon" style="font-size: 14px; margin-top:2px; flex-shrink:0;">${icon}</span>
      <div style="display:flex; flex-direction:column; gap:2px; flex:1; min-width:0;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div class="notif-center-title" style="font-size:11px; font-weight:700; color:${color}; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; ${isChecked ? 'opacity:0.75;' : ''}">${escapeHtml(e.title)}</div>
          <span style="font-size:9.5px; color:var(--muted); opacity:0.8; margin-left:6px; flex-shrink:0;">🔍</span>
        </div>
        <div class="notif-center-msg" style="font-size:10px; color:${isChecked ? 'var(--muted)' : '#fff'}; line-height:1.4; word-break:break-word;">${escapeHtml(e.message)}</div>
        <div style="font-size:9px; color:var(--muted); margin-top:2px;">${dt.toLocaleString()}</div>
      </div>
      ${!isChecked ? `<div class="notif-unread-dot" style="width:6px; height:6px; border-radius:50%; background:var(--brand, #0ea5e9); margin-left:auto; margin-top:6px; flex-shrink:0;"></div>` : ''}
    `;
    list.appendChild(row);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const markReadBtn = document.getElementById('notif-mark-read');
  if (markReadBtn) {
    markReadBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.latestStats && state.latestStats.events && state.latestStats.events.length > 0) {
        state.latestStats.events.forEach(ev => markEventChecked(ev, false));
        saveCheckedEvents();
        lastReadEventTs = Math.max(...state.latestStats.events.map(ev => ev.ts));
        localStorage.setItem('zettnas_last_read_event_ts_v2', lastReadEventTs.toString());
        updateNotificationBadge();
        renderNotificationCenter();
      }
    });
  }

  const clearAllBtn = document.getElementById('notif-clear-all');
  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      clearedEventsTs = Math.floor(Date.now() / 1000);
      localStorage.setItem('zettnas_cleared_events_ts', clearedEventsTs.toString());
      updateNotificationBadge();
      renderNotificationCenter();
    });
  }

  document.querySelectorAll('.notif-filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      document.querySelectorAll('.notif-filter-btn').forEach(b => {
        b.classList.remove('active');
        b.style.background = 'transparent';
        b.style.borderColor = 'transparent';
        b.style.color = b.dataset.filter === 'error' ? 'var(--crit, #ff5c5c)' : (b.dataset.filter === 'warning' ? 'var(--warn, #f5a623)' : (b.dataset.filter === 'info' ? '#93c5fd' : '#cbd5e1'));
      });
      btn.classList.add('active');
      btn.style.background = 'rgba(255,255,255,0.1)';
      btn.style.borderColor = 'rgba(255,255,255,0.15)';
      btn.style.color = '#fff';
      currentNotifFilter = btn.dataset.filter || 'all';
      renderNotificationCenter();
    });
  });
  
  const notifSettingsBtn = document.getElementById('notif-settings-btn');
  if (notifSettingsBtn) {
    notifSettingsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('notif-center-panel');
      if (panel) {
        panel.style.display = 'none';
        saveOpenWindowsState();
      }
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-pane-notifications');
      }
    });
  }

  const notifCloseBtn = document.getElementById('notif-close-btn');
  if (notifCloseBtn) {
    notifCloseBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('notif-center-panel');
      if (panel) {
        panel.style.display = 'none';
        saveOpenWindowsState();
      }
    });
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
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

  ZettEventBus.on('stats:updated', () => {
    updateNotificationBadge();
    const panel = document.getElementById('notif-center-panel');
    if (panel && panel.style.display !== 'none') {
      renderNotificationCenter();
    }
    const tooltip = document.getElementById('dock-hover-tooltip');
    if (tooltip && tooltip.classList.contains('visible') && tooltip.dataset.currentWindowId === 'notif') {
      const notifBtn = document.querySelector('.dock-notif-btn');
      if (notifBtn && window.DockManager && window.DockManager.showTooltip) {
        window.DockManager.showTooltip(notifBtn, 'notif', t('dock.notifications', 'Notification Center'), '#i-bell', false);
      }
    }
  });
});

window.renderNotificationCenter = renderNotificationCenter;
window.resetCheckedEventsState = resetCheckedEventsState;
window.markEventChecked = markEventChecked;
window.isEventChecked = isEventChecked;
window.saveWindowBounds = saveWindowBounds;
window.loadSavedWindowBounds = loadSavedWindowBounds;
window.saveOpenWindowsState = saveOpenWindowsState;
window.restoreOpenWindowsState = restoreOpenWindowsState;
window.setWindowRestorationComplete = setWindowRestorationComplete;
window.applyDockSettings = applyDockSettings;
window.initDockSettingsControls = initDockSettingsControls;
window.getDockSettings = getDockSettings;
window.initParabolicDockMagnification = initParabolicDockMagnification;

if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => {
    saveOpenWindowsState();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      saveOpenWindowsState();
    }
  });
}

