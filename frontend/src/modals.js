import { showToast } from "./toast.js";
import { ZettEventBus } from './event-bus.js';
import { DockManager, bringToFront, makeDraggable } from './components/dock.js';
import { trapFocus } from './utils.js';
import { t } from './i18n.js';
import { formatDateTime } from './format.js';
// Metric detail windows (CPU, memory, network...) and the event detail window. Drives have
// their own app, Drive Health (components/drive-health.js).

let activeModalType = null;
let smartOverlay, smartCloseBtn, smartTitle, smartModel, smartSerial, smartHealth, smartHours, smartRaw, smartLbl1, smartLbl2, smartLbl3, smartLbl4, smartRawTitle, smartRefreshBtn;
let _unbindSmartTrap = null;
let _eventDetailOverlay = null;
let _unbindEventDetailTrap = null;
let _currentEventDetailData = null;

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
        if (activeModalType) {
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

    // Event Detail Modal Setup
    _eventDetailOverlay = document.getElementById("event-detail-modal-overlay");
    const eventDetailClose = document.getElementById("event-detail-close");
    const eventDetailCloseBtn = document.getElementById("event-detail-close-btn");
    const eventDetailCopyBtn = document.getElementById("event-detail-copy-btn");
    const eventDetailHeader = document.getElementById("event-detail-header");
    const eventDetailWindow = _eventDetailOverlay ? _eventDetailOverlay.querySelector(".smart-modal-window") : null;

    if (eventDetailClose) eventDetailClose.addEventListener("click", closeEventDetailModal);
    if (eventDetailCloseBtn) eventDetailCloseBtn.addEventListener("click", closeEventDetailModal);
    if (_eventDetailOverlay) {
      _eventDetailOverlay.addEventListener("click", (e) => {
        if (e.target === _eventDetailOverlay) closeEventDetailModal();
      });
    }

    if (eventDetailWindow && eventDetailHeader && makeDraggable) {
      makeDraggable(eventDetailWindow, eventDetailHeader, "event-detail");
    }

    if (eventDetailCopyBtn) {
      eventDetailCopyBtn.addEventListener("click", async () => {
        if (!_currentEventDetailData) return;
        let textToCopy = JSON.stringify(_currentEventDetailData, null, 2);
        if (_currentEventDetailData?.details?.report_markdown) {
          textToCopy = _currentEventDetailData.details.report_markdown;
        }
        try {
          await copyText(textToCopy);
          const copyText = document.getElementById("event-detail-copy-text");
          const copyIcon = document.getElementById("event-detail-copy-icon");
          if (copyText) copyText.textContent = t("event_detail.copied", "Copied!");
          if (copyIcon) copyIcon.textContent = "✓";
          eventDetailCopyBtn.style.borderColor = "var(--ok2, #10b981)";
          eventDetailCopyBtn.style.color = "var(--ok2, #10b981)";
          showToast(t('toast.event_details_copied_to_clipboard', "Event details copied to clipboard"), "info");
          setTimeout(() => {
            if (copyText) copyText.textContent = t("event_detail.copy", "Copy Details");
            if (copyIcon) copyIcon.textContent = "📋";
            eventDetailCopyBtn.style.borderColor = "rgba(255, 255, 255, 0.14)";
            eventDetailCopyBtn.style.color = "#fff";
          }, 2000);
        } catch (err) {
          console.warn("Copy details failed:", err);
        }
      });
    }
});

