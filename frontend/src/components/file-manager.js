import {
  FmMarqueeController,
  FmSidebarTree,
  FmInspector,
  FmTransfersCockpit,
  FmContextMenu,
  extractDataTransferEntries,
} from './file-manager-helpers.js';
import { api, auth, ApiError } from '../api.js';
import { escapeHtml, copyTextToClipboard } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast, showPromptToast, showBottomSheet, showActionToast } from '../toast.js';
import { t } from '../i18n.js';
import { binColumns, binBar } from './fm-bin-view.js';
import { makeDraggable, bringToFront } from './dock.js';
import { openFilePreview as openFilePreviewModal } from '../file-preview-loader.js';
import { transferCenter } from './transfer-center.js';
import { favorites, isFavorite, toggleFavorite, closestPath } from './fm-favorites.js';
import { thumbKind, thumbUrl } from './viewer-kit.js';

import { formatBytes as formatSize, formatDateTime } from '../format.js';
import { isCompact } from '../device.js';
import '../styles/files-lazy.css'; // the explorer's own sheet loads with this code (PERF-9)
// Virtualized DOM constants
const ROW_HEIGHT = 42;
const BUFFER = 5;
const BOUNDS_KEY = 'zettnas_fm_bounds';

// Shared clipboard across all File Explorer instances
let _clipboard = { items: [], action: 'copy', sourceInstanceId: null };

// Map of all active File Explorer instances: instanceId -> FileManagerWindow
const _fmInstances = new Map();
let _fmInstanceSeq = 1;
let _activeFmInstance = null;

export function formatBytes(bytes) {
  return formatSize(bytes, { decimals: 2 });
}

export function getActiveFmInstance() {
  if (_activeFmInstance && _activeFmInstance.isOpen()) {
    return _activeFmInstance;
  }
  for (const inst of _fmInstances.values()) {
    if (inst.windowEl && inst.windowEl.classList.contains('active-window')) {
      return inst;
    }
  }
  if (window.DockManager && window.DockManager.activeId) {
    for (const inst of _fmInstances.values()) {
      if (inst.dockId === window.DockManager.activeId) return inst;
    }
  }
  return _fmInstances.get('file-manager-window') || _fmInstances.values().next().value || null;
}

/**
 * FileManagerWindow represents an independent, full-featured File Explorer instance.
 * Supports arbitrary folder paths, multi-selection, 2D virtualized rendering,
 * navigation history stacks, client/server search, and inter-window drag-and-drop.
 */
export function fsUploadUrl(dir, name) {
  return `/api/fs/upload?path=${encodeURIComponent(dir)}&filename=${encodeURIComponent(name)}`;
}

const SEL_ICONS = {
  clear: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.2" fill="none" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',
  share: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>',
  download: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>',
  move: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" aria-hidden="true"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><polyline points="12 11 15 14 12 17"></polyline><line x1="8" y1="14" x2="15" y2="14"></line></svg>',
  trash: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" aria-hidden="true"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path></svg>',
};

/**
 * The selection actions: a pill floating at the bottom of the file area while items are
 * selected, so the toolbar keeps its room. Labels show when the pane is wide enough.
 */
function selectionBarHtml(withIds) {
  const id = (name) => (withIds ? ` id="${name}"` : '');
  const btn = (name, cls, icon, label, extra = '') =>
    `<button type="button"${id(name)} class="fm-sel-btn ${cls}" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}"${extra}>${icon}<span class="fm-sel-label">${escapeHtml(label)}</span></button>`;
  return `
    <div${id('fm-selection-bar')} class="fm-selection-bar" role="toolbar" aria-label="${escapeHtml(t('fm.selection_actions', 'Selection actions'))}" style="display: none;">
      <button type="button"${id('fm-clear-sel-btn')} class="fm-sel-btn fm-sel-clear fm-clear-sel-btn" title="${escapeHtml(t('fm.clear_selection', 'Clear selection (Esc)'))}" aria-label="${escapeHtml(t('fm.clear_selection', 'Clear selection (Esc)'))}">${SEL_ICONS.clear}</button>
      <span${id('fm-selected-count')} class="fm-selected-count" aria-live="polite">0 selected</span>
      <span class="fm-sel-divider" aria-hidden="true"></span>
      ${btn('fm-bulk-share-btn', 'fm-bulk-share-btn', SEL_ICONS.share, t('fm.share_link', 'Share link'))}
      ${btn('fm-bulk-zip-btn', 'fm-bulk-zip-btn', SEL_ICONS.download, t('fm.download', 'Download'))}
      ${btn('fm-bulk-move-btn', 'fm-bulk-move-btn', SEL_ICONS.move, t('fm.move_to', 'Move to…'))}
      ${btn('fm-bulk-delete-btn', 'fm-sel-danger fm-bulk-delete-btn', SEL_ICONS.trash, t('fm.delete', 'Delete'))}
    </div>`;
}


/** What a delete asks: the file's own name for one item, the count for several. Items already
 * in a Recycle Bin are deleted for good, and the question says so. */
export function binConfirmText(paths) {
  const inBin = paths.length > 0 && paths.every((p) => String(p).includes('/.RecycleBin/'));
  if (paths.length === 1) {
    const name = String(paths[0]).replace(/\/+$/, '').split('/').pop() || String(paths[0]);
    return inBin
      ? t('fm.confirm_delete_one_permanent', "“{name}” will be deleted for good. This can't be undone.", { name })
      : t('fm.confirm_delete_one', 'Move “{name}” to the Recycle Bin?', { name });
  }
  return inBin
    ? t('fm.confirm_bulk_delete_permanent', "{count, plural, one {# item will be deleted for good. This can't be undone.} other {# items will be deleted for good. This can't be undone.}}", { count: paths.length })
    : t('fm.confirm_bulk_delete', 'Move {count, plural, one {# item} other {# items}} to the Recycle Bin?', { count: paths.length });
}

export class FileManagerWindow {
  constructor(id, dockId, initialPath, isPrimary = false) {
    this.id = id;
    this.dockId = dockId;
    this.isPrimary = isPrimary;
    this.currentPath = initialPath || (isPrimary ? (localStorage.getItem('zettnas_fm_last_path') || '/mnt/user') : '/mnt/user');
    this.viewMode = localStorage.getItem('zettnas_fm_view_mode') || 'list';
    this.fileList = [];
    this.rawFileList = [];
    this.selectedPaths = new Set();
    this.lastSelectedIndex = -1;
    this.selectionAnchorIndex = -1;
    this.currentSortBy = 'name';
    this.currentSortDir = 'asc';
    this.isMaximized = false;
    this.preMaxBounds = null;

    // Navigation history stack
    this.history = [];
    this.historyIndex = -1;

    // Search and lifecycle controllers
    this.searchQuery = '';
    this.isSearching = false;
    this.abortController = null;
    this.searchAbortController = null;
    this.resizeObserver = null;

    // Scoped DOM references
    this.windowEl = null;
    this.viewport = null;
    this.spacer = null;
    this.list = null;
    this.pathInput = null;
    this.breadcrumbs = null;
    this.selectionBar = null;
    this.selectedCount = null;
    this.bulkDeleteBtn = null;
    this.bulkMoveBtn = null;
    this.bulkZipBtn = null;
    this.clearSelBtn = null;
    this.selectAllCheckbox = null;
    this.titleFolderSpan = null;
    this.backBtn = null;
    this.fwdBtn = null;
    this.upBtn = null;
    this.refreshBtn = null;
    this.searchInput = null;
    this.newFolderBtn = null;
    this.newWinBtn = null;
    this.organizeBtn = null;
    this.btnViewList = null;
    this.btnViewIcon = null;
    this.headerRow = null;
    this.colName = null;
    this.colSize = null;
    this.colType = null;
    this.colMtime = null;
    this.btnViewCompact = null;
    this.btnInspectorToggle = null;
    this.btnTransfersToggle = null;
    this.sidebarTree = null;
    this.inspector = null;
    this.marqueeController = null;
    this.contextMenu = null;
    this.transfersCockpit = null;
    this._springLoadTimer = null;
    this._springLoadTarget = null;
  }

  isOpen() {
    return Boolean(
      this.windowEl &&
      this.windowEl.style.display !== 'none' &&
      !this.windowEl.classList.contains('window-minimized')
    );
  }

  getTitle() {
    const baseTitle = t('fm.title', 'File Explorer');
    const folderName = this.currentPath.split('/').filter(Boolean).pop();
    if (!folderName || (this.isPrimary && this.currentPath === '/mnt/user')) {
      return baseTitle;
    }
    return `${baseTitle} (${folderName})`;
  }

  init() {
    this.initDOM();
    this.bindElements();
    this.bindEvents();
    if (this.isPrimary) {
      this.restoreSavedBounds();
    }
  }

