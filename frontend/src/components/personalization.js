/**
 * ZettNAS Toolkit - Dedicated Desktop & Personalization Application
 * Manages Wallpaper gallery, Desktop Themes, Glassmorphism, Dock & Taskbar,
 * Screensavers, Desktop Widgets, and Console Display Customization.
 */

import { ensureManagementDom } from '../management-dom.js';
import { api } from '../api.js';
import { state } from '../state.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast } from '../toast.js';
import { t } from '../i18n.js';
import { makeDraggable, bringToFront, trapFocus } from './dock.js';
import { applyDesktopTheme, applyLcdTheme } from './dashboard.js';

let personalizationWindow = null;
let _activeTab = 'wallpaper';
let _unbindTrap = null;

export function initPersonalization() {
  if (window._personalizationInitialized) return;
  window._personalizationInitialized = true;

  window.openPersonalizationWindow = openPersonalizationWindow;
  window.closePersonalizationWindow = closePersonalizationWindow;

  // Inject Window DOM if not already present
  if (!document.getElementById('personalization-window')) {
    const html = `
      <div id="personalization-window" class="os-window personalization-window" style="display: none; width: 940px; height: 620px; min-width: 600px; min-height: 400px;">
        <div class="os-window-header">
          <div class="os-window-title">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>
            <span data-i18n="dock.personalization">${t('dock.personalization', 'Desktop & Personalization')}</span>
          </div>
          <div class="os-window-controls">
            <button class="os-control-btn os-btn-minimize" id="personalization-btn-min" title="${t('window.minimize', 'Minimize')}">─</button>
            <button class="os-control-btn os-btn-maximize" id="personalization-btn-max" title="${t('ui.maximize', 'Maximize')}">□</button>
            <button class="os-control-btn os-btn-close" id="personalization-btn-close" title="${t('diagnostics.close_btn', 'Close')}">✕</button>
          </div>
        </div>

        <div class="personalization-container" style="display: flex; flex: 1; height: calc(100% - 38px); overflow: hidden;">
          <!-- Left Navigation Sidebar -->
          <div class="personalization-sidebar" style="width: 220px; background: var(--zn-shade-20); border-right: 1px solid var(--zn-line-8); display: flex; flex-direction: column; padding: 12px 8px; gap: 4px; overflow-y: auto;">
            <button class="personalization-nav-item active" data-tab="wallpaper">
              <span class="p-nav-icon">🖼️</span>
              <span class="p-nav-text" data-i18n="mgmt.subtab_wallpaper">${t('mgmt.subtab_wallpaper', 'Wallpaper')}</span>
            </button>
            <button class="personalization-nav-item" data-tab="theme">
              <span class="p-nav-icon">🎨</span>
              <span class="p-nav-text" data-i18n="mgmt.subtab_theme">${t('mgmt.subtab_theme', 'Color Theme')}</span>
            </button>
            <button class="personalization-nav-item" data-tab="glass">
              <span class="p-nav-icon">✨</span>
              <span class="p-nav-text" data-i18n="mgmt.subtab_glass">${t('mgmt.subtab_glass', 'Glass & Layout')}</span>
            </button>
            <button class="personalization-nav-item" data-tab="dock">
              <span class="p-nav-icon">⚓</span>
              <span class="p-nav-text" data-i18n="mgmt.subtab_dock">${t('mgmt.subtab_dock', 'Dock & Taskbar')}</span>
            </button>
            <button class="personalization-nav-item" data-tab="screensaver">
              <span class="p-nav-icon">🌙</span>
              <span class="p-nav-text" data-i18n="mgmt.subtab_screensaver">${t('mgmt.subtab_screensaver', 'Screensaver')}</span>
            </button>
            <button class="personalization-nav-item" data-tab="widgets">
              <span class="p-nav-icon">📊</span>
              <span class="p-nav-text" data-i18n="mgmt.subtab_widgets">${t('mgmt.subtab_widgets', 'Desktop Widgets')}</span>
            </button>
            <button class="personalization-nav-item" data-tab="console">
              <span class="p-nav-icon">📟</span>
              <span class="p-nav-text" data-i18n="settings.tab_layout_title">${t('settings.tab_layout_title', 'Console Layout & Theme')}</span>
            </button>
          </div>

          <!-- Main Content Area -->
          <div class="personalization-content-area" id="personalization-content-body" style="flex: 1; padding: 20px; overflow-y: auto; background: var(--lt-b-0000001a, rgba(0,0,0,0.1));">
            <!-- Dynamic tab content container -->
            <div id="p-pane-wallpaper" class="personalization-pane" style="display: block;"></div>
            <div id="p-pane-theme" class="personalization-pane" style="display: none;"></div>
            <div id="p-pane-glass" class="personalization-pane" style="display: none;"></div>
            <div id="p-pane-dock" class="personalization-pane" style="display: none;"></div>
            <div id="p-pane-screensaver" class="personalization-pane" style="display: none;"></div>
            <div id="p-pane-widgets" class="personalization-pane" style="display: none;"></div>
            <div id="p-pane-console" class="personalization-pane" style="display: none;"></div>
          </div>
        </div>
      </div>
    `;
    const temp = document.createElement('div');
    temp.innerHTML = html.trim();
    document.body.appendChild(temp.firstElementChild);
  }

  personalizationWindow = document.getElementById('personalization-window');

  // Hook controls
  const minBtn = document.getElementById('personalization-btn-min');
  const maxBtn = document.getElementById('personalization-btn-max');
  const closeBtn = document.getElementById('personalization-btn-close');

  if (minBtn) {
    minBtn.addEventListener('click', () => {
      if (window.DockManager) window.DockManager.minimize('personalization');
    });
  }

  if (maxBtn) {
    maxBtn.addEventListener('click', () => {
      personalizationWindow.classList.toggle('window-maximized');
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', closePersonalizationWindow);
  }

  // Hook sidebar navigation tabs
  const navBtns = document.querySelectorAll('.personalization-nav-item');
  navBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      switchPersonalizationTab(tab);
    });
  });

  makeDraggable(personalizationWindow, personalizationWindow.querySelector('.os-window-header'));
  personalizationWindow.addEventListener('mousedown', () => bringToFront(personalizationWindow));

  // Populate pane content from Mission Control's panes (inserted when first needed, FE-04)
  ensureManagementDom().then(syncPersonalizationPanes);
}

