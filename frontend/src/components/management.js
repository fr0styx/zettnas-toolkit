import { syncWidgetSettingsUI } from './widgets.js';
import { syncDesktopThemeUI } from './settings.js';
import { openContainerInspector } from './container-modal.js';
/**
 * ZettNAS Toolkit - System Management Window Controller
 * Manages the dedicated System Management desktop window, hub app grid,
 * category navigation, and card views (Wallpaper, Metrics, Events, Security).
 */
import { fetchAndRenderMetrics } from './metrics-chart.js';
import { bringToFront, DockManager, makeDraggable } from './dock.js';
import { state } from '../state.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { trapFocus, escapeHtml } from '../utils.js';
import { t, getLanguage } from '../i18n.js';

let _activeProfile = 'balanced';
let _unbindMgmtTrap = null;

export function updateManagementTelemetry(stats) {
  if (!stats) return;
  const overlay = document.getElementById('management-modal-overlay');
  if (overlay && (!overlay.classList.contains('open') || overlay.classList.contains('window-minimized') || overlay.style.display === 'none')) {
    return;
  }
  const unraid = stats.unraid;
  if (unraid && unraid.available) {
    const stateEl = document.getElementById('mgmt-unraid-state');
    const srvEl = document.getElementById('mgmt-unraid-server');
    const verEl = document.getElementById('mgmt-unraid-version');
    const disksEl = document.getElementById('mgmt-unraid-disks');
    const parityEl = document.getElementById('mgmt-unraid-parity');
    const moverEl = document.getElementById('mgmt-unraid-mover');

    if (stateEl) {
      stateEl.textContent = unraid.state;
      stateEl.style.color = unraid.color?.startsWith('green') ? 'var(--ok2)' : 'var(--warn)';
    }
    if (srvEl) srvEl.textContent = `${unraid.server_name || 'NAS'} (${unraid.model || stats.chassis?.model || 'D6U'})`;
    if (verEl) verEl.textContent = `Unraid ${unraid.version || ''}`;
    if (disksEl) {
      const d = unraid.disks || {};
      disksEl.textContent = `${d.total || 0} Disks (${d.disabled || 0} disabled, ${d.invalid || 0} invalid)`;
    }
    if (parityEl) {
      const p = unraid.parity_check || {};
      if (p.active) {
        parityEl.textContent = `Active (${p.action || 'Sync'} ${p.progress_pct || 0}%) • ${p.errors || 0} Errors`;
        parityEl.style.color = 'var(--accent-cyan,#00f0ff)';
      } else {
        parityEl.textContent = `Completed / Idle • ${p.errors || 0} Errors`;
        parityEl.style.color = 'var(--ok2)';
      }
    }
    if (moverEl) {
      const m = unraid.mover || {};
      if (m.active) {
        moverEl.textContent = `Active (${m.remain_files || 0} files left)`;
        moverEl.style.color = 'var(--warn)';
      } else {
        moverEl.textContent = 'Idle';
        moverEl.style.color = 'var(--muted)';
      }
    }
  }

  // Update Docker pill in Hub and Left Sidebar
  if (stats.docker && Array.isArray(stats.docker)) {
    const runningCount = stats.docker.filter(c => c.state === 'running').length;
    const dockPill = document.getElementById('mgmt-hub-docker-pill');
    if (dockPill) dockPill.textContent = `${runningCount} Active`;
    const sideDockBadge = document.getElementById('mgmt-sidebar-docker-badge');
    if (sideDockBadge) sideDockBadge.textContent = `${runningCount} Active`;
  }

  // Update UPS pill, sidebar badge, and telemetry if active
  if (stats.ups) {
    const upsVal = stats.ups.battery_charge_pct != null ? `${stats.ups.battery_charge_pct}%` : (stats.ups.available ? 'Active' : 'Offline');
    const upsPill = document.getElementById('mgmt-hub-ups-pill');
    if (upsPill) upsPill.textContent = upsVal;
    const sideUpsBadge = document.getElementById('mgmt-sidebar-ups-badge');
    if (sideUpsBadge) sideUpsBadge.textContent = upsVal;

    const statusEl = document.getElementById('mgmt-ups-status');
    const modelEl = document.getElementById('mgmt-ups-model');
    const chargeEl = document.getElementById('mgmt-ups-charge');
    const runtimeEl = document.getElementById('mgmt-ups-runtime');
    const loadEl = document.getElementById('mgmt-ups-load');
    const linevEl = document.getElementById('mgmt-ups-linev');

    if (statusEl) {
      statusEl.textContent = stats.ups.status || (stats.ups.available ? 'ONLINE' : 'Offline');
      statusEl.style.color = stats.ups.available ? 'var(--ok2)' : 'var(--warn)';
    }
    if (modelEl) modelEl.textContent = stats.ups.model || 'Generic UPS';
    if (chargeEl) {
      chargeEl.textContent = stats.ups.battery_charge_pct != null ? `${stats.ups.battery_charge_pct}%` : 'N/A';
      chargeEl.style.color = (stats.ups.battery_charge_pct == null || stats.ups.battery_charge_pct > 30) ? 'var(--ok2)' : 'var(--crit)';
    }
    if (runtimeEl) runtimeEl.textContent = stats.ups.time_left_min != null ? `${stats.ups.time_left_min} min` : 'N/A';
    if (loadEl) loadEl.textContent = stats.ups.load_pct != null ? `${stats.ups.load_pct}%` : 'N/A';
    if (linevEl) linevEl.textContent = stats.ups.line_volts != null ? `${stats.ups.line_volts} V` : 'N/A';
  }

  if (stats.fan_control && stats.fan_control.profile) {
    const prof = stats.fan_control.profile.toLowerCase();
    if (['auto', 'quiet', 'balanced', 'performance'].includes(prof) && prof !== _activeProfile) {
      _activeProfile = prof;
      document.querySelectorAll('.profile-btn').forEach((b) => {
        b.classList.toggle('active', b.dataset.profile === prof);
      });
    }
    const currentPill = document.getElementById('unraid-profile-current-pill');
    if (currentPill) {
      currentPill.textContent = `ACTIVE: ${prof === 'auto' ? 'AUTO DYNAMIC' : prof.toUpperCase()}`;
      currentPill.style.color = prof === 'performance' ? 'var(--warn)' : 'var(--ok2)';
    }
  }
}

let _dockerContainersList = [];
let _dockerFilter = 'all';
let _dockerSearchQuery = '';

let _catalogList = [];
let _catalogCat = 'all';
let _catalogSearchQuery = '';

export function _resetDockerStateForTesting() {
  _dockerContainersList = [];
  _dockerFilter = 'all';
  _dockerSearchQuery = '';
}

export function _resetCatalogStateForTesting() {
  _catalogList = [];
  _catalogCat = 'all';
  _catalogSearchQuery = '';
}

