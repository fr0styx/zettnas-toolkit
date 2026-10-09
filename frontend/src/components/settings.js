/**
 * ZettNAS Toolkit Settings & Preferences Controller
 * Handles settings drawer, tabs, screen backlight, timezone, hardware buttons, card layout locks, and security credentials.
 */
import { api, auth, ApiError } from '../api.js';
import { state, ZOOM_PROFILES } from '../state.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast } from '../toast.js';
import { applyTheme, applyDesktopTheme, applyLcdTheme } from './dashboard.js';
import { applyDashboardLayout, persistDashboardLayout, fitMiniPreviewScale, syncMiniPreviewTelemetry } from './mini-preview.js';
import { fetchAndRenderMetrics } from './metrics-chart.js';
import { t } from '../i18n.js';

const $ = (id) => document.getElementById(id);

export function openDrawer(tabId = null) {
  const drawer = $('led-drawer') || document.querySelector('.slide-drawer');
  const overlay = $('drawer-overlay') || document.querySelector('.drawer-backdrop');
  if (drawer && overlay) {
    drawer.classList.add('open');
    overlay.classList.add('open');
    document.body.classList.add('drawer-is-open');
    if (tabId) {
      const tabBtn = document.querySelector(`.drawer-tab-btn[data-tab="${tabId}"]`);
      if (tabBtn) tabBtn.click();
    }
    setTimeout(() => {
      fitMiniPreviewScale();
      syncMiniPreviewTelemetry();
    }, 100);
  }
}
window.openDrawer = openDrawer;

export function closeDrawer() {
  const drawer = $('led-drawer') || document.querySelector('.slide-drawer');
  const overlay = $('drawer-overlay') || document.querySelector('.drawer-backdrop');
  if (drawer && overlay) {
    drawer.classList.remove('open');
    overlay.classList.remove('open');
    document.body.classList.remove('drawer-is-open');
  }
}
window.closeDrawer = closeDrawer;

