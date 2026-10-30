/**
 * ZettNAS Toolkit - SOTA File Explorer Auxiliary Engines
 * Handles 2D Canvas Marquee Selection, 3-Pane Sidebar Tree, Metadata Inspector,
 * Popover Context Menu with Viewport Boundary Clamping, and Transfer Queue Cockpit.
 */

import { t } from '../i18n.js';
import { escapeHtml, copyTextToClipboard } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { formatBytes, executeTransferWithConflictCheck } from './file-manager.js';
import { openFilePreview as openFilePreviewModal } from '../file-preview-loader.js';
import { auth, api } from '../api.js';
import { thumbKind, previewUrl } from './viewer-kit.js';
import { canPlayHere, describeMedia, mediaInfoUrl } from './media-support.js';
import { showToast } from '../toast.js';

import { formatDateTime } from '../format.js';
import { transferCenter } from './transfer-center.js';
import { favorites, loadFavorites, removeFavorite, isFavorite, toggleFavorite } from './fm-favorites.js';
/** The "Sort by" rows of the menu for empty space in a folder: each field, the current one
 * ticked, then ascending and descending. */
export function sortMenuHtml(sortBy, sortDir) {
  const fields = [
    ['name', t('fm.sort_name', 'Name')],
    ['size', t('fm.sort_size', 'Size')],
    ['type', t('fm.sort_type', 'Type')],
    ['mtime', t('fm.sort_mtime', 'Date modified')],
  ];
  const dirs = [
    ['asc', t('fm.sort_asc', 'Ascending')],
    ['desc', t('fm.sort_desc', 'Descending')],
  ];
  const row = (act, label, on) =>
    `<div class="fm-ctx-item${on ? ' is-current' : ''}" data-act="${act}" role="menuitemradio" tabindex="-1" aria-checked="${on}"><span class="fm-ctx-check">${on ? '✓' : ''}</span>${escapeHtml(label)}</div>`;
  return `<div class="fm-ctx-group" role="group" aria-label="${escapeHtml(t('fm.sort_by', 'Sort by'))}"><div class="fm-ctx-heading">${escapeHtml(t('fm.sort_by', 'Sort by'))}</div>${fields
    .map(([k, label]) => row(`sort-${k}`, label, sortBy === k))
    .join('')}<div class="fm-ctx-divider"></div>${dirs.map(([k, label]) => row(`sort-${k}`, label, sortDir === k)).join('')}</div>`;
}

/** "Ctrl" on Windows and Linux, "⌘" on a Mac or iPad (NUX-7). */
export function modKey(nav = typeof navigator !== 'undefined' ? navigator : null) {
  const p = nav ? `${nav.platform || ''} ${nav.userAgent || ''}` : '';
  return /Mac|iPhone|iPad/i.test(p) ? '⌘' : 'Ctrl';
}

/** One row of the right-click menu: a menu item with its icon, label and key. */
export function ctxItem(act, icon, label, key = '', extraClass = '') {
  const k = key ? ` <span class="fm-ctx-key" aria-hidden="true">${escapeHtml(key)}</span>` : '';
  return `<div class="fm-ctx-item${extraClass ? ` ${extraClass}` : ''}" data-act="${act}" role="menuitem" tabindex="-1"><span aria-hidden="true">${icon}</span> ${escapeHtml(label)}${k}</div>`;
}

/** Arrow keys, Home, End, Enter and Space in a menu; Tab closes it (NUX-7). */
export function onMenuKeys(menu, e, hide) {
  const items = /** @type {HTMLElement[]} */ ([...menu.querySelectorAll('[role="menuitem"], [role="menuitemradio"]')]);
  if (!items.length) return;
  const i = items.indexOf(/** @type {HTMLElement} */ (document.activeElement));
  let next;
  if (e.key === 'ArrowDown') next = (i + 1) % items.length;
  else if (e.key === 'ArrowUp') next = (i - 1 + items.length) % items.length;
  else if (e.key === 'Home') next = 0;
  else if (e.key === 'End') next = items.length - 1;
  else if ((e.key === 'Enter' || e.key === ' ') && i >= 0) {
    e.preventDefault();
    items[i].click();
    return;
  } else if (e.key === 'Tab') {
    hide();
    return;
  } else return;
  e.preventDefault();
  items[next].focus();
}

export function isGuardedSystemDir(path) {
  if (!path) return false;
  const normalized = String(path).replace(/\\/g, '/').toLowerCase();
  const guarded = ['/boot', '/etc', '/sys', '/proc', '/dev', '/usr', '/bin', '/sbin', '/var', '/appdata', '/mnt/user/appdata'];
  return guarded.some((p) => normalized === p || normalized.startsWith(p + '/'));
}

/**
 * 1. 2D Marquee (Rubber-Band) Selection Controller
 * 60FPS AABB spatial collision math, Shift/Cmd modifier algebra, and edge auto-scrolling.
 */
export class FmMarqueeController {
  constructor(fmWindow) {
    this.fm = fmWindow;
    this.viewport = fmWindow.viewport;
    this.marqueeBox = fmWindow.marqueeBox;
    this.isSelecting = false;
    this.hasMoved = false;
    this.startX = 0;
    this.startY = 0;
    this.initialSelection = new Set();
    this.boundOnPointerMove = this.onPointerMove.bind(this);
    this.boundOnPointerUp = this.onPointerUp.bind(this);
    this.init();
  }

  init() {
    if (!this.viewport) return;
    this.viewport.addEventListener('pointerdown', (e) => this.onPointerDown(e));
  }

  onPointerDown(e) {
    // Mouse only, left button only
    if (e.pointerType !== 'mouse' || e.button !== 0) return;
    // Don't initiate marquee if clicking an existing file item, button, input, or scrollbar
    if (e.target.closest('.fm-row, .fm-grid-card, .fm-file-item, button, input, .fm-header-row, a, .fm-act-btn')) {
      return;
    }

    this.isSelecting = true;
    this.hasMoved = false;
    const vpRect = this.viewport.getBoundingClientRect();
    this.startX = e.clientX - vpRect.left + this.viewport.scrollLeft;
    this.startY = e.clientY - vpRect.top + this.viewport.scrollTop;
    this.shiftKey = e.shiftKey;
    this.ctrlKey = e.ctrlKey || e.metaKey;
    this.initialSelection = new Set(this.fm.selectedPaths);

    if (this.marqueeBox) {
      this.marqueeBox.style.left = `${this.startX}px`;
      this.marqueeBox.style.top = `${this.startY}px`;
      this.marqueeBox.style.width = '0px';
      this.marqueeBox.style.height = '0px';
      this.marqueeBox.style.display = 'none';
    }

    window.addEventListener('pointermove', this.boundOnPointerMove);
    window.addEventListener('pointerup', this.boundOnPointerUp);
    try {
      this.viewport.setPointerCapture(e.pointerId);
    } catch (_) {}
  }

