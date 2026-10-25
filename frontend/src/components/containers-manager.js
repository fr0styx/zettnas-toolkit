/**
 * ZettNAS Toolkit - Dedicated Docker Containers & Services Window Manager
 * Provides a dedicated desktop window for Docker containers with live telemetry,
 * filtering, search, compose stacks, container controls, and app catalog access.
 */

import { api } from '../api.js';
import { catalogCardHtml, catalogChipsHtml, filterCatalog, isInstalled, bindCatalogChips } from './catalog-view.js';
import { escapeHtml, reconcileKeyedTable } from '../utils.js';
import { emptyStateHtml } from './empty-state.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast, showBottomSheet } from '../toast.js';
import { t } from '../i18n.js';
import { makeDraggable, bringToFront } from './dock.js';
import { openContainerInspector, openContainerDeleteModal } from './container-modal.js';
import { openStackModal, openStackPickerModal } from './stack-modal.js';
import { openNetworkMap } from './container-network-map.js';
import {
  createContainerRow as createSharedContainerRow,
  updateContainerRow as updateSharedContainerRow,
  buildContainerRowInner as buildSharedContainerRowInner,
  getSelectedContainerIds,
  isContainerSelected,
  toggleContainerSelected,
  clearSelectedContainers,
  selectAllContainers,
  runBulkContainerAction,
  initSynchronizedTableScrollbars,
} from './docker-table.js';

