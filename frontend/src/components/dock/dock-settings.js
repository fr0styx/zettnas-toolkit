// Dock position, size, autohide and magnification, and their controls.
// Part of dock.js, split out by ARC-5.

import { prefersReducedMotion } from '../../motion.js';
import { t } from '../../i18n.js';
import { showDockToast } from './notifications.js';

let _magnificationEnabled = true;
let _magnificationScale = 1.45;
export let _dockPosition = 'bottom';
export let _dockSize = 'medium';
export let _dockAutohide = false;
let _parabolicInitialized = false;

export function initParabolicDockMagnification(dockEl) {
  if (!dockEl) dockEl = document.getElementById('os-dock');
  if (!dockEl) return;
  if (dockEl._parabolicBound) return;
  dockEl._parabolicBound = true;

  const radius = 130;

  dockEl.addEventListener('pointermove', (e) => {
    if (!_magnificationEnabled) return;
    if (prefersReducedMotion()) return;

    const items = Array.from(dockEl.querySelectorAll('.dock-item'));
    if (!items.length) return;

    const isVertical = _dockPosition === 'left';
    const pointerPos = isVertical ? (e.clientY ?? 0) : (e.clientX ?? 0);

    items.forEach((item) => {
      const rect = item.getBoundingClientRect();
      const center = isVertical
        ? (rect.top + rect.height / 2)
        : (rect.left + rect.width / 2);
      const distance = Math.abs(pointerPos - center);

      let scale = 1;
      if (distance < radius) {
        const cosFactor = Math.cos((distance / radius) * (Math.PI / 2));
        scale = 1 + (_magnificationScale - 1) * cosFactor;
      }
      item.style.setProperty('--dock-item-scale', scale.toFixed(3));
    });
  });

  dockEl.addEventListener('pointerleave', () => {
    const items = dockEl.querySelectorAll('.dock-item');
    items.forEach((item) => {
      item.style.setProperty('--dock-item-scale', '1');
    });
  });
}

export function applyDockSettings(position = 'bottom', magnification = true, maxScale = 1.45, iconSize = 'medium', autohide = false, persist = true) {
  _dockPosition = ['bottom', 'left', 'top'].includes(position) ? position : 'bottom';
  _magnificationEnabled = Boolean(magnification);
  _magnificationScale = Math.max(1.1, Math.min(1.8, parseFloat(maxScale) || 1.45));
  _dockSize = ['small', 'medium', 'large'].includes(iconSize) ? iconSize : 'medium';
  _dockAutohide = Boolean(autohide);

  if (typeof document !== 'undefined') {
    const root = document.documentElement;
    const dockContainer = document.getElementById('os-dock-container');
    const dock = document.getElementById('os-dock');

    let heightVal = '52px';
    let iconPx = '48px';
    if (_dockSize === 'small') {
      heightVal = '44px';
      iconPx = '42px';
    } else if (_dockSize === 'large') {
      heightVal = '64px';
      iconPx = '60px';
    }

    if (root) {
      root.style.setProperty('--dock-position', _dockPosition);
      root.style.setProperty('--dock-height', heightVal);
      root.style.setProperty('--dock-icon-size', iconPx);

      if (_dockPosition === 'bottom') {
        root.style.setProperty('--workspace-inset-bottom', _dockAutohide ? '0px' : `calc(${heightVal} + 16px)`);
        root.style.setProperty('--workspace-inset-left', '0px');
        root.style.setProperty('--workspace-inset-top', '0px');
      } else if (_dockPosition === 'left') {
        root.style.setProperty('--workspace-inset-bottom', '0px');
        root.style.setProperty('--workspace-inset-left', _dockAutohide ? '0px' : `calc(${heightVal} + 16px)`);
        root.style.setProperty('--workspace-inset-top', '0px');
      } else if (_dockPosition === 'top') {
        root.style.setProperty('--workspace-inset-bottom', '0px');
        root.style.setProperty('--workspace-inset-left', '0px');
        root.style.setProperty('--workspace-inset-top', _dockAutohide ? '0px' : `calc(${heightVal} + 16px)`);
      }
    }

    if (dockContainer) {
      dockContainer.classList.remove('dock-pos-bottom', 'dock-pos-left', 'dock-pos-top');
      dockContainer.classList.add(`dock-pos-${_dockPosition}`);
      dockContainer.classList.toggle('dock-autohide', _dockAutohide);
    }

    if (dock) {
      dock.classList.remove('dock-size-small', 'dock-size-medium', 'dock-size-large');
      dock.classList.add(`dock-size-${_dockSize}`);
      dock.classList.toggle('dock-magnify-enabled', _magnificationEnabled);

      if (!_magnificationEnabled) {
        dock.querySelectorAll('.dock-item').forEach((item) => {
          item.style.setProperty('--dock-item-scale', '1');
        });
      }
    }

    const posBtns = document.querySelectorAll('.dock-pos-btn');
    posBtns.forEach((btn) => {
      const isMatch = btn.dataset.pos === _dockPosition;
      btn.classList.toggle('active', isMatch);
      btn.setAttribute('aria-checked', isMatch ? 'true' : 'false');
    });

    const sizeBtns = document.querySelectorAll('.dock-size-btn');
    sizeBtns.forEach((btn) => {
      const isMatch = btn.dataset.size === _dockSize;
      btn.classList.toggle('active', isMatch);
      btn.setAttribute('aria-checked', isMatch ? 'true' : 'false');
    });

    const magToggle = document.getElementById('dock-magnification-toggle');
    if (magToggle) magToggle.checked = _magnificationEnabled;

    const magSlider = document.getElementById('dock-magnification-slider');
    if (magSlider && parseFloat(magSlider.value) !== _magnificationScale) {
      magSlider.value = _magnificationScale.toString();
    }

    const magVal = document.getElementById('dock-magnification-val');
    if (magVal) magVal.textContent = `${_magnificationScale.toFixed(2)}x`;

    const autohideToggle = document.getElementById('dock-autohide-toggle');
    if (autohideToggle) autohideToggle.checked = _dockAutohide;

    if (typeof window !== 'undefined' && typeof window.syncDesktopTwinPreview === 'function') {
      window.syncDesktopTwinPreview({ dockPos: _dockPosition });
    }
  }

  if (persist) {
    try {
      localStorage.setItem('zettnas_dock_position', _dockPosition);
      localStorage.setItem('zettnas_dock_magnification', _magnificationEnabled ? 'true' : 'false');
      localStorage.setItem('zettnas_dock_scale', _magnificationScale.toString());
      localStorage.setItem('zettnas_dock_size', _dockSize);
      localStorage.setItem('zettnas_dock_autohide', _dockAutohide ? 'true' : 'false');
    } catch (e) {}
  }
}

