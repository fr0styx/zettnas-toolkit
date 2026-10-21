/**
 * ZettNAS Toolkit Settings & Preferences Controller
 * Handles settings drawer, tabs, screen backlight, timezone, hardware buttons, card layout locks, and security credentials.
 */
import { api, auth, ApiError, apiFetch } from '../api.js';
import { state, ZOOM_PROFILES } from '../state.js';
import { ZettEventBus } from '../event-bus.js';
import { applyTheme, applyDesktopTheme, applyLcdTheme, setScreenLayoutStyle, hexToRgb, getContrastRatio, syncDesktopTwinPreview } from './dashboard.js';
import { applyDashboardLayout, persistDashboardLayout, fitMiniPreviewScale, syncMiniPreviewTelemetry } from './mini-preview.js';
import { fetchAndRenderMetrics } from './metrics-chart.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';
import { showToast, showActionToast, showPromptToast } from '../toast.js';
import { applyGlassSettings, applyWallpaperReadability } from './wallpapers.js';
import { applyDockSettings } from './dock.js';
import { initGlassTimePickers } from './time-picker.js';

const $ = (id) => document.getElementById(id);

export function restoreHardwareTabsToManagement() {
  const drawer = $('led-drawer') || document.querySelector('.slide-drawer');
  if (drawer && drawer.classList.contains('open')) {
    return;
  }

  const lcdSlot = $('mgmt-pane-hardware-lcd-slot');
  const ledSlot = $('mgmt-pane-hardware-led-slot');
  const fansSlot = $('mgmt-pane-hardware-fans-slot');
  const copySlot = $('mgmt-pane-hardware-copy-slot');

  const tabLayout = $('tab-layout');
  const tabLed = $('tab-led');
  const tabFans = $('tab-fans');
  const tabButtons = $('tab-buttons');

  if (lcdSlot && tabLayout && tabLayout.parentElement !== lcdSlot) {
    lcdSlot.appendChild(tabLayout);
  }
  if (ledSlot && tabLed && tabLed.parentElement !== ledSlot) {
    ledSlot.appendChild(tabLed);
  }
  if (fansSlot && tabFans && tabFans.parentElement !== fansSlot) {
    fansSlot.appendChild(tabFans);
  }
  if (copySlot && tabButtons && tabButtons.parentElement !== copySlot) {
    copySlot.appendChild(tabButtons);
  }
}
window.restoreHardwareTabsToManagement = restoreHardwareTabsToManagement;

export function mountTabsInDrawer(requestedTabId = null) {
  const safeTabId = typeof requestedTabId === 'string' && requestedTabId.trim() ? requestedTabId.trim() : null;
  const drawerContainer = $('drawer-tabs-container') || $('led-drawer') || document.querySelector('.slide-drawer');
  if (!drawerContainer) return;

  const tabLayout = $('tab-layout');
  const tabLed = $('tab-led');
  const tabFans = $('tab-fans');
  const tabButtons = $('tab-buttons');

  if (tabLayout && tabLayout.parentElement !== drawerContainer) {
    drawerContainer.appendChild(tabLayout);
  }
  if (tabLed && tabLed.parentElement !== drawerContainer) {
    drawerContainer.appendChild(tabLed);
  }
  if (tabFans && tabFans.parentElement !== drawerContainer) {
    drawerContainer.appendChild(tabFans);
  }
  if (tabButtons && tabButtons.parentElement !== drawerContainer) {
    drawerContainer.appendChild(tabButtons);
  }

  const activeBtn = document.querySelector('.drawer-tab-btn.active');
  const activeTabId = safeTabId || (activeBtn ? activeBtn.dataset.tab : 'tab-layout');
  [tabLayout, tabLed, tabFans, tabButtons].forEach((t) => {
    if (t) {
      if (t.id === activeTabId) {
        t.classList.add('active');
      } else {
        t.classList.remove('active');
      }
    }
  });
}
window.mountTabsInDrawer = mountTabsInDrawer;