function syncPersonalizationPanes() {
  const mountSource = (sourceId, targetId) => {
    const src = document.getElementById(sourceId);
    const dst = document.getElementById(targetId);
    if (src && dst && !dst.hasChildNodes()) {
      // Clone children into the personalization pane
      const clone = src.cloneNode(true);
      clone.style.display = 'block';
      clone.id = `${targetId}-content`;
      // Safeguard 2: Prefix IDs on cloned children so there are NEVER duplicate DOM IDs in the document
      clone.querySelectorAll('[id]').forEach((el) => {
        el.id = `p-clone-${el.id}`;
      });
      dst.appendChild(clone);
    }
  };

  mountSource('mgmt-pane-wallpaper', 'p-pane-wallpaper');
  mountSource('mgmt-pane-theme', 'p-pane-theme');
  mountSource('mgmt-pane-glass', 'p-pane-glass');
  mountSource('mgmt-pane-dock', 'p-pane-dock');
  mountSource('mgmt-pane-screensaver', 'p-pane-screensaver');
  mountSource('mgmt-pane-widgets', 'p-pane-widgets');
  mountSource('tab-layout', 'p-pane-console');
}

export function switchPersonalizationTab(tabName) {
  _activeTab = tabName || 'wallpaper';
  const navBtns = document.querySelectorAll('.personalization-nav-item');
  navBtns.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === _activeTab);
  });

  const panes = document.querySelectorAll('.personalization-pane');
  panes.forEach((p) => {
    p.style.display = p.id === `p-pane-${_activeTab}` ? 'block' : 'none';
  });
}

export function openPersonalizationWindow(tab = null) {
  if (!personalizationWindow) {
    initPersonalization();
  }
  if (!personalizationWindow) return;

  if (tab) {
    // Map alias tabs
    const tabMap = {
      'wallpaper': 'wallpaper',
      'theme': 'theme',
      'glass': 'glass',
      'dock': 'dock',
      'screensaver': 'screensaver',
      'widgets': 'widgets',
      'console': 'console',
      'layout': 'console'
    };
    switchPersonalizationTab(tabMap[tab] || 'wallpaper');
  }

  if (window.DockManager) {
    if (!window.DockManager.windows['personalization']) {
      window.DockManager.register(
        'personalization',
        personalizationWindow,
        '#i-screen',
        t('dock.personalization', 'Desktop & Personalization')
      );
    }
    window.DockManager.restore('personalization');
  }

  personalizationWindow.classList.remove('window-minimized');
  personalizationWindow.style.removeProperty('display');
  personalizationWindow.style.display = 'flex';
  bringToFront(personalizationWindow);
  ZettEventBus.emit('window:open', { id: 'personalization-window', tab: _activeTab });
}

export function closePersonalizationWindow() {
  if (!personalizationWindow) return;
  personalizationWindow.style.display = 'none';
  if (window.DockManager) {
    window.DockManager.close('personalization');
  }
}