  initDOM() {
    if (this.isPrimary) {
      if (!document.getElementById('file-manager-window')) {
        const primaryHtml = `
          <div id="file-manager-window" class="os-window file-manager-window" tabindex="-1" style="display: none;">
            <div class="os-window-header">
              <div class="os-window-title">
                <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                <span class="fm-title-main" data-i18n="fm.title">${t('fm.title', 'File Explorer')}</span>
                <span class="fm-title-folder" style="margin-left: 6px; font-weight: normal; opacity: 0.75; font-size: var(--zn-fs-xs);"></span>
              </div>
              <div class="os-window-controls">
                <button class="win-btn min-btn" id="fm-min" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
                <button class="win-btn max-btn" id="fm-max" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
                <button class="win-btn close-btn" id="fm-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
              </div>
            </div>
            <div class="fm-toolbar">
              <div class="fm-nav-btn-group" style="display:flex; align-items:center; gap:2px;">
                <button class="fm-tool-btn fm-back-btn" title="${t('fm.back', 'Back')}" data-i18n-title="fm.back" aria-label="${t('fm.back', 'Back')}" disabled>
                  <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="15 18 9 12 15 6"></polyline></svg>
                </button>
                <button class="fm-tool-btn fm-fwd-btn" title="${t('fm.forward', 'Forward')}" data-i18n-title="fm.forward" aria-label="${t('fm.forward', 'Forward')}" disabled>
                  <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="9 18 15 12 9 6"></polyline></svg>
                </button>
                <button id="fm-up-btn" class="fm-tool-btn fm-up-btn" title="${t('fm.go_up', 'Go Up')}" data-i18n-title="fm.go_up" aria-label="${t('fm.go_up', 'Go Up')}">
                  <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
                </button>
                <button type="button" class="fm-tool-btn fm-locations-btn" title="${t('fm.quick_locations', 'Quick Locations')}" aria-label="${t('fm.quick_locations', 'Quick Locations')}" aria-haspopup="menu" aria-expanded="false">📍</button>
              </div>
              <div class="fm-path-container" style="flex: 1; position: relative; display: flex; align-items: center; min-width: 0;">
                <input type="text" id="fm-path-input" class="fm-path-input" aria-label="${escapeHtml(t('fm.path_input_label', 'Folder path'))}" spellcheck="false" list="fm-path-list" style="width: 100%; color: transparent;" />
                <div id="fm-path-breadcrumbs" class="fm-path-breadcrumbs" style="position: absolute; left: 0; top: 0; bottom: 0; right: 30px; display: flex; align-items: center; padding-left: 8px; cursor: text; overflow: hidden; pointer-events: auto;"></div>
                <datalist id="fm-path-list">
                  <option value="/mnt/user"></option>
                  <option value="/mnt/user/.RecycleBin"></option>
                  <option value="/boot"></option>
                  <option value="/mnt/user/appdata"></option>
                  <option value="/mnt/user/system"></option>
                </datalist>
              </div>
              <button id="fm-refresh-btn" class="fm-tool-btn fm-refresh-btn" title="${t('fm.refresh', 'Refresh')}" data-i18n-title="fm.refresh" aria-label="${t('vm.refresh', 'Refresh')}">
                <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
              </button>
              <div class="fm-search-wrap" style="position: relative; display: flex; align-items: center; gap: 3px; margin: 0 4px;">
                <input type="text" class="fm-search-input" placeholder="${t('fm.search_placeholder', 'Search...')}" style="width: 105px; font-size: var(--zn-fs-xs); padding: 3px 8px 3px 22px; border-radius: 6px; background: var(--zn-shade-25); border: 1px solid var(--zn-line-12); color: var(--fg); outline: none;" />
                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none" style="position: absolute; left: 6px; color: var(--muted); pointer-events: none;"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                <button type="button" class="fm-tool-btn fm-ai-search-toggle" title="${t('ui.toggle_zettai_semantic_visual_rag', 'Turn AI search on or off (it never wakes sleeping drives)')}" aria-label="${t('ui.ai_semantic_search', 'AI Semantic Search')}" style="font-size: var(--zn-fs-xs); padding: 2px 5px; border-radius: 5px;">✨ AI</button>
              </div>
              <button id="fm-new-folder-btn" class="fm-tool-btn fm-new-folder-btn" title="${t('fm.new_folder', 'New Folder')}" data-i18n-title="fm.new_folder" aria-label="${t('fm.new_folder', 'New Folder')}">
                <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><line x1="12" y1="11" x2="12" y2="17"></line><line x1="9" y1="14" x2="15" y2="14"></line></svg>
              </button>
              <button id="fm-new-window-btn" class="fm-tool-btn fm-new-win-btn" title="${t('fm.new_window', 'New Window (Ctrl+N)')}" data-i18n-title="fm.new_window" aria-label="${t('dock.new_fm_window', 'New Window')}">
                <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="3" width="14" height="14" rx="2" ry="2"></rect><line x1="21" y1="9" x2="21" y2="15"></line><line x1="18" y1="12" x2="24" y2="12"></line></svg>
              </button>
              <button id="fm-organize-btn" class="fm-tool-btn fm-organize-btn" title="${t('fm.organize_media', 'Organize Media')}" data-i18n-title="fm.organize_media" aria-label="${t('fm.organize_media', 'Organize Media')}">
                <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
              </button>
              <div class="fm-view-mode-group">
                <button id="fm-btn-view-list" class="fm-tool-btn fm-btn-view-list ${this.viewMode === 'list' ? 'active' : ''}" title="${t('fm.view_list', 'List View')}" data-i18n-title="fm.view_list" aria-label="${t('fm.view_list', 'List View')}">
                  <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
                </button>
                <button id="fm-btn-view-compact" class="fm-tool-btn fm-btn-view-compact ${this.viewMode === 'compact' ? 'active' : ''}" title="${t('fm.view_compact', 'Compact View')}" data-i18n-title="fm.view_compact" aria-label="${t('fm.view_compact', 'Compact View')}">
                  <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
                </button>
                <button id="fm-btn-view-icon" class="fm-tool-btn fm-btn-view-icon ${this.viewMode === 'icon' ? 'active' : ''}" title="${t('fm.view_icon', 'Icon View')}" data-i18n-title="fm.view_icon" aria-label="${t('fm.view_icon', 'Icon View')}">
                  <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
                </button>
              </div>
              <div class="fm-aux-tool-group" style="display: flex; align-items: center; gap: 3px; margin-left: 4px;">
                <button type="button" id="fm-btn-transfers" class="fm-tool-btn fm-btn-transfers-toggle" title="${t('fm.transfers', 'Transfers')}" data-i18n-title="fm.transfers" aria-label="${t('transfers.title', 'Transfers')}">
                  <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="8 17 12 21 16 17"></polyline><line x1="12" y1="12" x2="12" y2="21"></line><path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"></path></svg>
                  <span class="fm-transfers-count-badge" style="display: none; background: #0ea5e9; color: #fff; font-size: var(--zn-fs-xs); font-weight: 700; padding: 1px 4px; border-radius: 6px; margin-left: 2px;">0</span>
                </button>
                <button type="button" id="fm-btn-inspector" class="fm-tool-btn fm-btn-inspector-toggle" title="${t('fm.inspector_toggle', 'Toggle Inspector')}" data-i18n-title="fm.inspector_toggle" aria-label="${t('fm.inspector_toggle', 'Toggle Inspector')}">
                  <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                </button>
              </div>
            </div>
            <div class="fm-content" style="position: relative; display: flex; flex-direction: column;">
              <div class="fm-3pane-layout" style="display: flex; flex: 1; min-height: 0; width: 100%; position: relative; overflow: hidden;">
                <div class="fm-sidebar-tree">
                  <div class="fm-tree-scroll"></div>
                </div>
                <div class="fm-main-pane" style="display: flex; flex-direction: column; flex: 1; min-width: 0; position: relative; overflow: hidden;">
                  ${selectionBarHtml(true)}
                  <div class="fm-header-row">
                    <div class="fm-col fm-col-check"><input type="checkbox" id="fm-select-all-checkbox" class="fm-checkbox fm-select-all-checkbox" title="${t('ui.select_all', 'Select All')}" /></div>
                    <div class="fm-col fm-col-name" data-i18n="fm.col_name" data-sort="name">${t('fm.col_name', 'Name')} <span class="fm-sort-icon"></span></div>
                    <div class="fm-col fm-col-type" data-i18n="fm.col_type" data-sort="type">${t('fm.col_type', 'Type')} <span class="fm-sort-icon"></span></div>
                    <div class="fm-col fm-col-size" data-i18n="fm.col_size" data-sort="size">${t('fm.col_size', 'Size')} <span class="fm-sort-icon"></span></div>
                    <div class="fm-col fm-col-mtime" data-i18n="fm.col_mtime" data-sort="mtime">${t('fm.col_mtime', 'Modified')} <span class="fm-sort-icon"></span></div>
                    <div class="fm-col fm-col-actions" data-i18n="fm.col_actions">${t('fm.col_actions', 'Actions')}</div>
                  </div>
                  <div id="fm-viewport" class="fm-viewport" data-scrollable="true" tabindex="0">
                    <div id="fm-spacer" class="fm-spacer"></div>
                    <div id="fm-list" class="fm-list"></div>
                    <div class="fm-marquee-box" style="display: none;"></div>
                  </div>
                </div>
                <div class="fm-inspector-pane" style="display: none;">
                  <div class="fm-inspector-header" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 1px solid var(--zn-line-6);">
                    <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--fg); text-transform: uppercase; letter-spacing: 0.5px;">Inspector</span>
                    <button type="button" class="fm-inspector-close-btn" style="background: none; border: none; font-size: 14px; color: var(--muted); cursor: pointer;">✕</button>
                  </div>
                  <div class="fm-inspector-content" style="flex: 1; overflow-y: auto; padding: 12px;"></div>
                </div>
              </div>
              <input type="file" class="fm-file-upload-input" multiple style="display: none;" />
              <button type="button" class="fm-mobile-fab" title="${t('ui.quick_actions', 'Quick Actions')}" aria-label="${t('ui.quick_actions', 'Quick Actions')}" style="display: none;">+</button>
            </div>
          </div>
        `;
        document.body.insertAdjacentHTML('beforeend', primaryHtml);
      }
      this.windowEl = document.getElementById('file-manager-window');
      if (this.viewMode === 'icon') this.windowEl?.classList.add('fm-mode-icon');
    } else {
      // Secondary window
      const secHtml = `
        <div id="${this.id}" class="os-window file-manager-window" tabindex="-1" style="display: none;">
          <div class="os-window-header">
            <div class="os-window-title">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
              <span class="fm-title-main" data-i18n="fm.title">${t('fm.title', 'File Explorer')}</span>
              <span class="fm-title-folder" style="margin-left: 6px; font-weight: normal; opacity: 0.75; font-size: var(--zn-fs-xs);"></span>
            </div>
            <div class="os-window-controls">
              <button class="win-btn min-btn" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
              <button class="win-btn max-btn" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
              <button class="win-btn close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
            </div>
          </div>
          <div class="fm-toolbar">
            <div class="fm-nav-btn-group" style="display:flex; align-items:center; gap:2px;">
              <button class="fm-tool-btn fm-back-btn" title="${t('fm.back', 'Back')}" data-i18n-title="fm.back" aria-label="${t('fm.back', 'Back')}" disabled>
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="15 18 9 12 15 6"></polyline></svg>
              </button>
              <button class="fm-tool-btn fm-fwd-btn" title="${t('fm.forward', 'Forward')}" data-i18n-title="fm.forward" aria-label="${t('fm.forward', 'Forward')}" disabled>
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="9 18 15 12 9 6"></polyline></svg>
              </button>
              <button class="fm-tool-btn fm-up-btn" title="${t('fm.go_up', 'Go Up')}" data-i18n-title="fm.go_up" aria-label="${t('fm.go_up', 'Go Up')}">
                <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
              </button>
              <button type="button" class="fm-tool-btn fm-locations-btn" title="${t('fm.quick_locations', 'Quick Locations')}" aria-label="${t('fm.quick_locations', 'Quick Locations')}" aria-haspopup="menu" aria-expanded="false">📍</button>
            </div>
            <div class="fm-path-container" style="flex: 1; position: relative; display: flex; align-items: center; min-width: 0;">
              <input type="text" class="fm-path-input" aria-label="${escapeHtml(t('fm.path_input_label', 'Folder path'))}" spellcheck="false" list="${this.id}-path-list" style="width: 100%; color: transparent;" />
              <div class="fm-path-breadcrumbs" style="position: absolute; left: 0; top: 0; bottom: 0; right: 30px; display: flex; align-items: center; padding-left: 8px; cursor: text; overflow: hidden; pointer-events: auto;"></div>
              <datalist id="${this.id}-path-list">
                <option value="/mnt/user"></option>
                <option value="/mnt/user/.RecycleBin"></option>
                <option value="/boot"></option>
                <option value="/mnt/user/appdata"></option>
                <option value="/mnt/user/system"></option>
              </datalist>
            </div>
            <button class="fm-tool-btn fm-refresh-btn" title="${t('fm.refresh', 'Refresh')}" data-i18n-title="fm.refresh" aria-label="${t('vm.refresh', 'Refresh')}">
              <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
            </button>
            <div class="fm-search-wrap" style="position: relative; display: flex; align-items: center; gap: 3px; margin: 0 4px;">
              <input type="text" class="fm-search-input" placeholder="${t('fm.search_placeholder', 'Search...')}" style="width: 105px; font-size: var(--zn-fs-xs); padding: 3px 8px 3px 22px; border-radius: 6px; background: var(--zn-shade-25); border: 1px solid var(--zn-line-12); color: var(--fg); outline: none;" />
              <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none" style="position: absolute; left: 6px; color: var(--muted); pointer-events: none;"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
              <button type="button" class="fm-tool-btn fm-ai-search-toggle" title="${t('ui.toggle_zettai_semantic_visual_rag', 'Turn AI search on or off (it never wakes sleeping drives)')}" aria-label="${t('ui.ai_semantic_search', 'AI Semantic Search')}" style="font-size: var(--zn-fs-xs); padding: 2px 5px; border-radius: 5px;">✨ AI</button>
            </div>
            <button class="fm-tool-btn fm-new-folder-btn" title="${t('fm.new_folder', 'New Folder')}" data-i18n-title="fm.new_folder" aria-label="${t('fm.new_folder', 'New Folder')}">
              <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><line x1="12" y1="11" x2="12" y2="17"></line><line x1="9" y1="14" x2="15" y2="14"></line></svg>
            </button>
            <button class="fm-tool-btn fm-new-win-btn" title="${t('fm.new_window', 'New Window (Ctrl+N)')}" data-i18n-title="fm.new_window" aria-label="${t('dock.new_fm_window', 'New Window')}">
              <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="3" width="14" height="14" rx="2" ry="2"></rect><line x1="21" y1="9" x2="21" y2="15"></line><line x1="18" y1="12" x2="24" y2="12"></line></svg>
            </button>
            <button class="fm-tool-btn fm-organize-btn" title="${t('fm.organize_media', 'Organize Media')}" data-i18n-title="fm.organize_media" aria-label="${t('fm.organize_media', 'Organize Media')}">
              <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
            </button>
            <div class="fm-view-mode-group">
              <button class="fm-tool-btn fm-btn-view-list ${this.viewMode === 'list' ? 'active' : ''}" title="${t('fm.view_list', 'List View')}" data-i18n-title="fm.view_list" aria-label="${t('fm.view_list', 'List View')}">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
              </button>
              <button class="fm-tool-btn fm-btn-view-compact ${this.viewMode === 'compact' ? 'active' : ''}" title="${t('fm.view_compact', 'Compact View')}" data-i18n-title="fm.view_compact" aria-label="${t('fm.view_compact', 'Compact View')}">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
              </button>
              <button class="fm-tool-btn fm-btn-view-icon ${this.viewMode === 'icon' ? 'active' : ''}" title="${t('fm.view_icon', 'Icon View')}" data-i18n-title="fm.view_icon" aria-label="${t('fm.view_icon', 'Icon View')}">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
              </button>
            </div>
            <div class="fm-aux-tool-group" style="display: flex; align-items: center; gap: 3px; margin-left: 4px;">
              <button type="button" class="fm-tool-btn fm-btn-transfers-toggle" title="${t('fm.transfers', 'Transfers')}" data-i18n-title="fm.transfers" aria-label="${t('transfers.title', 'Transfers')}">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="8 17 12 21 16 17"></polyline><line x1="12" y1="12" x2="12" y2="21"></line><path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"></path></svg>
                <span class="fm-transfers-count-badge" style="display: none; background: #0ea5e9; color: #fff; font-size: var(--zn-fs-xs); font-weight: 700; padding: 1px 4px; border-radius: 6px; margin-left: 2px;">0</span>
              </button>
              <button type="button" class="fm-tool-btn fm-btn-inspector-toggle" title="${t('fm.inspector_toggle', 'Toggle Inspector')}" data-i18n-title="fm.inspector_toggle" aria-label="${t('fm.inspector_toggle', 'Toggle Inspector')}">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
              </button>
            </div>
          </div>
          <div class="fm-content" style="position: relative; display: flex; flex-direction: column;">
            <div class="fm-3pane-layout" style="display: flex; flex: 1; min-height: 0; width: 100%; position: relative; overflow: hidden;">
              <div class="fm-sidebar-tree">
                <div class="fm-tree-scroll"></div>
              </div>
              <div class="fm-main-pane" style="display: flex; flex-direction: column; flex: 1; min-width: 0; position: relative; overflow: hidden;">
                  ${selectionBarHtml(false)}
                <div class="fm-header-row">
                  <div class="fm-col fm-col-check"><input type="checkbox" class="fm-checkbox fm-select-all-checkbox" title="${t('ui.select_all', 'Select All')}" /></div>
                  <div class="fm-col fm-col-name" data-i18n="fm.col_name" data-sort="name">${t('fm.col_name', 'Name')} <span class="fm-sort-icon"></span></div>
                  <div class="fm-col fm-col-type" data-i18n="fm.col_type" data-sort="type">${t('fm.col_type', 'Type')} <span class="fm-sort-icon"></span></div>
                  <div class="fm-col fm-col-size" data-i18n="fm.col_size" data-sort="size">${t('fm.col_size', 'Size')} <span class="fm-sort-icon"></span></div>
                  <div class="fm-col fm-col-mtime" data-i18n="fm.col_mtime" data-sort="mtime">${t('fm.col_mtime', 'Modified')} <span class="fm-sort-icon"></span></div>
                  <div class="fm-col fm-col-actions" data-i18n="fm.col_actions">${t('fm.col_actions', 'Actions')}</div>
                </div>
                <div class="fm-viewport" data-scrollable="true" tabindex="0">
                  <div class="fm-spacer"></div>
                  <div class="fm-list"></div>
                  <div class="fm-marquee-box" style="display: none;"></div>
                </div>
              </div>
              <div class="fm-inspector-pane" style="display: none;">
                <div class="fm-inspector-header" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 1px solid var(--zn-line-6);">
                  <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--fg); text-transform: uppercase; letter-spacing: 0.5px;">Inspector</span>
                  <button type="button" class="fm-inspector-close-btn" style="background: none; border: none; font-size: 14px; color: var(--muted); cursor: pointer;">✕</button>
                </div>
                <div class="fm-inspector-content" style="flex: 1; overflow-y: auto; padding: 12px;"></div>
              </div>
            </div>
            <input type="file" class="fm-file-upload-input" multiple style="display: none;" />
            <button type="button" class="fm-mobile-fab" title="${t('ui.quick_actions', 'Quick Actions')}" aria-label="${t('ui.quick_actions', 'Quick Actions')}" style="display: none;">+</button>
          </div>
        </div>
      `;
      document.body.insertAdjacentHTML('beforeend', secHtml);
      this.windowEl = document.getElementById(this.id);
      if (this.viewMode === 'icon') this.windowEl?.classList.add('fm-mode-icon');
    }
    if (this.windowEl) {
      if (!this.windowEl.querySelector('.fm-locations-btn')) {
        const navGrp = this.windowEl.querySelector('.fm-nav-btn-group');
        if (navGrp) {
          navGrp.insertAdjacentHTML('beforeend', '<button type="button" class="fm-tool-btn fm-locations-btn" title="' + t('fm.quick_locations', 'Quick Locations') + '" aria-label="' + t('fm.quick_locations', 'Quick Locations') + '" aria-haspopup="menu" aria-expanded="false">📍</button>');
        }
      }
      if (!this.windowEl.querySelector('.fm-sidebar-toggle')) {
        const navGrp = this.windowEl.querySelector('.fm-nav-btn-group');
        const label = t('fm.folders', 'Folders');
        navGrp?.insertAdjacentHTML(
          'afterbegin',
          `<button type="button" class="fm-tool-btn fm-sidebar-toggle" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}" aria-expanded="false"><svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/></svg></button>`
        );
        const toggle = this.windowEl.querySelector('.fm-sidebar-toggle');
        toggle?.addEventListener('click', (e) => {
          e.stopPropagation();
          const open = this.windowEl.classList.toggle('fm-sidebar-open');
          toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        // Picking a folder in the drawer closes it
        this.windowEl.querySelector('.fm-sidebar-tree')?.addEventListener('click', (e) => {
          if (e.target.closest('.fm-tree-item, [data-path]')) {
            this.windowEl.classList.remove('fm-sidebar-open');
            toggle?.setAttribute('aria-expanded', 'false');
          }
        });
      }
      const contentEl = this.windowEl.querySelector('.fm-content');
      if (contentEl) {
        contentEl.style.position = 'relative';
        if (!contentEl.querySelector('.fm-file-upload-input')) {
          contentEl.insertAdjacentHTML('beforeend', '<input type="file" class="fm-file-upload-input" multiple style="display: none;" />');
        }
        if (!contentEl.querySelector('.fm-mobile-fab')) {
          contentEl.insertAdjacentHTML('beforeend', '<button type="button" class="fm-mobile-fab" title="' + t('ui.quick_actions', 'Quick Actions') + '" aria-label="' + t('ui.quick_actions', 'Quick Actions') + '" style="display: none;">+</button>');
        }
      }
    }
  }

  bindElements() {
    if (!this.windowEl) return;
    this.viewport = this.windowEl.querySelector('.fm-viewport');
    this.spacer = this.windowEl.querySelector('.fm-spacer');
    this.list = this.windowEl.querySelector('.fm-list');
    this.pathInput = this.windowEl.querySelector('.fm-path-input');
    this.breadcrumbs = this.windowEl.querySelector('.fm-path-breadcrumbs');
    this.selectionBar = this.windowEl.querySelector('.fm-selection-bar');
    this.selectedCount = this.windowEl.querySelector('.fm-selected-count');
    this.bulkDeleteBtn = this.windowEl.querySelector('.fm-bulk-delete-btn');
    this.bulkMoveBtn = this.windowEl.querySelector('.fm-bulk-move-btn');
    this.bulkZipBtn = this.windowEl.querySelector('.fm-bulk-zip-btn');
    this.clearSelBtn = this.windowEl.querySelector('.fm-clear-sel-btn');
    this.bulkShareBtn = this.windowEl.querySelector('.fm-bulk-share-btn');
    this.selectAllCheckbox = this.windowEl.querySelector('.fm-select-all-checkbox');
    this.titleFolderSpan = this.windowEl.querySelector('.fm-title-folder');
    this.backBtn = this.windowEl.querySelector('.fm-back-btn');
    // a phone's or tablet's Back goes back a folder before it leaves Files (UX-37)
    this.windowEl.zettBack = () => {
      if (this.historyIndex > 0) {
        this.goBack();
        return true;
      }
      return false;
    };
    this.fwdBtn = this.windowEl.querySelector('.fm-fwd-btn');
    this.upBtn = this.windowEl.querySelector('.fm-up-btn');
    this.locationsBtn = this.windowEl.querySelector('.fm-locations-btn');
    this.refreshBtn = this.windowEl.querySelector('.fm-refresh-btn');
    this.searchInput = this.windowEl.querySelector('.fm-search-input');
    this.aiSearchToggle = this.windowEl.querySelector('.fm-ai-search-toggle');
    this.aiSearchMode = false;
    this.newFolderBtn = this.windowEl.querySelector('.fm-new-folder-btn');
    this.newWinBtn = this.windowEl.querySelector('.fm-new-win-btn');
    this.organizeBtn = this.windowEl.querySelector('.fm-organize-btn');
    this.btnViewList = this.windowEl.querySelector('.fm-btn-view-list');
    this.btnViewIcon = this.windowEl.querySelector('.fm-btn-view-icon');
    this.headerRow = this.windowEl.querySelector('.fm-header-row');
    this.colName = this.windowEl.querySelector('.fm-header-row .fm-col-name');
    this.colSize = this.windowEl.querySelector('.fm-header-row .fm-col-size');
    this.colType = this.windowEl.querySelector('.fm-header-row .fm-col-type');
    this.colMtime = this.windowEl.querySelector('.fm-header-row .fm-col-mtime');
    this.uploadInput = this.windowEl.querySelector('.fm-file-upload-input');
    this.mobileFab = this.windowEl.querySelector('.fm-mobile-fab');
    this.btnViewCompact = this.windowEl.querySelector('.fm-btn-view-compact');
    this.btnTransfersToggle = this.windowEl.querySelector('.fm-btn-transfers-toggle');
    this.btnInspectorToggle = this.windowEl.querySelector('.fm-btn-inspector-toggle');
    this.marqueeBox = this.windowEl.querySelector('.fm-marquee-box');

    const treeContainer = this.windowEl.querySelector('.fm-sidebar-tree');
    if (treeContainer) {
      if (this.sidebarTree) {
        this.sidebarTree.container = treeContainer;
        this.sidebarTree.init();
      } else {
        this.sidebarTree = new FmSidebarTree(this, treeContainer);
      }
    }
    const inspectorContainer = this.windowEl.querySelector('.fm-inspector-pane');
    if (inspectorContainer) {
      if (this.inspector) {
        this.inspector.container = inspectorContainer;
        this.inspector.init();
      } else {
        this.inspector = new FmInspector(this, inspectorContainer);
      }
    }
    if (this.viewport) {
      if (this.marqueeController) {
        this.marqueeController.viewport = this.viewport;
        this.marqueeController.marqueeBox = this.marqueeBox;
        this.marqueeController.init();
      } else {
        this.marqueeController = new FmMarqueeController(this);
      }
    }
    if (!this.contextMenu) {
      this.contextMenu = new FmContextMenu(this);
    }
    if (this.transfersCockpit) {
      this.transfersCockpit.createCockpitDOM();
    } else {
      this.transfersCockpit = new FmTransfersCockpit(this);
    }
  }

  /** A window with no saved place opens centred below the top bar, not under it. */
  placeIfUnplaced() {
    const el = this.windowEl;
    if (!el || el.style.top || isCompact()) return;
    const r = el.getBoundingClientRect();
    const w = r.width || 900;
    const h = r.height || 600;
    el.style.left = `${Math.max(24, Math.round((window.innerWidth - w) / 2))}px`;
    el.style.top = `${Math.max(56, Math.round((window.innerHeight - h) / 2) - 20)}px`;
  }

  restoreSavedBounds() {
    try {
      const isMobile = isCompact();
      if (!isMobile) {
        const saved = JSON.parse(localStorage.getItem(BOUNDS_KEY) || 'null');
        if (saved && saved.left != null && saved.top != null) {
          const maxL = Math.max(24, window.innerWidth - (saved.width || 400) - 10);
          const maxT = Math.max(56, window.innerHeight - (saved.height || 300) - 70);
          this.windowEl.style.left = Math.max(24, Math.min(maxL, saved.left)) + 'px';
          this.windowEl.style.top = Math.max(56, Math.min(maxT, saved.top)) + 'px';
          if (saved.width) this.windowEl.style.width = Math.min(window.innerWidth - 30, Math.max(480, saved.width)) + 'px';
          if (saved.height) this.windowEl.style.height = Math.min(window.innerHeight - 100, Math.max(320, saved.height)) + 'px';
        }
      }
    } catch (_) {}
  }

  isTouchTap(e) {
    const type = (e && e.pointerType) || this._lastPointerType;
    return type === 'touch' && !e.shiftKey && !e.ctrlKey && !e.metaKey;
  }

  openListItem(file) {
    if (file.is_dir) {
      this.loadPath(file.path);
    } else {
      this.handleAction('preview', file.path, file.name);
    }
  }

  // A window opened while the screen was narrow has no position; give it its saved one back.
  restoreAfterWiden() {
    const narrow = isCompact();
    const widened = this._wasNarrow && !narrow;
    this._wasNarrow = narrow;
    if (widened && this.isPrimary && !this.isMaximized) this.restoreSavedBounds();
  }

  saveBounds() {
    if (this.isMaximized || !this.isPrimary) return;
    if (isCompact()) return;
    try {
      const rect = this.windowEl.getBoundingClientRect();
      localStorage.setItem(BOUNDS_KEY, JSON.stringify({
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      }));
    } catch (_) {}
  }

  bindEvents() {
    if (!this.windowEl) return;

    makeDraggable(this.windowEl, this.windowEl.querySelector('.os-window-header'), this.dockId);

    const activate = (e) => {
      bringToFront(this.windowEl);
      _activeFmInstance = this;
      this.windowEl.classList.add('active-window');
      document.querySelectorAll('.chassis-hero-box').forEach((el) => {
        try { el.blur(); } catch (_) {}
      });
      if (!e || !e.target || !e.target.closest('input:not([type="checkbox"]), textarea, select')) {
        this.ensureFocus();
      }
    };
    this.windowEl.addEventListener('mousedown', activate);
    this.windowEl.addEventListener('pointerdown', activate);

    this._onSaveBounds = () => this.saveBounds();
    this._wasNarrow = isCompact();
    this._onResize = () => {
      this.renderViewport();
      this.restoreAfterWiden();
    };
    if (this.isPrimary) {
      window.addEventListener('mouseup', this._onSaveBounds);
    }
    window.addEventListener('resize', this._onResize);

    // Controls
    const closeBtn = this.windowEl.querySelector('.close-btn');
    if (closeBtn) {
      const onClose = (e) => {
        if (e) { e.preventDefault(); e.stopPropagation(); }
        this.destroy();
      };
      closeBtn.addEventListener('click', onClose);
      closeBtn.addEventListener('touchend', onClose);
    }

    const minBtn = this.windowEl.querySelector('.min-btn');
    if (minBtn) {
      const onMin = (e) => {
        if (e) { e.preventDefault(); e.stopPropagation(); }
        this.minimize();
      };
      minBtn.addEventListener('click', onMin);
      minBtn.addEventListener('touchend', onMin);
    }

    const maxBtn = this.windowEl.querySelector('.max-btn');
    if (maxBtn) {
      let lastTouchTs = 0;
      const onMax = (e) => {
        if (e) {
          if (e.type === 'click' && Date.now() - lastTouchTs < 450) {
            e.preventDefault(); e.stopPropagation(); return;
          }
          if (e.type === 'touchend') lastTouchTs = Date.now();
          e.preventDefault(); e.stopPropagation();
        }
        this.toggleMaximize();
      };
      maxBtn.addEventListener('click', onMax);
      maxBtn.addEventListener('touchend', onMax);
    }

    // Navigation buttons
    this.backBtn?.addEventListener('click', () => this.goBack());
    this.fwdBtn?.addEventListener('click', () => this.goForward());
    this.upBtn?.addEventListener('click', () => this.goUp());

    // Quick Locations: a dropdown under the button on desktop, a bottom sheet on phones
    this.locationsBtn?.addEventListener('click', (e) => {
      e.stopPropagation();
      const places = [
        { icon: '📁', name: t('fm.loc_user_shares', 'User Shares'), path: '/mnt/user' },
        { icon: '⚙️', name: t('fm.loc_appdata', 'AppData'), path: '/mnt/user/appdata' },
        { icon: '💾', name: t('fm.loc_boot', 'Boot Flash'), path: '/boot' },
        { icon: '☁️', name: t('fm.loc_remotes', 'Cloud Remotes'), path: '/mnt/remotes' },
      ];
      (this.sidebarTree?.remotes || []).forEach((r) => {
        if (r.available !== false && r.is_mounted !== false) places.push({ icon: '☁️', name: r.name, path: r.path });
      });
      (this.sidebarTree?.pools || []).forEach((pool) => {
        if (pool.available !== false) places.push({ icon: pool.type === 'disk' ? '💽' : '⚡', name: pool.name, path: pool.path });
      });
      places.push({ icon: '🗑️', name: t('dock.recycle_bin', 'Recycle Bin'), path: '/mnt/user/.RecycleBin' });
      favorites().forEach((f) => places.push({ icon: '⭐', name: f.name, path: f.path, favorite: true }));
      const here = this.currentPath;
      const starred = isFavorite(here);
      places.push({
        icon: starred ? '☆' : '⭐',
        name: starred ? t('fm.fav_remove_here', 'Remove this folder from Favorites') : t('fm.fav_add_here', 'Add this folder to Favorites'),
        path: here,
        action: () => toggleFavorite(here),
      });

      const isPhone = isCompact();
      if (isPhone) {
        showBottomSheet({
          title: t('fm.quick_locations', 'Quick Locations'),
          subtitle: `Current: ${this.currentPath}`,
          items: places.map((pl) => ({ icon: pl.icon, label: pl.action ? pl.name : `${pl.name} (${pl.path})`, onClick: () => (pl.action ? pl.action() : this.loadPath(pl.path)) })),
        });
        return;
      }
      this.showLocationsMenu(this.locationsBtn, places);
    });

    // Hidden file upload input
    if (this.uploadInput) {
      this.uploadInput.addEventListener('change', async (e) => {
        const files = e.target.files;
        if (files && files.length > 0) {
          await this.uploadFiles(files);
          this.uploadInput.value = '';
        }
      });
    }

    // Mobile Floating Action Button (+)
    this.mobileFab?.addEventListener('click', (e) => {
      e.stopPropagation();
      const fabItems = [
        { icon: '📁', label: t('fm.new_folder', 'New Folder'), onClick: () => this.newFolderBtn?.click() },
        { icon: '⬆️', label: 'Upload File(s)', onClick: () => this.uploadInput?.click() },
      ];
      if (_clipboard && _clipboard.items && _clipboard.items.length > 0) {
        fabItems.push({
          icon: '📋',
          label: `Paste Here (${_clipboard.items.length} item${_clipboard.items.length > 1 ? 's' : ''})`,
          onClick: async () => {
            await executeTransferWithConflictCheck(_clipboard.items, this.currentPath, _clipboard.action || 'copy');
            if (_clipboard.action === 'move') _clipboard = { items: [], action: 'copy', sourceInstanceId: null };
            this.loadPath(this.currentPath);
            ZettEventBus.emit('fm:refresh');
          },
        });
      }
      fabItems.push(
        { icon: '🎬', label: t('fm.organize_media', 'Organize Media'), onClick: () => this.organizeBtn?.click() },
        { icon: '🔄', label: t('fm.refresh', 'Refresh'), onClick: () => this.loadPath(this.currentPath) }
      );
      showBottomSheet({
        title: 'Folder Actions',
        subtitle: this.currentPath,
        items: fabItems,
      });
    });

    // Refresh button
    this.refreshBtn?.addEventListener('click', () => this.loadPath(this.currentPath));

    // Search input & ZettAI Semantic Toggle
    if (this.aiSearchToggle) {
      this.aiSearchToggle.addEventListener('click', () => {
        this.aiSearchMode = !this.aiSearchMode;
        this.aiSearchToggle.classList.toggle('active', this.aiSearchMode);
        this.aiSearchToggle.style.color = this.aiSearchMode ? '#3bf58b' : '';
        this.aiSearchToggle.style.borderColor = this.aiSearchMode ? 'rgba(59,245,139,0.4)' : '';
        if (this.searchInput) {
          this.searchInput.placeholder = this.aiSearchMode
            ? t('ai.fm_placeholder', 'Ask AI (recipe, red car...)')
            : t('fm.search_placeholder', 'Search...');
          if (this.searchInput.value.trim()) {
            this.executeBackendSearch(this.searchInput.value);
          }
        }
      });
    }
    if (this.searchInput) {
      this.searchInput.addEventListener('input', (e) => this.handleSearchInput(e.target.value));
      this.searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.executeBackendSearch(e.target.value);
        } else if (e.key === 'Escape') {
          this.searchInput.value = '';
          this.handleSearchInput('');
          this.ensureFocus();
        }
      });
    }