export function openDrawer(tabId = null) {
  const safeTabId = typeof tabId === 'string' && tabId.trim() ? tabId.trim() : null;
  const drawer = $('led-drawer') || document.querySelector('.slide-drawer');
  const overlay = $('drawer-overlay') || document.querySelector('.drawer-backdrop');
  if (drawer && overlay) {
    mountTabsInDrawer(safeTabId);
    drawer.classList.add('open');
    overlay.classList.add('open');
    document.body.classList.add('drawer-is-open');

    const activeBtn = document.querySelector('.drawer-tab-btn.active');
    const targetTabId = safeTabId || (activeBtn ? activeBtn.dataset.tab : 'tab-layout');
    const tabBtn = document.querySelector(`.drawer-tab-btn[data-tab="${targetTabId}"]`);
    if (tabBtn) {
      tabBtn.click();
    } else {
      const targetContent = $(targetTabId);
      if (targetContent) targetContent.classList.add('active');
    }

    setTimeout(() => {
      fitMiniPreviewScale();
      syncMiniPreviewTelemetry();
    }, 100);
  } else if (typeof window.openManagementWindow === 'function') {
    const targetTab = safeTabId || 'tab-layout';
    if (targetTab === 'tab-fans') {
      window.openManagementWindow('mgmt-pane-hardware-fans');
    } else if (targetTab === 'tab-led') {
      window.openManagementWindow('mgmt-pane-hardware-led');
    } else if (targetTab === 'tab-buttons') {
      window.openManagementWindow('mgmt-pane-copy');
    } else if (targetTab === 'tab-layout' && typeof window.openPersonalizationWindow === 'function') {
      window.openPersonalizationWindow('console');
    } else {
      window.openManagementWindow('mgmt-sec-hardware');
    }
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
    restoreHardwareTabsToManagement();
    setTimeout(() => {
      fitMiniPreviewScale();
      syncMiniPreviewTelemetry();
    }, 50);
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
      document.querySelectorAll('.drawer-tab-btn').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.drawer-tab-content').forEach((c) => c.classList.remove('active'));
      btn.classList.add('active');
      const targetId = btn.dataset.tab;
      const targetContent = $(targetId);
      if (targetContent) targetContent.classList.add('active');
      updateDrawerDynamicHeader(targetId);
    });
  });

  if (toggleBtn) toggleBtn.addEventListener('click', () => openDrawer());
  if (suiteBtn) suiteBtn.addEventListener('click', () => openDrawer());
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
  initLcdStyleControls();

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

  // --- Universal Drawer Card Reordering & Locking ---
  const _cardReorderUpdaters = [];

  function setupCardContainerReordering({
    containerId,
    lockBtnId,
    storageOrderKey,
    storageLockKey,
    idAttr,
    ignoredSelectors = [],
  }) {
    const container = $(containerId);
    const lockBtn = $(lockBtnId);
    if (!container) return;

    let isLocked = localStorage.getItem(storageLockKey) !== 'false';

    function setLockState(locked) {
      isLocked = locked;
      localStorage.setItem(storageLockKey, isLocked);
      container.classList.toggle('locked', isLocked);
      if (lockBtn) {
        lockBtn.textContent = isLocked ? t('settings.btn_locked', '🔒 Locked') : t('settings.btn_reorder', '🔓 Reorder');
        lockBtn.classList.toggle('unlocked', !isLocked);
      }
      container.querySelectorAll('.draggable-card').forEach((card) => {
        card.setAttribute('draggable', !isLocked);
      });
    }

    _cardReorderUpdaters.push(() => {
      if (lockBtn) {
        lockBtn.textContent = isLocked ? t('settings.btn_locked', '🔒 Locked') : t('settings.btn_reorder', '🔓 Reorder');
      }
    });

    const savedOrder = JSON.parse(localStorage.getItem(storageOrderKey) || '[]');
    if (savedOrder.length > 0) {
      const cardMap = {};
      container.querySelectorAll('.draggable-card').forEach((c) => {
        const id = c.dataset[idAttr];
        if (id) cardMap[id] = c;
      });
      savedOrder.forEach((id) => {
        if (cardMap[id]) container.appendChild(cardMap[id]);
      });
    }

    let draggedCard = null;
    let allowDrag = false;

    container.addEventListener('mousedown', (e) => {
      for (const sel of ignoredSelectors) {
        if (e.target.closest(sel)) {
          allowDrag = false;
          return;
        }
      }
      allowDrag = !isLocked && !!e.target.closest('.drag-handle');
    });

    container.querySelectorAll('.draggable-card').forEach((card) => {
      card.addEventListener('dragstart', (e) => {
        if (isLocked || !allowDrag) { e.preventDefault(); return false; }
        draggedCard = card;
        card.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        const cardId = card.dataset[idAttr] || '';
        e.dataTransfer.setData('text/plain', cardId);
      });

      card.addEventListener('dragend', () => {
        allowDrag = false;
        if (draggedCard) draggedCard.classList.remove('dragging');
        container.querySelectorAll('.draggable-card').forEach((c) => c.classList.remove('drag-over'));
        const order = Array.from(container.querySelectorAll('.draggable-card'))
          .map((c) => c.dataset[idAttr])
          .filter(Boolean);
        localStorage.setItem(storageOrderKey, JSON.stringify(order));
      });

      card.addEventListener('dragover', (e) => {
        if (isLocked || !draggedCard) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const targetCard = e.target.closest('.draggable-card');
        if (targetCard && targetCard !== draggedCard && targetCard.parentElement === container) {
          const rect = targetCard.getBoundingClientRect();
          const next = (e.clientY - rect.top) / (rect.bottom - rect.top) > 0.5;
          container.insertBefore(draggedCard, (next && targetCard.nextSibling) || targetCard);
        }
      });
    });

    if (lockBtn) lockBtn.addEventListener('click', () => setLockState(!isLocked));
    setLockState(isLocked);
  }

  // 1. Dashboard Layout Cards
  setupCardContainerReordering({
    containerId: 'layout-sections-container',
    lockBtnId: 'layout-cards-lock-btn',
    storageOrderKey: 'lcd_dash_card_order',
    storageLockKey: 'lcd_dash_cards_locked',
    idAttr: 'layoutCardId',
    ignoredSelectors: ['#mini-lcd-canvas', '.dash-reorder-flow'],
  });

  // 2. LED Strip Bar Cards
  setupCardContainerReordering({
    containerId: 'drawer-cards-container',
    lockBtnId: 'drawer-lock-btn',
    storageOrderKey: 'lcd_led_card_order',
    storageLockKey: 'lcd_led_cards_locked',
    idAttr: 'cardId',
  });

  // 3. Fans Control Cards
  setupCardContainerReordering({
    containerId: 'fan-cards-container',
    lockBtnId: 'fan-cards-lock-btn',
    storageOrderKey: 'lcd_fans_card_order',
    storageLockKey: 'lcd_fans_cards_locked',
    idAttr: 'fanCardId',
  });

  // 4. Front Panel COPY Button Cards
  setupCardContainerReordering({
    containerId: 'btn-sections-container',
    lockBtnId: 'btn-cards-lock-btn',
    storageOrderKey: 'lcd_copy_card_order',
    storageLockKey: 'lcd_copy_cards_locked',
    idAttr: 'btnCardId',
  });

  // --- Screen Backlight & Night Dimming ---
  const screenBriSlider = $('screen-bri-slider');
  const screenBriVal = $('screen-bri-val');
  const screenPowerBtn = $('btn-toggle-screen-power');
  const screenNightToggle = $('screen-night-toggle');
  const screenNightStart = $('screen-night-start');
  const screenNightEnd = $('screen-night-end');
  const screenNightBri = $('screen-night-bri');
  const screenCarouselSelect = $('screen-carousel-select');
  let screenDebounce = null;
  let screenPower = true;
  let lastNonZeroBrightness = 100;

  function updateScreenPowerUI() {
    const bri = parseInt(screenBriSlider ? screenBriSlider.value : 100, 10);
    if (bri > 0) {
      lastNonZeroBrightness = bri;
    }
    const isOff = !screenPower || bri <= 0;
    if (screenBriVal) {
      screenBriVal.textContent = isOff ? 'OFF' : `${bri}%`;
      screenBriVal.style.color = isOff ? 'var(--muted)' : '';
    }
    if (screenPowerBtn) {
      const lblOn = t('settings.screen_turn_on');
      const lblOff = t('settings.screen_turn_off');
      screenPowerBtn.textContent = isOff
        ? (lblOn !== 'settings.screen_turn_on' ? lblOn : 'Turn On')
        : (lblOff !== 'settings.screen_turn_off' ? lblOff : 'Turn Off');
      screenPowerBtn.style.borderColor = isOff ? 'rgba(37, 194, 160, 0.5)' : '';
      screenPowerBtn.style.color = isOff ? 'var(--ok2, #25c2a0)' : '';
    }
    if (screenBriSlider) {
      screenBriSlider.style.opacity = isOff ? '0.45' : '1';
    }
    const badge = $('lcd-renderer-badge');
    if (badge && !badge.textContent.includes('NO /dev/fb0') && !badge.textContent.includes('DISABLED')) {
      if (isOff) {
        badge.textContent = 'LCD: SCREEN OFF';
        badge.className = 'lcd-status-badge lcd-status-disabled';
        badge.title = 'Physical LCD display is turned off (0 FPS).';
      } else {
        badge.textContent = 'LCD: 10 FPS ACTIVE';
        badge.className = 'lcd-status-badge lcd-status-active';
        badge.title = 'LCD direct output is actively streaming.';
      }
    }
  }

  async function postScreenState() {
    const bri = parseInt(screenBriSlider ? screenBriSlider.value : 100, 10);
    const payload = {
      power: screenPower && bri > 0,
      brightness: bri,
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
      if (data.power !== undefined) {
        screenPower = data.power !== false && data.power !== 'off';
      }
      if (screenBriSlider && data.brightness !== undefined) {
        screenBriSlider.value = data.brightness;
        if (data.brightness > 0) lastNonZeroBrightness = data.brightness;
      }
      if (screenNightToggle) screenNightToggle.checked = Boolean(data.night_mode);
      if (screenNightStart && data.night_start) screenNightStart.value = data.night_start;
      if (screenNightEnd && data.night_end) screenNightEnd.value = data.night_end;
      initGlassTimePickers($('tab-layout') || document);
      if (screenNightBri && data.night_brightness !== undefined) screenNightBri.value = data.night_brightness;
      updateScreenPowerUI();
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

  if (screenPowerBtn) {
    screenPowerBtn.addEventListener('click', async () => {
      const bri = parseInt(screenBriSlider ? screenBriSlider.value : 100, 10);
      const currentlyOff = !screenPower || bri <= 0;
      if (currentlyOff) {
        screenPower = true;
        if (screenBriSlider && bri <= 0) {
          screenBriSlider.value = String(lastNonZeroBrightness || 100);
        }
      } else {
        screenPower = false;
      }
      updateScreenPowerUI();
      await postScreenState();
      showToast(screenPower ? 'Physical LCD screen turned on' : 'Physical LCD screen turned off', 'info');
    });
  }

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
      const val = parseInt(e.target.value, 10);
      screenPower = val > 0;
      updateScreenPowerUI();
      clearTimeout(screenDebounce);
      screenDebounce = setTimeout(postScreenState, 100);
    });
    screenBriSlider.addEventListener('change', (e) => {
      const val = parseInt(e.target.value, 10);
      screenPower = val > 0;
      updateScreenPowerUI();
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
        action: 'copy',
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

  const btnMediaCopyNow = $('btn-media-copy-now');
  if (btnMediaCopyNow) {
    btnMediaCopyNow.addEventListener('click', async () => {
      const srcSlot = btnCopySrc ? btnCopySrc.value : 'sd';
      const dstPath = btnCopyDst ? btnCopyDst.value : '/mnt/user/';
      btnMediaCopyNow.disabled = true;
      const origText = btnMediaCopyNow.textContent;
      btnMediaCopyNow.textContent = 'Starting...';
      try {
        await api.post('/api/copy/start', {
          source: srcSlot,
          dest: dstPath,
          use_exif: btnCopyExif ? btnCopyExif.checked : true,
        });
        showToast(t('media.copy_started', 'Starting ingest from media slot...'), 'success');
      } catch (err) {
        showToast(`Copy failed: ${err.message || err}`, 'error');
      } finally {
        setTimeout(() => {
          if (btnMediaCopyNow) {
            btnMediaCopyNow.disabled = false;
            btnMediaCopyNow.textContent = origText;
          }
        }, 1500);
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

  async function fetchSecurityAdvisor() {
    try {
      const adv = await api.get('/api/security/advisor');
      const scoreBadge = $('sec-advisor-score-badge');
      if (scoreBadge) {
        scoreBadge.textContent = `Score: ${adv.score}/100`;
        if (adv.score >= 90) {
          scoreBadge.style.color = 'var(--ok2, #25c2a0)';
          scoreBadge.style.borderColor = 'rgba(37,194,160,0.4)';
          scoreBadge.style.background = 'rgba(37,194,160,0.15)';
        } else if (adv.score >= 70) {
          scoreBadge.style.color = 'var(--warn, #f5a623)';
          scoreBadge.style.borderColor = 'rgba(245,166,35,0.4)';
          scoreBadge.style.background = 'rgba(245,166,35,0.15)';
        } else {
          scoreBadge.style.color = 'var(--crit, #ff5c5c)';
          scoreBadge.style.borderColor = 'rgba(255,92,92,0.4)';
          scoreBadge.style.background = 'rgba(255,92,92,0.15)';
        }
      }

      const itemsEl = $('sec-advisor-items');
      if (itemsEl && Array.isArray(adv.checks)) {
        itemsEl.innerHTML = adv.checks.map((chk) => {
          const icon = chk.status === 'pass' ? '✅' : (chk.status === 'fail' ? '❌' : (chk.status === 'warn' ? '⚠️' : 'ℹ️'));
          const color = chk.status === 'pass' ? 'var(--ok2, #25c2a0)' : (chk.status === 'fail' ? 'var(--crit, #ff5c5c)' : 'var(--warn, #f5a623)');
          const isPass = chk.status === 'pass';
          const actionText = isPass ? t('sec.action_review', 'Review ➔') : t('sec.action_configure', 'Configure ➔');
          return `
            <div class="sec-advisor-item ${isPass ? 'passed' : 'needs-action'}" data-check-id="${escapeHtml(chk.id)}" role="button" tabindex="0" title="${t('sec.click_to_configure', 'Click to configure')}" style="padding: 7px 10px; background: ${isPass ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)'}; border: 1px solid ${isPass ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.3)'}; border-radius: 6px;">
              <div style="display:flex; align-items:center; gap:8px; flex:1; min-width:0;">
                <span>${icon}</span>
                <div style="min-width:0;">
                  <span style="font-weight:600; color:#fff; font-size:11.5px;">${escapeHtml(chk.title)}: </span>
                  <span style="color:${color}; font-size:10.5px;">${escapeHtml(chk.message)}</span>
                </div>
              </div>
              <span class="sec-advisor-action-pill">${actionText}</span>
            </div>
          `;
        }).join('');

        itemsEl.querySelectorAll('.sec-advisor-item').forEach(item => {
          const checkId = item.dataset.checkId;
          const trigger = () => {
            if (typeof window.handleSecurityAdvisorClick === 'function') {
              window.handleSecurityAdvisorClick(checkId);
            }
          };
          item.addEventListener('click', trigger);
          item.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              trigger();
            }
          });
        });
      }

      const disableAdminCont = $('sec-disable-admin-container');
      const disableAdminBtn = $('btn-disable-default-admin');
      if (disableAdminCont && disableAdminBtn) {
        if (!adv.admin_is_disabled) {
          disableAdminCont.style.display = 'block';
          const canDisable = adv.active_superadmins_count >= 2;
          disableAdminBtn.disabled = !canDisable;
          disableAdminBtn.style.opacity = canDisable ? '1' : '0.5';
          disableAdminBtn.style.cursor = canDisable ? 'pointer' : 'not-allowed';
          if (!canDisable) {
            disableAdminBtn.title = t('sec.disable_admin_need_superadmin', "Create another active SuperAdmin account first before disabling 'admin'.");
          } else {
            disableAdminBtn.title = t('sec.disable_admin_btn', "Disable Default Admin");
          }
        } else {
          disableAdminCont.style.display = 'none';
        }
      }
    } catch (e) {
      console.warn('Failed to load security advisor', e);
    }
  }

  const disableAdminBtn = $('btn-disable-default-admin');
  if (disableAdminBtn && !disableAdminBtn.dataset.bound) {
    disableAdminBtn.dataset.bound = 'true';
    disableAdminBtn.addEventListener('click', () => {
      const confirmMsg = t('sec.disable_admin_confirm', "Are you sure you want to disable the default 'admin' account? You must use an alternative SuperAdmin to manage this server.");
      showConfirmToast(t('common.confirm', 'Confirm Action'), confirmMsg, async () => {
        try {
          const res = await api.post('/api/users/admin/disable', {});
          showToast(t('sec.disable_admin_success', "Default admin account has been disabled."), 'success');
          if (res.is_self) {
            setTimeout(() => {
              window.location.href = '/login';
            }, 1200);
          } else {
            fetchSecurity();
            fetchSecurityAdvisor();
          }
        } catch (err) {
          showToast(err.message, 'error');
        }
      });
    });
  }

  fetchSecurity();
  fetchSecurityAdvisor();

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
          localStorage.removeItem('zettnas_signed_in');
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
          localStorage.removeItem('zettnas_signed_in');
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
    const consoleWin = document.getElementById('vm-console-window');
    const isConsoleActive = consoleWin && !consoleWin.classList.contains('window-minimized') && consoleWin.style.display !== 'none' && (consoleWin.dataset.focused === 'true' || consoleWin.contains(document.activeElement));
    if (activeTag === 'input' || activeTag === 'select' || activeTag === 'textarea' || document.activeElement?.isContentEditable || isConsoleActive) {
      if (e.key === 'Escape' && activeTag !== 'canvas') document.activeElement?.blur?.();
      return;
    }

    if (e.key === 'Escape') {
      ZettEventBus.emit('modal:smart:close');
      closeDrawer();
    } else if (e.key === 'y' || e.key === 'Y') {
      applyTheme(state.currentTheme === 'yak' ? 'cyber' : 'yak');
    } else if (e.key === 't' || e.key === 'T' || e.key === 'd' || e.key === 'D') {
      if (toggleBtn && (toggleBtn.classList.contains('hidden') || toggleBtn.style.display === 'none')) {
        return;
      }
      if (drawer && drawer.classList.contains('open')) {
        closeDrawer();
      } else {
        openDrawer();
      }
    }
  });

  window.addEventListener('zettnas:lang-changed', () => {
    updateDrawerDynamicHeader();
    _cardReorderUpdaters.forEach((fn) => fn());
    const copySaveBtn = $('btn-copy-save');
    if (copySaveBtn) {
      copySaveBtn.textContent = t('settings.btn_save_config', '💾 Save Configuration');
    }
    syncThemeSettingsUI();
  });

  restoreHardwareTabsToManagement();
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
  const currentAccentOrBrand = curAccent || (curTheme === 'amber' ? '#ffbe40' : curTheme === 'emerald' ? '#3bf58b' : curTheme === 'sapphire' ? '#38bdf8' : curTheme === 'amethyst' ? '#c084fc' : curTheme === 'crimson' ? '#fb7185' : curTheme === 'yak' ? '#d48a37' : '#00f0ff');
  if (hexVal) {
    hexVal.textContent = currentAccentOrBrand.toUpperCase();
  }

  // Live WCAG 2.2 AA Contrast Badge calculation against active dark card surface
  const contrastBadge = $('desktop-contrast-badge');
  if (contrastBadge) {
    const rgb = hexToRgb(currentAccentOrBrand);
    const bg = curTheme === 'oled' ? [0, 0, 0] : [15, 23, 42];
    const ratio = rgb ? getContrastRatio(rgb, bg) : 4.5;
    if (ratio >= 7.0) {
      contrastBadge.textContent = 'AAA PASS';
      contrastBadge.style.background = 'rgba(34, 197, 94, 0.2)';
      contrastBadge.style.color = '#22c55e';
      contrastBadge.style.borderColor = 'rgba(34, 197, 94, 0.4)';
    } else if (ratio >= 4.5) {
      contrastBadge.textContent = 'AA PASS';
      contrastBadge.style.background = 'rgba(34, 197, 94, 0.15)';
      contrastBadge.style.color = '#22c55e';
      contrastBadge.style.borderColor = 'rgba(34, 197, 94, 0.35)';
    } else {
      contrastBadge.textContent = 'LOW (' + ratio.toFixed(1) + ':1)';
      contrastBadge.style.background = 'rgba(239, 68, 68, 0.15)';
      contrastBadge.style.color = '#ef4444';
      contrastBadge.style.borderColor = 'rgba(239, 68, 68, 0.35)';
    }
  }

  document.querySelectorAll('.desktop-color-chip').forEach((chip) => {
    chip.classList.toggle('active', chip.dataset.color && chip.dataset.color.toLowerCase() === curAccent.toLowerCase());
  });
}