let containersWindow = null;
let _cwContainersList = [];
let _cwUpdatesCache = null;
let _cwFilter = 'all';
let _cwSearchQuery = '';
let _cwSortCol = null;
let _cwSortDir = 'asc';
let _cwIsMax = false;
let _cwPreMaxBounds = null;
let _cwInCatalogView = false;
let _cwCatalogApps = [];
let _cwCatalogCategory = 'all';
let _cwCatalogSearch = '';

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
            <button class="win-btn min-btn" id="containers-min" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
            <button class="win-btn max-btn" id="containers-max" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
            <button class="win-btn close-btn" id="containers-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Telemetry & Action Strip Header -->
        <div class="containers-telemetry-header">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
            <!-- Quick Status Badges -->
            <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
              <div class="cw-docker-status-chip" style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: var(--zn-fs-xs); font-weight: 600; background: rgba(16,185,129,0.15); color: var(--lt-t-34d399ff, #34d399); border: 1px solid rgba(16,185,129,0.3);">
                <span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:#34d399; box-shadow:0 0 6px #34d399;"></span>
                <span id="cw-stat-daemon">Docker Socket Active</span>
                <span style="opacity:0.35;">•</span>
                <span style="font-size:var(--zn-fs-xs); color:var(--lt-t-cbd5e1ff, #cbd5e1); font-weight:500;">Live Sync</span>
              </div>
              <div style="display: inline-flex; align-items: center; gap: 6px; font-size: var(--zn-fs-xs); color: var(--muted);">
                <span>Total: <strong id="cw-count-all" style="color: var(--lt-t-ffffffff, #fff);">0</strong></span>
                <span>•</span>
                <span style="color: var(--lt-t-34d399ff, #34d399);">Running: <strong id="cw-count-running">0</strong></span>
                <span>•</span>
                <span style="color: var(--lt-t-94a3b8ff, #94a3b8);">Stopped: <strong id="cw-count-stopped">0</strong></span>
                <span id="cw-count-updates-wrap" style="display: none;">• <span style="color: var(--lt-t-fbbf24ff, #fbbf24);">Updates: <strong id="cw-count-updates">0</strong></span></span>
              </div>
            </div>

            <!-- Quick Action Buttons -->
            <div class="cw-action-btns-wrap" style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
              <button id="btn-cw-check-updates" class="btn-pill-toggle" title="${t('ui.check_remote_registries_for_container', 'Check remote registries for container image updates')}">
                <span style="color: var(--ok2, #25c2a0);">✓</span> <span>Check Updates</span>
              </button>
              <button id="btn-cw-update-all" class="btn-pill-toggle" style="display: none; color: var(--lt-t-fbbf24ff, #fbbf24); border-color: rgba(251,191,36,0.4); background: rgba(251,191,36,0.12);" title="${t('ui.update_all_containers_with_available', 'Update all containers with available image updates')}">
                <span aria-hidden="true">↑</span> <span>Update All (<span id="cw-updates-count-badge">0</span>)</span>
              </button>
              <button id="btn-cw-stacks" class="btn-pill-toggle" title="${t('ui.manage_docker_compose_stacks', 'Manage Docker Compose Stacks')}" style="color: var(--lt-ink-brand, var(--accent-cyan, #38bdf8));">
                <span aria-hidden="true">📁</span> <span>Compose Stacks</span>
              </button>
              <button id="btn-cw-netmap" class="btn-pill-toggle" title="${t('cw.netmap_title', 'Container Network Map')}">
                <span aria-hidden="true">🕸️</span> <span data-i18n="cw.netmap_btn">${t('cw.netmap_btn', 'Network Map')}</span>
              </button>
              <button id="btn-cw-prune" class="btn-pill-toggle" title="${t('ui.clean_up_unused_container_images', 'Clean up unused container images, stopped containers, and volumes')}">
                <span aria-hidden="true">🧹</span> <span>Prune</span>
              </button>
              <button id="btn-cw-catalog" class="btn-pill-toggle is-primary">
                <span aria-hidden="true">📦</span> <span>${t('apps.get_apps', 'Get apps')}</span>
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
              <input type="text" id="cw-docker-search-input" placeholder="${t('mgmt.docker_search_placeholder', 'Search containers, images, ports...')}" class="tz-text-input" style="font-size: var(--zn-fs-xs); padding: 4px 10px; width: 220px; height: 26px; border-radius: 4px;">
            </div>
          </div>
        </div>

        <!-- Table Body -->
        <div class="containers-content-body" data-scrollable="true" style="flex: 1; min-height: 0; overflow-y: auto; -webkit-overflow-scrolling: touch; touch-action: pan-y; padding: 14px 16px;">
          <div class="cw-docker-table-wrap" style="overflow-x: auto; background: var(--lt-b-00000040, rgba(0,0,0,0.25)); border: 1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06)); border-radius: 8px;">
            <table class="copy-history-table docker-table responsive-cards">
              <thead>
                <tr>
                  <th class="cw-sortable-th" data-sort-col="name" role="columnheader" aria-sort="none" tabindex="0" title="${t('ui.click_to_sort_by_name', 'Click to sort by Name')}">
                    <input type="checkbox" id="cw-docker-select-all" title="${t('ui.select_all_containers', 'Select All Containers')}" style="margin: 0 6px 0 0; cursor: pointer; accent-color: var(--brand, #0ea5e9); vertical-align: middle;">
                    <span data-i18n="mgmt.tbl_name">${t('mgmt.tbl_name', 'Name')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="stack" role="columnheader" aria-sort="none" tabindex="0" title="${t('ui.click_to_sort_by_stack', 'Click to sort by Stack / Type')}">
                    <span data-i18n="mgmt.tbl_stack">${t('mgmt.tbl_stack', 'Stack / Type')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="hardware" role="columnheader" aria-sort="none" tabindex="0" title="${t('ui.click_to_sort_by_hardware', 'Click to sort by Hardware')}">
                    <span data-i18n="mgmt.tbl_hardware">${t('mgmt.tbl_hardware', 'Hardware')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="cpu" role="columnheader" aria-sort="none" tabindex="0" title="${t('ui.click_to_sort_by_cpu', 'Click to sort by CPU / RAM')}">
                    <span data-i18n="mgmt.tbl_telemetry">${t('mgmt.tbl_telemetry', 'CPU / RAM')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="ports" role="columnheader" aria-sort="none" tabindex="0" title="${t('ui.click_to_sort_by_ports', 'Click to sort by Ports & Web UI')}">
                    <span data-i18n="mgmt.tbl_ports">${t('mgmt.tbl_ports', 'Ports & Web UI')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th class="cw-sortable-th" data-sort-col="status" role="columnheader" aria-sort="none" tabindex="0" title="${t('ui.click_to_sort_by_status', 'Click to sort by Status & Uptime')}">
                    <span data-i18n="mgmt.tbl_uptime">${t('mgmt.tbl_uptime', 'Status & Uptime')}</span><span class="docker-sort-indicator" aria-hidden="true"></span>
                  </th>
                  <th style="text-align: right;" data-i18n="mgmt.tbl_actions">${t('mgmt.tbl_actions', 'Actions')}</th>
                </tr>
              </thead>
              <tbody id="cw-docker-containers-tbody">
                <tr><td colspan="7" style="text-align: center; color: var(--muted); padding: 24px;">Scanning Docker socket...</td></tr>
              </tbody>
            </table>
          </div>
          <!-- Sticky Bottom Horizontal Scrollbar (Sticky to viewport bottom) -->
          <div class="docker-table-sticky-scroll" id="cw-docker-table-sticky-scroll" style="display:none;" aria-label="${t('ui.horizontal_scrollbar_bottom', 'Horizontal scrollbar (bottom)')}" title="${t('ui.scroll_table_horizontally', 'Scroll table horizontally')}">
            <div class="docker-table-sticky-scroll-inner" id="cw-docker-table-sticky-scroll-inner"></div>
          </div>
          <div id="cw-docker-bulk-bar" class="docker-floating-bulk-bar" style="display: none;">
            <div class="bulk-bar-info">
              <span id="cw-docker-bulk-count" class="bulk-bar-count">0</span>
              <span>selected</span>
            </div>
            <div class="bulk-bar-actions">
              <button class="btn-bulk-action" data-bulk="start" title="${t('ui.start_selected_containers', 'Start selected containers')}">▶ Start</button>
              <button class="btn-bulk-action" data-bulk="stop" title="${t('ui.stop_selected_containers', 'Stop selected containers')}">⏹ Stop</button>
              <button class="btn-bulk-action" data-bulk="restart" title="${t('ui.restart_selected_containers', 'Restart selected containers')}">🔄 Restart</button>
              <button class="btn-bulk-action" data-bulk="pause" title="${t('ui.pause_selected_containers', 'Pause selected containers')}">⏸ Pause</button>
              <button class="btn-bulk-action" data-bulk="unpause" title="${t('ui.resume_selected_containers', 'Resume selected containers')}">⏵ Resume</button>
              <button class="btn-bulk-action btn-bulk-delete" data-bulk="delete" title="${t('ui.delete_selected_containers', 'Delete selected containers')}">🗑️ Delete</button>
              <button class="btn-bulk-action btn-bulk-cancel" data-bulk="cancel" title="${t('ui.deselect_all', 'Deselect all')}">✕</button>
            </div>
          </div>
          <div id="cw-docker-catalog-wrap" style="display: none; flex-direction: column; gap: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; background: var(--lt-b-00000040, rgba(0,0,0,0.25)); border: 1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06)); border-radius: 8px; padding: 10px 14px;">
              <div class="cw-catalog-filter-pills" style="display: flex; gap: 6px; flex-wrap: wrap;">
                <button class="btn-pill-toggle cw-cat-btn active" data-cat="all">All</button>
                <button class="btn-pill-toggle cw-cat-btn" data-cat="media">Media</button>
                <button class="btn-pill-toggle cw-cat-btn" data-cat="productivity">Productivity</button>
                <button class="btn-pill-toggle cw-cat-btn" data-cat="utilities">Utilities</button>
                <button class="btn-pill-toggle cw-cat-btn" data-cat="security">Security</button>
                <button class="btn-pill-toggle cw-cat-btn" data-cat="smart_home">Smart Home</button>
                <button class="btn-pill-toggle cw-cat-btn" data-cat="downloaders">Downloaders</button>
              </div>
              <div style="position: relative;">
                <input type="text" id="cw-catalog-search-input" placeholder="${t('ui.search_templates_apps_images', 'Search templates, apps, images...')}" class="tz-text-input" style="font-size: var(--zn-fs-xs); padding: 4px 10px; width: 220px; height: 26px; border-radius: 4px;">
              </div>
            </div>
            <div id="cw-catalog-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px;">
              <div style="text-align: center; color: var(--muted); padding: 24px; grid-column: 1 / -1;">Loading application catalog...</div>
            </div>
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
      stopCwAutoRefresh();
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
      stopCwAutoRefresh();
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

  const btnCheckUpdates = document.getElementById('btn-cw-check-updates');
  if (btnCheckUpdates) {
    btnCheckUpdates.onclick = async () => {
      btnCheckUpdates.disabled = true;
      const orig = btnCheckUpdates.innerHTML;
      btnCheckUpdates.innerHTML = '<span aria-hidden="true">⏳</span> <span>Checking...</span>';
      try {
        const res = await api.post('/api/docker/updates/check');
        _cwUpdatesCache = res;
        const count = res.updates_available_count || 0;
        updateCwUpdatesUI(count);
        if (count > 0) {
          showToast(t('toast.container_updates_available', 'Update check complete: {count} container update(s) available!', { count }), 'warn');
        } else {
          showToast(t('toast.all_containers_are_up_to_date', 'All containers are up to date!'), 'success');
        }
        await loadContainersData();
      } catch (err) {
        showToast(t('toast.update_check_failed', 'Update check failed: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.batch_container_update_initiated', 'Batch container update initiated...'), 'info');
          try {
            await api.post('/api/docker/updates/apply-all');
            showToast(t('toast.all_container_updates_dispatched', 'All container updates dispatched.'), 'success');
            await Promise.all([refreshCwUpdatesStatus(), loadContainersData()]);
            renderContainersWindowTable(_cwContainersList);
          } catch (err) {
            showToast(t('toast.batch_update_failed', 'Batch update failed: {error}', { error: err.message }), 'error');
          } finally {
            btnUpdateAll.disabled = false;
          }
        },
        null,
        { okText: '↑ Update All', cancelText: 'Cancel', isUpdate: true }
      );
    };
  }

  const btnNetmap = document.getElementById('btn-cw-netmap');
  if (btnNetmap) btnNetmap.onclick = () => openNetworkMap();

  const btnStacks = document.getElementById('btn-cw-stacks');
  if (btnStacks) {
    btnStacks.onclick = async () => {
      try {
        const res = await api.get('/api/docker/stacks');
        const stacks = Array.isArray(res) ? res : (res?.stacks || []);
        if (!stacks.length) {
          showToast(t('toast.no_active_compose_stacks_found', 'No active Compose stacks found.'), 'info');
        }
        openStackPickerModal(stacks);
      } catch (e) {
        showToast(t('toast.failed_to_load_compose_stacks', 'Failed to load Compose stacks: {message}', { message: e.message }), 'error');
        openStackPickerModal([]);
      }
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
      const tableWrap = containersWindow ? containersWindow.querySelector('.cw-docker-table-wrap') : null;
      const catalogWrap = document.getElementById('cw-docker-catalog-wrap');
      const searchWrap = containersWindow ? containersWindow.querySelector('.cw-docker-search-wrap') : null;
      const filterPills = containersWindow ? containersWindow.querySelector('.cw-docker-filter-pills') : null;

      _cwInCatalogView = !_cwInCatalogView;
      if (_cwInCatalogView) {
        if (tableWrap) tableWrap.style.display = 'none';
        if (catalogWrap) catalogWrap.style.display = 'flex';
        if (searchWrap) searchWrap.style.display = 'none';
        if (filterPills) filterPills.style.display = 'none';
        btnCatalog.innerHTML = `<span aria-hidden="true">🐳</span> <span>${t('apps.installed', 'Installed apps')}</span>`;
        if (_cwCatalogApps.length === 0) {
          loadCwCatalogData();
        } else {
          renderCwCatalogGrid();
        }
      } else {
        if (tableWrap) tableWrap.style.display = 'block';
        if (catalogWrap) catalogWrap.style.display = 'none';
        if (searchWrap) searchWrap.style.display = 'block';
        if (filterPills) filterPills.style.display = 'flex';
        btnCatalog.innerHTML = `<span aria-hidden="true">📦</span> <span>${t('apps.get_apps', 'Get apps')}</span>`;
      }
    };
  }

  // Catalog Category Filter Buttons
  const catBtns = containersWindow.querySelectorAll('.cw-cat-btn');
  catBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      catBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _cwCatalogCategory = btn.dataset.cat || 'all';
      renderCwCatalogGrid();
    });
  });

  // Catalog Search Input
  const catSearchInput = document.getElementById('cw-catalog-search-input');
  if (catSearchInput) {
    catSearchInput.addEventListener('input', (e) => {
      _cwCatalogSearch = (e.target.value || '').trim().toLowerCase();
      renderCwCatalogGrid();
    });
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
    th.addEventListener('click', (e) => {
      if (e.target.id === 'cw-docker-select-all' || e.target.closest('#cw-docker-select-all')) return;
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

  // Select All Containers Checkbox
  const selectAll = document.getElementById('cw-docker-select-all');
  if (selectAll) {
    selectAll.addEventListener('change', (e) => {
      e.stopPropagation();
      const tbody = document.getElementById('cw-docker-containers-tbody');
      if (!tbody) return;
      if (selectAll.checked) {
        // Only containers matching the current filter/search: a bulk delete must
        // never hit containers the user could not see.
        selectAllContainers(getCwFilteredContainerIds());
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
      updateCwBulkBar();
    });
  }

  // Floating Bulk Action Bar Buttons
  const bulkBar = document.getElementById('cw-docker-bulk-bar');
  if (bulkBar) {
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

  // Live Event Bus Subscriptions for instant reactive updates
  ZettEventBus.on('docker:action', () => {
    loadContainersData(true);
  });
  ZettEventBus.on('docker:containers:refresh', () => {
    loadContainersData(true);
  });
  ZettEventBus.on('docker:containers-updated', () => {
    loadContainersData(true);
  });
  ZettEventBus.on('stats:updated', (stats) => {
    if (!stats || !Array.isArray(stats.docker)) return;
    _cwLastSseAt = Date.now();
    if (!containersWindow) {
      containersWindow = document.getElementById('containers-manager-window');
    }
    if (!containersWindow) return;
    if (
      containersWindow.style.display === 'none' ||
      containersWindow.classList.contains('minimized') ||
      containersWindow.classList.contains('window-minimized')
    ) {
      return;
    }
    _cwContainersList = stats.docker;
    renderContainersWindowTable(_cwContainersList);
  });

  // Enable drag and bringToFront
  if (containersWindow) {
    makeDraggable(containersWindow, containersWindow.querySelector('.os-window-header'));
    containersWindow.addEventListener('mousedown', () => bringToFront(containersWindow));
  }
}

let _cwAutoRefreshTimer = null;
let _isCwAutoRefreshing = false;
let _cwAutoRefreshCount = 0;
let _cwLastSseAt = 0;

// Live container data arrives over SSE (stats:updated), so there is no REST poll.
// A slow watchdog refreshes update badges and falls back to HTTP only when the
// stream has gone quiet.
export const CW_WATCHDOG_MS = 15000;
export const CW_SSE_STALE_MS = 10000;
const CW_UPDATES_EVERY_TICKS = 4; // ~60 s

// An updated container is up to date at once: its badge and the Updates count drop now,
// then the server's list replaces this guess.
export function markCwContainerUpdated(name, id) {
  const map = _cwUpdatesCache?.containers;
  if (!map) return;
  let dropped = false;
  for (const key of [name, id]) {
    const entry = key && map[key];
    if (entry?.has_update) {
      entry.has_update = false;
      entry.status = 'up_to_date';
      dropped = true;
    }
  }
  if (dropped) {
    _cwUpdatesCache.updates_available_count = Math.max(0, (_cwUpdatesCache.updates_available_count || 1) - 1);
    updateCwUpdatesUI(_cwUpdatesCache.updates_available_count);
  }
}

export function _setCwUpdatesCacheForTesting(value) {
  _cwUpdatesCache = value;
}

export function refreshCwUpdatesStatus() {
  return api
    .get('/api/docker/updates/status')
    .then((res) => {
      _cwUpdatesCache = res;
      updateCwUpdatesUI(res?.updates_available_count || 0);
    })
    .catch(() => {});
}

export function startCwAutoRefresh() {
  if (_cwAutoRefreshTimer) return;
  refreshCwUpdatesStatus();
  _cwAutoRefreshTimer = setInterval(async () => {
    if (typeof document !== 'undefined' && document.hidden) return;
    if (!containersWindow) {
      containersWindow = document.getElementById('containers-manager-window');
    }
    if (!containersWindow) return;
    if (
      containersWindow.style.display === 'none' ||
      containersWindow.classList.contains('minimized') ||
      containersWindow.classList.contains('window-minimized')
    ) {
      return;
    }

    if (_isCwAutoRefreshing) return;
    _isCwAutoRefreshing = true;
    try {
      _cwAutoRefreshCount++;
      if (_cwAutoRefreshCount % CW_UPDATES_EVERY_TICKS === 0) {
        refreshCwUpdatesStatus();
      }
      if (Date.now() - _cwLastSseAt > CW_SSE_STALE_MS) {
        await loadContainersData(true);
      }
    } catch (e) {
      console.warn('CW watchdog refresh error:', e);
    } finally {
      _isCwAutoRefreshing = false;
    }
  }, CW_WATCHDOG_MS);
}

export function stopCwAutoRefresh() {
  if (_cwAutoRefreshTimer) {
    clearInterval(_cwAutoRefreshTimer);
    _cwAutoRefreshTimer = null;
  }
}

export function _resetCwAutoRefreshForTesting() {
  stopCwAutoRefresh();
  _isCwAutoRefreshing = false;
  _cwAutoRefreshCount = 0;
  _cwLastSseAt = 0;
  _cwContainersList = [];
  _cwUpdatesCache = null;
}

export function openContainersManager(opts = {}) {
  if (!containersWindow) {
    containersWindow = document.getElementById('containers-manager-window');
  }
  if (!containersWindow) return;
  const wantCatalog = opts && opts.view === 'catalog';
  const wantInstalled = opts && opts.view === 'installed';
  if ((wantCatalog && !_cwInCatalogView) || (wantInstalled && _cwInCatalogView)) {
    document.getElementById('btn-cw-catalog')?.click();
  }

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
  startCwAutoRefresh();
  loadContainersData();
}

export async function loadContainersData(isBackground = false) {
  try {
    const list = await api.get('/api/docker/containers').catch(() => []);
    _cwContainersList = Array.isArray(list) ? list : [];
    renderContainersWindowTable(_cwContainersList);
  } catch (err) {
    if (!isBackground || _cwContainersList.length === 0) {
      showToast(t('toast.failed_to_load_containers', 'Failed to load containers: {error}', { error: err.message }), 'error');
      const tbody = document.getElementById('cw-docker-containers-tbody');
      if (tbody && _cwContainersList.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--crit, #ef4444); padding:24px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
      }
    } else {
      console.warn('Silent cw background refresh error:', err);
    }
  }
}

export async function loadCwCatalogData() {
  const grid = document.getElementById('cw-catalog-grid');
  if (!grid) return;
  try {
    const res = await api.get('/api/docker/catalog');
    _cwCatalogApps = res.templates || res.apps || (Array.isArray(res) ? res : []);
    renderCwCatalogGrid();
  } catch (err) {
    if (grid) {
      grid.innerHTML = `<div style="text-align: center; color: var(--err, var(--lt-t-ef4444ff, #ef4444)); padding: 24px; grid-column: 1 / -1;">Failed to load catalog: ${escapeHtml(err.message)}</div>`;
    }
  }
}

export function renderCwCatalogGrid() {
  const grid = document.getElementById('cw-catalog-grid');
  if (!grid) return;
  const pills = document.querySelector('.cw-catalog-filter-pills');
  if (pills) {
    if (_cwCatalogCategory !== 'all' && !_cwCatalogApps.some((a) => (a.category || 'other') === _cwCatalogCategory)) _cwCatalogCategory = 'all';
    pills.innerHTML = catalogChipsHtml(_cwCatalogApps, _cwCatalogCategory, 'cw-cat-btn');
    bindCatalogChips(pills, '.cw-cat-btn', (cat) => {
      _cwCatalogCategory = cat;
      renderCwCatalogGrid();
    });
  }

  const filtered = filterCatalog(_cwCatalogApps, _cwCatalogCategory, _cwCatalogSearch);
  if (filtered.length === 0) {
    grid.innerHTML = emptyStateHtml({
      title: t('catalog.none_match', 'No apps match'),
      body: t('catalog.none_match_desc', 'Try another word, or show every category.'),
      action: { id: 'cw-catalog-clear-filters', label: t('catalog.show_all', 'Show all apps') },
    });
    grid.querySelector('#cw-catalog-clear-filters')?.addEventListener('click', () => {
      _cwCatalogSearch = '';
      _cwCatalogCategory = 'all';
      const input = document.getElementById('cw-catalog-search-input');
      if (input) input.value = '';
      renderCwCatalogGrid();
    });
    return;
  }
  grid.innerHTML = filtered.map((app) => catalogCardHtml(app, { installed: isInstalled(app, _cwContainersList) })).join('');

  grid.querySelectorAll('.btn-deploy-app').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const m = await import('./management.js');
      if (typeof m.openAppDeployModal === 'function') {
        m.openAppDeployModal(btn.dataset.appid);
      }
    });
  });
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
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:24px;">${t('mgmt.docker_none', 'No Docker containers detected or socket not connected.')}</td></tr>`;
    const cwStickyScroll = document.getElementById('cw-docker-table-sticky-scroll');
    if (cwStickyScroll) cwStickyScroll.style.display = 'none';
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
      } else if (_cwSortCol === 'stack') {
        va = (a.stack || (a.managed_by === 'unraid' ? 'Unraid' : 'Standalone')).toLowerCase();
        vb = (b.stack || (b.managed_by === 'unraid' ? 'Unraid' : 'Standalone')).toLowerCase();
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
      if (_cwSortCol === 'name') {
        const sa = (a.stack || '').toLowerCase();
        const sb = (b.stack || '').toLowerCase();
        if (sa < sb) return -1;
        if (sa > sb) return 1;
      } else if (_cwSortCol === 'stack') {
        const na = (a.name || '').toLowerCase();
        const nb = (b.name || '').toLowerCase();
        if (na < nb) return -1;
        if (na > nb) return 1;
      }
      return 0;
    });
  }

  if (filtered.length === 0) {
    _cwFilteredList = [];
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:24px;">${t('mgmt.docker_no_matching', 'No containers match your search or filter.')}</td></tr>`;
    const cwStickyScroll = document.getElementById('cw-docker-table-sticky-scroll');
    if (cwStickyScroll) cwStickyScroll.style.display = 'none';
    return;
  }

  const currentHost = typeof window !== 'undefined' && window.location.hostname ? window.location.hostname : 'localhost';

  // Clear the "no containers" placeholder row, but never the virtual spacer rows:
  // wiping those collapses the table and throws the scroll position to the top.
  const firstRow = tbody.firstElementChild;
  if (firstRow && !firstRow.classList.contains('cw-virtual-spacer') && firstRow.querySelector('td[colspan]')) {
    tbody.innerHTML = '';
  }

  bindCwTableEvents(tbody);

  renderCwRows(tbody, filtered, currentHost);

  updateCwBulkBar();

  const cwWrap = document.querySelector('.cw-docker-table-wrap');
  const cwStickyScroll = document.getElementById('cw-docker-table-sticky-scroll');
  if (cwWrap) {
    // One horizontal scrollbar, kept at the bottom edge of the window
    initSynchronizedTableScrollbars(cwWrap, null, cwStickyScroll);
  }
}


