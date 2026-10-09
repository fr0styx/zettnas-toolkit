import { escapeHtml, trapFocus, copyTextToClipboard, reconcileKeyedTable } from '../utils.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { announceA11y } from '../a11y.js';
import { showToast, showConfirmToast } from '../toast.js';
import { state } from '../state.js';
import { makeDraggable } from './dock.js';

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
  showToast(`⚡ Locating drive /dev/${devName}: Pulsing physical activity LED and backplane indicator for 5s to identify bay.`, 'info');

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
  let chassisModel = options.model || 'STORAGE ENCLOSURE';
  let bays = [];
  let nvmes = [];
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

    chassisModel = options.model || (totalBays <= 4 ? 'ZETTLAB D4' : totalBays <= 6 ? 'ZETTLAB D6' : totalBays <= 8 ? 'ZETTLAB D8' : 'DIY STORAGE CHASSIS');
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
  let gridClass = 'dual-cols';
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
            <span class="bay-meta" style="font-size:10px; color:var(--muted); letter-spacing:0.04em;">NO DISK</span>
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
            <button class="bay-locate-btn" data-dev="${devName}" title="Locate Drive (Blink Bay LED)" aria-label="Locate drive in Bay ${slotNum}">
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
          <span>MOTHERBOARD M.2 NVME TWIN</span>
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
            <button class="chassis-config-btn" id="chassis-open-slots-btn" title="Configure Chassis Bays & Profile" aria-label="Configure Chassis Bays & Profile">
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
      const isStandby = slot.classList.contains('standby') || Boolean(slot.querySelector('.bay-led-lens')?.classList.contains('standby-pulse'));
      if (isStandby) {
        showConfirmToast(
          'Drive in Standby Mode',
          `Drive /dev/${dev} in this bay is currently sleeping. Querying S.M.A.R.T. will spin up the disk. Are you sure you want to wake it?`,
          () => {
            showToast(`Waking disk /dev/${dev}...`, 'info');
            ZettEventBus.emit('modal:smart:open', { dev, forceWake: true });
          }
        );
      } else {
        ZettEventBus.emit('modal:smart:open', dev);
      }
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
        <button class="win-btn close-btn" id="chassis-config-close" title="Close" aria-label="Close"></button>
      </div>
      <div class="smart-modal-body" style="padding: 16px; overflow-y: auto; flex: 1; display:flex; flex-direction:column; gap: 14px;">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div>
            <label style="display:block; font-size:10.5px; font-weight:700; color:var(--muted); margin-bottom:6px;">ENCLOSURE PROFILE</label>
            <select id="chassis-profile-select" class="tz-select-input" style="width:100%; padding:8px; border-radius:6px; background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.12); color:#fff; font-size:12px;">
              <option value="auto" ${profile === 'auto' ? 'selected' : ''}>Auto Dynamic (Auto-Detect)</option>
              <option value="compact_dual" ${profile === 'compact_dual' ? 'selected' : ''}>Compact Dual (1–2 Bays)</option>
              <option value="tower_desktop" ${profile === 'tower_desktop' ? 'selected' : ''}>Desktop Tower (3–6 Bays)</option>
              <option value="rackmount_backplane" ${profile === 'rackmount_backplane' ? 'selected' : ''}>Enterprise Rackmount (8–24 Bays)</option>
              <option value="custom" ${profile === 'custom' ? 'selected' : ''}>Custom Enclosure</option>
            </select>
          </div>
          <div>
            <label style="display:block; font-size:10.5px; font-weight:700; color:var(--muted); margin-bottom:6px;">TOTAL PHYSICAL BAYS</label>
            <input type="number" id="chassis-total-bays-input" min="1" max="48" value="${totalBays}" style="width:100%; padding:8px; border-radius:6px; background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.12); color:#fff; font-size:12px;">
          </div>
        </div>

        <div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <label style="font-size:10.5px; font-weight:700; color:var(--muted); letter-spacing:0.5px;">PHYSICAL BAY ALLOCATION & LABELS</label>
            <button id="chassis-auto-assign-btn" class="btn-pill-toggle" style="padding:4px 10px; font-size:11px;">⚡ Auto-Assign Sequentially</button>
          </div>
          <div style="max-height: 320px; overflow-y: auto; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; background: rgba(0,0,0,0.2);">
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
      <div class="smart-modal-footer" style="padding: 12px 16px; border-top: 1px solid rgba(255,255,255,0.08); display:flex; justify-content:flex-end; gap: 8px;">
        <button id="chassis-config-cancel-btn" class="btn-pill-toggle" style="padding: 8px 16px;">Cancel</button>
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
          <td style="font-weight:700; color:var(--accent-cyan,#00f0ff);">BAY ${slot}</td>
          <td>
            <select class="slot-drive-select tz-select-input" style="width:100%; padding:6px; font-size:11.5px; background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.1); color:#fff; border-radius:4px;">
              ${optionsHtml}
            </select>
          </td>
          <td>
            <input type="text" class="slot-label-input tz-text-input" maxlength="64" value="${escapeHtml(currentLabel)}" placeholder="e.g. Parity 1, Pool A" style="width:100%; padding:6px; font-size:11.5px; background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.1); color:#fff; border-radius:4px;">
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
      showToast('Assigned detected drives sequentially.', 'info');
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
        showToast('Chassis bay mapping updated successfully.', 'success');
        closeModal();
        if (typeof onSaved === 'function') onSaved(payload);
      } else {
        showToast('Failed to save chassis bay mapping.', 'error');
      }
    } catch (err) {
      showToast(`Error saving bay mapping: ${err.message}`, 'error');
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
  const fillColor = hasErrors ? 'rgba(245, 183, 49, 0.15)' : 'rgba(59, 245, 139, 0.12)';

  return `
    <svg class="smart-sparkline-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <path d="${areaD}" fill="${fillColor}"/>
      <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      ${coords.map((c) => `<circle cx="${c.x}" cy="${c.y}" r="${c.val > 0 ? 3 : 1.5}" fill="${c.val > 0 ? strokeColor : '#ffffff'}"/>`).join('')}
    </svg>
  `;
}

