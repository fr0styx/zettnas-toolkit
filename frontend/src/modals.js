import { showToast } from "./toast.js";
import { ZettEventBus } from './event-bus.js';
import { api } from './api.js';
import { DockManager, bringToFront } from './components/dock.js';
import { trapFocus } from './utils.js';
import { t } from './i18n.js';
// S.M.A.R.T. & INTERACTIVE METRIC DIAGNOSTIC MODAL CONTROLLER

let activeModalType = null;
let smartOverlay, smartCloseBtn, smartTitle, smartModel, smartSerial, smartHealth, smartHours, smartRaw, smartLbl1, smartLbl2, smartLbl3, smartLbl4, smartRawTitle, smartRefreshBtn;
let _unbindSmartTrap = null;

window.addEventListener('DOMContentLoaded', () => {
    smartOverlay = document.getElementById("smart-modal-overlay");
    smartCloseBtn = document.getElementById("smart-modal-close");
    smartTitle = document.getElementById("smart-modal-title");
    smartModel = document.getElementById("smart-meta-model");
    smartSerial = document.getElementById("smart-meta-serial");
    smartHealth = document.getElementById("smart-meta-health");
    smartHours = document.getElementById("smart-meta-hours");
    smartRaw = document.getElementById("smart-raw-output");
    smartLbl1 = document.getElementById("smart-lbl-1");
    smartLbl2 = document.getElementById("smart-lbl-2");
    smartLbl3 = document.getElementById("smart-lbl-3");
    smartLbl4 = document.getElementById("smart-lbl-4");
    smartRawTitle = document.getElementById("smart-modal-raw-title");
    smartRefreshBtn = document.getElementById("smart-modal-refresh");
    const minBtn = document.getElementById("smart-min") || document.getElementById("smart-modal-min");
    
    if (smartRefreshBtn) {
      smartRefreshBtn.addEventListener("click", () => {
        if (activeModalType && activeModalType.startsWith("disk_")) {
          openSmartModal(activeModalType.replace("disk_", ""));
        } else if (activeModalType) {
          openMetricModal(activeModalType);
        }
      });
    }
    if (smartCloseBtn) {
      const handleClose = (e) => {
        if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
        closeSmartModal();
      };
      smartCloseBtn.addEventListener("click", handleClose);
      smartCloseBtn.addEventListener("touchend", handleClose);
    }
    if (minBtn) {
      const handleMin = (e) => {
        if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
        if (DockManager) DockManager.minimize("smart");
      };
      minBtn.addEventListener("click", handleMin);
      minBtn.addEventListener("touchend", handleMin);
    }
    if (smartOverlay) {
      smartOverlay.addEventListener("click", (e) => {
        if (e.target === smartOverlay) closeSmartModal();
      });
    }

    const shortTestBtn = document.getElementById("smart-btn-short-test");
    const extTestBtn = document.getElementById("smart-btn-extended-test");
    const abortTestBtn = document.getElementById("smart-btn-abort-test");
    const testStatus = document.getElementById("smart-test-status");

    async function triggerTest(type) {
      if (!activeModalType || !activeModalType.startsWith("disk_")) return;
      const dev = activeModalType.replace("disk_", "");
      if (testStatus) testStatus.textContent = type === 'abort' ? 'Aborting test...' : `Starting ${type} test...`;
      try {
        const res = await api.post("/api/disk/smart_test", { dev, test_type: type });
        if (res && res.success) {
          if (type === 'abort') {
            showToast(`Self-test aborted on /dev/${dev}`, "ok");
            if (testStatus) testStatus.textContent = "Test Aborted";
            if (abortTestBtn) abortTestBtn.style.display = "none";
          } else {
            showToast(`${type.toUpperCase()} self-test started on /dev/${dev}`, "ok");
            if (testStatus) testStatus.textContent = `Running ${type} test`;
            if (abortTestBtn) abortTestBtn.style.display = "inline-block";
          }
          if (smartRaw) smartRaw.textContent = `[S.M.A.R.T. Self-Test Action: ${type}]\n${res.output}\n\n` + smartRaw.textContent;
        } else {
          showToast(`Failed: ${res?.error || 'Unknown error'}`, "error");
          if (testStatus) testStatus.textContent = `Failed: ${res?.error || 'Error'}`;
        }
      } catch (err) {
        showToast(`Test error: ${err.message}`, "error");
        if (testStatus) testStatus.textContent = "Error";
      }
    }

    if (shortTestBtn) shortTestBtn.addEventListener("click", () => triggerTest("short"));
    if (extTestBtn) extTestBtn.addEventListener("click", () => triggerTest("long"));
    if (abortTestBtn) abortTestBtn.addEventListener("click", () => triggerTest("abort"));
});


