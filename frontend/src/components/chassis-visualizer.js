import { escapeHtml, trapFocus, copyTextToClipboard, reconcileKeyedTable } from '../utils.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { announceA11y } from '../a11y.js';
import { showToast, showConfirmToast, showPromptToast } from '../toast.js';
import { state } from '../state.js';
import { makeDraggable, bringToFront, DockManager } from './dock.js';

import { formatBytes as formatSize, formatDateTime } from '../format.js';
import { emptyStateHtml } from './empty-state.js';
/**
 * ZettNAS Physical Chassis Twin & Storage Topology Visualizer
 * - Parametric SVG chassis twin (Compact Dual, Desktop Tower, Enterprise Rackmount)
 * - Multi-zone thermal heatmaps (<35C cool, 35-45C green, 46-52C yellow, >=53C red)
 * - Quad-action Locate Drive / Blink Bay strobe
 * - Platter Standby / Spindown Twin with calm breathe glow
 * - M.2 Motherboard Twin with PCIe lanes & endurance meters
 * - Zero-bloat S.M.A.R.T. Velocity SVG Sparklines (7d & 30d)
 * - Storage Pool / Array Topology Tree with live IOPS & throughput
 * - Persistent User Bay Slot Mapping Modal
 */

// Zero-asset Web Audio Synthesizer for tactical user feedback
export function playChirp(freq = 880, duration = 0.12, type = 'sine') {
  try {
    if (typeof window === 'undefined') return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    const ctx = new AudioContextClass();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    gain.gain.setValueAtTime(0.06, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);
  } catch (_) {}
}

/**
 * Triggers physical and visual drive identification (Locate Drive / Blink Bay)
 */
export async function triggerLocateDisk(devName, targetElement = null) {
  if (!devName) return;

  // 1. Play tactile acoustic feedback
  playChirp(880, 0.08);
  setTimeout(() => playChirp(1320, 0.1), 90);

  // 2. Visual strobe on DOM element if provided
  if (targetElement) {
    targetElement.classList.add('strobe-active');
    setTimeout(() => {
      targetElement.classList.remove('strobe-active');
    }, 5200);
  }

  // 3. Screen reader a11y announcement & user toast
  announceA11y(`Locating drive ${devName}. Physical bay indicator flashing.`);
  showToast(t('toast.locating_drive_dev_pulsing_physical_activity', '⚡ Locating drive /dev/{devName}: Pulsing physical activity LED and backplane indicator for 5s to identify bay.', { devName: devName }), 'info');

  // 4. Issue backend hardware strobe request
  try {
    await api.request('/api/disk/locate', {
      method: 'POST',
      body: { dev: devName, duration: 5 }
    });
  } catch (err) {
    console.warn('[LocateDisk] Hardware strobe request failed:', err);
  }
}

/**
 * Computes color and status token for thermal heatmap
 */
export function getThermalLevel(tempC, isStandby = false) {
  if (isStandby || tempC == null) {
    return {
      cls: 'standby',
      color: 'var(--muted, #64748b)',
      glow: 'rgba(100, 116, 139, 0.3)',
      text: isStandby ? 'STANDBY' : 'UNKNOWN',
      toString() { return this.cls; }
    };
  }
  if (tempC >= 53) {
    return { cls: 'crit', color: 'var(--crit, #f0553b)', glow: 'rgba(240, 85, 59, 0.45)', text: `${tempC}°C`, toString() { return this.cls; } };
  }
  if (tempC >= 46) {
    return { cls: 'warn', color: 'var(--warn, #f5b731)', glow: 'rgba(245, 183, 49, 0.45)', text: `${tempC}°C`, toString() { return this.cls; } };
  }
  if (tempC >= 35) {
    return { cls: 'ok', color: 'var(--ok, #3bf58b)', glow: 'rgba(59, 245, 139, 0.35)', text: `${tempC}°C`, toString() { return this.cls; } };
  }
  return { cls: 'cool', color: 'var(--brand, #38bdf8)', glow: 'rgba(56, 189, 248, 0.35)', text: `${tempC}°C`, toString() { return this.cls; } };
}

/**
 * Renders parametric SVG / interactive Chassis Twin
 */
export function renderChassisTwin(container, disks = [], options = {}) {
  if (!container) return;

  const cfg = options.chassisConfig || null;
  const isBayConfig = Boolean(cfg && Array.isArray(cfg.bays));

  let profile = 'tower_desktop';
  let totalBays = 4;
  let chassisModel;
  let bays = [];
  let nvmes;
  let availableDrives = [];

  if (isBayConfig) {
    profile = cfg.profile || 'auto';
    totalBays = cfg.total_bays || (cfg.bays ? cfg.bays.length : 4);
    chassisModel = cfg.chassis_model || options.model || (totalBays <= 2 ? 'COMPACT DUAL' : totalBays <= 6 ? 'DESKTOP TOWER' : 'ENTERPRISE RACK');
    bays = cfg.bays || [];
    nvmes = (cfg.nvme_slots || []).map((s) => s.disk).filter(Boolean);
    availableDrives = cfg.available_drives || [];
  } else {
    // disks is raw array of disks for backward compatibility
    const hdds = disks.filter((d) => !String(d.dev || d.name).startsWith('nvme'));
    nvmes = disks.filter((d) => String(d.dev || d.name).startsWith('nvme'));
    totalBays = Math.max(options.minBays || 4, hdds.length);
    if (totalBays <= 2) profile = 'compact_dual';
    else if (totalBays <= 6) profile = 'tower_desktop';
    else profile = 'rackmount_backplane';

    chassisModel = options.model || (totalBays <= 4 ? 'ZETTLAB D4' : totalBays <= 6 ? 'ZETTLAB D6' : totalBays <= 8 ? 'ZETTLAB D8U' : 'DIY STORAGE CHASSIS');
    bays = [];
    for (let i = 0; i < totalBays; i++) {
      const d = hdds[i];
      bays.push({
        slot_index: i + 1,
        is_populated: Boolean(d),
        custom_label: null,
        disk: d ? {
          dev: d.name || d.dev || `sd${String.fromCharCode(97 + i)}`,
          model: d.model,
          serial: d.serial,
          size_formatted: d.size_formatted || d.size,
          transport: d.transport || 'sata',
          controller_driver: d.controller_driver,
          temp: d.temp,
          health: d.health,
          standby: Boolean(d.standby || d.health === 'standby'),
        } : null
      });
    }
  }

  // Determine grid CSS layout
  let gridClass;
  if (profile === 'compact_dual') {
    gridClass = 'mode-compact-dual dual-cols';
  } else if (profile === 'tower_desktop') {
    gridClass = `mode-tower ${totalBays > 4 ? 'tri-cols' : 'dual-cols'}`;
  } else if (profile === 'rackmount_backplane') {
    gridClass = `mode-rackmount ${totalBays > 12 ? 'octa-cols' : totalBays > 6 ? 'quad-cols' : 'tri-cols'}`;
  } else {
    gridClass = `mode-custom ${totalBays > 6 ? 'quad-cols' : totalBays > 4 ? 'tri-cols' : 'dual-cols'}`;
  }

  let baysHtml = '';
  bays.forEach((bay) => {
    const slotNum = bay.slot_index;
    const isPopulated = bay.is_populated && bay.disk;
    const customLabel = bay.custom_label ? `<span class="bay-custom-label" title="${escapeHtml(bay.custom_label)}">${escapeHtml(bay.custom_label)}</span>` : '';

    if (!isPopulated) {
      baysHtml += `
        <div class="chassis-bay-slot empty" data-bay="${slotNum}" role="region" aria-label="Bay ${slotNum} Empty">
          <div class="bay-header">
            <div style="display:flex; align-items:center; gap:6px; overflow:hidden;">
              <span class="bay-num">BAY ${slotNum}</span>
              ${customLabel}
            </div>
            <span class="bay-status-badge empty">VACANT</span>
          </div>
          <div class="bay-tray-handle">
            <div class="bay-led-lens off"></div>
            <div class="bay-drive-info">
              <span class="bay-drive-model" style="opacity: 0.5;">VACANT</span>
              <span class="bay-drive-dev" style="opacity: 0.4;">Slot ${slotNum} Available</span>
              <span class="bay-sub-badge" style="opacity: 0.35;">STANDBY READY</span>
            </div>
          </div>
          <div class="bay-footer">
            <span class="bay-meta" style="font-size:var(--zn-fs-xs); color:var(--muted); letter-spacing:0.04em;">NO DISK</span>
            <span class="bay-health-tag" style="opacity:0.3;">EMPTY</span>
          </div>
        </div>
      `;
    } else {
      const d = bay.disk;
      const devName = d.dev || d.name || `sd${String.fromCharCode(96 + slotNum)}`;
      const isStandby = Boolean(d.standby || d.health === 'standby');
      const thermal = getThermalLevel(d.temp, isStandby);
      const modelStr = d.model ? d.model.slice(0, 14) : devName;
      const sizeStr = d.size_formatted || d.size || '';
      const transportStr = d.transport ? d.transport.toUpperCase() : 'SATA';
      const driverStr = d.controller_driver ? ` • ${d.controller_driver}` : '';

      baysHtml += `
        <div class="chassis-bay-slot populated ${thermal.cls}" data-bay="${slotNum}" data-dev="${devName}" role="button" tabindex="0" aria-label="Bay ${slotNum}: ${escapeHtml(modelStr)}, ${thermal.text}">
          <div class="bay-header">
            <div style="display:flex; align-items:center; gap:6px; overflow:hidden;">
              <span class="bay-num">BAY ${slotNum}</span>
              ${customLabel}
            </div>
            <span class="bay-temp-pill" style="color: ${thermal.color}; border-color: ${thermal.color};">${thermal.text}</span>
          </div>
          <div class="bay-tray-handle">
            <div class="bay-led-lens ${isStandby ? 'standby-pulse' : 'online'}"></div>
            <div class="bay-drive-info">
              <span class="bay-drive-model" title="${escapeHtml(d.model || devName)}">${escapeHtml(modelStr)}</span>
              <span class="bay-drive-dev">/dev/${devName} ${sizeStr ? '• ' + sizeStr : ''}</span>
              <span class="bay-sub-badge">${transportStr}${driverStr}</span>
            </div>
          </div>
          <div class="bay-footer">
            <button class="bay-locate-btn" data-dev="${devName}" title="${t('ui.locate_drive_blink_bay_led', 'Locate Drive (Blink Bay LED)')}" aria-label="Locate drive in Bay ${slotNum}">
              <svg class="locate-icon" viewBox="0 0 24 24" width="12" height="12"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor"/></svg>
              <span>LOCATE</span>
            </button>
            <span class="bay-health-tag ${thermal.cls}">${isStandby ? 'STANDBY' : (d.health ? String(d.health).toUpperCase() : 'OK')}</span>
          </div>
        </div>
      `;
    }
  });

  let m2Html = '';
  if (nvmes.length > 0) {
    m2Html = `
      <div class="m2-motherboard-twin">
        <div class="m2-twin-header">
          <svg viewBox="0 0 24 24" width="14" height="14"><use href="#i-nvme"/></svg>
          <span>${escapeHtml(t('storage.m2_on_board', 'M.2 drives on the mainboard'))}</span>
        </div>
        <div class="m2-slots-grid">
    `;
    nvmes.forEach((nv, idx) => {
      const devName = nv.name || nv.dev || `nvme${idx}n1`;
      const isStandby = Boolean(nv.standby);
      const thermal = getThermalLevel(nv.temp, isStandby);
      const wear = nv.percentage_used != null ? `${nv.percentage_used}%` : nv.wear != null ? `${nv.wear}%` : '--';
      m2Html += `
        <div class="m2-slot-card ${thermal.cls}" data-dev="${devName}" role="button" tabindex="0">
          <div class="m2-header">
            <span class="m2-name">M.2 SLOT ${idx + 1} • /dev/${devName}</span>
            <span class="m2-temp" style="color:${thermal.color};">${thermal.text}</span>
          </div>
          <div class="m2-body">
            <span class="m2-model">${escapeHtml(nv.model || 'PCIe NVMe SSD')}</span>
            <span class="m2-wear">Endurance Used: <strong>${wear}</strong></span>
          </div>
          <button class="m2-locate-btn bay-locate-btn" data-dev="${devName}">
            <svg viewBox="0 0 24 24" width="11" height="11"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor"/></svg>
            <span>LOCATE</span>
          </button>
        </div>
      `;
    });
    m2Html += `</div></div>`;
  }

  container.innerHTML = `
    <div class="chassis-twin-view">
      <div class="chassis-enclosure-faceplate">
        <div class="chassis-top-bar">
          <div class="chassis-screw-head"></div>
          <div class="chassis-brand-mark">${escapeHtml(chassisModel)}</div>
          <div class="chassis-top-actions">
            <button class="chassis-config-btn" id="chassis-open-slots-btn" title="${t('ui.configure_chassis_bays_profile', 'Configure Chassis Bays & Profile')}" aria-label="${t('ui.configure_chassis_bays_profile', 'Configure Chassis Bays & Profile')}">
              <svg viewBox="0 0 24 24" width="12" height="12"><path d="M12 15a3 3 0 100-6 3 3 0 000 6z" fill="currentColor"/><path fill-rule="evenodd" d="M1.323 11.447C2.811 6.976 7.028 3.75 12.001 3.75c4.97 0 9.185 3.223 10.675 7.69.12.362.12.752 0 1.113-1.487 4.471-5.705 7.697-10.677 7.697-4.97 0-9.186-3.223-10.675-7.69a1.762 1.762 0 010-1.113zM17.25 12a5.25 5.25 0 11-10.5 0 5.25 5.25 0 0110.5 0z" clip-rule="evenodd" fill="currentColor"/></svg>
              <span>SLOTS / MAPPING</span>
            </button>
          </div>
          <div class="chassis-honeycomb-vents"></div>
          <div class="chassis-screw-head"></div>
        </div>
        <div class="chassis-bay-grid ${gridClass}">
          ${baysHtml}
        </div>
        ${m2Html}
      </div>
    </div>
  `;

  // Attach event handlers
  container.querySelectorAll('.bay-locate-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const dev = btn.dataset.dev;
      const slot = btn.closest('.chassis-bay-slot, .m2-slot-card');
      triggerLocateDisk(dev, slot);
    });
  });

  container.querySelectorAll('.chassis-bay-slot.populated, .m2-slot-card').forEach((slot) => {
    slot.addEventListener('click', (e) => {
      if (e.target.closest('.bay-locate-btn')) return;
      const dev = slot.dataset.dev;
      if (!dev) return;
      // Drive Health shows a sleeping drive from its last reading and never wakes it on open
      ZettEventBus.emit('modal:smart:open', dev);
    });
  });

  const slotsBtn = container.querySelector('#chassis-open-slots-btn');
  if (slotsBtn) {
    slotsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const activeCfg = cfg || {
        profile,
        total_bays: totalBays,
        bays,
        available_drives: availableDrives
      };
      openChassisConfigModal(activeCfg, () => {
        fetchAndRenderChassisTwin(container, options);
      });
    });
  }
}

/**
 * Fetches latest chassis configuration and renders the twin
 */
export async function fetchAndRenderChassisTwin(container, options = {}) {
  if (!container) return;
  try {
    const res = await api.request('/api/chassis/config');
    if (res.ok) {
      const config = await res.json();
      renderChassisTwin(container, config.bays || [], { ...options, chassisConfig: config });
      return config;
    }
  } catch (err) {
    console.warn('[ChassisVisualizer] Failed to load chassis config:', err);
  }

  // Fallback to latestStats.disks if available
  const fallbackDisks = state.latestStats?.disks || [];
  renderChassisTwin(container, fallbackDisks, options);
}

/**
 * Modal to configure physical chassis profile, bay counts, and slot assignments
 */
