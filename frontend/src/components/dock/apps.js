// The apps the dock knows, the File Explorer window switcher and the dock item menu.
// Part of dock.js, split out by ARC-5.

import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { ZettEventBus } from '../../event-bus.js';
import { openConsoleWindow } from './console-window.js';
import { DockManager } from './dock-manager.js';
import { bringToFront } from './window-drag.js';

export const KNOWN_APPS = {
  fm: {
    id: 'fm',
    icon: '#i-storage',
    getTitle: () => t('dock.file_manager', 'File Explorer'),
    launch: (path = null) => {
      if (typeof window.openFileManager === 'function') {
        window.openFileManager(path);
      } else {
        const fmWin = document.getElementById('file-manager-window');
        if (fmWin) {
          if (window.DockManager && !window.DockManager.windows['fm']) {
            window.DockManager.register('fm', fmWin, '#i-storage', t('dock.file_manager', 'File Explorer'), false);
          }
          if (window.DockManager) window.DockManager.restore('fm');
          ZettEventBus.emit('window:open', { id: 'file-manager-window', path: path || undefined });
        } else {
          document.getElementById('fm-desktop-icon')?.click();
        }
      }
    }
  },
  management: {
    id: 'management',
    icon: '#i-management',
    getTitle: () => t('dock.management', 'Settings'),
    launch: (pane = null) => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow(pane === 'hub' ? null : pane);
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
    getTitle: () => t('dh.title', 'Drive Health'),
    launch: (devName = null) => ZettEventBus.emit('modal:smart:open', devName)
  },
  'container-inspector': {
    id: 'container-inspector',
    icon: '#i-chip',
    getTitle: () => 'Container Inspector',
    launch: (data = null) => {
      if (data && data.cid && typeof window.openContainerInspector === 'function') {
        window.openContainerInspector(data.cid, data.cname);
      }
    }
  },
  containers: {
    id: 'containers',
    icon: '#i-chip',
    getTitle: () => t('dock.containers', 'Containers'),
    launch: () => {
      if (typeof window.openContainersManager === 'function') {
        window.openContainersManager();
      } else if (typeof window.openContainersWindow === 'function') {
        window.openContainersWindow();
      } else {
        const cWin = document.getElementById('containers-manager-window');
        if (cWin) {
          if (window.DockManager && !window.DockManager.windows['containers']) {
            window.DockManager.register('containers', cWin, '#i-chip', t('dock.containers', 'Containers'), false);
          }
          if (window.DockManager) window.DockManager.restore('containers');
          ZettEventBus.emit('window:open', { id: 'containers-manager-window' });
        } else {
          document.getElementById('containers-desktop-icon')?.click();
        }
      }
    }
  },
  vm: {
    id: 'vm',
    icon: '#i-vm',
    getTitle: () => t('dock.vm_manager', 'Virtual Machines'),
    launch: () => {
      if (typeof window.openVmManager === 'function') {
        window.openVmManager();
      } else {
        const vmWin = document.getElementById('vm-manager-window');
        if (vmWin) {
          if (window.DockManager && !window.DockManager.windows['vm']) {
            window.DockManager.register('vm', vmWin, '#i-vm', t('dock.vm_manager', 'Virtual Machines'), false);
          }
          if (window.DockManager) window.DockManager.restore('vm');
          ZettEventBus.emit('window:open', { id: 'vm-manager-window' });
        } else {
          document.getElementById('vm-desktop-icon')?.click();
        }
      }
    }
  },
  'app-deploy': {
    id: 'app-deploy',
    icon: '#i-chip',
    getTitle: () => 'App Deployment',
    launch: () => {
      const overlay = document.getElementById('app-deploy-modal-overlay');
      const win = document.getElementById('app-deploy-modal-window');
      if (overlay) {
        if (DockManager) DockManager.restore('app-deploy');
        if (win) bringToFront(win);
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
  },
  'cloud-remote': {
    id: 'cloud-remote',
    icon: '#i-cloud',
    getTitle: () => 'Cloud Remotes',
    launch: () => {
      if (typeof window.openNewCloudRemoteModal === 'function') {
        window.openNewCloudRemoteModal();
      } else {
        const crOverlay = document.getElementById('modal-new-cloud-remote');
        const crWin = document.getElementById('cloud-remote-window');
        if (crOverlay && window.DockManager) {
          window.DockManager.restore('cloud-remote');
          if (crWin) bringToFront(crWin);
        }
      }
    }
  },
  personalization: {
    id: 'personalization',
    icon: '#i-screen',
    getTitle: () => t('dock.personalization', 'Desktop & Personalization'),
    launch: (tab = null) => {
      if (typeof window.openPersonalizationWindow === 'function') {
        window.openPersonalizationWindow(tab);
      }
    }
  },
  zettai: {
    id: 'zettai',
    icon: '#i-search',
    getTitle: () => t('dock.zettai', 'Ask Zetty'),
    launch: () => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-ai-rag', 'mgmt-pane-ai-rag');
      } else {
        document.getElementById('management-desktop-icon')?.click();
      }
    }
  }
};

