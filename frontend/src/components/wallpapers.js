import { state } from '../state.js';
/**
 * ZettNAS Toolkit Visual Wallpaper Gallery Engine
 * Provides responsive thumbnail grid, 1-click live preview, drag-and-drop upload,
 * and seamless background switching.
 */
import { api } from '../api.js';
import { showToast, showPromptToast, showConfirmToast } from '../toast.js';
import { escapeHtml } from '../utils.js';

let _wallpapersInitialized = false;
let _loadPromise = null;
let _currentFiles = [];
let _activeWallpaper = null;

export function setWallpaper(url, filename = null) {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;

  if (url) {
    if (filename) {
      try {
        localStorage.setItem('zettnas_active_wallpaper', filename);
      } catch (e) {}
    }
    document.body.style.setProperty('background-image', `url('${url}')`, 'important');
    document.body.style.setProperty('background-size', 'cover', 'important');
    document.body.style.setProperty('background-position', 'center center', 'important');
    document.body.style.setProperty('background-repeat', 'no-repeat', 'important');
    document.body.style.setProperty('background-attachment', 'fixed', 'important');
  } else {
    try {
      localStorage.removeItem('zettnas_active_wallpaper');
    } catch (e) {}
    document.body.style.removeProperty('background-image');
    document.body.style.removeProperty('background-size');
    document.body.style.removeProperty('background-position');
    document.body.style.removeProperty('background-repeat');
    document.body.style.removeProperty('background-attachment');
  }

  // Update active state in visual gallery grid if rendered
  _updateGalleryActiveState(filename);

  const earlyWp = document.getElementById('zettnas-wallpaper-early-style');
  if (earlyWp && earlyWp.parentNode) {
    earlyWp.parentNode.removeChild(earlyWp);
  }
}

function _updateGalleryActiveState(activeName) {
  _activeWallpaper = activeName;
  const cards = document.querySelectorAll('.wallpaper-card');
  cards.forEach((card) => {
    const cardFile = card.getAttribute('data-filename');
    const isThisActive = (activeName && cardFile === activeName) || (!activeName && !cardFile);
    if (isThisActive) {
      card.classList.add('active');
      const badge = card.querySelector('.wallpaper-card-active-indicator');
      if (badge) badge.style.display = 'flex';
    } else {
      card.classList.remove('active');
      const badge = card.querySelector('.wallpaper-card-active-indicator');
      if (badge) badge.style.display = 'none';
    }
  });
}

export async function selectWallpaper(filename) {
  const selectDropdown = document.getElementById('wallpaper-select');
  if (selectDropdown) {
    selectDropdown.value = filename || '';
  }

  if (filename) {
    setWallpaper(`/api/wallpapers/download/${encodeURIComponent(filename)}`, filename);
    try {
      await api.post('/api/wallpapers/select', { filename });
      showToast(`Active wallpaper: ${filename}`, 'success');
    } catch (err) {
      showToast('Failed to save wallpaper setting', 'error');
    }
  } else {
    setWallpaper(null);
    try {
      await api.post('/api/wallpapers/select', { filename: null });
      showToast('Theme gradient restored', 'info');
    } catch (err) {
      showToast('Failed to save wallpaper setting', 'error');
    }
  }
}

export async function renameWallpaper(oldName) {
  if (!oldName) return;
  showPromptToast(
    'Rename Wallpaper',
    `Enter a new name for <strong>${escapeHtml(oldName)}</strong>:`,
    oldName,
    async (newName) => {
      newName = (newName || '').trim();
      if (!newName || newName === oldName) return;

      try {
        const data = await api.post('/api/wallpapers/rename', {
          old_name: oldName,
          new_name: newName
        });
        if (data.success) {
          showToast(`Wallpaper renamed to ${data.new_name}`, 'success');
          if (localStorage.getItem('zettnas_active_wallpaper') === oldName) {
            try {
              localStorage.setItem('zettnas_active_wallpaper', data.new_name);
            } catch (e) {}
          }
          await loadWallpapers();
        } else {
          showToast('Rename failed: ' + (data.error || 'Unknown error'), 'error');
        }
      } catch (err) {
        showToast('Rename request failed: ' + err.message, 'error');
      }
    },
    null,
    { okText: 'Rename', cancelText: 'Cancel' }
  );
}

