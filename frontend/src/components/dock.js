import { escapeHtml } from '../utils.js';
import { state } from '../state.js';
import { t } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
/**
 * ZettNAS Toolkit Dock & Window Manager
 * Handles floating modal registration, minimize/restore, dragging, and z-index depth stacking.
 */

let activeWindowZIndex = 1000;
let lastReadEventTs = parseFloat(localStorage.getItem('zettnas_last_read_event_ts_v2') || '0');
let clearedEventsTs = parseFloat(localStorage.getItem('zettnas_cleared_events_ts') || '0');
let currentNotifFilter = 'all';

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

export function showDockToast(msg) {
  let container = document.getElementById('global-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'global-toast-container';
    container.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:var(--z-toast, 10000);display:flex;flex-direction:column;gap:8px;';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = 'dock-pin-toast';
  toast.style.cssText = 'background:rgba(15,23,42,0.92); border:1px solid rgba(255,255,255,0.18); backdrop-filter:blur(12px); color:#fff; font-size:11px; font-weight:600; padding:6px 14px; border-radius:20px; box-shadow:0 4px 16px rgba(0,0,0,0.5); pointer-events:none; transition:opacity 0.25s ease, transform 0.25s ease; transform:translateY(10px); opacity:0;';
  toast.textContent = msg;
  container.appendChild(toast);
  requestAnimationFrame(() => {
    toast.style.transform = 'translateY(0)';
    toast.style.opacity = '1';
  });
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-6px)';
    setTimeout(() => toast.remove(), 300);
  }, 2000);
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
    localStorage.setItem(WIN_BOUNDS_KEY, JSON.stringify(all));
  } catch (e) {
    console.warn('Failed to save window bounds', e);
  }
}

export function applySavedBounds(dragEl, winId) {
  if (!dragEl || document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
  const id = winId || dragEl.id || dragEl.dataset.windowId;
  if (!id) return;
  const all = loadSavedWindowBounds();
  const saved = all[id]
    || (id === 'file-manager-window' ? all['fm'] : (id === 'fm' ? all['file-manager-window'] : null))
    || (id === 'management-window' ? all['management'] : (id === 'management' ? all['management-window'] : null))
    || (id === 'console-window' ? all['console'] : (id === 'console' ? all['console-window'] : null))
    || (id === 'smart-modal-window' ? all['smart'] : (id === 'smart' ? all['smart-modal-window'] : null));
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

  if (saved.width && !dragEl.classList.contains('smart-modal-window') && !dragEl.classList.contains('chassis-front-panel')) {
    dragEl.style.width = `${Math.min(window.innerWidth - 20, Math.max(320, saved.width))}px`;
  }
  if (saved.height && !dragEl.classList.contains('smart-modal-window') && !dragEl.classList.contains('chassis-front-panel')) {
    dragEl.style.height = `${Math.min(window.innerHeight - 80, Math.max(240, saved.height))}px`;
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
    }
  }
}

export function saveOpenWindowsState() {
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
            const activeTabBtn = document.querySelector('.mgmt-inner-tab.active');
            if (activeTabBtn && activeTabBtn.dataset.tabTarget) {
              stateObj.windows[id].activePane = activeTabBtn.dataset.tabTarget;
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
  if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
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
          bringToFront(activeWin.el);
        }
      }, 120);
    }
  } catch (e) {
    console.warn('Failed to restore open windows', e);
  }
}

export function bringToFront(windowEl) {
  if (!windowEl) return;
  activeWindowZIndex++;
  if (activeWindowZIndex >= 4900) {
    activeWindowZIndex = 1000;
  }
  const backdrop = windowEl.closest('.smart-modal-backdrop');
  if (backdrop) {
    backdrop.style.zIndex = activeWindowZIndex.toString();
  }
  windowEl.style.zIndex = activeWindowZIndex.toString();

  if (window.DockManager) {
    let foundId = null;
    Object.keys(window.DockManager.windows).forEach((id) => {
      const wEl = window.DockManager.windows[id].el;
      if (wEl === backdrop || wEl === windowEl || (wEl && wEl.contains && wEl.contains(windowEl))) {
        foundId = id;
      }
    });
    if (foundId) {
      window.DockManager.activeId = foundId;
      window.DockManager.render();
      saveOpenWindowsState();
    }
  }
}

