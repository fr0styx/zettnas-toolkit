/**
 * ZettNAS Toolkit - Desktop Right-Click Context Menu Engine
 * Provides consumer-grade macOS / Windows 11 style glassmorphic desktop context menu
 * with quick shortcuts to wallpaper styling, themes, widgets, dock, fullscreen, and lock.
 */
import { ZettEventBus } from '../event-bus.js';
import { showToast } from '../toast.js';
import { openAddDesktopShortcutModal } from './desktop-shortcuts.js';

let _contextMenuInitialized = false;

export function initDesktopContextMenu() {
  if (_contextMenuInitialized) return;
  _contextMenuInitialized = true;

  const menu = document.getElementById('desktop-context-menu');
  if (!menu) return;

  // Global right-click handler
  document.addEventListener('contextmenu', (e) => {
    if (typeof e.target?.closest !== 'function') return;
    // 1. Allow native context menu in text inputs, textareas, contenteditable, monaco, code editors, and links
    if (e.target.closest('input, textarea, select, [contenteditable="true"], .monaco-editor, #ci-logs-terminal, .terminal, .code-editor, a[href]')) {
      return;
    }

    // 2. Allow windows, modals, dock, navbar, and DESKTOP ICONS to handle their own context menus
    if (e.target.closest(
      '.os-window, .smart-modal-window, .notif-center-window, #os-dock, #os-dock-container, ' +
      '.suite-navbar, .smart-modal-backdrop, .chassis-hero-box, #desktop-ctx-menu, .dock-context-menu'
    )) {
      return;
    }

    // 3. Prevent native menu on empty desktop space and display unified desktop context menu
    e.preventDefault();
    showDesktopContextMenu(e.clientX, e.clientY);
  });

  // Global dismiss handlers
  document.addEventListener('pointerdown', (e) => {
    if (!menu.contains(e.target)) {
      hideDesktopContextMenu();
    }
  });

  window.addEventListener('blur', hideDesktopContextMenu);
  window.addEventListener('resize', hideDesktopContextMenu);

  document.addEventListener('keydown', (e) => {
    if (menu.style.display !== 'none') {
      if (e.key === 'Escape') {
        hideDesktopContextMenu();
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        navigateMenuItems(e.key === 'ArrowDown' ? 1 : -1);
      } else if (e.key === 'Enter') {
        const focused = menu.querySelector('.context-menu-item:focus');
        if (focused) {
          e.preventDefault();
          executeContextAction(focused.getAttribute('data-action'));
        }
      }
    }
  });

  // Bind menu item click actions
  const items = menu.querySelectorAll('.context-menu-item');
  items.forEach((item) => {
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      const action = item.getAttribute('data-action');
      executeContextAction(action);
      hideDesktopContextMenu();
    });
  });
}

export function showDesktopContextMenu(x, y) {
  const menu = document.getElementById('desktop-context-menu');
  if (!menu) return;

  // Ensure any other context menus are hidden
  const iconCtx = document.getElementById('desktop-ctx-menu');
  if (iconCtx) iconCtx.style.display = 'none';
  const dockCtx = document.getElementById('dock-item-ctx-menu');
  if (dockCtx) dockCtx.style.display = 'none';

  menu.style.display = 'flex';
  menu.setAttribute('aria-hidden', 'false');

  // Compute bounding box and prevent overflowing window edges
  const rect = menu.getBoundingClientRect();
  const menuW = rect.width || 230;
  const menuH = rect.height || 260;

  const maxX = window.innerWidth - menuW - 12;
  const maxY = window.innerHeight - menuH - 12;

  const posX = Math.max(12, Math.min(x, maxX));
  const posY = Math.max(12, Math.min(y, maxY));

  menu.style.left = `${posX}px`;
  menu.style.top = `${posY}px`;

  // Focus first item for a11y keyboard support
  const firstItem = menu.querySelector('.context-menu-item');
  if (firstItem) firstItem.focus();
}

export function hideDesktopContextMenu() {
  const menu = document.getElementById('desktop-context-menu');
  if (menu && menu.style.display !== 'none') {
    menu.style.display = 'none';
    menu.setAttribute('aria-hidden', 'true');
  }
}

function navigateMenuItems(direction) {
  const menu = document.getElementById('desktop-context-menu');
  if (!menu) return;

  const items = Array.from(menu.querySelectorAll('.context-menu-item'));
  if (!items.length) return;

  const currentIdx = items.indexOf(document.activeElement);
  let nextIdx = currentIdx + direction;

  if (nextIdx < 0) nextIdx = items.length - 1;
  if (nextIdx >= items.length) nextIdx = 0;

  items[nextIdx].focus();
}

export function executeContextAction(action) {
  hideDesktopContextMenu();
  if (!action) return;

  switch (action) {
    case 'add-shortcut':
      if (typeof window.openAddDesktopShortcutModal === 'function') {
        window.openAddDesktopShortcutModal();
      } else {
        openAddDesktopShortcutModal();
      }
      break;

    case 'align-grid':
      if (typeof window.alignDesktopGrid === 'function') {
        window.alignDesktopGrid();
      }
      break;

    case 'sort-name':
      if (typeof window.sortDesktopIcons === 'function') {
        window.sortDesktopIcons();
      }
      break;

    case 'refresh-desktop':
      window.location.reload();
      break;

    case 'spotlight':
      if (typeof window.openSpotlight === 'function') {
        window.openSpotlight();
      }
      break;

    case 'wallpaper':
      if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-wallpaper');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' });
      }
      break;

    case 'theme':
      if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-theme');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' });
      }
      break;

    case 'glass':
      if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-glass');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-glass' });
      }
      break;

    case 'dock':
      if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-dock');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-dock' });
      }
      break;

    case 'screensaver':
      if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-screensaver');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-screensaver' });
      }
      break;

    case 'fullscreen':
      try {
        if (!document.fullscreenElement) {
          if (document.documentElement.requestFullscreen) {
            document.documentElement.requestFullscreen().catch(() => {});
          }
        } else {
          if (document.exitFullscreen) {
            document.exitFullscreen().catch(() => {});
          }
        }
      } catch (err) {
        showToast('Fullscreen toggle not supported in this view', 'info');
      }
      break;

    case 'activity':
      if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-activity', 'mgmt-pane-metrics');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' });
      }
      break;

    case 'lock':
      if (typeof window.lockDesktopScreen === 'function') {
        window.lockDesktopScreen();
      } else {
        document.documentElement.classList.add('is-desktop-locked');
      }
      break;

    default:
      console.warn(`[CONTEXT MENU] Unhandled action: ${action}`);
  }
}