export async function deleteWallpaper(filename) {
  if (!filename) return;
  showConfirmToast(
    'Delete Wallpaper',
    `Are you sure you want to delete wallpaper <strong>${escapeHtml(filename)}</strong>? This action cannot be undone.`,
    async () => {
      try {
        await api.delete(`/api/wallpapers/${encodeURIComponent(filename)}`);
        if (localStorage.getItem('zettnas_active_wallpaper') === filename) {
          try {
            localStorage.removeItem('zettnas_active_wallpaper');
          } catch (e) {}
        }
        showToast('Wallpaper deleted', 'success');
        await loadWallpapers();
      } catch (err) {
        showToast('Delete failed: ' + err.message, 'error');
      }
    },
    null,
    { okText: '🗑️ Delete', cancelText: 'Cancel' }
  );
}

export function renderWallpaperGallery(files, active, version) {
  const galleryEl = document.getElementById('wallpaper-gallery-grid');
  const countBadge = document.getElementById('wallpaper-count-badge');

  if (countBadge) {
    countBadge.textContent = `${files.length} Background${files.length === 1 ? '' : 's'}`;
  }

  if (!galleryEl) return;
  galleryEl.innerHTML = '';

  const v = version ? `?v=${version}` : '';

  // 1. Default Theme Gradient Card
  const isDefaultActive = !active;
  const defaultCard = document.createElement('div');
  defaultCard.className = `wallpaper-card ${isDefaultActive ? 'active' : ''}`;
  defaultCard.setAttribute('data-filename', '');
  defaultCard.setAttribute('role', 'button');
  defaultCard.setAttribute('tabindex', '0');
  defaultCard.setAttribute('title', 'Click to use default theme gradient');
  defaultCard.innerHTML = `
    <div class="wallpaper-card-thumb-wrap default-gradient-thumb">
      <div class="wallpaper-gradient-preview"></div>
      <div class="wallpaper-card-active-indicator" style="${isDefaultActive ? 'display:flex;' : 'display:none;'}">
        <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
        <span>ACTIVE</span>
      </div>
    </div>
    <div class="wallpaper-card-footer">
      <span class="wallpaper-card-title">Theme Gradient</span>
    </div>
  `;
  defaultCard.addEventListener('click', () => selectWallpaper(''));
  defaultCard.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      selectWallpaper('');
    }
  });
  galleryEl.appendChild(defaultCard);

  // 2. Wallpaper Cards for Each File
  files.forEach((f) => {
    const isActive = active === f;
    const card = document.createElement('div');
    card.className = `wallpaper-card ${isActive ? 'active' : ''}`;
    card.setAttribute('data-filename', f);
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('title', `Click to set "${f}" as wallpaper`);

    const thumbUrl = `/api/wallpapers/thumb/${encodeURIComponent(f)}${v}`;
    const fullUrl = `/api/wallpapers/download/${encodeURIComponent(f)}${v}`;

    card.innerHTML = `
      <div class="wallpaper-card-thumb-wrap">
        <img class="wallpaper-card-thumb" src="${thumbUrl}" alt="${f}" loading="lazy" onerror="this.onerror=null; this.src='${fullUrl}';">
        <div class="wallpaper-card-active-indicator" style="${isActive ? 'display:flex;' : 'display:none;'}">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
          <span>ACTIVE</span>
        </div>
        <div class="wallpaper-card-actions">
          <button class="wallpaper-action-btn rename-btn" title="Rename image" aria-label="Rename image">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
          </button>
          <button class="wallpaper-action-btn delete-btn" title="Delete image" aria-label="Delete image">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
          </button>
        </div>
      </div>
      <div class="wallpaper-card-footer">
        <span class="wallpaper-card-title" title="${f}">${f}</span>
      </div>
    `;

    card.addEventListener('click', (e) => {
      if (e.target.closest('.wallpaper-action-btn')) return;
      selectWallpaper(f);
    });

    card.addEventListener('keydown', (e) => {
      if (e.target.closest('.wallpaper-action-btn')) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        selectWallpaper(f);
      }
    });

    const renameBtn = card.querySelector('.rename-btn');
    if (renameBtn) {
      renameBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        renameWallpaper(f);
      });
    }

    const delBtn = card.querySelector('.delete-btn');
    if (delBtn) {
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteWallpaper(f);
      });
    }

    galleryEl.appendChild(card);
  });
}