export function openChassisConfigModal(currentConfig = {}, onSaved = null) {
  let modalOverlay = document.getElementById('chassis-config-modal-overlay');
  if (!modalOverlay) {
    modalOverlay = document.createElement('div');
    modalOverlay.id = 'chassis-config-modal-overlay';
    modalOverlay.className = 'smart-modal-backdrop open';
    modalOverlay.setAttribute('role', 'dialog');
    modalOverlay.setAttribute('aria-modal', 'true');
    document.body.appendChild(modalOverlay);
  }

  modalOverlay.style.display = 'flex';
  modalOverlay.classList.remove('window-minimized');
  modalOverlay.classList.add('open');

  const profile = currentConfig.profile || 'auto';
  let totalBays = currentConfig.total_bays || (currentConfig.bays ? currentConfig.bays.length : 4);
  const availableDrives = currentConfig.available_drives || [];
  const currentBays = currentConfig.bays || [];

  modalOverlay.innerHTML = `
    <div class="smart-modal-window chassis-slots-modal" style="width: 660px; max-width: 95vw; max-height: 85vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center;">
        <div class="smart-modal-title" style="display:flex; align-items:center; gap:8px;">
          <svg viewBox="0 0 24 24" width="16" height="16"><path d="M12 15a3 3 0 100-6 3 3 0 000 6z" fill="currentColor"/></svg>
          <span>CHASSIS ENCLOSURE & BAY CONFIGURATION</span>
        </div>
        <button class="win-btn close-btn" id="chassis-config-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
      </div>
      <div class="smart-modal-body" style="padding: 16px; overflow-y: auto; flex: 1; display:flex; flex-direction:column; gap: 14px;">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div>
            <label for="chassis-profile-select" style="display:block; font-size:var(--zn-fs-xs); font-weight:700; color:var(--muted); margin-bottom:6px;">ENCLOSURE PROFILE</label>
            <select id="chassis-profile-select" class="tz-select-input" style="width:100%; padding:8px; border-radius:6px; background:var(--zn-shade-30); border:1px solid var(--zn-line-12); color:var(--zn-text-strong); font-size:var(--zn-fs-xs);">
              <option value="auto" ${profile === 'auto' ? 'selected' : ''}>Auto Dynamic (Auto-Detect)</option>
              <option value="compact_dual" ${profile === 'compact_dual' ? 'selected' : ''}>Compact Dual (1–2 Bays)</option>
              <option value="tower_desktop" ${profile === 'tower_desktop' ? 'selected' : ''}>Desktop Tower (3–6 Bays)</option>
              <option value="rackmount_backplane" ${profile === 'rackmount_backplane' ? 'selected' : ''}>Enterprise Rackmount (8–24 Bays)</option>
              <option value="custom" ${profile === 'custom' ? 'selected' : ''}>Custom Enclosure</option>
            </select>
          </div>
          <div>
            <label for="chassis-total-bays-input" style="display:block; font-size:var(--zn-fs-xs); font-weight:700; color:var(--muted); margin-bottom:6px;">TOTAL PHYSICAL BAYS</label>
            <input type="number" id="chassis-total-bays-input" min="1" max="48" value="${totalBays}" style="width:100%; padding:8px; border-radius:6px; background:var(--zn-shade-30); border:1px solid var(--zn-line-12); color:var(--zn-text-strong); font-size:var(--zn-fs-xs);">
          </div>
        </div>

        <div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <label style="font-size:var(--zn-fs-xs); font-weight:700; color:var(--muted); letter-spacing:0.5px;">PHYSICAL BAY ALLOCATION & LABELS</label>
            <button id="chassis-auto-assign-btn" class="btn-pill-toggle">⚡ Auto-Assign Sequentially</button>
          </div>
          <div style="max-height: 320px; overflow-y: auto; border: 1px solid var(--zn-line-8); border-radius: 6px; background: var(--zn-shade-20);">
            <table class="copy-history-table chassis-slots-table" style="width:100%;">
              <thead>
                <tr>
                  <th style="width:80px;">Slot</th>
                  <th>Assigned Physical Drive</th>
                  <th style="width:180px;">Custom Label</th>
                </tr>
              </thead>
              <tbody id="chassis-slots-tbody">
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="smart-modal-footer" style="padding: 12px 16px; border-top: 1px solid var(--zn-line-8); display:flex; justify-content:flex-end; gap: 8px;">
        <button id="chassis-config-cancel-btn" class="btn-pill-toggle">Cancel</button>
        <button id="chassis-config-save-btn" class="btn-save-preset" style="padding: 8px 20px;">Save Bay Mapping</button>
      </div>
    </div>
  `;

  const tbody = modalOverlay.querySelector('#chassis-slots-tbody');
  const baysInput = modalOverlay.querySelector('#chassis-total-bays-input');
  const profileSelect = modalOverlay.querySelector('#chassis-profile-select');

  function renderRows(count, mappings = []) {
    let rowsHtml = '';
    for (let slot = 1; slot <= count; slot++) {
      const existing = mappings.find((m) => m.slot_index === slot) || currentBays.find((b) => b.slot_index === slot);
      const currentCid = existing?.canonical_id || existing?.disk?.canonical_id || existing?.disk?.dev || '';
      const currentLabel = existing?.custom_label || '';

      let optionsHtml = `<option value="">-- [ Vacant / Empty Tray ] --</option>`;
      availableDrives.forEach((d) => {
        const isSel = d.canonical_id === currentCid || d.dev === currentCid || d.serial === currentCid;
        const text = `${d.dev} • ${d.model || 'Drive'} (${d.size_formatted || ''}) [${d.serial || ''}]`;
        optionsHtml += `<option value="${escapeHtml(d.canonical_id)}" ${isSel ? 'selected' : ''}>${escapeHtml(text)}</option>`;
      });

      rowsHtml += `
        <tr data-slot="${slot}">
          <td style="font-weight:700; color:var(--lt-ink-brand, var(--accent-cyan, #00f0ff));">BAY ${slot}</td>
          <td>
            <select class="slot-drive-select tz-select-input" style="width:100%; padding:6px; font-size:var(--zn-fs-xs); background:var(--zn-shade-30); border:1px solid var(--zn-line-10); color:var(--zn-text-strong); border-radius:4px;">
              ${optionsHtml}
            </select>
          </td>
          <td>
            <input type="text" class="slot-label-input tz-text-input" maxlength="64" value="${escapeHtml(currentLabel)}" placeholder="${t('ui.e_g_parity_1_pool', 'e.g. Parity 1, Pool A')}" style="width:100%; padding:6px; font-size:var(--zn-fs-xs); background:var(--zn-shade-30); border:1px solid var(--zn-line-10); color:var(--zn-text-strong); border-radius:4px;">
          </td>
        </tr>
      `;
    }
    tbody.innerHTML = rowsHtml;
  }

  renderRows(totalBays);

  baysInput.addEventListener('change', () => {
    const val = parseInt(baysInput.value, 10);
    if (val >= 1 && val <= 48) {
      totalBays = val;
      renderRows(totalBays);
    }
  });

  const autoAssignBtn = modalOverlay.querySelector('#chassis-auto-assign-btn');
  if (autoAssignBtn) {
    autoAssignBtn.addEventListener('click', () => {
      const autoMappings = availableDrives.slice(0, totalBays).map((d, idx) => ({
        slot_index: idx + 1,
        canonical_id: d.canonical_id,
        custom_label: idx === 0 ? 'Parity / Primary' : `Disk ${idx}`
      }));
      renderRows(totalBays, autoMappings);
      showToast(t('toast.assigned_detected_drives_sequentially', 'Assigned detected drives sequentially.'), 'info');
    });
  }

  function closeModal() {
    modalOverlay.style.display = 'none';
    modalOverlay.classList.remove('open');
  }

  modalOverlay.querySelector('#chassis-config-close').addEventListener('click', closeModal);
  modalOverlay.querySelector('#chassis-config-cancel-btn').addEventListener('click', closeModal);

  modalOverlay.querySelector('#chassis-config-save-btn').addEventListener('click', async () => {
    const mappings = [];
    tbody.querySelectorAll('tr[data-slot]').forEach((tr) => {
      const slotIdx = parseInt(tr.dataset.slot, 10);
      const select = tr.querySelector('.slot-drive-select');
      const labelInp = tr.querySelector('.slot-label-input');
      const cid = select.value;
      if (cid) {
        mappings.push({
          slot_index: slotIdx,
          canonical_id: cid,
          custom_label: labelInp.value.trim() || null
        });
      }
    });

    const payload = {
      profile: profileSelect.value,
      total_bays: parseInt(baysInput.value, 10),
      mappings
    };

    try {
      const res = await api.request('/api/chassis/bay_map', {
        method: 'POST',
        body: payload
      });
      if (res.ok) {
        showToast(t('toast.chassis_bay_mapping_updated_successfully', 'Chassis bay mapping updated successfully.'), 'success');
        closeModal();
        if (typeof onSaved === 'function') onSaved(payload);
      } else {
        showToast(t('toast.failed_to_save_chassis_bay_mapping', 'Failed to save chassis bay mapping.'), 'error');
      }
    } catch (err) {
      showToast(t('toast.error_saving_bay_mapping', 'Error saving bay mapping: {error}', { error: err.message }), 'error');
    }
  });

  const win = modalOverlay.querySelector('.smart-modal-window');
  trapFocus(win, closeModal);
}

/**
 * Zero-bloat SVG Sparkline Generator for 7d & 30d S.M.A.R.T. Velocity
 */
export function generateSmartSparklineSvg(points = [], width = 280, height = 50) {
  if (!points || points.length === 0) {
    return `
      <svg class="smart-sparkline-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
        <text x="${width / 2}" y="${height / 2 + 4}" font-size="10" fill="#64748b" text-anchor="middle">No historical data recorded</text>
      </svg>
    `;
  }

  const values = points.map((p) => (p.realloc || 0) + (p.pending || 0));
  const maxVal = Math.max(1, Math.max(...values));

  const padX = 6;
  const padY = 6;
  const availW = width - padX * 2;
  const availH = height - padY * 2;

  const coords = points.map((p, idx) => {
    const x = padX + (idx / Math.max(1, points.length - 1)) * availW;
    const val = (p.realloc || 0) + (p.pending || 0);
    const y = padY + availH - (val / maxVal) * availH;
    return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, val };
  });

  const pathD = coords.reduce((acc, c, idx) => `${acc} ${idx === 0 ? 'M' : 'L'} ${c.x} ${c.y}`, '');
  const areaD = `${pathD} L ${coords[coords.length - 1].x} ${height - padY} L ${coords[0].x} ${height - padY} Z`;

  const hasErrors = values.some((v) => v > 0);
  const strokeColor = hasErrors ? '#f5b731' : '#3bf58b';
  const fillColor = hasErrors ? 'rgba(245, 183, 49, 0.15)' : 'rgba(59, 245, 139, 0.08)';

  // For markers: if errors exist, highlight all error points. If healthy (val == 0), render clean start/end points
  // in theme green rather than dozens of dense white circles that merge into a solid white bar.
  let circlesHtml = '';
  if (hasErrors) {
    circlesHtml = coords
      .filter((c) => c.val > 0)
      .map((c) => `<circle cx="${c.x}" cy="${c.y}" r="3" fill="${strokeColor}" stroke="#0b1118" stroke-width="1"/>`)
      .join('');
  } else if (coords.length > 0) {
    const first = coords[0];
    const last = coords[coords.length - 1];
    circlesHtml = `
      <circle cx="${first.x}" cy="${first.y}" r="1.5" fill="${strokeColor}" opacity="0.6"/>
      <circle cx="${last.x}" cy="${last.y}" r="2" fill="${strokeColor}"/>
    `;
  }

  return `
    <svg class="smart-sparkline-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <path d="${areaD}" fill="${fillColor}"/>
      <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      ${circlesHtml}
    </svg>
  `;
}

export function formatBytes(bytes) {
  // Disk capacity is labelled the way disk makers do: powers of 1000.
  return formatSize(bytes, { si: true, fixed: true });
}

export function formatNumber(num) {
  if (!num) return '0';
  const n = Number(num);
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
}

/**
 * Renders Structured Storage Pools Topology from /api/storage/pools
 */
export function renderStructuredPoolsTopology(container, data) {
  if (!container || !data || !Array.isArray(data.pools)) return;

  const pools = data.pools;
  const isObserver = data.is_observer_mode ?? true;
  const platform = data.platform || '';

  let tree = container.querySelector('.storage-topology-tree');
  if (!tree) {
    container.innerHTML = `
      <div class="storage-topology-tree">
        ${isObserver ? `
          <div class="topo-observer-banner">
            <span class="observer-icon">ℹ️</span>
            <span>${escapeHtml(t('storage.mode_host_desc', '{platform} manages the storage pools, array and parity checks here. ZettNAS shows them and never changes them.', { platform: platformName(platform) }))}</span>
          </div>
        ` : `
          <div class="topo-observer-banner" style="background:rgba(99,102,241,0.12); border-color:rgba(99,102,241,0.25);">
            <span class="observer-icon">⚡</span>
            <span>${escapeHtml(t('storage.mode_zettnas_desc', 'ZettNAS manages the storage pools, RAID protection against bit rot, and snapshots on this machine.'))}</span>
          </div>
        `}
        <div class="topo-pools-container"></div>
      </div>
    `;
    tree = container.querySelector('.storage-topology-tree');
  }

  bindTopologyTreeEvents(tree, container);

  const poolsContainer = tree.querySelector('.topo-pools-container') || tree;
  reconcileKeyedTable(
    poolsContainer,
    pools,
    (p) => p.id || p.name,
    (p) => {
      const block = document.createElement('div');
      block.className = 'topo-pool-block';
      block.dataset.key = p.id || p.name;
      block.innerHTML = buildPoolBlockInner(p, isObserver);
      return block;
    },
    (block, p) => {
      block.innerHTML = buildPoolBlockInner(p, isObserver);
    }
  );
}

function buildPoolBlockInner(pool, isObserver) {
  const usedStr = formatBytes(pool.used_bytes);
  const totalStr = formatBytes(pool.total_bytes);
  const freeStr = formatBytes(pool.free_bytes);
  const pct = pool.used_pct || 0;
  const barColor = pct > 90 ? 'var(--alert, #ef4444)' : (pct > 75 ? 'var(--warn, #f59e0b)' : 'var(--accent, #3bf58b)');

  let statusClass = 'status-healthy';
  let statusLabel = pool.status || 'HEALTHY';
  if (statusLabel === 'SYNCING') {
    statusClass = 'status-syncing';
    statusLabel = '🔄 PARITY SYNCING';
  } else if (statusLabel === 'DEGRADED') {
    statusClass = 'status-degraded';
  }

  const membersHtml = (pool.members || []).map((m) => {
    const isStandby = m.spundown || m.status === 'STANDBY';
    const tempDisplay = isStandby ? '🌙 Standby' : (m.temp_c != null ? `${m.temp_c}°C` : '--');
    const tempLevel = isStandby ? 'standby' : (m.temp_c != null ? getThermalLevel(m.temp_c).cls : 'cool');
    const readsStr = m.num_reads ? formatNumber(m.num_reads) : '0';
    const writesStr = m.num_writes ? formatNumber(m.num_writes) : '0';

    return `
      <div class="topo-disk-card role-${m.role || 'data'} ${isStandby ? 'disk-standby' : ''}">
        <div class="topo-disk-top">
          <span class="topo-role-badge role-${m.role || 'data'}">${(m.role || 'DATA').toUpperCase()}</span>
          <span class="topo-dev-name">/dev/${escapeHtml(m.device || m.name)}</span>
          <span class="topo-temp-badge thermal-${tempLevel}">${tempDisplay}</span>
        </div>
        <div class="topo-disk-sub">
          <span class="topo-disk-size">${formatBytes(m.size_bytes)}</span>
          <span class="topo-disk-io" title="${t('ui.disk_i_o_reads_writes', 'Disk I/O Reads & Writes')}">R: ${readsStr} · W: ${writesStr}</span>
        </div>
        <div class="topo-disk-actions">
          <button class="btn-locate-topo" data-dev="${escapeHtml(m.device || m.name)}" title="${t('ui.blink_drive_activity_led', 'Blink drive activity LED')}">
            💡 Locate
          </button>
        </div>
      </div>
    `;
  }).join('');

  return `
    <div class="topo-pool-header">
      <div class="topo-pool-title-wrap">
        <svg viewBox="0 0 24 24" width="18" height="18" class="pool-icon"><use href="#i-storage"/></svg>
        <div>
          <span class="topo-pool-name">${escapeHtml(pool.name)}</span>
          <span class="topo-pool-fs">${escapeHtml(pool.fs_type.toUpperCase())}${pool.fs_profile ? ` · ${escapeHtml(pool.fs_profile.toUpperCase())}` : ''}</span>
        </div>
      </div>
      <div class="topo-pool-badges">
        ${pool.parity_protected ? '<span class="topo-parity-badge" title="' + t('ui.protected_against_disk_failure', 'Protected against disk failure') + '">🛡️ Parity Protected</span>' : ''}
        <span class="topo-status-pill ${statusClass}">${escapeHtml(statusLabel)}</span>
      </div>
    </div>

    <div class="topo-pool-usage">
      <div class="topo-usage-labels">
        <span><strong>${usedStr}</strong> used / <strong>${totalStr}</strong> total (${pct}%)</span>
        <span class="topo-free-space">${freeStr} Free</span>
      </div>
      <div class="topo-usage-track">
        <div class="topo-usage-fill" style="width: ${Math.min(100, Math.max(0, pct))}%; background: ${barColor};"></div>
      </div>
    </div>

    <div class="topo-members-section">
      <div class="topo-members-label">POOL MEMBER DISKS (${(pool.members || []).length})</div>
      <div class="topo-members-grid">
        ${membersHtml || '<span class="empty-note">No assigned member drives</span>'}
      </div>
    </div>

    <div class="topo-pool-actions" style="margin-top:12px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
      <button class="btn-pool-scrub btn-pill-toggle" data-pool-id="${escapeHtml(pool.id)}" title="${t('ui.trigger_filesystem_scrub_or_parity', 'Trigger filesystem scrub or parity check')}">⚡ Scrub Pool</button>
      ${!isObserver ? `<button class="btn-pool-rename btn-pill-toggle" data-pool-id="${escapeHtml(pool.id)}" data-pool-name="${escapeHtml(pool.name)}" title="${t('ui.rename_storage_pool', 'Rename storage pool')}">✏️ Rename</button>` : ''}
      ${pool.fs_type === 'btrfs' ? `<button class="btn-pool-snaps btn-pill-toggle" data-pool-id="${escapeHtml(pool.id)}" style="background: rgba(14,165,233,0.15); border-color: rgba(14,165,233,0.3); color: var(--zn-text-accent);" title="${t('ui.manage_subvolume_snapshots', 'Manage Subvolume Snapshots')}">📸 Snapshots</button>` : ''}
      ${(!isObserver || pool.fs_type === 'zfs') && pool.id !== 'unraid_array' && pool.id !== 'default_pool' ? `<button class="btn-pool-export btn-pill-toggle" data-pool-id="${escapeHtml(pool.id)}" style="background: rgba(245,158,11,0.15); border-color: rgba(245,158,11,0.3); color: var(--zn-text-warn);" title="${t('ui.safely_flush_dirty_cache_and', 'Safely flush dirty cache and detach pool')}">⏏️ Safely Eject</button>` : ''}
      ${!isObserver && pool.id !== 'default_pool' ? `<button class="btn-pool-destroy btn-pill-toggle is-danger" data-pool-id="${escapeHtml(pool.id)}" title="${t('ui.destroy_storage_pool', 'Destroy storage pool')}">🗑️ Destroy</button>` : ''}
    </div>
  `;
}

function bindTopologyTreeEvents(tree, container) {
  if (tree._eventsBound) return;
  tree._eventsBound = true;

  tree.addEventListener('click', async (e) => {
    const locateBtn = e.target.closest('.btn-locate-topo');
    if (locateBtn) {
      e.stopPropagation();
      const dev = locateBtn.dataset.dev;
      if (dev) triggerLocateDisk(dev, locateBtn);
      return;
    }

    const scrubBtn = e.target.closest('.btn-pool-scrub');
    if (scrubBtn) {
      e.stopPropagation();
      const pid = scrubBtn.dataset.poolId;
      try {
        const res = await api.post('/api/storage/scrub', { pool_id: pid, action: 'start' });
        showToast(res.message || 'Scrub initiated.', 'info');
      } catch (err) {
        showToast(err.message || 'Failed to trigger scrub', 'error');
      }
      return;
    }

    const renameBtn = e.target.closest('.btn-pool-rename');
    if (renameBtn) {
      e.stopPropagation();
      const pid = renameBtn.dataset.poolId;
      const pname = renameBtn.dataset.poolName || pid;
      openRenameStoragePoolModal(pid, pname, () => fetchAndRenderStorageTopology(container));
      return;
    }

    const snapBtn = e.target.closest('.btn-pool-snaps');
    if (snapBtn) {
      e.stopPropagation();
      openSnapshotsModal(snapBtn.dataset.poolId);
      return;
    }

    const destroyBtn = e.target.closest('.btn-pool-destroy');
    if (destroyBtn) {
      e.stopPropagation();
      const pid = destroyBtn.dataset.poolId;
      showConfirmToast(
        'Destroy Pool',
        `Are you sure you want to destroy pool '${pid}'? All mounted data will be unmounted.`,
        async () => {
          try {
            await api.delete(`/api/storage/pools/${pid}`, { confirmed: true });
            showToast(t('toast.pool_destroyed', 'Pool \'{pid}\' destroyed.', { pid: pid }), 'info');
            fetchAndRenderStorageTopology(container);
          } catch (err) {
            showToast(err.message || 'Failed to destroy pool', 'error');
          }
        },
        null,
        { okText: 'Destroy Pool', cancelText: 'Cancel' }
      );
      return;
    }

    const exportBtn = e.target.closest('.btn-pool-export');
    if (exportBtn) {
      e.stopPropagation();
      const pid = exportBtn.dataset.poolId;
      showConfirmToast(
        'Safely Eject Pool',
        `Safely flush write cache and export/detach pool '${pid}'? Make sure no active file transfers are running.`,
        async () => {
          try {
            exportBtn.disabled = true;
            exportBtn.textContent = t('ui.ejecting', '⏳ Ejecting...');
            const res = await api.post(`/api/storage/pools/${encodeURIComponent(pid)}/export`, { force: false });
            showToast(res.message || `Pool '${pid}' safely ejected. You may disconnect the cable.`, 'success');
            fetchAndRenderStorageTopology(container);
          } catch (err) {
            if (err.message && err.message.includes('force=true')) {
              showConfirmToast(
                'Force Export Pool',
                `${err.message}\n\nDo you want to FORCE export and unmount anyway?`,
                async () => {
                  try {
                    const res = await api.post(`/api/storage/pools/${encodeURIComponent(pid)}/export`, { force: true });
                    showToast(res.message || `Pool '${pid}' safely ejected.`, 'success');
                    fetchAndRenderStorageTopology(container);
                  } catch (e2) {
                    showToast(e2.message || 'Failed to force eject pool', 'error');
                  }
                },
                null,
                { okText: 'Force Eject', cancelText: 'Cancel' }
              );
            } else {
              showToast(err.message || 'Failed to safely eject pool', 'error');
            }
          } finally {
            exportBtn.disabled = false;
            exportBtn.textContent = t('ui.safely_eject', '⏏️ Safely Eject');
          }
        },
        null,
        { okText: 'Safely Eject', cancelText: 'Cancel' }
      );
      return;
    }

    const importBtn = e.target.closest('.btn-import-external-pool');
    if (importBtn) {
      e.stopPropagation();
      const pid = importBtn.dataset.poolId;
      const fstype = importBtn.dataset.fsType || 'zfs';
      try {
        importBtn.disabled = true;
        importBtn.textContent = t('ui.importing', '⏳ Importing...');
        await api.post('/api/storage/pools/import', { pool_id: pid, fs_type: fstype });
        showToast(t('toast.successfully_imported_storage_pool', 'Successfully imported storage pool \'{pid}\'!', { pid: pid }), 'success');
        fetchAndRenderStorageTopology(container);
      } catch (err) {
        showToast(err.message || `Failed to import pool '${pid}'`, 'error');
        importBtn.disabled = false;
        importBtn.textContent = t('ui.import_pool', '📥 Import Pool');
      }
      return;
    }
  });
}