  onPointerMove(e) {
    if (!this.isSelecting) return;
    const vpRect = this.viewport.getBoundingClientRect();
    const curX = e.clientX - vpRect.left + this.viewport.scrollLeft;
    const curY = e.clientY - vpRect.top + this.viewport.scrollTop;

    const left = Math.min(this.startX, curX);
    const top = Math.min(this.startY, curY);
    const width = Math.abs(curX - this.startX);
    const height = Math.abs(curY - this.startY);

    // Only initiate selection box when dragged beyond threshold
    if (width > 4 || height > 4) {
      if (!this.hasMoved) {
        this.hasMoved = true;
        if (!this.shiftKey && !this.ctrlKey) {
          this.fm.clearSelection();
        }
      }

      if (this.marqueeBox) {
        this.marqueeBox.style.left = `${left}px`;
        this.marqueeBox.style.top = `${top}px`;
        this.marqueeBox.style.width = `${width}px`;
        this.marqueeBox.style.height = `${height}px`;
        this.marqueeBox.style.display = 'block';
      }

      this.calculateIntersections(left, top, width, height);
    }

    // Auto-scroll when near top or bottom edges
    const edgeMargin = 28;
    if (e.clientY < vpRect.top + edgeMargin) {
      this.viewport.scrollTop -= 14;
    } else if (e.clientY > vpRect.bottom - edgeMargin) {
      this.viewport.scrollTop += 14;
    }
  }

  calculateIntersections(mLeft, mTop, mWidth, mHeight) {
    const mRight = mLeft + mWidth;
    const mBottom = mTop + mHeight;

    const vpRect = this.viewport.getBoundingClientRect();
    const items = this.viewport.querySelectorAll('.fm-row, .fm-grid-card');
    const newSelected = new Set(this.shiftKey || this.ctrlKey ? this.initialSelection : []);

    items.forEach((item) => {
      const path = item.dataset.path;
      if (!path || item.dataset.name === '..') return;
      const r = item.getBoundingClientRect();
      const itemLeft = r.left - vpRect.left + this.viewport.scrollLeft;
      const itemTop = r.top - vpRect.top + this.viewport.scrollTop;
      const itemRight = itemLeft + r.width;
      const itemBottom = itemTop + r.height;

      const intersects = !(itemRight < mLeft || itemLeft > mRight || itemBottom < mTop || itemTop > mBottom);

      if (intersects) {
        if (this.ctrlKey && this.initialSelection.has(path)) {
          newSelected.delete(path);
        } else {
          newSelected.add(path);
        }
      }
    });

    this.fm.selectedPaths = newSelected;
    this.fm.updateRowSelectionUI();
    this.fm.updateSelectionToolbar();
    if (this.fm.inspector) this.fm.inspector.update();
  }

  onPointerUp(e) {
    if (!this.isSelecting) return;
    this.isSelecting = false;
    if (this.marqueeBox) {
      this.marqueeBox.style.display = 'none';
    }
    window.removeEventListener('pointermove', this.boundOnPointerMove);
    window.removeEventListener('pointerup', this.boundOnPointerUp);
    try {
      this.viewport.releasePointerCapture(e.pointerId);
    } catch (_) {}

    // Suppress subsequent synthetic click on viewport if the pointer actually dragged
    if (this.hasMoved) {
      this.fm._suppressNextViewportClick = true;
      setTimeout(() => {
        this.fm._suppressNextViewportClick = false;
      }, 350);
    }

    this.fm.updateRowSelectionUI();
    this.fm.updateSelectionToolbar();
    if (this.fm.inspector) this.fm.inspector.update();
  }
}

/**
 * 2. Left Tree Navigation Sidebar
 * Expandable storage places, NVMe pools, array shares, remotes, and favorites.
 */
export class FmSidebarTree {
  constructor(fmWindow, containerEl) {
    this.fm = fmWindow;
    this.container = containerEl;
    this.roots = [];
    this.remotes = [];
    this.expandedPaths = new Set(['/mnt/user']);
    this._onMountChanged = () => this.refresh();
    this._onFavorites = () => this.render();
    ZettEventBus.on('fm:favorites', this._onFavorites);
    ZettEventBus.on('fm:refresh', this._onMountChanged);
    ZettEventBus.on('storage:mount_changed', this._onMountChanged);
    this.init();
  }

  async init() {
    if (!this.container) return;
    await Promise.all([this.loadRoots(), loadFavorites()]);
    this.render();
  }

  async refresh() {
    await this.loadRoots();
    this.render();
    this.updateActive(this.fm.currentPath);
  }

  destroy() {
    if (this._onFavorites) {
      ZettEventBus.off('fm:favorites', this._onFavorites);
      this._onFavorites = null;
    }
    if (this._onMountChanged) {
      ZettEventBus.off('fm:refresh', this._onMountChanged);
      ZettEventBus.off('storage:mount_changed', this._onMountChanged);
      this._onMountChanged = null;
    }
  }

  async loadRoots() {
    try {
      const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';
      const res = await fetch('/api/fs/roots', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        this.roots = data.roots || [];
        this.array = data.array || null;
        this.remotes = data.remotes || [];
        this.pools = data.pools || [];
        this.special = data.special || [];
      }
    } catch (_) {
      this.roots = [];
      this.remotes = [];
      this.pools = [];
      this.special = [];
    }

    if (!this.roots.length) {
      this.roots = [
        { name: 'Array Shares', path: '/mnt/user', icon: '📁', is_dir: true },
        { name: 'Recycle Bin', path: '/mnt/user/.RecycleBin', icon: '🗑️', is_dir: true },
        { name: 'Cloud Remotes', path: '/mnt/remotes', icon: '☁️', is_dir: true },
      ];
    }
  }