function _bindDockerEvents() {
  const containerPane = document.getElementById('mgmt-pane-docker');
  if (!containerPane || containerPane._dockerEventsBound) return;

  const searchInput = document.getElementById('docker-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      _dockerSearchQuery = (e.target.value || '').trim().toLowerCase();
      renderDockerContainersTable();
    });
  }

  const filterBtns = containerPane.querySelectorAll('.docker-filter-btn');
  filterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      filterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _dockerFilter = btn.dataset.filter || 'all';
      renderDockerContainersTable();
    });
  });

  // Toggle between Containers Table and App Catalog
  const btnContainers = document.getElementById('btn-view-docker-containers');
  const btnCatalog = document.getElementById('btn-view-docker-catalog');
  const wrapContainers = document.getElementById('docker-view-containers-wrap');
  const wrapCatalog = document.getElementById('docker-view-catalog-wrap');

  if (btnContainers && btnCatalog) {
    btnContainers.addEventListener('click', () => {
      btnContainers.classList.add('active');
      btnCatalog.classList.remove('active');
      if (wrapContainers) wrapContainers.style.display = 'block';
      if (wrapCatalog) wrapCatalog.style.display = 'none';
    });
    btnCatalog.addEventListener('click', () => {
      btnCatalog.classList.add('active');
      btnContainers.classList.remove('active');
      if (wrapContainers) wrapContainers.style.display = 'none';
      if (wrapCatalog) wrapCatalog.style.display = 'block';
      fetchAndRenderAppCatalog();
    });
  }

  // Catalog category filter pills
  const catFilterBtns = containerPane.querySelectorAll('.catalog-filter-btn');
  catFilterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      catFilterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _catalogCat = btn.dataset.cat || 'all';
      renderAppCatalogGrid();
    });
  });

  // Catalog search input
  const catSearchInput = document.getElementById('catalog-search-input');
  if (catSearchInput) {
    catSearchInput.addEventListener('input', (e) => {
      _catalogSearchQuery = (e.target.value || '').trim().toLowerCase();
      renderAppCatalogGrid();
    });
  }

  containerPane._dockerEventsBound = true;
}

export function renderDockerContainersTable() {
  const tbody = document.getElementById('docker-containers-tbody');
  if (!tbody) return;

  // Compute counts
  const totalCount = _dockerContainersList.length;
  const runningCount = _dockerContainersList.filter((c) => c.state === 'running').length;
  const stoppedCount = _dockerContainersList.filter((c) => c.state !== 'running').length;
  const composeCount = _dockerContainersList.filter((c) => c.managed_by === 'compose' || Boolean(c.stack)).length;
  const standaloneCount = _dockerContainersList.filter((c) => c.managed_by !== 'compose' && !c.stack).length;

  const cAll = document.getElementById('docker-count-all');
  if (cAll) cAll.textContent = totalCount;
  const cRun = document.getElementById('docker-count-running');
  if (cRun) cRun.textContent = runningCount;
  const cStop = document.getElementById('docker-count-stopped');
  if (cStop) cStop.textContent = stoppedCount;
  const cComp = document.getElementById('docker-count-compose');
  if (cComp) cComp.textContent = composeCount;
  const cStand = document.getElementById('docker-count-standalone');
  if (cStand) cStand.textContent = standaloneCount;

  const pill = document.getElementById('mgmt-hub-docker-pill');
  if (pill) pill.textContent = `${runningCount} Active`;
  const sideBadge = document.getElementById('mgmt-sidebar-docker-badge');
  if (sideBadge) sideBadge.textContent = `${runningCount} Active`;

  if (totalCount === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:20px;">${t('mgmt.docker_none', 'No Docker containers detected or socket not connected.')}</td></tr>`;
    return;
  }

  // Filter list
  const filtered = _dockerContainersList.filter((c) => {
    // Check tab filter
    if (_dockerFilter === 'running' && c.state !== 'running') return false;
    if (_dockerFilter === 'stopped' && c.state === 'running') return false;
    if (_dockerFilter === 'compose' && c.managed_by !== 'compose' && !c.stack) return false;
    if (_dockerFilter === 'standalone' && (c.managed_by === 'compose' || Boolean(c.stack))) return false;

    // Check search query
    if (_dockerSearchQuery) {
      const q = _dockerSearchQuery;
      const matchName = (c.name || '').toLowerCase().includes(q);
      const matchImage = (c.image || '').toLowerCase().includes(q);
      const matchStack = (c.stack || '').toLowerCase().includes(q);
      const matchService = (c.service || '').toLowerCase().includes(q);
      const matchPort = (c.ports || []).some(
        (p) => String(p.public_port).includes(q) || String(p.private_port).includes(q)
      );
      if (!matchName && !matchImage && !matchStack && !matchService && !matchPort) {
        return false;
      }
    }
    return true;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:20px;">${t('mgmt.docker_no_matching', 'No containers match your search or filter.')}</td></tr>`;
    return;
  }

  const currentHost = typeof window !== 'undefined' && window.location.hostname ? window.location.hostname : 'localhost';

  tbody.innerHTML = filtered
    .map((c) => {
      const isRunning = c.state === 'running';
      const badgeColor = isRunning ? 'var(--ok2)' : 'var(--muted)';
      const badgeBg = isRunning ? 'rgba(37, 194, 160, 0.15)' : 'rgba(255, 255, 255, 0.05)';
      const idShort = c.id ? c.id.slice(0, 12) : '';

      // Column 1: Stack & Name
      let stackHtml = '';
      if (c.stack) {
        stackHtml = `<span class="docker-stack-pill" title="Compose Stack: ${escapeHtml(c.stack)}">📁 ${escapeHtml(c.stack)}</span>`;
      } else {
        const originLabel = c.managed_by === 'unraid' ? 'Unraid' : 'Standalone';
        stackHtml = `<span class="docker-origin-pill">${originLabel}</span>`;
      }

      // Column 2: Hardware Badges
      let hwHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
      if (c.hardware_badges && c.hardware_badges.length > 0) {
        hwHtml = c.hardware_badges
          .map(
            (b) =>
              `<span class="docker-hw-badge docker-hw-${escapeHtml(b.id)}" title="${escapeHtml(b.label)}">${escapeHtml(b.label)}</span>`
          )
          .join('');
      }

      // Column 3: Telemetry (CPU / RAM)
      let telemHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
      if (isRunning) {
        const cpuStr = `${(c.cpu_pct || 0).toFixed(1)}%`;
        const memStr = c.mem_used ? `${(c.mem_used / (1024 * 1024)).toFixed(0)} MB` : '--';
        telemHtml = `<span class="docker-telemetry-pill"><span class="telem-cpu">${cpuStr}</span><span style="opacity:0.4;">•</span><span class="telem-mem">${memStr}</span></span>`;
      }

      // Column 4: Ports & Web UI
      let portsHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
      const portParts = [];
      if (c.webui_url && c.primary_port) {
        const resolvedUrl = c.webui_url.replace('[HOST]', currentHost);
        portParts.push(
          `<a href="${escapeHtml(resolvedUrl)}" target="_blank" rel="noopener noreferrer" class="btn-webui-badge" title="Open Web UI (Port ${c.primary_port})">🌐 :${c.primary_port} ↗</a>`
        );
      }
      // Additional public ports
      const otherPorts = (c.ports || []).filter(
        (p) => p.public_port && p.public_port !== c.primary_port
      );
      if (otherPorts.length > 0) {
        const otherTags = otherPorts
          .slice(0, 3)
          .map((p) => `<span class="docker-port-tag">:${p.public_port}</span>`)
          .join('');
        portParts.push(otherTags);
      }
      if (portParts.length > 0) {
        portsHtml = portParts.join(' ');
      }

      // Column 5: Status & Uptime
      const statusHtml = `
        <div style="display:flex; align-items:center; gap:6px;">
          <span style="display:inline-block; padding:2px 6px; border-radius:4px; font-size:9.5px; font-weight:700; background:${badgeBg}; color:${badgeColor}; text-transform:uppercase;">${escapeHtml(c.state)}</span>
          <span style="font-size:10px; color:#cbd5e1; max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
        </div>
      `;

      // Column 6: Actions
      const inspectBtn = `<button class="btn-container-act btn-docker-inspect" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="inspect" title="Inspect ${escapeHtml(c.name)}">🔍</button>`;
      const actions = isRunning
        ? `
          ${inspectBtn}
          <button class="btn-container-act btn-docker-restart" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="restart" title="Restart ${escapeHtml(c.name)}">🔄</button>
          <button class="btn-container-act btn-docker-stop" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="stop" title="Stop ${escapeHtml(c.name)}">⏹</button>
        `
        : `
          ${inspectBtn}
          <button class="btn-container-act btn-docker-start" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="start" title="Start ${escapeHtml(c.name)}">▶</button>
        `;

      return `
        <tr>
          <td>
            <div style="display:flex; align-items:baseline; gap:6px;">
              <button class="btn-docker-name-link" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" style="background:none; border:none; padding:0; color:#fff; font-size:11.5px; font-weight:700; cursor:pointer; text-align:left; font-family:inherit;" title="Inspect ${escapeHtml(c.name)}">${escapeHtml(c.name)}</button>
              <code style="font-size:9px; color:var(--muted); font-family:var(--font-mono, monospace);">${escapeHtml(idShort)}</code>
            </div>
            <div>${stackHtml}</div>
          </td>
          <td>${hwHtml}</td>
          <td>${telemHtml}</td>
          <td>${portsHtml}</td>
          <td>${statusHtml}</td>
          <td style="text-align:right; white-space:nowrap;">${actions}</td>
        </tr>
      `;
    })
    .join('');

  // Wire container action buttons
  tbody.querySelectorAll('.btn-container-act').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const cid = btn.dataset.id;
      const cname = btn.dataset.name;
      const act = btn.dataset.action;
      if (!cid || !act) return;

      if (act === 'inspect') {
        openContainerInspector(cid, cname);
        return;
      }

      btn.disabled = true;
      btn.style.opacity = '0.5';
      showToast(`${act.toUpperCase()} request sent for ${cname}...`, 'info');

      try {
        await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: act });
        showToast(`Container "${cname}" successfully ${act}ed.`, 'success');
        await fetchAndRenderDockerContainers();
      } catch (err) {
        showToast(`Failed to ${act} container: ${err.message}`, 'error');
        btn.disabled = false;
        btn.style.opacity = '1';
      }
    });
  });

  // Wire container name click to open inspector
  tbody.querySelectorAll('.btn-docker-name-link').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.stopPropagation();
      const cid = link.dataset.id;
      const cname = link.dataset.name;
      if (cid) openContainerInspector(cid, cname);
    });
  });
}

