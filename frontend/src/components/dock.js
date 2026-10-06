import { escapeHtml } from '../utils.js';
import { state } from '../state.js';
import { t } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
/**
 * ZettNAS Toolkit Dock & Window Manager
 * Handles floating modal registration, minimize/restore, dragging, and z-index depth stacking.
 */

let activeWindowZIndex = 1000;
let lastReadEventTs = parseFloat(localStorage.getItem('zettnas_last_read_event_ts') || '0');

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

export function makeDraggable(dragEl, handleEl) {
  if (!dragEl) return;
  handleEl = handleEl || dragEl;
  handleEl.style.cursor = 'move';

  let startX = 0, startY = 0, initialMouseX = 0, initialMouseY = 0;
  let activeSnap = null;

  handleEl.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || e.target.closest('button') || e.target.closest('input') || e.target.closest('.modal-ctrl-btn')) return;
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    e.preventDefault();

    const ghost = getOrCreateSnapGhost();
    activeSnap = null;

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
    };

    document.addEventListener('mousemove', drag);
    document.addEventListener('mouseup', stopDrag);
  });

  handleEl.addEventListener('dblclick', (e) => {
    if (e.target.closest('button') || e.target.closest('input') || e.target.closest('.modal-ctrl-btn')) return;
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
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
  });
}

