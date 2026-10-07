import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast } from '../toast.js';
import { t } from '../i18n.js';
import { makeDraggable, bringToFront } from './dock.js';

let fmWindow = null;
let currentPath = localStorage.getItem('zettnas_fm_last_path') || '/mnt/user';
let fileList = [];

let currentSortBy = 'name';
let currentSortDir = 'asc';
let selectedPaths = new Set();
let lastSelectedIndex = -1;

function updateFmSelectionToolbar() {
  const bar = document.getElementById('fm-selection-bar');
  const countSpan = document.getElementById('fm-selected-count');
  const bulkDelBtn = document.getElementById('fm-bulk-delete-btn');
  if (!bar || !countSpan) return;
  const count = selectedPaths.size;
  if (count > 0) {
    bar.style.display = 'inline-flex';
    countSpan.textContent = t('fm.selected_count', `${count} selected`).replace('{count}', count);
    if (bulkDelBtn) bulkDelBtn.textContent = `🗑️ ${t('fm.bulk_delete', `Delete (${count})`).replace('{count}', count)}`;
  } else {
    bar.style.display = 'none';
  }
}

function updateRowSelectionUI() {
  const rows = document.querySelectorAll('.fm-row');
  rows.forEach(r => {
    const p = r.dataset.path;
    if (p && selectedPaths.has(p)) {
      r.classList.add('selected');
    } else {
      r.classList.remove('selected');
    }
  });
}

// Virtualized DOM logic
const ROW_HEIGHT = 42;
const BUFFER = 5;

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
      <div id="file-manager-window" class="os-window file-manager-window" style="display: none; top: 100px; left: 150px; width: 800px; height: 600px;">
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
          <div id="fm-selection-bar" style="display: none; align-items: center; gap: 6px; margin-left: 8px;">
            <span id="fm-selected-count" style="font-size: 11px; font-weight: 700; color: var(--accent-cyan, #0ea5e9); padding: 2px 8px; background: rgba(14,165,233,0.12); border-radius: 4px; border: 1px solid rgba(14,165,233,0.25);">0 selected</span>
            <button id="fm-bulk-delete-btn" class="btn-pill-toggle" style="padding: 3px 10px; font-size: 11px; background: rgba(239,68,68,0.2); border: 1px solid rgba(239,68,68,0.4); color: #f87171; border-radius: 4px; cursor: pointer;" title="Delete Selected">🗑️ Delete</button>
            <button id="fm-clear-sel-btn" class="fm-tool-btn" style="font-size: 11px; padding: 2px 6px;" title="Clear Selection">✕</button>
          </div>
        </div>
        <div class="fm-content">
          <div class="fm-header-row">
            <div class="fm-col fm-col-name" data-i18n="fm.col_name">${t('fm.col_name', 'Name')}</div>
            <div class="fm-col fm-col-type" data-i18n="fm.col_type">Type</div>
            <div class="fm-col fm-col-size" data-i18n="fm.col_size">${t('fm.col_size', 'Size')}</div>
            <div class="fm-col fm-col-actions" data-i18n="fm.col_actions">${t('fm.col_actions', 'Actions')}</div>
          </div>
          <div id="fm-viewport" class="fm-viewport" data-scrollable="true">
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
    const saved = JSON.parse(localStorage.getItem(BOUNDS_KEY) || 'null');
    if (saved && saved.left != null && saved.top != null) {
      const maxL = Math.max(24, window.innerWidth - (saved.width || 400) - 10);
      const maxT = Math.max(56, window.innerHeight - (saved.height || 300) - 70);
      fmWindow.style.left = Math.max(24, Math.min(maxL, saved.left)) + 'px';
      fmWindow.style.top = Math.max(56, Math.min(maxT, saved.top)) + 'px';
      if (saved.width) fmWindow.style.width = Math.min(window.innerWidth - 30, Math.max(480, saved.width)) + 'px';
      if (saved.height) fmWindow.style.height = Math.min(window.innerHeight - 100, Math.max(320, saved.height)) + 'px';
    }
  } catch (e) {}



  makeDraggable(fmWindow, fmWindow.querySelector('.os-window-header'), 'fm');
  fmWindow.addEventListener('mousedown', () => bringToFront(fmWindow));

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
  const toggleMaxFm = (e) => {
    if (e) {
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
    }
  });

  document.getElementById('fm-up-btn')?.addEventListener('click', () => {
    const parent = currentPath.substring(0, currentPath.lastIndexOf('/')) || '/mnt/user';
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
    import('../toast.js').then(m => {
      if (m.showPromptToast) {
        m.showPromptToast('New Folder', promptMsg, '', (name) => {
          if (name) {
            api.post('/api/mkdir', { path: currentPath + '/' + name }).then(() => {
              loadPath(currentPath);
            }).catch(err => m.showToast(err.message, 'error'));
          }
        });
      } else {
        const name = prompt(promptMsg);
        if (name) {
          api.post('/api/mkdir', { path: currentPath + '/' + name }).then(() => {
            loadPath(currentPath);
          }).catch(err => m.showToast(err.message, 'error'));
        }
      }
    });
  });

  const viewport = document.getElementById('fm-viewport');

  

  if (viewport) viewport.addEventListener('scroll', () => renderViewport());

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
      
      if (!e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
      
      const { auth, ApiError } = await import('../api.js');
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
          import('../toast.js').then(m => m.showToast(`Failed to upload ${file.name}: ${err.message}`, 'error'));
        }
      }
      
      if (successCount > 0) {
        import('../toast.js').then(m => m.showToast(`Successfully uploaded ${successCount} file(s)`, 'success'));
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

  const clearSelBtn = document.getElementById('fm-clear-sel-btn');
  if (clearSelBtn) {
    clearSelBtn.addEventListener('click', () => {
      selectedPaths.clear();
      lastSelectedIndex = -1;
      updateRowSelectionUI();
      updateFmSelectionToolbar();
    });
  }

  // Keyboard navigation & shortcuts inside file manager
  if (fmWindow && !fmWindow.dataset.kbBound) {
    fmWindow.dataset.kbBound = 'true';
    fmWindow.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'Escape') {
        if (selectedPaths.size > 0) {
          e.preventDefault();
          selectedPaths.clear();
          lastSelectedIndex = -1;
          updateRowSelectionUI();
          updateFmSelectionToolbar();
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
        e.preventDefault();
        selectedPaths.clear();
        fileList.forEach((f) => {
          if (f.name !== '..') {
            selectedPaths.add(f.path);
          }
        });
        lastSelectedIndex = fileList.length - 1;
        updateRowSelectionUI();
        updateFmSelectionToolbar();
      } else if (e.key === 'Delete' || (e.metaKey && e.key === 'Backspace')) {
        if (selectedPaths.size > 0) {
          e.preventDefault();
          bulkDeleteBtn?.click();
        }
      }
    });
  }

}

