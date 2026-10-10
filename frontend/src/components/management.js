import { syncWidgetSettingsUI } from './widgets.js';
import { syncDesktopThemeUI } from './settings.js';
import { openContainerInspector, openContainerDeleteModal } from './container-modal.js';
import { ZettEventBus } from '../event-bus.js';
import { fetchAndRenderChassisTwin, renderStorageTopologyTree, fetchAndRenderStorageTopology, fetchAndRenderNetworkShares, fetchAndRenderRemoteStorage, openNewCloudRemoteModal, openCreateStoragePoolModal, openCreateNetworkShareModal, openSnapshotsModal, triggerLocateDisk, getThermalLevel } from './chassis-visualizer.js';
/**
 * ZettNAS Toolkit - System Management Window Controller
 * Manages the dedicated System Management desktop window, hub app grid,
 * category navigation, and card views (Wallpaper, Metrics, Events, Security).
 */
import { fetchAndRenderMetrics } from './metrics-chart.js';
import { bringToFront, DockManager, makeDraggable, saveWindowBounds, saveOpenWindowsState } from './dock.js';
import { state } from '../state.js';
import { api } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';
import { trapFocus, escapeHtml, copyTextToClipboard, reconcileKeyedTable } from '../utils.js';
import { t, getLanguage } from '../i18n.js';

let _activeProfile = 'balanced';
let _unbindMgmtTrap = null;

export const SUBPANE_MAP = {
  'mgmt-pane-wallpaper': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
  'mgmt-pane-widgets': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-widgets' },
  'mgmt-pane-theme': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' },
  'mgmt-sec-theme': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' },
  'mgmt-pane-glass': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-glass' },
  'mgmt-sec-glass': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-glass' },
  'mgmt-pane-dock': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-dock' },
  'mgmt-sec-dock': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-dock' },
  'mgmt-pane-screensaver': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-screensaver' },
  'mgmt-sec-screensaver': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-screensaver' },
  'mgmt-sec-wallpaper': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
  'mgmt-pane-language': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'mgmt-sec-language': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'mgmt-sec-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'mgmt-pane-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'mgmt-sec-copy': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-copy' },
  'mgmt-pane-copy': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-copy' },
  'mgmt-sec-network': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-network' },
  'mgmt-pane-network': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-network' },
  'mgmt-sec-activity': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  // Hardware & Profiles
  'mgmt-sec-hardware': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-pane-hardware': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-sec-services': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' }, // Backward compat
  'mgmt-sec-unraid': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-pane-unraid': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  // Apps & Containers (First-Class Top-Level)
  'mgmt-sec-docker': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-pane-docker': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-sec-catalog': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-sec-storage': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-chassis-twin' },
  'mgmt-pane-chassis-twin': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-chassis-twin' },
  'mgmt-pane-storage-topo': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-pane-storage-shares': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-shares' },
  'mgmt-pane-storage-remotes': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-remotes' },
  'mgmt-pane-storage-disks': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-disks' },
  'mgmt-sec-notifications': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-notifications' },
  'mgmt-pane-notifications': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-notifications' },
  'mgmt-sec-users': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-users' },
  'mgmt-pane-users': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-users' },
  'mgmt-sec-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-pane-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-sec-events': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-events' },
  'mgmt-pane-events': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-events' },
  'mgmt-sec-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-system' },
  'mgmt-pane-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-system' },
  'mgmt-sec-about': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-about' },
  'mgmt-pane-about': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-about' },
  'mgmt-sec-system-group': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-sec-ups': { section: 'mgmt-sec-ups', pane: null },
};

export function updateManagementTelemetry(stats) {
  if (!stats) return;
  const overlay = document.getElementById('management-modal-overlay');
  if (overlay && (!overlay.classList.contains('open') || overlay.classList.contains('window-minimized') || overlay.style.display === 'none')) {
    return;
  }
  const unraid = stats.unraid;
  const unraidGrid = document.querySelector('.unraid-details-grid');
  const genericGrid = document.querySelector('.generic-details-grid');

  if (unraid && unraid.available) {
    if (unraidGrid) unraidGrid.style.display = 'grid';
    if (genericGrid) genericGrid.style.display = 'none';

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
  } else {
    if (unraidGrid) unraidGrid.style.display = 'none';
    if (genericGrid) genericGrid.style.display = 'grid';

    const osNameEl = document.getElementById('mgmt-generic-os');
    const hostEl = document.getElementById('mgmt-generic-host');
    const uptimeEl = document.getElementById('mgmt-generic-uptime');
    const cpuEl = document.getElementById('mgmt-generic-cpu');
    const loadEl = document.getElementById('mgmt-generic-load');
    const engineEl = document.getElementById('mgmt-generic-engine');

    if (osNameEl) osNameEl.textContent = stats.os?.distro || stats.system?.os || 'Linux';
    if (hostEl) hostEl.textContent = stats.system?.hostname || 'ZettNAS Host';
    if (uptimeEl) uptimeEl.textContent = stats.system?.uptime_str || stats.os?.uptime || 'Active';
    if (cpuEl) cpuEl.textContent = stats.cpu?.model ? stats.cpu.model.slice(0, 24) : 'x86_64 / ARM64';
    if (loadEl) loadEl.textContent = stats.cpu?.load_avg ? stats.cpu.load_avg.join(', ') : 'Normal';
    if (engineEl) engineEl.textContent = stats.storage?.engine || 'Btrfs / OpenZFS';
  }

  // Update Docker pill in Hub and Left Sidebar
  if (stats.docker && Array.isArray(stats.docker)) {
    const runningCount = stats.docker.filter(c => c.state === 'running').length;
    const dockPill = document.getElementById('mgmt-hub-docker-pill');
    if (dockPill) dockPill.textContent = `${runningCount} Active`;
    const sideDockBadge = document.getElementById('mgmt-sidebar-docker-badge');
    if (sideDockBadge) {
      sideDockBadge.textContent = `${runningCount} Active`;
      sideDockBadge.style.display = 'inline-block';
    }
  }

  // Update Storage pill in Hub and Left Sidebar
  if (stats.disks && Array.isArray(stats.disks)) {
    const storagePill = document.getElementById('mgmt-hub-storage-pill');
    if (storagePill) storagePill.textContent = `${stats.disks.length} Drives`;
    const sideStorageBadge = document.getElementById('mgmt-sidebar-storage-badge');
    if (sideStorageBadge) {
      sideStorageBadge.textContent = `${stats.disks.length} Drives`;
      sideStorageBadge.style.display = 'inline-block';
    }

    // Live update Disks Inventory table if currently rendered
    const diskTbody = document.getElementById('mgmt-disks-inventory-tbody');
    if (diskTbody) {
      const existingRows = diskTbody.querySelectorAll('tr[data-dev]');
      if (existingRows.length > 0) {
        stats.disks.forEach((d) => {
          const devName = d.dev || d.name;
          if (!devName) return;
          const row = diskTbody.querySelector(`tr[data-dev="${devName}"]`);
          if (row) {
            const isStandby = Boolean(d.standby || d.health === 'standby');
            const thermal = getThermalLevel(d.temp, isStandby);
            const healthStr = isStandby ? 'STANDBY' : (d.health ? String(d.health).toUpperCase() : 'OK');
            
            const healthTag = row.querySelector('.bay-health-tag');
            if (healthTag) {
              healthTag.className = `bay-health-tag ${thermal.cls}`;
              healthTag.textContent = healthStr;
            }
            const tempPill = row.querySelector('.bay-temp-pill');
            if (tempPill) {
              tempPill.style.color = thermal.color;
              tempPill.style.borderColor = thermal.color;
              tempPill.textContent = thermal.text;
            }
            const sizeTd = row.children[3];
            if (sizeTd && (d.size_formatted || d.size)) {
              sizeTd.textContent = d.size_formatted || d.size;
            }
          }
        });
      }
    }
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
        const isAct = b.dataset.profile === prof;
        b.classList.toggle('active', isAct);
        b.setAttribute('aria-checked', isAct ? 'true' : 'false');
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
let _dockerUpdatesCache = null;

let _catalogList = [];
let _catalogCat = 'all';
let _catalogSearchQuery = '';
let _catalogSources = [];

export function _resetDockerStateForTesting() {
  _dockerContainersList = [];
  _dockerFilter = 'all';
  _dockerSearchQuery = '';
  _dockerUpdatesCache = null;
}

export function _resetCatalogStateForTesting() {
  _catalogList = [];
  _catalogCat = 'all';
  _catalogSearchQuery = '';
  _catalogSources = [];
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

  // Prune button
  const btnPrune = document.getElementById('btn-docker-prune');
  if (btnPrune) {
    btnPrune.addEventListener('click', () => {
      openDockerPruneModal();
    });
  }

  // Sources button
  const btnSources = document.getElementById('btn-manage-app-sources');
  if (btnSources) {
    btnSources.addEventListener('click', () => {
      openAppSourcesModal();
    });
  }

  // Check for updates button
  const btnCheckUpdates = document.getElementById('btn-docker-check-updates');
  if (btnCheckUpdates) {
    btnCheckUpdates.addEventListener('click', async () => {
      btnCheckUpdates.disabled = true;
      const originalHtml = btnCheckUpdates.innerHTML;
      btnCheckUpdates.innerHTML = '<span>⏳</span> <span>Checking updates...</span>';
      try {
        const res = await api.post('/api/docker/updates/check');
        _dockerUpdatesCache = res;
        const count = res.updates_available_count || 0;
        updateDockerUpdatesToolbarUI(count);
        if (count > 0) {
          showToast(`Update check complete: ${count} container update${count > 1 ? 's' : ''} available!`, 'warn');
        } else {
          showToast('All containers are up to date!', 'success');
        }
        renderDockerContainersTable();
      } catch (err) {
        showToast(`Update check failed: ${err.message}`, 'error');
      } finally {
        btnCheckUpdates.disabled = false;
        btnCheckUpdates.innerHTML = originalHtml;
      }
    });
  }

  // Update all button
  const btnUpdateAll = document.getElementById('btn-docker-update-all');
  if (btnUpdateAll) {
    btnUpdateAll.addEventListener('click', async () => {
      const count = _dockerUpdatesCache?.updates_available_count || 0;
      if (!confirm(`Update all ${count} containers to their latest images? Each container will be safely recreated with automated rollback protection.`)) {
        return;
      }
      btnUpdateAll.disabled = true;
      btnUpdateAll.innerHTML = '<span>⏳</span> <span>Updating all...</span>';
      showToast(`Starting batch update for ${count} containers...`, 'info');
      try {
        const res = await api.post('/api/docker/updates/apply-all');
        const updatedCount = res.total_updated || (res.updated || []).length;
        showToast(`Batch update complete: ${updatedCount} updated, ${(res.failed || []).length} failed.`, updatedCount > 0 ? 'success' : 'warn');
        await refreshDockerUpdatesStatus();
        await fetchAndRenderDockerContainers();
      } catch (err) {
        showToast(`Batch update failed: ${err.message}`, 'error');
      } finally {
        btnUpdateAll.disabled = false;
      }
    });
  }

  ZettEventBus.on('docker:containers-updated', () => {
    fetchAndRenderDockerContainers();
  });

  ZettEventBus.on('docker:containers:refresh', () => {
    fetchAndRenderDockerContainers();
    refreshDockerUpdatesStatus();
  });

  containerPane._dockerEventsBound = true;
}

export async function refreshDockerUpdatesStatus() {
  try {
    const res = await api.get('/api/docker/updates/status');
    _dockerUpdatesCache = res;
    updateDockerUpdatesToolbarUI(res.updates_available_count || 0);
    renderDockerContainersTable();
  } catch (e) {}
}

export function updateDockerUpdatesToolbarUI(count) {
  const btnUpdateAll = document.getElementById('btn-docker-update-all');
  const badge = document.getElementById('docker-updates-count-badge');
  if (badge) badge.textContent = count;
  if (btnUpdateAll) {
    btnUpdateAll.style.display = count > 0 ? 'inline-flex' : 'none';
  }
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
  if (sideBadge) {
    sideBadge.textContent = `${runningCount} Active`;
    sideBadge.style.display = 'inline-block';
  }

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

  if (tbody.firstElementChild && tbody.firstElementChild.querySelector('td[colspan]')) {
    tbody.innerHTML = '';
  }

  bindDockerTableEvents(tbody);

  reconcileKeyedTable(
    tbody,
    filtered,
    (c) => c.id || c.name,
    (c) => createContainerRow(c, currentHost),
    (tr, c) => updateContainerRow(tr, c, currentHost)
  );
}

function buildContainerRowInner(c, currentHost) {
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
      <span class="docker-state-badge" style="display:inline-block; padding:2px 6px; border-radius:4px; font-size:9.5px; font-weight:700; background:${badgeBg}; color:${badgeColor}; text-transform:uppercase;">${escapeHtml(c.state)}</span>
      <span class="docker-status-text" style="font-size:10px; color:#cbd5e1; max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
    </div>
  `;

  // Column 6: Actions
  const updateInfo = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
  const hasUpdate = Boolean(updateInfo?.has_update);
  const updateBadge = hasUpdate
    ? `<span class="ci-badge badge-update-ready" title="New image update available" style="display:inline-flex; align-items:center; gap:2px; background:rgba(245,158,11,0.18); color:#fbbf24; border:1px solid rgba(245,158,11,0.4); font-size:9px; font-weight:700; padding:1px 5px; border-radius:3px; margin-left:4px;">⬆️ UPDATE</span>`
    : '';

  const inspectBtn = `<button class="btn-container-act btn-docker-inspect" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="inspect" title="Inspect ${escapeHtml(c.name)}">🔍</button>`;
  const editBtn = `<button class="btn-container-act btn-docker-edit" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="edit" title="Edit ${escapeHtml(c.name)}">✏️</button>`;
  const updateBtn = hasUpdate
    ? `<button class="btn-container-act btn-docker-update-single" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="update-single" title="Update ${escapeHtml(c.name)} to latest image" style="color:#fbbf24;">⬆️</button>`
    : '';
  const deleteBtn = `<button class="btn-container-act btn-docker-delete" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-image="${escapeHtml(c.image || '')}" data-action="delete" title="Destroy / Delete ${escapeHtml(c.name)}" style="color:var(--crit, #ff6b6b);">🗑️</button>`;
  const actions = isRunning
    ? `
      ${inspectBtn}
      ${editBtn}
      ${updateBtn}
      <button class="btn-container-act btn-docker-restart" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="restart" title="Restart ${escapeHtml(c.name)}">🔄</button>
      <button class="btn-container-act btn-docker-stop" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="stop" title="Stop ${escapeHtml(c.name)}">⏹</button>
      ${deleteBtn}
    `
    : `
      ${inspectBtn}
      ${editBtn}
      ${updateBtn}
      <button class="btn-container-act btn-docker-start" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="start" title="Start ${escapeHtml(c.name)}">▶</button>
      ${deleteBtn}
    `;

  return `
    <td>
      <div style="display:flex; align-items:baseline; gap:6px;">
        <button class="btn-docker-name-link" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" style="background:none; border:none; padding:0; color:#fff; font-size:11.5px; font-weight:700; cursor:pointer; text-align:left; font-family:inherit;" title="Inspect ${escapeHtml(c.name)}">${escapeHtml(c.name)}</button>
        <code style="font-size:9px; color:var(--muted); font-family:var(--font-mono, monospace);">${escapeHtml(idShort)}</code>
        ${updateBadge}
      </div>
      <div>${stackHtml}</div>
    </td>
    <td>${hwHtml}</td>
    <td class="docker-telemetry-cell">${telemHtml}</td>
    <td>${portsHtml}</td>
    <td class="docker-status-cell">${statusHtml}</td>
    <td class="docker-actions-cell" style="text-align:right; white-space:nowrap;">${actions}</td>
  `;
}

function createContainerRow(c, currentHost) {
  const tr = document.createElement('tr');
  const key = c.id || c.name || '';
  tr.dataset.key = key;
  tr.dataset.id = c.id || '';
  tr.dataset.state = c.state || '';
  tr.innerHTML = buildContainerRowInner(c, currentHost);
  return tr;
}

function updateContainerRow(tr, c, currentHost) {
  if (tr.dataset.state !== c.state || !tr.children.length) {
    tr.dataset.state = c.state || '';
    tr.innerHTML = buildContainerRowInner(c, currentHost);
    return;
  }

  const isRunning = c.state === 'running';
  const telemCell = tr.querySelector('.docker-telemetry-cell');
  if (telemCell) {
    if (isRunning) {
      const cpuStr = `${(c.cpu_pct || 0).toFixed(1)}%`;
      const memStr = c.mem_used ? `${(c.mem_used / (1024 * 1024)).toFixed(0)} MB` : '--';
      const cpuEl = telemCell.querySelector('.telem-cpu');
      const memEl = telemCell.querySelector('.telem-mem');
      if (cpuEl && memEl) {
        cpuEl.textContent = cpuStr;
        memEl.textContent = memStr;
      } else {
        telemCell.innerHTML = `<span class="docker-telemetry-pill"><span class="telem-cpu">${cpuStr}</span><span style="opacity:0.4;">•</span><span class="telem-mem">${memStr}</span></span>`;
      }
    } else {
      telemCell.innerHTML = '<span style="color:var(--muted); font-size:10px;">—</span>';
    }
  }

  const statusText = tr.querySelector('.docker-status-text');
  if (statusText && statusText.textContent !== c.status) {
    statusText.textContent = c.status;
    statusText.title = c.status;
  }
}

function bindDockerTableEvents(tbody) {
  if (tbody._dockerTableEventsBound) return;
  tbody._dockerTableEventsBound = true;

  tbody.addEventListener('click', async (e) => {
    const actBtn = e.target.closest('.btn-container-act');
    if (actBtn) {
      e.stopPropagation();
      const cid = actBtn.dataset.id;
      const cname = actBtn.dataset.name;
      const act = actBtn.dataset.action;
      if (!cid || !act) return;

      if (act === 'inspect') {
        openContainerInspector(cid, cname);
        return;
      }

      if (act === 'edit') {
        openContainerInspector(cid, cname, 'edit');
        return;
      }

      if (act === 'update-single') {
        if (!confirm(`Update container "${cname}" to the latest image? The newest image will be pulled and the container will be atomically recreated.`)) {
          return;
        }
        actBtn.disabled = true;
        actBtn.textContent = '⏳';
        showToast(`Updating "${cname}" to latest image...`, 'info');
        try {
          await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/update-image`);
          showToast(`Container "${cname}" updated and restarted successfully!`, 'success');
          await fetchAndRenderDockerContainers();
          await refreshDockerUpdatesStatus();
        } catch (err) {
          showToast(`Update failed: ${err.message}`, 'error');
          actBtn.disabled = false;
          actBtn.textContent = '⬆️';
        }
        return;
      }

      if (act === 'delete') {
        openContainerDeleteModal(cid, cname, actBtn.dataset.image || '', () => {
          fetchAndRenderDockerContainers();
        });
        return;
      }

      actBtn.disabled = true;
      actBtn.style.opacity = '0.5';
      showToast(`${act.toUpperCase()} request sent for ${cname}...`, 'info');

      try {
        await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: act });
        showToast(`Container "${cname}" successfully ${act}ed.`, 'success');
        await fetchAndRenderDockerContainers();
      } catch (err) {
        showToast(`Failed to ${act} container: ${err.message}`, 'error');
        actBtn.disabled = false;
        actBtn.style.opacity = '1';
      }
      return;
    }

    const nameLink = e.target.closest('.btn-docker-name-link');
    if (nameLink) {
      e.stopPropagation();
      const cid = nameLink.dataset.id;
      const cname = nameLink.dataset.name;
      if (cid) openContainerInspector(cid, cname);
    }
  });
}