export function initSettings() {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) {
    return;
  }

  const toggleBtn = $('drawer-toggle-btn');
  const suiteBtn = $('suite-toolkit-btn') || $('toolkit-suite-btn');
  const closeBtn = $('drawer-close-btn');
  const overlay = $('drawer-overlay') || document.querySelector('.drawer-backdrop');
  const drawer = $('led-drawer') || document.querySelector('.slide-drawer');

  // --- Drawer Tabs Switching ---
  const dynamicTitle = $('drawer-dynamic-title');
  const dynamicDesc = $('drawer-dynamic-desc');
  const tabBtns = document.querySelectorAll('.drawer-tab-btn');
  const tabContents = document.querySelectorAll('.drawer-tab-content');

  function updateDrawerDynamicHeader(targetId) {
    if (!targetId) {
      const activeBtn = document.querySelector('.drawer-tab-btn.active');
      targetId = activeBtn ? activeBtn.dataset.tab : 'tab-layout';
    }
    if (targetId === 'tab-layout') {
      if (dynamicTitle) dynamicTitle.textContent = t('settings.tab_layout_title', 'Dashboard Layout');
      if (dynamicDesc) dynamicDesc.textContent = t('settings.tab_layout_desc', 'Configure dashboard sizes, visibility, and layout presets.');
    } else if (targetId === 'tab-led') {
      if (dynamicTitle) dynamicTitle.textContent = t('settings.tab_led_title', 'LED Strip bar');
      if (dynamicDesc) dynamicDesc.textContent = t('settings.tab_led_desc', 'Adjust physical lighting and reactive hardware alerts.');
    } else if (targetId === 'tab-fans') {
      if (dynamicTitle) dynamicTitle.textContent = t('settings.tab_fans_title', 'Fans');
      if (dynamicDesc) dynamicDesc.textContent = t('settings.tab_fans_desc', 'Configure cooling thresholds and dynamic thermal curves.');
    } else if (targetId === 'tab-buttons') {
      if (dynamicTitle) dynamicTitle.textContent = t('settings.tab_buttons_title', 'Copy Button');
      if (dynamicDesc) dynamicDesc.textContent = t('settings.tab_buttons_desc', 'Assign SD card copy rules to the physical hardware button.');
    }
  }

  tabBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      tabBtns.forEach((b) => b.classList.remove('active'));
      tabContents.forEach((c) => c.classList.remove('active'));
      btn.classList.add('active');
      const targetId = btn.dataset.tab;
      const targetContent = $(targetId);
      if (targetContent) targetContent.classList.add('active');
      updateDrawerDynamicHeader(targetId);
    });
  });

  if (toggleBtn) toggleBtn.addEventListener('click', openDrawer);
  if (suiteBtn) suiteBtn.addEventListener('click', openDrawer);
  if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
  if (overlay) overlay.addEventListener('click', closeDrawer);

  let wheelZoomCooldown = 0;
  window.addEventListener('wheel', (e) => {
    if (e.target.closest('.slide-drawer') || e.target.closest('.smart-modal-window, #console-window') || e.target.closest('#mini-lcd-canvas') || e.target.closest('.file-manager-window, .os-window, .cmd-palette-modal, .mgmt-detail-card')) {
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

  // --- Theme & Color Scheme Controls ---
  initThemeControls();

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

  const tzSelect = $('tz-select') || $('tz-select-input');
  const tzCustomInput = $('tz-custom-input');
  if (tzSelect) {
    if (state.currentTimezone) tzSelect.value = state.currentTimezone;
    tzSelect.addEventListener('change', (e) => {
      const val = e.target.value;
      if (val === 'custom') {
        if (tzCustomInput) {
          tzCustomInput.style.display = 'block';
          tzCustomInput.focus();
        }
      } else {
        if (tzCustomInput) tzCustomInput.style.display = 'none';
        state.currentTimezone = val;
        applyDashboardLayout();
        persistDashboardLayout();
      }
    });
  }

  if (tzCustomInput) {
    let tzTimeout = null;
    tzCustomInput.addEventListener('input', (e) => {
      clearTimeout(tzTimeout);
      tzTimeout = setTimeout(() => {
        if (e.target.value.trim()) {
          state.currentTimezone = e.target.value.trim();
          applyDashboardLayout();
          persistDashboardLayout();
        }
      }, 500);
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
      layoutLockBtn.textContent = isLayoutLocked ? t('settings.btn_locked', '🔒 Locked') : t('settings.btn_reorder', '🔓 Reorder');
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
        if (draggedLayoutCard) draggedLayoutCard.classList.remove('dragging');
        layoutSectionsContainer.querySelectorAll('.draggable-card').forEach((c) => c.classList.remove('drag-over'));
        const order = Array.from(layoutSectionsContainer.querySelectorAll('.draggable-card')).map((c) => c.dataset.layoutCardId);
        localStorage.setItem(LAYOUT_SECTIONS_STORAGE_KEY, JSON.stringify(order));
      });

      card.addEventListener('dragover', (e) => {
        if (isLayoutLocked || !draggedLayoutCard) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const targetCard = e.target.closest('.draggable-card');
        if (targetCard && targetCard !== draggedLayoutCard && targetCard.parentElement === layoutSectionsContainer) {
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
  const screenCarouselSelect = $('screen-carousel-select');
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

    try {
      const lcdData = await api.get('/api/lcd/page');
      if (screenCarouselSelect && lcdData.cycle_seconds !== undefined) {
        screenCarouselSelect.value = String(lcdData.cycle_seconds);
      }
    } catch (e) {
      console.warn('Failed to fetch LCD carousel state', e);
    }
  }

  fetchScreenState();

  if (screenCarouselSelect) {
    screenCarouselSelect.addEventListener('change', async (e) => {
      const secs = parseInt(e.target.value, 10);
      try {
        await api.post('/api/lcd/page', { cycle_seconds: secs });
        showToast(secs > 0 ? `Auto-cycling LCD every ${secs}s` : 'Auto-cycling disabled (manual control)', 'info');
      } catch (err) {
        showToast('Failed to update LCD cycle rate', 'error');
      }
    });
  }

  if (screenBriSlider) {
    screenBriSlider.addEventListener('input', (e) => {
      if (screenBriVal) screenBriVal.textContent = e.target.value + '%';
      clearTimeout(screenDebounce);
      screenDebounce = setTimeout(postScreenState, 100);
    });
    screenBriSlider.addEventListener('change', () => {
      clearTimeout(screenDebounce);
      postScreenState();
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
  const btnCopyAutoIngest = $('btn-copy-auto-ingest');
  const btnCopyRequireConfirm = $('btn-copy-require-confirm');
  const btnCopyCollision = $('btn-copy-collision');
  const btnCopySave = $('btn-copy-save');

  async function loadButtonConfig() {
    try {
      const data = await api.get('/api/buttons');
      if (btnCopyToggle) btnCopyToggle.checked = !!data.enabled;
      if (btnCopySrc) btnCopySrc.value = data.source || 'sd';
      if (btnCopyDst) btnCopyDst.value = data.dest || '/mnt/user/';
      if (btnCopyExif) btnCopyExif.checked = data.use_exif !== false;
      if (btnCopyAutoIngest) btnCopyAutoIngest.checked = !!data.auto_ingest;
      if (btnCopyRequireConfirm) btnCopyRequireConfirm.checked = data.require_confirmation !== false;
      if (btnCopyCollision) btnCopyCollision.value = data.on_collision || 'skip';

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
        use_exif: btnCopyExif ? btnCopyExif.checked : true,
        auto_ingest: btnCopyAutoIngest ? btnCopyAutoIngest.checked : false,
        require_confirmation: btnCopyRequireConfirm ? btnCopyRequireConfirm.checked : true,
        on_collision: btnCopyCollision ? btnCopyCollision.value : 'skip'
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

  const btnMediaRescan = $('btn-media-rescan');
  if (btnMediaRescan) {
    btnMediaRescan.addEventListener('click', async () => {
      btnMediaRescan.textContent = 'Scanning...';
      try {
        await api.post('/api/copy/rescan');
        ZettEventBus.emit('media:slots_rescanned');
        showToast(t('media.scan_complete', 'Media slots rescanned.'), 'info');
      } catch (err) {
        showToast(`Scan failed: ${err.message || err}`, 'error');
      } finally {
        setTimeout(() => { if (btnMediaRescan) btnMediaRescan.textContent = '🔄 Scan'; }, 1000);
      }
    });
  }

  const btnMediaEject = $('btn-media-eject');
  if (btnMediaEject) {
    btnMediaEject.addEventListener('click', async () => {
      const srcSlot = btnCopySrc ? btnCopySrc.value : 'sd';
      try {
        await api.post('/api/copy/eject', { slot: srcSlot });
        ZettEventBus.emit('media:slot_ejected', srcSlot);
        showToast(t('media.ejected', 'Card safely unmounted and ejected. You can now remove it.'), 'info');
      } catch (err) {
        showToast(`Eject failed: ${err.message || err}`, 'error');
      }
    });
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

  const newPwdEl = $('sec-new-pwd');
  const confirmPwdEl = $('sec-confirm-pwd');
  const mismatchMsg = $('sec-pwd-mismatch-msg');

  function checkPwdMatch() {
    if (!newPwdEl || !confirmPwdEl) return;
    const newPwd = newPwdEl.value;
    const confirmPwd = confirmPwdEl.value;

    if (!newPwd && !confirmPwd) {
      if (mismatchMsg) mismatchMsg.style.display = 'none';
      newPwdEl.style.borderColor = 'rgba(255,255,255,0.12)';
      confirmPwdEl.style.borderColor = 'rgba(255,255,255,0.12)';
      return;
    }

    if (confirmPwd.length > 0) {
      if (newPwd !== confirmPwd) {
        if (mismatchMsg) mismatchMsg.style.display = 'flex';
        confirmPwdEl.style.borderColor = 'var(--crit, #ff6b6b)';
      } else {
        if (mismatchMsg) mismatchMsg.style.display = 'none';
        confirmPwdEl.style.borderColor = 'var(--ok2, #10b981)';
      }
    } else {
      if (mismatchMsg) mismatchMsg.style.display = 'none';
      confirmPwdEl.style.borderColor = 'rgba(255,255,255,0.12)';
    }
  }

  if (newPwdEl) newPwdEl.addEventListener('input', checkPwdMatch);
  if (confirmPwdEl) confirmPwdEl.addEventListener('input', checkPwdMatch);

  const secSaveBtn = $('sec-save-btn');
  if (secSaveBtn) {
    secSaveBtn.addEventListener('click', async () => {
      const curPwd = $('sec-cur-pwd') ? $('sec-cur-pwd').value : '';
      if (!curPwd) {
        showToast(t('mgmt.sec_err_cur_pwd_required', 'Current password is required to save changes'), 'error');
        if ($('sec-cur-pwd')) $('sec-cur-pwd').focus();
        return;
      }

      const newPwd = newPwdEl ? newPwdEl.value : '';
      const confirmPwd = confirmPwdEl ? confirmPwdEl.value : '';

      if (newPwd) {
        if (!confirmPwd) {
          showToast(t('mgmt.sec_err_confirm_required', 'Please confirm your new password.'), 'error');
          if (confirmPwdEl) confirmPwdEl.focus();
          return;
        }
        if (newPwd !== confirmPwd) {
          showToast(t('mgmt.sec_err_pwd_mismatch', 'New passwords do not match. Please verify and try again.'), 'error');
          if (mismatchMsg) mismatchMsg.style.display = 'flex';
          if (confirmPwdEl) {
            confirmPwdEl.style.borderColor = 'var(--crit, #ff6b6b)';
            confirmPwdEl.focus();
          }
          return;
        }
        if (newPwd.length < 8) {
          showToast(t('mgmt.sec_err_min_8', 'New password must be at least 8 characters.'), 'error');
          if (newPwdEl) newPwdEl.focus();
          return;
        }
        if (newPwd.toLowerCase() === 'admin') {
          showToast(t('mgmt.sec_err_not_admin', 'Please choose a password other than the default.'), 'error');
          if (newPwdEl) newPwdEl.focus();
          return;
        }
      }

      const payload = {
        current_password: curPwd,
        new_password: newPwd,
        username: $('sec-username') ? $('sec-username').value : '',
        email: $('sec-email') ? $('sec-email').value : ''
      };

      secSaveBtn.textContent = 'SAVING...';
      try {
        await api.post('/api/security', payload);
        showToast(t('mgmt.sec_saved', 'Security settings updated successfully.'), 'success');
        if ($('sec-cur-pwd')) $('sec-cur-pwd').value = '';
        if (newPwdEl) {
          newPwdEl.value = '';
          newPwdEl.style.borderColor = 'rgba(255,255,255,0.12)';
        }
        if (confirmPwdEl) {
          confirmPwdEl.value = '';
          confirmPwdEl.style.borderColor = 'rgba(255,255,255,0.12)';
        }
        if (mismatchMsg) mismatchMsg.style.display = 'none';
        fetchSecurity();

        if (payload.new_password) {
          localStorage.removeItem('zettnas_token');
          setTimeout(() => window.location.reload(), 1000);
        }
      } catch (err) {
        showToast(err.message || 'Failed to update settings', 'error');
      }
      secSaveBtn.textContent = 'SAVE CREDENTIALS';
    });
  }

  const logoutBtn = $('sec-logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
      try { await api.post('/api/auth/logout', {}); } catch (e) { /* session may already be gone */ }
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
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    if (activeTag === 'input' || activeTag === 'select' || activeTag === 'textarea' || document.activeElement?.isContentEditable) {
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

  window.addEventListener('zettnas:lang-changed', () => {
    updateDrawerDynamicHeader();
    if (layoutLockBtn) {
      layoutLockBtn.textContent = isLayoutLocked ? t('settings.btn_locked', '🔒 Locked') : t('settings.btn_reorder', '🔓 Reorder');
    }
    const copySaveBtn = $('btn-copy-save');
    if (copySaveBtn) {
      copySaveBtn.textContent = t('settings.btn_save_config', '💾 Save Configuration');
    }
    syncThemeSettingsUI();
  });
}

let saveLcdDebounce = null;
export async function saveLcdThemeToServer(theme, customAccent, textClarity) {
  clearTimeout(saveLcdDebounce);
  saveLcdDebounce = setTimeout(async () => {
    try {
      await api.post('/api/system/client-preferences', {
        lcd_theme: theme,
        lcd_custom_accent: customAccent || '',
        lcd_text_clarity: textClarity ? 'true' : 'false'
      });
    } catch (e) {
      console.warn('[LCD THEME] Failed syncing LCD theme to server:', e);
    }
  }, 150);
}

let saveDesktopDebounce = null;
export async function saveDesktopThemeToServer(theme, customAccent) {
  clearTimeout(saveDesktopDebounce);
  saveDesktopDebounce = setTimeout(async () => {
    try {
      await api.post('/api/system/client-preferences', {
        desktop_theme: theme,
        desktop_custom_accent: customAccent || ''
      });
    } catch (e) {
      console.warn('[DESKTOP THEME] Failed syncing desktop theme to server:', e);
    }
  }, 150);
}

export async function saveThemeToServer(theme, customAccent, textClarity) {
  saveDesktopThemeToServer(theme, customAccent);
  if (textClarity !== undefined && textClarity !== null) {
    saveLcdThemeToServer(theme, customAccent, textClarity);
  }
}

const THEME_NAMES = {
  cyber: 'CYBER TEAL',
  amber: 'AMBER GOLD',
  emerald: 'EMERALD MATRIX',
  sapphire: 'SAPPHIRE ICE',
  amethyst: 'AMETHYST VIOLET',
  crimson: 'CRIMSON RUBY',
  oled: 'PURE OLED BLACK',
  light: 'DAYLIGHT WHITE',
  yak: 'YAK BRONZE'
};

// --- Desktop Theme Workstation (Mission Control -> Appearance) ---
export function syncDesktopThemeUI() {
  const curTheme = state.desktopTheme || 'cyber';
  const curAccent = state.desktopCustomAccent || '';

  document.querySelectorAll('.desktop-theme-preset').forEach((card) => {
    const isThis = card.dataset.themeId === curTheme;
    card.classList.toggle('active', isThis);
    card.setAttribute('aria-checked', isThis ? 'true' : 'false');
    if (isThis) {
      card.setAttribute('aria-selected', 'true');
    } else {
      card.removeAttribute('aria-selected');
    }
  });

  const badge = $('desktop-theme-active-badge');
  if (badge) {
    const localized = t('settings.theme_' + curTheme, THEME_NAMES[curTheme] || curTheme.toUpperCase());
    badge.textContent = localized.toUpperCase();
    const themeBrandColor = curTheme === 'amber' ? '#ffbe40' : curTheme === 'emerald' ? '#3bf58b' : curTheme === 'sapphire' ? '#38bdf8' : curTheme === 'amethyst' ? '#c084fc' : curTheme === 'crimson' ? '#f43f5e' : curTheme === 'yak' ? '#d48a37' : curTheme === 'oled' ? '#00f0ff' : '#00f0ff';
    badge.style.color = curAccent || themeBrandColor;
    badge.style.borderColor = curAccent || themeBrandColor;
  }

  const picker = $('desktop-custom-color-picker');
  const hexVal = $('desktop-custom-hex-val');
  if (picker && curAccent) {
    picker.value = curAccent;
  }
  if (hexVal) {
    hexVal.textContent = (curAccent || (curTheme === 'amber' ? '#ffbe40' : curTheme === 'emerald' ? '#3bf58b' : curTheme === 'sapphire' ? '#38bdf8' : curTheme === 'amethyst' ? '#c084fc' : curTheme === 'crimson' ? '#fb7185' : curTheme === 'yak' ? '#d48a37' : '#00f0ff')).toUpperCase();
  }

  document.querySelectorAll('.desktop-color-chip').forEach((chip) => {
    chip.classList.toggle('active', chip.dataset.color && chip.dataset.color.toLowerCase() === curAccent.toLowerCase());
  });
}

export function initDesktopThemeControls() {
  const container = $('mgmt-pane-theme');
  if (!container) return;

  const themePresets = Array.from(container.querySelectorAll('.desktop-theme-preset'));
  themePresets.forEach((btn, idx) => {
    btn.addEventListener('click', () => {
      const themeId = btn.dataset.themeId;
      if (!themeId) return;
      applyDesktopTheme(themeId, state.desktopCustomAccent);
      saveDesktopThemeToServer(themeId, state.desktopCustomAccent);
      syncDesktopThemeUI();
    });

    btn.addEventListener('keydown', (e) => {
      let targetBtn = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        targetBtn = themePresets[(idx + 1) % themePresets.length];
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        targetBtn = themePresets[(idx - 1 + themePresets.length) % themePresets.length];
      }
      if (targetBtn) {
        targetBtn.focus();
        targetBtn.click();
      }
    });
  });

  const picker = $('desktop-custom-color-picker');
  if (picker) {
    picker.addEventListener('input', (e) => {
      const hex = e.target.value;
      applyDesktopTheme(state.desktopTheme, hex);
      syncDesktopThemeUI();
    });
    picker.addEventListener('change', (e) => {
      const hex = e.target.value;
      applyDesktopTheme(state.desktopTheme, hex);
      saveDesktopThemeToServer(state.desktopTheme, hex);
      syncDesktopThemeUI();
    });
  }

  container.querySelectorAll('.desktop-color-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const color = chip.dataset.color;
      if (!color) return;
      applyDesktopTheme(state.desktopTheme, color);
      saveDesktopThemeToServer(state.desktopTheme, color);
      syncDesktopThemeUI();
    });
  });

  const resetBtn = $('desktop-theme-reset-accent-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      applyDesktopTheme(state.desktopTheme, '');
      saveDesktopThemeToServer(state.desktopTheme, '');
      syncDesktopThemeUI();
    });
  }

  ZettEventBus.on('desktop_theme:changed', () => {
    syncDesktopThemeUI();
  });

  syncDesktopThemeUI();
}

// --- Simple LCD Screen Themer (Hardware Settings -> Dashboard Layout) ---
export function syncLcdThemeUI() {
  const curTheme = state.lcdTheme || 'cyber';
  const curAccent = state.lcdCustomAccent || '';
  const curClarity = state.lcdTextClarity !== false;

  document.querySelectorAll('.lcd-theme-chip').forEach((chip) => {
    const isThis = chip.dataset.lcdTheme === curTheme;
    chip.classList.toggle('active', isThis);
    if (isThis) {
      chip.setAttribute('aria-selected', 'true');
    } else {
      chip.removeAttribute('aria-selected');
    }
  });

  const badge = $('lcd-theme-active-badge');
  if (badge) {
    const localized = t('settings.theme_' + curTheme, THEME_NAMES[curTheme] || curTheme.toUpperCase());
    badge.textContent = localized.toUpperCase();
    badge.style.color = curAccent || 'var(--brand, #00f0ff)';
    badge.style.borderColor = curAccent || 'var(--brand, #00f0ff)';
  }

  const picker = $('lcd-custom-color-picker');
  const hexVal = $('lcd-custom-hex-val');
  if (picker && curAccent) {
    picker.value = curAccent;
  }
  if (hexVal) {
    hexVal.textContent = (curAccent || (curTheme === 'amber' ? '#ffbe40' : curTheme === 'emerald' ? '#3bf58b' : curTheme === 'sapphire' ? '#38bdf8' : curTheme === 'amethyst' ? '#c084fc' : curTheme === 'crimson' ? '#fb7185' : curTheme === 'yak' ? '#d48a37' : '#00f0ff')).toUpperCase();
  }

  const clarityToggle = $('lcd-text-clarity-toggle');
  if (clarityToggle) {
    clarityToggle.checked = curClarity;
  }
}

export function initLcdThemeControls() {
  const container = $('sec-lcd-theme') || document.querySelector('[data-layout-card-id="sec-lcd-theme"]');
  if (!container) return;

  container.querySelectorAll('.lcd-theme-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      const themeId = btn.dataset.lcdTheme;
      if (!themeId) return;
      applyLcdTheme(themeId, state.lcdCustomAccent, state.lcdTextClarity);
      saveLcdThemeToServer(themeId, state.lcdCustomAccent, state.lcdTextClarity);
      syncLcdThemeUI();
    });
  });

  const picker = $('lcd-custom-color-picker');
  if (picker) {
    picker.addEventListener('input', (e) => {
      const hex = e.target.value;
      applyLcdTheme(state.lcdTheme, hex, state.lcdTextClarity);
      syncLcdThemeUI();
    });
    picker.addEventListener('change', (e) => {
      const hex = e.target.value;
      applyLcdTheme(state.lcdTheme, hex, state.lcdTextClarity);
      saveLcdThemeToServer(state.lcdTheme, hex, state.lcdTextClarity);
      syncLcdThemeUI();
    });
  }

  const resetBtn = $('lcd-reset-accent-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      applyLcdTheme(state.lcdTheme, '', state.lcdTextClarity);
      saveLcdThemeToServer(state.lcdTheme, '', state.lcdTextClarity);
      syncLcdThemeUI();
    });
  }

  const clarityToggle = $('lcd-text-clarity-toggle');
  if (clarityToggle) {
    clarityToggle.addEventListener('change', (e) => {
      const enabled = e.target.checked;
      applyLcdTheme(state.lcdTheme, state.lcdCustomAccent, enabled);
      saveLcdThemeToServer(state.lcdTheme, state.lcdCustomAccent, enabled);
      syncLcdThemeUI();
    });
  }

  ZettEventBus.on('lcd_theme:changed', () => {
    syncLcdThemeUI();
  });

  syncLcdThemeUI();
}

// Backward compatibility alias
export function syncThemeSettingsUI() {
  syncDesktopThemeUI();
  syncLcdThemeUI();
}

export function initThemeControls() {
  initLcdThemeControls();
  initDesktopThemeControls();
}

export function gatherClientPreferences() {
  const prefs = {};
  if (typeof localStorage === 'undefined') return prefs;
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key) continue;
    // Exclude volatile session tokens and temporary caches
    if (key === 'zettnas_token' || key.startsWith('zettnas_weather_cache_') || key.startsWith('zettnas_holiday_cache_')) {
      continue;
    }
    // Capture all ZettNAS desktop configurations, window positions, widgets, dock pinned apps, themes, and layout locks
    if (key.startsWith('zettnas_') || key.startsWith('lcd_')) {
      prefs[key] = localStorage.getItem(key);
    }
  }
  return prefs;
}