// ---- Large inventories: render only rows near the viewport ----
// Below CW_VIRTUALIZE_MIN_ROWS the table renders every row as before. Above it,
// spacer rows stand in for off-screen rows so the DOM stays small and the
// scrollbar keeps its size. Selection lives in docker-table.js, not in the DOM,
// so it survives rows scrolling out.
export const CW_VIRTUALIZE_MIN_ROWS = 60;
const CW_VIRTUAL_OVERSCAN = 8;
const CW_DEFAULT_ROW_PX = 52;
let _cwFilteredList = [];
let _cwRowHeight = 0;
let _cwLastWindow = '';
let _cwVirtualScrollTarget = null;
let _cwVirtualRafPending = false;

function cwScrollParent(el) {
  for (let p = el ? el.parentElement : null; p && p !== document.body; p = p.parentElement) {
    // overflow-x:auto (the table wrap) also computes overflow-y:auto, so only
    // accept an ancestor whose content actually overflows vertically.
    const oy = getComputedStyle(p).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight + 1) return p;
  }
  return null;
}

function cwVirtualRange(total, tbody) {
  const rowH = _cwRowHeight || CW_DEFAULT_ROW_PX;
  const scroller = cwScrollParent(tbody);
  const viewTop = scroller ? scroller.getBoundingClientRect().top : 0;
  const viewport = (scroller && scroller.clientHeight) || window.innerHeight || 800;
  const offset = Math.max(0, viewTop - tbody.getBoundingClientRect().top);
  const start = Math.max(0, Math.floor(offset / rowH) - CW_VIRTUAL_OVERSCAN);
  const end = Math.min(total, start + Math.ceil(viewport / rowH) + CW_VIRTUAL_OVERSCAN * 2);
  return { start, end, rowH };
}

