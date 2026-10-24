/**
 * Mission Control: Docker containers table, app catalog, deploy, prune, sources and sideload.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { catalogCardHtml, catalogChipsHtml, filterCatalog, isInstalled, bindCatalogChips } from '../catalog-view.js';
import { openContainerInspector, openContainerDeleteModal } from '../container-modal.js';
import { openStackModal, openStackPickerModal } from '../stack-modal.js';
import { ZettEventBus } from '../../event-bus.js';
import { clearSelectedContainers, createContainerRow, getSelectedContainerIds, initSynchronizedTableScrollbars, isContainerSelected, runBulkContainerAction, selectAllContainers, toggleContainerSelected, updateContainerRow } from '../docker-table.js';
import { bringToFront, DockManager, makeDraggable, showDockToast } from '../dock.js';
import { api } from '../../api.js';
import { showToast, showConfirmToast, showBottomSheet } from '../../toast.js';
import { escapeHtml, copyTextToClipboard, reconcileKeyedTable, copyText } from '../../utils.js';
import { t } from '../../i18n.js';
import { formatBytes as formatSize } from '../../format.js';
import { setDeployButtonTone } from '../management.js';

let _dockerContainersList = [];
let _dockerFilter = 'all';
let _dockerSearchQuery = '';
let _dockerUpdatesCache = null;

let _dockerSortCol = null;
let _dockerSortDir = 'asc';
try {
  const savedCol = localStorage.getItem('zettnas_docker_sort_col');
  const savedDir = localStorage.getItem('zettnas_docker_sort_dir');
  if (savedCol && ['name', 'hardware', 'cpu', 'ports', 'status'].includes(savedCol)) {
    _dockerSortCol = savedCol;
  }
  if (savedDir && ['asc', 'desc'].includes(savedDir)) {
    _dockerSortDir = savedDir;
  }
} catch (e) {}

let _catalogList = [];
let _catalogCat = 'all';
let _catalogSearchQuery = '';
let _catalogSources = [];

export function setDockerSort(col, dir) {
  _dockerSortCol = col;
  if (dir) _dockerSortDir = dir;
  try {
    if (col) {
      localStorage.setItem('zettnas_docker_sort_col', _dockerSortCol);
      localStorage.setItem('zettnas_docker_sort_dir', _dockerSortDir);
    } else {
      localStorage.removeItem('zettnas_docker_sort_col');
      localStorage.removeItem('zettnas_docker_sort_dir');
    }
  } catch (e) {}
  renderDockerContainersTable();
}

export function getDockerSort() {
  return { col: _dockerSortCol, dir: _dockerSortDir };
}

export function getContainerPortSortValue(c) {
  if (!c) return 0;
  if (c.primary_port && Number(c.primary_port) > 0) {
    return Number(c.primary_port);
  }
  if (Array.isArray(c.ports) && c.ports.length > 0) {
    const pubPorts = c.ports
      .map((p) => Number(p.public_port))
      .filter((p) => !isNaN(p) && p > 0);
    if (pubPorts.length > 0) return Math.min(...pubPorts);
  }
  return 0;
}

export function getContainerStatusRank(c) {
  if (!c) return 0;
  const state = (c.state || '').toLowerCase();
  if (state === 'running') return 3;
  if (state === 'restarting') return 2;
  if (state === 'paused') return 1;
  return 0;
}

export function sortDockerContainers(list, col = 'name', dir = 'asc') {
  if (!Array.isArray(list) || list.length <= 1 || !col) return list;

  list.sort((a, b) => {
    switch (col) {
      case 'hardware': {
        const hwA = (a.hardware_badges || []).map((x) => x.label || x.id || '').filter(Boolean).join(' ');
        const hwB = (b.hardware_badges || []).map((x) => x.label || x.id || '').filter(Boolean).join(' ');
        if (hwA && !hwB) return dir === 'desc' ? -1 : 1;
        if (!hwA && hwB) return dir === 'desc' ? 1 : -1;
        if (hwA !== hwB) {
          const cmp = hwA.localeCompare(hwB);
          return dir === 'desc' ? -cmp : cmp;
        }
        return (a.name || '').localeCompare(b.name || '');
      }

      case 'cpu': {
        const cpuA = Number(a.cpu_pct) || 0;
        const cpuB = Number(b.cpu_pct) || 0;
        if (cpuA !== cpuB) {
          return dir === 'desc' ? cpuB - cpuA : cpuA - cpuB;
        }
        const memA = Number(a.mem_used) || 0;
        const memB = Number(b.mem_used) || 0;
        if (memA !== memB) {
          return dir === 'desc' ? memB - memA : memA - memB;
        }
        return (a.name || '').localeCompare(b.name || '');
      }

      case 'ports': {
        const portA = getContainerPortSortValue(a);
        const portB = getContainerPortSortValue(b);
        if (portA > 0 && portB === 0) return -1;
        if (portA === 0 && portB > 0) return 1;
        if (portA !== portB) {
          return dir === 'desc' ? portB - portA : portA - portB;
        }
        return (a.name || '').localeCompare(b.name || '');
      }

      case 'status': {
        const rankA = getContainerStatusRank(a);
        const rankB = getContainerStatusRank(b);
        if (rankA !== rankB) {
          return dir === 'desc' ? rankA - rankB : rankB - rankA;
        }
        const statusCmp = (a.status || '').localeCompare(b.status || '');
        if (statusCmp !== 0) {
          return dir === 'desc' ? -statusCmp : statusCmp;
        }
        return (a.name || '').localeCompare(b.name || '');
      }

      case 'stack': {
        const stackA = (a.stack || (a.managed_by === 'unraid' ? 'Unraid' : 'Standalone')).toLowerCase();
        const stackB = (b.stack || (b.managed_by === 'unraid' ? 'Unraid' : 'Standalone')).toLowerCase();
        const cmp = stackA.localeCompare(stackB);
        if (cmp !== 0) return dir === 'desc' ? -cmp : cmp;
        const nameA = (a.name || a.id || '').toLowerCase();
        const nameB = (b.name || b.id || '').toLowerCase();
        return nameA.localeCompare(nameB);
      }

      case 'name':
      default: {
        const nameA = (a.name || a.id || '').toLowerCase();
        const nameB = (b.name || b.id || '').toLowerCase();
        const cmp = nameA.localeCompare(nameB);
        if (cmp !== 0) return dir === 'desc' ? -cmp : cmp;
        const stackA = (a.stack || a.managed_by || '').toLowerCase();
        const stackB = (b.stack || b.managed_by || '').toLowerCase();
        const sCmp = stackA.localeCompare(stackB);
        return dir === 'desc' ? -sCmp : sCmp;
      }
    }
  });

  return list;
}

export function updateDockerTableHeaderUI() {
  const containerPane = document.getElementById('mgmt-pane-docker');
  if (!containerPane) return;
  const sortHeaders = containerPane.querySelectorAll('th.sortable-th');
  sortHeaders.forEach((th) => {
    const col = th.dataset.sortCol;
    const indicator = th.querySelector('.docker-sort-indicator');
    if (col === _dockerSortCol) {
      th.classList.add('active-sort');
      th.setAttribute('aria-sort', _dockerSortDir === 'asc' ? 'ascending' : 'descending');
      if (indicator) {
        indicator.textContent = _dockerSortDir === 'asc' ? '▲' : '▼';
        indicator.title = _dockerSortDir === 'asc' ? 'Sorted Ascending' : 'Sorted Descending';
      }
    } else {
      th.classList.remove('active-sort');
      th.setAttribute('aria-sort', 'none');
      if (indicator) {
        indicator.textContent = '';
        indicator.title = '';
      }
    }
  });
}

export function updateDockerBulkBar() {
  const bar = document.getElementById('docker-bulk-bar');
  const countEl = document.getElementById('docker-bulk-count');
  const selectAll = document.getElementById('docker-select-all');
  const selectedIds = getSelectedContainerIds();
  const count = selectedIds.length;

  if (bar) {
    if (count > 0) {
      bar.style.display = 'flex';
      if (countEl) countEl.textContent = count;
    } else {
      bar.style.display = 'none';
    }
  }

  if (selectAll) {
    const totalVisible = _dockerContainersList.length;
    if (count === 0) {
      selectAll.checked = false;
      selectAll.indeterminate = false;
    } else if (count >= totalVisible && totalVisible > 0) {
      selectAll.checked = true;
      selectAll.indeterminate = false;
    } else {
      selectAll.checked = false;
      selectAll.indeterminate = true;
    }
  }
}

export async function executeBulkContainerAction(action) {
  return runBulkContainerAction(action, {
    rerender: renderDockerContainersTable,
    refresh: () => fetchAndRenderDockerContainers(),
    updateBar: updateDockerBulkBar,
  });
}

export function _resetDockerStateForTesting() {
  stopDockerAutoRefresh();
  clearSelectedContainers();
  const containerPane = document.getElementById('mgmt-pane-docker');
  if (containerPane) containerPane._dockerEventsBound = false;
  _dockerContainersList = [];
  _dockerFilter = 'all';
  _dockerSearchQuery = '';
  _dockerUpdatesCache = null;
  _dockerSortCol = null;
  _dockerSortDir = 'asc';
  try {
    localStorage.removeItem('zettnas_docker_sort_col');
    localStorage.removeItem('zettnas_docker_sort_dir');
  } catch (e) {}
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

  const launchWinBtn = document.getElementById('btn-mgmt-docker-launch-window');
  if (launchWinBtn) {
    launchWinBtn.addEventListener('click', () => {
      if (typeof window.openContainersManager === 'function') {
        window.openContainersManager();
      } else if (typeof window.openContainersWindow === 'function') {
        window.openContainersWindow();
      }
    });
  }

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
    const showContainersView = () => {
      btnContainers.style.display = 'none';
      btnContainers.classList.remove('active');
      btnCatalog.classList.remove('active');
      if (wrapContainers) wrapContainers.style.display = 'block';
      if (wrapCatalog) wrapCatalog.style.display = 'none';
      const tabContainers = document.getElementById('docker-inner-tab-containers');
      const tabCatalog = document.getElementById('docker-inner-tab-catalog');
      if (tabContainers) {
        tabContainers.classList.add('active');
        tabContainers.setAttribute('aria-selected', 'true');
      }
      if (tabCatalog) {
        tabCatalog.classList.remove('active');
        tabCatalog.setAttribute('aria-selected', 'false');
      }
    };

    const showCatalogView = () => {
      btnCatalog.classList.add('active');
      btnContainers.style.display = 'inline-flex';
      btnContainers.textContent = '← Back to Containers';
      btnContainers.classList.remove('active');
      if (wrapContainers) wrapContainers.style.display = 'none';
      if (wrapCatalog) wrapCatalog.style.display = 'block';
      const tabContainers = document.getElementById('docker-inner-tab-containers');
      const tabCatalog = document.getElementById('docker-inner-tab-catalog');
      if (tabCatalog) {
        tabCatalog.classList.add('active');
        tabCatalog.setAttribute('aria-selected', 'true');
      }
      if (tabContainers) {
        tabContainers.classList.remove('active');
        tabContainers.setAttribute('aria-selected', 'false');
      }
      fetchAndRenderAppCatalog();
    };

    btnContainers.addEventListener('click', showContainersView);
    btnCatalog.addEventListener('click', () => {
      if (wrapCatalog && wrapCatalog.style.display === 'block') {
        showContainersView();
      } else {
        showCatalogView();
      }
    });

    const tabContainers = document.getElementById('docker-inner-tab-containers');
    const tabCatalog = document.getElementById('docker-inner-tab-catalog');
    if (tabContainers && !tabContainers.dataset.bound) {
      tabContainers.dataset.bound = '1';
      tabContainers.addEventListener('click', showContainersView);
    }
    if (tabCatalog && !tabCatalog.dataset.bound) {
      tabCatalog.dataset.bound = '1';
      tabCatalog.addEventListener('click', showCatalogView);
    }
  }

  // Catalog category filter pills
  const catFilterParent = document.getElementById('mgmt-pane-docker-catalog') || containerPane;
  const catFilterBtns = catFilterParent ? catFilterParent.querySelectorAll('.catalog-filter-btn') : [];
  catFilterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      catFilterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _catalogCat = btn.dataset.cat || 'all';
      renderAppCatalogGrid();
    });
  });

  const btnRefreshCatalog = document.getElementById('btn-refresh-catalog');
  if (btnRefreshCatalog && !btnRefreshCatalog.dataset.bound) {
    btnRefreshCatalog.dataset.bound = '1';
    btnRefreshCatalog.addEventListener('click', () => {
      fetchAndRenderAppCatalog();
    });
  }

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

  // Sideload button
  const btnSideload = document.getElementById('btn-sideload-app-package');
  if (btnSideload) {
    btnSideload.addEventListener('click', () => {
      openSideloadAppModal();
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
          showToast(t('toast.container_updates_available', 'Update check complete: {count} container update(s) available!', { count }), 'warn');
        } else {
          showToast(t('toast.all_containers_are_up_to_date', 'All containers are up to date!'), 'success');
        }
        await fetchAndRenderDockerContainers(false);
      } catch (err) {
        showToast(t('toast.update_check_failed', 'Update check failed: {error}', { error: err.message }), 'error');
      } finally {
        btnCheckUpdates.disabled = false;
        btnCheckUpdates.innerHTML = originalHtml;
      }
    });
  }

  // Update all button
  const btnUpdateAll = document.getElementById('btn-docker-update-all');
  if (btnUpdateAll) {
    btnUpdateAll.addEventListener('click', () => {
      const count = _dockerUpdatesCache?.updates_available_count || 0;
      showConfirmToast(
        'Update All Containers',
        `Update all <strong>${count} containers</strong> with available image updates?<br><br><span style="font-size:11.5px; color:var(--muted);">Each container will be repulled and recreated with automated rollback protection if startup fails.</span>`,
        async () => {
          btnUpdateAll.disabled = true;
          btnUpdateAll.innerHTML = '<span>⏳</span> <span>Updating all...</span>';
          showToast(t('toast.starting_batch_update_for_containers', 'Starting batch update for {count} containers...', { count: count }), 'info');
          try {
            const res = await api.post('/api/docker/updates/apply-all');
            const updatedCount = res.total_updated || (res.updated || []).length;
            showToast(t('toast.batch_update_complete_updated_failed', 'Batch update complete: {updatedCount} updated, {failed} failed.', { updatedCount: updatedCount, failed: (res.failed || []).length }), updatedCount > 0 ? 'success' : 'warn');
            await refreshDockerUpdatesStatus();
            await fetchAndRenderDockerContainers();
          } catch (err) {
            showToast(t('toast.batch_update_failed', 'Batch update failed: {error}', { error: err.message }), 'error');
          } finally {
            btnUpdateAll.disabled = false;
            updateDockerUpdatesToolbarUI();
          }
        },
        null,
        {
          okText: '⬆️ Update All Now',
          cancelText: 'Cancel',
          isUpdate: true,
          allowHtml: true,
        }
      );
    });
  }

  // Manage Stacks button
  const btnStacksMenu = document.getElementById('btn-docker-stacks-menu');
  if (btnStacksMenu) {
    btnStacksMenu.addEventListener('click', async () => {
      try {
        const stacks = await api.get('/api/docker/stacks');
        if (!stacks || !stacks.length) {
          showToast(t('toast.no_active_compose_stacks_found', 'No active Compose stacks found.'), 'info');
          return;
        }
        openStackPickerModal(stacks);
      } catch (err) {
        showToast(t('toast.failed_loading_stacks', 'Failed loading stacks: {error}', { error: err.message }), 'error');
      }
    });
  }

  // Sortable column headers
  const sortHeaders = containerPane.querySelectorAll('th.sortable-th');
  sortHeaders.forEach((th) => {
    const col = th.dataset.sortCol;
    if (!col) return;

    const handleSort = () => {
      if (_dockerSortCol === col) {
        _dockerSortDir = _dockerSortDir === 'asc' ? 'desc' : 'asc';
      } else {
        _dockerSortCol = col;
        _dockerSortDir = (col === 'cpu' || col === 'hardware') ? 'desc' : 'asc';
      }
      try {
        localStorage.setItem('zettnas_docker_sort_col', _dockerSortCol);
        localStorage.setItem('zettnas_docker_sort_dir', _dockerSortDir);
      } catch (e) {}
      renderDockerContainersTable();
    };

    th.addEventListener('click', (e) => {
      if (e.target.id === 'docker-select-all' || e.target.closest('#docker-select-all')) return;
      handleSort();
    });
    th.addEventListener('keydown', (e) => {
      if (e.target.id === 'docker-select-all' || e.target.closest('#docker-select-all')) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleSort();
      }
    });
  });

  // Select All Containers Checkbox
  const selectAll = document.getElementById('docker-select-all');
  if (selectAll && !selectAll._bound) {
    selectAll._bound = true;
    selectAll.addEventListener('change', (e) => {
      e.stopPropagation();
      const tbody = document.getElementById('docker-containers-tbody');
      if (!tbody) return;
      if (selectAll.checked) {
        const visibleIds = _dockerContainersList.map((c) => c.id).filter(Boolean);
        selectAllContainers(visibleIds);
      } else {
        clearSelectedContainers();
      }
      tbody.querySelectorAll('.docker-row-select').forEach((chk) => {
        const cid = chk.dataset.id;
        const isChecked = isContainerSelected(cid);
        chk.checked = isChecked;
        const tr = chk.closest('tr');
        if (tr) {
          if (isChecked) tr.classList.add('docker-row-selected');
          else tr.classList.remove('docker-row-selected');
        }
      });
      updateDockerBulkBar();
    });
  }

  // Floating Bulk Action Bar Buttons
  const bulkBar = document.getElementById('docker-bulk-bar');
  if (bulkBar && !bulkBar._bound) {
    bulkBar._bound = true;
    bulkBar.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-bulk-action');
      if (!btn) return;
      e.stopPropagation();
      const action = btn.dataset.bulk;
      if (action) {
        executeBulkContainerAction(action);
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

  ZettEventBus.on('stats:updated', (stats) => {
    if (!stats || !Array.isArray(stats.docker)) return;
    const mgmtWin = document.getElementById('management-window');
    if (!mgmtWin) return;
    if (
      mgmtWin.style.display === 'none' ||
      mgmtWin.classList.contains('minimized') ||
      mgmtWin.classList.contains('window-minimized')
    ) {
      return;
    }
    const dockerSec = document.getElementById('mgmt-sec-docker');
    if (!dockerSec || dockerSec.style.display === 'none') return;
    _dockerContainersList = stats.docker;
    renderDockerContainersTable();
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
  const filterUpd = document.getElementById('btn-docker-filter-updates');
  const cUpd = document.getElementById('docker-count-updates');
  if (badge) badge.textContent = count;
  if (cUpd) cUpd.textContent = count;
  if (filterUpd) {
    filterUpd.style.display = count > 0 ? 'inline-flex' : 'none';
  }
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
  const updatesCount = _dockerContainersList.filter((c) => {
    const info = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
    return Boolean(info?.has_update);
  }).length;

  const cAll = document.getElementById('docker-count-all');
  if (cAll) cAll.textContent = totalCount;
  const cRun = document.getElementById('docker-count-running');
  if (cRun) cRun.textContent = runningCount;
  const cStop = document.getElementById('docker-count-stopped');
  if (cStop) cStop.textContent = stoppedCount;
  const cUpd = document.getElementById('docker-count-updates');
  if (cUpd) cUpd.textContent = updatesCount;
  const filterUpd = document.getElementById('btn-docker-filter-updates');
  if (filterUpd) filterUpd.style.display = updatesCount > 0 ? 'inline-flex' : 'none';
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
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:36px 20px;">
      <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px;">
        <div style="font-size:32px; opacity:0.8;">🐳</div>
        <div style="font-size:13.5px; font-weight:600; color:var(--text, #fff);">${t('mgmt.docker_none_title', 'No Docker Containers Deployed')}</div>
        <div style="font-size:12px; color:var(--muted, #94a3b8); max-width:420px; line-height:1.5;">${t('mgmt.docker_none', 'No Docker containers detected or socket not connected.')}</div>
        <button id="btn-empty-deploy-app" class="btn-pill-toggle is-primary" style="margin-top: 6px;">
          🚀 ${t('mgmt.docker_open_catalog', 'Browse App Catalog')}
        </button>
      </div>
    </td></tr>`;
    const btnEmptyCatalog = tbody.querySelector('#btn-empty-deploy-app');
    if (btnEmptyCatalog) {
      btnEmptyCatalog.addEventListener('click', () => {
        const catBtn = document.getElementById('btn-view-docker-catalog') || document.getElementById('docker-inner-tab-catalog');
        if (catBtn) catBtn.click();
      });
    }
    updateDockerBulkBar();
    return;
  }

  // Filter list
  const filtered = _dockerContainersList.filter((c) => {
    // Check tab filter
    if (_dockerFilter === 'running' && c.state !== 'running') return false;
    if (_dockerFilter === 'stopped' && c.state === 'running') return false;
    if (_dockerFilter === 'updates') {
      const updateInfo = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
      if (!updateInfo?.has_update) return false;
    }
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

  // Sort list if sort column active
  if (_dockerSortCol) {
    sortDockerContainers(filtered, _dockerSortCol, _dockerSortDir);
  }
  updateDockerTableHeaderUI();

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:20px;">${t('mgmt.docker_no_matching', 'No containers match your search or filter.')}</td></tr>`;
    const stickyScroll = document.getElementById('docker-table-sticky-scroll');
    if (stickyScroll) stickyScroll.style.display = 'none';
    updateDockerBulkBar();
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
    (c) => createContainerRow(c, currentHost, _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id]),
    (tr, c) => updateContainerRow(tr, c, currentHost, _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id])
  );
  updateDockerBulkBar();

  const tableWrap = document.querySelector('.docker-table-container');
  const stickyScroll = document.getElementById('docker-table-sticky-scroll');
  if (tableWrap) {
    // One horizontal scrollbar, kept at the bottom edge of the window
    initSynchronizedTableScrollbars(tableWrap, null, stickyScroll);
  }
}

function bindDockerTableEvents(tbody) {
  if (tbody._dockerTableEventsBound) return;
  tbody._dockerTableEventsBound = true;

  tbody.addEventListener('change', (e) => {
    if (e.target.classList.contains('docker-row-select')) {
      const cid = e.target.dataset.id;
      toggleContainerSelected(cid, e.target.checked);
      const tr = e.target.closest('tr');
      if (tr) {
        if (e.target.checked) tr.classList.add('docker-row-selected');
        else tr.classList.remove('docker-row-selected');
      }
      updateDockerBulkBar();
    }
  });

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
        const c = _dockerContainersList.find((item) => (item.id === cid || item.name === cname));
        if (!c) return;
        const updateInfo = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
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
          onClick: () => {
            openContainerDeleteModal(cid, cname, c.image || '', () => {
              fetchAndRenderDockerContainers();
            });
          },
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
            showToast(t('toast.updating_to_latest_image', 'Updating "{cname}" to latest image...', { cname: cname }), 'info');
            try {
              await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/update-image`);
              showToast(t('toast.container_updated_and_restarted_successfully', 'Container "{cname}" updated and restarted successfully!', { cname: cname }), 'success');
              await refreshDockerUpdatesStatus();
              await fetchAndRenderDockerContainers();
            } catch (err) {
              showToast(t('toast.update_failed', 'Update failed: {error}', { error: err.message }), 'error');
              actBtn.disabled = false;
              actBtn.innerHTML = originalContent;
            }
          },
          null,
          {
            okText: '⬆️ Update Now',
            cancelText: 'Cancel',
            isUpdate: true,
            allowHtml: true,
          }
        );
        return;
      }

      if (act === 'backup') {
        actBtn.disabled = true;
        const originalContent = actBtn.innerHTML;
        actBtn.innerHTML = '⏳';
        showToast(t('toast.creating_backup_for_2', 'Creating backup for {cname}...', { cname: cname }), 'info');
        try {
          const res = await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/backup`);
          const archiveName = res?.backup?.archive_file || 'archive.tar.gz';
          const sizeStr = res?.backup?.archive_size_formatted || '';
          showToast(t('toast.app_backed_up', 'App "{name}" backed up ({archive}).', { name: cname, archive: sizeStr ? `${archiveName}, ${sizeStr}` : archiveName }), 'success');
        } catch (err) {
          showToast(t('toast.backup_failed', 'Backup failed: {error}', { error: err.message }), 'error');
        } finally {
          actBtn.disabled = false;
          actBtn.innerHTML = originalContent;
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
      showToast(t('toast.request_sent_for', '{act} request sent for {cname}...', { act: act.toUpperCase(), cname: cname }), 'info');

      try {
        await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: act });
        showToast(t('toast.container_successfully_ed', 'Container "{cname}" successfully {act}ed.', { cname: cname, act: act }), 'success');
        await fetchAndRenderDockerContainers();
      } catch (err) {
        showToast(t('toast.failed_to_container', 'Failed to {act} container: {error}', { act: act, error: err.message }), 'error');
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

let _dockerAutoRefreshTimer = null;
let _isDockerAutoRefreshing = false;
let _dockerAutoRefreshCount = 0;

let _dockerLastSseAt = 0;
let _dockerSseBound = false;
const DOCKER_WATCHDOG_MS = 15000;
const DOCKER_SSE_STALE_MS = 10000;

function _dockerSectionVisible() {
  if (typeof document === 'undefined' || document.hidden) return false;
  const mgmtWin = document.getElementById('management-window');
  if (mgmtWin && (mgmtWin.style.display === 'none' || mgmtWin.classList.contains('minimized') || mgmtWin.classList.contains('window-minimized'))) {
    return false;
  }
  const dockerSec = document.getElementById('mgmt-sec-docker');
  if (!dockerSec || dockerSec.style.display === 'none') return false;
  const style = typeof window !== 'undefined' && window.getComputedStyle ? window.getComputedStyle(dockerSec) : null;
  return !(style && style.display === 'none');
}

// Mission Control's container table follows the live stats stream, like the Containers
// window; the timer only fetches when the stream has gone quiet (FE-12).
export function startDockerAutoRefresh() {
  if (!_dockerSseBound) {
    _dockerSseBound = true;
    ZettEventBus.on('stats:updated', (stats) => {
      if (!stats || !Array.isArray(stats.docker)) return;
      _dockerLastSseAt = Date.now();
      if (!_dockerAutoRefreshTimer || !_dockerSectionVisible()) return;
      _dockerContainersList = stats.docker;
      renderDockerContainersTable();
    });
  }
  if (_dockerAutoRefreshTimer) return;
  _dockerAutoRefreshTimer = setInterval(async () => {
    if (!_dockerSectionVisible()) return;
    if (_isDockerAutoRefreshing) return;
    _isDockerAutoRefreshing = true;
    try {
      _dockerAutoRefreshCount++;
      if (_dockerAutoRefreshCount % 4 === 0) {
        refreshDockerUpdatesStatus().catch(() => {});
      }
      if (Date.now() - _dockerLastSseAt > DOCKER_SSE_STALE_MS) {
        await fetchAndRenderDockerContainers(true);
      }
    } catch (e) {
      console.warn('Docker background auto-refresh poll error:', e);
    } finally {
      _isDockerAutoRefreshing = false;
    }
  }, DOCKER_WATCHDOG_MS);
}

export function stopDockerAutoRefresh() {
  if (_dockerAutoRefreshTimer) {
    clearInterval(_dockerAutoRefreshTimer);
    _dockerAutoRefreshTimer = null;
  }
}

export async function fetchAndRenderDockerContainers(isBackground = false) {
  _bindDockerEvents();
  const tbody = document.getElementById('docker-containers-tbody');
  const cwTbody = document.getElementById('cw-docker-containers-tbody');
  if (!tbody && !cwTbody) return;
  try {
    const [list] = await Promise.all([
      api.get('/api/docker/containers'),
      (!isBackground || !_dockerUpdatesCache) ? refreshDockerUpdatesStatus().catch(() => {}) : Promise.resolve(),
    ]);
    _dockerContainersList = Array.isArray(list) ? list : [];
    if (tbody) renderDockerContainersTable();
    if (typeof window.renderContainersWindowTable === 'function') {
      window.renderContainersWindowTable(_dockerContainersList);
    }
  } catch (err) {
    if (!isBackground || _dockerContainersList.length === 0) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
      if (cwTbody) cwTbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
    } else {
      console.warn('Silent docker refresh error:', err);
    }
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

function _setCatalogCountBadges(n) {
  for (const id of ['catalog-total-badge', 'catalog-total-badge-tab', 'catalog-all-count']) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(n);
  }
}

let _catalogCountFetchedAt = 0;
/** Shows the real number of catalog apps on the Containers view before the catalog is opened. */
export async function refreshCatalogCountBadges() {
  if (Date.now() - _catalogCountFetchedAt < 5 * 60 * 1000) return;
  _catalogCountFetchedAt = Date.now();
  try {
    const list = await api.get('/api/docker/catalog');
    if (Array.isArray(list)) _setCatalogCountBadges(list.length);
  } catch (err) {
    _catalogCountFetchedAt = 0;
    console.warn('[Docker] Could not load the app catalog count:', err);
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

    _setCatalogCountBadges(_catalogList.length);
    updateCatalogSourcesBadge();
    renderCatalogChips();

    renderAppCatalogGrid();
  } catch (err) {
    grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; color:var(--crit); padding:20px;">Failed to load catalog: ${escapeHtml(err.message)}</div>`;
  }
}

