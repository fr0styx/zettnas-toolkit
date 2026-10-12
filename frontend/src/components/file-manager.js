import { api, auth, ApiError } from '../api.js';
import { escapeHtml } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast, showPromptToast } from '../toast.js';
import { t } from '../i18n.js';
import { makeDraggable, bringToFront } from './dock.js';

let fmWindow = null;
let currentPath = localStorage.getItem('zettnas_fm_last_path') || '/mnt/user';
let fileList = [];

let currentSortBy = 'name';
let currentSortDir = 'asc';
let selectedPaths = new Set();
let lastSelectedIndex = -1;
let selectionAnchorIndex = -1;
let _clipboard = { items: [], action: 'copy' };

function updateFmSelectionToolbar() {
  const bar = document.getElementById('fm-selection-bar');
  const countSpan = document.getElementById('fm-selected-count');
  const bulkDelBtn = document.getElementById('fm-bulk-delete-btn');
  if (!bar || !countSpan) return;
  const count = selectedPaths.size;
  if (count > 0) {
    bar.style.display = 'inline-flex';
    let totalBytes = 0;
    fileList.forEach(f => {
      if (selectedPaths.has(f.path) && !f.is_dir && typeof f.size === 'number') {
        totalBytes += f.size;
      }
    });
    const sizeStr = totalBytes > 0 ? ` (${formatBytes(totalBytes)})` : '';
    countSpan.textContent = `✓ ${t('fm.selected_count', `${count} selected`).replace('{count}', count)}${sizeStr}`;
    if (bulkDelBtn) bulkDelBtn.textContent = `🗑️ ${t('fm.bulk_delete', `Delete (${count})`).replace('{count}', count)}`;
  } else {
    bar.style.display = 'none';
  }
}

function updateRowSelectionUI() {
  const rows = document.querySelectorAll('.fm-row');
  rows.forEach(r => {
    const p = r.dataset.path;
    const isSel = Boolean(p && selectedPaths.has(p));
    if (isSel) {
      r.classList.add('selected');
    } else {
      r.classList.remove('selected');
    }
    const chk = r.querySelector('.fm-row-checkbox');
    if (chk) chk.checked = isSel;
  });

  const masterChk = document.getElementById('fm-select-all-checkbox');
  if (masterChk) {
    const selectableFiles = fileList.filter(f => f.name !== '..');
    const totalSelectable = selectableFiles.length;
    const count = selectedPaths.size;
    if (totalSelectable > 0 && count === totalSelectable) {
      masterChk.checked = true;
      masterChk.indeterminate = false;
    } else if (count > 0) {
      masterChk.checked = false;
      masterChk.indeterminate = true;
    } else {
      masterChk.checked = false;
      masterChk.indeterminate = false;
    }
  }
}

// Virtualized DOM logic
const ROW_HEIGHT = 42;
const BUFFER = 5;

export function ensureFmFocus() {
  const viewport = document.getElementById('fm-viewport');
  if (!viewport) return;
  const active = document.activeElement;
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT' || active.isContentEditable)) {
    return;
  }
  const win = fmWindow || document.getElementById('file-manager-window');
  if (win && win.contains(active) && active !== win && active !== viewport) {
    return;
  }
  try {
    viewport.focus({ preventScroll: true });
  } catch (_) {}
}

export function scrollIndexIntoView(idx) {
  const viewport = document.getElementById('fm-viewport');
  if (!viewport || idx < 0) return;
  const targetTop = idx * ROW_HEIGHT;
  const targetBottom = targetTop + ROW_HEIGHT;
  const viewTop = viewport.scrollTop;
  const viewHeight = viewport.clientHeight || 400;
  const viewBottom = viewTop + viewHeight;

  if (targetTop < viewTop) {
    viewport.scrollTop = targetTop;
  } else if (targetBottom > viewBottom) {
    viewport.scrollTop = Math.max(0, targetBottom - viewHeight);
  }
  renderViewport();
}

export function isFmActive() {
  const win = fmWindow || document.getElementById('file-manager-window');
  if (!win) return false;
  if (win.style.display === 'none' || win.classList.contains('window-minimized')) return false;
  if (document.activeElement && win.contains(document.activeElement)) return true;
  if (win.classList.contains('active-window')) return true;
  if (window.DockManager && window.DockManager.activeId === 'fm') return true;
  if (!window.DockManager && win.style.display !== 'none') return true;
  return false;
}

export function getFmSelectedPaths() {
  return Array.from(selectedPaths);
}

export function getFmSelectionState() {
  return {
    selectedPaths: Array.from(selectedPaths),
    lastSelectedIndex,
    selectionAnchorIndex,
  };
}

export function setFmStateForTesting(opts = {}) {
  if (opts.fileList) fileList = opts.fileList;
  if (opts.selectedPaths) selectedPaths = new Set(opts.selectedPaths);
  if (opts.lastSelectedIndex !== undefined) lastSelectedIndex = opts.lastSelectedIndex;
  if (opts.selectionAnchorIndex !== undefined) selectionAnchorIndex = opts.selectionAnchorIndex;
  if (opts.currentPath !== undefined) currentPath = opts.currentPath;
}