export function formatBytes(bytes) {
  if (bytes == null || isNaN(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let i = 0;
  let val = Number(bytes);
  while (val >= 1000 && i < units.length - 1) {
    val /= 1000;
    i++;
  }
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
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

  let tree = container.querySelector('.storage-topology-tree');
  if (!tree) {
    container.innerHTML = `
      <div class="storage-topology-tree">
        ${isObserver ? `
          <div class="topo-observer-banner">
            <span class="observer-icon">ℹ️</span>
            <span><strong>Host Observer Mode:</strong> Storage pools, arrays, and parity checks are managed authoritatively by the host OS. Zero risk of parity alteration.</span>
          </div>
        ` : `
          <div class="topo-observer-banner" style="background:rgba(99,102,241,0.12); border-color:rgba(99,102,241,0.25);">
            <span class="observer-icon">⚡</span>
            <span><strong>Active Provisioner Mode:</strong> Generic Linux host detected. Storage pools, Btrfs RAID bitrot protection, and subvolume snapshots are fully managed.</span>
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
          <span class="topo-disk-io" title="Disk I/O Reads & Writes">R: ${readsStr} · W: ${writesStr}</span>
        </div>
        <div class="topo-disk-actions">
          <button class="btn-locate-topo" data-dev="${escapeHtml(m.device || m.name)}" title="Blink drive activity LED">
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
        ${pool.parity_protected ? '<span class="topo-parity-badge" title="Protected against disk failure">🛡️ Parity Protected</span>' : ''}
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
      <button class="btn-pool-scrub btn-pill-toggle" data-pool-id="${escapeHtml(pool.id)}" title="Trigger filesystem scrub or parity check">⚡ Scrub Pool</button>
      ${pool.fs_type === 'btrfs' ? `<button class="btn-pool-snaps btn-pill-toggle" data-pool-id="${escapeHtml(pool.id)}" style="background:rgba(14,165,233,0.15); border-color:rgba(14,165,233,0.3); color:#38bdf8;" title="Manage Subvolume Snapshots">📸 Snapshots</button>` : ''}
      ${!isObserver && pool.id !== 'default_pool' ? `<button class="btn-pool-destroy btn-pill-toggle" data-pool-id="${escapeHtml(pool.id)}" style="background:rgba(239,68,68,0.15); border-color:rgba(239,68,68,0.3); color:#f87171;" title="Destroy storage pool">🗑️ Destroy</button>` : ''}
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
      if (confirm(`Are you sure you want to destroy pool '${pid}'? All mounted data will be unmounted.`)) {
        try {
          await api.delete(`/api/storage/pools/${pid}`);
          showToast(`Pool '${pid}' destroyed.`, 'info');
          fetchAndRenderStorageTopology(container);
        } catch (err) {
          showToast(err.message || 'Failed to destroy pool', 'error');
        }
      }
    }
  });
}