export function applyClientPreferences(prefs) {
  if (!prefs || typeof prefs !== 'object' || typeof localStorage === 'undefined') return;
  Object.entries(prefs).forEach(([k, v]) => {
    if (k === 'zettnas_token') return;
    try {
      localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v));
    } catch (e) {
      console.warn('[BACKUP] Failed restoring preference key:', k, e);
    }
  });
}

export async function syncClientPreferencesFromServerIfEmpty() {
  if (typeof localStorage === 'undefined' || typeof window === 'undefined') return;
  // If user has no desktop widgets or theme configured locally, hydrate from server DATA_DIR
  const hasLocal = localStorage.getItem('zettnas_desktop_widgets_config') || localStorage.getItem('lcd_theme');
  if (!hasLocal) {
    try {
      const token = auth.getToken();
      const res = await window.fetch('/api/system/client-preferences', {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      });
      if (res.ok) {
        const data = await res.json();
        if (data.preferences && Object.keys(data.preferences).length > 0) {
          applyClientPreferences(data.preferences);
          if (data.preferences.desktop_theme || data.preferences.desktop_custom_accent !== undefined) {
            applyDesktopTheme(
              data.preferences.desktop_theme || state.desktopTheme,
              data.preferences.desktop_custom_accent !== undefined ? data.preferences.desktop_custom_accent : state.desktopCustomAccent
            );
          }
          if (data.preferences.lcd_theme || data.preferences.lcd_custom_accent !== undefined || data.preferences.lcd_text_clarity !== undefined) {
            applyLcdTheme(
              data.preferences.lcd_theme || state.lcdTheme,
              data.preferences.lcd_custom_accent !== undefined ? data.preferences.lcd_custom_accent : state.lcdCustomAccent,
              data.preferences.lcd_text_clarity !== undefined ? data.preferences.lcd_text_clarity !== 'false' : state.lcdTextClarity
            );
          }
        }
      }
    } catch {
      // Quiet fail if network/auth offline
    }
  }
}