export function toggleFmWindowSwitcher(anchorEl, fmWindows = []) {
  let popover = document.getElementById('dock-fm-switcher');
  if (popover) {
    popover.remove();
    return;
  }
  if (!fmWindows.length) return;

  popover = document.createElement('div');
  popover.id = 'dock-fm-switcher';
  popover.className = 'dock-switcher-popover glassmorphic-panel';

  const header = document.createElement('div');
  header.className = 'dock-switcher-header';
  header.innerHTML = `
    <span>${t('dock.switcher_title', 'File Explorer Windows')} (${fmWindows.length})</span>
    <button class="win-btn close-btn" style="width:14px; height:14px;" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
  `;
  header.querySelector('.close-btn').onclick = () => popover.remove();
  popover.appendChild(header);

  fmWindows.forEach((w) => {
    const item = document.createElement('div');
    const isActive = DockManager.activeId === w.id && !w.minimized;
    item.className = `dock-switcher-item ${isActive ? 'active' : ''}`;
    const winTitle = w.title || 'File Explorer';
    const folderName = winTitle.includes('(') ? winTitle.split('(')[1].replace(')', '') : winTitle;
    let pathStr = '';
    if (w.el && typeof w.el.querySelector === 'function') {
      const pathInput = w.el.querySelector('.fm-path-input');
      if (pathInput && pathInput.value) pathStr = pathInput.value;
    }

    item.innerHTML = `
      <span class="dock-switcher-icon">📁</span>
      <div class="dock-switcher-info">
        <span class="dock-switcher-name">${escapeHtml(folderName)}</span>
        ${pathStr ? `<span class="dock-switcher-path">${escapeHtml(pathStr)}</span>` : ''}
      </div>
      <button class="dock-switcher-close" title="${t('dock.close_window', 'Close Window')}" aria-label="${t('dock.close_window', 'Close Window')}">✕</button>
    `;

    item.addEventListener('click', (e) => {
      if (e.target.closest('.dock-switcher-close')) return;
      popover.remove();
      DockManager.restore(w.id);
      const innerWin = w.el?.querySelector?.('.file-manager-window') || w.el;
      if (innerWin) bringToFront(innerWin);
    });

    item.querySelector('.dock-switcher-close').addEventListener('click', (e) => {
      e.stopPropagation();
      const closeBtn = w.el?.querySelector?.('.close-btn') || w.el?.querySelector?.('#fm-close');
      if (closeBtn) closeBtn.click();
      else DockManager.closeWindow(w.id);
      popover.remove();
    });

    popover.appendChild(item);
  });

  document.body.appendChild(popover);

  const rect = anchorEl.getBoundingClientRect();
  const popW = 280;
  const popH = popover.offsetHeight || 180;
  let left = rect.left + (rect.width / 2) - (popW / 2);
  left = Math.max(12, Math.min(window.innerWidth - popW - 12, left));
  let top = rect.top - popH - 12;
  if (top < 10) top = rect.bottom + 12;

  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;

  const closeOnOutside = (e) => {
    if (!popover.contains(e.target) && !anchorEl.contains(e.target)) {
      popover.remove();
      document.removeEventListener('pointerdown', closeOnOutside);
    }
  };
  setTimeout(() => document.addEventListener('pointerdown', closeOnOutside), 50);
}

