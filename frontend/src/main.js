import './style.css';
import { ZettEventBus } from './event-bus.js';
import { showToast, showConfirmToast } from './toast.js';
import './folder-browser.js';
import './modals.js';


let _metricsChart = null;
let _metricsRange = "24h";

async function fetchAndRenderMetrics() {
  if (_metricsChart) _metricsChart.destroy();
  try {
    const res = await fetch("/api/history?range=" + _metricsRange);
    const data = await res.json();
    if (!data || data.length === 0) return;
    
    const labels = data.map(d => {
      const dt = new Date(d.ts * 1000);
      if (_metricsRange === "24h") {
          return dt.getHours().toString().padStart(2, '0') + ':' + dt.getMinutes().toString().padStart(2, '0');
      } else {
          return (dt.getMonth()+1) + '/' + dt.getDate() + ' ' + dt.getHours().toString().padStart(2, '0') + ':00';
      }
    });
    
    const cpuTemps = data.map(d => d.cpu_temp);
    const cpuUtils = data.map(d => d.cpu_util);
    const memPcts = data.map(d => d.mem_pct);
    
    const ctx = document.getElementById("metricsChart").getContext("2d");
    
    Chart.defaults.color = "#a0aec0";
    Chart.defaults.font.family = "Inter, sans-serif";
    
    _metricsChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'CPU Temp (°C)',
            data: cpuTemps,
            borderColor: '#e74c3c',
            backgroundColor: 'rgba(231, 76, 60, 0.1)',
            borderWidth: 2,
            tension: 0.3,
            fill: true,
            pointRadius: 0
          },
          {
            label: 'CPU Util (%)',
            data: cpuUtils,
            borderColor: '#3498db',
            borderWidth: 2,
            tension: 0.3,
            pointRadius: 0
          },
          {
            label: 'Mem (%)',
            data: memPcts,
            borderColor: '#9b59b6',
            borderWidth: 2,
            tension: 0.3,
            pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 10, usePointStyle: true, font: { size: 10 } } }
        },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { maxTicksLimit: 8 } },
          y: { grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true, max: 100 }
        }
      }
    });
  } catch (e) {
    console.error("Failed to load metrics:", e);
  }
}

let copyToastMinimized = false;
// Instant detection for headless Chromium renderer
const isLcdDirect = window.location.search.includes("mode=lcd") || document.body.classList.contains("lcd-direct");
if (isLcdDirect) {
  document.body.classList.add("lcd-direct");
}

// Polls /api/stats and updates the 640x172 dashboard with gauges, icons,
// color thresholds and RPM-driven fan animation.

// ---- FAN CURVE SHARED STATE (accessible by both top-level and IIFE functions) ----
let curvePoints = [[30, 32], [37, 32], [50, 100], [60, 100]];
let isDraggingCurve = false;
let dragIndex = -1;
let _curveInitialized = false;
let _lastCurveSaveTime = 0; // timestamp: ignore server curve updates for 5s after user edit

function tempToX(t) { return 38 + ((Math.max(30, Math.min(60, t)) - 30) / 30) * (285 - 38); }
function xToTemp(x) { return Math.round(30 + ((x - 38) / (285 - 38)) * 30); }
function pctToY(p) { return 100 - (Math.max(0, Math.min(100, p)) / 100) * (100 - 20); }
function yToPct(y) { return Math.round(100 - ((y - 20) / (100 - 20)) * 100); }

function renderCurveLines() {
  try {
    const curveArea = document.getElementById("curve-area-path");
    const curveLine = document.getElementById("curve-svg-path");
    if (!curveArea || !curveLine) return;

    const pts = curvePoints.slice().sort((a, b) => a[0] - b[0]);
    let d = `M 38 100 L 38 ${pctToY(pts[0][1]).toFixed(1)}`;
    for (const p of pts) {
      d += ` L ${tempToX(p[0]).toFixed(1)} ${pctToY(p[1]).toFixed(1)}`;
    }
    d += ` L 285 ${pctToY(pts[pts.length - 1][1]).toFixed(1)}`;

    curveLine.setAttribute("d", d);
    curveArea.setAttribute("d", d + " L 285 100 Z");

    for (let i = 0; i < 4; i++) {
      const h = document.getElementById("ch-" + i);
      if (h && pts[i]) {
        h.setAttribute("cx", tempToX(pts[i][0]).toFixed(1));
        h.setAttribute("cy", pctToY(pts[i][1]).toFixed(1));
      }
    }
  } catch (err) {
    console.error("renderCurveLines error:", err);
  }
}
// ---- END FAN CURVE SHARED STATE ----

const $ = (id) => document.getElementById(id);



const FAN_LABELS = ["D1", "D2", "CPU", "SYS"];

// Shared local client state
let clockFormat = "24";
let currentTimezone = "America/New_York";
let latestStats = null;

let activeLayoutVersion = 0;
let isDraggingPreview = false;
let currentTheme = localStorage.getItem("lcd_theme") || "cyber";

// Zone isolation filter for Fan Curve ("all" | "zone1" | "zone2" | "cpu")
let selectedZoneFilter = "all";

function getLocalClock(tz, fmt) {
  try {
    const formatter = new Intl.DateTimeFormat([], {
      timeZone: tz || "America/New_York",
      hour: "numeric",
      minute: "2-digit",
      hour12: fmt === "12"
    });
    return formatter.format(new Date());
  } catch (e) {
    const d = new Date();
    return d.toTimeString().slice(0, 5);
  }
}

// ---- threshold helpers: return 'ok' | 'warn' | 'crit' ----
const lvlDisk   = (t) => t == null ? "ok" : t >= 60 ? "crit" : t >= 50 ? "warn" : "ok";
const lvlCpu    = (t) => t == null ? "ok" : t >= 85 ? "crit" : t >= 70 ? "warn" : "ok";
const lvlUtil   = (u) => u >= 90 ? "crit" : u >= 75 ? "warn" : "ok";
const lvlFull   = (p) => p >= 90 ? "crit" : p >= 75 ? "warn" : "ok";
const cssVar    = (lvl) => lvl === "crit" ? "var(--crit)" : lvl === "warn" ? "var(--warn)" : "var(--ok)";

function setArc(el, pct, lvl) {
  if (!el) return;
  el.style.setProperty("--pct", Math.max(0, Math.min(100, pct)));
  el.style.setProperty("--c", cssVar(lvl));
}

function renderFans(fans) {
  const rows = document.querySelectorAll(".fan-row");
  if (rows.length === 0) return;

  if (!fans || fans.length === 0) {
    rows.forEach((r) => {
      r.innerHTML = '<span class="fv" style="color:var(--muted);font-size:11px">n/a</span>';
    });
    return;
  }

  const max = Math.max(...fans, 1);
  const count = fans.length;

  rows.forEach((r) => {
    r.classList.toggle("three-fans", count >= 3);
    r.classList.toggle("four-fans", count >= 4);

    const existing = r.querySelectorAll(".fan");

    // Rebuild only if fan count changed
    if (existing.length !== count) {
      const html = fans.map((rpm, i) => {
        const dur = rpm > 0 ? Math.max(0.25, 2.0 - (rpm / max) * 1.7).toFixed(2) : 0;
        const label = FAN_LABELS[i] || ("F" + (i + 1));
        return (
          `<div class="fan">` +
          `<svg class="fan-ic${rpm > 0 ? " spin" : ""}" style="--dur:${dur}s"><use href="#i-fan"/></svg>` +
          `<span class="fv">${rpm}</span>` +
          `<span class="fl">${label}</span>` +
          `</div>`
        );
      }).join("");
      r.innerHTML = html;
    } else {
      // Keyed diff: update only changed values, preserve animation continuity
      fans.forEach((rpm, i) => {
        const fanEl = existing[i];
        if (!fanEl) return;
        const dur = rpm > 0 ? Math.max(0.25, 2.0 - (rpm / max) * 1.7).toFixed(2) : 0;
        const ic = fanEl.querySelector(".fan-ic");
        const fv = fanEl.querySelector(".fv");
        if (fv && fv.textContent !== String(rpm)) fv.textContent = rpm;
        if (ic) {
          const wantSpin = rpm > 0;
          const hasSpin = ic.classList.contains("spin");
          if (wantSpin !== hasSpin) ic.classList.toggle("spin", wantSpin);
          // Only update --dur when it changes meaningfully (>5% change)
          const curDur = parseFloat(ic.style.getPropertyValue("--dur") || "0");
          if (Math.abs(curDur - parseFloat(dur)) > 0.03) {
            ic.style.setProperty("--dur", `${dur}s`);
          }
        }
      });
    }
  });

  fans.forEach((rpm, i) => {
    const dur = rpm > 0 ? Math.max(0.25, 2.0 - (rpm / max) * 1.7).toFixed(2) : 0;
    const dfRpm = $(`df-rpm-${i}`);
    const dfIc = $(`df-ic-${i}`);
    if (dfRpm) dfRpm.textContent = rpm;
    if (dfIc) {
      dfIc.style.setProperty("--dur", `${dur}s`);
      dfIc.classList.toggle("spin", rpm > 0);
    }
  });
}


const ROLE_META = {
  data:  { label: "DATA",  icon: "#i-disk", cls: "r-data" },
  cache: { label: "CACHE", icon: "#i-nvme", cls: "r-cache" },
  os:    { label: "OS",    icon: "#i-nvme", cls: "r-os" },
};

function diskTile(d) {
  const isStandby = Boolean(d.standby || d.health === "standby");
  const lvl = isStandby ? "standby" : (d.health || lvlDisk(d.temp));
  const t = d.temp;
  const meta = ROLE_META[d.role] || ROLE_META.data;
  const w = isStandby ? 0 : (t == null ? 0 : Math.max(8, Math.min(100, ((t - 20) / 40) * 100)));
  const el = document.createElement("div");
  el.className = "disk " + meta.cls + " h-" + lvl + (d.active ? " io-active" : "") + (isStandby ? " disk-standby" : "");
  el.dataset.dev = d.dev || d.name;
  el.title = isStandby ? `${d.name} is in standby (spun-down)` : `Click to inspect S.M.A.R.T. health for ${d.name}`;
  
  const tempHtml = isStandby
    ? `<div class="dt s-standby"><span class="standby-badge">STANDBY</span></div>`
    : `<div class="dt ${"s-" + lvl}">${t == null ? "--" : t}<span class="u">°C</span></div>`;

  el.innerHTML =
    `<div class="dh"><svg class="disk-ic"><use href="${meta.icon}"/></svg>` +
    `<span class="dn">${d.name}</span>` +
    `<div class="disk-indicators">` +
      (isStandby ? `<span class="standby-zzz" title="Spun-down / Standby">zZz</span>` : `<span class="io-dot" title="Active I/O"></span>`) +
      `<span class="hdot ${"dot-" + lvl}"></span>` +
    `</div></div>` +
    tempHtml +
    `<div class="db"><i class="${"bg-" + lvl}" style="width:${w}%"></i></div>`;
  
  el.addEventListener("click", () => {
    if (isStandby) {
      showConfirmToast(
        "Drive in Standby Mode", 
        `Disk ${d.name} is currently sleeping. Querying S.M.A.R.T. data will wake it up, causing mechanical wear and consuming power. Are you sure you want to wake it?`,
        () => ZettEventBus.dispatchEvent(new CustomEvent('modal:smart:open', {detail: d.dev || d.name}))
      );
    } else {
      ZettEventBus.dispatchEvent(new CustomEvent('modal:smart:open', {detail: d.dev || d.name}));
    }
  });
  return el;
}

function renderDisks(disks) {
  const row = $("diskRow");
  if (!row) return;
  const total = disks.length || 1;
  row.classList.toggle("compact", total >= 7);

  // Check if structure changed (different disk count or devs)
  const existingDevs = Array.from(row.querySelectorAll("[data-dev]")).map(el => el.dataset.dev);
  const newDevs = disks.map(d => d.dev || d.name);
  const structureChanged = existingDevs.length !== newDevs.length || existingDevs.some((d, i) => d !== newDevs[i]);

  if (structureChanged) {
    // Full rebuild needed
    row.innerHTML = "";
    const order = ["os", "data", "cache"];
    const groups = order
      .map((r) => ({ role: r, items: disks.filter((d) => d.role === r) }))
      .filter((g) => g.items.length);
    const isYak = (currentTheme === "yak");
    groups.forEach((g, gi) => {
      const meta = ROLE_META[g.role];
      const grp = document.createElement("div");
      grp.className = "disk-group " + meta.cls;
      grp.dataset.role = g.role;
      grp.style.setProperty("--n", g.items.length);
      const lab = document.createElement("div");
      lab.className = "group-label";
      let roleLabel = meta.label;
      if (isYak) {
        if (g.role === "data") roleLabel = "PARCELS";
        else if (g.role === "cache") roleLabel = "EXPRESS";
        else if (g.role === "os") roleLabel = "LOGISTICS";
      }
      lab.innerHTML = `<svg class="grp-ic"><use href="${meta.icon}"/></svg>${roleLabel}`;
      grp.appendChild(lab);
      const tiles = document.createElement("div");
      tiles.className = "group-tiles";
      tiles.style.setProperty("--n", g.items.length);
      g.items.forEach((d) => tiles.appendChild(diskTile(d)));
      grp.appendChild(tiles);
      row.appendChild(grp);
      if (gi < groups.length - 1) {
        const div = document.createElement("div");
        div.className = "group-div";
        row.appendChild(div);
      }
    });
  } else {
    // Fast path: update existing tiles in place
    disks.forEach((d) => {
      const devId = d.dev || d.name;
      const tile = row.querySelector(`[data-dev="${devId}"]`);
      if (!tile) return;
      const nameEl = tile.querySelector(".disk-name");
      const tempEl = tile.querySelector(".disk-temp");
      if (nameEl) nameEl.textContent = d.name;
      if (tempEl) {
        if (d.standby) {
          tempEl.textContent = "zZz";
          tempEl.style.color = "#78838f";
        } else if (d.temp !== null && d.temp !== undefined) {
          tempEl.textContent = d.temp + "°";
          tempEl.style.color = "";
        } else {
          tempEl.textContent = "--";
          tempEl.style.color = "";
        }
      }
      // Update health class
      tile.classList.toggle("h-warn", d.health === "warn");
      tile.classList.toggle("h-crit", d.health === "crit");
      tile.classList.toggle("standby", !!d.standby);
      // Update active IO indicator
      const ioEl = tile.querySelector(".disk-io");
      if (ioEl) ioEl.classList.toggle("io-active", !!d.active);
    });
  }
}

