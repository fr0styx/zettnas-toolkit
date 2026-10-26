/**
 * ZettNAS Toolkit - Docker Container Table Component & Keyed Reconciler
 * Unified container table row renderer and event binder for Containers Manager & Mission Control.
 * Conforms to AGENTS.md §1.3 (Keyed DOM Reconciliation & Row Dataset Invariant).
 */

import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

import { api } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';
let _selectedContainerIds = new Set();

export function getSelectedContainerIds() {
  return Array.from(_selectedContainerIds);
}

export function isContainerSelected(cid) {
  return _selectedContainerIds.has(cid);
}

export function toggleContainerSelected(cid, selected) {
  if (selected === undefined) {
    if (_selectedContainerIds.has(cid)) _selectedContainerIds.delete(cid);
    else _selectedContainerIds.add(cid);
  } else if (selected) {
    _selectedContainerIds.add(cid);
  } else {
    _selectedContainerIds.delete(cid);
  }
}

export function clearSelectedContainers() {
  _selectedContainerIds.clear();
}

export function selectAllContainers(containerIds) {
  for (const id of containerIds) {
    if (id) _selectedContainerIds.add(id);
  }
}

/**
 * Computes a deterministic string signature representing the dynamic state of a container row.
 * Used by updateContainerRow to verify if tr.innerHTML must be re-rendered without a full page reload.
 */
export function computeContainerRowSignature(c, updateInfo) {
  const hasUpdate = updateInfo?.has_update ? '1' : '0';
  const portsSig = (c.ports || []).map((p) => `${p.public_port || ''}:${p.private_port || ''}`).join(',');
  const hwSig = (c.hardware_badges || []).map((b) => b.id || '').join(',');
  const stack = c.stack || '';
  const image = c.image || '';
  return `${c.id || ''}|${c.name || ''}|${c.state || ''}|${hasUpdate}|${c.primary_port || ''}|${portsSig}|${hwSig}|${stack}|${image}`;
}

/**
 * Generates the inner HTML for a container row (7 columns: Name, Stack, Hardware, CPU/RAM, Ports, Status, Actions).
 */