export async function fetchAndRenderDockerContainers() {
  _bindDockerEvents();
  const tbody = document.getElementById('docker-containers-tbody');
  if (!tbody) return;
  try {
    const list = await api.get('/api/docker/containers');
    _dockerContainersList = Array.isArray(list) ? list : [];
    renderDockerContainersTable();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export async function fetchAndRenderAppCatalog() {
  _bindDockerEvents();
  const grid = document.getElementById('docker-catalog-grid');
  if (!grid) return;
  try {
    const list = await api.get('/api/docker/catalog');
    _catalogList = Array.isArray(list) ? list : [];
    renderAppCatalogGrid();
  } catch (err) {
    grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; color:var(--crit); padding:20px;">Failed to load catalog: ${escapeHtml(err.message)}</div>`;
  }
}

export function renderAppCatalogGrid() {
  const grid = document.getElementById('docker-catalog-grid');
  if (!grid) return;

  const filtered = _catalogList.filter((app) => {
    if (_catalogCat !== 'all' && app.category !== _catalogCat) return false;
    if (_catalogSearchQuery) {
      const q = _catalogSearchQuery;
      const matchName = (app.name || '').toLowerCase().includes(q);
      const matchDesc = (app.description || '').toLowerCase().includes(q);
      const matchId = (app.id || '').toLowerCase().includes(q);
      if (!matchName && !matchDesc && !matchId) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--muted); padding:30px;">No applications match your search.</div>';
    return;
  }

  const categoryIcons = {
    media: '🎬',
    photos: '📸',
    cloud: '☁️',
    automation: '⚡',
    utilities: '🛠️',
    downloads: '📥',
  };

  grid.innerHTML = filtered.map((app) => {
    const icon = categoryIcons[app.category] || '📦';
    return `
      <div class="catalog-app-card" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px; display:flex; flex-direction:column; justify-content:space-between; gap:10px; transition:border-color 0.2s, background 0.2s;">
        <div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:6px; margin-bottom:6px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:20px; line-height:1;">${icon}</span>
              <div>
                <div style="font-size:12.5px; font-weight:700; color:#fff;">${escapeHtml(app.name)}</div>
                <code style="font-size:9.5px; color:var(--muted); font-family:var(--font-mono, monospace);">${escapeHtml(app.image)}</code>
              </div>
            </div>
            <span class="ci-badge" style="font-size:9px; text-transform:uppercase; background:rgba(255,255,255,0.06); color:#cbd5e1; padding:2px 6px; border-radius:4px;">${escapeHtml(app.category)}</span>
          </div>
          <p style="font-size:11px; color:#94a3b8; line-height:1.4; margin:0 0 6px 0; min-height:32px;">${escapeHtml(app.description)}</p>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid rgba(255,255,255,0.06); padding-top:8px;">
          <span style="font-size:10.5px; font-family:var(--font-mono, monospace); color:var(--accent-cyan, #00f0ff); background:rgba(0,240,255,0.08); padding:2px 6px; border-radius:4px;">Port :${app.default_port}</span>
          <button class="btn-pill-toggle btn-deploy-app" data-appid="${escapeHtml(app.id)}" style="background:var(--brand, #0ea5e9); color:#fff; border:none; padding:3px 10px; font-weight:700; font-size:11px;">Deploy / Stack</button>
        </div>
      </div>
    `;
  }).join('');

  grid.querySelectorAll('.btn-deploy-app').forEach((btn) => {
    btn.addEventListener('click', () => {
      openAppDeployModal(btn.dataset.appid);
    });
  });
}

export async function openAppDeployModal(appId) {
  let modal = document.getElementById('app-deploy-modal-overlay');
  if (!modal) {
    const modalHtml = `
      <div id="app-deploy-modal-overlay" class="smart-modal-backdrop" style="display:none; z-index:10020;">
        <div id="app-deploy-modal-window" class="smart-modal-window" style="width:620px; max-width:94vw; max-height:88vh; display:flex; flex-direction:column;">
          <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span id="adm-icon" style="font-size:18px;">📦</span>
              <span id="adm-title" style="font-weight:700; color:#fff; font-size:13px;">Deploy Application Stack</span>
            </div>
            <button class="win-btn close-btn" id="adm-close-btn" title="Close" aria-label="Close"></button>
          </div>

          <!-- View 1: Configuration View -->
          <div id="adm-view-config" style="flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:12px;">
            <div id="adm-conflict-banner" style="padding:10px 12px; border-radius:6px; font-size:11px; line-height:1.4;"></div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
              <div>
                <label style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:4px;">HOST PORT MAPPING</label>
                <input type="number" id="adm-port-input" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px;">
              </div>
              <div>
                <label style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:4px;">STORAGE ROOT DIRECTORY</label>
                <input type="text" id="adm-storage-input" value="/mnt/user/appdata" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px;">
              </div>
            </div>
            <div>
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:10.5px; font-weight:700; color:var(--muted);">DOCKER COMPOSE DEFINITION</span>
                <div style="display:flex; gap:6px;">
                  <button class="btn-pill-toggle" id="adm-copy-btn">📋 Copy YAML</button>
                  <button class="btn-pill-toggle" id="adm-download-btn">⬇️ Download</button>
                </div>
              </div>
              <pre id="adm-compose-pre" style="margin:0; background:#080c14; border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:10px; max-height:200px; overflow:auto; font-family:var(--font-mono, monospace); font-size:10.5px; color:#e2e8f0; line-height:1.45;"></pre>
            </div>
          </div>

          <!-- View 2: Live Deployment Progress View -->
          <div id="adm-view-progress" style="display:none; flex:1; overflow-y:auto; padding:18px 16px; flex-direction:column; gap:12px;">
            <div style="display:flex; align-items:center; justify-content:space-between;">
              <div style="display:flex; align-items:center; gap:10px;">
                <span id="adm-progress-spinner" style="font-size:22px; display:inline-block;">⚙️</span>
                <div>
                  <div id="adm-progress-title" style="font-size:13px; font-weight:700; color:#fff;">Deploying Application...</div>
                  <div id="adm-progress-status-text" style="font-size:11px; color:var(--muted); margin-top:2px;">Preparing environment and directories...</div>
                </div>
              </div>
              <div id="adm-progress-pct-badge" style="font-size:13px; font-weight:800; font-family:var(--font-mono, monospace); color:var(--accent-cyan, #00f0ff); background:rgba(0,240,255,0.08); padding:3px 9px; border-radius:6px; border:1px solid rgba(0,240,255,0.2);">0%</div>
            </div>

            <!-- Stylized Progress Bar -->
            <div style="width:100%; height:10px; background:rgba(255,255,255,0.06); border-radius:5px; overflow:hidden; border:1px solid rgba(255,255,255,0.1); position:relative;">
              <div id="adm-progress-bar-fill" style="height:100%; width:0%; background:linear-gradient(90deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); transition:width 0.25s ease; box-shadow:0 0 10px rgba(37,194,160,0.5);"></div>
            </div>

            <!-- Real-time Activity Log Terminal -->
            <div style="margin-top:2px;">
              <div style="font-size:9.5px; font-weight:700; color:var(--muted); margin-bottom:4px; text-transform:uppercase; letter-spacing:0.5px;">Deployment Console Log</div>
              <div id="adm-deploy-logs" style="background:#05080f; border:1px solid rgba(255,255,255,0.1); border-radius:6px; height:160px; overflow-y:auto; padding:10px; font-family:var(--font-mono, monospace); font-size:10.5px; line-height:1.5; color:#cbd5e1;">
                <div style="color:var(--muted);">Waiting for deployment stream to begin...</div>
              </div>
            </div>

            <!-- Success Callout -->
            <div id="adm-success-box" style="display:none; padding:12px 14px; background:rgba(37,194,160,0.12); border:1px solid var(--ok2, #25c2a0); border-radius:6px; align-items:center; justify-content:space-between; gap:12px;">
              <div>
                <div style="font-weight:700; color:var(--ok2, #25c2a0); font-size:12px;">🚀 Container is Live & Running!</div>
                <div id="adm-success-msg" style="font-size:11px; color:#cbd5e1; margin-top:2px;">Your application has been deployed and started successfully.</div>
              </div>
              <a id="adm-webui-launch-btn" href="#" target="_blank" rel="noopener noreferrer" class="btn-pill-toggle" style="background:var(--ok2, #25c2a0); color:#000; font-weight:700; font-size:11px; padding:6px 14px; text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
                🌐 Open Web UI ↗
              </a>
            </div>
          </div>

          <!-- Footer for Config View -->
          <div id="adm-footer-config" style="padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="adm-cancel-btn">Cancel</button>
            <button class="btn-pill-toggle" id="adm-deploy-confirm-btn" style="background:linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); color:#fff; border:none; padding:6px 16px; font-weight:700; cursor:pointer;">
              🚀 Deploy & Launch Container
            </button>
          </div>

          <!-- Footer for Progress View -->
          <div id="adm-footer-progress" style="display:none; padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="adm-back-to-config-btn" style="display:none;">← Reconfigure</button>
            <div style="flex:1;"></div>
            <button class="btn-pill-toggle" id="adm-progress-close-btn" style="display:none; background:var(--ok2, #25c2a0); color:#fff; border:none; padding:6px 16px; font-weight:700;">✓ Done</button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    modal = document.getElementById('app-deploy-modal-overlay');

    document.getElementById('adm-close-btn').addEventListener('click', () => { modal.style.display = 'none'; });
    document.getElementById('adm-cancel-btn').addEventListener('click', () => { modal.style.display = 'none'; });
  }

  // Ensure config view is visible by default
  const viewConfig = document.getElementById('adm-view-config');
  const viewProgress = document.getElementById('adm-view-progress');
  const footerConfig = document.getElementById('adm-footer-config');
  const footerProgress = document.getElementById('adm-footer-progress');
  if (viewConfig) viewConfig.style.display = 'flex';
  if (viewProgress) viewProgress.style.display = 'none';
  if (footerConfig) footerConfig.style.display = 'flex';
  if (footerProgress) footerProgress.style.display = 'none';

  modal.style.display = 'flex';

  let suggestedPort = 8080;
  const banner = document.getElementById('adm-conflict-banner');
  const portInput = document.getElementById('adm-port-input');
  const storageInput = document.getElementById('adm-storage-input');
  const composePre = document.getElementById('adm-compose-pre');
  const title = document.getElementById('adm-title');

  title.textContent = `Deploy ${appId.toUpperCase()}`;
  banner.innerHTML = '<span style="color:var(--muted);">Probing host ports for conflicts...</span>';
  banner.style.background = 'rgba(255,255,255,0.04)';
  banner.style.border = '1px solid rgba(255,255,255,0.08)';

  try {
    const resolveData = await api.get(`/api/docker/catalog/${appId}/resolve`);
    suggestedPort = resolveData.suggested_port;
    portInput.value = suggestedPort;

    if (resolveData.conflict_detected) {
      banner.style.background = 'rgba(245, 166, 35, 0.12)';
      banner.style.border = '1px solid var(--warn, #f5a623)';
      banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict Detected:</span> Default port ${resolveData.default_port} is busy. Automatically mapped to free port <strong>${suggestedPort}</strong>!`;
    } else {
      banner.style.background = 'rgba(37, 194, 160, 0.12)';
      banner.style.border = '1px solid var(--ok2, #25c2a0)';
      banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ Ready to Deploy:</span> Port ${suggestedPort} is free and ready.`;
    }
  } catch (e) {
    portInput.value = 8080;
    banner.innerHTML = '<span style="color:var(--muted);">Port status: Default assigned</span>';
  }

  async function updateComposePreview() {
    const p = parseInt(portInput.value, 10) || suggestedPort;
    const s = storageInput.value.trim() || '/mnt/user/appdata';
    try {
      const comp = await api.post(`/api/docker/catalog/${appId}/compose`, { host_port: p, storage_root: s });
      composePre.textContent = comp.compose_yaml;
    } catch (err) {
      composePre.textContent = `# Failed to generate compose: ${err.message}`;
    }
  }

  portInput.oninput = updateComposePreview;
  storageInput.oninput = updateComposePreview;
  await updateComposePreview();

  document.getElementById('adm-copy-btn').onclick = () => {
    navigator.clipboard.writeText(composePre.textContent).then(() => {
      showToast('Docker Compose YAML copied to clipboard!', 'success');
    });
  };

  document.getElementById('adm-download-btn').onclick = () => {
    const blob = new Blob([composePre.textContent], { type: 'text/yaml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${appId}-compose.yml`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Downloaded ${appId}-compose.yml`, 'info');
  };

  // Deployment execution with live progress bar and streaming console
  const deployConfirmBtn = document.getElementById('adm-deploy-confirm-btn');
  const progressFill = document.getElementById('adm-progress-bar-fill');
  const progressPct = document.getElementById('adm-progress-pct-badge');
  const progressStatus = document.getElementById('adm-progress-status-text');
  const progressTitle = document.getElementById('adm-progress-title');
  const progressSpinner = document.getElementById('adm-progress-spinner');
  const deployLogs = document.getElementById('adm-deploy-logs');
  const successBox = document.getElementById('adm-success-box');
  const webuiBtn = document.getElementById('adm-webui-launch-btn');
  const closeProgressBtn = document.getElementById('adm-progress-close-btn');
  const backConfigBtn = document.getElementById('adm-back-to-config-btn');
  const closeBtn = document.getElementById('adm-close-btn');

  function logDeployLine(msg, type = 'info') {
    if (!deployLogs) return;
    const now = new Date().toTimeString().split(' ')[0];
    const color = type === 'error' ? 'var(--crit, #ff6b6b)' : type === 'success' ? 'var(--ok2, #25c2a0)' : '#cbd5e1';
    const line = document.createElement('div');
    line.style.color = color;
    line.textContent = `[${now}] ${msg}`;
    deployLogs.appendChild(line);
    deployLogs.scrollTop = deployLogs.scrollHeight;
  }

  function handleDeployEvent(data) {
    if (!data) return;

    if (data.percent != null && data.step !== 'error') {
      if (progressFill) progressFill.style.width = `${data.percent}%`;
      if (progressPct) progressPct.textContent = `${data.percent}%`;
    }
    if (data.message) {
      if (progressStatus) progressStatus.textContent = data.message;
      logDeployLine(data.message, data.step === 'error' ? 'error' : data.step === 'success' ? 'success' : 'info');
    }

    if (data.step === 'success') {
      if (progressFill) progressFill.style.width = '100%';
      if (progressPct) {
        progressPct.textContent = '100%';
        progressPct.style.color = 'var(--ok2, #25c2a0)';
      }
      if (progressTitle) progressTitle.textContent = `✓ ${appId.toUpperCase()} Deployed!`;
      if (progressSpinner) {
        progressSpinner.textContent = '✅';
        progressSpinner.style.animation = 'none';
      }

      if (successBox) successBox.style.display = 'flex';
      const webUrl = data.webui_url ? data.webui_url.replace('[HOST]', window.location.hostname) : `http://${window.location.hostname}:${data.port || suggestedPort}`;
      if (webuiBtn) {
        webuiBtn.href = webUrl;
        webuiBtn.textContent = `🌐 Open Web UI (:${data.port || suggestedPort}) ↗`;
      }

      if (closeBtn) {
        closeBtn.disabled = false;
        closeBtn.style.opacity = '1';
        closeBtn.style.pointerEvents = 'auto';
      }
      if (closeProgressBtn) {
        closeProgressBtn.style.display = 'inline-block';
        closeProgressBtn.textContent = '✓ Done';
      }

      try {
        fetchAndRenderDockerContainers();
      } catch (e) {}

      showToast(`${appId} stack deployed and running!`, 'success');
    } else if (data.step === 'error') {
      if (progressSpinner) {
        progressSpinner.textContent = '❌';
        progressSpinner.style.animation = 'none';
      }
      if (progressTitle) progressTitle.textContent = 'Deployment Failed';
      if (progressStatus) progressStatus.style.color = 'var(--crit, #ff6b6b)';
      if (progressPct) progressPct.style.color = 'var(--crit, #ff6b6b)';

      if (closeBtn) {
        closeBtn.disabled = false;
        closeBtn.style.opacity = '1';
        closeBtn.style.pointerEvents = 'auto';
      }
      if (backConfigBtn) backConfigBtn.style.display = 'inline-block';
      if (closeProgressBtn) {
        closeProgressBtn.style.display = 'inline-block';
        closeProgressBtn.textContent = 'Close';
      }

      showToast(`Deployment failed: ${data.message}`, 'error');
    }
  }

  deployConfirmBtn.onclick = async () => {
    const p = parseInt(portInput.value, 10) || suggestedPort;
    const s = storageInput.value.trim() || '/mnt/user/appdata';

    // Switch views
    viewConfig.style.display = 'none';
    footerConfig.style.display = 'none';
    viewProgress.style.display = 'flex';
    footerProgress.style.display = 'flex';

    // Lock close button while active
    closeBtn.disabled = true;
    closeBtn.style.opacity = '0.3';
    closeBtn.style.pointerEvents = 'none';

    // Reset progress UI
    if (progressFill) progressFill.style.width = '0%';
    if (progressPct) {
      progressPct.textContent = '0%';
      progressPct.style.color = 'var(--accent-cyan, #00f0ff)';
    }
    if (progressTitle) progressTitle.textContent = `Deploying ${appId.toUpperCase()} Stack...`;
    if (progressStatus) {
      progressStatus.textContent = 'Connecting to Docker daemon...';
      progressStatus.style.color = 'var(--muted)';
    }
    if (progressSpinner) {
      progressSpinner.textContent = '⚙️';
      progressSpinner.style.animation = 'spin 2s linear infinite';
    }
    if (deployLogs) deployLogs.innerHTML = '';
    if (successBox) successBox.style.display = 'none';
    if (closeProgressBtn) closeProgressBtn.style.display = 'none';
    if (backConfigBtn) backConfigBtn.style.display = 'none';

    logDeployLine(`Initiating deployment request for ${appId} (Port :${p}, Storage: ${s})...`);

    try {
      const response = await api.request(`/api/docker/catalog/${appId}/deploy`, {
        method: 'POST',
        body: { host_port: p, storage_root: s },
      });

      if (!response.ok) {
        throw new Error(`Deployment request failed: HTTP ${response.status}`);
      }

      if (!response.body || !response.body.getReader) {
        const text = await response.text();
        const lines = text.split('\n').filter(Boolean);
        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            handleDeployEvent(data);
          } catch (e) {}
        }
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const eventData = JSON.parse(line);
            handleDeployEvent(eventData);
          } catch (err) {
            console.warn('NDJSON parsing error:', err, line);
          }
        }
      }

      if (buffer.trim()) {
        try {
          const eventData = JSON.parse(buffer);
          handleDeployEvent(eventData);
        } catch (e) {}
      }
    } catch (err) {
      handleDeployEvent({
        step: 'error',
        percent: 0,
        message: err.message || 'Deployment connection failed',
        error: err.message,
        done: true,
      });
    }
  };

  if (backConfigBtn) {
    backConfigBtn.onclick = () => {
      viewProgress.style.display = 'none';
      footerProgress.style.display = 'none';
      viewConfig.style.display = 'flex';
      footerConfig.style.display = 'flex';
    };
  }

  if (closeProgressBtn) {
    closeProgressBtn.onclick = () => {
      modal.style.display = 'none';
      viewProgress.style.display = 'none';
      footerProgress.style.display = 'none';
      viewConfig.style.display = 'flex';
      footerConfig.style.display = 'flex';
    };
  }
}