export function renderExtractedChips(colors) {
  const container = $('wallpaper-extracted-chips');
  if (!container) return;
  container.innerHTML = '';
  colors.forEach(hex => {
    const btn = document.createElement('button');
    btn.className = 'desktop-color-chip color-chip-btn';
    btn.dataset.color = hex;
    btn.style.background = hex;
    btn.title = `Extracted: ${hex.toUpperCase()}`;
    if (state.desktopCustomAccent && state.desktopCustomAccent.toLowerCase() === hex.toLowerCase()) {
      btn.classList.add('active');
    }
    btn.addEventListener('click', () => {
      applyDesktopTheme(state.desktopTheme, hex);
      saveDesktopThemeToServer(state.desktopTheme, hex);
      syncDesktopThemeUI();
      container.querySelectorAll('.desktop-color-chip').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
    });
    container.appendChild(btn);
  });
}

export async function sampleWallpaperPalette() {
  const container = $('wallpaper-extracted-chips');
  if (!container) return;

  let imgUrl = null;
  const wpLayer = document.getElementById('desktop-wallpaper');
  if (wpLayer && wpLayer.style.backgroundImage) {
    const match = wpLayer.style.backgroundImage.match(/url\(["']?([^"']+)["']?\)/);
    if (match) imgUrl = match[1];
  }
  if (!imgUrl && typeof localStorage !== 'undefined') {
    const savedName = localStorage.getItem('zettnas_active_wallpaper');
    if (savedName) {
      imgUrl = `/api/wallpapers/download/${encodeURIComponent(savedName)}`;
    }
  }

  if (!imgUrl) {
    const fallbackPalette = ['#00f0ff', '#38bdf8', '#3bf58b', '#ffbe40', '#c084fc', '#f43f5e'];
    renderExtractedChips(fallbackPalette);
    showToast(t('settings.palette_sampled_default', 'Sampled default theme accents'), 'info');
    return;
  }

  try {
    container.innerHTML = `<span style="font-size:10.5px; color:var(--brand); display:flex; align-items:center; gap:6px;"><span class="spinner-inline" style="width:12px; height:12px; border-width:2px;"></span> Sampling wallpaper pixels...</span>`;

    const img = new Image();
    img.crossOrigin = 'Anonymous';
    img.src = imgUrl;
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      setTimeout(resolve, 2500);
    });

    if (!img.naturalWidth) {
      throw new Error('Image could not be rendered to canvas');
    }

    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) throw new Error('Canvas 2D context unavailable');

    ctx.drawImage(img, 0, 0, 64, 64);
    const imgData = ctx.getImageData(0, 0, 64, 64).data;

    const colorMap = new Map();
    for (let i = 0; i < imgData.length; i += 16) {
      const r = imgData[i];
      const g = imgData[i + 1];
      const b = imgData[i + 2];
      const a = imgData[i + 3];
      if (a < 128) continue;

      const qr = Math.round(r / 32) * 32;
      const qg = Math.round(g / 32) * 32;
      const qb = Math.round(b / 32) * 32;

      const maxVal = Math.max(qr, qg, qb);
      const minVal = Math.min(qr, qg, qb);
      const sat = maxVal === 0 ? 0 : (maxVal - minVal) / maxVal;
      const lum = 0.2126 * (qr / 255) + 0.7152 * (qg / 255) + 0.0722 * (qb / 255);

      if (lum < 0.15 || lum > 0.85 || sat < 0.2) continue;

      const hex = '#' + [qr, qg, qb].map(x => Math.min(255, Math.max(0, x)).toString(16).padStart(2, '0')).join('');
      colorMap.set(hex, (colorMap.get(hex) || 0) + 1);
    }

    let sorted = Array.from(colorMap.entries()).sort((a, b) => b[1] - a[1]).map(entry => entry[0]);
    if (sorted.length < 5) {
      const fillers = ['#00f0ff', '#38bdf8', '#3bf58b', '#ffbe40', '#c084fc', '#f43f5e'];
      for (const f of fillers) {
        if (!sorted.includes(f)) sorted.push(f);
        if (sorted.length >= 6) break;
      }
    } else {
      sorted = sorted.slice(0, 6);
    }

    renderExtractedChips(sorted);
    showToast(t('settings.palette_extracted_success', 'Extracted 6 vibrant wallpaper accents!'), 'success');
  } catch (err) {
    console.warn('[PALETTE] Extraction fallback:', err);
    const fallbackPalette = ['#00f0ff', '#38bdf8', '#3bf58b', '#ffbe40', '#c084fc', '#f43f5e'];
    renderExtractedChips(fallbackPalette);
    showToast(t('settings.palette_sampled_default', 'Sampled default theme accents'), 'info');
  }
}