export function buildContainerRowInner(c, currentHost, updateInfo = null) {
  const isRunning = c.state === 'running';
  const badgeColor = isRunning ? 'var(--ok2)' : 'var(--muted)';
  const badgeBg = isRunning ? 'rgba(37, 194, 160, 0.15)' : 'rgba(255, 255, 255, 0.05)';
  const idShort = c.id ? c.id.slice(0, 12) : '';
  const isChecked = _selectedContainerIds.has(c.id);
  const checkedAttr = isChecked ? 'checked' : '';

  // Column 2: Stack & Type
  let stackHtml;
  if (c.stack) {
    stackHtml = `<span class="docker-stack-pill clickable-stack-pill" data-stack="${escapeHtml(c.stack)}" title="Open & Edit Stack: ${escapeHtml(c.stack)}" style="cursor:pointer;">📁 ${escapeHtml(c.stack)}</span>`;
  } else {
    const originLabel = c.managed_by === 'unraid' ? 'Unraid' : 'Standalone';
    stackHtml = `<span class="docker-origin-pill">${originLabel}</span>`;
  }

  // Column 3: Hardware Badges
  let hwHtml = '<span style="color:var(--muted); font-size:var(--zn-fs-xs);">—</span>';
  if (c.hardware_badges && c.hardware_badges.length > 0) {
    hwHtml = c.hardware_badges
      .map(
        (b) =>
          `<span class="docker-hw-badge docker-hw-${escapeHtml(b.id)}" title="${escapeHtml(b.label)}">${escapeHtml(b.label)}</span>`
      )
      .join('');
  }

  // Column 4: Telemetry (CPU / RAM)
  let telemHtml = '<span style="color:var(--muted); font-size:var(--zn-fs-xs);">—</span>';
  if (isRunning) {
    const cpuStr = `${(c.cpu_pct || 0).toFixed(1)}%`;
    const memStr = c.mem_used ? `${(c.mem_used / (1024 * 1024)).toFixed(0)} MB` : '--';
    telemHtml = `<span class="docker-telemetry-pill"><span class="telem-cpu">${cpuStr}</span><span style="opacity:0.4;">•</span><span class="telem-mem">${memStr}</span></span>`;
  }

  // Column 5: Ports & Web UI
  let portsHtml = '<span style="color:var(--muted); font-size:var(--zn-fs-xs);">—</span>';
  const portParts = [];
  if (c.webui_url && c.primary_port) {
    const resolvedUrl = c.webui_url.replace('[HOST]', currentHost);
    if (/^https?:\/\//i.test(resolvedUrl)) {
      portParts.push(
        `<a href="${escapeHtml(resolvedUrl)}" target="_blank" rel="noopener noreferrer" class="btn-webui-badge" title="Open Web UI (Port ${escapeHtml(String(c.primary_port))})">🌐 :${escapeHtml(String(c.primary_port))} ↗</a>`
      );
    }
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

  // Column 6: Status & Uptime
  const statusHtml = `
    <div style="display:flex; align-items:center; gap:6px;">
      <span class="docker-state-badge" style="display:inline-block; padding:2px 6px; border-radius:4px; font-size:var(--zn-fs-xs); font-weight:700; background:${badgeBg}; color:${badgeColor}; text-transform:uppercase;">${escapeHtml(c.state)}</span>
      <span class="docker-status-text" style="font-size:var(--zn-fs-xs); color:var(--zn-text-soft); max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
    </div>
  `;

  // Column 7: Actions
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
  const backupBtn = `<button class="btn-container-act btn-docker-backup" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="backup" title="${t('ui.backup_app_data_config', 'Backup App Data & Config')}">💾</button>`;
  const deleteBtn = `<button class="btn-container-act btn-docker-delete" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-image="${escapeHtml(c.image || '')}" data-action="delete" title="Destroy / Delete ${escapeHtml(c.name)}">🗑️</button>`;
  const moreBtn = `<button class="btn-container-act btn-docker-more-sheet" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="more-sheet" title="${t('ui.more_actions', 'More Actions')}">···</button>`;
  const actions = isRunning
    ? `
      ${inspectBtn}
      ${editBtn}
      ${stackBtn}
      ${updateBtn}
      ${backupBtn}
      <button class="btn-container-act btn-docker-restart" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="restart" title="Restart ${escapeHtml(c.name)}">🔄</button>
      <button class="btn-container-act btn-docker-stop" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="stop" title="Stop ${escapeHtml(c.name)}"><svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="1.5" y="1.5" width="13" height="13" rx="2.5"/></svg></button>
      ${deleteBtn}
      ${moreBtn}
    `
    : `
      ${inspectBtn}
      ${editBtn}
      ${stackBtn}
      ${updateBtn}
      ${backupBtn}
      <button class="btn-container-act btn-docker-start" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="start" title="Start ${escapeHtml(c.name)}"><svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4 2.8v10.4c0 .7.8 1.1 1.4.8l8.4-5.2c.6-.4.6-1.2 0-1.6L5.4 2c-.6-.4-1.4 0-1.4.8z"/></svg></button>
      ${deleteBtn}
      ${moreBtn}
    `;

  return `
    <td class="docker-name-cell">
      <div style="display:flex; align-items:center; gap:6px;">
        <input type="checkbox" class="docker-row-select" data-id="${escapeHtml(c.id)}" ${checkedAttr} title="Select ${escapeHtml(c.name)}" style="margin:0; cursor:pointer; accent-color:var(--brand, #0ea5e9); flex-shrink:0;">
        <button class="btn-docker-name-link clickable-container-name" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" style="background:none; border:none; padding:0; color:var(--zn-text-strong); font-size:var(--zn-fs-xs); font-weight:700; cursor:pointer; text-align:left; font-family:inherit;" title="Inspect ${escapeHtml(c.name)}">${escapeHtml(c.name)}</button>
        <code style="font-size:var(--zn-fs-xs); color:var(--muted); font-family:var(--font-mono, monospace);">${escapeHtml(idShort)}</code>
        ${updateBadge}
      </div>
    </td>
    <td class="docker-stack-cell">${stackHtml}</td>
    <td class="docker-hw-cell">${hwHtml}</td>
    <td class="docker-telemetry-cell">${telemHtml}</td>
    <td class="docker-ports-cell">${portsHtml}</td>
    <td class="docker-status-cell">${statusHtml}</td>
    <td class="docker-actions-cell" style="text-align:right; white-space:nowrap;"><div class="docker-actions-btn-group">${actions}</div></td>
  `;
}

/**
 * Creates a brand new <tr> container row element conforming to AGENTS.md §1.3.
 */
export function createContainerRow(c, currentHost, updateInfo = null) {
  const tr = document.createElement('tr');
  const key = c.id || c.name || '';
  tr.dataset.key = key;
  tr.dataset.id = c.id || '';
  tr.dataset.name = c.name || '';
  tr.dataset.state = c.state || '';
  const hasUpdate = updateInfo?.has_update ? '1' : '0';
  tr.dataset.hasUpdate = hasUpdate;
  tr.dataset.rowSig = computeContainerRowSignature(c, updateInfo);
  tr.innerHTML = buildContainerRowInner(c, currentHost, updateInfo);
  if (_selectedContainerIds.has(c.id)) {
    tr.classList.add('docker-row-selected');
  }
  return tr;
}

/**
 * Updates an existing <tr> row element in place, honoring AGENTS.md §1.3.
 */
export function updateContainerRow(tr, c, currentHost, updateInfo = null) {
  const hasUpdate = Boolean(updateInfo?.has_update);
  const prevHasUpdate = tr.dataset.hasUpdate === '1';
  const newSig = computeContainerRowSignature(c, updateInfo);

  tr.dataset.id = c.id || '';
  tr.dataset.name = c.name || '';

  // Synchronize selection state on the row
  const isChecked = _selectedContainerIds.has(c.id);
  const chk = tr.querySelector('.docker-row-select');
  if (chk && chk.checked !== isChecked) {
    chk.checked = isChecked;
  }
  if (isChecked) {
    tr.classList.add('docker-row-selected');
  } else {
    tr.classList.remove('docker-row-selected');
  }

  // Check state and signature invariants
  if (
    tr.dataset.state !== c.state ||
    prevHasUpdate !== hasUpdate ||
    tr.dataset.rowSig !== newSig ||
    !tr.children.length
  ) {
    tr.dataset.state = c.state || '';
    tr.dataset.hasUpdate = hasUpdate ? '1' : '0';
    tr.dataset.rowSig = newSig;
    tr.innerHTML = buildContainerRowInner(c, currentHost, updateInfo);
    if (isChecked) {
      tr.classList.add('docker-row-selected');
    }
    return;
  }

  // Fast-path in-place telemetry update if inner HTML is already stable
  const isRunning = c.state === 'running';
  const telemCell = tr.querySelector('.docker-telemetry-cell');
  if (telemCell) {
    if (isRunning) {
      const cpuStr = `${(c.cpu_pct || 0).toFixed(1)}%`;
      const memStr = c.mem_used ? `${(c.mem_used / (1024 * 1024)).toFixed(0)} MB` : '--';
      const cpuEl = telemCell.querySelector('.telem-cpu');
      const memEl = telemCell.querySelector('.telem-mem');
      if (cpuEl && memEl) {
        if (cpuEl.textContent !== cpuStr) cpuEl.textContent = cpuStr;
        if (memEl.textContent !== memStr) memEl.textContent = memStr;
      } else {
        telemCell.innerHTML = `<span class="docker-telemetry-pill"><span class="telem-cpu">${cpuStr}</span><span style="opacity:0.4;">•</span><span class="telem-mem">${memStr}</span></span>`;
      }
    } else {
      telemCell.innerHTML = '<span style="color:var(--muted); font-size:var(--zn-fs-xs);">—</span>';
    }
  }

  const statusText = tr.querySelector('.docker-status-text');
  if (statusText && statusText.textContent !== c.status) {
    statusText.textContent = c.status;
    statusText.title = c.status;
  }
}

/**
 * Synchronizes horizontal scrolling between a table container and auxiliary top/bottom scrollbars.
 * Ensures that users at the top of long container lists immediately see and can use horizontal scrollbars.
 */
export function initSynchronizedTableScrollbars(tableWrapEl, topScrollEl, stickyScrollEl) {
  if (!tableWrapEl) return { update: () => {}, destroy: () => {} };

  if (tableWrapEl._syncScrollbarsController) {
    tableWrapEl._syncScrollbarsController.update();
    return tableWrapEl._syncScrollbarsController;
  }

  const topInner = topScrollEl ? topScrollEl.querySelector('.docker-table-top-scroll-inner') || topScrollEl.firstElementChild : null;
  const stickyInner = stickyScrollEl ? stickyScrollEl.querySelector('.docker-table-sticky-scroll-inner') || stickyScrollEl.firstElementChild : null;

  let isSyncing = false;
  let rafId = null;

  function update() {
    const table = tableWrapEl.querySelector('table');
    if (!table) return;

    const scrollWidth = Math.max(table.scrollWidth || 0, table.offsetWidth || 0, tableWrapEl.scrollWidth || 0);
    const clientWidth = tableWrapEl.clientWidth || 0;
    const needsScroll = clientWidth > 0 && scrollWidth > clientWidth + 3;

    if (topScrollEl && topInner) {
      if (needsScroll) {
        topInner.style.width = `${scrollWidth}px`;
        topScrollEl.style.display = 'block';
        topScrollEl.scrollLeft = tableWrapEl.scrollLeft;
      } else {
        topScrollEl.style.display = 'none';
      }
    }

    if (stickyScrollEl && stickyInner) {
      if (needsScroll) {
        stickyInner.style.width = `${scrollWidth}px`;
        stickyScrollEl.style.display = 'block';
        stickyScrollEl.scrollLeft = tableWrapEl.scrollLeft;
      } else {
        stickyScrollEl.style.display = 'none';
      }
    }
  }

  const syncFrom = (source, targets) => {
    if (isSyncing) return;
    isSyncing = true;
    const pos = source.scrollLeft;
    for (const t of targets) {
      if (t && t.scrollLeft !== pos) {
        t.scrollLeft = pos;
      }
    }
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      isSyncing = false;
    });
  };

  const onTableScroll = () => syncFrom(tableWrapEl, [topScrollEl, stickyScrollEl]);
  const onTopScroll = () => {
    if (topScrollEl) syncFrom(topScrollEl, [tableWrapEl, stickyScrollEl]);
  };
  const onStickyScroll = () => {
    if (stickyScrollEl) syncFrom(stickyScrollEl, [tableWrapEl, topScrollEl]);
  };

  tableWrapEl.addEventListener('scroll', onTableScroll, { passive: true });
  if (topScrollEl) topScrollEl.addEventListener('scroll', onTopScroll, { passive: true });
  if (stickyScrollEl) stickyScrollEl.addEventListener('scroll', onStickyScroll, { passive: true });

  let resizeObserver = null;
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      update();
    });
    resizeObserver.observe(tableWrapEl);
    const table = tableWrapEl.querySelector('table');
    if (table) resizeObserver.observe(table);
  }

  // Initial update
  update();

  const controller = {
    update,
    destroy() {
      tableWrapEl.removeEventListener('scroll', onTableScroll);
      if (topScrollEl) topScrollEl.removeEventListener('scroll', onTopScroll);
      if (stickyScrollEl) stickyScrollEl.removeEventListener('scroll', onStickyScroll);
      if (resizeObserver) resizeObserver.disconnect();
      if (rafId) cancelAnimationFrame(rafId);
      delete tableWrapEl._syncScrollbarsController;
    },
  };

  tableWrapEl._syncScrollbarsController = controller;
  return controller;
}