function createCwSpacerRow(item) {
  const tr = document.createElement('tr');
  tr.className = 'cw-virtual-spacer';
  tr.setAttribute('aria-hidden', 'true');
  tr.innerHTML = '<td colspan="7" style="padding:0;border:0;"></td>';
  updateCwSpacerRow(tr, item);
  return tr;
}

function updateCwSpacerRow(tr, item) {
  const td = tr.firstElementChild;
  if (td) td.style.height = `${item.height}px`;
  tr.style.display = item.height > 0 ? '' : 'none';
}

function ensureCwVirtualScroll(tbody) {
  const target = cwScrollParent(tbody) || window;
  if (_cwVirtualScrollTarget === target) return;
  if (_cwVirtualScrollTarget) _cwVirtualScrollTarget.removeEventListener('scroll', onCwVirtualScroll);
  _cwVirtualScrollTarget = target;
  target.addEventListener('scroll', onCwVirtualScroll, { passive: true });
}

function onCwVirtualScroll() {
  if (_cwVirtualRafPending) return;
  _cwVirtualRafPending = true;
  requestAnimationFrame(() => {
    _cwVirtualRafPending = false;
    const tbody = document.getElementById('cw-docker-containers-tbody');
    if (!tbody || _cwFilteredList.length < CW_VIRTUALIZE_MIN_ROWS) return;
    const { start, end } = cwVirtualRange(_cwFilteredList.length, tbody);
    if (`${start}:${end}:${_cwFilteredList.length}` === _cwLastWindow) return;
    const currentHost = window.location.hostname || 'localhost';
    renderCwRows(tbody, _cwFilteredList, currentHost);
  });
}