export function initSystemTab() {
  if (typeof renderApiTokens !== 'undefined') renderApiTokens();
  syncClientPreferencesFromServerIfEmpty();
  const btnDownload = document.getElementById('btn-backup-download');
  if (btnDownload) {
    btnDownload.addEventListener('click', async () => {
      const origHtml = btnDownload.innerHTML;
      try {
        btnDownload.disabled = true;
        btnDownload.innerHTML = `<span class="spinner-inline"></span> ${t('settings.generating_backup', 'Generating Backup...')}`;

        // 1. Gather all client settings from localStorage and sync to server
        const prefs = gatherClientPreferences();
        const token = auth.getToken();
        try {
          await window.fetch('/api/system/client-preferences', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { 'Authorization': `Bearer ${token}` } : {})
            },
            body: JSON.stringify(prefs)
          });
        } catch (syncErr) {
          console.warn('[BACKUP] Client preferences pre-backup sync warning:', syncErr);
        }

        // 2. Fetch the backup archive stream
        const res = await window.fetch('/api/system/backup', {
          headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!res.ok) throw await ApiError.from(res);

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;

        const disposition = res.headers.get('content-disposition');
        let filename = `zettnas_backup_${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}.zip`;
        if (disposition && disposition.includes('filename=')) {
          filename = disposition.split('filename=')[1].replace(/["']/g, '').trim();
        }
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
        showToast(t('settings.backup_success', 'Configuration backup downloaded successfully!'), 'success');
      } catch (err) {
        showToast(t('settings.backup_failed', 'Backup generation failed: ') + err.message, 'error');
      } finally {
        btnDownload.disabled = false;
        btnDownload.innerHTML = origHtml;
      }
    });
  }

  const uploadInput = document.getElementById('backup-upload-input');
  if (uploadInput) {
    uploadInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      if (!file.name.endsWith('.zip')) {
        showToast('Please upload a .zip backup file.', 'error');
        uploadInput.value = '';
        return;
      }
      showConfirmToast(
        t('settings.restore_confirm_title', 'Restore Configuration'),
        t('settings.restore_confirm_desc', 'Are you sure you want to restore this configuration? This will restore all hardware settings, fan curves, layouts, widgets, and themes, and reload the interface.'),
        async () => {
          try {
            const token = auth.getToken();
            const res = await window.fetch('/api/system/restore', {
              method: 'POST',
              headers: token ? { 'Authorization': `Bearer ${token}` } : {},
              body: file
            });
            if (!res.ok) throw await ApiError.from(res);
            const data = await res.json();

            // Restore client preferences to browser localStorage if bundled
            if (data.client_preferences && typeof data.client_preferences === 'object') {
              applyClientPreferences(data.client_preferences);
            }

            showToast(t('settings.restore_success', 'Restore successful! Reloading to apply all configurations...'), 'success');
            setTimeout(() => {
              window.location.reload();
            }, 1200);
          } catch (err) {
            showToast(t('settings.restore_failed', 'Restore failed: ') + err.message, 'error');
          } finally {
            uploadInput.value = '';
          }
        }
      );
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initSystemTab();
});