/**
 * Fetches and renders Storage Topology Tree
 */
export async function fetchAndRenderStorageTopology(container) {
  if (!container) return;
  if (!container.firstElementChild || container.querySelector('.loader-spinner')) {
    container.innerHTML = `
      <div style="text-align:center; padding:30px; color:var(--muted);">
        <div class="loader-spinner" style="margin:0 auto 10px;"></div>
        Scanning storage pools and array topology...
      </div>
    `;
  }

  try {
    const [data, platformData, discoveredData] = await Promise.all([
      api.get('/api/storage/pools'),
      api.get('/api/storage/platform').catch(() => ({})),
      api.get('/api/storage/pools/discover').catch(() => ({ discovered_pools: [] })),
    ]);

    const canCreatePools = platformData?.capabilities?.can_create_pools ?? false;
    const btnCreatePool = document.getElementById('btn-create-storage-pool');
    const btnSnapshots = document.getElementById('btn-manage-snapshots');
    if (btnCreatePool) {
      btnCreatePool.style.display = canCreatePools ? 'inline-flex' : 'none';
      btnCreatePool.onclick = () => openCreateStoragePoolModal(() => fetchAndRenderStorageTopology(container));
    }
    if (btnSnapshots) {
      btnSnapshots.style.display = canCreatePools ? 'inline-flex' : 'none';
      btnSnapshots.onclick = () => openSnapshotsModal();
    }

    const discoveredList = discoveredData?.discovered_pools || [];
    let externalBannerHtml = '';
    if (discoveredList.length > 0) {
      externalBannerHtml = discoveredList.map(p => `
        <div class="external-pools-banner" style="background:rgba(14,165,233,0.12); border:1px solid rgba(14,165,233,0.3); border-radius:8px; padding:12px 16px; margin-bottom:16px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;">
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:20px;">🔌</span>
            <div>
              <strong style="color:var(--zn-text-accent);">External Storage Pool Detected:</strong>
              <span style="color:var(--zn-text-strong); margin-left:6px; font-weight:600;">${escapeHtml(p.pool_id)}</span>
              <span style="color:var(--muted); font-size:var(--zn-fs-xs); margin-left:8px;">(${escapeHtml((p.fs_type || 'zfs').toUpperCase())}${p.status ? ` · ${escapeHtml(p.status)}` : ''})</span>
            </div>
          </div>
          <button class="btn-import-external-pool btn-pill-toggle" data-pool-id="${escapeHtml(p.pool_id)}" data-fs-type="${escapeHtml(p.fs_type || 'zfs')}" style="background: rgba(34,197,94,0.15); border-color: rgba(34,197,94,0.3); color: var(--lt-t-4ade80ff, #4ade80);" title="${t('ui.import_detached_storage_pool', 'Import detached storage pool')}">
            📥 Import Pool
          </button>
        </div>
      `).join('');
    }

    if (!data || !Array.isArray(data.pools) || data.pools.length === 0) {
      renderStorageTopologyTree(container, state.latestStats?.disks, state.latestStats?.unraid || {});
    } else {
      renderStructuredPoolsTopology(container, data);
    }

    if (externalBannerHtml) {
      container.insertAdjacentHTML('afterbegin', externalBannerHtml);
      if (!container._externalPoolEventsBound) {
        container._externalPoolEventsBound = true;
        container.addEventListener('click', async (e) => {
          const importBtn = e.target.closest('.btn-import-external-pool');
          if (importBtn) {
            e.stopPropagation();
            const pid = importBtn.dataset.poolId;
            const fstype = importBtn.dataset.fsType || 'zfs';
            try {
              importBtn.disabled = true;
              importBtn.textContent = t('ui.importing', '⏳ Importing...');
              await api.post('/api/storage/pools/import', { pool_id: pid, fs_type: fstype });
              showToast(t('toast.successfully_imported_storage_pool', 'Successfully imported storage pool \'{pid}\'!', { pid: pid }), 'success');
              fetchAndRenderStorageTopology(container);
            } catch (err) {
              showToast(err.message || `Failed to import pool '${pid}'`, 'error');
              importBtn.disabled = false;
              importBtn.textContent = t('ui.import_pool', '📥 Import Pool');
            }
          }
        });
      }
    }
  } catch (err) {
    console.warn('[ZettNAS] Failed to load /api/storage/pools, falling back to local disks:', err);
    renderStorageTopologyTree(container, state.latestStats?.disks, state.latestStats?.unraid || {});
  }
}

/**
 * Builds HTML for Inbound SFTP Subsystem Server Card
 */
export function buildSftpCardHtml(sftpStatus, usersCount = 0, sampleUser = 'admin') {
  const isRunning = Boolean(sftpStatus?.running);
  const port = sftpStatus?.port || 2222;
  const sftpPillClass = isRunning ? 'running' : 'stopped';
  const sftpPillText = isRunning ? `🟢 RUNNING (Port ${port})` : '⚪ STOPPED';
  const hostIp = window.location.hostname || '127.0.0.1';
  const user = sampleUser || 'username';

  const finderCmd = `sftp://${user}@${hostIp}:${port}/`;
  const terminalCmd = `sftp -P ${port} ${user}@${hostIp}`;
  const filezillaHint = `Host: ${hostIp} · Port: ${port} · Protocol: SFTP`;
  const sshfsCmd = `sshfs -p ${port} ${user}@${hostIp}:/ /mnt/sftp`;

  return `
    <div class="webdav-server-card sftp-server-card" id="mgmt-sftp-subsystem-card">
      <div class="webdav-card-header">
        <div class="webdav-header-title">
          <svg class="ic" style="width:18px; height:18px; fill:currentColor; color:var(--lt-ink-brand, var(--brand, #0ea5e9));"><use href="#i-storage"/></svg>
          <span data-i18n="sftp.title">SFTP file access</span>
          <span class="webdav-status-pill ${sftpPillClass}">${sftpPillText}</span>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <button class="btn-pill-toggle btn-sftp-toggle-action" id="btn-sftp-header-toggle" style="padding:5px 12px; font-size:var(--zn-fs-xs); font-weight:700; ${isRunning ? 'background:rgba(239,68,68,0.15); color:var(--zn-text-crit); border-color:rgba(239,68,68,0.3);' : ''}">
            ${isRunning ? '⏹ Stop SFTP' : '▶ Start SFTP'}
          </button>
          <button class="btn-pill-toggle btn-sftp-users-action" id="btn-sftp-header-users" style="background: rgba(14,165,233,0.15); color: var(--zn-text-accent); border-color: rgba(14,165,233,0.3);" title="${t('ui.manage_sftp_users_and_permissions', 'Manage SFTP users and permissions')}">
            👥 Manage Users (${usersCount})
          </button>
        </div>
      </div>

      <div style="display:flex; gap:16px; flex-wrap:wrap; font-size:var(--zn-fs-xs); color:var(--muted); align-items:center;">
        <span>Line-Rate Port: <strong style="color:var(--zn-text-strong);">${port}</strong></span>
        <span>Subsystem: <code style="color:var(--zn-text-accent);">internal-sftp</code></span>
        <span>Isolation: <strong style="color:var(--zn-text-strong);">Chroot Jail (/home/%u)</strong></span>
        <span>Host Shell: <strong style="color:var(--ok2, #22c55e); background:rgba(34,197,94,0.12); padding:1px 6px; border-radius:4px; font-size:var(--zn-fs-xs);">Prohibited (No PTY)</strong></span>
      </div>

      <!-- Quick Connect Grid -->
      <div class="webdav-quickconnect-grid">
        <div class="webdav-qc-item">
          <div class="webdav-qc-label">
            <span>🍏 macOS Finder / Cyberduck</span>
            <button class="btn-qc-copy" data-copy="${escapeHtml(finderCmd)}" title="${t('ui.copy_sftp_url', 'Copy SFTP URL')}">📋 Copy</button>
          </div>
          <div class="webdav-qc-code">
            <span>${escapeHtml(finderCmd)}</span>
          </div>
        </div>

        <div class="webdav-qc-item">
          <div class="webdav-qc-label">
            <span>💻 Terminal / OpenSSH</span>
            <button class="btn-qc-copy" data-copy="${escapeHtml(terminalCmd)}" title="${t('ui.copy_cli_command', 'Copy CLI Command')}">📋 Copy</button>
          </div>
          <div class="webdav-qc-code">
            <span>${escapeHtml(terminalCmd)}</span>
          </div>
        </div>

        <div class="webdav-qc-item">
          <div class="webdav-qc-label">
            <span>📁 FileZilla / WinSCP Client</span>
            <button class="btn-qc-copy" data-copy="${escapeHtml(filezillaHint)}" title="${t('ui.copy_connection_info', 'Copy Connection Info')}">📋 Copy</button>
          </div>
          <div class="webdav-qc-code">
            <span>${escapeHtml(filezillaHint)}</span>
          </div>
        </div>

        <div class="webdav-qc-item">
          <div class="webdav-qc-label">
            <span>📜 SSHFS Mount (Linux/macOS)</span>
            <button class="btn-qc-copy" data-copy="${escapeHtml(sshfsCmd)}" title="${t('ui.copy_sshfs_mount_command', 'Copy SSHFS Mount Command')}">📋 Copy</button>
          </div>
          <div class="webdav-qc-code">
            <span>${escapeHtml(sshfsCmd)}</span>
          </div>
        </div>
      </div>
    </div>
  `;
}

/**
 * Binds interactivity to SFTP Subsystem Server Card
 */
export function bindSftpCardEvents(container, onRefresh) {
  if (!container) return;

  const card = container.querySelector('#mgmt-sftp-subsystem-card');
  if (!card) return;

  const toggleBtn = card.querySelector('.btn-sftp-toggle-action');
  if (toggleBtn) {
    toggleBtn.onclick = async () => {
      toggleBtn.disabled = true;
      try {
        const status = await api.get('/api/sftp/status').catch(() => ({ running: false }));
        const isRunning = Boolean(status.running);
        await api.post('/api/sftp/toggle', { enabled: !isRunning });
        showToast(!isRunning ? t('toast.sftp_started', 'SFTP service started.') : t('toast.sftp_stopped', 'SFTP service stopped.'), 'success');
        if (onRefresh) onRefresh();
      } catch (err) {
        showToast(t('toast.failed_to_toggle_sftp', 'Failed to toggle SFTP: {error}', { error: err.message }), 'error');
        toggleBtn.disabled = false;
      }
    };
  }

  const usersBtn = card.querySelector('.btn-sftp-users-action');
  if (usersBtn) {
    usersBtn.onclick = () => openSftpUsersModal(onRefresh);
  }

  card.querySelectorAll('.btn-qc-copy').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const text = btn.dataset.copy;
      if (text) {
        const ok = await copyTextToClipboard(text);
        if (ok) {
          showToast(t('toast.copied_to_clipboard_3', 'Copied to clipboard!'), 'info');
        } else {
          showToast(t('toast.failed_to_copy_to_clipboard', 'Failed to copy to clipboard'), 'warn');
        }
      }
    };
  });
}

/**
 * Fetches and renders Network Shares & Protocols
 */
/** The sharing-protocol pills show what each service is doing now, never a fixed "Active" (UX-4). */
export function renderProtocolPills({ smb, sftp, webdav } = {}) {
  const set = (id, label, status, port) => {
    const el = document.getElementById(id);
    if (!el) return;
    const state = !status ? 'unknown' : status.running ? 'on' : 'off';
    const word = state === 'on' ? t('proto.on', 'on') : state === 'off' ? t('proto.off', 'off') : t('proto.unknown', 'unknown');
    el.dataset.state = state;
    el.textContent = `${label}${state === 'on' && port ? ` :${port}` : ''} · ${word}`;
  };
  set('proto-pill-smb', 'SMB', smb, null);
  set('proto-pill-sftp', 'SFTP', sftp, sftp?.port);
  set('proto-pill-webdav', 'WebDAV', webdav, webdav?.port);
}

export async function fetchAndRenderNetworkShares(container) {
  if (!container) return;
  container.innerHTML = `
    <div style="text-align:center; padding:30px; color:var(--muted);">
      <div class="loader-spinner" style="margin:0 auto 10px;"></div>
      Auditing network shares and protocols...
    </div>
  `;

  try {
    const [sharesData, platformData, sftpStatus, sftpUsersRes, sambaStatus, webdavStatus] = await Promise.all([
      api.get('/api/storage/shares'),
      api.get('/api/storage/platform').catch(() => ({})),
      api.get('/api/sftp/status').catch(() => ({ running: false, port: 2222 })),
      api.get('/api/sftp/users').catch(() => []),
      api.get('/api/samba/status').catch(() => null),
      api.get('/api/webdav/status').catch(() => null),
    ]);
    _shareServices = { smb: sambaStatus, webdav: webdavStatus, sftp: sftpStatus };
    renderProtocolPills({ smb: sambaStatus, sftp: sftpStatus, webdav: webdavStatus });

    const shares = sharesData.shares || [];
    const isObserver = sharesData.is_observer_mode ?? true;
    const platform = platformData.platform || sharesData.platform || 'unraid';
    const canManageShares = platformData?.capabilities?.can_manage_shares ?? (!isObserver);

    const sftpUsers = Array.isArray(sftpUsersRes) ? sftpUsersRes : (sftpUsersRes?.users || []);
    const sampleUser = sftpUsers[0]?.username || 'admin';

    const btnCreateShare = document.getElementById('btn-create-network-share');
    if (btnCreateShare) {
      btnCreateShare.style.display = canManageShares ? 'inline-flex' : 'none';
      btnCreateShare.onclick = () => openCreateNetworkShareModal(() => fetchAndRenderNetworkShares(container));
    }

    // Update platform badge in pane header
    const badge = document.getElementById('mgmt-shares-platform-badge');
    if (badge) {
      if (isObserver) {
        badge.textContent = t('storage.mode_host', 'Managed by {platform}', { platform: platformName(platform) });
        badge.title = t('storage.mode_host_desc', '{platform} manages the storage pools, array and parity checks here. ZettNAS shows them and never changes them.', { platform: platformName(platform) });
        badge.style.background = 'rgba(59,245,139,0.12)';
        badge.style.color = '#3bf58b';
      } else {
        badge.textContent = t('storage.mode_zettnas', 'Managed by ZettNAS');
        badge.title = t('storage.mode_zettnas_desc', 'ZettNAS manages the storage pools, RAID protection against bit rot, and snapshots on this machine.');
        badge.style.background = 'rgba(99,102,241,0.15)';
        badge.style.color = 'var(--lt-t-818cf8ff, #818cf8)';
      }
    }

    let sftpCard = container.querySelector('#mgmt-sftp-subsystem-card');
    let grid = container.querySelector('.storage-shares-grid');
    if (!grid || !sftpCard) {
      container.innerHTML = `
        ${buildSftpCardHtml(sftpStatus, sftpUsers.length, sampleUser)}
        <div class="storage-shares-grid"></div>
      `;
      grid = container.querySelector('.storage-shares-grid');
      bindSftpCardEvents(container, () => fetchAndRenderNetworkShares(container));
    } else {
      const tempWrapper = document.createElement('div');
      tempWrapper.innerHTML = buildSftpCardHtml(sftpStatus, sftpUsers.length, sampleUser);
      const newCard = tempWrapper.firstElementChild;
      if (newCard && sftpCard.parentNode) {
        sftpCard.parentNode.replaceChild(newCard, sftpCard);
        bindSftpCardEvents(container, () => fetchAndRenderNetworkShares(container));
      }
    }

    if (shares.length === 0) {
      grid.innerHTML = emptyStateHtml({
        icon: '<svg viewBox="0 0 24 24" width="32" height="32"><use href="#i-storage"/></svg>',
        title: t('mgmt.shares_none_title', 'No shares yet'),
        body: canManageShares
          ? t('mgmt.shares_none_desc', 'A share is a folder your computers and phones can open over the network (SMB for Windows and Mac, NFS for Linux).')
          : t('mgmt.shares_none_observer', 'Shares are managed by the host system here; any it creates appear in this list.'),
        action: canManageShares ? { id: 'btn-empty-create-share', label: t('mgmt.create_share', 'Create share') } : null,
      });
      const emptyCreateBtn = grid.querySelector('#btn-empty-create-share');
      if (emptyCreateBtn) {
        emptyCreateBtn.onclick = () => openCreateNetworkShareModal(() => fetchAndRenderNetworkShares(container));
      }
      return;
    }

    bindSharesGridEvents(grid, container);

    reconcileKeyedTable(
      grid,
      shares,
      (s) => s.name,
      (s) => {
        const card = document.createElement('div');
        card.className = 'storage-share-card';
        card.dataset.key = s.name;
        card.dataset.share = s.name;
        card.innerHTML = buildShareCardInner(s, canManageShares);
        return card;
      },
      (card, s) => {
        updateShareCard(card, s, canManageShares);
      }
    );
  } catch (err) {
    console.error('[ZettNAS] Failed to fetch network shares:', err);
    container.innerHTML = `
      <div style="text-align:center; padding:30px; color:var(--alert, var(--lt-t-ef4444ff, #ef4444));">
        Failed to audit network shares: ${escapeHtml(err.message || 'Unknown error')}
      </div>
    `;
  }
}

let _shareServices = {};

const PLATFORM_NAMES = { unraid: 'Unraid', truenas: 'TrueNAS', truenas_scale: 'TrueNAS SCALE', omv: 'OpenMediaVault', openmediavault: 'OpenMediaVault', synology: 'Synology DSM', qnap: 'QNAP', proxmox: 'Proxmox', generic_linux: 'Linux' };
/** A platform id as people know it: "unraid" is Unraid. */
export function platformName(id) {
  const k = String(id || '').toLowerCase();
  return PLATFORM_NAMES[k] || (k ? k.charAt(0).toUpperCase() + k.slice(1) : 'the host');
}

/**
 * Protocol tags for a share that say whether each service really serves it (UX-11):
 * on, off for this share, or turned on but not running.
 */
