/**
 * Mission Control: UPS telemetry, events and the UPS settings drawer.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { api } from '../../api.js';
import { showToast, showConfirmToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { formatDateTime } from '../../format.js';

export function renderUpsTelemetry(ups) {
  if (!ups) return;
  const isPermErr = Boolean(ups.permission_error);
  const upsVal = isPermErr
    ? 'Perm Req'
    : (ups.battery_charge_pct != null ? `${ups.battery_charge_pct}%` : (ups.available ? 'Active' : 'Offline'));
  const upsPill = document.getElementById('mgmt-hub-ups-pill');
  if (upsPill) {
    upsPill.textContent = upsVal;
    if (isPermErr) {
      upsPill.style.background = 'rgba(235,87,87,0.15)';
      upsPill.style.color = 'var(--err, #eb5757)';
    } else if (ups.available && ups.battery_charge_pct != null) {
      upsPill.style.background = ups.battery_charge_pct <= 20 ? 'rgba(235,87,87,0.15)' : 'rgba(37,194,160,0.15)';
      upsPill.style.color = ups.battery_charge_pct <= 20 ? 'var(--err, #eb5757)' : 'var(--ok2, #25c2a0)';
    }
  }
  const sideUpsBadge = document.getElementById('mgmt-sidebar-ups-badge');
  if (sideUpsBadge) {
    sideUpsBadge.textContent = upsVal;
    sideUpsBadge.style.display = (ups.available || isPermErr) ? 'inline-block' : 'none';
    if (isPermErr) {
      sideUpsBadge.style.background = 'rgba(235,87,87,0.2)';
      sideUpsBadge.style.color = 'var(--err, #eb5757)';
    }
  }

  const statusEl = document.getElementById('mgmt-ups-status');
  const modelEl = document.getElementById('mgmt-ups-model');
  const chargeEl = document.getElementById('mgmt-ups-charge');
  const runtimeEl = document.getElementById('mgmt-ups-runtime');
  const loadEl = document.getElementById('mgmt-ups-load');
  const linevEl = document.getElementById('mgmt-ups-linev');
  const protocolEl = document.getElementById('mgmt-ups-protocol');
  const battvEl = document.getElementById('mgmt-ups-battv');
  const policyEl = document.getElementById('mgmt-ups-policy');

  if (statusEl) {
    statusEl.textContent = isPermErr ? 'Permission Required' : (ups.status || (ups.available ? 'ONLINE' : 'Offline'));
    statusEl.style.color = isPermErr
      ? 'var(--err, #eb5757)'
      : (ups.available ? (ups.on_battery ? 'var(--warn)' : 'var(--ok2)') : 'var(--muted)');
  }
  if (modelEl) modelEl.textContent = ups.model || 'Generic UPS';
  if (chargeEl) {
    chargeEl.textContent = ups.battery_charge_pct != null ? `${ups.battery_charge_pct}%` : 'N/A';
    chargeEl.style.color = (ups.battery_charge_pct == null || ups.battery_charge_pct > 30) ? 'var(--ok2)' : 'var(--crit)';
  }
  if (runtimeEl) runtimeEl.textContent = ups.time_left_min != null ? `${ups.time_left_min} min` : 'N/A';
  if (loadEl) loadEl.textContent = ups.load_pct != null ? `${ups.load_pct}%` : 'N/A';
  if (linevEl) linevEl.textContent = ups.line_volts != null ? `${ups.line_volts} V` : (ups.output_volts != null ? `${ups.output_volts} V` : 'N/A');
  if (protocolEl) {
    let protoLabel = ups.protocol || 'Auto / NIS';
    if (ups.is_usb && !protoLabel.toLowerCase().includes('usb')) {
      protoLabel = `${protoLabel} (USB)`;
    }
    protocolEl.textContent = protoLabel;
    const currentUpsMode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
    updateUpsConnCardState(currentUpsMode, ups);
  }
  if (battvEl) battvEl.textContent = ups.battery_volts != null ? `${ups.battery_volts} V` : 'N/A';
  if (policyEl) policyEl.textContent = ups.active_policy ? `Policy: ${ups.active_policy}` : 'Runtime < 5m';

  // Digital Twin Nodes
  const flowContainer = document.getElementById('ups-power-flow-container');
  const twinLinev = document.getElementById('ups-twin-linev');
  const twinGridStatus = document.getElementById('ups-twin-grid-status');
  const twinWatts = document.getElementById('ups-twin-watts');
  const twinBattVolts = document.getElementById('ups-twin-batt-volts');
  const radialFill = document.getElementById('ups-radial-fill');
  const gridDot = document.getElementById('ups-grid-dot');
  const emergencyBanner = document.getElementById('ups-emergency-banner');
  const emergencyCountdown = document.getElementById('ups-emergency-countdown');
  const permBanner = document.getElementById('ups-permission-banner');
  const permMsg = document.getElementById('ups-permission-msg');

  if (permBanner) {
    if (isPermErr) {
      permBanner.style.display = 'flex';
      if (permMsg && ups.permission_detail) {
        permMsg.textContent = ups.permission_detail;
      }
    } else {
      permBanner.style.display = 'none';
    }
  }

  if (twinLinev) twinLinev.textContent = ups.line_volts != null ? `${ups.line_volts} V` : (ups.output_volts != null ? `${ups.output_volts} V` : (ups.available ? '120.0 V' : '-- V'));
  if (twinGridStatus) {
    twinGridStatus.textContent = ups.on_battery ? 'AC Mains Disconnected' : (ups.line_freq_hz ? `${ups.line_freq_hz} Hz Nominal` : '120V / 60Hz Nominal');
  }
  if (twinWatts) twinWatts.textContent = ups.power_watts != null ? `${ups.power_watts} W` : (ups.load_pct != null ? `${Math.round(ups.load_pct * ((ups.nominal_power_watts || 900) / 100))} W` : '-- W');
  if (twinBattVolts) {
    const vStr = ups.battery_volts != null ? `${ups.battery_volts} V` : '-- V';
    const tStr = ups.battery_temp_c != null ? `${ups.battery_temp_c}°C` : '--°C';
    twinBattVolts.textContent = `${vStr} • ${tStr}`;
  }

  // Radial progress ring (circumference for r=28 is 175.93)
  if (radialFill) {
    const pct = Math.max(0, Math.min(100, ups.battery_charge_pct != null ? ups.battery_charge_pct : 100));
    const offset = 175.93 * (1 - pct / 100);
    radialFill.style.strokeDashoffset = offset;
    radialFill.style.stroke = pct <= 20 ? 'var(--err, #eb5757)' : (pct <= 40 ? 'var(--warn, #f5a623)' : 'var(--ok2, #25c2a0)');
  }

  if (flowContainer) {
    flowContainer.classList.toggle('on-battery', Boolean(ups.on_battery));
    flowContainer.classList.toggle('critical-battery', Boolean(ups.battery_charge_pct != null && ups.battery_charge_pct <= 20));
  }

  if (gridDot) {
    gridDot.className = 'ups-card-status-dot ' + (isPermErr ? 'danger' : (ups.on_battery ? 'danger' : (ups.available ? 'active' : '')));
  }

  if (emergencyBanner) {
    if (ups.on_battery) {
      emergencyBanner.style.display = 'flex';
      if (emergencyCountdown) {
        emergencyCountdown.textContent = ups.time_left_min != null ? `~${ups.time_left_min}m remaining` : 'ON BATTERY';
      }
    } else {
      emergencyBanner.style.display = 'none';
    }
  }
}

export async function fetchAndRenderUpsEvents() {
  const tbody = document.getElementById('ups-events-tbody');
  if (!tbody) return;
  try {
    const res = await api.get('/api/ups/events');
    const events = res && Array.isArray(res.events) ? res.events : [];
    if (!events.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--muted); padding:16px;">No power events or brownouts recorded. All power lines normal.</td></tr>';
      return;
    }
    tbody.innerHTML = events.map(ev => {
      const dateStr = formatDateTime(ev.ts);
      let typeBadge = `<span class="badge" style="background:var(--lt-b-00f0ff26, rgba(0,240,255,0.15)); border:1px solid #00f0ff; color:var(--lt-t-00f0ffff, #00f0ff); padding:2px 8px; border-radius:4px; font-size:var(--zn-fs-xs);">${escapeHtml(ev.event_type)}</span>`;
      if (ev.event_type.includes('OUTAGE') || ev.event_type.includes('FAILSAFE')) {
        typeBadge = `<span class="badge" style="background:rgba(245,166,35,0.15); border:1px solid #f5a623; color:var(--lt-t-f5a623ff, #f5a623); padding:2px 8px; border-radius:4px; font-size:var(--zn-fs-xs);">${escapeHtml(ev.event_type)}</span>`;
      } else if (ev.event_type.includes('SELF_TEST')) {
        typeBadge = `<span class="badge" style="background:rgba(37,194,160,0.15); border:1px solid #25c2a0; color:var(--lt-t-25c2a0ff, #25c2a0); padding:2px 8px; border-radius:4px; font-size:var(--zn-fs-xs);">${escapeHtml(ev.event_type)}</span>`;
      }
      const durStr = ev.duration_sec ? `${ev.duration_sec}s` : '--';
      const battDelta = ev.start_battery_pct != null && ev.end_battery_pct != null
        ? `${ev.start_battery_pct}% ➔ ${ev.end_battery_pct}%`
        : (ev.start_battery_pct != null ? `${ev.start_battery_pct}%` : '--');
      const action = ev.action_taken || ev.status || '--';

      return `<tr>
        <td style="font-size:var(--zn-fs-xs); font-variant-numeric:tabular-nums;">${escapeHtml(dateStr)}</td>
        <td>${typeBadge}</td>
        <td style="font-size:var(--zn-fs-xs);">${escapeHtml(durStr)}</td>
        <td style="font-size:var(--zn-fs-xs);">${escapeHtml(battDelta)}</td>
        <td style="font-size:var(--zn-fs-xs); color:var(--text);">${escapeHtml(action)}</td>
      </tr>`;
    }).join('');
  } catch (err) {
    console.debug('Failed to fetch UPS events:', err);
  }
}

export async function fetchAndRenderUpsTelemetry() {
  try {
    const ups = await api.get('/api/ups');
    if (!ups) return;
    renderUpsTelemetry(ups);
    fetchAndRenderUpsEvents();
  } catch (err) {
    console.debug('Failed to fetch UPS telemetry:', err);
  }
}

export function openUpsDrawer() {
  const drawer = document.getElementById('ups-config-drawer');
  const overlay = document.getElementById('ups-drawer-overlay');
  if (!drawer || !overlay) return;
  drawer.style.display = 'flex';
  overlay.style.display = 'block';
  void drawer.offsetWidth;
  drawer.classList.add('open');
  overlay.classList.add('open');
  loadUpsConfigToDrawer();
}
if (typeof window !== 'undefined') window.openUpsDrawer = openUpsDrawer;

export function closeUpsDrawer() {
  const drawer = document.getElementById('ups-config-drawer');
  const overlay = document.getElementById('ups-drawer-overlay');
  if (!drawer || !overlay) return;
  drawer.classList.remove('open');
  overlay.classList.remove('open');
  setTimeout(() => {
    drawer.style.display = 'none';
    overlay.style.display = 'none';
  }, 250);
}
if (typeof window !== 'undefined') window.closeUpsDrawer = closeUpsDrawer;

let upsSaveDebounceTimer = null;
let isUpsLoadingConfig = false;
let isUpsConfigLoaded = false;

export function setUpsConfigLoaded(val = true) {
  isUpsConfigLoaded = Boolean(val);
}
if (typeof window !== 'undefined') window.setUpsConfigLoaded = setUpsConfigLoaded;

export function updateUpsConnCardState(mode, upsData) {
  const connCard = document.getElementById('ups-drawer-conn-card');
  const badge = document.getElementById('ups-conn-disabled-badge');
  const toggleContainer = document.getElementById('ups-toggle-params-container');
  const toggleBtn = document.getElementById('btn-toggle-ups-conn-params');
  if (!connCard) return;

  const currentMode = mode || document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
  const protocolText = (document.getElementById('mgmt-ups-protocol')?.textContent || '').toLowerCase().trim();
  const isUsbProtocol = protocolText.includes('usb') || protocolText.includes('hid');
  const isDirectUsb = (currentMode === 'usb_hid') ||
                      Boolean(upsData?.is_usb) ||
                      (upsData?.cable && String(upsData.cable).toLowerCase().includes('usb')) ||
                      (upsData?.driver && String(upsData.driver).toLowerCase().includes('usb')) ||
                      (currentMode === 'auto' && isUsbProtocol);

  if (isDirectUsb) {
    connCard.classList.add('disabled');
    connCard.setAttribute('aria-disabled', 'true');
    // Hide the connection parameters card when connected via USB or in Direct USB mode
    if (!connCard.dataset.manuallyExpanded) {
      connCard.style.display = 'none';
    } else {
      connCard.style.removeProperty('display');
    }
    if (badge) badge.style.display = 'inline-flex';
    if (toggleContainer) toggleContainer.style.display = 'flex';
    if (toggleBtn) {
      const toggleText = toggleBtn.querySelector('#ups-toggle-params-text');
      if (toggleText) {
        toggleText.textContent = connCard.dataset.manuallyExpanded
          ? t('mgmt.ups_hide_params', 'Hide Connection Parameters')
          : t('mgmt.ups_show_params', 'Show Connection Parameters');
      }
    }
  } else {
    delete connCard.dataset.manuallyExpanded;
    connCard.classList.remove('disabled');
    connCard.removeAttribute('aria-disabled');
    connCard.style.removeProperty('display');
    if (badge) badge.style.display = 'none';
    if (toggleContainer) toggleContainer.style.display = 'none';
  }
  const inputs = connCard.querySelectorAll('input, button');
  inputs.forEach(el => {
    el.disabled = isDirectUsb;
  });
}
if (typeof window !== 'undefined') window.updateUpsConnCardState = updateUpsConnCardState;

export function updateUpsPolicySliders(selectedPolicy) {
  const policy = selectedPolicy || document.querySelector('input[name="ups-policy"]:checked')?.value || 'runtime_left';
  const rtContainer = document.getElementById('ups-slider-runtime-container');
  const battContainer = document.getElementById('ups-slider-battery-container');
  const timerContainer = document.getElementById('ups-slider-timer-container');

  if (rtContainer) rtContainer.style.display = (policy === 'runtime_left') ? 'flex' : 'none';
  if (battContainer) battContainer.style.display = (policy === 'battery_pct') ? 'flex' : 'none';
  if (timerContainer) timerContainer.style.display = (policy === 'timer') ? 'flex' : 'none';

  updateUpsPolicySummary();
}
if (typeof window !== 'undefined') window.updateUpsPolicySliders = updateUpsPolicySliders;

export function updateUpsPolicySummary() {
  const summaryText = document.getElementById('ups-policy-summary-text');
  if (!summaryText) return;

  const policy = document.querySelector('input[name="ups-policy"]:checked')?.value || 'runtime_left';
  const rtVal = document.getElementById('ups-slider-runtime')?.value || 5;
  const battVal = document.getElementById('ups-slider-battery')?.value || 20;
  const timerVal = document.getElementById('ups-slider-timer')?.value || 300;
  const dockerChecked = document.getElementById('ups-chk-docker')?.checked;

  let policyDesc;
  if (policy === 'runtime_left') {
    policyDesc = `Estimated Runtime < ${rtVal} min`;
  } else if (policy === 'battery_pct') {
    policyDesc = `Battery Charge < ${battVal}%`;
  } else {
    policyDesc = `Time on Battery > ${timerVal}s`;
  }

  if (dockerChecked) {
    policyDesc += ' · Docker WAL flush';
  }
  summaryText.textContent = `Active: ${policyDesc}`;
}
if (typeof window !== 'undefined') window.updateUpsPolicySummary = updateUpsPolicySummary;

export async function saveUpsConfigFromDrawer() {
  if (isUpsLoadingConfig || !isUpsConfigLoaded) {
    console.debug('[UPS] Skipping auto-save: config loading or not yet loaded.');
    return;
  }
  try {
    const mode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
    const host = document.getElementById('ups-cfg-host')?.value.trim() || '127.0.0.1';
    let defaultPort = 3551;
    if (mode === 'nut_client') defaultPort = 3493;
    const port = parseInt(document.getElementById('ups-cfg-port')?.value, 10) || defaultPort;
    const ups_name = document.getElementById('ups-cfg-name')?.value.trim() || 'ups';
    const username = document.getElementById('ups-cfg-user')?.value.trim() || '';
    const passwordRaw = document.getElementById('ups-cfg-pass')?.value || '';
    const password = passwordRaw.startsWith('••') ? undefined : passwordRaw;

    const policy = document.querySelector('input[name="ups-policy"]:checked')?.value || 'runtime_left';
    const runtime_threshold_min = parseInt(document.getElementById('ups-slider-runtime')?.value, 10) || 5;
    const battery_threshold_pct = parseInt(document.getElementById('ups-slider-battery')?.value, 10) || 20;
    const shutdown_timer_sec = parseInt(document.getElementById('ups-slider-timer')?.value, 10) || 300;

    const container_shutdown_timeout_sec = document.getElementById('ups-chk-docker')?.checked ? 45 : 0;
    const poweroff_ups = Boolean(document.getElementById('ups-chk-cutpower')?.checked);

    const payload = {
      enabled: true,
      mode,
      host,
      port,
      ups_name,
      username,
      shutdown_policy: policy,
      runtime_threshold_min,
      battery_threshold_pct,
      shutdown_timer_sec,
      container_shutdown_timeout_sec,
      poweroff_ups
    };
    if (password !== undefined) {
      payload.password = password;
    }

    const statusEl = document.getElementById('ups-save-status');
    if (statusEl) {
      statusEl.textContent = t('ui.saving_2', 'Saving…');
      statusEl.style.display = 'inline-flex';
    }

    await api.post('/api/ups/config', payload);

    if (statusEl) {
      statusEl.textContent = t('mgmt.ups_auto_saved', '✓ Saved');
      statusEl.style.display = 'inline-flex';
      const savedAt = String(Date.now());
      statusEl.dataset.savedAt = savedAt;
      setTimeout(() => {
        if (statusEl && statusEl.dataset.savedAt === savedAt) {
          statusEl.style.display = 'none';
        }
      }, 1500);
    }
    fetchAndRenderUpsTelemetry();
  } catch (err) {
    console.warn('Failed to auto-save UPS configuration:', err);
    const statusEl = document.getElementById('ups-save-status');
    if (statusEl) {
      statusEl.textContent = t('ui.error_2', '✗ Error');
      setTimeout(() => {
        if (statusEl) statusEl.style.display = 'none';
      }, 3000);
    }
  }
}
if (typeof window !== 'undefined') window.saveUpsConfigFromDrawer = saveUpsConfigFromDrawer;

export async function loadUpsConfigToDrawer() {
  try {
    isUpsLoadingConfig = true;
    const cfg = await api.get('/api/ups/config');
    if (!cfg) return;

    // Mode selection
    const mode = cfg.mode || 'auto';
    const modeRadios = document.querySelectorAll('input[name="ups-mode"]');
    modeRadios.forEach(r => {
      r.checked = (r.value === mode);
    });

    // Update connection parameters card state (gray out if Direct USB)
    updateUpsConnCardState(mode);

    // Inputs
    const hostEl = document.getElementById('ups-cfg-host');
    const portEl = document.getElementById('ups-cfg-port');
    const nameEl = document.getElementById('ups-cfg-name');
    const userEl = document.getElementById('ups-cfg-user');
    const passEl = document.getElementById('ups-cfg-pass');

    if (hostEl) hostEl.value = cfg.host || '127.0.0.1';
    if (portEl) portEl.value = cfg.port || (mode === 'nut_client' ? 3493 : 3551);
    if (nameEl) nameEl.value = cfg.ups_name || 'ups';
    if (userEl) userEl.value = cfg.username || '';
    if (passEl) passEl.value = cfg.password || '';

    // Shutdown Policy
    const policy = cfg.shutdown_policy || 'runtime_left';
    const policyRadios = document.querySelectorAll('input[name="ups-policy"]');
    policyRadios.forEach(r => {
      r.checked = (r.value === policy);
    });

    // Sliders
    const runtimeSlider = document.getElementById('ups-slider-runtime');
    const runtimeVal = document.getElementById('ups-val-runtime');
    if (runtimeSlider) {
      runtimeSlider.value = cfg.runtime_threshold_min != null ? cfg.runtime_threshold_min : 5;
      if (runtimeVal) runtimeVal.textContent = `${runtimeSlider.value} min`;
    }

    const batterySlider = document.getElementById('ups-slider-battery');
    const batteryVal = document.getElementById('ups-val-battery');
    if (batterySlider) {
      batterySlider.value = cfg.battery_threshold_pct != null ? cfg.battery_threshold_pct : 20;
      if (batteryVal) batteryVal.textContent = `${batterySlider.value} %`;
    }

    const timerSlider = document.getElementById('ups-slider-timer');
    const timerVal = document.getElementById('ups-val-timer');
    if (timerSlider) {
      timerSlider.value = cfg.shutdown_timer_sec != null ? cfg.shutdown_timer_sec : 300;
      if (timerVal) timerVal.textContent = `${timerSlider.value} sec`;
    }

    // Checkboxes
    const chkDocker = document.getElementById('ups-chk-docker');
    if (chkDocker) {
      chkDocker.checked = (cfg.container_shutdown_timeout_sec ?? 45) > 0;
    }

    const chkCutpower = document.getElementById('ups-chk-cutpower');
    if (chkCutpower) {
      chkCutpower.checked = Boolean(cfg.poweroff_ups);
    }

    // Restore policy collapse state
    try {
      const isPolicyCollapsed = localStorage.getItem('zettnas_ups_policy_collapsed') === '1';
      const policyBody = document.getElementById('ups-policy-body');
      const policySummary = document.getElementById('ups-policy-summary');
      const toggleText = document.getElementById('ups-toggle-policy-text');
      if (policyBody && isPolicyCollapsed) {
        policyBody.style.display = 'none';
        if (policySummary) policySummary.style.display = 'flex';
        if (toggleText) toggleText.textContent = t('mgmt.ups_expand_policy', 'Configure Policy');
      }
    } catch (_) {}
    updateUpsPolicySliders(policy);

    isUpsConfigLoaded = true;
  } catch (err) {
    console.debug('Failed to load UPS config:', err);
  } finally {
    isUpsLoadingConfig = false;
  }
}

export function initUpsDrawerControls() {
  const loadPromise = loadUpsConfigToDrawer();
  const btnOpen = document.getElementById('btn-open-ups-config');
  btnOpen?.addEventListener('click', (e) => {
    e.preventDefault();
    const cfgSec = document.getElementById('ups-cockpit-config-section');
    if (cfgSec) {
      cfgSec.scrollIntoView({ behavior: 'smooth' });
    } else {
      openUpsDrawer();
    }
  });

  const btnRefresh = document.getElementById('btn-refresh-ups');
  btnRefresh?.addEventListener('click', async () => {
    try {
      btnRefresh.disabled = true;
      btnRefresh.textContent = t('ui.refreshing', 'Refreshing...');
      await fetchAndRenderUpsTelemetry();
      await loadUpsConfigToDrawer();
      showToast(t('toast.ups_telemetry_parameters_updated', 'UPS telemetry & parameters updated'), 'info');
    } catch (err) {
      console.debug('Failed to refresh UPS telemetry:', err);
    } finally {
      btnRefresh.disabled = false;
      btnRefresh.textContent = t('mgmt.refresh', '🔄 Refresh');
    }
  });

  const btnClose = document.getElementById('btn-close-ups-drawer');
  btnClose?.addEventListener('click', (e) => {
    e.preventDefault();
    closeUpsDrawer();
  });

  const overlay = document.getElementById('ups-drawer-overlay');
  overlay?.addEventListener('click', () => {
    closeUpsDrawer();
  });

  const triggerDebouncedSave = (delay = 200) => {
    clearTimeout(upsSaveDebounceTimer);
    upsSaveDebounceTimer = setTimeout(() => {
      saveUpsConfigFromDrawer();
    }, delay);
  };

  const triggerImmediateSave = () => {
    clearTimeout(upsSaveDebounceTimer);
    saveUpsConfigFromDrawer();
  };

  // Slider value listeners + auto-save
  const runtimeSlider = document.getElementById('ups-slider-runtime');
  const runtimeVal = document.getElementById('ups-val-runtime');
  runtimeSlider?.addEventListener('input', () => {
    if (runtimeVal) runtimeVal.textContent = `${runtimeSlider.value} min`;
    updateUpsPolicySummary();
    triggerDebouncedSave(200);
  });
  runtimeSlider?.addEventListener('change', () => {
    updateUpsPolicySummary();
    triggerImmediateSave();
  });

  const batterySlider = document.getElementById('ups-slider-battery');
  const batteryVal = document.getElementById('ups-val-battery');
  batterySlider?.addEventListener('input', () => {
    if (batteryVal) batteryVal.textContent = `${batterySlider.value} %`;
    updateUpsPolicySummary();
    triggerDebouncedSave(200);
  });
  batterySlider?.addEventListener('change', () => {
    updateUpsPolicySummary();
    triggerImmediateSave();
  });

  const timerSlider = document.getElementById('ups-slider-timer');
  const timerVal = document.getElementById('ups-val-timer');
  timerSlider?.addEventListener('input', () => {
    if (timerVal) timerVal.textContent = `${timerSlider.value} sec`;
    updateUpsPolicySummary();
    triggerDebouncedSave(200);
  });
  timerSlider?.addEventListener('change', () => {
    updateUpsPolicySummary();
    triggerImmediateSave();
  });

  // Policy radio auto-save + accordion slider collapse
  const policyRadios = document.querySelectorAll('input[name="ups-policy"]');
  policyRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      updateUpsPolicySliders(radio.value);
      triggerImmediateSave();
    });
  });

  // Toggle Safe Shutdown Policy Collapse/Expand
  const btnTogglePolicy = document.getElementById('btn-toggle-ups-policy');
  btnTogglePolicy?.addEventListener('click', () => {
    const policyBody = document.getElementById('ups-policy-body');
    const policySummary = document.getElementById('ups-policy-summary');
    const toggleText = document.getElementById('ups-toggle-policy-text');
    if (!policyBody) return;

    const isCollapsed = policyBody.style.display === 'none';
    if (isCollapsed) {
      policyBody.style.display = 'flex';
      if (policySummary) policySummary.style.display = 'none';
      if (toggleText) toggleText.textContent = t('mgmt.ups_collapse_policy', 'Collapse Policy');
      try { localStorage.setItem('zettnas_ups_policy_collapsed', '0'); } catch (_) {}
    } else {
      policyBody.style.display = 'none';
      if (policySummary) policySummary.style.display = 'flex';
      updateUpsPolicySummary();
      if (toggleText) toggleText.textContent = t('mgmt.ups_expand_policy', 'Configure Policy');
      try { localStorage.setItem('zettnas_ups_policy_collapsed', '1'); } catch (_) {}
    }
  });

  // Checkbox toggles auto-save
  const chkDocker = document.getElementById('ups-chk-docker');
  chkDocker?.addEventListener('change', () => {
    updateUpsPolicySummary();
    triggerImmediateSave();
  });

  const chkCutpower = document.getElementById('ups-chk-cutpower');
  chkCutpower?.addEventListener('change', () => {
    triggerImmediateSave();
  });

  // Mode radio ports auto-fill, gray-out state, and auto-save
  const modeRadios = document.querySelectorAll('input[name="ups-mode"]');
  modeRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      const portEl = document.getElementById('ups-cfg-port');
      if (radio.value === 'apcupsd_client' && portEl && (portEl.value === '3493' || !portEl.value)) {
        portEl.value = '3551';
      } else if (radio.value === 'nut_client' && portEl && (portEl.value === '3551' || !portEl.value)) {
        portEl.value = '3493';
      }
      updateUpsConnCardState(radio.value);
      triggerImmediateSave();
    });
  });

  // Toggle Manual Parameters in Direct USB mode
  const btnToggleParams = document.getElementById('btn-toggle-ups-conn-params');
  btnToggleParams?.addEventListener('click', () => {
    const connCard = document.getElementById('ups-drawer-conn-card');
    if (!connCard) return;
    if (connCard.dataset.manuallyExpanded) {
      delete connCard.dataset.manuallyExpanded;
    } else {
      connCard.dataset.manuallyExpanded = '1';
    }
    const activeMode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
    updateUpsConnCardState(activeMode);
  });

  // Connection text inputs auto-save
  const connInputs = [
    document.getElementById('ups-cfg-host'),
    document.getElementById('ups-cfg-port'),
    document.getElementById('ups-cfg-name'),
    document.getElementById('ups-cfg-user'),
    document.getElementById('ups-cfg-pass')
  ];
  connInputs.forEach(input => {
    if (!input) return;
    input.addEventListener('change', () => {
      triggerImmediateSave();
    });
    input.addEventListener('input', () => {
      triggerDebouncedSave(600);
    });
  });

  // Auto-Discovery
  const btnDiscover = document.getElementById('btn-ups-discover');
  const discoverContainer = document.getElementById('ups-discover-candidates');
  btnDiscover?.addEventListener('click', async () => {
    try {
      btnDiscover.disabled = true;
      btnDiscover.textContent = t('ui.scanning', 'Scanning...');
      const res = await api.post('/api/ups/discover');
      const candidates = res && Array.isArray(res.candidates) ? res.candidates : [];
      if (!discoverContainer) return;
      if (candidates.length === 0) {
        discoverContainer.innerHTML = `<div style="font-size:var(--zn-fs-xs); color:var(--muted); padding:6px 0;">No active UPS daemons or USB devices detected on local ports.</div>`;
        return;
      }
      discoverContainer.innerHTML = candidates.map((cand, idx) => {
        const isUsb = Boolean(cand.is_usb || cand.type === 'usb_hid' || cand.mode === 'usb_hid');
        const isApc = !isUsb && (cand.type === 'apcupsd' || cand.type === 'apcupsd_client' || cand.port === 3551);
        const isNut = !isUsb && (cand.type === 'nut' || cand.type === 'nut_client' || cand.port === 3493);
        const typeLabel = isUsb ? 'Direct USB HID' : (isApc ? 'APCUPSD NIS' : (isNut ? 'NUT Server' : 'USB HID Device'));
        const hostPort = isUsb
          ? (cand.description || `USB ${cand.vendor_id || ''}:${cand.product_id || ''}`)
          : (cand.port ? `${cand.host}:${cand.port}` : (cand.path || cand.host || 'local'));
        const displayTitle = cand.title || cand.label || typeLabel;
        return `<div class="ups-discover-item" data-idx="${idx}" style="display:flex; justify-content:space-between; align-items:center; background:var(--zn-shade-30); border:1px solid var(--zn-line-8); padding:8px 12px; border-radius:6px; cursor:pointer;">
          <div>
            <div style="font-size:var(--zn-fs-xs); font-weight:600; color:var(--zn-text-strong);">${escapeHtml(displayTitle)}</div>
            <div style="font-size:var(--zn-fs-xs); color:var(--muted);">${escapeHtml(typeLabel)} • <code>${escapeHtml(hostPort)}</code></div>
          </div>
          <button type="button" class="btn-rect is-small">Apply</button>
        </div>`;
      }).join('');

      discoverContainer.querySelectorAll('.ups-discover-item').forEach(item => {
        item.addEventListener('click', () => {
          const idx = parseInt(item.dataset.idx, 10);
          const cand = candidates[idx];
          if (!cand) return;
          const isUsb = Boolean(cand.is_usb || cand.type === 'usb_hid' || cand.mode === 'usb_hid');
          const isApc = !isUsb && (cand.type === 'apcupsd' || cand.type === 'apcupsd_client' || cand.port === 3551);
          const isNut = !isUsb && (cand.type === 'nut' || cand.type === 'nut_client' || cand.port === 3493);
          const targetMode = isUsb ? 'usb_hid' : (cand.mode || (isApc ? 'apcupsd_client' : (isNut ? 'nut_client' : 'auto')));
          const radio = document.querySelector(`input[name="ups-mode"][value="${targetMode}"]`);
          if (radio) radio.checked = true;
          const hostEl = document.getElementById('ups-cfg-host');
          const portEl = document.getElementById('ups-cfg-port');
          const nameEl = document.getElementById('ups-cfg-name');
          if (isUsb) {
            if (hostEl) hostEl.value = '';
            if (portEl) portEl.value = '';
          } else {
            if (hostEl && cand.host) hostEl.value = cand.host;
            if (portEl) {
              if (cand.port && cand.port > 0) {
                portEl.value = cand.port;
              } else if (targetMode === 'apcupsd_client') {
                portEl.value = 3551;
              } else if (targetMode === 'nut_client') {
                portEl.value = 3493;
              }
            }
            if (nameEl && cand.ups_name) nameEl.value = cand.ups_name;
          }
          updateUpsConnCardState(targetMode);
          triggerImmediateSave();
          const displayTitle = cand.title || cand.label || (isUsb ? 'Direct USB HID' : (isApc ? 'APCUPSD' : (isNut ? 'NUT' : 'USB HID')));
          showToast(t('toast.applied_parameters', 'Applied {displayTitle} parameters!', { displayTitle: displayTitle }), 'info');
        });
      });
    } catch (err) {
      showToast(t('toast.auto_discovery_failed', 'Auto-discovery failed: {error}', { error: err.message }), 'error');
    } finally {
      btnDiscover.disabled = false;
      btnDiscover.textContent = t('mgmt.ups_btn_scan', 'Scan Hardware');
    }
  });

  // Test Connection
  const btnTest = document.getElementById('btn-ups-test-conn');
  btnTest?.addEventListener('click', async () => {
    try {
      btnTest.disabled = true;
      btnTest.textContent = t('ui.testing', 'Testing...');
      const mode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
      const host = document.getElementById('ups-cfg-host')?.value.trim() || '127.0.0.1';
      const port = parseInt(document.getElementById('ups-cfg-port')?.value, 10) || 3551;
      const ups_name = document.getElementById('ups-cfg-name')?.value.trim() || 'ups';
      const username = document.getElementById('ups-cfg-user')?.value.trim() || '';
      const passwordRaw = document.getElementById('ups-cfg-pass')?.value || '';
      const password = passwordRaw.startsWith('••') ? '' : passwordRaw;
      const isUsbMode = (mode === 'usb_hid');

      const res = await api.post('/api/ups/test-connection', {
        mode,
        host: isUsbMode ? '' : host,
        port: isUsbMode ? 0 : port,
        ups_name: isUsbMode ? '' : ups_name,
        username: isUsbMode ? '' : username,
        password: isUsbMode ? '' : password
      });

      if (res && (res.connected || res.success)) {
        showToast(t('toast.connection_successful', 'Connection successful! ({model})', { model: res.model || res.status || 'ONLINE' }), 'success');
        btnTest.textContent = t('ui.connected', '✓ Connected');
        setTimeout(() => { btnTest.textContent = t('mgmt.ups_btn_test_conn', '🔌 Test Connection'); }, 3000);
      } else {
        showToast(t('toast.connection_failed', 'Connection failed: {error}', { error: res.error || 'UPS daemon unreachable' }), 'error');
        btnTest.textContent = t('ui.failed', '✗ Failed');
        setTimeout(() => { btnTest.textContent = t('mgmt.ups_btn_test_conn', '🔌 Test Connection'); }, 3000);
      }
    } catch (err) {
      showToast(t('toast.connection_test_error', 'Connection test error: {error}', { error: err.message }), 'error');
      btnTest.textContent = t('ui.error_2', '✗ Error');
      setTimeout(() => { btnTest.textContent = t('mgmt.ups_btn_test_conn', '🔌 Test Connection'); }, 3000);
    } finally {
      btnTest.disabled = false;
    }
  });

  // Legacy save button handler fallback if still rendered in custom views
  const btnSave = document.getElementById('btn-save-ups-config');
  btnSave?.addEventListener('click', async () => {
    await saveUpsConfigFromDrawer();
    closeUpsDrawer();
  });

  // Battery Self-Test
  const btnSelfTest = document.getElementById('btn-run-ups-selftest');
  btnSelfTest?.addEventListener('click', () => {
    showConfirmToast(
      'Run Diagnostic Battery Self-Test?',
      'This commands the UPS inverter to perform a 10-second internal battery discharge test under active load.',
      async () => {
        try {
          showToast(t('toast.initiating_battery_self_test', 'Initiating battery self-test...'), 'info');
          const res = await api.post('/api/ups/self-test');
          showToast(res.message || 'Battery self-test command sent successfully!', 'success');
          fetchAndRenderUpsTelemetry();
        } catch (err) {
          showToast(t('toast.self_test_failed', 'Self-test failed: {error}', { error: err.message }), 'error');
        }
      },
      null,
      { okText: '🔋 Run Self-Test', cancelText: 'Cancel' }
    );
  });

  // Outage Simulation Drill
  const btnSimulate = document.getElementById('btn-ups-simulate');
  btnSimulate?.addEventListener('click', () => {
    showConfirmToast(
      'Simulate Power Outage Drill?',
      'This simulates a 15-second utility power failure drill to verify digital twin electron animations, emergency countdown banner, and event ledger logging. <strong>Host will NOT shut down.</strong>',
      async () => {
        try {
          showToast(t('toast.outage_drill_started_15s', 'Outage drill started (15s)...'), 'warn');
          await api.post('/api/ups/simulate', { duration_sec: 15 });
          fetchAndRenderUpsTelemetry();
        } catch (err) {
          showToast(t('toast.simulation_failed', 'Simulation failed: {error}', { error: err.message }), 'error');
        }
      },
      null,
      { okText: '⚠️ Start Drill', cancelText: 'Cancel', allowHtml: true }
    );
  });
  return loadPromise;
}
if (typeof window !== 'undefined') window.initUpsDrawerControls = initUpsDrawerControls;