let _smartFetchController = null;

async function openSmartModal(devName) {
  if (_smartFetchController) _smartFetchController.abort();
  _smartFetchController = new AbortController();
  if (!smartOverlay) smartOverlay = document.getElementById("smart-modal-overlay");
  if (!smartOverlay) return;
  activeModalType = "disk_" + devName;
  smartOverlay.style.display = "flex";
  smartOverlay.classList.remove("window-minimized");
  smartOverlay.classList.add("open");
  if (DockManager) {
    DockManager.register("smart", smartOverlay, "#i-disk", "Diagnostics");
    DockManager.restore("smart");
  }
  const modalWin = smartOverlay.querySelector(".smart-modal-window");
  if (modalWin && bringToFront) bringToFront(modalWin);
  if (_unbindSmartTrap) { _unbindSmartTrap(); }
  if (modalWin) _unbindSmartTrap = trapFocus(modalWin, closeSmartModal);

  const actionsBox = document.getElementById("smart-actions-container");
  if (actionsBox) actionsBox.style.display = "flex";

  if (smartTitle) smartTitle.innerHTML = `<svg class="ic"><use href="#i-disk"/></svg> ${t('modal.diag_title', 'S.M.A.R.T. Diagnostics')} • /dev/${devName}`;
  if (smartLbl1) smartLbl1.textContent = t('modal.smart_device_model', "DEVICE & MODEL");
  if (smartLbl2) smartLbl2.textContent = t('modal.smart_serial_metric', "SERIAL NUMBER");
  if (smartLbl3) smartLbl3.textContent = t('modal.smart_health_status', "HEALTH STATUS");
  if (smartLbl4) smartLbl4.textContent = t('modal.smart_hours_readout', "POWER-ON HOURS");
  if (smartRawTitle) smartRawTitle.textContent = t('modal.smart_raw_telemetry', "RAW SMART ATTRIBUTES");

  if (smartModel) smartModel.textContent = t('common.loading', "Loading...");
  if (smartSerial) smartSerial.textContent = t('common.loading', "Loading...");
  if (smartHealth) smartHealth.textContent = t('common.loading', "Loading...");
  if (smartHours) smartHours.textContent = t('common.loading', "Loading...");
  if (smartRaw) smartRaw.textContent = t('common.loading', "Loading...");

  try {
    const res = await api.request(`/api/disk_detail?dev=${encodeURIComponent(devName)}`, { signal: _smartFetchController.signal });
    if (res.ok) {
      const data = await res.json();
      if (smartModel) smartModel.textContent = data.model || "Unknown";
      if (smartSerial) smartSerial.textContent = data.serial || "Unknown";
      if (smartHealth) {
        smartHealth.textContent = data.health || "UNKNOWN";
        if (data.health === "PASSED") {
          smartHealth.style.color = "var(--ok)";
        } else if (data.health === "UNKNOWN") {
          smartHealth.style.color = "var(--muted)";
        } else {
          smartHealth.style.color = "var(--crit)";
        }
      }
      const abortTestBtn = document.getElementById("smart-btn-abort-test");
      const testStatus = document.getElementById("smart-test-status");
      if (data.self_test_status) {
        if (testStatus) testStatus.textContent = data.self_test_status;
        const low = data.self_test_status.toLowerCase();
        const inProg = low.includes("in progress") || low.includes("remaining") || low.includes("started");
        if (abortTestBtn) abortTestBtn.style.display = inProg ? "inline-block" : "none";
      } else {
        if (testStatus) testStatus.textContent = "";
        if (abortTestBtn) abortTestBtn.style.display = "none";
      }
      if (smartHours) smartHours.textContent = data.power_on_hours || "Unknown";
      if (smartRaw) smartRaw.textContent = data.raw || "No raw output.";

      const degBanner = document.getElementById("smart-degradation-banner");
      if (degBanner) {
        let bannerHtml = '';
        if (data.nvme_endurance) {
          const nv = data.nvme_endurance;
          const tbw = nv.tbw_tb != null ? `${nv.tbw_tb} TB` : '--';
          const tbr = nv.tbr_tb != null ? `${nv.tbr_tb} TB` : '--';
          const wear = nv.percentage_used != null ? `${nv.percentage_used}%` : '--';
          const spare = nv.available_spare != null ? `${nv.available_spare}%` : '--';
          bannerHtml += `
            <div style="display: flex; gap: 12px; margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 10px; font-weight: 600; text-transform: uppercase; color: var(--text-color);">
              <span>💾 <strong>TBW:</strong> ${tbw}</span>
              <span>📖 <strong>TBR:</strong> ${tbr}</span>
              <span>⚡ <strong>Wear:</strong> ${wear}</span>
              <span>🛡️ <strong>Spare:</strong> ${spare}</span>
            </div>
          `;
        }
        if (data.degradation) {
          const deg = data.degradation;
          const color = deg.status === 'critical' ? 'var(--crit)' : deg.status === 'warning' ? 'var(--warn)' : 'var(--ok)';
          const icon = deg.status === 'critical' ? '⚠️' : deg.status === 'warning' ? '⏳' : '🛡️';
          bannerHtml += `
            <div style="display: flex; align-items: flex-start; gap: 8px;">
              <span style="font-size: 14px;">${icon}</span>
              <div style="flex: 1;">
                <div style="font-weight: 700; color: ${color}; text-transform: uppercase; font-size: 10px; letter-spacing: 0.5px;">
                  ${deg.status.replace('_', ' ')} • SMART Velocity Analysis
                </div>
                <div style="color: var(--text-secondary); margin-top: 2px;">
                  ${deg.recommendation}
                </div>
              </div>
            </div>
          `;
        }
        if (bannerHtml) {
          degBanner.innerHTML = bannerHtml;
          degBanner.style.display = 'block';
        } else {
          degBanner.style.display = 'none';
        }
      }
    }
  } catch (err) {
    if (smartRaw) smartRaw.textContent = `Error querying disk details: ${err}`;
  }
}