    // New Window button
    this.newWinBtn?.addEventListener('click', () => {
      openNewFileManagerWindow(this.currentPath);
    });

    // New folder button
    this.newFolderBtn?.addEventListener('click', () => {
      const promptMsg = t('fm.prompt_new_folder', 'Enter new folder name:');
      showPromptToast('New Folder', promptMsg, '', (name) => {
        if (name) {
          api.post('/api/mkdir', { path: this.currentPath + '/' + name })
            .then(() => {
              this.loadPath(this.currentPath);
              ZettEventBus.emit('fm:refresh');
            })
            .catch((err) => showToast(err.message, 'error'));
        }
      });
    });

    // Organize media button
    this.organizeBtn?.addEventListener('click', () => {
      openMediaOrganizerModal(this.currentPath);
    });

    // View mode buttons
    this.btnViewList?.addEventListener('click', () => this.setViewMode('list'));
    this.btnViewCompact?.addEventListener('click', () => this.setViewMode('compact'));
    this.btnViewIcon?.addEventListener('click', () => this.setViewMode('icon'));

    // Auxiliary toolbar buttons
    this.btnTransfersToggle?.addEventListener('click', () => {
      if (this.transfersCockpit) {
        this.transfersCockpit.toggle();
        this.btnTransfersToggle.classList.toggle('active', this.transfersCockpit.isOpen);
      }
    });
    this.btnInspectorToggle?.addEventListener('click', () => {
      if (this.inspector) {
        this.inspector.toggle();
        this.btnInspectorToggle.classList.toggle('active', this.inspector.isVisible);
      }
    });

