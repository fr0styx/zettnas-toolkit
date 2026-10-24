/**
 * Mission Control: Backup tasks, pool snapshots, app backups.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { api } from '../../api.js';
import { showToast, showConfirmToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { formatDateTime } from '../../format.js';
import { emptyStateHtml } from '../empty-state.js';
import { openSnapshotBrowser, renderSnapshotSchedules } from '../snapshot-browser.js';
import { renderOffsite } from '../offsite-backup.js';

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
      mount.innerHTML = emptyStateHtml({
        icon: '🛡️',
        title: t('backup.none_title', 'No backups scheduled'),
        body: t('backup.none_desc', 'A backup copies your files somewhere else on a schedule, so a failed disk, ransomware or a mistaken delete is not the end of them.'),
        action: { target: 'btn-open-create-backup-job', label: t('backup.none_action', 'Schedule a backup') },
      });
      return;
    }

    const rowsHtml = jobs.map(job => {
      const isRemote = job.destination_type === 'remote';
      const isSettings = job.kind === 'config';
      const destBadge = isRemote
        ? `<span class="badge" style="background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid rgba(14,165,233,0.3); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">☁️ ${escapeHtml(job.remote_name || 'Cloud')}:${escapeHtml(job.remote_path || '')}</span>`
        : job.destination_type === 'local_folder'
          ? `<span class="badge" style="background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">📁 ${escapeHtml(job.local_path || '')}</span>`
          : `<span class="badge" style="background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">📸 Local Snapshot</span>`;

      const schedBadge = `<span class="badge" style="background: rgba(255,255,255,0.06); color: #cbd5e1; font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; text-transform: capitalize;">${escapeHtml(job.schedule || 'daily')}</span>`;
      
      let statusHtml;
      if (job.last_status === 'running') {
        statusHtml = `<span style="display:inline-flex; align-items:center; gap:4px; color: #38bdf8; font-size: var(--zn-fs-xs);"><span class="spinner-inline" style="width:10px; height:10px;"></span> Running...</span>`;
      } else if (job.last_status === 'success') {
        statusHtml = `<span style="color: #34d399; font-size: var(--zn-fs-xs); font-weight:600;">✓ Success</span>`;
      } else if (job.last_status === 'error') {
        statusHtml = `<span style="color: #f43f5e; font-size: var(--zn-fs-xs); font-weight:600;" title="${escapeHtml(job.last_error || '')}">⚠ Failed</span>`;
      } else {
        statusHtml = `<span style="color: var(--muted); font-size: var(--zn-fs-xs);">Idle</span>`;
      }

      const lastRunStr = formatDateTime(job.last_run_at, undefined, t('common.never', 'Never'));

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: var(--zn-fs-sm);">
          <td style="padding: 10px 12px; font-weight: 600; color: #fff;">
            <div>${escapeHtml(job.name)}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); font-weight: normal;">${isSettings
              ? escapeHtml(t('backup.kind_config_source', 'ZettNAS settings (encrypted)'))
              : `Subvolume: <code>${escapeHtml(job.source_subvolume || '@shares')}</code>`}</div>
          </td>
          <td style="padding: 10px 12px;">${destBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
              ${schedBadge}
              <span style="font-size: var(--zn-fs-xs); color: var(--muted);">Keep ${job.retention_count || 7}</span>
            </div>
          </td>
          <td style="padding: 10px 12px;">
            <div>${statusHtml}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${lastRunStr}</div>
          </td>
          <td style="padding: 10px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect primary btn-run-backup-job" data-job-id="${escapeHtml(job.id)}" title="${t('ui.run_backup_job_now', 'Run Backup Job Now')}">
                ▶ Run
              </button>
              <button class="btn-rect danger btn-delete-backup-job" data-job-id="${escapeHtml(job.id)}" title="${t('ui.delete_backup_job', 'Delete Backup Job')}">
                🗑️
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
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: var(--zn-fs-xs); font-weight: 800; color: var(--muted); text-transform: uppercase;">
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
          showToast(t('toast.triggering_backup_pipeline', 'Triggering backup pipeline {jobId}...', { jobId: jobId }), 'info');
          await api.post(`/api/backup/schedule/${jobId}/run`);
          showToast(t('toast.backup_pipeline_completed_successfully', `Backup pipeline completed successfully!`), 'success');
          fetchAndRenderBackupJobs(mount);
        } catch (err) {
          showToast(t('toast.backup_run_failed', 'Backup run failed: {error}', { error: err.message }), 'error');
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
            showToast(t('toast.backup_task_removed', 'Backup task removed.'), 'success');
            fetchAndRenderBackupJobs(mount);
          } catch (err) {
            showToast(t('toast.failed_to_delete_job', 'Failed to delete job: {error}', { error: err.message }), 'error');
          }
        });
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: var(--zn-fs-sm);">Failed to load backup jobs: ${escapeHtml(err.message)}</div>`;
  }
}

// =========================================================================
// Storage Pool Snapshots & Revert
// =========================================================================

export async function fetchAndRenderSystemSnapshots(mountEl) {
  const mount = mountEl || document.getElementById('system-snapshots-mount');
  if (!mount) return;
  renderSnapshotSchedules(document.getElementById('snapshot-schedules-mount'));
  renderOffsite(document.getElementById('offsite-backup-mount'));

  try {
    const data = await api.get('/api/backup/snapshots');
    const snaps = (data && data.snapshots) || [];

    if (snaps.length === 0) {
      mount.innerHTML = emptyStateHtml({
        compact: true,
        title: t('backup.snap_none_title', 'No snapshots yet'),
        body: t('backup.snap_none_desc', 'A snapshot freezes a folder as it is now, in seconds, so you can go back to it later.'),
        action: { target: 'btn-take-snapshot-submit', label: t('backup.snap_take', 'Take a snapshot') },
      });
      return;
    }

    const rowsHtml = snaps.map(s => {
      const createdDate = formatDateTime(s.created_at, undefined, 'N/A');
      const poolId = s.pool_id || 'default';
      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: var(--zn-fs-sm);">
          <td style="padding: 8px 12px; font-weight: 600; color: #fff;">
            <span style="font-family: monospace;">📸 ${escapeHtml(s.name)}</span>
          </td>
          <td style="padding: 8px 12px; color: var(--muted); font-size: var(--zn-fs-xs);">
            ${escapeHtml(s.path || '')}
          </td>
          <td style="padding: 8px 12px; color: var(--muted); font-size: var(--zn-fs-xs);">
            ${createdDate}
          </td>
          <td style="padding: 8px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect btn-sys-browse-snap" data-snap-name="${escapeHtml(s.name)}" title="${t('snap.browse', 'Browse and restore files')}">
                <svg class="ic" aria-hidden="true"><use href="#i-storage"/></svg> ${t('snap.browse_short', 'Files')}
              </button>
              <button class="btn-rect btn-sys-restore-snap" data-snap-name="${escapeHtml(s.name)}" data-pool-id="${escapeHtml(poolId)}" title="${t('ui.rollback_to_this_snapshot', 'Rollback to this snapshot')}">
                ⏪ Restore
              </button>
              <button class="btn-rect danger btn-sys-delete-snap" data-snap-name="${escapeHtml(s.name)}" data-pool-id="${escapeHtml(poolId)}" title="${t('ui.delete_snapshot', 'Delete Snapshot')}">
                🗑️
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
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: var(--zn-fs-xs); font-weight: 800; color: var(--muted); text-transform: uppercase;">
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

    mount.querySelectorAll('.btn-sys-browse-snap').forEach((btn) => {
      btn.addEventListener('click', () => openSnapshotBrowser(btn.dataset.snapName));
    });

    mount.querySelectorAll('.btn-sys-restore-snap').forEach(btn => {
      btn.addEventListener('click', () => {
        const snapName = btn.dataset.snapName;
        const poolId = btn.dataset.poolId || 'default';
        showConfirmToast(`Roll back to snapshot "${snapName}"? Existing subvolume will be archived safely.`, async () => {
          try {
            showToast(t('toast.restoring_snapshot', 'Restoring snapshot {snapName}...', { snapName: snapName }), 'info');
            await api.post('/api/backup/restore-snapshot', {
              pool_id: poolId,
              snapshot_name: snapName,
            });
            showToast(t('toast.snapshot_successfully_restored', 'Snapshot "{snapName}" successfully restored!', { snapName: snapName }), 'success');
            fetchAndRenderSystemSnapshots(mount);
          } catch (err) {
            showToast(t('toast.restore_failed', 'Restore failed: {error}', { error: err.message }), 'error');
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
            await api.delete(`/api/backup/snapshots/${encodeURIComponent(poolId)}/${encodeURIComponent(snapName)}`, { confirmed: true });
            showToast(t('toast.snapshot_deleted', 'Snapshot "{snapName}" deleted.', { snapName: snapName }), 'success');
            fetchAndRenderSystemSnapshots(mount);
          } catch (err) {
            showToast(t('toast.failed_to_delete_snapshot', 'Failed to delete snapshot: {error}', { error: err.message }), 'error');
          }
        });
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: var(--zn-fs-sm);">Failed to load snapshots: ${escapeHtml(err.message)}</div>`;
  }
}

// =========================================================================
// Application Backups & Recovery (Per-App & Box-Wide)
// =========================================================================

export async function fetchAndRenderAppBackups(mountEl, filterApp = '') {
  const mount = mountEl || document.getElementById('app-backups-mount');
  if (!mount) return;

  try {
    const url = `/api/backup/apps${filterApp ? `?app_name=${encodeURIComponent(filterApp)}` : ''}`;
    const data = await api.get(url);
    const backups = Array.isArray(data) ? data : (data?.backups || []);

    // Update filter dropdown options if element exists and not currently active
    const filterSelect = document.getElementById('app-backups-filter-app');
    if (filterSelect && (!filterApp || filterSelect.options.length <= 1)) {
      const currentVal = filterSelect.value || filterApp;
      const allData = filterApp ? await api.get('/api/backup/apps') : data;
      const allBackups = Array.isArray(allData) ? allData : (allData?.backups || []);
      const appNames = Array.from(new Set(allBackups.map(b => b.container_name).filter(Boolean))).sort();
      
      filterSelect.innerHTML = `<option value="">All Applications (Box-Wide)</option>` +
        appNames.map(name => `<option value="${escapeHtml(name)}" ${name === currentVal ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
    }

    if (backups.length === 0) {
      mount.innerHTML = emptyStateHtml({
        icon: '📦',
        title: t('backup.app_none_title', 'No app backups yet'),
        body: filterApp
          ? t('backup.app_none_for', 'No backups recorded for {app}.', { app: filterApp })
          : t('backup.app_none_desc', 'An app backup is made when you remove an app with "keep a backup" ticked, or from an app\'s details with Back up now.'),
      });
      return;
    }

    const rowsHtml = backups.map(b => {
      const isUninstall = b.reason === 'uninstall';
      const reasonBadge = isUninstall
        ? `<span class="badge" style="background: rgba(239,68,68,0.15); color: #fca5a5; border: 1px solid rgba(239,68,68,0.3); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">⚠️ Auto-Archive (Uninstall)</span>`
        : `<span class="badge" style="background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.35); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">💾 On-Demand</span>`;

      const createdDate = formatDateTime(b.created_at_epoch || b.created_at, undefined, 'N/A');
      const sizeStr = b.archive_size_formatted || (b.archive_size_bytes ? `${(b.archive_size_bytes / (1024 * 1024)).toFixed(1)} MB` : '--');
      const stackHtml = b.stack ? `<span style="font-size: var(--zn-fs-xs); color:var(--muted); margin-left:6px;">(Stack: <code>${escapeHtml(b.stack)}</code>)</span>` : '';
      const mountsCount = b.mounts_count || (b.mounts ? b.mounts.length : 0);

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: var(--zn-fs-sm);">
          <td style="padding: 10px 12px; font-weight: 600; color: #fff;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span aria-hidden="true">📦</span>
              <strong>${escapeHtml(b.container_name || b.id)}</strong>
              ${stackHtml}
            </div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); font-weight: normal; margin-top:2px;">
              Image: <code style="font-size: var(--zn-fs-xs); color:#cbd5e1;">${escapeHtml(b.image || 'N/A')}</code>
            </div>
          </td>
          <td style="padding: 10px 12px;">${reasonBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="font-family: var(--font-mono, monospace); font-size: var(--zn-fs-xs); color: #e2e8f0;">${escapeHtml(b.archive_file || b.id)}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-top: 2px;">
              ${sizeStr} • ${mountsCount} volume${mountsCount === 1 ? '' : 's'}
            </div>
          </td>
          <td style="padding: 10px 12px; color: var(--muted); font-size: var(--zn-fs-xs);">
            ${createdDate}
          </td>
          <td style="padding: 10px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect btn-download-app-backup" data-backup-id="${escapeHtml(b.id)}" data-file="${escapeHtml(b.archive_file || 'app_backup.tar.gz')}" title="${t('ui.download_archive_tar_gz', 'Download Archive (.tar.gz)')}">
                ⬇️ Download
              </button>
              <button class="btn-rect btn-restore-app-backup" data-backup-id="${escapeHtml(b.id)}" data-app-name="${escapeHtml(b.container_name || b.id)}" title="${t('ui.restore_configuration_data', 'Restore Configuration & Data')}">
                🔄 Restore
              </button>
              <button class="btn-rect danger btn-delete-app-backup" data-backup-id="${escapeHtml(b.id)}" data-file="${escapeHtml(b.archive_file || b.id)}" title="${t('ui.delete_backup_archive', 'Delete Backup Archive')}">
                🗑️
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
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: var(--zn-fs-xs); font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">Application</th>
              <th style="padding: 8px 12px;">Trigger</th>
              <th style="padding: 8px 12px;">Archive File & Size</th>
              <th style="padding: 8px 12px;">Created</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    `;

    // Download action
    mount.querySelectorAll('.btn-download-app-backup').forEach(btn => {
      btn.addEventListener('click', async () => {
        const backupId = btn.dataset.backupId;
        const filename = btn.dataset.file;
        try {
          btn.disabled = true;
          showToast(t('toast.downloading_backup', 'Downloading backup "{filename}"...', { filename: filename }), 'info');
          await api.downloadBlob(`/api/backup/apps/${encodeURIComponent(backupId)}/download`, filename);
        } catch (err) {
          showToast(t('toast.download_failed', 'Download failed: {error}', { error: err.message }), 'error');
        } finally {
          btn.disabled = false;
        }
      });
    });

    // Restore action
    mount.querySelectorAll('.btn-restore-app-backup').forEach(btn => {
      btn.addEventListener('click', () => {
        const backupId = btn.dataset.backupId;
        const appName = btn.dataset.appName;
        showConfirmToast(
          `Restore App Data for "${appName}"?`,
          `This will extract configurations and mount files back into the original host directories. Existing paths will be preserved in a <code>.pre_restore</code> backup.`,
          async () => {
            try {
              showToast(t('toast.restoring', 'Restoring {appName}...', { appName: appName }), 'info');
              const res = await api.post(`/api/backup/apps/${encodeURIComponent(backupId)}/restore`);
              showToast(t('toast.app_successfully_restored_paths_restored', 'App "{appName}" successfully restored ({extracted_count} paths restored)!', { appName: appName, extracted_count: res.extracted_count || 'all' }), 'success');
              fetchAndRenderAppBackups(mount, document.getElementById('app-backups-filter-app')?.value || '');
            } catch (err) {
              showToast(t('toast.restore_failed', 'Restore failed: {error}', { error: err.message }), 'error');
            }
          },
          null,
          { okText: '🔄 Restore App Data', cancelText: 'Cancel', allowHtml: true }
        );
      });
    });

    // Delete action
    mount.querySelectorAll('.btn-delete-app-backup').forEach(btn => {
      btn.addEventListener('click', () => {
        const backupId = btn.dataset.backupId;
        const filename = btn.dataset.file;
        showConfirmToast(
          `Delete Backup Archive?`,
          `Are you sure you want to permanently delete backup archive <strong>${escapeHtml(filename)}</strong>? This cannot be undone.`,
          async () => {
            try {
              await api.delete(`/api/backup/apps/${encodeURIComponent(backupId)}`, { confirmed: true });
              showToast(t('toast.backup_deleted', 'Backup "{filename}" deleted.', { filename: filename }), 'success');
              fetchAndRenderAppBackups(mount, document.getElementById('app-backups-filter-app')?.value || '');
            } catch (err) {
              showToast(t('toast.delete_failed', 'Delete failed: {error}', { error: err.message }), 'error');
            }
          },
          null,
          { okText: '🗑 Delete Archive', cancelText: 'Cancel', allowHtml: true }
        );
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: var(--zn-fs-sm);">Failed to load application backups: ${escapeHtml(err.message)}</div>`;
  }
}