export function getDockSettings() {
  return {
    position: _dockPosition,
    magnification: _magnificationEnabled,
    scale: _magnificationScale,
    size: _dockSize,
    autohide: _dockAutohide
  };
}

export function initDockSettingsControls() {
  let savedPos = 'bottom';
  let savedMag = true;
  let savedScale = 1.45;
  let savedSize = 'medium';
  let savedAutohide = false;

  try {
    const p = localStorage.getItem('zettnas_dock_position');
    if (p) savedPos = p;
    const m = localStorage.getItem('zettnas_dock_magnification');
    if (m !== null) savedMag = (m === 'true');
    const s = localStorage.getItem('zettnas_dock_scale');
    if (s !== null) savedScale = parseFloat(s) || 1.45;
    const sz = localStorage.getItem('zettnas_dock_size');
    if (sz) savedSize = sz;
    const ah = localStorage.getItem('zettnas_dock_autohide');
    if (ah !== null) savedAutohide = (ah === 'true');
  } catch (e) {}

  applyDockSettings(savedPos, savedMag, savedScale, savedSize, savedAutohide, false);

  const dockEl = document.getElementById('os-dock');
  if (dockEl) {
    initParabolicDockMagnification(dockEl);
  }

  const posBtns = document.querySelectorAll('.dock-pos-btn');
  posBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const pos = btn.dataset.pos;
      applyDockSettings(pos, _magnificationEnabled, _magnificationScale, _dockSize, _dockAutohide, true);
    });
  });

  const sizeBtns = document.querySelectorAll('.dock-size-btn');
  sizeBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const sz = btn.dataset.size;
      applyDockSettings(_dockPosition, _magnificationEnabled, _magnificationScale, sz, _dockAutohide, true);
    });
  });

  const magToggle = document.getElementById('dock-magnification-toggle');
  if (magToggle) {
    magToggle.addEventListener('change', (e) => {
      applyDockSettings(_dockPosition, e.target.checked, _magnificationScale, _dockSize, _dockAutohide, true);
    });
  }

  const magSlider = document.getElementById('dock-magnification-slider');
  if (magSlider) {
    magSlider.addEventListener('input', (e) => {
      applyDockSettings(_dockPosition, _magnificationEnabled, parseFloat(e.target.value), _dockSize, _dockAutohide, false);
    });
    magSlider.addEventListener('change', (e) => {
      applyDockSettings(_dockPosition, _magnificationEnabled, parseFloat(e.target.value), _dockSize, _dockAutohide, true);
    });
  }

  const autohideToggle = document.getElementById('dock-autohide-toggle');
  if (autohideToggle) {
    autohideToggle.addEventListener('change', (e) => {
      applyDockSettings(_dockPosition, _magnificationEnabled, _magnificationScale, _dockSize, e.target.checked, true);
    });
  }

  const resetBtn = document.getElementById('dock-reset-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      applyDockSettings('bottom', true, 1.45, 'medium', false, true);
      showDockToast(t('mgmt.dock_reset_toast', 'Dock settings restored to defaults'));
    });
  }
}