/**
 * Fetches and renders Storage Topology Tree
 */
export async function fetchAndRenderStorageTopology(container) {
  if (!container) return;
  container.innerHTML = `
    <div style="text-align:center; padding:30px; color:var(--muted);">
      <div class="loader-spinner" style="margin:0 auto 10px;"></div>
      Scanning storage pools and array topology...
    </div>
  `;

  try {
    const [data, platformData] = await Promise.all([
      api.get('/api/storage/pools'),
      api.get('/api/storage/platform').catch(() => ({})),
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

    if (!data || !Array.isArray(data.pools) || data.pools.length === 0) {
      renderStorageTopologyTree(container, state.latestStats?.disks, state.latestStats?.unraid || {});
      return;
    }
    renderStructuredPoolsTopology(container, data);
  } catch (err) {
    console.warn('[ZettNAS] Failed to load /api/storage/pools, falling back to local disks:', err);
    renderStorageTopologyTree(container, state.latestStats?.disks, state.latestStats?.unraid || {});
  }
}

/**
 * Fetches and renders Network Shares & Protocols
 */
export async function fetchAndRenderNetworkShares(container) {
  if (!container) return;
  container.innerHTML = `
    <div style="text-align:center; padding:30px; color:var(--muted);">
      <div class="loader-spinner" style="margin:0 auto 10px;"></div>
      Auditing network shares and protocols...
    </div>
  `;

  try {
    const [sharesData, platformData] = await Promise.all([
      api.get('/api/storage/shares'),
      api.get('/api/storage/platform').catch(() => ({})),
    ]);

    const shares = sharesData.shares || [];
    const isObserver = sharesData.is_observer_mode ?? true;
    const platform = platformData.platform || sharesData.platform || 'unraid';
    const canManageShares = platformData?.capabilities?.can_manage_shares ?? (!isObserver);

    const btnCreateShare = document.getElementById('btn-create-network-share');
    if (btnCreateShare) {
      btnCreateShare.style.display = canManageShares ? 'inline-flex' : 'none';
      btnCreateShare.onclick = () => openCreateNetworkShareModal(() => fetchAndRenderNetworkShares(container));
    }

    // Update platform badge in pane header
    const badge = document.getElementById('mgmt-shares-platform-badge');
    if (badge) {
      if (isObserver) {
        badge.textContent = `${platform.toUpperCase()} · Observer Mode`;
        badge.style.background = 'rgba(59,245,139,0.12)';
        badge.style.color = '#3bf58b';
      } else {
        badge.textContent = `${platform.toUpperCase()} · Active Provisioner`;
        badge.style.background = 'rgba(99,102,241,0.15)';
        badge.style.color = '#818cf8';
      }
    }

    if (shares.length === 0) {
      container.innerHTML = `
        <div class="empty-shares-box" style="text-align:center; padding:40px; color:var(--muted);">
          <svg viewBox="0 0 24 24" width="32" height="32" style="margin:0 auto 10px; opacity:0.5;"><use href="#i-storage"/></svg>
          <div>No active network shares detected on host.</div>
        </div>
      `;
      return;
    }

    if (shares.length === 0) {
      container.innerHTML = `
        <div class="empty-shares-box" style="text-align:center; padding:40px; color:var(--muted);">
          <svg viewBox="0 0 24 24" width="32" height="32" style="margin:0 auto 10px; opacity:0.5;"><use href="#i-storage"/></svg>
          <div>No active network shares detected on host.</div>
        </div>
      `;
      return;
    }

    let grid = container.querySelector('.storage-shares-grid');
    if (!grid) {
      container.innerHTML = `<div class="storage-shares-grid"></div>`;
      grid = container.querySelector('.storage-shares-grid');
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
      <div style="text-align:center; padding:30px; color:var(--alert, #ef4444);">
        Failed to audit network shares: ${escapeHtml(err.message || 'Unknown error')}
      </div>
    `;
  }
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
      <span class="proto-tag ${s.export_smb ? 'proto-on' : 'proto-off'}" title="Samba SMB Protocol">SMB</span>
      <span class="proto-tag ${s.export_nfs ? 'proto-on' : 'proto-off'}" title="NFS Protocol">NFS</span>
      <span class="proto-tag proto-on" title="Universal WebDAV Port 8084">WebDAV :8084</span>
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
      <button class="btn-share-reveal" data-path="${escapeHtml(s.mountpoint || '')}" title="Open share in File Explorer">
        📂 Open in File Explorer
      </button>
      ${canManageShares ? `
        <button class="btn-share-delete btn-pill-toggle" data-share-name="${escapeHtml(s.name)}" style="background:rgba(239,68,68,0.15); border-color:rgba(239,68,68,0.3); color:#f87171; padding:3px 8px; font-size:10.5px;" title="Delete network share">
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
      if (confirm(`Are you sure you want to remove share '${sName}'?`)) {
        try {
          await api.delete(`/api/storage/shares/${sName}`);
          showToast(`Share '${sName}' removed.`, 'info');
          fetchAndRenderNetworkShares(container);
        } catch (err) {
          showToast(err.message || 'Failed to delete share', 'error');
        }
      }
    }
  });
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
    const [webdavStatus, remotes] = await Promise.all([
      api.get('/api/webdav/status'),
      api.get('/api/remotes')
    ]);

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
        <div style="text-align:center; padding:36px 20px; background:rgba(0,0,0,0.25); border:1px dashed rgba(255,255,255,0.12); border-radius:10px;">
          <div style="font-size:32px; margin-bottom:8px;">☁️</div>
          <div style="font-size:14px; font-weight:700; color:#fff; margin-bottom:4px;">No Cloud Remotes Connected</div>
          <div style="font-size:12px; color:var(--muted); max-width:440px; margin:0 auto 16px auto; line-height:1.45;">
            Connect your cloud storage buckets (Amazon S3, Backblaze B2, Google Drive, OneDrive, SFTP) to mount them directly into the ZettNAS File Explorer (/mnt/remotes).
          </div>
          <button class="btn-pill-toggle btn-trigger-new-remote" style="padding:7px 18px; font-size:12px; font-weight:700; background:var(--brand, #0ea5e9); color:#fff; border-color:var(--brand, #0ea5e9);">
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

            <div style="font-size:11px; color:var(--muted); font-family:monospace; background:rgba(0,0,0,0.3); padding:6px 8px; border-radius:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
              /mnt/remotes/${escapeHtml(r.name)}
            </div>

            <div class="remote-card-actions">
              <div>
                ${isMounted ? `
                  <button class="btn-remote-reveal btn-pill-toggle" data-path="${escapeHtml(r.mount_path)}" title="Open in File Explorer" style="padding:4px 10px; font-size:11px; background:rgba(14,165,233,0.15); color:#38bdf8; border-color:rgba(14,165,233,0.3);">
                    📂 Open in File Explorer
                  </button>
                ` : `
                  <button class="btn-remote-mount btn-pill-toggle" data-name="${escapeHtml(r.name)}" title="Mount to /mnt/remotes" style="padding:4px 10px; font-size:11px; background:rgba(59,245,139,0.12); color:#3bf58b; border-color:rgba(59,245,139,0.25);">
                    ▶ Mount
                  </button>
                `}
              </div>
              <div style="display:flex; gap:6px;">
                ${isMounted ? `
                  <button class="btn-remote-unmount btn-pill-toggle" data-name="${escapeHtml(r.name)}" title="Unmount from system" style="padding:4px 8px; font-size:11px;">
                    ⏹ Unmount
                  </button>
                ` : ''}
                <button class="btn-remote-delete btn-pill-toggle" data-name="${escapeHtml(r.name)}" title="Delete remote" style="padding:4px 8px; font-size:11px; color:var(--crit,#ef4444); border-color:rgba(239,68,68,0.25);">
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
              <svg class="ic" style="width:18px; height:18px; fill:currentColor; color:var(--brand, #0ea5e9);"><use href="#i-globe"/></svg>
              <span>Universal WebDAV File Server</span>
              <span class="webdav-status-pill ${webdavPillClass}">${webdavPillText}</span>
            </div>
            <div style="display:flex; gap:8px; align-items:center;">
              <button class="btn-pill-toggle" id="btn-webdav-toggle" style="padding:5px 12px; font-size:11px; font-weight:700;">
                ${isRunning ? '⏹ Stop Server' : '▶ Start Server'}
              </button>
              <button class="btn-pill-toggle" id="btn-webdav-restart" style="padding:5px 10px; font-size:11px;" title="Restart WebDAV Server">
                ↺ Restart
              </button>
              <button class="btn-pill-toggle" id="btn-webdav-config-open" style="padding:5px 10px; font-size:11px;" title="Configure WebDAV settings">
                ⚙️ Settings
              </button>
            </div>
          </div>

          <div style="display:flex; gap:16px; flex-wrap:wrap; font-size:11.5px; color:var(--muted); align-items:center;">
            <span>Line-Rate Port: <strong style="color:#fff;">${webdavStatus.port}</strong></span>
            <span>Root Path: <code style="color:#38bdf8;">${escapeHtml(webdavStatus.root_path)}</code></span>
            <span>Mode: <strong style="color:#fff;">${webdavStatus.read_only ? 'Read-Only' : 'Read/Write'}</strong></span>
            <span>Auth: <strong style="color:#fff;">${webdavStatus.auth_enabled ? 'Basic Auth (' + escapeHtml(webdavStatus.username) + ')' : 'Anonymous / None'}</strong></span>
          </div>

          <!-- Quick Connect Grid -->
          <div class="webdav-quickconnect-grid">
            <div class="webdav-qc-item">
              <div class="webdav-qc-label">
                <span>🍏 macOS Finder (⌘K)</span>
                <button class="btn-qc-copy" data-copy="${escapeHtml(qc.macos || '')}" title="Copy command">📋 Copy</button>
              </div>
              <div class="webdav-qc-code">
                <span>${escapeHtml(qc.macos || '')}</span>
              </div>
            </div>

            <div class="webdav-qc-item">
              <div class="webdav-qc-label">
                <span>🪟 Windows Map Network Drive</span>
                <button class="btn-qc-copy" data-copy="${escapeHtml(qc.windows || '')}" title="Copy command">📋 Copy</button>
              </div>
              <div class="webdav-qc-code">
                <span>${escapeHtml(qc.windows || '')}</span>
              </div>
            </div>

            <div class="webdav-qc-item">
              <div class="webdav-qc-label">
                <span>📱 iOS & Android Files</span>
                <button class="btn-qc-copy" data-copy="${escapeHtml(qc.ios || '')}" title="Copy URL">📋 Copy</button>
              </div>
              <div class="webdav-qc-code">
                <span>${escapeHtml(qc.ios || '')}</span>
              </div>
            </div>

            <div class="webdav-qc-item">
              <div class="webdav-qc-label">
                <span>🌐 Toolkit HTTP Reverse Proxy</span>
                <button class="btn-qc-copy" data-copy="${escapeHtml(proxyUrl)}" title="Copy Proxy URL">📋 Copy</button>
              </div>
              <div class="webdav-qc-code">
                <span>${escapeHtml(proxyUrl)}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Section 2: Connected Cloud & Remote Drives -->
        <div style="display:flex; flex-direction:column; gap:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-size:13px; font-weight:800; color:#fff; letter-spacing:0.5px; text-transform:uppercase;">
              Connected Cloud Drives & Buckets (${remotes ? remotes.length : 0})
            </div>
          </div>
          ${remotesHtml}
        </div>
      </div>
    `;

    // Event bindings
    // WebDAV toggle
    container.querySelector('#btn-webdav-toggle')?.addEventListener('click', async () => {
      playChirp(600, 0.08, 'sine');
      try {
        await api.post('/api/webdav/toggle', { enabled: !isRunning });
        showToast(isRunning ? 'WebDAV server stopped.' : 'WebDAV server started on port ' + webdavStatus.port, 'info');
        fetchAndRenderRemoteStorage(container);
      } catch (e) {
        showToast('Failed to toggle WebDAV: ' + (e.message || 'Error'), 'error');
      }
    });

    // WebDAV restart
    container.querySelector('#btn-webdav-restart')?.addEventListener('click', async () => {
      playChirp(700, 0.08, 'sine');
      try {
        await api.post('/api/webdav/restart');
        showToast('WebDAV server restarted.', 'info');
        fetchAndRenderRemoteStorage(container);
      } catch (e) {
        showToast('Failed to restart WebDAV: ' + (e.message || 'Error'), 'error');
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
            showToast('Copied to clipboard!', 'info');
          } else {
            showToast('Failed to copy to clipboard', 'warn');
          }
        }
      });
    });

    // "+ Connect First Cloud Remote" CTA button
    container.querySelector('.btn-trigger-new-remote')?.addEventListener('click', () => {
      playChirp(640, 0.08, 'triangle');
      openNewCloudRemoteModal(() => fetchAndRenderRemoteStorage(container));
    });

    // Open in File Explorer
    container.querySelectorAll('.btn-remote-reveal').forEach((btn) => {
      btn.addEventListener('click', () => {
        const path = btn.dataset.path;
        playChirp(720, 0.08, 'triangle');
        ZettEventBus.emit('window:open', { id: 'file-manager-window', path });
        showToast(`Opened ${path} in File Explorer`, 'info');
      });
    });

    // Mount remote
    container.querySelectorAll('.btn-remote-mount').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const name = btn.dataset.name;
        btn.textContent = 'Mounting...';
        btn.disabled = true;
        try {
          await api.post(`/api/remotes/${name}/mount`, {});
          playChirp(800, 0.1, 'sine');
          showToast(`Remote '${name}' mounted to /mnt/remotes/${name}`, 'info');
          fetchAndRenderRemoteStorage(container);
        } catch (e) {
          showToast(`Mount failed: ${e.message || 'Error'}`, 'error');
          fetchAndRenderRemoteStorage(container);
        }
      });
    });

    // Unmount remote
    container.querySelectorAll('.btn-remote-unmount').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const name = btn.dataset.name;
        btn.textContent = 'Unmounting...';
        btn.disabled = true;
        try {
          await api.post(`/api/remotes/${name}/unmount`);
          playChirp(500, 0.1, 'sine');
          showToast(`Remote '${name}' unmounted.`, 'info');
          fetchAndRenderRemoteStorage(container);
        } catch (e) {
          showToast(`Unmount failed: ${e.message || 'Error'}`, 'error');
          fetchAndRenderRemoteStorage(container);
        }
      });
    });

    // Delete remote
    container.querySelectorAll('.btn-remote-delete').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const name = btn.dataset.name;
        if (confirm(`Are you sure you want to remove remote '${name}'? This will unmount and delete its stored credentials.`)) {
          try {
            await api.delete(`/api/remotes/${name}`);
            playChirp(440, 0.1, 'sawtooth');
            showToast(`Remote '${name}' deleted.`, 'info');
            fetchAndRenderRemoteStorage(container);
          } catch (e) {
            showToast(`Failed to delete remote: ${e.message || 'Error'}`, 'error');
          }
        }
      });
    });

  } catch (err) {
    console.error('[ZettNAS] Failed to fetch remote storage:', err);
    container.innerHTML = `
      <div style="text-align:center; padding:30px; color:var(--alert, #ef4444);">
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
  const authToggle = document.getElementById('webdav-cfg-auth-toggle');
  const roToggle = document.getElementById('webdav-cfg-readonly-toggle');

  if (portInput) portInput.value = currentConfig?.port || 8084;
  if (rootInput) rootInput.value = currentConfig?.root_path || '/mnt/user';
  if (userInput) userInput.value = currentConfig?.username || 'admin';
  if (passInput) passInput.value = '';
  if (authToggle) authToggle.checked = currentConfig?.auth_enabled ?? true;
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
        auth_enabled: authToggle.checked,
        read_only: roToggle.checked
      };
      if (passInput.value.trim()) {
        payload.password = passInput.value.trim();
      }
      try {
        await api.post('/api/webdav/config', payload);
        close();
        playChirp(880, 0.1, 'sine');
        showToast('WebDAV configuration saved and server restarted!', 'info');
        if (onSuccess) onSuccess();
      } catch (err) {
        showToast('Error saving WebDAV config: ' + (err.message || 'Error'), 'error');
      }
    };
  }
}