let _smartFetchController = null;

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

  const navTabs = document.getElementById("smart-nav-tabs");
  if (navTabs) navTabs.style.display = "none";
  const healthPane = document.getElementById("smart-pane-health");
  const selftestPane = document.getElementById("smart-pane-selftest");
  const rawPane = document.getElementById("smart-pane-raw");
  if (healthPane) {
    healthPane.classList.add("active");
    healthPane.style.display = "block";
  }
  if (selftestPane) {
    selftestPane.classList.remove("active");
    selftestPane.style.display = "none";
  }
  if (rawPane) {
    rawPane.classList.add("active");
    rawPane.style.display = "block";
  }
  const rawFilterWrap = document.querySelector(".smart-raw-toolbar");
  if (rawFilterWrap) rawFilterWrap.style.display = "none";

  if (type === "storage") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-disk"/></svg> ${t('modal.storage_diag', 'Storage Array Diagnostics')}`;
    smartLbl1.textContent = t('modal.used_space', "Used");
    smartLbl2.textContent = t('modal.total_cap', "Total");
    smartLbl3.textContent = t('modal.utilization', "In use");
    smartLbl4.textContent = t('modal.target_pool', "Pool");
    smartHours.textContent = "/mnt/user";
    smartRawTitle.textContent = "ACTIVE DISK INVENTORY";
  } else if (type === "cpu") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-cpu"/></svg> ${t('modal.cpu_diag', 'Processor Diagnostics')}`;
    smartLbl1.textContent = t('modal.core_temp', "Temperature");
    smartLbl2.textContent = t('modal.active_util', "Busy");
    smartLbl3.textContent = t('modal.thermal_state', "Heat");
    smartLbl4.textContent = t('modal.system_uptime', "Running for");
    smartRawTitle.textContent = "CPU TOPOLOGY & DELTAS";
  } else if (type === "mem") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-mem"/></svg> ${t('modal.mem_diag', 'Memory Distribution')}`;
    smartLbl1.textContent = t('modal.ram_used', "Memory used");
    smartLbl2.textContent = t('modal.ram_total', "Memory total");
    smartLbl3.textContent = t('modal.usage', "Usage");
    smartLbl4.textContent = t('modal.free_mem', "Free memory");
    smartRawTitle.textContent = "HOST MEMINFO SNAPSHOT";
  } else if (type === "fans") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-fan"/></svg> ${t('modal.fans_diag', 'Cooling & Fan Tachometers')}`;
    smartLbl1.textContent = t('modal.rear_fan_1', "Rear fan 1");
    smartLbl2.textContent = t('modal.rear_fan_2', "Rear fan 2");
    smartLbl3.textContent = t('modal.cpu_fan', "Processor fan");
    smartHealth.style.color = "var(--ok2)";
    smartLbl4.textContent = t('modal.hwmon_chip', "Sensor chip");
    smartHours.textContent = "zettlab_d8_fans";
    smartRawTitle.textContent = "LIVE FAN SENSOR TELEMETRY";
  } else if (type === "net") {
    smartTitle.innerHTML = `<svg class="ic"><use href="#i-net"/></svg> ${t('modal.net_diag', 'Network Throughput Diagnostics')}`;
    smartLbl1.textContent = t('modal.current_tx', "Sending now");
    smartLbl2.textContent = t('modal.current_rx', "Receiving now");
    smartLbl3.textContent = t('modal.link_state', "Connection");
    smartLbl4.textContent = t('modal.primary_ip', "IP address");
    smartRawTitle.textContent = "NETWORK INTERFACE TELEMETRY";
  }
  updateMetricModalLive();
}