// S.M.A.R.T. & INTERACTIVE METRIC DIAGNOSTIC MODAL CONTROLLER

// Bind click handlers ONLY on the main dashboard console screen via EventBus
$("screen").querySelectorAll(".card-storage").forEach((el) => el.addEventListener("click", () => ZettEventBus.dispatchEvent(new CustomEvent('modal:metric:open', {detail: "storage"}))));
$("screen").querySelectorAll(".card-cpu").forEach((el) => el.addEventListener("click", () => ZettEventBus.dispatchEvent(new CustomEvent('modal:metric:open', {detail: "cpu"}))));
$("screen").querySelectorAll(".card-mem").forEach((el) => el.addEventListener("click", () => ZettEventBus.dispatchEvent(new CustomEvent('modal:metric:open', {detail: "mem"}))));
$("screen").querySelectorAll(".card-fans").forEach((el) => el.addEventListener("click", () => ZettEventBus.dispatchEvent(new CustomEvent('modal:metric:open', {detail: "fans"}))));

$("screen").querySelectorAll(".card-net").forEach((el) => el.addEventListener("click", () => ZettEventBus.dispatchEvent(new CustomEvent('modal:metric:open', {detail: "net"}))));

let anyWarn = false;

function updateRowTelemetryBadges(s) {
  if (!s) return;
  const stBadge = $("telemetry-badge-storage");
  const cpuBadge = $("telemetry-badge-cpu");
  const memBadge = $("telemetry-badge-mem");
  const fanBadge = $("telemetry-badge-fans");
  const netBadge = $("telemetry-badge-net");
  const dskBadge = $("telemetry-badge-disks");

  if (stBadge && s.storage) stBadge.textContent = `${s.storage.pct}% • ${s.storage.used}`;
  if (cpuBadge && s.cpu) cpuBadge.textContent = `${s.cpu.temp}°C • ${s.cpu.util}%`;
  if (memBadge && s.mem) memBadge.textContent = `${s.mem.pct}% • ${s.mem.used_gb}G`;
  if (fanBadge && s.fans && s.fans.length) fanBadge.textContent = `${s.fans[0] || 0} / ${s.fans[1] || 0} RPM`;
  if (netBadge && s.net) netBadge.textContent = `${s.net.tx} / ${s.net.rx}`;
  if (dskBadge && s.disks) dskBadge.textContent = `${s.disks.length} Drives Online`;
}

function updateFanCurveWorkstation(s) {
  if (!s || !s.fan_control) return;
  const fc = s.fan_control;

  if ($("zp-z1-temp")) $("zp-z1-temp").textContent = `${fc.zone1_temp}°C`;
  if ($("zp-z1-pwm")) $("zp-z1-pwm").textContent = `PWM: ${fc.zone1_pwm}`;
  if ($("zp-z2-temp")) $("zp-z2-temp").textContent = `${fc.zone2_temp}°C`;
  if ($("zp-z2-pwm")) $("zp-z2-pwm").textContent = `PWM: ${fc.zone2_pwm}`;
  if ($("zp-cpu-temp")) $("zp-cpu-temp").textContent = `${fc.cpu_temp}°C`;
  if ($("zp-cpu-pwm")) $("zp-cpu-pwm").textContent = fc.ctrl_cpu_fan ? `PWM: ${fc.cpu_pwm}` : `BIOS Auto`;

  const hBadge = $("hysteresis-badge");
  if (hBadge) {
    if (fc.disk_hold_remaining > 0) {
      hBadge.textContent = `HOLD: ACTIVE (${fc.disk_hold_remaining}s)`;
      hBadge.style.background = "rgba(245,183,49,0.15)";
      hBadge.style.color = "var(--warn)";
      hBadge.style.borderColor = "rgba(245,183,49,0.4)";
    } else if (fc.ctrl_cpu_fan && fc.cpu_hold_remaining > 0) {
      hBadge.textContent = `CPU HOLD (${fc.cpu_hold_remaining}s)`;
      hBadge.style.background = "rgba(245,183,49,0.15)";
      hBadge.style.color = "var(--warn)";
      hBadge.style.borderColor = "rgba(245,183,49,0.4)";
    } else {
      hBadge.textContent = `HOLD: READY`;
      hBadge.style.background = "rgba(51,209,122,0.15)";
      hBadge.style.color = "var(--ok)";
      hBadge.style.borderColor = "rgba(51,209,122,0.35)";
    }
  }


  const graphMinT = 30;
  const graphMaxT = 60;
  const tSpan = 30;


  // Skip curve updates while user is actively dragging, or within 5s of a save
  // (the backend daemon may still be serving stale cached curve_points)
  const curveUpdateCooldown = (Date.now() - _lastCurveSaveTime) < 5000;
  
  if (!isDraggingCurve && !curveUpdateCooldown) {
    console.log("[ZettNAS] Checking curve update. server points:", fc.curve_points, "local points:", JSON.stringify(curvePoints), "_curveInitialized:", _curveInitialized);
    if (fc.curve_points && fc.curve_points.length > 0) {
      if (JSON.stringify(curvePoints) !== JSON.stringify(fc.curve_points)) {
        console.log("[ZettNAS] Overwriting local curve with server curve:", fc.curve_points);
        curvePoints = fc.curve_points;
      }
      _curveInitialized = true;
    } else if (!_curveInitialized) {
      const tMin = fc.temp_min || 37;
      const tMax = fc.temp_max || 50;
      curvePoints = [[30, 32], [tMin, 32], [tMax, 100], [60, 100]];
      console.log("[ZettNAS] Initialized default curve:", curvePoints);
      _curveInitialized = true;
    }
  } else if (curveUpdateCooldown) {
      console.log("[ZettNAS] In cooldown. Ignoring server curve.");
  }
  
  renderCurveLines();



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

  const dotZ1 = $("curve-dot-z1");
  const dotZ2 = $("curve-dot-z2");
  const dotCpu = $("curve-dot-cpu");

  if (dotZ1) {
    dotZ1.setAttribute("cx", svgZ1X);
    dotZ1.setAttribute("cy", svgZ1Y);
    dotZ1.style.display = (selectedZoneFilter === "all" || selectedZoneFilter === "zone1") ? "block" : "none";
  }

  if (dotZ2) {
    dotZ2.setAttribute("cx", svgZ2X);
    dotZ2.setAttribute("cy", svgZ2Y);
    dotZ2.style.display = (selectedZoneFilter === "all" || selectedZoneFilter === "zone2") ? "block" : "none";
  }

  if (dotCpu) {
    dotCpu.setAttribute("cx", svgCpuX);
    dotCpu.setAttribute("cy", svgCpuY);
    dotCpu.style.display = (selectedZoneFilter === "all" || selectedZoneFilter === "cpu") ? "block" : "none";
  }

  const readout = $("curve-readout-text");
  if (readout) {
    if (selectedZoneFilter === "zone1") {
      readout.textContent = `Zone 1 Isolated: ${fc.zone1_temp}°C (${fc.zone1_pwm} PWM)`;
    } else if (selectedZoneFilter === "zone2") {
      readout.textContent = `Zone 2 Isolated: ${fc.zone2_temp}°C (${fc.zone2_pwm} PWM)`;
    } else if (selectedZoneFilter === "cpu") {
      readout.textContent = `CPU Isolated: ${fc.cpu_temp}°C (${fc.cpu_pwm || 'Auto'} PWM)`;
    } else {
      const maxDisk = Math.max(fc.zone1_temp, fc.zone2_temp);
      readout.textContent = `All Zones: Max Bay ${maxDisk}°C`;
    }
  }
}

function setZoneFilter(filterKey) {
  selectedZoneFilter = filterKey;

  const colZ1 = $("fan-col-zone1");
  const colZ2 = $("fan-col-zone2");
  const colCpu = $("fan-col-cpu");
  const btnReset = $("btn-reset-curve");
  const instruction = $("curve-filter-instruction");

  if (colZ1) colZ1.classList.toggle("active-zone-filter", filterKey === "zone1");
  if (colZ2) colZ2.classList.toggle("active-zone-filter", filterKey === "zone2");
  if (colCpu) colCpu.classList.toggle("active-zone-filter", filterKey === "cpu");

  if (btnReset) {
    btnReset.style.display = (filterKey !== "all") ? "inline-block" : "none";
  }

  if (instruction) {
    if (filterKey === "all") {
      instruction.textContent = "Displaying all thermal zones. Click a zone tachometer above or below to isolate.";
    } else {
      const nameMap = { zone1: "Zone 1 (Left Bays)", zone2: "Zone 2 (Right Bays)", cpu: "CPU Package" };
      instruction.textContent = `Filtered to ${nameMap[filterKey]}. Only this zone is active on the graph.`;
    }
  }

  if (latestStats) updateFanCurveWorkstation(latestStats);
}

function initFanCurveInteractivity() {
  const colZ1 = $("fan-col-zone1");
  const colZ2 = $("fan-col-zone2");
  const colCpu = $("fan-col-cpu");
  const legZ1 = $("leg-item-z1");
  const legZ2 = $("leg-item-z2");
  const legCpu = $("leg-item-cpu");
  const btnReset = $("btn-reset-curve");

  const toggleFilter = (key) => {
    setZoneFilter(selectedZoneFilter === key ? "all" : key);
  };

  if (colZ1) colZ1.addEventListener("click", () => toggleFilter("zone1"));
  if (colZ2) colZ2.addEventListener("click", () => toggleFilter("zone2"));
  if (colCpu) colCpu.addEventListener("click", () => toggleFilter("cpu"));

  if (legZ1) legZ1.addEventListener("click", () => toggleFilter("zone1"));
  if (legZ2) legZ2.addEventListener("click", () => toggleFilter("zone2"));
  if (legCpu) legCpu.addEventListener("click", () => toggleFilter("cpu"));

  if (btnReset) btnReset.addEventListener("click", () => setZoneFilter("all"));
}

function updateChassisImageForTheme() {
  const chassisImg = $("chassis-hero-img");
  if (!chassisImg) return;

  if (currentTheme === "yak") {
    chassisImg.src = "img/yak.png";
  } else if (latestStats && latestStats.chassis) {
    const modelMap = {
      "d4": "img/chassis-d4.png",
      "d8u": "img/chassis-d8u.png",
      "d6u": "img/chassis-d6u.png"
    };
    chassisImg.src = modelMap[latestStats.chassis] || "img/chassis-d6u.png";
  }
}

function applyTheme(themeName) {
  currentTheme = themeName;
  localStorage.setItem("lcd_theme", currentTheme);
  const isYak = (themeName === "yak");

  document.body.classList.toggle("theme-yak", isYak);

  const yakEggBtn = $("yak-easter-egg-btn");
  if (yakEggBtn) {
    yakEggBtn.title = isYak ? "Yak Express Active! [Press Y or click to toggle]" : "Trust in the Yak [Easter Egg Hot-key: Y]";
  }

  const title = $("suite-brand-title");
  const badge = $("suite-brand-badge");
  const engraved = $("chassis-panel-engraved");
  const drawerSub = $("drawer-sub-badge");
  const icon = $("suite-brand-icon");

  if (title) title.textContent = isYak ? "YAK EXPRESS" : "ZETTNAS";
  if (badge) badge.textContent = isYak ? "RELIABILITY CULT" : "HARDWARE TOOLKIT";
  if (engraved) engraved.textContent = isYak ? "YAK EXPRESS • TOASTIE LOGISTICS LAB" : "ZETTNAS • SYSTEM CONSOLE";
  if (drawerSub) drawerSub.textContent = isYak ? "LOGISTICS LAB" : "HARDWARE TOOLKIT";
  if (icon) icon.innerHTML = isYak ? '<use href="#i-yak"/>' : '<use href="#i-chip"/>';

  if ($("lbl-module-storage")) $("lbl-module-storage").textContent = isYak ? "Cargo Hold (Capacity & Donut)" : "Storage (Donut & Capacity)";
  if ($("lbl-module-cpu")) $("lbl-module-cpu").textContent = isYak ? "YAK64 Toastie CPU" : "CPU Gauge";
  if ($("lbl-module-fans")) $("lbl-module-fans").textContent = isYak ? "Asthmatic Yak Airflow & Fans" : "Fans & Uptime";
  if ($("lbl-module-disks")) $("lbl-module-disks").textContent = isYak ? "Yak Parcel Bays (OS, Data, Cache)" : "Drives Tray (OS, Data, Cache)";
  if ($("lbl-module-net")) $("lbl-module-net").textContent = isYak ? "Transit Courier Throughput" : "Network Throughput";

  const storageTitle = document.querySelector(".card-storage .card-title-txt");
  const cpuTitle = document.querySelector(".card-cpu .card-title-txt");
  const fansTitle = document.querySelector(".card-fans .card-title-txt");
  const netTitle = document.querySelector(".card-net .card-title-txt");
  if (storageTitle) storageTitle.textContent = isYak ? "CARGO HOLD" : "STORAGE";
  if (cpuTitle) cpuTitle.textContent = isYak ? "YAK64 CPU" : "CPU";
  if (fansTitle) fansTitle.textContent = isYak ? "YAK AIRFLOW" : "FANS";
  if (netTitle) netTitle.textContent = isYak ? "TRANSIT I/O" : "NETWORK I/O";

  if (latestStats && latestStats.disks) {
    renderDisks(latestStats.disks);
  }

  updateChassisImageForTheme();

  if (isYak) {
    const stageGlow = $("virtual-chassis-lightbar");
    if (stageGlow) {
      stageGlow.style.background = "linear-gradient(90deg, #1b68b8 0%, #e07a38 50%, #1b68b8 100%)";
      stageGlow.style.boxShadow = "0 0 16px rgba(224, 122, 56, 0.5)";
    }
  }
}