export function shareProtocolTags(s, services = {}) {
  const tag = (label, state, why) => `<span class="proto-tag proto-${state}" title="${escapeHtml(why)}">${escapeHtml(label)}</span>`;
  const svc = (status) => (status ? (status.running ? 'on' : 'down') : 'unknown');
  const out = [];
  const smb = svc(services.smb);
  if (!s.export_smb) out.push(tag('SMB', 'off', t('share.proto_not_shared', 'Not shared over {proto}', { proto: 'SMB' })));
  else if (smb === 'down') out.push(tag('SMB', 'down', t('share.proto_down', '{proto} is turned on for this share but its service is not running', { proto: 'SMB' })));
  else out.push(tag('SMB', 'on', t('share.proto_on', 'Shared over {proto}', { proto: 'SMB' })));
  out.push(s.export_nfs
    ? tag('NFS', 'on', t('share.proto_on', 'Shared over {proto}', { proto: 'NFS' }))
    : tag('NFS', 'off', t('share.proto_not_shared', 'Not shared over {proto}', { proto: 'NFS' })));
  const dav = services.webdav;
  if (dav && dav.running) out.push(tag(`WebDAV :${dav.port}`, 'on', t('share.proto_on', 'Shared over {proto}', { proto: 'WebDAV' })));
  else if (dav && dav.enabled) out.push(tag('WebDAV', 'down', t('share.proto_service_down', '{proto} is turned on but not running', { proto: 'WebDAV' })));
  else if (dav) out.push(tag('WebDAV', 'off', t('share.proto_service_off', '{proto} is turned off', { proto: 'WebDAV' })));
  const sftp = services.sftp;
  if (sftp && sftp.running) out.push(tag(`SFTP :${sftp.port}`, 'on', t('share.proto_on', 'Shared over {proto}', { proto: 'SFTP' })));
  else if (sftp) out.push(tag('SFTP', 'off', t('share.proto_service_off', '{proto} is turned off', { proto: 'SFTP' })));
  return out.join('\n      ');
}

function buildShareCardInner(s, canManageShares) {
  const usedStr = formatBytes(s.used_bytes);
  const totalStr = formatBytes(s.total_bytes);
  const freeStr = formatBytes(s.free_bytes);
  const pct = s.used_pct || 0;
  const barColor = pct > 90 ? 'var(--alert, #ef4444)' : (pct > 75 ? 'var(--warn, #f59e0b)' : 'var(--accent, #3bf58b)');

  return `
    <div class="share-card-header">
      <div class="share-title-wrap">
        <span class="share-folder-icon">📁</span>
        <div>
          <span class="share-name">${escapeHtml(s.name)}</span>
          ${s.comment ? `<div class="share-comment">${escapeHtml(s.comment)}</div>` : ''}
        </div>
      </div>
      <span class="share-sec-badge sec-${s.security || 'public'}">${escapeHtml((s.security || 'public').toUpperCase())}</span>
    </div>

    <div class="share-protocols-row">
      ${shareProtocolTags(s, _shareServices)}
      ${s.cache_mode && s.cache_mode !== 'none' ? `
        <span class="share-cache-tag" title="Cache Tiering: ${s.cache_mode}">Cache: ${escapeHtml(s.cache_mode)}${s.cache_pool ? ` (${escapeHtml(s.cache_pool)})` : ''}</span>
      ` : ''}
    </div>

    <div class="share-usage-wrap">
      <div class="share-usage-labels">
        <span class="share-usage-text">${usedStr} / ${totalStr}</span>
        <span class="share-free-text">${pct}% used · ${freeStr} free</span>
      </div>
      <div class="share-progress-track">
        <div class="share-progress-fill" style="width: ${Math.min(100, Math.max(0, pct))}%; background: ${barColor};"></div>
      </div>
    </div>

    <div class="share-card-actions" style="display:flex; justify-content:space-between; align-items:center;">
      <button class="btn-share-reveal" data-path="${escapeHtml(s.mountpoint || '')}" title="${t('ui.open_share_in_file_explorer', 'Open share in File Explorer')}">
        📂 Open in File Explorer
      </button>
      ${canManageShares ? `
        <button class="btn-share-delete btn-pill-toggle is-danger is-small" data-share-name="${escapeHtml(s.name)}" title="${t('ui.delete_network_share', 'Delete network share')}">
          🗑️ Delete
        </button>
      ` : ''}
    </div>
  `;
}

function updateShareCard(card, s, canManageShares) {
  const usedStr = formatBytes(s.used_bytes);
  const totalStr = formatBytes(s.total_bytes);
  const freeStr = formatBytes(s.free_bytes);
  const pct = s.used_pct || 0;
  const barColor = pct > 90 ? 'var(--alert, #ef4444)' : (pct > 75 ? 'var(--warn, #f59e0b)' : 'var(--accent, #3bf58b)');

  const usageText = card.querySelector('.share-usage-text');
  if (usageText) usageText.textContent = `${usedStr} / ${totalStr}`;
  const freeText = card.querySelector('.share-free-text');
  if (freeText) freeText.textContent = `${pct}% used · ${freeStr} free`;
  const fill = card.querySelector('.share-progress-fill');
  if (fill) {
    fill.style.width = `${Math.min(100, Math.max(0, pct))}%`;
    fill.style.background = barColor;
  }
}

function bindSharesGridEvents(grid, container) {
  if (grid._sharesEventsBound) return;
  grid._sharesEventsBound = true;

  grid.addEventListener('click', async (e) => {
    const revealBtn = e.target.closest('.btn-share-reveal');
    if (revealBtn) {
      const path = revealBtn.dataset.path;
      playChirp(720, 0.08, 'triangle');
      ZettEventBus.emit('window:open', { id: 'file-manager-window', path });
      showToast(t('mgmt.opened_share', `Opened share in File Explorer: ${path}`), 'info');
      return;
    }

    const delBtn = e.target.closest('.btn-share-delete');
    if (delBtn) {
      e.stopPropagation();
      const sName = delBtn.dataset.shareName;
      showConfirmToast(
        'Remove Share',
        `Are you sure you want to remove share '${sName}'?`,
        async () => {
          try {
            await api.delete(`/api/storage/shares/${sName}`, { confirmed: true });
            showToast(t('toast.share_removed', 'Share \'{sName}\' removed.', { sName: sName }), 'info');
            fetchAndRenderNetworkShares(container);
          } catch (err) {
            showToast(err.message || 'Failed to delete share', 'error');
          }
        },
        null,
        { okText: t('shares.remove_share', 'Remove Share'), destructive: true, typeToConfirm: sName }
      );
    }
  });
}

export async function openSftpUsersModal(onSuccess) {
  const modal = document.getElementById('modal-sftp-users');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-sftp-close-btn');
  const closeBottomBtn = document.getElementById('modal-sftp-close-bottom-btn');
  const toggleBtn = document.getElementById('btn-sftp-toggle-service');
  const statusText = document.getElementById('sftp-status-text');
  const usersList = document.getElementById('sftp-users-list');
  const copyBtn = document.getElementById('btn-copy-sftp-cmd');
  const addForm = document.getElementById('sftp-add-user-form');
  const quickHint = document.getElementById('sftp-quick-connect-hint');

  function closeModal() {
    modal.style.display = 'none';
    modal.classList.remove('open');
  }

  if (closeBtn) closeBtn.onclick = closeModal;
  if (closeBottomBtn) closeBottomBtn.onclick = closeModal;
  modal.onclick = (e) => {
    if (e.target === modal) closeModal();
  };

  const modalWin = modal.querySelector('.smart-modal-window');
  const modalHdr = modal.querySelector('.smart-modal-header');
  if (modalWin && modalHdr) makeDraggable(modalWin, modalHdr, 'sftp-users');

  const hostIp = window.location.hostname || '127.0.0.1';

  async function refreshSftpUI() {
    try {
      const [status, usersRes] = await Promise.all([
        api.get('/api/sftp/status'),
        api.get('/api/sftp/users').catch(() => []),
      ]);

      const isRunning = Boolean(status?.running);
      if (statusText) {
        statusText.innerHTML = isRunning
          ? `<span style="color:var(--ok2, #22c55e);">● Running</span> on port ${status?.port || 2222}`
          : `<span style="color:var(--muted);">○ Stopped</span> (Port ${status?.port || 2222})`;
      }

      if (toggleBtn) {
        toggleBtn.textContent = isRunning ? 'Stop SFTP' : 'Start SFTP';
        toggleBtn.style.background = isRunning ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)';
        toggleBtn.style.color = isRunning ? '#f87171' : '#4ade80';
        toggleBtn.style.borderColor = isRunning ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)';
        toggleBtn.onclick = async () => {
          toggleBtn.disabled = true;
          try {
            await api.post('/api/sftp/toggle', { enabled: !isRunning });
            showToast(!isRunning ? t('toast.sftp_started', 'SFTP service started.') : t('toast.sftp_stopped', 'SFTP service stopped.'), 'success');
            await refreshSftpUI();
            if (onSuccess) onSuccess();
          } catch (err) {
            showToast(t('toast.failed_to_toggle_sftp', 'Failed to toggle SFTP: {error}', { error: err.message }), 'error');
          } finally {
            toggleBtn.disabled = false;
          }
        };
      }

      const users = Array.isArray(usersRes) ? usersRes : (usersRes?.users || []);
      const sampleUser = users[0]?.username || 'username';
      const port = status?.port || 2222;

      if (quickHint) {
        quickHint.textContent = `sftp -P ${port} ${sampleUser}@${hostIp}`;
      }

      if (copyBtn) {
        copyBtn.onclick = () => {
          copyTextToClipboard(`sftp -P ${port} ${sampleUser}@${hostIp}`);
          showToast(t('toast.sftp_command_copied_to_clipboard', 'SFTP command copied to clipboard.'), 'info');
        };
      }

      if (usersList) {
        if (users.length === 0) {
          usersList.innerHTML = `<div style="text-align:center; padding:16px; color:var(--muted); font-size:var(--zn-fs-xs);">No SFTP users configured yet. Create one below.</div>`;
        } else {
          usersList.innerHTML = users.map((u) => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; border-bottom:1px solid var(--zn-line-5); font-size:var(--zn-fs-xs);">
              <div>
                <span style="font-weight:700; color:var(--zn-text-strong);">${escapeHtml(u.username)}</span>
                <span class="ci-badge" style="margin-left:6px; font-size:var(--zn-fs-xs); background:var(--zn-glaze-6); color:var(--muted); padding:1px 5px; border-radius:3px;">
                  ${u.read_only ? 'Read-Only' : 'Read/Write'}
                </span>
                <div style="font-size:var(--zn-fs-xs); color:var(--muted); font-family:monospace; margin-top:2px;">
                  Chroot: ${escapeHtml(u.home_dir || '/home/' + u.username)}
                </div>
              </div>
              <button class="btn-pill-toggle btn-delete-sftp-user is-danger is-small" data-user="${escapeHtml(u.username)}">
                Delete
              </button>
            </div>
          `).join('');

          usersList.querySelectorAll('.btn-delete-sftp-user').forEach((btn) => {
            btn.onclick = () => {
              const username = btn.dataset.user;
              showConfirmToast(
                'Delete SFTP User',
                `Delete SFTP user '${username}'?`,
                async () => {
                  btn.disabled = true;
                  try {
                    await api.delete(`/api/sftp/users/${username}`);
                    showToast(t('toast.user_deleted', 'User \'{username}\' deleted.', { username: username }), 'info');
                    await refreshSftpUI();
                    if (onSuccess) onSuccess();
                  } catch (err) {
                    showToast(t('toast.failed_to_delete_user', 'Failed to delete user: {error}', { error: err.message }), 'error');
                    btn.disabled = false;
                  }
                },
                null,
                { okText: 'Delete User', cancelText: 'Cancel' }
              );
            };
          });
        }
      }
    } catch (err) {
      console.warn('Failed to load SFTP status/users:', err);
    }
  }

  if (addForm) {
    addForm.onsubmit = async (e) => {
      e.preventDefault();
      const uInput = document.getElementById('sftp-new-username');
      const pInput = document.getElementById('sftp-new-password');
      const roInput = document.getElementById('sftp-new-readonly');
      const username = (uInput?.value || '').trim();
      const password = (pInput?.value || '').trim();
      const read_only = roInput?.checked || false;
      if (!username || !password) return;

      try {
        await api.post('/api/sftp/users', { username, password, read_only });
        showToast(t('toast.sftp_user_created', 'SFTP user \'{username}\' created.', { username: username }), 'success');
        uInput.value = '';
        pInput.value = '';
        await refreshSftpUI();
        if (onSuccess) onSuccess();
      } catch (err) {
        showToast(t('toast.failed_to_create_sftp_user', 'Failed to create SFTP user: {error}', { error: err.message }), 'error');
      }
    };
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
  await refreshSftpUI();
}

/**
 * Fallback Renders Storage Topology Tree (Pool -> VDEVs / Disks -> Datasets)
 */
export function renderStorageTopologyTree(container, disks = [], unraidData = {}) {
  if (!container) return;

  const parityDisks = disks.filter((d) => d.role === 'os' || String(d.dev).includes('parity'));
  const dataDisks = disks.filter((d) => d.role === 'data' || (!String(d.dev).includes('parity') && !String(d.dev).startsWith('nvme')));
  const cacheDisks = disks.filter((d) => d.role === 'cache' || String(d.dev).startsWith('nvme'));

  const arrayStatus = unraidData.state || 'ACTIVE / ONLINE';

  let parityHtml = parityDisks.map((d) => `
    <div class="topo-disk-pill role-parity" data-dev="${d.dev || d.name}">
      <span class="topo-dev">/dev/${d.dev || d.name}</span>
      <span class="topo-role">PARITY</span>
      <span class="topo-temp">${d.temp != null ? d.temp + '°C' : '--'}</span>
    </div>
  `).join('');

  let dataHtml = dataDisks.map((d, i) => `
    <div class="topo-disk-pill role-data" data-dev="${d.dev || d.name}">
      <span class="topo-dev">DISK ${i + 1} (${d.dev || d.name})</span>
      <span class="topo-temp">${d.temp != null ? d.temp + '°C' : '--'}</span>
    </div>
  `).join('');

  let cacheHtml = cacheDisks.map((d) => `
    <div class="topo-disk-pill role-cache" data-dev="${d.dev || d.name}">
      <span class="topo-dev">${d.dev || d.name}</span>
      <span class="topo-role">CACHE</span>
      <span class="topo-temp">${d.temp != null ? d.temp + '°C' : '--'}</span>
    </div>
  `).join('');

  container.innerHTML = `
    <div class="storage-topology-tree">
      <div class="topo-root-node">
        <div class="topo-root-header">
          <svg viewBox="0 0 24 24" width="16" height="16"><use href="#i-storage"/></svg>
          <span class="topo-root-title">STORAGE POOL & TOPOLOGY</span>
          <span class="topo-root-badge">${escapeHtml(arrayStatus)}</span>
        </div>
        <div class="topo-branches">
          ${parityDisks.length > 0 ? `
            <div class="topo-branch-group">
              <div class="topo-branch-label">PARITY PROTECTION (${parityDisks.length})</div>
              <div class="topo-disk-grid">${parityHtml}</div>
            </div>
          ` : ''}
          <div class="topo-branch-group">
            <div class="topo-branch-label">DATA ARRAY POOL (${dataDisks.length} DRIVES)</div>
            <div class="topo-disk-grid">${dataHtml || '<span class="empty-note">No active data drives</span>'}</div>
          </div>
          ${cacheDisks.length > 0 ? `
            <div class="topo-branch-group">
              <div class="topo-branch-label">NVME / SSD CACHE POOL (${cacheDisks.length})</div>
              <div class="topo-disk-grid">${cacheHtml}</div>
            </div>
          ` : ''}
        </div>
      </div>
    </div>
  `;
}

const PROVIDER_ICONS = {
  s3: '⚡',
  b2: '💾',
  drive: '🔺',
  onedrive: '☁️',
  sftp: '🖥️',
  webdav: '📁',
  smb: '🔗',
  dropbox: '📦',
  unknown: '☁️'
};

/**
 * Fetches and renders Universal WebDAV and Cloud Remote Storage Subsystem (Sprint 4)
 */
export async function fetchAndRenderRemoteStorage(container) {
  if (!container) return;
  container.innerHTML = `
    <div style="text-align:center; padding:30px; color:var(--muted);">
      <div class="loader-spinner" style="margin:0 auto 10px;"></div>
      Scanning cloud remotes and WebDAV engine...
    </div>
  `;

  try {
    const [webdavStatus, remotes, sftpStatus, sftpUsersRes] = await Promise.all([
      api.get('/api/webdav/status'),
      api.get('/api/remotes'),
      api.get('/api/sftp/status').catch(() => ({ running: false, port: 2222 })),
      api.get('/api/sftp/users').catch(() => []),
    ]);

    const sftpUsers = Array.isArray(sftpUsersRes) ? sftpUsersRes : (sftpUsersRes?.users || []);
    const sampleUser = sftpUsers[0]?.username || 'admin';

    const isRunning = webdavStatus.running;
    const webdavPillClass = isRunning ? 'running' : 'stopped';
    const webdavPillText = isRunning ? `🟢 RUNNING (PID: ${webdavStatus.pid || 'Active'})` : '⚪ STOPPED';

    const qc = webdavStatus.quick_connect || {};
    const hostIp = window.location.hostname;
    const directUrl = webdavStatus.direct_url || `http://${hostIp}:${webdavStatus.port || 8084}/`;
    const proxyUrl = `${window.location.origin}${webdavStatus.proxy_url || '/webdav/'}`;

    let remotesHtml = '';
    if (!remotes || remotes.length === 0) {
      remotesHtml = `
        <div style="text-align:center; padding:36px 20px; background:var(--zn-shade-25); border:1px dashed var(--zn-line-12); border-radius:10px;">
          <div style="font-size:32px; margin-bottom:8px;">☁️</div>
          <div style="font-size:14px; font-weight:700; color:var(--zn-text-strong); margin-bottom:4px;">No Cloud Remotes Connected</div>
          <div style="font-size:var(--zn-fs-xs); color:var(--muted); max-width:440px; margin:0 auto 16px auto; line-height:1.45;">
            Connect your cloud storage buckets (Amazon S3, Backblaze B2, Google Drive, OneDrive, SFTP) to mount them directly into the ZettNAS File Explorer (/mnt/remotes).
          </div>
          <button class="btn-pill-toggle btn-trigger-new-remote is-primary">
            ☁️ + Connect First Cloud Remote
          </button>
        </div>
      `;
    } else {
      const cards = remotes.map((r) => {
        const icon = PROVIDER_ICONS[r.type] || PROVIDER_ICONS.unknown;
        const isMounted = r.is_mounted;
        const statusText = isMounted ? `🟢 Mounted at ${escapeHtml(r.mount_path)}` : '⚪ Not Mounted';
        const statusCls = isMounted ? 'mounted' : '';

        return `
          <div class="remote-card" data-remote-name="${escapeHtml(r.name)}">
            <div class="remote-card-header">
              <div class="remote-title-wrap">
                <span class="remote-icon">${icon}</span>
                <div>
                  <div class="remote-name">${escapeHtml(r.name)}</div>
                  <div class="remote-mount-status ${statusCls}">${statusText}</div>
                </div>
              </div>
              <span class="remote-type-tag">${escapeHtml(r.type)}</span>
            </div>

            <div style="font-size:var(--zn-fs-xs); color:var(--muted); font-family:monospace; background:var(--zn-shade-30); padding:6px 8px; border-radius:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
              /mnt/remotes/${escapeHtml(r.name)}
            </div>

            <div class="remote-card-actions">
              <div>
                ${isMounted ? `
                  <button class="btn-remote-reveal btn-pill-toggle" data-path="${escapeHtml(r.mount_path)}" title="${t('ui.open_in_file_explorer', 'Open in File Explorer')}" style="background: rgba(14,165,233,0.15); color: var(--zn-text-accent); border-color: rgba(14,165,233,0.3);">
                    📂 Open in File Explorer
                  </button>
                ` : `
                  <button class="btn-remote-mount btn-pill-toggle" data-name="${escapeHtml(r.name)}" title="${t('ui.mount_to_mnt_remotes', 'Mount to /mnt/remotes')}" style="background: var(--lt-b-3bf58b1f, rgba(59,245,139,0.12)); color: var(--lt-t-3bf58bff, #3bf58b); border-color: var(--lt-r-3bf58b40, rgba(59,245,139,0.25));">
                    ▶ Mount
                  </button>
                `}
              </div>
              <div style="display:flex; gap:6px;">
                ${isMounted ? `
                  <button class="btn-remote-unmount btn-pill-toggle" data-name="${escapeHtml(r.name)}" title="${t('ui.unmount_from_system', 'Unmount from system')}">
                    ⏹ Unmount
                  </button>
                ` : ''}
                <button class="btn-remote-delete btn-pill-toggle is-danger" data-name="${escapeHtml(r.name)}" title="${t('ui.delete_remote', 'Delete remote')}">
                  🗑
                </button>
              </div>
            </div>
          </div>
        `;
      }).join('');

      remotesHtml = `
        <div class="remotes-grid">
          ${cards}
        </div>
      `;
    }

    container.innerHTML = `
      <div class="remote-storage-container">
        <!-- Section 1: Universal WebDAV File Server -->
        <div class="webdav-server-card">
          <div class="webdav-card-header">
            <div class="webdav-header-title">
              <svg class="ic" style="width:18px; height:18px; fill:currentColor; color:var(--lt-ink-brand, var(--brand, #0ea5e9));"><use href="#i-globe"/></svg>
              <span>Universal WebDAV File Server</span>
              <span class="webdav-status-pill ${webdavPillClass}">${webdavPillText}</span>
            </div>
            <div style="display:flex; gap:8px; align-items:center;">
              <button class="btn-pill-toggle" id="btn-webdav-toggle">
                ${isRunning ? '⏹ Stop Server' : '▶ Start Server'}
              </button>
              <button class="btn-pill-toggle" id="btn-webdav-restart" title="${t('ui.restart_webdav_server', 'Restart WebDAV Server')}">
                ↺ Restart
              </button>
              <button class="btn-pill-toggle" id="btn-webdav-config-open" title="${t('ui.configure_webdav_settings', 'Configure WebDAV settings')}">
                ⚙️ Settings
              </button>
            </div>
          </div>

          <div style="display:flex; gap:16px; flex-wrap:wrap; font-size:var(--zn-fs-xs); color:var(--muted); align-items:center;">
            <span>Line-Rate Port: <strong style="color:var(--zn-text-strong);">${webdavStatus.port}</strong></span>
            <span>Root Path: <code style="color:var(--zn-text-accent);">${escapeHtml(webdavStatus.root_path)}</code></span>
            <span>Mode: <strong style="color:var(--zn-text-strong);">${webdavStatus.read_only ? 'Read-Only' : 'Read/Write'}</strong></span>
            <span>Auth: <strong style="color:var(--zn-text-strong);">${escapeHtml(t('webdav.auth_accounts', 'ZettNAS accounts'))}</strong></span>
          </div>

          <!-- Quick Connect Grid -->
          <div class="webdav-quickconnect-grid">
            <div class="webdav-qc-item">
              <div class="webdav-qc-label">
                <span>🍏 macOS Finder (⌘K)</span>
                <button class="btn-qc-copy" data-copy="${escapeHtml(qc.macos || '')}" title="${t('ui.copy_command', 'Copy command')}">📋 Copy</button>
              </div>
              <div class="webdav-qc-code">
                <span>${escapeHtml(qc.macos || '')}</span>
              </div>
            </div>

            <div class="webdav-qc-item">
              <div class="webdav-qc-label">
                <span>🪟 Windows Map Network Drive</span>
                <button class="btn-qc-copy" data-copy="${escapeHtml(qc.windows || '')}" title="${t('ui.copy_command', 'Copy command')}">📋 Copy</button>
              </div>
              <div class="webdav-qc-code">
                <span>${escapeHtml(qc.windows || '')}</span>
              </div>
            </div>

            <div class="webdav-qc-item">
              <div class="webdav-qc-label">
                <span>📱 iOS & Android Files</span>
                <button class="btn-qc-copy" data-copy="${escapeHtml(qc.ios || '')}" title="${t('ui.copy_url', 'Copy URL')}">📋 Copy</button>
              </div>
              <div class="webdav-qc-code">
                <span>${escapeHtml(qc.ios || '')}</span>
              </div>
            </div>

            <div class="webdav-qc-item">
              <div class="webdav-qc-label">
                <span>🌐 Toolkit HTTP Reverse Proxy</span>
                <button class="btn-qc-copy" data-copy="${escapeHtml(proxyUrl)}" title="${t('ui.copy_proxy_url', 'Copy Proxy URL')}">📋 Copy</button>
              </div>
              <div class="webdav-qc-code">
                <span>${escapeHtml(proxyUrl)}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Section 2: Inbound SFTP Subsystem -->
        ${buildSftpCardHtml(sftpStatus, sftpUsers.length, sampleUser)}

        <!-- Section 3: Connected Cloud & Remote Drives -->
        <div style="display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-size:13px; font-weight:800; color:var(--zn-text-strong); letter-spacing:0.5px; text-transform:uppercase;">
              Connected Cloud Drives & Buckets (${remotes ? remotes.length : 0})
            </div>
            <button class="btn-pill-toggle btn-trigger-new-remote" style="background: rgba(14,165,233,0.15); color: var(--zn-text-accent); border-color: rgba(14,165,233,0.3);" title="${t('ui.connect_new_cloud_remote', 'Connect New Cloud Remote')}">
              ☁️ + Add Remote
            </button>
          </div>
          ${remotesHtml}
        </div>
      </div>
    `;

    bindSftpCardEvents(container, () => fetchAndRenderRemoteStorage(container));

    // Event bindings
    // WebDAV toggle
    container.querySelector('#btn-webdav-toggle')?.addEventListener('click', async () => {
      playChirp(600, 0.08, 'sine');
      try {
        await api.post('/api/webdav/toggle', { enabled: !isRunning });
        showToast(isRunning ? 'WebDAV server stopped.' : 'WebDAV server started on port ' + webdavStatus.port, 'info');
        fetchAndRenderRemoteStorage(container);
      } catch (e) {
        showToast(t('toast.failed_toggle_webdav', 'Failed to toggle WebDAV: {error}', { error: e.message || t('toast.unknown_error', 'Unknown error') }), 'error');
      }
    });

    // WebDAV restart
    container.querySelector('#btn-webdav-restart')?.addEventListener('click', async () => {
      playChirp(700, 0.08, 'sine');
      try {
        await api.post('/api/webdav/restart');
        showToast(t('toast.webdav_server_restarted', 'WebDAV server restarted.'), 'info');
        fetchAndRenderRemoteStorage(container);
      } catch (e) {
        showToast(t('toast.failed_restart_webdav', 'Failed to restart WebDAV: {error}', { error: e.message || t('toast.unknown_error', 'Unknown error') }), 'error');
      }
    });

    // WebDAV settings modal open
    container.querySelector('#btn-webdav-config-open')?.addEventListener('click', () => {
      playChirp(640, 0.08, 'triangle');
      openWebdavConfigModal(webdavStatus, () => fetchAndRenderRemoteStorage(container));
    });

    // Quick Connect copy buttons
    container.querySelectorAll('.btn-qc-copy').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const text = btn.dataset.copy;
        if (text) {
          const ok = await copyTextToClipboard(text);
          playChirp(880, 0.08, 'triangle');
          if (ok) {
            showToast(t('toast.copied_to_clipboard_3', 'Copied to clipboard!'), 'info');
          } else {
            showToast(t('toast.failed_to_copy_to_clipboard', 'Failed to copy to clipboard'), 'warn');
          }
        }
      });
    });

    // "+ Connect First Cloud Remote" CTA button(s)
    container.querySelectorAll('.btn-trigger-new-remote').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        playChirp(640, 0.08, 'triangle');
        openNewCloudRemoteModal(() => fetchAndRenderRemoteStorage(container));
      });
    });

    // Open in File Explorer
    container.querySelectorAll('.btn-remote-reveal').forEach((btn) => {
      btn.addEventListener('click', () => {
        const path = btn.dataset.path || `/mnt/remotes/${btn.dataset.name || ''}`;
        playChirp(720, 0.08, 'triangle');
        ZettEventBus.emit('window:open', { id: 'file-manager-window', path });
        ZettEventBus.emit('fm:refresh');
        showToast(t('toast.opened_in_file_explorer', 'Opened {path} in File Explorer', { path: path }), 'info');
      });
    });

    // Mount remote
    container.querySelectorAll('.btn-remote-mount').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const name = btn.dataset.name;
        btn.textContent = t('ui.mounting', 'Mounting...');
        btn.disabled = true;
        try {
          await api.post(`/api/remotes/${name}/mount`, {});
          playChirp(800, 0.1, 'sine');
          showToast(t('toast.remote_mounted_to_mnt_remotes', 'Remote \'{name}\' mounted to /mnt/remotes/{name}', { name: name }), 'info');
          fetchAndRenderRemoteStorage(container);
          ZettEventBus.emit('fm:refresh');
          ZettEventBus.emit('storage:mount_changed', { name, path: `/mnt/remotes/${name}`, action: 'mount' });
        } catch (e) {
          showToast(t('toast.mount_failed', 'Mount failed: {message}', { message: e.message || 'Error' }), 'error');
          fetchAndRenderRemoteStorage(container);
        }
      });
    });

    // Unmount remote
    container.querySelectorAll('.btn-remote-unmount').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const name = btn.dataset.name;
        btn.textContent = t('ui.unmounting', 'Unmounting...');
        btn.disabled = true;
        try {
          await api.post(`/api/remotes/${name}/unmount`);
          playChirp(500, 0.1, 'sine');
          showToast(t('toast.remote_unmounted', 'Remote \'{name}\' unmounted.', { name: name }), 'info');
          fetchAndRenderRemoteStorage(container);
          ZettEventBus.emit('fm:refresh');
          ZettEventBus.emit('storage:mount_changed', { name, path: `/mnt/remotes/${name}`, action: 'unmount' });
        } catch (e) {
          showToast(t('toast.unmount_failed', 'Unmount failed: {message}', { message: e.message || 'Error' }), 'error');
          fetchAndRenderRemoteStorage(container);
        }
      });
    });

    // Delete remote
    container.querySelectorAll('.btn-remote-delete').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const name = btn.dataset.name;
        showConfirmToast(
          t('remotes.delete_confirm_title', 'Delete Cloud Remote'),
          t('remotes.delete_confirm_msg', `Are you sure you want to remove remote '${name}'? This will unmount the filesystem and delete its stored credentials.`).replace('{name}', escapeHtml(name)),
          async () => {
            try {
              await api.delete(`/api/remotes/${name}`);
              playChirp(440, 0.1, 'sawtooth');
              showToast(t('remotes.deleted', `Remote '${name}' deleted successfully.`), 'info');
              fetchAndRenderRemoteStorage(container);
              ZettEventBus.emit('fm:refresh');
              ZettEventBus.emit('storage:mount_changed', { name, path: `/mnt/remotes/${name}`, action: 'delete' });
            } catch (err) {
              showToast(t('remotes.delete_failed', `Failed to delete remote: ${err.message || 'Error'}`), 'error');
            }
          },
          null,
          {
            okText: t('remotes.delete_btn', '🗑️ Delete Remote'),
            cancelText: t('common.cancel', 'Cancel'),
            icon: '🗑️'
          }
        );
      });
    });

  } catch (err) {
    console.error('[ZettNAS] Failed to fetch remote storage:', err);
    container.innerHTML = `
      <div style="text-align:center; padding:30px; color:var(--alert, var(--lt-t-ef4444ff, #ef4444));">
        Failed to load remote storage subsystem: ${escapeHtml(err.message || 'Unknown error')}
      </div>
    `;
  }
}

