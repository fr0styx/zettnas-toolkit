/**
 * ZettNAS Toolkit Settings & Preferences Controller
 * Handles settings drawer, screen backlight, timezone, hardware buttons, card layout locks, and security credentials.
 */
import { api } from '../api.js';
import { state, ZOOM_PROFILES } from '../state.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast } from '../toast.js';
import { applyTheme } from './dashboard.js';
import { applyDashboardLayout, persistDashboardLayout } from './mini-preview.js';

const $ = (id) => document.getElementById(id);

export function openDrawer() {
  const drawer = $('slide-drawer');
  const overlay = $('drawer-backdrop');
  if (drawer) drawer.classList.add('open');
  if (overlay) overlay.classList.add('open');
  document.body.classList.add('drawer-is-open');
}

export function closeDrawer() {
  const drawer = $('slide-drawer');
  const overlay = $('drawer-backdrop');
  if (drawer) drawer.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
  document.body.classList.remove('drawer-is-open');
}

export function initSettings() {
  const toggleBtn = $('drawer-toggle-btn');
  const suiteBtn = $('toolkit-suite-btn');
  const closeBtn = $('drawer-close-btn');
  const overlay = $('drawer-backdrop');
  const drawer = $('slide-drawer');

  if (toggleBtn) toggleBtn.addEventListener('click', openDrawer);
  if (suiteBtn) suiteBtn.addEventListener('click', openDrawer);
  if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
  if (overlay) overlay.addEventListener('click', closeDrawer);

  let wheelZoomCooldown = 0;
  window.addEventListener('wheel', (e) => {
    if (e.target.closest('.slide-drawer') || e.target.closest('.smart-modal-window, #console-window') || e.target.closest('#mini-lcd-canvas')) {
      return;
    }
    const now = Date.now();
    if (now - wheelZoomCooldown < 150) return;

    if (e.deltaY < 0 && state.currentZoomIdx < ZOOM_PROFILES.length - 1) {
      state.setZoomIdx(state.currentZoomIdx + 1);
      wheelZoomCooldown = now;
    } else if (e.deltaY > 0 && state.currentZoomIdx > 0) {
      state.setZoomIdx(state.currentZoomIdx - 1);
      wheelZoomCooldown = now;
    }
  }, { passive: true });

  const yakEggBtn = $('yak-easter-egg-btn');
  if (yakEggBtn) {
    yakEggBtn.addEventListener('click', () => {
      applyTheme(state.currentTheme === 'yak' ? 'cyber' : 'yak');
    });
  }

  // --- Clock Format & Timezone ---
  const clockFmtBtn = $('clock-format-btn');
  if (clockFmtBtn) {
    clockFmtBtn.addEventListener('click', () => {
      state.clockFormat = state.clockFormat === '24' ? '12' : '24';
      clockFmtBtn.textContent = state.clockFormat === '12' ? '12 Hours' : '24 Hours';
      applyDashboardLayout();
      persistDashboardLayout();
    });
  }

  const tzSelect = $('tz-select-input');
  if (tzSelect) {
    tzSelect.value = state.currentTimezone;
    tzSelect.addEventListener('change', (e) => {
      state.currentTimezone = e.target.value;
      applyDashboardLayout();
      persistDashboardLayout();
    });
  }

  // --- Layout Cards Locking & Dragging ---
  const layoutSectionsContainer = $('layout-sections-container');
  const layoutLockBtn = $('layout-cards-lock-btn');
  const LAYOUT_SECTIONS_STORAGE_KEY = 'lcd_dash_card_order';
  const LAYOUT_LOCK_KEY = 'lcd_dash_cards_locked';
  let isLayoutLocked = localStorage.getItem(LAYOUT_LOCK_KEY) !== 'false';

  function setLayoutLockState(locked) {
    isLayoutLocked = locked;
    localStorage.setItem(LAYOUT_LOCK_KEY, isLayoutLocked);
    if (layoutSectionsContainer) layoutSectionsContainer.classList.toggle('locked', isLayoutLocked);
    if (layoutLockBtn) {
      layoutLockBtn.textContent = isLayoutLocked ? '🔒 Locked' : '🔓 Reorder';
      layoutLockBtn.classList.toggle('unlocked', !isLayoutLocked);
    }
    if (layoutSectionsContainer) {
      layoutSectionsContainer.querySelectorAll('.draggable-card').forEach((card) => {
        card.setAttribute('draggable', !isLayoutLocked);
      });
    }
  }

  function initLayoutSectionReordering() {
    if (!layoutSectionsContainer) return;
    const savedOrder = JSON.parse(localStorage.getItem(LAYOUT_SECTIONS_STORAGE_KEY) || '[]');
    if (savedOrder.length > 0) {
      const cardMap = {};
      layoutSectionsContainer.querySelectorAll('.draggable-card').forEach((c) => {
        cardMap[c.dataset.layoutCardId] = c;
      });
      savedOrder.forEach((id) => {
        if (cardMap[id]) layoutSectionsContainer.appendChild(cardMap[id]);
      });
    }

    let draggedLayoutCard = null;
    let allowLayoutDrag = false;

    layoutSectionsContainer.addEventListener('mousedown', (e) => {
      if (e.target.closest('#mini-lcd-canvas') || e.target.closest('.dash-reorder-flow')) {
        allowLayoutDrag = false;
        return;
      }
      allowLayoutDrag = !isLayoutLocked && !!e.target.closest('.drag-handle');
    });

    layoutSectionsContainer.querySelectorAll('.draggable-card').forEach((card) => {
      card.addEventListener('dragstart', (e) => {
        if (isLayoutLocked || !allowLayoutDrag) { e.preventDefault(); return false; }
        draggedLayoutCard = card;
        card.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', card.dataset.layoutCardId);
      });

      card.addEventListener('dragend', () => {
        allowLayoutDrag = false;
        card.classList.remove('dragging');
        layoutSectionsContainer.querySelectorAll('.draggable-card').forEach((c) => c.classList.remove('drag-over'));
        const order = Array.from(layoutSectionsContainer.querySelectorAll('.draggable-card')).map((c) => c.dataset.layoutCardId);
        localStorage.setItem(LAYOUT_SECTIONS_STORAGE_KEY, JSON.stringify(order));
      });

      card.addEventListener('dragover', (e) => {
        if (isLayoutLocked) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const targetCard = e.target.closest('.draggable-card');
        if (targetCard && targetCard !== draggedLayoutCard) {
          const rect = targetCard.getBoundingClientRect();
          const next = (e.clientY - rect.top) / (rect.bottom - rect.top) > 0.5;
          layoutSectionsContainer.insertBefore(draggedLayoutCard, next && targetCard.nextSibling || targetCard);
        }
      });
    });

    if (layoutLockBtn) layoutLockBtn.addEventListener('click', () => setLayoutLockState(!isLayoutLocked));
    setLayoutLockState(isLayoutLocked);
  }

  initLayoutSectionReordering();

  // --- Screen Backlight & Night Dimming ---
  const screenBriSlider = $('screen-bri-slider');
  const screenBriVal = $('screen-bri-val');
  const screenNightToggle = $('screen-night-toggle');
  const screenNightStart = $('screen-night-start');
  const screenNightEnd = $('screen-night-end');
  const screenNightBri = $('screen-night-bri');
  let screenDebounce = null;

  async function postScreenState() {
    const payload = {
      brightness: parseInt(screenBriSlider ? screenBriSlider.value : 100, 10),
      night_mode: screenNightToggle ? screenNightToggle.checked : false,
      night_start: screenNightStart ? screenNightStart.value : '23:00',
      night_end: screenNightEnd ? screenNightEnd.value : '07:00',
      night_brightness: parseInt(screenNightBri ? screenNightBri.value : 10, 10)
    };
    try {
      await api.post('/api/screen', payload);
    } catch (e) {
      console.warn('Failed to update screen state', e);
    }
  }

  async function fetchScreenState() {
    try {
      const data = await api.get('/api/screen');
      if (screenBriSlider && data.brightness !== undefined) screenBriSlider.value = data.brightness;
      if (screenBriVal && screenBriSlider) screenBriVal.textContent = screenBriSlider.value + '%';
      if (screenNightToggle) screenNightToggle.checked = Boolean(data.night_mode);
      if (screenNightStart && data.night_start) screenNightStart.value = data.night_start;
      if (screenNightEnd && data.night_end) screenNightEnd.value = data.night_end;
      if (screenNightBri && data.night_brightness !== undefined) screenNightBri.value = data.night_brightness;
    } catch (e) {
      console.warn('Failed to fetch screen state', e);
    }
  }

  fetchScreenState();

  if (screenBriSlider) {
    screenBriSlider.addEventListener('input', (e) => {
      if (screenBriVal) screenBriVal.textContent = e.target.value + '%';
      clearTimeout(screenDebounce);
      screenDebounce = setTimeout(postScreenState, 100);
    });
  }
  if (screenNightToggle) screenNightToggle.addEventListener('change', postScreenState);
  if (screenNightStart) screenNightStart.addEventListener('change', postScreenState);
  if (screenNightEnd) screenNightEnd.addEventListener('change', postScreenState);
  if (screenNightBri) screenNightBri.addEventListener('change', postScreenState);

  // --- Hardware Auto-Copy Button Config ---
  const btnCopyToggle = $('btn-copy-toggle');
  const btnCopyOptions = $('btn-copy-options');
  const btnCopySrc = $('btn-copy-src');
  const btnCopyDst = $('btn-copy-dst');
  const btnCopyExif = $('btn-copy-exif');
  const btnCopySave = $('btn-copy-save');

  async function loadButtonConfig() {
    try {
      const data = await api.get('/api/buttons');
      if (btnCopyToggle) btnCopyToggle.checked = !!data.enabled;
      if (btnCopySrc) btnCopySrc.value = data.source || 'sd';
      if (btnCopyDst) btnCopyDst.value = data.dest || '/mnt/user/';
      if (btnCopyExif) btnCopyExif.checked = data.use_exif !== false;

      if (btnCopyOptions) {
        btnCopyOptions.style.opacity = data.enabled ? '1' : '0.3';
        btnCopyOptions.style.pointerEvents = data.enabled ? 'auto' : 'none';
        btnCopyOptions.style.transition = 'opacity 0.2s ease';
      }
      const statusText = $('btn-copy-status-text');
      if (statusText) {
        statusText.textContent = data.enabled ? 'ENABLED' : 'DISABLED';
        statusText.style.color = data.enabled ? '#2ecc71' : 'inherit';
      }
    } catch (e) {
      console.warn('Failed to load button config', e);
    }
  }

  async function saveButtonConfig(e) {
    try {
      await api.post('/api/buttons', {
        enabled: btnCopyToggle ? btnCopyToggle.checked : false,
        source: btnCopySrc ? btnCopySrc.value : 'sd',
        dest: btnCopyDst ? btnCopyDst.value : '/mnt/user/',
        use_exif: btnCopyExif ? btnCopyExif.checked : true
      });
      showToast('Button configuration saved', 'success');
    } catch (err) {
      showToast('Config Error: ' + err.message, 'error');
      loadButtonConfig();
    }
  }

  if (btnCopyToggle) {
    btnCopyToggle.addEventListener('change', (e) => {
      const isEnabled = e.target.checked;
      if (btnCopyOptions) {
        btnCopyOptions.style.opacity = isEnabled ? '1' : '0.3';
        btnCopyOptions.style.pointerEvents = isEnabled ? 'auto' : 'none';
      }
      const statusText = $('btn-copy-status-text');
      if (statusText) {
        statusText.textContent = isEnabled ? 'ENABLED' : 'DISABLED';
        statusText.style.color = isEnabled ? '#2ecc71' : 'inherit';
      }
      saveButtonConfig();
    });
  }

  if (btnCopySave) {
    btnCopySave.addEventListener('click', async (e) => {
      btnCopySave.textContent = 'Saving...';
      await saveButtonConfig(e);
      btnCopySave.textContent = 'Saved!';
      setTimeout(() => { if (btnCopySave) btnCopySave.textContent = '💾 Save Configuration'; }, 2000);
    });
  }

  if (btnCopySrc) btnCopySrc.addEventListener('change', () => saveButtonConfig());
  if (btnCopyExif) btnCopyExif.addEventListener('change', () => saveButtonConfig());
  if (btnCopyDst) {
    btnCopyDst.addEventListener('change', saveButtonConfig);
  }

  loadButtonConfig();

  // --- Folder Selection Integration ---
  ZettEventBus.on('folder_selected', (path) => {
    if (btnCopyDst) {
      btnCopyDst.value = path;
      saveButtonConfig();
    }
  });

  // --- Security Password Management ---
  async function fetchSecurity() {
    try {
      const data = await api.get('/api/security');
      if ($('sec-username')) $('sec-username').value = data.username || '';
      if ($('sec-email')) $('sec-email').value = data.email || '';
      if (data.is_default_password) {
        const warnEl = $('sec-default-pwd-warning');
        if (warnEl) warnEl.style.display = 'block';
      }
    } catch (e) {
      console.warn('Failed to load security info', e);
    }
  }

  fetchSecurity();

  const secSaveBtn = $('sec-save-btn');
  if (secSaveBtn) {
    secSaveBtn.addEventListener('click', async () => {
      const curPwd = $('sec-cur-pwd') ? $('sec-cur-pwd').value : '';
      if (!curPwd) {
        showToast('Current password is required to save changes', 'error');
        return;
      }

      const payload = {
        current_password: curPwd,
        new_password: $('sec-new-pwd') ? $('sec-new-pwd').value : '',
        username: $('sec-username') ? $('sec-username').value : '',
        email: $('sec-email') ? $('sec-email').value : ''
      };

      secSaveBtn.textContent = 'SAVING...';
      try {
        await api.post('/api/security', payload);
        showToast('Security settings updated successfully', 'success');
        if ($('sec-cur-pwd')) $('sec-cur-pwd').value = '';
        if ($('sec-new-pwd')) $('sec-new-pwd').value = '';
        fetchSecurity();

        if (payload.new_password) {
          localStorage.removeItem('zettnas_token');
          setTimeout(() => window.location.reload(), 1000);
        }
      } catch (err) {
        showToast(err.message || 'Failed to update settings', 'error');
      }
      secSaveBtn.textContent = 'SAVE CHANGES';
    });
  }

  const logoutBtn = $('sec-logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      localStorage.removeItem('zettnas_token');
      document.cookie = 'zettnas_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
      window.location.reload();
    });
  }

  // --- Card Minimize / Collapse Toggle ---
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-minimize');
    if (!btn) return;
    const card = btn.closest('.draggable-card');
    if (!card) return;
    card.classList.toggle('card-collapsed');

    const collapsed = [];
    document.querySelectorAll('.draggable-card.card-collapsed').forEach((c) => {
      const id = c.dataset.layoutCardId || c.dataset.ledCardId || c.dataset.fanCardId || c.dataset.btnCardId || c.dataset.miscCardId;
      if (id) collapsed.push(id);
    });
    localStorage.setItem('zettnas_collapsed_cards', JSON.stringify(collapsed));
  });

  try {
    const collapsed = JSON.parse(localStorage.getItem('zettnas_collapsed_cards') || '[]');
    document.querySelectorAll('.draggable-card').forEach((c) => {
      const id = c.dataset.layoutCardId || c.dataset.ledCardId || c.dataset.fanCardId || c.dataset.btnCardId || c.dataset.miscCardId;
      if (id && collapsed.includes(id)) {
        c.classList.add('card-collapsed');
      }
    });
  } catch (e) {}

  // --- Global Keyboard Shortcuts ---
  window.addEventListener('keydown', (e) => {
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    if (activeTag === 'input' || activeTag === 'select' || activeTag === 'textarea') {
      if (e.key === 'Escape') document.activeElement.blur();
      return;
    }

    if (e.key === 'Escape') {
      ZettEventBus.emit('modal:smart:close');
      closeDrawer();
    } else if (e.key === 'y' || e.key === 'Y') {
      applyTheme(state.currentTheme === 'yak' ? 'cyber' : 'yak');
    } else if (e.key === 't' || e.key === 'T' || e.key === 'd' || e.key === 'D') {
      if (drawer && drawer.classList.contains('open')) {
        closeDrawer();
      } else {
        openDrawer();
      }
    }
  });
}