  render() {
    if (!this.container) return;
    const treeScroll = this.container.querySelector('.fm-tree-scroll');
    if (!treeScroll) return;

    const isCloudActive = this.fm.currentPath === '/mnt/remotes';

    const getRemoteIcon = (type) => {
      const t = (type || '').toLowerCase();
      if (t === 'onedrive') return '☁️';
      if (t === 'drive' || t === 'google cloud storage') return '📁';
      if (t === 'dropbox') return '📦';
      if (t === 's3' || t === 'b2' || t === 'r2' || t === 'wasabi' || t === 'minio') return '🪣';
      if (t === 'webdav' || t === 'nextcloud' || t === 'owncloud') return '🌐';
      if (t === 'sftp' || t === 'ftp') return '🔒';
      if (t === 'smb' || t === 'cifs') return '🖥️';
      if (t === 'box') return '📦';
      if (t === 'pcloud') return '☁️';
      if (t === 'mega') return '🔴';
      return '☁️';
    };

    const mountedRemotes = (this.remotes || []).filter((r) => r.is_mounted !== false && r.available !== false);

    // UX-29: places are buttons with names in the person's language, built from where this
    // server keeps its files (Unraid's /mnt/user, or /mnt/storage, or the first browse root)
    const base = (this.array && this.array.path) || '/mnt/user';
    const onUnraid = base === '/mnt/user';
    const hasRoot = (p) => (this.roots || []).some((r) => (typeof r === 'string' ? r : r && r.path) === p);
    const place = (path, icon, label, active, cls = '', extra = '') => `
        <div class="fm-tree-item ${cls} ${active ? 'active' : ''}" data-path="${escapeHtml(path)}" role="button" tabindex="0"${active ? ' aria-current="true"' : ''} title="${escapeHtml(path)}"${extra}>
          <span class="fm-tree-icon" aria-hidden="true">${icon}</span>
          <span class="fm-tree-label">${escapeHtml(label)}</span>
        </div>`;
    const at = (p) => this.fm.currentPath === p;
    let html = `
      <div class="fm-tree-group">
        <div class="fm-tree-group-title">${t('fm.places', 'Places')}</div>
        ${place(base, '📁', t('fm.place_shares', 'Shared folders'), at(base))}
        ${onUnraid ? place('/mnt/user/appdata', '⚡', t('fm.place_appdata', 'App data'), at('/mnt/user/appdata')) : ''}
        ${onUnraid ? place('/mnt/user/system', '⚙️', t('fm.place_system', 'System files'), at('/mnt/user/system')) : ''}
        ${place(`${base}/.RecycleBin`, '🗑️', t('dock.recycle_bin', 'Recycle Bin'), this.fm.currentPath.includes('.RecycleBin'))}
      </div>

      ${favorites().length ? `
      <div class="fm-tree-group fm-tree-favorites" style="margin-top: 12px;">
        <div class="fm-tree-group-title">${t('fm.favorites', 'Favorites')}</div>
        ${favorites().map((f) => `
          <div class="fm-tree-item fm-fav-item ${this.fm.currentPath === f.path ? 'active' : ''}${f.available === false ? ' is-missing' : ''}" data-path="${escapeHtml(f.path)}" title="${escapeHtml(f.available === false ? t('fm.fav_missing', 'This folder is no longer available') : f.path)}">
            <span class="fm-tree-icon" aria-hidden="true">⭐</span>
            <span class="fm-tree-label" role="button" tabindex="0"${this.fm.currentPath === f.path ? ' aria-current="true"' : ''}>${escapeHtml(f.name)}</span>
            <button type="button" class="fm-fav-remove" data-fav-remove="${escapeHtml(f.path)}" title="${escapeHtml(t('fm.fav_remove', 'Remove from Favorites'))}" aria-label="${escapeHtml(t('fm.fav_remove', 'Remove from Favorites'))}: ${escapeHtml(f.name)}">✕</button>
          </div>`).join('')}
      </div>` : ''}

      <div class="fm-tree-group" style="margin-top: 12px;">
        <div class="fm-tree-group-title">${t('fm.storage_remotes', 'Storage and remotes')}</div>
        ${place('/mnt/remotes', '☁️', t('fm.cloud_mounts', 'Cloud folders'), isCloudActive)}
        ${mountedRemotes.map((r) => {
          const isRemoteActive = this.fm.currentPath === r.path || this.fm.currentPath.startsWith(r.path + '/');
          const icon = getRemoteIcon(r.type);
          return `
            <div class="fm-tree-item fm-tree-sub-item ${isRemoteActive ? 'active' : ''}" data-path="${escapeHtml(r.path)}" role="button" tabindex="0"${isRemoteActive ? ' aria-current="true"' : ''} style="padding-left: 24px;" title="${escapeHtml(r.name)} (${escapeHtml(r.type || 'cloud')})">
              <span class="fm-tree-icon" aria-hidden="true">${icon}</span>
              <span class="fm-tree-label">${escapeHtml(r.name)}</span>
            </div>
          `;
        }).join('')}
        ${(this.pools || []).map((p) => {
          const isPoolActive = this.fm.currentPath === p.path || this.fm.currentPath.startsWith(p.path + '/');
          const icon = p.type === 'disk' ? '💽' : '⚡';
          return `
            <div class="fm-tree-item ${isPoolActive ? 'active' : ''}" data-path="${escapeHtml(p.path)}" role="button" tabindex="0"${isPoolActive ? ' aria-current="true"' : ''} title="${escapeHtml(p.path)}">
              <span class="fm-tree-icon" aria-hidden="true">${icon}</span>
              <span class="fm-tree-label">${escapeHtml(p.name)}</span>
            </div>
          `;
        }).join('')}
        ${hasRoot('/boot') ? place('/boot', '💾', t('fm.place_boot', 'Boot drive'), at('/boot')) : ''}
      </div>
    `;

    treeScroll.innerHTML = html;

    // Click and Drag & Drop handlers for tree items
    treeScroll.querySelectorAll('[data-fav-remove]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeFavorite(btn.dataset.favRemove);
      });
    });

    treeScroll.querySelectorAll('.fm-tree-item').forEach((item) => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        const p = item.dataset.path;
        if (p) this.fm.loadPath(p);
      });

      item.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = (e.altKey || window._activeDragPayload?.action === 'copy') ? 'copy' : 'move';
        item.classList.add('fm-tree-drop-hover');
      });

      item.addEventListener('dragleave', (e) => {
        e.preventDefault();
        item.classList.remove('fm-tree-drop-hover');
      });

      item.addEventListener('drop', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        item.classList.remove('fm-tree-drop-hover');
        const targetPath = item.dataset.path;
        if (!targetPath) return;

        let payload = window._activeDragPayload || window.__zettActiveFmDrag;
        if (!payload || !payload.paths || payload.paths.length === 0) {
          try {
            const jsonStr = e.dataTransfer.getData('application/json');
            if (jsonStr) payload = JSON.parse(jsonStr);
          } catch (_) {}
        }
        if (!payload || !payload.paths || payload.paths.length === 0) {
          try {
            const text = e.dataTransfer.getData('text/plain');
            if (text) {
              const paths = text.split('\n').map((s) => s.trim()).filter(Boolean);
              if (paths.length > 0 && paths[0].startsWith('/')) {
                payload = { paths, action: e.altKey ? 'copy' : 'move' };
              }
            }
          } catch (_) {}
        }

        if (payload && payload.paths && payload.paths.length > 0) {
          const action = e.altKey ? 'copy' : (payload.action || 'move');
          if (targetPath.includes('.RecycleBin')) {
            if (typeof this.fm.handleAction === 'function') {
              for (const src of payload.paths) {
                const name = src.split('/').pop();
                await this.fm.handleAction('delete', src, name);
              }
            }
          } else {
            // executeTransferWithConflictCheck imported statically
            await executeTransferWithConflictCheck(payload.paths, targetPath, action);
          }
          window._activeDragPayload = null;
          window.__zettActiveFmDrag = null;
          ZettEventBus.emit('fm:refresh');
          return;
        }

        // External OS file drops on sidebar item
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          if (typeof this.fm.uploadFiles === 'function') {
            await this.fm.uploadFiles(e.dataTransfer.files, targetPath);
          }
        }
      });
    });
  }

  updateActive(currentPath) {
    if (!this.container) return;
    this.container.querySelectorAll('.fm-tree-item').forEach((item) => {
      const p = item.dataset.path;
      if (item.classList.contains('fm-tree-sub-item')) {
        if (p && (currentPath === p || currentPath.startsWith(p + '/'))) {
          item.classList.add('active');
        } else {
          item.classList.remove('active');
        }
      } else {
        if (p === currentPath) {
          item.classList.add('active');
        } else {
          item.classList.remove('active');
        }
      }
    });
  }
}