const defaultDashOrder = ["metric-storage", "metric-cpu", "metric-mem", "metric-fans", "metric-net", "metric-disks"];
const defaultVis = {
  "metric-storage": true,
  "metric-cpu": true,
  "metric-mem": true,
  "metric-fans": true,
  "metric-net": true,
  "metric-disks": true
};
const defaultSizes = {
  "metric-storage": "full",
  "metric-cpu": "full",
  "metric-mem": "full",
  "metric-fans": "full",
  "metric-net": "full",
  "metric-disks": "full"
};

let dashOrder = [...defaultDashOrder];
let dashVis = { ...defaultVis };
let dashSizes = { ...defaultSizes };

function applyDashboardLayout() {
  const screenCanvasEl = $("screen");
  const dashCardsContainer = $("dashboard-cards-container");
  const diskRowEl = $("diskRow");
  if (!dashCardsContainer || !screenCanvasEl) return;

  const cardMap = {};
  dashCardsContainer.querySelectorAll(".card").forEach((c) => {
    cardMap[c.dataset.metricId] = c;
  });

  dashOrder.forEach((id) => {
    if (cardMap[id]) dashCardsContainer.appendChild(cardMap[id]);
  });

  if (diskRowEl) {
    const disksIdx = dashOrder.indexOf("metric-disks");
    const firstCardIdx = dashOrder.findIndex((id) => id !== "metric-disks" && cardMap[id]);
    if (disksIdx !== -1 && firstCardIdx !== -1 && disksIdx < firstCardIdx) {
      screenCanvasEl.insertBefore(diskRowEl, dashCardsContainer);
    } else {
      screenCanvasEl.appendChild(diskRowEl);
    }
  }

  let allTopHidden = true;
  Object.keys(dashVis).forEach((id) => {
    if (id !== "metric-disks" && cardMap[id]) {
      const isHidden = !dashVis[id];
      cardMap[id].classList.toggle("card-hidden", isHidden);
      if (!isHidden) allTopHidden = false;
      cardMap[id].classList.toggle("card-compact", dashSizes[id] === "compact");
    }
  });

  dashCardsContainer.classList.toggle("card-hidden", allTopHidden);

  if (diskRowEl) {
    diskRowEl.classList.toggle("card-hidden", dashVis["metric-disks"] === false);
    diskRowEl.classList.toggle("compact", dashSizes["metric-disks"] === "compact");
  }

  screenCanvasEl.classList.toggle("no-disks", dashVis["metric-disks"] === false);
  screenCanvasEl.classList.toggle("no-cards", allTopHidden);

  document.querySelectorAll(".dash-module-item").forEach((item) => {
    const id = item.dataset.metricTarget;
    const isEnabled = dashVis[id] !== false;
    item.classList.toggle("disabled", !isEnabled);

    const toggle = item.querySelector(".metric-vis-toggle");
    if (toggle) toggle.checked = isEnabled;

    const currentSize = dashSizes[id] || "full";
    item.querySelectorAll(".seg-size-btn").forEach((sBtn) => {
      sBtn.classList.toggle("active", sBtn.dataset.size === currentSize);
    });
  });

  if ($("clock-format-btn")) {
    $("clock-format-btn").textContent = clockFormat === "12" ? "12 Hours" : "24 Hours";
  }

  if ($("clock")) $("clock").textContent = getLocalClock(currentTimezone, clockFormat);

  evaluateActivePreset();
  syncMiniPreviewStructure();
}

function evaluateActivePreset() {
  const presetCardBtns = document.querySelectorAll(".preset-btn-card");
  const presetBadge = $("preset-state-badge");
  const isVisMatch = (v) => Object.keys(v).every((k) => dashVis[k] === v[k]);

  const isDefault = isVisMatch(defaultVis);
  const isThermal = isVisMatch({ "metric-storage": false, "metric-cpu": true, "metric-mem": false, "metric-fans": true, "metric-net": false, "metric-disks": true });
  const isStorage = isVisMatch({ "metric-storage": true, "metric-cpu": false, "metric-mem": false, "metric-fans": false, "metric-net": false, "metric-disks": true });
  const isDisksOnly = isVisMatch({ "metric-storage": false, "metric-cpu": false, "metric-mem": false, "metric-fans": false, "metric-net": false, "metric-disks": true });

  let activeKey = null;
  if (isDefault) activeKey = "default";
  else if (isThermal) activeKey = "thermal";
  else if (isStorage) activeKey = "storage";
  else if (isDisksOnly) activeKey = "disks-only";

  presetCardBtns.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.preset === activeKey);
  });

  if (presetBadge) {
    if (activeKey) {
      presetBadge.textContent = `${activeKey.toUpperCase()} ENGAGED`;
      presetBadge.classList.remove("custom");
    } else {
      presetBadge.textContent = "CUSTOM CONFIGURATION";
      presetBadge.classList.add("custom");
    }
  }
}

async function persistDashboardLayout() {
  try {
    const res = await fetch("/api/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order: dashOrder,
        vis: dashVis,
        sizes: dashSizes,
        clock_format: clockFormat,
        timezone: currentTimezone
      })
    });
    if (res.ok) {
      const resp = await res.json();
      if (resp.layout && resp.layout.version) {
        activeLayoutVersion = resp.layout.version;
      }
    }
  } catch (err) {}
}

async function fetchDashboardLayout() {
  try {
    const res = await fetch("/api/layout", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      if (data.version) activeLayoutVersion = data.version;
      if (data.order) dashOrder = data.order;
      if (data.vis) dashVis = data.vis;
      if (data.sizes) dashSizes = data.sizes;
      if (data.clock_format) clockFormat = data.clock_format;
      if (data.timezone) currentTimezone = data.timezone;
    }
  } catch (err) { showToast("Failed to load layout: " + err, "error");  showToast("Failed to load layout: " + err, "error"); }
  applyDashboardLayout();
}

function syncMiniPreviewStructure() {
  const miniInner = $("mini-preview-inner");
  const screenEl = $("screen");
  if (!miniInner || !screenEl) return;

  let miniCardsContainer = miniInner.querySelector(".cards");
  let miniDiskRow = miniInner.querySelector(".disks");
  const screenDiskRow = screenEl.querySelector("#diskRow");

  if (!miniCardsContainer || !miniDiskRow) {
    miniInner.innerHTML = screenEl.innerHTML;
    miniCardsContainer = miniInner.querySelector(".cards");
    miniDiskRow = miniInner.querySelector(".disks");
    miniInner.className = "mini-preview-inner " + screenEl.className;
    setupMiniPreviewInteractivity();
  }

  if (screenDiskRow && screenDiskRow.children.length > 0 && miniDiskRow.children.length === 0) {
    miniDiskRow.innerHTML = screenDiskRow.innerHTML;
  }

  const sFanRowStruct = screenEl.querySelector(".fan-row");
  const dFanRowStruct = miniInner.querySelector(".fan-row");
  if (sFanRowStruct && dFanRowStruct) {
    dFanRowStruct.innerHTML = sFanRowStruct.innerHTML;
    dFanRowStruct.className = sFanRowStruct.className;
  }

  const cardMap = {};
  miniCardsContainer.querySelectorAll(".card").forEach((c) => {
    cardMap[c.dataset.metricId] = c;
  });

  dashOrder.forEach((id) => {
    if (cardMap[id]) miniCardsContainer.appendChild(cardMap[id]);
  });

  const disksIdx = dashOrder.indexOf("metric-disks");
  const firstCardIdx = dashOrder.findIndex((id) => id !== "metric-disks" && cardMap[id]);
  if (disksIdx !== -1 && firstCardIdx !== -1 && disksIdx < firstCardIdx) {
    miniInner.insertBefore(miniDiskRow, miniCardsContainer);
  } else {
    miniInner.appendChild(miniDiskRow);
  }

  Object.keys(dashVis).forEach((id) => {
    if (id !== "metric-disks" && cardMap[id]) {
      cardMap[id].classList.toggle("card-hidden", !dashVis[id]);
      cardMap[id].classList.toggle("card-compact", dashSizes[id] === "compact");
    }
  });

  miniDiskRow.classList.toggle("card-hidden", dashVis["metric-disks"] === false);
  miniDiskRow.classList.toggle("compact", dashSizes["metric-disks"] === "compact");

  // Live sync inner content so numbers match the main dashboard
  const sHeader = screenEl.querySelector("header");
  const mHeader = miniInner.querySelector("header");
  if (sHeader && mHeader) mHeader.innerHTML = sHeader.innerHTML;

  Object.keys(cardMap).forEach((id) => {
    const sCard = screenEl.querySelector(`[data-metric-id="${id}"]`);
    if (sCard && cardMap[id]) {
      cardMap[id].innerHTML = sCard.innerHTML;
    }
  });


  miniInner.className = "mini-preview-inner " + screenEl.className;
  fitMiniPreviewScale();
}

function fitMiniPreviewScale() {
  if (window.innerWidth <= 720) {
    const inner = $("mini-preview-inner");
    if (inner) inner.style.transform = "";
    return;
  }
  const canvas = $("mini-lcd-canvas");
  const inner = $("mini-preview-inner");
  if (!canvas || !inner) return;
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  if (!cw || !ch) return;
  const sW = (cw - 4) / 640;
  const sH = (ch - 4) / 172;
  const s = Math.min(sW, sH, 0.78);
  inner.style.setProperty("--mini-scale", s.toFixed(3));
  inner.style.transform = `translate(-50%, -50%) scale(${s.toFixed(3)})`;
}

function syncMiniPreviewTelemetry() {
  const miniInner = $("mini-preview-inner");
  const screenEl = $("screen");
  if (!miniInner || !screenEl || isDraggingPreview) return;

  // Sync header
  const sHeader = screenEl.querySelector("header");
  const mHeader = miniInner.querySelector("header");
  if (sHeader && mHeader) mHeader.innerHTML = sHeader.innerHTML;

  // Sync cards
  const miniCardsContainer = miniInner.querySelector(".cards");
  if (miniCardsContainer) {
    miniCardsContainer.querySelectorAll(".card").forEach(c => {
      const id = c.dataset.metricId;
      if (id) {
        const sCard = screenEl.querySelector(`[data-metric-id="${id}"]`);
        if (sCard) c.innerHTML = sCard.innerHTML;
      }
    });
  }

  // Sync disks
  const screenDiskRow = screenEl.querySelector("#diskRow");
  const miniDiskRow = miniInner.querySelector(".disks");
  if (screenDiskRow && miniDiskRow) {
    miniDiskRow.innerHTML = screenDiskRow.innerHTML;
  }
}


function setupMiniPreviewInteractivity() {
  const miniInner = $("mini-preview-inner");
  if (!miniInner) return;

  let draggedMetricId = null;

  miniInner.querySelectorAll(".card, .disks").forEach((el) => {
    const metricId = el.dataset.metricId;
    if (!metricId) return;

    el.setAttribute("draggable", "true");

    el.addEventListener("dragstart", (e) => {
      e.stopPropagation();
      isDraggingPreview = true;
      draggedMetricId = metricId;
      el.classList.add("mini-dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", metricId);
    });

    el.addEventListener("dragend", (e) => {
      e.stopPropagation();
      isDraggingPreview = false;
      draggedMetricId = null;
      el.classList.remove("mini-dragging");
      miniInner.querySelectorAll(".card, .disks").forEach((c) => c.classList.remove("mini-drag-over"));
    });

    el.addEventListener("dragover", (e) => {
      if (!draggedMetricId || draggedMetricId === metricId) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = "move";
      el.classList.add("mini-drag-over");
    });

    el.addEventListener("dragleave", (e) => {
      e.stopPropagation();
      el.classList.remove("mini-drag-over");
    });

    el.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      el.classList.remove("mini-drag-over");
      if (!draggedMetricId) return;

      const miniRect = miniInner.getBoundingClientRect();
      const isLowerHalf = (e.clientY - miniRect.top) / miniRect.height > 0.5;

      if (draggedMetricId === "metric-disks") {
        const newOrder = dashOrder.filter(x => x !== "metric-disks");
        if (isLowerHalf) {
          newOrder.push("metric-disks");
        } else {
          newOrder.unshift("metric-disks");
        }
        dashOrder = newOrder;
      } else if (metricId === "metric-disks") {
        const cardId = draggedMetricId;
        const cardsOnly = dashOrder.filter(x => x !== "metric-disks");
        const oldIdx = cardsOnly.indexOf(cardId);
        if (oldIdx !== -1) cardsOnly.splice(oldIdx, 1);
        if (isLowerHalf) {
          cardsOnly.push(cardId);
        } else {
          cardsOnly.unshift(cardId);
        }
        const disksWasFirst = dashOrder.indexOf("metric-disks") === 0;
        dashOrder = disksWasFirst ? ["metric-disks", ...cardsOnly] : [...cardsOnly, "metric-disks"];
      } else {
        const oldIdx = dashOrder.indexOf(draggedMetricId);
        const targetIdx = dashOrder.indexOf(metricId);
        if (oldIdx !== -1 && targetIdx !== -1 && oldIdx !== targetIdx) {
          const newOrder = [...dashOrder];
          newOrder.splice(oldIdx, 1);
          newOrder.splice(targetIdx, 0, draggedMetricId);
          dashOrder = newOrder;
        }
      }

      isDraggingPreview = false;
      draggedMetricId = null;

      applyDashboardLayout();
      persistDashboardLayout();
    });
  });

  const miniCardsContainer = miniInner.querySelector(".cards");
  if (miniCardsContainer) {
    miniCardsContainer.addEventListener("dragover", (e) => {
      if (!draggedMetricId || draggedMetricId === "metric-disks") return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    });

    miniCardsContainer.addEventListener("drop", (e) => {
      if (!draggedMetricId || draggedMetricId === "metric-disks") return;
      if (e.target === miniCardsContainer) {
        e.preventDefault();
        const dropX = e.clientX;
        const cards = Array.from(miniCardsContainer.querySelectorAll(".card"));
        let closestCardId = null;
        let minDiff = Infinity;
        cards.forEach((c) => {
          const cr = c.getBoundingClientRect();
          const cardCenter = cr.left + cr.width / 2;
          const diff = Math.abs(dropX - cardCenter);
          if (diff < minDiff) {
            minDiff = diff;
            closestCardId = c.dataset.metricId;
          }
        });
        if (closestCardId && closestCardId !== draggedMetricId) {
          const oldIdx = dashOrder.indexOf(draggedMetricId);
          const targetIdx = dashOrder.indexOf(closestCardId);
          if (oldIdx !== -1 && targetIdx !== -1 && oldIdx !== targetIdx) {
            const newOrder = [...dashOrder];
            newOrder.splice(oldIdx, 1);
            newOrder.splice(targetIdx, 0, draggedMetricId);
            dashOrder = newOrder;
            applyDashboardLayout();
            persistDashboardLayout();
          }
        }
        isDraggingPreview = false;
        draggedMetricId = null;
      }
    });
  }

  miniInner.addEventListener("dragover", (e) => {
    if (!draggedMetricId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  });

  miniInner.addEventListener("drop", (e) => {
    if (!draggedMetricId) return;
    const rect = miniInner.getBoundingClientRect();
    const isLowerHalf = (e.clientY - rect.top) / rect.height > 0.5;
    
    if (draggedMetricId === "metric-disks") {
      const newOrder = dashOrder.filter(x => x !== "metric-disks");
      if (isLowerHalf) {
        newOrder.push("metric-disks");
      } else {
        newOrder.unshift("metric-disks");
      }
      dashOrder = newOrder;
      isDraggingPreview = false;
      draggedMetricId = null;
      applyDashboardLayout();
      persistDashboardLayout();
    }
  });
}