export function loadWallpapers() {
  if (_loadPromise) return _loadPromise;
  _loadPromise = (async () => {
    try {
      const data = await api.get('/api/wallpapers');
      _currentFiles = data.files || [];
      _activeWallpaper = data.active || null;
      const selectDropdown = document.getElementById('wallpaper-select');

      // Populate legacy/test select dropdown
      if (selectDropdown) {
        selectDropdown.innerHTML = '<option value="">Default Gradient</option>';
        _currentFiles.forEach((f) => {
          const opt = document.createElement('option');
          opt.value = f;
          opt.textContent = f;
          selectDropdown.appendChild(opt);
        });
        selectDropdown.value = data.active || '';
      }

      // Render modern visual gallery
      renderWallpaperGallery(_currentFiles, data.active, data.version);

      if (data.active) {
        const v = data.version ? `?v=${data.version}` : '';
        setWallpaper(`/api/wallpapers/download/${encodeURIComponent(data.active)}${v}`, data.active);
      } else {
        setWallpaper(null);
      }
    } catch (err) {
      console.warn('Could not load wallpapers', err);
    }
  })().finally(() => {
    _loadPromise = null;
  });
  return _loadPromise;
}

if (typeof window !== 'undefined') {
  window.loadWallpapers = loadWallpapers;
  window.setWallpaper = setWallpaper;
  window.selectWallpaper = selectWallpaper;
}

export async function uploadAndApplyWallpaper(file) {
  if (!file) return;
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async (ev) => {
      const base64data = ev.target.result;
      try {
        const data = await api.post('/api/wallpapers/upload', {
          image: base64data,
          filename: file.name
        });
        if (data && data.success) {
          if (data.filename) {
            try {
              localStorage.setItem('zettnas_active_wallpaper', data.filename);
            } catch (e) {}
          }
          await loadWallpapers();
          if (data.filename) {
            await selectWallpaper(data.filename);
          }
          showToast(`Wallpaper uploaded & applied: ${data.filename || file.name}`, 'success');
          resolve(data);
        } else {
          showToast('Failed: ' + ((data && data.error) || 'Upload error'), 'error');
          reject(new Error((data && data.error) || 'Upload error'));
        }
      } catch (err) {
        showToast('Upload failed: ' + err.message, 'error');
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error('Failed reading image file'));
    reader.readAsDataURL(file);
  });
}