/** Category chips with counts, built from the templates the server sent. */
function renderCatalogChips() {
  const pills = document.querySelector('#docker-view-catalog-wrap .catalog-filter-pills');
  if (!pills) return;
  if (_catalogCat !== 'all' && !_catalogList.some((a) => (a.category || 'other') === _catalogCat)) _catalogCat = 'all';
  pills.innerHTML = catalogChipsHtml(_catalogList, _catalogCat, 'catalog-filter-btn', 'catalog-all-count');
  bindCatalogChips(pills, '.catalog-filter-btn', (cat) => {
    _catalogCat = cat;
    renderAppCatalogGrid();
  });
}

/** Opens the catalog with a search already typed, e.g. "reverse proxy" from the HTTPS guide. */
export function presetCatalogSearch(query, tries = 30) {
  _catalogSearchQuery = String(query || '').toLowerCase();
  _catalogCat = 'all';
  const input = document.getElementById('catalog-search-input');
  if (input) input.value = query || '';
  // Mission Control builds its panes on first open: switch to the catalog tab once it is wired
  const tab = document.getElementById('docker-inner-tab-catalog');
  if (tab && tab.dataset.bound === '1') {
    tab.click(); // shows the catalog and loads it with the search above
    renderCatalogChips();
    renderAppCatalogGrid();
  } else if (tries > 0) {
    setTimeout(() => presetCatalogSearch(query, tries - 1), 100);
  }
}