export const DockManager = {
  windows: {},
  activeId: null,

  register(id, el, icon, title, initialMinimized = false) {
    if (!this.windows[id]) {
      this.windows[id] = { el, icon, title, minimized: initialMinimized };
    }
    if (!initialMinimized) {
      this.windows[id].minimized = false;
      el.classList.remove('window-minimized');
      el.classList.add('open');
      el.style.removeProperty('display');
    } else {
      this.windows[id].minimized = true;
      el.classList.add('window-minimized');
      el.classList.remove('open');
      el.style.setProperty('display', 'none', 'important');
      const innerWin = el.querySelector('.smart-modal-window, .chassis-front-panel, .os-window, .mgmt-app-window');
      if (innerWin) {
        innerWin.classList.add('window-minimized');
        innerWin.style.setProperty('display', 'none', 'important');
      }
    }
    this.render();
  },

  unregister(id) {
    if (this.windows[id]) {
      delete this.windows[id];
      this.render();
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
    }
  },

  restore(id) {
    if (this.windows[id]) {
      this.windows[id].minimized = false;
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
      }
      if (id === 'console' && window.updateLcdPages && state.latestStats) {
        window.updateLcdPages(state.latestStats);
      }
      this.render();
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
          ? [...state.latestStats.events].sort((a, b) => b.ts - a.ts)
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

        const unread = events.filter((e) => e.ts > lastReadEventTs);
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
      }
      return null;
    }

    function showDockTooltip(dockItem, id, title, icon, isMinimized) {
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
          const unreadCount = events.filter((e) => e.ts > lastReadEventTs).length;
          if (unreadCount > 0) {
            badgeEl.textContent = `${unreadCount > 99 ? '99+' : unreadCount} UNREAD`;
            badgeEl.className = 'dock-tooltip-status alert';
          } else {
            badgeEl.textContent = 'ALL CAUGHT UP';
            badgeEl.className = 'dock-tooltip-status active';
          }
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

    Object.keys(this.windows).forEach((id) => {
      const win = this.windows[id];
      const item = document.createElement('button');
      item.type = 'button';
      let cls = 'dock-item';
      if (win.minimized) cls += ' minimized';
      if (this.activeId === id && !win.minimized) cls += ' active-window';
      item.className = cls;
      item.setAttribute('aria-label', win.title);
      item.dataset.windowId = id;
      item.innerHTML = `<svg><use href="${win.icon}"/></svg>`;

      item.addEventListener('mousedown', (e) => e.stopPropagation());
      item.addEventListener('mouseenter', () => showDockTooltip(item, id, win.title, win.icon, win.minimized));
      item.addEventListener('focus', () => showDockTooltip(item, id, win.title, win.icon, win.minimized));
      item.addEventListener('mouseleave', hideDockTooltip);
      item.addEventListener('blur', hideDockTooltip);
      item.addEventListener('click', () => {
        hideDockTooltip();
        this.toggle(id);
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

export function initDockSystem() {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  const consoleModal = document.getElementById('console-window');
  const consoleHeader = document.querySelector('#console-window .chassis-panel-header');
  if (consoleModal) makeDraggable(consoleModal, consoleHeader);

  const consoleOverlay = document.getElementById('console-modal-overlay');
  if (consoleOverlay) {
    DockManager.register('console', consoleOverlay, '#i-screen', t('dock.zettnas', 'ZettNAS'), true);
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

  const consoleClose = document.getElementById('console-close');
  if (consoleClose) {
    const handleClose = (e) => {
      if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
      DockManager.minimize('console');
    };
    consoleClose.addEventListener('click', handleClose);
    consoleClose.addEventListener('touchend', handleClose);
  }

  const consolePopout = document.getElementById('console-popout');
  if (consolePopout) {
    consolePopout.addEventListener('click', () => {
      const popupW = 680;
      const popupH = 240;
      const left = Math.max(0, Math.round((window.screen.width - popupW) / 2));
      const top = Math.max(0, Math.round((window.screen.height - popupH) / 2));
      window.open(
        `${window.location.origin}/?mode=lcd`,
        'ZettNAS_Dashboard_Popup',
        `width=${popupW},height=${popupH},top=${top},left=${left},status=no,menubar=no,toolbar=no,location=no,resizable=yes`
      );
    });
  }

  const chassisDesktopIcon = document.getElementById('chassis-desktop-icon');
  if (chassisDesktopIcon) {
    const openOrFocusDashboard = (e) => {
      if (e && e.type === 'touchend') {
        e.preventDefault();
      }
      if (consoleOverlay) {
        if (DockManager.windows['console']?.minimized || consoleOverlay.style.display === 'none' || !consoleOverlay.classList.contains('open')) {
          DockManager.restore('console');
          consoleOverlay.style.removeProperty('display');
          consoleOverlay.classList.add('open');
          consoleModal?.classList.remove('window-minimized');
          if (window.updateLcdPages && state.latestStats) window.updateLcdPages(state.latestStats);
        }
        if (consoleModal) {
          bringToFront(consoleModal);
          consoleModal.classList.remove('window-focus-pulse');
          void consoleModal.offsetWidth; // trigger reflow
          consoleModal.classList.add('window-focus-pulse');
          setTimeout(() => consoleModal.classList.remove('window-focus-pulse'), 850);
        }
      }
    };
    chassisDesktopIcon.addEventListener('click', openOrFocusDashboard);
    chassisDesktopIcon.addEventListener('touchend', openOrFocusDashboard);
    chassisDesktopIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openOrFocusDashboard();
      }
    });
  }

  initDraggableDesktopIcons();

  const smartModal = document.querySelector('#smart-modal-overlay .smart-modal-window');
  const smartHeader = document.querySelector('#smart-modal-overlay .smart-modal-header');
  if (smartModal) makeDraggable(smartModal, smartHeader);

  const fbModal = document.querySelector('#folder-browser-modal .smart-modal-window');
  const fbHeader = document.querySelector('#folder-browser-modal .smart-modal-header');
  if (fbModal) makeDraggable(fbModal, fbHeader);

  const copyToast = document.getElementById('copy-toast');
  const copyToastHeader = document.querySelector('#copy-toast .smart-modal-header');
  if (copyToast) makeDraggable(copyToast, copyToastHeader);

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

  document.querySelectorAll('.smart-modal-window, #console-window').forEach((win) => {
    win.addEventListener('mousedown', (e) => {
      bringToFront(win);
      e._handledAsWindowClick = true;
    });
  });

  document.addEventListener('mousedown', (e) => {
    if (e._handledAsWindowClick) return;
    const windowEl = e.target.closest('.smart-modal-window, #console-window');
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
  const stage = document.querySelector('.desktop-icons-container');
  if (stage) {
    let ctxMenu = document.getElementById('desktop-ctx-menu');
    if (!ctxMenu) {
      ctxMenu = document.createElement('div');
      ctxMenu.id = 'desktop-ctx-menu';
      ctxMenu.className = 'os-context-menu';
      ctxMenu.innerHTML = `
        <div class="ctx-item" id="ctx-align-grid" data-i18n="desktop.align_grid">${t('desktop.align_grid', 'Align to Grid')}</div>
        <div class="ctx-item" id="ctx-sort-name" data-i18n="desktop.sort_name">${t('desktop.sort_name', 'Sort by Name')}</div>
      `;
      document.body.appendChild(ctxMenu);

      const hideMenu = () => ctxMenu.style.display = 'none';
      document.addEventListener('click', hideMenu);
      
      document.body.addEventListener('contextmenu', (e) => {
        if (!e.target.closest('.smart-modal-window') && !e.target.closest('.os-window') && !e.target.closest('#console-window') && !e.target.closest('.os-context-menu') && !e.target.closest('.chassis-hero-box')) {
          e.preventDefault();
          ctxMenu.style.display = 'block';
          ctxMenu.style.left = e.pageX + 'px';
          ctxMenu.style.top = e.pageY + 'px';
        }
      });

      document.getElementById('ctx-align-grid').addEventListener('click', () => {
        if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
        const GRID_X = 140;
        const GRID_Y = 112;
        const OFFSET_X = 24;
        const OFFSET_Y = 56;
        iconConfigs.forEach(({id}) => {
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
      });

      document.getElementById('ctx-sort-name').addEventListener('click', () => {
        if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
        let items = [];
        iconConfigs.forEach(conf => {
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
      });
    }
  }

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
  const panel = document.getElementById('notif-center-panel');
  if (!badge || !state.latestStats || !state.latestStats.events) return;
  
  const events = state.latestStats.events;
  const unreadCount = events.filter(e => e.ts > lastReadEventTs).length;
  
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
    renderNotificationCenter();
    document.addEventListener('click', closeNotifPanelOutside);
  } else {
    panel.style.display = 'none';
    document.removeEventListener('click', closeNotifPanelOutside);
  }
};

function closeNotifPanelOutside(e) {
  const panel = document.getElementById('notif-center-panel');
  if (!panel) return;
  if (!panel.contains(e.target) && !e.target.closest('.dock-notif-btn')) {
    panel.style.display = 'none';
    document.removeEventListener('click', closeNotifPanelOutside);
  }
}

function renderNotificationCenter() {
  const list = document.getElementById('notif-center-list');
  if (!list || !state.latestStats || !state.latestStats.events) return;
  
  const events = [...state.latestStats.events].sort((a,b) => b.ts - a.ts);
  
  if (events.length === 0) {
    list.innerHTML = `<div style="padding:20px; text-align:center; color:var(--muted); font-size:11px;">No recent notifications.</div>`;
    return;
  }
  
  list.innerHTML = '';
  events.slice(0, 50).forEach(e => {
    const isUnread = e.ts > lastReadEventTs;
    const dt = new Date(e.ts * 1000);
    let color = '#cbd5e1';
    let icon = 'ℹ️';
    if (e.level === 'error') { color = 'var(--crit)'; icon = '❌'; }
    else if (e.level === 'warning') { color = 'var(--warn)'; icon = '⚠️'; }
    else if (e.level === 'success') { color = 'var(--ok2)'; icon = '✅'; }
    
    const row = document.createElement('div');
    row.style.cssText = `padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; gap: 8px; align-items: flex-start; background: ${isUnread ? 'rgba(255,255,255,0.05)' : 'transparent'}; cursor:pointer;`;
    row.innerHTML = `
      <span style="font-size: 14px; margin-top:2px;">${icon}</span>
      <div style="display:flex; flex-direction:column; gap:2px;">
        <div style="font-size:11px; font-weight:700; color:${color};">${escapeHtml(e.title)}</div>
        <div style="font-size:10px; color:#fff; line-height:1.4;">${escapeHtml(e.message)}</div>
        <div style="font-size:9px; color:var(--muted); margin-top:2px;">${dt.toLocaleString()}</div>
      </div>
      ${isUnread ? `<div style="width:6px; height:6px; border-radius:50%; background:var(--brand); margin-left:auto; margin-top:6px; flex-shrink:0;"></div>` : ''}
    `;
    
    // Quick action on click (open Management -> Events tab if they want, or just mark read)
    row.addEventListener('click', () => {
      lastReadEventTs = Math.max(lastReadEventTs, e.ts);
      localStorage.setItem('zettnas_last_read_event_ts', lastReadEventTs.toString());
      updateNotificationBadge();
      renderNotificationCenter();
      
      // Optionally open the full events log
      if (window.DockManager && window.DockManager.windows['management']) {
        window.DockManager.restore('management');
        const evTab = document.querySelector('.tab-btn[data-target="management-events"]');
        if (evTab) evTab.click();
      }
    });
    
    list.appendChild(row);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const markReadBtn = document.getElementById('notif-mark-read');
  if (markReadBtn) {
    markReadBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.latestStats && state.latestStats.events && state.latestStats.events.length > 0) {
        lastReadEventTs = Math.max(...state.latestStats.events.map(ev => ev.ts));
        localStorage.setItem('zettnas_last_read_event_ts', lastReadEventTs.toString());
        updateNotificationBadge();
        renderNotificationCenter();
      }
    });
  }
  
  ZettEventBus.on('stats:updated', () => {
    updateNotificationBadge();
    const panel = document.getElementById('notif-center-panel');
    if (panel && panel.style.display !== 'none') {
      // Re-render if open
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
