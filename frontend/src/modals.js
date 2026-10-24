import { showToast, showConfirmToast } from "./toast.js";
import { state } from "./state.js";
import { ZettEventBus } from './event-bus.js';
import { api } from './api.js';
import { DockManager, bringToFront, makeDraggable } from './components/dock.js';
import { trapFocus, escapeHtml, copyText } from './utils.js';
import { t } from './i18n.js';
import { formatDateTime, formatNumber } from './format.js';
// S.M.A.R.T. & INTERACTIVE METRIC DIAGNOSTIC MODAL CONTROLLER

let activeModalType = null;
let smartOverlay, smartCloseBtn, smartTitle, smartModel, smartSerial, smartHealth, smartHours, smartRaw, smartLbl1, smartLbl2, smartLbl3, smartLbl4, smartRawTitle, smartRefreshBtn;
let _unbindSmartTrap = null;
let _eventDetailOverlay = null;
let _unbindEventDetailTrap = null;
let _currentEventDetailData = null;
let _currentSmartData = null;
let _smartPollTimer = null;
let _smartPollingDev = null;

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
          const dev = activeModalType.replace("disk_", "");
          showToast(t('toast.refreshing_disk_dev', 'Refreshing disk /dev/{dev}...', { dev: dev }), "info");
          openSmartModal(dev, true);
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
    const copyReportBtn = document.getElementById("smart-btn-copy-report");

    async function triggerTest(type) {
      if (!activeModalType || !activeModalType.startsWith("disk_")) return;
      const dev = activeModalType.replace("disk_", "");
      if (testStatus) testStatus.textContent = type === 'abort' ? 'Aborting test...' : `Starting ${type} test...`;
      try {
        if (type === 'abort') {
          stopSmartPolling();
          const res = await api.post("/api/disk/smart_test", { dev, test_type: type });
          if (res && res.success) {
            showToast(t('toast.self_test_aborted_on_dev', 'Self-test aborted on /dev/{dev}', { dev: dev }), "ok");
            updateSmartTestProgressUI({ self_test_progress: { is_aborted: true, percent_completed: 100, in_progress: false } }, type);
          } else {
            showToast(t('toast.failed_to_abort', 'Failed to abort: {result}', { result: res?.error || t('toast.unknown_error', 'Unknown error') }), "error");
          }
          return;
        }

        const res = await api.post("/api/disk/smart_test", { dev, test_type: type });
        if (res && res.success) {
          showToast(t('toast.self_test_started_on_dev', '{type} self-test started on /dev/{dev}', { type: type.toUpperCase(), dev: dev }), "ok");
          const initData = {
            self_test_progress: {
              in_progress: true,
              percent_completed: 0,
              percent_remaining: 100,
              status_text: `Running ${type} self-test...`,
              polling_minutes: res.polling_minutes
            }
          };
          updateSmartTestProgressUI(initData, type);
          startSmartPolling(dev, type);
          if (smartRaw) smartRaw.textContent = `[S.M.A.R.T. Self-Test Action: ${type}]\n${res.output}\n\n` + smartRaw.textContent;
        } else {
          showToast(t('toast.failed', 'Failed: {error}', { error: res?.error || t('toast.unknown_error', 'Unknown error') }), "error");
          if (testStatus) testStatus.textContent = `Failed: ${res?.error || 'Error'}`;
        }
      } catch (err) {
        showToast(t('toast.test_error', 'Test error: {error}', { error: err.message }), "error");
        if (testStatus) testStatus.textContent = t('ui.error', 'Error');
      }
    }

    if (shortTestBtn) shortTestBtn.addEventListener("click", () => triggerTest("short"));
    if (extTestBtn) extTestBtn.addEventListener("click", () => triggerTest("long"));
    if (abortTestBtn) abortTestBtn.addEventListener("click", () => triggerTest("abort"));
    if (copyReportBtn) copyReportBtn.addEventListener("click", copySmartReport);

    // Segmented S.M.A.R.T. Navigation Tabs
    const smartTabs = document.querySelectorAll(".smart-tab-btn");
    smartTabs.forEach((btn) => {
      btn.addEventListener("click", () => {
        switchSmartTab(btn.dataset.tab);
      });
    });

    // Raw Telemetry Search / Filter and Copy
    const rawFilterInput = document.getElementById("smart-raw-filter");
    const copyRawBtn = document.getElementById("smart-btn-copy-raw");
    if (rawFilterInput) {
      rawFilterInput.addEventListener("input", () => {
        const q = rawFilterInput.value.toLowerCase().trim();
        if (!smartRaw || !_currentSmartData || !_currentSmartData.raw) return;
        if (!q) {
          smartRaw.textContent = _currentSmartData.raw;
          return;
        }
        const lines = _currentSmartData.raw.split("\n");
        const matched = lines.filter((l) => l.toLowerCase().includes(q));
        smartRaw.textContent = matched.length > 0 ? matched.join("\n") : `No attributes matched filter "${q}".`;
      });
    }
    if (copyRawBtn) {
      copyRawBtn.addEventListener("click", async () => {
        if (!smartRaw || !smartRaw.textContent) return;
        try {
          await copyText(smartRaw.textContent);
          showToast(t("modal.smart_raw_copied", "Raw SMART attributes copied to clipboard"), "ok");
        } catch {
          showToast(t('toast.failed_to_copy_raw_attributes', "Failed to copy raw attributes"), "error");
        }
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

export function switchSmartTab(tabName) {
  const smartTabs = document.querySelectorAll(".smart-tab-btn");
  smartTabs.forEach((b) => b.classList.toggle("active", b.dataset.tab === tabName));
  document.querySelectorAll(".smart-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === `smart-pane-${tabName}`);
    pane.style.display = ""; // clear inline overrides
  });
}

export function renderSelfTestLog(log) {
  const tbody = document.getElementById("smart-test-history-tbody");
  const empty = document.getElementById("smart-test-history-empty");
  const badge = document.getElementById("smart-test-count-badge");
  const table = document.getElementById("smart-test-history-table");
  if (!tbody) return;

  if (!log || !Array.isArray(log) || log.length === 0) {
    tbody.innerHTML = "";
    if (empty) empty.style.display = "block";
    if (table) table.style.display = "none";
    if (badge) badge.textContent = "0";
    return;
  }

  if (empty) empty.style.display = "none";
  if (table) table.style.display = "table";
  if (badge) badge.textContent = String(log.length);

  const escapeHtml = (str) => {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  };

  tbody.innerHTML = log.map((item) => {
    let pillClass;
    let icon;
    const statusText = item.status || "Unknown";
    const low = statusText.toLowerCase();

    if (item.passed) {
      pillClass = "smart-test-status-passed";
      icon = "✓";
    } else if (low.includes("abort") || low.includes("interrupted") || low.includes("cancelled")) {
      pillClass = "smart-test-status-aborted";
      icon = "⏹";
    } else if (low.includes("in progress") || low.includes("remaining") || low.includes("started")) {
      pillClass = "smart-test-status-running";
      icon = "⏳";
    } else {
      pillClass = "smart-test-status-failed";
      icon = "✗";
    }

    const hours = item.lifetime_hours != null ? `${formatNumber(item.lifetime_hours)} h` : "--";
    const lba = item.lba_first_error || "-";

    return `
      <tr>
        <td style="color: var(--muted); font-weight: 700;">#${escapeHtml(item.num)}</td>
        <td style="font-weight: 600;">${escapeHtml(item.type)}</td>
        <td><span class="smart-test-status-pill ${pillClass}">${icon} ${escapeHtml(statusText)}</span></td>
        <td>${escapeHtml(hours)}</td>
        <td style="color: ${lba !== '-' ? 'var(--crit)' : 'inherit'};">${escapeHtml(lba)}</td>
      </tr>
    `;
  }).join("");
}

export function renderSmartLatestReport(data) {
  const card = document.getElementById("smart-latest-report-card");
  const emptyHero = document.getElementById("smart-empty-hero");
  const badge = document.getElementById("smart-report-badge");
  const meta = document.getElementById("smart-report-meta");
  const lbaEl = document.getElementById("smart-report-lba");
  const tempEl = document.getElementById("smart-report-temp");
  const hoursEl = document.getElementById("smart-report-hours");
  const typeEl = document.getElementById("smart-report-type");
  const recEl = document.getElementById("smart-report-recommendation");
  if (!card) return;

  const report = data?.latest_report;
  const topLog = data?.self_test_log && data.self_test_log.length > 0 ? data.self_test_log[0] : null;

  if (!report && !topLog) {
    card.style.display = "none";
    if (emptyHero) emptyHero.style.display = "flex";
    return;
  }

  if (emptyHero) emptyHero.style.display = "none";
  card.style.display = "flex";

  const passed = report ? report.passed : topLog ? topLog.passed : true;
  const statusStr = report ? report.status : topLog ? topLog.status : "Completed";
  const testType = report ? report.test_type : topLog ? topLog.type : "Self-test";
  const lba = (report ? report.lba_first_error : topLog ? topLog.lba_first_error : "-") || "-";
  const hours = (report ? report.power_on_hours : topLog ? topLog.lifetime_hours : data?.power_on_hours) || "--";
  const temp = report && report.temp_end != null ? `${report.temp_end}°C` : data?.temp != null ? `${data.temp}°C` : "--";

  if (badge) {
    badge.className = "smart-report-badge-pill";
    if (passed) {
      badge.textContent = `✓ ${t("modal.smart_verdict_passed", "PASSED")}`;
    } else if (statusStr.toLowerCase().includes("abort") || statusStr.toLowerCase().includes("cancel")) {
      badge.classList.add("smart-report-badge-warn");
      badge.textContent = `⏹ ${t("modal.smart_verdict_aborted", "ABORTED")}`;
    } else {
      badge.classList.add("smart-report-badge-crit");
      badge.textContent = `✗ ${t("modal.smart_verdict_failed", "FAILED")}`;
    }
  }

  if (meta) {
    const timeStr = report ? formatDateTime(report.ts, undefined, "") : "";
    meta.textContent = `${testType.toUpperCase()} • ${statusStr}${timeStr ? ` • ${timeStr}` : ""}`;
  }

  if (lbaEl) {
    lbaEl.textContent = lba === "-" ? t("modal.smart_zero_defects", "0 Defects Detected") : `Error at LBA ${lba}`;
    lbaEl.style.color = lba === "-" ? "var(--ok, #10b981)" : "var(--crit, #ef4444)";
  }

  if (tempEl) tempEl.textContent = temp;
  if (hoursEl) hoursEl.textContent = hours !== "--" ? `${formatNumber(hours)} h` : "--";
  if (typeEl) typeEl.textContent = testType.charAt(0).toUpperCase() + testType.slice(1);

  if (recEl) {
    let rec = report?.recommendation || "";
    if (!rec) {
      if (passed) {
        rec = t(
          "modal.smart_rec_passed",
          "Drive passed all internal mechanical, magnetic, and electronics checks. Safe for array storage."
        );
      } else {
        rec = t(
          "modal.smart_rec_failed",
          "Critical surface read or media defect detected. Plan immediate backup and drive replacement."
        );
      }
    }
    recEl.textContent = `💡 ${rec}`;
  }
}

export function updateSmartTestProgressUI(data, testType) {
  const progressCard = document.getElementById("smart-progress-card");
  const progressBar = document.getElementById("smart-progress-bar");
  const pctLabel = document.getElementById("smart-progress-pct-label");
  const statusDesc = document.getElementById("smart-progress-status-desc");
  const pulseDot = document.getElementById("smart-progress-pulse");
  const etaLabel = document.getElementById("smart-progress-eta");
  const shortBtn = document.getElementById("smart-btn-short-test");
  const extBtn = document.getElementById("smart-btn-extended-test");
  const abortBtn = document.getElementById("smart-btn-abort-test");
  const testStatus = document.getElementById("smart-test-status");

  if (!progressCard || !progressBar) return;

  const prog = data?.self_test_progress;

  if (prog && prog.in_progress) {
    progressCard.style.display = "flex";
    const pct = Math.max(5, Math.min(99, prog.percent_completed || 0));
    progressBar.style.width = `${pct}%`;
    progressBar.style.background = "linear-gradient(90deg, #0ea5e9, #22c55e)";
    if (pctLabel) pctLabel.textContent = `${prog.percent_completed || 0}%`;
    if (statusDesc) statusDesc.textContent = prog.status_text || t("modal.smart_test_in_progress", "Self-test in progress...");
    if (pulseDot) {
      pulseDot.style.background = "var(--brand, #38bdf8)";
      pulseDot.style.boxShadow = "0 0 10px var(--brand, #38bdf8)";
      pulseDot.style.display = "inline-block";
    }

    if (etaLabel && prog.polling_minutes) {
      const typeKey = (testType === 'long' || testType === 'extended') ? 'extended' : 'short';
      const estMin = prog.polling_minutes[typeKey];
      if (estMin) {
        etaLabel.textContent = `~${estMin} min est.`;
        etaLabel.style.display = "inline";
      } else {
        etaLabel.style.display = "none";
      }
    }

    if (shortBtn) {
      shortBtn.disabled = true;
      shortBtn.style.opacity = "0.5";
      shortBtn.style.cursor = "not-allowed";
    }
    if (extBtn) {
      extBtn.disabled = true;
      extBtn.style.opacity = "0.5";
      extBtn.style.cursor = "not-allowed";
    }
    if (abortBtn) abortBtn.style.display = "inline-block";
    if (testStatus) testStatus.textContent = `Running (${prog.percent_completed || 0}%)`;
  } else if (prog && prog.is_aborted) {
    progressCard.style.display = "flex";
    progressBar.style.width = "100%";
    progressBar.style.background = "linear-gradient(90deg, #f59e0b, #ef4444)";
    if (pctLabel) pctLabel.textContent = t('ui.aborted', 'Aborted');
    if (statusDesc) statusDesc.textContent = t("modal.smart_test_aborted", "Self-test aborted");
    if (pulseDot) {
      pulseDot.style.background = "var(--warn, #f59e0b)";
      pulseDot.style.boxShadow = "none";
    }
    if (etaLabel) etaLabel.style.display = "none";

    if (shortBtn) {
      shortBtn.disabled = false;
      shortBtn.style.opacity = "1";
      shortBtn.style.cursor = "pointer";
    }
    if (extBtn) {
      extBtn.disabled = false;
      extBtn.style.opacity = "1";
      extBtn.style.cursor = "pointer";
    }
    if (abortBtn) abortBtn.style.display = "none";
    if (testStatus) testStatus.textContent = t('ui.test_aborted', 'Test Aborted');
  } else if (prog && prog.percent_completed === 100 && _smartPollingDev) {
    progressCard.style.display = "flex";
    progressBar.style.width = "100%";
    progressBar.style.background = "linear-gradient(90deg, #10b981, #22c55e)";
    if (pctLabel) pctLabel.textContent = t('preview.actual_size', '100%');
    if (statusDesc) statusDesc.textContent = `✓ ${t("modal.smart_test_completed", "Self-test completed successfully")}`;
    if (pulseDot) {
      pulseDot.style.background = "var(--ok, #10b981)";
      pulseDot.style.boxShadow = "0 0 10px var(--ok, #10b981)";
    }
    if (etaLabel) etaLabel.style.display = "none";

    if (shortBtn) {
      shortBtn.disabled = false;
      shortBtn.style.opacity = "1";
      shortBtn.style.cursor = "pointer";
    }
    if (extBtn) {
      extBtn.disabled = false;
      extBtn.style.opacity = "1";
      extBtn.style.cursor = "pointer";
    }
    if (abortBtn) abortBtn.style.display = "none";
    if (testStatus) testStatus.textContent = t('ui.completed', 'Completed');
  } else {
    progressCard.style.display = "none";
    if (shortBtn) {
      shortBtn.disabled = false;
      shortBtn.style.opacity = "1";
      shortBtn.style.cursor = "pointer";
    }
    if (extBtn) {
      extBtn.disabled = false;
      extBtn.style.opacity = "1";
      extBtn.style.cursor = "pointer";
    }
    if (abortBtn) abortBtn.style.display = "none";
    if (testStatus) testStatus.textContent = data?.self_test_status || "";
  }
}

export function stopSmartPolling() {
  if (_smartPollTimer) {
    clearInterval(_smartPollTimer);
    _smartPollTimer = null;
  }
  _smartPollingDev = null;
}

export function startSmartPolling(devName, testType = 'short') {
  stopSmartPolling();
  _smartPollingDev = devName;
  if (!activeModalType) activeModalType = "disk_" + devName;

  _smartPollTimer = setInterval(async () => {
    if (!smartOverlay) smartOverlay = document.getElementById("smart-modal-overlay");
    if (!smartOverlay || !smartOverlay.classList.contains("open") || (activeModalType && activeModalType !== "disk_" + devName)) {
      stopSmartPolling();
      return;
    }
    try {
      const res = await api.request(`/api/disk_detail?dev=${encodeURIComponent(devName)}`);
      if (!res.ok) return;
      const data = await res.json();
      _currentSmartData = data;

      if (smartRaw && data.raw) smartRaw.textContent = data.raw;
      renderSelfTestLog(data.self_test_log);
      renderSmartLatestReport(data);
      updateSmartTestProgressUI(data, testType);

      if (!data.self_test_progress?.in_progress) {
        const isAborted = Boolean(data.self_test_progress?.is_aborted);
        stopSmartPolling();
        if (isAborted) {
          showToast(t("modal.smart_test_aborted", `Self-test aborted on /dev/${devName}`), "warn");
        } else {
          showToast(t("modal.smart_test_completed", `Self-test completed on /dev/${devName}`), "ok");
        }
      }
    } catch (err) {
      console.warn("SMART polling tick error:", err);
    }
  }, 3000);
}

export function generateSmartReportMarkdown(data) {
  if (!data) return "No S.M.A.R.T. data available.";
  if (data.latest_report && data.latest_report.report_markdown) {
    return data.latest_report.report_markdown;
  }
  const dev = data.dev || "unknown";
  const model = data.model || "Unknown";
  const serial = data.serial || "Unknown";
  const health = data.health || "UNKNOWN";
  const hours = data.power_on_hours != null ? `${data.power_on_hours} hrs` : "Unknown";
  const temp = data.temp != null ? `${data.temp}°C` : "N/A";
  const status = data.self_test_status || "N/A";
  const generatedAt = new Date().toISOString();

  let md = `# S.M.A.R.T. Diagnostic Report: /dev/${dev}\n`;
  md += `**Generated**: ${generatedAt}\n\n`;
  md += `## Device Telemetry\n`;
  md += `- **Device Node**: \`/dev/${dev}\`\n`;
  md += `- **Drive Model**: ${model}\n`;
  md += `- **Serial Number**: ${serial}\n`;
  md += `- **Health Assessment**: **${health}**\n`;
  md += `- **Operating Temperature**: ${temp}\n`;
  md += `- **Power-On Lifetime**: ${hours}\n`;
  md += `- **Latest Self-Test Status**: ${status}\n\n`;

  if (data.nvme_endurance) {
    const nv = data.nvme_endurance;
    md += `## NVMe Solid-State Endurance\n`;
    if (nv.tbw_tb != null) md += `- **Total Bytes Written (TBW)**: ${nv.tbw_tb} TB\n`;
    if (nv.tbr_tb != null) md += `- **Total Bytes Read (TBR)**: ${nv.tbr_tb} TB\n`;
    if (nv.percentage_used != null) md += `- **Wear Indicator**: ${nv.percentage_used}%\n`;
    if (nv.available_spare != null) md += `- **Available Spare**: ${nv.available_spare}%\n`;
    md += `\n`;
  }

  if (data.degradation) {
    const deg = data.degradation;
    md += `## SMART Velocity & Degradation Analysis\n`;
    md += `- **Status**: ${deg.status ? deg.status.toUpperCase() : 'UNKNOWN'}\n`;
    md += `- **Reallocated Sectors (7d Delta)**: +${deg.realloc_7d_delta || 0}\n`;
    if (deg.recommendation) md += `- **Recommendation**: ${deg.recommendation}\n`;
    md += `\n`;
  }

  const log = data.self_test_log || [];
  md += `## Self-Test Results History (${log.length} Records)\n`;
  if (log.length > 0) {
    md += `| # | Test Type | Status / Result | Lifetime Hours | First Error LBA |\n`;
    md += `|---|-----------|-----------------|----------------|-----------------|\n`;
    log.forEach((e) => {
      const eHours = e.lifetime_hours != null ? `${e.lifetime_hours} h` : "-";
      md += `| ${e.num} | ${e.type} | ${e.status} | ${eHours} | ${e.lba_first_error || '-'} |\n`;
    });
  } else {
    md += `*No historical self-test logs recorded on this drive.*\n`;
  }

  return md;
}

export async function copySmartReport() {
  if (!_currentSmartData) {
    showToast(t('toast.no_smart_data_to_export', "No SMART data to export"), "warn");
    return;
  }
  const reportText = generateSmartReportMarkdown(_currentSmartData);
  try {
    await copyText(reportText);

    const btn = document.getElementById("smart-btn-copy-report");
    const icon = document.getElementById("smart-copy-report-icon");
    const label = document.getElementById("smart-copy-report-label");
    if (icon) icon.textContent = "✓";
    if (label) label.textContent = t("modal.smart_report_copied", "Report Copied!");
    if (btn) {
      btn.style.borderColor = "var(--ok2, #10b981)";
      btn.style.color = "var(--ok2, #10b981)";
    }
    showToast(t("modal.smart_report_copied", "SMART report copied to clipboard"), "ok");
    setTimeout(() => {
      if (icon) icon.textContent = "📋";
      if (label) label.textContent = t("modal.smart_copy_report", "Copy Report");
      if (btn) {
        btn.style.borderColor = "rgba(56, 189, 248, 0.3)";
        btn.style.color = "#38bdf8";
      }
    }, 2000);
  } catch (err) {
    console.warn("Failed to copy SMART report:", err);
    showToast(t('toast.failed_to_copy_report', "Failed to copy report"), "error");
  }
}

let _smartFetchController = null;

async function openSmartModal(devName, forceWake = false) {
  if (!devName) return;

  if (!forceWake) {
    const disks = state?.latestStats?.disks || _latestStats?.disks || [];
    const diskData = disks.find((d) => (d.dev || d.name) === devName || d.name === devName || d.dev === devName);
    const isStandby = Boolean(diskData?.standby || diskData?.health === 'standby');
    if (isStandby) {
      const diskLabel = diskData?.model ? `${diskData.model} (/dev/${devName})` : `/dev/${devName}`;
      showConfirmToast(
        'Drive in Standby Mode',
        `Disk ${diskLabel} is currently sleeping. Querying S.M.A.R.T. diagnostics will wake the drive, spinning up platters and consuming power. Do you wish to proceed and wake it?`,
        () => {
          showToast(t('toast.waking_disk_dev', 'Waking disk /dev/{devName}...', { devName: devName }), 'info');
          openSmartModal(devName, true);
        }
      );
      return;
    }
  }

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

  switchSmartTab("health");
  const navTabs = document.getElementById("smart-nav-tabs");
  if (navTabs) navTabs.style.display = "flex";
  const rawFilterWrap = document.querySelector(".smart-raw-toolbar");
  if (rawFilterWrap) rawFilterWrap.style.display = "flex";
  const rawFilterInput = document.getElementById("smart-raw-filter");
  if (rawFilterInput) rawFilterInput.value = "";

  if (smartTitle) smartTitle.innerHTML = `<svg class="ic"><use href="#i-disk"/></svg> ${t('modal.diag_title', 'S.M.A.R.T. Diagnostics')} • /dev/${escapeHtml(devName)}`;
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
    const wakeParam = forceWake ? '&wake=true' : '';
    const res = await api.request(`/api/disk_detail?dev=${encodeURIComponent(devName)}${wakeParam}`, { signal: _smartFetchController.signal });
    if (res.ok) {
      const data = await res.json();
      _currentSmartData = data;
      const isStandby = Boolean(data.is_standby || data.health === "STANDBY");
      const standbyBanner = document.getElementById("smart-standby-banner");
      if (standbyBanner) {
        if (isStandby) {
          standbyBanner.style.display = "flex";
          const wakeBtn = document.getElementById("smart-btn-wake-modal");
          if (wakeBtn && !wakeBtn.dataset.bound) {
            wakeBtn.dataset.bound = "1";
            wakeBtn.addEventListener("click", () => {
              showToast(t('toast.waking_disk_dev', 'Waking disk /dev/{devName}...', { devName: devName }), "info");
              openSmartModal(devName, true);
            });
          }
        } else {
          standbyBanner.style.display = "none";
        }
      }
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
      renderSelfTestLog(data.self_test_log);
      renderSmartLatestReport(data);
      updateSmartTestProgressUI(data);

      if (data.self_test_progress && data.self_test_progress.in_progress) {
        startSmartPolling(devName);
      } else {
        stopSmartPolling();
      }

      if (smartHours) smartHours.textContent = data.power_on_hours || "Unknown";
      if (smartRaw) smartRaw.textContent = data.raw || "No raw output.";

      const degBanner = document.getElementById("smart-degradation-banner");
      let locateDisk = null;
      if (degBanner) {
        let bannerHtml = '';
        if (data.nvme_endurance) {
          const nv = data.nvme_endurance;
          const tbw = nv.tbw_tb != null ? `${nv.tbw_tb} TB` : '--';
          const tbr = nv.tbr_tb != null ? `${nv.tbr_tb} TB` : '--';
          const wear = nv.percentage_used != null ? `${nv.percentage_used}%` : '--';
          const spare = nv.available_spare != null ? `${nv.available_spare}%` : '--';
          bannerHtml += `
            <div style="display: flex; gap: 12px; margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-color);">
              <span>💾 <strong>TBW:</strong> ${tbw}</span>
              <span>📖 <strong>TBR:</strong> ${tbr}</span>
              <span>⚡ <strong>Wear:</strong> ${wear}</span>
              <span>🛡️ <strong>Spare:</strong> ${spare}</span>
            </div>
          `;
        }
        if (data.degradation) {
          // The chassis visualizer (~100 kB) loads with the first disk report, not the page (PERF-5)
          const { generateSmartSparklineSvg, triggerLocateDisk } = await import('./components/chassis-visualizer.js');
          locateDisk = triggerLocateDisk;
          const deg = data.degradation;
          const color = deg.status === 'critical' ? 'var(--crit)' : deg.status === 'warning' ? 'var(--warn)' : 'var(--ok)';
          const icon = deg.status === 'critical' ? '⚠️' : deg.status === 'warning' ? '⏳' : '🛡️';

          let sparklineHtml = '';
          if (deg.sparkline_points && deg.sparkline_points.length > 0) {
            sparklineHtml = `
              <div style="margin-top: 8px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase;">
                  <span>30-Day Degradation Sparkline</span>
                  <span>Rate: ${deg.realloc_7d_delta > 0 ? '+' + deg.realloc_7d_delta + ' / 7d' : 'STABLE'}</span>
                </div>
                ${generateSmartSparklineSvg(deg.sparkline_points, 320, 44)}
              </div>
            `;
          }

          bannerHtml += `
            <div style="display: flex; align-items: flex-start; gap: 8px;">
              <span style="font-size: 14px;">${icon}</span>
              <div style="flex: 1;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <div style="font-weight: 700; color: ${color}; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px;">
                    ${escapeHtml(deg.status.replace('_', ' '))} • SMART Velocity Analysis
                  </div>
                  <button id="smart-btn-locate-drive" style="background:rgba(56, 189, 248, 0.12); border:1px solid rgba(56, 189, 248, 0.35); color:#38bdf8; border-radius:4px; padding:2px 8px; cursor:pointer; font-weight:600; font-size:11px; display:flex; align-items:center; gap:4px;">
                    <svg viewBox="0 0 24 24" width="10" height="10"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor"/></svg>
                    LOCATE
                  </button>
                </div>
                <div style="color: var(--text-secondary); margin-top: 2px;">
                  ${escapeHtml(deg.recommendation || '')}
                </div>
                ${sparklineHtml}
              </div>
            </div>
          `;
        }
        if (bannerHtml) {
          degBanner.innerHTML = bannerHtml;
          degBanner.style.display = 'block';
          const locateBtn = degBanner.querySelector('#smart-btn-locate-drive');
          if (locateBtn) {
            locateBtn.addEventListener('click', (e) => {
              e.stopPropagation();
              if (locateDisk) locateDisk(devName, modalWin);
            });
          }
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

export function closeSmartModal() {
  activeModalType = null;
  stopSmartPolling();
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
    if (typeof e.detail === 'object' && e.detail !== null) {
        openSmartModal(e.detail.dev, Boolean(e.detail.forceWake));
    } else {
        openSmartModal(e.detail, false);
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
    actionLabel = t("event_detail.action_smart", "Inspect S.M.A.R.T.");
    actionFn = () => {
      closeEventDetailModal();
      const dev = ev.details?.dev || (searchStr.match(/\b(sd[a-z]|nvme\d+n\d+)\b/) || [])[1];
      if (dev && typeof openSmartModal === "function") {
        openSmartModal(dev, true).then(() => {
          if (typeof switchSmartTab === "function") {
            switchSmartTab("selftest");
          }
        });
        return;
      }
      if (typeof window.openManagementWindow === "function") {
        window.openManagementWindow("mgmt-pane-unraid");
      } else if (typeof openSmartModal === "function") {
        openSmartModal();
      }
    };
  }
  // 8. Docker Containers
  else if (/\bdocker\b|\bcontainers?\b|compose|cgroup/.test(searchStr)) {
    subsystem = "DOCKER CONTAINERS";
    actionLabel = t("event_detail.action_docker", "Open Container Telemetry");
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
    if (activeModalType.startsWith('disk_')) {
        const devName = activeModalType.replace('disk_', '');
        if (smartTitle) smartTitle.innerHTML = `<svg class="ic"><use href="#i-disk"/></svg> ${t('modal.diag_title', 'S.M.A.R.T. Diagnostics')} • /dev/${escapeHtml(devName)}`;
        if (smartLbl1) smartLbl1.textContent = t('modal.smart_device_model', "DEVICE & MODEL");
        if (smartLbl2) smartLbl2.textContent = t('modal.smart_serial_metric', "SERIAL NUMBER");
        if (smartLbl3) smartLbl3.textContent = t('modal.smart_health_status', "HEALTH STATUS");
        if (smartLbl4) smartLbl4.textContent = t('modal.smart_hours_readout', "POWER-ON HOURS");
        if (smartRawTitle) smartRawTitle.textContent = t('modal.smart_raw_telemetry', "RAW SMART ATTRIBUTES");
        const copyReportLabel = document.getElementById("smart-copy-report-label");
        if (copyReportLabel) copyReportLabel.textContent = t('modal.smart_copy_report', "Copy Report");
        if (_currentSmartData) {
          renderSelfTestLog(_currentSmartData.self_test_log);
          updateSmartTestProgressUI(_currentSmartData);
        }
    } else {
        openMetricModal(activeModalType);
    }
});

window.openSmartModal = openSmartModal;
window.closeSmartModal = closeSmartModal;
export { openSmartModal };