/**
 * 3. Right-Hand Metadata & Inspector Pane
 * Live previews, POSIX permissions, SHA-256 calculator, and spindown-safe folder size.
 */
export class FmInspector {
  constructor(fmWindow, containerEl) {
    this.fm = fmWindow;
    this.container = containerEl;
    this.isVisible = false;
    this.init();
  }

  init() {
    if (!this.container) return;
    const closeBtn = this.container.querySelector('.fm-inspector-close-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this.toggle(false));
    }
  }

  toggle(show = null) {
    this.isVisible = show !== null ? show : !this.isVisible;
    if (this.container) {
      this.container.style.display = this.isVisible ? 'flex' : 'none';
    }
    if (this.isVisible) this.update();
  }

  async update() {
    if (!this.container || !this.isVisible) return;
    const content = this.container.querySelector('.fm-inspector-content');
    if (!content) return;

    const count = this.fm.selectedPaths.size;
    const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';

    if (count === 0) {
      // Current folder info
      const folderName = this.fm.currentPath.split('/').filter(Boolean).pop() || 'Root';
      content.innerHTML = `
        <div style="text-align: center; padding: 16px 0;">
          <div style="font-size: 40px; margin-bottom: 8px;">📁</div>
          <div style="font-weight: 700; font-size: 13px; color: var(--fg); word-break: break-all;">${escapeHtml(folderName)}</div>
          <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-top: 4px;">${escapeHtml(this.fm.currentPath)}</div>
        </div>
        <div class="fm-inspector-section">
          <div class="fm-inspector-row"><span>Items:</span> <strong>${this.fm.fileList.length}</strong></div>
          <div class="fm-inspector-row"><span>Type:</span> <strong>Directory</strong></div>
        </div>
      `;
      return;
    }

    if (count > 1) {
      // Multi-selection summary
      let totalBytes = 0;
      let fileCount = 0;
      let dirCount = 0;
      this.fm.fileList.forEach((f) => {
        if (this.fm.selectedPaths.has(f.path)) {
          if (f.is_dir) dirCount++;
          else {
            fileCount++;
            totalBytes += f.size || 0;
          }
        }
      });

      content.innerHTML = `
        <div style="text-align: center; padding: 16px 0;">
          <div style="font-size: 40px; margin-bottom: 8px;">📦</div>
          <div style="font-weight: 700; font-size: 14px; color: var(--accent, var(--lt-t-0ea5e9ff, #0ea5e9));">${count} Items Selected</div>
          <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-top: 4px;">${formatBytes(totalBytes)} total</div>
        </div>
        <div class="fm-inspector-section">
          <div class="fm-inspector-row"><span>Files:</span> <strong>${fileCount}</strong></div>
          <div class="fm-inspector-row"><span>Folders:</span> <strong>${dirCount}</strong></div>
        </div>
      `;
      return;
    }

    // Exactly 1 item selected
    const selPath = Array.from(this.fm.selectedPaths)[0];
    const item = this.fm.fileList.find((f) => f.path === selPath);
    if (!item) return;

    const kind = thumbKind(item.name);
    const isImage = kind === 'image' || kind === 'vector' || kind === 'video';
    const isVideo = kind === 'video';
    const thumbUrl = kind === 'vector' ? `/api/fs/download?path=${encodeURIComponent(item.path)}` : previewUrl(item.path, 480);
    const isGuarded = isGuardedSystemDir(item.path);

    let previewHtml;
    if (item.is_dir) {
      previewHtml = '<div style="font-size: 48px; margin-bottom: 8px;">📁</div>';
    } else if (isImage) {
      const fallback = isVideo ? '🎬' : '🖼️';
      previewHtml = `<img src="${thumbUrl}" style="max-width: 100%; max-height: 140px; border-radius: 6px; object-fit: contain; box-shadow: 0 4px 12px rgba(0,0,0,0.5); margin-bottom: 8px;" alt="${escapeHtml(item.name)}" data-img-fallback="hide-show-next:block" /><div style="display:none; font-size: 48px; margin-bottom: 8px;">${fallback}</div>`;
    } else {
      previewHtml = '<div style="font-size: 48px; margin-bottom: 8px;">📄</div>';
    }

    const dateModified = formatDateTime(item.mtime);

    const tabsHeaderHtml = `
      <div class="fm-inspector-tabs" style="display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid var(--zn-line-8); padding-bottom: 6px;">
        <button type="button" class="btn-pill-toggle ${this.activeTab === 'details' ? 'active' : ''}" id="fm-insp-tab-details" style="flex: 1;">ℹ️ Info</button>
        <button type="button" class="btn-pill-toggle ${this.activeTab === 'permissions' ? 'active' : ''}" id="fm-insp-tab-perms" style="flex: 1;">🔒 Permissions</button>
      </div>
    `;

    if (this.activeTab === 'permissions') {
      content.innerHTML = `
        ${tabsHeaderHtml}
        <div class="fm-inspector-perms-pane" style="font-size: var(--zn-fs-xs);">
          <div style="font-weight: 700; color: var(--zn-text-strong); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
            <span>POSIX Access Control</span>
            <span id="fm-insp-perm-badge" style="font-family: monospace; font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; background: rgba(56,189,248,0.15); color: var(--zn-text-accent);">--</span>
          </div>

          ${isGuarded ? `
            <div class="fm-perm-guarded-banner" style="padding: 8px 10px; border-radius: 6px; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.3); color: var(--lt-t-fca5a5ff, #fca5a5); font-size: var(--zn-fs-xs); margin-bottom: 10px;">
              ⚠️ Protected system path. Permissions cannot be modified directly.
            </div>
          ` : ''}

          <div style="margin-bottom: 10px;">
            <label for="fm-insp-octal-input" style="display: block; font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 4px;">Octal Mode (e.g. 0755, 0644)</label>
            <div style="display: flex; gap: 6px;">
              <input type="text" id="fm-insp-octal-input" maxlength="4" placeholder="0755" value="${escapeHtml(item.mode || '0755')}" ${isGuarded ? 'disabled' : ''} style="flex: 1; padding: 5px 8px; font-family: monospace; font-size: var(--zn-fs-xs); background: var(--zn-shade-30); border: 1px solid var(--zn-line-15); border-radius: 5px; color: var(--zn-text-strong);" />
              <span id="fm-insp-human-mode" style="padding: 5px 8px; font-family: monospace; font-size: var(--zn-fs-xs); color: var(--zn-text-muted); background: var(--zn-shade-20); border-radius: 5px;">-rwxr-xr-x</span>
            </div>
          </div>

          <div class="fm-perms-grid" style="display: grid; grid-template-columns: 1fr repeat(3, 30px); gap: 4px; align-items: center; margin-bottom: 12px; font-size: var(--zn-fs-xs); text-align: center;">
            <div></div>
            <div style="color: var(--muted); font-weight: 700;">R</div>
            <div style="color: var(--muted); font-weight: 700;">W</div>
            <div style="color: var(--muted); font-weight: 700;">X</div>

            <div style="text-align: left; font-weight: 600; color: var(--zn-text-soft);">Owner</div>
            <input type="checkbox" id="fm-perm-ur" data-perm="256" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-uw" data-perm="128" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-ux" data-perm="64" ${isGuarded ? 'disabled' : ''} />

            <div style="text-align: left; font-weight: 600; color: var(--zn-text-soft);">Group</div>
            <input type="checkbox" id="fm-perm-gr" data-perm="32" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-gw" data-perm="16" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-gx" data-perm="8" ${isGuarded ? 'disabled' : ''} />

            <div style="text-align: left; font-weight: 600; color: var(--zn-text-soft);">Others</div>
            <input type="checkbox" id="fm-perm-or" data-perm="4" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-ow" data-perm="2" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-ox" data-perm="1" ${isGuarded ? 'disabled' : ''} />
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;">
            <div>
              <label for="fm-insp-owner-input" style="display: block; font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 4px;">User (Owner)</label>
              <input type="text" id="fm-insp-owner-input" placeholder="e.g. root" value="root" ${isGuarded ? 'disabled' : ''} style="width: 100%; box-sizing: border-box; padding: 5px 8px; font-size: var(--zn-fs-xs); background: var(--zn-shade-30); border: 1px solid var(--zn-line-15); border-radius: 5px; color: var(--zn-text-strong);" />
            </div>
            <div>
              <label for="fm-insp-group-input" style="display: block; font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 4px;">Group</label>
              <input type="text" id="fm-insp-group-input" placeholder="e.g. users" value="users" ${isGuarded ? 'disabled' : ''} style="width: 100%; box-sizing: border-box; padding: 5px 8px; font-size: var(--zn-fs-xs); background: var(--zn-shade-30); border: 1px solid var(--zn-line-15); border-radius: 5px; color: var(--zn-text-strong);" />
            </div>
          </div>

          ${item.is_dir ? `
            <div style="margin-bottom: 14px;">
              <label style="display: flex; align-items: center; gap: 6px; font-size: var(--zn-fs-xs); color: var(--zn-text-soft); cursor: pointer;">
                <input type="checkbox" id="fm-insp-recursive-chk" ${isGuarded ? 'disabled' : ''} />
                <span>Apply recursively to all subfolders & files</span>
              </label>
            </div>
          ` : ''}

          <button type="button" id="fm-insp-apply-perms-btn" class="btn-pill-toggle active" ${isGuarded ? `disabled title="${escapeHtml(t('fm.why_guarded', 'System folder: its permissions are protected'))}"` : ''} style="width: 100%; font-size: var(--zn-fs-xs); font-weight: 700; padding: 6px 12px; background: #0284c7; color: #fff;">
            Apply Permissions
          </button>
        </div>
      `;

      // Tab switcher
      const tabDetails = content.querySelector('#fm-insp-tab-details');
      if (tabDetails) {
        tabDetails.addEventListener('click', () => {
          this.activeTab = 'details';
          this.update();
        });
      }

      // Checkbox <-> Octal synchronization helper
      const octInput = content.querySelector('#fm-insp-octal-input');
      const humanLabel = content.querySelector('#fm-insp-human-mode');
      const badgeLabel = content.querySelector('#fm-insp-perm-badge');
      const chkUR = content.querySelector('#fm-perm-ur');
      const chkUW = content.querySelector('#fm-perm-uw');
      const chkUX = content.querySelector('#fm-perm-ux');
      const chkGR = content.querySelector('#fm-perm-gr');
      const chkGW = content.querySelector('#fm-perm-gw');
      const chkGX = content.querySelector('#fm-perm-gx');
      const chkOR = content.querySelector('#fm-perm-or');
      const chkOW = content.querySelector('#fm-perm-ow');
      const chkOX = content.querySelector('#fm-perm-ox');

      const syncChecksFromOctal = (octalStr) => {
        const val = parseInt(octalStr || '0755', 8) || 0;
        if (chkUR) chkUR.checked = Boolean(val & 0o400);
        if (chkUW) chkUW.checked = Boolean(val & 0o200);
        if (chkUX) chkUX.checked = Boolean(val & 0o100);
        if (chkGR) chkGR.checked = Boolean(val & 0o040);
        if (chkGW) chkGW.checked = Boolean(val & 0o020);
        if (chkGX) chkGX.checked = Boolean(val & 0o010);
        if (chkOR) chkOR.checked = Boolean(val & 0o004);
        if (chkOW) chkOW.checked = Boolean(val & 0o002);
        if (chkOX) chkOX.checked = Boolean(val & 0o001);

        const rwx = (d) => (d & 4 ? 'r' : '-') + (d & 2 ? 'w' : '-') + (d & 1 ? 'x' : '-');
        const u = ((chkUR?.checked ? 4 : 0) + (chkUW?.checked ? 2 : 0) + (chkUX?.checked ? 1 : 0));
        const g = ((chkGR?.checked ? 4 : 0) + (chkGW?.checked ? 2 : 0) + (chkGX?.checked ? 1 : 0));
        const o = ((chkOR?.checked ? 4 : 0) + (chkOW?.checked ? 2 : 0) + (chkOX?.checked ? 1 : 0));
        const human = (item.is_dir ? 'd' : '-') + rwx(u) + rwx(g) + rwx(o);
        if (humanLabel) humanLabel.textContent = human;
        if (badgeLabel) badgeLabel.textContent = `0${u}${g}${o}`;
      };

      const syncOctalFromChecks = () => {
        const u = (chkUR?.checked ? 4 : 0) + (chkUW?.checked ? 2 : 0) + (chkUX?.checked ? 1 : 0);
        const g = (chkGR?.checked ? 4 : 0) + (chkGW?.checked ? 2 : 0) + (chkGX?.checked ? 1 : 0);
        const o = (chkOR?.checked ? 4 : 0) + (chkOW?.checked ? 2 : 0) + (chkOX?.checked ? 1 : 0);
        const octStr = `0${u}${g}${o}`;
        if (octInput) octInput.value = octStr;
        if (badgeLabel) badgeLabel.textContent = octStr;
        const rwx = (d) => (d & 4 ? 'r' : '-') + (d & 2 ? 'w' : '-') + (d & 1 ? 'x' : '-');
        if (humanLabel) humanLabel.textContent = (item.is_dir ? 'd' : '-') + rwx(u) + rwx(g) + rwx(o);
      };

      [chkUR, chkUW, chkUX, chkGR, chkGW, chkGX, chkOR, chkOW, chkOX].forEach((chk) => {
        if (chk) chk.addEventListener('change', syncOctalFromChecks);
      });

      if (octInput) {
        octInput.addEventListener('input', () => syncChecksFromOctal(octInput.value));
      }

      // Load initial permissions from backend
      try {
        const pRes = await fetch(`/api/fs/permissions?path=${encodeURIComponent(item.path)}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (pRes.ok) {
          const pData = await pRes.json();
          if (octInput) octInput.value = pData.mode_octal || '0755';
          const ownerIn = content.querySelector('#fm-insp-owner-input');
          const groupIn = content.querySelector('#fm-insp-group-input');
          if (ownerIn) ownerIn.value = pData.owner || 'root';
          if (groupIn) groupIn.value = pData.group || 'users';
          syncChecksFromOctal(pData.mode_octal || '0755');
        } else {
          syncChecksFromOctal(item.mode || '0755');
        }
      } catch (_) {
        syncChecksFromOctal(item.mode || '0755');
      }

      // Apply changes handler
      const applyBtn = content.querySelector('#fm-insp-apply-perms-btn');
      if (applyBtn) {
        applyBtn.addEventListener('click', async () => {
          if (isGuarded) {
            showToast(t('toast.modifying_permissions_on_system_roots_is', 'Modifying permissions on system roots is forbidden'), 'error');
            return;
          }
          applyBtn.disabled = true;
          applyBtn.textContent = t('ui.applying', 'Applying...');
          const modeVal = octInput ? octInput.value.trim() : '0755';
          const ownerVal = content.querySelector('#fm-insp-owner-input')?.value.trim() || null;
          const groupVal = content.querySelector('#fm-insp-group-input')?.value.trim() || null;
          const isRecursive = Boolean(content.querySelector('#fm-insp-recursive-chk')?.checked);

          try {
            await api.put('/api/fs/permissions', {
              path: item.path,
              mode_octal: modeVal,
              owner: ownerVal,
              group: groupVal,
              recursive: isRecursive,
            });
            item.mode = modeVal;
            showToast(t('toast.permissions_updated_successfully', 'Permissions updated successfully!'), 'success');
            applyBtn.textContent = t('ui.applied', 'Applied ✓');
            setTimeout(() => {
              applyBtn.disabled = false;
              applyBtn.textContent = t('ui.apply_permissions', 'Apply Permissions');
            }, 1400);
          } catch (err) {
            showToast(t('toast.failed_updating_permissions', 'Failed updating permissions: {error}', { error: err.message }), 'error');
            applyBtn.disabled = false;
            applyBtn.textContent = t('ui.apply_permissions', 'Apply Permissions');
          }
        });
      }
      return;
    }

    // Default Details / Info tab
    content.innerHTML = `
      ${tabsHeaderHtml}
      <div style="text-align: center; padding: 8px 0 14px;">
        ${previewHtml}
        <div style="font-weight: 700; font-size: 13px; color: var(--fg); word-break: break-all;">${escapeHtml(item.name)}</div>
        <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-top: 4px;">${item.is_dir ? 'Directory' : formatBytes(item.size)}</div>
      </div>

      <div class="fm-inspector-section">
        <div class="fm-inspector-row"><span>Modified:</span> <span>${dateModified}</span></div>
        <div class="fm-inspector-row"><span>Mode:</span> <span id="fm-insp-mode">${item.mode || '--'}</span></div>
        <div class="fm-inspector-row"><span>Owner:</span> <span id="fm-insp-owner">Loading...</span></div>
        ${isVideo ? '<div id="fm-insp-media" class="fm-inspector-media" aria-live="polite"></div>' : ''}
        <button type="button" id="fm-insp-go-perms-btn" class="btn-pill-toggle is-block is-small" style="margin-top: 8px;">🔒 Edit Permissions & Mode</button>
      </div>

      ${!item.is_dir ? `
        <div class="fm-inspector-section" style="margin-top: 10px;">
          <div style="font-size: var(--zn-fs-xs); font-weight: 600; color: var(--muted); margin-bottom: 6px;">Integrity (SHA-256)</div>
          <button type="button" id="fm-btn-calc-sha" class="btn-pill-toggle is-block">Compute Checksum</button>
          <div id="fm-insp-sha-result" style="font-family: monospace; font-size: var(--zn-fs-xs); word-break: break-all; margin-top: 6px; color: var(--accent); display: none;"></div>
        </div>
      ` : `
        <div class="fm-inspector-section" style="margin-top: 10px;">
          <div style="font-size: var(--zn-fs-xs); font-weight: 600; color: var(--muted); margin-bottom: 6px;">Folder Size</div>
          <button type="button" id="fm-btn-calc-folder-sz" class="btn-pill-toggle is-block">Calculate Disk Usage</button>
          <div id="fm-insp-folder-sz-res" style="font-size: var(--zn-fs-xs); margin-top: 6px; color: var(--fg); display: none;"></div>
        </div>
      `}

      <div class="fm-inspector-actions" style="margin-top: 16px; display: flex; flex-direction: column; gap: 6px;">
        ${!item.is_dir ? `<button type="button" id="fm-insp-preview-btn" class="btn-pill-toggle is-block">QuickLook Preview (Space)</button>` : ''}
        ${!item.is_dir ? `<button type="button" id="fm-insp-download-btn" class="btn-pill-toggle is-block">Download File</button>` : ''}
      </div>
    `;

    // Tab switcher listeners
    const tabPerms = content.querySelector('#fm-insp-tab-perms');
    if (tabPerms) {
      tabPerms.addEventListener('click', () => {
        this.activeTab = 'permissions';
        this.update();
      });
    }
    const goPermsBtn = content.querySelector('#fm-insp-go-perms-btn');
    if (goPermsBtn) {
      goPermsBtn.addEventListener('click', () => {
        this.activeTab = 'permissions';
        this.update();
      });
    }

    // Video details: duration, resolution, codecs, and whether this browser plays it as is
    const mediaEl = content.querySelector('#fm-insp-media');
    if (mediaEl) {
      api.get(mediaInfoUrl(item.path)).then((info) => {
        if (!mediaEl.isConnected) return;
        mediaEl.replaceChildren(...describeMedia(info, canPlayHere(info, item.name)).map(([label, value]) => {
          const row = document.createElement('div');
          row.className = 'fm-inspector-row';
          row.append(Object.assign(document.createElement('span'), { textContent: `${label}:` }), ' ', Object.assign(document.createElement('span'), { textContent: value }));
          return row;
        }));
      }).catch((err) => console.warn('Video details unavailable:', err));
    }

    // Fetch POSIX permissions
    try {
      const pRes = await fetch(`/api/fs/permissions?path=${encodeURIComponent(item.path)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (pRes.ok) {
        const pData = await pRes.json();
        const modeEl = content.querySelector('#fm-insp-mode');
        const ownerEl = content.querySelector('#fm-insp-owner');
        if (modeEl) modeEl.textContent = `${pData.mode_octal} (${pData.mode_human})`;
        if (ownerEl) ownerEl.textContent = `${pData.owner}:${pData.group}`;
      }
    } catch (_) {}

    // Checksum calculator button
    const shaBtn = content.querySelector('#fm-btn-calc-sha');
    if (shaBtn) {
      shaBtn.addEventListener('click', async () => {
        shaBtn.textContent = t('ui.calculating', 'Calculating...');
        shaBtn.disabled = true;
        try {
          const cRes = await fetch('/api/fs/checksum', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ path: item.path, algorithm: 'sha256' }),
          });
          if (cRes.ok) {
            const cData = await cRes.json();
            const resEl = content.querySelector('#fm-insp-sha-result');
            if (resEl) {
              resEl.textContent = cData.checksum;
              resEl.style.display = 'block';
            }
            shaBtn.textContent = t('ui.computed', 'Computed ✓');
          } else {
            shaBtn.textContent = t('ui.error', 'Error');
          }
        } catch (_) {
          shaBtn.textContent = t('jobs.status_error', 'Failed');
        }
      });
    }

    // Folder size calculator (Spindown-Safe)
    const fldrSzBtn = content.querySelector('#fm-btn-calc-folder-sz');
    if (fldrSzBtn) {
      fldrSzBtn.addEventListener('click', async () => {
        fldrSzBtn.textContent = t('ui.scanning', 'Scanning...');
        fldrSzBtn.disabled = true;
        try {
          const sRes = await fetch('/api/fs/folder-size', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ path: item.path, force_wake: false }),
          });
          if (sRes.ok) {
            const sData = await sRes.json();
            const szEl = content.querySelector('#fm-insp-folder-sz-res');
            if (szEl) {
              if (sData.is_standby) {
                szEl.innerHTML = `<span style="color: var(--lt-t-eab308ff, #eab308);">💤 Drive in Standby</span><br><span style="font-size:var(--zn-fs-xs); color:var(--muted);">Calculation deferred (0 wakeups)</span>`;
              } else {
                szEl.textContent = `${formatBytes(sData.size)} (${sData.files_count} files, ${sData.dirs_count} folders)`;
              }
              szEl.style.display = 'block';
            }
            fldrSzBtn.textContent = t('ui.refreshed', 'Refreshed ✓');
          }
        } catch (_) {
          fldrSzBtn.textContent = t('jobs.status_error', 'Failed');
        }
      });
    }

    // QuickLook & download
    const prevBtn = content.querySelector('#fm-insp-preview-btn');
    if (prevBtn) {
      prevBtn.addEventListener('click', () => openFilePreviewModal(item.path, item.name));
    }
    const dlBtn = content.querySelector('#fm-insp-download-btn');
    if (dlBtn) {
      dlBtn.addEventListener('click', () => {
        const url = `/api/fs/download?path=${encodeURIComponent(item.path)}`;
        window.open(url, '_blank');
      });
    }
  }
}