export function initWallpapers() {
  const fileInput = document.getElementById('wallpaper-upload');
  const clearBtn = document.getElementById('wallpaper-clear-btn');
  const defaultBtn = document.getElementById('wallpaper-default-btn');
  const selectDropdown = document.getElementById('wallpaper-select');
  const deleteBtn = document.getElementById('wallpaper-delete-btn');
  const renameBtn = document.getElementById('wallpaper-rename-btn');
  const galleryEl = document.getElementById('wallpaper-gallery-grid');

  loadWallpapers();
  initWallpaperReadabilityControls();
  initGlassControls();

  if (_wallpapersInitialized) return;
  _wallpapersInitialized = true;

  if (defaultBtn) {
    defaultBtn.addEventListener('click', () => selectWallpaper(''));
  }

  if (selectDropdown) {
    selectDropdown.addEventListener('change', (e) => {
      const val = e.target.value;
      if (val) {
        setWallpaper(`/api/wallpapers/download/${encodeURIComponent(val)}`, val);
      } else {
        setWallpaper(null);
      }
    });
  }

  // File upload handler
  const handleUploadFile = (file) => {
    uploadAndApplyWallpaper(file);
  };

  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      handleUploadFile(file);
      fileInput.value = '';
    });
  }

  // Drag-and-drop on gallery grid
  if (galleryEl) {
    galleryEl.addEventListener('dragover', (e) => {
      e.preventDefault();
      galleryEl.classList.add('dragover');
    });
    galleryEl.addEventListener('dragleave', (e) => {
      if (!galleryEl.contains(e.relatedTarget)) {
        galleryEl.classList.remove('dragover');
      }
    });
    galleryEl.addEventListener('drop', (e) => {
      e.preventDefault();
      galleryEl.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleUploadFile(e.dataTransfer.files[0]);
      }
    });
  }

  // Legacy compatibility buttons
  if (clearBtn) {
    clearBtn.addEventListener('click', async () => {
      const val = selectDropdown ? selectDropdown.value : '';
      selectWallpaper(val || null);
    });
  }

  if (renameBtn) {
    renameBtn.addEventListener('click', async () => {
      const val = selectDropdown ? selectDropdown.value : '';
      renameWallpaper(val);
    });
  }

  if (deleteBtn) {
    deleteBtn.addEventListener('click', async () => {
      const val = selectDropdown ? selectDropdown.value : '';
      deleteWallpaper(val);
    });
  }
}

/**
 * Wallpaper Readability & Contrast Engine (Dimming & Blur)
 */
export function applyWallpaperReadability(dimPercent, blurPx, persist = true) {
  dimPercent = Math.max(0, Math.min(70, parseInt(dimPercent, 10) || 0));
  blurPx = Math.max(0, Math.min(30, parseInt(blurPx, 10) || 0));

  if (typeof document !== 'undefined') {
    if (document.documentElement) {
      document.documentElement.style.setProperty('--wallpaper-dim', (dimPercent / 100).toFixed(2));
      document.documentElement.style.setProperty('--wallpaper-blur', `${blurPx}px`);
    }
    const dimVal = document.getElementById('wallpaper-dim-val');
    const dimSlider = document.getElementById('wallpaper-dim-slider');
    const blurVal = document.getElementById('wallpaper-blur-val');
    const blurSlider = document.getElementById('wallpaper-blur-slider');

    if (dimVal) dimVal.textContent = `${dimPercent}%`;
    if (dimSlider && parseInt(dimSlider.value, 10) !== dimPercent) dimSlider.value = dimPercent;
    if (blurVal) blurVal.textContent = `${blurPx}px`;
    if (blurSlider && parseInt(blurSlider.value, 10) !== blurPx) blurSlider.value = blurPx;
  }

  if (persist) {
    try {
      localStorage.setItem('zettnas_wallpaper_dim', dimPercent.toString());
      localStorage.setItem('zettnas_wallpaper_blur', blurPx.toString());
    } catch (e) {}
  }
}