export function handleFmKeydown(e) {
  if (!e || e.defaultPrevented) return;
  if (!isFmActive()) return;

  const target = e.target;
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) {
    return;
  }
  // Check if any modal or toast prompt is active over the UI
  if (document.querySelector('.smart-modal-backdrop.open, .smart-modal-backdrop:not([style*="display: none"]):not([style*="display:none"]), .toast-prompt-backdrop, #modal-fm-collision.open')) {
    return;
  }

  const minSelectableIndex = (fileList[0]?.name === '..') ? 1 : 0;
  const hasSelectableFiles = fileList.length > minSelectableIndex;

  if (e.key === 'Escape') {
    if (selectedPaths.size > 0) {
      e.preventDefault();
      e.stopPropagation();
      selectedPaths.clear();
      lastSelectedIndex = -1;
      selectionAnchorIndex = -1;
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    }
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
    e.preventDefault();
    e.stopPropagation();
    selectedPaths.clear();
    fileList.forEach((f) => {
      if (f.name !== '..') {
        selectedPaths.add(f.path);
      }
    });
    lastSelectedIndex = fileList.length - 1;
    selectionAnchorIndex = minSelectableIndex;
    updateRowSelectionUI();
    updateFmSelectionToolbar();
  } else if (e.key === 'Delete' || (e.metaKey && e.key === 'Backspace')) {
    if (selectedPaths.size > 0) {
      e.preventDefault();
      e.stopPropagation();
      document.getElementById('fm-bulk-delete-btn')?.click();
    }
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
    if (selectedPaths.size > 0) {
      e.preventDefault();
      e.stopPropagation();
      _clipboard = { items: Array.from(selectedPaths), action: 'copy' };
      const msg = t('fm.copied_clipboard', `Copied ${selectedPaths.size} item(s) to clipboard`).replace('{count}', selectedPaths.size);
      showToast(msg, 'info');
    }
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'x') {
    if (selectedPaths.size > 0) {
      e.preventDefault();
      e.stopPropagation();
      _clipboard = { items: Array.from(selectedPaths), action: 'move' };
      const msg = t('fm.cut_clipboard', `Cut ${selectedPaths.size} item(s) to clipboard`).replace('{count}', selectedPaths.size);
      showToast(msg, 'info');
    }
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') {
    if (_clipboard && _clipboard.items && _clipboard.items.length > 0) {
      e.preventDefault();
      e.stopPropagation();
      executeTransferWithConflictCheck(_clipboard.items, currentPath, _clipboard.action);
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    e.stopPropagation();
    ensureFmFocus();
    if (!hasSelectableFiles) return;

    if (lastSelectedIndex === -1) {
      const targetIdx = minSelectableIndex;
      lastSelectedIndex = targetIdx;
      selectionAnchorIndex = targetIdx;
      selectedPaths.clear();
      if (fileList[targetIdx] && fileList[targetIdx].name !== '..') {
        selectedPaths.add(fileList[targetIdx].path);
      }
      scrollIndexIntoView(targetIdx);
      updateRowSelectionUI();
      updateFmSelectionToolbar();
      return;
    }

    if (e.shiftKey) {
      if (selectionAnchorIndex === -1) selectionAnchorIndex = lastSelectedIndex;
      const nextIdx = Math.min(fileList.length - 1, lastSelectedIndex + 1);
      lastSelectedIndex = nextIdx;
      selectedPaths.clear();
      const start = Math.min(selectionAnchorIndex, lastSelectedIndex);
      const end = Math.max(selectionAnchorIndex, lastSelectedIndex);
      for (let j = start; j <= end; j++) {
        if (fileList[j] && fileList[j].name !== '..') {
          selectedPaths.add(fileList[j].path);
        }
      }
      scrollIndexIntoView(lastSelectedIndex);
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    } else if (!e.ctrlKey && !e.metaKey) {
      const targetIdx = Math.min(fileList.length - 1, lastSelectedIndex + 1);
      lastSelectedIndex = targetIdx;
      selectionAnchorIndex = targetIdx;
      selectedPaths.clear();
      if (fileList[targetIdx] && fileList[targetIdx].name !== '..') {
        selectedPaths.add(fileList[targetIdx].path);
      }
      scrollIndexIntoView(targetIdx);
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    e.stopPropagation();
    ensureFmFocus();
    if (!hasSelectableFiles) return;

    if (lastSelectedIndex === -1) {
      const targetIdx = fileList.length - 1;
      lastSelectedIndex = targetIdx;
      selectionAnchorIndex = targetIdx;
      selectedPaths.clear();
      if (fileList[targetIdx] && fileList[targetIdx].name !== '..') {
        selectedPaths.add(fileList[targetIdx].path);
      }
      scrollIndexIntoView(targetIdx);
      updateRowSelectionUI();
      updateFmSelectionToolbar();
      return;
    }

    if (e.shiftKey) {
      if (selectionAnchorIndex === -1) selectionAnchorIndex = lastSelectedIndex;
      const prevIdx = Math.max(minSelectableIndex, lastSelectedIndex - 1);
      lastSelectedIndex = prevIdx;
      selectedPaths.clear();
      const start = Math.min(selectionAnchorIndex, lastSelectedIndex);
      const end = Math.max(selectionAnchorIndex, lastSelectedIndex);
      for (let j = start; j <= end; j++) {
        if (fileList[j] && fileList[j].name !== '..') {
          selectedPaths.add(fileList[j].path);
        }
      }
      scrollIndexIntoView(lastSelectedIndex);
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    } else if (!e.ctrlKey && !e.metaKey) {
      const targetIdx = Math.max(minSelectableIndex, lastSelectedIndex - 1);
      lastSelectedIndex = targetIdx;
      selectionAnchorIndex = targetIdx;
      selectedPaths.clear();
      if (fileList[targetIdx] && fileList[targetIdx].name !== '..') {
        selectedPaths.add(fileList[targetIdx].path);
      }
      scrollIndexIntoView(targetIdx);
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    }
  } else if (e.key === 'Home') {
    e.preventDefault();
    e.stopPropagation();
    ensureFmFocus();
    if (!hasSelectableFiles) return;
    const targetIdx = minSelectableIndex;
    if (e.shiftKey) {
      if (selectionAnchorIndex === -1) selectionAnchorIndex = (lastSelectedIndex >= 0) ? lastSelectedIndex : targetIdx;
      lastSelectedIndex = targetIdx;
      selectedPaths.clear();
      const start = Math.min(selectionAnchorIndex, lastSelectedIndex);
      const end = Math.max(selectionAnchorIndex, lastSelectedIndex);
      for (let j = start; j <= end; j++) {
        if (fileList[j] && fileList[j].name !== '..') {
          selectedPaths.add(fileList[j].path);
        }
      }
    } else if (!e.ctrlKey && !e.metaKey) {
      lastSelectedIndex = targetIdx;
      selectionAnchorIndex = targetIdx;
      selectedPaths.clear();
      if (fileList[targetIdx] && fileList[targetIdx].name !== '..') {
        selectedPaths.add(fileList[targetIdx].path);
      }
    }
    scrollIndexIntoView(lastSelectedIndex);
    updateRowSelectionUI();
    updateFmSelectionToolbar();
  } else if (e.key === 'End') {
    e.preventDefault();
    e.stopPropagation();
    ensureFmFocus();
    if (!hasSelectableFiles) return;
    const targetIdx = fileList.length - 1;
    if (e.shiftKey) {
      if (selectionAnchorIndex === -1) selectionAnchorIndex = (lastSelectedIndex >= 0) ? lastSelectedIndex : minSelectableIndex;
      lastSelectedIndex = targetIdx;
      selectedPaths.clear();
      const start = Math.min(selectionAnchorIndex, lastSelectedIndex);
      const end = Math.max(selectionAnchorIndex, lastSelectedIndex);
      for (let j = start; j <= end; j++) {
        if (fileList[j] && fileList[j].name !== '..') {
          selectedPaths.add(fileList[j].path);
        }
      }
    } else if (!e.ctrlKey && !e.metaKey) {
      lastSelectedIndex = targetIdx;
      selectionAnchorIndex = targetIdx;
      selectedPaths.clear();
      if (fileList[targetIdx] && fileList[targetIdx].name !== '..') {
        selectedPaths.add(fileList[targetIdx].path);
      }
    }
    scrollIndexIntoView(lastSelectedIndex);
    updateRowSelectionUI();
    updateFmSelectionToolbar();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    e.stopPropagation();
    let targetItem = null;
    if (selectedPaths.size === 1) {
      const selPath = Array.from(selectedPaths)[0];
      targetItem = fileList.find(f => f.path === selPath);
    } else if (lastSelectedIndex >= 0 && fileList[lastSelectedIndex]) {
      targetItem = fileList[lastSelectedIndex];
    }
    if (targetItem && targetItem.name !== '..') {
      if (targetItem.is_dir) {
        loadPath(targetItem.path);
      } else if (targetItem.name.match(/\.(jpeg|jpg|png|gif|webp|svg)$/i)) {
        handleAction('preview', targetItem.path, targetItem.name);
      }
    }
  } else if ((e.key === 'Backspace' && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) || ((e.altKey || e.metaKey) && e.key === 'ArrowUp')) {
    e.preventDefault();
    e.stopPropagation();
    document.getElementById('fm-up-btn')?.click();
  } else if ((e.key === ' ' || e.code === 'Space') && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    let targetItem = null;
    if (selectedPaths.size === 1) {
      const selPath = Array.from(selectedPaths)[0];
      targetItem = fileList.find(f => f.path === selPath);
    } else if (lastSelectedIndex >= 0 && fileList[lastSelectedIndex]) {
      targetItem = fileList[lastSelectedIndex];
    }
    if (targetItem && !targetItem.is_dir && targetItem.name.match(/\.(jpeg|jpg|png|gif|webp|svg)$/i)) {
      e.preventDefault();
      e.stopPropagation();
      handleAction('preview', targetItem.path, targetItem.name);
    }
  }
}

export function initFileManager() {
  if (window._fmInitialized) return;
  window._fmInitialized = true;

  const fmIcon = document.getElementById("fm-desktop-icon");
  const openFm = (e) => {
    if (e && e.type === 'touchend') {
      e.preventDefault();
    }
    if (window.DockManager) {
      if (!window.DockManager.windows['fm']) {
        const fmWin = document.getElementById('file-manager-window');
        if (fmWin) {
          window.DockManager.register('fm', fmWin, '#i-storage', t('dock.file_manager', 'File Explorer'));
        }
      }
      window.DockManager.restore('fm');
    }
    ZettEventBus.emit("window:open", { id: "file-manager-window" });
  };

  if (fmIcon) {
    fmIcon.addEventListener("click", openFm);
    fmIcon.addEventListener("touchend", openFm);
    fmIcon.addEventListener("dblclick", openFm);
    fmIcon.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openFm();
      }
    });
  }

  const BOUNDS_KEY = 'zettnas_fm_bounds';
  let _isMaximized = false;
  let _preMaxBounds = null;

  // Inject the window HTML into the body if it doesn't exist
  if (!document.getElementById('file-manager-window')) {
    const html = `
      <div id="file-manager-window" class="os-window file-manager-window" tabindex="-1" style="display: none;">
        <div class="os-window-header">
          <div class="os-window-title">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
            <span data-i18n="fm.title">${t('fm.title', 'File Explorer')}</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn min-btn" id="fm-min" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="fm-max" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="fm-close" title="Close" aria-label="Close"></button>
          </div>
        </div>
        <div class="fm-toolbar">
          <button id="fm-up-btn" class="fm-tool-btn" title="${t('fm.go_up', 'Go Up')}" data-i18n-title="fm.go_up" aria-label="Go Up">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
          </button>
          <div class="fm-path-container" style="flex: 1; position: relative; display: flex; align-items: center; min-width: 0;">
            <input type="text" id="fm-path-input" class="fm-path-input" spellcheck="false" list="fm-path-list" style="width: 100%; color: transparent;" />
            <div id="fm-path-breadcrumbs" style="position: absolute; left: 0; top: 0; bottom: 0; right: 30px; display: flex; align-items: center; padding-left: 8px; cursor: text; overflow: hidden; pointer-events: auto;"></div>
            <datalist id="fm-path-list">
              <option value="/mnt/user"></option>
              <option value="/mnt/user/.RecycleBin"></option>
              <option value="/boot"></option>
              <option value="/mnt/user/appdata"></option>
              <option value="/mnt/user/system"></option>
            </datalist>
          </div>
          <button id="fm-refresh-btn" class="fm-tool-btn" title="${t('fm.refresh', 'Refresh')}" data-i18n-title="fm.refresh" aria-label="Refresh">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
          </button>
          <button id="fm-new-folder-btn" class="fm-tool-btn" title="${t('fm.new_folder', 'New Folder')}" data-i18n-title="fm.new_folder" aria-label="New Folder">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><line x1="12" y1="11" x2="12" y2="17"></line><line x1="9" y1="14" x2="15" y2="14"></line></svg>
          </button>
          <button id="fm-organize-btn" class="fm-tool-btn" title="${t('fm.organize_media', 'Organize Media')}" data-i18n-title="fm.organize_media" aria-label="Organize Media">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
          </button>
          <div id="fm-selection-bar" style="display: none; align-items: center; gap: 6px; margin-left: 8px;">
            <span id="fm-selected-count" style="font-size: 11px; font-weight: 700; color: var(--accent-cyan, #0ea5e9); padding: 2px 8px; background: rgba(14,165,233,0.12); border-radius: 4px; border: 1px solid rgba(14,165,233,0.25);">0 selected</span>
            <button id="fm-bulk-move-btn" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 11px; background: rgba(14,165,233,0.15); border: 1px solid rgba(14,165,233,0.3); color: #38bdf8; border-radius: 4px; cursor: pointer;" title="Move Selected">📦 Move To...</button>
            <button id="fm-bulk-zip-btn" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 11px; background: rgba(34,197,94,0.15); border: 1px solid rgba(34,197,94,0.3); color: #4ade80; border-radius: 4px; cursor: pointer;" title="Download Selected">⬇️ Download</button>
            <button id="fm-bulk-delete-btn" class="btn-pill-toggle" style="padding: 3px 10px; font-size: 11px; background: rgba(239,68,68,0.2); border: 1px solid rgba(239,68,68,0.4); color: #f87171; border-radius: 4px; cursor: pointer;" title="Delete Selected">🗑️ Delete</button>
            <button id="fm-clear-sel-btn" class="fm-tool-btn" style="font-size: 11px; padding: 2px 6px;" title="Clear Selection">✕</button>
          </div>
        </div>
        <div class="fm-content">
          <div class="fm-header-row">
            <div class="fm-col fm-col-check"><input type="checkbox" id="fm-select-all-checkbox" class="fm-checkbox" title="Select All" /></div>
            <div class="fm-col fm-col-name" data-i18n="fm.col_name">${t('fm.col_name', 'Name')}</div>
            <div class="fm-col fm-col-type" data-i18n="fm.col_type">Type</div>
            <div class="fm-col fm-col-size" data-i18n="fm.col_size">${t('fm.col_size', 'Size')}</div>
            <div class="fm-col fm-col-actions" data-i18n="fm.col_actions">${t('fm.col_actions', 'Actions')}</div>
          </div>
          <div id="fm-viewport" class="fm-viewport" data-scrollable="true" tabindex="0">
            <div id="fm-spacer" class="fm-spacer"></div>
            <div id="fm-list" class="fm-list"></div>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
  }

  fmWindow = document.getElementById('file-manager-window');

  // Restore saved position and dimensions
  try {
    const isMobile = document.body.classList.contains('mobile-mode') || window.innerWidth <= 768;
    if (!isMobile) {
      const saved = JSON.parse(localStorage.getItem(BOUNDS_KEY) || 'null');
      if (saved && saved.left != null && saved.top != null) {
        const maxL = Math.max(24, window.innerWidth - (saved.width || 400) - 10);
        const maxT = Math.max(56, window.innerHeight - (saved.height || 300) - 70);
        fmWindow.style.left = Math.max(24, Math.min(maxL, saved.left)) + 'px';
        fmWindow.style.top = Math.max(56, Math.min(maxT, saved.top)) + 'px';
        if (saved.width) fmWindow.style.width = Math.min(window.innerWidth - 30, Math.max(480, saved.width)) + 'px';
        if (saved.height) fmWindow.style.height = Math.min(window.innerHeight - 100, Math.max(320, saved.height)) + 'px';
      }
    }
  } catch (e) {}



  makeDraggable(fmWindow, fmWindow.querySelector('.os-window-header'), 'fm');
  const handleFmActivation = (e) => {
    bringToFront(fmWindow);
    if (!e || !e.target || !e.target.closest('input, textarea, select, button, .fm-tool-btn, .fm-act-btn')) {
      ensureFmFocus();
    }
  };
  fmWindow.addEventListener('mousedown', handleFmActivation);
  fmWindow.addEventListener('pointerdown', handleFmActivation);

  // Save bounds on resize/drag
  const saveBounds = () => {
    if (_isMaximized) return;
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    try {
      const rect = fmWindow.getBoundingClientRect();
      localStorage.setItem(BOUNDS_KEY, JSON.stringify({
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      }));
    } catch (e) {}
  };
  window.addEventListener('mouseup', saveBounds);
  window.addEventListener('resize', () => {
    renderViewport();
  });

  // Close button
  const closeFm = (e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    fmWindow.classList.add('window-minimized');
    fmWindow.style.setProperty('display', 'none', 'important');
    if (window.DockManager) window.DockManager.unregister('fm');
  };

  const closeBtn = document.getElementById('fm-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeFm);
    closeBtn.addEventListener('touchend', closeFm);
  }

  // Minimize button
  const minFm = (e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (window.DockManager) {
      if (!window.DockManager.windows['fm']) {
        window.DockManager.register('fm', fmWindow, '#i-storage', t('dock.file_manager', 'File Explorer'));
      }
      window.DockManager.minimize('fm');
    }
    fmWindow.classList.add('window-minimized');
    fmWindow.style.setProperty('display', 'none', 'important');
  };

  const minBtn = document.getElementById('fm-min');
  if (minBtn) {
    minBtn.addEventListener('click', minFm);
    minBtn.addEventListener('touchend', minFm);
  }

  // Maximize button
  const maxBtn = document.getElementById('fm-max');
  let _lastFmTouchTs = 0;
  const toggleMaxFm = (e) => {
    if (e) {
      if (e.type === 'click' && Date.now() - _lastFmTouchTs < 450) {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      if (e.type === 'touchend') {
        _lastFmTouchTs = Date.now();
      }
      e.preventDefault();
      e.stopPropagation();
    }
    if (!_isMaximized) {
      _preMaxBounds = {
        left: fmWindow.style.left,
        top: fmWindow.style.top,
        width: fmWindow.style.width,
        height: fmWindow.style.height
      };
      fmWindow.style.left = '16px';
      fmWindow.style.top = '56px';
      fmWindow.style.width = 'calc(100vw - 32px)';
      fmWindow.style.height = 'calc(100vh - 128px)';
      _isMaximized = true;
    } else {
      if (_preMaxBounds) {
        fmWindow.style.left = _preMaxBounds.left;
        fmWindow.style.top = _preMaxBounds.top;
        fmWindow.style.width = _preMaxBounds.width;
        fmWindow.style.height = _preMaxBounds.height;
      }
      _isMaximized = false;
    }
  };
  if (maxBtn) {
    maxBtn.addEventListener('click', toggleMaxFm);
    maxBtn.addEventListener('touchend', toggleMaxFm);
  }

  ZettEventBus.on('window:open', (payload) => {
    if (payload.id === 'file-manager-window') {
      if (window.DockManager) {
        if (!window.DockManager.windows['fm']) {
          window.DockManager.register('fm', fmWindow, '#i-storage', t('dock.file_manager', 'File Explorer'));
        }
        window.DockManager.restore('fm');
      }
      bringToFront(fmWindow);
      fmWindow.classList.remove('window-minimized');
      fmWindow.style.removeProperty('display');
      fmWindow.style.setProperty('display', 'flex', 'important');
      loadPath(payload.path || currentPath);
      setTimeout(ensureFmFocus, 60);
    }
  });

  document.getElementById('fm-up-btn')?.addEventListener('click', () => {
    let parent = currentPath.substring(0, currentPath.lastIndexOf('/'));
    if (!parent) {
      if (currentPath !== '/mnt' && currentPath !== '/') {
        parent = '/mnt';
      } else {
        parent = currentPath;
      }
    }
    loadPath(parent);
  });

  document.getElementById('fm-refresh-btn')?.addEventListener('click', () => loadPath(currentPath));

  const pathInputEl = document.getElementById('fm-path-input');
  if (pathInputEl && !pathInputEl.dataset.bound) {
    pathInputEl.dataset.bound = "true";
    
    const handlePathSubmit = () => {
      const val = pathInputEl.value.trim();
      if (val && val !== currentPath) {
        loadPath(val);
      }
    };
    
    pathInputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        pathInputEl.blur();
        handlePathSubmit();
      }
    });
    
    // Selecting from a datalist triggers a change event.
    pathInputEl.addEventListener('change', () => {
      handlePathSubmit();
    });

    const bcContainer = document.getElementById('fm-path-breadcrumbs');
    if (bcContainer) {
      bcContainer.onclick = () => pathInputEl.focus();
    }
    pathInputEl.addEventListener('focus', () => {
      pathInputEl.style.color = 'var(--fg)';
      if (bcContainer) bcContainer.style.display = 'none';
    });
    pathInputEl.addEventListener('blur', () => {
      pathInputEl.style.color = 'transparent';
      if (bcContainer) bcContainer.style.display = 'flex';
      // If they blurred without submitting, reset to current path so breadcrumbs match
      if (pathInputEl.value.trim() !== currentPath) {
        pathInputEl.value = currentPath;
      }
    });
  }


  document.getElementById('fm-new-folder-btn')?.addEventListener('click', () => {
    const promptMsg = t('fm.prompt_new_folder', 'Enter new folder name:');
    showPromptToast('New Folder', promptMsg, '', (name) => {
      if (name) {
        api.post('/api/mkdir', { path: currentPath + '/' + name }).then(() => {
          loadPath(currentPath);
        }).catch(err => showToast(err.message, 'error'));
      }
    });
  });

  document.getElementById('fm-organize-btn')?.addEventListener('click', () => {
    openMediaOrganizerModal(currentPath);
  });

  const viewport = document.getElementById('fm-viewport');

  if (viewport) {
    viewport.addEventListener('scroll', () => renderViewport());
    if (!viewport.dataset.clickBound) {
      viewport.dataset.clickBound = 'true';
      viewport.addEventListener('click', (e) => {
        if (e.target === viewport || e.target.id === 'fm-spacer' || e.target.id === 'fm-list') {
          selectedPaths.clear();
          lastSelectedIndex = -1;
          selectionAnchorIndex = -1;
          updateRowSelectionUI();
          updateFmSelectionToolbar();
          ensureFmFocus();
        }
      });
    }
  }

  // Drag and Drop Upload
  
  document.querySelector('.fm-header-row .fm-col-name')?.addEventListener('click', () => {
    if (currentSortBy === 'name') currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
    else { currentSortBy = 'name'; currentSortDir = 'asc'; }
    loadPath(currentPath);
  });
  
  document.querySelector('.fm-header-row .fm-col-size')?.addEventListener('click', () => {
    if (currentSortBy === 'size') currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
    else { currentSortBy = 'size'; currentSortDir = 'desc'; }
    loadPath(currentPath);
  });

  document.querySelector('.fm-header-row .fm-col-type')?.addEventListener('click', () => {
    if (currentSortBy === 'type') currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
    else { currentSortBy = 'type'; currentSortDir = 'asc'; }
    loadPath(currentPath);
  });

  const viewportElem = document.getElementById('fm-viewport');
  if (viewportElem && !viewportElem.dataset.dndBound) {
    viewportElem.dataset.dndBound = "true";
    viewportElem.addEventListener('dragover', (e) => {
      e.preventDefault();
      viewportElem.style.background = 'rgba(255,255,255,0.05)';
    });
    
    viewportElem.addEventListener('dragleave', (e) => {
      e.preventDefault();
      viewportElem.style.background = 'transparent';
    });
    
    viewportElem.addEventListener('drop', async (e) => {
      e.preventDefault();
      viewportElem.style.background = 'transparent';

      const jsonStr = e.dataTransfer.getData('application/json');
      if (jsonStr) {
        try {
          const payload = JSON.parse(jsonStr);
          if (payload.paths && payload.paths.length > 0) {
            executeTransferWithConflictCheck(payload.paths, currentPath, payload.action || 'move');
            return;
          }
        } catch (err) {}
      }

      if (!e.dataTransfer.files || e.dataTransfer.files.length === 0) return;

      const token = auth.getToken();

      let successCount = 0;
      let failCount = 0;

      for (let i = 0; i < e.dataTransfer.files.length; i++) {
        const file = e.dataTransfer.files[i];
        try {
          const res = await window.fetch(`/api/fs/upload?path=${encodeURIComponent(currentPath)}&filename=${encodeURIComponent(file.name)}`, {
            method: 'POST',
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
            body: file
          });
          if (!res.ok) throw await ApiError.from(res);
          successCount++;
        } catch (err) {
          failCount++;
          showToast(`Failed to upload ${file.name}: ${err.message}`, 'error');
        }
      }

      if (successCount > 0) {
        showToast(`Successfully uploaded ${successCount} file(s)`, 'success');
      }
      loadPath(currentPath);
    });
  }

  const bulkDeleteBtn = document.getElementById('fm-bulk-delete-btn');
  if (bulkDeleteBtn) {
    bulkDeleteBtn.addEventListener('click', () => {
      const count = selectedPaths.size;
      if (count === 0) return;
      const confirmTemplate = t('fm.confirm_bulk_delete', 'Are you sure you want to move {count} items to the Recycle Bin?');
      const confirmMsg = confirmTemplate.replace('{count}', count);
      showConfirmToast(t('common.confirm', 'Confirm Action'), confirmMsg, async () => {
        const targets = Array.from(selectedPaths);
        let success = 0;
        let failed = 0;
        for (const p of targets) {
          try {
            await api.post('/api/fs/delete', { path: p });
            success++;
          } catch (e) {
            failed++;
          }
        }
        selectedPaths.clear();
        lastSelectedIndex = -1;
        updateFmSelectionToolbar();
        loadPath(currentPath);
        if (failed > 0) {
          showToast(`Deleted ${success} items, failed to delete ${failed} items`, 'warning');
        } else {
          const successMsg = t('fm.bulk_deleted_success', `Successfully moved ${success} items to Recycle Bin.`).replace('{count}', success);
          showToast(successMsg, 'success');
        }
      });
    });
  }

  const bulkMoveBtn = document.getElementById('fm-bulk-move-btn');
  if (bulkMoveBtn) {
    bulkMoveBtn.addEventListener('click', () => {
      const count = selectedPaths.size;
      if (count === 0) return;
      _clipboard = { items: Array.from(selectedPaths), action: 'move' };
      showToast(t('fm.cut_items_toast', `Selected ${count} item(s) to move. Navigate to destination folder and click Paste.`), 'info');
    });
  }

  const bulkZipBtn = document.getElementById('fm-bulk-zip-btn');
  if (bulkZipBtn) {
    bulkZipBtn.addEventListener('click', () => {
      const paths = Array.from(selectedPaths);
      if (paths.length === 0) return;
      showToast(t('fm.downloading_items', `Downloading ${paths.length} item(s)...`), 'info');
      for (const p of paths) {
        const token = auth.getToken();
        const url = `/api/fs/download?path=${encodeURIComponent(p)}${token ? `&token=${encodeURIComponent(token)}` : ''}`;
        const a = document.createElement('a');
        a.href = url;
        a.download = p.split('/').pop() || 'download';
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
    });
  }

  const masterChk = document.getElementById('fm-select-all-checkbox');
  if (masterChk) {
    masterChk.addEventListener('change', () => {
      const selectableFiles = fileList.filter(f => f.name !== '..');
      if (masterChk.checked) {
        selectableFiles.forEach(f => selectedPaths.add(f.path));
        lastSelectedIndex = fileList.length - 1;
        selectionAnchorIndex = (fileList[0]?.name === '..') ? 1 : 0;
      } else {
        selectedPaths.clear();
        lastSelectedIndex = -1;
        selectionAnchorIndex = -1;
      }
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    });
  }

  const clearSelBtn = document.getElementById('fm-clear-sel-btn');
  if (clearSelBtn) {
    clearSelBtn.addEventListener('click', () => {
      selectedPaths.clear();
      lastSelectedIndex = -1;
      selectionAnchorIndex = -1;
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    });
  }

  // Keyboard navigation & shortcuts inside file manager
  if (fmWindow && !fmWindow.dataset.kbBound) {
    fmWindow.dataset.kbBound = 'true';
    fmWindow.addEventListener('keydown', handleFmKeydown);
  }

  if (typeof document !== 'undefined' && !document._fmDocKbBound) {
    document._fmDocKbBound = true;
    document.addEventListener('keydown', handleFmKeydown);
  }

}

async function loadPath(path) {
  try {
    const res = await api.get(`/api/browse?path=${encodeURIComponent(path)}&dirs_only=0`);
    currentPath = res.current;
    try { localStorage.setItem('zettnas_fm_last_path', currentPath); } catch (e) {}
    if (res.roots && Array.isArray(res.roots)) {
      window._fmRoots = res.roots;
      const datalist = document.getElementById('fm-path-list');
      if (datalist && datalist.dataset.populated !== res.roots.join(',')) {
        datalist.dataset.populated = res.roots.join(',');
        datalist.innerHTML = res.roots.map((r) => `<option value="${r}"></option>`).join('') +
          `<option value="${res.current}/.RecycleBin"></option>`;
      }
    }
    selectedPaths.clear();
    lastSelectedIndex = -1;
    selectionAnchorIndex = -1;
    updateFmSelectionToolbar();
    const pathInput = document.getElementById('fm-path-input');
    if (pathInput) pathInput.value = currentPath;

    // Update Headers
    const colName = document.querySelector('.fm-header-row .fm-col-name');
    const colSize = document.querySelector('.fm-header-row .fm-col-size');
    const colType = document.querySelector('.fm-header-row .fm-col-type');
    if (colName && colSize && colType) {
      const getArrow = (col) => {
        if (currentSortBy !== col) return ' <span class="fm-sort-indicator" style="opacity: 0.2;">▼</span>';
        return currentSortDir === 'asc' ? ' <span class="fm-sort-indicator" style="opacity: 0.9; color: var(--accent-cyan, #0ea5e9);">▲</span>' : ' <span class="fm-sort-indicator" style="opacity: 0.9; color: var(--accent-cyan, #0ea5e9);">▼</span>';
      };
      colName.innerHTML = t('fm.col_name', 'Name') + getArrow('name');
      colSize.innerHTML = t('fm.col_size', 'Size') + getArrow('size');
      colType.innerHTML = 'Type' + getArrow('type');
    }

    // Render breadcrumbs
    const bcContainer = document.getElementById('fm-path-breadcrumbs');
    if (bcContainer) {
      bcContainer.innerHTML = '';
      const parts = currentPath.split('/').filter(Boolean);
      let built = '/';
      
      const addSpan = (text, p, isLast) => {
        const span = document.createElement('span');
        span.textContent = text;
        span.style.padding = '2px 4px';
        span.style.borderRadius = '4px';
        span.style.cursor = isLast ? 'text' : 'pointer';
        span.style.color = isLast ? '#0ea5e9' : 'var(--fg)';
        span.style.fontWeight = isLast ? 'bold' : 'normal';
        span.style.fontFamily = 'monospace';
        
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
              targetPath = (window._fmRoots && window._fmRoots.includes('/mnt')) ? '/mnt' : (window._fmRoots ? window._fmRoots[0] : '/mnt/user');
            }
            loadPath(targetPath);
          };
        }
        bcContainer.appendChild(span);
      };
      
      if (parts.length === 0) {
        addSpan('/', '/', true);
      } else {
        addSpan('/', '/', false);
        parts.forEach((part, i) => {
          built += part + '/';
          const isLast = (i === parts.length - 1);
          addSpan(part, built, isLast);
          if (!isLast) {
            const sep = document.createElement('span');
            sep.textContent = '/';
            sep.style.color = 'var(--muted)';
            sep.style.fontFamily = 'monospace';
            sep.style.margin = '0 2px';
            bcContainer.appendChild(sep);
          }
        });
      }
    }

    fileList = (res.dirs || []).sort((a, b) => {
      if (a.name === '..') return -1;
      if (b.name === '..') return 1;
      
      let nameA = a.name.toLowerCase();
      let nameB = b.name.toLowerCase();
      let nameCompare = nameA < nameB ? -1 : (nameA > nameB ? 1 : 0);
      
      const getType = (f) => f.is_dir ? 'Folder' : (f.name.includes('.') ? f.name.split('.').pop().toUpperCase() : 'File');
      
      let valA, valB;
      if (currentSortBy === 'size') {
        valA = a.size || 0; valB = b.size || 0;
        if (valA !== valB) {
          return currentSortDir === 'asc' ? valA - valB : valB - valA;
        }
        // Tie-breaker: Name, but keep folders above files if size is the same (e.g. 0)
        if (a.is_dir && !b.is_dir) return currentSortDir === 'asc' ? -1 : 1;
        if (!a.is_dir && b.is_dir) return currentSortDir === 'asc' ? 1 : -1;
        return currentSortDir === 'asc' ? nameCompare : -nameCompare;
        
      } else if (currentSortBy === 'type') {
        valA = getType(a); valB = getType(b);
        if (valA !== valB) {
          let cmp = valA < valB ? -1 : (valA > valB ? 1 : 0);
          return currentSortDir === 'asc' ? cmp : -cmp;
        }
        // Tie-breaker: Name
        return currentSortDir === 'asc' ? nameCompare : -nameCompare;
        
      } else {
        // When sorting by Name, always keep folders on top
        if (a.is_dir && !b.is_dir) return -1;
        if (!a.is_dir && b.is_dir) return 1;
        return currentSortDir === 'asc' ? nameCompare : -nameCompare;
      }
    });

    const spacer = document.getElementById('fm-spacer');
    if (spacer) spacer.style.height = (fileList.length * ROW_HEIGHT) + 'px';
    const viewport = document.getElementById('fm-viewport');

  

    if (viewport) viewport.scrollTop = 0;
    renderViewport();
  } catch (err) {
    showToast(t('fm.err_access_denied', "Access denied or path invalid"), 'error');
  }
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024, sizes = ['B', 'KB', 'MB', 'GB', 'TB'], i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function renderViewport() {
  const viewport = document.getElementById('fm-viewport');

  

  const list = document.getElementById('fm-list');
  if (!viewport || !list) return;

  if (fileList.length === 0) {
    list.style.transform = 'none';
    list.innerHTML = `<div style="padding: 32px; text-align: center; color: var(--muted); font-size: 13px;">${escapeHtml(t('fm.empty_folder', 'This folder is empty.'))}</div>`;
    return;
  }

  const scrollTop = viewport.scrollTop;
  const viewportHeight = viewport.clientHeight;

  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER);
  const endIndex = Math.min(fileList.length, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + BUFFER);

  list.style.transform = `translateY(${startIndex * ROW_HEIGHT}px)`;
  list.innerHTML = '';

  for (let i = startIndex; i < endIndex; i++) {
    const file = fileList[i];
    const row = document.createElement('div');
    row.className = 'fm-row';
    row.dataset.path = file.path;
    if (selectedPaths.has(file.path)) row.classList.add('selected');

    const icon = file.is_dir
      ? '<svg viewBox="0 0 24 24" width="18" stroke="currentColor" fill="#eab308"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>'
      : '<svg viewBox="0 0 24 24" width="18" stroke="currentColor" fill="none"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>';

    const escName = escapeHtml(file.name);
    const escPath = escapeHtml(file.path);

    const isImage = file.name.match(/\.(jpeg|jpg|png|gif|webp|svg)$/i);
    const fileType = file.is_dir ? 'Folder' : (file.name.includes('.') ? file.name.split('.').pop().toUpperCase() : 'File');
    row.innerHTML = `
      <div class="fm-col fm-col-check">${file.name !== '..' ? `<input type="checkbox" class="fm-checkbox fm-row-checkbox" ${selectedPaths.has(file.path) ? 'checked' : ''} data-path="${escPath}" title="Select item" />` : ''}</div>
      <div class="fm-col fm-col-name">${icon} <span class="fm-name-text">${escName}</span></div>
      <div class="fm-col fm-col-type">${file.name === '..' ? '--' : fileType}</div>
      <div class="fm-col fm-col-size">${file.is_dir ? '--' : formatBytes(file.size)}</div>
      <div class="fm-col fm-col-actions">
        ${(!file.is_dir && file.name !== '..' && isImage) ? `<button class="fm-act-btn" data-act="preview" data-path="${escPath}" title="Preview">👁️</button>` : ''}
        ${!file.is_dir && file.name !== '..' ? `<button class="fm-act-btn" data-act="download" data-path="${escPath}" title="Download">⬇️</button>` : ''}
        ${file.name !== '..' ? `<button class="fm-act-btn" data-act="rename" data-path="${escPath}" title="Rename">✏️</button>` : ''}
        ${file.name !== '..' ? `<button class="fm-act-btn" data-act="delete" data-path="${escPath}" title="Delete">🗑️</button>` : ''}
      </div>
    `;

    if (file.name !== '..') {
      row.setAttribute('draggable', 'true');
      row.addEventListener('dragstart', (e) => {
        const paths = selectedPaths.has(file.path) ? Array.from(selectedPaths) : [file.path];
        e.dataTransfer.setData('application/json', JSON.stringify({ paths, action: 'move' }));
        e.dataTransfer.effectAllowed = 'move';
      });
    }

    if (file.is_dir && file.name !== '..') {
      row.addEventListener('dragover', (e) => {
        e.preventDefault();
        row.style.background = 'rgba(14, 165, 233, 0.15)';
      });
      row.addEventListener('dragleave', (e) => {
        e.preventDefault();
        row.style.background = '';
      });
      row.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        row.style.background = '';
        const jsonStr = e.dataTransfer.getData('application/json');
        if (jsonStr) {
          try {
            const payload = JSON.parse(jsonStr);
            if (payload.paths && payload.paths.length > 0) {
              executeTransferWithConflictCheck(payload.paths, file.path, payload.action || 'move');
            }
          } catch (err) {}
        }
      });
    }


    row.addEventListener('click', (e) => {
      if (e.target.closest('.fm-act-btn') || file.name === '..') return;
      ensureFmFocus();
      if (e.target.closest('.fm-checkbox')) {
        const chk = e.target.closest('.fm-checkbox');
        if (chk.checked) {
          selectedPaths.add(file.path);
        } else {
          selectedPaths.delete(file.path);
        }
        lastSelectedIndex = i;
        if (selectionAnchorIndex === -1) selectionAnchorIndex = i;
        updateRowSelectionUI();
        updateFmSelectionToolbar();
        return;
      }
      const idx = i;
      if (e.shiftKey) {
        if (selectionAnchorIndex === -1) {
          selectionAnchorIndex = (lastSelectedIndex !== -1) ? lastSelectedIndex : idx;
        }
        const start = Math.min(selectionAnchorIndex, idx);
        const end = Math.max(selectionAnchorIndex, idx);
        if (!e.ctrlKey && !e.metaKey) {
          selectedPaths.clear();
        }
        for (let j = start; j <= end; j++) {
          if (fileList[j] && fileList[j].name !== '..') {
            selectedPaths.add(fileList[j].path);
          }
        }
        lastSelectedIndex = idx;
      } else if (e.ctrlKey || e.metaKey) {
        if (selectedPaths.has(file.path)) {
          selectedPaths.delete(file.path);
        } else {
          selectedPaths.add(file.path);
        }
        lastSelectedIndex = idx;
        selectionAnchorIndex = idx;
      } else {
        selectedPaths.clear();
        selectedPaths.add(file.path);
        lastSelectedIndex = idx;
        selectionAnchorIndex = idx;
      }
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    });

    if (file.is_dir) {
      row.addEventListener('dblclick', () => loadPath(file.path));
    } else if (isImage) {
      row.addEventListener('dblclick', () => handleAction('preview', file.path, file.name));
    }

    row.querySelectorAll('.fm-act-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        handleAction(btn.dataset.act, btn.dataset.path, file.name);
      });
    });

    list.appendChild(row);
  }
}

async function handleAction(act, path, oldName) {

  if (act === 'preview') {
    const token = localStorage.getItem('zettnas_token');
    const url = `/api/fs/download?path=${encodeURIComponent(path)}&token=${token}`;
    // Show image in a simple centered modal
    let previewModal = document.getElementById('fm-image-preview');
    if (!previewModal) {
      previewModal = document.createElement('div');
      previewModal.id = 'fm-image-preview';
      previewModal.style.cssText = 'position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 10000; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(5px); cursor: zoom-out;';
      previewModal.innerHTML = `<img style="max-width: 90%; max-height: 90%; object-fit: contain; border-radius: 8px; box-shadow: 0 10px 40px rgba(0,0,0,0.5);" />`;
      previewModal.addEventListener('click', () => { previewModal.style.display = 'none'; });
      document.body.appendChild(previewModal);
    }
    previewModal.querySelector('img').src = url;
    previewModal.style.display = 'flex';
  } else if (act === 'download') {
    const token = localStorage.getItem('zettnas_token');
    window.open(`/api/fs/download?path=${encodeURIComponent(path)}&token=${token}`, '_blank');
  } else if (act === 'delete') {
    const confirmTemplate = t('fm.confirm_delete', 'Are you sure you want to move {name} to the Recycle Bin? (If it is already in the Recycle Bin, it will be permanently deleted)');
    const confirmMsg = confirmTemplate.replace('{name}', oldName);
    showConfirmToast(t('common.confirm', 'Confirm Action'), confirmMsg, async () => {
      try {
        await api.post('/api/fs/delete', { path });
        loadPath(currentPath);
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  } else if (act === 'rename') {
    const promptMsg = t('fm.prompt_rename', 'Enter new name:');
    showPromptToast('Rename', promptMsg, oldName, async (newName) => {
      if (newName && newName !== oldName) {
        try {
          await api.post('/api/fs/rename', { path, new_name: newName });
          loadPath(currentPath);
        } catch (err) {
          showToast(err.message, 'error');
        }
      }
    });
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

  try {
    const checkRes = await api.post('/api/fs/conflict-check', {
      sources: validSources,
      destination_dir: destinationDir,
    });

    if (!checkRes.has_conflict) {
      const res = await api.post('/api/fs/transfer', {
        sources: validSources,
        destination_dir: destinationDir,
        action,
        collision_policy: 'merge',
      });
      const count = res.transferred != null ? res.transferred : validSources.length;
      showToast(t('fm.transfer_success', `Successfully transferred ${count} item(s)`).replace('{count}', count), 'success');
      loadPath(currentPath);
      return;
    }

    showCollisionModal({
      sources: validSources,
      destinationDir,
      action,
      conflicts: checkRes.conflicts,
      onResolved: () => {
        loadPath(currentPath);
      },
    });
  } catch (err) {
    showToast(`Transfer failed: ${err.message}`, 'error');
  }
}

export function showCollisionModal({ sources, destinationDir, action, conflicts, onResolved }) {
  let modal = document.getElementById('modal-fm-collision');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-fm-collision';
    modal.className = 'modal-backdrop';
    document.body.appendChild(modal);
  }

  const hasDir = conflicts && conflicts.some((c) => c.is_dir);

  modal.innerHTML = `
    <div class="modal-card glassmorphic-card" style="max-width: 520px; width: 90%; max-height: 85vh; display: flex; flex-direction: column; padding: 24px; border-radius: 14px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
        <h3 style="margin: 0; font-size: 16px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px;">
          <span>⚠️</span> <span>${escapeHtml(t('fm.collision_title', 'File & Directory Conflict'))}</span>
        </h3>
        <button id="fm-collision-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 18px;">✕</button>
      </div>
      <p style="font-size: 12px; color: var(--muted); margin: 0 0 12px 0;">
        ${escapeHtml(t('fm.collision_desc', 'The following files or directories already exist at the destination:'))}
      </p>
      <div style="background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 10px; max-height: 180px; overflow-y: auto; margin-bottom: 16px;">
        ${(conflicts || [])
          .map(
            (c) => `
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 12px;">
            <div style="display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              <span>${c.is_dir ? '📁' : '📄'}</span>
              <span style="font-weight: 600; color: #fff;">${escapeHtml(c.name)}</span>
            </div>
            <span style="font-size: 10px; color: var(--muted);">${c.is_dir ? 'Directory' : formatBytes(c.dest_size || 0)}</span>
          </div>
        `
          )
          .join('')}
      </div>
      <div style="margin-bottom: 18px;">
        <label style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); cursor: pointer;">
          <input type="checkbox" id="fm-collision-apply-all" checked style="accent-color: var(--accent-cyan, #0ea5e9);" />
          <span>${escapeHtml(t('fm.apply_all', 'Apply to all conflicts'))}</span>
        </label>
      </div>
      <div style="display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap;">
        <button id="fm-collision-cancel" class="btn-secondary" style="padding: 7px 14px; font-size: 12px; border-radius: 6px; cursor: pointer;">Cancel</button>
        <button id="fm-collision-skip" class="btn-secondary" style="padding: 7px 14px; font-size: 12px; border-radius: 6px; cursor: pointer;">${escapeHtml(t('fm.skip', 'Skip'))}</button>
        ${
          !hasDir
            ? `
          <button id="fm-collision-keep-both" class="btn-secondary" style="padding: 7px 14px; font-size: 12px; border-radius: 6px; cursor: pointer;">${escapeHtml(t('fm.keep_both', 'Keep Both'))}</button>
        `
            : ''
        }
        <button id="fm-collision-overwrite" class="btn-pill-toggle" style="padding: 7px 14px; font-size: 12px; border-radius: 6px; cursor: pointer; background: rgba(239,68,68,0.2); border: 1px solid rgba(239,68,68,0.4); color: #f87171;">${escapeHtml(t('fm.overwrite', 'Overwrite'))}</button>
        ${
          hasDir
            ? `
          <button id="fm-collision-merge" class="btn-primary" style="padding: 7px 16px; font-size: 12px; font-weight: 700; border-radius: 6px; cursor: pointer; background: var(--accent-cyan, #0ea5e9); color: #fff; border: none;">${escapeHtml(t('fm.merge', 'Merge'))}</button>
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
    try {
      const res = await api.post('/api/fs/transfer', {
        sources,
        destination_dir: destinationDir,
        action,
        collision_policy: policy,
      });
      const count = res.transferred != null ? res.transferred : sources.length;
      showToast(t('fm.transfer_success', `Successfully transferred ${count} item(s)`).replace('{count}', count), 'success');
      if (typeof onResolved === 'function') onResolved();
    } catch (err) {
      showToast(`Transfer failed: ${err.message}`, 'error');
    }
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

export function openFileManager(path = null) {
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
  } else if (currentPath && currentPath.startsWith('/mnt/storage')) {
    target = '/mnt/storage/.RecycleBin';
  }
  ZettEventBus.emit('window:open', { id: 'file-manager-window', path: target });
};

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
        showToast('Please specify both source and destination folders.', 'warning');
        return;
      }

      btnPreview.disabled = true;
      btnPreview.innerHTML = '<span>⏳</span> <span>Analyzing...</span>';
      if (previewWrap) {
        previewWrap.innerHTML = '<div style="text-align:center; padding:25px; color:var(--muted); font-size:12px;"><div class="loader-spinner" style="margin:0 auto 10px;"></div>Parsing media files via regex heuristics...</div>';
      }

      try {
        const res = await api.post('/api/media/organize/preview', { source_dir, target_dir });
        const items = res.items || [];
        previewItems = items;

        if (items.length === 0) {
          if (previewWrap) {
            previewWrap.innerHTML = '<div style="text-align:center; padding:25px; color:var(--muted); font-size:12px;">No video files found in source folder.</div>';
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
            <div style="font-size:11px; padding:8px 12px; background:rgba(255,255,255,0.03); border-bottom:1px solid rgba(255,255,255,0.08); font-weight:700; color:var(--muted); display:flex; justify-content:space-between;">
              <span>Detected ${items.length} file(s) for reorganization:</span>
              <span>Plex / Jellyfin Schema</span>
            </div>
            <div style="display:flex; flex-direction:column;">
              ${items.map((it) => {
                const isTv = it.media_type === 'tv';
                const typeBadge = isTv
                  ? `<span class="ci-badge" style="font-size:9px; background:rgba(168,85,247,0.15); color:#c084fc; border:1px solid rgba(168,85,247,0.3); padding:1px 5px; border-radius:3px;">TV Show · S${String(it.season || 1).padStart(2, '0')}E${String(it.episode || 1).padStart(2, '0')}</span>`
                  : `<span class="ci-badge" style="font-size:9px; background:rgba(14,165,233,0.15); color:#38bdf8; border:1px solid rgba(14,165,233,0.3); padding:1px 5px; border-radius:3px;">Movie ${it.year ? `(${it.year})` : ''}</span>`;
                const qualBadge = `<span class="ci-badge" style="font-size:9px; background:rgba(255,255,255,0.06); color:#cbd5e1; padding:1px 5px; border-radius:3px;">${escapeHtml(it.resolution || '1080p')} · ${escapeHtml(it.codec || 'x264')}</span>`;

                return `
                  <div style="padding:8px 12px; border-bottom:1px solid rgba(255,255,255,0.04); display:flex; flex-direction:column; gap:4px; font-size:11px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                      <div style="font-weight:700; color:#fff; word-break:break-all;">${escapeHtml(it.title || it.original_filename)}</div>
                      <div style="display:flex; gap:6px;">${typeBadge}${qualBadge}</div>
                    </div>
                    <div style="color:var(--muted); font-size:10px; font-family:monospace; display:flex; align-items:center; gap:6px;">
                      <span style="color:#f87171; text-decoration:line-through;">${escapeHtml(it.original_filename)}</span>
                      <span>➔</span>
                      <span style="color:#4ade80;">${escapeHtml(it.proposed_relative_path)}</span>
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          `;
        }

        if (btnApply) {
          btnApply.disabled = false;
          btnApply.style.opacity = '1';
          btnApply.style.cursor = 'pointer';
        }
      } catch (err) {
        showToast(`Preview failed: ${err.message}`, 'error');
        if (previewWrap) {
          previewWrap.innerHTML = `<div style="text-align:center; padding:25px; color:var(--alert, #ef4444); font-size:12px;">Failed: ${escapeHtml(err.message)}</div>`;
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
      btnApply.innerHTML = '<span>⏳</span> <span>Organizing...</span>';

      try {
        const res = await api.post('/api/media/organize/apply', {
          items: previewItems,
          action,
          hardlink,
        });

        const procCount = res.processed != null ? res.processed : previewItems.length;
        showToast(t('media.success', `Media organization completed successfully (${procCount} files).`), 'success');
        closeModal();
        if (typeof loadPath === 'function') {
          loadPath(srcInput?.value || initialPath);
        }
      } catch (err) {
        showToast(`Failed to execute reorganization: ${err.message}`, 'error');
      } finally {
        btnApply.disabled = false;
        btnApply.innerHTML = t('media.apply_btn', 'Execute Reorganization');
      }
    };
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
}

