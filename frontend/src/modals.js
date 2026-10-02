import { ZettEventBus } from './event-bus.js';
// S.M.A.R.T. & INTERACTIVE METRIC DIAGNOSTIC MODAL CONTROLLER


let activeModalType = null;
let smartOverlay, smartCloseBtn, smartTitle, smartModel, smartSerial, smartHealth, smartHours, smartRaw, smartLbl1, smartLbl2, smartLbl3, smartLbl4, smartRawTitle, smartRefreshBtn;

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
    
    if (smartRefreshBtn) {
      smartRefreshBtn.addEventListener("click", () => {
        if (activeModalType && activeModalType.startsWith("disk_")) {
          openSmartModal(activeModalType.replace("disk_", ""));
        } else if (activeModalType) {
          openMetricModal(activeModalType);
        }
      });
    }
    if (smartCloseBtn) smartCloseBtn.addEventListener("click", closeSmartModal);
    if (smartOverlay) {
      smartOverlay.addEventListener("click", (e) => {
        if (e.target === smartOverlay) closeSmartModal();
      });
    }
});


let _smartFetchController = null;

async function openSmartModal(devName) {
  if (_smartFetchController) _smartFetchController.abort();
  _smartFetchController = new AbortController();
  if (!smartOverlay) return;
  activeModalType = "disk_" + devName;
  smartOverlay.classList.add("open");
  if (smartTitle) smartTitle.innerHTML = `<svg class="ic"><use href="#i-disk"/></svg> S.M.A.R.T. Diagnostics • /dev/${devName}`;
  if (smartLbl1) smartLbl1.textContent = "DEVICE & MODEL";
  if (smartLbl2) smartLbl2.textContent = "SERIAL NUMBER";
  if (smartLbl3) smartLbl3.textContent = "HEALTH STATUS";
  if (smartLbl4) smartLbl4.textContent = "POWER-ON HOURS";
  if (smartRawTitle) smartRawTitle.textContent = "RAW SMART ATTRIBUTES";

  if (smartModel) smartModel.textContent = "Loading...";
  if (smartSerial) smartSerial.textContent = "Loading...";
  if (smartHealth) smartHealth.textContent = "Loading...";
  if (smartHours) smartHours.textContent = "Loading...";
  if (smartRaw) smartRaw.textContent = "Querying drive controller via smartctl...";

  try {
    const res = await fetch(`/api/disk_detail?dev=${encodeURIComponent(devName)}`, { signal: _smartFetchController.signal });
    if (res.ok) {
      const data = await res.json();
      if (smartModel) smartModel.textContent = data.model || "Unknown";
      if (smartSerial) smartSerial.textContent = data.serial || "Unknown";
      if (smartHealth) {
        smartHealth.textContent = data.health || "PASSED";
        smartHealth.style.color = (data.health === "PASSED") ? "var(--ok)" : "var(--crit)";
      }
      if (smartHours) smartHours.textContent = data.power_on_hours || "Unknown";
      if (smartRaw) smartRaw.textContent = data.raw || "No raw output.";
    }
  } catch (err) {
    if (smartRaw) smartRaw.textContent = `Error querying disk details: ${err}`;
  }
}