    // Path input and breadcrumbs
    if (this.pathInput) {
      const handlePathSubmit = () => {
        const val = this.pathInput.value.trim();
        if (val && val !== this.currentPath) {
          this.loadPath(val);
        }
      };

      this.pathInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.pathInput.blur();
          handlePathSubmit();
        }
      });

      this.pathInput.addEventListener('change', handlePathSubmit);

      if (this.breadcrumbs) {
        this.breadcrumbs.onclick = () => this.pathInput.focus();
      }
      this.pathInput.addEventListener('focus', () => {
        this.pathInput.style.color = 'var(--fg)';
        if (this.breadcrumbs) this.breadcrumbs.style.display = 'none';
      });
      this.pathInput.addEventListener('blur', () => {
        this.pathInput.style.color = 'transparent';
        if (this.breadcrumbs) this.breadcrumbs.style.display = 'flex';
        if (this.pathInput.value.trim() !== this.currentPath) {
          this.pathInput.value = this.currentPath;
        }
      });
    }

    // ResizeObserver on viewport for dynamic virtual scroll recalculation
    if (this.viewport && typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => {
        if (this.isOpen()) this.renderViewport();
      });
      this.resizeObserver.observe(this.viewport);
    }

    // Viewport scrolling
    if (this.viewport) {
      this.viewport.addEventListener('scroll', () => {
        this.renderViewport();
      }, { passive: true });

      this.viewport.addEventListener('click', (e) => {
        if (this._suppressNextViewportClick) {
          this._suppressNextViewportClick = false;
          return;
        }
        if (e.shiftKey || e.ctrlKey || e.metaKey) return;
        if (e.target === this.viewport || e.target === this.spacer || e.target === this.list) {
          this.clearSelection();
          this.ensureFocus();
        }
      });

      this.viewport.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        const itemEl = e.target.closest('.fm-row, .fm-grid-card');
        let itemFile = null;
        if (itemEl && itemEl.dataset.path) {
          const p = itemEl.dataset.path;
          itemFile = this.fileList.find((f) => f.path === p);
          if (itemFile && !this.selectedPaths.has(p)) {
            if (!e.ctrlKey && !e.metaKey && !e.shiftKey) {
              this.selectedPaths.clear();
            }
            this.selectedPaths.add(p);
            this.updateRowSelectionUI();
            this.updateSelectionToolbar();
          }
        }
        if (this.contextMenu) {
          this.contextMenu.show(e, itemFile);
        }
      });

      // Viewport & Subfolder Unified Drag & Drop Engine
      this.viewport.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = (e.altKey || window._activeDragPayload?.action === 'copy' || window.__zettActiveFmDrag?.action === 'copy') ? 'copy' : 'move';

        // Detect if hovering over a specific subfolder row or card
        const folderItem = e.target.closest('.fm-row, .fm-grid-card');
        const p = folderItem?.dataset?.path;
        const file = p ? this.fileList.find((f) => f.path === p) : null;
        const isDir = Boolean(file && file.is_dir && file.name !== '..');

        if (isDir && folderItem) {
          if (this._currentHoveredFolder !== folderItem) {
            if (this._currentHoveredFolder) {
              this._currentHoveredFolder.classList.remove('fm-drop-hover');
            }
            this._currentHoveredFolder = folderItem;
            folderItem.classList.add('fm-drop-hover');
          }
          this.viewport.classList.remove('fm-drop-hover');
        } else {
          if (this._currentHoveredFolder) {
            this._currentHoveredFolder.classList.remove('fm-drop-hover');
            this._currentHoveredFolder = null;
          }
          this.viewport.classList.add('fm-drop-hover');
        }
      });

      this.viewport.addEventListener('dragleave', (e) => {
        if (!this.viewport.contains(e.relatedTarget)) {
          this.viewport.classList.remove('fm-drop-hover');
          if (this._currentHoveredFolder) {
            this._currentHoveredFolder.classList.remove('fm-drop-hover');
            this._currentHoveredFolder = null;
          }
        }
      });

      this.viewport.addEventListener('drop', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.viewport.classList.remove('fm-drop-hover');
        const hoveredFolder = this._currentHoveredFolder;
        if (this._currentHoveredFolder) {
          this._currentHoveredFolder.classList.remove('fm-drop-hover');
          this._currentHoveredFolder = null;
        }

        // Determine target destination path: subfolder if dropped on one, otherwise currentPath
        const folderItem = hoveredFolder || e.target.closest('.fm-row, .fm-grid-card');
        const p = folderItem?.dataset?.path;
        const file = p ? this.fileList.find((f) => f.path === p) : null;
        const destPath = (file && file.is_dir && file.name !== '..') ? file.path : this.currentPath;

        // Extract payload with full multi-source fallback
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
          await executeTransferWithConflictCheck(payload.paths, destPath, action);
          window._activeDragPayload = null;
          window.__zettActiveFmDrag = null;
          ZettEventBus.emit('fm:refresh');
          return;
        }

        // Check recursive OS folder upload
        if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
          const entries = await extractDataTransferEntries(e.dataTransfer);
          if (entries && entries.length > 0) {
            await this.uploadExtractedEntries(entries, destPath);
            return;
          }
        }

        // File uploads from client OS
        if (!e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
        await this.uploadFiles(e.dataTransfer.files, destPath);
      });
    }

    // Single-Root Event Delegation on this.list
    if (this.list) {
      // Touch screens: a tap opens (like a phone's Files app); the mouse keeps
      // click-to-select and double-click-to-open.
      this.list.addEventListener('pointerdown', (e) => { this._lastPointerType = e.pointerType; }, { passive: true });
      this.list.addEventListener('click', (e) => {
        const actBtn = e.target.closest('.fm-act-btn');
        if (actBtn) {
          e.stopPropagation();
          const p = actBtn.dataset.path;
          const file = this.fileList.find((f) => f.path === p);
          this.handleAction(actBtn.dataset.act, p, file?.name || '');
          return;
        }

        const item = e.target.closest('.fm-row, .fm-grid-card');
        if (!item) return;
        const p = item.dataset.path;
        const file = this.fileList.find((f) => f.path === p);
        const touchTap = this.isTouchTap(e);
        if (!file || (file.name === '..' && !touchTap)) return;

        bringToFront(this.windowEl);
        _activeFmInstance = this;
        this.windowEl.classList.add('active-window');
        document.querySelectorAll('.chassis-hero-box').forEach((el) => {
          try { el.blur(); } catch (_) {}
        });

        const chk = e.target.closest('.fm-checkbox');
        const chkCell = e.target.closest('.fm-col-check');
        if (touchTap && !chk && !chkCell) {
          if (Date.now() - (this._touchOpenAt || 0) < 450) return; // second tap of a double-tap
          if (this.selectedPaths.size === 0 || file.name === '..') {
            this._touchOpenAt = Date.now();
            this.openListItem(file);
            return;
          }
          // While items are selected, a tap adds or removes one, like the checkbox.
          if (this.selectedPaths.has(file.path)) this.selectedPaths.delete(file.path);
          else this.selectedPaths.add(file.path);
          this.lastSelectedIndex = this.fileList.findIndex((f) => f.path === p);
          this.updateRowSelectionUI();
          this.updateSelectionToolbar();
          return;
        }
        if (chk || chkCell) {
          e.stopPropagation();
          const isSelected = this.selectedPaths.has(file.path);
          const shouldSelect = chk ? chk.checked : !isSelected;
          if (shouldSelect) {
            this.selectedPaths.add(file.path);
          } else {
            this.selectedPaths.delete(file.path);
          }
          const idx = this.fileList.findIndex((f) => f.path === p);
          this.lastSelectedIndex = idx;
          if (this.selectionAnchorIndex === -1) this.selectionAnchorIndex = idx;
          if (chk) { try { chk.blur(); } catch (_) {} }
          this.ensureFocus();
          this.updateRowSelectionUI();
          this.updateSelectionToolbar();
          return;
        }

        const idx = this.fileList.findIndex((f) => f.path === p);
        if (e.shiftKey) {
          if (this.selectionAnchorIndex === -1) {
            this.selectionAnchorIndex = (this.lastSelectedIndex !== -1) ? this.lastSelectedIndex : idx;
          }
          const start = Math.min(this.selectionAnchorIndex, idx);
          const end = Math.max(this.selectionAnchorIndex, idx);
          if (!e.ctrlKey && !e.metaKey) {
            this.selectedPaths.clear();
          }
          for (let j = start; j <= end; j++) {
            if (this.fileList[j] && this.fileList[j].name !== '..') {
              this.selectedPaths.add(this.fileList[j].path);
            }
          }
          this.lastSelectedIndex = idx;
        } else if (e.ctrlKey || e.metaKey) {
          if (this.selectedPaths.has(file.path)) {
            this.selectedPaths.delete(file.path);
          } else {
            this.selectedPaths.add(file.path);
          }
          this.lastSelectedIndex = idx;
          this.selectionAnchorIndex = idx;
        } else {
          this.selectedPaths.clear();
          this.selectedPaths.add(file.path);
          this.lastSelectedIndex = idx;
          this.selectionAnchorIndex = idx;
        }
        this.ensureFocus();
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      });

      this.list.addEventListener('dblclick', (e) => {
        if (this._lastPointerType === 'touch') return; // the tap already opened it
        const item = e.target.closest('.fm-row, .fm-grid-card');
        if (!item) return;
        const p = item.dataset.path;
        const file = this.fileList.find((f) => f.path === p);
        if (!file) return;
        this.openListItem(file);
      });

      // Drag start & end from this window
      this.list.addEventListener('dragstart', (e) => {
        const item = e.target.closest('.fm-row, .fm-grid-card');
        if (!item) return;
        const p = item.dataset.path;
        const file = this.fileList.find((f) => f.path === p);
        if (!file || file.name === '..') {
          e.preventDefault();
          return;
        }

        // If dragging an unselected item, select it exclusively
        if (!this.selectedPaths.has(file.path)) {
          this.selectedPaths.clear();
          this.selectedPaths.add(file.path);
          const idx = this.fileList.findIndex((f) => f.path === p);
          this.lastSelectedIndex = idx;
          this.selectionAnchorIndex = idx;
          this.updateRowSelectionUI();
          this.updateSelectionToolbar();
        }

        const paths = Array.from(this.selectedPaths);
        const payload = {
          paths,
          action: e.altKey ? 'copy' : 'move',
          sourcePath: this.currentPath,
          sourceInstanceId: this.id,
          timestamp: Date.now(),
        };
        window._activeDragPayload = payload;
        window.__zettActiveFmDrag = payload;

        try {
          e.dataTransfer.setData('application/json', JSON.stringify(payload));
          e.dataTransfer.setData('text/plain', paths.join('\n'));
          e.dataTransfer.effectAllowed = 'copyMove';
        } catch (_) {}

        try {
          const ghost = document.createElement('div');
          ghost.className = 'fm-drag-ghost';
          ghost.innerHTML = `<span aria-hidden="true">📁</span> <span class="fm-drag-ghost-count">${paths.length}</span>`;
          document.body.appendChild(ghost);
          if (e.dataTransfer.setDragImage) {
            e.dataTransfer.setDragImage(ghost, 15, 15);
          }
          setTimeout(() => ghost.remove(), 0);
        } catch (_) {}
      });

      this.list.addEventListener('dragend', () => {
        const payload = window.__zettActiveFmDrag;
        window._activeDragPayload = null;
        setTimeout(() => {
          if (window.__zettActiveFmDrag === payload) {
            window.__zettActiveFmDrag = null;
          }
        }, 2500);
        document.querySelectorAll('.fm-drop-hover, .fm-tree-drop-hover').forEach((el) => {
          el.classList.remove('fm-drop-hover', 'fm-tree-drop-hover');
        });
      });
    }

    // Column Header Sorting
    this.colName?.addEventListener('click', () => this.sortBy('name'));
    this.colSize?.addEventListener('click', () => this.sortBy('size'));
    this.colType?.addEventListener('click', () => this.sortBy('type'));
    this.colMtime?.addEventListener('click', () => this.sortBy('mtime'));
    for (const col of [this.colName, this.colSize, this.colType, this.colMtime]) {
      col?.addEventListener('keydown', (ev) => {
        const e = /** @type {KeyboardEvent} */ (ev);
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          /** @type {HTMLElement} */ (col).click(); // headers sort by keyboard too (NUX-7)
        }
      });
    }
    this.updateSortHeaderUI();

    // Bulk Delete
    this.bulkDeleteBtn?.addEventListener('click', () => {
      const count = this.selectedPaths.size;
      if (count === 0) return;
      const confirmMsg = binConfirmText(Array.from(this.selectedPaths));
      showConfirmToast(t('common.confirm', 'Confirm Action'), confirmMsg, async () => {
        const targets = Array.from(this.selectedPaths);
        this.selectedPaths.clear();
        this.lastSelectedIndex = -1;
        this.selectionAnchorIndex = -1;
        await this.deleteWithProgress(targets);
      });
    });

    // Move to…: pick a folder, then move in the background with progress
    this.bulkMoveBtn?.addEventListener('click', () => {
      const paths = Array.from(this.selectedPaths);
      if (paths.length === 0) return;
      if (typeof window.openFolderBrowser !== 'function') {
        _clipboard = { items: paths, action: 'move', sourceInstanceId: this.id };
        showToast(t('fm.cut_items_toast', `Selected ${paths.length} item(s) to move. Navigate to destination folder and click Paste.`), 'info');
        return;
      }
      window.openFolderBrowser(this.currentPath, (dest) => {
        const target = String(dest || '').replace(/\/+$/, '') || '/';
        executeTransferWithConflictCheck(paths, target, 'move');
      });
    });

    // Share link (one item)
    this.bulkShareBtn?.addEventListener('click', () => {
      const [p] = Array.from(this.selectedPaths);
      if (p) openShareLinkModal(p, p.split('/').pop(), this.bulkShareBtn);
    });

    // Bulk Zip / Download
    this.bulkZipBtn?.addEventListener('click', () => {
      const paths = Array.from(this.selectedPaths);
      if (paths.length === 0) return;
      if (paths.length === 1) {
        this.handleAction('download', paths[0], paths[0].split('/').pop());
        return;
      }
      showToast(t('fm.downloading_items', 'Downloading {count, plural, one {# item} other {# items}}…', { count: paths.length }), 'info');
      const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';
      const qs = paths.map((p) => `paths=${encodeURIComponent(p)}`).join('&');
      window.open(`/api/fs/download-zip?${qs}`, '_blank');
    });

    // Clear Selection
    this.clearSelBtn?.addEventListener('click', () => {
      this.selectedPaths.clear();
      this.lastSelectedIndex = -1;
      this.selectionAnchorIndex = -1;
      this.updateRowSelectionUI();
      this.updateSelectionToolbar();
      this.ensureFocus();
    });

    // Select All Checkbox
    this.selectAllCheckbox?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (this.selectAllCheckbox.checked) {
        this.fileList.forEach((f) => {
          if (f.name !== '..') this.selectedPaths.add(f.path);
        });
        this.lastSelectedIndex = this.fileList.length - 1;
        this.selectionAnchorIndex = (this.fileList[0]?.name === '..') ? 1 : 0;
      } else {
        this.selectedPaths.clear();
        this.lastSelectedIndex = -1;
        this.selectionAnchorIndex = -1;
      }
      this.updateRowSelectionUI();
      this.updateSelectionToolbar();
      this.ensureFocus();
    });

    const headerCheckCol = this.windowEl.querySelector('.fm-header-row .fm-col-check');
    if (headerCheckCol) {
      headerCheckCol.addEventListener('click', (e) => {
        if (e.target !== this.selectAllCheckbox && this.selectAllCheckbox) {
          e.stopPropagation();
          this.selectAllCheckbox.checked = !this.selectAllCheckbox.checked;
          this.selectAllCheckbox.dispatchEvent(new Event('click'));
        }
      });
    }
  }

  ensureFocus() {
    if (
      document.activeElement &&
      document.activeElement !== document.body &&
      document.activeElement !== this.windowEl &&
      this.windowEl &&
      this.windowEl.contains(document.activeElement) &&
      (document.activeElement.tagName === 'INPUT' ||
       document.activeElement.tagName === 'TEXTAREA' ||
       document.activeElement.tagName === 'SELECT' ||
       document.activeElement.isContentEditable) &&
      document.activeElement.type !== 'checkbox' &&
      document.activeElement.type !== 'radio'
    ) {
      return;
    }
    document.querySelectorAll('.chassis-hero-box').forEach((el) => {
      try { el.blur(); } catch (_) {}
    });
    if (this.viewport && typeof this.viewport.focus === 'function') {
      try {
        this.viewport.focus({ preventScroll: true });
      } catch (_) {}
    }
  }

  open(targetPath) {
    if (!this.viewport || !this.list || !this.spacer) {
      this.bindElements();
    }
    if (!this.resizeObserver && this.viewport && typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => {
        if (this.isOpen()) this.renderViewport();
      });
      this.resizeObserver.observe(this.viewport);
    }
    if (window.DockManager) {
      if (!window.DockManager.windows[this.dockId]) {
        window.DockManager.register(this.dockId, this.windowEl, '#i-storage', this.getTitle());
      }
      window.DockManager.restore(this.dockId);
    }
    bringToFront(this.windowEl);
    _activeFmInstance = this;
    this.windowEl.classList.remove('window-minimized');
    this.windowEl.classList.add('active-window');
    this.windowEl.style.removeProperty('display');
    this.windowEl.style.setProperty('display', 'flex', 'important');
    this.placeIfUnplaced();
    this.loadPath(targetPath || this.currentPath);
    if (this.sidebarTree) {
      this.sidebarTree.refresh();
    }

    // Unfocus any desktop icon that was clicked
    document.querySelectorAll('.chassis-hero-box').forEach((el) => {
      try { el.blur(); } catch (_) {}
    });
    this.ensureFocus();
    setTimeout(() => this.ensureFocus(), 40);
  }

  minimize() {
    if (window.DockManager) {
      if (!window.DockManager.windows[this.dockId]) {
        window.DockManager.register(this.dockId, this.windowEl, '#i-storage', this.getTitle());
      }
      window.DockManager.minimize(this.dockId);
    }
    this.windowEl.classList.add('window-minimized');
    this.windowEl.style.setProperty('display', 'none', 'important');
  }

  toggleMaximize() {
    if (!this.isMaximized) {
      this.preMaxBounds = {
        left: this.windowEl.style.left,
        top: this.windowEl.style.top,
        width: this.windowEl.style.width,
        height: this.windowEl.style.height,
      };
      this.windowEl.style.left = '16px';
      this.windowEl.style.top = '56px';
      this.windowEl.style.width = 'calc(100vw - 32px)';
      this.windowEl.style.height = 'calc(100vh - 128px)';
      this.isMaximized = true;
    } else {
      if (this.preMaxBounds) {
        this.windowEl.style.left = this.preMaxBounds.left;
        this.windowEl.style.top = this.preMaxBounds.top;
        this.windowEl.style.width = this.preMaxBounds.width;
        this.windowEl.style.height = this.preMaxBounds.height;
      }
      this.isMaximized = false;
    }
  }

  destroy() {
    if (this._crumbObserver) {
      this._crumbObserver.disconnect();
      this._crumbObserver = null;
    }
    if (this.abortController) {
      try { this.abortController.abort(); } catch (_) {}
      this.abortController = null;
    }
    if (this.searchAbortController) {
      try { this.searchAbortController.abort(); } catch (_) {}
      this.searchAbortController = null;
    }
    if (this.resizeObserver) {
      try { this.resizeObserver.disconnect(); } catch (_) {}
      this.resizeObserver = null;
    }
    if (this._onSaveBounds) {
      window.removeEventListener('mouseup', this._onSaveBounds);
      this._onSaveBounds = null;
    }
    if (this._onResize) {
      window.removeEventListener('resize', this._onResize);
      this._onResize = null;
    }
    if (this._activeDropdownMenu) {
      try {
        this._activeDropdownMenu.remove();
        if (this._activeDropdownClose) {
          document.removeEventListener('pointerdown', this._activeDropdownClose);
        }
      } catch (_) {}
      this._activeDropdownMenu = null;
      this._activeDropdownClose = null;
    }

    if (this.isPrimary) {
      this.windowEl?.classList.add('window-minimized');
      this.windowEl?.style.setProperty('display', 'none', 'important');
      this.history = [];
      this.historyIndex = -1;
      this.selectedPaths.clear();
      this.lastSelectedIndex = -1;
      this.selectionAnchorIndex = -1;
      if (window.DockManager) window.DockManager.unregister('fm');
    } else {
      if (this.windowEl) {
        this.windowEl.remove();
        this.windowEl = null;
      }
      _fmInstances.delete(this.id);
      if (window.DockManager) {
        window.DockManager.unregister(this.dockId);
      }
      this.viewport = null;
      this.list = null;
      this.spacer = null;
    }

    if (_activeFmInstance === this) {
      _activeFmInstance = _fmInstances.get('file-manager-window') || _fmInstances.values().next().value || null;
    }
  }

  goBack() {
    if (this.historyIndex > 0) {
      this.historyIndex--;
      const prevPath = this.history[this.historyIndex];
      return this.loadPath(prevPath, true);
    }
    return Promise.resolve();
  }

  goForward() {
    if (this.historyIndex < this.history.length - 1) {
      this.historyIndex++;
      const nextPath = this.history[this.historyIndex];
      return this.loadPath(nextPath, true);
    }
    return Promise.resolve();
  }

  goUp() {
    let parent = this.currentPath.substring(0, this.currentPath.lastIndexOf('/'));
    if (!parent) {
      if (this.currentPath !== '/mnt' && this.currentPath !== '/') parent = '/mnt';
      else parent = this.currentPath;
    }
    return this.loadPath(parent);
  }

  updateNavButtons() {
    if (this.backBtn) this.backBtn.disabled = this.historyIndex <= 0;
    if (this.fwdBtn) this.fwdBtn.disabled = this.historyIndex >= this.history.length - 1;
    if (this.upBtn) this.upBtn.disabled = (this.currentPath === '/' || this.currentPath === '');
  }

  handleSearchInput(val) {
    this.searchQuery = (val || '').trim();
    if (!this.searchQuery) {
      this.isSearching = false;
      this.fileList = [...this.rawFileList];
    } else {
      this.isSearching = true;
      const q = this.searchQuery.toLowerCase();
      this.fileList = this.rawFileList.filter((f) => f.name === '..' || f.name.toLowerCase().includes(q));
    }
    this.renderViewport();
  }

  async executeBackendSearch(query) {
    const q = (query || '').trim();
    if (!q) return;
    if (this.searchAbortController) {
      this.searchAbortController.abort();
    }
    this.searchAbortController = new AbortController();
    const useAi = Boolean(this.aiSearchMode || q.startsWith('?') || /^ai:/i.test(q));
    const cleanQ = q.replace(/^(\?|ai:\s*)/i, '').trim() || q;
    try {
      if (useAi) {
        showToast(t('toast.zettai_searching', '✨ ZettAI searching "{cleanQ}"...', { cleanQ: cleanQ }), 'info');
        const aiRes = await api.post('/api/media/search', {
          query: cleanQ,
          path_prefix: this.currentPath && this.currentPath !== '/' ? this.currentPath : null,
          limit: 50,
        });
        const items = (aiRes?.results || []).map((r) => ({
          name: r.file_name || (r.file_path ? r.file_path.split('/').pop() : 'file'),
          path: r.file_path,
          is_dir: false,
          size: r.file_size || 0,
          ext: r.ext || '',
          ai_score: r.score,
          ai_excerpt: r.excerpt,
          ai_file_id: r.file_id,
        }));
        this.fileList = items;
        this.isSearching = true;
        this.renderViewport();
        showToast(t('fm.search_results', 'Found {count, plural, one {# item} other {# items}}', { count: items.length }), 'success');
        if (aiRes?.degraded) {
          showToast(t('ai.search_degraded', "The AI search model didn't answer, so these results match words only. Try again in a moment."), 'warning');
        }
        return;
      }
      showToast(t('fm.searching', `Searching for "${q}"...`), 'info');
      const res = await api.get(`/api/fs/search?path=${encodeURIComponent(this.currentPath)}&q=${encodeURIComponent(q)}&limit=200`, {
        signal: this.searchAbortController.signal,
      });
      if (res && Array.isArray(res.items)) {
        this.fileList = res.items;
        this.isSearching = true;
        this.renderViewport();
        showToast(t('fm.search_results', 'Found {count, plural, one {# item} other {# items}}', { count: res.items.length }), 'success');
        // PERF-25: a sleeping disk is searched through the AI index only, and a huge walk stops early
        if (res.partial === 'asleep') {
          showToast(t('fm.search_partial_asleep', 'A disk here is asleep, so only files the AI index knows about are shown.'), 'info');
        } else if (res.partial === 'capped') {
          showToast(t('fm.search_partial_capped', 'This folder is very large, so the search stopped early. Search a smaller folder to see everything.'), 'info');
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        showToast(t('toast.search_error', 'Search error: {error}', { error: err.message }), 'error');
      }
    }
  }

  scrollIndexIntoView(idx) {
    if (!this.viewport || idx < 0) return;
    if (this.viewMode === 'icon') {
      const targetItem = this.fileList[idx];
      if (targetItem) {
        const card = this.viewport.querySelector(`.fm-grid-card[data-path="${CSS.escape(targetItem.path)}"]`);
        if (card && typeof card.scrollIntoView === 'function') {
          card.scrollIntoView({ block: 'nearest' });
          return;
        }
      }
    }
    const targetScroll = idx * ROW_HEIGHT;
    const currentScroll = this.viewport.scrollTop;
    const viewportHeight = this.viewport.clientHeight || 400;

    if (targetScroll < currentScroll) {
      this.viewport.scrollTop = targetScroll;
    } else if (targetScroll + ROW_HEIGHT > currentScroll + viewportHeight) {
      this.viewport.scrollTop = targetScroll + ROW_HEIGHT - viewportHeight;
    }
  }

  setViewMode(mode) {
    if (this.viewMode === mode) return;
    this.viewMode = mode;
    try {
      localStorage.setItem('zettnas_fm_view_mode', mode);
    } catch (_) {}

    if (this.windowEl) {
      this.windowEl.classList.toggle('fm-mode-icon', mode === 'icon');
      this.windowEl.classList.toggle('fm-mode-compact', mode === 'compact');
    }
    if (this.btnViewList) {
      this.btnViewList.classList.toggle('active', mode === 'list');
    }
    if (this.btnViewCompact) {
      this.btnViewCompact.classList.toggle('active', mode === 'compact');
    }
    if (this.btnViewIcon) {
      this.btnViewIcon.classList.toggle('active', mode === 'icon');
    }

    // Synchronize view mode across all open FM instances
    for (const inst of _fmInstances.values()) {
      if (inst !== this && inst.viewMode !== mode) {
        inst.viewMode = mode;
        if (inst.windowEl) {
          inst.windowEl.classList.toggle('fm-mode-icon', mode === 'icon');
          inst.windowEl.classList.toggle('fm-mode-compact', mode === 'compact');
        }
        if (inst.btnViewList) inst.btnViewList.classList.toggle('active', mode === 'list');
        if (inst.btnViewCompact) inst.btnViewCompact.classList.toggle('active', mode === 'compact');
        if (inst.btnViewIcon) inst.btnViewIcon.classList.toggle('active', mode === 'icon');
        inst.renderViewport();
      }
    }

    this.renderViewport();
    this.ensureFocus();
  }

  getGridColumnCount() {
    if (this.viewMode !== 'icon' || !this.viewport) return 1;
    const cards = this.viewport.querySelectorAll('.fm-grid-card');
    if (cards.length >= 2) {
      const firstTop = cards[0].offsetTop;
      for (let i = 1; i < cards.length; i++) {
        if (cards[i].offsetTop > firstTop) {
          return i;
        }
      }
      return cards.length;
    }
    return 1;
  }

  updateSelectionToolbar() {
    if (!this.selectionBar || !this.selectedCount) return;
    const count = this.selectedPaths.size;
    if (count > 0) {
      this.selectionBar.style.display = 'flex';
      let totalBytes = 0;
      this.fileList.forEach((f) => {
        if (this.selectedPaths.has(f.path) && !f.is_dir && typeof f.size === 'number') {
          totalBytes += f.size;
        }
      });
      const label = t('fm.selected_count', '{count} selected', { count: count });
      this.selectedCount.innerHTML = escapeHtml(label) + (totalBytes > 0 ? `<span class="fm-sel-size"> · ${escapeHtml(formatBytes(totalBytes))}</span>` : '');
      if (this.bulkShareBtn) this.bulkShareBtn.hidden = count !== 1; // a share link is for one item
      if (this.bulkDeleteBtn) {
        const del = count > 1 ? t('fm.bulk_delete', 'Delete ({count})', { count: count }) : t('fm.delete', 'Delete');
        this.bulkDeleteBtn.title = del;
        this.bulkDeleteBtn.setAttribute('aria-label', del);
      }
    } else {
      this.selectionBar.style.display = 'none';
    }
  }

  updateRowSelectionUI() {
    if (!this.viewport) return;
    const items = this.viewport.querySelectorAll('.fm-row, .fm-grid-card');
    items.forEach((r) => {
      const p = r.dataset.path;
      const isSel = Boolean(p && this.selectedPaths.has(p));
      if (isSel) {
        r.classList.add('selected');
        r.setAttribute('tabindex', '0');
        r.setAttribute('aria-selected', 'true');
      } else {
        r.classList.remove('selected');
        r.setAttribute('tabindex', '-1');
        r.setAttribute('aria-selected', 'false');
      }
      const chk = r.querySelector('.fm-row-checkbox, .fm-card-checkbox');
      if (chk) chk.checked = isSel;

      if (_clipboard && _clipboard.action === 'move' && _clipboard.items && _clipboard.items.includes(p)) {
        r.classList.add('fm-cut-pending');
      } else {
        r.classList.remove('fm-cut-pending');
      }
    });

    if (this.selectAllCheckbox) {
      const selectableFiles = this.fileList.filter((f) => f.name !== '..');
      const totalSelectable = selectableFiles.length;
      const count = this.selectedPaths.size;
      if (totalSelectable > 0 && count === totalSelectable) {
        this.selectAllCheckbox.checked = true;
        this.selectAllCheckbox.indeterminate = false;
      } else if (count > 0) {
        this.selectAllCheckbox.checked = false;
        this.selectAllCheckbox.indeterminate = true;
      } else {
        this.selectAllCheckbox.checked = false;
        this.selectAllCheckbox.indeterminate = false;
      }
    }
    if (this.inspector && this.inspector.isVisible) {
      this.inspector.update();
    }
  }

  renderBreadcrumbs() {
    if (!this.breadcrumbs) return;
    this.breadcrumbs.innerHTML = '';
    const parts = this.currentPath.split('/').filter(Boolean);

    const addSpan = (text, p, isLast) => {
      const span = document.createElement('span');
      span.textContent = text;
      if (isLast) span.classList.add('fm-crumb-last');
      span.style.padding = '2px 4px';
      span.style.borderRadius = '4px';
      span.style.cursor = isLast ? 'text' : 'pointer';
      span.style.color = isLast ? 'var(--accent-cyan, #0ea5e9)' : 'var(--fg)';
      span.style.fontWeight = isLast ? 'bold' : 'normal';
      span.style.fontFamily = 'monospace';
      span.style.whiteSpace = 'nowrap';
      span.style.flexShrink = '0';

      if (!isLast) {
        span.onmouseover = () => {
          span.style.background = 'rgba(255,255,255,0.1)';
          span.style.textDecoration = 'underline';
        };
        span.onmouseout = () => {
          span.style.background = 'transparent';
          span.style.textDecoration = 'none';
        };
        span.onclick = (e) => {
          e.stopPropagation();
          let targetPath = p;
          if (targetPath === '/' && (!window._fmRoots || !window._fmRoots.includes('/'))) {
            targetPath = (window._fmRoots && window._fmRoots.includes('/mnt'))
              ? '/mnt'
              : (window._fmRoots ? window._fmRoots[0] : '/mnt/user');
          }
          this.loadPath(targetPath);
        };
      }

      // Allow dropping into breadcrumb path segments
      span.className = (span.className ? span.className + ' ' : '') + 'fm-crumb';
      span.ondragover = (e) => {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = (e.altKey || window._activeDragPayload?.action === 'copy') ? 'copy' : 'move';
        span.classList.add('fm-crumb-drop-hover');
      };
      span.ondragleave = (e) => {
        e.preventDefault();
        span.classList.remove('fm-crumb-drop-hover');
      };
      span.ondrop = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        span.classList.remove('fm-crumb-drop-hover');
        const targetPath = p.replace(/\/+$/, '') || '/';

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
          await executeTransferWithConflictCheck(payload.paths, targetPath, action);
          window._activeDragPayload = null;
          window.__zettActiveFmDrag = null;
          ZettEventBus.emit('fm:refresh');
          return;
        }

        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          await this.uploadFiles(e.dataTransfer.files, targetPath);
        }
      };
      this.breadcrumbs.appendChild(span);
    };

    const addSep = () => {
      const sep = document.createElement('span');
      sep.textContent = '/';
      sep.className = 'fm-crumb-sep';
      sep.style.color = 'var(--muted)';
      sep.style.fontFamily = 'monospace';
      sep.style.margin = '0 2px';
      this.breadcrumbs.appendChild(sep);
    };

    // Draws the path with `hidden` folders after the first one folded into a "..." pill
    const draw = (hidden) => {
      this.breadcrumbs.innerHTML = '';
      if (parts.length === 0) {
        addSpan('/', '/', true);
        return;
      }
      addSpan('/', '/', false);
      parts.forEach((part, i) => {
        const isLast = i === parts.length - 1;
        if (i >= 1 && i <= hidden) {
          if (i === 1) {
            const ellipsis = document.createElement('span');
            ellipsis.textContent = '...';
            ellipsis.className = 'fm-breadcrumb-ellipsis';
            ellipsis.style.cssText = 'padding: 1px 5px; border-radius: 4px; background: rgba(255,255,255,0.08); cursor: pointer; font-size: var(--zn-fs-xs); margin: 0 2px;';
            ellipsis.title = t('ui.show_intermediate_folders', 'Show intermediate folders');
            ellipsis.onclick = (e) => {
              e.stopPropagation();
              this.showBreadcrumbsDropdown(ellipsis, parts, 1, hidden + 1);
            };
            this.breadcrumbs.appendChild(ellipsis);
            addSep();
          }
          return;
        }
        addSpan(part, '/' + parts.slice(0, i + 1).join('/') + '/', isLast);
        if (!isLast) addSep();
      });
    };

    // Show the whole path; fold middle folders only while it does not fit
    const fit = () => {
      draw(0);
      const box = this.breadcrumbs;
      if (!box.clientWidth) return; // not laid out yet: the resize observer fits it later
      for (let hidden = 1; hidden <= parts.length - 2 && box.scrollWidth > box.clientWidth; hidden++) {
        draw(hidden);
      }
    };
    this._fitBreadcrumbs = fit;
    fit();

    if (!this._crumbObserver && typeof ResizeObserver !== 'undefined') {
      let lastWidth = 0;
      this._crumbObserver = new ResizeObserver(() => {
        const w = this.breadcrumbs?.clientWidth || 0;
        if (w !== lastWidth) {
          lastWidth = w;
          this._fitBreadcrumbs?.();
        }
      });
      this._crumbObserver.observe(this.breadcrumbs);
    }
  }

  /** Desktop Quick Locations: a keyboard-friendly menu anchored under the button. */
  showLocationsMenu(anchorEl, places) {
    const old = document.getElementById('fm-locations-menu');
    if (old) {
      old._close?.();
      if (old._anchor === anchorEl) return; // a second click closes it
    }
    const menu = document.createElement('div');
    menu.id = 'fm-locations-menu';
    menu.className = 'fm-loc-menu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', t('fm.quick_locations', 'Quick Locations'));
    // Only the closest place is the current one (/mnt/user/appdata, not also /mnt/user)
    const currentPath = closestPath(places.filter((pl) => !pl.action).map((pl) => pl.path), this.currentPath);
    menu.innerHTML = places.map((pl, i) => {
      const current = !pl.action && pl.path === currentPath;
      const sep = (pl.favorite && !places[i - 1]?.favorite) || (pl.action && i > 0) ? '<div class="fm-loc-sep" role="separator"></div>' : '';
      return `${sep}<button type="button" class="fm-loc-item${current ? ' is-current' : ''}${pl.action ? ' is-action' : ''}" role="menuitem" data-idx="${i}" title="${escapeHtml(pl.path)}">
        <span class="fm-loc-icon" aria-hidden="true">${pl.icon}</span>
        <span class="fm-loc-text"><span class="fm-loc-name">${escapeHtml(pl.name)}</span>${pl.action ? '' : `<span class="fm-loc-path">${escapeHtml(pl.path)}</span>`}</span>
        ${current ? '<span class="fm-loc-check" aria-hidden="true">✓</span>' : ''}
      </button>`;
    }).join('');
    document.body.appendChild(menu);
    menu._anchor = anchorEl;
    anchorEl.setAttribute('aria-expanded', 'true');

    const r = anchorEl.getBoundingClientRect();
    const w = menu.offsetWidth;
    const h = menu.offsetHeight;
    menu.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
    menu.style.top = `${r.bottom + 6 + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 6) : r.bottom + 6}px`;

    const items = Array.from(menu.querySelectorAll('.fm-loc-item'));
    const close = (refocus = false) => {
      document.removeEventListener('pointerdown', onOutside, true);
      document.removeEventListener('keydown', onKey, true);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('blur', onResize);
      anchorEl.setAttribute('aria-expanded', 'false');
      menu.remove();
      if (refocus) anchorEl.focus();
    };
    const onOutside = (ev) => {
      if (!menu.contains(ev.target) && ev.target !== anchorEl) close();
    };
    const onResize = () => close();
    const onKey = (ev) => {
      const i = items.indexOf(document.activeElement);
      if (ev.key === 'Escape') {
        ev.preventDefault();
        ev.stopPropagation();
        close(true);
      } else if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        const step = ev.key === 'ArrowDown' ? 1 : -1;
        items[(i + step + items.length) % items.length]?.focus();
      } else if (ev.key === 'Home' || ev.key === 'End') {
        ev.preventDefault();
        (ev.key === 'Home' ? items[0] : items[items.length - 1])?.focus();
      } else if ((ev.key === 'Enter' || ev.key === ' ') && i >= 0) {
        // The explorer has its own Enter shortcut; the menu takes the key first
        ev.preventDefault();
        ev.stopPropagation();
        items[i].click();
      } else if (ev.key === 'Tab') {
        close();
      }
    };
    menu._close = () => close();
    menu.addEventListener('click', (ev) => {
      const item = ev.target instanceof Element ? ev.target.closest('.fm-loc-item') : null;
      if (!item) return;
      const pl = places[Number(item.dataset.idx)];
      close();
      if (pl?.action) pl.action();
      else if (pl) this.loadPath(pl.path);
    });
    document.addEventListener('pointerdown', onOutside, true);
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', onResize);
    window.addEventListener('blur', onResize);
    (menu.querySelector('.is-current') || items[0])?.focus({ preventScroll: true });
  }

  showBreadcrumbsDropdown(anchorEl, parts, from = 1, to = parts.length - 2) {
    let menu = document.getElementById('fm-breadcrumbs-dropdown');
    if (menu) { menu.remove(); return; }
    menu = document.createElement('div');
    menu.id = 'fm-breadcrumbs-dropdown';
    menu.className = 'os-context-menu';
    menu.style.cssText = 'position: fixed; z-index: 10000; background: rgba(18,25,35,0.95); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; padding: 4px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); backdrop-filter: blur(12px); font-size: var(--zn-fs-xs); font-family: monospace; max-height: 200px; overflow-y: auto;';

    for (let i = from; i < to; i++) {
      const segPath = '/' + parts.slice(0, i + 1).join('/');
      const item = document.createElement('div');
      item.className = 'ctx-item';
      item.style.cssText = 'padding: 4px 8px; border-radius: 4px; cursor: pointer; color: #cbd5e1; display: flex; align-items: center; gap: 6px;';
      item.innerHTML = `<span aria-hidden="true">📁</span> <span>${escapeHtml(parts[i])}</span>`;
      item.onmouseover = () => { item.style.background = 'rgba(255,255,255,0.1)'; };
      item.onmouseout = () => { item.style.background = 'transparent'; };
      item.onclick = (e) => {
        e.stopPropagation();
        menu.remove();
        this.loadPath(segPath);
      };
      menu.appendChild(item);
    }

    document.body.appendChild(menu);
    const rect = anchorEl.getBoundingClientRect();
    menu.style.left = `${rect.left}px`;
    menu.style.top = `${rect.bottom + 4}px`;

    const closeMenu = (e) => {
      if (!menu.contains(e.target) && e.target !== anchorEl) {
        menu.remove();
        document.removeEventListener('pointerdown', closeMenu);
        if (this._activeDropdownMenu === menu) {
          this._activeDropdownMenu = null;
          this._activeDropdownClose = null;
        }
      }
    };
    this._activeDropdownMenu = menu;
    this._activeDropdownClose = closeMenu;
    setTimeout(() => document.addEventListener('pointerdown', closeMenu), 50);
  }

  async loadPath(path, isNavigatingHistory = false, keepSelection = false) {
    if (this.abortController) {
      try { this.abortController.abort(); } catch (_) {}
    }
    this.abortController = new AbortController();

    try {
      this._lastLoadTs = Date.now();
      const res = await api.get(`/api/browse?path=${encodeURIComponent(path)}&dirs_only=0`, {
        signal: this.abortController.signal,
      });
      this.currentPath = res.current;
      if (this.isPrimary) {
        try { localStorage.setItem('zettnas_fm_last_path', this.currentPath); } catch (_) {}
      }

      // History update
      if (!isNavigatingHistory) {
        if (this.historyIndex === -1) {
          this.history = [this.currentPath];
          this.historyIndex = 0;
        } else if (this.history[this.historyIndex] !== this.currentPath) {
          if (this.historyIndex < this.history.length - 1) {
            this.history = this.history.slice(0, this.historyIndex + 1);
          }
          this.history.push(this.currentPath);
          this.historyIndex = this.history.length - 1;
        }
      }
      this.updateNavButtons();

      if (res.roots && Array.isArray(res.roots)) {
        window._fmRoots = res.roots;
        const datalist = this.windowEl.querySelector('datalist');
        if (datalist && datalist.dataset.populated !== res.roots.join(',')) {
          datalist.dataset.populated = res.roots.join(',');
          datalist.replaceChildren(...[...res.roots, `${res.current}/.RecycleBin`].map((v) => {
            const opt = document.createElement('option');
            opt.value = v;
            return opt;
          }));
        }
      }

      const shouldRetain = Boolean((this._retainingRefresh || keepSelection) && this.currentPath === res.current && this.selectedPaths.size > 0);
      this._retainingRefresh = false;
      if (shouldRetain) {
        const existingPaths = new Set((res.dirs || []).map((f) => f.path));
        const retained = new Set();
        this.selectedPaths.forEach((p) => {
          if (existingPaths.has(p)) retained.add(p);
        });
        this.selectedPaths = retained;
      } else {
        this.selectedPaths.clear();
        this.lastSelectedIndex = -1;
        this.selectionAnchorIndex = -1;
      }
      this.updateSelectionToolbar();

      if (this.pathInput) this.pathInput.value = this.currentPath;
      this._inBin = Boolean(res.recycle_bin);
      binColumns(this, this._inBin); // "From" and "Deleted" in the Recycle Bin (NUX-17)
      binBar(this, this._inBin, () => this.loadPath(this.currentPath, true));
      if (res.recycle_bin && res.bins_asleep > 0 && this._binsAsleepShown !== res.bins_asleep) {
        this._binsAsleepShown = res.bins_asleep;
        showToast(t('fm.bins_asleep', '{count, plural, one {# Recycle Bin is} other {# Recycle Bins are}} on a sleeping disk and not shown, so the disk stays asleep. They appear once it wakes.', { count: res.bins_asleep }), 'info');
      }

      // Update folder title in header
      if (this.titleFolderSpan) {
        const folderName = this.currentPath.split('/').filter(Boolean).pop();
        this.titleFolderSpan.textContent = folderName ? `— ${folderName}` : '';
      }

      // Update DockManager title
      if (window.DockManager && window.DockManager.windows[this.dockId]) {
        window.DockManager.windows[this.dockId].title = this.getTitle();
        window.DockManager.render();
      }

      // Update Column Headers with sort indicators
      if (this.colName && this.colSize && this.colType) {
        const getArrow = (col) => {
          if (this.currentSortBy !== col) return ' <span class="fm-sort-indicator" style="opacity: 0.2;">▼</span>';
          return this.currentSortDir === 'asc'
            ? ' <span class="fm-sort-indicator" style="opacity: 0.9; color: var(--lt-ink-brand, var(--accent-cyan, #0ea5e9));">▲</span>'
            : ' <span class="fm-sort-indicator" style="opacity: 0.9; color: var(--lt-ink-brand, var(--accent-cyan, #0ea5e9));">▼</span>';
        };
        this.colName.innerHTML = t('fm.col_name', 'Name') + getArrow('name');
        this.colSize.innerHTML = t('fm.col_size', 'Size') + getArrow('size');
        this.colType.innerHTML = 'Type' + getArrow('type');
      }

      // Render breadcrumbs
      this.renderBreadcrumbs();

      // Sort file list
      this.fileList = (res.dirs || []).sort((a, b) => {
        if (a.name === '..') return -1;
        if (b.name === '..') return 1;

        let nameA = a.name.toLowerCase();
        let nameB = b.name.toLowerCase();
        let nameCompare = nameA < nameB ? -1 : (nameA > nameB ? 1 : 0);
        const getType = (f) => f.is_dir ? 'Folder' : (f.name.includes('.') ? f.name.split('.').pop().toUpperCase() : 'File');

        if (this.currentSortBy === 'size') {
          let valA = a.size || 0;
          let valB = b.size || 0;
          if (valA !== valB) {
            return this.currentSortDir === 'asc' ? valA - valB : valB - valA;
          }
          if (a.is_dir && !b.is_dir) return this.currentSortDir === 'asc' ? -1 : 1;
          if (!a.is_dir && b.is_dir) return this.currentSortDir === 'asc' ? 1 : -1;
          return this.currentSortDir === 'asc' ? nameCompare : -nameCompare;
        } else if (this.currentSortBy === 'type') {
          let valA = getType(a);
          let valB = getType(b);
          if (valA !== valB) {
            let cmp = valA < valB ? -1 : (valA > valB ? 1 : 0);
            return this.currentSortDir === 'asc' ? cmp : -cmp;
          }
          return this.currentSortDir === 'asc' ? nameCompare : -nameCompare;
        } else {
          if (a.is_dir && !b.is_dir) return -1;
          if (!a.is_dir && b.is_dir) return 1;
          return this.currentSortDir === 'asc' ? nameCompare : -nameCompare;
        }
      });

      this.rawFileList = [...this.fileList];
      if (this.searchInput) this.searchInput.value = '';
      this.searchQuery = '';
      this.isSearching = false;

      if (this.spacer) this.spacer.style.height = (this.fileList.length * (this.viewMode === 'compact' ? 28 : ROW_HEIGHT)) + 'px';
      if (this.viewport) this.viewport.scrollTop = 0;
      if (this.sidebarTree) {
        this.sidebarTree.updateActive(this.currentPath);
      }
      if (this.inspector && this.inspector.isVisible) {
        this.inspector.update();
      }
      this.renderViewport();
    } catch (err) {
      if (err.name !== 'AbortError') {
        const errorMsg =
          err?.status === 403
            ? t('fm.err_access_denied', 'Access denied or path invalid')
            : (err?.detail?.message || err?.detail || err?.message || t('fm.err_load_dir', 'Failed to load directory'));
        showToast(errorMsg, 'error');
      }
    }
  }

  renderViewport() {
    if (!this.viewport || !this.list) return;

    if (this.fileList.length === 0) {
      if (this.spacer) this.spacer.style.height = '0px';
      this.list.style.transform = 'none';
      this.list.innerHTML = `<div style="padding: 32px; text-align: center; color: var(--muted); font-size: 13px;">${escapeHtml(t('fm.empty_folder', 'This folder is empty.'))}</div>`;
      return;
    }

    if (this.viewMode === 'icon') {
      const count = this.fileList.length;
      const cellWidth = 110;
      const cellHeight = 120;
      const gap = 12;
      const viewportWidth = this.viewport.clientWidth || 800;
      const clientHeight = this.viewport.clientHeight || 600;
      const columns = Math.max(1, Math.floor((viewportWidth + gap) / (cellWidth + gap)));
      const totalRows = Math.ceil(count / columns);
      const rowPitch = cellHeight + gap;
      const totalHeight = totalRows * rowPitch;

      if (this.spacer) {
        this.spacer.style.height = `${totalHeight}px`;
        this.spacer.style.display = 'block';
      }

      const scrollTop = this.viewport.scrollTop || 0;
      const startRow = Math.max(0, Math.floor(scrollTop / rowPitch) - BUFFER);
      const endRow = Math.min(totalRows, Math.ceil((scrollTop + clientHeight) / rowPitch) + BUFFER);
      const startIndex = startRow * columns;
      const endIndex = Math.min(count, endRow * columns);

      this.list.style.transform = `translateY(${startRow * rowPitch}px)`;
      this.list.innerHTML = '';
      this.list.setAttribute('role', 'grid');
      this.list.setAttribute('aria-label', 'File Explorer Grid');
      const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';

      const folderSvg = '<svg viewBox="0 0 24 24" width="44" height="44" stroke="currentColor" stroke-width="1.5" fill="#eab308"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>';
      const fileSvg = '<svg viewBox="0 0 24 24" width="40" height="40" stroke="currentColor" stroke-width="1.5" fill="none"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>';
      const upSvg = '<svg viewBox="0 0 24 24" width="40" height="40" stroke="currentColor" stroke-width="1.5" fill="none"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>';

      for (let i = startIndex; i < endIndex; i++) {
        const file = this.fileList[i];
        const card = document.createElement('div');
        card.className = 'fm-grid-card';
        card.dataset.path = file.path;
        card.dataset.name = file.name;
        card.dataset.index = i;
        card.setAttribute('role', 'row');
        const isCardSelected = this.selectedPaths.has(file.path);
        card.setAttribute('tabindex', isCardSelected ? '0' : '-1');
        card.setAttribute('aria-selected', isCardSelected ? 'true' : 'false');
        if (isCardSelected) card.classList.add('selected');
        if (_clipboard && _clipboard.action === 'move' && _clipboard.items && _clipboard.items.includes(file.path)) {
          card.classList.add('fm-cut-pending');
        }

        const escName = escapeHtml(file.name);
        const escPath = escapeHtml(file.path);
        const isImage = Boolean(file.name.match(/\.(jpeg|jpg|png|gif|webp|svg)$/i));

        let iconContent;
        if (file.name === '..') {
          iconContent = upSvg;
        } else if (file.is_dir) {
          iconContent = folderSvg;
        } else if (thumbKind(file.name)) {
          // A small thumbnail from the server (photos, HEIC, a frame of a video), never the whole file
          const isVideo = thumbKind(file.name) === 'video';
          iconContent = `
            <img src="${thumbUrl(file.path)}" class="fm-thumb-img" loading="lazy" decoding="async" alt="${escName}" data-img-fallback="hide-show-next:flex" />
            <div class="fm-fallback-img-icon" style="display:none;">${fileSvg}</div>
            ${isVideo ? '<span class="fm-thumb-play" aria-hidden="true"><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></span>' : ''}
          `;
        } else {
          iconContent = fileSvg;
        }

        const metaText = file.name === '..' ? '--' : (file.is_dir ? 'Folder' : formatBytes(file.size));

        // One grid cell per card (a row of the grid); display: contents keeps the card's layout
        card.innerHTML = `<div class="fm-card-cell" role="gridcell">
          ${file.name !== '..' ? `<input type="checkbox" class="fm-checkbox fm-card-checkbox" ${this.selectedPaths.has(file.path) ? 'checked' : ''} data-path="${escPath}" title="${t('ui.select_item', 'Select item')}" />` : ''}
          <div class="fm-card-preview">${iconContent}</div>
          <div class="fm-card-info">
            <div class="fm-card-name" title="${escName}">${escName}</div>
            <div class="fm-card-meta">${metaText}</div>
          </div>
          <div class="fm-card-actions">
            ${(!file.is_dir && file.name !== '..' && isImage) ? `<button class="fm-act-btn" data-act="preview" data-path="${escPath}" title="${t('ui.preview', 'Preview')}">👁️</button>` : ''}
            ${!file.is_dir && file.name !== '..' ? `<button class="fm-act-btn" data-act="download" data-path="${escPath}" title="${t('preview.download', 'Download')}">⬇️</button>` : ''}
            ${file.name !== '..' ? `<button class="fm-act-btn" data-act="share" data-path="${escPath}" title="${t('ui.share_via_link', 'Share via Link')}">🔗</button>` : ''}
            ${file.name !== '..' ? `<button class="fm-act-btn" data-act="rename" data-path="${escPath}" title="${t('mgmt.wallpaper_rename', 'Rename')}">✏️</button>` : ''}
            ${file.name !== '..' ? `<button class="fm-act-btn" data-act="delete" data-path="${escPath}" title="${t('vm.delete', 'Delete')}">🗑️</button>` : ''}
            ${file.name !== '..' ? `<button class="fm-act-btn fm-act-more-sheet" data-act="more-sheet" data-path="${escPath}" title="${t('ui.more_actions', 'More Actions')}" style="display:none;">···</button>` : ''}
          </div>
        </div>`;

        if (file.name !== '..') {
          card.setAttribute('draggable', 'true');
        }

        this.list.appendChild(card);
      }
      return;
    }

    // List or Compact view
    const isCompact = this.viewMode === 'compact';
    const pitch = isCompact ? 28 : ROW_HEIGHT;
    const totalHeight = this.fileList.length * pitch;
    if (this.spacer) this.spacer.style.height = `${totalHeight}px`;
    const scrollTop = this.viewport.scrollTop || 0;
    const viewportHeight = this.viewport.clientHeight || 400;

    const startIndex = Math.max(0, Math.floor(scrollTop / pitch) - BUFFER);
    const endIndex = Math.min(this.fileList.length, Math.ceil((scrollTop + viewportHeight) / pitch) + BUFFER);

    this.list.style.transform = `translateY(${startIndex * pitch}px)`;
    this.list.innerHTML = '';

    this.list.setAttribute('role', 'grid');
    this.list.setAttribute('aria-label', 'Files');
    this.list.setAttribute('aria-multiselectable', 'true');
    for (let i = startIndex; i < endIndex; i++) {
      const file = this.fileList[i];
      const row = document.createElement('div');
      row.className = isCompact ? 'fm-row fm-row-compact' : 'fm-row';
      row.dataset.path = file.path;
      row.dataset.name = file.name;
      row.dataset.index = i;
      row.setAttribute('role', 'row');
      const isRowSelected = this.selectedPaths.has(file.path);
      row.setAttribute('tabindex', isRowSelected ? '0' : '-1');
      row.setAttribute('aria-selected', isRowSelected ? 'true' : 'false');
      if (isRowSelected) row.classList.add('selected');
      if (_clipboard && _clipboard.action === 'move' && _clipboard.items && _clipboard.items.includes(file.path)) {
        row.classList.add('fm-cut-pending');
      }

      const isRemoteDir = this.currentPath === '/mnt/remotes';
      const isDiskDir = this.currentPath === '/mnt/disks';
      let icon;
      if (file.is_dir) {
        if (isRemoteDir) {
          icon = '<svg viewBox="0 0 24 24" width="18" height="18" stroke="#38bdf8" fill="rgba(56,189,248,0.2)" stroke-width="2"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path></svg>';
        } else if (isDiskDir) {
          icon = '<svg viewBox="0 0 24 24" width="18" height="18" stroke="#a855f7" fill="rgba(168,85,247,0.2)" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"></rect><circle cx="12" cy="12" r="4"></circle><circle cx="12" cy="12" r="1"></circle></svg>';
        } else {
          icon = '<svg viewBox="0 0 24 24" width="18" stroke="currentColor" fill="#eab308"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>';
        }
      } else {
        icon = '<svg viewBox="0 0 24 24" width="18" stroke="currentColor" fill="none"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>';
      }

      const escName = escapeHtml(file.name);
      const escPath = escapeHtml(file.path);
      const isImage = file.name.match(/\.(jpeg|jpg|png|gif|webp|svg)$/i);
      let fileType = file.is_dir ? (isRemoteDir ? 'Cloud Drive' : (isDiskDir ? 'Disk Drive' : 'Folder')) : (file.name.includes('.') ? file.name.split('.').pop().toUpperCase() : 'File');
      if (this._inBin) fileType = file.original_path ? file.original_path.replace(/\/[^/]*$/, '') || '/' : '–'; // where it was
      const mtimeStr = formatDateTime(file.mtime, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

      const rowThumb = !file.is_dir && ['image', 'video'].includes(thumbKind(file.name));
      const leading = rowThumb
        ? `<img class="fm-row-thumb" src="${thumbUrl(file.path)}" alt="" loading="lazy" decoding="async" data-img-fallback="hide-show-next:inline-flex" /><span class="fm-row-thumb-fallback" style="display:none;">${icon}</span>`
        : icon;
      const subLine = file.name === '..' ? '' : (file.is_dir ? mtimeStr : `${formatBytes(file.size)} · ${mtimeStr}`);
      row.innerHTML = `
        <div class="fm-col fm-col-check">${file.name !== '..' ? `<input type="checkbox" class="fm-checkbox fm-row-checkbox" ${this.selectedPaths.has(file.path) ? 'checked' : ''} data-path="${escPath}" title="${t('ui.select_item', 'Select item')}" />` : ''}</div>
        <div class="fm-col fm-col-name">${leading} <span class="fm-name-stack"><span class="fm-name-text">${escName}</span><span class="fm-row-sub">${escapeHtml(subLine)}</span></span></div>
        <div class="fm-col fm-col-type">${file.name === '..' ? '--' : escapeHtml(fileType)}</div>
        <div class="fm-col fm-col-size">${file.is_dir ? '--' : formatBytes(file.size)}</div>
        <div class="fm-col fm-col-mtime">${file.name === '..' ? '--' : mtimeStr}</div>
        <div class="fm-col fm-col-actions">
          ${(!file.is_dir && file.name !== '..' && isImage) ? `<button class="fm-act-btn" data-act="preview" data-path="${escPath}" title="${t('ui.preview', 'Preview')}">👁️</button>` : ''}
          ${!file.is_dir && file.name !== '..' ? `<button class="fm-act-btn" data-act="download" data-path="${escPath}" title="${t('preview.download', 'Download')}">⬇️</button>` : ''}
          ${file.name !== '..' ? `<button class="fm-act-btn" data-act="share" data-path="${escPath}" title="${t('ui.share_via_link', 'Share via Link')}">🔗</button>` : ''}
          ${file.name !== '..' ? `<button class="fm-act-btn" data-act="rename" data-path="${escPath}" title="${t('mgmt.wallpaper_rename', 'Rename')}">✏️</button>` : ''}
          ${file.name !== '..' ? `<button class="fm-act-btn" data-act="delete" data-path="${escPath}" title="${t('vm.delete', 'Delete')}">🗑️</button>` : ''}
          ${file.name !== '..' ? `<button class="fm-act-btn fm-act-more-sheet" data-act="more-sheet" data-path="${escPath}" title="${t('ui.more_actions', 'More Actions')}" aria-label="${t('ui.more_actions', 'More Actions')}">···</button>` : ''}
        </div>
      `;
      row.querySelectorAll(':scope > .fm-col').forEach((cell) => cell.setAttribute('role', 'gridcell'));

      if (file.name !== '..') {
        row.setAttribute('draggable', 'true');
      }

      this.list.appendChild(row);
    }
  }

  async uploadFiles(files, targetPath = null) {
    if (!files || files.length === 0) return;
    const destDir = targetPath || this.currentPath;
    const list = Array.from(files);
    const totalBytes = list.reduce((sum, f) => sum + (f.size || 0), 0);
    let cancelled = false;
    const job = transferCenter.startLocal({
      kind: 'upload',
      label: t('transfers.uploading', 'Uploading {count} file(s) to {dest}', { count: list.length, dest: destDir.split('/').pop() || '/' }),
      totalFiles: list.length,
      totalBytes,
      cancel: () => { cancelled = true; },
    });
    let successCount = 0;
    let doneBytes = 0;
    const errors = [];

    for (let i = 0; i < list.length && !cancelled; i++) {
      const file = list[i];
      job.progress({ current: file.name });
      try {
        if (file.size > 16 * 1024 * 1024) {
          await this._uploadFileChunked(file, destDir, (sent) => job.progress({ bytes: doneBytes + sent }), () => cancelled);
        } else {
          // The upload API takes the folder and name in the query and the file as the body
          const res = await api.postRaw(fsUploadUrl(destDir, file.name), file);
          if (!res.ok) throw await ApiError.from(res);
        }
        successCount++;
      } catch (err) {
        if (!cancelled) errors.push(`${file.name}: ${err.message}`);
      }
      doneBytes += file.size || 0;
      job.progress({ files: i + 1, bytes: doneBytes });
    }

    if (cancelled) job.finish('cancelled');
    else if (errors.length && !successCount) job.finish('failed', errors[0]);
    else job.finish('completed', errors.length ? `${errors.length} file(s) failed: ${errors[0]}` : null);
    if (successCount > 0) this.loadPath(this.currentPath);
  }

  async _uploadFileChunked(file, destDir, onProgress = null, isCancelled = null) {
    const CHUNK_SIZE = 16 * 1024 * 1024;
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    const initRes = await api.post('/api/fs/upload/init', {
      filename: file.name,
      destination_dir: destDir,
      total_size: file.size,
      chunk_size: CHUNK_SIZE,
    });
    if (!initRes || !initRes.upload_id) throw new Error('Upload initialization failed');
    const uploadId = initRes.upload_id;

    for (let c = 0; c < totalChunks; c++) {
      const start = c * CHUNK_SIZE;
      const end = Math.min(start + CHUNK_SIZE, file.size);
      const slice = file.slice(start, end);
      const chunkUrl = `/api/fs/upload/chunk?upload_id=${encodeURIComponent(uploadId)}&chunk_index=${c}`;
      const chunkRes = await api.postRaw(chunkUrl, slice, {
        headers: { 'Content-Type': 'application/octet-stream' },
      });
      if (!chunkRes.ok) throw await ApiError.from(chunkRes);
      if (onProgress) onProgress(end);
      if (isCancelled && isCancelled()) throw new Error('Cancelled');
    }

    const completeRes = await api.post('/api/fs/upload/complete', {
      upload_id: uploadId,
    });
    return completeRes;
  }

  async handleAction(act, path, oldName) {
    if (act === 'more-sheet') {
      const file = this.fileList.find((f) => f.path === path);
      const isDir = Boolean(file?.is_dir);
      const isImage = Boolean(oldName && oldName.match(/\.(jpeg|jpg|png|gif|webp|svg)$/i));
      const sheetItems = [];
      if (isDir) {
        sheetItems.push({
          icon: '📂',
          label: 'Open Folder',
          onClick: () => this.loadPath(path),
        });
      } else {
        if (isImage) {
          sheetItems.push({
            icon: '👁️',
            label: 'Preview Image',
            onClick: () => this.handleAction('preview', path, oldName),
          });
        } else {
          sheetItems.push({
            icon: '👁️',
            label: 'Quick Look / Preview',
            onClick: () => this.handleAction('preview', path, oldName),
          });
        }
        sheetItems.push({
          icon: '⬇️',
          label: 'Download File',
          onClick: () => this.handleAction('download', path, oldName),
        });
      }
      sheetItems.push(
        {
          icon: '🔗',
          label: 'Create Public Share Link',
          onClick: () => this.handleAction('share', path, oldName),
        },
        {
          icon: '✏️',
          label: t('fm.rename_title', 'Rename Item'),
          onClick: () => this.handleAction('rename', path, oldName),
        },
        {
          icon: '📋',
          label: 'Copy Item',
          onClick: () => {
            _clipboard = { items: [path], action: 'copy', sourceInstanceId: this.id };
            showToast(t('toast.copied_to_clipboard_2', 'Copied \'{oldName}\' to clipboard', { oldName: oldName }), 'info');
          },
        },
        {
          icon: '✂️',
          label: 'Cut / Move Item',
          onClick: () => {
            _clipboard = { items: [path], action: 'move', sourceInstanceId: this.id };
            this.renderViewport();
            showToast(t('toast.cut_open_destination_and_tap_to', 'Cut \'{oldName}\' — open destination and tap + to Paste', { oldName: oldName }), 'info');
          },
        },
        {
          icon: '🗑️',
          label: 'Delete Item',
          destructive: true,
          onClick: () => this.handleAction('delete', path, oldName),
        }
      );
      showBottomSheet({
        title: oldName || path.split('/').pop(),
        subtitle: isDir ? 'Folder' : (file ? formatBytes(file.size) : path),
        items: sheetItems,
      });
      return;
    } else if (act === 'preview') {
      openFilePreviewModal(path, oldName);
    } else if (act === 'share') {
      openShareLinkModal(path, oldName);
    } else if (act === 'download') {
      const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';
      window.open(`/api/fs/download?path=${encodeURIComponent(path)}`, '_blank');
    } else if (act === 'delete') {
      const confirmMsg = binConfirmText([path]);
      showConfirmToast(t('common.confirm', 'Confirm Action'), confirmMsg, async () => {
        await this.deleteWithProgress([path]);
      });
    } else if (act === 'rename') {
      showPromptToast(
        t('fm.rename_title', 'Rename Item'),
        t('fm.prompt_rename', 'Enter new name:'),
        oldName,
        async (newName) => {
          if (newName && newName !== oldName) {
            try {
              const parent = path.substring(0, path.lastIndexOf('/'));
              const newPath = parent ? `${parent}/${newName}` : `/${newName}`;
              await api.post('/api/fs/rename', { old_path: path, new_path: newPath });
              this.loadPath(this.currentPath);
              ZettEventBus.emit('fm:refresh');
            } catch (err) {
              showToast(err.message, 'error');
            }
          }
        }
      );
    }
  }

  handleKeydown(e) {
    if (!e || e.defaultPrevented) return;
    if (!isFmActive(this.windowEl)) return;

    const target = e.target;
    const isTextInput = target && (
      target.tagName === 'TEXTAREA' ||
      target.tagName === 'SELECT' ||
      target.isContentEditable ||
      (target.tagName === 'INPUT' && target.type !== 'checkbox' && target.type !== 'radio')
    );
    if (isTextInput) return;

    if (isFmModalBlocking()) {
      return;
    }

    const minSelectableIndex = (this.fileList[0]?.name === '..') ? 1 : 0;
    const hasSelectableFiles = this.fileList.length > minSelectableIndex;

    // F2 -> Inline rename selected item (if exactly 1 item selected)
    if (e.key === 'F2') {
      if (this.selectedPaths.size === 1) {
        e.preventDefault();
        e.stopPropagation();
        const selectedPath = Array.from(this.selectedPaths)[0];
        const selectedFile = this.fileList.find((f) => f.path === selectedPath);
        if (selectedFile && selectedFile.name !== '..') {
          this.triggerInlineRename(selectedFile);
        }
      }
      return;
    }

    // Ctrl+D / Cmd+D -> Duplicate selected item(s)
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd' && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      e.stopPropagation();
      this.duplicateSelected();
      return;
    }

    // Ctrl+F / Cmd+F -> Focus in-window search input
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f' && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      e.stopPropagation();
      if (this.searchInput) {
        this.searchInput.focus();
        this.searchInput.select?.();
      }
      return;
    }

    // Ctrl+N / Cmd+N -> Open New File Explorer Window
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n' && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      e.stopPropagation();
      openNewFileManagerWindow(this.currentPath);
      return;
    }

    // Alt+Left / Backspace -> Back
    if ((e.altKey || e.metaKey) && e.key === 'ArrowLeft') {
      e.preventDefault();
      e.stopPropagation();
      this.goBack();
      return;
    }

    // Alt+Right -> Forward
    if ((e.altKey || e.metaKey) && e.key === 'ArrowRight') {
      e.preventDefault();
      e.stopPropagation();
      this.goForward();
      return;
    }

    if (e.key === 'Escape') {
      if (this.selectedPaths.size > 0) {
        e.preventDefault();
        e.stopPropagation();
        this.selectedPaths.clear();
        this.lastSelectedIndex = -1;
        this.selectionAnchorIndex = -1;
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      }
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
      e.preventDefault();
      e.stopPropagation();
      this.selectedPaths.clear();
      this.fileList.forEach((f) => {
        if (f.name !== '..') {
          this.selectedPaths.add(f.path);
        }
      });
      this.lastSelectedIndex = this.fileList.length - 1;
      this.selectionAnchorIndex = minSelectableIndex;
      this.updateRowSelectionUI();
      this.updateSelectionToolbar();
    } else if (e.key === 'Delete' || (e.metaKey && e.key === 'Backspace')) {
      if (this.selectedPaths.size > 0) {
        e.preventDefault();
        e.stopPropagation();
        this.bulkDeleteBtn?.click();
      }
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
      if (this.selectedPaths.size > 0) {
        e.preventDefault();
        e.stopPropagation();
        _clipboard = { items: Array.from(this.selectedPaths), action: 'copy', sourceInstanceId: this.id };
        const msg = t('fm.copied_clipboard', 'Copied {count, plural, one {# item} other {# items}}', { count: this.selectedPaths.size });
        showToast(msg, 'info');
      }
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'x') {
      if (this.selectedPaths.size > 0) {
        e.preventDefault();
        e.stopPropagation();
        _clipboard = { items: Array.from(this.selectedPaths), action: 'move', sourceInstanceId: this.id };
        const msg = t('fm.cut_clipboard', 'Cut {count, plural, one {# item} other {# items}}', { count: this.selectedPaths.size });
        showToast(msg, 'info');
        this.updateRowSelectionUI();
      }
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') {
      if (_clipboard && _clipboard.items && _clipboard.items.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        executeTransferWithConflictCheck(_clipboard.items, this.currentPath, _clipboard.action);
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      e.stopPropagation();
      this.ensureFocus();
      if (!hasSelectableFiles) return;
      const step = this.viewMode === 'icon' ? this.getGridColumnCount() : 1;

      if (this.lastSelectedIndex === -1) {
        const targetIdx = minSelectableIndex;
        this.selectionAnchorIndex = targetIdx;
        if (e.shiftKey) {
          const nextIdx = Math.min(this.fileList.length - 1, targetIdx + step);
          this.lastSelectedIndex = nextIdx;
          this.selectedPaths.clear();
          for (let j = targetIdx; j <= nextIdx; j++) {
            if (this.fileList[j] && this.fileList[j].name !== '..') {
              this.selectedPaths.add(this.fileList[j].path);
            }
          }
        } else {
          this.lastSelectedIndex = targetIdx;
          this.selectedPaths.clear();
          if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
            this.selectedPaths.add(this.fileList[targetIdx].path);
          }
        }
        this.scrollIndexIntoView(this.lastSelectedIndex);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
        return;
      }

      if (e.shiftKey) {
        if (this.selectionAnchorIndex === -1) this.selectionAnchorIndex = this.lastSelectedIndex;
        const nextIdx = Math.min(this.fileList.length - 1, this.lastSelectedIndex + step);
        this.lastSelectedIndex = nextIdx;
        this.selectedPaths.clear();
        const start = Math.min(this.selectionAnchorIndex, this.lastSelectedIndex);
        const end = Math.max(this.selectionAnchorIndex, this.lastSelectedIndex);
        for (let j = start; j <= end; j++) {
          if (this.fileList[j] && this.fileList[j].name !== '..') {
            this.selectedPaths.add(this.fileList[j].path);
          }
        }
        this.scrollIndexIntoView(this.lastSelectedIndex);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      } else if (!e.ctrlKey && !e.metaKey) {
        const targetIdx = Math.min(this.fileList.length - 1, this.lastSelectedIndex + step);
        this.lastSelectedIndex = targetIdx;
        this.selectionAnchorIndex = targetIdx;
        this.selectedPaths.clear();
        if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
          this.selectedPaths.add(this.fileList[targetIdx].path);
        }
        this.scrollIndexIntoView(targetIdx);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      e.stopPropagation();
      this.ensureFocus();
      if (!hasSelectableFiles) return;
      const step = this.viewMode === 'icon' ? this.getGridColumnCount() : 1;

      if (this.lastSelectedIndex === -1) {
        const targetIdx = this.fileList.length - 1;
        this.selectionAnchorIndex = targetIdx;
        if (e.shiftKey) {
          const nextIdx = Math.max(minSelectableIndex, targetIdx - step);
          this.lastSelectedIndex = nextIdx;
          this.selectedPaths.clear();
          const start = Math.min(targetIdx, nextIdx);
          const end = Math.max(targetIdx, nextIdx);
          for (let j = start; j <= end; j++) {
            if (this.fileList[j] && this.fileList[j].name !== '..') {
              this.selectedPaths.add(this.fileList[j].path);
            }
          }
        } else {
          this.lastSelectedIndex = targetIdx;
          this.selectedPaths.clear();
          if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
            this.selectedPaths.add(this.fileList[targetIdx].path);
          }
        }
        this.scrollIndexIntoView(this.lastSelectedIndex);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
        return;
      }

      if (e.shiftKey) {
        if (this.selectionAnchorIndex === -1) this.selectionAnchorIndex = this.lastSelectedIndex;
        const prevIdx = Math.max(minSelectableIndex, this.lastSelectedIndex - step);
        this.lastSelectedIndex = prevIdx;
        this.selectedPaths.clear();
        const start = Math.min(this.selectionAnchorIndex, this.lastSelectedIndex);
        const end = Math.max(this.selectionAnchorIndex, this.lastSelectedIndex);
        for (let j = start; j <= end; j++) {
          if (this.fileList[j] && this.fileList[j].name !== '..') {
            this.selectedPaths.add(this.fileList[j].path);
          }
        }
        this.scrollIndexIntoView(this.lastSelectedIndex);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      } else if (!e.ctrlKey && !e.metaKey) {
        const targetIdx = Math.max(minSelectableIndex, this.lastSelectedIndex - step);
        this.lastSelectedIndex = targetIdx;
        this.selectionAnchorIndex = targetIdx;
        this.selectedPaths.clear();
        if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
          this.selectedPaths.add(this.fileList[targetIdx].path);
        }
        this.scrollIndexIntoView(targetIdx);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      }
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      e.stopPropagation();
      this.ensureFocus();
      if (!hasSelectableFiles) return;

      if (this.lastSelectedIndex === -1) {
        const targetIdx = minSelectableIndex;
        this.lastSelectedIndex = targetIdx;
        this.selectionAnchorIndex = targetIdx;
        this.selectedPaths.clear();
        if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
          this.selectedPaths.add(this.fileList[targetIdx].path);
        }
        this.scrollIndexIntoView(targetIdx);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
        return;
      }

      if (e.shiftKey) {
        if (this.selectionAnchorIndex === -1) this.selectionAnchorIndex = this.lastSelectedIndex;
        const nextIdx = Math.min(this.fileList.length - 1, this.lastSelectedIndex + 1);
        this.lastSelectedIndex = nextIdx;
        this.selectedPaths.clear();
        const start = Math.min(this.selectionAnchorIndex, this.lastSelectedIndex);
        const end = Math.max(this.selectionAnchorIndex, this.lastSelectedIndex);
        for (let j = start; j <= end; j++) {
          if (this.fileList[j] && this.fileList[j].name !== '..') {
            this.selectedPaths.add(this.fileList[j].path);
          }
        }
        this.scrollIndexIntoView(this.lastSelectedIndex);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      } else if (!e.ctrlKey && !e.metaKey) {
        const targetIdx = Math.min(this.fileList.length - 1, this.lastSelectedIndex + 1);
        this.lastSelectedIndex = targetIdx;
        this.selectionAnchorIndex = targetIdx;
        this.selectedPaths.clear();
        if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
          this.selectedPaths.add(this.fileList[targetIdx].path);
        }
        this.scrollIndexIntoView(targetIdx);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      }
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      e.stopPropagation();
      this.ensureFocus();
      if (!hasSelectableFiles) return;

      if (this.lastSelectedIndex === -1) {
        const targetIdx = this.fileList.length - 1;
        this.lastSelectedIndex = targetIdx;
        this.selectionAnchorIndex = targetIdx;
        this.selectedPaths.clear();
        if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
          this.selectedPaths.add(this.fileList[targetIdx].path);
        }
        this.scrollIndexIntoView(targetIdx);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
        return;
      }

      if (e.shiftKey) {
        if (this.selectionAnchorIndex === -1) this.selectionAnchorIndex = this.lastSelectedIndex;
        const prevIdx = Math.max(minSelectableIndex, this.lastSelectedIndex - 1);
        this.lastSelectedIndex = prevIdx;
        this.selectedPaths.clear();
        const start = Math.min(this.selectionAnchorIndex, this.lastSelectedIndex);
        const end = Math.max(this.selectionAnchorIndex, this.lastSelectedIndex);
        for (let j = start; j <= end; j++) {
          if (this.fileList[j] && this.fileList[j].name !== '..') {
            this.selectedPaths.add(this.fileList[j].path);
          }
        }
        this.scrollIndexIntoView(this.lastSelectedIndex);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      } else if (!e.ctrlKey && !e.metaKey) {
        const targetIdx = Math.max(minSelectableIndex, this.lastSelectedIndex - 1);
        this.lastSelectedIndex = targetIdx;
        this.selectionAnchorIndex = targetIdx;
        this.selectedPaths.clear();
        if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
          this.selectedPaths.add(this.fileList[targetIdx].path);
        }
        this.scrollIndexIntoView(targetIdx);
        this.updateRowSelectionUI();
        this.updateSelectionToolbar();
      }
    } else if (e.key === 'Home') {
      e.preventDefault();
      e.stopPropagation();
      this.ensureFocus();
      if (!hasSelectableFiles) return;
      const targetIdx = minSelectableIndex;
      if (e.shiftKey) {
        if (this.selectionAnchorIndex === -1) this.selectionAnchorIndex = (this.lastSelectedIndex >= 0) ? this.lastSelectedIndex : targetIdx;
        this.lastSelectedIndex = targetIdx;
        this.selectedPaths.clear();
        const start = Math.min(this.selectionAnchorIndex, this.lastSelectedIndex);
        const end = Math.max(this.selectionAnchorIndex, this.lastSelectedIndex);
        for (let j = start; j <= end; j++) {
          if (this.fileList[j] && this.fileList[j].name !== '..') {
            this.selectedPaths.add(this.fileList[j].path);
          }
        }
      } else if (!e.ctrlKey && !e.metaKey) {
        this.lastSelectedIndex = targetIdx;
        this.selectionAnchorIndex = targetIdx;
        this.selectedPaths.clear();
        if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
          this.selectedPaths.add(this.fileList[targetIdx].path);
        }
      }
      this.scrollIndexIntoView(this.lastSelectedIndex);
      this.updateRowSelectionUI();
      this.updateSelectionToolbar();
    } else if (e.key === 'End') {
      e.preventDefault();
      e.stopPropagation();
      this.ensureFocus();
      if (!hasSelectableFiles) return;
      const targetIdx = this.fileList.length - 1;
      if (e.shiftKey) {
        if (this.selectionAnchorIndex === -1) this.selectionAnchorIndex = (this.lastSelectedIndex >= 0) ? this.lastSelectedIndex : minSelectableIndex;
        this.lastSelectedIndex = targetIdx;
        this.selectedPaths.clear();
        const start = Math.min(this.selectionAnchorIndex, this.lastSelectedIndex);
        const end = Math.max(this.selectionAnchorIndex, this.lastSelectedIndex);
        for (let j = start; j <= end; j++) {
          if (this.fileList[j] && this.fileList[j].name !== '..') {
            this.selectedPaths.add(this.fileList[j].path);
          }
        }
      } else if (!e.ctrlKey && !e.metaKey) {
        this.lastSelectedIndex = targetIdx;
        this.selectionAnchorIndex = targetIdx;
        this.selectedPaths.clear();
        if (this.fileList[targetIdx] && this.fileList[targetIdx].name !== '..') {
          this.selectedPaths.add(this.fileList[targetIdx].path);
        }
      }
      this.scrollIndexIntoView(this.lastSelectedIndex);
      this.updateRowSelectionUI();
      this.updateSelectionToolbar();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      let targetItem = null;
      if (this.selectedPaths.size === 1) {
        const selPath = Array.from(this.selectedPaths)[0];
        targetItem = this.fileList.find((f) => f.path === selPath);
      } else if (this.lastSelectedIndex >= 0 && this.fileList[this.lastSelectedIndex]) {
        targetItem = this.fileList[this.lastSelectedIndex];
      }
      if (targetItem && targetItem.name !== '..') {
        if (targetItem.is_dir) {
          this.loadPath(targetItem.path);
        } else {
          this.handleAction('preview', targetItem.path, targetItem.name);
        }
      }
    } else if (
      (e.key === 'Backspace' && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) ||
      ((e.altKey || e.metaKey) && e.key === 'ArrowUp')
    ) {
      e.preventDefault();
      e.stopPropagation();
      this.upBtn?.click();
    } else if ((e.key === ' ' || e.code === 'Space') && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      let targetItem = null;
      if (this.selectedPaths.size === 1) {
        const selPath = Array.from(this.selectedPaths)[0];
        targetItem = this.fileList.find((f) => f.path === selPath);
      } else if (this.lastSelectedIndex >= 0 && this.fileList[this.lastSelectedIndex]) {
        targetItem = this.fileList[this.lastSelectedIndex];
      }
      if (targetItem && !targetItem.is_dir && targetItem.name !== '..') {
        e.preventDefault();
        e.stopPropagation();
        openFilePreviewModal(targetItem.path, targetItem.name);
      }
    }
  }

  clearSelection() {
    this.selectedPaths.clear();
    this.lastSelectedIndex = -1;
    this.selectionAnchorIndex = -1;
    this.updateRowSelectionUI();
    this.updateSelectionToolbar();
  }

  handleClipboardAction(action) {
    if (this.selectedPaths.size === 0) return;
    _clipboard = { items: Array.from(this.selectedPaths), action, sourceInstanceId: this.id };
    const count = this.selectedPaths.size;
    const msg = action === 'move'
      ? t('fm.cut_clipboard', 'Cut {count, plural, one {# item} other {# items}}', { count })
      : t('fm.copied_clipboard', 'Copied {count, plural, one {# item} other {# items}}', { count });
    showToast(msg, 'info');
    this.updateRowSelectionUI();
  }

  handlePaste() {
    if (_clipboard && _clipboard.items && _clipboard.items.length > 0) {
      executeTransferWithConflictCheck(_clipboard.items, this.currentPath, _clipboard.action || 'copy');
      if (_clipboard.action === 'move') {
        _clipboard = { items: [], action: 'copy', sourceInstanceId: null };
      }
      this.loadPath(this.currentPath);
      ZettEventBus.emit('fm:refresh');
    }
  }

  async duplicateSelected() {
    const paths = Array.from(this.selectedPaths);
    // One background copy per folder, each item renamed "name copy.ext" next to the original
    const byParent = new Map();
    for (const p of paths) {
      const file = this.fileList.find((f) => f.path === p);
      if (!file || file.name === '..') continue;
      const oldName = file.name;
      const lastDot = oldName.lastIndexOf('.');
      const stem = (file.is_dir || lastDot <= 0) ? oldName : oldName.substring(0, lastDot);
      const ext = (file.is_dir || lastDot <= 0) ? '' : oldName.substring(lastDot);
      const parent = p.substring(0, p.lastIndexOf('/')) || '/';
      if (!byParent.has(parent)) byParent.set(parent, { sources: [], names: [] });
      byParent.get(parent).sources.push(p);
      byParent.get(parent).names.push(`${stem} copy${ext}`);
    }
    for (const [parent, { sources, names }] of byParent) {
      await transferCenter.startTransfer({
        sources,
        destinationDir: parent,
        action: 'copy',
        policy: 'keep_both',
        targetNames: names,
        kind: 'duplicate',
      });
    }
  }

  triggerRename(file) {
    this.triggerInlineRename(file);
  }

  triggerInlineRename(file) {
    if (!file || file.name === '..') return;
    const itemEl = this.viewport?.querySelector(`[data-path="${CSS.escape(file.path)}"]`);
    if (!itemEl) {
      this.handleAction('rename', file.path, file.name);
      return;
    }

    const nameEl = itemEl.querySelector('.fm-name-text, .fm-card-name');
    if (!nameEl) {
      this.handleAction('rename', file.path, file.name);
      return;
    }

    const oldName = file.name;
    const lastDot = oldName.lastIndexOf('.');
    const stem = (file.is_dir || lastDot <= 0) ? oldName : oldName.substring(0, lastDot);

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'fm-inline-rename-input';
    input.value = oldName;
    input.style.cssText = 'width: 100%; padding: 2px 4px; font-size: inherit; background: rgba(0,0,0,0.6); border: 1px solid var(--accent, #0ea5e9); border-radius: 4px; color: #fff; outline: none; z-index: 10;';

    nameEl.style.display = 'none';
    nameEl.parentNode.insertBefore(input, nameEl);
    input.focus();

    try {
      input.setSelectionRange(0, stem.length);
    } catch (_) {
      input.select();
    }

    let committed = false;
    const commit = async () => {
      if (committed) return;
      committed = true;
      const newName = input.value.trim();
      input.remove();
      nameEl.style.display = '';
      if (newName && newName !== oldName) {
        try {
          const parent = file.path.substring(0, file.path.lastIndexOf('/'));
          const newPath = parent ? `${parent}/${newName}` : `/${newName}`;
          await api.post('/api/fs/rename', { old_path: file.path, new_path: newPath });
          this.loadPath(this.currentPath);
          ZettEventBus.emit('fm:refresh');
        } catch (err) {
          showToast(err.message, 'error');
        }
      }
      this.ensureFocus();
    };

    const cancel = () => {
      if (committed) return;
      committed = true;
      input.remove();
      nameEl.style.display = '';
      this.ensureFocus();
    };

    input.addEventListener('keydown', (ev) => {
      ev.stopPropagation();
      if (ev.key === 'Enter') {
        ev.preventDefault();
        commit();
      } else if (ev.key === 'Escape') {
        ev.preventDefault();
        cancel();
      }
    });

    input.addEventListener('blur', () => {
      commit();
    });
  }

  async createArchive(paths, type = 'zip') {
    if (!paths || paths.length === 0) return;
    const fmt = type === 'tar.gz' || type === 'tar' ? type : 'zip';
    const first = paths[0].replace(/\/+$/, '').split('/').pop();
    const stem = paths.length === 1 ? first.replace(/\.[^.]+$/, '') || first : t('fm.archive_default_name', 'Archive');
    const archiveName = `${stem}.${fmt}`;
    try {
      const res = await api.post('/api/fs/archive/create', {
        sources: paths,
        destination_dir: this.currentPath,
        archive_name: archiveName,
        format: fmt,
      });
      transferCenter.followServerTask(
        res,
        { action: 'archive_create', kind: 'archive_create', sources: paths, destination: `${this.currentPath}/${archiveName}` },
        { label: t('transfers.zipping', 'Creating {name}', { name: archiveName }) },
      );
    } catch (err) {
      showToast(t('toast.archive_creation_failed', 'Archive creation failed: {error}', { error: err.message }), 'error');
    }
  }

  async extractArchive(archivePath, destDir = null) {
    const targetDir = destDir || this.currentPath;
    const name = archivePath.split('/').pop();
    try {
      const res = await api.post('/api/fs/archive/extract', {
        archive_path: archivePath,
        destination_dir: targetDir,
      });
      transferCenter.followServerTask(
        res,
        { action: 'archive_extract', kind: 'archive_extract', sources: [archivePath], destination: targetDir },
        { label: t('transfers.extracting', 'Extracting {name}', { name }) },
      );
    } catch (err) {
      showToast(t('toast.extraction_failed', 'Extraction failed: {error}', { error: err.message }), 'error');
    }
  }

  /** Deletes items one by one, showing progress when it takes a while. */
  async deleteWithProgress(targets, { permanent = false } = {}) {
    const job = transferCenter.startLocal({
      kind: permanent ? 'delete' : 'trash',
      label: permanent
        ? t('transfers.deleting', 'Deleting {count} item(s)', { count: targets.length })
        : t('transfers.trashing', 'Moving {count} item(s) to the Recycle Bin', { count: targets.length }),
      totalFiles: targets.length,
    });
    let success = 0;
    const errors = [];
    const trashIds = [];
    for (const p of targets) {
      job.progress({ current: p.split('/').pop() });
      try {
        const res = await api.post('/api/fs/delete', permanent ? { path: p, permanent: true } : { path: p });
        if (res?.trash_id) trashIds.push(res.trash_id);
        success++;
      } catch (err) {
        errors.push(`${p.split('/').pop()}: ${err.message}`);
      }
      job.progress({ files: success + errors.length });
    }
    if (errors.length && !success) job.finish('failed', errors[0]);
    else job.finish('completed', errors.length ? `${errors.length} item(s) failed: ${errors[0]}` : null);
    this.loadPath(this.currentPath);
    if (trashIds.length) this.offerUndo(trashIds);
    return { success, failed: errors.length };
  }

  /** Puts items from the Recycle Bin view back where they were deleted from. */
  async restoreFromBin(paths) {
    const ids = paths
      .map((p) => (this.fileList || []).find((f) => f.path === p))
      .filter((f) => f && f.trash_id)
      .map((f) => f.trash_id);
    let restored = 0;
    for (const id of ids) {
      try {
        await api.post('/api/fs/trash/restore', { item_id: id });
        restored++;
      } catch (err) {
        showToast(t('toast.restore_failed', 'Restore failed: {error}', { error: err.message }), 'error');
      }
    }
    if (restored) showToast(t('fm.restored_count', '{count, plural, one {Restored # item} other {Restored # items}}', { count: restored }), 'success');
    this.loadPath(this.currentPath);
    return restored;
  }

  /** UX-6: a toast with Undo that brings the items back from the Recycle Bin. */
  offerUndo(trashIds) {
    showActionToast(
      t('fm.moved_to_bin', '{count, plural, one {Moved # item to the Recycle Bin} other {Moved # items to the Recycle Bin}}', { count: trashIds.length }),
      t('fm.undo', 'Undo'),
      async () => {
        let restored = 0;
        for (const id of trashIds) {
          try {
            await api.post('/api/fs/trash/restore', { item_id: id });
            restored++;
          } catch (err) {
            showToast(t('toast.restore_failed', 'Restore failed: {error}', { error: err.message }), 'error');
          }
        }
        if (restored) showToast(t('fm.restored_count', '{count, plural, one {Restored # item} other {Restored # items}}', { count: restored }), 'success');
        this.loadPath(this.currentPath);
      },
    );
  }

  bulkDelete(isPermanent = false) {
    const count = this.selectedPaths.size;
    if (count === 0) return;
    const confirmMsg = isPermanent
      ? t('fm.confirm_bulk_delete_permanent', "{count, plural, one {# item will be deleted for good. This can't be undone.} other {# items will be deleted for good. This can't be undone.}}", { count })
      : binConfirmText(Array.from(this.selectedPaths));
    showConfirmToast(t('fm.delete_title', '{count, plural, one {Delete # item?} other {Delete # items?}}', { count }), confirmMsg, async () => {
      const targets = Array.from(this.selectedPaths);
      this.clearSelection();
      await this.deleteWithProgress(targets, { permanent: isPermanent });
    }, null, {
      destructive: true,
      okText: isPermanent ? t('fm.delete_permanently', 'Delete permanently') : t('fm.move_to_bin', 'Move to Recycle Bin'),
    });
  }

  /** Sorts by a field in a direction, as chosen from the folder's right-click menu. */
  setSort(col, dir) {
    this.currentSortBy = ['name', 'size', 'type', 'mtime'].includes(col) ? col : 'name';
    this.currentSortDir = dir === 'desc' ? 'desc' : 'asc';
    this.applySorting();
    this.updateSortHeaderUI();
    this.renderViewport();
  }

  sortBy(col) {
    if (this.currentSortBy === col) {
      this.currentSortDir = this.currentSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.currentSortBy = col;
      this.currentSortDir = 'asc';
    }
    this.applySorting();
    this.updateSortHeaderUI();
    this.renderViewport();
  }

  applySorting() {
    const dir = this.currentSortDir === 'asc' ? 1 : -1;
    const col = this.currentSortBy;
    const upItem = this.fileList.find((f) => f.name === '..');
    const rest = this.fileList.filter((f) => f.name !== '..');

    rest.sort((a, b) => {
      if (a.is_dir && !b.is_dir) return -1;
      if (!a.is_dir && b.is_dir) return 1;

      let res;
      if (col === 'size') {
        res = (a.size || 0) - (b.size || 0);
      } else if (col === 'type') {
        const extA = (a.name.split('.').pop() || '').toLowerCase();
        const extB = (b.name.split('.').pop() || '').toLowerCase();
        res = extA.localeCompare(extB);
      } else if (col === 'mtime') {
        res = (a.mtime || 0) - (b.mtime || 0);
      } else {
        res = (a.name || '').localeCompare(b.name || '', undefined, { numeric: true, sensitivity: 'base' });
      }
      return res * dir;
    });

    this.fileList = upItem ? [upItem, ...rest] : rest;
  }

  updateSortHeaderUI() {
    const cols = [
      { el: this.colName, key: 'name' },
      { el: this.colType, key: 'type' },
      { el: this.colSize, key: 'size' },
      { el: this.colMtime, key: 'mtime' },
    ];
    cols.forEach(({ el, key }) => {
      if (!el) return;
      const isCurrent = this.currentSortBy === key;
      el.classList.toggle('sorted', isCurrent);
      const icon = el.querySelector('.fm-sort-icon');
      if (icon) {
        icon.textContent = isCurrent ? (this.currentSortDir === 'asc' ? ' ▲' : ' ▼') : '';
        icon.setAttribute('aria-hidden', 'true'); // aria-sort says it (NUX-7)
      }
      el.setAttribute('role', 'columnheader');
      el.setAttribute('tabindex', '0');
      el.setAttribute('aria-sort', isCurrent ? (this.currentSortDir === 'asc' ? 'ascending' : 'descending') : 'none');
    });
  }

  async uploadExtractedEntries(entries, targetPath = null) {
    if (!entries || entries.length === 0) return;
    const baseDir = targetPath || this.currentPath;
    showToast(t('fm.uploading_toast', 'Uploading {count, plural, one {# file} other {# files}}…', { count: entries.length }), 'info');
    let success = 0;
    const createdDirs = new Set();

    for (const item of entries) {
      const relParts = item.relPath.split('/');
      if (relParts.length > 1) {
        const subDir = relParts.slice(0, -1).join('/');
        const fullSubDir = `${baseDir}/${subDir}`;
        if (!createdDirs.has(fullSubDir)) {
          try {
            await api.post('/api/mkdir', { path: fullSubDir });
            createdDirs.add(fullSubDir);
          } catch (_) {}
        }
      }
      const destDir = relParts.length > 1
        ? `${baseDir}/${relParts.slice(0, -1).join('/')}`
        : baseDir;

      try {
        const res = await api.postRaw(fsUploadUrl(destDir, item.file.name), item.file);
        if (res.ok) success++;
      } catch (_) {}
    }

    if (success > 0) {
      showToast(t('toast.uploaded_file_s_successfully', 'Uploaded {success} file(s) successfully', { success: success }), 'success');
      this.loadPath(this.currentPath);
      ZettEventBus.emit('fm:refresh');
    }
  }
}