async function renderApiTokens() {
  const list = document.getElementById('api-tokens-list');
  if (!list) return;
  
  try {
    const tokens = await api.get('/api/tokens');
    
    if (tokens.length === 0) {
      list.innerHTML = `<div style="font-size:11px; color:var(--muted); text-align:center;">No API tokens generated.</div>`;
      return;
    }
    
    list.innerHTML = '';
    tokens.forEach(t => {
      const row = document.createElement('div');
      row.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 8px; background: rgba(0,0,0,0.2); border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);';
      row.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:2px;">
          <div style="font-size:11px; font-weight:700; color:#fff;">${t.name}</div>
          <div style="font-size:10px; color:var(--muted); font-family:monospace;">${t.masked_token}</div>
        </div>
        <button class="btn-rect danger" style="padding:4px 8px; font-size:10px;" data-id="${t.id}">Revoke</button>
      `;
      
      row.querySelector('button').addEventListener('click', async () => {
        showConfirmToast('Revoke Token', `Revoke token "${t.name}"?`, async () => {
          try {
            await api.delete(`/api/tokens/${t.id}`);
            renderApiTokens();
          } catch (err) {
            showToast(err.message, 'error');
          }
        });
      });
      list.appendChild(row);
    });
  } catch (err) {
    list.innerHTML = `<div style="font-size:11px; color:var(--crit); text-align:center;">Failed to load tokens</div>`;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const btnGen = document.getElementById('btn-generate-token');
  const inputName = document.getElementById('new-token-name');
  
  if (btnGen && inputName) {
    btnGen.addEventListener('click', async () => {
      const name = inputName.value.trim();
      if (!name) return;
      
      try {
        const res = await api.post('/api/tokens', { name });
        inputName.value = '';
        renderApiTokens();
        
        showConfirmToast('Token Generated', `Your new token is:

${res.token}

Copy it now. You won't be able to see it again!`, () => {});
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }
});
