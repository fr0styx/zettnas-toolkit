/**
 * ZettNAS Toolkit - Docker Container Table Component & Keyed Reconciler
 * Unified container table row renderer and event binder for Containers Manager & Mission Control.
 * Conforms to AGENTS.md §1.3 (Keyed DOM Reconciliation & Row Dataset Invariant).
 */

import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

/**
 * Computes a deterministic string signature representing the dynamic state of a container row.
 * Used by updateContainerRow to verify if tr.innerHTML must be re-rendered without a full page reload.
 */
export function computeContainerRowSignature(c, updateInfo) {
  const hasUpdate = updateInfo?.has_update ? '1' : '0';
  const portsSig = (c.ports || []).map((p) => `${p.public_port || ''}:${p.private_port || ''}`).join(',');
  const hwSig = (c.hardware_badges || []).map((b) => b.id || '').join(',');
  const cpuVal = (c.cpu_pct || 0).toFixed(1);
  const memVal = c.mem_used || 0;
  return `${c.id || ''}|${c.name || ''}|${c.state || ''}|${c.status || ''}|${hasUpdate}|${cpuVal}|${memVal}|${c.primary_port || ''}|${portsSig}|${hwSig}`;
}

/**
 * Generates the inner HTML for a container row (6 columns).
 */
export function buildContainerRowInner(c, currentHost, updateInfo = null) {
  const isRunning = c.state === 'running';
  const badgeColor = isRunning ? 'var(--ok2)' : 'var(--muted)';
  const badgeBg = isRunning ? 'rgba(37, 194, 160, 0.15)' : 'rgba(255, 255, 255, 0.05)';
  const idShort = c.id ? c.id.slice(0, 12) : '';

  // Column 1: Stack & Name
  let stackHtml = '';
  if (c.stack) {
    stackHtml = `<span class="docker-stack-pill clickable-stack-pill" data-stack="${escapeHtml(c.stack)}" title="Open & Edit Stack: ${escapeHtml(c.stack)}" style="cursor:pointer;">📁 ${escapeHtml(c.stack)}</span>`;
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

  // Column 5: Status & Uptime
  const statusHtml = `
    <div style="display:flex; align-items:center; gap:6px;">
      <span class="docker-state-badge" style="display:inline-block; padding:2px 6px; border-radius:4px; font-size:9.5px; font-weight:700; background:${badgeBg}; color:${badgeColor}; text-transform:uppercase;">${escapeHtml(c.state)}</span>
      <span class="docker-status-text" style="font-size:10px; color:#cbd5e1; max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
    </div>
  `;

  // Column 6: Actions
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
    <td class="docker-name-cell">
      <div style="display:flex; align-items:baseline; gap:6px;">
        <button class="btn-docker-name-link clickable-container-name" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" style="background:none; border:none; padding:0; color:#fff; font-size:11.5px; font-weight:700; cursor:pointer; text-align:left; font-family:inherit;" title="Inspect ${escapeHtml(c.name)}">${escapeHtml(c.name)}</button>
        <code style="font-size:9px; color:var(--muted); font-family:var(--font-mono, monospace);">${escapeHtml(idShort)}</code>
        ${updateBadge}
      </div>
      <div>${stackHtml}</div>
    </td>
    <td class="docker-hw-cell">${hwHtml}</td>
    <td class="docker-telemetry-cell">${telemHtml}</td>
    <td class="docker-ports-cell">${portsHtml}</td>
    <td class="docker-status-cell">${statusHtml}</td>
    <td class="docker-actions-cell" style="text-align:right; white-space:nowrap;">${actions}</td>
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