export async function fetchAndRenderDockerContainers() {
  _bindDockerEvents();
  const tbody = document.getElementById('docker-containers-tbody');
  if (!tbody) return;
  try {
    const [list] = await Promise.all([
      api.get('/api/docker/containers'),
      _dockerUpdatesCache ? Promise.resolve() : refreshDockerUpdatesStatus().catch(() => {}),
    ]);
    _dockerContainersList = Array.isArray(list) ? list : [];
    renderDockerContainersTable();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export async function fetchCatalogSources() {
  try {
    const sources = await api.get('/api/docker/catalog/sources');
    _catalogSources = Array.isArray(sources) ? sources : [];
    updateCatalogSourcesBadge();
    return _catalogSources;
  } catch (err) {
    console.error('Failed to fetch catalog sources:', err);
    return [];
  }
}

export function updateCatalogSourcesBadge() {
  const badge = document.getElementById('catalog-sources-count-badge');
  if (badge) {
    const enabledCount = _catalogSources.filter((s) => s.enabled !== false).length;
    badge.textContent = enabledCount || _catalogSources.length || '1';
  }
}

export async function fetchAndRenderAppCatalog() {
  _bindDockerEvents();
  const grid = document.getElementById('docker-catalog-grid');
  if (!grid) return;
  try {
    const [list, sources] = await Promise.all([
      api.get('/api/docker/catalog'),
      api.get('/api/docker/catalog/sources').catch(() => []),
    ]);
    _catalogList = Array.isArray(list) ? list : [];
    _catalogSources = Array.isArray(sources) ? sources : [];

    const totalBadge = document.getElementById('catalog-total-badge');
    if (totalBadge) totalBadge.textContent = _catalogList.length;
    const allCount = document.getElementById('catalog-all-count');
    if (allCount) allCount.textContent = _catalogList.length;
    updateCatalogSourcesBadge();

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
      const matchImg = (app.image || '').toLowerCase().includes(q);
      const matchSrc = (app.source_name || '').toLowerCase().includes(q);
      if (!matchName && !matchDesc && !matchId && !matchImg && !matchSrc) return false;
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
    other: '📦',
  };

  grid.innerHTML = filtered.map((app) => {
    const icon = categoryIcons[app.category] || '📦';
    const logoHtml = app.logo
      ? `<img src="${escapeHtml(app.logo)}" alt="${escapeHtml(app.name)}" style="width:24px; height:24px; object-fit:contain; border-radius:4px; vertical-align:middle; flex-shrink:0;" onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='inline';" /><span style="font-size:20px; line-height:1; display:none;">${icon}</span>`
      : `<span style="font-size:20px; line-height:1;">${icon}</span>`;

    const sourceBadge = app.source_name && app.source_name !== 'Built-in'
      ? `<span class="ci-badge" style="font-size:8.5px; background:rgba(14,165,233,0.15); color:#38bdf8; border:1px solid rgba(14,165,233,0.3); padding:1px 5px; border-radius:3px;">${escapeHtml(app.source_name)}</span>`
      : `<span class="ci-badge" style="font-size:8.5px; background:rgba(37,194,160,0.15); color:var(--accent, #25c2a0); border:1px solid rgba(37,194,160,0.3); padding:1px 5px; border-radius:3px;">Built-in</span>`;

    const typeBadge = app.type === 'stack'
      ? `<span class="ci-badge" style="font-size:8.5px; background:rgba(168,85,247,0.15); color:#c084fc; border:1px solid rgba(168,85,247,0.3); padding:1px 5px; border-radius:3px;">Stack</span>`
      : '';

    const imageDisplay = app.image || (app.repository ? 'compose-stack' : 'container');

    return `
      <div class="catalog-app-card" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px; display:flex; flex-direction:column; justify-content:space-between; gap:10px; transition:border-color 0.2s, background 0.2s;">
        <div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:6px; margin-bottom:6px;">
            <div style="display:flex; align-items:center; gap:8px; overflow:hidden;">
              ${logoHtml}
              <div style="overflow:hidden;">
                <div style="font-size:12.5px; font-weight:700; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(app.name)}</div>
                <code style="font-size:9.5px; color:var(--muted); font-family:var(--font-mono, monospace); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:block;">${escapeHtml(imageDisplay)}</code>
              </div>
            </div>
            <div style="display:flex; gap:4px; align-items:center; flex-shrink:0;">
              ${typeBadge}
              ${sourceBadge}
              <span class="ci-badge" style="font-size:9px; text-transform:uppercase; background:rgba(255,255,255,0.06); color:#cbd5e1; padding:2px 6px; border-radius:4px;">${escapeHtml(app.category)}</span>
            </div>
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
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
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

    document.getElementById('adm-close-btn').addEventListener('click', (e) => {
      e.preventDefault();
      if (modal._close) modal._close();
    });
    document.getElementById('adm-cancel-btn').addEventListener('click', (e) => {
      e.preventDefault();
      if (modal._close) modal._close();
    });
    modal.addEventListener('click', (e) => {
      if (e.target === modal && modal._close) {
        modal._close();
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open') && modal._close) {
        modal._close();
      }
    });
  }

  modal._close = () => {
    if (modal._isDeploying) return;
    modal.classList.remove('open');
    modal.style.display = 'none';
    const vc = document.getElementById('adm-view-config');
    const vp = document.getElementById('adm-view-progress');
    const fc = document.getElementById('adm-footer-config');
    const fp = document.getElementById('adm-footer-progress');
    if (vc) vc.style.display = 'flex';
    if (vp) vp.style.display = 'none';
    if (fc) fc.style.display = 'flex';
    if (fp) fp.style.display = 'none';
  };

  // Ensure config view is visible by default and open modal
  modal._isDeploying = false;
  modal.classList.add('open');
  modal.style.display = 'flex';

  const viewConfig = document.getElementById('adm-view-config');
  const viewProgress = document.getElementById('adm-view-progress');
  const footerConfig = document.getElementById('adm-footer-config');
  const footerProgress = document.getElementById('adm-footer-progress');
  if (viewConfig) viewConfig.style.display = 'flex';
  if (viewProgress) viewProgress.style.display = 'none';
  if (footerConfig) footerConfig.style.display = 'flex';
  if (footerProgress) footerProgress.style.display = 'none';

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
    copyTextToClipboard(composePre.textContent).then((ok) => {
      if (ok) {
        showToast('Docker Compose YAML copied to clipboard!', 'success');
      } else {
        showToast('Failed to copy to clipboard', 'warn');
      }
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
      modal._isDeploying = false;

      try {
        fetchAndRenderDockerContainers();
      } catch (e) {}

      showToast(`${appId} stack deployed and running!`, 'success');
    } else if (data.step === 'error') {
      modal._isDeploying = false;
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
    modal._isDeploying = true;
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
      modal._isDeploying = false;
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
      modal._isDeploying = false;
      if (modal._close) modal._close();
    };
  }
}

export async function openDockerPruneModal() {
  let modal = document.getElementById('docker-prune-modal-overlay');
  if (!modal) {
    const html = `
      <div id="docker-prune-modal-overlay" class="smart-modal-backdrop" style="display:none; z-index:10020;">
        <div id="docker-prune-modal-window" class="smart-modal-window" style="width:580px; max-width:94vw; max-height:88vh; display:flex; flex-direction:column;">
          <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:18px;">🧹</span>
              <span style="font-weight:700; color:#fff; font-size:13px;">Docker Storage Prune & Cleanup</span>
            </div>
            <button class="win-btn close-btn" id="dpm-close-btn" title="Close" aria-label="Close"></button>
          </div>
          <div style="padding:16px; overflow-y:auto; display:flex; flex-direction:column; gap:12px;">
            <div style="font-size:11px; color:#cbd5e1; line-height:1.4;">
              Reclaim host storage space by pruning unused Docker resources. Safe for running containers.
            </div>

            <!-- Live Disk Usage Breakdown -->
            <div id="dpm-df-summary" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(110px, 1fr)); gap:8px;">
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:9px; color:var(--muted); text-transform:uppercase; font-weight:700;">Images</div>
                <div id="dpm-df-images" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:9px; color:var(--muted); text-transform:uppercase; font-weight:700;">Containers</div>
                <div id="dpm-df-containers" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:9px; color:var(--muted); text-transform:uppercase; font-weight:700;">Volumes</div>
                <div id="dpm-df-volumes" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(0,240,255,0.06); border:1px solid rgba(0,240,255,0.2); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:9px; color:var(--accent-cyan, #00f0ff); text-transform:uppercase; font-weight:700;">Reclaimable</div>
                <div id="dpm-df-reclaimable" style="font-size:12.5px; font-weight:800; color:var(--ok2, #25c2a0); margin-top:2px;">--</div>
              </div>
            </div>

            <!-- Prune Options -->
            <div style="background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:12px; display:flex; flex-direction:column; gap:10px;">
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-containers" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Stopped Containers</strong>
                  <div style="font-size:10px; color:var(--muted);">Deletes all exited, stopped, and dead containers.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-images" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Dangling Images</strong>
                  <div style="font-size:10px; color:var(--muted);">Removes untagged &lt;none&gt; build layers and intermediate images.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-all-images" style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune ALL Unused Images</strong>
                  <div style="font-size:10px; color:var(--muted);">Removes all images not currently referenced by at least one running container.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-volumes" style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Unused Local Volumes</strong>
                  <div style="font-size:10px; color:var(--warn, #f5a623);">Caution: Removes local anonymous volumes not mounted by containers.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-buildcache" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Build Cache & Unused Networks</strong>
                  <div style="font-size:10px; color:var(--muted);">Frees temporary Docker build cache layers and disconnected bridge networks.</div>
                </div>
              </label>
            </div>
          </div>
          <div style="padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="dpm-cancel-btn">Cancel</button>
            <button class="btn-pill-toggle" id="dpm-confirm-btn" style="background:linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); color:#fff; border:none; padding:6px 18px; font-weight:700; cursor:pointer;">
              🧹 Run Prune & Reclaim Storage
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('docker-prune-modal-overlay');

    const closeModal = () => {
      modal.classList.remove('open');
      modal.style.display = 'none';
    };
    document.getElementById('dpm-close-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    document.getElementById('dpm-cancel-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
    });

    const optImages = document.getElementById('dpm-opt-images');
    const optAllImages = document.getElementById('dpm-opt-all-images');
    const syncImageOptions = () => {
      if (optAllImages && optImages) {
        if (optAllImages.checked) {
          optImages.checked = true;
          optImages.disabled = true;
          optImages.parentElement.style.opacity = '0.5';
        } else {
          optImages.disabled = false;
          optImages.parentElement.style.opacity = '1';
        }
      }
    };
    if (optAllImages) optAllImages.onchange = syncImageOptions;
  }

  modal.classList.add('open');
  modal.style.display = 'flex';

  // Fetch live system df metrics
  try {
    const df = await api.get('/api/docker/system/df');
    const imgEl = document.getElementById('dpm-df-images');
    const cntEl = document.getElementById('dpm-df-containers');
    const volEl = document.getElementById('dpm-df-volumes');
    const recEl = document.getElementById('dpm-df-reclaimable');

    if (imgEl && df.images) imgEl.textContent = `${df.images.total_count} (${df.images.unused_count} unused)`;
    if (cntEl && df.containers) cntEl.textContent = `${df.containers.total_count} (${df.containers.stopped_count} stopped)`;
    if (volEl && df.volumes) volEl.textContent = `${df.volumes.total_count} (${df.volumes.unused_count} unused)`;
    if (recEl) recEl.textContent = df.total_reclaimable_human || '0 B';
  } catch (err) {
    console.warn('Failed to load system df:', err);
  }

  const confirmBtn = document.getElementById('dpm-confirm-btn');
  confirmBtn.disabled = false;
  confirmBtn.textContent = '🧹 Run Prune & Reclaim Storage';

  confirmBtn.onclick = async () => {
    const pruneContainers = document.getElementById('dpm-opt-containers').checked;
    const pruneImages = document.getElementById('dpm-opt-images').checked;
    const allImages = document.getElementById('dpm-opt-all-images').checked;
    const pruneVolumes = document.getElementById('dpm-opt-volumes').checked;
    const pruneBuildCache = document.getElementById('dpm-opt-buildcache').checked;

    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Pruning storage...';

    try {
      const res = await api.post('/api/docker/system/prune', {
        prune_containers: pruneContainers,
        prune_images: pruneImages || allImages,
        all_images: allImages,
        prune_volumes: pruneVolumes,
        prune_networks: pruneBuildCache,
        prune_build_cache: pruneBuildCache,
      });

      const details = [];
      if (res.images_deleted_count > 0) details.push(`${res.images_deleted_count} image${res.images_deleted_count > 1 ? 's' : ''}`);
      if (res.containers_deleted_count > 0) details.push(`${res.containers_deleted_count} container${res.containers_deleted_count > 1 ? 's' : ''}`);
      if (res.volumes_deleted_count > 0) details.push(`${res.volumes_deleted_count} volume${res.volumes_deleted_count > 1 ? 's' : ''}`);
      if (res.build_caches_deleted_count > 0) details.push(`${res.build_caches_deleted_count} build cache layer${res.build_caches_deleted_count > 1 ? 's' : ''}`);

      let msg = '';
      if (res.space_reclaimed_bytes > 0) {
        msg = `Prune completed! Reclaimed ${res.space_reclaimed_human}${details.length ? ' (' + details.join(', ') + ')' : ''}.`;
      } else if (details.length > 0) {
        msg = `Prune completed! Removed ${details.join(', ')} (no additional space freed).`;
      } else {
        msg = 'Prune completed: No unused resources were found to remove.';
      }

      showToast(msg, 'success');
      modal.classList.remove('open');
      modal.style.display = 'none';

      await fetchAndRenderDockerContainers();
    } catch (err) {
      showToast(`Prune failed: ${err.message}`, 'error');
      confirmBtn.disabled = false;
      confirmBtn.textContent = '🧹 Run Prune & Reclaim Storage';
    }
  };
}

function formatRelativeTime(ts) {
  if (!ts) return 'Never';
  const sec = Math.floor(Date.now() / 1000 - ts);
  if (sec < 60) return 'Just now';
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export async function openAppSourcesModal() {
  let modal = document.getElementById('app-sources-modal-overlay');
  if (!modal) {
    const html = `
      <div id="app-sources-modal-overlay" class="smart-modal-backdrop" style="display:none; z-index:10020;">
        <div id="app-sources-modal-window" class="smart-modal-window" style="width:680px; max-width:94vw; max-height:88vh; display:flex; flex-direction:column;">
          <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:18px;">🌐</span>
              <span style="font-weight:700; color:#fff; font-size:13px;">App Template Sources</span>
            </div>
            <button class="win-btn close-btn" id="asm-close-btn" title="Close" aria-label="Close"></button>
          </div>
          <div style="padding:16px; overflow-y:auto; display:flex; flex-direction:column; gap:14px;">
            <div style="font-size:11px; color:#cbd5e1; line-height:1.4;">
              Expand your App Catalog with external Portainer v2/v3 or custom JSON template repositories.
            </div>

            <!-- Quick Add Preset Banner -->
            <div id="asm-preset-banner" style="background:linear-gradient(135deg, rgba(14,165,233,0.12), rgba(37,194,160,0.08)); border:1px solid rgba(14,165,233,0.3); border-radius:8px; padding:12px 14px; display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;">
              <div>
                <div style="font-size:12px; font-weight:700; color:#fff; display:flex; align-items:center; gap:6px;">
                  <span>⭐ Lissy93 Portainer Templates</span>
                  <span class="ci-badge" style="font-size:9px; background:rgba(37,194,160,0.2); color:var(--accent);">790+ Apps</span>
                </div>
                <div style="font-size:10.5px; color:#94a3b8; margin-top:2px;">
                  Comprehensive community catalog of self-hosted homelab applications, web tools, and stacks.
                </div>
              </div>
              <button class="btn-pill-toggle" id="asm-btn-add-lissy" style="background:var(--brand, #0ea5e9); color:#fff; border:none; padding:5px 12px; font-weight:700; font-size:11px; white-space:nowrap; cursor:pointer;">
                + Add Lissy93 (790+ Apps)
              </button>
            </div>

            <!-- Add Custom Source Form -->
            <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px; display:flex; flex-direction:column; gap:10px;">
              <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px;">Add Custom Template Source</div>
              <div style="display:grid; grid-template-columns:1fr 2fr auto; gap:8px; align-items:end;">
                <div>
                  <label style="display:block; font-size:9.5px; font-weight:700; color:var(--muted); margin-bottom:3px;">SOURCE NAME</label>
                  <input type="text" id="asm-input-name" placeholder="e.g. Community Apps" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:5px 8px;">
                </div>
                <div>
                  <label style="display:block; font-size:9.5px; font-weight:700; color:var(--muted); margin-bottom:3px;">TEMPLATE URL (JSON)</label>
                  <input type="url" id="asm-input-url" placeholder="https://example.com/templates.json" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:5px 8px;">
                </div>
                <div>
                  <button class="btn-pill-toggle" id="asm-btn-add-custom" style="background:linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); color:#fff; border:none; padding:5px 14px; font-weight:700; font-size:11px; height:28px; white-space:nowrap; cursor:pointer;">
                    + Add & Sync
                  </button>
                </div>
              </div>
              <div id="asm-form-status" style="font-size:10.5px; display:none; padding:4px 6px; border-radius:4px;"></div>
            </div>

            <!-- Active Sources List -->
            <div>
              <div style="font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase; margin-bottom:8px; letter-spacing:0.5px;">
                Configured Sources (<span id="asm-sources-count">0</span>)
              </div>
              <div id="asm-sources-list" style="display:flex; flex-direction:column; gap:8px; max-height:260px; overflow-y:auto;">
                <div style="text-align:center; color:var(--muted); padding:16px;">Loading sources...</div>
              </div>
            </div>
          </div>
          <div style="padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:flex-end; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="asm-done-btn">Done</button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('app-sources-modal-overlay');

    const closeModal = () => {
      modal.classList.remove('open');
      modal.style.display = 'none';
      fetchAndRenderAppCatalog();
    };
    document.getElementById('asm-close-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    document.getElementById('asm-done-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
    });

    // Wire Lissy93 quick add
    const btnLissy = document.getElementById('asm-btn-add-lissy');
    if (btnLissy) {
      btnLissy.onclick = async () => {
        btnLissy.disabled = true;
        btnLissy.textContent = '⏳ Adding & Syncing...';
        try {
          await api.post('/api/docker/catalog/sources', {
            name: 'Lissy93 Templates',
            url: 'https://raw.githubusercontent.com/Lissy93/portainer-templates/main/templates.json',
          });
          showToast('Lissy93 Portainer templates added (790+ apps)!', 'success');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(`Failed to add Lissy93 templates: ${err.message}`, 'error');
          btnLissy.disabled = false;
          btnLissy.textContent = '+ Add Lissy93 (790+ Apps)';
        }
      };
    }

    // Wire custom add
    const btnCustom = document.getElementById('asm-btn-add-custom');
    if (btnCustom) {
      btnCustom.onclick = async () => {
        const nameInput = document.getElementById('asm-input-name');
        const urlInput = document.getElementById('asm-input-url');
        const statusEl = document.getElementById('asm-form-status');
        const name = (nameInput.value || '').trim();
        const url = (urlInput.value || '').trim();
        if (!name || !url) {
          statusEl.style.display = 'block';
          statusEl.style.background = 'rgba(239,68,68,0.15)';
          statusEl.style.color = '#fca5a5';
          statusEl.textContent = 'Please enter both name and URL.';
          return;
        }
        btnCustom.disabled = true;
        btnCustom.textContent = '⏳ Syncing...';
        statusEl.style.display = 'block';
        statusEl.style.background = 'rgba(14,165,233,0.15)';
        statusEl.style.color = '#38bdf8';
        statusEl.textContent = 'Fetching and caching remote templates...';
        try {
          await api.post('/api/docker/catalog/sources', { name, url });
          nameInput.value = '';
          urlInput.value = '';
          statusEl.style.background = 'rgba(37,194,160,0.15)';
          statusEl.style.color = 'var(--accent)';
          statusEl.textContent = '✓ Source added and synced successfully!';
          showToast(`Added template source "${name}"!`, 'success');
          setTimeout(() => { statusEl.style.display = 'none'; }, 3000);
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          statusEl.style.background = 'rgba(239,68,68,0.15)';
          statusEl.style.color = '#fca5a5';
          statusEl.textContent = `Error: ${err.message}`;
          showToast(`Failed to add source: ${err.message}`, 'error');
        } finally {
          btnCustom.disabled = false;
          btnCustom.textContent = '+ Add & Sync';
        }
      };
    }
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
  await refreshSourcesUI();
}

async function refreshSourcesUI() {
  const listEl = document.getElementById('asm-sources-list');
  const countEl = document.getElementById('asm-sources-count');
  const btnLissy = document.getElementById('asm-btn-add-lissy');
  if (!listEl) return;

  try {
    const sources = await api.get('/api/docker/catalog/sources');
    _catalogSources = Array.isArray(sources) ? sources : [];
    if (countEl) countEl.textContent = _catalogSources.length;
    updateCatalogSourcesBadge();

    // Check if Lissy93 is present
    const hasLissy = _catalogSources.some(
      (s) => (s.url && s.url.includes('Lissy93')) || (s.name && s.name.toLowerCase().includes('lissy'))
    );
    if (btnLissy) {
      if (hasLissy) {
        btnLissy.disabled = true;
        btnLissy.style.background = 'rgba(37,194,160,0.15)';
        btnLissy.style.color = 'var(--accent)';
        btnLissy.style.border = '1px solid rgba(37,194,160,0.3)';
        btnLissy.textContent = '✓ Lissy93 Added';
      } else {
        btnLissy.disabled = false;
        btnLissy.style.background = 'var(--brand, #0ea5e9)';
        btnLissy.style.color = '#fff';
        btnLissy.style.border = 'none';
        btnLissy.textContent = '+ Add Lissy93 (790+ Apps)';
      }
    }

    if (_catalogSources.length === 0) {
      listEl.innerHTML = '<div style="text-align:center; color:var(--muted); padding:16px;">No template sources configured.</div>';
      return;
    }

    listEl.innerHTML = _catalogSources.map((src) => {
      const isBuiltin = src.id === 'builtin';
      const isEnabled = src.enabled !== false;
      const statusBadge = src.status === 'ok'
        ? `<span class="ci-badge" style="font-size:9px; background:rgba(37,194,160,0.15); color:var(--accent);">✓ Synced (${formatRelativeTime(src.last_synced)})</span>`
        : (src.status === 'error'
          ? `<span class="ci-badge" style="font-size:9px; background:rgba(239,68,68,0.15); color:#fca5a5;" title="${escapeHtml(src.error || 'Sync failed')}">⚠️ Error</span>`
          : `<span class="ci-badge" style="font-size:9px; background:rgba(14,165,233,0.15); color:#38bdf8;">🔄 ${escapeHtml(src.status || 'pending')}</span>`);

      const toggleBtnClass = isEnabled ? 'btn-pill-toggle active' : 'btn-pill-toggle';
      const toggleText = isEnabled ? 'Enabled' : 'Disabled';

      return `
        <div class="asm-source-card" data-sourceid="${escapeHtml(src.id)}" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px 12px; display:flex; justify-content:space-between; align-items:center; gap:10px;">
          <div style="overflow:hidden; flex:1;">
            <div style="display:flex; align-items:center; gap:8px;">
              <strong style="font-size:12px; color:#fff;">${escapeHtml(src.name)}</strong>
              <span class="ci-badge" style="font-size:9px; background:rgba(255,255,255,0.06); color:#cbd5e1;">${src.item_count || 0} apps</span>
              ${statusBadge}
            </div>
            <div style="font-size:10px; color:var(--muted); font-family:var(--font-mono, monospace); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px;">
              ${escapeHtml(src.url)}
            </div>
            ${src.error ? `<div style="font-size:10px; color:#fca5a5; margin-top:3px;">${escapeHtml(src.error)}</div>` : ''}
          </div>
          <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
            <button class="${toggleBtnClass} asm-btn-toggle" data-sourceid="${escapeHtml(src.id)}" data-enabled="${isEnabled ? 'true' : 'false'}" style="font-size:10.5px; padding:3px 8px; cursor:pointer;">
              ${toggleText}
            </button>
            <button class="btn-pill-toggle asm-btn-sync" data-sourceid="${escapeHtml(src.id)}" title="Sync Now" style="font-size:11px; padding:3px 8px; cursor:pointer;">
              🔄
            </button>
            ${!isBuiltin ? `
              <button class="btn-pill-toggle asm-btn-delete" data-sourceid="${escapeHtml(src.id)}" title="Delete Source" style="font-size:11px; padding:3px 8px; color:#fca5a5; cursor:pointer;">
                🗑️
              </button>
            ` : ''}
          </div>
        </div>
      `;
    }).join('');

    // Wire toggle buttons
    listEl.querySelectorAll('.asm-btn-toggle').forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.dataset.sourceid;
        const curEnabled = btn.dataset.enabled === 'true';
        btn.disabled = true;
        try {
          await api.post(`/api/docker/catalog/sources/${sid}/toggle`, { enabled: !curEnabled });
          showToast(`Source ${!curEnabled ? 'enabled' : 'disabled'}.`, 'info');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(`Failed to toggle source: ${err.message}`, 'error');
          btn.disabled = false;
        }
      };
    });

    // Wire sync buttons
    listEl.querySelectorAll('.asm-btn-sync').forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.dataset.sourceid;
        btn.disabled = true;
        btn.textContent = '⏳';
        try {
          const res = await api.post(`/api/docker/catalog/sources/${sid}/sync`);
          showToast(`Source synced (${res.source ? res.source.item_count : 0} apps).`, 'success');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(`Failed to sync source: ${err.message}`, 'error');
          btn.disabled = false;
          btn.textContent = '🔄';
        }
      };
    });

    // Wire delete buttons
    listEl.querySelectorAll('.asm-btn-delete').forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.dataset.sourceid;
        if (!confirm('Are you sure you want to delete this template source and all cached templates?')) return;
        btn.disabled = true;
        try {
          await api.delete(`/api/docker/catalog/sources/${sid}`);
          showToast('Source deleted successfully.', 'info');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(`Failed to delete source: ${err.message}`, 'error');
          btn.disabled = false;
        }
      };
    });

  } catch (err) {
    listEl.innerHTML = `<div style="text-align:center; color:var(--crit); padding:16px;">Failed to load sources: ${escapeHtml(err.message)}</div>`;
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

export async function fetchAndRenderNetworkTopology() {
  const switchFaceplate = document.getElementById('network-switch-faceplate');
  const physicalTbody = document.getElementById('network-physical-tbody');
  const bridgesContainer = document.getElementById('network-bridges-container');
  const dockerContainer = document.getElementById('network-docker-container');
  const activeBadge = document.getElementById('net-active-ports-badge');

  // KPI elements
  const kpiIp = document.getElementById('net-kpi-ip');
  const kpiIface = document.getElementById('net-kpi-iface');
  const kpiGw = document.getElementById('net-kpi-gw');
  const kpiDns = document.getElementById('net-kpi-dns');
  const kpiSpeed = document.getElementById('net-kpi-speed');
  const kpiCarrier = document.getElementById('net-kpi-carrier');
  const kpiDocker = document.getElementById('net-kpi-docker');
  const kpiContainers = document.getElementById('net-kpi-containers');

  function fmtBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
  }

  try {
    const topo = await api.get('/api/system/network-topology');
    if (!topo || topo.status !== 'ok') {
      if (physicalTbody) {
        physicalTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--crit); padding:16px;">Failed to load network topology: ${escapeHtml(topo?.message || 'Unknown error')}</td></tr>`;
      }
      return;
    }

    const summary = topo.summary || {};
    const physical = topo.physical_interfaces || [];
    const bonds = topo.bonds || [];
    const bridges = topo.bridges || [];
    const dockerNets = topo.docker_networks || [];

    // 1. Update KPIs
    if (kpiIp) kpiIp.textContent = summary.primary_ip || '--';
    if (kpiIface) kpiIface.textContent = `Via ${summary.primary_interface || 'eth0'}`;
    if (kpiGw) kpiGw.textContent = summary.default_gateway || '--';
    if (kpiDns) kpiDns.textContent = `DNS: ${(summary.dns_servers || []).join(', ') || 'Auto'}`;
    if (kpiSpeed) kpiSpeed.textContent = summary.max_speed || '--';
    if (kpiCarrier) kpiCarrier.textContent = `${summary.active_physical || 0} of ${summary.total_physical || 0} Ports Online`;
    if (kpiDocker) kpiDocker.textContent = `${summary.docker_networks_count || 0} Networks`;
    if (kpiContainers) kpiContainers.textContent = `${summary.docker_containers_count || 0} Containers Attached`;
    if (activeBadge) activeBadge.textContent = `${summary.active_physical || 0} Active`;

    // 2. Render Hardware Switch Ports (Front-Panel Faceplate)
    if (switchFaceplate) {
      if (physical.length === 0) {
        switchFaceplate.innerHTML = `<div style="color:var(--muted); font-size:12px; padding:12px;">No physical network interfaces detected.</div>`;
      } else {
        switchFaceplate.innerHTML = physical.map((nic) => {
          const isUp = Boolean(nic.is_up);
          const is10G = (nic.speed_mbps || 0) >= 2500;
          const speedPillClass = isUp ? (is10G ? 'speed-10g' : '') : 'speed-down';
          const linkLedClass = isUp ? 'led-link-on' : '';
          const speedLedClass = isUp ? (is10G ? 'led-speed-10g' : 'led-speed-gig') : '';

          return `
            <div class="switch-port-jack ${isUp ? 'is-active' : ''}">
              <div class="switch-port-top">
                <div class="switch-port-id">
                  <svg style="width:12px; height:12px; fill:${isUp ? 'var(--ok2, #3bf58b)' : 'var(--muted, #64748b)'};"><circle cx="6" cy="6" r="4"/></svg>
                  ${escapeHtml(nic.name.toUpperCase())}
                </div>
                <div class="switch-port-leds">
                  <div class="switch-led-group">
                    <span class="switch-led-lbl">LNK</span>
                    <span class="switch-led-dot ${linkLedClass}"></span>
                  </div>
                  <div class="switch-led-group">
                    <span class="switch-led-lbl">ACT</span>
                    <span class="switch-led-dot ${speedLedClass}"></span>
                  </div>
                </div>
              </div>
              <div class="switch-port-socket">
                <svg viewBox="0 0 24 24">
                  <rect x="3" y="5" width="18" height="14" rx="2" />
                  <path d="M7 15v-4h10v4M9 11V8h6v3" />
                </svg>
              </div>
              <div class="switch-port-badge-row">
                <span class="switch-speed-pill ${speedPillClass}">${escapeHtml(nic.speed_human || (isUp ? 'Connected' : 'Disconnected'))}</span>
                <span style="font-size:10px; color:var(--muted);">${nic.duplex === 'full' ? 'Full Duplex' : nic.duplex}</span>
              </div>
              <div class="switch-port-meta">
                <div>MAC: ${escapeHtml(nic.mac || 'N/A')}</div>
                ${nic.master ? `<div style="color:var(--accent-cyan);">Master: ${escapeHtml(nic.master)}</div>` : ''}
              </div>
            </div>
          `;
        }).join('');
      }
    }

    // 3. Render Physical Interfaces Detailed Table
    if (physicalTbody) {
      if (physical.length === 0) {
        physicalTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--muted); padding:16px;">No physical interfaces found.</td></tr>`;
      } else {
        physicalTbody.innerHTML = physical.map((nic) => {
          const isUp = Boolean(nic.is_up);
          const rxFmt = fmtBytes(nic.rx_bytes);
          const txFmt = fmtBytes(nic.tx_bytes);

          return `
            <tr>
              <td>
                <div style="display:flex; align-items:center; gap:6px; font-weight:700; font-family:var(--font-mono, monospace);">
                  <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${isUp ? 'var(--ok2, #3bf58b)' : 'var(--muted, #64748b)'};"></span>
                  ${escapeHtml(nic.name)}
                </div>
              </td>
              <td>
                <span class="switch-speed-pill ${isUp ? 'speed-10g' : 'speed-down'}">
                  ${isUp ? 'UP / CARRIER' : 'DOWN'}
                </span>
              </td>
              <td>
                <span style="font-weight:600; color:${isUp ? '#f8fafc' : 'var(--muted)'};">${escapeHtml(nic.speed_human)}</span>
                <span style="font-size:10px; color:var(--muted); margin-left:4px;">(${escapeHtml(nic.duplex)})</span>
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:11px;">${escapeHtml(nic.mac || '--')}</td>
              <td style="font-family:var(--font-mono, monospace);">${escapeHtml(String(nic.mtu || 1500))}</td>
              <td>
                ${nic.master ? `<span class="network-member-pill" style="color:var(--accent-cyan); border-color:rgba(56,189,248,0.3);">${escapeHtml(nic.master)}</span>` : '<span style="color:var(--muted);">Standalone</span>'}
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:11px;">
                <div>↓ ${rxFmt} <span style="font-size:9.5px; color:var(--muted);">(${nic.rx_packets?.toLocaleString() || 0} pkts)</span></div>
                <div>↑ ${txFmt} <span style="font-size:9.5px; color:var(--muted);">(${nic.tx_packets?.toLocaleString() || 0} pkts)</span></div>
              </td>
              <td style="font-size:11px; color:var(--muted);">
                <div>${escapeHtml(nic.driver || 'Generic')}</div>
                <div style="font-family:var(--font-mono, monospace); font-size:9.5px;">${escapeHtml(nic.pci_slot || '--')}</div>
              </td>
            </tr>
          `;
        }).join('');
      }
    }

    // 4. Render Virtual Switches, Bonds & Bridges
    if (bridgesContainer) {
      const items = [];
      // Bridges
      bridges.forEach((br) => {
        items.push(`
          <div class="network-bridge-card">
            <div class="network-bridge-header">
              <span class="network-bridge-name">Bridge: ${escapeHtml(br.name)}</span>
              <span class="network-bridge-ip">${escapeHtml(br.ip_address || 'Unassigned IP')}</span>
            </div>
            <div style="font-size:11px; color:var(--muted);">Member Ports:</div>
            <div class="network-bridge-members">
              ${(br.interfaces || []).map((m) => `<span class="network-member-pill">${escapeHtml(m)}</span>`).join('') || '<span style="color:var(--muted); font-size:10px;">No members</span>'}
            </div>
          </div>
        `);
      });

      // Bonds
      bonds.forEach((b) => {
        items.push(`
          <div class="network-bridge-card">
            <div class="network-bridge-header">
              <span class="network-bridge-name">Bond: ${escapeHtml(b.name)}</span>
              <span class="switch-speed-pill speed-10g">${escapeHtml(b.mode || 'Bonding')}</span>
            </div>
            <div style="font-size:11px; color:var(--muted);">Active Slave: <strong style="color:var(--ok2, #3bf58b);">${escapeHtml(b.active_slave || 'None')}</strong></div>
            <div class="network-bridge-members">
              ${(b.slaves || []).map((s) => `<span class="network-member-pill ${s === b.active_slave ? 'active' : ''}">${escapeHtml(s)}</span>`).join('')}
            </div>
          </div>
        `);
      });

      bridgesContainer.innerHTML = items.length > 0 ? items.join('') : `<div style="color:var(--muted); font-size:12px; padding:12px;">No virtual bridges or bonds configured.</div>`;
    }

    // 5. Render Docker Networks & Containers
    if (dockerContainer) {
      if (dockerNets.length === 0) {
        dockerContainer.innerHTML = `<div style="color:var(--muted); font-size:12px; padding:12px;">No active Docker bridge networks found.</div>`;
      } else {
        dockerContainer.innerHTML = dockerNets.map((net) => {
          const containers = net.containers || [];
          return `
            <div class="network-docker-card">
              <div class="network-docker-top">
                <div class="network-docker-name">
                  <svg class="ic" style="width:14px; height:14px;"><use href="#i-chip"/></svg>
                  ${escapeHtml(net.name)}
                  <span class="network-docker-driver">${escapeHtml(net.driver)}</span>
                </div>
                <div class="network-docker-cidr">
                  ${net.subnet ? `Subnet: <strong>${escapeHtml(net.subnet)}</strong>` : ''}
                  ${net.gateway ? ` • Gateway: <strong>${escapeHtml(net.gateway)}</strong>` : ''}
                  ${net.bridge_device ? ` • Dev: <strong>${escapeHtml(net.bridge_device)}</strong>` : ''}
                </div>
              </div>
              <div class="network-docker-containers">
                ${containers.length === 0 ? '<span style="font-size:11px; color:var(--muted);">No containers attached</span>' : containers.map((c) => `
                  <div class="network-container-chip">
                    <span class="network-chip-dot"></span>
                    <span class="network-chip-name">${escapeHtml(c.name)}</span>
                    <span class="network-chip-ip">${escapeHtml(c.ipv4 || 'Host')}</span>
                    ${c.ports?.length ? `<span class="network-chip-ports">[${escapeHtml(c.ports.join(', '))}]</span>` : ''}
                  </div>
                `).join('')}
              </div>
            </div>
          `;
        }).join('');
      }
    }
  } catch (err) {
    console.warn('[ZettNAS] Error fetching network topology:', err);
    if (physicalTbody) {
      physicalTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--crit); padding:16px;">Failed to load network topology: ${escapeHtml(err.message || String(err))}</td></tr>`;
    }
  }
}