export function isFmModalBlocking() {
  const modal = document.querySelector(
    '.smart-modal-backdrop.open:not(.window-minimized):not(#management-modal-overlay):not(#console-modal-overlay):not(#container-inspector-overlay):not(#stack-inspector-overlay), ' +
    '#modal-fm-collision.open, ' +
    '#confirm-toast-backdrop.open, ' +
    '#confirm-toast-modal.open, ' +
    '#mobile-sheet-backdrop.open, ' +
    '.quicklook-modal-overlay'
  );
  if (!modal) return false;
  if (
    modal.style.display === 'none' ||
    modal.classList.contains('hidden') ||
    modal.classList.contains('window-minimized')
  ) {
    return false;
  }
  return true;
}

export function ensureFmFocus(targetWin) {
  if (
    document.activeElement &&
    (document.activeElement.tagName === 'INPUT' ||
     document.activeElement.tagName === 'TEXTAREA' ||
     document.activeElement.tagName === 'SELECT' ||
     document.activeElement.isContentEditable)
  ) {
    return;
  }
  const inst = (targetWin && targetWin.id && _fmInstances.get(targetWin.id)) || getActiveFmInstance();
  if (inst) {
    inst.ensureFocus();
  } else {
    const viewport = document.getElementById('fm-viewport');
    if (viewport) {
      try { viewport.focus({ preventScroll: true }); } catch (_) {}
    }
  }
}

