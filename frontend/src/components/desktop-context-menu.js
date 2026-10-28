/**
 * ZettNAS Toolkit - Desktop Right-Click Context Menu Engine
 * Provides consumer-grade macOS / Windows 11 style glassmorphic desktop context menu
 * with quick shortcuts to wallpaper styling, themes, widgets, dock, fullscreen, and lock.
 */
import { ZettEventBus } from '../event-bus.js';
import { showToast } from '../toast.js';
import { openAddDesktopShortcutModal } from './desktop-shortcuts.js';
import { getWidgetKeyFromElement, getWidgetDisplayName } from './widget-names.js';

// the rest of the widgets code loads after the first paint (PERF-9)
const removeWidget = (key) => import('./widgets.js').then((m) => m.removeWidget(key));
const openWidgetSettings = () => import('./widgets.js').then((m) => m.openWidgetSettings());
import { t } from '../i18n.js';

let _contextMenuInitialized = false;
let _activeContextWidgetKey = null;
let _activeContextWidgetEl = null;

export function _resetDesktopContextMenuForTesting() {
  _contextMenuInitialized = false;
  _activeContextWidgetKey = null;
  _activeContextWidgetEl = null;
}

export function initDesktopContextMenu() {
  if (_contextMenuInitialized) return;
  _contextMenuInitialized = true;

  // Global right-click handler
  document.addEventListener('contextmenu', (e) => {
    if (typeof e.target?.closest !== 'function') return;
    // 1. Allow native context menu in text inputs, textareas, contenteditable, monaco, code editors, and links
    if (e.target.closest('input, textarea, select, [contenteditable="true"], .monaco-editor, #ci-logs-terminal, .terminal, .code-editor, a[href]')) {
      return;
    }

    // 2. Allow widgets to show dedicated widget context menu
    const widgetEl = e.target.closest('.desktop-widget');
    if (widgetEl) {
      e.preventDefault();
      const widgetKey = getWidgetKeyFromElement(widgetEl);
      showWidgetContextMenu(e.clientX, e.clientY, widgetEl, widgetKey);
      return;
    }

    // 3. Allow windows, modals, dock, navbar, and DESKTOP ICONS to handle their own context menus
    if (e.target.closest(
      '.os-window, .smart-modal-window, .notif-center-window, #os-dock, #os-dock-container, ' +
      '.suite-navbar, .smart-modal-backdrop, .chassis-hero-box, #desktop-ctx-menu, .dock-context-menu'
    )) {
      return;
    }

    // 4. Prevent native menu on empty desktop space and display unified desktop context menu
    const menu = document.getElementById('desktop-context-menu');
    if (menu) {
      e.preventDefault();
      showDesktopContextMenu(e.clientX, e.clientY);
    }
  });

  // Global dismiss handlers
  document.addEventListener('pointerdown', (e) => {
    const menu = document.getElementById('desktop-context-menu');
    const widgetMenu = document.getElementById('widget-context-menu');
    const inMenu = menu && menu.contains(e.target);
    const inWidgetMenu = widgetMenu && widgetMenu.contains(e.target);
    if (!inMenu && !inWidgetMenu) {
      hideDesktopContextMenu();
      hideWidgetContextMenu();
    }
  });

  window.addEventListener('blur', () => {
    hideDesktopContextMenu();
    hideWidgetContextMenu();
  });

  window.addEventListener('resize', () => {
    hideDesktopContextMenu();
    hideWidgetContextMenu();
  });

  document.addEventListener('keydown', (e) => {
    const menu = document.getElementById('desktop-context-menu');
    const widgetMenu = document.getElementById('widget-context-menu');
    const isMenuOpen = menu && menu.style.display !== 'none';
    const isWidgetMenuOpen = widgetMenu && widgetMenu.style.display !== 'none';

    if (isMenuOpen || isWidgetMenuOpen) {
      const activeMenu = isWidgetMenuOpen ? widgetMenu : menu;
      if (e.key === 'Escape') {
        hideDesktopContextMenu();
        hideWidgetContextMenu();
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        navigateMenuItems(activeMenu, e.key === 'ArrowDown' ? 1 : -1);
      } else if (e.key === 'Enter') {
        const focused = activeMenu.querySelector('.context-menu-item:focus');
        if (focused) {
          e.preventDefault();
          executeContextAction(focused.getAttribute('data-action'));
        }
      }
    }
  });

  // Document-level event delegation for context menu item clicks
  document.addEventListener('click', (e) => {
    const item = e.target.closest?.('.context-menu-item');
    if (!item) return;
    const parentMenu = item.closest?.('#desktop-context-menu, #widget-context-menu');
    if (!parentMenu) return;

    e.stopPropagation();
    const action = item.getAttribute('data-action');
    executeContextAction(action);
  });
}