export async function fetchAndRenderDisksInventory() {
  const tbody = document.getElementById('mgmt-disks-inventory-tbody');
  if (!tbody) return;

  try {
    const res = await api.request('/api/chassis/config');
    let disks = [];
    if (res.ok) {
      const data = await res.json();
      const hddDisks = (data.bays || []).map((b) => b.disk).filter(Boolean);
      const nvmeDisks = (data.nvme_slots || []).map((s) => s.disk).filter(Boolean);
      disks = [...hddDisks, ...nvmeDisks];
    } else {
      disks = state.latestStats?.disks || [];
    }

    if (disks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:20px;">No physical disks discovered.</td></tr>`;
      return;
    }

    if (tbody.firstElementChild && tbody.firstElementChild.querySelector('td[colspan]')) {
      tbody.innerHTML = '';
    }

    bindDiskTableEvents(tbody);

    reconcileKeyedTable(
      tbody,
      disks,
      (d) => d.dev || d.name || 'unknown',
      createDiskRow,
      updateDiskRow
    );
  } catch (err) {
    console.warn('[Management] Failed to fetch disks inventory:', err);
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--crit); padding:20px;">Failed to load disks inventory.</td></tr>`;
  }
}

function buildDiskRowInner(d) {
  const devName = d.dev || d.name || 'unknown';
  const isStandby = Boolean(d.standby || d.health === 'standby');
  const thermal = getThermalLevel(d.temp, isStandby);
  const modelStr = d.model || 'Generic Disk';
  const serialStr = d.serial && d.serial !== 'Unknown' ? d.serial : '--';
  const transportStr = (d.transport || (devName.startsWith('nvme') ? 'nvme' : 'sata')).toUpperCase();
  const driverStr = d.controller_driver || (devName.startsWith('nvme') ? 'nvme' : 'ahci');
  const sizeStr = d.size_formatted || d.size || '--';
  const healthStr = isStandby ? 'STANDBY' : (d.health ? String(d.health).toUpperCase() : 'OK');

  return `
    <td style="font-weight:700; color:#fff;">/dev/${escapeHtml(devName)}</td>
    <td>
      <div style="font-weight:600; color:#e2e8f0;">${escapeHtml(modelStr)}</div>
      <div style="font-size:10px; color:var(--muted);">SN: ${escapeHtml(serialStr)}</div>
    </td>
    <td>
      <span class="bay-sub-badge" style="background:rgba(255,255,255,0.06); padding:2px 6px; border-radius:4px;">${escapeHtml(transportStr)} • ${escapeHtml(driverStr)}</span>
    </td>
    <td class="disk-size-cell" style="font-weight:600; color:var(--accent-cyan,#00f0ff);">${escapeHtml(sizeStr)}</td>
    <td>
      <span class="bay-health-tag ${thermal.cls}">${escapeHtml(healthStr)}</span>
    </td>
    <td>
      <span class="bay-temp-pill" style="color:${thermal.color}; border-color:${thermal.color};">${thermal.text}</span>
    </td>
    <td style="text-align:right;">
      <div style="display:inline-flex; gap:6px;">
        <button class="btn-pill-toggle btn-locate-row" data-dev="${devName}" title="Locate Drive (Blink Bay LED)" style="padding:3px 8px; font-size:10.5px;">⚡ Locate</button>
        <button class="btn-pill-toggle btn-smart-row" data-dev="${devName}" title="View S.M.A.R.T. Diagnostics" style="padding:3px 8px; font-size:10.5px;">📊 S.M.A.R.T.</button>
      </div>
    </td>
  `;
}

