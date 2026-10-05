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

    const dashItem = document.createElement('div');
    dashItem.className = 'dock-item';
    dashItem.title = 'Dashboard Home';
    dashItem.innerHTML = `<svg><use href="#i-globe"/></svg>`;
    dashItem.addEventListener('click', () => {
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
      item.title = win.title;
      item.innerHTML = `<svg><use href="${win.icon}"/></svg>`;

      item.addEventListener('mousedown', (e) => e.stopPropagation());
      item.addEventListener('click', () => this.toggle(id));

      dock.appendChild(item);
    });
  }
};

window.DockManager = DockManager;
window.bringToFront = bringToFront;

export function initDockSystem() {
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