// ---- Live update via Server-Sent Events (SSE) ----
// Falls back to 2-second polling if SSE is unavailable.
let _sseRetryCount = 0;

function applyStats(s) {
  try {
    latestStats = s;
    if (s.events) renderEventLog(s.events);
    anyWarn = false;

  if (s.copy_state) {
    const toast = $("copy-toast");
    if (toast) {
      const state = s.copy_state;
      if (state.active || state.status !== "idle") {
        toast.style.opacity = "1";
        toast.style.pointerEvents = "auto";
        
        const backdrop = $("copy-toast-backdrop");
        if (backdrop) {
          if (!copyToastMinimized && (state.active || state.status === "error" || state.status === "success" || state.status === "awaiting_confirmation")) {
            backdrop.style.opacity = "1";
            backdrop.style.pointerEvents = "auto";
            toast.style.boxShadow = "0 0 40px rgba(0,0,0,0.8)";
            toast.style.bottom = "50%";
            toast.style.right = "50%";
            toast.style.transform = "translate(50%, 50%) scale(1.2)";
          } else {
            backdrop.style.opacity = "0";
            backdrop.style.pointerEvents = "none";
            toast.style.boxShadow = "none";
            toast.style.bottom = "20px";
            toast.style.right = "20px";
            toast.style.transform = "translate(0, 0) scale(1)";
          }
        } else {
            toast.style.transform = "translateY(0)";
        }
        
        const prog = state.progress || {};
        const total = prog.total || 0;
        const copied = prog.copied || 0;
        const pct = total > 0 ? Math.min(100, Math.round((copied / total) * 100)) : 0;
        
        if ($("copy-toast-pct")) $("copy-toast-pct").textContent = pct + "%";
        if ($("copy-toast-bar")) $("copy-toast-bar").style.width = pct + "%";
        if ($("copy-toast-file")) $("copy-toast-file").textContent = prog.file || "";
        
        let statusText = "Copying...";
        let barColor = "var(--ok2)";
        if (state.status === "success") {
          statusText = "Success!";
          barColor = "#2ecc71";
          if ($("copy-toast-bar")) $("copy-toast-bar").style.width = "100%";
          if ($("copy-toast-pct")) $("copy-toast-pct").textContent = "100%";
        } else if (state.status === "error") {
          statusText = "Failed!";
          barColor = "#e74c3c";
        }
        if ($("copy-toast-status")) $("copy-toast-status").textContent = statusText;
        if ($("copy-toast-bar")) $("copy-toast-bar").style.background = barColor;
        
        if (state.status === "copying" && total > 0 && prog.start > 0) {
          const elapsed = (Date.now() / 1000) - prog.start;
          if (elapsed > 3 && copied > 0) {
            const rate = copied / elapsed;
            const remaining = (total - copied) / rate;
            const mins = Math.floor(remaining / 60);
            const secs = Math.floor(remaining % 60);
            const mbps = (rate / 1024 / 1024).toFixed(1);
            let filesLeftStr = "";
            if (prog.files_total) {
                const left = Math.max(0, prog.files_total - (prog.files_done || 0));
                filesLeftStr = `${left} file${left === 1 ? '' : 's'} left • `;
            }
            if ($("copy-toast-time")) $("copy-toast-time").textContent = `${filesLeftStr}${mbps} MB/s • ~${mins}m ${secs}s`;
          } else {
            if ($("copy-toast-time")) $("copy-toast-time").textContent = "Estimating time...";
          }
        } else {
          if ($("copy-toast-time")) $("copy-toast-time").textContent = "";
        }
        
        if (state.status === "awaiting_confirmation") {
          if (!$("copy-toast-actions")) {
            const actionsDiv = document.createElement("div");
            actionsDiv.id = "copy-toast-actions";
            actionsDiv.style.display = "flex";
            actionsDiv.style.gap = "8px";
            actionsDiv.style.marginTop = "10px";
            actionsDiv.innerHTML = `
              <button class="btn-save-preset" style="flex:1; padding:6px;" onclick="window.confirmCopy('skip')">Skip Existing</button>
              <button class="btn-save-preset" style="flex:1; padding:6px;" onclick="window.confirmCopy('overwrite')">Overwrite All</button>
              <button class="btn-save-preset" style="flex:1; padding:6px; border-color: rgba(240,85,59,0.5); color: var(--crit);" onclick="window.confirmCopy('cancel')" onmouseenter="this.style.background='var(--crit)'; this.style.color='#fff'; this.style.borderColor='var(--crit)';" onmouseleave="this.style.background='#1c2736'; this.style.color='var(--crit)'; this.style.borderColor='rgba(240,85,59,0.5)';">Cancel</button>
            `;
            $("copy-toast").querySelector(".smart-modal-body").appendChild(actionsDiv);
            
            window.confirmCopy = async (action) => {
              try {
                $("copy-toast-actions").style.opacity = "0.5";
                $("copy-toast-actions").style.pointerEvents = "none";
                await fetch("/api/copy/confirm", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ action })
                });
              } catch(e) {}
            };
          } else {
            $("copy-toast-actions").style.display = "flex";
            $("copy-toast-actions").style.opacity = "1";
            $("copy-toast-actions").style.pointerEvents = "auto";
          }
          if ($("copy-toast-pct")) $("copy-toast-pct").textContent = "WAIT";
        } else {
          if ($("copy-toast-actions")) $("copy-toast-actions").style.display = "none";
        }
        if (state.status === "idle" || state.status === "success" || state.status === "aborted" || state.status === "error") {
            if ($("copy-toast-abort-actions")) $("copy-toast-abort-actions").style.display = "none";
        }
        
        
  const btnToastCancel = $("copy-toast-cancel");
  if (btnToastCancel && !btnToastCancel.dataset.listening) {
    btnToastCancel.dataset.listening = "true";
    btnToastCancel.addEventListener("click", (e) => {
      if (window._customToastActive) return; // handled by custom onclick
      const statusText = ($("copy-toast-status")?.textContent || "").toUpperCase();
      if (statusText === "FAILED!" || statusText === "SUCCESS!" || statusText === "ERROR!" || statusText === "DONE!") {
        const toast = $("copy-toast");
        if (toast) {
          toast.style.opacity = "0";
          toast.style.pointerEvents = "none";
          toast.style.transform = "translateY(20px)";
          const backdrop = $("copy-toast-backdrop");
          if (backdrop) {
            backdrop.style.opacity = "0";
            backdrop.style.pointerEvents = "none";
          }
        }
        fetch("/api/copy/cancel", { method: "POST" });
        return;
      }
      
      if (!$("copy-toast-abort-actions")) {
        const actionsDiv = document.createElement("div");
        actionsDiv.id = "copy-toast-abort-actions";
        actionsDiv.style.marginTop = "10px";
        actionsDiv.style.paddingTop = "10px";
        actionsDiv.style.borderTop = "1px solid rgba(255,255,255,0.05)";
        actionsDiv.innerHTML = `
          <div style="font-size: 11px; color: #cbd5e1; margin-bottom: 8px; font-weight: 500;">Are you sure you want to completely abort the transfer? All incomplete files will be deleted.</div>
          <div style="display: flex; gap: 8px;">
            <button class="btn-save-preset" style="flex:1; padding:6px; border-color: rgba(240,85,59,0.5); color: var(--crit);" onclick="window.abortCopyConfirm(true)" onmouseenter="this.style.background='var(--crit)'; this.style.color='#fff'; this.style.borderColor='var(--crit)';" onmouseleave="this.style.background='#1c2736'; this.style.color='var(--crit)'; this.style.borderColor='rgba(240,85,59,0.5)';">Yes, Abort</button>
            <button class="btn-save-preset" style="flex:1; padding:6px;" onclick="window.abortCopyConfirm(false)">Resume</button>
          </div>
        `;
        $("copy-toast").querySelector(".smart-modal-body").appendChild(actionsDiv);
        
        window.abortCopyConfirm = async (yes) => {
          if (yes) {
            $("copy-toast-abort-actions").style.opacity = "0.5";
            $("copy-toast-abort-actions").style.pointerEvents = "none";
            fetch("/api/copy/cancel", { method: "POST" });
          } else {
            $("copy-toast-abort-actions").style.display = "none";
          }
        };
      } else {
        $("copy-toast-abort-actions").style.display = "block";
        $("copy-toast-abort-actions").style.opacity = "1";
        $("copy-toast-abort-actions").style.pointerEvents = "auto";
      }
    });
  }

  const btnMin = $("copy-toast-min");
        if (btnMin && !btnMin.dataset.listening) {
          btnMin.dataset.listening = "true";
          btnMin.addEventListener("click", () => {
            copyToastMinimized = !copyToastMinimized;
            btnMin.textContent = copyToastMinimized ? "□" : "–";
            if (latestStats) applyStats(latestStats);
          });
        }
      } else if (!window._customToastActive) {
        toast.style.opacity = "0";
        toast.style.pointerEvents = "none";
        toast.style.transform = "translateY(20px)";
        const backdrop = $("copy-toast-backdrop");
        if (backdrop) {
            backdrop.style.opacity = "0";
            backdrop.style.pointerEvents = "none";
        }
        copyToastMinimized = false;
      }
    }
  }

    if (s.layout && s.layout.version && s.layout.version !== activeLayoutVersion) {
      activeLayoutVersion = s.layout.version;
      if (s.layout.order) dashOrder = s.layout.order;
      if (s.layout.vis) dashVis = s.layout.vis;
      if (s.layout.sizes) dashSizes = s.layout.sizes;
      if (s.layout.clock_format) clockFormat = s.layout.clock_format;
      if (s.layout.timezone) currentTimezone = s.layout.timezone;
      applyDashboardLayout();
    }


    // Media Slots Labeling
    if (s.media_slots) {
      const srcSelect = $("btn-copy-src");
      if (srcSelect) {
        const sdSize = s.media_slots.sd.size;
        let sdText = "SD 4.0 Slot";
        if (sdSize > 0) sdText += ` [${(sdSize / 1e9).toFixed(1)} GB]`;
        else sdText += " [Empty]";
        
        const tfSize = s.media_slots.tf.size;
        let tfText = "TF 4.0 Slot (MicroSD)";
        if (tfSize > 0) tfText += ` [${(tfSize / 1e9).toFixed(1)} GB]`;
        else tfText += " [Empty]";

        for (let i = 0; i < srcSelect.options.length; i++) {
          const opt = srcSelect.options[i];
          if (opt.value === "sd" && opt.text !== sdText) opt.text = sdText;
          if (opt.value === "tf" && opt.text !== tfText) opt.text = tfText;
        }
      }
    }

    // Copy Status Badge
    let copyBadge = $("copy-badge");
    if (s.copy_status && s.copy_status !== "idle") {
      if (!copyBadge) {
        copyBadge = document.createElement("span");
        copyBadge.id = "copy-badge";
        copyBadge.className = "header-badge";
        copyBadge.style.marginLeft = "10px";
        const titleArea = document.querySelector(".header-title");
        if (titleArea) titleArea.appendChild(copyBadge);
      }
      
      if (s.copy_status === "copying") {
        copyBadge.textContent = "COPYING MEDIA...";
        copyBadge.style.background = "rgba(41, 128, 185, 0.2)";
        copyBadge.style.color = "#3498db";
        copyBadge.style.borderColor = "rgba(41, 128, 185, 0.4)";
      } else if (s.copy_status === "success") {
        copyBadge.textContent = "COPY SUCCESS";
        copyBadge.style.background = "rgba(46, 204, 113, 0.2)";
        copyBadge.style.color = "#2ecc71";
        copyBadge.style.borderColor = "rgba(46, 204, 113, 0.4)";
      } else if (s.copy_status === "error") {
        copyBadge.textContent = "COPY FAILED";
        copyBadge.style.background = "rgba(231, 76, 60, 0.2)";
        copyBadge.style.color = "#e74c3c";
        copyBadge.style.borderColor = "rgba(231, 76, 60, 0.4)";
      }
    } else if (copyBadge) {
      copyBadge.remove();
    }

    if ($("nasName")) $("nasName").textContent = s.name;
    if ($("drawer-nas-name")) $("drawer-nas-name").textContent = s.name.toUpperCase();

    if ($("statusText")) {
      if (currentTheme === "yak" && !s.status.includes("ALERT") && !s.status.includes("WARN")) {
        $("statusText").textContent = "YAK OK";
      } else {
        $("statusText").textContent = s.status;
      }
    }

    if ($("clock")) $("clock").textContent = getLocalClock(currentTimezone, clockFormat);
    if ($("ip")) $("ip").textContent = s.ip;

    updateChassisImageForTheme();

    const stLvl = lvlFull(s.storage.pct);
    if ($("storagePct")) $("storagePct").textContent = s.storage.pct + "%";
    if ($("stUsed")) $("stUsed").textContent = s.storage.used;
    if ($("stTotal")) $("stTotal").textContent = s.storage.total;
    const donut = $("donut");
    if (donut) {
      donut.style.setProperty("--pct", s.storage.pct);
      donut.style.setProperty("--c", cssVar(stLvl));
    }

    const cpuLvl = lvlCpu(s.cpu.temp);
    const utilLvl = lvlUtil(s.cpu.util);
    if ($("cpuTemp")) $("cpuTemp").textContent = s.cpu.temp;
    if ($("cpuTemp") && $("cpuTemp").parentElement) $("cpuTemp").parentElement.className = "arc-val " + "s-" + cpuLvl;
    if ($("cpuUtil")) {
      $("cpuUtil").textContent = s.cpu.util + "%";
      $("cpuUtil").className = "val s-" + utilLvl;
    }
    if ($("cpuArc")) setArc($("cpuArc"), (s.cpu.temp / 100) * 100, cpuLvl);

    const memLvl = lvlUtil(s.mem.pct);
    if ($("memPct")) $("memPct").textContent = s.mem.pct;
    if ($("memPct") && $("memPct").parentElement) $("memPct").parentElement.className = "arc-val s-" + memLvl;
    if ($("memUsed")) $("memUsed").textContent = s.mem.used_gb.toFixed(1) + "G";
    if ($("memTotal")) $("memTotal").textContent = "/" + s.mem.total_gb.toFixed(0) + "G";
    if ($("memArc")) setArc($("memArc"), s.mem.pct, memLvl);

    renderFans(s.fans);
    renderDisks(s.disks);
    if ($("uptime")) $("uptime").textContent = "up " + s.uptime;

    if (s.net) {
      if ($("netTx")) $("netTx").textContent = s.net.tx;
      if ($("netRx")) $("netRx").textContent = s.net.rx;
    }

    if (!isLcdDirect) {
      ZettEventBus.dispatchEvent(new CustomEvent('stats_tick', { detail: s }));
      updateRowTelemetryBadges(s);
      updateFanCurveWorkstation(s);
      // Only sync mini preview when drawer is open (saves DOM queries when hidden)
      if (document.body.classList.contains("drawer-is-open")) {
        syncMiniPreviewTelemetry();
      }
    }

    if ([stLvl, cpuLvl, utilLvl, memLvl].includes("crit") ||
        s.disks.some((d) => (d.health || lvlDisk(d.temp)) !== "ok")) anyWarn = true;
    if ($("statusPill")) $("statusPill").className = "pill" + (anyWarn ? " warn" : "");

  } catch (e) {}
}

