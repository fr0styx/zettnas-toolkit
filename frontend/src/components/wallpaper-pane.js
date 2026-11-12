/**
 * Kiboto Visual Wallpaper Gallery: thumbnail grid, 1-click live preview, drag-and-drop
 * upload, rename and delete, and the readability and glass sliders. Loaded when Mission Control's
 * wallpaper pane opens or an image is dropped on the desktop (NUX-15); wallpapers.js keeps what
 * the first paint needs.
 */
import { api } from '../api.js';
import { showToast, showPromptToast, showConfirmToast } from '../toast.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { applyGlassSettings, applyWallpaperReadability, loadWallpapers, setWallpaper } from './wallpapers.js';

let _wallpapersInitialized = false;

export async function selectWallpaper(filename) {
  const selectDropdown = document.getElementById('wallpaper-select');
  if (selectDropdown) {
    selectDropdown.value = filename || '';
  }

  if (filename) {
    setWallpaper(`/api/wallpapers/download/${encodeURIComponent(filename)}`, filename);
    try {
      await api.post('/api/wallpapers/select', { filename });
      showToast(t('toast.active_wallpaper', 'Active wallpaper: {filename}', { filename: filename }), 'success');
    } catch (err) {
      showToast(t('toast.failed_to_save_wallpaper_setting', 'Failed to save wallpaper setting'), 'error');
    }
  } else {
    setWallpaper(null);
    try {
      await api.post('/api/wallpapers/select', { filename: null });
      showToast(t('toast.theme_gradient_restored', 'Theme gradient restored'), 'info');
    } catch (err) {
      showToast(t('toast.failed_to_save_wallpaper_setting', 'Failed to save wallpaper setting'), 'error');
    }
  }
}

export async function renameWallpaper(oldName) {
  if (!oldName) return;
  showPromptToast(
    t('wp.rename_title', 'Rename wallpaper'),
    t('wp.rename_msg', 'Enter a new name for {name}:', { name: `<strong>${escapeHtml(oldName)}</strong>` }),
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
          showToast(t('toast.wallpaper_renamed_to', 'Wallpaper renamed to {new_name}', { new_name: data.new_name }), 'success');
          if (localStorage.getItem('kiboto_active_wallpaper') === oldName) {
            try {
              localStorage.setItem('kiboto_active_wallpaper', data.new_name);
            } catch (e) {}
          }
          await loadWallpapers();
        } else {
          showToast(t('toast.rename_failed', 'Rename failed: {error}', { error: data.error || t('toast.unknown_error', 'Unknown error') }), 'error');
        }
      } catch (err) {
        showToast(t('toast.rename_request_failed', 'Rename request failed: {error}', { error: err.message }), 'error');
      }
    },
    null,
    { okText: t('wp.rename', 'Rename'), cancelText: t('common.cancel', 'Cancel') }
  );
}

export async function deleteWallpaper(filename) {
  if (!filename) return;
  showConfirmToast(
    t('wp.delete_title', 'Delete wallpaper'),
    t('wp.delete_msg', 'Delete the wallpaper {name}? This can’t be undone.', { name: `<strong>${escapeHtml(filename)}</strong>` }),
    async () => {
      try {
        await api.delete(`/api/wallpapers/${encodeURIComponent(filename)}`);
        if (localStorage.getItem('kiboto_active_wallpaper') === filename) {
          try {
            localStorage.removeItem('kiboto_active_wallpaper');
          } catch (e) {}
        }
        showToast(t('toast.wallpaper_deleted', 'Wallpaper deleted'), 'success');
        await loadWallpapers();
      } catch (err) {
        showToast(t('toast.delete_failed', 'Delete failed: {error}', { error: err.message }), 'error');
      }
    },
    null,
    { okText: t('mgmt.wallpaper_delete', 'Delete'), cancelText: t('common.cancel', 'Cancel') }
  );
}