export function openWebdavConfigModal(currentConfig, onSuccess) {
  const modal = document.getElementById('modal-webdav-config');
  if (!modal) return;

  const portInput = document.getElementById('webdav-cfg-port');
  const rootInput = document.getElementById('webdav-cfg-root');
  const userInput = document.getElementById('webdav-cfg-user');
  const passInput = document.getElementById('webdav-cfg-pass');
  const roToggle = document.getElementById('webdav-cfg-readonly-toggle');

  if (portInput) portInput.value = currentConfig?.port || 8084;
  if (rootInput) rootInput.value = currentConfig?.root_path || '/mnt/user';
  if (userInput) userInput.value = currentConfig?.username || 'admin';
  if (passInput) passInput.value = '';
  if (roToggle) roToggle.checked = currentConfig?.read_only ?? false;

  modal.classList.add('open');
  modal.style.display = 'flex';

  const close = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  };
  const cBtn = document.getElementById('modal-webdav-close-btn');
  const canBtn = document.getElementById('modal-webdav-cancel-btn');
  if (cBtn) cBtn.onclick = close;
  if (canBtn) canBtn.onclick = close;

  const form = document.getElementById('webdav-config-form');
  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      const payload = {
        port: Number(portInput.value),
        root_path: rootInput.value.trim(),
        username: userInput.value.trim(),
        read_only: roToggle.checked
      };
      if (passInput.value.trim()) {
        payload.password = passInput.value.trim();
      }
      try {
        await api.post('/api/webdav/config', payload);
        close();
        playChirp(880, 0.1, 'sine');
        showToast(t('toast.webdav_configuration_saved_and_server_restarted', 'WebDAV configuration saved and server restarted!'), 'info');
        if (onSuccess) onSuccess();
      } catch (err) {
        showToast(t('toast.error_saving_webdav', 'Error saving WebDAV config: {error}', { error: err.message || t('toast.unknown_error', 'Unknown error') }), 'error');
      }
    };
  }
}

let _providersCache = null;