export function scrollIndexIntoView(idx) {
  const inst = getActiveFmInstance();
  if (inst) inst.scrollIndexIntoView(idx);
}

export function isFmActive(win) {
  if (win) {
    if (win.style.display === 'none' || win.classList.contains('window-minimized')) return false;
    if (document.activeElement && win.contains(document.activeElement)) return true;
    if (win.classList.contains('active-window')) return true;
    const inst = _fmInstances.get(win.id);
    if (inst && window.DockManager && window.DockManager.activeId === inst.dockId) return true;
    if (_activeFmInstance && _activeFmInstance.windowEl === win && _activeFmInstance.isOpen()) {
      if (!isFmModalBlocking()) {
        const otherActiveWin = document.querySelector('.os-window.active-window:not(.file-manager-window), .management-window.active-window, .container-inspector-window.active-window');
        if (!otherActiveWin) return true;
      }
    }
    if (!window.DockManager && win.style.display !== 'none') return true;
    return false;
  }
  const activeInst = getActiveFmInstance();
  if (activeInst && activeInst.windowEl) {
    return isFmActive(activeInst.windowEl);
  }
  const defaultWin = document.getElementById('file-manager-window');
  if (!defaultWin) return false;
  return isFmActive(defaultWin);
}

export function getFmSelectedPaths() {
  const inst = getActiveFmInstance();
  return inst ? Array.from(inst.selectedPaths) : [];
}