export function closeSmartModal() {
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

ZettEventBus.addEventListener('modal:metric:open', (e) => {
    openMetricModal(e.detail);
});

ZettEventBus.addEventListener('modal:smart:close', () => closeSmartModal());

export function closeEventDetailModal() {
  if (_unbindEventDetailTrap) {
    _unbindEventDetailTrap();
    _unbindEventDetailTrap = null;
  }
  if (!_eventDetailOverlay || !document.body.contains(_eventDetailOverlay)) {
    _eventDetailOverlay = document.getElementById("event-detail-modal-overlay");
  }
  if (_eventDetailOverlay) {
    _eventDetailOverlay.classList.remove("open");
    _eventDetailOverlay.style.display = "none";
  }
}

export function openEventDetailModal(ev) {
  if (!ev) return;
  _currentEventDetailData = ev;
  if (!_eventDetailOverlay || !document.body.contains(_eventDetailOverlay)) {
    _eventDetailOverlay = document.getElementById("event-detail-modal-overlay");
  }
  if (!_eventDetailOverlay) return;

  _eventDetailOverlay.style.display = "flex";
  _eventDetailOverlay.classList.remove("window-minimized");
  _eventDetailOverlay.classList.add("open");

  const modalWin = _eventDetailOverlay.querySelector(".smart-modal-window");
  if (modalWin && bringToFront) bringToFront(modalWin);
  if (_unbindEventDetailTrap) { _unbindEventDetailTrap(); }
  if (modalWin) _unbindEventDetailTrap = trapFocus(modalWin, closeEventDetailModal);

  const headerIcon = document.getElementById("event-detail-header-icon");
  const badgeIcon = document.getElementById("event-detail-badge-icon");
  const badgeText = document.getElementById("event-detail-badge-text");
  const badgeEl = document.getElementById("event-detail-badge");
  const subsystemEl = document.getElementById("event-detail-subsystem");
  const relTimeEl = document.getElementById("event-detail-reltime");
  const headlineEl = document.getElementById("event-detail-event-title");
  const messageEl = document.getElementById("event-detail-event-message");
  const localTimeEl = document.getElementById("event-detail-localtime");
  const epochEl = document.getElementById("event-detail-epoch");
  const rawEl = document.getElementById("event-detail-raw");
  const contextBtn = document.getElementById("event-detail-context-btn");

  const lvl = (ev.level || "info").toLowerCase();
  let icon = "ℹ️";
  let badgeColor = "#38bdf8";
  let badgeBg = "rgba(14, 165, 233, 0.2)";
  let badgeBorder = "rgba(14, 165, 233, 0.4)";

  if (lvl === "error") {
    icon = "❌";
    badgeColor = "var(--crit, #ff5c5c)";
    badgeBg = "rgba(239, 68, 68, 0.2)";
    badgeBorder = "rgba(239, 68, 68, 0.4)";
  } else if (lvl === "warning") {
    icon = "⚠️";
    badgeColor = "var(--warn, #f5a623)";
    badgeBg = "rgba(245, 166, 35, 0.2)";
    badgeBorder = "rgba(245, 166, 35, 0.4)";
  } else if (lvl === "success") {
    icon = "✅";
    badgeColor = "var(--ok2, #10b981)";
    badgeBg = "rgba(16, 185, 129, 0.2)";
    badgeBorder = "rgba(16, 185, 129, 0.4)";
  }

  if (headerIcon) headerIcon.textContent = icon;
  if (badgeIcon) badgeIcon.textContent = icon;
  if (badgeText) badgeText.textContent = lvl.toUpperCase();
  if (badgeEl) {
    badgeEl.style.color = badgeColor;
    badgeEl.style.background = badgeBg;
    badgeEl.style.border = `1px solid ${badgeBorder}`;
  }

  const searchStr = `${ev.title || ""} ${ev.message || ""}`.toLowerCase();
  let subsystem;
  let actionLabel;
  let actionFn;

  // 1. SD Card / TF Card / Media Slots / Ingest / Copy Button
  if (/sd card|tf card|microsd|\bsd\b|\bslot\b|media slot|media ingest|auto-ingest|ingest|card reader|card eject|card insert|copy button|\bcopy\b/.test(searchStr)) {
    subsystem = "MEDIA & INGEST";
    actionLabel = t("event_detail.action_media_card", "Open Media Card Settings");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openDrawer === "function") {
        window.openDrawer("tab-buttons");
      } else {
        const drawerBtn = document.getElementById("drawer-toggle-btn") || document.getElementById("suite-toolkit-btn");
        if (drawerBtn) drawerBtn.click();
        const tabBtn = document.querySelector('.drawer-tab-btn[data-tab="tab-buttons"]');
        if (tabBtn) tabBtn.click();
      }
    };
  }
  // 2. LED Strip / Lightbar / Night Mode
  else if (/\bled\b|lightbar|argb|\brgb\b|lighting|night mode|blackout/.test(searchStr)) {
    subsystem = "ARGB LIGHTBAR";
    actionLabel = t("event_detail.action_led", "Open LED Controls");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openDrawer === "function") {
        window.openDrawer("tab-led");
      } else {
        const drawerBtn = document.getElementById("drawer-toggle-btn") || document.getElementById("suite-toolkit-btn");
        if (drawerBtn) drawerBtn.click();
        const tabBtn = document.querySelector('.drawer-tab-btn[data-tab="tab-led"]');
        if (tabBtn) tabBtn.click();
      }
    };
  }
  // 3. Thermal & Fans
  else if (/\bfans?\b|thermal|\btemps?\b|temperature|\brpm\b|\bpwm\b|fan curve|cooling|\bcpu\b|zero[ -]?rpm|tachometer|hysteresis/.test(searchStr)) {
    subsystem = "THERMAL & FANS";
    actionLabel = t("event_detail.action_thermal", "Open Fan Control");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openDrawer === "function") {
        window.openDrawer("tab-fans");
      } else {
        const drawerBtn = document.getElementById("drawer-toggle-btn") || document.getElementById("suite-toolkit-btn");
        if (drawerBtn) drawerBtn.click();
        const fanTab = document.querySelector('.drawer-tab-btn[data-tab="tab-fans"]');
        if (fanTab) fanTab.click();
      }
    };
  }
  // 4. File Explorer & Recycle Bin
  else if (/file explorer|recycle bin|file deleted|file uploaded|fs_upload|\btrash\b/.test(searchStr)) {
    subsystem = "FILE EXPLORER";
    actionLabel = t("event_detail.action_files", "Open File Explorer");
    actionFn = () => {
      closeEventDetailModal();
      if (/recycle bin|trash/.test(searchStr) && typeof window.openRecycleBin === "function") {
        window.openRecycleBin();
      } else {
        ZettEventBus.emit('window:open', { id: 'file-manager-window' });
      }
    };
  }
  // 5. Security & Access
  else if (/security|\btokens?\b|api token|password|\bauth\b|login|unauthorized|credential|permission/.test(searchStr)) {
    subsystem = "SECURITY & ACCESS";
    actionLabel = t("event_detail.action_security", "Open Security Settings");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openManagementWindow === "function") {
        window.openManagementWindow("mgmt-pane-security");
      }
    };
  }
  // 6. Power & UPS
  else if (/\bups\b|battery|\bpower\b|\bnut\b|apcupsd|charge|runtime|on-battery|on battery/.test(searchStr)) {
    subsystem = "POWER & UPS";
    actionLabel = t("event_detail.action_ups", "Open Power & UPS");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openManagementWindow === "function") {
        window.openManagementWindow("mgmt-sec-ups");
      }
    };
  }
  // 7. Storage & S.M.A.R.T. Disks
  else if (/smart|\bdisks?\b|\bnvme\b|\bdrives?\b|tbw|sectors?|storage|zpool|btrfs|\bata\b|drive health|degradation/.test(searchStr)) {
    subsystem = "STORAGE & S.M.A.R.T.";
    actionLabel = t("event_detail.action_smart", "Open Drive Health");
    actionFn = () => {
      closeEventDetailModal();
      const dev = ev.details?.dev || (searchStr.match(/\b(sd[a-z]|nvme\d+n\d+)\b/) || [])[1];
      ZettEventBus.emit('modal:smart:open', dev || null);
    };
  }
  // 8. Docker Containers
  else if (/\bdocker\b|\bcontainers?\b|compose|cgroup/.test(searchStr)) {
    subsystem = "DOCKER CONTAINERS";
    actionLabel = t("event_detail.action_docker", "Open the app");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openManagementWindow === "function") {
        window.openManagementWindow("mgmt-pane-docker");
      }
    };
  }
  // 9. Unraid OS & Array
  else if (/unraid|\barray\b|parity|mover|disks\.ini|var\.ini/.test(searchStr)) {
    subsystem = "UNRAID OS & ARRAY";
    actionLabel = t("event_detail.action_unraid", "Open Array Status");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openManagementWindow === "function") {
        window.openManagementWindow("mgmt-pane-unraid");
      }
    };
  }
  // 10. Dashboard Layout & Widgets
  else if (/layout|\bwidgets?\b|dashboard layout|tachometer card/.test(searchStr)) {
    subsystem = "DASHBOARD LAYOUT";
    actionLabel = t("event_detail.action_layout", "Customize Dashboard");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openDrawer === "function") {
        window.openDrawer("tab-layout");
      } else {
        const drawerBtn = document.getElementById("drawer-toggle-btn") || document.getElementById("suite-toolkit-btn");
        if (drawerBtn) drawerBtn.click();
        const tabBtn = document.querySelector('.drawer-tab-btn[data-tab="tab-layout"]');
        if (tabBtn) tabBtn.click();
      }
    };
  }
  // 11. System Console
  else if (/console|terminal|\bpty\b|\bshell\b|stdout|stderr/.test(searchStr)) {
    subsystem = "SYSTEM CONSOLE";
    actionLabel = t("event_detail.action_console", "Open System Console");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openConsoleWindow === "function") {
        window.openConsoleWindow();
      }
    };
  }
  // 12. Appearance & Wallpaper
  else if (/wallpaper|\btheme\b|appearance|dark mode/.test(searchStr)) {
    subsystem = "APPEARANCE & THEME";
    actionLabel = t("event_detail.action_wallpaper", "Open Wallpaper Settings");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openManagementWindow === "function") {
        window.openManagementWindow("mgmt-pane-wallpaper");
      }
    };
  }
  // 13. System Metrics & Telemetry
  else if (/metrics|telemetry|load average|ram usage|memory usage|network bandwidth/.test(searchStr)) {
    subsystem = "SYSTEM METRICS";
    actionLabel = t("event_detail.action_metrics", "Open Activity Monitor");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openManagementWindow === "function") {
        window.openManagementWindow("mgmt-pane-metrics");
      }
    };
  }
  // 14. Fallback: Full Event Log
  else {
    subsystem = "SYSTEM LOG";
    actionLabel = t("event_detail.action_events", "Open Full Event Log");
    actionFn = () => {
      closeEventDetailModal();
      if (typeof window.openManagementWindow === "function") {
        window.openManagementWindow("mgmt-pane-events");
      }
    };
  }

  if (subsystemEl) subsystemEl.textContent = subsystem;

  const ts = ev.ts || Math.floor(Date.now() / 1000);
  const now = Math.floor(Date.now() / 1000);
  const diff = Math.max(0, now - ts);
  let relText;
  if (diff < 10) relText = t("time.just_now", "Just now");
  else if (diff < 3600) relText = `${Math.floor(diff / 60)}m ago`;
  else if (diff < 86400) relText = `${Math.floor(diff / 3600)}h ago`;
  else relText = `${Math.floor(diff / 86400)}d ago`;

  const dt = new Date(ts * 1000);
  if (relTimeEl) relTimeEl.textContent = relText;
  if (localTimeEl) localTimeEl.textContent = formatDateTime(dt);
  if (epochEl) epochEl.textContent = `${ts} (${dt.toISOString()})`;

  if (headlineEl) headlineEl.textContent = ev.title || "System Notification";
  if (messageEl) messageEl.textContent = ev.message || "--";

  if (rawEl) {
    if (ev.details && ev.details.report_markdown) {
      rawEl.textContent = ev.details.report_markdown;
    } else {
      try {
        rawEl.textContent = JSON.stringify(ev, null, 2);
      } catch {
        rawEl.textContent = String(ev);
      }
    }
  }

  if (contextBtn) {
    if (actionLabel && actionFn) {
      contextBtn.textContent = actionLabel;
      contextBtn.style.display = "inline-block";
      contextBtn.onclick = actionFn;
    } else {
      contextBtn.style.display = "none";
      contextBtn.onclick = null;
    }
  }
}

window.openEventDetailModal = openEventDetailModal;
window.closeEventDetailModal = closeEventDetailModal;

ZettEventBus.addEventListener('modal:event-detail:open', (e) => {
    openEventDetailModal(e.detail);
});

ZettEventBus.addEventListener('modal:event-detail:close', () => closeEventDetailModal());

window.addEventListener('zettnas:lang-changed', () => {
    if (_eventDetailOverlay && _eventDetailOverlay.classList.contains('open') && _currentEventDetailData) {
        openEventDetailModal(_currentEventDetailData);
    }
    if (!smartOverlay || !smartOverlay.classList.contains('open') || !activeModalType) return;
    openMetricModal(activeModalType);
});

window.closeSmartModal = closeSmartModal;