let _providersCache = null;

export async function openNewCloudRemoteModal(onSuccess) {
  const modal = document.getElementById('modal-new-cloud-remote');
  if (!modal) return;

  const providerSelect = document.getElementById('new-remote-provider-select');
  const descEl = document.getElementById('new-remote-provider-desc');
  const dynamicFields = document.getElementById('new-remote-dynamic-fields');
  const nameInput = document.getElementById('new-remote-name');
  const autoMountToggle = document.getElementById('new-remote-auto-mount');
  const errorBox = document.getElementById('new-remote-error-box');

  if (errorBox) errorBox.style.display = 'none';
  if (nameInput) nameInput.value = '';

  modal.classList.add('open');
  modal.style.display = 'flex';

  const close = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  };
  const cBtn = document.getElementById('modal-remote-close-btn');
  const canBtn = document.getElementById('modal-remote-cancel-btn');
  if (cBtn) cBtn.onclick = close;
  if (canBtn) canBtn.onclick = close;

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
        const selectedType = providerSelect.value;
        const prov = providers.find((p) => p.type === selectedType) || providers[0];
        if (descEl) descEl.textContent = prov ? prov.description || '' : '';

        if (dynamicFields && prov) {
          dynamicFields.innerHTML = (prov.fields || []).map((f) => {
            if (f.type === 'select') {
              const opts = (f.options || []).map((o) => `<option value="${o}" ${o === f.default ? 'selected' : ''}>${o}</option>`).join('');
              return `
                <div>
                  <label style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:4px; letter-spacing:0.5px;">${escapeHtml(f.label.toUpperCase())}</label>
                  <select name="${escapeHtml(f.name)}" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.3); padding:8px 10px; color:#fff; border-radius:6px; font-size:12px;">
                    ${opts}
                  </select>
                </div>
              `;
            } else {
              return `
                <div>
                  <label style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:4px; letter-spacing:0.5px;">
                    ${escapeHtml(f.label.toUpperCase())} ${f.required ? '<span style="color:var(--crit,#ef4444);">*</span>' : ''}
                  </label>
                  <input type="${f.type === 'password' ? 'password' : 'text'}"
                    name="${escapeHtml(f.name)}"
                    placeholder="${escapeHtml(f.placeholder || '')}"
                    value="${escapeHtml(f.default != null ? String(f.default) : '')}"
                    class="tz-select-input"
                    style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.3); padding:8px 10px; color:#fff; border-radius:6px; font-size:12px;"
                    ${f.required ? 'required' : ''} />
                </div>
              `;
            }
          }).join('');
        }
      };

      providerSelect.onchange = renderFields;
      renderFields();
    }

    const form = document.getElementById('new-remote-form');
    if (form) {
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
          submitBtn.textContent = 'Connecting...';
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
          showToast(`Cloud remote '${name}' connected successfully!`, 'info');
          if (onSuccess) onSuccess();
        } catch (err) {
          if (errorBox) {
            errorBox.textContent = err.message || 'Failed to connect remote';
            errorBox.style.display = 'block';
          }
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Save & Connect Remote';
          }
        }
      };
    }
  } catch (err) {
    showToast('Failed to load storage providers: ' + (err.message || 'Error'), 'error');
  }
}