function updateMetricModalLive() {
  const s = _latestStats; if (!smartOverlay || !smartOverlay.classList.contains("open") || !s || !activeModalType) return;
  
  if (activeModalType === "storage") {
    smartModel.textContent = s.storage.used;
    smartSerial.textContent = s.storage.total;
    smartHealth.textContent = `${s.storage.pct}%`;
    smartHealth.style.color = s.storage.pct >= 90 ? "var(--crit)" : "var(--ok)";
    smartRaw.textContent = JSON.stringify(s.disks, null, 2);
  } else if (activeModalType === "cpu") {
    smartModel.textContent = `${s.cpu.temp}°C`;
    smartSerial.textContent = `${s.cpu.util}%`;
    smartHealth.textContent = s.cpu.temp >= 75 ? "ELEVATED" : "OPTIMAL";
    smartHealth.style.color = s.cpu.temp >= 75 ? "var(--warn)" : "var(--ok)";
    smartHours.textContent = s.uptime;
    smartRaw.textContent = `Host: ${s.name}\nIP: ${s.ip}\nCPU Temp: ${s.cpu.temp}°C\nCPU Util: ${s.cpu.util}%\nUptime: ${s.uptime}`;
  } else if (activeModalType === "mem") {
    smartModel.textContent = `${s.mem.used_gb} GB`;
    smartSerial.textContent = `${s.mem.total_gb} GB`;
    smartHealth.textContent = `${s.mem.pct}%`;
    smartHealth.style.color = s.mem.pct >= 90 ? "var(--crit)" : "var(--ok)";
    smartHours.textContent = `${(s.mem.total_gb - s.mem.used_gb).toFixed(1)} GB`;
    smartRaw.textContent = JSON.stringify(s.mem, null, 2);
  } else if (activeModalType === "fans") {
    const f = s.fans || [];
    smartModel.textContent = f[0] ? `${f[0]} RPM` : "N/A";
    smartSerial.textContent = f[1] ? `${f[1]} RPM` : "N/A";
    smartHealth.textContent = f[2] ? `${f[2]} RPM` : "N/A";
    smartRaw.textContent = `Tachometer Inputs:\n- Fan 1 (Disks 1): ${f[0] || 0} RPM\n- Fan 2 (Disks 2): ${f[1] || 0} RPM\n- Fan 3 (CPU): ${f[2] || 0} RPM\n- Sysfs Path: /sys/class/hwmon\n- Native Duty Range: 0-183`;
  } else if (activeModalType === "net") {
    smartModel.textContent = s.net ? s.net.tx : "0 KB/s";
    smartSerial.textContent = s.net ? s.net.rx : "0 KB/s";
    smartHealth.textContent = "CONNECTED";
    smartHealth.style.color = "var(--ok)";
    smartHours.textContent = s.ip;
    smartRaw.textContent = `Network Subsystem Telemetry:\n- Host IP: ${s.ip}\n- Interface Transmit Rate (TX): ${s.net ? s.net.tx : "0 KB/s"}\n- Interface Receive Rate (RX): ${s.net ? s.net.rx : "0 KB/s"}\n- Host Source: /proc/net/dev`;
  }
}