export async function openNewCloudRemoteModal(onSuccess) {
  const modal = document.getElementById('modal-new-cloud-remote');
  if (!modal) return;

  const winEl = document.getElementById('cloud-remote-window') || modal.querySelector('.smart-modal-window');
  const headerEl = document.getElementById('cloud-remote-window-header') || modal.querySelector('.smart-modal-header');
  const providerSelect = document.getElementById('new-remote-provider-select');
  const descEl = document.getElementById('new-remote-provider-desc');
  const dynamicFields = document.getElementById('new-remote-dynamic-fields');
  const nameInput = document.getElementById('new-remote-name');
  const autoMountToggle = document.getElementById('new-remote-auto-mount');
  const errorBox = document.getElementById('new-remote-error-box');
  const testResult = document.getElementById('new-remote-test-result');
  const testBtn = document.getElementById('new-remote-test-btn');

  if (errorBox) errorBox.style.display = 'none';
  if (testResult) testResult.style.display = 'none';
  if (nameInput) nameInput.value = '';
  if (testBtn) {
    testBtn.classList.remove('tested-green');
    testBtn.disabled = false;
    testBtn.innerHTML = '<span>⚡ Test Connection</span>';
  }

  // Register with DockManager as a real desktop window
  if (typeof DockManager !== 'undefined' && DockManager.register) {
    DockManager.register('cloud-remote', modal, '#i-cloud', 'Cloud Remotes', false);
    if (typeof DockManager.restore === 'function') {
      DockManager.restore('cloud-remote');
    }
  }
  modal.classList.remove('window-minimized');
  modal.classList.add('open');
  modal.style.removeProperty('display');
  modal.style.setProperty('display', 'flex', 'important');

  if (winEl) {
    winEl.classList.remove('window-minimized');
    winEl.style.removeProperty('display');
    bringToFront(winEl);
    bringToFront(modal);
    winEl.addEventListener('pointerdown', () => {
      bringToFront(winEl);
      bringToFront(modal);
    });
  }
  if (winEl && headerEl) {
    makeDraggable(winEl, headerEl, 'cloud-remote');
  }

  let _currentOAuthSession = null;
  let _oauthPollTimer = null;
  let _focusListener = null;

  const close = () => {
    if (_oauthPollTimer) {
      clearInterval(_oauthPollTimer);
      _oauthPollTimer = null;
    }
    if (_focusListener && typeof window !== 'undefined' && window.removeEventListener) {
      window.removeEventListener('focus', _focusListener);
      _focusListener = null;
    }
    if (_currentOAuthSession && _currentOAuthSession.session_id) {
      api.delete(`/api/remotes/oauth/${_currentOAuthSession.session_id}`).catch(() => {});
      _currentOAuthSession = null;
    }
    if (typeof DockManager !== 'undefined' && DockManager.unregister) {
      DockManager.unregister('cloud-remote');
    }
    modal.classList.remove('open');
    modal.classList.add('window-minimized');
    modal.style.setProperty('display', 'none', 'important');
    if (winEl) {
      winEl.classList.add('window-minimized');
      winEl.style.setProperty('display', 'none', 'important');
    }
  };

  const cBtn = document.getElementById('modal-remote-close-btn');
  const canBtn = document.getElementById('modal-remote-cancel-btn');
  if (cBtn) cBtn.onclick = close;
  if (canBtn) canBtn.onclick = close;

  // Minimize button
  const minBtn = document.getElementById('modal-remote-min-btn');
  if (minBtn) {
    minBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (typeof DockManager !== 'undefined' && DockManager.minimize) {
        DockManager.minimize('cloud-remote');
      } else {
        close();
      }
    };
  }

  // Maximize / Restore toggle
  const maxBtn = document.getElementById('modal-remote-max-btn');
  const toggleMaximize = () => {
    if (!winEl) return;
    const isMax = winEl.dataset.maximized === 'true';
    if (isMax) {
      winEl.dataset.maximized = 'false';
      winEl.style.width = winEl.dataset.prevWidth || '';
      winEl.style.height = winEl.dataset.prevHeight || '';
      winEl.style.top = winEl.dataset.prevTop || '';
      winEl.style.left = winEl.dataset.prevLeft || '';
      winEl.style.transform = winEl.dataset.prevTransform || '';
    } else {
      winEl.dataset.prevWidth = winEl.style.width;
      winEl.dataset.prevHeight = winEl.style.height;
      winEl.dataset.prevTop = winEl.style.top;
      winEl.dataset.prevLeft = winEl.style.left;
      winEl.dataset.prevTransform = winEl.style.transform;
      winEl.dataset.maximized = 'true';
      winEl.style.top = '50%';
      winEl.style.left = '50%';
      winEl.style.transform = 'translate(-50%, -50%)';
    }
  };
  if (maxBtn) maxBtn.onclick = toggleMaximize;
  if (headerEl) {
    headerEl.ondblclick = (e) => {
      if (e.target.closest('.os-window-controls')) return;
      toggleMaximize();
    };
  }

  try {
    if (!_providersCache) {
      _providersCache = await api.get('/api/remotes/providers');
    }
    const providers = _providersCache || [];

    if (providerSelect) {
      providerSelect.innerHTML = providers.map((p) => `
        <option value="${p.type}">${p.name} (${p.category})</option>
      `).join('');

      const renderFields = () => {
        if (_oauthPollTimer) {
          clearInterval(_oauthPollTimer);
          _oauthPollTimer = null;
        }
        if (_focusListener && typeof window !== 'undefined' && window.removeEventListener) {
          window.removeEventListener('focus', _focusListener);
          _focusListener = null;
        }
        if (_currentOAuthSession && _currentOAuthSession.session_id) {
          api.delete(`/api/remotes/oauth/${_currentOAuthSession.session_id}`).catch(() => {});
          _currentOAuthSession = null;
        }

        const selectedType = providerSelect.value;
        const prov = providers.find((p) => p.type === selectedType) || providers[0];
        if (descEl) descEl.textContent = prov ? prov.description || '' : '';
        if (testResult) testResult.style.display = 'none';
        if (errorBox) errorBox.style.display = 'none';

        if (dynamicFields && prov) {
          const isOAuthProv = prov.type === 'onedrive' || prov.type === 'drive' || prov.type === 'dropbox' || prov.type === 'box' || Boolean(prov.authorize_cmd);
          const provTitle = prov.type === 'onedrive'
            ? 'Microsoft OneDrive'
            : (prov.type === 'drive'
              ? 'Google Drive'
              : (prov.type === 'dropbox'
                ? 'Dropbox'
                : (prov.type === 'box' ? 'Box.com' : prov.name)));
          const brandBtnLabel = prov.type === 'onedrive'
            ? '1-Click Authorize with Microsoft'
            : (prov.type === 'drive'
              ? '1-Click Authorize with Google'
              : (prov.type === 'dropbox'
                ? '1-Click Authorize with Dropbox'
                : (prov.type === 'box'
                  ? '1-Click Authorize with Box'
                  : `1-Click Authorize with ${prov.name}`)));

          const oauthAssistantHtml = isOAuthProv ? `
            <div class="oauth-assistant-card" style="margin-bottom: 16px; padding: 14px 16px; background: rgba(14, 165, 233, 0.08); border: 1px solid rgba(14, 165, 233, 0.28); border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.25);">
              <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; border-bottom: 1px solid var(--zn-line-6); padding-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="font-size: 18px;">🔑</span>
                  <span style="font-size: 13px; font-weight: 700; color: var(--zn-text-strong); letter-spacing: 0.3px;">Connect ${escapeHtml(provTitle)}</span>
                </div>
                <span style="font-size: var(--zn-fs-xs); padding: 2px 8px; background: rgba(34, 197, 94, 0.15); color: var(--lt-t-4ade80ff, #4ade80); border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 12px; font-weight: 600;">
                  No Terminal Required · In-App OAuth
                </span>
              </div>

              <!-- Auth Mode Switcher (Tabs) -->
              <div style="display: flex; gap: 6px; margin-bottom: 12px; background: var(--zn-shade-30); padding: 3px; border-radius: 6px; border: 1px solid var(--zn-line-6);">
                <button type="button" id="tab-oauth-desktop" style="flex: 1; padding: 6px 10px; font-size: var(--zn-fs-xs); font-weight: 700; border-radius: 4px; border: none; cursor: pointer; background: #0284c7; color: #fff; display: flex; align-items: center; justify-content: center; gap: 6px; transition: all 0.15s;">
                  <span>💻 Desktop 1-Click</span>
                </button>
                <button type="button" id="tab-oauth-qr" class="btn-pill-toggle is-ghost is-small" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;">
                  <span>📱 Mobile QR Code</span>
                </button>
              </div>

              <!-- Step 1: Desktop Panel -->
              <div id="oauth-desktop-panel">
                <button type="button" id="btn-oauth-browser" style="width: 100%; display: flex; align-items: center; justify-content: center; gap: 8px; padding: 11px 16px; background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%); border: 1px solid var(--zn-line-20); color: #fff; border-radius: 7px; font-size: var(--zn-fs-xs); font-weight: 700; cursor: pointer; box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35); transition: all 0.2s;">
                  <span>🌐 ${escapeHtml(brandBtnLabel)}</span>
                </button>

                <div style="margin-top: 8px; margin-bottom: 12px; padding: 8px 10px; background: rgba(14, 165, 233, 0.07); border: 1px dashed rgba(14, 165, 233, 0.28); border-radius: 6px; font-size: var(--zn-fs-xs); color: var(--zn-text-soft); line-height: 1.45;">
                  <strong style="color: var(--zn-text-accent);">📌 What to expect:</strong> After approving login in Microsoft, the new tab will show <code style="color:var(--zn-text-crit); background:rgba(239,68,68,0.15); padding:1px 4px; border-radius:3px;">This site can't be reached (localhost:53682)</code>. <strong>This is completely normal!</strong> Simply copy the address bar from that tab and paste it in Step 2 below.
                </div>
              </div>

              <!-- Step 1: Mobile QR Code Panel -->
              <div id="oauth-qr-panel" style="display: none; margin-bottom: 12px;">
                <div id="oauth-qr-box" style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 12px; background: var(--zn-shade-35); border: 1px dashed rgba(14, 165, 233, 0.35); border-radius: 8px;">
                  <div id="oauth-qr-target" style="display: inline-flex; align-items: center; justify-content: center; padding: 8px; background: #ffffff; border-radius: 8px; min-width: 140px; min-height: 140px; box-shadow: 0 4px 14px rgba(0,0,0,0.6);">
                    <div style="font-size: var(--zn-fs-xs); color: var(--lt-t-0284c7ff, #0284c7); font-weight: 600;">⏳ Initializing QR code...</div>
                  </div>
                  <div style="font-size: var(--zn-fs-xs); font-weight: 600; color: var(--zn-text); margin-top: 8px; display: flex; align-items: center; gap: 6px;">
                    <span>📱 Scan with your phone or tablet camera to sign in</span>
                    <button type="button" id="btn-oauth-qr" class="btn-pill-toggle is-small" title="${t('ui.refresh_qr_code', 'Refresh QR Code')}">🔄 Refresh</button>
                  </div>
                </div>
              </div>

              <!-- Status feedback pill -->
              <div id="oauth-assistant-status" style="display: none; margin-bottom: 12px; padding: 8px 12px; border-radius: 6px; font-size: var(--zn-fs-xs); line-height: 1.45;"></div>

              <!-- Step 2: Code Relay Input & Complete button -->
              <div id="oauth-step2-box" style="padding-top: 12px; border-top: 1px solid var(--zn-line-8);">
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text); margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                  <span style="color: var(--zn-text-accent);">Step 2:</span>
                  <span>If browser says "This site can't be reached", paste the resulting URL from your address bar here:</span>
                </div>
                <div style="font-size: var(--zn-fs-xs); color: var(--zn-text-muted); line-height: 1.45; margin-bottom: 8px;">
                  When Microsoft/Google finishes logging in, copy the full address from your browser address bar and paste it below:
                </div>
                <div style="display: flex; gap: 6px;">
                  <input type="text" id="oauth-redirect-url" class="tz-select-input" placeholder="http://localhost:53682/?code=M.R3_... or full redirect URL" style="flex: 1; font-family: monospace; font-size: var(--zn-fs-xs);" />
                  <button type="button" id="btn-oauth-paste" class="btn-pill-toggle is-small" style="white-space: nowrap;">
                    📋 Paste
                  </button>
                </div>
                <button type="button" id="btn-oauth-exchange" style="margin-top: 10px; width: 100%; padding: 10px 14px; background: var(--ok2, #22c55e); color: var(--zn-text-strong); font-size: var(--zn-fs-xs); font-weight: 700; border: none; border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 4px 14px rgba(34, 197, 94, 0.3);">
                  <span>✓ Complete & Populate Token</span>
                </button>
              </div>
            </div>
          ` : '';

          const fieldsHtml = (prov.fields || []).map((f) => {
            if (f.type === 'select') {
              const opts = (f.options || []).map((o) => `<option value="${o}" ${o === f.default ? 'selected' : ''}>${o}</option>`).join('');
              return `
                <div>
                  <label style="display:block; font-size:var(--zn-fs-xs); font-weight:700; color:var(--zn-text-muted); margin-bottom:4px; letter-spacing:0.5px;">${escapeHtml(f.label.toUpperCase())}</label>
                  <select name="${escapeHtml(f.name)}" class="tz-select-input" style="width:100%;">
                    ${opts}
                  </select>
                </div>
              `;
            } else if (f.type === 'textarea') {
              return `
                <div>
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                    <label style="display:block; font-size:var(--zn-fs-xs); font-weight:700; color:var(--zn-text-muted); letter-spacing:0.5px;">
                      ${escapeHtml(f.label.toUpperCase())} ${f.required ? '<span style="color:var(--crit,#ef4444);">*</span>' : ''}
                    </label>
                    ${prov.authorize_cmd ? `
                      <button type="button" class="remote-copy-cmd-btn" data-cmd="${escapeHtml(prov.authorize_cmd)}" style="background:rgba(14,165,233,0.15); border:1px solid rgba(14,165,233,0.3); color:var(--zn-text-accent); font-size:var(--zn-fs-xs); font-weight:600; padding:2px 8px; border-radius:4px; cursor:pointer;">
                        📋 Copy: ${escapeHtml(prov.authorize_cmd)}
                      </button>
                    ` : ''}
                  </div>
                  <textarea
                    name="${escapeHtml(f.name)}"
                    placeholder="${escapeHtml(f.placeholder || '')}"
                    class="tz-select-input"
                    rows="4"
                    style="width:100%; font-family:monospace; resize:vertical;"
                    ${f.required ? 'required' : ''}>${escapeHtml(f.default != null ? String(f.default) : '')}</textarea>
                  ${f.help ? `<div style="font-size:var(--zn-fs-xs); color:var(--zn-text-muted); margin-top:4px; line-height:1.4;">${escapeHtml(f.help)}</div>` : ''}
                </div>
              `;
            } else {
              return `
                <div>
                  <label style="display:block; font-size:var(--zn-fs-xs); font-weight:700; color:var(--zn-text-muted); margin-bottom:4px; letter-spacing:0.5px;">
                    ${escapeHtml(f.label.toUpperCase())} ${f.required ? '<span style="color:var(--crit,#ef4444);">*</span>' : ''}
                  </label>
                  <input type="${f.type === 'password' ? 'password' : 'text'}"
                    name="${escapeHtml(f.name)}"
                    placeholder="${escapeHtml(f.placeholder || '')}"
                    value="${escapeHtml(f.default != null ? String(f.default) : '')}"
                    class="tz-select-input"
                    style="width:100%;"
                    ${f.required ? 'required' : ''} />
                </div>
              `;
            }
          }).join('');

          dynamicFields.innerHTML = oauthAssistantHtml + fieldsHtml;

          // Bind OAuth Assistant if present
          if (isOAuthProv) {
            const browserBtn = dynamicFields.querySelector('#btn-oauth-browser');
            const qrBtn = dynamicFields.querySelector('#btn-oauth-qr');
            const pasteBtn = dynamicFields.querySelector('#btn-oauth-paste');
            const exchangeBtn = dynamicFields.querySelector('#btn-oauth-exchange');
            const urlInput = dynamicFields.querySelector('#oauth-redirect-url');
            const statusEl = dynamicFields.querySelector('#oauth-assistant-status');
            const qrBox = dynamicFields.querySelector('#oauth-qr-box');
            const qrTarget = dynamicFields.querySelector('#oauth-qr-target');
            const step2Box = dynamicFields.querySelector('#oauth-step2-box');
            const tabDesktop = dynamicFields.querySelector('#tab-oauth-desktop');
            const tabQr = dynamicFields.querySelector('#tab-oauth-qr');
            const desktopPanel = dynamicFields.querySelector('#oauth-desktop-panel');
            const qrPanel = dynamicFields.querySelector('#oauth-qr-panel');

            if (tabDesktop && tabQr) {
              tabDesktop.onclick = () => {
                tabDesktop.style.background = '#0284c7';
                tabDesktop.style.color = '#fff';
                tabQr.style.background = 'transparent';
                tabQr.style.color = '#94a3b8';
                if (desktopPanel) desktopPanel.style.display = 'block';
                if (qrPanel) qrPanel.style.display = 'none';
              };
              tabQr.onclick = () => {
                tabQr.style.background = '#0284c7';
                tabQr.style.color = '#fff';
                tabDesktop.style.background = 'transparent';
                tabDesktop.style.color = '#94a3b8';
                if (desktopPanel) desktopPanel.style.display = 'none';
                if (qrPanel) qrPanel.style.display = 'block';
                if (qrBox) qrBox.style.display = 'block';
                startOAuth(true);
              };
            }

            const applyAcquiredToken = (token, drive_id = '', drive_type = 'personal') => {
              const tokenArea = dynamicFields.querySelector('textarea[name="token"]');
              if (tokenArea) {
                tokenArea.value = token;
                tokenArea.dispatchEvent(new Event('input', { bubbles: true }));
              }
              const driveType = dynamicFields.querySelector('select[name="drive_type"]');
              if (driveType) {
                driveType.value = drive_type || 'personal';
                driveType.dispatchEvent(new Event('change', { bubbles: true }));
              }
              const driveIdInput = dynamicFields.querySelector('input[name="drive_id"]');
              if (driveIdInput && drive_id) {
                driveIdInput.value = drive_id;
                driveIdInput.dispatchEvent(new Event('input', { bubbles: true }));
              }
              if (nameInput && !nameInput.value.trim()) {
                nameInput.value = prov.type === 'onedrive' ? 'onedrive-personal' : `${prov.type}-cloud`;
              }
              if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.style.background = 'rgba(34, 197, 94, 0.18)';
                statusEl.style.border = '1px solid rgba(34, 197, 94, 0.4)';
                statusEl.style.color = '#4ade80';
                statusEl.innerHTML = '✅ <strong>Authentication Successful!</strong> Token verified & auto-populated below. You may now click <em>⚡ Test Connection</em> or <em>Save & Connect Remote</em>.';
              }
              const desktopP = dynamicFields.querySelector('#oauth-desktop-panel');
              const qrP = dynamicFields.querySelector('#oauth-qr-panel');
              if (desktopP) desktopP.style.display = 'none';
              if (qrP) qrP.style.display = 'none';
              if (tabDesktop && tabDesktop.parentElement) tabDesktop.parentElement.style.display = 'none';
              if (qrBox) qrBox.style.display = 'none';
              if (step2Box) step2Box.style.display = 'none';
              playChirp(880, 0.12, 'sine');
              showToast(t('toast.cloud_credentials_verified_token_auto_populated', 'Cloud credentials verified & token auto-populated!'), 'info');
            };

            const renderQrCode = async (session) => {
              if (!qrTarget || !session) return;
              try {
                const origin = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : 'http://127.0.0.1:8082';
                const mobileUrl = `${origin}/api/remotes/oauth/mobile-page?sid=${encodeURIComponent(session.session_id)}`;
                const { default: QRCode } = await import('qrcode');
                const svgStr = await QRCode.toString(mobileUrl, {
                  type: 'svg',
                  margin: 1,
                  width: 170,
                  color: { dark: '#000000', light: '#ffffff' }
                });
                qrTarget.innerHTML = svgStr;

                let directLink = qrBox ? qrBox.querySelector('.oauth-direct-links') : null;
                if (qrBox && !directLink) {
                  directLink = document.createElement('div');
                  directLink.className = 'oauth-direct-links';
                  directLink.style.cssText = 'margin-top: 8px; font-size: var(--zn-fs-xs); text-align: center; line-height: 1.5;';
                  qrBox.appendChild(directLink);
                }
                if (directLink) {
                  directLink.innerHTML = `
                    <div style="color: var(--zn-text-muted); font-size: var(--zn-fs-xs); margin-bottom: 2px;">Can't scan QR code?</div>
                    <a href="${escapeHtml(session.auth_url)}" target="_blank" rel="noopener noreferrer" style="color: var(--zn-text-accent); text-decoration: underline; font-weight: 600;">
                      🔗 Open Direct Login Page
                    </a>
                  `;
                }
              } catch (qErr) {
                qrTarget.innerHTML = `
                  <div style="padding: 12px; text-align: center;">
                    <div style="color: var(--zn-text-crit); font-size: var(--zn-fs-xs); margin-bottom: 6px;">Could not display QR code</div>
                    <a href="${escapeHtml(session.auth_url)}" target="_blank" rel="noopener noreferrer" style="color: var(--zn-text-accent); text-decoration: underline; font-size: var(--zn-fs-xs); font-weight: 600;">Click here to log in directly</a>
                  </div>
                `;
              }
            };

            const startOAuth = async (isQr = false, forceNew = false) => {
              // Reuse existing active session if available
              if (!forceNew && _currentOAuthSession && _currentOAuthSession.auth_url) {
                if (isQr) {
                  if (qrBox) qrBox.style.display = 'block';
                  await renderQrCode(_currentOAuthSession);
                  if (statusEl) {
                    statusEl.style.display = 'block';
                    statusEl.style.background = 'rgba(56, 189, 248, 0.12)';
                    statusEl.style.border = '1px solid rgba(56, 189, 248, 0.3)';
                    statusEl.style.color = '#38bdf8';
                    statusEl.innerHTML = '📱 <strong>QR Code Ready:</strong> Scan with your phone camera to sign in on mobile, or follow Step 2 below.';
                  }
                } else {
                  if (typeof window !== 'undefined' && window.open) {
                    window.open(_currentOAuthSession.auth_url, '_blank');
                  }
                  if (statusEl) {
                    statusEl.style.display = 'block';
                    statusEl.style.background = 'rgba(56, 189, 248, 0.12)';
                    statusEl.style.border = '1px solid rgba(56, 189, 248, 0.3)';
                    statusEl.style.color = '#38bdf8';
                    statusEl.innerHTML = '🌐 <strong>Sign-in window opened:</strong> Log in to your account. When redirected to the page saying <em>"This site can\'t be reached"</em>, copy the full address from your URL bar and paste it in Step 2 below.';
                  }
                  if (urlInput) {
                    setTimeout(() => urlInput.focus(), 200);
                  }
                }
                if (step2Box) step2Box.style.display = 'block';
                return;
              }

              // If forcing new and there was an existing session, delete it cleanly
              if (_currentOAuthSession && _currentOAuthSession.session_id) {
                api.delete(`/api/remotes/oauth/${_currentOAuthSession.session_id}`).catch(() => {});
                _currentOAuthSession = null;
              }

              if (browserBtn) {
                browserBtn.disabled = true;
                browserBtn.innerHTML = '<span>⏳ Starting Authorization...</span>';
              }
              if (qrBtn) qrBtn.disabled = true;
              if (qrTarget && isQr) {
                qrTarget.innerHTML = '<div style="font-size: var(--zn-fs-xs); color: var(--lt-t-0284c7ff, #0284c7); font-weight: 600;">⏳ Initializing QR code...</div>';
              }

              if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.style.background = 'rgba(14, 165, 233, 0.15)';
                statusEl.style.border = '1px solid rgba(14, 165, 233, 0.3)';
                statusEl.style.color = '#38bdf8';
                statusEl.innerHTML = '⏳ Contacting NAS to start OAuth authorization session...';
              }

              try {
                const res = await api.post('/api/remotes/oauth/start', {
                  provider_type: prov.type,
                });

                if (res && res.auth_url) {
                  _currentOAuthSession = res;
                  if (step2Box) step2Box.style.display = 'block';

                  if (isQr) {
                    if (qrBox) qrBox.style.display = 'block';
                    await renderQrCode(res);
                    if (statusEl) {
                      statusEl.style.background = 'rgba(56, 189, 248, 0.12)';
                      statusEl.style.border = '1px solid rgba(56, 189, 248, 0.3)';
                      statusEl.style.color = '#38bdf8';
                      statusEl.innerHTML = '📱 <strong>QR Code Ready:</strong> Scan with your phone camera to sign in on mobile, or follow Step 2 below.';
                    }
                  } else {
                    if (typeof window !== 'undefined' && window.open) {
                      window.open(res.auth_url, '_blank');
                    }
                    if (statusEl) {
                      statusEl.style.background = 'rgba(56, 189, 248, 0.12)';
                      statusEl.style.border = '1px solid rgba(56, 189, 248, 0.3)';
                      statusEl.style.color = '#38bdf8';
                      statusEl.innerHTML = '🌐 <strong>Sign-in window opened:</strong> Log in to your account. When redirected to the page saying <em>"This site can\'t be reached"</em>, copy the full address from your URL bar and paste it in Step 2 below.';
                    }
                    if (urlInput) {
                      setTimeout(() => urlInput.focus(), 300);
                    }
                  }

                  if (_oauthPollTimer) clearInterval(_oauthPollTimer);
                  _oauthPollTimer = setInterval(async () => {
                    try {
                      if (!_currentOAuthSession?.session_id) return;
                      const st = await api.get(`/api/remotes/oauth/status/${_currentOAuthSession.session_id}`);
                      if (st && st.completed && st.token) {
                        clearInterval(_oauthPollTimer);
                        _oauthPollTimer = null;
                        applyAcquiredToken(st.token, st.drive_id, st.drive_type);
                      }
                    } catch (_) {}
                  }, 2500);
                }
              } catch (err) {
                if (statusEl) {
                  statusEl.style.display = 'block';
                  statusEl.style.background = 'rgba(239, 68, 68, 0.15)';
                  statusEl.style.border = '1px solid rgba(239, 68, 68, 0.3)';
                  statusEl.style.color = '#f87171';
                  statusEl.innerHTML = `❌ Failed to start authorization: ${escapeHtml(err.message || 'Unknown error')}`;
                }
                if (isQr && qrTarget) {
                  qrTarget.innerHTML = `
                    <div style="padding: 12px; text-align: center; color: var(--lt-t-ef4444ff, #ef4444); font-size: var(--zn-fs-xs);">
                      <div>❌ ${escapeHtml(err.message || 'Failed to start authorization')}</div>
                      <button type="button" class="btn-retry-qr" style="margin-top: 8px; padding: 4px 10px; font-size: var(--zn-fs-xs); background: rgba(239,68,68,0.2); border: 1px solid rgba(239,68,68,0.4); color: var(--zn-text-strong); border-radius: 4px; cursor: pointer;">🔄 Retry</button>
                    </div>
                  `;
                  const retryBtn = qrTarget.querySelector('.btn-retry-qr');
                  if (retryBtn) {
                    retryBtn.onclick = () => startOAuth(true, true);
                  }
                }
              } finally {
                if (browserBtn) {
                  browserBtn.disabled = false;
                  browserBtn.innerHTML = `<span>🌐 ${escapeHtml(brandBtnLabel)}</span>`;
                }
                if (qrBtn) qrBtn.disabled = false;
              }
            };

            if (browserBtn) {
              browserBtn.onclick = () => {
                startOAuth(false, false);
              };
            }

            if (qrBtn) {
              qrBtn.onclick = () => {
                if (qrPanel) qrPanel.style.display = 'block';
                if (desktopPanel) desktopPanel.style.display = 'none';
                if (tabQr) {
                  tabQr.style.background = '#0284c7';
                  tabQr.style.color = '#fff';
                }
                if (tabDesktop) {
                  tabDesktop.style.background = 'transparent';
                  tabDesktop.style.color = '#94a3b8';
                }
                startOAuth(true, true);
              };
            }

            if (pasteBtn && urlInput) {
              pasteBtn.onclick = async () => {
                try {
                  if (navigator.clipboard && navigator.clipboard.readText) {
                    const text = await navigator.clipboard.readText();
                    if (text && text.trim()) {
                      urlInput.value = text.trim();
                      showToast(t('toast.pasted_url_from_clipboard', 'Pasted URL from clipboard'), 'info');
                      if (exchangeBtn) {
                        exchangeBtn.focus();
                      }
                      return;
                    }
                  }
                } catch (_) {}
                showPromptToast(
                  'Paste Redirect URL',
                  'Paste the redirect URL from your browser address bar:',
                  '',
                  (manual) => {
                    if (manual && manual.trim()) {
                      urlInput.value = manual.trim();
                    }
                  },
                  null,
                  { placeholder: 'http://localhost:53682/...' }
                );
              };
            }

            // Smart clipboard watcher: detect when returning from authorization tab
            _focusListener = async () => {
              try {
                if (navigator.clipboard && navigator.clipboard.readText) {
                  const clip = await navigator.clipboard.readText();
                  if (clip && (clip.includes('localhost:53682') || clip.includes('127.0.0.1:53682') || clip.includes('code='))) {
                    if (urlInput && !urlInput.value.trim()) {
                      urlInput.value = clip.trim();
                      showToast(t('toast.detected_oauth_redirect_url_from_clipboard', 'Detected OAuth redirect URL from clipboard!'), 'info');
                      if (statusEl) {
                        statusEl.style.display = 'block';
                        statusEl.style.background = 'rgba(34, 197, 94, 0.15)';
                        statusEl.style.border = '1px solid rgba(34, 197, 94, 0.35)';
                        statusEl.style.color = '#4ade80';
                        statusEl.innerHTML = '📋 <strong>Redirect URL detected in clipboard!</strong> Auto-filled in Step 2. Click <strong>✓ Complete & Populate Token</strong> to finish.';
                      }
                      if (exchangeBtn) {
                        exchangeBtn.focus();
                      }
                    }
                  }
                }
              } catch (_) {}
            };
            if (typeof window !== 'undefined' && window.addEventListener) {
              window.addEventListener('focus', _focusListener);
            }

            if (exchangeBtn && urlInput) {
              exchangeBtn.onclick = async () => {
                const rawUrl = urlInput.value.trim();
                if (!rawUrl) {
                  showToast(t('toast.please_paste_the_redirect_url_first', 'Please paste the redirect URL first'), 'warning');
                  return;
                }
                if (!_currentOAuthSession?.session_id) {
                  showToast(t('toast.no_active_authorization_session_please_click', 'No active authorization session. Please click 1-Click Authorize first.'), 'warning');
                  return;
                }
                exchangeBtn.disabled = true;
                exchangeBtn.innerHTML = '<span>⏳ Exchanging Token...</span>';
                if (statusEl) {
                  statusEl.style.display = 'block';
                  statusEl.style.background = 'rgba(14, 165, 233, 0.15)';
                  statusEl.style.border = '1px solid rgba(14, 165, 233, 0.3)';
                  statusEl.style.color = '#38bdf8';
                  statusEl.innerHTML = '⏳ Contacting authorization server to exchange code for token...';
                }

                try {
                  const exRes = await api.post('/api/remotes/oauth/exchange', {
                    session_id: _currentOAuthSession.session_id,
                    redirect_url: rawUrl,
                  });

                  if (exRes && exRes.token) {
                    if (_oauthPollTimer) {
                      clearInterval(_oauthPollTimer);
                      _oauthPollTimer = null;
                    }
                    applyAcquiredToken(exRes.token, exRes.drive_id, exRes.drive_type);
                  } else {
                    throw new Error(exRes?.error || 'Token exchange failed');
                  }
                } catch (err) {
                  if (statusEl) {
                    statusEl.style.display = 'block';
                    statusEl.style.background = 'rgba(239, 68, 68, 0.15)';
                    statusEl.style.border = '1px solid rgba(239, 68, 68, 0.3)';
                    statusEl.style.color = '#f87171';
                    statusEl.innerHTML = `❌ Token Exchange Error: ${escapeHtml(err.message || 'Failed to exchange code')}`;
                  }
                } finally {
                  exchangeBtn.disabled = false;
                  exchangeBtn.innerHTML = '<span>✓ Complete & Populate Token</span>';
                }
              };
            }
          }

          // Bind copy buttons inside dynamic fields
          dynamicFields.querySelectorAll('.remote-copy-cmd-btn').forEach((btn) => {
            btn.onclick = async (ev) => {
              ev.preventDefault();
              const cmd = btn.getAttribute('data-cmd');
              if (cmd) {
                const ok = await copyTextToClipboard(cmd);
                if (ok) {
                  btn.textContent = t('ui.copied', '✅ Copied!');
                  showToast(t('toast.copied_command', 'Copied command: {cmd}', { cmd: cmd }), 'info');
                  setTimeout(() => {
                    btn.textContent = `📋 Copy: ${cmd}`;
                  }, 2000);
                }
              }
            };
          });
        }
      };

      providerSelect.onchange = renderFields;
      renderFields();
    }

    // Bind Test Connection button
    if (testBtn) {
      testBtn.onclick = async (e) => {
        e.preventDefault();
        const formEl = document.getElementById('new-remote-form');
        if (!formEl) return;
        const provType = providerSelect.value;
        const formData = new FormData(formEl);
        const parameters = {};

        formData.forEach((val, key) => {
          if (key !== 'name' && val !== '') {
            parameters[key] = val;
          }
        });

        testBtn.disabled = true;
        testBtn.classList.remove('tested-green');
        testBtn.innerHTML = `<span>${t('remotes.test_btn_testing', '⏳ Testing Connection...')}</span>`;
        if (testResult) {
          testResult.style.display = 'block';
          testResult.style.background = 'rgba(56, 189, 248, 0.12)';
          testResult.style.border = '1px solid rgba(56, 189, 248, 0.3)';
          testResult.style.color = '#38bdf8';
          testResult.innerHTML = '<span>🔄 Validating credentials and connecting to remote...</span>';
        }

        try {
          const res = await api.post('/api/remotes/test', {
            type: provType,
            parameters
          });

          if (res && res.success) {
            playChirp(880, 0.12, 'sine');
            testBtn.classList.add('tested-green');
            testBtn.innerHTML = `<span>${t('remotes.test_btn_success', '✅ Connection Successful')}</span>`;
            showToast(t('remotes.test_success', 'Connection test successful! Valid credentials and remote accessible.'), 'ok');
            if (res.drive_id) {
              const driveIdInput = dynamicFields?.querySelector('input[name="drive_id"]');
              if (driveIdInput && !driveIdInput.value) {
                driveIdInput.value = res.drive_id;
                driveIdInput.dispatchEvent(new Event('input', { bubbles: true }));
              }
            }
            if (res.drive_type) {
              const driveTypeSelect = dynamicFields?.querySelector('select[name="drive_type"]');
              if (driveTypeSelect && !driveTypeSelect.value) {
                driveTypeSelect.value = res.drive_type;
                driveTypeSelect.dispatchEvent(new Event('change', { bubbles: true }));
              }
            }
            if (testResult) {
              testResult.style.display = 'block';
              testResult.style.background = 'rgba(34, 197, 94, 0.18)';
              testResult.style.border = '1px solid rgba(34, 197, 94, 0.4)';
              testResult.style.color = '#4ade80';
              const sample = (res.items_sample && res.items_sample.length > 0)
                ? ` (Files found: ${res.items_sample.slice(0, 3).join(', ')})`
                : '';
              testResult.innerHTML = `✅ <strong>Connection Test Successful: Connection Verified!</strong> Valid credentials and remote accessible${sample}.`;
            }
          } else {
            testBtn.classList.remove('tested-green');
            testBtn.innerHTML = '<span>⚡ Test Connection</span>';
            if (testResult) {
              testResult.style.display = 'block';
              testResult.style.background = 'rgba(239, 68, 68, 0.15)';
              testResult.style.border = '1px solid rgba(239, 68, 68, 0.3)';
              testResult.style.color = '#f87171';
              testResult.innerHTML = `❌ <strong>Connection Failed:</strong> ${escapeHtml(res?.error || 'Authentication error')}`;
            }
            showToast(res?.error || 'Connection test failed', 'error');
          }
        } catch (err) {
          testBtn.classList.remove('tested-green');
          testBtn.innerHTML = '<span>⚡ Test Connection</span>';
          if (testResult) {
            testResult.style.display = 'block';
            testResult.style.background = 'rgba(239, 68, 68, 0.15)';
            testResult.style.border = '1px solid rgba(239, 68, 68, 0.3)';
            testResult.style.color = '#f87171';
            testResult.innerHTML = `❌ <strong>Connection Failed:</strong> ${escapeHtml(err.message || 'Error communicating with host')}`;
          }
          showToast(err.message || 'Error testing connection', 'error');
        } finally {
          testBtn.disabled = false;
          if (!testBtn.classList.contains('tested-green')) {
            testBtn.innerHTML = '<span>⚡ Test Connection</span>';
          }
        }
      };
    }

    const resetTestGreen = () => {
      if (testBtn && testBtn.classList.contains('tested-green')) {
        testBtn.classList.remove('tested-green');
        testBtn.innerHTML = '<span>⚡ Test Connection</span>';
      }
      if (testResult) {
        testResult.style.display = 'none';
      }
    };

    const form = document.getElementById('new-remote-form');
    if (form) {
      form.addEventListener('input', resetTestGreen);
      form.addEventListener('change', resetTestGreen);
      form.onsubmit = async (e) => {
        e.preventDefault();
        const name = nameInput.value.trim();
        const provType = providerSelect.value;
        const formData = new FormData(form);
        const parameters = {};

        formData.forEach((val, key) => {
          if (key !== 'name' && val !== '') {
            parameters[key] = val;
          }
        });

        const submitBtn = document.getElementById('new-remote-submit-btn');
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.textContent = t('ui.connecting', 'Connecting...');
        }

        try {
          await api.post('/api/remotes', {
            name,
            type: provType,
            parameters
          });

          if (autoMountToggle && autoMountToggle.checked) {
            try {
              await api.post(`/api/remotes/${name}/mount`, {});
            } catch (mErr) {
              console.warn('[Remote] Auto-mount warning:', mErr);
            }
          }

          close();
          playChirp(880, 0.12, 'sine');
          showToast(t('toast.cloud_remote_connected_successfully', 'Cloud remote \'{name}\' connected successfully!', { name: name }), 'info');
          ZettEventBus.emit('fm:refresh');
          ZettEventBus.emit('storage:mount_changed', { name, path: `/mnt/remotes/${name}`, action: 'create' });
          if (onSuccess) onSuccess();
        } catch (err) {
          if (errorBox) {
            errorBox.textContent = err.message || 'Failed to connect remote';
            errorBox.style.display = 'block';
          }
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = t('ui.save_connect_remote', 'Save & Connect Remote');
          }
        }
      };
    }
  } catch (err) {
    showToast(t('toast.failed_load_storage_providers', 'Failed to load storage providers: {error}', { error: err.message || t('toast.unknown_error', 'Unknown error') }), 'error');
  }
}

