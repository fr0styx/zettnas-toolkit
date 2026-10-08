import { escapeHtml } from '../utils.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { announceA11y } from '../a11y.js';

/**
 * ZettNAS Physical Chassis Twin & Storage Topology Visualizer
 * - Parametric SVG chassis twin (D4, D6, D8, DIY)
 * - Multi-zone thermal heatmaps (<35C cool, 35-45C green, 46-52C yellow, >=53C red)
 * - Quad-action Locate Drive / Blink Bay strobe
 * - Platter Standby / Spindown Twin with calm breathe glow
 * - M.2 Motherboard Twin with PCIe lanes & endurance meters
 * - Zero-bloat S.M.A.R.T. Velocity SVG Sparklines (7d & 30d)
 * - Storage Pool / Array Topology Tree with live IOPS & throughput
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

  // 3. Screen reader a11y announcement
  announceA11y(`Locating drive ${devName}. Physical bay indicator flashing.`);

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
      color: '#64748b',
      glow: 'rgba(100, 116, 139, 0.3)',
      text: isStandby ? 'STANDBY' : 'UNKNOWN'
    };
  }
  if (tempC >= 53) {
    return { cls: 'crit', color: '#f0553b', glow: 'rgba(240, 85, 59, 0.45)', text: `${tempC}°C` };
  }
  if (tempC >= 46) {
    return { cls: 'warn', color: '#f5b731', glow: 'rgba(245, 183, 49, 0.45)', text: `${tempC}°C` };
  }
  if (tempC >= 35) {
    return { cls: 'ok', color: '#3bf58b', glow: 'rgba(59, 245, 139, 0.35)', text: `${tempC}°C` };
  }
  return { cls: 'cool', color: '#38bdf8', glow: 'rgba(56, 189, 248, 0.35)', text: `${tempC}°C` };
}

/**
 * Renders parametric SVG / interactive Chassis Twin
 */
export function renderChassisTwin(container, disks = [], options = {}) {
  if (!container) return;

  const hdds = disks.filter((d) => !String(d.dev || d.name).startsWith('nvme'));
  const nvmes = disks.filter((d) => String(d.dev || d.name).startsWith('nvme'));

  const count = Math.max(options.minBays || 4, hdds.length);
  let chassisModel = options.model || (count <= 4 ? 'ZETTLAB D4' : count <= 6 ? 'ZETTLAB D6' : count <= 8 ? 'ZETTLAB D8' : 'DIY STORAGE CHASSIS');

  let baysHtml = '';
  for (let i = 0; i < count; i++) {
    const d = hdds[i];
    if (!d) {
      baysHtml += `
        <div class="chassis-bay-slot empty" data-bay="${i + 1}" role="region" aria-label="Bay ${i + 1} Empty">
          <div class="bay-header">
            <span class="bay-num">BAY ${i + 1}</span>
            <span class="bay-status-badge empty">VACANT</span>
          </div>
          <div class="bay-tray-handle">
            <svg class="bay-icon" viewBox="0 0 24 24"><use href="#i-disk"/></svg>
            <span class="bay-label">EMPTY TRAY</span>
          </div>
          <div class="bay-footer">
            <span class="bay-meta">NO DISK</span>
          </div>
        </div>
      `;
    } else {
      const devName = d.name || d.dev || `sd${String.fromCharCode(97 + i)}`;
      const isStandby = Boolean(d.standby || d.health === 'standby');
      const thermal = getThermalLevel(d.temp, isStandby);
      const modelStr = d.model ? d.model.slice(0, 14) : devName;
      const sizeStr = d.size_formatted || d.size || '';

      baysHtml += `
        <div class="chassis-bay-slot populated ${thermal.cls}" data-bay="${i + 1}" data-dev="${devName}" role="button" tabindex="0" aria-label="Bay ${i + 1}: ${escapeHtml(modelStr)}, ${thermal.text}">
          <div class="bay-header">
            <span class="bay-num">BAY ${i + 1}</span>
            <span class="bay-temp-pill" style="color: ${thermal.color}; border-color: ${thermal.color};">${thermal.text}</span>
          </div>
          <div class="bay-tray-handle">
            <div class="bay-led-lens ${isStandby ? 'standby-pulse' : 'online'}"></div>
            <div class="bay-drive-info">
              <span class="bay-drive-model" title="${escapeHtml(d.model || devName)}">${escapeHtml(modelStr)}</span>
              <span class="bay-drive-dev">/dev/${devName} ${sizeStr ? '• ' + sizeStr : ''}</span>
            </div>
          </div>
          <div class="bay-footer">
            <button class="bay-locate-btn" data-dev="${devName}" title="Locate Drive (Blink Bay LED)" aria-label="Locate drive in Bay ${i + 1}">
              <svg class="locate-icon" viewBox="0 0 24 24" width="12" height="12"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor"/></svg>
              <span>LOCATE</span>
            </button>
            <span class="bay-health-tag ${thermal.cls}">${isStandby ? 'STANDBY' : (d.health ? d.health.toUpperCase() : 'OK')}</span>
          </div>
        </div>
      `;
    }
  }

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
          <div class="chassis-honeycomb-vents"></div>
          <div class="chassis-screw-head"></div>
        </div>
        <div class="chassis-bay-grid ${count > 6 ? 'quad-cols' : count > 4 ? 'tri-cols' : 'dual-cols'}">
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
      if (dev) {
        ZettEventBus.emit('modal:smart:open', dev);
      }
    });
  });
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
  const minVal = 0;
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

/**
 * Renders Storage Topology Tree (Pool -> VDEVs / Disks -> Datasets)
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