export function renderAppCatalogGrid() {
  const grid = document.getElementById('docker-catalog-grid');
  if (!grid) return;

  const filtered = filterCatalog(_catalogList, _catalogCat, _catalogSearchQuery);
  if (filtered.length === 0) {
    grid.innerHTML = '<div class="cat-empty">No applications match your search.</div>';
    return;
  }
  grid.innerHTML = filtered.map((app) => catalogCardHtml(app, { installed: isInstalled(app, _dockerContainersList) })).join('');

  grid.querySelectorAll('.btn-deploy-app').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      openAppDeployModal(btn.dataset.appid);
    });
  });
}

/** After a deploy: the login to use (generated passwords included), or where to connect. */
function showDeployCredentials(successBox, data, hostPort) {
  if (!successBox || !successBox.parentElement) return;
  successBox.parentElement.querySelector('.adm-credentials')?.remove();
  const c = data.credentials || {};
  const rows = [];
  if (data.has_webui === false) rows.push([t('catalog.connect_to', 'Connect to'), hostPort]);
  if (c.user) rows.push([t('catalog.cred_user', 'User'), c.user]);
  if (c.password) rows.push([t('catalog.cred_password', 'Password'), c.password]);
  if (!rows.length && !c.note) return;
  const box = document.createElement('div');
  box.className = 'adm-credentials';
  box.innerHTML = `<div class="adm-cred-title">🔑 ${escapeHtml(t('catalog.cred_title', 'Sign-in details'))}</div>` +
    rows.map(([label, value], i) => `<div class="adm-cred-row"><span class="adm-cred-label">${escapeHtml(label)}</span><code class="adm-cred-val">${escapeHtml(value)}</code><button type="button" class="adm-cred-copy" data-i="${i}" aria-label="${escapeHtml(t('catalog.copy', 'Copy'))} ${escapeHtml(label)}">${escapeHtml(t('catalog.copy', 'Copy'))}</button></div>`).join('') +
    (c.note ? `<div class="adm-cred-note">${escapeHtml(c.note)}</div>` : '') +
    (c.password && /[A-Za-z0-9_-]{20,}/.test(c.password) ? `<div class="adm-cred-note">${escapeHtml(t('catalog.cred_saved', 'Saved in the app folder as .zettnas-secrets.json.'))}</div>` : '');
  box.addEventListener('click', async (e) => {
    const btn = e.target instanceof Element ? e.target.closest('.adm-cred-copy') : null;
    if (!btn) return;
    try {
      await copyText(rows[Number(btn.dataset.i)][1]);
      showToast(t('common.copied', 'Copied to clipboard!'), 'success');
    } catch (_) {
      showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error');
    }
  });
  successBox.insertAdjacentElement('afterend', box);
}