export async function fetchAndRenderUpsTelemetry() {
  try {
    const ups = await api.get('/api/ups');
    if (!ups) return;
    const statusEl = document.getElementById('mgmt-ups-status');
    const modelEl = document.getElementById('mgmt-ups-model');
    const chargeEl = document.getElementById('mgmt-ups-charge');
    const runtimeEl = document.getElementById('mgmt-ups-runtime');
    const loadEl = document.getElementById('mgmt-ups-load');
    const linevEl = document.getElementById('mgmt-ups-linev');
    const pill = document.getElementById('mgmt-hub-ups-pill');

    if (statusEl) {
      statusEl.textContent = ups.status || (ups.available ? 'ONLINE' : 'Offline');
      statusEl.style.color = ups.available ? 'var(--ok2)' : 'var(--warn)';
    }
    if (pill) {
      pill.textContent = ups.battery_charge_pct != null ? `${ups.battery_charge_pct}%` : (ups.available ? 'Active' : 'Offline');
    }
    if (modelEl) modelEl.textContent = ups.model || 'Generic UPS';
    if (chargeEl) {
      chargeEl.textContent = ups.battery_charge_pct != null ? `${ups.battery_charge_pct}%` : 'N/A';
      chargeEl.style.color = (ups.battery_charge_pct == null || ups.battery_charge_pct > 30) ? 'var(--ok2)' : 'var(--crit)';
    }
    if (runtimeEl) runtimeEl.textContent = ups.time_left_min != null ? `${ups.time_left_min} min` : 'N/A';
    if (loadEl) loadEl.textContent = ups.load_pct != null ? `${ups.load_pct}%` : 'N/A';
    if (linevEl) linevEl.textContent = ups.line_volts != null ? `${ups.line_volts} V` : 'N/A';
  } catch (err) {
    console.debug('Failed to fetch UPS telemetry:', err);
  }
}