async function tick() {
  try {
    const s = await (await fetch("/api/stats", { cache: "no-store" })).json();
    applyStats(s);
  } catch (e) {}
}

function startSSE() {
  if (isLcdDirect) {
    // LCD renderer: just poll (no SSE overhead needed for headless)
    tick();
    setInterval(tick, 2000);
    return;
  }

  const es = new EventSource("/api/stats/stream");
  es.onmessage = (e) => {
    try {
      _sseRetryCount = 0;
      applyStats(JSON.parse(e.data));
    } catch (err) { showToast("Failed to load layout: " + err, "error"); }
  };
  es.onerror = () => {
    _sseRetryCount++;
    es.close();
    // Fall back to polling after 3 consecutive SSE failures
    if (_sseRetryCount >= 3) {
      console.warn("[ZettNAS] SSE unavailable, falling back to 2s polling");
      tick();
      setInterval(tick, 2000);
    } else {
      // Retry SSE after a short delay
      setTimeout(startSSE, 3000);
    }
  };
}

async function fetchLcdStatus() {
  if (isLcdDirect) return;
  try {
    const res = await fetch("/api/lcd_status", { cache: "no-store" });
    const badge = $("lcd-renderer-badge");
    if (res.ok && badge) {
      const data = await res.json();
      badge.className = "lcd-status-badge";
      if (!data.enabled) {
        badge.classList.add("lcd-status-disabled");
        badge.innerHTML = "&#x2B24; Disabled";
      } else if (data.active) {
        badge.classList.add("lcd-status-active");
        badge.innerHTML = `&#x2B24; Active (${data.fps} FPS)`;
      } else {
        badge.classList.add("lcd-status-offline");
        badge.innerHTML = "&#x2B24; Offline / Restarting";
      }
    }
  } catch (e) {
    const badge = $("lcd-renderer-badge");
    if (badge) {
      badge.className = "lcd-status-badge lcd-status-offline";
      badge.innerHTML = "&#x2B24; Unreachable";
    }
  }
}

fetchDashboardLayout().then(() => {
  startSSE();
  if (!isLcdDirect) {
    fetchLcdStatus();
    setInterval(fetchLcdStatus, 5000);
  }
});

