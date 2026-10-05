import { state } from '../state.js';
/**
 * ZettNAS Toolkit Dock & Window Manager
 * Handles floating modal registration, minimize/restore, dragging, and z-index depth stacking.
 */

let activeWindowZIndex = 10000;

export function bringToFront(windowEl) {
  if (!windowEl) return;
  activeWindowZIndex++;
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

export function makeDraggable(dragEl, handleEl) {
  if (!dragEl) return;
  handleEl = handleEl || dragEl;
  handleEl.style.cursor = 'move';

  let startX = 0, startY = 0, initialMouseX = 0, initialMouseY = 0;

  handleEl.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || e.target.closest('button') || e.target.closest('input')) return;
    e.preventDefault();

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
    };

    const stopDrag = () => {
      document.removeEventListener('mousemove', drag);
      document.removeEventListener('mouseup', stopDrag);
    };

    document.addEventListener('mousemove', drag);
    document.addEventListener('mouseup', stopDrag);
  });
}

export const DockManager = {
  windows: {},
  activeId: null,

  register(id, el, icon, title) {
    if (!this.windows[id]) {
      this.windows[id] = { el, icon, title, minimized: false };
    }
    this.windows[id].minimized = false;
    el.classList.remove('window-minimized');
    el.style.removeProperty('display');
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
      this.windows[id].el.style.setProperty('display', 'none', 'important');
      this.render();
    }
  },

  restore(id) {
    if (this.windows[id]) {
      this.windows[id].minimized = false;
      this.windows[id].el.classList.remove('window-minimized');
      this.windows[id].el.style.removeProperty('display');

      const winEl = this.windows[id].el.classList.contains('smart-modal-window') || this.windows[id].el.classList.contains('chassis-front-panel')
        ? this.windows[id].el
        : this.windows[id].el.querySelector('.smart-modal-window, .chassis-front-panel');
      if (winEl) {
        bringToFront(winEl);
      }
      this.render();
    }
  },

  toggle(id) {
    if (this.windows[id]) {
      if (this.windows[id].minimized) {
        this.restore(id);
      } else {
        const winEl = this.windows[id].el.classList.contains('smart-modal-window') || this.windows[id].el.classList.contains('chassis-front-panel')
          ? this.windows[id].el
          : this.windows[id].el.querySelector('.smart-modal-window, .chassis-front-panel');
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
        const model = document.getElementById('smart-meta-model')?.textContent || 'Drive Health';
        const health = document.getElementById('smart-meta-health')?.textContent || 'PASSED';
        const hours = document.getElementById('smart-meta-hours')?.textContent || '--';
        const devTitle = document.getElementById('smart-modal-title')?.textContent || 'Diagnostics';
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
      } else if (id === 'copy') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        const status = document.getElementById('copy-toast-status')?.textContent || 'Ingest';
        const pct = document.getElementById('copy-toast-pct')?.textContent || '0%';
        const file = document.getElementById('copy-toast-file')?.textContent || 'Preparing...';
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
        const path = document.getElementById('fb-current-path')?.textContent || '/mnt/user';
        container.innerHTML = `
          <div style="font-size:9px; font-weight:700; color:#fff;">Folder Destination</div>
          <div style="font-family:monospace; font-size:8px; color:var(--ok2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:3px;">${path}</div>
        `;
        return container;
      } else if (id === 'home') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        container.style.cssText = 'display:flex; align-items:center; gap:8px; height:100%;';
        container.innerHTML = `
          <img src="img/chassis-d6u.png" style="width:42px; height:auto; border-radius:4px; filter:drop-shadow(0 2px 5px rgba(0,0,0,0.5));" alt="Chassis">
          <div style="display:flex; flex-direction:column; gap:2px;">
            <span style="font-size:10px; font-weight:700; color:#fff;">Desktop Home</span>
            <span style="font-size:8px; color:var(--muted);">Click to clear / minimize all</span>
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

      const rect = dockItem.getBoundingClientRect();
      const tooltipW = 210;
      const tooltipH = 92;

      let leftPos = rect.left + (rect.width / 2) - (tooltipW / 2);
      leftPos = Math.max(10, Math.min(window.innerWidth - tooltipW - 10, leftPos));
      const topPos = rect.top - tooltipH - 10;

      tooltip.style.left = `${leftPos}px`;
      tooltip.style.top = `${topPos}px`;
      tooltip.classList.add('visible');
    }

    function hideDockTooltip() {
      clearTimeout(hoverTimeout);
      hoverTimeout = setTimeout(() => {
        const tooltip = document.getElementById('dock-hover-tooltip');
        if (tooltip) tooltip.classList.remove('visible');
      }, 120);
    }

    const dashItem = document.createElement('div');
    dashItem.className = 'dock-item';
    dashItem.setAttribute('aria-label', 'Dashboard Home');
    dashItem.innerHTML = `<svg><use href="#i-globe"/></svg>`;
    dashItem.addEventListener('mouseenter', () => showDockTooltip(dashItem, 'home', 'Dashboard Home', '#i-globe', false));
    dashItem.addEventListener('mouseleave', hideDockTooltip);
    dashItem.addEventListener('click', () => {
      hideDockTooltip();
      const allModals = document.querySelectorAll('.smart-modal-backdrop, .smart-modal-window, #console-window');
      allModals.forEach((m) => {
        if (m.classList.contains('smart-modal-backdrop') && m.classList.contains('open')) {
          m.style.zIndex = '40';
        } else if (m.id === 'copy-toast' && m.style.opacity === '1') {
          m.style.zIndex = '40';
        }
      });
    });
    dock.appendChild(dashItem);

    Object.keys(this.windows).forEach((id) => {
      const win = this.windows[id];
      const item = document.createElement('div');
      let cls = 'dock-item';
      if (win.minimized) cls += ' minimized';
      if (this.activeId === id && !win.minimized) cls += ' active-window';
      item.className = cls;
      item.setAttribute('aria-label', win.title);
      item.innerHTML = `<svg><use href="${win.icon}"/></svg>`;

      item.addEventListener('mousedown', (e) => e.stopPropagation());
      item.addEventListener('mouseenter', () => showDockTooltip(item, id, win.title, win.icon, win.minimized));
      item.addEventListener('mouseleave', hideDockTooltip);
      item.addEventListener('click', () => {
        hideDockTooltip();
        this.toggle(id);
      });

      dock.appendChild(item);
    });
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
    DockManager.register('console', consoleOverlay, '#i-chip', 'System Console');
    if (consoleModal) bringToFront(consoleModal);
  }

  const consoleMin = document.getElementById('console-min');
  if (consoleMin) {
    consoleMin.addEventListener('click', () => {
      DockManager.minimize('console');
    });
  }

  const consoleClose = document.getElementById('console-close');
  if (consoleClose) {
    consoleClose.addEventListener('click', () => {
      DockManager.minimize('console');
    });
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
    const openOrFocusDashboard = () => {
      if (consoleOverlay) {
        if (DockManager.windows['console']?.minimized || consoleOverlay.style.display === 'none' || !consoleOverlay.classList.contains('open')) {
          DockManager.restore('console');
          consoleOverlay.style.removeProperty('display');
          consoleOverlay.classList.add('open');
          consoleModal?.classList.remove('window-minimized');
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
    chassisDesktopIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openOrFocusDashboard();
      }
    });
  }

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
    toastContainer.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:10005;display:flex;flex-direction:column;gap:8px;';
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
      return;
    }
    const allModals = document.querySelectorAll('.smart-modal-backdrop, .smart-modal-window, #console-window');
    allModals.forEach((m) => {
      if (m.classList.contains('smart-modal-backdrop') && m.classList.contains('open')) {
        m.style.zIndex = '40';
      } else if (m.id === 'copy-toast' && m.style.opacity === '1') {
        m.style.zIndex = '40';
      }
    });
  });
}