export async function fetchAndRenderCopyHistory() {
  const tbody = document.getElementById('copy-history-tbody');
  if (!tbody) return;
  try {
    const history = await api.get('/api/copy/history?limit=30');
    if (!history || history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:16px;">No ingest operations recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = history.map((item) => {
      const d = new Date(item.ts * 1000);
      const timeStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const sizeMB = (item.total_bytes / (1024 * 1024)).toFixed(1);
      const durStr = item.duration_sec ? `${item.duration_sec.toFixed(1)}s` : '--';
      const isSuccess = item.status === 'success';
      const statusColor = isSuccess ? 'var(--ok2)' : item.status === 'aborted' ? 'var(--warn)' : 'var(--crit)';
      const checksumBadge = item.checksum_verified
        ? '<span class="checksum-badge">✓ SHA-256</span>'
        : '<span style="color:var(--muted); font-size:9px;">None</span>';
      const destName = item.dest ? item.dest.split('/').filter(Boolean).pop() || item.dest : '/';

      return `
        <tr>
          <td style="font-family:var(--font-mono, monospace); font-size:10px; color:var(--muted);">${timeStr}</td>
          <td><strong>${(item.source || 'sd').toUpperCase()}</strong></td>
          <td title="${escapeHtml(item.dest)}" style="max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(destName)}</td>
          <td>${item.files_count || 0}</td>
          <td>${sizeMB} MB</td>
          <td>${durStr}</td>
          <td>
            <span style="font-weight:700; color:${statusColor}; text-transform:uppercase; margin-right:6px;">${escapeHtml(item.status)}</span>
            ${checksumBadge}
          </td>
        </tr>
      `;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--crit); padding:16px;">Failed to load history: ${escapeHtml(e.message)}</td></tr>`;
  }
}