function updateMetricModalLive() {
  if (!smartOverlay || !smartOverlay.classList.contains("open") || !latestStats || !activeModalType) return;
  
  if (activeModalType === "storage") {
    smartModel.textContent = latestStats.storage.used;
    smartSerial.textContent = latestStats.storage.total;
    smartHealth.textContent = `${latestStats.storage.pct}%`;
    smartHealth.style.color = latestStats.storage.pct >= 90 ? "var(--crit)" : "var(--ok)";
    smartRaw.textContent = JSON.stringify(latestStats.disks, null, 2);
  } else if (activeModalType === "cpu") {
    smartModel.textContent = `${latestStats.cpu.temp}°C`;
    smartSerial.textContent = `${latestStats.cpu.util}%`;
    smartHealth.textContent = latestStats.cpu.temp >= 75 ? "ELEVATED" : "OPTIMAL";
    smartHealth.style.color = latestStats.cpu.temp >= 75 ? "var(--warn)" : "var(--ok)";
    smartHours.textContent = latestStats.uptime;
    smartRaw.textContent = `Host: ${latestStats.name}\nIP: ${latestStats.ip}\nCPU Temp: ${latestStats.cpu.temp}°C\nCPU Util: ${latestStats.cpu.util}%\nUptime: ${latestStats.uptime}`;
  } else if (activeModalType === "mem") {
    smartModel.textContent = `${latestStats.mem.used_gb} GB`;
    smartSerial.textContent = `${latestStats.mem.total_gb} GB`;
    smartHealth.textContent = `${latestStats.mem.pct}%`;
    smartHealth.style.color = latestStats.mem.pct >= 90 ? "var(--crit)" : "var(--ok)";
    smartHours.textContent = `${(latestStats.mem.total_gb - latestStats.mem.used_gb).toFixed(1)} GB`;
    smartRaw.textContent = JSON.stringify(latestStats.mem, null, 2);
  } else if (activeModalType === "fans") {
    const f = latestStats.fans || [];
    smartModel.textContent = f[0] ? `${f[0]} RPM` : "N/A";
    smartSerial.textContent = f[1] ? `${f[1]} RPM` : "N/A";
    smartHealth.textContent = f[2] ? `${f[2]} RPM` : "N/A";
    smartRaw.textContent = `Tachometer Inputs:\n- Fan 1 (Disks 1): ${f[0] || 0} RPM\n- Fan 2 (Disks 2): ${f[1] || 0} RPM\n- Fan 3 (CPU): ${f[2] || 0} RPM\n- Sysfs Path: /sys/class/hwmon\n- Native Duty Range: 0-183`;
  } else if (activeModalType === "net") {
    smartModel.textContent = latestStats.net ? latestStats.net.tx : "0 KB/s";
    smartSerial.textContent = latestStats.net ? latestStats.net.rx : "0 KB/s";
    smartHealth.textContent = "CONNECTED";
    smartHealth.style.color = "var(--ok)";
    smartHours.textContent = latestStats.ip;
    smartRaw.textContent = `Network Subsystem Telemetry:\n- Host IP: ${latestStats.ip}\n- Interface Transmit Rate (TX): ${latestStats.net ? latestStats.net.tx : "0 KB/s"}\n- Interface Receive Rate (RX): ${latestStats.net ? latestStats.net.rx : "0 KB/s"}\n- Host Source: /proc/net/dev`;
  }
}

function openMetricModal(type) {
  if (!smartOverlay || !latestStats) return;
  activeModalType = type;
  smartOverlay.classList.add("open");

  if (type === "storage") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-disk"/></svg> Storage Array Diagnostics`;
    smartLbl1.textContent = "USED SPACE";
    smartLbl2.textContent = "TOTAL CAPACITY";
    smartLbl3.textContent = "UTILIZATION";
    smartLbl4.textContent = "TARGET POOL";
    smartHours.textContent = "/mnt/user";
    smartRawTitle.textContent = "ACTIVE DISK INVENTORY";
  } else if (type === "cpu") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-cpu"/></svg> Processor Diagnostics`;
    smartLbl1.textContent = "CORE TEMP";
    smartLbl2.textContent = "ACTIVE UTILIZATION";
    smartLbl3.textContent = "THERMAL STATE";
    smartLbl4.textContent = "SYSTEM UPTIME";
    smartRawTitle.textContent = "CPU TOPOLOGY & DELTAS";
  } else if (type === "mem") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-mem"/></svg> Memory Distribution`;
    smartLbl1.textContent = "RAM USED";
    smartLbl2.textContent = "RAM TOTAL";
    smartLbl3.textContent = "USAGE";
    smartLbl4.textContent = "FREE MEMORY";
    smartRawTitle.textContent = "HOST MEMINFO SNAPSHOT";
  } else if (type === "fans") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-fan"/></svg> Cooling & Fan Tachometers`;
    smartLbl1.textContent = "REAR FAN 1 (D1)";
    smartLbl2.textContent = "REAR FAN 2 (D2)";
    smartLbl3.textContent = "CPU FAN";
    smartHealth.style.color = "var(--ok2)";
    smartLbl4.textContent = "HWMON CHIP";
    smartHours.textContent = "zettlab_d8_fans";
    smartRawTitle.textContent = "LIVE FAN SENSOR TELEMETRY";
  } else if (type === "net") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-net"/></svg> Network Throughput Diagnostics`;
    smartLbl1.textContent = "CURRENT TX";
    smartLbl2.textContent = "CURRENT RX";
    smartLbl3.textContent = "LINK STATE";
    smartLbl4.textContent = "PRIMARY IP";
    smartRawTitle.textContent = "NETWORK INTERFACE TELEMETRY";
  }
  updateMetricModalLive();
}

function closeSmartModal() {
  activeModalType = null;
  if (smartOverlay) smartOverlay.classList.remove("open");
}




// --- EVENT BUS BINDINGS ---
let _latestStats = null;
ZettEventBus.addEventListener('stats_tick', (e) => {
    _latestStats = e.detail;
    if (typeof updateMetricModalLive === 'function') {
        window.latestStats = _latestStats; 
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