export function initWallpaperReadabilityControls() {
  const dimSlider = document.getElementById('wallpaper-dim-slider');
  const blurSlider = document.getElementById('wallpaper-blur-slider');
  const resetBtn = document.getElementById('wallpaper-readability-reset-btn');

  // Load saved values or default
  let savedDim = 15;
  let savedBlur = 0;
  try {
    const d = localStorage.getItem('zettnas_wallpaper_dim');
    if (d !== null) savedDim = parseInt(d, 10);
    const b = localStorage.getItem('zettnas_wallpaper_blur');
    if (b !== null) savedBlur = parseInt(b, 10);
  } catch (e) {}

  applyWallpaperReadability(savedDim, savedBlur, false);

  if (dimSlider) {
    dimSlider.addEventListener('input', (e) => {
      const curBlur = blurSlider ? parseInt(blurSlider.value, 10) : 0;
      applyWallpaperReadability(e.target.value, curBlur, false);
    });
    dimSlider.addEventListener('change', (e) => {
      const curBlur = blurSlider ? parseInt(blurSlider.value, 10) : 0;
      applyWallpaperReadability(e.target.value, curBlur, true);
    });
  }

  if (blurSlider) {
    blurSlider.addEventListener('input', (e) => {
      const curDim = dimSlider ? parseInt(dimSlider.value, 10) : 15;
      applyWallpaperReadability(curDim, e.target.value, false);
    });
    blurSlider.addEventListener('change', (e) => {
      const curDim = dimSlider ? parseInt(dimSlider.value, 10) : 15;
      applyWallpaperReadability(curDim, e.target.value, true);
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      applyWallpaperReadability(15, 0, true);
      showToast('Wallpaper readability reset to defaults', 'info');
    });
  }
}

/**
 * Glassmorphism & Visual Effects Engine (Acrylic Blur, Opacity, Radius, Specular Glow)
 */
export function applyGlassSettings(blurPx, opacityPercent, radiusPx, glowEnabled, persist = true) {
  blurPx = Math.max(0, Math.min(40, parseInt(blurPx, 10) || 0));
  opacityPercent = Math.max(30, Math.min(95, parseInt(opacityPercent, 10) || 72));
  radiusPx = ['6px', '12px', '20px'].includes(radiusPx) ? radiusPx : '12px';
  glowEnabled = Boolean(glowEnabled);

  if (typeof document !== 'undefined') {
    if (document.documentElement) {
      document.documentElement.style.setProperty('--glass-blur', `${blurPx}px`);
      document.documentElement.style.setProperty('--glass-opacity', (opacityPercent / 100).toFixed(2));
      document.documentElement.style.setProperty('--window-radius', radiusPx);
      document.documentElement.style.setProperty('--window-glow-enabled', glowEnabled ? '1' : '0');
    }
    if (document.body) {
      document.body.classList.toggle('no-specular-glow', !glowEnabled);
    }

    const blurVal = document.getElementById('glass-blur-val');
    const blurSlider = document.getElementById('glass-blur-slider');
    const opacityVal = document.getElementById('glass-opacity-val');
    const opacitySlider = document.getElementById('glass-opacity-slider');
    const glowToggle = document.getElementById('window-glow-toggle');
    const radiusBtns = document.querySelectorAll('.window-radius-btn');

    if (blurVal) blurVal.textContent = `${blurPx}px`;
    if (blurSlider && parseInt(blurSlider.value, 10) !== blurPx) blurSlider.value = blurPx;
    if (opacityVal) opacityVal.textContent = `${opacityPercent}%`;
    if (opacitySlider && parseInt(opacitySlider.value, 10) !== opacityPercent) opacitySlider.value = opacityPercent;
    if (glowToggle) glowToggle.checked = glowEnabled;

    radiusBtns.forEach((btn) => {
      const isMatch = btn.dataset.radius === radiusPx;
      btn.classList.toggle('active', isMatch);
      btn.setAttribute('aria-checked', isMatch ? 'true' : 'false');
    });
  }

  if (persist) {
    try {
      localStorage.setItem('zettnas_glass_blur', blurPx.toString());
      localStorage.setItem('zettnas_glass_opacity', opacityPercent.toString());
      localStorage.setItem('zettnas_window_radius', radiusPx);
      localStorage.setItem('zettnas_window_glow', glowEnabled ? 'true' : 'false');
    } catch (e) {}
  }
}