if (typeof window !== 'undefined') {
  window.openNewCloudRemoteModal = openNewCloudRemoteModal;
}

/**
 * Opens Create Storage Pool Modal (Generic Linux Active Provisioner)
 */
function askPoolPrompt(title, msg, inputType) {
  return new Promise((resolve) => {
    showPromptToast(title, msg, '', (v) => resolve(v ? v.trim() : null), () => resolve(null), { inputType, okText: 'Continue' });
  });
}

export async function openCreateStoragePoolModal(onSuccess) {
  const modal = document.getElementById('modal-create-storage-pool');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-create-pool-close-btn');
  const cancelBtn = document.getElementById('modal-create-pool-cancel-btn');
  const form = document.getElementById('create-pool-form');
  const errorBox = document.getElementById('create-pool-error-box');
  const disksContainer = document.getElementById('create-pool-disks-container');
  const submitBtn = document.getElementById('create-pool-submit-btn');

  const close = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  };

  if (closeBtn) closeBtn.onclick = close;
  if (cancelBtn) cancelBtn.onclick = close;

  const modalWin = modal.querySelector('.smart-modal-window');
  const modalHdr = modal.querySelector('.smart-modal-header');
  if (modalWin && modalHdr) makeDraggable(modalWin, modalHdr);

  modal.classList.add('open');
  modal.style.display = 'flex';
  if (errorBox) errorBox.style.display = 'none';

  const fsSelect = document.getElementById('create-pool-fs');
  const profileSelect = document.getElementById('create-pool-profile');
  const updateProfiles = () => {
    if (!profileSelect) return;
    const fs = fsSelect?.value || 'btrfs';
    if (fs === 'zfs') {
      profileSelect.innerHTML = `
        <option value="raidz2" selected>RAIDZ2 (Dual Parity - 4+ Drives - Recommended)</option>
        <option value="raidz1">RAIDZ1 (Single Parity - 3+ Drives)</option>
        <option value="raidz3">RAIDZ3 (Triple Parity - 5+ Drives)</option>
        <option value="mirror">ZFS Mirror (2+ Drives)</option>
        <option value="single">Single / Stripe (No Parity)</option>
      `;
    } else if (fs === 'btrfs') {
      profileSelect.innerHTML = `
        <option value="raid1" selected>RAID 1 (Mirroring - 2+ Drives)</option>
        <option value="raid10">RAID 10 (Striped Mirrors - 4+ Drives)</option>
        <option value="raid0">RAID 0 (Striping - Fast, No Redundancy)</option>
        <option value="single">Single (JBOD Drive)</option>
      `;
    } else {
      profileSelect.innerHTML = `
        <option value="single" selected>Single Volume (Standard Drive)</option>
      `;
    }
  };
  if (fsSelect) {
    fsSelect.onchange = updateProfiles;
    updateProfiles();
  }

  // Populate available physical disks
  if (disksContainer) {
    disksContainer.innerHTML = '<div style="color:var(--muted); font-size:var(--zn-fs-xs);">Scanning available physical disks...</div>';
    try {
      const overview = await api.get('/api/storage/overview').catch(() => null);
      let disksList = overview?.unassigned_disks;
      if (!disksList || disksList.length === 0) {
        const disksRes = await api.get('/api/storage/disks').catch(() => null);
        disksList = Array.isArray(disksRes) ? disksRes : (disksRes?.disks || null);
      }
      if (!disksList || disksList.length === 0) {
        const legacyRes = await api.get('/api/system/disks').catch(() => []);
        disksList = Array.isArray(legacyRes) ? legacyRes : (legacyRes?.disks || []);
      }
      const filtered = (disksList || []).filter((d) => {
        const n = String(d.dev || d.name || '').toLowerCase();
        return !n.includes('loop') && !n.includes('zram') && !n.includes('boot') && !d.assigned;
      });

      if (filtered.length === 0) {
        disksContainer.innerHTML = '<div style="color:var(--muted); font-size:var(--zn-fs-xs);">No unassigned disks available.</div>';
      } else {
        disksContainer.innerHTML = filtered.map((d) => `
          <label style="display:flex; align-items:center; gap:8px; font-size:var(--zn-fs-xs); color:var(--zn-text-strong); cursor:pointer;">
            <input type="checkbox" name="pool-disk" value="${escapeHtml(d.dev || d.name)}" style="accent-color:var(--ok2);" />
            <span><strong>/dev/${escapeHtml(d.dev || d.name)}</strong> (${d.size || formatBytes(d.size_bytes)}) · ${escapeHtml(d.model || '')}</span>
          </label>
        `).join('');
      }
    } catch (dErr) {
      disksContainer.innerHTML = '<div style="color:var(--muted); font-size:var(--zn-fs-xs);">Failed to scan disks.</div>';
    }
  }

  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (errorBox) errorBox.style.display = 'none';

      const name = document.getElementById('create-pool-name')?.value.trim();
      const fsType = document.getElementById('create-pool-fs')?.value || 'btrfs';
      const profile = document.getElementById('create-pool-profile')?.value || 'raid1';
      const mountpoint = document.getElementById('create-pool-mountpoint')?.value.trim() || '';

      const checkedBoxes = Array.from(modal.querySelectorAll('input[name="pool-disk"]:checked'));
      const disks = checkedBoxes.map((cb) => cb.value);

      if (disks.length === 0) {
        if (errorBox) {
          errorBox.textContent = t('ui.please_select_at_least_one', 'Please select at least one member disk.');
          errorBox.style.display = 'block';
        }
        return;
      }

      // Formatting erases the disks (SEC-08): typed pool name + password, then an explicit
      // second yes if the server finds existing data on them.
      const typed = await askPoolPrompt(
        'Erase and format disks',
        `Every selected disk (${disks.join(', ')}) will be erased. Type the pool name "${name}" to confirm.`,
        'text'
      );
      if (typed === null) return;
      const password = await askPoolPrompt('Confirm with your password', 'Enter your ZettNAS password to create the pool.', 'password');
      if (password === null) return;

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = t('ui.provisioning', 'Provisioning...');
      }

      const body = { name, fs_type: fsType, profile, disks, mountpoint, confirm_name: typed, current_password: password };
      try {
        try {
          await api.post('/api/storage/pools', body, { confirmed: true });
        } catch (err) {
          if (err && err.error === 'disks_not_safe' && err.body && err.body.erasable) {
            const erase = await new Promise((resolve) => {
              showConfirmToast(
                'Disks contain data',
                `${escapeHtml(err.message)}<br><br>Erase everything on them and continue?`,
                () => resolve(true),
                () => resolve(false)
              );
            });
            if (!erase) throw err;
            await api.post('/api/storage/pools', { ...body, erase_existing_data: true }, { confirmed: true });
          } else {
            throw err;
          }
        }

        close();
        playChirp(880, 0.12, 'sine');
        showToast(t('toast.storage_pool_provisioned_successfully', 'Storage pool \'{name}\' provisioned successfully!', { name: name }), 'info');
        if (onSuccess) onSuccess();
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = err.message || 'Failed to create storage pool';
          errorBox.style.display = 'block';
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = t('ui.provision_storage_pool', '🚀 Provision Storage Pool');
        }
      }
    };
  }
}

