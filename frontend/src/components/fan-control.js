/**
 * ZettNAS Toolkit Fan Curve Workstation
 * Interactive SVG curve editor, thermal zone isolation, and PWM profile management.
 */
import { api } from '../api.js';
import { state } from '../state.js';
import { ZettEventBus } from '../event-bus.js';
import { t } from '../i18n.js';

const $ = (id) => document.getElementById(id);

let isDraggingCurve = false;
let dragIndex = -1;
let _curveInitialized = false;
let _lastCurveSaveTime = 0;
let currentFanProfile = 'auto';

export function tempToX(t) { return 38 + ((Math.max(30, Math.min(60, t)) - 30) / 30) * (285 - 38); }
export function xToTemp(x) { return Math.round(30 + ((x - 38) / (285 - 38)) * 30); }
export function pctToY(p) { return 100 - (Math.max(0, Math.min(100, p)) / 100) * (100 - 20); }
export function yToPct(y) { return Math.round(100 - ((y - 20) / (100 - 20)) * 100); }

export function renderCurveLines() {
  const pts = state.curvePoints;
  const path = $('curve-svg-path') || $('fan-curve-path');
  const area = $('curve-area-path') || $('fan-curve-area');
  if (!path || !area) return;

  const svgCoords = pts.map((p) => [tempToX(p[0]), pctToY(p[1])]);

  let d = `M ${svgCoords[0][0]} ${svgCoords[0][1]}`;
  for (let i = 1; i < svgCoords.length; i++) {
    d += ` L ${svgCoords[i][0]} ${svgCoords[i][1]}`;
  }
  path.setAttribute('d', d);

  const dArea = `${d} L ${svgCoords[svgCoords.length - 1][0]} 100 L ${svgCoords[0][0]} 100 Z`;
  area.setAttribute('d', dArea);

  pts.forEach((p, i) => {
    const handle = $(`ch-${i}`);
    if (handle) {
      handle.setAttribute('cx', svgCoords[i][0]);
      handle.setAttribute('cy', svgCoords[i][1]);
    }
  });

  const rangeVal = $('fan-curve-range-val');
  if (rangeVal && pts.length >= 4) {
    rangeVal.textContent = `${pts[1][0]}°C – ${pts[2][0]}°C (${pts[1][1]}% – ${pts[2][1]}%)`;
  }
}