let _appearanceUndoSnapshot = null;
let _appearanceUndoTimer = null;

export function exportThemeBundle() {
  let savedBlur = 24, savedOpacity = 72, savedRadius = '12px', savedGlow = false;
  let savedDim = 15, savedBlurWp = 0;
  let savedDockPos = 'bottom', savedDockSize = 'medium', savedDockMag = 1.4, savedDockAutoHide = false;
  let savedEco = false;

  try {
    if (localStorage.getItem('zettnas_glass_blur') !== null) savedBlur = parseInt(localStorage.getItem('zettnas_glass_blur'), 10);
    if (localStorage.getItem('zettnas_glass_opacity') !== null) savedOpacity = parseInt(localStorage.getItem('zettnas_glass_opacity'), 10);
    if (localStorage.getItem('zettnas_window_radius')) savedRadius = localStorage.getItem('zettnas_window_radius');
    if (localStorage.getItem('zettnas_window_glow') !== null) savedGlow = localStorage.getItem('zettnas_window_glow') === 'true';

    if (localStorage.getItem('zettnas_wallpaper_dim') !== null) savedDim = parseInt(localStorage.getItem('zettnas_wallpaper_dim'), 10);
    if (localStorage.getItem('zettnas_wallpaper_blur') !== null) savedBlurWp = parseInt(localStorage.getItem('zettnas_wallpaper_blur'), 10);

    if (localStorage.getItem('zettnas_dock_position')) savedDockPos = localStorage.getItem('zettnas_dock_position');
    if (localStorage.getItem('zettnas_dock_size')) savedDockSize = localStorage.getItem('zettnas_dock_size');
    if (localStorage.getItem('zettnas_dock_magnification') !== null) savedDockMag = parseFloat(localStorage.getItem('zettnas_dock_magnification'));
    if (localStorage.getItem('zettnas_dock_autohide') !== null) savedDockAutoHide = localStorage.getItem('zettnas_dock_autohide') === 'true';

    if (localStorage.getItem('zettnas_eco_mode') !== null) savedEco = localStorage.getItem('zettnas_eco_mode') === 'true';
  } catch (e) {}

  const bundle = {
    app: 'zettnas-toolkit',
    format: 'zett-theme',
    version: 1,
    exported_at: new Date().toISOString(),
    theme: state.desktopTheme || 'cyber',
    custom_accent: state.desktopCustomAccent || '',
    glass: {
      blur: savedBlur,
      opacity: savedOpacity,
      radius: savedRadius,
      glow: savedGlow
    },
    wallpaper: {
      active_file: (typeof localStorage !== 'undefined' ? localStorage.getItem('zettnas_active_wallpaper') : null) || null,
      dim: savedDim,
      blur: savedBlurWp
    },
    dock: {
      position: savedDockPos,
      size: savedDockSize,
      magnification: savedDockMag,
      autohide: savedDockAutoHide
    },
    performance: {
      eco_mode: savedEco
    }
  };

  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `zettnas-theme-${state.desktopTheme || 'cyber'}-${Date.now().toString(36)}.zett-theme.json`;
  document.body.appendChild(a);
  a.click();
  URL.revokeObjectURL(url);
  a.remove();
  showToast(t('settings.theme_exported', 'Theme exported successfully!'), 'success');
}

