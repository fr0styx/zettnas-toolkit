import { onManagementDom } from '../management-dom.js';
import { state } from '../state.js';
/**
 * Kiboto wallpaper: the active wallpaper and the readability and glass settings, which
 * the desktop needs from the first paint. The gallery, upload, rename, delete and the sliders are
 * in wallpaper-pane.js, loaded when Mission Control's pane opens or an image is dropped (NUX-15).
 */
import { api } from '../api.js';

let _loadPromise = null;
let _currentFiles = [];
let _activeWallpaper = null;

export function setWallpaper(url, filename = null) {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;

  const wpLayer = typeof document !== 'undefined' ? document.getElementById('desktop-wallpaper') : null;

  if (url) {
    if (filename) {
      try {
        localStorage.setItem('kiboto_active_wallpaper', filename);
      } catch (e) {}
    }
    if (wpLayer) {
      wpLayer.style.setProperty('background-image', `url('${url}')`);
      wpLayer.style.display = 'block';
    }
    const dtWp = typeof document !== 'undefined' ? document.getElementById('dt-wallpaper') : null;
    if (dtWp) {
      dtWp.style.setProperty('background-image', `url('${url}')`);
      dtWp.style.display = 'block';
    }
    document.body.style.setProperty('background-image', `url('${url}')`, 'important');
    document.body.style.setProperty('background-size', 'cover', 'important');
    document.body.style.setProperty('background-position', 'center center', 'important');
    document.body.style.setProperty('background-repeat', 'no-repeat', 'important');
    document.body.style.setProperty('background-attachment', 'fixed', 'important');
  } else {
    try {
      localStorage.removeItem('kiboto_active_wallpaper');
    } catch (e) {}
    if (wpLayer) {
      wpLayer.style.removeProperty('background-image');
      wpLayer.style.display = 'none';
    }
    const dtWp = typeof document !== 'undefined' ? document.getElementById('dt-wallpaper') : null;
    if (dtWp) {
      dtWp.style.removeProperty('background-image');
    }
    document.body.style.removeProperty('background-image');
    document.body.style.removeProperty('background-size');
    document.body.style.removeProperty('background-position');
    document.body.style.removeProperty('background-repeat');
    document.body.style.removeProperty('background-attachment');
  }

  // Update active state in visual gallery grid if rendered
  _updateGalleryActiveState(filename);

  const earlyWp = document.getElementById('kiboto-wallpaper-early-style');
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

export function loadWallpapers() {
  if (_loadPromise) return _loadPromise;
  _loadPromise = (async () => {
    try {
      const data = await api.get('/api/wallpapers');
      _currentFiles = data.files || [];
      _activeWallpaper = data.active || null;
      // the gallery and the list are Mission Control's: drawn only once that pane is there (NUX-15)
      if (document.getElementById('wallpaper-gallery-grid') || document.getElementById('wallpaper-select')) {
        const pane = await import('./wallpaper-pane.js');
        pane.showWallpaperList(_currentFiles, data.active, data.version);
      }

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

export function initWallpapers() {
  loadWallpapers(); // applies the active wallpaper right away
  onManagementDom(() => import('./wallpaper-pane.js').then((pane) => pane.initWallpaperPane()));
}

if (typeof window !== 'undefined') {
  window.loadWallpapers = loadWallpapers;
  window.setWallpaper = setWallpaper;
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
      document.documentElement.classList.toggle('has-wallpaper-blur', blurPx > 0);
    }
    const dimVal = document.getElementById('wallpaper-dim-val');
    const dimSlider = document.getElementById('wallpaper-dim-slider');
    const blurVal = document.getElementById('wallpaper-blur-val');
    const blurSlider = document.getElementById('wallpaper-blur-slider');

    if (dimVal) dimVal.textContent = `${dimPercent}%`;
    if (dimSlider && parseInt(dimSlider.value, 10) !== dimPercent) dimSlider.value = dimPercent;
    if (blurVal) blurVal.textContent = `${blurPx}px`;
    if (blurSlider && parseInt(blurSlider.value, 10) !== blurPx) blurSlider.value = blurPx;

    if (typeof window !== 'undefined' && typeof window.syncDesktopTwinPreview === 'function') {
      window.syncDesktopTwinPreview({ wallpaperDim: dimPercent, wallpaperBlur: blurPx });
    }
  }

  if (persist) {
    try {
      localStorage.setItem('kiboto_wallpaper_dim', dimPercent.toString());
      localStorage.setItem('kiboto_wallpaper_blur', blurPx.toString());
    } catch (e) {}
  }
}
if (typeof window !== 'undefined') window.applyWallpaperReadability = applyWallpaperReadability;

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

    if (typeof window !== 'undefined') /** @type {any} */ (window).syncWindowStyleUI?.();
    if (typeof window !== 'undefined' && typeof window.syncDesktopTwinPreview === 'function') {
      window.syncDesktopTwinPreview({
        glassBlur: blurPx,
        glassOpacity: opacityPercent,
        windowRadius: radiusPx,
        windowGlow: glowEnabled
      });
    }
  }

  if (persist) {
    try {
      localStorage.setItem('kiboto_glass_blur', blurPx.toString());
      localStorage.setItem('kiboto_glass_opacity', opacityPercent.toString());
      localStorage.setItem('kiboto_window_radius', radiusPx);
      localStorage.setItem('kiboto_window_glow', glowEnabled ? 'true' : 'false');
    } catch (e) {}
  }
}
if (typeof window !== 'undefined') window.applyGlassSettings = applyGlassSettings;
