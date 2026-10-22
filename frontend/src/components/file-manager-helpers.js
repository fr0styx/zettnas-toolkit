/**
 * ZettNAS Toolkit - SOTA File Explorer Auxiliary Engines
 * Handles 2D Canvas Marquee Selection, 3-Pane Sidebar Tree, Metadata Inspector,
 * Popover Context Menu with Viewport Boundary Clamping, and Transfer Queue Cockpit.
 */

import { t } from '../i18n.js';
import { escapeHtml, copyTextToClipboard } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { formatBytes, executeTransferWithConflictCheck } from './file-manager.js';
import { openFilePreviewModal } from './file-preview-modal.js';
import { auth, api } from '../api.js';
import { thumbKind, previewUrl } from './viewer-kit.js';
import { canPlayHere, describeMedia, mediaInfoUrl } from './media-support.js';
import { showToast } from '../toast.js';

import { formatDateTime } from '../format.js';
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
    ZettEventBus.on('fm:refresh', this._onMountChanged);
    ZettEventBus.on('storage:mount_changed', this._onMountChanged);
    this.init();
  }

  async init() {
    if (!this.container) return;
    await this.loadRoots();
    this.render();
  }

  async refresh() {
    await this.loadRoots();
    this.render();
    this.updateActive(this.fm.currentPath);
  }

  destroy() {
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

    let html = `
      <div class="fm-tree-group">
        <div class="fm-tree-group-title">${t('fm.places', 'Places')}</div>
        <div class="fm-tree-item ${this.fm.currentPath === '/mnt/user' ? 'active' : ''}" data-path="/mnt/user">
          <span class="fm-tree-icon">📁</span>
          <span class="fm-tree-label">User Shares</span>
        </div>
        <div class="fm-tree-item ${this.fm.currentPath === '/mnt/user/appdata' ? 'active' : ''}" data-path="/mnt/user/appdata">
          <span class="fm-tree-icon">⚡</span>
          <span class="fm-tree-label">AppData</span>
        </div>
        <div class="fm-tree-item ${this.fm.currentPath === '/mnt/user/system' ? 'active' : ''}" data-path="/mnt/user/system">
          <span class="fm-tree-icon">⚙️</span>
          <span class="fm-tree-label">System</span>
        </div>
        <div class="fm-tree-item ${this.fm.currentPath.includes('.RecycleBin') ? 'active' : ''}" data-path="/mnt/user/.RecycleBin">
          <span class="fm-tree-icon">🗑️</span>
          <span class="fm-tree-label">${t('fm.empty_trash', 'Recycle Bin')}</span>
        </div>
      </div>

      <div class="fm-tree-group" style="margin-top: 12px;">
        <div class="fm-tree-group-title">Storage & Remotes</div>
        <div class="fm-tree-item ${isCloudActive ? 'active' : ''}" data-path="/mnt/remotes">
          <span class="fm-tree-icon">☁️</span>
          <span class="fm-tree-label">Cloud Mounts</span>
        </div>
        ${mountedRemotes.map((r) => {
          const isRemoteActive = this.fm.currentPath === r.path || this.fm.currentPath.startsWith(r.path + '/');
          const icon = getRemoteIcon(r.type);
          return `
            <div class="fm-tree-item fm-tree-sub-item ${isRemoteActive ? 'active' : ''}" data-path="${escapeHtml(r.path)}" style="padding-left: 24px;" title="${escapeHtml(r.name)} (${escapeHtml(r.type || 'cloud')})">
              <span class="fm-tree-icon">${icon}</span>
              <span class="fm-tree-label">${escapeHtml(r.name)}</span>
            </div>
          `;
        }).join('')}
        ${(this.pools || []).map((p) => {
          const isPoolActive = this.fm.currentPath === p.path || this.fm.currentPath.startsWith(p.path + '/');
          const icon = p.type === 'disk' ? '💽' : '⚡';
          return `
            <div class="fm-tree-item ${isPoolActive ? 'active' : ''}" data-path="${escapeHtml(p.path)}" title="${escapeHtml(p.path)}">
              <span class="fm-tree-icon">${icon}</span>
              <span class="fm-tree-label">${escapeHtml(p.name)}</span>
            </div>
          `;
        }).join('')}
        <div class="fm-tree-item ${this.fm.currentPath === '/boot' ? 'active' : ''}" data-path="/boot">
          <span class="fm-tree-icon">💾</span>
          <span class="fm-tree-label">Flash Boot</span>
        </div>
      </div>
    `;

    treeScroll.innerHTML = html;

    // Click and Drag & Drop handlers for tree items
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
          <div style="font-size: 11px; color: var(--muted); margin-top: 4px;">${escapeHtml(this.fm.currentPath)}</div>
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
          <div style="font-weight: 700; font-size: 14px; color: var(--accent, #0ea5e9);">${count} Items Selected</div>
          <div style="font-size: 11px; color: var(--muted); margin-top: 4px;">${formatBytes(totalBytes)} total</div>
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
      <div class="fm-inspector-tabs" style="display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 6px;">
        <button type="button" class="btn-pill-toggle ${this.activeTab === 'details' ? 'active' : ''}" id="fm-insp-tab-details" style="flex: 1; font-size: 11px; padding: 4px 6px;">ℹ️ Info</button>
        <button type="button" class="btn-pill-toggle ${this.activeTab === 'permissions' ? 'active' : ''}" id="fm-insp-tab-perms" style="flex: 1; font-size: 11px; padding: 4px 6px;">🔒 Permissions</button>
      </div>
    `;

    if (this.activeTab === 'permissions') {
      content.innerHTML = `
        ${tabsHeaderHtml}
        <div class="fm-inspector-perms-pane" style="font-size: 11.5px;">
          <div style="font-weight: 700; color: #fff; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
            <span>POSIX Access Control</span>
            <span id="fm-insp-perm-badge" style="font-family: monospace; font-size: 11px; padding: 2px 6px; border-radius: 4px; background: rgba(56,189,248,0.15); color: #38bdf8;">--</span>
          </div>

          ${isGuarded ? `
            <div class="fm-perm-guarded-banner" style="padding: 8px 10px; border-radius: 6px; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.3); color: #fca5a5; font-size: 11px; margin-bottom: 10px;">
              ⚠️ Protected system path. Permissions cannot be modified directly.
            </div>
          ` : ''}

          <div style="margin-bottom: 10px;">
            <label style="display: block; font-size: 11px; color: var(--muted); margin-bottom: 4px;">Octal Mode (e.g. 0755, 0644)</label>
            <div style="display: flex; gap: 6px;">
              <input type="text" id="fm-insp-octal-input" maxlength="4" placeholder="0755" value="${escapeHtml(item.mode || '0755')}" ${isGuarded ? 'disabled' : ''} style="flex: 1; padding: 5px 8px; font-family: monospace; font-size: 11px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.15); border-radius: 5px; color: #fff;" />
              <span id="fm-insp-human-mode" style="padding: 5px 8px; font-family: monospace; font-size: 11px; color: #94a3b8; background: rgba(0,0,0,0.2); border-radius: 5px;">-rwxr-xr-x</span>
            </div>
          </div>

          <div class="fm-perms-grid" style="display: grid; grid-template-columns: 1fr repeat(3, 30px); gap: 4px; align-items: center; margin-bottom: 12px; font-size: 11px; text-align: center;">
            <div></div>
            <div style="color: var(--muted); font-weight: 700;">R</div>
            <div style="color: var(--muted); font-weight: 700;">W</div>
            <div style="color: var(--muted); font-weight: 700;">X</div>

            <div style="text-align: left; font-weight: 600; color: #cbd5e1;">Owner</div>
            <input type="checkbox" id="fm-perm-ur" data-perm="256" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-uw" data-perm="128" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-ux" data-perm="64" ${isGuarded ? 'disabled' : ''} />

            <div style="text-align: left; font-weight: 600; color: #cbd5e1;">Group</div>
            <input type="checkbox" id="fm-perm-gr" data-perm="32" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-gw" data-perm="16" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-gx" data-perm="8" ${isGuarded ? 'disabled' : ''} />

            <div style="text-align: left; font-weight: 600; color: #cbd5e1;">Others</div>
            <input type="checkbox" id="fm-perm-or" data-perm="4" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-ow" data-perm="2" ${isGuarded ? 'disabled' : ''} />
            <input type="checkbox" id="fm-perm-ox" data-perm="1" ${isGuarded ? 'disabled' : ''} />
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;">
            <div>
              <label style="display: block; font-size: 11px; color: var(--muted); margin-bottom: 4px;">User (Owner)</label>
              <input type="text" id="fm-insp-owner-input" placeholder="e.g. root" value="root" ${isGuarded ? 'disabled' : ''} style="width: 100%; box-sizing: border-box; padding: 5px 8px; font-size: 11px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.15); border-radius: 5px; color: #fff;" />
            </div>
            <div>
              <label style="display: block; font-size: 11px; color: var(--muted); margin-bottom: 4px;">Group</label>
              <input type="text" id="fm-insp-group-input" placeholder="e.g. users" value="users" ${isGuarded ? 'disabled' : ''} style="width: 100%; box-sizing: border-box; padding: 5px 8px; font-size: 11px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.15); border-radius: 5px; color: #fff;" />
            </div>
          </div>

          ${item.is_dir ? `
            <div style="margin-bottom: 14px;">
              <label style="display: flex; align-items: center; gap: 6px; font-size: 11px; color: #cbd5e1; cursor: pointer;">
                <input type="checkbox" id="fm-insp-recursive-chk" ${isGuarded ? 'disabled' : ''} />
                <span>Apply recursively to all subfolders & files</span>
              </label>
            </div>
          ` : ''}

          <button type="button" id="fm-insp-apply-perms-btn" class="btn-pill-toggle active" ${isGuarded ? 'disabled' : ''} style="width: 100%; font-size: 11.5px; font-weight: 700; padding: 6px 12px; background: #0284c7; color: #fff;">
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
          applyBtn.textContent = 'Applying...';
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
            applyBtn.textContent = 'Applied ✓';
            setTimeout(() => {
              applyBtn.disabled = false;
              applyBtn.textContent = 'Apply Permissions';
            }, 1400);
          } catch (err) {
            showToast(t('toast.failed_updating_permissions', 'Failed updating permissions: {error}', { error: err.message }), 'error');
            applyBtn.disabled = false;
            applyBtn.textContent = 'Apply Permissions';
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
        <div style="font-size: 11px; color: var(--muted); margin-top: 4px;">${item.is_dir ? 'Directory' : formatBytes(item.size)}</div>
      </div>

      <div class="fm-inspector-section">
        <div class="fm-inspector-row"><span>Modified:</span> <span>${dateModified}</span></div>
        <div class="fm-inspector-row"><span>Mode:</span> <span id="fm-insp-mode">${item.mode || '--'}</span></div>
        <div class="fm-inspector-row"><span>Owner:</span> <span id="fm-insp-owner">Loading...</span></div>
        ${isVideo ? '<div id="fm-insp-media" class="fm-inspector-media" aria-live="polite"></div>' : ''}
        <button type="button" id="fm-insp-go-perms-btn" class="btn-pill-toggle" style="width: 100%; font-size: 11px; padding: 3px 8px; margin-top: 8px;">🔒 Edit Permissions & Mode</button>
      </div>

      ${!item.is_dir ? `
        <div class="fm-inspector-section" style="margin-top: 10px;">
          <div style="font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 6px;">Integrity (SHA-256)</div>
          <button type="button" id="fm-btn-calc-sha" class="btn-pill-toggle" style="width: 100%; font-size: 11px; padding: 4px 8px;">Compute Checksum</button>
          <div id="fm-insp-sha-result" style="font-family: monospace; font-size: 11px; word-break: break-all; margin-top: 6px; color: var(--accent); display: none;"></div>
        </div>
      ` : `
        <div class="fm-inspector-section" style="margin-top: 10px;">
          <div style="font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 6px;">Folder Size</div>
          <button type="button" id="fm-btn-calc-folder-sz" class="btn-pill-toggle" style="width: 100%; font-size: 11px; padding: 4px 8px;">Calculate Disk Usage</button>
          <div id="fm-insp-folder-sz-res" style="font-size: 11px; margin-top: 6px; color: var(--fg); display: none;"></div>
        </div>
      `}

      <div class="fm-inspector-actions" style="margin-top: 16px; display: flex; flex-direction: column; gap: 6px;">
        ${!item.is_dir ? `<button type="button" id="fm-insp-preview-btn" class="btn-pill-toggle" style="width: 100%;">QuickLook Preview (Space)</button>` : ''}
        ${!item.is_dir ? `<button type="button" id="fm-insp-download-btn" class="btn-pill-toggle" style="width: 100%;">Download File</button>` : ''}
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
        shaBtn.textContent = 'Calculating...';
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
            shaBtn.textContent = 'Computed ✓';
          } else {
            shaBtn.textContent = 'Error';
          }
        } catch (_) {
          shaBtn.textContent = 'Failed';
        }
      });
    }

    // Folder size calculator (Spindown-Safe)
    const fldrSzBtn = content.querySelector('#fm-btn-calc-folder-sz');
    if (fldrSzBtn) {
      fldrSzBtn.addEventListener('click', async () => {
        fldrSzBtn.textContent = 'Scanning...';
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
                szEl.innerHTML = `<span style="color: #eab308;">💤 Drive in Standby</span><br><span style="font-size:11px; color:var(--muted);">Calculation deferred (0 wakeups)</span>`;
              } else {
                szEl.textContent = `${formatBytes(sData.size)} (${sData.files_count} files, ${sData.dirs_count} folders)`;
              }
              szEl.style.display = 'block';
            }
            fldrSzBtn.textContent = 'Refreshed ✓';
          }
        } catch (_) {
          fldrSzBtn.textContent = 'Failed';
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
 * 4. Background Transfer Queue Cockpit
 * Real-time SSE streaming of transfers, velocity in MB/s, ETA, and Pause/Resume/Cancel controls.
 */
export class FmTransfersCockpit {
  constructor(fmWindow) {
    this.fm = fmWindow;
    this.cockpitEl = null;
    this.badgeEl = null;
    this.eventSource = null;
    this.tasks = [];
    this.isOpen = false;
    this.init();
  }

  init() {
    this.createCockpitDOM();
    this.connectSSE();
  }

  createCockpitDOM() {
    let el = document.getElementById('fm-transfers-cockpit');
    if (!el) {
      const html = `
        <div id="fm-transfers-cockpit" class="fm-transfers-cockpit" style="display: none; position: fixed; right: 20px; bottom: 60px; width: 340px; max-height: 420px; background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.15); border-radius: 10px; box-shadow: 0 20px 50px rgba(0,0,0,0.8); z-index: 9200; flex-direction: column; overflow: hidden; font-family: inherit;">
          <div class="fm-cockpit-header" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
            <div style="font-size: 12px; font-weight: 700; color: var(--fg); display: flex; align-items: center; gap: 6px;">
              <span>⇄</span> Transfers & Tasks
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
              <button type="button" id="fm-cockpit-clear-btn" style="background: none; border: none; font-size: 11px; color: var(--muted); cursor: pointer;" title="Clear Completed">Clear</button>
              <button type="button" id="fm-cockpit-close-btn" style="background: none; border: none; font-size: 14px; color: var(--muted); cursor: pointer;">✕</button>
            </div>
          </div>
          <div class="fm-cockpit-body" style="flex: 1; overflow-y: auto; padding: 8px;">
            <!-- Task items rendered here -->
          </div>
        </div>
      `;
      document.body.insertAdjacentHTML('beforeend', html);
      el = document.getElementById('fm-transfers-cockpit');
    }
    this.cockpitEl = el;

    const closeBtn = el.querySelector('#fm-cockpit-close-btn');
    if (closeBtn) closeBtn.addEventListener('click', () => this.toggle(false));

    const clearBtn = el.querySelector('#fm-cockpit-clear-btn');
    if (clearBtn) {
      clearBtn.addEventListener('click', async () => {
        const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';
        await fetch('/api/fs/transfers/completed', {
          method: 'DELETE',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        this.tasks = this.tasks.filter((t) => t.status === 'running' || t.status === 'paused');
        this.render();
      });
    }
  }

  toggle(show = null) {
    this.isOpen = show !== null ? show : !this.isOpen;
    if (this.cockpitEl) {
      this.cockpitEl.style.display = this.isOpen ? 'flex' : 'none';
    }
  }

  connectSSE() {
    try {
      const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';
      const sseUrl = `/api/fs/transfers/stream`;
      this.eventSource = new EventSource(sseUrl);

      this.eventSource.addEventListener('snapshot', (e) => {
        try {
          const data = JSON.parse(e.data);
          this.tasks = data.tasks || [];
          this.render();
        } catch (_) {}
      });

      this.eventSource.addEventListener('task_update', (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data && data.task) {
            const idx = this.tasks.findIndex((t) => t.id === data.task.id);
            if (idx >= 0) {
              this.tasks[idx] = data.task;
            } else {
              this.tasks.unshift(data.task);
            }
            this.render();
          }
        } catch (_) {}
      });

      this.eventSource.onerror = () => {
        // Auto-reconnect handled natively by EventSource
      };
    } catch (_) {}
  }

  render() {
    const activeTasks = this.tasks.filter((t) => t.status === 'running' || t.status === 'paused');
    const badgeCount = activeTasks.length;

    // Update toolbar button badge
    document.querySelectorAll('.fm-transfers-count-badge').forEach((badge) => {
      badge.textContent = badgeCount > 0 ? String(badgeCount) : '';
      badge.style.display = badgeCount > 0 ? 'inline-block' : 'none';
    });

    if (!this.cockpitEl) return;
    const body = this.cockpitEl.querySelector('.fm-cockpit-body');
    if (!body) return;

    if (!this.tasks.length) {
      body.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 24px 0;">No active transfers</div>';
      return;
    }

    body.innerHTML = this.tasks.slice(0, 10).map((t) => {
      const isRunning = t.status === 'running';
      const isPaused = t.status === 'paused';
      const isDone = t.status === 'completed';
      const isFailed = t.status === 'failed';
      const isCancelled = t.status === 'cancelled';

      const statusColor = isDone ? '#22c55e' : (isFailed ? '#ef4444' : (isRunning ? '#0ea5e9' : '#eab308'));
      const speedStr = t.speed_bps > 1024 ? `${(t.speed_bps / (1024 * 1024)).toFixed(1)} MB/s` : '';
      const etaStr = t.eta_seconds != null && t.eta_seconds > 0 ? `${Math.round(t.eta_seconds)}s remaining` : '';

      return `
        <div class="fm-task-card" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; padding: 8px 10px; margin-bottom: 6px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
            <span style="font-size: 11px; font-weight: 700; color: ${statusColor}; text-transform: uppercase;">${t.action}</span>
            <span style="font-size: 11px; color: var(--muted);">${t.percent}%</span>
          </div>
          <div style="font-size: 11px; color: var(--fg); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(t.current_file || t.destination)}">
            ${escapeHtml(t.current_file ? t.current_file.split('/').pop() : t.destination)}
          </div>
          <div class="fm-progress-bar-wrap" style="height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; margin: 6px 0; overflow: hidden;">
            <div style="height: 100%; width: ${t.percent}%; background: ${statusColor}; transition: width 0.2s;"></div>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: var(--muted);">
            <span>${speedStr} ${etaStr ? '• ' + etaStr : ''}</span>
            <div style="display: flex; gap: 4px;">
              ${isRunning ? `<button class="fm-task-btn" data-act="pause" data-id="${t.id}" style="background:none; border:none; color:var(--fg); cursor:pointer;">⏸</button>` : ''}
              ${isPaused ? `<button class="fm-task-btn" data-act="resume" data-id="${t.id}" style="background:none; border:none; color:#22c55e; cursor:pointer;">▶</button>` : ''}
              ${!isDone && !isFailed && !isCancelled ? `<button class="fm-task-btn" data-act="cancel" data-id="${t.id}" style="background:none; border:none; color:#ef4444; cursor:pointer;">✕</button>` : ''}
            </div>
          </div>
        </div>
      `;
    }).join('');

    // Bind pause/resume/cancel
    body.querySelectorAll('.fm-task-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const act = btn.dataset.act;
        const tid = btn.dataset.id;
        const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';
        await fetch(`/api/fs/transfers/${tid}/${act}`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
      });
    });
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
    this.init();
  }

  init() {
    let el = document.getElementById('fm-context-menu');
    if (!el) {
      const html = `<div id="fm-context-menu" class="fm-context-menu" style="display: none; position: fixed; z-index: 99999;"></div>`;
      document.body.insertAdjacentHTML('beforeend', html);
      el = document.getElementById('fm-context-menu');
    }
    this.menuEl = el;

    document.addEventListener('click', () => this.hide());
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

    let itemsHtml = `
      <div class="fm-ctx-group">
        ${fileItem && !isDir ? `<div class="fm-ctx-item" data-act="preview">👁️ QuickLook <span class="fm-ctx-key">Space</span></div>` : ''}
        ${fileItem && isDir ? `<div class="fm-ctx-item" data-act="open">📂 Open <span class="fm-ctx-key">Enter</span></div>` : ''}
        <div class="fm-ctx-item" data-act="new-window">🪟 Open in New Window</div>
      </div>
      <div class="fm-ctx-divider"></div>
      <div class="fm-ctx-group">
        ${hasSelection ? `<div class="fm-ctx-item" data-act="cut">✂️ Cut <span class="fm-ctx-key">Cmd+X</span></div>` : ''}
        ${hasSelection ? `<div class="fm-ctx-item" data-act="copy">📋 Copy <span class="fm-ctx-key">Cmd+C</span></div>` : ''}
        <div class="fm-ctx-item" data-act="paste">📥 Paste <span class="fm-ctx-key">Cmd+V</span></div>
        ${hasSelection ? `<div class="fm-ctx-item" data-act="duplicate">📄 Duplicate <span class="fm-ctx-key">Cmd+D</span></div>` : ''}
        ${isSingle ? `<div class="fm-ctx-item" data-act="rename">✏️ Rename <span class="fm-ctx-key">F2</span></div>` : ''}
      </div>
      <div class="fm-ctx-divider"></div>
      <div class="fm-ctx-group">
        ${hasSelection ? `<div class="fm-ctx-item" data-act="archive-create">🗜️ Create Archive (.zip)</div>` : ''}
        ${isZip ? `<div class="fm-ctx-item" data-act="archive-extract">📦 Extract Archive Here</div>` : ''}
        ${isSingle && !isDir ? `<div class="fm-ctx-item" data-act="share">🔗 Share Link</div>` : ''}
        ${isSingle && !isDir ? `<div class="fm-ctx-item" data-act="checksum">🛡️ Compute SHA-256</div>` : ''}
      </div>
      <div class="fm-ctx-divider"></div>
      <div class="fm-ctx-group">
        ${hasSelection ? `<div class="fm-ctx-item text-danger" data-act="trash">🗑️ Move to Trash <span class="fm-ctx-key">Delete</span></div>` : ''}
        ${hasSelection ? `<div class="fm-ctx-item text-danger" data-act="delete-perm">⚠️ Permanent Delete <span class="fm-ctx-key">Shift+Del</span></div>` : ''}
      </div>
    `;

    this.menuEl.innerHTML = itemsHtml;
    this.menuEl.style.display = 'block';

    // Viewport edge clamping
    const menuWidth = 220;
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
    if (this.menuEl) this.menuEl.style.display = 'none';
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