/**
 * Opens Create Storage Pool Modal (Generic Linux Active Provisioner)
 */
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

  // Populate available physical disks
  if (disksContainer) {
    disksContainer.innerHTML = '<div style="color:var(--muted); font-size:11px;">Scanning available physical disks...</div>';
    try {
      const disksRes = await api.get('/api/system/disks').catch(() => []);
      const disksList = Array.isArray(disksRes) ? disksRes : (disksRes.disks || []);
      const filtered = disksList.filter((d) => {
        const n = String(d.dev || d.name || '').toLowerCase();
        return !n.includes('loop') && !n.includes('zram') && !n.includes('boot');
      });

      if (filtered.length === 0) {
        disksContainer.innerHTML = '<div style="color:var(--muted); font-size:11px;">No unassigned disks available.</div>';
      } else {
        disksContainer.innerHTML = filtered.map((d) => `
          <label style="display:flex; align-items:center; gap:8px; font-size:12px; color:#fff; cursor:pointer;">
            <input type="checkbox" name="pool-disk" value="${escapeHtml(d.dev || d.name)}" style="accent-color:var(--ok2);" />
            <span><strong>/dev/${escapeHtml(d.dev || d.name)}</strong> (${d.size || formatBytes(d.size_bytes)}) · ${escapeHtml(d.model || '')}</span>
          </label>
        `).join('');
      }
    } catch (dErr) {
      disksContainer.innerHTML = '<div style="color:var(--muted); font-size:11px;">Failed to scan disks.</div>';
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
          errorBox.textContent = 'Please select at least one member disk.';
          errorBox.style.display = 'block';
        }
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Provisioning...';
      }

      try {
        await api.post('/api/storage/pools', {
          name,
          fs_type: fsType,
          profile,
          disks,
          mountpoint,
        });

        close();
        playChirp(880, 0.12, 'sine');
        showToast(`Storage pool '${name}' provisioned successfully!`, 'info');
        if (onSuccess) onSuccess();
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = err.message || 'Failed to create storage pool';
          errorBox.style.display = 'block';
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = '🚀 Provision Storage Pool';
        }
      }
    };
  }
}