export function importThemeBundle(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result);
      if (!data || (data.format !== 'zett-theme' && !data.theme)) {
        throw new Error('Invalid theme file format. Expected a .zett-theme.json bundle.');
      }

      // Snapshot current state for undo
      takeAppearanceSnapshot();

      // Apply theme
      const targetTheme = data.theme || 'cyber';
      const targetAccent = data.custom_accent !== undefined ? data.custom_accent : '';
      applyDesktopTheme(targetTheme, targetAccent);
      saveDesktopThemeToServer(targetTheme, targetAccent);

      // Apply glass
      if (data.glass) {
        applyGlassSettings(data.glass.blur ?? 24, data.glass.opacity ?? 72, data.glass.radius ?? '12px', data.glass.glow ?? false, true);
      }

      // Apply wallpaper readability
      if (data.wallpaper) {
        applyWallpaperReadability(data.wallpaper.dim ?? 15, data.wallpaper.blur ?? 0, true);
      }

      // Apply dock settings
      if (data.dock) {
        applyDockSettings(data.dock.position || 'bottom', data.dock.size || 'medium', data.dock.magnification ?? 1.4, data.dock.autohide ?? false, true);
      }

      // Apply eco mode
      if (data.performance) {
        const isEco = !!data.performance.eco_mode;
        if (isEco) document.body.setAttribute('data-performance-mode', 'eco');
        else document.body.removeAttribute('data-performance-mode');
        try { localStorage.setItem('zettnas_eco_mode', isEco ? 'true' : 'false'); } catch (err) {}
        const ecoToggle = document.getElementById('eco-mode-toggle');
        if (ecoToggle) ecoToggle.checked = isEco;
      }

      syncDesktopThemeUI();
      if (typeof window.syncDesktopTwinPreview === 'function') {
        window.syncDesktopTwinPreview({ theme: targetTheme, accent: targetAccent });
      }

      showToast(t('settings.theme_imported', 'Theme imported successfully!'), 'success');
    } catch (err) {
      showToast(t('settings.theme_import_failed', 'Failed to import theme: ') + err.message, 'error');
    }
  };
  reader.readAsText(file);
}