export async function openAppDeployModal(appId) {
  let modal = document.getElementById('app-deploy-modal-overlay');
  if (!modal) {
    const modalHtml = `
      <div id="app-deploy-modal-overlay" class="smart-modal-backdrop" style="display:none;">
        <div id="app-deploy-modal-window" class="smart-modal-window app-deploy-window" style="width:620px; max-width:94vw; max-height:88vh; display:flex; flex-direction:column; position:relative;">
          <div class="smart-modal-header" id="adm-header" style="cursor:move; user-select:none; display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span id="adm-icon" style="font-size:18px;">📦</span>
              <span id="adm-title" style="font-weight:700; color:#fff; font-size:13px;">Deploy Application Stack</span>
            </div>
            <div class="os-window-controls" style="display:flex; gap:6px; align-items:center;">
              <button class="win-btn min-btn" id="adm-min-btn" title="Minimize to Dock" aria-label="Minimize"></button>
              <button class="win-btn close-btn" id="adm-close-btn" title="Close" aria-label="Close"></button>
            </div>
          </div>

          <!-- View 1: Configuration View -->
          <div id="adm-view-config" style="flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:12px;">
            <div id="adm-conflict-banner" style="padding:10px 12px; border-radius:6px; font-size:11px; line-height:1.4;"></div>
            
            <!-- Pre-existing Container Action Choice Box -->
            <div id="adm-existing-box" style="display:none; padding:11px 13px; border-radius:6px; background:rgba(245, 166, 35, 0.09); border:1px solid rgba(245, 166, 35, 0.35); flex-direction:column; gap:8px;">
              <div style="display:flex; align-items:center; justify-content:space-between;">
                <div style="display:flex; align-items:center; gap:6px; color:var(--warn, #f5a623); font-weight:700; font-size:11.5px;">
                  <span>⚠️</span> <span id="adm-existing-title">Pre-existing Container Detected</span>
                </div>
                <span id="adm-existing-status-badge" style="font-size:11px; padding:2px 7px; border-radius:4px; background:rgba(255,255,255,0.08); font-family:var(--font-mono, monospace); font-weight:700;">Running</span>
              </div>
              <div id="adm-existing-desc" style="color:#cbd5e1; font-size:11px; line-height:1.4;">
                A container with this name or port already exists on your system. Choose an action:
              </div>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:4px;">
                <button type="button" id="adm-choice-replace-btn" class="btn-pill-toggle is-danger" style="text-align: center; color: #ff8080;">
                  🔄 Stop &amp; Replace Existing
                </button>
                <button type="button" id="adm-choice-new-btn" class="btn-pill-toggle" style="text-align: center; border: 2px solid var(--ok2, #25c2a0); background: rgba(37, 194, 160, 0.18); color: var(--ok2, #25c2a0);">
                  ➕ Deploy Alongside (New)
                </button>
              </div>
            </div>

            <div style="display:grid; grid-template-columns:1.2fr 1fr; gap:10px;">
              <div>
                <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">CONTAINER NAME</label>
                <input type="text" id="adm-name-input" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px; font-family:var(--font-mono, monospace);">
              </div>
              <div>
                <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">HOST PORT MAPPING</label>
                <input type="number" id="adm-port-input" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px; font-family:var(--font-mono, monospace);">
              </div>
            </div>
            <div>
              <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">STORAGE ROOT DIRECTORY</label>
              <input type="text" id="adm-storage-input" value="/mnt/user/appdata" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px;">
            </div>
            <div>
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:11px; font-weight:700; color:var(--muted);">DOCKER COMPOSE DEFINITION</span>
                <div style="display:flex; gap:6px;">
                  <button class="btn-pill-toggle" id="adm-copy-btn">📋 Copy YAML</button>
                  <button class="btn-pill-toggle" id="adm-download-btn">⬇️ Download</button>
                </div>
              </div>
              <pre id="adm-compose-pre" style="margin:0; background:#080c14; border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:10px; max-height:200px; overflow:auto; font-family:var(--font-mono, monospace); font-size:11px; color:#e2e8f0; line-height:1.45;"></pre>
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
              <div style="font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px; text-transform:uppercase; letter-spacing:0.5px;">Deployment Console Log</div>
              <div id="adm-deploy-logs" style="background:#05080f; border:1px solid rgba(255,255,255,0.1); border-radius:6px; height:160px; overflow-y:auto; padding:10px; font-family:var(--font-mono, monospace); font-size:11px; line-height:1.5; color:#cbd5e1;">
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
            <button class="btn-pill-toggle is-primary" id="adm-deploy-confirm-btn">
              🚀 Deploy & Launch Container
            </button>
          </div>

          <!-- Footer for Progress View -->
          <div id="adm-footer-progress" style="display:none; padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="adm-back-to-config-btn" style="display: none;">← Reconfigure</button>
            <div style="flex:1;"></div>
            <button class="btn-pill-toggle is-primary" id="adm-progress-close-btn" style="display: none;">✓ Done</button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    modal = document.getElementById('app-deploy-modal-overlay');

    const win = document.getElementById('app-deploy-modal-window');
    const header = document.getElementById('adm-header');
    if (win && header) {
      makeDraggable(win, header, 'app-deploy');
    }
    if (win) {
      win.addEventListener('pointerdown', () => {
        bringToFront(win);
      }, { capture: true });
    }

    const minBtn = document.getElementById('adm-min-btn');
    if (minBtn) {
      minBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (DockManager) {
          DockManager.minimize('app-deploy');
        } else {
          modal.classList.add('window-minimized');
          modal.style.display = 'none';
        }
      });
    }

    document.getElementById('adm-close-btn').addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (modal._isDeploying) {
        if (DockManager) {
          DockManager.minimize('app-deploy');
        } else {
          modal.classList.add('window-minimized');
          modal.style.display = 'none';
        }
        showToast(t('toast.deploying_in_background_click_dock_icon', 'Deploying {activeAppId} in background. Click Dock icon to restore.', { activeAppId: modal._activeAppId || 'app' }), 'info');
      } else {
        if (modal._close) modal._close();
      }
    });

    document.getElementById('adm-cancel-btn').addEventListener('click', (e) => {
      e.preventDefault();
      if (modal._close) modal._close();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open') && !modal.classList.contains('window-minimized')) {
        if (modal._isDeploying) {
          if (DockManager) DockManager.minimize('app-deploy');
          else modal.classList.add('window-minimized');
          showToast(t('toast.deploying_in_background_reopen_from_dock', `Deploying in background. Reopen from Dock anytime.`), 'info');
        } else if (modal._close) {
          modal._close();
        }
      }
    });
  }

  modal._close = () => {
    modal._isDeploying = false;
    modal.classList.remove('open', 'window-minimized');
    modal.style.display = 'none';
    if (DockManager) {
      DockManager.unregister('app-deploy');
    }
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
  modal._activeAppId = appId;
  modal._isDeploying = false;
  modal.classList.remove('window-minimized');
  modal.classList.add('open');
  modal.style.display = 'flex';

  const win = document.getElementById('app-deploy-modal-window');
  if (win) {
    win.classList.remove('window-minimized');
    win.style.removeProperty('display');
    bringToFront(win);
  }

  // Register in DockManager
  if (DockManager) {
    if (!DockManager.windows['app-deploy']) {
      DockManager.register('app-deploy', modal, '#i-chip', `Deploy: ${appId.toUpperCase()}`, false);
    } else {
      DockManager.windows['app-deploy'].title = `Deploy: ${appId.toUpperCase()}`;
      DockManager.restore('app-deploy');
    }
  }

  modal.style.display = 'flex';

  const viewConfig = document.getElementById('adm-view-config');
  const viewProgress = document.getElementById('adm-view-progress');
  const footerConfig = document.getElementById('adm-footer-config');
  const footerProgress = document.getElementById('adm-footer-progress');
  if (viewConfig) viewConfig.style.display = 'flex';
  if (viewProgress) viewProgress.style.display = 'none';
  if (footerConfig) footerConfig.style.display = 'flex';
  if (footerProgress) footerProgress.style.display = 'none';

  let replaceExisting = false;
  let defaultContainerName = appId;
  let suggestedContainerName = appId;
  let defaultPort = 8080;
  let suggestedPort = 8080;
  let existingContainerInfo;

  const deployConfirmBtn = document.getElementById('adm-deploy-confirm-btn');
  const banner = document.getElementById('adm-conflict-banner');
  const existingBox = document.getElementById('adm-existing-box');
  const existingBadge = document.getElementById('adm-existing-status-badge');
  const existingDesc = document.getElementById('adm-existing-desc');
  const choiceReplaceBtn = document.getElementById('adm-choice-replace-btn');
  const choiceNewBtn = document.getElementById('adm-choice-new-btn');
  const nameInput = document.getElementById('adm-name-input');
  const portInput = document.getElementById('adm-port-input');
  const storageInput = document.getElementById('adm-storage-input');
  const composePre = document.getElementById('adm-compose-pre');
  const title = document.getElementById('adm-title');

  if (existingBox) existingBox.style.display = 'none';
  if (choiceReplaceBtn) {
    choiceReplaceBtn.style.border = '1px solid rgba(235, 87, 87, 0.4)';
    choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.12)';
    choiceReplaceBtn.style.opacity = '0.75';
    choiceReplaceBtn.style.boxShadow = 'none';
  }
  if (choiceNewBtn) {
    choiceNewBtn.style.border = '2px solid var(--ok2, #25c2a0)';
    choiceNewBtn.style.background = 'rgba(37, 194, 160, 0.18)';
    choiceNewBtn.style.opacity = '1';
    choiceNewBtn.style.boxShadow = '0 0 8px rgba(37,194,160,0.3)';
  }

  if (nameInput) {
    nameInput.value = appId;
    nameInput.style.borderColor = '';
  }
  if (portInput) {
    portInput.value = 8080;
    portInput.style.borderColor = '';
  }

  if (deployConfirmBtn) {
    deployConfirmBtn.disabled = false;
    deployConfirmBtn.style.opacity = '1';
    deployConfirmBtn.style.pointerEvents = 'auto';
    deployConfirmBtn.textContent = '🚀 Deploy & Launch Container';
    setDeployButtonTone(deployConfirmBtn, 'brand');
  }

  title.textContent = `Deploy ${appId.toUpperCase()}`;
  banner.innerHTML = '<span style="color:var(--muted);">Probing host ports and container state...</span>';
  banner.style.background = 'rgba(255,255,255,0.04)';
  banner.style.border = '1px solid rgba(255,255,255,0.08)';

  try {
    const resolveData = await api.get(`/api/docker/catalog/${appId}/resolve`);
    defaultPort = resolveData.default_port || 8080;
    suggestedPort = resolveData.suggested_port || defaultPort;
    existingContainerInfo = resolveData.existing_container;
    suggestedContainerName = resolveData.suggested_container_name || appId;
    defaultContainerName = (existingContainerInfo && existingContainerInfo.name) ? existingContainerInfo.name : appId;

    if (existingContainerInfo) {
      if (existingBox) existingBox.style.display = 'flex';
      const isRunning = existingContainerInfo.state === 'running';
      if (existingBadge) {
        existingBadge.textContent = isRunning ? 'RUNNING' : (existingContainerInfo.state || 'EXISTING').toUpperCase();
        existingBadge.style.color = isRunning ? 'var(--ok2, #25c2a0)' : 'var(--muted)';
        existingBadge.style.background = isRunning ? 'rgba(37,194,160,0.15)' : 'rgba(255,255,255,0.08)';
      }
      if (existingDesc) {
        existingDesc.innerHTML = `Found existing container <strong>${existingContainerInfo.name}</strong> (${existingContainerInfo.state || 'present'}). Would you like to stop and replace it, or deploy alongside as a new instance?`;
      }

      // Default to Deploy Alongside
      replaceExisting = false;
      if (nameInput) nameInput.value = suggestedContainerName;
      if (portInput) portInput.value = suggestedPort;

      if (resolveData.conflict_detected) {
        banner.style.background = 'rgba(245, 166, 35, 0.12)';
        banner.style.border = '1px solid var(--warn, #f5a623)';
        const occupier = resolveData.in_use_by ? ` (in use by ${resolveData.in_use_by})` : '';
        banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict Detected:</span> Default port ${defaultPort} is busy${occupier}. Automatically remapped to free port <strong>${suggestedPort}</strong>!`;
      } else {
        banner.style.background = 'rgba(37, 194, 160, 0.12)';
        banner.style.border = '1px solid var(--ok2, #25c2a0)';
        banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ Deploy Alongside:</span> Suggested new container name <strong>${suggestedContainerName}</strong> on available port <strong>${suggestedPort}</strong>.`;
      }
      if (deployConfirmBtn) deployConfirmBtn.textContent = '🚀 Deploy New Instance';
    } else if (resolveData.conflict_detected) {
      if (nameInput) nameInput.value = appId;
      if (portInput) portInput.value = suggestedPort;
      banner.style.background = 'rgba(245, 166, 35, 0.12)';
      banner.style.border = '1px solid var(--warn, #f5a623)';
      const occupier = resolveData.in_use_by ? ` (in use by ${resolveData.in_use_by})` : '';
      banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict Detected:</span> Default port ${defaultPort} is busy${occupier}. Automatically remapped to free port <strong>${suggestedPort}</strong>!`;
    } else {
      if (nameInput) nameInput.value = appId;
      if (portInput) portInput.value = suggestedPort;
      banner.style.background = 'rgba(37, 194, 160, 0.12)';
      banner.style.border = '1px solid var(--ok2, #25c2a0)';
      banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ Ready to Deploy:</span> Port ${suggestedPort} and name <strong>${appId}</strong> are free.`;
    }
  } catch (e) {
    if (nameInput) nameInput.value = appId;
    if (portInput) portInput.value = 8080;
    banner.innerHTML = '<span style="color:var(--muted);">Port status: Default assigned</span>';
  }

  function selectReplaceMode() {
    replaceExisting = true;
    if (nameInput) {
      nameInput.value = defaultContainerName;
      nameInput.style.borderColor = '';
    }
    if (portInput) {
      portInput.value = defaultPort;
      portInput.style.borderColor = '';
    }

    if (choiceReplaceBtn) {
      choiceReplaceBtn.style.border = '2px solid var(--err, #eb5757)';
      choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.22)';
      choiceReplaceBtn.style.opacity = '1';
      choiceReplaceBtn.style.boxShadow = '0 0 8px rgba(235,87,87,0.4)';
    }
    if (choiceNewBtn) {
      choiceNewBtn.style.border = '1px solid rgba(37, 194, 160, 0.4)';
      choiceNewBtn.style.background = 'rgba(37, 194, 160, 0.1)';
      choiceNewBtn.style.opacity = '0.75';
      choiceNewBtn.style.boxShadow = 'none';
    }

    banner.style.background = 'rgba(235, 87, 87, 0.12)';
    banner.style.border = '1px solid var(--err, #eb5757)';
    banner.innerHTML = `<span style="color:#ff8080; font-weight:bold;">⚠️ Stop &amp; Replace Mode:</span> The existing container <strong>${defaultContainerName}</strong> will be cleanly stopped and replaced on port <strong>${defaultPort}</strong>. Persistent data will be preserved.`;

    if (deployConfirmBtn) {
      deployConfirmBtn.textContent = '🔄 Stop, Replace & Launch';
      setDeployButtonTone(deployConfirmBtn, 'danger');
      deployConfirmBtn.disabled = false;
      deployConfirmBtn.style.opacity = '1';
      deployConfirmBtn.style.pointerEvents = 'auto';
    }

    updateComposePreview();
  }

  function selectNewInstanceMode() {
    replaceExisting = false;
    if (nameInput) {
      nameInput.value = suggestedContainerName;
      nameInput.style.borderColor = '';
    }
    if (portInput) {
      portInput.value = suggestedPort;
      portInput.style.borderColor = '';
    }

    if (choiceNewBtn) {
      choiceNewBtn.style.border = '2px solid var(--ok2, #25c2a0)';
      choiceNewBtn.style.background = 'rgba(37, 194, 160, 0.18)';
      choiceNewBtn.style.opacity = '1';
      choiceNewBtn.style.boxShadow = '0 0 8px rgba(37,194,160,0.3)';
    }
    if (choiceReplaceBtn) {
      choiceReplaceBtn.style.border = '1px solid rgba(235, 87, 87, 0.4)';
      choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.12)';
      choiceReplaceBtn.style.opacity = '0.75';
      choiceReplaceBtn.style.boxShadow = 'none';
    }

    banner.style.background = 'rgba(37, 194, 160, 0.12)';
    banner.style.border = '1px solid var(--ok2, #25c2a0)';
    banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ New Instance Mode:</span> Configuring container <strong>${suggestedContainerName}</strong> on free port <strong>${suggestedPort}</strong> alongside existing instance.`;

    if (deployConfirmBtn) {
      deployConfirmBtn.textContent = '🚀 Deploy New Instance';
      setDeployButtonTone(deployConfirmBtn, 'brand');
      deployConfirmBtn.disabled = false;
      deployConfirmBtn.style.opacity = '1';
      deployConfirmBtn.style.pointerEvents = 'auto';
    }

    updateComposePreview();
  }

  if (choiceReplaceBtn) choiceReplaceBtn.onclick = selectReplaceMode;
  if (choiceNewBtn) choiceNewBtn.onclick = selectNewInstanceMode;

  let nameValidationTimer = null;
  async function validateEnteredName() {
    const rawName = nameInput ? nameInput.value.trim() : '';
    if (!rawName) {
      banner.style.background = 'rgba(235, 87, 87, 0.12)';
      banner.style.border = '1px solid var(--err, #eb5757)';
      if (nameInput) nameInput.style.borderColor = 'var(--err, #eb5757)';
      banner.innerHTML = `<span style="color:var(--err, #eb5757); font-weight:bold;">✕ Invalid Name:</span> Container name cannot be empty.`;
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = true;
        deployConfirmBtn.style.opacity = '0.5';
        deployConfirmBtn.style.pointerEvents = 'none';
      }
      return;
    }

    try {
      const check = await api.get(`/api/docker/check_container_name?name=${encodeURIComponent(rawName)}`);
      if (check && check.exists) {
        if (replaceExisting && check.name === defaultContainerName) {
          if (nameInput) nameInput.style.borderColor = '';
          banner.style.background = 'rgba(235, 87, 87, 0.12)';
          banner.style.border = '1px solid var(--err, #eb5757)';
          banner.innerHTML = `<span style="color:#ff8080; font-weight:bold;">⚠️ Stop &amp; Replace Mode:</span> Existing container <strong>${check.name}</strong> will be stopped and replaced.`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = false;
            deployConfirmBtn.style.opacity = '1';
            deployConfirmBtn.style.pointerEvents = 'auto';
          }
        } else {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          if (nameInput) nameInput.style.borderColor = 'var(--warn, #f5a623)';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Container Name In Use:</span> A container named <strong>${check.name}</strong> already exists. Please choose a different name or select 'Stop &amp; Replace'.`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = true;
            deployConfirmBtn.style.opacity = '0.5';
            deployConfirmBtn.style.pointerEvents = 'none';
          }
        }
      } else {
        if (nameInput) nameInput.style.borderColor = '';
        validateEnteredPort();
      }
    } catch (e) {
      if (nameInput) nameInput.style.borderColor = '';
    }
  }

  let portValidationTimer = null;
  async function validateEnteredPort() {
    const val = parseInt(portInput.value, 10);
    if (!val || val < 1 || val > 65535) {
      banner.style.background = 'rgba(235, 87, 87, 0.12)';
      banner.style.border = '1px solid var(--err, #eb5757)';
      portInput.style.borderColor = 'var(--err, #eb5757)';
      banner.innerHTML = `<span style="color:var(--err, #eb5757); font-weight:bold;">✕ Invalid Port:</span> Please enter a valid port between 1 and 65535.`;
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = true;
        deployConfirmBtn.style.opacity = '0.5';
        deployConfirmBtn.style.pointerEvents = 'none';
      }
      return;
    }

    try {
      const check = await api.get(`/api/docker/check_port?port=${val}&proto=tcp`);
      if (check && check.available === false) {
        const cName = nameInput ? nameInput.value.trim() : appId;
        const isOccupiedByTarget = replaceExisting && check.in_use_by && (
          check.in_use_by === `container '${cName}'` ||
          check.in_use_by.includes(cName)
        );

        if (isOccupiedByTarget) {
          banner.style.background = 'rgba(235, 87, 87, 0.12)';
          banner.style.border = '1px solid var(--err, #eb5757)';
          portInput.style.borderColor = '';
          banner.innerHTML = `<span style="color:#ff8080; font-weight:bold;">⚠️ Stop &amp; Replace Mode:</span> Port ${val} is currently bound by <strong>${cName}</strong>, which will be stopped and replaced.`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = false;
            deployConfirmBtn.style.opacity = '1';
            deployConfirmBtn.style.pointerEvents = 'auto';
          }
          return;
        }

        banner.style.background = 'rgba(245, 166, 35, 0.15)';
        banner.style.border = '1px solid var(--warn, #f5a623)';
        portInput.style.borderColor = 'var(--warn, #f5a623)';
        const inUse = check.in_use_by ? ` (in use by ${check.in_use_by})` : '';
        banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict:</span> Port ${val} is already busy${inUse}. Please choose an available port before deploying.`;
        if (deployConfirmBtn) {
          deployConfirmBtn.disabled = true;
          deployConfirmBtn.style.opacity = '0.5';
          deployConfirmBtn.style.pointerEvents = 'none';
        }
      } else {
        banner.style.background = 'rgba(37, 194, 160, 0.12)';
        banner.style.border = '1px solid var(--ok2, #25c2a0)';
        portInput.style.borderColor = '';
        const cName = nameInput ? nameInput.value.trim() : appId;
        banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ Ready to Deploy:</span> Port ${val} is free and ready for container <strong>${cName}</strong>.`;
        if (deployConfirmBtn) {
          deployConfirmBtn.disabled = false;
          deployConfirmBtn.style.opacity = '1';
          deployConfirmBtn.style.pointerEvents = 'auto';
        }
      }
    } catch (err) {
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = false;
        deployConfirmBtn.style.opacity = '1';
        deployConfirmBtn.style.pointerEvents = 'auto';
      }
    }
  }

  async function updateComposePreview() {
    const p = parseInt(portInput.value, 10) || suggestedPort;
    const s = storageInput.value.trim() || '/mnt/user/appdata';
    const cName = nameInput ? nameInput.value.trim() : appId;
    try {
      const comp = await api.post(`/api/docker/catalog/${appId}/compose`, {
        host_port: p,
        storage_root: s,
        container_name: cName,
      });
      composePre.textContent = comp.compose_yaml;
    } catch (err) {
      composePre.textContent = `# Failed to generate compose: ${err.message}`;
    }
  }

  if (nameInput) {
    nameInput.oninput = () => {
      updateComposePreview();
      clearTimeout(nameValidationTimer);
      nameValidationTimer = setTimeout(validateEnteredName, 250);
    };
  }

  portInput.oninput = () => {
    updateComposePreview();
    clearTimeout(portValidationTimer);
    portValidationTimer = setTimeout(validateEnteredPort, 250);
  };
  storageInput.oninput = updateComposePreview;
  await updateComposePreview();

  document.getElementById('adm-copy-btn').onclick = () => {
    copyTextToClipboard(composePre.textContent).then((ok) => {
      if (ok) {
        showToast(t('toast.docker_compose_yaml_copied_to_clipboard', 'Docker Compose YAML copied to clipboard!'), 'success');
      } else {
        showToast(t('toast.failed_to_copy_to_clipboard', 'Failed to copy to clipboard'), 'warn');
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
    showToast(t('toast.downloaded_compose_yml_2', 'Downloaded {appId}-compose.yml', { appId: appId }), 'info');
  };

  // Deployment execution with live progress bar and streaming console
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
      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `${appId.toUpperCase()} (${data.percent}%)`;
        DockManager.render();
      }
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
        webuiBtn.style.display = data.has_webui === false ? 'none' : '';
      }
      showDeployCredentials(successBox, data, `${window.location.hostname}:${data.port || suggestedPort}`);

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

      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `✓ ${appId.toUpperCase()} Deployed`;
        DockManager.render();
      }
      if (modal.classList.contains('window-minimized') || (DockManager && DockManager.windows['app-deploy']?.minimized)) {
        showDockToast(`🚀 ${appId.toUpperCase()} stack deployed and running! Click to open.`, 'app-deploy');
      }

      try {
        fetchAndRenderDockerContainers();
      } catch (e) {}

      showToast(t('toast.stack_deployed_and_running', '{appId} stack deployed and running!', { appId: appId }), 'success');
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

      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `❌ ${appId.toUpperCase()} Failed`;
        DockManager.render();
      }
      if (modal.classList.contains('window-minimized') || (DockManager && DockManager.windows['app-deploy']?.minimized)) {
        showDockToast(`❌ ${appId.toUpperCase()} deployment failed! Click to view logs.`, 'app-deploy');
      }

      showToast(t('toast.deployment_failed', 'Deployment failed: {message}', { message: data.message }), 'error');
    }
  }

  deployConfirmBtn.onclick = async () => {
    const p = parseInt(portInput.value, 10) || suggestedPort;
    const s = storageInput.value.trim() || '/mnt/user/appdata';
    const cName = nameInput ? nameInput.value.trim() : appId;

    if (!replaceExisting) {
      // 1. Verify container name is available
      try {
        const nameCheck = await api.get(`/api/docker/check_container_name?name=${encodeURIComponent(cName)}`);
        if (nameCheck && nameCheck.exists) {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          if (nameInput) nameInput.style.borderColor = 'var(--warn, #f5a623)';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Container Name In Use:</span> A container named <strong>${cName}</strong> already exists. Please choose a unique name or select 'Stop &amp; Replace Existing'.`;
          showToast(t('toast.container_already_exists_please_rename_or', 'Container \'{cName}\' already exists. Please rename or select Replace.', { cName: cName }), 'warn');
          return;
        }
      } catch (err) {}

      // 2. Verify port availability before starting deployment
      try {
        const check = await api.get(`/api/docker/check_port?port=${p}&proto=tcp`);
        if (check && check.available === false) {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          portInput.style.borderColor = 'var(--warn, #f5a623)';
          const inUse = check.in_use_by ? ` (in use by ${check.in_use_by})` : '';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict:</span> Port ${p} is already busy${inUse}. Please choose an available port before deploying.`;
          showToast(t('toast.port_is_already_in_use_please', 'Port {p} is already in use{inUse}. Please change the port.', { p: p, inUse: inUse }), 'warn');
          return;
        }
      } catch (err) {}
    }

    modal._isDeploying = true;
    modal._activeAppId = appId;

    // Switch views
    viewConfig.style.display = 'none';
    footerConfig.style.display = 'none';
    viewProgress.style.display = 'flex';
    footerProgress.style.display = 'flex';

    // Keep close button interactive while active
    closeBtn.disabled = false;
    closeBtn.style.opacity = '1';
    closeBtn.style.pointerEvents = 'auto';

    // Reset progress UI
    if (progressFill) progressFill.style.width = '0%';
    if (progressPct) {
      progressPct.textContent = '0%';
      progressPct.style.color = 'var(--accent-cyan, #00f0ff)';
    }
    if (progressTitle) progressTitle.textContent = `Deploying ${cName} Stack...`;
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

    logDeployLine(`Initiating deployment request for ${cName} (Port :${p}, Storage: ${s}, Replace: ${replaceExisting})...`);

    try {
      const response = await api.request(`/api/docker/catalog/${appId}/deploy`, {
        method: 'POST',
        body: {
          host_port: p,
          storage_root: s,
          container_name: cName,
          replace_existing: replaceExisting,
        },
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
                <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Images</div>
                <div id="dpm-df-images" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Containers</div>
                <div id="dpm-df-containers" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Volumes</div>
                <div id="dpm-df-volumes" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(0,240,255,0.06); border:1px solid rgba(0,240,255,0.2); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:11px; color:var(--accent-cyan, #00f0ff); text-transform:uppercase; font-weight:700;">Reclaimable</div>
                <div id="dpm-df-reclaimable" style="font-size:12.5px; font-weight:800; color:var(--ok2, #25c2a0); margin-top:2px;">--</div>
              </div>
            </div>

            <!-- Prune Options -->
            <div style="background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:12px; display:flex; flex-direction:column; gap:10px;">
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-containers" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Stopped Containers</strong>
                  <div style="font-size:11px; color:var(--muted);">Deletes all exited, stopped, and dead containers.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-images" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Dangling Images</strong>
                  <div style="font-size:11px; color:var(--muted);">Removes untagged &lt;none&gt; build layers and intermediate images.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-all-images" style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune ALL Unused Images</strong>
                  <div style="font-size:11px; color:var(--muted);">Removes images no container uses, running or stopped. Images of stopped containers (such as update rollbacks) are kept.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-volumes" style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Unused Local Volumes</strong>
                  <div style="font-size:11px; color:var(--warn, #f5a623);">Caution: Removes local anonymous volumes not mounted by containers.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-buildcache" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Build Cache & Unused Networks</strong>
                  <div style="font-size:11px; color:var(--muted);">Frees temporary Docker build cache layers and disconnected bridge networks.</div>
                </div>
              </label>
            </div>

            <!-- Progress while the cleanup runs (it continues if this dialog is closed) -->
            <div id="dpm-progress" class="zn-card zn-box" hidden>
              <div class="zn-row zn-row--between">
                <span id="dpm-progress-msg" class="zn-muted"></span>
                <strong id="dpm-progress-pct" class="dpm-progress-pct">0%</strong>
              </div>
              <div class="dpm-bar" id="dpm-bar" role="progressbar" aria-label="Cleanup progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="dpm-bar-fill" id="dpm-bar-fill"></div></div>
              <ul class="zn-list" id="dpm-steps"></ul>
              <div class="zn-muted" id="dpm-freed"></div>
            </div>
          </div>
          <div style="padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="dpm-cancel-btn">Cancel</button>
            <button class="btn-pill-toggle is-primary" id="dpm-confirm-btn">
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
  setPruneIdle();

  confirmBtn.onclick = async () => {
    if (confirmBtn.dataset.mode === 'done') {
      modal.classList.remove('open');
      modal.style.display = 'none';
      setPruneIdle();
      return;
    }
    const allImages = document.getElementById('dpm-opt-all-images').checked;
    const pruneBuildCache = document.getElementById('dpm-opt-buildcache').checked;
    confirmBtn.disabled = true;
    try {
      const res = await api.post('/api/docker/system/prune/jobs', {
        prune_containers: document.getElementById('dpm-opt-containers').checked,
        prune_images: document.getElementById('dpm-opt-images').checked || allImages,
        all_images: allImages,
        prune_volumes: document.getElementById('dpm-opt-volumes').checked,
        prune_networks: pruneBuildCache,
        prune_build_cache: pruneBuildCache,
      });
      followPruneJob(res.job);
    } catch (err) {
      showToast(t('toast.prune_failed', 'Prune failed: {error}', { error: err.message }), 'error');
      setPruneIdle();
    }
  };

  // A cleanup started earlier (maybe from another tab) is still running: show it.
  try {
    const cur = await api.get('/api/docker/system/prune/jobs/current');
    if (cur && cur.job && cur.job.state === 'running') followPruneJob(cur.job);
  } catch (err) {
    console.warn('Could not check for a running cleanup:', err);
  }
}

const PRUNE_STEP_LABELS = () => ({
  containers: t('prune.step_containers', 'Stopped containers'),
  images: t('prune.step_images', 'Unused images'),
  volumes: t('prune.step_volumes', 'Unused volumes'),
  networks: t('prune.step_networks', 'Unused networks'),
  build_cache: t('prune.step_build_cache', 'Build cache'),
});
const PRUNE_STEP_ICONS = { pending: '○', running: '◐', done: '✓', skipped: '–', error: '!' };
let _prunePollTimer = null;

function setPruneIdle() {
  const btn = document.getElementById('dpm-confirm-btn');
  const cancel = document.getElementById('dpm-cancel-btn');
  const opts = document.getElementById('dpm-opt-containers')?.closest('div[style*="flex-direction:column"]');
  if (btn) {
    btn.disabled = false;
    btn.dataset.mode = 'start';
    btn.textContent = '🧹 Run Prune & Reclaim Storage';
  }
  if (cancel) {
    cancel.hidden = false;
    cancel.textContent = t('common.cancel', 'Cancel');
    cancel.onclick = (e) => {
      e.preventDefault();
      const m = document.getElementById('docker-prune-modal-overlay');
      if (m) { m.classList.remove('open'); m.style.display = 'none'; }
    };
  }
  if (opts) opts.inert = false;
  const prog = document.getElementById('dpm-progress');
  if (prog) prog.hidden = true;
}

export function renderPruneJob(job) {
  const prog = document.getElementById('dpm-progress');
  if (!prog || !job) return;
  prog.hidden = false;
  const labels = PRUNE_STEP_LABELS();
  const pct = Math.max(0, Math.min(100, job.percent || 0));
  const fill = document.getElementById('dpm-bar-fill');
  if (fill) fill.style.width = `${pct}%`;
  document.getElementById('dpm-bar')?.setAttribute('aria-valuenow', String(pct));
  const pctEl = document.getElementById('dpm-progress-pct');
  if (pctEl) pctEl.textContent = `${pct}%`;
  const msgEl = document.getElementById('dpm-progress-msg');
  if (msgEl) {
    let msg = job.step ? `${labels[job.step] || job.step}…` : '';
    if (job.step === 'images' && job.images_total) {
      msg = t('prune.images_progress', 'Removing image {done} of {total}', { done: Math.min(job.images_done + 1, job.images_total), total: job.images_total });
    }
    if (job.state !== 'running') msg = '';
    msgEl.textContent = msg;
  }
  const list = document.getElementById('dpm-steps');
  if (list) {
    list.replaceChildren(...(job.steps || []).map((s) => {
      const li = document.createElement('li');
      li.className = `dpm-step is-${s.state}`;
      const icon = Object.assign(document.createElement('span'), { className: 'dpm-step-icon', textContent: PRUNE_STEP_ICONS[s.state] || '○' });
      icon.setAttribute('aria-hidden', 'true');
      const name = Object.assign(document.createElement('span'), { textContent: labels[s.key] || s.key });
      let detail = s.detail || '';
      if (s.key === 'images' && s.state === 'running' && job.images_total) detail = `${job.images_done} / ${job.images_total}`;
      if (s.freed_bytes > 0) detail = `${detail}${detail ? ' · ' : ''}${formatSize(s.freed_bytes)}`;
      const det = Object.assign(document.createElement('span'), { className: 'zn-push-end zn-muted', textContent: detail });
      li.append(icon, name, det);
      return li;
    }));
  }
  const freed = document.getElementById('dpm-freed');
  if (freed) freed.textContent = t('prune.freed', '{freed} freed so far', { freed: job.freed_human || '0 B' });
}

function followPruneJob(job) {
  const btn = document.getElementById('dpm-confirm-btn');
  const cancel = document.getElementById('dpm-cancel-btn');
  const opts = document.getElementById('dpm-opt-containers')?.closest('div[style*="flex-direction:column"]');
  if (opts) opts.inert = true;
  if (cancel) {
    cancel.hidden = false;
    cancel.textContent = t('prune.stop', 'Stop');
    cancel.onclick = async (e) => {
      e.preventDefault();
      cancel.disabled = true;
      try { await api.post(`/api/docker/system/prune/jobs/${job.id}/cancel`, {}); } catch (err) { console.warn('Stop failed:', err); }
      cancel.disabled = false;
    };
  }
  const tick = (j) => {
    renderPruneJob(j);
    if (btn) {
      btn.disabled = true;
      btn.textContent = t('prune.running_pct', 'Cleaning up… {pct}%', { pct: j.percent || 0 });
    }
    if (j.state !== 'running') finishPruneJob(j);
  };
  tick(job);
  if (_prunePollTimer) clearInterval(_prunePollTimer);
  if (job.state !== 'running') return;
  _prunePollTimer = setInterval(async () => {
    try {
      const res = await api.get(`/api/docker/system/prune/jobs/${job.id}`);
      tick(res.job);
    } catch (err) {
      console.warn('Cleanup progress unavailable:', err);
    }
  }, 900);
}

async function finishPruneJob(job) {
  if (_prunePollTimer) { clearInterval(_prunePollTimer); _prunePollTimer = null; }
  renderPruneJob(job);
  const freed = job.freed_human || '0 B';
  if (job.state === 'cancelled') {
    showToast(t('prune.stopped', 'Cleanup stopped: {freed} freed so far.', { freed }), 'info');
  } else if (job.errors && job.errors.length) {
    showToast(t('prune.done_errors', 'Cleanup finished with errors: {freed} freed. {errors}', { freed, errors: job.errors.join('; ') }), 'warning');
  } else {
    showToast(t('prune.done', 'Cleanup finished: {freed} freed.', { freed }), 'success');
  }
  const btn = document.getElementById('dpm-confirm-btn');
  const cancel = document.getElementById('dpm-cancel-btn');
  if (btn) {
    btn.disabled = false;
    btn.dataset.mode = 'done';
    btn.textContent = t('prune.close', 'Done');
  }
  if (cancel) cancel.hidden = true;
  try { await fetchAndRenderDockerContainers(); } catch (err) { console.warn('Container list refresh failed:', err); }
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
                  <span class="ci-badge" style="font-size:11px; background:rgba(37,194,160,0.2); color:var(--accent);">790+ Apps</span>
                </div>
                <div style="font-size:11px; color:#94a3b8; margin-top:2px;">
                  Comprehensive community catalog of self-hosted homelab applications, web tools, and stacks.
                </div>
              </div>
              <button class="btn-pill-toggle is-primary" id="asm-btn-add-lissy">
                + Add Lissy93 (790+ Apps)
              </button>
            </div>

            <!-- Add Custom Source Form -->
            <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px; display:flex; flex-direction:column; gap:10px;">
              <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px;">Add Custom Template Source</div>
              <div style="display:grid; grid-template-columns:1fr 2fr auto; gap:8px; align-items:end;">
                <div>
                  <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:3px;">SOURCE NAME</label>
                  <input type="text" id="asm-input-name" placeholder="e.g. Community Apps" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:5px 8px;">
                </div>
                <div>
                  <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:3px;">TEMPLATE URL (JSON)</label>
                  <input type="url" id="asm-input-url" placeholder="https://example.com/templates.json" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:5px 8px;">
                </div>
                <div>
                  <button class="btn-pill-toggle is-primary" id="asm-btn-add-custom">
                    + Add & Sync
                  </button>
                </div>
              </div>
              <div id="asm-form-status" style="font-size:11px; display:none; padding:4px 6px; border-radius:4px;"></div>
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
          showToast(t('toast.lissy93_portainer_templates_added_790_apps', 'Lissy93 Portainer templates added (790+ apps)!'), 'success');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(t('toast.failed_to_add_lissy93_templates', 'Failed to add Lissy93 templates: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.added_template_source', 'Added template source "{name}"!', { name: name }), 'success');
          setTimeout(() => { statusEl.style.display = 'none'; }, 3000);
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          statusEl.style.background = 'rgba(239,68,68,0.15)';
          statusEl.style.color = '#fca5a5';
          statusEl.textContent = `Error: ${err.message}`;
          showToast(t('toast.failed_to_add_source', 'Failed to add source: {error}', { error: err.message }), 'error');
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
        ? `<span class="ci-badge" style="font-size:11px; background:rgba(37,194,160,0.15); color:var(--accent);">✓ Synced (${formatRelativeTime(src.last_synced)})</span>`
        : (src.status === 'error'
          ? `<span class="ci-badge" style="font-size:11px; background:rgba(239,68,68,0.15); color:#fca5a5;" title="${escapeHtml(src.error || 'Sync failed')}">⚠️ Error</span>`
          : `<span class="ci-badge" style="font-size:11px; background:rgba(14,165,233,0.15); color:#38bdf8;">🔄 ${escapeHtml(src.status || 'pending')}</span>`);

      const toggleBtnClass = isEnabled ? 'btn-pill-toggle active' : 'btn-pill-toggle';
      const toggleText = isEnabled ? 'Enabled' : 'Disabled';

      return `
        <div class="asm-source-card" data-sourceid="${escapeHtml(src.id)}" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px 12px; display:flex; justify-content:space-between; align-items:center; gap:10px;">
          <div style="overflow:hidden; flex:1;">
            <div style="display:flex; align-items:center; gap:8px;">
              <strong style="font-size:12px; color:#fff;">${escapeHtml(src.name)}</strong>
              <span class="ci-badge" style="font-size:11px; background:rgba(255,255,255,0.06); color:#cbd5e1;">${src.item_count || 0} apps</span>
              ${statusBadge}
            </div>
            <div style="font-size:11px; color:var(--muted); font-family:var(--font-mono, monospace); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px;">
              ${escapeHtml(src.url)}
            </div>
            ${src.error ? `<div style="font-size:11px; color:#fca5a5; margin-top:3px;">${escapeHtml(src.error)}</div>` : ''}
          </div>
          <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
            <button class="${toggleBtnClass} asm-btn-toggle" data-sourceid="${escapeHtml(src.id)}" data-enabled="${isEnabled ? 'true' : 'false'}" style="font-size:11px; padding:3px 8px; cursor:pointer;">
              ${toggleText}
            </button>
            <button class="btn-pill-toggle asm-btn-sync is-small" data-sourceid="${escapeHtml(src.id)}" title="Sync Now">
              🔄
            </button>
            ${!isBuiltin ? `
              <button class="btn-pill-toggle asm-btn-delete is-danger is-small" data-sourceid="${escapeHtml(src.id)}" title="Delete Source">
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
          showToast(!curEnabled ? t('toast.source_enabled', 'Source enabled.') : t('toast.source_disabled', 'Source disabled.'), 'info');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(t('toast.failed_to_toggle_source', 'Failed to toggle source: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.source_synced', 'Source synced ({count} apps).', { count: res.source ? res.source.item_count : 0 }), 'success');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(t('toast.failed_to_sync_source', 'Failed to sync source: {error}', { error: err.message }), 'error');
          btn.disabled = false;
          btn.textContent = '🔄';
        }
      };
    });

    // Wire delete buttons
    listEl.querySelectorAll('.asm-btn-delete').forEach((btn) => {
      btn.onclick = () => {
        const sid = btn.dataset.sourceid;
        showConfirmToast(
          t('catalog.delete_source_title', 'Delete Template Source'),
          t('catalog.delete_source_confirm', 'Are you sure you want to delete this template source and all cached templates?'),
          async () => {
            btn.disabled = true;
            try {
              await api.delete(`/api/docker/catalog/sources/${sid}`);
              showToast(t('toast.source_deleted_successfully', 'Source deleted successfully.'), 'info');
              await refreshSourcesUI();
              fetchAndRenderAppCatalog();
            } catch (err) {
              showToast(t('toast.failed_to_delete_source', 'Failed to delete source: {error}', { error: err.message }), 'error');
              btn.disabled = false;
            }
          }
        );
      };
    });

  } catch (err) {
    listEl.innerHTML = `<div style="text-align:center; color:var(--crit); padding:16px;">Failed to load sources: ${escapeHtml(err.message)}</div>`;
  }
}