export function getFmSelectionState() {
  const inst = getActiveFmInstance();
  if (!inst) {
    return { selectedPaths: [], lastSelectedIndex: -1, selectionAnchorIndex: -1 };
  }
  return {
    selectedPaths: Array.from(inst.selectedPaths),
    lastSelectedIndex: inst.lastSelectedIndex,
    selectionAnchorIndex: inst.selectionAnchorIndex,
  };
}

export function getFmViewMode() {
  const inst = getActiveFmInstance();
  return inst ? inst.viewMode : 'list';
}

export function setFmStateForTesting(opts = {}) {
  const inst = getActiveFmInstance() || _fmInstances.get('file-manager-window');
  if (inst) {
    if (opts.fileList) {
      inst.fileList = opts.fileList;
      inst.rawFileList = [...opts.fileList];
    }
    if (opts.selectedPaths) inst.selectedPaths = new Set(opts.selectedPaths);
    if (opts.lastSelectedIndex !== undefined) inst.lastSelectedIndex = opts.lastSelectedIndex;
    if (opts.selectionAnchorIndex !== undefined) inst.selectionAnchorIndex = opts.selectionAnchorIndex;
    if (opts.currentPath !== undefined) inst.currentPath = opts.currentPath;
    if (opts.viewMode !== undefined) inst.viewMode = opts.viewMode;
  }
}

export function handleFmKeydown(e) {
  if (!e || e.defaultPrevented) return;

  const target = e.target;
  const isTextInput = target && (
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT' ||
    target.isContentEditable ||
    (target.tagName === 'INPUT' && target.type !== 'checkbox' && target.type !== 'radio')
  );
  if (isTextInput) return;

  if (isFmModalBlocking()) {
    return;
  }

  let inst = null;
  if (target && typeof target.closest === 'function') {
    const winEl = target.closest('.file-manager-window');
    if (winEl && winEl.id && _fmInstances.has(winEl.id)) {
      inst = _fmInstances.get(winEl.id);
    }
  }
  if (!inst) {
    inst = getActiveFmInstance();
  }
  if (!inst || !isFmActive(inst.windowEl)) return;

  // Intercept File Explorer keyboard actions to prevent focus leakage to desktop icons
  const fmNavKeys = ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageDown', 'PageUp'];
  const fmActKeys = ['Enter', 'Escape', 'F2', 'Delete', 'Backspace', ' '];
  const isLetterShortcut = (e.ctrlKey || e.metaKey) && ['a', 'c', 'x', 'v', 'd', 'f', 'n'].includes(e.key?.toLowerCase());

  if (fmNavKeys.includes(e.key) || fmActKeys.includes(e.key) || isLetterShortcut) {
    if (target && !inst.windowEl.contains(target)) {
      document.querySelectorAll('.chassis-hero-box').forEach((el) => {
        try { el.blur(); } catch (_) {}
      });
      inst.ensureFocus();
    }
    inst.handleKeydown(e);
  }
}

export function openNewFileManagerWindow(path = null) {
  _fmInstanceSeq++;
  const instId = `file-manager-window-${_fmInstanceSeq}`;
  const dockId = `fm-${_fmInstanceSeq}`;
  const targetPath = path || (getActiveFmInstance()?.currentPath) || '/mnt/user';

  const inst = new FileManagerWindow(instId, dockId, targetPath, false);
  _fmInstances.set(instId, inst);
  inst.init();

  // Modulo cascade position
  const count = _fmInstances.size - 1;
  const maxLeft = Math.max(24, window.innerWidth - 680);
  const maxTop = Math.max(56, window.innerHeight - 480);
  const left = 24 + ((count * 32) % (maxLeft || 1));
  const top = 56 + ((count * 32) % (maxTop || 1));

  inst.windowEl.style.left = `${left}px`;
  inst.windowEl.style.top = `${top}px`;
  inst.windowEl.style.width = '720px';
  inst.windowEl.style.height = '500px';

  inst.open();
  return inst;
}
window.openNewFileManagerWindow = openNewFileManagerWindow;

export function closeAllFileManagerWindows() {
  const instances = Array.from(_fmInstances.values());
  instances.forEach((inst) => {
    inst.destroy();
  });
  _activeFmInstance = null;
}
window.closeAllFileManagerWindows = closeAllFileManagerWindows;
window.getActiveFmInstance = getActiveFmInstance;

export function openFileManager(path = null) {
  let primary = _fmInstances.get('file-manager-window');
  if (!primary) {
    initFileManager();
    primary = _fmInstances.get('file-manager-window');
  }
  if (primary) {
    primary.open(path);
  }
  ZettEventBus.emit('window:open', { id: 'file-manager-window', path: path || undefined });
}
window.openFileManager = openFileManager;

window.navigateToPath = (path = null) => {
  if (typeof window.openFileManager === 'function') {
    window.openFileManager(path);
  } else {
    ZettEventBus.emit('window:open', { id: 'file-manager-window', path: path || undefined });
  }
};

window.openRecycleBin = () => {
  let target = '/mnt/user/.RecycleBin';
  if (window._fmRoots && window._fmRoots.length > 0) {
    if (window._fmRoots.includes('/mnt/user')) target = '/mnt/user/.RecycleBin';
    else if (window._fmRoots.includes('/mnt/storage')) target = '/mnt/storage/.RecycleBin';
    else target = `${window._fmRoots[0].replace(/\/$/, '')}/.RecycleBin`;
  } else {
    const cur = getActiveFmInstance()?.currentPath;
    if (cur && cur.startsWith('/mnt/storage')) target = '/mnt/storage/.RecycleBin';
  }
  ZettEventBus.emit('window:open', { id: 'file-manager-window', path: target });
};

export function initFileManager() {
  if (window._fmInitialized) return;
  window._fmInitialized = true;

  // Initialize primary instance
  const currentPath = localStorage.getItem('zettnas_fm_last_path') || '/mnt/user';
  let primary = _fmInstances.get('file-manager-window');
  if (!primary) {
    primary = new FileManagerWindow('file-manager-window', 'fm', currentPath, true);
    _fmInstances.set('file-manager-window', primary);
  }
  _activeFmInstance = primary;
  primary.init();

  const fmIcon = document.getElementById('fm-desktop-icon');
  const openFm = (e) => {
    if (e && e.type === 'touchend') e.preventDefault();
    document.querySelectorAll('.chassis-hero-box').forEach((el) => {
      try { el.blur(); } catch (_) {}
    });

    primary.open();
    ZettEventBus.emit('window:open', { id: 'file-manager-window' });
  };

  if (fmIcon) {
    const blurDesktopIcons = () => {
      document.querySelectorAll('.chassis-hero-box').forEach((el) => {
        try { el.blur(); } catch (_) {}
      });
    };
    fmIcon.addEventListener('mousedown', blurDesktopIcons);
    fmIcon.addEventListener('pointerdown', blurDesktopIcons);
    fmIcon.addEventListener('click', openFm);
    fmIcon.addEventListener('touchend', openFm);
    fmIcon.addEventListener('dblclick', openFm);
    fmIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openFm();
      }
    });
  }

  ZettEventBus.on('window:open', (payload) => {
    if (payload.id === 'file-manager-window') {
      primary.open(payload.path);
    }
  });

  // Cross-window sync: refresh all open File Explorer instances
  ZettEventBus.on('fm:refresh', () => {
    const refreshAll = () => {
      _fmInstances.forEach((inst) => {
        if (inst.isOpen()) {
          inst._retainingRefresh = true;
          inst.loadPath(inst.currentPath);
          if (inst.sidebarTree) {
            inst.sidebarTree.refresh();
          }
        }
      });
    };
    refreshAll();
    setTimeout(refreshAll, 350);
  });

  if (typeof document !== 'undefined' && !document._fmDocKbBound) {
    document._fmDocKbBound = true;
    document.addEventListener('keydown', handleFmKeydown);
  }
}

export async function executeTransferWithConflictCheck(sources, destinationDir, action = 'copy') {
  if (!sources || sources.length === 0) return;
  const normDst = (destinationDir || '').replace(/\/+$/, '');
  const validSources = sources.filter((s) => {
    const normSrc = (s || '').replace(/\/+$/, '');
    return normSrc !== normDst && !normDst.startsWith(normSrc + '/');
  });

  if (validSources.length === 0) {
    showToast(t('fm.err_drop_into_self', 'Cannot move an item into itself or its own subfolder.'), 'warning');
    return;
  }

  if (action === 'move') {
    const sameFolderSources = validSources.filter((s) => {
      const parent = s.substring(0, s.lastIndexOf('/')) || '/';
      return parent === normDst;
    });
    if (sameFolderSources.length === validSources.length) {
      // Items are already in destination directory
      return;
    }
  }

  try {
    const checkRes = await api.post('/api/fs/conflict-check', {
      sources: validSources,
      destination_dir: destinationDir,
    });

    if (!checkRes.has_conflict) {
      await transferCenter.startTransfer({ sources: validSources, destinationDir, action, policy: 'merge' });
      return;
    }

    showCollisionModal({
      sources: validSources,
      destinationDir,
      action,
      conflicts: checkRes.conflicts,
      onResolved: () => {
        ZettEventBus.emit('fm:refresh');
      },
    });
  } catch (err) {
    showToast(t('toast.transfer_failed', 'Transfer failed: {error}', { error: err.message }), 'error');
  }
}