export function showDockItemContextMenu(x, y, id, title, isPinned, isRunning, openWindowsList = []) {
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
  const isFmApp = id === 'fm' || (id && id.startsWith('fm-')) || (id && id.startsWith('file-manager-window'));

  let html = `
    <div class="ctx-item" id="dock-ctx-pin">
      <span style="font-size:var(--zn-fs-xs); margin-right:6px;">${pinIcon}</span>
      <span>${escapeHtml(pinLabel)}</span>
    </div>
  `;

  if (isFmApp) {
    html += `
      <div class="ctx-item" id="dock-ctx-new-window">
        <span style="font-size:var(--zn-fs-xs); margin-right:6px;">🪟</span>
        <span>${escapeHtml(t('dock.new_fm_window', 'New Window (Ctrl+N)'))}</span>
      </div>
    `;

    if (openWindowsList && openWindowsList.length > 0) {
      html += `<div style="height:1px; background:var(--zn-glaze-8); margin:4px 0;"></div>`;
      html += `<div style="font-size:var(--zn-fs-xs); color:var(--muted); padding:3px 10px; font-weight:700; text-transform:uppercase;">${escapeHtml(t('dock.open_windows', 'Open Windows'))}</div>`;
      openWindowsList.forEach((w) => {
        const wTitle = w.title || 'File Explorer';
        const isCurrentActive = DockManager.activeId === w.id;
        html += `
          <div class="ctx-item dock-ctx-fm-win" data-win-id="${escapeHtml(w.id)}" style="display:flex; align-items:center; justify-content:space-between;">
            <div style="display:flex; align-items:center; gap:6px; min-width:0; overflow:hidden;">
              <span style="font-size:var(--zn-fs-xs);">📁</span>
              <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(wTitle)}</span>
            </div>
            ${isCurrentActive ? `<span style="color:var(--lt-ink-brand, var(--accent-cyan, #0ea5e9)); font-size:var(--zn-fs-xs);">✓</span>` : ''}
          </div>
        `;
      });
      html += `<div style="height:1px; background:var(--zn-glaze-8); margin:4px 0;"></div>`;
      html += `
        <div class="ctx-item" id="dock-ctx-close-all" style="color:var(--crit, #ff5c5c);">
          <span style="font-size:var(--zn-fs-xs); margin-right:6px;">✕</span>
          <span>${escapeHtml(t('dock.close_all_windows', 'Close All Windows'))}</span>
        </div>
      `;
    } else if (isRunning) {
      html += `
        <div class="ctx-item" id="dock-ctx-close" style="color:var(--crit, #ff5c5c);">
          <span style="font-size:var(--zn-fs-xs); margin-right:6px;">✕</span>
          <span>${escapeHtml(closeLabel)}</span>
        </div>
      `;
    } else {
      html += `
        <div class="ctx-item" id="dock-ctx-open" style="color:var(--ok2, #25c2a0);">
          <span style="font-size:var(--zn-fs-xs); margin-right:6px;">▶</span>
          <span>${escapeHtml(openLabel)}</span>
        </div>
      `;
    }
  } else {
    if (isRunning) {
      html += `
        <div class="ctx-item" id="dock-ctx-close" style="color:var(--crit, #ff5c5c);">
          <span style="font-size:var(--zn-fs-xs); margin-right:6px;">✕</span>
          <span>${escapeHtml(closeLabel)}</span>
        </div>
      `;
    } else {
      html += `
        <div class="ctx-item" id="dock-ctx-open" style="color:var(--ok2, #25c2a0);">
          <span style="font-size:var(--zn-fs-xs); margin-right:6px;">▶</span>
          <span>${escapeHtml(openLabel)}</span>
        </div>
      `;
    }
  }

  menu.innerHTML = html;
  menu.style.display = 'block';
  const menuW = 180;
  const menuH = menu.offsetHeight || 90;
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

  document.getElementById('dock-ctx-new-window')?.addEventListener('click', (e) => {
    e.stopPropagation();
    if (typeof window.openNewFileManagerWindow === 'function') {
      window.openNewFileManagerWindow();
    }
    hideMenu();
  });

  document.querySelectorAll('.dock-ctx-fm-win').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const winId = el.dataset.winId;
      if (winId && DockManager.windows[winId]) {
        DockManager.restore(winId);
        const winEl = DockManager.windows[winId]?.el;
        const innerWin = winEl?.querySelector?.('.file-manager-window') || winEl;
        if (innerWin) bringToFront(innerWin);
      }
      hideMenu();
    });
  });

  document.getElementById('dock-ctx-close-all')?.addEventListener('click', (e) => {
    e.stopPropagation();
    if (typeof window.closeAllFileManagerWindows === 'function') {
      window.closeAllFileManagerWindows();
    } else {
      openWindowsList.forEach((w) => DockManager.closeWindow(w.id));
    }
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