function openMetricModal(type) {
  const s = _latestStats;
  if (!smartOverlay) smartOverlay = document.getElementById("smart-modal-overlay");
  if (!smartOverlay || !s) return;
  activeModalType = type;
  smartOverlay.style.display = "flex";
  smartOverlay.classList.remove("window-minimized");
  smartOverlay.classList.add("open");
  if (DockManager) {
    DockManager.register("smart", smartOverlay, "#i-disk", "Diagnostics");
    DockManager.restore("smart");
  }
  const modalWin = smartOverlay.querySelector(".smart-modal-window");
  if (modalWin && bringToFront) bringToFront(modalWin);
  if (_unbindSmartTrap) { _unbindSmartTrap(); }
  if (modalWin) _unbindSmartTrap = trapFocus(modalWin, closeSmartModal);

  const actionsBox = document.getElementById("smart-actions-container");
  if (actionsBox) actionsBox.style.display = "none";

  if (type === "storage") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-disk"/></svg> ${t('modal.storage_diag', 'Storage Array Diagnostics')}`;
    smartLbl1.textContent = t('modal.used_space', "USED SPACE");
    smartLbl2.textContent = t('modal.total_cap', "TOTAL CAPACITY");
    smartLbl3.textContent = t('modal.utilization', "UTILIZATION");
    smartLbl4.textContent = t('modal.target_pool', "TARGET POOL");
    smartHours.textContent = "/mnt/user";
    smartRawTitle.textContent = "ACTIVE DISK INVENTORY";
  } else if (type === "cpu") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-cpu"/></svg> ${t('modal.cpu_diag', 'Processor Diagnostics')}`;
    smartLbl1.textContent = t('modal.core_temp', "CORE TEMP");
    smartLbl2.textContent = t('modal.active_util', "ACTIVE UTILIZATION");
    smartLbl3.textContent = t('modal.thermal_state', "THERMAL STATE");
    smartLbl4.textContent = t('modal.system_uptime', "SYSTEM UPTIME");
    smartRawTitle.textContent = "CPU TOPOLOGY & DELTAS";
  } else if (type === "mem") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-mem"/></svg> ${t('modal.mem_diag', 'Memory Distribution')}`;
    smartLbl1.textContent = t('modal.ram_used', "RAM USED");
    smartLbl2.textContent = t('modal.ram_total', "RAM TOTAL");
    smartLbl3.textContent = t('modal.usage', "USAGE");
    smartLbl4.textContent = t('modal.free_mem', "FREE MEMORY");
    smartRawTitle.textContent = "HOST MEMINFO SNAPSHOT";
  } else if (type === "fans") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-fan"/></svg> ${t('modal.fans_diag', 'Cooling & Fan Tachometers')}`;
    smartLbl1.textContent = t('modal.rear_fan_1', "REAR FAN 1 (D1)");
    smartLbl2.textContent = t('modal.rear_fan_2', "REAR FAN 2 (D2)");
    smartLbl3.textContent = t('modal.cpu_fan', "CPU FAN");
    smartHealth.style.color = "var(--ok2)";
    smartLbl4.textContent = t('modal.hwmon_chip', "HWMON CHIP");
    smartHours.textContent = "zettlab_d8_fans";
    smartRawTitle.textContent = "LIVE FAN SENSOR TELEMETRY";
  } else if (type === "net") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-net"/></svg> ${t('modal.net_diag', 'Network Throughput Diagnostics')}`;
    smartLbl1.textContent = t('modal.current_tx', "CURRENT TX");
    smartLbl2.textContent = t('modal.current_rx', "CURRENT RX");
    smartLbl3.textContent = t('modal.link_state', "LINK STATE");
    smartLbl4.textContent = t('modal.primary_ip', "PRIMARY IP");
    smartRawTitle.textContent = "NETWORK INTERFACE TELEMETRY";
  }
  updateMetricModalLive();
}

