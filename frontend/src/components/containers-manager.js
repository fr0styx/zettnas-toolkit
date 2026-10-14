/**
 * ZettNAS Toolkit - Dedicated Docker Containers & Services Window Manager
 * Provides a dedicated desktop window for Docker containers with live telemetry,
 * filtering, search, compose stacks, container controls, and app catalog access.
 */

import { api } from '../api.js';
import { escapeHtml, reconcileKeyedTable } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast, showBottomSheet } from '../toast.js';
import { t } from '../i18n.js';
import { makeDraggable, bringToFront } from './dock.js';
import { openContainerInspector, openContainerDeleteModal } from './container-modal.js';
import { openStackModal, openStackPickerModal } from './stack-modal.js';

let containersWindow = null;
let _cwContainersList = [];
let _cwUpdatesCache = null;
let _cwFilter = 'all';
let _cwSearchQuery = '';
let _cwSortCol = null;
let _cwSortDir = 'asc';
let _cwIsMax = false;
let _cwPreMaxBounds = null;

export function initContainersManager() {
  if (window._containersManagerInitialized) return;
  window._containersManagerInitialized = true;

  const cIcon = document.getElementById('containers-desktop-icon');
  const openContainers = (e) => {
    if (e && e.type === 'touchend') e.preventDefault();
    openContainersManager();
  };

  if (cIcon) {
    cIcon.addEventListener('click', openContainers);
    cIcon.addEventListener('touchend', openContainers);
    cIcon.addEventListener('dblclick', openContainers);
    cIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openContainers();
      }
    });
  }

  window.openContainersManager = openContainersManager;
  window.openContainersWindow = openContainersManager;
  window.renderContainersWindowTable = renderContainersWindowTable;

  // Inject Window DOM if not already present
  if (!document.getElementById('containers-manager-window')) {
    const html = `
      <div id="containers-manager-window" class="os-window containers-manager-window" style="display: none; width: 1040px; height: 660px; min-width: 680px; min-height: 440px;">
        <div class="os-window-header">
          <div class="os-window-title">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
            <span data-i18n="dock.containers">${t('dock.containers', 'Containers')}</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn min-btn" id="containers-min" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="containers-max" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="containers-close" title="Close" aria-label="Close"></button>
          </div>
        </div>

        <!-- Telemetry & Action Strip Header -->
        <div class="containers-telemetry-header" style="padding: 14px 16px; background: rgba(0,0,0,0.25); border-bottom: 1px solid rgba(255,255,255,0.06);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
            <!-- Quick Status Badges -->
            <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
              <div style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">
                <span>🐳</span> <span id="cw-stat-daemon">Docker Socket Active</span>
              </div>
              <div style="display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--muted);">
                <span>Total: <strong id="cw-count-all" style="color: #fff;">0</strong></span>
                <span>•</span>
                <span style="color: #34d399;">Running: <strong id="cw-count-running">0</strong></span>
                <span>•</span>
                <span style="color: #94a3b8;">Stopped: <strong id="cw-count-stopped">0</strong></span>
                <span id="cw-count-updates-wrap" style="display: none;">• <span style="color: #fbbf24;">Updates: <strong id="cw-count-updates">0</strong></span></span>
              </div>
            </div>

            <!-- Quick Action Buttons -->
            <div class="cw-action-btns-wrap" style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
              <button id="btn-cw-refresh" class="btn-pill-toggle" title="Refresh Containers" style="display: inline-flex; align-items: center; gap: 5px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <span data-i18n="mgmt.refresh">${t('mgmt.refresh', 'Refresh')}</span>
              </button>
              <button id="btn-cw-check-updates" class="btn-pill-toggle" title="Check remote registries for container image updates" style="display: inline-flex; align-items: center; gap: 5px;">
                <span style="color: var(--ok2, #25c2a0);">✓</span> <span>Check Updates</span>
              </button>
              <button id="btn-cw-update-all" class="btn-pill-toggle" style="display: none; align-items: center; gap: 5px; font-weight: 700; color: #fbbf24; border-color: rgba(251,191,36,0.4); background: rgba(251,191,36,0.12);" title="Update all containers with available image updates">
                <span>↑</span> <span>Update All (<span id="cw-updates-count-badge">0</span>)</span>
              </button>
              <button id="btn-cw-stacks" class="btn-pill-toggle" title="Manage Docker Compose Stacks" style="display: inline-flex; align-items: center; gap: 5px; color: var(--accent-cyan, #38bdf8);">
                <span>📁</span> <span>Compose Stacks</span>
              </button>
              <button id="btn-cw-prune" class="btn-pill-toggle" title="Clean up unused container images, stopped containers, and volumes">
                <span>🧹</span> <span>Prune</span>
              </button>
              <button id="btn-cw-catalog" class="btn-save-preset" style="background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff; font-weight: 700;">
                <span>📦</span> <span>App Catalog</span>
              </button>
            </div>
          </div>

          <!-- Filter Pills and Search Bar -->
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
            <div class="cw-docker-filter-pills" style="display: flex; gap: 6px; flex-wrap: wrap;">
              <button class="btn-pill-toggle cw-filter-btn active" data-filter="all"><span data-i18n="mgmt.docker_filter_all">${t('mgmt.docker_filter_all', 'All')}</span> <span id="cw-pill-all" class="docker-count-badge">0</span></button>
              <button class="btn-pill-toggle cw-filter-btn" data-filter="running"><span data-i18n="mgmt.docker_filter_running">${t('mgmt.docker_filter_running', 'Running')}</span> <span id="cw-pill-running" class="docker-count-badge">0</span></button>
              <button class="btn-pill-toggle cw-filter-btn" data-filter="stopped"><span data-i18n="mgmt.docker_filter_stopped">${t('mgmt.docker_filter_stopped', 'Stopped')}</span> <span id="cw-pill-stopped" class="docker-count-badge">0</span></button>
              <button class="btn-pill-toggle cw-filter-btn" id="btn-cw-filter-updates" data-filter="updates" style="display: none;"><span data-i18n="mgmt.docker_filter_updates">${t('mgmt.docker_filter_updates', 'Updates')}</span> <span id="cw-pill-updates" class="docker-count-badge badge-warning">0</span></button>
              <button class="btn-pill-toggle cw-filter-btn" data-filter="compose"><span data-i18n="mgmt.docker_filter_compose">${t('mgmt.docker_filter_compose', 'Stacks')}</span> <span id="cw-pill-compose" class="docker-count-badge">0</span></button>
              <button class="btn-pill-toggle cw-filter-btn" data-filter="standalone"><span data-i18n="mgmt.docker_filter_standalone">${t('mgmt.docker_filter_standalone', 'Standalone')}</span> <span id="cw-pill-standalone" class="docker-count-badge">0</span></button>
            </div>
            <div class="cw-docker-search-wrap" style="position: relative;">
              <input type="text" id="cw-docker-search-input" placeholder="${t('mgmt.docker_search_placeholder', 'Search containers, images, ports...')}" class="tz-text-input" style="font-size: 11px; padding: 4px 10px; width: 220px; height: 26px; border-radius: 4px;">
            </div>
          </div>
        </div>

        <!-- Table Body -->
        <div class="containers-content-body" data-scrollable="true" style="flex: 1; min-height: 0; overflow-y: auto; -webkit-overflow-scrolling: touch; touch-action: pan-y; padding: 14px 16px;">
          <div class="cw-docker-table-wrap" style="overflow-x: auto; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px;">
            <table class="copy-history-table docker-table responsive-cards">
              <thead>
                <tr>
                  <th class="cw-sortable-th" data-sort-col="name" role="columnheader" aria-sort="none" tabindex="0" title="Click to sort by Name / Stack">
                    <span data-i18n="mgmt.tbl_name_id">${t('mgmt.tbl_name_id', 'Name / Stack')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="hardware" role="columnheader" aria-sort="none" tabindex="0" title="Click to sort by Hardware">
                    <span data-i18n="mgmt.tbl_hardware">${t('mgmt.tbl_hardware', 'Hardware')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="cpu" role="columnheader" aria-sort="none" tabindex="0" title="Click to sort by CPU / RAM">
                    <span data-i18n="mgmt.tbl_telemetry">${t('mgmt.tbl_telemetry', 'CPU / RAM')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="ports" role="columnheader" aria-sort="none" tabindex="0" title="Click to sort by Ports & Web UI">
                    <span data-i18n="mgmt.tbl_ports">${t('mgmt.tbl_ports', 'Ports & Web UI')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="status" role="columnheader" aria-sort="none" tabindex="0" title="Click to sort by Status & Uptime">
                    <span data-i18n="mgmt.tbl_uptime">${t('mgmt.tbl_uptime', 'Status & Uptime')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th style="text-align: right;" data-i18n="mgmt.tbl_actions">${t('mgmt.tbl_actions', 'Actions')}</th>
                </tr>
              </thead>
              <tbody id="cw-docker-containers-tbody">
                <tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 24px;">Scanning Docker socket...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
  }

  containersWindow = document.getElementById('containers-manager-window');

  // Window Controls
  const minBtn = document.getElementById('containers-min');
  const maxBtn = document.getElementById('containers-max');
  const closeBtn = document.getElementById('containers-close');

  if (minBtn) {
    minBtn.onclick = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (containersWindow) {
        containersWindow.classList.add('window-minimized');
        containersWindow.classList.remove('open');
        containersWindow.style.setProperty('display', 'none', 'important');
      }
      if (window.DockManager) window.DockManager.minimize('containers');
    };
  }

  if (closeBtn) {
    closeBtn.onclick = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (containersWindow) {
        containersWindow.classList.add('window-minimized');
        containersWindow.classList.remove('open');
        containersWindow.style.setProperty('display', 'none', 'important');
      }
      if (window.DockManager) window.DockManager.closeWindow('containers');
    };
  }

  if (maxBtn) {
    maxBtn.onclick = () => {
      if (!_cwIsMax) {
        _cwPreMaxBounds = {
          left: containersWindow.style.left,
          top: containersWindow.style.top,
          width: containersWindow.style.width,
          height: containersWindow.style.height,
        };
        containersWindow.style.left = '0px';
        containersWindow.style.top = '36px';
        containersWindow.style.width = '100vw';
        containersWindow.style.height = 'calc(100vh - 36px - 72px)';
        _cwIsMax = true;
      } else {
        if (_cwPreMaxBounds) {
          containersWindow.style.left = _cwPreMaxBounds.left;
          containersWindow.style.top = _cwPreMaxBounds.top;
          containersWindow.style.width = _cwPreMaxBounds.width;
          containersWindow.style.height = _cwPreMaxBounds.height;
        }
        _cwIsMax = false;
      }
    };
  }

  // Quick Action Buttons
  const btnRefresh = document.getElementById('btn-cw-refresh');
  if (btnRefresh) {
    btnRefresh.onclick = () => {
      loadContainersData();
      showToast('Containers refreshed.', 'info');
    };
  }

  const btnCheckUpdates = document.getElementById('btn-cw-check-updates');
  if (btnCheckUpdates) {
    btnCheckUpdates.onclick = async () => {
      btnCheckUpdates.disabled = true;
      const orig = btnCheckUpdates.innerHTML;
      btnCheckUpdates.innerHTML = '<span>⏳</span> <span>Checking...</span>';
      try {
        const res = await api.post('/api/docker/updates/check');
        _cwUpdatesCache = res;
        const count = res.updates_available_count || 0;
        updateCwUpdatesUI(count);
        if (count > 0) {
          showToast(`Update check complete: ${count} container update${count > 1 ? 's' : ''} available!`, 'warn');
        } else {
          showToast('All containers are up to date!', 'success');
        }
        await loadContainersData();
      } catch (err) {
        showToast(`Update check failed: ${err.message}`, 'error');
      } finally {
        btnCheckUpdates.disabled = false;
        btnCheckUpdates.innerHTML = orig;
      }
    };
  }

  const btnUpdateAll = document.getElementById('btn-cw-update-all');
  if (btnUpdateAll) {
    btnUpdateAll.onclick = () => {
      showConfirmToast(
        'Update All Containers',
        'Are you sure you want to pull latest images and update all containers with available updates?',
        async () => {
          btnUpdateAll.disabled = true;
          showToast('Batch container update initiated...', 'info');
          try {
            await api.post('/api/docker/updates/apply-all');
            showToast('All container updates dispatched.', 'success');
            await loadContainersData();
          } catch (err) {
            showToast(`Batch update failed: ${err.message}`, 'error');
          } finally {
            btnUpdateAll.disabled = false;
          }
        },
        null,
        { okText: '↑ Update All', cancelText: 'Cancel', isUpdate: true }
      );
    };
  }

  const btnStacks = document.getElementById('btn-cw-stacks');
  if (btnStacks) {
    btnStacks.onclick = () => {
      openStackPickerModal();
    };
  }

  const btnPrune = document.getElementById('btn-cw-prune');
  if (btnPrune) {
    btnPrune.onclick = () => {
      import('./management.js').then((m) => {
        if (typeof m.openDockerPruneModal === 'function') m.openDockerPruneModal();
      });
    };
  }

  const btnCatalog = document.getElementById('btn-cw-catalog');
  if (btnCatalog) {
    btnCatalog.onclick = () => {
      if (typeof window.openManagementSection === 'function') {
        window.openManagementSection('mgmt-sec-docker', 'mgmt-pane-docker');
        const mcCatalogBtn = document.getElementById('btn-view-docker-catalog');
        if (mcCatalogBtn) mcCatalogBtn.click();
      }
    };
  }

  // Filter Buttons
  const filterBtns = containersWindow.querySelectorAll('.cw-filter-btn');
  filterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      filterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _cwFilter = btn.dataset.filter || 'all';
      renderContainersWindowTable();
    });
  });

  // Search Input
  const searchInput = document.getElementById('cw-docker-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      _cwSearchQuery = (e.target.value || '').trim().toLowerCase();
      renderContainersWindowTable();
    });
  }

  // Table Sorting
  const sortHeaders = containersWindow.querySelectorAll('.cw-sortable-th');
  sortHeaders.forEach((th) => {
    th.addEventListener('click', () => {
      const col = th.dataset.sortCol;
      if (!col) return;
      if (_cwSortCol === col) {
        _cwSortDir = _cwSortDir === 'asc' ? 'desc' : 'asc';
      } else {
        _cwSortCol = col;
        _cwSortDir = 'asc';
      }
      sortHeaders.forEach((h) => {
        h.setAttribute('aria-sort', h === th ? (_cwSortDir === 'asc' ? 'ascending' : 'descending') : 'none');
        const ind = h.querySelector('.docker-sort-indicator');
        if (ind) ind.textContent = h === th ? (_cwSortDir === 'asc' ? ' ▲' : ' ▼') : '';
      });
      renderContainersWindowTable();
    });
  });

  // Enable drag and bringToFront
  if (containersWindow) {
    makeDraggable(containersWindow, containersWindow.querySelector('.os-window-header'));
    containersWindow.addEventListener('mousedown', () => bringToFront(containersWindow));
  }
}

export function openContainersManager() {
  if (!containersWindow) {
    containersWindow = document.getElementById('containers-manager-window');
  }
  if (!containersWindow) return;

  if (window.DockManager) {
    if (!window.DockManager.windows['containers']) {
      window.DockManager.register('containers', containersWindow, '#i-chip', t('dock.containers', 'Containers'));
    }
    window.DockManager.restore('containers');
  }

  containersWindow.classList.remove('window-minimized');
  containersWindow.style.removeProperty('display');
  containersWindow.style.display = 'flex';
  bringToFront(containersWindow);
  ZettEventBus.emit('window:open', { id: 'containers-manager-window' });
  loadContainersData();
}

export async function loadContainersData() {
  try {
    const list = await api.get('/api/docker/containers').catch(() => []);
    _cwContainersList = Array.isArray(list) ? list : [];
    renderContainersWindowTable(_cwContainersList);
  } catch (err) {
    showToast(`Failed to load containers: ${err.message}`, 'error');
  }
}

function updateCwUpdatesUI(count) {
  const badgeWrap = document.getElementById('cw-count-updates-wrap');
  const countEl = document.getElementById('cw-count-updates');
  const pillBtn = document.getElementById('btn-cw-filter-updates');
  const pillCount = document.getElementById('cw-pill-updates');
  const updateAllBtn = document.getElementById('btn-cw-update-all');
  const updateAllBadge = document.getElementById('cw-updates-count-badge');

  if (count > 0) {
    if (badgeWrap) badgeWrap.style.display = 'inline';
    if (countEl) countEl.textContent = count;
    if (pillBtn) pillBtn.style.display = 'inline-flex';
    if (pillCount) pillCount.textContent = count;
    if (updateAllBtn) updateAllBtn.style.display = 'inline-flex';
    if (updateAllBadge) updateAllBadge.textContent = count;
  } else {
    if (badgeWrap) badgeWrap.style.display = 'none';
    if (pillBtn) pillBtn.style.display = 'none';
    if (updateAllBtn) updateAllBtn.style.display = 'none';
  }
}

export function renderContainersWindowTable(containersList = null) {
  if (Array.isArray(containersList)) {
    _cwContainersList = containersList;
  }
  const tbody = document.getElementById('cw-docker-containers-tbody');
  if (!tbody) return;

  const totalCount = _cwContainersList.length;
  const runningCount = _cwContainersList.filter((c) => c.state === 'running').length;
  const stoppedCount = _cwContainersList.filter((c) => c.state !== 'running').length;
  const composeCount = _cwContainersList.filter((c) => c.managed_by === 'compose' || Boolean(c.stack)).length;
  const standaloneCount = _cwContainersList.filter((c) => c.managed_by !== 'compose' && !c.stack).length;
  const updatesCount = _cwContainersList.filter((c) => {
    const info = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
    return Boolean(info?.has_update);
  }).length;

  const cAll = document.getElementById('cw-count-all');
  if (cAll) cAll.textContent = totalCount;
  const cRun = document.getElementById('cw-count-running');
  if (cRun) cRun.textContent = runningCount;
  const cStop = document.getElementById('cw-count-stopped');
  if (cStop) cStop.textContent = stoppedCount;
  const cUpd = document.getElementById('cw-count-updates');
  if (cUpd) cUpd.textContent = updatesCount;
  const pAll = document.getElementById('cw-pill-all');
  if (pAll) pAll.textContent = totalCount;
  const pRun = document.getElementById('cw-pill-running');
  if (pRun) pRun.textContent = runningCount;
  const pStop = document.getElementById('cw-pill-stopped');
  if (pStop) pStop.textContent = stoppedCount;
  const pComp = document.getElementById('cw-pill-compose');
  if (pComp) pComp.textContent = composeCount;
  const pStand = document.getElementById('cw-pill-standalone');
  if (pStand) pStand.textContent = standaloneCount;

  updateCwUpdatesUI(updatesCount);

  if (totalCount === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:24px;">${t('mgmt.docker_none', 'No Docker containers detected or socket not connected.')}</td></tr>`;
    return;
  }

  // Filter list
  const filtered = _cwContainersList.filter((c) => {
    if (_cwFilter === 'running' && c.state !== 'running') return false;
    if (_cwFilter === 'stopped' && c.state === 'running') return false;
    if (_cwFilter === 'updates') {
      const updateInfo = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
      if (!updateInfo?.has_update) return false;
    }
    if (_cwFilter === 'compose' && c.managed_by !== 'compose' && !c.stack) return false;
    if (_cwFilter === 'standalone' && (c.managed_by === 'compose' || Boolean(c.stack))) return false;

    if (_cwSearchQuery) {
      const q = _cwSearchQuery;
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

  // Sort list if sort column active
  if (_cwSortCol) {
    filtered.sort((a, b) => {
      let va = '';
      let vb = '';
      if (_cwSortCol === 'name') {
        va = (a.name || '').toLowerCase();
        vb = (b.name || '').toLowerCase();
      } else if (_cwSortCol === 'hardware') {
        va = (a.hardware_badges || []).map((b) => b.label).join(' ');
        vb = (b.hardware_badges || []).map((b) => b.label).join(' ');
      } else if (_cwSortCol === 'cpu') {
        va = a.cpu_pct || 0;
        vb = b.cpu_pct || 0;
      } else if (_cwSortCol === 'ports') {
        va = a.primary_port || 0;
        vb = b.primary_port || 0;
      } else if (_cwSortCol === 'status') {
        va = (a.state || '').toLowerCase();
        vb = (b.state || '').toLowerCase();
      }
      if (va < vb) return _cwSortDir === 'asc' ? -1 : 1;
      if (va > vb) return _cwSortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:24px;">${t('mgmt.docker_no_matching', 'No containers match your search or filter.')}</td></tr>`;
    return;
  }

  const currentHost = typeof window !== 'undefined' && window.location.hostname ? window.location.hostname : 'localhost';

  if (tbody.firstElementChild && tbody.firstElementChild.querySelector('td[colspan]')) {
    tbody.innerHTML = '';
  }

  bindCwTableEvents(tbody);

  reconcileKeyedTable(
    tbody,
    filtered,
    (c) => c.id || c.name,
    (c) => createCwContainerRow(c, currentHost),
    (tr, c) => updateCwContainerRow(tr, c, currentHost)
  );
}

function buildCwContainerRowInner(c, currentHost) {
  const isRunning = c.state === 'running';
  const badgeColor = isRunning ? 'var(--ok2)' : 'var(--muted)';
  const badgeBg = isRunning ? 'rgba(37, 194, 160, 0.15)' : 'rgba(255, 255, 255, 0.05)';
  const idShort = c.id ? c.id.slice(0, 12) : '';

  // Stack & Name
  let stackHtml = '';
  if (c.stack) {
    stackHtml = `<span class="docker-stack-pill clickable-stack-pill" data-stack="${escapeHtml(c.stack)}" title="Open & Edit Stack: ${escapeHtml(c.stack)}" style="cursor:pointer;">📁 ${escapeHtml(c.stack)}</span>`;
  } else {
    const originLabel = c.managed_by === 'unraid' ? 'Unraid' : 'Standalone';
    stackHtml = `<span class="docker-origin-pill">${originLabel}</span>`;
  }

  // Hardware Badges
  let hwHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
  if (c.hardware_badges && c.hardware_badges.length > 0) {
    hwHtml = c.hardware_badges
      .map(
        (b) =>
          `<span class="docker-hw-badge docker-hw-${escapeHtml(b.id)}" title="${escapeHtml(b.label)}">${escapeHtml(b.label)}</span>`
      )
      .join('');
  }

  // Telemetry (CPU / RAM)
  let telemHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
  if (isRunning) {
    const cpuStr = `${(c.cpu_pct || 0).toFixed(1)}%`;
    const memStr = c.mem_used ? `${(c.mem_used / (1024 * 1024)).toFixed(0)} MB` : '--';
    telemHtml = `<span class="docker-telemetry-pill"><span class="telem-cpu">${cpuStr}</span><span style="opacity:0.4;">•</span><span class="telem-mem">${memStr}</span></span>`;
  }

  // Ports & Web UI
  let portsHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
  const portParts = [];
  if (c.webui_url && c.primary_port) {
    const resolvedUrl = c.webui_url.replace('[HOST]', currentHost);
    portParts.push(
      `<a href="${escapeHtml(resolvedUrl)}" target="_blank" rel="noopener noreferrer" class="btn-webui-badge" title="Open Web UI (Port ${c.primary_port})">🌐 :${c.primary_port} ↗</a>`
    );
  }
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

  // Status & Uptime
  const statusHtml = `
    <div style="display:flex; align-items:center; gap:6px;">
      <span class="docker-state-badge" style="display:inline-block; padding:2px 6px; border-radius:4px; font-size:9.5px; font-weight:700; background:${badgeBg}; color:${badgeColor}; text-transform:uppercase;">${escapeHtml(c.state)}</span>
      <span class="docker-status-text" style="font-size:10px; color:#cbd5e1; max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
    </div>
  `;

  // Actions
  const updateInfo = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
  const hasUpdate = Boolean(updateInfo?.has_update);
  const updateBadge = hasUpdate
    ? `<button class="ci-badge badge-update-ready btn-container-act btn-docker-update-badge" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="update-single" title="Click to update ${escapeHtml(c.name)} to latest image">⬆️ UPDATE</button>`
    : '';

  const inspectBtn = `<button class="btn-container-act btn-docker-inspect" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="inspect" title="Inspect ${escapeHtml(c.name)}">🔍</button>`;
  const editBtn = `<button class="btn-container-act btn-docker-edit" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="edit" title="Edit ${escapeHtml(c.name)}">✏️</button>`;
  const stackBtn = c.stack
    ? `<button class="btn-container-act btn-docker-stack" data-action="stack" data-stack="${escapeHtml(c.stack)}" title="Open & Edit Stack: ${escapeHtml(c.stack)}">📁</button>`
    : '';
  const updateBtn = hasUpdate
    ? `<button class="btn-container-act btn-docker-update-single" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="update-single" title="Update ${escapeHtml(c.name)} to latest image">⬆️</button>`
    : '';
  const backupBtn = `<button class="btn-container-act btn-docker-backup" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="backup" title="Backup App Data & Config">💾</button>`;
  const deleteBtn = `<button class="btn-container-act btn-docker-delete" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-image="${escapeHtml(c.image || '')}" data-action="delete" title="Destroy / Delete ${escapeHtml(c.name)}">🗑️</button>`;
  const moreBtn = `<button class="btn-container-act btn-docker-more-sheet" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="more-sheet" title="More Actions">···</button>`;
  const actions = isRunning
    ? `
      ${inspectBtn}
      ${editBtn}
      ${stackBtn}
      ${updateBtn}
      ${backupBtn}
      <button class="btn-container-act btn-docker-restart" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="restart" title="Restart ${escapeHtml(c.name)}">🔄</button>
      <button class="btn-container-act btn-docker-stop" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="stop" title="Stop ${escapeHtml(c.name)}">⏹</button>
      ${deleteBtn}
      ${moreBtn}
    `
    : `
      ${inspectBtn}
      ${editBtn}
      ${stackBtn}
      ${updateBtn}
      ${backupBtn}
      <button class="btn-container-act btn-docker-start" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="start" title="Start ${escapeHtml(c.name)}">▶</button>
      ${deleteBtn}
      ${moreBtn}
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

function createCwContainerRow(c, currentHost) {
  const tr = document.createElement('tr');
  const key = c.id || c.name || '';
  tr.dataset.key = key;
  tr.dataset.id = c.id || '';
  tr.dataset.name = c.name || '';
  tr.dataset.state = c.state || '';
  const updateInfo = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
  tr.dataset.hasUpdate = updateInfo?.has_update ? '1' : '0';
  tr.innerHTML = buildCwContainerRowInner(c, currentHost);
  return tr;
}

function updateCwContainerRow(tr, c, currentHost) {
  const updateInfo = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
  const hasUpdate = Boolean(updateInfo?.has_update);
  const prevHasUpdate = tr.dataset.hasUpdate === '1';

  tr.dataset.id = c.id || '';
  tr.dataset.name = c.name || '';

  if (tr.dataset.state !== c.state || prevHasUpdate !== hasUpdate || !tr.children.length) {
    tr.dataset.state = c.state || '';
    tr.dataset.hasUpdate = hasUpdate ? '1' : '0';
    tr.innerHTML = buildCwContainerRowInner(c, currentHost);
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

function bindCwTableEvents(tbody) {
  if (tbody._cwTableEventsBound) return;
  tbody._cwTableEventsBound = true;

  tbody.addEventListener('click', async (e) => {
    const stackPill = e.target.closest('.clickable-stack-pill, .open-stack-btn');
    if (stackPill) {
      e.stopPropagation();
      const stackName = stackPill.dataset.stack;
      if (stackName) {
        openStackModal(stackName);
        return;
      }
    }

    const actBtn = e.target.closest('.btn-container-act');
    if (actBtn) {
      e.stopPropagation();
      const cid = actBtn.dataset.id;
      const cname = actBtn.dataset.name;
      const act = actBtn.dataset.action;

      if (act === 'stack') {
        const stackName = actBtn.dataset.stack;
        if (stackName) openStackModal(stackName);
        return;
      }

      if (!cid || !act) return;

      if (act === 'more-sheet') {
        const c = _cwContainersList.find((item) => (item.id === cid || item.name === cname));
        if (!c) return;
        const updateInfo = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
        const hasUpdate = Boolean(updateInfo?.has_update);

        const items = [
          {
            icon: '🔍',
            label: t('docker.inspect', 'Inspect & Overview'),
            onClick: () => openContainerInspector(cid, cname, 'overview'),
          },
          {
            icon: '📋',
            label: t('docker.logs', 'View Container Logs'),
            onClick: () => openContainerInspector(cid, cname, 'logs'),
          },
          {
            icon: '📟',
            label: t('docker.terminal', 'Web Terminal Console'),
            onClick: () => openContainerInspector(cid, cname, 'terminal'),
          },
          {
            icon: '✏️',
            label: t('docker.edit', 'Edit Configuration'),
            onClick: () => openContainerInspector(cid, cname, 'edit'),
          },
        ];

        if (c.stack) {
          items.push({
            icon: '📁',
            label: `Manage Stack: ${c.stack}`,
            onClick: () => openStackModal(c.stack),
          });
        }

        if (hasUpdate) {
          items.push({
            icon: '⬆️',
            label: 'Update to Latest Image',
            onClick: () => {
              actBtn.parentElement.querySelector('[data-action="update-single"]')?.click();
            },
          });
        }

        items.push({
          icon: '💾',
          label: 'Backup App Data & Config',
          onClick: () => {
            actBtn.parentElement.querySelector('[data-action="backup"]')?.click();
          },
        });

        items.push({
          icon: '🗑️',
          label: `Delete "${cname}"`,
          destructive: true,
          onClick: () => openContainerDeleteModal(cid, cname, c.image),
        });

        showBottomSheet({
          title: cname,
          subtitle: `State: ${(c.state || '').toUpperCase()} • ${c.image || 'Docker Container'}`,
          items,
        });
        return;
      }

      if (act === 'inspect') {
        openContainerInspector(cid, cname);
        return;
      }

      if (act === 'edit') {
        openContainerInspector(cid, cname, 'edit');
        return;
      }

      if (act === 'update-single') {
        showConfirmToast(
          `Update Container "${cname}"`,
          `Pull the latest image and update <strong>${escapeHtml(cname)}</strong> to its newest release?<br><br><span style="font-size:11.5px; color:var(--muted);">All volumes, persistent paths, and environment settings will be preserved intact.</span>`,
          async () => {
            actBtn.disabled = true;
            const originalContent = actBtn.innerHTML;
            actBtn.innerHTML = '⏳';
            showToast(`Updating "${cname}" to latest image...`, 'info');
            try {
              await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/update-image`);
              showToast(`Container "${cname}" updated and restarted successfully!`, 'success');
              await loadContainersData();
            } catch (err) {
              showToast(`Update failed: ${err.message}`, 'error');
              actBtn.disabled = false;
              actBtn.innerHTML = originalContent;
            }
          },
          null,
          {
            okText: '⬆️ Update Now',
            cancelText: 'Cancel',
            isUpdate: true,
          }
        );
        return;
      }

      if (act === 'backup') {
        actBtn.disabled = true;
        const originalContent = actBtn.innerHTML;
        actBtn.innerHTML = '⏳';
        showToast(`Creating backup for ${cname}...`, 'info');
        try {
          const res = await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/backup`);
          const archiveName = res?.backup?.archive_file || 'archive.tar.gz';
          const sizeStr = res?.backup?.archive_size_formatted || '';
          showToast(`App "${cname}" backed up successfully (${archiveName}${sizeStr ? ' - ' + sizeStr : ''})!`, 'success');
        } catch (err) {
          showToast(`Backup failed: ${err.message}`, 'error');
        } finally {
          actBtn.disabled = false;
          actBtn.innerHTML = originalContent;
        }
        return;
      }

      if (act === 'delete') {
        openContainerDeleteModal(cid, cname, actBtn.dataset.image || '', () => {
          loadContainersData();
        });
        return;
      }

      actBtn.disabled = true;
      actBtn.style.opacity = '0.5';
      showToast(`${act.toUpperCase()} request sent for ${cname}...`, 'info');

      try {
        await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: act });
        showToast(`Container "${cname}" successfully ${act}ed.`, 'success');
        await loadContainersData();
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