function createDiskRow(d) {
  const devName = d.dev || d.name || 'unknown';
  const tr = document.createElement('tr');
  tr.dataset.key = devName;
  tr.dataset.dev = devName;
  tr.innerHTML = buildDiskRowInner(d);
  return tr;
}

function updateDiskRow(row, d) {
  const isStandby = Boolean(d.standby || d.health === 'standby');
  const thermal = getThermalLevel(d.temp, isStandby);
  const healthStr = isStandby ? 'STANDBY' : (d.health ? String(d.health).toUpperCase() : 'OK');

  const healthTag = row.querySelector('.bay-health-tag');
  if (healthTag) {
    healthTag.className = `bay-health-tag ${thermal.cls}`;
    healthTag.textContent = healthStr;
  }
  const tempPill = row.querySelector('.bay-temp-pill');
  if (tempPill) {
    tempPill.style.color = thermal.color;
    tempPill.style.borderColor = thermal.color;
    tempPill.textContent = thermal.text;
  }
  const sizeTd = row.querySelector('.disk-size-cell') || row.children[3];
  if (sizeTd && (d.size_formatted || d.size)) {
    sizeTd.textContent = d.size_formatted || d.size;
  }
}

function bindDiskTableEvents(tbody) {
  if (tbody._diskEventsBound) return;
  tbody._diskEventsBound = true;

  tbody.addEventListener('click', (e) => {
    const locateBtn = e.target.closest('.btn-locate-row');
    if (locateBtn) {
      const dev = locateBtn.dataset.dev;
      triggerLocateDisk(dev, locateBtn.closest('tr'));
      return;
    }

    const smartBtn = e.target.closest('.btn-smart-row');
    if (smartBtn) {
      const dev = smartBtn.dataset.dev;
      const row = smartBtn.closest('tr');
      const isStandby = row?.querySelector('.bay-health-tag')?.textContent?.trim() === 'STANDBY';
      if (isStandby) {
        showConfirmToast(
          'Drive in Standby Mode',
          `Disk /dev/${dev} is currently sleeping. Querying S.M.A.R.T. diagnostics will wake the drive, spinning up platters. Do you wish to wake it?`,
          () => {
            showToast(`Waking disk /dev/${dev}...`, 'info');
            ZettEventBus.emit('modal:smart:open', { dev, forceWake: true });
          }
        );
      } else {
        ZettEventBus.emit('modal:smart:open', dev);
      }
    }
  });
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

  win.addEventListener('mousedown', () => {
    bringToFront(win);
    saveOpenWindowsState();
  });

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
        win.dataset.snapped = 'maximize';
        _isMaximized = true;
        saveWindowBounds('management', {
          left: 16,
          top: 56,
          width: window.innerWidth - 32,
          height: window.innerHeight - 128,
          snapped: 'maximize'
        });
        saveOpenWindowsState();
      } else {
        win.dataset.snapped = '';
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
        saveWindowBounds('management', {
          left: Math.round(window.innerWidth / 2 - 450),
          top: Math.round(window.innerHeight / 2 - 300),
          width: 900,
          height: 600,
          snapped: ''
        });
        saveOpenWindowsState();
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
    const earlyStyle = document.getElementById('zettnas-mgmt-early-style');
    if (earlyStyle) earlyStyle.remove();
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
    saveOpenWindowsState();
  }

  


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
    } else if (paneId === 'mgmt-pane-dock') {
      if (typeof window.initDockSettingsControls === 'function') {
        window.initDockSettingsControls();
      }
    } else if (paneId === 'mgmt-pane-screensaver') {
      if (typeof window.initScreensaverSettingsControls === 'function') {
        window.initScreensaverSettingsControls();
      }
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
    } else if (paneId === 'mgmt-pane-network') {
      fetchAndRenderNetworkTopology();
    } else if (paneId === 'mgmt-pane-unraid') {
      if (state.lastStats) updateManagementTelemetry(state.lastStats);
    } else if (paneId === 'mgmt-pane-docker') {
      fetchAndRenderDockerContainers();
    } else if (paneId === 'mgmt-pane-chassis-twin') {
      const mount = document.getElementById('mgmt-chassis-twin-mount');
      if (mount) fetchAndRenderChassisTwin(mount);
    } else if (paneId === 'mgmt-pane-storage-topo') {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      if (mount) fetchAndRenderStorageTopology(mount);
    } else if (paneId === 'mgmt-pane-storage-shares') {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      if (mount) fetchAndRenderNetworkShares(mount);
    } else if (paneId === 'mgmt-pane-storage-remotes') {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      if (mount) fetchAndRenderRemoteStorage(mount);
    } else if (paneId === 'mgmt-pane-storage-disks') {
      fetchAndRenderDisksInventory();
    } else if (paneId === 'mgmt-pane-system') {
      if (typeof fetchAPITokens === 'function') fetchAPITokens();
      fetchAndRenderBackupJobs();
      fetchAndRenderSystemSnapshots();
    } else if (paneId === 'mgmt-pane-notifications') {
      fetchAndRenderNotificationConfig();
    } else if (paneId === 'mgmt-pane-users') {
      import('./users.js').then((m) => m.loadUsersPane());
    } else if (paneId === 'mgmt-pane-about') {
      fetchAndRenderSystemAbout();
    }
  }


  function showSection(targetId) {
    const earlyStyle = document.getElementById('zettnas-mgmt-early-style');
    if (earlyStyle) earlyStyle.remove();
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
    } else if (targetId === 'mgmt-sec-activity') {
      sectionName = t('mgmt.activity_title', 'Activity Monitor');
    } else if (targetId === 'mgmt-sec-docker') {
      sectionName = t('mgmt.docker_title', 'Apps & Containers');
      fetchAndRenderDockerContainers();
    } else if (targetId === 'mgmt-sec-hardware' || targetId === 'mgmt-sec-services') {
      sectionName = t('mgmt.hardware_title', 'Hardware & Profiles');
      if (state.lastStats || state.latestStats) updateManagementTelemetry(state.lastStats || state.latestStats);
    } else if (targetId === 'mgmt-sec-storage') {
      sectionName = t('mgmt.storage_title', 'Storage & Chassis');
    } else if (targetId === 'mgmt-sec-ups') {
      sectionName = t('mgmt.sidebar_ups', 'UPS & Power');
      if (typeof fetchAndRenderUpsTelemetry === 'function') fetchAndRenderUpsTelemetry();
      else if (typeof fetchAndRenderUPS === 'function') fetchAndRenderUPS();
    } else if (targetId === 'mgmt-sec-system-group') {
      sectionName = t('mgmt.system_title', 'System');
    }

    if (titleText) titleText.textContent = sectionName;

    const parentCard = document.getElementById(targetId);
    if (parentCard) {
      if (desiredSubPane) {
        parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
          t.classList.toggle('active', t.dataset.tabTarget === desiredSubPane);
        });
        parentCard.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
          p.style.display = p.id === desiredSubPane ? 'block' : 'none';
        });
        triggerSubTabLoad(desiredSubPane);
      } else {
        let activeTabBtn = parentCard.querySelector('.mgmt-inner-tab.active');
        if (!activeTabBtn) {
          activeTabBtn = parentCard.querySelector('.mgmt-inner-tab');
          if (activeTabBtn) activeTabBtn.classList.add('active');
        }
        if (activeTabBtn) {
          const paneId = activeTabBtn.dataset.tabTarget;
          parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
            t.classList.toggle('active', t === activeTabBtn);
          });
          parentCard.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
            p.style.display = p.id === paneId ? 'block' : 'none';
          });
          triggerSubTabLoad(paneId);
        }
      }
    }
    saveOpenWindowsState();
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
      saveOpenWindowsState();
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
      saveOpenWindowsState();
    });
  });

  // Hub cards click listener
  document.querySelectorAll('.mgmt-app-card').forEach((card) => {
    card.addEventListener('click', () => {
      const targetId = card.dataset.mgmtTarget;
      if (targetId) {
        showSection(targetId);
        saveOpenWindowsState();
      }
    });
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const targetId = card.dataset.mgmtTarget;
        if (targetId) {
          showSection(targetId);
          saveOpenWindowsState();
        }
      }
    });
  });

  // Header quick tabs click listener
  document.querySelectorAll('.mgmt-category-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.mgmtTarget;
      if (targetId) {
        showSection(targetId);
        saveOpenWindowsState();
      }
    });
  });

  // Back button click listener
  if (backBtn) {
    backBtn.addEventListener('click', () => {
      showHub();
      saveOpenWindowsState();
    });
  }

  // Global helper to open / focus Management window
  window.openManagementWindow = (sectionId = null) => {
    if (sectionId) {
      showSection(sectionId);
    } else {
      showHub();
    }

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
  };

  // Support window:open event bus deep-linking
  ZettEventBus.on('window:open', (payload) => {
    if (payload && (payload.id === 'management' || payload.id === 'management-window')) {
      window.openManagementWindow(payload.pane || payload.section);
    }
  });

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

  // Profile buttons listener and keyboard navigation
  const profileBtns = Array.from(document.querySelectorAll('.profile-btn'));
  profileBtns.forEach((btn, idx) => {
    btn.addEventListener('click', async () => {
      const p = btn.dataset.profile;
      if (!p) return;
      _activeProfile = p;
      profileBtns.forEach((b) => {
        const isAct = b === btn;
        b.classList.toggle('active', isAct);
        b.setAttribute('aria-checked', isAct ? 'true' : 'false');
      });
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

    btn.addEventListener('keydown', (e) => {
      let targetBtn = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        targetBtn = profileBtns[(idx + 1) % profileBtns.length];
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        targetBtn = profileBtns[(idx - 1 + profileBtns.length) % profileBtns.length];
      }
      if (targetBtn) {
        targetBtn.focus();
        targetBtn.click();
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

  // Network topology refresh button
  const refreshNetBtn = document.getElementById('btn-refresh-network-topology');
  if (refreshNetBtn) {
    refreshNetBtn.addEventListener('click', () => {
      fetchAndRenderNetworkTopology();
      showToast('Network topology refreshed.', 'info');
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

  // Chassis digital twin refresh button
  const refreshChassisBtn = document.getElementById('btn-refresh-chassis');
  if (refreshChassisBtn) {
    refreshChassisBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-chassis-twin-mount');
      if (mount) fetchAndRenderChassisTwin(mount);
      showToast('Chassis digital twin refreshed.', 'info');
    });
  }

  // Storage pool topology refresh & create buttons
  const refreshTopoBtn = document.getElementById('btn-refresh-topo');
  if (refreshTopoBtn) {
    refreshTopoBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      if (mount) fetchAndRenderStorageTopology(mount);
      showToast('Storage topology refreshed.', 'info');
    });
  }

  const createPoolBtn = document.getElementById('btn-create-storage-pool');
  if (createPoolBtn) {
    createPoolBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      openCreateStoragePoolModal(() => {
        if (mount) fetchAndRenderStorageTopology(mount);
      });
    });
  }

  const manageSnapsBtn = document.getElementById('btn-manage-snapshots');
  if (manageSnapsBtn) {
    manageSnapsBtn.addEventListener('click', () => {
      openSnapshotsModal();
    });
  }

  // Network shares refresh & create buttons
  const refreshSharesBtn = document.getElementById('btn-refresh-shares');
  if (refreshSharesBtn) {
    refreshSharesBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      if (mount) fetchAndRenderNetworkShares(mount);
      showToast('Network shares refreshed.', 'info');
    });
  }

  const createShareBtn = document.getElementById('btn-create-network-share');
  if (createShareBtn) {
    createShareBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      openCreateNetworkShareModal(() => {
        if (mount) fetchAndRenderNetworkShares(mount);
      });
    });
  }

  // Remote & Cloud Storage refresh button
  const refreshRemotesBtn = document.getElementById('btn-refresh-remotes');
  if (refreshRemotesBtn) {
    refreshRemotesBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      if (mount) fetchAndRenderRemoteStorage(mount);
      showToast('Remote storage refreshed.', 'info');
    });
  }

  // Connect Cloud Remote button
  const addRemoteBtn = document.getElementById('btn-add-cloud-remote');
  if (addRemoteBtn) {
    addRemoteBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      openNewCloudRemoteModal(() => {
        if (mount) fetchAndRenderRemoteStorage(mount);
      });
    });
  }

  // Disks inventory refresh button
  const refreshDisksInvBtn = document.getElementById('btn-refresh-disks-inventory');

  if (refreshDisksInvBtn) {
    refreshDisksInvBtn.addEventListener('click', () => {
      fetchAndRenderDisksInventory();
      showToast('Disks inventory refreshed.', 'info');
    });
  }

  // Check for updates button
  const checkUpdatesBtn = document.getElementById('btn-check-updates');
  if (checkUpdatesBtn) {
    checkUpdatesBtn.addEventListener('click', () => {
      fetchAndRenderSystemAbout(true);
    });
  }

  // Diagnostics bundle download button
  const downloadDiagBtn = document.getElementById('btn-download-diagnostics');
  if (downloadDiagBtn) {
    downloadDiagBtn.addEventListener('click', downloadDiagnosticsBundle);
  }

  // Notification Center triggers
  const sendTestAlertBtn = document.getElementById('btn-send-test-alert');
  if (sendTestAlertBtn) {
    sendTestAlertBtn.addEventListener('click', testAllNotificationChannels);
  }
  const saveNotifBtn = document.getElementById('btn-save-notifications');
  if (saveNotifBtn) {
    saveNotifBtn.addEventListener('click', saveNotificationsConfig);
  }
  document.querySelectorAll('.notif-cfg-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      openChannelConfigModal(btn.dataset.channel);
    });
  });
  document.querySelectorAll('.notif-test-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      testSingleChannel(btn.dataset.channel);
    });
  });
  const saveChannelModalBtn = document.getElementById('btn-save-channel-modal');
  if (saveChannelModalBtn) {
    saveChannelModalBtn.addEventListener('click', saveCurrentChannelModal);
  }
  const closeChannelModalBtn = document.getElementById('btn-close-channel-modal');
  if (closeChannelModalBtn) {
    closeChannelModalBtn.addEventListener('click', () => {
      const m = document.getElementById('modal-notification-channel');
      if (m) m.style.display = 'none';
    });
  }

  // Hyper-Backup & Snapshots event bindings
  const btnOpenBackupJob = document.getElementById('btn-open-create-backup-job');
  const modalBackupJob = document.getElementById('modal-create-backup-job');
  const btnCloseBackupJob = document.getElementById('modal-backup-job-close-btn');
  const btnCancelBackupJob = document.getElementById('modal-backup-job-cancel-btn');
  const formBackupJob = document.getElementById('create-backup-job-form');
  const btnRefreshBackupJobs = document.getElementById('btn-refresh-backup-jobs');

  if (btnOpenBackupJob && modalBackupJob) {
    btnOpenBackupJob.addEventListener('click', () => {
      modalBackupJob.style.display = 'flex';
      const nameInput = document.getElementById('backup-job-name');
      if (nameInput) nameInput.focus();
    });
  }
  const closeBackupModal = () => {
    if (modalBackupJob) modalBackupJob.style.display = 'none';
  };
  if (btnCloseBackupJob) btnCloseBackupJob.addEventListener('click', closeBackupModal);
  if (btnCancelBackupJob) btnCancelBackupJob.addEventListener('click', closeBackupModal);

  const destTypeSelect = document.getElementById('backup-job-dest-type');
  const remoteFieldsDiv = document.getElementById('backup-remote-fields');
  if (destTypeSelect && remoteFieldsDiv) {
    destTypeSelect.addEventListener('change', () => {
      remoteFieldsDiv.style.display = destTypeSelect.value === 'remote' ? 'flex' : 'none';
    });
  }

  if (formBackupJob) {
    formBackupJob.addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        name: document.getElementById('backup-job-name')?.value.trim() || 'Untitled Backup Task',
        source_subvolume: document.getElementById('backup-job-subvolume')?.value.trim() || '',
        destination_type: document.getElementById('backup-job-dest-type')?.value || 'remote',
        remote_name: document.getElementById('backup-job-remote-name')?.value.trim() || '',
        remote_path: document.getElementById('backup-job-remote-path')?.value.trim() || '',
        schedule: document.getElementById('backup-job-schedule')?.value || 'daily',
        retention_count: parseInt(document.getElementById('backup-job-retention')?.value, 10) || 7,
        enabled: !!document.getElementById('backup-job-enabled')?.checked,
      };

      try {
        await api.post('/api/backup/schedule', payload);
        showToast('Hyper-backup pipeline saved successfully!', 'success');
        closeBackupModal();
        formBackupJob.reset();
        fetchAndRenderBackupJobs();
      } catch (err) {
        showToast(`Failed to save backup job: ${err.message}`, 'error');
      }
    });
  }

  if (btnRefreshBackupJobs) {
    btnRefreshBackupJobs.addEventListener('click', () => fetchAndRenderBackupJobs());
  }

  // Snapshots modal & actions
  const btnOpenSnapshot = document.getElementById('btn-open-create-snapshot');
  const modalSnapshot = document.getElementById('modal-create-snapshot');
  const btnCloseSnapshot = document.getElementById('modal-create-snapshot-close-btn');
  const btnCancelSnapshot = document.getElementById('modal-create-snapshot-cancel-btn');
  const formSnapshot = document.getElementById('create-snapshot-form');
  const btnRefreshSnapshots = document.getElementById('btn-refresh-snapshots');

  if (btnOpenSnapshot && modalSnapshot) {
    btnOpenSnapshot.addEventListener('click', () => {
      modalSnapshot.style.display = 'flex';
      const subvolInput = document.getElementById('snapshot-subvol-input');
      if (subvolInput) subvolInput.focus();
    });
  }
  const closeSnapshotModal = () => {
    if (modalSnapshot) modalSnapshot.style.display = 'none';
  };
  if (btnCloseSnapshot) btnCloseSnapshot.addEventListener('click', closeSnapshotModal);
  if (btnCancelSnapshot) btnCancelSnapshot.addEventListener('click', closeSnapshotModal);

  if (formSnapshot) {
    formSnapshot.addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        subvol_name: document.getElementById('snapshot-subvol-input')?.value.trim() || '',
        snapshot_name: document.getElementById('snapshot-custom-name-input')?.value.trim() || undefined,
        readonly: !!document.getElementById('snapshot-readonly-input')?.checked,
      };

      try {
        await api.post('/api/backup/snapshots', payload);
        showToast('Filesystem snapshot created successfully!', 'success');
        closeSnapshotModal();
        formSnapshot.reset();
        fetchAndRenderSystemSnapshots();
      } catch (err) {
        showToast(`Failed to create snapshot: ${err.message}`, 'error');
      }
    });
  }

  if (btnRefreshSnapshots) {
    btnRefreshSnapshots.addEventListener('click', () => fetchAndRenderSystemSnapshots());
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

export async function downloadDiagnosticsBundle() {
  const btn = document.getElementById('btn-download-diagnostics');
  const btnIcon = document.getElementById('btn-download-diagnostics-icon');
  const btnText = document.getElementById('btn-download-diagnostics-text');

  if (btn) btn.disabled = true;
  if (btnIcon) btnIcon.textContent = '⏳';
  if (btnText) btnText.textContent = 'Generating Archive...';

  showToast('Generating diagnostics bundle (scrubbing secrets)...', 'info');

  try {
    const filename = await api.downloadBlob('/api/system/diagnostics-bundle', 'zettnas_diagnostics.zip');
    showToast(`Diagnostics bundle downloaded successfully (${filename}).`, 'success');
  } catch (err) {
    showToast(`Failed to download diagnostics: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (btnIcon) btnIcon.textContent = '📦';
    if (btnText) btnText.textContent = 'Download Diagnostics Bundle';
  }
}

// ============================================================================
// Notifications & Alert Channels Subsystem
// ============================================================================
let _notificationConfig = null;

export async function fetchAndRenderNotificationConfig() {
  try {
    const res = await api.get('/notifications/config');
    _notificationConfig = res || {};
    renderNotificationConfigUI();
  } catch (err) {
    logger.error('Failed to load notification config:', err);
    showToast(t('notif.load_fail', 'Failed to load notification settings'), 'error');
  }
}

export function renderNotificationConfigUI() {
  if (!_notificationConfig) return;
  const cfg = _notificationConfig;

  // Master switch
  const masterSwitch = document.getElementById('notif-master-enabled');
  const masterBadge = document.getElementById('notif-master-status-badge');
  if (masterSwitch) masterSwitch.checked = !!cfg.enabled;
  if (masterBadge) {
    masterBadge.textContent = cfg.enabled ? t('notif.badge.active', 'Active') : t('notif.badge.disabled', 'Disabled');
    masterBadge.style.background = cfg.enabled ? 'rgba(37,194,160,0.15)' : 'rgba(255,255,255,0.06)';
    masterBadge.style.color = cfg.enabled ? 'var(--ok2)' : 'var(--muted)';
    masterBadge.style.border = cfg.enabled ? '1px solid rgba(37,194,160,0.4)' : '1px solid rgba(255,255,255,0.1)';
  }

  // Channel badges
  const updateBadge = (id, active, activeText = 'Active') => {
    const b = document.getElementById(id);
    if (!b) return;
    b.textContent = active ? activeText : 'Off';
    b.style.background = active ? 'rgba(37,194,160,0.15)' : 'rgba(255,255,255,0.06)';
    b.style.color = active ? 'var(--ok2)' : 'var(--muted)';
    b.style.border = active ? '1px solid rgba(37,194,160,0.4)' : '1px solid rgba(255,255,255,0.1)';
  };

  updateBadge('notif-badge-discord', !!(cfg.discord_enabled && cfg.discord_webhook_url));
  updateBadge('notif-badge-telegram', !!(cfg.telegram_enabled && cfg.telegram_bot_token && cfg.telegram_chat_id));
  updateBadge('notif-badge-email', !!(cfg.email_enabled && cfg.smtp_host));
  updateBadge('notif-badge-ntfy', !!(cfg.ntfy_enabled && cfg.ntfy_topic));
  updateBadge('notif-badge-webhook', !!(cfg.webhook_enabled && cfg.webhook_url));

  const rawCount = Array.isArray(cfg.apprise_urls) ? cfg.apprise_urls.length : 0;
  updateBadge('notif-badge-apprise', rawCount > 0, `${rawCount} URLs`);

  // Event trigger checkboxes
  const setChk = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.checked = val !== false;
  };
  setChk('notif-toggle-smart', cfg.notify_on_smart);
  setChk('notif-toggle-ups', cfg.notify_on_ups);
  setChk('notif-toggle-temp', cfg.notify_on_temp);
  setChk('notif-toggle-fan', cfg.notify_on_fan);
  setChk('notif-toggle-copy', cfg.notify_on_copy);
  setChk('notif-toggle-container', cfg.notify_on_container);
  setChk('notif-toggle-backup', cfg.notify_on_backup);

  // Thresholds
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined) el.value = val;
  };
  setVal('notif-input-hdd-temp', cfg.hdd_temp_threshold ?? 50);
  setVal('notif-input-cpu-temp', cfg.cpu_temp_threshold ?? 80);
  setVal('notif-input-cooldown', Math.round((cfg.cooldown_seconds ?? 1800) / 60));
}

export async function saveNotificationsConfig() {
  if (!_notificationConfig) _notificationConfig = {};
  const cfg = _notificationConfig;

  cfg.enabled = !!document.getElementById('notif-master-enabled')?.checked;
  cfg.notify_on_smart = !!document.getElementById('notif-toggle-smart')?.checked;
  cfg.notify_on_ups = !!document.getElementById('notif-toggle-ups')?.checked;
  cfg.notify_on_temp = !!document.getElementById('notif-toggle-temp')?.checked;
  cfg.notify_on_fan = !!document.getElementById('notif-toggle-fan')?.checked;
  cfg.notify_on_copy = !!document.getElementById('notif-toggle-copy')?.checked;
  cfg.notify_on_container = !!document.getElementById('notif-toggle-container')?.checked;
  cfg.notify_on_backup = !!document.getElementById('notif-toggle-backup')?.checked;

  const hdd = parseInt(document.getElementById('notif-input-hdd-temp')?.value, 10);
  if (!isNaN(hdd)) cfg.hdd_temp_threshold = Math.max(30, Math.min(80, hdd));

  const cpu = parseInt(document.getElementById('notif-input-cpu-temp')?.value, 10);
  if (!isNaN(cpu)) cfg.cpu_temp_threshold = Math.max(40, Math.min(105, cpu));

  const cd = parseInt(document.getElementById('notif-input-cooldown')?.value, 10);
  if (!isNaN(cd)) cfg.cooldown_seconds = Math.max(1, Math.min(1440, cd)) * 60;

  try {
    const res = await api.post('/notifications/config', cfg);
    _notificationConfig = res.config || cfg;
    renderNotificationConfigUI();
    showToast(t('notif.saved_ok', 'Notification settings saved successfully!'), 'success');
  } catch (err) {
    logger.error('Failed to save notification settings:', err);
    showToast(err.message || 'Failed to save notifications', 'error');
  }
}

export async function testAllNotificationChannels() {
  const btn = document.getElementById('btn-send-test-alert');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Testing...';
  }
  try {
    const res = await api.post('/notifications/test', {});
    const channels = res?.tested_channels || {};
    const successList = Object.keys(channels).filter(k => channels[k]);
    if (successList.length > 0) {
      showToast(`✓ Test alerts delivered to: ${successList.join(', ')}`, 'success');
    } else {
      showToast('No active channels succeeded. Check configuration and credentials.', 'warning');
    }
  } catch (err) {
    showToast(`Test failed: ${err.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `⚡ <span data-i18n="mgmt.notif_btn_test_all">Send Test Alert</span>`;
    }
  }
}

export async function testSingleChannel(channel) {
  const btn = document.querySelector(`.notif-test-btn[data-channel="${channel}"]`);
  const origText = btn ? btn.textContent : '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳';
  }
  try {
    const res = await api.post('/notifications/test-channel', {
      channel: channel,
      config: _notificationConfig || {}
    });
    if (res?.success) {
      showToast(`✓ ${channel.toUpperCase()}: Delivered in ${res.latency_ms}ms`, 'success');
    } else {
      showToast(`⚠️ ${channel.toUpperCase()}: ${res.message || 'Delivery failed'}`, 'error');
    }
  } catch (err) {
    showToast(`Test failed for ${channel}: ${err.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }
}

export function openChannelConfigModal(channel) {
  const modal = document.getElementById('modal-notification-channel');
  if (!modal) return;
  const cfg = _notificationConfig || {};

  const titleEl = document.getElementById('notif-modal-title');
  const bodyEl = document.getElementById('notif-modal-body');
  const enableChk = document.getElementById('notif-modal-channel-enable');

  if (titleEl) titleEl.textContent = `Configure ${channel.charAt(0).toUpperCase() + channel.slice(1)} Alerts`;

  let formHtml = '';
  if (channel === 'discord') {
    if (enableChk) enableChk.checked = !!cfg.discord_enabled;
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">DISCORD WEBHOOK URL</label>
        <input type="url" id="cfg-discord-url" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="https://discord.com/api/webhooks/..." value="${escapeHtml(cfg.discord_webhook_url || '')}">
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Paste the Webhook URL created in your Discord channel settings -> Integrations.</div>
      </div>
    `;
  } else if (channel === 'telegram') {
    if (enableChk) enableChk.checked = !!cfg.telegram_enabled;
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">TELEGRAM BOT TOKEN</label>
        <input type="password" id="cfg-telegram-token" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="123456789:ABCDefgh..." value="${escapeHtml(cfg.telegram_bot_token || '')}">
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">TELEGRAM CHAT ID</label>
        <input type="text" id="cfg-telegram-chat" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="-100123456789" value="${escapeHtml(cfg.telegram_chat_id || '')}">
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Obtained from @userinfobot or your Telegram channel/group chat ID.</div>
      </div>
    `;
  } else if (channel === 'email') {
    if (enableChk) enableChk.checked = !!cfg.email_enabled;
    formHtml = `
      <div style="display:grid; grid-template-columns: 2fr 1fr; gap:10px; margin-bottom:12px;">
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">SMTP HOST</label>
          <input type="text" id="cfg-smtp-host" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="smtp.gmail.com" value="${escapeHtml(cfg.smtp_host || '')}">
        </div>
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">PORT</label>
          <input type="number" id="cfg-smtp-port" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" value="${cfg.smtp_port || 587}">
        </div>
      </div>
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">SMTP USER</label>
          <input type="text" id="cfg-smtp-user" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="user@domain.com" value="${escapeHtml(cfg.smtp_user || '')}">
        </div>
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">SMTP PASSWORD</label>
          <input type="password" id="cfg-smtp-pass" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="••••••••" value="${escapeHtml(cfg.smtp_pass || '')}">
        </div>
      </div>
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">FROM EMAIL</label>
          <input type="email" id="cfg-email-from" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="nas@domain.com" value="${escapeHtml(cfg.email_from || '')}">
        </div>
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">TO RECIPIENT(S)</label>
          <input type="email" id="cfg-email-to" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="admin@domain.com" value="${escapeHtml(cfg.email_to || '')}">
        </div>
      </div>
      <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-size:11px; color:#fff;">
        <input type="checkbox" id="cfg-smtp-tls" ${cfg.smtp_tls !== false ? 'checked' : ''}> Use TLS / STARTTLS Encryption
      </label>
    `;
  } else if (channel === 'ntfy') {
    if (enableChk) enableChk.checked = !!cfg.ntfy_enabled;
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">NTFY SERVER URL</label>
        <input type="url" id="cfg-ntfy-url" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="https://ntfy.sh" value="${escapeHtml(cfg.ntfy_url || 'https://ntfy.sh')}">
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">TOPIC NAME</label>
        <input type="text" id="cfg-ntfy-topic" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="my_nas_alerts" value="${escapeHtml(cfg.ntfy_topic || '')}">
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">ACCESS TOKEN (Optional)</label>
        <input type="password" id="cfg-ntfy-token" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="tk_••••••••" value="${escapeHtml(cfg.ntfy_token || '')}">
      </div>
    `;
  } else if (channel === 'webhook') {
    if (enableChk) enableChk.checked = !!cfg.webhook_enabled;
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">WEBHOOK URL</label>
        <input type="url" id="cfg-webhook-url" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="https://..." value="${escapeHtml(cfg.webhook_url || '')}">
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Receives POST requests with JSON payload: { event, title, message, level, timestamp }</div>
      </div>
    `;
  } else if (channel === 'apprise_raw') {
    const rawVal = Array.isArray(cfg.apprise_urls) ? cfg.apprise_urls.join('\n') : '';
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">APPRISE TARGET URLS (One per line)</label>
        <textarea id="cfg-apprise-raw" class="tz-select-input" style="width:100%; height:120px; font-family:monospace; font-size:11px; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="pover://userkey@token&#10;slack://TokenA/TokenB/TokenC&#10;gotify://gotify.server/token">${escapeHtml(rawVal)}</textarea>
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Apprise supports 100+ notification targets. See Apprise documentation for syntax.</div>
      </div>
    `;
  }

  if (bodyEl) bodyEl.innerHTML = formHtml;
  modal.dataset.currentChannel = channel;
  modal.style.display = 'flex';
}

export function saveCurrentChannelModal() {
  const modal = document.getElementById('modal-notification-channel');
  if (!modal) return;
  const channel = modal.dataset.currentChannel;
  if (!_notificationConfig) _notificationConfig = {};
  const cfg = _notificationConfig;
  const enabled = !!document.getElementById('notif-modal-channel-enable')?.checked;

  if (channel === 'discord') {
    cfg.discord_enabled = enabled;
    cfg.discord_webhook_url = document.getElementById('cfg-discord-url')?.value.trim() || '';
  } else if (channel === 'telegram') {
    cfg.telegram_enabled = enabled;
    const tok = document.getElementById('cfg-telegram-token')?.value.trim() || '';
    if (tok && tok !== '********') cfg.telegram_bot_token = tok;
    cfg.telegram_chat_id = document.getElementById('cfg-telegram-chat')?.value.trim() || '';
  } else if (channel === 'email') {
    cfg.email_enabled = enabled;
    cfg.smtp_host = document.getElementById('cfg-smtp-host')?.value.trim() || '';
    cfg.smtp_port = parseInt(document.getElementById('cfg-smtp-port')?.value, 10) || 587;
    cfg.smtp_user = document.getElementById('cfg-smtp-user')?.value.trim() || '';
    const pass = document.getElementById('cfg-smtp-pass')?.value || '';
    if (pass && pass !== '********') cfg.smtp_pass = pass;
    cfg.smtp_tls = !!document.getElementById('cfg-smtp-tls')?.checked;
    cfg.email_from = document.getElementById('cfg-email-from')?.value.trim() || '';
    cfg.email_to = document.getElementById('cfg-email-to')?.value.trim() || '';
  } else if (channel === 'ntfy') {
    cfg.ntfy_enabled = enabled;
    cfg.ntfy_url = document.getElementById('cfg-ntfy-url')?.value.trim() || 'https://ntfy.sh';
    cfg.ntfy_topic = document.getElementById('cfg-ntfy-topic')?.value.trim() || '';
    const tk = document.getElementById('cfg-ntfy-token')?.value.trim() || '';
    if (tk && tk !== '********') cfg.ntfy_token = tk;
  } else if (channel === 'webhook') {
    cfg.webhook_enabled = enabled;
    cfg.webhook_url = document.getElementById('cfg-webhook-url')?.value.trim() || '';
  } else if (channel === 'apprise_raw') {
    const rawLines = document.getElementById('cfg-apprise-raw')?.value.split('\n') || [];
    cfg.apprise_urls = rawLines.map(l => l.trim()).filter(Boolean);
  }

  saveNotificationsConfig();
  modal.style.display = 'none';
}


// =========================================================================
// Hyper-Backup Tasks & 3-2-1 Pipelines
// =========================================================================

export async function fetchAndRenderBackupJobs(mountEl) {
  const mount = mountEl || document.getElementById('backup-jobs-mount');
  if (!mount) return;

  try {
    const data = await api.get('/api/backup/schedule');
    const jobs = (data && data.jobs) || [];

    if (jobs.length === 0) {
      mount.innerHTML = `
        <div style="text-align: center; padding: 24px 16px; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px dashed rgba(255,255,255,0.1);">
          <div style="font-size: 24px; margin-bottom: 8px;">🛡️</div>
          <div style="font-size: 13px; font-weight: 700; color: #fff; margin-bottom: 4px;">No Backup Pipelines Configured</div>
          <div style="font-size: 11.5px; color: var(--muted); max-width: 400px; margin: 0 auto 12px; line-height: 1.4;">
            Automate snapshot rotation and offsite cloud backups to protect against drive failure, ransomware, or accidental deletion.
          </div>
          <button type="button" class="btn-rect primary" onclick="document.getElementById('btn-open-create-backup-job')?.click()" style="font-size: 11px; padding: 6px 14px;">
            Configure First Pipeline
          </button>
        </div>
      `;
      return;
    }

    const rowsHtml = jobs.map(job => {
      const isRemote = job.destination_type === 'remote';
      const destBadge = isRemote
        ? `<span class="badge" style="background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid rgba(14,165,233,0.3); font-size: 10px; padding: 2px 6px; border-radius: 4px;">☁️ ${escapeHtml(job.remote_name || 'Cloud')}:${escapeHtml(job.remote_path || '')}</span>`
        : `<span class="badge" style="background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); font-size: 10px; padding: 2px 6px; border-radius: 4px;">📸 Local Snapshot</span>`;

      const schedBadge = `<span class="badge" style="background: rgba(255,255,255,0.06); color: #cbd5e1; font-size: 10px; padding: 2px 6px; border-radius: 4px; text-transform: capitalize;">${escapeHtml(job.schedule || 'daily')}</span>`;
      
      let statusHtml = '';
      if (job.last_status === 'running') {
        statusHtml = `<span style="display:inline-flex; align-items:center; gap:4px; color: #38bdf8; font-size: 11px;"><span class="spinner-inline" style="width:10px; height:10px;"></span> Running...</span>`;
      } else if (job.last_status === 'success') {
        statusHtml = `<span style="color: #34d399; font-size: 11px; font-weight:600;">✓ Success</span>`;
      } else if (job.last_status === 'error') {
        statusHtml = `<span style="color: #f43f5e; font-size: 11px; font-weight:600;" title="${escapeHtml(job.last_error || '')}">⚠ Failed</span>`;
      } else {
        statusHtml = `<span style="color: var(--muted); font-size: 11px;">Idle</span>`;
      }

      const lastRunStr = job.last_run_at ? new Date(job.last_run_at * 1000).toLocaleString() : 'Never';

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11.5px;">
          <td style="padding: 10px 12px; font-weight: 600; color: #fff;">
            <div>${escapeHtml(job.name)}</div>
            <div style="font-size: 10px; color: var(--muted); font-weight: normal;">Subvolume: <code>${escapeHtml(job.source_subvolume || '@shares')}</code></div>
          </td>
          <td style="padding: 10px 12px;">${destBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
              ${schedBadge}
              <span style="font-size: 10px; color: var(--muted);">Keep ${job.retention_count || 7}</span>
            </div>
          </td>
          <td style="padding: 10px 12px;">
            <div>${statusHtml}</div>
            <div style="font-size: 10px; color: var(--muted);">${lastRunStr}</div>
          </td>
          <td style="padding: 10px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect primary btn-run-backup-job" data-job-id="${escapeHtml(job.id)}" style="font-size: 10.5px; padding: 4px 10px;">
                ▶ Run
              </button>
              <button class="btn-rect danger btn-delete-backup-job" data-job-id="${escapeHtml(job.id)}" style="font-size: 10.5px; padding: 4px 8px;">
                🗑
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    mount.innerHTML = `
      <div style="overflow-x: auto; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 10px; font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">Task & Target</th>
              <th style="padding: 8px 12px;">Pipeline</th>
              <th style="padding: 8px 12px;">Schedule & Retention</th>
              <th style="padding: 8px 12px;">Last Run</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    `;

    mount.querySelectorAll('.btn-run-backup-job').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.dataset.jobId;
        const origText = btn.innerHTML;
        try {
          btn.disabled = true;
          btn.innerHTML = `<span class="spinner-inline" style="width:8px; height:8px;"></span>`;
          showToast(`Triggering backup pipeline ${jobId}...`, 'info');
          await api.post(`/api/backup/schedule/${jobId}/run`);
          showToast(`Backup pipeline completed successfully!`, 'success');
          fetchAndRenderBackupJobs(mount);
        } catch (err) {
          showToast(`Backup run failed: ${err.message}`, 'error');
        } finally {
          btn.disabled = false;
          btn.innerHTML = origText;
        }
      });
    });

    mount.querySelectorAll('.btn-delete-backup-job').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.dataset.jobId;
        showConfirmToast(`Delete scheduled backup task "${jobId}"?`, async () => {
          try {
            await api.delete(`/api/backup/schedule/${jobId}`);
            showToast('Backup task removed.', 'success');
            fetchAndRenderBackupJobs(mount);
          } catch (err) {
            showToast(`Failed to delete job: ${err.message}`, 'error');
          }
        });
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: 12px;">Failed to load backup jobs: ${escapeHtml(err.message)}</div>`;
  }
}

// =========================================================================
// Storage Pool Snapshots & Revert
// =========================================================================

export async function fetchAndRenderSystemSnapshots(mountEl) {
  const mount = mountEl || document.getElementById('system-snapshots-mount');
  if (!mount) return;

  try {
    const data = await api.get('/api/backup/snapshots');
    const snaps = (data && data.snapshots) || [];

    if (snaps.length === 0) {
      mount.innerHTML = `
        <div style="text-align: center; padding: 20px; font-size: 12px; color: var(--muted);">
          No active filesystem snapshots found. Click "Take Snapshot" to create an atomic snapshot.
        </div>
      `;
      return;
    }

    const rowsHtml = snaps.map(s => {
      const createdDate = s.created_at ? new Date(s.created_at * 1000).toLocaleString() : 'N/A';
      const poolId = s.pool_id || 'default';
      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11.5px;">
          <td style="padding: 8px 12px; font-weight: 600; color: #fff;">
            <span style="font-family: monospace;">📸 ${escapeHtml(s.name)}</span>
          </td>
          <td style="padding: 8px 12px; color: var(--muted); font-size: 11px;">
            ${escapeHtml(s.path || '')}
          </td>
          <td style="padding: 8px 12px; color: var(--muted); font-size: 11px;">
            ${createdDate}
          </td>
          <td style="padding: 8px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect btn-sys-restore-snap" data-snap-name="${escapeHtml(s.name)}" data-pool-id="${escapeHtml(poolId)}" style="font-size: 10px; padding: 3px 8px; background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); color: #fbbf24; cursor: pointer;">
                ⏪ Restore
              </button>
              <button class="btn-rect danger btn-sys-delete-snap" data-snap-name="${escapeHtml(s.name)}" data-pool-id="${escapeHtml(poolId)}" style="font-size: 10px; padding: 3px 6px; cursor: pointer;">
                🗑
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    mount.innerHTML = `
      <div style="overflow-x: auto; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 10px; font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">Snapshot Name</th>
              <th style="padding: 8px 12px;">Filesystem Path</th>
              <th style="padding: 8px 12px;">Created</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    `;

    mount.querySelectorAll('.btn-sys-restore-snap').forEach(btn => {
      btn.addEventListener('click', () => {
        const snapName = btn.dataset.snapName;
        const poolId = btn.dataset.poolId || 'default';
        showConfirmToast(`Roll back to snapshot "${snapName}"? Existing subvolume will be archived safely.`, async () => {
          try {
            showToast(`Restoring snapshot ${snapName}...`, 'info');
            await api.post('/api/backup/restore-snapshot', {
              pool_id: poolId,
              snapshot_name: snapName,
            });
            showToast(`Snapshot "${snapName}" successfully restored!`, 'success');
            fetchAndRenderSystemSnapshots(mount);
          } catch (err) {
            showToast(`Restore failed: ${err.message}`, 'error');
          }
        });
      });
    });

    mount.querySelectorAll('.btn-sys-delete-snap').forEach(btn => {
      btn.addEventListener('click', () => {
        const snapName = btn.dataset.snapName;
        const poolId = btn.dataset.poolId || 'default';
        showConfirmToast(`Delete snapshot "${snapName}"?`, async () => {
          try {
            await api.delete(`/api/backup/snapshots/${encodeURIComponent(poolId)}/${encodeURIComponent(snapName)}`);
            showToast(`Snapshot "${snapName}" deleted.`, 'success');
            fetchAndRenderSystemSnapshots(mount);
          } catch (err) {
            showToast(`Failed to delete snapshot: ${err.message}`, 'error');
          }
        });
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: 12px;">Failed to load snapshots: ${escapeHtml(err.message)}</div>`;
  }
}