export function showDesktopContextMenu(x, y) {
  const menu = document.getElementById('desktop-context-menu');
  if (!menu) return;

  // Ensure any other context menus are hidden
  hideWidgetContextMenu();
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

export function showWidgetContextMenu(x, y, widgetEl, widgetKey) {
  const widgetMenu = document.getElementById('widget-context-menu');
  if (!widgetMenu) return;

  hideDesktopContextMenu();
  const iconCtx = document.getElementById('desktop-ctx-menu');
  if (iconCtx) iconCtx.style.display = 'none';
  const dockCtx = document.getElementById('dock-item-ctx-menu');
  if (dockCtx) dockCtx.style.display = 'none';

  _activeContextWidgetKey = widgetKey || getWidgetKeyFromElement(widgetEl);
  _activeContextWidgetEl = widgetEl || null;

  const removeLabel = document.getElementById('ctx-remove-widget-label');
  if (removeLabel) {
    const displayName = getWidgetDisplayName(_activeContextWidgetKey);
    const baseRemove = t('ctx.remove_widget', 'Remove Widget');
    removeLabel.textContent = `${baseRemove} (${displayName})`;
  }

  widgetMenu.style.display = 'flex';
  widgetMenu.setAttribute('aria-hidden', 'false');

  const rect = widgetMenu.getBoundingClientRect();
  const menuW = rect.width || 230;
  const menuH = rect.height || 260;

  const maxX = window.innerWidth - menuW - 12;
  const maxY = window.innerHeight - menuH - 12;

  const posX = Math.max(12, Math.min(x, maxX));
  const posY = Math.max(12, Math.min(y, maxY));

  widgetMenu.style.left = `${posX}px`;
  widgetMenu.style.top = `${posY}px`;

  const firstItem = widgetMenu.querySelector('.context-menu-item');
  if (firstItem) firstItem.focus();
}

export function hideWidgetContextMenu() {
  const widgetMenu = document.getElementById('widget-context-menu');
  if (widgetMenu && widgetMenu.style.display !== 'none') {
    widgetMenu.style.display = 'none';
    widgetMenu.setAttribute('aria-hidden', 'true');
  }
}

function navigateMenuItems(menu, direction) {
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
  const widgetKeyToActOn = _activeContextWidgetKey;
  hideDesktopContextMenu();
  hideWidgetContextMenu();
  if (!action) return;

  switch (action) {
    case 'remove-widget':
      if (widgetKeyToActOn) {
        if (typeof window.removeWidget === 'function') {
          window.removeWidget(widgetKeyToActOn);
        } else {
          removeWidget(widgetKeyToActOn);
        }
      }
      break;

    case 'add-widget':
    case 'widgets':
    case 'widget-settings':
      if (typeof window.openWidgetSettings === 'function') {
        window.openWidgetSettings();
      } else {
        openWidgetSettings();
      }
      break;

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
      if (typeof window.openPersonalizationWindow === 'function') {
        window.openPersonalizationWindow('wallpaper');
      } else if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-wallpaper');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' });
      }
      break;

    case 'theme':
      if (typeof window.openPersonalizationWindow === 'function') {
        window.openPersonalizationWindow('theme');
      } else if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-theme');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' });
      }
      break;

    case 'glass':
      if (typeof window.openPersonalizationWindow === 'function') {
        window.openPersonalizationWindow('glass');
      } else if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-glass');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-glass' });
      }
      break;

    case 'dock':
      if (typeof window.openPersonalizationWindow === 'function') {
        window.openPersonalizationWindow('dock');
      } else if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-dock');
      } else {
        ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-dock' });
      }
      break;

    case 'screensaver':
      if (typeof window.openPersonalizationWindow === 'function') {
        window.openPersonalizationWindow('screensaver');
      } else if (typeof window.openManagementSection === 'function') {
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
        showToast(t('toast.fullscreen_toggle_not_supported_in_this', 'Fullscreen toggle not supported in this view'), 'info');
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

window.showDesktopContextMenu = showDesktopContextMenu;
window.hideDesktopContextMenu = hideDesktopContextMenu;
window.showWidgetContextMenu = showWidgetContextMenu;
window.hideWidgetContextMenu = hideWidgetContextMenu;
window.executeContextAction = executeContextAction;