export function renderWallpaperGallery(files, active, version) {
  const galleryEl = document.getElementById('wallpaper-gallery-grid');
  const countBadge = document.getElementById('wallpaper-count-badge');

  if (countBadge) {
    countBadge.textContent = t('wp.count', '{n, plural, one {# background} other {# backgrounds}}', { n: files.length });
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
  defaultCard.setAttribute('title', t('wp.default_title', 'Use the theme gradient'));
  defaultCard.innerHTML = `
    <div class="wallpaper-card-thumb-wrap default-gradient-thumb">
      <div class="wallpaper-gradient-preview"></div>
      <div class="wallpaper-card-active-indicator" style="${isDefaultActive ? 'display:flex;' : 'display:none;'}">
        <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
        <span>ACTIVE</span>
      </div>
    </div>
    <div class="wallpaper-card-footer">
      <span class="wallpaper-card-title">${t('wp.theme_gradient', 'Theme gradient')}</span>
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
    card.setAttribute('title', t('wp.set_title', 'Use {name} as the wallpaper', { name: f }));

    const thumbUrl = `/api/wallpapers/thumb/${encodeURIComponent(f)}${v}`;
    const fullUrl = `/api/wallpapers/download/${encodeURIComponent(f)}${v}`;

    card.innerHTML = `
      <div class="wallpaper-card-thumb-wrap">
        <img class="wallpaper-card-thumb" src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(f)}" loading="lazy" data-img-fallback="${escapeHtml(fullUrl)}">
        <div class="wallpaper-card-active-indicator" style="${isActive ? 'display:flex;' : 'display:none;'}">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
          <span>${escapeHtml(t('wp.active', 'Active'))}</span>
        </div>
        <div class="wallpaper-card-actions">
          <button class="wallpaper-action-btn rename-btn" title="${t('ui.rename_image', 'Rename image')}" aria-label="${t('ui.rename_image', 'Rename image')}">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
          </button>
          <button class="wallpaper-action-btn delete-btn" title="${t('ui.delete_image', 'Delete image')}" aria-label="${t('ui.delete_image', 'Delete image')}">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
          </button>
        </div>
      </div>
      <div class="wallpaper-card-footer">
        <span class="wallpaper-card-title" title="${escapeHtml(f)}">${escapeHtml(f)}</span>
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

  filterGalleryByCategory(_activeCategory);
}

let _activeCategory = 'all';

export function filterGalleryByCategory(cat = 'all') {
  _activeCategory = cat;
  document.querySelectorAll('.wallpaper-cat-pill').forEach((pill) => {
    pill.classList.toggle('active', (pill.dataset.cat || pill.dataset.category) === cat);
  });
  const cards = document.querySelectorAll('.wallpaper-card');
  let visibleCount = 0;
  cards.forEach((card) => {
    const fn = (card.getAttribute('data-filename') || '').toLowerCase();
    let isMatch = true;
    if (cat === 'gradient') {
      isMatch = !fn || fn.includes('gradient');
    } else if (cat === 'scenic') {
      isMatch = fn.includes('nature') || fn.includes('mountain') || fn.includes('fjord') || fn.includes('landscape') || fn.includes('sea') || fn.includes('lake') || fn.includes('sunset') || fn.includes('aurora') || fn.includes('forest');
    } else if (cat === 'cyber') {
      isMatch = fn.includes('cyber') || fn.includes('matrix') || fn.includes('neon') || fn.includes('tokyo') || fn.includes('synth') || fn.includes('future') || fn.includes('amethyst');
    } else if (cat === 'oled') {
      isMatch = fn.includes('oled') || fn.includes('dark') || fn.includes('black') || fn.includes('space') || fn.includes('star');
    }
    card.style.display = isMatch ? 'flex' : 'none';
    if (isMatch) visibleCount++;
  });
  const countBadge = document.getElementById('wallpaper-count-badge');
  if (countBadge) {
    countBadge.textContent = t('wp.count', '{n, plural, one {# background} other {# backgrounds}}', { n: visibleCount });
  }
}

export function showWallpaperList(files, active, version) {
  const selectDropdown = document.getElementById('wallpaper-select');
  if (selectDropdown) {
    selectDropdown.replaceChildren(new Option(t('wp.theme_gradient', 'Theme gradient'), ''));
    files.forEach((f) => {
      const opt = document.createElement('option');
      opt.value = f;
      opt.textContent = f;
      selectDropdown.appendChild(opt);
    });
    selectDropdown.value = active || '';
  }
  renderWallpaperGallery(files, active, version);
}