function renderCwRows(tbody, filtered, currentHost) {
  _cwFilteredList = filtered;
  let items = filtered;
  if (filtered.length >= CW_VIRTUALIZE_MIN_ROWS) {
    ensureCwVirtualScroll(tbody);
    const { start, end, rowH } = cwVirtualRange(filtered.length, tbody);
    _cwLastWindow = `${start}:${end}:${filtered.length}`;
    items = [
      { __spacer: 'top', height: start * rowH },
      ...filtered.slice(start, end),
      { __spacer: 'bottom', height: (filtered.length - end) * rowH },
    ];
  } else {
    _cwLastWindow = '';
  }

  reconcileKeyedTable(
    tbody,
    items,
    (c) => (c.__spacer ? `__cw-spacer-${c.__spacer}` : c.id || c.name),
    (c) => (c.__spacer ? createCwSpacerRow(c) : createCwContainerRow(c, currentHost)),
    (tr, c) => (c.__spacer ? updateCwSpacerRow(tr, c) : updateCwContainerRow(tr, c, currentHost))
  );

  // Spacer maths uses the real row-to-row distance: it includes the gap between
  // the card rows on phones (flex layout), which a row's own height does not.
  const rows = tbody.querySelectorAll('tr:not(.cw-virtual-spacer)');
  if (rows.length > 1) {
    const first = rows[0].getBoundingClientRect().top;
    const last = rows[rows.length - 1].getBoundingClientRect().top;
    const stride = (last - first) / (rows.length - 1);
    if (stride > 0) _cwRowHeight = stride;
  } else if (rows.length === 1 && rows[0].offsetHeight > 0) {
    _cwRowHeight = rows[0].offsetHeight;
  }
  // The real scroller may only overflow once spacers exist; re-attach if so.
  if (filtered.length >= CW_VIRTUALIZE_MIN_ROWS) ensureCwVirtualScroll(tbody);
}