export function updateFanCurveWorkstation(s) {
  if (!s || !s.fan_control) return;
  const fc = s.fan_control;

  if ($('zp-z1-temp')) $('zp-z1-temp').textContent = `${fc.zone1_temp}°C`;
  if ($('zp-z1-pwm')) $('zp-z1-pwm').textContent = `PWM: ${fc.zone1_pwm}`;
  if ($('zp-z2-temp')) $('zp-z2-temp').textContent = `${fc.zone2_temp}°C`;
  if ($('zp-z2-pwm')) $('zp-z2-pwm').textContent = `PWM: ${fc.zone2_pwm}`;
  if ($('zp-cpu-temp')) $('zp-cpu-temp').textContent = `${fc.cpu_temp}°C`;
  if ($('zp-cpu-pwm')) $('zp-cpu-pwm').textContent = fc.ctrl_cpu_fan ? `PWM: ${fc.cpu_pwm}` : 'BIOS Auto';

  const hBadge = $('hysteresis-badge');
  if (hBadge) {
    if (fc.disk_hold_remaining > 0) {
      hBadge.textContent = `HOLD: ACTIVE (${fc.disk_hold_remaining}s)`;
      hBadge.style.background = 'rgba(245,183,49,0.15)';
      hBadge.style.color = 'var(--warn)';
      hBadge.style.borderColor = 'rgba(245,183,49,0.4)';
    } else if (fc.ctrl_cpu_fan && fc.cpu_hold_remaining > 0) {
      hBadge.textContent = `CPU HOLD (${fc.cpu_hold_remaining}s)`;
      hBadge.style.background = 'rgba(245,183,49,0.15)';
      hBadge.style.color = 'var(--warn)';
      hBadge.style.borderColor = 'rgba(245,183,49,0.4)';
    } else {
      hBadge.textContent = 'HOLD: READY';
      hBadge.style.background = 'rgba(51,209,122,0.15)';
      hBadge.style.color = 'var(--ok)';
      hBadge.style.borderColor = 'rgba(51,209,122,0.35)';
    }
  }

  const curveUpdateCooldown = (Date.now() - _lastCurveSaveTime) < 5000;
  if (!isDraggingCurve && !curveUpdateCooldown) {
    if (fc.curve_points && fc.curve_points.length > 0) {
      if (JSON.stringify(state.curvePoints) !== JSON.stringify(fc.curve_points)) {
        state.setCurvePoints(fc.curve_points);
      }
      _curveInitialized = true;
    } else if (!_curveInitialized) {
      const tMin = fc.temp_min || 37;
      const tMax = fc.temp_max || 50;
      state.setCurvePoints([[30, 32], [tMin, 32], [tMax, 100], [60, 100]]);
      _curveInitialized = true;
    }
  }

  renderCurveLines();

  const graphMinT = 30;
  const graphMaxT = 60;
  const tSpan = 30;

  const normZ1X = Math.max(graphMinT, Math.min(graphMaxT, fc.zone1_temp));
  const svgZ1X = 38 + ((normZ1X - graphMinT) / tSpan) * (285 - 38);
  const normZ1Pwm = Math.max(58, Math.min(183, fc.zone1_pwm));
  const svgZ1Y = 100 - ((normZ1Pwm - 58) / (183 - 58)) * (100 - 20);

  const normZ2X = Math.max(graphMinT, Math.min(graphMaxT, fc.zone2_temp));
  const svgZ2X = 38 + ((normZ2X - graphMinT) / tSpan) * (285 - 38);
  const normZ2Pwm = Math.max(58, Math.min(183, fc.zone2_pwm));
  const svgZ2Y = 100 - ((normZ2Pwm - 58) / (183 - 58)) * (100 - 20);

  const normCpuX = Math.max(30, Math.min(85, fc.cpu_temp));
  const svgCpuX = 38 + ((normCpuX - 30) / (85 - 30)) * (285 - 38);
  const normCpuPwm = Math.max(58, Math.min(183, fc.cpu_pwm || 85));
  const svgCpuY = 100 - ((normCpuPwm - 58) / (183 - 58)) * (100 - 20);

  const dotZ1 = $('curve-dot-z1');
  const dotZ2 = $('curve-dot-z2');
  const dotCpu = $('curve-dot-cpu');

  if (dotZ1) {
    dotZ1.setAttribute('cx', svgZ1X);
    dotZ1.setAttribute('cy', svgZ1Y);
    dotZ1.style.display = (state.selectedZoneFilter === 'all' || state.selectedZoneFilter === 'zone1') ? 'block' : 'none';
  }

  if (dotZ2) {
    dotZ2.setAttribute('cx', svgZ2X);
    dotZ2.setAttribute('cy', svgZ2Y);
    dotZ2.style.display = (state.selectedZoneFilter === 'all' || state.selectedZoneFilter === 'zone2') ? 'block' : 'none';
  }

  if (dotCpu) {
    dotCpu.setAttribute('cx', svgCpuX);
    dotCpu.setAttribute('cy', svgCpuY);
    dotCpu.style.display = (state.selectedZoneFilter === 'all' || state.selectedZoneFilter === 'cpu') ? 'block' : 'none';
  }

  const readout = $('curve-readout-text');
  if (readout) {
    if (state.selectedZoneFilter === 'zone1') {
      readout.textContent = `Zone 1 Isolated: ${fc.zone1_temp}°C (${fc.zone1_pwm} PWM)`;
    } else if (state.selectedZoneFilter === 'zone2') {
      readout.textContent = `Zone 2 Isolated: ${fc.zone2_temp}°C (${fc.zone2_pwm} PWM)`;
    } else if (state.selectedZoneFilter === 'cpu') {
      readout.textContent = `CPU Isolated: ${fc.cpu_temp}°C (${fc.cpu_pwm || 'Auto'} PWM)`;
    } else {
      const maxDisk = Math.max(fc.zone1_temp, fc.zone2_temp);
      readout.textContent = `All Zones: Max Bay ${maxDisk}°C`;
    }
  }
}