if (typeof window !== 'undefined') {
  window.selectWallpaper = selectWallpaper;
}

export async function uploadAndApplyWallpaper(file) {
  if (!file) return false;
  const MAX_BYTES = 15 * 1024 * 1024; // 15MB limit
  if (file.size && file.size > MAX_BYTES) {
    showToast(t('toast.file_size_exceeds_15mb_limit_please', 'File size exceeds 15MB limit. Please choose a smaller image.'), 'error');
    return false;
  }
  const validTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/avif', 'image/gif', 'image/svg+xml'];
  if (file.type && !validTypes.includes(file.type)) {
    showToast(t('toast.unsupported_file_format_please_upload_jpg', 'Unsupported file format. Please upload JPG, PNG, WEBP, or AVIF.'), 'error');
    return false;
  }
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
              localStorage.setItem('kiboto_active_wallpaper', data.filename);
            } catch (e) {}
          }
          await loadWallpapers();
          if (data.filename) {
            await selectWallpaper(data.filename);
          }
          showToast(t('toast.wallpaper_uploaded_applied', 'Wallpaper uploaded & applied: {filename}', { filename: data.filename || file.name }), 'success');
          resolve(data);
        } else {
          showToast(t('toast.upload_failed', 'Upload failed: {errDetail}', { errDetail: (data && data.error) || t('toast.unknown_error', 'Unknown error') }), 'error');
          reject(new Error((data && data.error) || 'Upload error'));
        }
      } catch (err) {
        showToast(t('toast.upload_failed', 'Upload failed: {errDetail}', { errDetail: err.message }), 'error');
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error('Failed reading image file'));
    reader.readAsDataURL(file);
  });
}

// The wallpaper gallery and sliders live in Mission Control, inserted when first needed (FE-04)
export function initWallpaperPane() {
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

  const catPills = document.querySelectorAll('.wallpaper-cat-pill');
  catPills.forEach((pill) => {
    pill.addEventListener('click', () => {
      const cat = pill.dataset.cat || 'all';
      catPills.forEach((p) => p.classList.toggle('active', p === pill));
      filterGalleryByCategory(cat);
    });
  });

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

export function initWallpaperReadabilityControls() {
  const dimSlider = document.getElementById('wallpaper-dim-slider');
  const blurSlider = document.getElementById('wallpaper-blur-slider');
  const resetBtn = document.getElementById('wallpaper-readability-reset-btn');

  // Load saved values or default
  let savedDim = 15;
  let savedBlur = 0;
  try {
    const d = localStorage.getItem('kiboto_wallpaper_dim');
    if (d !== null) savedDim = parseInt(d, 10);
    const b = localStorage.getItem('kiboto_wallpaper_blur');
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
      showToast(t('toast.wallpaper_readability_reset_to_defaults', 'Wallpaper readability reset to defaults'), 'info');
    });
  }
}

/** Effects' three window looks (APP-C). Solid is Eco mode: no blur, so its blur and opacity stay as they are. */
export const WINDOW_STYLES = {
  glass: { blur: 24, opacity: 72, eco: false },
  soft: { blur: 12, opacity: 88, eco: false },
  solid: { blur: 24, opacity: 72, eco: true },
};

/** Which look these settings are, or '' for a mix of the person's own. */
export function windowStyleOf({ blur, opacity, eco }) {
  if (eco) return 'solid';
  const hit = Object.entries(WINDOW_STYLES).find(([, s]) => !s.eco && s.blur === blur && s.opacity === opacity);
  return hit ? hit[0] : '';
}

function _sliderValue(id, fallback) {
  const el = /** @type {HTMLInputElement | null} */ (document.getElementById(id));
  const v = el ? parseInt(el.value, 10) : NaN;
  return Number.isFinite(v) ? v : fallback;
}

function _isEco() {
  return document.body.getAttribute('data-performance-mode') === 'eco';
}

