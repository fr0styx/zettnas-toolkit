import { state } from '../state.js';
import { t } from '../i18n.js';
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
      dragEl.style.left = Math.max(10, Math.min(window.innerWidth - targetW - 10, e.clientX - targetW / 2)) + 'px';
      dragEl.style.top = Math.max(48, e.clientY - 20) + 'px';
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
      dragEl.style.left = Math.max(10, Math.round((window.innerWidth - targetW) / 2)) + 'px';
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
      } else if (id === 'management') {
        const container = document.createElement('div');
        container.className = 'dock-preview-summary';
        container.style.cssText = 'display:flex; align-items:center; gap:8px; height:100%;';
        container.innerHTML = `
          <img src="img/chassis-d6u.png" style="width:38px; height:auto; border-radius:4px; filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5));" alt="Chassis">
          <div style="display:flex; flex-direction:column; gap:2px; overflow:hidden;">
            <div style="font-size:10px; font-weight:700; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">System Management</div>
            <div style="font-size:8px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Profiles • Containers • Storage</div>
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
      item.dataset.windowId = id;
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
    DockManager.register('console', consoleOverlay, '#i-screen', t('dock.zettnas', 'ZettNAS'));
    if (consoleModal) bringToFront(consoleModal);
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

  // Mobile / Stacked Mode Toggle & Auto-detection
  const mobileToggleBtn = document.getElementById('mobile-view-toggle-btn');
  const storedMobile = localStorage.getItem('zettnas_mobile_mode');
  if (storedMobile === '1' || (storedMobile === null && window.innerWidth <= 768)) {
    document.body.classList.add('mobile-mode');
    if (mobileToggleBtn) mobileToggleBtn.classList.add('active');
  }

  if (mobileToggleBtn) {
    mobileToggleBtn.addEventListener('click', () => {
      const isMobile = document.body.classList.toggle('mobile-mode');
      mobileToggleBtn.classList.toggle('active', isMobile);
      mobileToggleBtn.title = isMobile ? 'Mobile / Stacked View Active [Click for Desktop Windows]' : 'Toggle Mobile / Stacked Mode';
      localStorage.setItem('zettnas_mobile_mode', isMobile ? '1' : '0');
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
  const storageKey = 'zettnas_desktop_icon_positions';
  let savedPositions = {};
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw) savedPositions = JSON.parse(raw) || {};
  } catch (e) {
    savedPositions = {};
  }

  // 1st icon: Management; 2nd icon: ZettNAS
  const iconConfigs = [
    { id: 'management-desktop-icon', defaultLeft: 24, defaultTop: 24 },
    { id: 'chassis-desktop-icon', defaultLeft: 180, defaultTop: 24 },
  ];

  iconConfigs.forEach(({ id, defaultLeft, defaultTop }) => {
    const el = document.getElementById(id);
    if (!el) return;

    const applyPosition = (x, y) => {
      if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) {
        el.style.removeProperty('position');
        el.style.removeProperty('left');
        el.style.removeProperty('top');
        return;
      }
      const maxLeft = Math.max(10, window.innerWidth - (el.offsetWidth || 136) - 10);
      const maxTop = Math.max(48, window.innerHeight - (el.offsetHeight || 136) - 70);
      const clampedLeft = Math.max(10, Math.min(maxLeft, x));
      const clampedTop = Math.max(48, Math.min(maxTop, y));
      el.style.position = 'fixed';
      el.style.left = `${clampedLeft}px`;
      el.style.top = `${clampedTop}px`;
    };

    const saved = savedPositions[id];
    if (saved && typeof saved.left === 'number' && typeof saved.top === 'number') {
      applyPosition(saved.left, saved.top);
    } else {
      applyPosition(defaultLeft, defaultTop);
    }

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
          const curMaxLeft = Math.max(10, window.innerWidth - (el.offsetWidth || 136) - 10);
          const curMaxTop = Math.max(48, window.innerHeight - (el.offsetHeight || 136) - 70);
          const newLeft = Math.max(10, Math.min(curMaxLeft, initLeft + dx));
          const newTop = Math.max(48, Math.min(curMaxTop, initTop + dy));
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
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    iconConfigs.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const maxLeft = Math.max(10, window.innerWidth - (el.offsetWidth || 136) - 10);
      const maxTop = Math.max(48, window.innerHeight - (el.offsetHeight || 136) - 70);
      const clampedLeft = Math.max(10, Math.min(maxLeft, rect.left));
      const clampedTop = Math.max(48, Math.min(maxTop, rect.top));
      el.style.left = `${clampedLeft}px`;
      el.style.top = `${clampedTop}px`;
    });
  });
}