export function setZoneFilter(filterKey) {
  state.setZoneFilter(filterKey);

  const colZ1 = $('fan-col-zone1');
  const colZ2 = $('fan-col-zone2');
  const colCpu = $('fan-col-cpu');
  const btnReset = $('btn-reset-curve');
  const instruction = $('curve-filter-instruction');

  if (colZ1) colZ1.classList.toggle('active-zone-filter', filterKey === 'zone1');
  if (colZ2) colZ2.classList.toggle('active-zone-filter', filterKey === 'zone2');
  if (colCpu) colCpu.classList.toggle('active-zone-filter', filterKey === 'cpu');

  if (btnReset) {
    btnReset.style.display = (filterKey !== 'all') ? 'inline-block' : 'none';
  }

  if (instruction) {
    if (filterKey === 'all') {
      instruction.textContent = 'Displaying all thermal zones. Click a zone tachometer above or below to isolate.';
    } else {
      const nameMap = { zone1: 'Zone 1 (Left Bays)', zone2: 'Zone 2 (Right Bays)', cpu: 'CPU Package' };
      instruction.textContent = `Filtered to ${nameMap[filterKey]}. Only this zone is active on the graph.`;
    }
  }

  if (state.latestStats) updateFanCurveWorkstation(state.latestStats);
}