export function openSideloadAppModal() {
  const modal = document.getElementById('modal-sideload-app');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-sideload-close-btn');
  const cancelBtn = document.getElementById('modal-sideload-cancel-btn');
  const tabUrl = document.getElementById('sideload-tab-url');
  const tabPaste = document.getElementById('sideload-tab-paste');
  const urlWrap = document.getElementById('sideload-input-url-wrap');
  const pasteWrap = document.getElementById('sideload-input-paste-wrap');
  const urlInput = document.getElementById('sideload-url-input');
  const contentInput = document.getElementById('sideload-content-input');
  const btnInspect = document.getElementById('btn-sideload-inspect');
  const resultBox = document.getElementById('sideload-inspect-result');
  const btnConfirm = document.getElementById('btn-sideload-confirm');

  let activeTab = 'url';
  let inspectedApp = null;

  function closeModal() {
    modal.style.display = 'none';
    modal.classList.remove('open');
    if (resultBox) resultBox.style.display = 'none';
    if (btnConfirm) {
      btnConfirm.disabled = true;
      btnConfirm.style.opacity = '0.5';
      btnConfirm.style.cursor = 'not-allowed';
    }
  }

  if (closeBtn) closeBtn.onclick = closeModal;
  if (cancelBtn) cancelBtn.onclick = closeModal;
  modal.onclick = (e) => {
    if (e.target === modal) closeModal();
  };

  if (tabUrl && tabPaste) {
    tabUrl.onclick = () => {
      activeTab = 'url';
      tabUrl.classList.add('active');
      tabPaste.classList.remove('active');
      if (urlWrap) urlWrap.style.display = 'block';
      if (pasteWrap) pasteWrap.style.display = 'none';
    };
    tabPaste.onclick = () => {
      activeTab = 'paste';
      tabPaste.classList.add('active');
      tabUrl.classList.remove('active');
      if (urlWrap) urlWrap.style.display = 'none';
      if (pasteWrap) pasteWrap.style.display = 'block';
    };
  }

  if (btnInspect) {
    btnInspect.onclick = async () => {
      const url = activeTab === 'url' ? (urlInput?.value || '').trim() : '';
      const manifest = activeTab === 'paste' ? (contentInput?.value || '').trim() : '';
      if (!url && !manifest) {
        showToast(t('toast.please_provide_a_url_or_paste', 'Please provide a URL or paste manifest YAML/JSON.'), 'warning');
        return;
      }
      btnInspect.disabled = true;
      btnInspect.innerHTML = '<span>⏳</span> <span>Validating...</span>';
      try {
        const payload = url ? { url } : { manifest_content: manifest };
        const res = await api.post('/api/docker/catalog/sideload', payload);
        if (res.status === 'ok' && res.app) {
          inspectedApp = res.app;
          renderSideloadInspection(res.app, res.security_rating, res.security_flags, resultBox);
          if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.style.opacity = '1';
            btnConfirm.style.cursor = 'pointer';
          }
        }
      } catch (err) {
        showToast(t('toast.failed_to_inspect_manifest', 'Failed to inspect manifest: {error}', { error: err.message }), 'error');
        if (resultBox) {
          resultBox.style.display = 'block';
          resultBox.innerHTML = `<div style="color:var(--alert, #ef4444); font-size:12px;">Inspection Failed: ${escapeHtml(err.message)}</div>`;
        }
      } finally {
        btnInspect.disabled = false;
        btnInspect.innerHTML = '🔍 <span>Inspect & Validate</span>';
      }
    };
  }

  if (btnConfirm) {
    btnConfirm.onclick = () => {
      if (!inspectedApp) return;
      showToast(t('catalog.sideload_success', 'Application sideloaded successfully.'), 'success');
      closeModal();
      fetchAndRenderAppCatalog();
    };
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
}