/**
 * Opens Create Network Share Modal (Samba / WebDAV)
 */
/** Guest access and NFS for every host are explicit, warned choices (B11, SEC-22/23). */
export function confirmOpenShare(guest, nfsEveryone) {
  if (!guest && !nfsEveryone) return Promise.resolve(true);
  const parts = [];
  if (guest) parts.push(t('share.confirm_guest', 'Anyone on your network can open this folder without a password.'));
  if (nfsEveryone) parts.push(t('share.confirm_nfs_all', 'Any computer that can reach this NAS can mount it over NFS.'));
  return new Promise((resolve) => {
    showConfirmToast(t('share.confirm_open_title', 'Open this folder to everyone?'), parts.join(' '), () => resolve(true), () => resolve(false));
  });
}

export function openCreateNetworkShareModal(onSuccess) {
  const modal = document.getElementById('modal-create-network-share');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-create-share-close-btn');
  const cancelBtn = document.getElementById('modal-create-share-cancel-btn');
  const form = document.getElementById('create-share-form');
  const errorBox = document.getElementById('create-share-error-box');
  const submitBtn = document.getElementById('create-share-submit-btn');

  let _unbindTrap = null;
  const close = () => {
    if (_unbindTrap) {
      try { _unbindTrap(); } catch (_) {}
      _unbindTrap = null;
    }
    modal.classList.remove('open');
    modal.style.display = 'none';
  };

  if (closeBtn) closeBtn.onclick = close;
  if (cancelBtn) cancelBtn.onclick = close;

  const modalWin = modal.querySelector('.smart-modal-window') || modal;
  const modalHdr = modal.querySelector('.smart-modal-header');
  if (modalWin && modalHdr) makeDraggable(modalWin, modalHdr);

  modal.classList.add('open');
  modal.style.display = 'flex';
  _unbindTrap = trapFocus(modalWin, close);
  const firstInput = modal.querySelector('input:not([disabled]), select:not([disabled]), button:not([disabled])');
  if (firstInput) setTimeout(() => firstInput.focus(), 60);
  if (errorBox) errorBox.style.display = 'none';

  const exportNfsCb = document.getElementById('create-share-export-nfs');
  const nfsOpts = document.getElementById('create-share-nfs-opts');
  if (exportNfsCb && nfsOpts) {
    const toggleNfs = () => {
      nfsOpts.style.display = exportNfsCb.checked ? 'flex' : 'none';
    };
    exportNfsCb.onchange = toggleNfs;
    toggleNfs();
  }

  const usersMatrix = document.getElementById('create-share-users-matrix');
  const usersCount = document.getElementById('create-share-users-count');
  if (usersMatrix) {
    usersMatrix.innerHTML = '<div style="font-size:var(--zn-fs-xs); color:var(--muted); padding:4px;">Loading user accounts...</div>';
    api.get('/api/auth/users').then((data) => {
      const users = Array.isArray(data) ? data : (data?.users || []);
      if (!users.length) {
        usersMatrix.innerHTML = '<div style="font-size:var(--zn-fs-xs); color:var(--muted); padding:4px;">No custom users found. Defaulting to system access.</div>';
        if (usersCount) usersCount.textContent = t('ui.0_users', '0 Users');
        return;
      }
      if (usersCount) usersCount.textContent = `${users.length} Users`;
      usersMatrix.innerHTML = users.map((u) => {
        const uname = u.username || u.name || 'user';
        const role = u.role || 'user';
        return `
          <div class="user-perm-row" data-username="${uname}" style="display:flex; align-items:center; justify-content:space-between; padding:4px 6px; background:var(--zn-glaze-3); border-radius:4px; font-size:var(--zn-fs-xs);">
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-weight:600; color:var(--zn-text-strong);">👤 ${uname}</span>
              <span style="font-size:var(--zn-fs-xs); padding:1px 5px; border-radius:3px; background:var(--zn-glaze-8); color:var(--muted);">${role}</span>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
              <label style="display:flex; align-items:center; gap:3px; cursor:pointer; font-size:var(--zn-fs-xs); color:var(--lt-t-3bf58bff, #3bf58b);">
                <input type="radio" name="perm-${uname}" value="rw" checked style="accent-color:#3bf58b; width:12px; height:12px;" /> RW
              </label>
              <label style="display:flex; align-items:center; gap:3px; cursor:pointer; font-size:var(--zn-fs-xs); color:var(--zn-text-accent);">
                <input type="radio" name="perm-${uname}" value="ro" style="accent-color:#38bdf8; width:12px; height:12px;" /> RO
              </label>
              <label style="display:flex; align-items:center; gap:3px; cursor:pointer; font-size:var(--zn-fs-xs); color:var(--zn-text-crit);">
                <input type="radio" name="perm-${uname}" value="deny" style="accent-color:#f87171; width:12px; height:12px;" /> Deny
              </label>
            </div>
          </div>
        `;
      }).join('');
    }).catch(() => {
      usersMatrix.innerHTML = '<div style="font-size:var(--zn-fs-xs); color:var(--muted); padding:4px;">Standard user access rules apply.</div>';
      if (usersCount) usersCount.textContent = t('ui.standard', 'Standard');
    });
  }

  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (errorBox) errorBox.style.display = 'none';

      const name = document.getElementById('create-share-name')?.value.trim();
      const path = document.getElementById('create-share-path')?.value.trim() || '';
      const comment = document.getElementById('create-share-comment')?.value.trim() || '';
      const quotaVal = parseInt(document.getElementById('create-share-quota-gb')?.value, 10);
      const quotaGb = isNaN(quotaVal) ? 0 : Math.max(0, quotaVal);
      const security = document.getElementById('create-share-security')?.value || 'private';
      const readOnly = document.getElementById('create-share-readonly')?.checked ?? false;
      const isTm = document.getElementById('create-share-timemachine')?.checked ?? false;
      const exportSmb = document.getElementById('create-share-export-smb')?.checked ?? true;
      const exportNfs = document.getElementById('create-share-export-nfs')?.checked ?? false;
      const nfsSquash = document.getElementById('create-share-nfs-squash')?.value || 'root_squash';
      const nfsAnonuid = parseInt(document.getElementById('create-share-nfs-anonuid')?.value, 10) || 1000;
      const nfsAnongid = parseInt(document.getElementById('create-share-nfs-anongid')?.value, 10) || 1000;
      const nfsSync = (document.getElementById('create-share-nfs-sync')?.value || 'sync') === 'sync';
      const nfsClients = document.getElementById('create-share-nfs-clients')?.value.trim() || '';

      const userPermissions = {};
      if (usersMatrix) {
        usersMatrix.querySelectorAll('.user-perm-row').forEach((row) => {
          const u = row.dataset.username;
          const perm = row.querySelector(`input[name="perm-${u}"]:checked`)?.value || 'rw';
          if (u) userPermissions[u] = perm;
        });
      }

      if (!name) return;
      if (!(await confirmOpenShare(security === 'public', exportNfs && nfsClients === '*'))) return;

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = t('ui.provisioning', 'Provisioning...');
      }

      try {
        await api.post('/api/storage/shares', {
          name,
          path,
          comment,
          security,
          read_only: readOnly,
          export_smb: exportSmb,
          export_nfs: exportNfs,
          quota_gb: quotaGb,
          user_permissions: userPermissions,
          nfs_squash: nfsSquash,
          nfs_anonuid: nfsAnonuid,
          nfs_anongid: nfsAnongid,
          nfs_sync: nfsSync,
          nfs_clients: nfsClients,
          nfs_allow_everyone: nfsClients === '*',
        });

        if (isTm) {
          try {
            await api.post('/api/samba/shares', {
              name,
              path: path || `/mnt/storage/${name}`,
              comment: comment || 'Apple Time Machine Backup',
              read_only: readOnly,
              guest_ok: security === 'public',
              browseable: true,
              timemachine: true,
            });
          } catch (tmErr) {
            console.warn('[Samba] Time Machine configuration warning:', tmErr);
          }
        }

        close();
        playChirp(880, 0.12, 'sine');
        showToast(t('toast.share_created_successfully', 'Share \'{name}\' created successfully!', { name: name }), 'info');
        if (onSuccess) onSuccess();
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = err.message || 'Failed to create share';
          errorBox.style.display = 'block';
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = t('ui.provision_share', '📁 Provision Share');
        }
      }
    };
  }
}

/**
 * Opens Btrfs Subvolume Snapshots Manager Modal
 */
export async function openSnapshotsModal(poolId = 'default_pool') {
  const modal = document.getElementById('modal-btrfs-snapshots');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-snapshots-close-btn');
  const snapNameInput = document.getElementById('snap-name-input');
  const takeSnapBtn = document.getElementById('btn-take-snapshot-submit');
  const listMount = document.getElementById('snapshots-list-mount');

  const close = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  };

  if (closeBtn) closeBtn.onclick = close;

  const modalWin = modal.querySelector('.smart-modal-window');
  const modalHdr = modal.querySelector('.smart-modal-header');
  if (modalWin && modalHdr) makeDraggable(modalWin, modalHdr);

  modal.classList.add('open');
  modal.style.display = 'flex';

  async function loadSnapshots() {
    if (!listMount) return;
    listMount.innerHTML = '<div style="padding:15px; text-align:center; color:var(--muted); font-size:var(--zn-fs-xs);">Loading snapshots...</div>';
    try {
      const snaps = await api.get(`/api/storage/pools/${poolId}/snapshots`);
      if (!Array.isArray(snaps) || snaps.length === 0) {
        listMount.innerHTML = '<div style="padding:20px; text-align:center; color:var(--muted); font-size:var(--zn-fs-xs);">No active subvolume snapshots found.</div>';
        return;
      }

      let tbody = listMount.querySelector('tbody');
      if (!tbody) {
        listMount.innerHTML = `
          <table class="copy-history-table" style="width:100%;">
            <thead>
              <tr>
                <th>Snapshot Name</th>
                <th>Path</th>
                <th>Created</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        `;
        tbody = listMount.querySelector('tbody');
        bindSnapshotsTableEvents(tbody, poolId, loadSnapshots);
      }

      reconcileKeyedTable(
        tbody,
        snaps,
        (s) => s.name,
        (s) => {
          const dt = formatDateTime(s.created_at);
          const tr = document.createElement('tr');
          tr.dataset.key = s.name;
          tr.innerHTML = `
            <td><strong>${escapeHtml(s.name)}</strong></td>
            <td style="font-family:monospace; font-size:var(--zn-fs-xs); color:var(--zn-text-accent);">${escapeHtml(s.path)}</td>
            <td style="color:var(--muted); font-size:var(--zn-fs-xs);">${dt}</td>
            <td>
              <div style="display:flex; gap:6px; align-items:center;">
                <button class="btn-snap-restore btn-pill-toggle is-small" data-snap="${escapeHtml(s.name)}" style="background: rgba(245,158,11,0.15); border-color: rgba(245,158,11,0.3); color: var(--zn-text-warn);">
                  ⏪ Revert
                </button>
                <button class="btn-snap-del btn-pill-toggle is-danger is-small" data-snap="${escapeHtml(s.name)}">
                  🗑️ Delete
                </button>
              </div>
            </td>
          `;
          return tr;
        },
        (tr, s) => {
          const dt = formatDateTime(s.created_at);
          const pathTd = tr.children[1];
          if (pathTd) pathTd.textContent = s.path;
          const dtTd = tr.children[2];
          if (dtTd) dtTd.textContent = dt;
        }
      );
    } catch (err) {
      listMount.innerHTML = `<div style="padding:15px; color:var(--zn-text-crit); font-size:var(--zn-fs-xs);">Error loading snapshots: ${escapeHtml(err.message || '')}</div>`;
    }
  }

  function bindSnapshotsTableEvents(tbody, pId, onReload) {
    if (tbody._eventsBound) return;
    tbody._eventsBound = true;

    tbody.addEventListener('click', (e) => {
      const restoreBtn = e.target.closest('.btn-snap-restore');
      if (restoreBtn) {
        const sName = restoreBtn.dataset.snap;
        showConfirmToast(
          'Revert Snapshot',
          `Roll back subvolume to snapshot '${sName}'? Pre-existing state will be archived safely.`,
          async () => {
            try {
              await api.post(`/api/storage/pools/${pId}/snapshots/restore`, {
                snapshot_name: sName,
              }, { confirmed: true });
              showToast(t('toast.snapshot_reverted_successfully', 'Snapshot \'{sName}\' reverted successfully!', { sName: sName }), 'success');
              onReload();
            } catch (err) {
              showToast(err.message || 'Failed to revert snapshot', 'error');
            }
          },
          null,
          { okText: 'Revert Snapshot', cancelText: 'Cancel' }
        );
        return;
      }

      const btn = e.target.closest('.btn-snap-del');
      if (!btn) return;
      const sName = btn.dataset.snap;
      showConfirmToast(
        'Delete Snapshot',
        `Delete snapshot '${sName}'?`,
        async () => {
          try {
            await api.delete(`/api/storage/pools/${pId}/snapshots/${sName}`, { confirmed: true });
            showToast(t('toast.snapshot_deleted_2', 'Snapshot \'{sName}\' deleted.', { sName: sName }), 'info');
            onReload();
          } catch (err) {
            showToast(err.message || 'Failed to delete snapshot', 'error');
          }
        },
        null,
        { okText: 'Delete Snapshot', cancelText: 'Cancel' }
      );
    });
  }

  loadSnapshots();

  if (takeSnapBtn && snapNameInput) {
    takeSnapBtn.onclick = async () => {
      const snapName = snapNameInput.value.trim() || `snap-${Date.now()}`;
      try {
        await api.post(`/api/storage/pools/${poolId}/snapshots`, {
          subvolume: '@shares',
          snapshot_name: snapName,
          readonly: true,
        });
        showToast(t('toast.snapshot_taken', 'Snapshot \'{snapName}\' taken!', { snapName: snapName }), 'info');
        snapNameInput.value = '';
        loadSnapshots();
      } catch (err) {
        showToast(err.message || 'Failed to create snapshot', 'error');
      }
    };
  }
}




/**
 * Opens Rename Storage Pool Modal (OpenZFS / Btrfs)
 */
export function openRenameStoragePoolModal(poolId, currentName, onSuccess) {
  const modal = document.getElementById('modal-rename-storage-pool');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-rename-pool-close-btn');
  const cancelBtn = document.getElementById('modal-rename-pool-cancel-btn');
  const form = document.getElementById('rename-pool-form');
  const currentNameInput = document.getElementById('rename-pool-current-name');
  const newNameInput = document.getElementById('rename-pool-new-name');
  const errorBox = document.getElementById('rename-pool-error-box');
  const submitBtn = document.getElementById('rename-pool-submit-btn');

  const close = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  };

  if (closeBtn) closeBtn.onclick = close;
  if (cancelBtn) cancelBtn.onclick = close;

  const modalWin = modal.querySelector('.smart-modal-window');
  const modalHdr = modal.querySelector('.smart-modal-header');
  if (modalWin && modalHdr) makeDraggable(modalWin, modalHdr);

  if (currentNameInput) currentNameInput.value = currentName || poolId;
  if (newNameInput) newNameInput.value = '';
  if (errorBox) errorBox.style.display = 'none';

  modal.classList.add('open');
  modal.style.display = 'flex';
  if (newNameInput) newNameInput.focus();

  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (errorBox) errorBox.style.display = 'none';

      const newName = newNameInput?.value.trim();
      if (!newName) {
        if (errorBox) {
          errorBox.textContent = t('ui.please_enter_a_valid_new', 'Please enter a valid new pool name.');
          errorBox.style.display = 'block';
        }
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = t('ui.renaming', 'Renaming...');
      }

      try {
        await api.post(`/api/storage/pools/${encodeURIComponent(poolId)}/rename`, {
          new_name: newName,
        });

        close();
        playChirp(880, 0.12, 'sine');
        showToast(t('toast.storage_pool_renamed_to_successfully', 'Storage pool \'{currentName}\' renamed to \'{newName}\' successfully!', { currentName: currentName, newName: newName }), 'info');
        if (onSuccess) onSuccess();
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = err.message || 'Failed to rename storage pool';
          errorBox.style.display = 'block';
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = t('ui.apply_rename', '✏️ Apply Rename');
        }
      }
    };
  }
}