export function initFanControl() {
  const colZ1 = $('fan-col-zone1');
  const colZ2 = $('fan-col-zone2');
  const colCpu = $('fan-col-cpu');
  const legZ1 = $('leg-item-z1');
  const legZ2 = $('leg-item-z2');
  const legCpu = $('leg-item-cpu');
  const btnReset = $('btn-reset-curve');
  const fanProfileBtns = document.querySelectorAll('.fan-profile-btn');
  const fanPwmSlider = $('fan-pwm-slider');
  const fanPwmVal = $('fan-pwm-val-display') || $('fan-pwm-val');
  const cpuFanToggle = $('cpu-fan-toggle') || $('fan-ctrl-cpu');
  const fanCurveSvg = document.querySelector('.fan-curve-svg');

  let fanPwmDebounce = null;

  const toggleFilter = (key) => {
    setZoneFilter(state.selectedZoneFilter === key ? 'all' : key);
  };

  if (colZ1) colZ1.addEventListener('click', () => toggleFilter('zone1'));
  if (colZ2) colZ2.addEventListener('click', () => toggleFilter('zone2'));
  if (colCpu) colCpu.addEventListener('click', () => toggleFilter('cpu'));

  if (legZ1) legZ1.addEventListener('click', () => toggleFilter('zone1'));
  if (legZ2) legZ2.addEventListener('click', () => toggleFilter('zone2'));
  if (legCpu) legCpu.addEventListener('click', () => toggleFilter('cpu'));

  if (btnReset) btnReset.addEventListener('click', () => setZoneFilter('all'));

  function updateFanUiState(profile, pct) {
    currentFanProfile = profile;
    fanProfileBtns.forEach((b) => b.classList.toggle('active', b.dataset.fanProfile === profile));
    if (fanPwmSlider && pct !== undefined) {
      fanPwmSlider.value = pct;
    }
    if (fanPwmVal) {
      if (profile === 'manual') {
        const val = pct !== undefined ? pct : (fanPwmSlider ? fanPwmSlider.value : 60);
        fanPwmVal.textContent = `${val}% (Manual Active)`;
        fanPwmVal.style.color = 'var(--ok2)';
        fanPwmVal.style.opacity = '1';
        fanPwmVal.style.fontWeight = '700';
      } else {
        fanPwmVal.textContent = 'Auto Curve';
        fanPwmVal.style.color = 'var(--muted)';
        fanPwmVal.style.opacity = '0.5';
        fanPwmVal.style.fontWeight = '500';
      }
    }
  }

  async function postFanPwm(profile, manualPct, ctrlCpu, tMin, tMax, cPoints) {
    const curMin = tMin !== undefined ? tMin : 37;
    const curMax = tMax !== undefined ? tMax : 50;
    const mPct = (manualPct === null || manualPct === undefined) ? (fanPwmSlider ? fanPwmSlider.value : 60) : manualPct;
    try {
      const data = await api.post('/api/fans', {
        profile,
        manual_pct: parseInt(mPct, 10),
        ctrl_cpu_fan: ctrlCpu !== undefined ? ctrlCpu : (cpuFanToggle ? cpuFanToggle.checked : false),
        temp_min: curMin,
        temp_max: curMax,
        curve_points: cPoints || state.curvePoints
      });
      updateFanUiState(data.profile, data.manual_pct);
    } catch (e) {
      console.warn('Failed to update fans', e);
    }
  }

  async function fetchFanState() {
    try {
      const data = await api.get('/api/fans');
      const prof = data.profile || 'auto';
      const pct = data.manual_pct !== undefined ? data.manual_pct : 60;
      const tMin = data.temp_min !== undefined ? data.temp_min : 37;
      const tMax = data.temp_max !== undefined ? data.temp_max : 50;

      if (cpuFanToggle) cpuFanToggle.checked = !!data.ctrl_cpu_fan;
      if (data.curve_points && data.curve_points.length > 0) {
        state.setCurvePoints(data.curve_points);
      } else {
        state.setCurvePoints([[30, 32], [tMin, 32], [tMax, 100], [60, 100]]);
      }
      renderCurveLines();

      const crv = $('fan-curve-range-val');
      if (crv) crv.textContent = `${tMin}°C – ${tMax}°C`;

      updateFanUiState(prof, pct);
    } catch (e) {
      console.warn('Failed to fetch fans', e);
    }
  }

  fetchFanState();

  if (cpuFanToggle) {
    cpuFanToggle.addEventListener('change', (e) => {
      postFanPwm(currentFanProfile, parseInt(fanPwmSlider ? fanPwmSlider.value : 60, 10), e.target.checked);
    });
  }

  fanProfileBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const pr = btn.dataset.fanProfile;
      const map = { auto: 60, quiet: 37, balanced: 66, performance: 85, full: 100 };
      const pct = map[pr] || 60;
      updateFanUiState(pr, pct);
      postFanPwm(pr, pct);
    });
  });

  if (fanPwmSlider) {
    fanPwmSlider.addEventListener('input', (e) => {
      const val = parseInt(e.target.value, 10);
      updateFanUiState('manual', val);
      clearTimeout(fanPwmDebounce);
      fanPwmDebounce = setTimeout(() => postFanPwm('manual', val), 120);
    });
  }

  if (fanCurveSvg) {
    fanCurveSvg.addEventListener('mousedown', (e) => {
      if (e.target.classList.contains('curve-handle')) {
        isDraggingCurve = true;
        dragIndex = parseInt(e.target.id.replace('ch-', ''), 10);
      }
    });

    fanCurveSvg.addEventListener('touchstart', (e) => {
      const touch = e.target;
      if (touch.classList.contains('curve-handle')) {
        isDraggingCurve = true;
        dragIndex = parseInt(touch.id.replace('ch-', ''), 10);
      }
    }, { passive: false });

    let _curveRafPending = false;
    function onCurveMove(e) {
      if (!isDraggingCurve || dragIndex < 0) return;
      e.preventDefault();
      if (_curveRafPending) return;
      _curveRafPending = true;
      requestAnimationFrame(() => {
        _curveRafPending = false;
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        const rect = fanCurveSvg.getBoundingClientRect();
        const svgX = (clientX - rect.left) * (300 / rect.width);
        const svgY = (clientY - rect.top) * (140 / rect.height);

        let t = Math.max(30, Math.min(60, xToTemp(svgX)));
        let p = Math.max(0, Math.min(100, yToPct(svgY)));

        const pts = [...state.curvePoints];
        if (dragIndex > 0) t = Math.max(t, pts[dragIndex - 1][0] + 1);
        if (dragIndex < pts.length - 1) t = Math.min(t, pts[dragIndex + 1][0] - 1);

        pts[dragIndex] = [t, p];
        state.setCurvePoints(pts);
        renderCurveLines();
      });
    }

    window.addEventListener('mousemove', onCurveMove);
    window.addEventListener('touchmove', onCurveMove, { passive: false });

    function onCurveUp() {
      if (!isDraggingCurve) return;
      dragIndex = -1;
      _lastCurveSaveTime = Date.now();
      const savedPoints = state.curvePoints.map((p) => [...p]);
      postFanPwm(currentFanProfile, null, undefined, undefined, undefined, savedPoints)
        .finally(() => {
          state.setCurvePoints(savedPoints);
          isDraggingCurve = false;
        });
    }
    window.addEventListener('mouseup', onCurveUp);
    window.addEventListener('touchend', onCurveUp);
  }

  const presetSelect = $('fan-preset-select');
  const btnSavePreset = $('btn-save-fan-preset');
  const btnApplyPreset = $('btn-apply-fan-preset');
  const btnDeletePreset = $('btn-delete-fan-preset');

  async function loadFanPresets() {
    if (!presetSelect) return;
    try {
      const data = await api.get('/api/fans/presets');
      const presets = data.presets || {};
      const currentVal = presetSelect.value;
      presetSelect.innerHTML = `<option value="">${t('fan.select_preset', '-- Select Preset --')}</option>`;
      Object.keys(presets).sort().forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        presetSelect.appendChild(opt);
      });
      if (presets[currentVal]) {
        presetSelect.value = currentVal;
      }
      updatePresetButtons();
    } catch (e) {
      console.warn('Failed to load fan presets', e);
    }
  }

  const saveModal = document.getElementById('fan-preset-modal-overlay');
  const nameInput = document.getElementById('fan-preset-name-input');
  const btnSubmitSavePreset = document.getElementById('fan-preset-submit-btn');
  const btnCancelSavePreset = document.getElementById('fan-preset-cancel-btn');
  const btnCloseSavePreset = document.getElementById('fan-preset-close-btn');

  const deleteModal = document.getElementById('fan-preset-delete-overlay');
  const deleteTargetText = document.getElementById('fan-delete-preset-target');
  const btnConfirmDeletePreset = document.getElementById('fan-delete-confirm-btn');
  const btnCancelDeletePreset = document.getElementById('fan-delete-cancel-btn');
  const btnCloseDeletePreset = document.getElementById('fan-delete-close-btn');

  function openSavePresetModal() {
    if (!saveModal) return;
    if (nameInput) {
      nameInput.value = '';
      nameInput.style.borderColor = 'rgba(255, 255, 255, 0.15)';
    }
    saveModal.classList.add('open');
    saveModal.style.display = 'flex';
    setTimeout(() => {
      if (nameInput) nameInput.focus();
    }, 60);
  }

  function closeSavePresetModal() {
    if (!saveModal) return;
    saveModal.classList.remove('open');
    saveModal.style.display = 'none';
  }

  async function handleSavePreset() {
    const inputEl = document.getElementById('fan-preset-name-input');
    const cleanName = (inputEl ? inputEl.value : '').trim();
    if (!cleanName) {
      if (inputEl) {
        inputEl.focus();
        inputEl.style.borderColor = 'var(--crit, #ff5c5c)';
      }
      return;
    }
    try {
      const pts = (state.curvePoints && state.curvePoints.length >= 2) ? state.curvePoints : [[30, 32], [37, 32], [50, 100], [60, 100]];
      await api.post('/api/fans/presets', {
        name: cleanName,
        curve_points: pts,
      });
      closeSavePresetModal();
      await loadFanPresets();
      if (presetSelect) presetSelect.value = cleanName;
      updatePresetButtons();
      ZettEventBus.emit('toast', { message: `Preset "${cleanName}" saved`, type: 'success' });
    } catch (e) {
      ZettEventBus.emit('toast', { message: `Failed to save preset: ${e.message || e}`, type: 'error' });
    }
  }

  function openDeletePresetModal(name) {
    if (!deleteModal) return;
    deleteModal._targetPreset = name;
    const targetEl = document.getElementById('fan-delete-preset-target');
    if (targetEl) targetEl.textContent = `"${name}"`;
    deleteModal.classList.add('open');
    deleteModal.style.display = 'flex';
  }

  function closeDeletePresetModal() {
    if (!deleteModal) return;
    deleteModal.classList.remove('open');
    deleteModal.style.display = 'none';
    deleteModal._targetPreset = null;
  }

  async function handleDeletePreset() {
    const name = deleteModal ? deleteModal._targetPreset : null;
    if (!name) return;
    try {
      await api.delete(`/api/fans/presets/${encodeURIComponent(name)}`);
      closeDeletePresetModal();
      await loadFanPresets();
      updatePresetButtons();
      ZettEventBus.emit('toast', { message: `Preset "${name}" deleted`, type: 'info' });
    } catch (e) {
      ZettEventBus.emit('toast', { message: `Failed to delete preset: ${e.message || e}`, type: 'error' });
    }
  }

  function updatePresetButtons() {
    const hasVal = !!(presetSelect && presetSelect.value);
    if (btnApplyPreset) btnApplyPreset.disabled = !hasVal;
    if (btnDeletePreset) btnDeletePreset.style.display = hasVal ? 'inline-flex' : 'none';
  }

  if (presetSelect) {
    presetSelect.addEventListener('change', updatePresetButtons);
  }

  if (btnSavePreset) {
    btnSavePreset.addEventListener('click', openSavePresetModal);
  }

  if (saveModal) {
    saveModal.addEventListener('click', (e) => {
      if (e.target.closest('#fan-preset-submit-btn')) {
        handleSavePreset();
      } else if (e.target.closest('#fan-preset-cancel-btn') || e.target.closest('#fan-preset-close-btn') || e.target === saveModal) {
        closeSavePresetModal();
      }
    });
  }

  if (nameInput) {
    nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleSavePreset();
      } else if (e.key === 'Escape') {
        closeSavePresetModal();
      }
    });
    nameInput.addEventListener('input', () => {
      nameInput.style.borderColor = 'rgba(255, 255, 255, 0.15)';
    });
  }

  if (btnApplyPreset) {
    btnApplyPreset.addEventListener('click', async () => {
      const name = presetSelect ? presetSelect.value : '';
      if (!name) return;
      try {
        const res = await api.post(`/api/fans/presets/${encodeURIComponent(name)}/apply`);
        if (res && res.fan_config) {
          if (res.fan_config.curve_points) {
            state.setCurvePoints(res.fan_config.curve_points);
            renderCurveLines();
          }
          updateFanUiState(res.fan_config.profile || 'auto', res.fan_config.manual_pct);
        }
        ZettEventBus.emit('toast', { message: `Preset "${name}" applied`, type: 'success' });
      } catch (e) {
        ZettEventBus.emit('toast', { message: `Failed to apply preset: ${e.message || e}`, type: 'error' });
      }
    });
  }

  if (btnDeletePreset) {
    btnDeletePreset.addEventListener('click', () => {
      const name = presetSelect ? presetSelect.value : '';
      if (!name) return;
      openDeletePresetModal(name);
    });
  }

  if (deleteModal) {
    deleteModal.addEventListener('click', (e) => {
      if (e.target.closest('#fan-delete-confirm-btn')) {
        handleDeletePreset();
      } else if (e.target.closest('#fan-delete-cancel-btn') || e.target.closest('#fan-delete-close-btn') || e.target === deleteModal) {
        closeDeletePresetModal();
      }
    });
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (saveModal && saveModal.classList.contains('open')) {
        closeSavePresetModal();
      }
      if (deleteModal && deleteModal.classList.contains('open')) {
        closeDeletePresetModal();
      }
    }
  });

  window.openSavePresetModal = openSavePresetModal;
  window.closeSavePresetModal = closeSavePresetModal;
  window.openDeletePresetModal = openDeletePresetModal;
  window.closeDeletePresetModal = closeDeletePresetModal;

  loadFanPresets();
  window.addEventListener('zettnas:lang-changed', () => {
    loadFanPresets();
  });
  setTimeout(renderCurveLines, 400);
}
