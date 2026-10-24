/**
 * Mission Control: Disk inventory table.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { ZettEventBus } from '../../event-bus.js';
import { triggerLocateDisk, getThermalLevel } from '../chassis-visualizer.js';
import { state } from '../../state.js';
import { api } from '../../api.js';
import { showToast, showConfirmToast, showBottomSheet } from '../../toast.js';
import { escapeHtml, reconcileKeyedTable } from '../../utils.js';
import { t } from '../../i18n.js';

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
      <div style="font-size:11px; color:var(--muted);">SN: ${escapeHtml(serialStr)}</div>
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
      <div style="display:inline-flex; gap:6px; align-items:center;">
        <button class="btn-pill-toggle btn-locate-row is-small" data-dev="${devName}" title="${t('ui.locate_drive_blink_bay_led', 'Locate Drive (Blink Bay LED)')}">⚡ Locate</button>
        <button class="btn-pill-toggle btn-smart-row is-small" data-dev="${devName}" title="${t('ui.view_s_m_a_r', 'View S.M.A.R.T. Diagnostics')}">📊 S.M.A.R.T.</button>
        <button type="button" class="btn-pill-toggle btn-disk-more-sheet is-small" data-dev="${devName}" title="${t('ui.more_actions', 'More Actions')}" style="display: none;">···</button>
      </div>
    </td>
  `;
}

export function computeDiskRowSignature(d) {
  const devName = d.dev || d.name || 'unknown';
  const modelStr = d.model || 'Generic Disk';
  const serialStr = d.serial && d.serial !== 'Unknown' ? d.serial : '--';
  const transportStr = (d.transport || (devName.startsWith('nvme') ? 'nvme' : 'sata')).toUpperCase();
  const driverStr = d.controller_driver || (devName.startsWith('nvme') ? 'nvme' : 'ahci');
  const sizeStr = d.size_formatted || d.size || '--';
  return `${devName}|${modelStr}|${serialStr}|${transportStr}|${driverStr}|${sizeStr}`;
}

function createDiskRow(d) {
  const devName = d.dev || d.name || 'unknown';
  const tr = document.createElement('tr');
  tr.dataset.key = devName;
  tr.dataset.dev = devName;
  tr.dataset.rowSig = computeDiskRowSignature(d);
  tr.innerHTML = buildDiskRowInner(d);
  return tr;
}

function updateDiskRow(row, d) {
  const newSig = computeDiskRowSignature(d);
  if (row.dataset.rowSig !== newSig) {
    row.dataset.rowSig = newSig;
    row.innerHTML = buildDiskRowInner(d);
    return;
  }

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
    const moreBtn = e.target.closest('.btn-disk-more-sheet');
    if (moreBtn) {
      e.stopPropagation();
      const dev = moreBtn.dataset.dev;
      const row = moreBtn.closest('tr');
      const modelText = row?.children?.[1]?.firstElementChild?.textContent?.trim() || 'Physical Disk';
      const healthText = row?.querySelector('.bay-health-tag')?.textContent?.trim() || 'OK';
      showBottomSheet({
        title: `/dev/${dev}`,
        subtitle: `${modelText} • ${healthText}`,
        items: [
          {
            icon: '📊',
            label: 'View S.M.A.R.T. Diagnostics',
            onClick: () => row?.querySelector('.btn-smart-row')?.click(),
          },
          {
            icon: '⚡',
            label: 'Locate Drive (Blink Bay LED)',
            onClick: () => row?.querySelector('.btn-locate-row')?.click(),
          },
        ],
      });
      return;
    }

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
            showToast(t('toast.waking_disk_dev_2', 'Waking disk /dev/{dev}...', { dev: dev }), 'info');
            ZettEventBus.emit('modal:smart:open', { dev, forceWake: true });
          }
        );
      } else {
        ZettEventBus.emit('modal:smart:open', dev);
      }
    }
  });
}