async function loadPath(path) {
  try {
    const res = await api.get(`/api/browse?path=${encodeURIComponent(path)}&dirs_only=0`);
    currentPath = res.current;
    try { localStorage.setItem('zettnas_fm_last_path', currentPath); } catch (e) {}
    selectedPaths.clear();
    lastSelectedIndex = -1;
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
            loadPath(p);
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


    row.addEventListener('click', (e) => {
      if (e.target.closest('.fm-act-btn') || file.name === '..') return;
      const idx = i;
      if (e.shiftKey && lastSelectedIndex !== -1) {
        const start = Math.min(lastSelectedIndex, idx);
        const end = Math.max(lastSelectedIndex, idx);
        if (!e.ctrlKey && !e.metaKey) {
          selectedPaths.clear();
        }
        for (let j = start; j <= end; j++) {
          if (fileList[j] && fileList[j].name !== '..') {
            selectedPaths.add(fileList[j].path);
          }
        }
      } else if (e.ctrlKey || e.metaKey) {
        if (selectedPaths.has(file.path)) {
          selectedPaths.delete(file.path);
        } else {
          selectedPaths.add(file.path);
        }
        lastSelectedIndex = idx;
      } else {
        selectedPaths.clear();
        selectedPaths.add(file.path);
        lastSelectedIndex = idx;
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
    import('../toast.js').then(m => {
      if (m.showPromptToast) {
        m.showPromptToast('Rename', promptMsg, oldName, async (newName) => {
          if (newName && newName !== oldName) {
            try {
              await api.post('/api/fs/rename', { path, new_name: newName });
              loadPath(currentPath);
            } catch (err) {
              m.showToast(err.message, 'error');
            }
          }
        });
      }
    });
  }
}


window.openRecycleBin = () => {
  import('../event-bus.js').then(m => {
    m.ZettEventBus.emit('window:open', {id:'file-manager-window', path: '/mnt/user/.RecycleBin'});
  });
};