function takeAppearanceSnapshot() {
  try {
    _appearanceUndoSnapshot = {
      theme: state.desktopTheme || 'cyber',
      customAccent: state.desktopCustomAccent || '',
      glassBlur: localStorage.getItem('zettnas_glass_blur'),
      glassOpacity: localStorage.getItem('zettnas_glass_opacity'),
      windowRadius: localStorage.getItem('zettnas_window_radius'),
      windowGlow: localStorage.getItem('zettnas_window_glow'),
      wallpaperDim: localStorage.getItem('zettnas_wallpaper_dim'),
      wallpaperBlur: localStorage.getItem('zettnas_wallpaper_blur'),
      wallpaperFile: localStorage.getItem('zettnas_active_wallpaper'),
      dockPos: localStorage.getItem('zettnas_dock_position'),
      dockSize: localStorage.getItem('zettnas_dock_size'),
      dockMag: localStorage.getItem('zettnas_dock_magnification'),
      dockAutoHide: localStorage.getItem('zettnas_dock_autohide'),
      ecoMode: localStorage.getItem('zettnas_eco_mode')
    };
  } catch (e) {}
}

export function restoreAppearanceDefaultsWithUndo() {
  takeAppearanceSnapshot();

  // 1. Reset theme to cyber
  applyDesktopTheme('cyber', '');
  saveDesktopThemeToServer('cyber', '');

  // 2. Reset glass
  applyGlassSettings(24, 72, '12px', false, true);

  // 3. Reset wallpaper readability
  applyWallpaperReadability(15, 0, true);

  // 4. Reset dock
  applyDockSettings('bottom', 'medium', 1.4, false, true);

  // 5. Reset eco mode
  document.body.removeAttribute('data-performance-mode');
  try { localStorage.removeItem('zettnas_eco_mode'); } catch (err) {}
  const ecoToggle = document.getElementById('eco-mode-toggle');
  if (ecoToggle) ecoToggle.checked = false;

  syncDesktopThemeUI();
  if (typeof window.syncDesktopTwinPreview === 'function') {
    window.syncDesktopTwinPreview({ theme: 'cyber', accent: '', wallpaperDim: 15, wallpaperBlur: 0, dockPos: 'bottom' });
  }

  // Show 10s undo toast
  clearTimeout(_appearanceUndoTimer);
  showActionToast('Appearance reset to factory defaults', '↺ Undo (10s)', () => {
    if (!_appearanceUndoSnapshot) return;
    const snap = _appearanceUndoSnapshot;
    applyDesktopTheme(snap.theme, snap.customAccent);
    saveDesktopThemeToServer(snap.theme, snap.customAccent);

    applyGlassSettings(
      snap.glassBlur !== null ? parseInt(snap.glassBlur, 10) : 24,
      snap.glassOpacity !== null ? parseInt(snap.glassOpacity, 10) : 72,
      snap.windowRadius || '12px',
      snap.windowGlow === 'true',
      true
    );

    applyWallpaperReadability(
      snap.wallpaperDim !== null ? parseInt(snap.wallpaperDim, 10) : 15,
      snap.wallpaperBlur !== null ? parseInt(snap.wallpaperBlur, 10) : 0,
      true
    );

    applyDockSettings(
      snap.dockPos || 'bottom',
      snap.dockSize || 'medium',
      snap.dockMag !== null ? parseFloat(snap.dockMag) : 1.4,
      snap.dockAutoHide === 'true',
      true
    );

    if (snap.ecoMode === 'true') {
      document.body.setAttribute('data-performance-mode', 'eco');
      try { localStorage.setItem('zettnas_eco_mode', 'true'); } catch (e) {}
      if (ecoToggle) ecoToggle.checked = true;
    }
    syncDesktopThemeUI();
    showToast(t('settings.theme_restored', 'Appearance settings restored!'), 'success');
  }, 10000);
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

  // Hook Palette Extractor
  const extractBtn = $('extract-palette-btn');
  if (extractBtn) {
    extractBtn.addEventListener('click', () => {
      sampleWallpaperPalette();
    });
  }

  // Hook Theme Export
  const exportBtn = $('theme-export-btn');
  if (exportBtn) {
    exportBtn.addEventListener('click', () => {
      exportThemeBundle();
    });
  }

  // Hook Theme Import
  const importBtn = $('theme-import-btn');
  const importFileInput = $('theme-import-file');
  if (importBtn && importFileInput) {
    importBtn.addEventListener('click', () => {
      importFileInput.click();
    });
    importFileInput.addEventListener('change', (e) => {
      const file = e.target.files && e.target.files[0];
      if (file) {
        importThemeBundle(file);
        importFileInput.value = '';
      }
    });
  }

  // Hook Restore Defaults with Undo
  const resetAllBtn = $('theme-reset-all-btn');
  if (resetAllBtn) {
    resetAllBtn.addEventListener('click', () => {
      restoreAppearanceDefaultsWithUndo();
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

export function syncLcdStyleUI() {
  const container = $('sec-lcd-style') || document.querySelector('[data-layout-card-id="sec-lcd-style"]');
  if (!container) return;
  const curStyle = state.screenLayoutStyle || 'classic';
  container.querySelectorAll('.lcd-style-chip').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.screenStyle === curStyle);
  });
  const badge = $('lcd-style-active-badge');
  if (badge) {
    if (curStyle === 'streamline') {
      badge.textContent = 'STREAMLINE BIG IP';
    } else {
      badge.textContent = 'CLASSIC CARDS';
    }
  }
}

export function initLcdStyleControls() {
  const container = $('sec-lcd-style') || document.querySelector('[data-layout-card-id="sec-lcd-style"]');
  if (!container) return;

  container.querySelectorAll('.lcd-style-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      const style = btn.dataset.screenStyle;
      if (!style) return;
      setScreenLayoutStyle(style);
      syncLcdStyleUI();
    });
  });

  ZettEventBus.on('screen:layout_style_changed', () => {
    syncLcdStyleUI();
  });

  syncLcdStyleUI();
}