/** Marks the chosen look, and says so when the sliders hold a mix of the person's own. */
export function syncWindowStyleUI() {
  const cur = windowStyleOf({ blur: _sliderValue('glass-blur-slider', 24), opacity: _sliderValue('glass-opacity-slider', 72), eco: _isEco() });
  const btns = Array.from(document.querySelectorAll('[data-window-style]'));
  btns.forEach((b, i) => {
    const on = /** @type {HTMLElement} */ (b).dataset.windowStyle === cur;
    b.classList.toggle('active', on);
    b.setAttribute('aria-checked', on ? 'true' : 'false');
    // one stop for Tab: the chosen look, or the first when none is
    b.setAttribute('tabindex', on || (!cur && i === 0) ? '0' : '-1');
  });
  const note = document.getElementById('effects-custom-note');
  if (note) note.hidden = cur !== '';
}

/** Eco mode on or off: windows drawn solid, without the blur. */
export function setEcoMode(on) {
  if (on) document.body.setAttribute('data-performance-mode', 'eco');
  else document.body.removeAttribute('data-performance-mode');
  try {
    localStorage.setItem('kiboto_eco_mode', on ? 'true' : 'false');
  } catch {}
}

export function chooseWindowStyle(name) {
  const s = WINDOW_STYLES[name];
  if (!s) return;
  setEcoMode(s.eco);
  if (!s.eco) {
    const glow = /** @type {HTMLInputElement | null} */ (document.getElementById('window-glow-toggle'))?.checked || false;
    const radius = /** @type {HTMLElement | null} */ (document.querySelector('.window-radius-btn.active'))?.dataset.radius || '12px';
    applyGlassSettings(s.blur, s.opacity, radius, glow, true);
  }
  syncWindowStyleUI();
}

/** Arrow keys move through the looks, as in any group of radio buttons. */
export function onWindowStyleKey(e) {
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (!step) return;
  const btns = /** @type {HTMLElement[]} */ (Array.from(document.querySelectorAll('[data-window-style]')));
  const i = btns.indexOf(/** @type {HTMLElement} */ (e.currentTarget));
  const next = btns[(i + step + btns.length) % btns.length];
  e.preventDefault();
  chooseWindowStyle(next.dataset.windowStyle);
  next.focus();
}

/** Moving a Fine-tune slider means glass: Solid (Eco) lets go so the change shows. */
function _leaveSolid() {
  if (_isEco()) setEcoMode(false);
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
    const b = localStorage.getItem('kiboto_glass_blur');
    if (b !== null) savedBlur = parseInt(b, 10);
    const o = localStorage.getItem('kiboto_glass_opacity');
    if (o !== null) savedOpacity = parseInt(o, 10);
    const r = localStorage.getItem('kiboto_window_radius');
    if (r) savedRadius = r;
    const g = localStorage.getItem('kiboto_window_glow');
    if (g !== null) savedGlow = (g === 'true');
  } catch (e) {}

  applyGlassSettings(savedBlur, savedOpacity, savedRadius, savedGlow, false);

  if (blurSlider) {
    blurSlider.addEventListener('input', (e) => {
      _leaveSolid();
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
      _leaveSolid();
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

  let savedEco = false;
  try {
    savedEco = localStorage.getItem('kiboto_eco_mode') === 'true';
  } catch {}
  if (savedEco) document.body.setAttribute('data-performance-mode', 'eco');

  document.querySelectorAll('[data-window-style]').forEach((b) => {
    const btn = /** @type {HTMLElement} */ (b);
    btn.addEventListener('click', () => chooseWindowStyle(btn.dataset.windowStyle));
    btn.addEventListener('keydown', onWindowStyleKey);
  });
  // applyGlassSettings and a look import call this once the pane is loaded
  /** @type {any} */ (window).syncWindowStyleUI = syncWindowStyleUI;
  syncWindowStyleUI();

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      document.body.removeAttribute('data-performance-mode');
      try {
        localStorage.removeItem('kiboto_eco_mode');
      } catch (e) {}
      applyGlassSettings(24, 72, '12px', false, true);
      syncWindowStyleUI();
      showToast(t('toast.glass_and_visual_effects_reset_to', 'Glass and visual effects reset to defaults'), 'info');
    });
  }
}