function getOrCreateSnapGhost() {
  let ghost = document.getElementById('window-snap-ghost');
  if (!ghost) {
    ghost = document.createElement('div');
    ghost.id = 'window-snap-ghost';
    ghost.className = 'window-snap-ghost';
    document.body.appendChild(ghost);
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

  handleEl.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || e.target.closest('button') || e.target.closest('input') || e.target.closest('.modal-ctrl-btn')) return;
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
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

    const drag = (eMove) => {
      eMove.preventDefault();
      const dx = eMove.clientX - initialMouseX;
      const dy = eMove.clientY - initialMouseY;
      dragEl.style.left = (startX + dx) + 'px';
      dragEl.style.top = (startY + dy) + 'px';

      const snapMargin = 25;
      if (eMove.clientX <= snapMargin) {
        activeSnap = 'left';
        ghost.style.display = 'block';
        ghost.style.left = '8px';
        ghost.style.top = '48px';
        ghost.style.width = 'calc(50vw - 12px)';
        ghost.style.height = 'calc(100vh - 48px - 76px)';
      } else if (eMove.clientX >= window.innerWidth - snapMargin) {
        activeSnap = 'right';
        ghost.style.display = 'block';
        ghost.style.left = 'calc(50vw + 4px)';
        ghost.style.top = '48px';
        ghost.style.width = 'calc(50vw - 12px)';
        ghost.style.height = 'calc(100vh - 48px - 76px)';
      } else if (eMove.clientY <= snapMargin) {
        activeSnap = 'maximize';
        ghost.style.display = 'block';
        ghost.style.left = '8px';
        ghost.style.top = '48px';
        ghost.style.width = 'calc(100vw - 16px)';
        ghost.style.height = 'calc(100vh - 48px - 76px)';
      } else {
        activeSnap = null;
        ghost.style.display = 'none';
      }
    };

    const stopDrag = () => {
      ghost.style.display = 'none';
      document.removeEventListener('mousemove', drag);
      document.removeEventListener('mouseup', stopDrag);

      if (activeSnap) {
        if (!dragEl._preSnapWidth) {
          dragEl._preSnapWidth = (rect.width || dragEl.offsetWidth) + 'px';
          dragEl._preSnapHeight = (rect.height || dragEl.offsetHeight) + 'px';
        }
        dragEl.style.transition = 'all 0.22s cubic-bezier(0.16, 1, 0.3, 1)';
        dragEl.dataset.snapped = activeSnap;
        if (activeSnap === 'left') {
          dragEl.style.left = '8px';
          dragEl.style.top = '48px';
          dragEl.style.width = 'calc(50vw - 12px)';
          dragEl.style.height = 'calc(100vh - 48px - 76px)';
        } else if (activeSnap === 'right') {
          dragEl.style.left = 'calc(50vw + 4px)';
          dragEl.style.top = '48px';
          dragEl.style.width = 'calc(50vw - 12px)';
          dragEl.style.height = 'calc(100vh - 48px - 76px)';
        } else if (activeSnap === 'maximize') {
          dragEl.style.left = '8px';
          dragEl.style.top = '48px';
          dragEl.style.width = 'calc(100vw - 16px)';
          dragEl.style.height = 'calc(100vh - 48px - 76px)';
        }
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

    document.addEventListener('mousemove', drag);
    document.addEventListener('mouseup', stopDrag);
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
    launch: () => {
      const fmWin = document.getElementById('file-manager-window');
      if (fmWin) {
        if (window.DockManager && !window.DockManager.windows['fm']) {
          window.DockManager.register('fm', fmWin, '#i-storage', t('dock.file_manager', 'File Explorer'), false);
        }
        if (window.DockManager) window.DockManager.restore('fm');
        ZettEventBus.emit('window:open', { id: 'file-manager-window' });
      } else {
        document.getElementById('fm-desktop-icon')?.click();
      }
    }
  },
  management: {
    id: 'management',
    icon: '#i-management',
    getTitle: () => t('dock.management', 'Management'),
    launch: (pane = null) => {
      if (window.openManagementWindow) {
        window.openManagementWindow(pane);
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
    launch: () => {
      if (window.openSmartModal) {
        window.openSmartModal();
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
      showDockToast(toastMsg);
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
      showDockToast(toastMsg);
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
      el.style.removeProperty('display');
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
    saveOpenWindowsState();
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
      if (el.classList.contains('os-window') || el.classList.contains('file-manager-window')) {
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
            <div style="font-size:10px; font-weight:700; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">System Management</div>
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
        previewEl.innerHTML = '';
        const previewContent = generatePreviewForWindow(id);
        if (previewContent) {
          previewEl.appendChild(previewContent);
          previewEl.style.display = 'flex';
        } else {
          previewEl.style.display = 'none';
        }
      }

      tooltip.dataset.currentWindowId = id;
      const rect = dockItem.getBoundingClientRect();
      const tooltipW = tooltip.offsetWidth || 210;

      let leftPos = rect.left + (rect.width / 2) - (tooltipW / 2);
      leftPos = Math.max(24, Math.min(window.innerWidth - tooltipW - 10, leftPos));
      const bottomPos = Math.max(10, window.innerHeight - rect.top + 10);

      tooltip.style.left = `${leftPos}px`;
      tooltip.style.bottom = `${bottomPos}px`;
      tooltip.style.top = 'auto';
      tooltip.classList.add('visible');
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

  }
};

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

export function initDockSystem() {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
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
      DockManager.windows['management'].title = t('dock.management', 'Management');
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
    toastContainer.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:var(--z-toast, 10000);display:flex;flex-direction:column;gap:8px;';
    document.body.appendChild(toastContainer);
  }
  setTimeout(() => {
    const tC = document.getElementById('global-toast-container');
    if (tC) makeDraggable(tC, tC);
  }, 100);

  const notifPanel = document.getElementById('notif-center-panel');
  const notifHeader = document.getElementById('notif-center-header');
  if (notifPanel && notifHeader) {
    makeDraggable(notifPanel, notifHeader, 'notif-center');
  }

  document.querySelectorAll('.smart-modal-window, #console-window, #notif-center-panel').forEach((win) => {
    win.addEventListener('mousedown', (e) => {
      bringToFront(win);
      e._handledAsWindowClick = true;
    });
  });

  document.addEventListener('mousedown', (e) => {
    if (e._handledAsWindowClick) return;
    const windowEl = e.target.closest('.smart-modal-window, #console-window, #notif-center-panel');
    if (windowEl) {
      bringToFront(windowEl);
    }
  });

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
      DockManager.windows['management'].title = t('dock.management', 'Management');
    }
    DockManager.render();
  });

  // Always render the dock and update notification badge on startup
  DockManager.render();
  updateNotificationBadge();
}

export function initDraggableDesktopIcons() {
  const storageKey = 'zettnas_desktop_icon_positions_v2';
  let savedPositions = {};
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw) savedPositions = JSON.parse(raw) || {};
  } catch (e) {
    savedPositions = {};
  }

  // Desktop icons arranged vertically with compact spacing (gap ~20px, pitch = 112px)
  const iconConfigs = [
    { id: 'management-desktop-icon', defaultLeft: 24, defaultTop: 56 },
    { id: 'chassis-desktop-icon', defaultLeft: 24, defaultTop: 168 },
    { id: 'fm-desktop-icon', defaultLeft: 24, defaultTop: 280 },
    { id: 'rb-desktop-icon', defaultLeft: 24, defaultTop: 392 },
  ];

  // Desktop Context Menu
  let ctxMenu = document.getElementById('desktop-ctx-menu');
  if (!ctxMenu) {
    ctxMenu = document.createElement('div');
    ctxMenu.id = 'desktop-ctx-menu';
    ctxMenu.className = 'os-context-menu desktop-context-menu';
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

  const wireGridAndSort = () => {
    document.getElementById('ctx-align-grid')?.addEventListener('click', () => {
      if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
      const GRID_X = 140;
      const GRID_Y = 112;
      const OFFSET_X = 24;
      const OFFSET_Y = 56;
      iconConfigs.forEach(({ id }) => {
        const el = document.getElementById(id);
        if (el) {
          const rect = el.getBoundingClientRect();
          let snapLeft = OFFSET_X + Math.round((rect.left - OFFSET_X) / GRID_X) * GRID_X;
          let snapTop = OFFSET_Y + Math.round((rect.top - OFFSET_Y) / GRID_Y) * GRID_Y;

          if (snapLeft < OFFSET_X) snapLeft = OFFSET_X;
          if (snapTop < OFFSET_Y) snapTop = OFFSET_Y;

          el.style.left = snapLeft + 'px';
          el.style.top = snapTop + 'px';
          savedPositions[id] = { left: snapLeft, top: snapTop };
        }
      });
      localStorage.setItem(storageKey, JSON.stringify(savedPositions));
      hideMenu();
    });

    document.getElementById('ctx-sort-name')?.addEventListener('click', () => {
      if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
      let items = [];
      iconConfigs.forEach((conf) => {
        const el = document.getElementById(conf.id);
        if (el) {
          const nameEl = el.querySelector('.icon-text');
          items.push({ id: conf.id, el, name: nameEl ? nameEl.innerText : conf.id });
        }
      });
      items.sort((a, b) => a.name.localeCompare(b.name));
      let currentY = 56;
      const GAP = 20;
      items.forEach((item) => {
        item.el.style.left = '24px';
        item.el.style.top = currentY + 'px';
        savedPositions[item.id] = { left: 24, top: currentY };
        const rect = item.el.getBoundingClientRect();
        const height = rect.height > 0 ? rect.height : 92;
        currentY += height + GAP;
      });
      localStorage.setItem(storageKey, JSON.stringify(savedPositions));
      hideMenu();
    });
  };

  document.body.addEventListener('contextmenu', (e) => {
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
    let iconAppId = null;
    if (iconEl) {
      if (iconEl.id === 'management-desktop-icon') iconAppId = 'management';
      else if (iconEl.id === 'chassis-desktop-icon') iconAppId = 'console';
      else if (iconEl.id === 'fm-desktop-icon' || iconEl.id === 'rb-desktop-icon') iconAppId = 'fm';
    }

    e.preventDefault();

    if (iconAppId) {
      const openLabel = t('dock.open_app', 'Open');

      ctxMenu.innerHTML = `
        <div class="ctx-item" id="ctx-open-app">
          <span style="font-size:11px; margin-right:6px;">▶</span>
          <span>${escapeHtml(openLabel)}</span>
        </div>
        <div style="height:1px; background:rgba(255,255,255,0.08); margin:4px 0;"></div>
        <div class="ctx-item" id="ctx-align-grid">📐 ${t('desktop.align_grid', 'Align to Grid')}</div>
        <div class="ctx-item" id="ctx-sort-name">🔤 ${t('desktop.sort_name', 'Sort by Name')}</div>
      `;

      document.getElementById('ctx-open-app')?.addEventListener('click', (ev) => {
        ev.stopPropagation();
        hideMenu();
        if (KNOWN_APPS[iconAppId]?.launch) {
          KNOWN_APPS[iconAppId].launch();
        } else {
          iconEl.click();
        }
      });
    } else {
      ctxMenu.innerHTML = `
        <div class="ctx-item" id="ctx-align-grid">📐 ${t('desktop.align_grid', 'Align to Grid')}</div>
        <div class="ctx-item" id="ctx-sort-name">🔤 ${t('desktop.sort_name', 'Sort by Name')}</div>
      `;
    }

    wireGridAndSort();
    wireHide();

    ctxMenu.style.display = 'block';
    const menuW = 180;
    const menuH = ctxMenu.offsetHeight || 80;
    const left = Math.max(10, Math.min(window.innerWidth - menuW - 10, e.pageX));
    const top = Math.max(10, Math.min(window.innerHeight - menuH - 20, e.pageY));
    ctxMenu.style.left = `${left}px`;
    ctxMenu.style.top = `${top}px`;
  });

  const refreshIconPositions = () => {
    const isMobile = document.body.classList.contains('mobile-mode') || window.innerWidth <= 768;
    iconConfigs.forEach(({ id, defaultLeft, defaultTop }) => {
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
        const maxTop = Math.max(56, window.innerHeight - (el.offsetHeight || 136) - 70);
        const clampedLeft = Math.max(24, Math.min(maxLeft, curLeft));
        const clampedTop = Math.max(56, Math.min(maxTop, curTop));
        el.style.position = 'fixed';
        el.style.left = `${clampedLeft}px`;
        el.style.top = `${clampedTop}px`;
      }
    });
  };
  window.refreshDesktopIconPositions = refreshIconPositions;

  // Apply initial positions
  refreshIconPositions();

  iconConfigs.forEach(({ id }) => {
    const el = document.getElementById(id);
    if (!el) return;

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
          const curMaxTop = Math.max(56, window.innerHeight - (el.offsetHeight || 136) - 70);
          const newLeft = Math.max(24, Math.min(curMaxLeft, initLeft + dx));
          const newTop = Math.max(56, Math.min(curMaxTop, initTop + dy));
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
  });

  window.addEventListener('resize', () => {
    refreshIconPositions();
  });
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
      const panelW = 360;
      const panelH = 440;
      const defaultLeft = Math.max(20, window.innerWidth - panelW - 24);
      const defaultTop = Math.max(56, window.innerHeight - panelH - 80);
      panel.style.position = 'fixed';
      panel.style.margin = '0';
      panel.style.bottom = 'auto';
      panel.style.right = 'auto';
      panel.style.left = `${defaultLeft}px`;
      panel.style.top = `${defaultTop}px`;
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
