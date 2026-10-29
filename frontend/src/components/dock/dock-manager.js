// DockManager: the dock's items, pinned apps and window registry.
// Part of dock.js, split out by ARC-5.

import { escapeHtml } from '../../utils.js';
import { state } from '../../state.js';
import { t } from '../../i18n.js';
import { openSpotlight } from '../spotlight.js';
import { formatTime } from '../../format.js';
import { KNOWN_APPS, showDockItemContextMenu, toggleFmWindowSwitcher } from './apps.js';
import { ADVANCED_DOCK_APPS, advancedOn } from '../../advanced.js';
import { _dockPosition } from './dock-settings.js';
import { DOCK_PINNED_KEY, clearedEventsTs, isEventChecked, showDockToast } from './notifications.js';
import { bringToFront, keyboardFocused } from './window-drag.js';
import { applySavedBounds, saveOpenWindowsState } from './window-state.js';

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

  close(id) {
    this.closeWindow(id);
  },

  closeWindow(id) {
    if (typeof this.windows[id]?.onClose === 'function') {
      this.windows[id].onClose(); // a pop-up parked in the dock closes through its own close button
      return;
    }
    if (id === 'fm') {
      if (typeof window.closeAllFileManagerWindows === 'function') {
        window.closeAllFileManagerWindows();
        return;
      }
      const fmClose = document.getElementById('fm-close');
      if (fmClose) { fmClose.click(); return; }
    } else if (id && (id.startsWith('fm-') || id.startsWith('file-manager-window'))) {
      const win = this.windows[id]?.el;
      const closeBtn = win?.querySelector('.close-btn') || win?.querySelector('#fm-close');
      if (closeBtn) { closeBtn.click(); return; }
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
    } else if (id === 'cloud-remote') {
      const crClose = document.getElementById('modal-remote-close-btn');
      if (crClose) { crClose.click(); return; }
    } else if (id === 'vm-console') {
      const cw = document.getElementById('vm-console-window');
      if (cw) {
        cw.classList.add('window-minimized');
        cw.classList.remove('open');
        cw.style.setProperty('display', 'none', 'important');
      }
    } else if (id === 'vm-iso-manager') {
      const isoWin = document.getElementById('vm-iso-manager-window') || document.getElementById('modal-iso-manager');
      if (isoWin) {
        isoWin.classList.add('window-minimized');
        isoWin.classList.remove('open');
        isoWin.style.setProperty('display', 'none', 'important');
      }
    } else if (id === 'containers' || id === 'containers-manager') {
      const cWin = document.getElementById('containers-manager-window');
      if (cWin) {
        cWin.classList.add('window-minimized');
        cWin.classList.remove('open');
        cWin.style.setProperty('display', 'none', 'important');
      }
    } else if (id === 'vm' || id === 'vm-manager') {
      const vmWin = document.getElementById('vm-manager-window');
      if (vmWin) {
        vmWin.classList.add('window-minimized');
        vmWin.classList.remove('open');
        vmWin.style.setProperty('display', 'none', 'important');
      }
    }

    if (this.windows[id] && this.windows[id].el) {
      const el = this.windows[id].el;
      el.classList.add('window-minimized');
      el.classList.remove('open');
      el.style.setProperty('display', 'none', 'important');
      const innerWin = el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .mgmt-app-window, .file-manager-window');
      if (innerWin) {
        innerWin.classList.add('window-minimized');
        innerWin.style.setProperty('display', 'none', 'important');
      }
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
      if (el.classList.contains('smart-modal-backdrop') || el.classList.contains('os-window') || el.classList.contains('file-manager-window')) {
        el.style.setProperty('display', 'flex');
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
      const winObj = this.windows[id];
      if (winObj.el) {
        winObj.el.classList.add('window-minimized');
        winObj.el.classList.remove('open');
        winObj.el.style.setProperty('display', 'none', 'important');
        const innerWin = winObj.el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .mgmt-app-window, .file-manager-window');
        if (innerWin) {
          innerWin.classList.add('window-minimized');
          innerWin.style.setProperty('display', 'none', 'important');
        }
      }
      if (this.isPinned(id)) {
        winObj.minimized = true;
        winObj.closed = true;
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

  setActiveId(id) {
    this.activeId = id;
    const dock = document.getElementById('os-dock');
    if (!dock) return;
    const isFm = id === 'fm' || (typeof id === 'string' && (id.startsWith('fm-') || id.startsWith('file-manager-window')));
    dock.querySelectorAll('.dock-item').forEach((item) => {
      const winId = item.dataset.windowId;
      if (!winId) return;
      const isActive = winId === id || (isFm && winId === 'fm');
      item.classList.toggle('active-window', isActive);
      const dot = item.querySelector('.dock-indicator-dot');
      if (dot) dot.classList.toggle('active-dot', isActive);
    });
  },

  render() {
    const dockContainer = document.getElementById('os-dock-container');
    const dock = document.getElementById('os-dock');
    if (!dock || !dockContainer) return;

    dock.classList.add('active');
    const frag = document.createDocumentFragment();

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
            <div class="dock-tooltip-actions">
              <span class="dock-tooltip-status" id="dock-tooltip-badge">Active</span>
              <button type="button" class="dock-tooltip-close-btn" id="dock-tooltip-close-btn" title="${t('dock.close_window', 'Close Window')}" aria-label="${t('dock.close_window', 'Close Window')}">✕</button>
            </div>
          </div>
          <div class="dock-tooltip-preview" id="dock-tooltip-preview-content"></div>
        `;
        document.body.appendChild(tooltip);

        tooltip.addEventListener('mouseenter', () => clearTimeout(hoverTimeout));
        tooltip.addEventListener('mouseleave', () => hideDockTooltip());
      }
      return tooltip;
    }

    const APP_DESCRIPTIONS = {
      fm: () => t('dock.desc_fm', 'File Explorer & Storage Shares'),
      containers: () => t('dock.desc_containers', 'Docker Containers & Compose Stacks'),
      vm: () => t('dock.desc_vm', 'KVM Virtual Machine Management'),
      management: () => t('dock.desc_mgmt', 'Settings for the whole server'),
      console: () => t('dock.desc_console', 'ZettNAS Appliance LCD Display'),
      smart: () => t('dock.desc_smart', 'S.M.A.R.T. Health & Diagnostics'),
      personalization: () => t('dock.desc_personalization', 'Appearance, Themes & Wallpapers'),
      'cloud-remote': () => t('dock.desc_remotes', 'Cloud Storage & Remote Mounts'),
      zettai: () => t('dock.desc_zettai', 'AI Knowledge & Visual Search'),
      'app-deploy': () => 'App Deployment & Compose Stacks',
    };

    function resolveAppWindow(id) {
      if (DockManager.windows[id]?.el) {
        return DockManager.windows[id].el;
      }
      if (id === 'management') {
        return document.getElementById('management-window') || document.querySelector('.management-window');
      }
      if (id === 'containers') {
        return document.getElementById('containers-manager-window') || document.querySelector('.containers-manager-window');
      }
      if (id === 'vm') {
        return document.getElementById('vm-manager-window') || document.querySelector('.vm-manager-window');
      }
      if (id === 'fm') {
        return document.querySelector('.file-manager-window.active-window') || document.getElementById('file-manager-window') || document.querySelector('.file-manager-window');
      }
      if (id === 'console') {
        return document.getElementById('screen-window') || document.getElementById('screen');
      }
      if (id === 'smart') {
        return document.getElementById('smart-modal-window') || document.querySelector('.smart-modal-window');
      }
      if (id === 'personalization') {
        return document.getElementById('personalization-window') || document.querySelector('.personalization-window');
      }
      if (id === 'cloud-remote') {
        return document.getElementById('cloud-remote-window');
      }
      if (id === 'app-deploy') {
        return document.getElementById('app-deploy-modal-window');
      }
      return document.getElementById(id) || document.getElementById(`${id}-window`);
    }

    function isAppWindowRunning(id, winEl) {
      if (DockManager.windows[id]) {
        return !DockManager.windows[id].closed;
      }
      if (id === 'fm') {
        const isFmAppId = (wId) => wId === 'fm' || (typeof wId === 'string' && (wId.startsWith('fm-') || wId.startsWith('file-manager-window')));
        return Object.entries(DockManager.windows).some(([k, v]) => isFmAppId(k) && !v.closed);
      }
      if (winEl) {
        const overlay = winEl.closest?.('.os-modal-overlay, .smart-modal-overlay, #console-modal-overlay, #management-modal-overlay') || winEl;
        return overlay.style.display !== 'none' || overlay.classList.contains('open');
      }
      return false;
    }

    function generatePreviewForWindow(id, isRunning = true, isMinimized = false, title = '', icon = '') {
      if (id === 'home') {
        const container = document.createElement('div');
        container.className = 'dock-preview-desktop-home';
        const bgUrl = document.documentElement.style.getPropertyValue('--wallpaper-image') || '';
        if (bgUrl && bgUrl !== 'none') {
          container.style.backgroundImage = bgUrl;
        } else {
          container.style.background = 'radial-gradient(ellipse at 50% 40%, #1e293b 0%, #0a0e17 100%)';
        }
        const winIds = Object.keys(DockManager.windows);
        const activeWins = winIds.filter((k) => !DockManager.windows[k].closed && !DockManager.windows[k].minimized);
        const countStr = `${activeWins.length} ${t('dock.active_windows_count', 'Active Windows')}`;
        container.innerHTML = `
          <div class="dock-desktop-home-card">
            <span style="font-size:18px; line-height:1;">🖥️</span>
            <strong>${escapeHtml(t('dock.desktop_workspace', 'Desktop Workspace'))}</strong>
            <span>${escapeHtml(countStr)}</span>
          </div>
          <div class="dock-preview-hover-overlay">
            <div class="dock-preview-action-chip">
              <span>↩ ${escapeHtml(t('dock.click_to_focus', 'Click to Bring to Front'))}</span>
            </div>
          </div>
        `;
        container.addEventListener('click', (e) => {
          e.stopPropagation();
          hideDockTooltip();
          const anyOpen = winIds.some((k) => !DockManager.windows[k].minimized);
          if (anyOpen) {
            winIds.forEach((k) => DockManager.minimize(k));
          } else {
            winIds.forEach((k) => DockManager.restore(k));
          }
        });
        return container;
      }

      if (id === 'spotlight') {
        const container = document.createElement('div');
        container.className = 'dock-preview-app-splash';
        container.innerHTML = `
          <div class="dock-splash-icon-ring"><span style="font-size:20px; line-height:1;">🔍</span></div>
          <div class="dock-splash-title">Command Palette</div>
          <div class="dock-splash-desc">Press Cmd+K to search apps, files, containers & settings</div>
          <div class="dock-preview-action-chip" style="margin-top:4px;">
            <span>▶ Open Spotlight</span>
          </div>
        `;
        container.addEventListener('click', (e) => {
          e.stopPropagation();
          hideDockTooltip();
          openSpotlight();
        });
        return container;
      }

      if (id === 'notif') {
        const container = document.createElement('div');
        container.className = 'dock-preview-notif-feed';
        container.addEventListener('click', (e) => {
          e.stopPropagation();
          hideDockTooltip();
          if (window.toggleNotificationCenter) window.toggleNotificationCenter();
        });

        const events = (state.latestStats && Array.isArray(state.latestStats.events))
          ? [...state.latestStats.events].filter((e) => e.ts > clearedEventsTs).sort((a, b) => b.ts - a.ts)
          : [];

        if (events.length === 0) {
          container.innerHTML = `
            <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; gap:6px; text-align:center;">
              <span style="font-size:24px;">🔔</span>
              <strong style="font-size:var(--zn-fs-xs); color:var(--zn-text-strong);">${escapeHtml(t('dock.notifications', 'Notification Center'))}</strong>
              <span style="font-size:var(--zn-fs-xs); color:var(--zn-text-muted);">No recent system notifications</span>
            </div>
          `;
          return container;
        }

        const itemsHtml = events.slice(0, 2).map((ev) => {
          let nIcon = 'ℹ️';
          let col = '#93c5fd';
          if (ev.level === 'error') { nIcon = '❌'; col = 'var(--crit, #ff5c5c)'; }
          else if (ev.level === 'warning') { nIcon = '⚠️'; col = 'var(--warn, #f5a623)'; }
          else if (ev.level === 'success') { nIcon = '✅'; col = 'var(--ok2, #25c2a0)'; }
          const timeStr = formatTime(ev.ts, undefined, '');
          return `
            <div class="dock-notif-feed-item">
              <span style="font-size:var(--zn-fs-xs); line-height:1; flex-shrink:0;">${nIcon}</span>
              <div style="min-width:0; flex:1; overflow:hidden;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <strong class="dock-notif-feed-item-title" style="color:${col};">${escapeHtml(ev.title || 'Alert')}</strong>
                  <span style="font-size:var(--zn-fs-xs); color:var(--muted);">${timeStr}</span>
                </div>
                <div class="dock-notif-feed-item-msg">${escapeHtml(ev.message || '')}</div>
              </div>
            </div>
          `;
        }).join('');

        container.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--zn-line-8); padding-bottom:3px;">
            <span style="font-size:var(--zn-fs-xs); font-weight:700; color:var(--zn-text-strong);">Recent Alerts</span>
            <span style="font-size:var(--zn-fs-xs); color:var(--lt-ink-brand, var(--accent-cyan)); font-weight:700;">${events.length} total</span>
          </div>
          <div style="display:flex; flex-direction:column; gap:4px; overflow:hidden; flex:1;">
            ${itemsHtml}
          </div>
          <div class="dock-preview-hover-overlay">
            <div class="dock-preview-action-chip">
              <span>🔔 Open Notification Center</span>
            </div>
          </div>
        `;
        return container;
      }

      if (id === 'copy') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        const status = escapeHtml(document.getElementById('copy-toast-status')?.textContent || 'Ingest');
        const pct = escapeHtml(document.getElementById('copy-toast-pct')?.textContent || '0%');
        const file = escapeHtml(document.getElementById('copy-toast-file')?.textContent || 'Preparing...');
        container.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:var(--zn-fs-xs);">
            <strong style="color:var(--zn-text-strong);">${status}</strong>
            <strong style="color:var(--ok2);">${pct}</strong>
          </div>
          <div style="background:var(--zn-glaze-12); height:6px; border-radius:3px; overflow:hidden; margin:6px 0;">
            <div style="background:var(--ok2); height:100%; width:${pct};"></div>
          </div>
          <div style="font-size:var(--zn-fs-xs); color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${file}</div>
        `;
        return container;
      }

      // Check running status
      const winEl = resolveAppWindow(id);
      const appRunning = isRunning || isAppWindowRunning(id, winEl);

      if (appRunning && winEl) {
        const winCard = winEl.querySelector('.smart-modal-window, .os-window, .management-window, .containers-manager-window, .vm-manager-window, .file-manager-window, #screen') || winEl;

        let origW = parseInt(winCard.style?.width, 10) || winCard.offsetWidth;
        let origH = parseInt(winCard.style?.height, 10) || winCard.offsetHeight;

        if (!origW || origW < 300) {
          if (id === 'management') origW = 1080;
          else if (id === 'containers') origW = 1040;
          else if (id === 'vm') origW = 960;
          else if (id === 'fm') origW = 920;
          else if (id === 'console') origW = 640;
          else if (id === 'smart') origW = 760;
          else origW = 960;
        }
        if (!origH || origH < 200) {
          if (id === 'management') origH = 680;
          else if (id === 'containers') origH = 660;
          else if (id === 'vm') origH = 600;
          else if (id === 'fm') origH = 580;
          else if (id === 'console') origH = 172;
          else if (id === 'smart') origH = 520;
          else origH = 600;
        }

        const clone = winCard.cloneNode(true);
        clone.removeAttribute('id');
        clone.querySelectorAll('[id]').forEach((el) => el.removeAttribute('id'));
        clone.querySelectorAll('[name]').forEach((el) => el.removeAttribute('name'));
        clone.classList.remove('window-minimized', 'window-dragging', 'hidden');
        clone.classList.add('dock-cloned-preview-win');
        clone.style.setProperty('display', 'flex', 'important');
        clone.style.setProperty('visibility', 'visible', 'important');
        clone.style.setProperty('opacity', '1', 'important');
        clone.style.setProperty('transform', 'none', 'important');
        clone.style.setProperty('position', 'relative', 'important');
        clone.style.setProperty('top', '0px', 'important');
        clone.style.setProperty('left', '0px', 'important');
        clone.style.setProperty('right', 'auto', 'important');
        clone.style.setProperty('bottom', 'auto', 'important');
        clone.style.setProperty('inset', 'auto', 'important');
        clone.style.setProperty('width', `${origW}px`, 'important');
        clone.style.setProperty('height', `${origH}px`, 'important');
        clone.style.setProperty('max-width', 'none', 'important');
        clone.style.setProperty('max-height', 'none', 'important');
        clone.style.setProperty('min-width', '0', 'important');
        clone.style.setProperty('min-height', '0', 'important');
        clone.style.setProperty('pointer-events', 'none', 'important');
        clone.style.setProperty('user-select', 'none', 'important');
        clone.style.setProperty('margin', '0', 'important');
        clone.style.setProperty('transition', 'none', 'important');
        clone.style.setProperty('animation', 'none', 'important');

        // Copy canvas graphics (e.g. system charts, LCD framebuffers)
        const srcCanvases = winCard.querySelectorAll('canvas');
        const cloneCanvases = clone.querySelectorAll('canvas');
        srcCanvases.forEach((srcC, idx) => {
          const dstC = cloneCanvases[idx];
          if (dstC && srcC.width && srcC.height) {
            dstC.width = srcC.width;
            dstC.height = srcC.height;
            const ctx = dstC.getContext('2d');
            if (ctx) {
              try { ctx.drawImage(srcC, 0, 0); } catch {}
            }
          }
        });

        const PREVIEW_MAX_W = 260;
        const PREVIEW_MAX_H = 156;
        const scale = Math.min(PREVIEW_MAX_W / origW, PREVIEW_MAX_H / origH);
        const scaledW = origW * scale;
        const scaledH = origH * scale;
        const leftOffset = Math.max(0, Math.round((PREVIEW_MAX_W - scaledW) / 2));
        const topOffset = Math.max(0, Math.round((PREVIEW_MAX_H - scaledH) / 2));

        const scaler = document.createElement('div');
        scaler.className = 'dock-preview-live-scaler';
        scaler.style.width = `${origW}px`;
        scaler.style.height = `${origH}px`;
        scaler.style.transform = `scale(${scale})`;
        scaler.style.transformOrigin = 'top left';
        scaler.style.left = `${leftOffset}px`;
        scaler.style.top = `${topOffset}px`;

        scaler.appendChild(clone);

        const container = document.createElement('div');
        container.className = 'dock-preview-live-container';
        container.appendChild(scaler);

        const overlay = document.createElement('div');
        overlay.className = 'dock-preview-hover-overlay';
        const chip = document.createElement('div');
        chip.className = 'dock-preview-action-chip';
        chip.innerHTML = isMinimized
          ? `<span>↩ ${escapeHtml(t('dock.click_to_restore', 'Click to Restore'))}</span>`
          : `<span>🔍 ${escapeHtml(t('dock.click_to_focus', 'Click to Bring to Front'))}</span>`;
        overlay.appendChild(chip);
        container.appendChild(overlay);

        container.addEventListener('click', (e) => {
          e.stopPropagation();
          hideDockTooltip();
          if (id === 'fm') {
            DockManager.restore('fm');
            if (winCard) bringToFront(winCard);
          } else {
            DockManager.restore(id);
            if (winCard) bringToFront(winCard);
          }
        });
        return container;
      }

      // App is closed / pinned: show splash card
      if (KNOWN_APPS[id] || title) {
        const container = document.createElement('div');
        container.className = 'dock-preview-app-splash';
        const appObj = KNOWN_APPS[id];
        const appTitle = appObj?.getTitle ? appObj.getTitle() : (title || id);
        const appIcon = appObj?.icon || icon || '#i-chip';
        const appDesc = (APP_DESCRIPTIONS[id] ? APP_DESCRIPTIONS[id]() : '') || 'Application';

        container.innerHTML = `
          <div class="dock-splash-icon-ring">
            <svg><use href="${appIcon}"/></svg>
          </div>
          <div class="dock-splash-title">${escapeHtml(appTitle)}</div>
          <div class="dock-splash-desc">${escapeHtml(appDesc)}</div>
          <div class="dock-preview-action-chip" style="margin-top:4px;">
            <span>▶ ${escapeHtml(t('dock.click_to_open', 'Click to open application'))}</span>
          </div>
        `;

        container.addEventListener('click', (e) => {
          e.stopPropagation();
          hideDockTooltip();
          if (appObj?.launch) {
            appObj.launch();
          }
        });
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
      const closeBtn = document.getElementById('dock-tooltip-close-btn');
      const previewEl = document.getElementById('dock-tooltip-preview-content');

      if (textEl) textEl.textContent = title;
      if (iconEl) iconEl.innerHTML = `<use href="${icon}"/>`;

      if (badgeEl) {
        if (id === 'home') {
          badgeEl.textContent = t('ui.desktop', 'Desktop');
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
        } else if (id === 'spotlight') {
          badgeEl.textContent = 'PALETTE';
          badgeEl.className = 'dock-tooltip-status pinned';
        } else if (isClosed) {
          badgeEl.textContent = 'PINNED';
          badgeEl.className = 'dock-tooltip-status pinned';
        } else {
          badgeEl.textContent = isMinimized ? 'MINIMIZED' : 'ACTIVE';
          badgeEl.className = 'dock-tooltip-status ' + (isMinimized ? 'minimized' : 'active');
        }
      }

      if (closeBtn) {
        if (isClosed || id === 'home' || id === 'notif' || id === 'spotlight') {
          closeBtn.style.display = 'none';
        } else {
          closeBtn.style.display = 'flex';
          closeBtn.onclick = (e) => {
            e.stopPropagation();
            hideDockTooltip();
            DockManager.closeWindow(id);
          };
        }
      }

      if (previewEl) {
        const previewContent = generatePreviewForWindow(id, !isClosed, isMinimized, title, icon);
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
      tooltip.dataset.dockPos = _dockPosition;

      if (!isAlreadyVisibleForThisItem) {
        const dockEl = document.getElementById('os-dock');
        const dockRect = dockEl ? dockEl.getBoundingClientRect() : null;
        const rect = dockItem.getBoundingClientRect();
        const tooltipW = tooltip.offsetWidth || 280;
        const tooltipH = tooltip.offsetHeight || 190;

        if (_dockPosition === 'left') {
          const leftPos = dockRect ? Math.round(dockRect.right + 12) : Math.round(rect.right + 12);
          let topPos = Math.round(rect.top + (rect.height / 2) - (tooltipH / 2));
          topPos = Math.max(56, Math.min(window.innerHeight - tooltipH - 16, topPos));
          tooltip.style.left = `${leftPos}px`;
          tooltip.style.top = `${topPos}px`;
          tooltip.style.bottom = 'auto';

          const arrowY = Math.max(16, Math.min(tooltipH - 16, Math.round((rect.top + (rect.height / 2)) - topPos)));
          tooltip.style.setProperty('--arrow-y', `${arrowY}px`);
        } else if (_dockPosition === 'top') {
          const centerX = (dockEl && dockRect && typeof dockItem.offsetLeft === 'number')
            ? (dockRect.left + dockItem.offsetLeft - (dockEl.scrollLeft || 0) + (dockItem.offsetWidth / 2))
            : (rect.left + (rect.width / 2));
          let leftPos = Math.round(centerX - (tooltipW / 2));
          leftPos = Math.max(16, Math.min(window.innerWidth - tooltipW - 16, leftPos));
          const topPos = dockRect ? Math.round(dockRect.bottom + 12) : Math.round(rect.bottom + 12);
          tooltip.style.left = `${leftPos}px`;
          tooltip.style.top = `${topPos}px`;
          tooltip.style.bottom = 'auto';

          const arrowX = Math.max(16, Math.min(tooltipW - 16, Math.round(centerX - leftPos)));
          tooltip.style.setProperty('--arrow-x', `${arrowX}px`);
        } else {
          // Bottom (Default)
          const centerX = (dockEl && dockRect && typeof dockItem.offsetLeft === 'number')
            ? (dockRect.left + dockItem.offsetLeft - (dockEl.scrollLeft || 0) + (dockItem.offsetWidth / 2))
            : (rect.left + (rect.width / 2));

          let leftPos = Math.round(centerX - (tooltipW / 2));
          leftPos = Math.max(16, Math.min(window.innerWidth - tooltipW - 16, leftPos));
          const bottomPos = dockRect
            ? Math.max(10, Math.round(window.innerHeight - dockRect.top + 14))
            : Math.max(10, Math.round(window.innerHeight - rect.top + 10));

          tooltip.style.left = `${leftPos}px`;
          tooltip.style.bottom = `${bottomPos}px`;
          tooltip.style.top = 'auto';

          const arrowX = Math.max(16, Math.min(tooltipW - 16, Math.round(centerX - leftPos)));
          tooltip.style.setProperty('--arrow-x', `${arrowX}px`);
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
    dashItem.addEventListener('focus', () => keyboardFocused(dashItem) && showDockTooltip(dashItem, 'home', t('dock.home', 'Dashboard Home'), '#i-globe', false));
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
    frag.appendChild(dashItem);

    // Spotlight Quick Launcher
    const spotItem = document.createElement('button');
    spotItem.type = 'button';
    spotItem.className = 'dock-item dock-item-spotlight';
    spotItem.setAttribute('aria-label', 'Spotlight Command Palette (Cmd+K)');
    spotItem.innerHTML = `<span style="font-size:15px; line-height:1;">🔍</span>`;
    spotItem.addEventListener('mouseenter', () => showDockTooltip(spotItem, 'spotlight', 'Command Palette (Cmd+K)', '', false));
    spotItem.addEventListener('focus', () => keyboardFocused(spotItem) && showDockTooltip(spotItem, 'spotlight', 'Command Palette (Cmd+K)', '', false));
    spotItem.addEventListener('mouseleave', hideDockTooltip);
    spotItem.addEventListener('blur', hideDockTooltip);
    spotItem.addEventListener('click', () => {
      hideDockTooltip();
      openSpotlight();
    });
    frag.appendChild(spotItem);

    // Dynamic apps (pinned + running)
    const pinned = this.getPinnedApps();
    const isFmAppId = (wId) => wId === 'fm' || (typeof wId === 'string' && (wId.startsWith('fm-') || wId.startsWith('file-manager-window')));

    // Collect all open FM windows
    const fmWindows = Object.entries(this.windows)
      .filter(([k, v]) => isFmAppId(k) && !v.closed)
      .map(([k, v]) => ({ id: k, ...v }));
    const fmRunning = fmWindows.length > 0;

    const runningIds = Object.keys(this.windows).filter((id) => !this.windows[id].closed);
    // a pinned advanced app stays out of the dock while Advanced is off, unless it is open (UX-23)
    const displayedIds = pinned.filter((id) => advancedOn() || !ADVANCED_DOCK_APPS.includes(id) || runningIds.includes(id));

    // If any FM window is running and 'fm' isn't already in displayedIds, add 'fm'
    if (fmRunning && !displayedIds.includes('fm')) {
      displayedIds.push('fm');
    }

    runningIds.forEach((id) => {
      // Group all FM windows under 'fm'
      if (isFmAppId(id)) return;
      if (!displayedIds.includes(id)) {
        displayedIds.push(id);
      }
    });

    displayedIds.forEach((id) => {
      if (id === 'fm') {
        const isRunning = fmRunning;
        const isPinned = this.isPinned('fm');
        const win = this.windows['fm'] || (KNOWN_APPS.fm ? {
          icon: KNOWN_APPS.fm.icon,
          title: KNOWN_APPS.fm.getTitle(),
          minimized: !isRunning,
          closed: !isRunning,
        } : null);
        if (!win) return;

        const item = document.createElement('button');
        item.type = 'button';
        let cls = 'dock-item';
        if (!isRunning) cls += ' pinned-closed';
        else if (fmWindows.every((w) => w.minimized)) cls += ' minimized';
        const isFmActive = isFmAppId(this.activeId) && isRunning && fmWindows.some((w) => !w.minimized);
        if (isFmActive) cls += ' active-window';
        item.className = cls;
        item.setAttribute('aria-label', win.title);
        item.dataset.windowId = 'fm';

        let innerContent = `<svg><use href="${win.icon}"/></svg>`;
        if (fmWindows.length > 1) {
          innerContent += `<span class="dock-count-badge">${fmWindows.length}</span>`;
        }
        item.innerHTML = innerContent;

        item.addEventListener('mousedown', (e) => e.stopPropagation());
        item.addEventListener('mouseenter', () => showDockTooltip(item, 'fm', win.title, win.icon, !isRunning || fmWindows.every((w) => w.minimized), !isRunning));
        item.addEventListener('focus', () => keyboardFocused(item) && showDockTooltip(item, 'fm', win.title, win.icon, !isRunning || fmWindows.every((w) => w.minimized), !isRunning));
        item.addEventListener('mouseleave', hideDockTooltip);
        item.addEventListener('blur', hideDockTooltip);

        item.addEventListener('click', () => {
          hideDockTooltip();
          if (!isRunning) {
            if (KNOWN_APPS.fm?.launch) {
              KNOWN_APPS.fm.launch();
            }
          } else if (fmWindows.length > 1) {
            toggleFmWindowSwitcher(item, fmWindows);
          } else if (fmWindows.length === 1) {
            this.toggle(fmWindows[0].id);
          }
        });

        item.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          e.stopPropagation();
          hideDockTooltip();
          showDockItemContextMenu(e.pageX, e.pageY, 'fm', win.title, isPinned, isRunning, fmWindows);
        });

        frag.appendChild(item);
        return;
      }

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
      item.addEventListener('focus', () => keyboardFocused(item) && showDockTooltip(item, id, win.title, win.icon, win.minimized, !isRunning));
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

      frag.appendChild(item);
    });

    // Notification Center Button
    const notifItem = document.createElement('button');
    notifItem.type = 'button';
    notifItem.className = 'dock-item dock-notif-btn';
    notifItem.setAttribute('aria-label', t('dock.notifications', 'Notification Center'));
    notifItem.innerHTML = `<svg><use href="#i-bell"/></svg><span class="dock-badge" id="dock-notif-badge" aria-hidden="true" style="display:none; position:absolute; top:-2px; right:-2px; background:var(--crit); color:var(--zn-text-strong); font-size:var(--zn-fs-xs); font-weight:800; padding:1px 4px; border-radius:8px; border:1px solid var(--lt-r-000000ff, #000); box-shadow:0 1px 2px rgba(0,0,0,0.5); pointer-events:none;">0</span>`;
    notifItem.addEventListener('mouseenter', () => showDockTooltip(notifItem, 'notif', t('dock.notifications', 'Notification Center'), '#i-bell', false));
    notifItem.addEventListener('focus', () => keyboardFocused(notifItem) && showDockTooltip(notifItem, 'notif', t('dock.notifications', 'Notification Center'), '#i-bell', false));
    notifItem.addEventListener('mouseleave', hideDockTooltip);
    notifItem.addEventListener('blur', hideDockTooltip);
    notifItem.addEventListener('click', () => {
      hideDockTooltip();
      if (window.toggleNotificationCenter) window.toggleNotificationCenter();
    });
    frag.appendChild(notifItem);

    // Atomically swap dock items without geometry collapse
    dock.replaceChildren(frag);

    const dockButtons = Array.from(dock.querySelectorAll('.dock-item'));
    dockButtons.forEach((btn, idx) => {
      btn.setAttribute('tabindex', idx === 0 ? '0' : '-1');
    });

    if (dock.classList.contains('dock-magnify-enabled')) {
      dock.querySelectorAll('.dock-item').forEach((item) => {
        item.style.setProperty('--dock-item-scale', '1');
      });
    }

  }
};