function renderSideloadInspection(app, rating, flags, container) {
  if (!container) return;
  container.style.display = 'block';

  let badgeColor = '#4ade80';
  let badgeBg = 'rgba(34,197,94,0.15)';
  let badgeBorder = 'rgba(34,197,94,0.3)';
  let badgeText = '🛡️ Verified Safe';

  if (rating === 'review_required') {
    badgeColor = '#facc15';
    badgeBg = 'rgba(234,179,8,0.15)';
    badgeBorder = 'rgba(234,179,8,0.3)';
    badgeText = '⚠️ Review Required';
  } else if (rating === 'elevated') {
    badgeColor = '#f87171';
    badgeBg = 'rgba(239,68,68,0.15)';
    badgeBorder = 'rgba(239,68,68,0.3)';
    badgeText = '🚨 Elevated Privileges Risk';
  }

  const flagsHtml = (flags && flags.length > 0)
    ? `<div style="margin-top:8px; font-size:11px; background:rgba(0,0,0,0.3); border-radius:4px; padding:6px 10px;">
        <div style="font-weight:700; color:${badgeColor}; margin-bottom:4px;">Security Audit Findings:</div>
        <ul style="margin:0; padding-left:16px; color:#cbd5e1;">
          ${flags.map((f) => `<li>${escapeHtml(f)}</li>`).join('')}
        </ul>
      </div>`
    : `<div style="margin-top:8px; font-size:11px; color:#4ade80;">✓ Zero high-privilege risk flags detected. Standard isolated container sandbox.</div>`;

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
      <div style="font-weight:700; font-size:13px; color:#fff;">${escapeHtml(app.name)}</div>
      <span class="ci-badge" style="font-size:11px; background:${badgeBg}; color:${badgeColor}; border:1px solid ${badgeBorder}; padding:2px 8px; border-radius:4px;">${badgeText}</span>
    </div>
    <div style="font-size:11px; color:var(--muted); line-height:1.4;">
      <div><strong>Image:</strong> <code>${escapeHtml(app.image || 'compose-stack')}</code></div>
      <div><strong>Type:</strong> ${escapeHtml(app.type || 'standalone')} · <strong>Default Port:</strong> ${escapeHtml(String(app.default_port || 'N/A'))}</div>
    </div>
    ${flagsHtml}
  `;
}