export function initManagement() {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) {
    return;
  }

  const overlay = document.getElementById('management-modal-overlay');
  const win = document.getElementById('management-window');
  const header = document.getElementById('management-window-header');
  const hubView = document.getElementById('management-hub-view');
  const detailContainer = document.getElementById('management-detail-container');
  const backBtn = document.getElementById('management-back-btn');
  const titleText = document.getElementById('management-header-title-text');
  const headerNav = document.getElementById('management-header-nav');
  const desktopIcon = document.getElementById('management-desktop-icon');
  const secBadge = document.getElementById('mgmt-hub-sec-badge');

  if (!overlay || !win) return;

  // Make Management window draggable by its header
  if (header) {
    makeDraggable(win, header, 'management');
  }

  // Minimize button
  const minBtn = document.getElementById('management-min');
  if (minBtn) {
    const handleMin = (e) => {
      if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
      DockManager.minimize('management');
    };
    minBtn.addEventListener('click', handleMin);
    minBtn.addEventListener('touchend', handleMin);
  }

  // Maximize button
  const maxBtn = document.getElementById('management-max');
  let _isMaximized = false;
  let _preMaxBounds = null;
  if (maxBtn) {
    const handleMax = (e) => {
      if (e) { e.preventDefault(); e.stopPropagation(); }
      if (!_isMaximized) {
        _preMaxBounds = {
          left: win.style.left,
          top: win.style.top,
          transform: win.style.transform,
          width: win.style.width,
          height: win.style.height
        };
        win.style.left = '16px';
        win.style.top = '56px';
        win.style.transform = 'none';
        win.style.width = 'calc(100vw - 32px)';
        win.style.height = 'calc(100vh - 128px)';
        _isMaximized = true;
      } else {
        if (_preMaxBounds) {
          win.style.left = _preMaxBounds.left;
          win.style.top = _preMaxBounds.top;
          win.style.transform = _preMaxBounds.transform;
          win.style.width = _preMaxBounds.width;
          win.style.height = _preMaxBounds.height;
        } else {
          win.style.left = '50%';
          win.style.top = '50%';
          win.style.transform = 'translate(-50%, -50%)';
          win.style.width = '';
          win.style.height = '';
        }
        _isMaximized = false;
      }
    };
    maxBtn.addEventListener('click', handleMax);
    maxBtn.addEventListener('touchend', handleMax);
  }

  // Close button
  const closeBtn = document.getElementById('management-close');
  if (closeBtn) {
    const handleClose = (e) => {
      if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
      overlay.classList.remove('open');
      overlay.style.setProperty('display', 'none', 'important');
      win.classList.remove('window-focus-pulse');
      win.classList.add('window-minimized');
      if (_unbindMgmtTrap) {
        _unbindMgmtTrap();
        _unbindMgmtTrap = null;
      }
      DockManager.unregister('management');
    };
    closeBtn.addEventListener('click', handleClose);
    closeBtn.addEventListener('touchend', handleClose);
  }

  function showHub() {
    if (hubView) hubView.style.display = 'grid';
    if (detailContainer) detailContainer.style.display = 'none';
    if (headerNav) headerNav.style.display = 'none';
    if (backBtn) backBtn.style.display = 'none';
    if (titleText) titleText.textContent = t('mgmt.title', 'Mission Control');
    document.querySelectorAll('.mgmt-category-tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.mgmt-sidebar-item').forEach((b) => {
      b.classList.toggle('active', b.dataset.mgmtTarget === 'management-hub-view');
    });
    document.querySelectorAll('.mgmt-detail-card').forEach((c) => (c.style.display = 'none'));
  }

  
  const SUBPANE_MAP = {
    'mgmt-pane-wallpaper': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
    'mgmt-pane-widgets': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-widgets' },
    'mgmt-pane-theme': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' },
    'mgmt-sec-theme': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' },
    'mgmt-pane-language': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },
    'mgmt-sec-language': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },
    'mgmt-sec-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
    'mgmt-pane-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
    'mgmt-sec-copy': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-copy' },
    'mgmt-pane-copy': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-copy' },
    'mgmt-sec-unraid': { section: 'mgmt-sec-services', pane: 'mgmt-pane-unraid' },
    'mgmt-pane-unraid': { section: 'mgmt-sec-services', pane: 'mgmt-pane-unraid' },
    'mgmt-sec-docker': { section: 'mgmt-sec-services', pane: 'mgmt-pane-docker' },
    'mgmt-pane-docker': { section: 'mgmt-sec-services', pane: 'mgmt-pane-docker' },
    'mgmt-sec-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
    'mgmt-pane-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
    'mgmt-sec-events': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-events' },
    'mgmt-pane-events': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-events' },
    'mgmt-sec-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-system' },
    'mgmt-pane-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-system' },
    'mgmt-sec-about': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-about' },
    'mgmt-pane-about': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-about' },
  };

  function triggerActiveSubTab(parentId) {
    const parent = document.getElementById(parentId);
    if (!parent) return;
    const activeTabBtn = parent.querySelector('.mgmt-inner-tab.active');
    if (activeTabBtn) {
      const paneId = activeTabBtn.dataset.tabTarget;
      triggerSubTabLoad(paneId);
    }
  }

  function triggerSubTabLoad(paneId) {
    if (paneId === 'mgmt-pane-widgets') {
      if (typeof syncWidgetSettingsUI === 'function') syncWidgetSettingsUI();
    } else if (paneId === 'mgmt-pane-theme') {
      if (typeof syncDesktopThemeUI === 'function') syncDesktopThemeUI();
    } else if (paneId === 'mgmt-pane-language') {
      const select = document.getElementById('mgmt-lang-select');
      if (select && typeof getLanguage === 'function') {
        select.value = getLanguage();
      }
    } else if (paneId === 'mgmt-pane-metrics') {
      setTimeout(fetchAndRenderMetrics, 50);
    } else if (paneId === 'mgmt-pane-copy') {
      fetchAndRenderCopyHistory();
    } else if (paneId === 'mgmt-pane-unraid') {
      if (state.lastStats) updateManagementTelemetry(state.lastStats);
    } else if (paneId === 'mgmt-pane-docker') {
      fetchAndRenderDockerContainers();
    } else if (paneId === 'mgmt-pane-system') {
      if (typeof fetchAPITokens === 'function') fetchAPITokens();
    } else if (paneId === 'mgmt-pane-about') {
      fetchAndRenderSystemAbout();
    }
  }

  function showSection(targetId) {
    let desiredSubPane = null;
    if (SUBPANE_MAP[targetId]) {
      desiredSubPane = SUBPANE_MAP[targetId].pane;
      targetId = SUBPANE_MAP[targetId].section;
    }

    if (hubView) hubView.style.display = 'none';
    if (detailContainer) detailContainer.style.display = 'block';
    if (headerNav) headerNav.style.display = 'flex';
    if (backBtn) backBtn.style.display = 'inline-flex';

    document.querySelectorAll('.mgmt-detail-card').forEach((c) => {
      if (c.id === targetId) {
        c.style.display = 'block';
      } else {
        c.style.display = 'none';
      }
    });

    const targetTab = document.querySelector(`.mgmt-category-tab[data-mgmt-target="${targetId}"]`);
    document.querySelectorAll('.mgmt-category-tab').forEach((t) => t.classList.remove('active'));
    if (targetTab) targetTab.classList.add('active');

    document.querySelectorAll('.mgmt-sidebar-item').forEach((b) => {
      b.classList.toggle('active', b.dataset.mgmtTarget === targetId);
    });

    let sectionName = t('mgmt.title', 'Mission Control');
    if (targetId === 'mgmt-sec-wallpaper') {
      sectionName = t('mgmt.appearance_title', 'Appearance');
      triggerActiveSubTab(targetId);
    } else if (targetId === 'mgmt-sec-activity') {
      sectionName = t('mgmt.activity_title', 'Activity Monitor');
    } else if (targetId === 'mgmt-sec-services') {
      sectionName = t('mgmt.services_title', 'Services');
    } else if (targetId === 'mgmt-sec-ups') {
      sectionName = t('mgmt.sidebar_ups', 'UPS & Power');
      if (typeof fetchAndRenderUpsTelemetry === 'function') fetchAndRenderUpsTelemetry();
      else if (typeof fetchAndRenderUPS === 'function') fetchAndRenderUPS();
    } else if (targetId === 'mgmt-sec-system-group') {
      sectionName = t('mgmt.system_title', 'System');
    }

    if (titleText) titleText.textContent = sectionName;

    if (desiredSubPane) {
      const parentCard = document.getElementById(targetId);
      if (parentCard) {
        parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
          t.classList.toggle('active', t.dataset.tabTarget === desiredSubPane);
        });
        parentCard.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
          p.style.display = p.id === desiredSubPane ? 'block' : 'none';
        });
        triggerSubTabLoad(desiredSubPane);
      }
    } else {
      triggerActiveSubTab(targetId);
    }
  }

  // Left sidebar items click listener

  document.querySelectorAll('.mgmt-inner-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const parentCard = tab.closest('.mgmt-detail-card');
      if (!parentCard) return;
      
      // Update tab buttons
      parentCard.querySelectorAll('.mgmt-inner-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      
      // Update tab panes
      const targetPaneId = tab.dataset.tabTarget;
      parentCard.querySelectorAll('.mgmt-tab-pane').forEach(p => {
        if (p.id === targetPaneId) {
          p.style.display = 'block';
        } else {
          p.style.display = 'none';
        }
      });
      
      triggerSubTabLoad(targetPaneId);
    });
  });

  document.querySelectorAll('.mgmt-sidebar-item').forEach((item) => {
    item.addEventListener('click', () => {
      const targetId = item.dataset.mgmtTarget;
      if (targetId === 'management-hub-view') {
        showHub();
      } else if (targetId) {
        showSection(targetId);
      }
    });
  });

  // Hub cards click listener
  document.querySelectorAll('.mgmt-app-card').forEach((card) => {
    card.addEventListener('click', () => {
      const targetId = card.dataset.mgmtTarget;
      if (targetId) showSection(targetId);
    });
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const targetId = card.dataset.mgmtTarget;
        if (targetId) showSection(targetId);
      }
    });
  });

  // Header quick tabs click listener
  document.querySelectorAll('.mgmt-category-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.mgmtTarget;
      if (targetId) showSection(targetId);
    });
  });

  // Back button click listener
  if (backBtn) {
    backBtn.addEventListener('click', showHub);
  }

  // Global helper to open / focus Management window
  window.openManagementWindow = (sectionId = null) => {
    if (!DockManager.windows['management']) {
      DockManager.register('management', overlay, '#i-management', 'Management');
    }
    if (DockManager.windows['management']?.minimized || overlay.style.display === 'none' || !overlay.classList.contains('open')) {
      DockManager.restore('management');
      overlay.style.removeProperty('display');
      overlay.classList.add('open');
      win.classList.remove('window-minimized');
      if (state.latestStats) updateManagementTelemetry(state.latestStats);
    }
    bringToFront(win);
    win.classList.remove('window-focus-pulse');
    void win.offsetWidth; // Reflow
    win.classList.add('window-focus-pulse');
    setTimeout(() => win.classList.remove('window-focus-pulse'), 850);

    if (_unbindMgmtTrap) { _unbindMgmtTrap(); }
    _unbindMgmtTrap = trapFocus(win, () => {
      const cBtn = document.getElementById('management-close');
      if (cBtn) cBtn.click();
    });

    if (sectionId) {
      showSection(sectionId);
    } else {
      showHub();
    }
  };

  // Desktop icon click listener
  if (desktopIcon) {
    desktopIcon.addEventListener('click', () => {
      window.openManagementWindow();
    });
    desktopIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        window.openManagementWindow();
      }
    });
  }

  // Synchronize security alert badge on Security card and sidebar
  function syncSecurityBadge() {
    const defaultWarning = document.getElementById('sec-default-pwd-warning');
    const isWarning = defaultWarning && defaultWarning.style.display !== 'none';
    if (secBadge) {
      secBadge.style.display = isWarning ? 'flex' : 'none';
    }
    const sideSecBadge = document.getElementById('mgmt-sidebar-sec-badge');
    if (sideSecBadge) {
      sideSecBadge.style.display = isWarning ? 'inline-block' : 'none';
    }
  }

  const observer = new MutationObserver(syncSecurityBadge);
  const warnEl = document.getElementById('sec-default-pwd-warning');
  if (warnEl) {
    observer.observe(warnEl, { attributes: true, attributeFilter: ['style'] });
    syncSecurityBadge();
  }

  // Profile buttons listener
  document.querySelectorAll('.profile-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const p = btn.dataset.profile;
      if (!p) return;
      _activeProfile = p;
      document.querySelectorAll('.profile-btn').forEach((b) => b.classList.toggle('active', b === btn));
      const pill = document.getElementById('unraid-profile-current-pill');
      if (pill) {
        pill.textContent = `ACTIVE: ${p === 'auto' ? 'AUTO DYNAMIC' : p.toUpperCase()}`;
        pill.style.color = p === 'performance' ? 'var(--warn)' : 'var(--ok2)';
      }
      try {
        await api.post('/api/system/profile', { profile: p });
        showToast(`System profile switched to ${p === 'auto' ? 'AUTO DYNAMIC' : p.toUpperCase()}.`, 'success');
      } catch (err) {
        showToast(`Failed to switch profile: ${err.message}`, 'error');
      }
    });
  });

  // Copy history refresh button
  const refreshHistoryBtn = document.getElementById('btn-refresh-copy-history');
  if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener('click', () => {
      fetchAndRenderCopyHistory();
      showToast('Ingest history refreshed.', 'info');
    });
  }

  // Docker containers refresh button
  const refreshDockerBtn = document.getElementById('btn-refresh-docker');
  if (refreshDockerBtn) {
    refreshDockerBtn.addEventListener('click', () => {
      fetchAndRenderDockerContainers();
      showToast('Docker containers refreshed.', 'info');
    });
  }

  // UPS telemetry refresh button
  const refreshUpsBtn = document.getElementById('btn-refresh-ups');
  if (refreshUpsBtn) {
    refreshUpsBtn.addEventListener('click', () => {
      fetchAndRenderUpsTelemetry();
      showToast('UPS telemetry refreshed.', 'info');
    });
  }

  // Check for updates button
  const checkUpdatesBtn = document.getElementById('btn-check-updates');
  if (checkUpdatesBtn) {
    checkUpdatesBtn.addEventListener('click', () => {
      fetchAndRenderSystemAbout(true);
    });
  }

  // Language switch update
  window.addEventListener('zettnas:lang-changed', () => {
    const activeSection = Array.from(document.querySelectorAll('.mgmt-detail-card')).find((c) => c.style.display !== 'none');
    if (activeSection) {
      showSection(activeSection.id);
    } else if (hubView && hubView.style.display !== 'none') {
      showHub();
    }
  });
}