/**
 * 4. Transfers panel for one explorer window: all windows share transfer-center.js.
 */
export class FmTransfersCockpit {
  constructor(fmWindow) {
    this.fm = fmWindow;
    transferCenter.connect();
    transferCenter.ensureDom();
  }

  createCockpitDOM() {
    transferCenter.ensureDom();
  }

  get isOpen() {
    return transferCenter.isOpen;
  }

  toggle(show = null) {
    return transferCenter.toggle(show);
  }

  render() {
    transferCenter.render();
  }
}

/**
 * 5. Glassmorphic Context Menu with Viewport Boundary Clamping
 */
export class FmContextMenu {
  constructor(fmWindow) {
    this.fm = fmWindow;
    this.menuEl = null;
    this.targetItem = null;
    /** @type {HTMLElement | null} where focus goes back to when the menu closes */
    this._returnFocus = null;
    this.init();
  }

  init() {
    let el = document.getElementById('fm-context-menu');
    if (!el) {
      const html = `<div id="fm-context-menu" class="fm-context-menu" role="menu" style="display: none; position: fixed; z-index: 99999;"></div>`;
      document.body.insertAdjacentHTML('beforeend', html);
      el = document.getElementById('fm-context-menu');
    }
    this.menuEl = el;

    document.addEventListener('click', () => this.hide());
    // Any press outside the menu closes it: dragging a window never produces a click
    document.addEventListener('pointerdown', (e) => {
      if (this.menuEl && !this.menuEl.contains(e.target)) this.hide();
    }, true);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.hide();
    });
    el.addEventListener('keydown', (e) => onMenuKeys(el, e, () => this.hide()));
    window.addEventListener('blur', () => this.hide());
    window.addEventListener('resize', () => this.hide());
  }

  show(e, fileItem = null) {
    e.preventDefault();
    e.stopPropagation();
    this.targetItem = fileItem;

    const hasSelection = this.fm.selectedPaths.size > 0;
    const isSingle = this.fm.selectedPaths.size === 1;
    const isDir = fileItem && fileItem.is_dir;
    const isZip = fileItem && fileItem.name && fileItem.name.match(/\.(zip|tar|tar\.gz|tgz)$/i);

    const mod = modKey();
    const it = ctxItem;
    const group = (rows) => `<div class="fm-ctx-group" role="group">${rows.filter(Boolean).join('')}</div>`;
    const line = '<div class="fm-ctx-divider" role="separator"></div>';
    const fav = (here) => {
      const on = isFavorite(here ? this.fm.currentPath : fileItem.path);
      const label = here
        ? (on ? t('fm.fav_remove_here', 'Remove this folder from Favorites') : t('fm.fav_add_here', 'Add this folder to Favorites'))
        : (on ? t('fm.fav_remove', 'Remove from Favorites') : t('fm.fav_add', 'Add to Favorites'));
      return it(here ? 'fav-toggle-here' : 'fav-toggle', on ? '☆' : '⭐', label);
    };
    // every label in the person's language, keys as their keyboard has them (NUX-7)
    let itemsHtml = [
      group([
        fileItem && !isDir && it('preview', '👁️', t('fm.ctx_preview', 'Quick look'), t('fm.kbd_space', 'Space')),
        fileItem && isDir && it('open', '📂', t('fm.ctx_open', 'Open'), t('fm.kbd_enter', 'Enter')),
        fileItem && fileItem.trash_id && it('restore', '↩️', t('fm.restore', 'Restore')),
        it('new-window', '🪟', t('fm.ctx_new_window', 'Open in a new window')),
      ]),
      line,
      group([
        hasSelection && it('cut', '✂️', t('fm.ctx_cut', 'Cut'), `${mod}+X`),
        hasSelection && it('copy', '📋', t('fm.ctx_copy', 'Copy'), `${mod}+C`),
        it('paste', '📥', t('fm.ctx_paste', 'Paste'), `${mod}+V`),
        hasSelection && it('duplicate', '📄', t('fm.ctx_duplicate', 'Duplicate'), `${mod}+D`),
        isSingle && it('rename', '✏️', t('fm.ctx_rename', 'Rename'), 'F2'),
      ]),
      line,
      group([
        hasSelection && it('archive-create', '🗜️', t('fm.ctx_zip', 'Compress to a .zip file')),
        isZip && it('archive-extract', '📦', t('fm.ctx_unzip', 'Extract here')),
        isSingle && it('share', '🔗', t('fm.ctx_share', 'Share a link…')),
        isSingle && !isDir && it('checksum', '🛡️', t('fm.ctx_checksum', 'Show its SHA-256 checksum')),
        isSingle && !isDir && it('versions', '🕘', t('fm.versions_menu', 'Previous versions…')),
        isSingle && it('ask-zetty', '✨', t('fm.ask_zetty', 'Ask Zetty about this')),
        isSingle && isDir && fav(false),
        !fileItem && fav(true),
      ]),
      !fileItem ? `${line}${sortMenuHtml(this.fm.currentSortBy, this.fm.currentSortDir)}` : '',
      line,
      group([
        hasSelection && it('trash', '🗑️', t('fm.ctx_to_bin', 'Move to the Recycle Bin'), t('fm.kbd_delete', 'Delete'), 'text-danger'),
        hasSelection && it('delete-perm', '⚠️', t('fm.ctx_delete_forever', 'Delete permanently'), t('fm.kbd_shift_delete', 'Shift+Delete'), 'text-danger'),
      ]),
    ].join('');
    this._returnFocus = /** @type {HTMLElement | null} */ (document.activeElement);

    this.menuEl.innerHTML = itemsHtml;
    this.menuEl.style.display = 'block';

    // Viewport edge clamping
    const menuWidth = this.menuEl.offsetWidth || 220; // sized to its longest row
    const menuHeight = this.menuEl.offsetHeight || 300;
    let left = e.clientX;
    let top = e.clientY;

    if (left + menuWidth > window.innerWidth - 10) {
      left = Math.max(10, window.innerWidth - menuWidth - 10);
    }
    if (top + menuHeight > window.innerHeight - 10) {
      top = Math.max(10, window.innerHeight - menuHeight - 10);
    }

    this.menuEl.style.left = `${left}px`;
    this.menuEl.style.top = `${top}px`;
    const first = /** @type {HTMLElement | null} */ (this.menuEl.querySelector('[role="menuitem"], [role="menuitemradio"]'));
    if (first) first.focus(); // a menu opened with Shift+F10 or the menu key is used by keyboard

    // Click handler for menu actions
    this.menuEl.querySelectorAll('.fm-ctx-item').forEach((item) => {
      item.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.hide();
        this.handleAction(item.dataset.act);
      });
    });
  }

  hide() {
    if (!this.menuEl || this.menuEl.style.display === 'none') return;
    this.menuEl.style.display = 'none';
    const back = this._returnFocus;
    this._returnFocus = null;
    if (back && typeof back.focus === 'function' && document.contains(back)) back.focus();
  }

  handleAction(act) {
    if (!act) return;
    const item = this.targetItem;
    const paths = Array.from(this.fm.selectedPaths);

    switch (act) {
      case 'preview':
        if (item) openFilePreviewModal(item.path, item.name);
        break;
      case 'open':
        if (item && item.is_dir) this.fm.loadPath(item.path);
        break;
      case 'restore':
        this.fm.restoreFromBin(paths.length ? paths : [item?.path].filter(Boolean));
        break;
      case 'sort-name':
      case 'sort-size':
      case 'sort-type':
      case 'sort-mtime':
        this.fm.setSort(act.slice(5), this.fm.currentSortDir);
        break;
      case 'sort-asc':
      case 'sort-desc':
        this.fm.setSort(this.fm.currentSortBy, act.slice(5));
        break;
      case 'new-window':
        window.openNewFileManagerWindow?.(item && item.is_dir ? item.path : this.fm.currentPath);
        break;
      case 'cut':
        this.fm.handleClipboardAction('move');
        break;
      case 'copy':
        this.fm.handleClipboardAction('copy');
        break;
      case 'paste':
        this.fm.handlePaste();
        break;
      case 'duplicate':
        this.fm.duplicateSelected();
        break;
      case 'rename':
        if (item) this.fm.triggerRename(item);
        break;
      case 'archive-create':
        this.fm.createArchive(paths);
        break;
      case 'archive-extract':
        if (item) this.fm.extractArchive(item.path);
        break;
      case 'share':
        if (item) this.fm.handleAction('share', item.path, item.name);
        break;
      case 'checksum':
        if (item) {
          if (this.fm.inspector) {
            this.fm.inspector.toggle(true);
            setTimeout(() => {
              const btn = document.getElementById('fm-btn-calc-sha');
              if (btn) btn.click();
            }, 100);
          }
        }
        break;
      case 'versions':
        if (item) {
          import('./file-versions.js').then((m) => m.openPreviousVersions(item.path, item.name, () => this.fm.loadPath(this.fm.currentPath)));
        }
        break;
      case 'ask-zetty':
        if (item) window.askZettyAbout?.(item.path, item.name);
        break;
      case 'fav-toggle':
        if (item && item.is_dir) toggleFavorite(item.path, item.name);
        break;
      case 'fav-toggle-here':
        toggleFavorite(this.fm.currentPath);
        break;
      case 'trash':
        this.fm.bulkDelete();
        break;
      case 'delete-perm':
        this.fm.bulkDelete(true);
        break;
    }
  }
}

/**
 * 6. Batch Draining OS Recursive Directory Extractor
 * Prevents Chromium's 100-item cutoff using while(true) loop on readEntries().
 */
export async function extractDataTransferEntries(dataTransfer) {
  const filesToUpload = []; // { file, relPath }
  const items = dataTransfer.items;
  if (!items) return filesToUpload;

  async function scanEntry(entry, path = '') {
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      filesToUpload.push({ file, relPath: path ? `${path}/${file.name}` : file.name });
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      const currentPath = path ? `${path}/${entry.name}` : entry.name;
      while (true) {
        const batch = await new Promise((res, rej) => dirReader.readEntries(res, rej));
        if (!batch || batch.length === 0) break;
        for (const child of batch) {
          await scanEntry(child, currentPath);
        }
      }
    }
  }

  const promises = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (item.webkitGetAsEntry) {
      const entry = item.webkitGetAsEntry();
      if (entry) promises.push(scanEntry(entry));
    } else if (item.kind === 'file') {
      const f = item.getAsFile();
      if (f) filesToUpload.push({ file: f, relPath: f.name });
    }
  }
  await Promise.all(promises);
  return filesToUpload;
}