(function initHardwareBuilder() {
  if (isLcdDirect) return;
  const toggleBtn = $("drawer-toggle-btn");
  const suiteBtn = $("suite-toolkit-btn");
  const closeBtn = $("drawer-close-btn");
  const drawer = $("led-drawer");
  const overlay = $("drawer-overlay");
  const dynamicTitle = $("drawer-dynamic-title");
  const dynamicDesc = $("drawer-dynamic-desc");

  const tabBtns = document.querySelectorAll(".drawer-tab-btn");
  const tabContents = document.querySelectorAll(".drawer-tab-content");

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => b.classList.remove("active"));
      tabContents.forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      const targetId = btn.dataset.tab;
      const targetContent = $(targetId);
      if (targetContent) targetContent.classList.add("active");

      if (targetId === "tab-layout") {
        if (dynamicTitle) dynamicTitle.textContent = "Dashboard Layout";
        if (dynamicDesc) dynamicDesc.textContent = "Configure dashboard sizes, visibility, and layout presets.";
      } else if (targetId === "tab-led") {
        if (dynamicTitle) dynamicTitle.textContent = "LED Strip bar";
        if (dynamicDesc) dynamicDesc.textContent = "Adjust physical lighting and reactive hardware alerts.";
      } else if (targetId === "tab-fans") {
        if (dynamicTitle) dynamicTitle.textContent = "Fans";
        if (dynamicDesc) dynamicDesc.textContent = "Configure cooling thresholds and dynamic thermal curves.";
      } else if (targetId === "tab-buttons") {
        if (dynamicTitle) dynamicTitle.textContent = "Copy Button";
        if (dynamicDesc) dynamicDesc.textContent = "Assign SD card copy rules to the physical hardware button.";

      } else if (targetId === "tab-misc") {
        if (dynamicTitle) dynamicTitle.textContent = "Misc & Event Log";
        if (dynamicDesc) dynamicDesc.textContent = "Historical metrics, background operations, and hardware alerts.";
        fetchAndRenderMetrics();
      }
    });
  });

  function openDrawer() {
    if (drawer && overlay) {
      drawer.classList.add("open");
      overlay.classList.add("open");
      document.body.classList.add("drawer-is-open");
      setTimeout(() => {
        fitMiniPreviewScale();
        if (typeof syncMiniPreviewTelemetry === 'function') syncMiniPreviewTelemetry();
      }, 100);
    }
  }
  function closeDrawer() {
    if (drawer && overlay) {
      drawer.classList.remove("open");
      overlay.classList.remove("open");
      document.body.classList.remove("drawer-is-open");
    }
  }

  if (toggleBtn) toggleBtn.addEventListener("click", openDrawer);
  if (suiteBtn) suiteBtn.addEventListener("click", openDrawer);
  if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
  if (overlay) overlay.addEventListener("click", closeDrawer);

  const zoomBtn = $("suite-zoom-btn");
  const ZOOM_PROFILES = [
    { label: "1x",    zoom: 1.0,   chassis: 1.0,   opacity: 1.0,  gap: "24px", offsetY: "0px" },
    { label: "1.25x", zoom: 1.18,  chassis: 0.72,  opacity: 0.65, gap: "18px", offsetY: "-15px" },
    { label: "1.5x",  zoom: 1.35,  chassis: 0.42,  opacity: 0.25, gap: "12px", offsetY: "-30px" },
    { label: "2x",    zoom: 1.55,  chassis: 0.0,   opacity: 0.0,  gap: "0px",  offsetY: "-90px" }
  ];

  let currentZoomIdx = parseInt(localStorage.getItem("lcd_stage_zoom_idx") || "0", 10);
  if (isNaN(currentZoomIdx) || currentZoomIdx < 0 || currentZoomIdx >= ZOOM_PROFILES.length) {
    currentZoomIdx = 0;
  }

  function applyStageZoom() {
    const prof = ZOOM_PROFILES[currentZoomIdx];
    const root = document.documentElement;
    root.style.setProperty("--stage-zoom", prof.zoom);
    root.style.setProperty("--chassis-scale", prof.chassis);
    root.style.setProperty("--chassis-opacity", prof.opacity);
    root.style.setProperty("--stage-gap", prof.gap);
    root.style.setProperty("--stage-offset-y", prof.offsetY);
    if (zoomBtn) zoomBtn.textContent = `🔍 ${prof.label}`;
    localStorage.setItem("lcd_stage_zoom_idx", currentZoomIdx);
  }

  function cycleZoom() {
    currentZoomIdx = (currentZoomIdx + 1) % ZOOM_PROFILES.length;
    applyStageZoom();
  }

  if (zoomBtn) {
    zoomBtn.addEventListener("click", cycleZoom);
    applyStageZoom();
  }

  let wheelZoomCooldown = 0;
  window.addEventListener("wheel", (e) => {
    if (e.target.closest(".slide-drawer") || e.target.closest(".smart-modal-window") || e.target.closest("#mini-lcd-canvas")) {
      return;
    }
    const now = Date.now();
    if (now - wheelZoomCooldown < 150) return;

    if (e.deltaY < 0 && currentZoomIdx < ZOOM_PROFILES.length - 1) {
      currentZoomIdx++;
      applyStageZoom();
      wheelZoomCooldown = now;
    } else if (e.deltaY > 0 && currentZoomIdx > 0) {
      currentZoomIdx--;
      applyStageZoom();
      wheelZoomCooldown = now;
    }
  }, { passive: true });

  const yakEggBtn = $("yak-easter-egg-btn");
  if (yakEggBtn) {
    yakEggBtn.addEventListener("click", () => {
      applyTheme(currentTheme === "yak" ? "cyber" : "yak");
    });
  }


  applyTheme(currentTheme);

  initFanCurveInteractivity();

  const layoutSectionsContainer = $("layout-sections-container");
  const layoutLockBtn = $("layout-cards-lock-btn");
  const LAYOUT_SECTIONS_STORAGE_KEY = "lcd_dash_card_order";
  const LAYOUT_LOCK_KEY = "lcd_dash_cards_locked";
  let isLayoutLocked = localStorage.getItem(LAYOUT_LOCK_KEY) !== "false";

  function setLayoutLockState(locked) {
    isLayoutLocked = locked;
    localStorage.setItem(LAYOUT_LOCK_KEY, isLayoutLocked);
    if (layoutSectionsContainer) layoutSectionsContainer.classList.toggle("locked", isLayoutLocked);
    if (layoutLockBtn) {
      layoutLockBtn.textContent = isLayoutLocked ? "🔒 Locked" : "🔓 Reorder";
      layoutLockBtn.classList.toggle("unlocked", !isLayoutLocked);
    }
    if (layoutSectionsContainer) {
      layoutSectionsContainer.querySelectorAll(".draggable-card").forEach((card) => {
        card.setAttribute("draggable", !isLayoutLocked);
      });
    }
  }

  function initLayoutSectionReordering() {
    if (!layoutSectionsContainer) return;
    const savedOrder = JSON.parse(localStorage.getItem(LAYOUT_SECTIONS_STORAGE_KEY) || "[]");
    if (savedOrder.length > 0) {
      const cardMap = {};
      layoutSectionsContainer.querySelectorAll(".draggable-card").forEach((c) => { 
        cardMap[c.dataset.layoutCardId] = c; 
      });
      savedOrder.forEach((id) => { 
        if (cardMap[id]) layoutSectionsContainer.appendChild(cardMap[id]); 
      });
    }

    let draggedLayoutCard = null;
    let allowLayoutDrag = false;

    layoutSectionsContainer.addEventListener("mousedown", (e) => {
      if (e.target.closest("#mini-lcd-canvas") || e.target.closest(".dash-reorder-flow")) {
        allowLayoutDrag = false;
        return;
      }
      allowLayoutDrag = !isLayoutLocked && !!e.target.closest(".drag-handle");
    });

    layoutSectionsContainer.querySelectorAll(".draggable-card").forEach((card) => {
      card.addEventListener("dragstart", (e) => {
        if (isLayoutLocked || !allowLayoutDrag || e.target.closest("#mini-lcd-canvas")) {
          e.preventDefault();
          return false;
        }
        draggedLayoutCard = card;
        card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.dataset.layoutCardId);
      });

      card.addEventListener("dragend", () => {
        allowLayoutDrag = false;
        if (draggedLayoutCard) draggedLayoutCard.classList.remove("dragging");
        layoutSectionsContainer.querySelectorAll(".draggable-card").forEach((c) => c.classList.remove("drag-over"));
        const order = Array.from(layoutSectionsContainer.querySelectorAll(".draggable-card")).map((c) => c.dataset.layoutCardId);
        localStorage.setItem(LAYOUT_SECTIONS_STORAGE_KEY, JSON.stringify(order));
      });

      card.addEventListener("dragover", (e) => {
        if (isLayoutLocked || !draggedLayoutCard) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const targetCard = e.target.closest(".draggable-card");
        if (targetCard && targetCard !== draggedLayoutCard && targetCard.parentElement === layoutSectionsContainer) {
          const rect = targetCard.getBoundingClientRect();
          const next = (e.clientY - rect.top) / (rect.bottom - rect.top) > 0.5;
          layoutSectionsContainer.insertBefore(draggedLayoutCard, next && targetCard.nextSibling || targetCard);
        }
      });
    });

    if (layoutLockBtn) layoutLockBtn.addEventListener("click", () => setLayoutLockState(!isLayoutLocked));
    setLayoutLockState(isLayoutLocked);
  }

  initLayoutSectionReordering();

  if ($("clock-format-btn")) {
    $("clock-format-btn").addEventListener("click", () => {
      clockFormat = (clockFormat === "24") ? "12" : "24";
      applyDashboardLayout();
      persistDashboardLayout();
    });
  }

  const tzSelect = $("tz-select");
  const tzCustomInput = $("tz-custom-input");
  if (tzSelect) {
    tzSelect.addEventListener("change", (e) => {
      const val = e.target.value;
      if (val === "custom") {
        if (tzCustomInput) {
          tzCustomInput.style.display = "block";
          tzCustomInput.focus();
        }
      } else {
        if (tzCustomInput) tzCustomInput.style.display = "none";
        currentTimezone = val;
        applyDashboardLayout();
        persistDashboardLayout();
      }
    });
  }

  if (tzCustomInput) {
    let tzTimeout = null;
    tzCustomInput.addEventListener("input", (e) => {
      clearTimeout(tzTimeout);
      tzTimeout = setTimeout(() => {
        const val = e.target.value.trim();
        if (val) {
          currentTimezone = val;
          persistDashboardLayout();
        }
      }, 500);
    });
  }

  document.querySelectorAll(".seg-size-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const metricId = e.target.dataset.metricId;
      const targetSize = e.target.dataset.size;
      dashSizes[metricId] = targetSize;
      applyDashboardLayout();
      persistDashboardLayout();
    });
  });

  document.querySelectorAll(".metric-vis-toggle").forEach((toggle) => {
    toggle.addEventListener("change", (e) => {
      const id = e.target.dataset.metricId;
      dashVis[id] = e.target.checked;
      applyDashboardLayout();
      persistDashboardLayout();
    });
  });

  document.querySelectorAll(".preset-btn-card").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pr = btn.dataset.preset;
      if (pr === "thermal") {
        dashVis = { "metric-storage": false, "metric-cpu": true, "metric-mem": false, "metric-fans": true, "metric-net": false, "metric-disks": true };
      } else if (pr === "storage") {
        dashVis = { "metric-storage": true, "metric-cpu": false, "metric-mem": false, "metric-fans": false, "metric-net": false, "metric-disks": true };
      } else if (pr === "disks-only") {
        dashVis = { "metric-storage": false, "metric-cpu": false, "metric-mem": false, "metric-fans": false, "metric-net": false, "metric-disks": true };
      } else {
        dashVis = {
          "metric-storage": true,
          "metric-cpu": true,
          "metric-mem": true,
          "metric-fans": true,
          "metric-net": true,
          "metric-disks": true
        };
      }
      applyDashboardLayout();
      persistDashboardLayout();
    });
  });

  const btnSaveCustom = $("btn-save-custom-preset");
  if (btnSaveCustom) {
    btnSaveCustom.addEventListener("click", () => {
      localStorage.setItem("lcd_user_preset", JSON.stringify({
        order: dashOrder,
        vis: dashVis,
        sizes: dashSizes
      }));
      btnSaveCustom.textContent = "✓ Saved!";
      setTimeout(() => { btnSaveCustom.textContent = "💾 Save as My Preset"; }, 1500);
    });
  }

  const exportBtn = $("btn-export-layout");
  if (exportBtn) {
    exportBtn.addEventListener("click", async () => {
      let ledState = {};
      try {
        const r = await fetch("/api/led", { cache: "no-store" });
        if (r.ok) ledState = await r.json();
      } catch (e) {}

      let fanState = {};
      try {
        const r = await fetch("/api/fans", { cache: "no-store" });
        if (r.ok) fanState = await r.json();
      } catch (e) {}

      const drawerCardOrder = JSON.parse(localStorage.getItem("lcd_drawer_card_order") || "[]");
      const fanCardOrder = JSON.parse(localStorage.getItem("lcd_fan_card_order") || "[]");
      const dashSectionOrder = JSON.parse(localStorage.getItem(LAYOUT_SECTIONS_STORAGE_KEY) || "[]");

      const suiteConfig = {
        version: "2.0",
        timestamp: new Date().toISOString(),
        theme: currentTheme,
        dashboard_layout: {
          order: dashOrder,
          vis: dashVis,
          sizes: dashSizes,
          clock_format: clockFormat,
          timezone: currentTimezone
        },
        led_strip: ledState,
        fan_control: fanState,
        drawer_orders: {
          sections: dashSectionOrder,
          led_cards: drawerCardOrder,
          fan_cards: fanCardOrder
        }
      };

      const blob = new Blob([JSON.stringify(suiteConfig, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `zettnas_suite_backup_${Math.floor(Date.now() / 1000)}.json`;
      a.click();
    });
  }

  const importInput = $("file-import-layout");
  if (importInput) {
    importInput.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async (evt) => {
        try {
          const cfg = JSON.parse(evt.target.result);

          if (cfg.theme) {
            applyTheme(cfg.theme);
          }

          const dl = cfg.dashboard_layout || cfg;
          if (dl.order) dashOrder = dl.order;
          if (dl.vis) dashVis = dl.vis;
          if (dl.sizes) dashSizes = dl.sizes;
          if (dl.clock_format) clockFormat = dl.clock_format;
          if (dl.timezone) currentTimezone = dl.timezone;

          applyDashboardLayout();
          await persistDashboardLayout();

          if (cfg.led_strip) {
            await fetch("/api/led", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(cfg.led_strip)
            });
            fetchLedState();
          }

          if (cfg.fan_control) {
            await fetch("/api/fans", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(cfg.fan_control)
            });
            fetchFanState();
          }

          if (cfg.drawer_orders) {
            if (cfg.drawer_orders.sections) localStorage.setItem(LAYOUT_SECTIONS_STORAGE_KEY, JSON.stringify(cfg.drawer_orders.sections));
            if (cfg.drawer_orders.led_cards) localStorage.setItem("lcd_drawer_card_order", JSON.stringify(cfg.drawer_orders.led_cards));
            if (cfg.drawer_orders.fan_cards) localStorage.setItem("lcd_fan_card_order", JSON.stringify(cfg.drawer_orders.fan_cards));
            initLayoutSectionReordering();
            initDragAndDrop();
            initFanCardReordering();



  loadButtonConfig();
          }

          alert("✓ Suite configuration restored successfully!");
        } catch (err) {
          alert("Error importing suite configuration: " + err.message);
        }
      };
      reader.readAsText(file);
    });
  }

  const resetBtn = $("dashboard-reset-btn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      dashOrder = [...defaultDashOrder];
      dashVis = { ...defaultVis };
      dashSizes = { ...defaultSizes };
      clockFormat = "24";
      currentTimezone = "America/New_York";
      applyTheme("cyber");
      applyDashboardLayout();
      persistDashboardLayout();
    });
  }

  fetchDashboardLayout();

  const lockBtn = $("drawer-lock-btn");
  const cardsContainer = $("drawer-cards-container");
  const slider = $("led-slider");
  const valDisplay = $("led-val-display");
  const speedCard = $("speed-card");
  const speedSlider = $("speed-slider");
  const speedValDisplay = $("speed-val-display");
  const secColorCard = $("secondary-color-card");
  const priColorCard = $("primary-color-card");
  const powerBtn = $("btn-toggle-led");
  const reactiveToggle = $("reactive-toggle");
  const ledNightToggle = $("led-night-toggle");
  const ledNightStart = $("led-night-start");
  const ledNightEnd = $("led-night-end");

  // Screen Backlight & Night Dimming Controller
  const screenBriSlider = $("screen-bri-slider");
  const screenBriVal = $("screen-bri-val");
  const screenNightToggle = $("screen-night-toggle");
  const screenNightStart = $("screen-night-start");
  const screenNightEnd = $("screen-night-end");
  const screenNightBri = $("screen-night-bri");
  let screenDebounce = null;

  async function postScreenState() {
    const payload = {
      brightness: parseInt(screenBriSlider ? screenBriSlider.value : 100, 10),
      night_mode: screenNightToggle ? screenNightToggle.checked : false,
      night_start: screenNightStart ? screenNightStart.value : "23:00",
      night_end: screenNightEnd ? screenNightEnd.value : "07:00",
      night_brightness: parseInt(screenNightBri ? screenNightBri.value : 10, 10)
    };
    try {
      await fetch("/api/screen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } catch (e) {}
  }

  async function fetchScreenState() {
    try {
      const res = await fetch("/api/screen", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        if (screenBriSlider && data.brightness !== undefined) screenBriSlider.value = data.brightness;
        if (screenBriVal && screenBriSlider) screenBriVal.textContent = screenBriSlider.value + "%";
        if (screenNightToggle) screenNightToggle.checked = Boolean(data.night_mode);
        if (screenNightStart && data.night_start) screenNightStart.value = data.night_start;
        if (screenNightEnd && data.night_end) screenNightEnd.value = data.night_end;
        if (screenNightBri && data.night_brightness !== undefined) screenNightBri.value = data.night_brightness;
      }
    } catch (e) {}
  }

  fetchScreenState();

  if (screenBriSlider) {
    screenBriSlider.addEventListener("input", (e) => {
      if (screenBriVal) screenBriVal.textContent = e.target.value + "%";
      clearTimeout(screenDebounce);
      screenDebounce = setTimeout(postScreenState, 100);
    });
  }
  if (screenNightToggle) screenNightToggle.addEventListener("change", postScreenState);
  if (screenNightStart) screenNightStart.addEventListener("change", postScreenState);
  if (screenNightEnd) screenNightEnd.addEventListener("change", postScreenState);
  if (screenNightBri) screenNightBri.addEventListener("change", postScreenState);

  const previewBar = $("preview-bar");
  const previewTxt = $("preview-state-txt");

  const colorChips1 = document.querySelectorAll(".color-chip:not(.custom-picker-chip)");
  const customChip1Label = $("custom-chip-label");
  const customColorPicker1 = $("custom-color-picker");

  const colorChips2 = document.querySelectorAll(".color-chip2:not(.custom-picker-chip)");
  const customChip2Label = $("custom-chip2-label");
  const customColorPicker2 = $("custom-color-picker2");

  const effectBtns = document.querySelectorAll(".effect-btn");
  const profilePills = document.querySelectorAll(".profile-pill:not(.fan-profile-btn)");

  let currentColor = "25c2a0";
  let currentColor2 = "ff0055";
  let currentMode = "solid";
  let currentPower = "on";
  let briDebounce = null;
  let speedDebounce = null;
  let colorDebounce = null;

  const STORAGE_KEY = "lcd_drawer_card_order";
  const LOCK_KEY = "lcd_drawer_locked";
  let isLocked = localStorage.getItem(LOCK_KEY) !== "false";

  function setLockState(locked) {
    isLocked = locked;
    localStorage.setItem(LOCK_KEY, isLocked);
    if (cardsContainer) cardsContainer.classList.toggle("locked", isLocked);
    if (lockBtn) {
      lockBtn.textContent = isLocked ? "🔒 Locked" : "🔓 Reorder";
      lockBtn.classList.toggle("unlocked", !isLocked);
    }
    cardsContainer.querySelectorAll(".draggable-card").forEach((card) => {
      card.setAttribute("draggable", !isLocked);
    });
  }

  function initDragAndDrop() {
    if (!cardsContainer) return;
    const savedOrder = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    if (savedOrder.length > 0) {
      const cardMap = {};
      cardsContainer.querySelectorAll(".draggable-card").forEach((c) => { cardMap[c.dataset.cardId] = c; });
      savedOrder.forEach((id) => { if (cardMap[id]) cardsContainer.appendChild(cardMap[id]); });
    }

    let draggedItem = null;
    let allowDrag = false;

    cardsContainer.addEventListener("mousedown", (e) => {
      allowDrag = !isLocked && !!e.target.closest(".drag-handle");
    });

    cardsContainer.querySelectorAll(".draggable-card").forEach((card) => {
      card.addEventListener("dragstart", (e) => {
        if (isLocked || !allowDrag) { e.preventDefault(); return false; }
        draggedItem = card;
        card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.dataset.cardId);
      });

      card.addEventListener("dragend", () => {
        allowDrag = false;
        card.classList.remove("dragging");
        cardsContainer.querySelectorAll(".draggable-card").forEach((c) => c.classList.remove("drag-over"));
        const order = Array.from(cardsContainer.querySelectorAll(".draggable-card")).map((c) => c.dataset.cardId);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(order));
      });

      card.addEventListener("dragover", (e) => {
        if (isLocked) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const targetCard = e.target.closest(".draggable-card");
        if (targetCard && targetCard !== draggedItem) {
          const rect = targetCard.getBoundingClientRect();
          const next = (e.clientY - rect.top) / (rect.bottom - rect.top) > 0.5;
          cardsContainer.insertBefore(draggedItem, next && targetCard.nextSibling || targetCard);
        }
      });
    });

    if (lockBtn) lockBtn.addEventListener("click", () => setLockState(!isLocked));
    setLockState(isLocked);
  }

  initDragAndDrop();

  function formatSpeedText(val) {
    const v = parseInt(val, 10);
    if (v <= 20) return `Slow (${v}%)`;
    if (v <= 60) return `Medium (${v}%)`;
    if (v <= 85) return `Fast (${v}%)`;
    return `Ultra Fast (${v}%)`;
  }

  function updateLivePreview() {
    const stageGlow = $("virtual-chassis-lightbar");

    if (currentPower === "off") {
      if (previewTxt) previewTxt.textContent = "OFF";
      if (previewBar) {
        previewBar.style.background = "#1a2330";
        previewBar.style.boxShadow = "none";
        previewBar.style.animation = "none";
        previewBar.style.opacity = "0.2";
      }
      if (stageGlow) {
        stageGlow.style.background = "#1a2330";
        stageGlow.style.boxShadow = "none";
        stageGlow.style.animation = "none";
        stageGlow.style.opacity = "0.15";
      }
      return;
    }

    const c1 = "#" + currentColor;
    const c2 = "#" + currentColor2;
    const bri = parseInt(slider ? slider.value : 25, 10) / 100;
    const spd = parseInt(speedSlider ? speedSlider.value : 50, 10);
    const dur = Math.max(0.3, 4.0 - (spd / 100.0) * 3.7).toFixed(2) + "s";

    let bgStyle = c1;
    let shadowStyle = `0 0 10px ${c1}`;
    let animStyle = "none";
    let bgSize = "auto";

    if (currentMode === "solid") {
      bgStyle = c1;
      shadowStyle = `0 0 14px ${c1}`;
      animStyle = "none";
    } else if (currentMode === "breathe") {
      bgStyle = c1;
      shadowStyle = `0 0 16px ${c1}`;
      animStyle = `barBreathe ${dur} infinite ease-in-out`;
    } else if (currentMode === "flow" || currentMode === "chase") {
      bgStyle = `linear-gradient(90deg, ${c1} 0%, rgba(0,0,0,0.2) 50%, ${c1} 100%)`;
      bgSize = "200% 100%";
      shadowStyle = `0 0 12px ${c1}`;
      animStyle = `barFlow ${dur} infinite linear`;
    } else if (currentMode === "gradient") {
      bgStyle = `linear-gradient(90deg, ${c1} 0%, ${c2} 50%, ${c1} 100%)`;
      bgSize = "200% 100%";
      shadowStyle = `0 0 14px ${c1}`;
      animStyle = `barFlow ${dur} infinite linear`;
    } else if (currentMode === "rainbow") {
      bgStyle = `linear-gradient(90deg, #ff0000, #ffff00, #00ff00, #00ffff, #0000ff, #ff00ff, #ff0000)`;
      bgSize = "200% 100%";
      shadowStyle = `0 0 16px rgba(255,255,255,0.4)`;
      animStyle = `barRainbow ${dur} infinite linear`;
    } else if (currentMode === "flashing") {
      bgStyle = c1;
      shadowStyle = `0 0 14px ${c1}`;
      animStyle = `barFlash ${dur} infinite steps(1)`;
    }

    if (previewTxt) previewTxt.textContent = `${currentPower.toUpperCase()} • ${currentMode.toUpperCase()}`;
    if (previewBar) {
      previewBar.style.background = bgStyle;
      previewBar.style.backgroundSize = bgSize;
      previewBar.style.boxShadow = shadowStyle;
      previewBar.style.animation = animStyle;
      previewBar.style.opacity = Math.max(0.2, bri);
    }

    if (stageGlow) {
      stageGlow.style.background = bgStyle;
      stageGlow.style.backgroundSize = bgSize;
      stageGlow.style.boxShadow = shadowStyle;
      stageGlow.style.animation = animStyle;
      stageGlow.style.opacity = Math.max(0.2, bri);
    }
  }

  function updateDynamicCards() {
    if (speedCard) speedCard.style.display = currentMode === "solid" ? "none" : "flex";
    if (secColorCard) secColorCard.style.display = currentMode === "gradient" ? "flex" : "none";
    if (priColorCard) priColorCard.style.display = currentMode === "rainbow" ? "none" : "flex";
    updateLivePreview();
  }

  async function postLed(powerState) {
    updateLivePreview();
    const payload = {
      power: powerState,
      brightness: parseInt(slider ? slider.value : 25, 10),
      color: currentColor,
      color2: currentColor2,
      mode: currentMode,
      speed: parseInt(speedSlider ? speedSlider.value : 50, 10),
      reactive: reactiveToggle ? reactiveToggle.checked : true,
      night_mode: ledNightToggle ? ledNightToggle.checked : false,
      night_start: ledNightStart ? ledNightStart.value : "23:00",
      night_end: ledNightEnd ? ledNightEnd.value : "07:00"
    };
    try {
      const res = await fetch("/api/led", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        currentPower = powerState;
        if (powerBtn) powerBtn.textContent = currentPower === "on" ? "Turn Off" : "Turn On";
        updateLivePreview();
      }
    } catch (err) {}
  }

  async function fetchLedState() {
    try {
      const res = await fetch("/api/led", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        currentPower = data.power || "on";
        currentColor = (data.color || "25c2a0").replace("#", "");
        currentColor2 = (data.color2 || "ff0055").replace("#", "");
        currentMode = data.mode || "solid";

        if (slider) slider.value = data.brightness !== undefined ? data.brightness : 25;
        if (valDisplay && slider) valDisplay.textContent = slider.value + "%";

        if (speedSlider) speedSlider.value = data.speed !== undefined ? data.speed : 50;
        if (speedValDisplay && speedSlider) speedValDisplay.textContent = formatSpeedText(speedSlider.value);

        if (powerBtn) powerBtn.textContent = currentPower === "on" ? "Turn Off" : "Turn On";
        if (reactiveToggle) reactiveToggle.checked = data.reactive !== false;
        if (ledNightToggle) ledNightToggle.checked = Boolean(data.night_mode);
        if (ledNightStart && data.night_start) ledNightStart.value = data.night_start;
        if (ledNightEnd && data.night_end) ledNightEnd.value = data.night_end;

        effectBtns.forEach((b) => b.classList.toggle("active", b.dataset.effect === currentMode));
        colorChips1.forEach((c) => c.classList.toggle("active", c.dataset.hex.toLowerCase() === currentColor.toLowerCase()));
        colorChips2.forEach((c) => c.classList.toggle("active", c.dataset.hex.toLowerCase() === currentColor2.toLowerCase()));

        profilePills.forEach((pill) => {
          const pr = pill.dataset.profile;
          let match = false;
          if (pr === "clean" && currentMode === "solid" && currentColor.toLowerCase() === "25c2a0") match = true;
          else if (pr === "cyberpunk" && currentMode === "gradient" && currentColor.toLowerCase() === "00ffff" && currentColor2.toLowerCase() === "ff0055") match = true;
          else if (pr === "stealth" && currentMode === "solid" && currentColor.toLowerCase() === "001428") match = true;
          else if (pr === "rainbow" && currentMode === "rainbow") match = true;
          pill.classList.toggle("active", match);
        });

        updateDynamicCards();
        updateLivePreview();
      }
    } catch (e) {}
  }

  fetchLedState();

  profilePills.forEach((p) => {
    p.addEventListener("click", () => {
      const pr = p.dataset.profile;
      profilePills.forEach((pill) => pill.classList.toggle("active", pill === p));

      if (pr === "clean") { currentMode = "solid"; currentColor = "25c2a0"; if (slider) slider.value = 25; }
      else if (pr === "cyberpunk") { currentMode = "gradient"; currentColor = "00ffff"; currentColor2 = "ff0055"; if (slider) slider.value = 40; if (speedSlider) speedSlider.value = 65; }
      else if (pr === "stealth") { currentMode = "solid"; currentColor = "001428"; if (slider) slider.value = 8; }
      else if (pr === "rainbow") { currentMode = "rainbow"; if (slider) slider.value = 35; if (speedSlider) speedSlider.value = 70; }
      if (valDisplay && slider) valDisplay.textContent = slider.value + "%";
      if (speedValDisplay && speedSlider) speedValDisplay.textContent = formatSpeedText(speedSlider.value);
      effectBtns.forEach((b) => b.classList.toggle("active", b.dataset.effect === currentMode));
      colorChips1.forEach((c) => c.classList.toggle("active", c.dataset.hex.toLowerCase() === currentColor.toLowerCase()));
      colorChips2.forEach((c) => c.classList.toggle("active", c.dataset.hex.toLowerCase() === currentColor2.toLowerCase()));
      updateDynamicCards();
      postLed("on");
    });
  });

  if (reactiveToggle) reactiveToggle.addEventListener("change", () => postLed(currentPower));
  if (ledNightToggle) ledNightToggle.addEventListener("change", () => postLed(currentPower));
  if (ledNightStart) ledNightStart.addEventListener("change", () => postLed(currentPower));
  if (ledNightEnd) ledNightEnd.addEventListener("change", () => postLed(currentPower));

  if (slider) {
    slider.addEventListener("input", (e) => {
      profilePills.forEach((pill) => pill.classList.remove("active"));
      if (valDisplay) valDisplay.textContent = e.target.value + "%";
      updateLivePreview();
      clearTimeout(briDebounce);
      briDebounce = setTimeout(() => postLed("on"), 75);
    });
  }

  if (speedSlider) {
    speedSlider.addEventListener("input", (e) => {
      profilePills.forEach((pill) => pill.classList.remove("active"));
      if (speedValDisplay) speedValDisplay.textContent = formatSpeedText(e.target.value);
      updateLivePreview();
      clearTimeout(speedDebounce);
      speedDebounce = setTimeout(() => postLed("on"), 75);
    });
  }

  effectBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      profilePills.forEach((pill) => pill.classList.remove("active"));
      effectBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentMode = btn.dataset.effect;
      updateDynamicCards();
      postLed("on");
    });
  });

  colorChips1.forEach((chip) => {
    chip.addEventListener("click", () => {
      profilePills.forEach((pill) => pill.classList.remove("active"));
      colorChips1.forEach((c) => c.classList.remove("active"));
      if (customChip1Label) customChip1Label.classList.remove("active");
      chip.classList.add("active");
      currentColor = chip.dataset.hex;
      postLed("on");
    });
  });

  if (customColorPicker1) {
    customColorPicker1.addEventListener("input", (e) => {
      profilePills.forEach((pill) => pill.classList.remove("active"));
      colorChips1.forEach((c) => c.classList.remove("active"));
      if (customChip1Label) customChip1Label.classList.add("active");
      currentColor = e.target.value.replace("#", "");
      clearTimeout(colorDebounce);
      colorDebounce = setTimeout(() => postLed("on"), 75);
    });
  }

  colorChips2.forEach((chip) => {
    chip.addEventListener("click", () => {
      profilePills.forEach((pill) => pill.classList.remove("active"));
      colorChips2.forEach((c) => c.classList.remove("active"));
      if (customChip2Label) customChip2Label.classList.remove("active");
      chip.classList.add("active");
      currentColor2 = chip.dataset.hex;
      postLed("on");
    });
  });

  if (customColorPicker2) {
    customColorPicker2.addEventListener("input", (e) => {
      profilePills.forEach((pill) => pill.classList.remove("active"));
      colorChips2.forEach((c) => c.classList.remove("active"));
      if (customChip2Label) customChip2Label.classList.add("active");
      currentColor2 = e.target.value.replace("#", "");
      clearTimeout(colorDebounce);
      colorDebounce = setTimeout(() => postLed("on"), 75);
    });
  }

  if (powerBtn) {
    powerBtn.addEventListener("click", () => {
      postLed(currentPower === "on" ? "off" : "on");
    });
  }

  const fanCardsContainer = $("fan-cards-container");
  const fanCardsLockBtn = $("fan-cards-lock-btn");
  const fanPwmSlider = $("fan-pwm-slider");
  const fanPwmValDisplay = $("fan-pwm-val-display");
  const fanProfileBtns = document.querySelectorAll(".fan-profile-btn");
  const manualPwmCard = $("manual-pwm-card");
  const cpuFanToggle = $("cpu-fan-toggle");

  const FAN_STORAGE_KEY = "lcd_fan_card_order";
  const FAN_LOCK_KEY = "lcd_fan_cards_locked";
  let isFanLocked = localStorage.getItem(FAN_LOCK_KEY) !== "false";

  let currentFanProfile = "auto";
  let fanPwmDebounce = null;

  function setFanLockState(locked) {
    isFanLocked = locked;
    localStorage.setItem(FAN_LOCK_KEY, isFanLocked);
    if (fanCardsContainer) fanCardsContainer.classList.toggle("locked", isFanLocked);
    if (fanCardsLockBtn) {
      fanCardsLockBtn.textContent = isFanLocked ? "🔒 Locked" : "🔓 Reorder";
      fanCardsLockBtn.classList.toggle("unlocked", !isFanLocked);
    }
    if (fanCardsContainer) {
      fanCardsContainer.querySelectorAll(".draggable-card").forEach((card) => {
        card.setAttribute("draggable", !isFanLocked);
      });
    }
  }

  function initFanCardReordering() {
    if (!fanCardsContainer) return;
    const savedOrder = JSON.parse(localStorage.getItem(FAN_STORAGE_KEY) || "[]");
    if (savedOrder.length > 0) {
      const cardMap = {};
      fanCardsContainer.querySelectorAll(".draggable-card").forEach((c) => { 
        cardMap[c.dataset.fanCardId] = c; 
      });
      savedOrder.forEach((id) => { 
        if (cardMap[id]) fanCardsContainer.appendChild(cardMap[id]); 
      });
    }

    let draggedFanCard = null;
    let allowFanDrag = false;

    fanCardsContainer.addEventListener("mousedown", (e) => {
      allowFanDrag = !isFanLocked && !!e.target.closest(".drag-handle");
    });

    fanCardsContainer.querySelectorAll(".draggable-card").forEach((card) => {
      card.addEventListener("dragstart", (e) => {
        if (isFanLocked || !allowFanDrag) { e.preventDefault(); return false; }
        draggedFanCard = card;
        card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.dataset.fanCardId);
      });

      card.addEventListener("dragend", () => {
        allowFanDrag = false;
        card.classList.remove("dragging");
        fanCardsContainer.querySelectorAll(".draggable-card").forEach((c) => c.classList.remove("drag-over"));
        const order = Array.from(fanCardsContainer.querySelectorAll(".draggable-card")).map((c) => c.dataset.fanCardId);
        localStorage.setItem(FAN_STORAGE_KEY, JSON.stringify(order));
      });

      card.addEventListener("dragover", (e) => {
        if (isFanLocked) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const targetCard = e.target.closest(".draggable-card");
        if (targetCard && targetCard !== draggedFanCard) {
          const rect = targetCard.getBoundingClientRect();
          const next = (e.clientY - rect.top) / (rect.bottom - rect.top) > 0.5;
          fanCardsContainer.insertBefore(draggedFanCard, next && targetCard.nextSibling || targetCard);
        }
      });
    });

    if (fanCardsLockBtn) fanCardsLockBtn.addEventListener("click", () => setFanLockState(!isFanLocked));
    setFanLockState(isFanLocked);
  }

  initFanCardReordering();


  loadButtonConfig();

  function updateFanUiState(profile, pct) {
    currentFanProfile = profile;
    fanProfileBtns.forEach((b) => b.classList.toggle("active", b.dataset.fanProfile === profile));
    
    if (manualPwmCard) {
      manualPwmCard.classList.toggle("manual-override-disabled", profile === "auto");
    }
    if (fanPwmValDisplay) {
      fanPwmValDisplay.textContent = (profile === "auto") ? "Auto Curve" : (pct + "%");
    }
    if (fanPwmSlider && profile !== "auto") {
      fanPwmSlider.value = pct;
    }
  }

            let fanThreshDebounce = null;

  async function postFanPwm(profile, manualPct, ctrlCpu, tMin, tMax, cPoints) {
    const curMin = tMin !== undefined ? tMin : 37;
    const curMax = tMax !== undefined ? tMax : 50;
    const mPct = (manualPct === null || manualPct === undefined) ? (fanPwmSlider ? fanPwmSlider.value : 60) : manualPct;
    try {
      const res = await fetch("/api/fans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          profile: profile, 
          manual_pct: mPct, 
          ctrl_cpu_fan: ctrlCpu !== undefined ? ctrlCpu : (cpuFanToggle ? cpuFanToggle.checked : false),
          temp_min: curMin,
          temp_max: curMax,
          curve_points: cPoints || curvePoints
        })
      });
      if (res.ok) {
        const data = await res.json();
        updateFanUiState(data.profile, data.manual_pct);
        tick();
      }
    } catch (e) {}
  }

  async function fetchFanState() {
    try {
      const res = await fetch("/api/fans", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        const prof = data.profile || "auto";
        const pct = data.manual_pct !== undefined ? data.manual_pct : 60;
        const tMin = data.temp_min !== undefined ? data.temp_min : 37;
        const tMax = data.temp_max !== undefined ? data.temp_max : 50;

        if (cpuFanToggle) cpuFanToggle.checked = !!data.ctrl_cpu_fan;
        // Load curve points if saved
        if (data.curve_points && data.curve_points.length > 0) {
          curvePoints = data.curve_points;
        } else {
          curvePoints = [[30, 32], [tMin, 32], [tMax, 100], [60, 100]];
        }
        renderCurveLines();
        // Update the badge showing temp range
        const crv = document.getElementById("fan-curve-range-val");
        if (crv) crv.textContent = `${tMin}°C – ${tMax}°C`;

        updateFanUiState(prof, pct);
      }
    } catch (e) {}
  }

  fetchFanState();



  if (cpuFanToggle) {
    cpuFanToggle.addEventListener("change", (e) => {
      postFanPwm(currentFanProfile, parseInt(fanPwmSlider ? fanPwmSlider.value : 60, 10), e.target.checked);
    });
  }

  fanProfileBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const pr = btn.dataset.fanProfile;
      const map = { auto: 60, quiet: 37, balanced: 66, performance: 85, full: 100 };
      const pct = map[pr] || 60;
      updateFanUiState(pr, pct);
      postFanPwm(pr, pct);
    });
  });

  if (fanPwmSlider) {
    fanPwmSlider.addEventListener("input", (e) => {
      const val = parseInt(e.target.value, 10);
      updateFanUiState("manual", val);
      clearTimeout(fanPwmDebounce);
      fanPwmDebounce = setTimeout(() => postFanPwm("manual", val), 120);
    });
  }

  window.addEventListener("keydown", (e) => {
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
    if (activeTag === "input" || activeTag === "select" || activeTag === "textarea") {
      if (e.key === "Escape") document.activeElement.blur();
      return;
    }

    if (e.key === "Escape") {
      ZettEventBus.dispatchEvent(new CustomEvent('modal:smart:close'));
      closeDrawer();
    } else if (e.key === "z" || e.key === "Z") {
      cycleZoom();
    } else if (e.key === "y" || e.key === "Y") {
      applyTheme(currentTheme === "yak" ? "cyber" : "yak");
    } else if (e.key === "t" || e.key === "T" || e.key === "d" || e.key === "D") {
      if (drawer && drawer.classList.contains("open")) {
        closeDrawer();
      } else {
        openDrawer();
      }
    } else if (e.key === "l" || e.key === "L") {
      const chips = Array.from(colorChips1);
      if (chips.length > 0) {
        let activeIdx = chips.findIndex((c) => c.classList.contains("active"));
        let nextIdx = (activeIdx + 1) % chips.length;
        chips[nextIdx].click();
      }
    }
  });

  window.addEventListener("resize", fitMiniPreviewScale);


  // ---- INTERACTIVE FAN CURVE EDITOR EVENTS ----
  // renderCurveLines, curvePoints, isDraggingCurve are defined at top-level

  // Initial render after DOM is settled
  setTimeout(renderCurveLines, 400);

  const fanCurveSvg = document.querySelector(".fan-curve-svg");
  if (fanCurveSvg) {
    fanCurveSvg.addEventListener("mousedown", (e) => {
      if (e.target.classList.contains("curve-handle")) {
        isDraggingCurve = true;
        dragIndex = parseInt(e.target.id.replace("ch-", ""), 10);
      }
    });

    fanCurveSvg.addEventListener("touchstart", (e) => {
      const touch = e.target;
      if (touch.classList.contains("curve-handle")) {
        isDraggingCurve = true;
        dragIndex = parseInt(touch.id.replace("ch-", ""), 10);
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

        // prevent crossing neighbours
        if (dragIndex > 0) t = Math.max(t, curvePoints[dragIndex - 1][0] + 1);
        if (dragIndex < curvePoints.length - 1) t = Math.min(t, curvePoints[dragIndex + 1][0] - 1);

        curvePoints[dragIndex] = [t, p];
        renderCurveLines();
      });
    }

    window.addEventListener("mousemove", onCurveMove);
    window.addEventListener("touchmove", onCurveMove, { passive: false });

    function onCurveUp() {
      if (!isDraggingCurve) return;
      dragIndex = -1;
      _lastCurveSaveTime = Date.now(); // start 5s cooldown against stale server data
      const savedPoints = curvePoints.map(p => [...p]);
      postFanPwm(currentFanProfile, null, undefined, undefined, undefined, savedPoints)
        .finally(() => {
          curvePoints = savedPoints;
          isDraggingCurve = false;
        });
    }
    window.addEventListener("mouseup", onCurveUp);
    window.addEventListener("touchend", onCurveUp);
  }
  // ---- END INTERACTIVE FAN CURVE EDITOR ----