// Backward compatibility alias
export function syncThemeSettingsUI() {
  syncDesktopThemeUI();
  syncLcdThemeUI();
  syncLcdStyleUI();
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
    if (key === 'zettnas_token' || key === 'zettnas_signed_in' || key.startsWith('zettnas_weather_cache_') || key.startsWith('zettnas_holiday_cache_')) {
      continue;
    }
    // Capture all ZettNAS desktop configurations, window positions, widgets, dock pinned apps, themes, and layout locks
    if (key.startsWith('zettnas_') || key.startsWith('lcd_') || key === 'screen_layout_style') {
      prefs[key] = localStorage.getItem(key);
    }
  }
  return prefs;
}

export function applyClientPreferences(prefs) {
  if (!prefs || typeof prefs !== 'object' || typeof localStorage === 'undefined') return;
  Object.entries(prefs).forEach(([k, v]) => {
    if (k === 'zettnas_token' || k === 'zettnas_signed_in') return;
    try {
      localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v));
    } catch (e) {
      console.warn('[BACKUP] Failed restoring preference key:', k, e);
    }
  });
  if (prefs.screen_layout_style) {
    setScreenLayoutStyle(prefs.screen_layout_style, false);
  }
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

// Optional passphrase for configuration backups (AES-256-GCM). Resolves to the
// passphrase, '' for an unencrypted backup, or null when the user cancels.
function askBackupPassphrase(title, msg, allowEmpty) {
  return new Promise((resolve) => {
    showPromptToast(title, msg, '', (value) => {
      const v = (value || '').trim();
      if (!v && !allowEmpty) return resolve(null);
      if (v && v.length < 8) {
        showToast('Use a passphrase of at least 8 characters.', 'error');
        return resolve(null);
      }
      resolve(v);
    }, () => resolve(null), { inputType: 'password', placeholder: allowEmpty ? 'Leave empty for no encryption' : 'Backup passphrase' });
  });
}

