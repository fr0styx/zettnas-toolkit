/**
 * ZettNAS Toolkit Dock & Window Manager
 * Handles floating modal registration, minimize/restore, dragging, and z-index depth stacking.
 *
 * This module starts the dock (initDockSystem) and registers the window globals; the pieces
 * live in ./dock/ (ARC-5) and are re-exported here under the same names.
 */

import { onManagementDom } from '../management-dom.js';
import { state } from '../state.js';
import { t } from '../i18n.js';
import { _isConsoleMaximized, openConsoleWindow, toggleConsoleMaximize } from './dock/console-window.js';
import { initDraggableDesktopIcons } from './dock/desktop-icons.js';
import { DockManager } from './dock/dock-manager.js';
import { applyDockSettings, getDockSettings, initDockSettingsControls, initParabolicDockMagnification } from './dock/dock-settings.js';
import { isEventChecked, markEventChecked, renderNotificationCenter, resetCheckedEventsState, updateNotificationBadge } from './dock/notifications.js';
import { getCurrentWorkspace, initWindowKeyboardShortcuts, initWorkspaceSwitcher, switchWorkspace } from './dock/shortcuts.js';
import { initSnapAssistFlyout } from './dock/snap-assist.js';
import { getActiveWindowElement, restoreWindowSnap } from './dock/snap.js';
import { initTopbarUserPill } from './dock/user-flyout.js';
import { bringToFront, makeDraggable, makeResizable } from './dock/window-drag.js';
import { clearMobileInlineBounds, loadSavedWindowBounds, restoreOpenWindowsState, saveOpenWindowsState, saveWindowBounds, setWindowRestorationComplete } from './dock/window-state.js';
import { COMPACT_MAX } from '../device.js';
export { KNOWN_APPS, showDockItemContextMenu, toggleFmWindowSwitcher } from './dock/apps.js';
export { openConsoleWindow, toggleConsoleMaximize } from './dock/console-window.js';
export { initDraggableDesktopIcons } from './dock/desktop-icons.js';
export { DockManager } from './dock/dock-manager.js';
export { applyDockSettings, getDockSettings, initDockSettingsControls, initParabolicDockMagnification } from './dock/dock-settings.js';
export { initDesktopLasso } from './dock/lasso.js';
export { CHECKED_EVENTS_KEY, DOCK_PINNED_KEY, getEventKey, isEventChecked, markEventChecked, renderNotificationCenter, resetCheckedEventsState, saveCheckedEvents, showDockToast } from './dock/notifications.js';
export { WORKSPACES, getCurrentWorkspace, initWindowKeyboardShortcuts, initWorkspaceSwitcher, switchWorkspace } from './dock/shortcuts.js';
export { initSnapAssistFlyout } from './dock/snap-assist.js';
export { DOCK_MARGIN, NAVBAR_OFFSET, applyWindowSnap, evaluateSnapZone, getActiveWindowElement, getSnapGeometry, restoreWindowSnap } from './dock/snap.js';
export { initTopbarUserPill, toggleUserProfileFlyout } from './dock/user-flyout.js';
export { DESKTOP_WINDOW_SELECTOR, activeWindowZIndex, bringToFront, handleWindowActivation, makeDraggable, makeResizable } from './dock/window-drag.js';
export { OPEN_WINDOWS_KEY, applySavedBounds, clearMobileInlineBounds, loadSavedWindowBounds, restoreOpenWindowsState, restoreWindowsAfterWiden, saveOpenWindowsState, saveWindowBounds, setWindowRestorationComplete } from './dock/window-state.js';

try {
  localStorage.removeItem('zettnas_last_read_event_ts');
} catch {}

window.DockManager = DockManager;
window.bringToFront = bringToFront;

export function initDockSystem() {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  initSnapAssistFlyout();
  initTopbarUserPill();
  onManagementDom(initDockSettingsControls); // dock settings are in Mission Control (FE-04)
  initWindowKeyboardShortcuts();
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

  const crModal = document.getElementById('cloud-remote-window');
  const crHeader = document.getElementById('cloud-remote-window-header');
  if (crModal && crHeader) {
    makeDraggable(crModal, crHeader, 'cloud-remote');
  }

  // Mobile / Stacked Mode Toggle & Auto-detection
  const mobileToggleBtn = document.getElementById('mobile-view-toggle-btn');
  const storedMobile = localStorage.getItem('zettnas_mobile_mode');
  const isMobileInitial = storedMobile === '1' || (storedMobile === null && window.innerWidth <= COMPACT_MAX);
  const purgeAllMobileWindows = () => {
    document.querySelectorAll('.os-window, .file-manager-window, #management-window, .management-window, .smart-modal-window, #console-window, .chassis-front-panel, #container-inspector-window, #stack-inspector-window, #app-deploy-modal-window, #notif-center-panel').forEach(clearMobileInlineBounds);
  };
  if (isMobileInitial) {
    document.body.classList.add('mobile-mode');
    if (mobileToggleBtn) mobileToggleBtn.classList.add('active');
    purgeAllMobileWindows();
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
      if (isMobile) {
        purgeAllMobileWindows();
      } else {
        // Back to desktop windows: the resize handlers put each window where it was saved.
        window.dispatchEvent(new Event('resize'));
      }
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
        if (next) {
          items[activeIdx].setAttribute('tabindex', '-1');
          next.setAttribute('tabindex', '0');
          next.focus();
        }
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = items[(activeIdx - 1 + items.length) % items.length];
        if (prev) {
          items[activeIdx].setAttribute('tabindex', '-1');
          prev.setAttribute('tabindex', '0');
          prev.focus();
        }
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
window.getActiveWindowElement = getActiveWindowElement;
window.restoreWindowSnap = restoreWindowSnap;
window.getCurrentWorkspace = getCurrentWorkspace;
window.switchWorkspace = switchWorkspace;
window.initWorkspaceSwitcher = initWorkspaceSwitcher;

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