// Hardware Buttons UI
  const btnCopyToggle = $("btn-copy-toggle");
  const btnCopyOptions = $("btn-copy-options");
  const btnCopySrc = $("btn-copy-src");
  const btnCopyDst = $("btn-copy-dst");
  const btnCopyExif = $("btn-copy-exif");
  const btnCopySave = $("btn-copy-save");

  async function loadButtonConfig() {
    try {
      const res = await fetch("/api/buttons");
      if (res.ok) {
        const data = await res.json();
        if (btnCopyToggle) btnCopyToggle.checked = !!data.enabled;
        if (btnCopySrc) btnCopySrc.value = data.source || "sd";
        if (btnCopyDst) btnCopyDst.value = data.dest || "/mnt/user/";
        if (btnCopyExif) btnCopyExif.checked = data.use_exif !== false;
        
        if (btnCopyOptions) {
          btnCopyOptions.style.opacity = data.enabled ? "1" : "0.3";
          btnCopyOptions.style.pointerEvents = data.enabled ? "auto" : "none";
          btnCopyOptions.style.transition = "opacity 0.2s ease";
        }
        const statusText = $("btn-copy-status-text");
        if (statusText) {
          statusText.textContent = data.enabled ? "ENABLED" : "DISABLED";
          statusText.style.color = data.enabled ? "#2ecc71" : "inherit";
        }
      }
    } catch (e) {}
  }

  if (btnCopyToggle) {
    btnCopyToggle.addEventListener("change", (e) => {
      const isEnabled = e.target.checked;
      if (btnCopyOptions) {
        btnCopyOptions.style.opacity = isEnabled ? "1" : "0.3";
        btnCopyOptions.style.pointerEvents = isEnabled ? "auto" : "none";
      }
      const statusText = $("btn-copy-status-text");
      if (statusText) {
        statusText.textContent = isEnabled ? "ENABLED" : "DISABLED";
        statusText.style.color = isEnabled ? "#2ecc71" : "inherit";
      }
      if (btnCopySave) { btnCopySave.click(); } else { saveButtonConfig(); }
    });
  }

  if (btnCopySave) {
    btnCopySave.addEventListener("click", async (e) => {
      btnCopySave.textContent = "Saving...";
      await saveButtonConfig(e);
      if (btnCopySave.textContent === "Saving...") {
        btnCopySave.textContent = "Saved!";
        setTimeout(() => { if (btnCopySave) btnCopySave.textContent = "💾 Save Configuration"; }, 2000);
      }
    });
  }

  
  if (btnCopySrc) btnCopySrc.addEventListener("change", () => { if (btnCopySave) btnCopySave.click(); else saveButtonConfig(); });
  if (btnCopyExif) btnCopyExif.addEventListener("change", () => { if (btnCopySave) btnCopySave.click(); else saveButtonConfig(); });
  if (btnCopyDst) {
    btnCopyDst.addEventListener("change", saveButtonConfig);
    btnCopyDst.addEventListener("input", () => {
      clearTimeout(window._btnCopyTimer);
      window._btnCopyTimer = setTimeout(() => { if (btnCopySave) btnCopySave.click(); else saveButtonConfig(); }, 1000);
    });
  }

  async function saveButtonConfig(e) {
    try {
      const res = await fetch("/api/buttons", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: btnCopyToggle ? btnCopyToggle.checked : false,
          source: btnCopySrc ? btnCopySrc.value : "sd",
          dest: btnCopyDst ? btnCopyDst.value : "/mnt/user/",
          use_exif: btnCopyExif ? btnCopyExif.checked : true
        })
      });
      if (!res.ok) {
        const err = await res.json();
        showToast("Config Error: " + (err.error || "Invalid path"), "error");
        
        // Re-load the last valid config from the server to reset the UI
        loadButtonConfig();
        
        // If triggered by the Save Button click (has target), reset button text
        if (e && e.target && e.target.id === "copy-save-btn") {
            e.target.textContent = "💾 Save Configuration";
        }
      }
    } catch (e) {
      showToast("Network Error: " + e, "error");
    }
  }

  loadButtonConfig();


  // Folder browser extracted to js/folder-browser.js
})();