const BACKUP_MAGIC = 'ZETTBAK2';

async function isEncryptedBackup(file) {
  try {
    const head = await file.slice(0, BACKUP_MAGIC.length).text();
    return head === BACKUP_MAGIC;
  } catch (e) {
    return false;
  }
}

export function initSystemTab() {
  if (typeof renderApiTokens !== 'undefined') renderApiTokens();
  syncClientPreferencesFromServerIfEmpty();
  const btnDownload = document.getElementById('btn-backup-download');
  if (btnDownload) {
    btnDownload.addEventListener('click', async () => {
      const origHtml = btnDownload.innerHTML;
      const passphrase = await askBackupPassphrase(
        'Encrypt this backup?',
        'The backup holds users and password hashes, the server secret key, share and remote credentials. Enter a passphrase to encrypt it (recommended), or leave it empty.',
        true
      );
      if (passphrase === null) return;
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

        // 2. Fetch the backup archive stream (encrypted when a passphrase was given)
        const res = passphrase
          ? await apiFetch('/api/system/backup', { method: 'POST', body: { passphrase } })
          : await apiFetch('/api/system/backup');
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
      if (!file.name.endsWith('.zip') && !file.name.endsWith('.zettbak')) {
        showToast('Please choose a ZettNAS backup (.zip or .zettbak).', 'error');
        uploadInput.value = '';
        return;
      }
      let restorePassphrase = '';
      if (await isEncryptedBackup(file)) {
        restorePassphrase = await askBackupPassphrase('Encrypted backup', 'Enter the passphrase this backup was made with.', false);
        if (restorePassphrase === null) {
          uploadInput.value = '';
          return;
        }
      }
      showConfirmToast(
        t('settings.restore_confirm_title', 'Restore Configuration'),
        t('settings.restore_confirm_desc', 'Are you sure you want to restore this configuration? This will restore all hardware settings, fan curves, layouts, widgets, and themes, and reload the interface.'),
        async () => {
          try {
            const res = await apiFetch('/api/system/restore', {
              method: 'POST',
              body: file,
              confirmed: true,
              headers: restorePassphrase ? { 'X-Backup-Passphrase': restorePassphrase } : {},
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
          <div style="font-size:11px; font-weight:700; color:#fff;">${escapeHtml(t.name)}</div>
          <div style="font-size:10px; color:var(--muted); font-family:monospace;">${escapeHtml(t.masked_token)}</div>
        </div>
        <button class="btn-rect danger" style="padding:4px 8px; font-size:10px;" data-id="${escapeHtml(t.id)}">Revoke</button>
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