export async function fetchAndRenderSystemAbout(force = false) {
  const versionBadge = document.getElementById('about-version-badge');
  const chassisEl = document.getElementById('about-chassis-model');
  const hostEl = document.getElementById('about-host-platform');
  const runtimeEl = document.getElementById('about-runtime-env');
  const uptimeEl = document.getElementById('about-system-uptime');

  const statusIcon = document.getElementById('update-status-icon');
  const statusTitle = document.getElementById('update-status-title');
  const statusDesc = document.getElementById('update-status-desc');
  const lastCheckedEl = document.getElementById('update-last-checked');
  const detailsBox = document.getElementById('update-details-box');
  const releaseTitle = document.getElementById('update-release-title');
  const releaseLink = document.getElementById('update-release-link');
  const releaseNotes = document.getElementById('update-release-notes');

  const btnIcon = document.getElementById('btn-check-updates-icon');
  const btnText = document.getElementById('btn-check-updates-text');

  if (btnIcon && btnText) {
    btnIcon.textContent = '⏳';
    btnText.textContent = 'Checking...';
  }

  // 1. Fetch system about telemetry
  try {
    const about = await api.get('/api/system/about');
    if (about) {
      if (versionBadge) versionBadge.textContent = `${about.tag || 'v' + about.version} • ${about.release_channel || 'Stable'}`;
      if (chassisEl) chassisEl.textContent = about.chassis_model || 'Standard / DIY';
      if (hostEl) hostEl.textContent = `${about.hostname || 'NAS'} (${about.platform || 'Linux'})`;
      if (runtimeEl) runtimeEl.textContent = `${about.containerized ? 'Docker Container' : 'Native Host'} (Python ${about.python_version || '3.12'})`;
      if (uptimeEl && about.uptime_secs != null) {
        const d = Math.floor(about.uptime_secs / 86400);
        const h = Math.floor((about.uptime_secs % 86400) / 3600);
        const m = Math.floor((about.uptime_secs % 3600) / 60);
        uptimeEl.textContent = d > 0 ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
      }
    }
  } catch (err) {
    console.warn('[ZettNAS] Failed to fetch system about info:', err);
  }

  // 2. Fetch update status
  try {
    const data = await api.get(`/api/system/updates${force ? '?force=true' : ''}`);
    if (data) {
      if (data.update_available) {
        if (statusIcon) statusIcon.textContent = '🚀';
        if (statusTitle) {
          statusTitle.textContent = `Update Available: ${data.latest_tag || 'v' + data.latest_version}`;
          statusTitle.style.color = 'var(--warn, #f5a623)';
        }
        if (statusDesc) statusDesc.textContent = `A newer release of ZettNAS Workbench is available on GitHub.`;
        if (detailsBox) detailsBox.style.display = 'block';
        if (releaseTitle) releaseTitle.textContent = data.release_name || `Release ${data.latest_tag}`;
        if (releaseLink) releaseLink.href = data.release_url || 'https://github.com/fr0styx/zettnas-toolkit/releases';
        if (releaseNotes) releaseNotes.textContent = data.release_notes || 'No release notes provided.';
      } else {
        if (statusIcon) statusIcon.textContent = '✅';
        if (statusTitle) {
          statusTitle.textContent = `ZettNAS Workbench is up to date`;
          statusTitle.style.color = 'var(--ok2, #25c2a0)';
        }
        if (statusDesc) statusDesc.textContent = `You are running the latest stable release (${data.latest_tag || 'v' + data.current_version}).`;
        if (detailsBox) detailsBox.style.display = 'none';
      }
      if (lastCheckedEl && data.checked_at) {
        const timeStr = new Date(data.checked_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        lastCheckedEl.textContent = `Checked: ${timeStr}`;
      }
    }
  } catch (err) {
    if (statusIcon) statusIcon.textContent = '⚠️';
    if (statusTitle) {
      statusTitle.textContent = 'Unable to check for updates';
      statusTitle.style.color = 'var(--crit, #ff6b6b)';
    }
    if (statusDesc) statusDesc.textContent = err.message || 'Offline or network request failed.';
  } finally {
    if (btnIcon && btnText) {
      btnIcon.textContent = '🔄';
      btnText.textContent = 'Check for Updates';
    }
  }
}