export function initGlassControls() {
  const blurSlider = document.getElementById('glass-blur-slider');
  const opacitySlider = document.getElementById('glass-opacity-slider');
  const glowToggle = document.getElementById('window-glow-toggle');
  const resetBtn = document.getElementById('glass-reset-btn');
  const radiusBtns = document.querySelectorAll('.window-radius-btn');

  // Load saved or defaults
  let savedBlur = 24;
  let savedOpacity = 72;
  let savedRadius = '12px';
  let savedGlow = false;

  try {
    const b = localStorage.getItem('zettnas_glass_blur');
    if (b !== null) savedBlur = parseInt(b, 10);
    const o = localStorage.getItem('zettnas_glass_opacity');
    if (o !== null) savedOpacity = parseInt(o, 10);
    const r = localStorage.getItem('zettnas_window_radius');
    if (r) savedRadius = r;
    const g = localStorage.getItem('zettnas_window_glow');
    if (g !== null) savedGlow = (g === 'true');
  } catch (e) {}

  applyGlassSettings(savedBlur, savedOpacity, savedRadius, savedGlow, false);

  if (blurSlider) {
    blurSlider.addEventListener('input', (e) => {
      const curOpacity = opacitySlider ? parseInt(opacitySlider.value, 10) : 72;
      const curGlow = glowToggle ? glowToggle.checked : false;
      const curActiveRadiusBtn = document.querySelector('.window-radius-btn.active');
      const curRadius = curActiveRadiusBtn ? curActiveRadiusBtn.dataset.radius : '12px';
      applyGlassSettings(e.target.value, curOpacity, curRadius, curGlow, false);
    });
    blurSlider.addEventListener('change', (e) => {
      const curOpacity = opacitySlider ? parseInt(opacitySlider.value, 10) : 72;
      const curGlow = glowToggle ? glowToggle.checked : false;
      const curActiveRadiusBtn = document.querySelector('.window-radius-btn.active');
      const curRadius = curActiveRadiusBtn ? curActiveRadiusBtn.dataset.radius : '12px';
      applyGlassSettings(e.target.value, curOpacity, curRadius, curGlow, true);
    });
  }

  if (opacitySlider) {
    opacitySlider.addEventListener('input', (e) => {
      const curBlur = blurSlider ? parseInt(blurSlider.value, 10) : 24;
      const curGlow = glowToggle ? glowToggle.checked : false;
      const curActiveRadiusBtn = document.querySelector('.window-radius-btn.active');
      const curRadius = curActiveRadiusBtn ? curActiveRadiusBtn.dataset.radius : '12px';
      applyGlassSettings(curBlur, e.target.value, curRadius, curGlow, false);
    });
    opacitySlider.addEventListener('change', (e) => {
      const curBlur = blurSlider ? parseInt(blurSlider.value, 10) : 24;
      const curGlow = glowToggle ? glowToggle.checked : false;
      const curActiveRadiusBtn = document.querySelector('.window-radius-btn.active');
      const curRadius = curActiveRadiusBtn ? curActiveRadiusBtn.dataset.radius : '12px';
      applyGlassSettings(curBlur, e.target.value, curRadius, curGlow, true);
    });
  }

  radiusBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const radius = btn.dataset.radius;
      const curBlur = blurSlider ? parseInt(blurSlider.value, 10) : 24;
      const curOpacity = opacitySlider ? parseInt(opacitySlider.value, 10) : 72;
      const curGlow = glowToggle ? glowToggle.checked : false;
      applyGlassSettings(curBlur, curOpacity, radius, curGlow, true);
    });
  });

  if (glowToggle) {
    glowToggle.addEventListener('change', (e) => {
      const curBlur = blurSlider ? parseInt(blurSlider.value, 10) : 24;
      const curOpacity = opacitySlider ? parseInt(opacitySlider.value, 10) : 72;
      const curActiveRadiusBtn = document.querySelector('.window-radius-btn.active');
      const curRadius = curActiveRadiusBtn ? curActiveRadiusBtn.dataset.radius : '12px';
      applyGlassSettings(curBlur, curOpacity, curRadius, e.target.checked, true);
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      applyGlassSettings(24, 72, '12px', false, true);
      showToast('Glass and visual effects reset to defaults', 'info');
    });
  }
}