function closeSmartModal() {
  activeModalType = null;
  if (_smartFetchController) {
    _smartFetchController.abort();
    _smartFetchController = null;
  }
  if (_unbindSmartTrap) {
    _unbindSmartTrap();
    _unbindSmartTrap = null;
  }
  if (smartOverlay) {
    smartOverlay.classList.remove("open");
    smartOverlay.style.display = "none";
  }
  if (DockManager) DockManager.unregister("smart");
}




// --- EVENT BUS BINDINGS ---
let _latestStats = null;
ZettEventBus.addEventListener('stats_tick', (e) => {
    _latestStats = e.detail;
    if (typeof updateMetricModalLive === 'function') {
        updateMetricModalLive();
    }
});

ZettEventBus.addEventListener('modal:smart:open', (e) => {
    openSmartModal(e.detail);
});

ZettEventBus.addEventListener('modal:metric:open', (e) => {
    openMetricModal(e.detail);
});

ZettEventBus.addEventListener('modal:smart:close', () => closeSmartModal());

window.addEventListener('zettnas:lang-changed', () => {
    if (!smartOverlay || !smartOverlay.classList.contains('open') || !activeModalType) return;
    if (activeModalType.startsWith('disk_')) {
        const devName = activeModalType.replace('disk_', '');
        if (smartTitle) smartTitle.innerHTML = `<svg class="ic"><use href="#i-disk"/></svg> ${t('modal.diag_title', 'S.M.A.R.T. Diagnostics')} • /dev/${devName}`;
        if (smartLbl1) smartLbl1.textContent = t('modal.smart_device_model', "DEVICE & MODEL");
        if (smartLbl2) smartLbl2.textContent = t('modal.smart_serial_metric', "SERIAL NUMBER");
        if (smartLbl3) smartLbl3.textContent = t('modal.smart_health_status', "HEALTH STATUS");
        if (smartLbl4) smartLbl4.textContent = t('modal.smart_hours_readout', "POWER-ON HOURS");
        if (smartRawTitle) smartRawTitle.textContent = t('modal.smart_raw_telemetry', "RAW SMART ATTRIBUTES");
    } else {
        openMetricModal(activeModalType);
    }
});