export function getCwFilteredContainerIds() {
  return _cwFilteredList.map((c) => c.id).filter(Boolean);
}

function buildCwContainerRowInner(c, currentHost) {
  const updateInfo = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
  return buildSharedContainerRowInner(c, currentHost, updateInfo);
}

function createCwContainerRow(c, currentHost) {
  const updateInfo = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
  return createSharedContainerRow(c, currentHost, updateInfo);
}

function updateCwContainerRow(tr, c, currentHost) {
  const updateInfo = _cwUpdatesCache?.containers?.[c.name] || _cwUpdatesCache?.containers?.[c.id];
  return updateSharedContainerRow(tr, c, currentHost, updateInfo);
}

function bindCwTableEvents(tbody) {
  if (tbody._cwTableEventsBound) return;
  tbody._cwTableEventsBound = true;

  tbody.addEventListener('change', (e) => {
    if (e.target.classList.contains('docker-row-select')) {
      const cid = e.target.dataset.id;
      toggleContainerSelected(cid, e.target.checked);
      const tr = e.target.closest('tr');
      if (tr) {
        if (e.target.checked) tr.classList.add('docker-row-selected');
        else tr.classList.remove('docker-row-selected');
      }
      updateCwBulkBar();
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
          `Pull the latest image and update <strong>${escapeHtml(cname)}</strong> to its newest release?<br><br><span style="font-size:var(--zn-fs-xs); color:var(--muted);">All volumes, persistent paths, and environment settings will be preserved intact.</span>`,
          async () => {
            actBtn.disabled = true;
            const originalContent = actBtn.innerHTML;
            actBtn.innerHTML = '⏳';
            showToast(t('toast.updating_to_latest_image', 'Updating "{cname}" to latest image...', { cname: cname }), 'info');
            try {
              await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/update-image`);
              showToast(t('toast.container_updated_and_restarted_successfully', 'Container "{cname}" updated and restarted successfully!', { cname: cname }), 'success');
              markCwContainerUpdated(cname, cid);
              await Promise.all([refreshCwUpdatesStatus(), loadContainersData()]);
              renderContainersWindowTable(_cwContainersList);
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
          loadContainersData();
        });
        return;
      }

      actBtn.disabled = true;
      actBtn.style.opacity = '0.5';
      showToast(t('toast.request_sent_for', '{act} request sent for {cname}...', { act: act.toUpperCase(), cname: cname }), 'info');

      try {
        await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: act });
        showToast(t('toast.container_successfully_ed', 'Container "{cname}" successfully {act}ed.', { cname: cname, act: act }), 'success');
        await loadContainersData();
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

export function updateCwBulkBar() {
  const bar = document.getElementById('cw-docker-bulk-bar');
  const countEl = document.getElementById('cw-docker-bulk-count');
  const selectAll = document.getElementById('cw-docker-select-all');
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
    const totalVisible = _cwContainersList.length;
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
    rerender: () => renderContainersWindowTable(),
    refresh: () => loadContainersData(),
    updateBar: updateCwBulkBar,
  });
}