/**
 * Opens Create Network Share Modal (Samba / WebDAV)
 */
export function openCreateNetworkShareModal(onSuccess) {
  const modal = document.getElementById('modal-create-network-share');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-create-share-close-btn');
  const cancelBtn = document.getElementById('modal-create-share-cancel-btn');
  const form = document.getElementById('create-share-form');
  const errorBox = document.getElementById('create-share-error-box');
  const submitBtn = document.getElementById('create-share-submit-btn');

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

  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (errorBox) errorBox.style.display = 'none';

      const name = document.getElementById('create-share-name')?.value.trim();
      const path = document.getElementById('create-share-path')?.value.trim() || '';
      const comment = document.getElementById('create-share-comment')?.value.trim() || '';
      const security = document.getElementById('create-share-security')?.value || 'public';
      const readOnly = document.getElementById('create-share-readonly')?.checked ?? false;
      const isTm = document.getElementById('create-share-timemachine')?.checked ?? false;

      if (!name) return;

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Provisioning...';
      }

      try {
        await api.post('/api/storage/shares', {
          name,
          path,
          comment,
          security,
          read_only: readOnly,
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
        showToast(`Share '${name}' created successfully!`, 'info');
        if (onSuccess) onSuccess();
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = err.message || 'Failed to create share';
          errorBox.style.display = 'block';
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = '📁 Provision Share';
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
    listMount.innerHTML = '<div style="padding:15px; text-align:center; color:var(--muted); font-size:11px;">Loading snapshots...</div>';
    try {
      const snaps = await api.get(`/api/storage/pools/${poolId}/snapshots`);
      if (!Array.isArray(snaps) || snaps.length === 0) {
        listMount.innerHTML = '<div style="padding:20px; text-align:center; color:var(--muted); font-size:11px;">No active subvolume snapshots found.</div>';
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
          const dt = s.created_at ? new Date(s.created_at * 1000).toLocaleString() : '--';
          const tr = document.createElement('tr');
          tr.dataset.key = s.name;
          tr.innerHTML = `
            <td><strong>${escapeHtml(s.name)}</strong></td>
            <td style="font-family:monospace; font-size:11px; color:#38bdf8;">${escapeHtml(s.path)}</td>
            <td style="color:var(--muted); font-size:11px;">${dt}</td>
            <td>
              <button class="btn-snap-del btn-pill-toggle" data-snap="${escapeHtml(s.name)}" style="background:rgba(239,68,68,0.15); border-color:rgba(239,68,68,0.3); color:#f87171; padding:2px 8px; font-size:10.5px; cursor:pointer;">
                🗑️ Delete
              </button>
            </td>
          `;
          return tr;
        },
        (tr, s) => {
          const dt = s.created_at ? new Date(s.created_at * 1000).toLocaleString() : '--';
          const pathTd = tr.children[1];
          if (pathTd) pathTd.textContent = s.path;
          const dtTd = tr.children[2];
          if (dtTd) dtTd.textContent = dt;
        }
      );
    } catch (err) {
      listMount.innerHTML = `<div style="padding:15px; color:#f87171; font-size:11px;">Error loading snapshots: ${escapeHtml(err.message || '')}</div>`;
    }
  }

  function bindSnapshotsTableEvents(tbody, pId, onReload) {
    if (tbody._eventsBound) return;
    tbody._eventsBound = true;

    tbody.addEventListener('click', async (e) => {
      const btn = e.target.closest('.btn-snap-del');
      if (!btn) return;
      const sName = btn.dataset.snap;
      if (confirm(`Delete snapshot '${sName}'?`)) {
        try {
          await api.delete(`/api/storage/pools/${pId}/snapshots/${sName}`);
          showToast(`Snapshot '${sName}' deleted.`, 'info');
          onReload();
        } catch (err) {
          showToast(err.message || 'Failed to delete snapshot', 'error');
        }
      }
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
        showToast(`Snapshot '${snapName}' taken!`, 'info');
        snapNameInput.value = '';
        loadSnapshots();
      } catch (err) {
        showToast(err.message || 'Failed to create snapshot', 'error');
      }
    };
  }
}