/**
 * Bulk start/stop/restart/delete for the selected containers, shared by Mission Control
 * and the Containers window (FE-12). `view` tells it how to redraw that view:
 * { rerender(), refresh(), updateBar() }.
 */
export async function runBulkContainerAction(action, view) {
  const selectedIds = getSelectedContainerIds();
  if (selectedIds.length === 0) {
    showToast(t('toast.no_containers_selected', 'No containers selected.'), 'info');
    return;
  }
  if (action === 'cancel') {
    clearSelectedContainers();
    view.rerender();
    view.updateBar();
    return;
  }
  const run = () => _runBulk(action, selectedIds, view);
  const count = selectedIds.length;
  if (action === 'delete') {
    showConfirmToast(
      t('docker.bulk_delete_title', 'Delete {count} containers', { count }),
      t('docker.bulk_delete_confirm', 'Permanently delete the {count} selected containers? This cannot be undone.', { count }),
      run,
      null,
      { okText: t('docker.bulk_delete_ok', 'Delete'), cancelText: t('common.cancel', 'Cancel') }
    );
    return;
  }
  if (action === 'stop') {
    showConfirmToast(
      t('docker.bulk_stop_title', 'Stop {count} containers', { count }),
      t('docker.bulk_stop_confirm', 'Stop the {count} selected containers?', { count }),
      run,
      null,
      { okText: t('docker.bulk_stop_ok', 'Stop'), cancelText: t('common.cancel', 'Cancel') }
    );
    return;
  }
  await run();
}

async function _runBulk(action, selectedIds, view) {
  try {
    showToast(t('toast.executing_bulk_on_containers', 'Executing bulk {action} on {count} containers...', { action, count: selectedIds.length }), 'info');
    const res = await api.post('/api/docker/containers/bulk-action', {
      action,
      container_ids: selectedIds,
      force: action === 'delete',
    });
    const successful = res.successful || 0;
    const total = res.total || selectedIds.length;
    showToast(t('toast.bulk_of_succeeded', 'Bulk {action}: {successful} of {total} succeeded.', { action, successful, total }), successful === total ? 'success' : 'warn');
    clearSelectedContainers();
    await view.refresh();
    view.updateBar();
  } catch (err) {
    showToast(t('toast.bulk_failed', 'Bulk {action} failed: {error}', { action, error: err.message }), 'error');
  }
}