let _lastEventHash = "";
let _expandedEvents = new Set();

function renderEventLog(events) {
  const list = $("events-list");
  if (!list) return;
  
  const currentHash = events ? (events.length + "-" + (events[0] ? events[0].ts : 0)) : "empty";
  if (_lastEventHash === currentHash) return; // Skip DOM rebuild if data hasn't changed
  _lastEventHash = currentHash;

  if (!events || events.length === 0) {
    list.innerHTML = `<div style="padding: 14px; text-align: center; color: var(--muted); font-size: 11px;">No events logged yet.</div>`;
    return;
  }
  
  // Clear list to attach event listeners properly
  list.innerHTML = "";
  
  events.forEach(e => {
    const dt = new Date(e.ts * 1000);
    const timeStr = dt.toLocaleString();
    let color = "#e2e8f0";
    let icon = "ℹ️";
    if (e.level === "error") { color = "var(--crit)"; icon = "❌"; }
    else if (e.level === "warning") { color = "var(--warn)"; icon = "⚠️"; }
    else if (e.level === "success") { color = "var(--ok2)"; icon = "✅"; }
    
    const row = document.createElement("div");
    row.style.cssText = "padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; gap: 8px;";
    
    row.style.cursor = "pointer";
    row.onmouseover = () => row.style.background = "rgba(255,255,255,0.02)";
    row.onmouseout = () => row.style.background = "transparent";

    let topHtml = `
      <div style="display: flex; gap: 10px; align-items: flex-start;">
        <span style="font-size: 14px; margin-top: 2px;">${icon}</span>
        <div style="display: flex; flex-direction: column; gap: 4px; flex-grow: 1;">
          <div style="font-size: 11px; color: ${color}; font-weight: 700; letter-spacing: 0.3px;">${e.title}</div>
          <div style="font-size: 12px; color: #fff;">${e.message}</div>
          <div style="font-size: 10px; color: var(--muted);">${timeStr}</div>
        </div>
        <span style="font-size: 10px; color: var(--muted); padding-top: 4px;">▼ Details</span>
      </div>
    `;
    
    row.innerHTML = topHtml;
    
    const detailsBox = document.createElement("pre");
    detailsBox.style.cssText = "display: none; margin: 0; padding: 10px; background: rgba(0,0,0,0.4); border-radius: 6px; font-size: 10px; color: #a0aec0; border: 1px solid rgba(255,255,255,0.05); white-space: pre-wrap; word-break: break-all;";
    detailsBox.textContent = JSON.stringify(e, null, 2);
    row.appendChild(detailsBox);
    
    const evKey = e.ts + "_" + e.title;
    if (_expandedEvents.has(evKey)) {
      detailsBox.style.display = "block";
    }

    row.addEventListener("click", () => {
      const isHidden = detailsBox.style.display === "none";
      detailsBox.style.display = isHidden ? "block" : "none";
      if (isHidden) {
        _expandedEvents.add(evKey);
      } else {
        _expandedEvents.delete(evKey);
      }
    });
    
    list.appendChild(row);
  });
}

window.addEventListener("DOMContentLoaded", () => {
  const rs = document.getElementById("metrics-range-select");
  if (rs) {
    rs.addEventListener("change", (e) => {
      _metricsRange = e.target.value;
      fetchAndRenderMetrics();
    });
  }
});



ZettEventBus.addEventListener('folder_selected', (e) => { 
    const el = document.getElementById('btn-copy-dst'); 
    if(el) {
        el.value = e.detail;
        // Trigger save automatically
        const saveBtn = document.getElementById('btn-copy-save');
        if (saveBtn) saveBtn.click();
    }
});