export function showCollisionModal({ sources, destinationDir, action, conflicts, onResolved }) {
  let modal = document.getElementById('modal-fm-collision');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-fm-collision';
    document.body.appendChild(modal);
  }
  modal.className = 'smart-modal-backdrop open';
  modal.style.zIndex = '9500';
  modal.style.display = 'flex';

  const hasDir = conflicts && conflicts.some((c) => c.is_dir);

  modal.innerHTML = `
    <div class="fm-collision-dialog glassmorphic-card" style="padding: 24px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
        <h3 style="margin: 0; font-size: 16px; font-weight: 700; color: var(--zn-text-strong); display: flex; align-items: center; gap: 8px;">
          <span aria-hidden="true">⚠️</span> <span>${escapeHtml(t('fm.collision_title', 'File & Directory Conflict'))}</span>
        </h3>
        <button id="fm-collision-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 18px; line-height: 1; padding: 2px 6px; border-radius: 4px;" title="${escapeHtml(t('common.close', 'Close'))}">✕</button>
      </div>
      <p style="font-size: var(--zn-fs-xs); color: var(--muted); margin: 0 0 12px 0;">
        ${escapeHtml(t('fm.collision_desc', 'The following files or directories already exist at the destination:'))}
      </p>
      <div style="background: var(--zn-shade-30); border: 1px solid var(--zn-line-8); border-radius: 8px; padding: 10px; max-height: 180px; overflow-y: auto; margin-bottom: 16px;">
        ${(conflicts || [])
          .map(
            (c) => `
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 4px; border-bottom: 1px solid var(--lt-r-ffffff0a, rgba(255,255,255,0.04)); font-size: var(--zn-fs-xs);">
            <div style="display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              <span>${c.is_dir ? '📁' : '📄'}</span>
              <span style="font-weight: 600; color: var(--zn-text-strong);">${escapeHtml(c.name)}</span>
            </div>
            <span style="font-size: var(--zn-fs-xs); color: var(--muted);">${c.is_dir ? 'Directory' : formatBytes(c.dest_size || 0)}</span>
          </div>
        `
          )
          .join('')}
      </div>
      <div style="margin-bottom: 18px;">
        <label style="display: flex; align-items: center; gap: 8px; font-size: var(--zn-fs-xs); color: var(--muted); cursor: pointer;">
          <input type="checkbox" id="fm-collision-apply-all" checked style="accent-color: var(--accent-cyan, #0ea5e9);" />
          <span>${escapeHtml(t('fm.apply_all', 'Apply to all conflicts'))}</span>
        </label>
      </div>
      <div style="display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap;">
        <button id="fm-collision-cancel" class="btn-pill-toggle" style="background: var(--zn-glaze-6); border: 1px solid var(--zn-line-12); color: var(--zn-text-muted);">${escapeHtml(t('fm.cancel', 'Cancel'))}</button>
        <button id="fm-collision-skip" class="btn-pill-toggle" style="background: var(--zn-glaze-8); border: 1px solid var(--zn-line-18); color: var(--zn-text);">${escapeHtml(t('fm.skip', 'Skip'))}</button>
        ${
          !hasDir
            ? `
          <button id="fm-collision-keep-both" class="btn-pill-toggle" style="background: var(--zn-glaze-8); border: 1px solid var(--zn-line-18); color: var(--zn-text);">${escapeHtml(t('fm.keep_both', 'Keep Both'))}</button>
        `
            : ''
        }
        <button id="fm-collision-overwrite" class="btn-pill-toggle is-danger">${escapeHtml(t('fm.overwrite', 'Overwrite'))}</button>
        ${
          hasDir
            ? `
          <button id="fm-collision-merge" class="btn-pill-toggle is-primary" style="box-shadow: 0 4px 14px rgba(14, 165, 233, 0.35);">${escapeHtml(t('fm.merge', 'Merge'))}</button>
        `
            : ''
        }
      </div>
    </div>
  `;

  const closeModal = () => {
    modal.style.display = 'none';
    modal.classList.remove('open');
  };

  const executeWithPolicy = async (policy) => {
    closeModal();
    await transferCenter.startTransfer({
      sources,
      destinationDir,
      action,
      policy,
      onDone: () => {
        if (typeof onResolved === 'function') onResolved({ destinationDir, sources, action, policy });
      },
    });
  };

  const btnClose = modal.querySelector('#fm-collision-close');
  if (btnClose) btnClose.onclick = closeModal;

  const btnCancel = modal.querySelector('#fm-collision-cancel');
  if (btnCancel) btnCancel.onclick = closeModal;

  const btnSkip = modal.querySelector('#fm-collision-skip');
  if (btnSkip) btnSkip.onclick = () => executeWithPolicy('skip');

  const btnOverwrite = modal.querySelector('#fm-collision-overwrite');
  if (btnOverwrite) btnOverwrite.onclick = () => executeWithPolicy('overwrite');

  const btnKeepBoth = modal.querySelector('#fm-collision-keep-both');
  if (btnKeepBoth) btnKeepBoth.onclick = () => executeWithPolicy('keep_both');

  const btnMerge = modal.querySelector('#fm-collision-merge');
  if (btnMerge) btnMerge.onclick = () => executeWithPolicy('merge');

  modal.style.display = 'flex';
  modal.classList.add('open');
}

export function openMediaOrganizerModal(initialPath = '') {
  const modal = document.getElementById('modal-media-organizer');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-media-org-close-btn');
  const cancelBtn = document.getElementById('modal-media-org-cancel-btn');
  const srcInput = document.getElementById('media-org-source-input');
  const dstInput = document.getElementById('media-org-dest-input');
  const modeSelect = document.getElementById('media-org-mode-select');
  const btnPreview = document.getElementById('btn-media-org-preview');
  const btnApply = document.getElementById('btn-media-org-apply');
  const previewWrap = document.getElementById('media-org-preview-wrap');

  let previewItems = [];

  function closeModal() {
    modal.style.display = 'none';
    modal.classList.remove('open');
    if (btnApply) {
      btnApply.disabled = true;
      btnApply.style.opacity = '0.5';
      btnApply.style.cursor = 'not-allowed';
    }
  }

  if (closeBtn) closeBtn.onclick = closeModal;
  if (cancelBtn) cancelBtn.onclick = closeModal;
  modal.onclick = (e) => {
    if (e.target === modal) closeModal();
  };

  if (srcInput && (!srcInput.value || initialPath)) {
    srcInput.value = initialPath || '/mnt/user/downloads';
  }
  if (dstInput && !dstInput.value) {
    dstInput.value = '/mnt/user/media';
  }

  if (btnPreview) {
    btnPreview.onclick = async () => {
      const source_dir = (srcInput?.value || '').trim();
      const target_dir = (dstInput?.value || '').trim();
      if (!source_dir || !target_dir) {
        showToast(t('toast.please_specify_both_source_and_destination', 'Please specify both source and destination folders.'), 'warning');
        return;
      }

      btnPreview.disabled = true;
      btnPreview.innerHTML = '<span aria-hidden="true">⏳</span> <span>Analyzing...</span>';
      if (previewWrap) {
        previewWrap.innerHTML =
          '<div style="text-align:center; padding:25px; color:var(--muted); font-size:var(--zn-fs-xs);"><div class="loader-spinner" style="margin:0 auto 10px;"></div>Parsing media files via regex heuristics...</div>';
      }

      try {
        const res = await api.post('/api/media/organize/preview', { source_dir, target_dir });
        const items = res.items || [];
        previewItems = items;

        if (items.length === 0) {
          if (previewWrap) {
            previewWrap.innerHTML = '<div style="text-align:center; padding:25px; color:var(--muted); font-size:var(--zn-fs-xs);">No video files found in source folder.</div>';
          }
          if (btnApply) {
            btnApply.disabled = true;
            btnApply.style.opacity = '0.5';
            btnApply.style.cursor = 'not-allowed';
          }
          return;
        }

        if (previewWrap) {
          previewWrap.innerHTML = `
            <div style="font-size:var(--zn-fs-xs); padding:8px 12px; background:var(--zn-glaze-3); border-bottom:1px solid var(--zn-line-8); font-weight:700; color:var(--muted); display:flex; justify-content:space-between;">
              <span>Detected ${items.length} file(s) for reorganization:</span>
              <span>Plex / Jellyfin Schema</span>
            </div>
            <div style="display:flex; flex-direction:column;">
              ${items
                .map((it) => {
                  const isTv = it.media_type === 'tv';
                  const typeBadge = isTv
                    ? `<span class="ci-badge" style="font-size:var(--zn-fs-xs); background:rgba(168,85,247,0.15); color:var(--zn-text-ai); border:1px solid rgba(168,85,247,0.3); padding:1px 5px; border-radius:3px;">TV Show · S${String(it.season || 1).padStart(2, '0')}E${String(it.episode || 1).padStart(2, '0')}</span>`
                    : `<span class="ci-badge" style="font-size:var(--zn-fs-xs); background:rgba(14,165,233,0.15); color:var(--zn-text-accent); border:1px solid rgba(14,165,233,0.3); padding:1px 5px; border-radius:3px;">Movie ${it.year ? `(${it.year})` : ''}</span>`;
                  const qualBadge = `<span class="ci-badge" style="font-size:var(--zn-fs-xs); background:var(--zn-glaze-6); color:var(--zn-text-soft); padding:1px 5px; border-radius:3px;">${escapeHtml(it.resolution || '1080p')} · ${escapeHtml(it.codec || 'x264')}</span>`;

                  return `
                  <div style="padding:8px 12px; border-bottom:1px solid var(--lt-r-ffffff0a, rgba(255,255,255,0.04)); display:flex; flex-direction:column; gap:4px; font-size:var(--zn-fs-xs);">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                      <div style="font-weight:700; color:var(--zn-text-strong); word-break:break-all;">${escapeHtml(it.title || it.original_filename)}</div>
                      <div style="display:flex; gap:6px;">${typeBadge}${qualBadge}</div>
                    </div>
                    <div style="color:var(--muted); font-size:var(--zn-fs-xs); font-family:monospace; display:flex; align-items:center; gap:6px;">
                      <span style="color:var(--zn-text-crit); text-decoration:line-through;">${escapeHtml(it.original_filename)}</span>
                      <span aria-hidden="true">➔</span>
                      <span style="color:var(--lt-t-4ade80ff, #4ade80);">${escapeHtml(it.proposed_relative_path)}</span>
                    </div>
                  </div>
                `;
                })
                .join('')}
            </div>
          `;
        }

        if (btnApply) {
          btnApply.disabled = false;
          btnApply.style.opacity = '1';
          btnApply.style.cursor = 'pointer';
        }
      } catch (err) {
        showToast(t('toast.preview_failed', 'Preview failed: {error}', { error: err.message }), 'error');
        if (previewWrap) {
          previewWrap.innerHTML = `<div style="text-align:center; padding:25px; color:var(--alert, var(--lt-t-ef4444ff, #ef4444)); font-size:var(--zn-fs-xs);">Failed: ${escapeHtml(err.message)}</div>`;
        }
      } finally {
        btnPreview.disabled = false;
        btnPreview.innerHTML = '🔍 <span>Scan & Preview Diff</span>';
      }
    };
  }

  if (btnApply) {
    btnApply.onclick = async () => {
      if (!previewItems || previewItems.length === 0) return;
      const mode = modeSelect?.value || 'hardlink';
      const action = mode === 'move' ? 'move' : 'copy';
      const hardlink = mode === 'hardlink';

      btnApply.disabled = true;
      btnApply.innerHTML = '<span aria-hidden="true">⏳</span> <span>Organizing...</span>';

      try {
        const res = await api.post('/api/media/organize/apply', {
          items: previewItems,
          action,
          hardlink,
        });

        const procCount = res.processed != null ? res.processed : previewItems.length;
        showToast(t('media.success', `Media organization completed successfully (${procCount} files).`), 'success');
        closeModal();
        if (typeof openFileManager === 'function') {
          openFileManager(srcInput?.value || initialPath);
        }
      } catch (err) {
        showToast(t('toast.failed_to_execute_reorganization', 'Failed to execute reorganization: {error}', { error: err.message }), 'error');
      } finally {
        btnApply.disabled = false;
        btnApply.innerHTML = t('media.apply_btn', 'Execute Reorganization');
      }
    };
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
}

// Where the share pop-over opens: next to the button or menu item that was clicked
let _lastPointer = null;
if (typeof document !== 'undefined') {
  document.addEventListener('pointerdown', (e) => {
    _lastPointer = { x: e.clientX, y: e.clientY, el: e.target instanceof Element ? e.target : null, t: Date.now() };
  }, true);
}

/** Places a pop-over below its anchor, right edges aligned, flipped above and kept on screen. */
export function placePopover(pop, anchorRect, gap = 8, margin = 12) {
  const w = pop.offsetWidth || 480;
  const h = pop.offsetHeight || 360;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = anchorRect.right - w;
  let top = anchorRect.bottom + gap;
  if (top + h > vh - margin && anchorRect.top - gap - h >= margin) top = anchorRect.top - gap - h;
  left = Math.max(margin, Math.min(left, vw - w - margin));
  top = Math.max(margin, Math.min(top, vh - h - margin));
  pop.style.left = `${Math.round(left)}px`;
  pop.style.top = `${Math.round(top)}px`;
}

function shareAnchorRect(anchorEl) {
  const el = anchorEl || (_lastPointer && Date.now() - _lastPointer.t < 3000 ? _lastPointer.el?.closest('button, .fm-ctx-item, [data-act]') : null);
  const rect = el && el.isConnected ? el.getBoundingClientRect() : null;
  if (rect && (rect.width || rect.height)) return rect; // a closed menu's item has no size
  if (_lastPointer && Date.now() - _lastPointer.t < 3000) {
    return { left: _lastPointer.x, right: _lastPointer.x, top: _lastPointer.y, bottom: _lastPointer.y };
  }
  return { left: window.innerWidth / 2 + 240, right: window.innerWidth / 2 + 240, top: 80, bottom: 80 };
}

export function openShareLinkModal(path, fileName, anchorEl = null) {
  const anchorRect = shareAnchorRect(anchorEl);
  let modal = document.getElementById('modal-fm-share-link');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-fm-share-link';
    document.body.appendChild(modal);
  }
  // A pop-up window that does not block the rest: it stays open until closed, like other windows
  modal.className = 'dlg-modeless fm-share-layer';

  const safeName = escapeHtml(fileName || path.split('/').pop());

  modal.innerHTML = `
    <div class="smart-modal-window fm-share-popover" role="dialog" aria-labelledby="fm-share-title" data-dock-icon="#i-globe">
      <div class="smart-modal-header">
        <span class="smart-modal-title" id="fm-share-title"><span aria-hidden="true">🔗</span> Public Share Link</span>
        <div class="os-window-controls">
          <button type="button" id="fm-share-close" class="win-btn close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
        </div>
      </div>
      <div class="smart-modal-body fm-share-body">
      <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 16px;">
        Generate an instant, secure download link for <strong style="color: var(--zn-text-strong);">${safeName}</strong> that can be shared with anyone.
      </div>

      <div id="fm-share-create-section">
        <div class="form-group" style="margin-bottom: 14px;">
          <label for="fm-share-expires" style="display: block; font-size: var(--zn-fs-xs); font-weight: 600; color: var(--zn-text-muted); margin-bottom: 6px;">Link Expiration</label>
          <select id="fm-share-expires" style="width: 100%; padding: 8px 12px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-15); border-radius: 6px; color: var(--zn-text-strong); font-size: var(--zn-fs-xs);">
            <option value="1">1 Hour</option>
            <option value="24" selected>24 Hours (1 Day)</option>
            <option value="168">7 Days</option>
            <option value="720">30 Days</option>
            <option value="0">Never Expires</option>
          </select>
        </div>

        <div class="form-group" style="margin-bottom: 14px;">
          <label for="fm-share-password" style="display: block; font-size: var(--zn-fs-xs); font-weight: 600; color: var(--zn-text-muted); margin-bottom: 6px;">Password Protection (Optional)</label>
          <input type="password" id="fm-share-password" placeholder="${t('ui.leave_empty_for_public_access', 'Leave empty for public access')}" style="width: 100%; padding: 8px 12px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-15); border-radius: 6px; color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
        </div>

        <div class="form-group" style="margin-bottom: 18px;">
          <label for="fm-share-max-dl" style="display: block; font-size: var(--zn-fs-xs); font-weight: 600; color: var(--zn-text-muted); margin-bottom: 6px;">Max Downloads (Optional)</label>
          <input type="number" id="fm-share-max-dl" min="1" placeholder="${t('ui.unlimited', 'Unlimited')}" style="width: 100%; padding: 8px 12px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-15); border-radius: 6px; color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button id="fm-share-cancel" class="btn-pill-toggle">Cancel</button>
          <button id="fm-share-submit" class="btn-pill-toggle active is-primary">✨ Generate Share Link</button>
        </div>
      </div>

      <div id="fm-share-result-section" style="display: none;">
        <div style="padding: 12px; border-radius: 8px; background: rgba(14, 165, 233, 0.08); border: 1px solid rgba(14, 165, 233, 0.25); margin-bottom: 16px;">
          <div style="font-size: var(--zn-fs-xs); color: var(--zn-text-accent); font-weight: 600; margin-bottom: 6px;">Link Generated Successfully!</div>
          <div style="display: flex; gap: 8px;">
            <input type="text" id="fm-share-url-output" readonly style="flex: 1; padding: 8px 10px; background: var(--zn-shade-40); border: 1px solid var(--zn-line-15); border-radius: 6px; color: var(--zn-text-strong); font-size: var(--zn-fs-xs); font-family: monospace;" />
            <button id="fm-share-copy-btn" class="btn-pill-toggle active is-primary">📋 Copy</button>
          </div>
        </div>
        <div id="fm-share-meta-info" style="font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 16px;"></div>
        <div style="display: flex; justify-content: flex-end;">
          <button id="fm-share-done" class="btn-pill-toggle">Done</button>
        </div>
      </div>
      </div>
    </div>
  `;

  const closeModal = () => {
    modal.style.display = 'none';
    modal.classList.remove('open');
  };
  // Esc closes it while it has focus
  modal.querySelector('.fm-share-popover')?.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      closeModal();
    }
  });

  const closeBtn = modal.querySelector('#fm-share-close');
  if (closeBtn) closeBtn.onclick = closeModal;
  const cancelBtn = modal.querySelector('#fm-share-cancel');
  if (cancelBtn) cancelBtn.onclick = closeModal;

  const submitBtn = modal.querySelector('#fm-share-submit');
  if (submitBtn) {
    submitBtn.onclick = async () => {
      submitBtn.disabled = true;
      submitBtn.textContent = t('ui.generating', 'Generating...');

      const expSelect = modal.querySelector('#fm-share-expires');
      const expHours = expSelect ? parseInt(expSelect.value, 10) : 24;
      const pwdInput = modal.querySelector('#fm-share-password');
      const pwd = pwdInput ? pwdInput.value.trim() : '';
      const maxDlInput = modal.querySelector('#fm-share-max-dl');
      const maxDl = maxDlInput ? parseInt(maxDlInput.value, 10) : 0;

      try {
        const res = await api.post('/api/fs/share-links', {
          path,
          expires_hours: expHours > 0 ? expHours : null,
          password: pwd || null,
          max_downloads: maxDl > 0 ? maxDl : null,
        });

        const fullUrl = `${window.location.origin}${res.url}`;
        const createSec = modal.querySelector('#fm-share-create-section');
        const resSec = modal.querySelector('#fm-share-result-section');
        if (createSec) createSec.style.display = 'none';
        if (resSec) resSec.style.display = 'block';
        const popEl = modal.querySelector('.fm-share-popover');
        if (popEl) placePopover(popEl, anchorRect); // taller now: keep it on screen

        const urlInput = modal.querySelector('#fm-share-url-output');
        if (urlInput) urlInput.value = fullUrl;

        // Auto-copy
        copyTextToClipboard(fullUrl);
        showToast(t('toast.share_link_generated_and_copied_to', 'Share link generated and copied to clipboard!'), 'success');

        const copyBtn = modal.querySelector('#fm-share-copy-btn');
        if (copyBtn) {
          copyBtn.onclick = () => {
            copyTextToClipboard(fullUrl);
            showToast(t('toast.link_copied_to_clipboard', 'Link copied to clipboard!'), 'success');
          };
        }

        const metaEl = modal.querySelector('#fm-share-meta-info');
        if (metaEl) {
          let metaText = res.expires_at ? `Expires in ${expHours} hour(s)` : 'Never expires';
          if (res.has_password) metaText += ' • Password protected';
          if (res.max_downloads) metaText += ` • Max ${res.max_downloads} download(s)`;
          metaEl.textContent = metaText;
        }

        const doneBtn = modal.querySelector('#fm-share-done');
        if (doneBtn) doneBtn.onclick = closeModal;
      } catch (err) {
        showToast(t('toast.failed_to_create_share_link', 'Failed to create share link: {error}', { error: err.message }), 'error');
        submitBtn.disabled = false;
        submitBtn.textContent = t('ui.generate_share_link', '✨ Generate Share Link');
      }
    };
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
  const pop = modal.querySelector('.fm-share-popover');
  if (pop) placePopover(pop, anchorRect);
  modal.querySelector('#fm-share-expires')?.focus();
}

if (typeof window !== 'undefined') {
  window.openShareLinkModal = openShareLinkModal;
}

