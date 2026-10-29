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
import { renderOffsite, offerRecoveryKit } from '../offsite-backup.js';

// =========================================================================
// Backup jobs (3-2-1)
// =========================================================================

/** REL-9: a copy job becomes an off-site backup of the same folder on the same remote. */
export function migrateJob(jobId, onDone = null) {
  showConfirmToast(
    t('backup.migrate', 'Move to off-site backup'),
    t('backup.migrate_confirm', 'The folder will be backed up with versions and encryption to a new folder next to the copy on the same remote. The copy so far stays as it is; this copy job is turned off.'),
    async () => {
      try {
        const res = await api.post(`/api/backup/schedule/${encodeURIComponent(jobId)}/migrate`, {});
        showToast(t('backup.migrated', 'Now an off-site backup. Save its recovery kit.'), 'success');
        if (onDone) onDone();
        await offerRecoveryKit(res.repo);
      } catch (err) {
        showToast(t('toast.backup_run_failed', 'Backup run failed: {error}', { error: err.message }), 'error');
      }
    },
  );
}

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
        ? `<span class="badge" style="background: rgba(14,165,233,0.15); color: var(--zn-text-accent); border: 1px solid rgba(14,165,233,0.3); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">☁️ ${escapeHtml(job.remote_name || 'Cloud')}:${escapeHtml(job.remote_path || '')}</span>`
        : job.destination_type === 'local_folder'
          ? `<span class="badge" style="background: rgba(16,185,129,0.15); color: var(--zn-text-ok); border: 1px solid rgba(16,185,129,0.3); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">📁 ${escapeHtml(job.local_path || '')}</span>`
          : `<span class="badge" style="background: rgba(16,185,129,0.15); color: var(--zn-text-ok); border: 1px solid rgba(16,185,129,0.3); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">📸 ${escapeHtml(t('backup.dest_snapshot', 'Snapshot on this server'))}</span>`;

      const schedBadge = `<span class="badge" style="background: var(--zn-glaze-6); color: var(--zn-text-soft); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; text-transform: capitalize;">${escapeHtml(job.schedule || 'daily')}</span>`;
      
      let statusHtml;
      if (job.last_status === 'running') {
        statusHtml = `<span style="display:inline-flex; align-items:center; gap:4px; color: var(--zn-text-accent); font-size: var(--zn-fs-xs);"><span class="spinner-inline" style="width:10px; height:10px;"></span> ${escapeHtml(t('backup.state_running', 'Running…'))}</span>`;
      } else if (job.last_status === 'success') {
        statusHtml = `<span style="color: var(--zn-text-ok); font-size: var(--zn-fs-xs); font-weight:600;">${escapeHtml(t('backup.state_ok', '✓ Done'))}</span>`;
      } else if (job.last_status === 'skipped') {
        statusHtml = `<span class="backup-skipped" title="${escapeHtml(job.last_error || '')}">${escapeHtml(t('backup.skipped', 'Skipped'))}</span>`;
      } else if (job.last_status === 'error') {
        statusHtml = `<span style="color: var(--lt-t-f43f5eff, #f43f5e); font-size: var(--zn-fs-xs); font-weight:600;" title="${escapeHtml(job.last_error || '')}">${escapeHtml(t('backup.state_failed', '⚠ Failed'))}</span>`;
      } else {
        statusHtml = `<span style="color: var(--muted); font-size: var(--zn-fs-xs);">${escapeHtml(t('backup.state_idle', 'Not run yet'))}</span>`;
      }

      const lastRunStr = formatDateTime(job.last_run_at, undefined, t('common.never', 'Never'));

      return `
        <tr style="border-bottom: 1px solid var(--zn-line-6); font-size: var(--zn-fs-sm);">
          <td style="padding: 10px 12px; font-weight: 600; color: var(--zn-text-strong);">
            <div>${escapeHtml(job.name)}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); font-weight: normal;">${isSettings
              ? escapeHtml(t('backup.kind_config_source', 'ZettNAS settings (encrypted)'))
              : `${escapeHtml(t('backup.source_folder', 'Folder:'))} <code>${escapeHtml(job.source_subvolume || '@shares')}</code>`}</div>
          </td>
          <td style="padding: 10px 12px;">${destBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
              ${schedBadge}
              <span style="font-size: var(--zn-fs-xs); color: var(--muted);">${escapeHtml(t('backup.keep_n', 'Keep {count}', { count: job.retention_count || 7 }))}</span>
            </div>
          </td>
          <td style="padding: 10px 12px;">
            <div>${statusHtml}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${lastRunStr}</div>
          </td>
          <td style="padding: 10px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              ${isRemote && !isSettings && !job.migrated_to ? `<button class="btn-rect btn-migrate-backup-job" data-job-id="${escapeHtml(job.id)}" title="${escapeHtml(t('backup.migrate_help', 'Make this an off-site backup: versions of every file, encrypted. The copy so far stays where it is.'))}">${escapeHtml(t('backup.migrate', 'Move to off-site backup'))}</button>` : ''}
              <button class="btn-rect primary btn-run-backup-job" data-job-id="${escapeHtml(job.id)}" title="${t('ui.run_backup_job_now', 'Run Backup Job Now')}">
                ${escapeHtml(t('backup.run', '▶ Run'))}
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
      <div style="overflow-x: auto; background: var(--zn-shade-20); border-radius: 8px; border: 1px solid var(--zn-line-8);">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid var(--zn-line-10); font-size: var(--zn-fs-xs); font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_job', 'What'))}</th>
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_where', 'Where to'))}</th>
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_when', 'When and how many'))}</th>
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_last', 'Last run'))}</th>
              <th style="padding: 8px 12px; text-align: right;">${escapeHtml(t('backup.col_actions', 'Actions'))}</th>
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
          showToast(t('toast.backup_started', 'The backup started. You will get a notification when it finishes.'), 'success');
          fetchAndRenderBackupJobs(mount);
        } catch (err) {
          showToast(t('toast.backup_run_failed', 'Backup run failed: {error}', { error: err.message }), 'error');
        } finally {
          btn.disabled = false;
          btn.innerHTML = origText;
        }
      });
    });

    mount.querySelectorAll('.btn-migrate-backup-job').forEach((btn) => {
      btn.addEventListener('click', () => migrateJob(btn.dataset.jobId, () => fetchAndRenderBackupJobs(mount)));
    });

    mount.querySelectorAll('.btn-delete-backup-job').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.dataset.jobId;
        showConfirmToast(t('backup.delete_job_q', 'Delete the backup job "{name}"? Copies already made stay where they are.', { name: jobId }), async () => {
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
    mount.innerHTML = `<div style="padding: 16px; color: var(--lt-t-f43f5eff, #f43f5e); font-size: var(--zn-fs-sm);">${escapeHtml(t('backup.jobs_failed', 'The backup jobs couldn\'t be loaded: {error}', { error: err.message }))}</div>`;
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
        <tr style="border-bottom: 1px solid var(--zn-line-6); font-size: var(--zn-fs-sm);">
          <td style="padding: 8px 12px; font-weight: 600; color: var(--zn-text-strong);">
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
                ${escapeHtml(t('backup.snap_restore', '⏪ Go back'))}
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
      <div style="overflow-x: auto; background: var(--zn-shade-20); border-radius: 8px; border: 1px solid var(--zn-line-8);">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid var(--zn-line-10); font-size: var(--zn-fs-xs); font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_snap', 'Snapshot'))}</th>
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_path', 'Folder'))}</th>
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_created', 'Made'))}</th>
              <th style="padding: 8px 12px; text-align: right;">${escapeHtml(t('backup.col_actions', 'Actions'))}</th>
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
        showConfirmToast(t('backup.snap_restore_q', 'Go back to snapshot "{name}"? The folder as it is now is kept as a snapshot first.', { name: snapName }), async () => {
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
        showConfirmToast(t('backup.snap_delete_q', 'Delete snapshot "{name}"?', { name: snapName }), async () => {
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
    mount.innerHTML = `<div style="padding: 16px; color: var(--lt-t-f43f5eff, #f43f5e); font-size: var(--zn-fs-sm);">${escapeHtml(t('backup.snaps_failed', 'The snapshots couldn\'t be loaded: {error}', { error: err.message }))}</div>`;
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
      
      filterSelect.innerHTML = `<option value="">${escapeHtml(t('backup.apps_all', 'All apps'))}</option>` +
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
        ? `<span class="badge" style="background: rgba(239,68,68,0.15); color: var(--lt-t-fca5a5ff, #fca5a5); border: 1px solid rgba(239,68,68,0.3); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">⚠️ ${escapeHtml(t('backup.app_reason_uninstall', 'When removed'))}</span>`
        : `<span class="badge" style="background: rgba(249, 115, 22, 0.15); color: var(--lt-t-fb923cff, #fb923c); border: 1px solid rgba(249, 115, 22, 0.35); font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px;">💾 ${escapeHtml(t('backup.app_reason_manual', 'By hand'))}</span>`;

      const createdDate = formatDateTime(b.created_at_epoch || b.created_at, undefined, 'N/A');
      const sizeStr = b.archive_size_formatted || (b.archive_size_bytes ? `${(b.archive_size_bytes / (1024 * 1024)).toFixed(1)} MB` : '--');
      const stackHtml = b.stack ? `<span style="font-size: var(--zn-fs-xs); color:var(--muted); margin-left:6px;">(${escapeHtml(t('backup.app_stack', 'Stack:'))} <code>${escapeHtml(b.stack)}</code>)</span>` : '';
      const mountsCount = b.mounts_count || (b.mounts ? b.mounts.length : 0);

      return `
        <tr style="border-bottom: 1px solid var(--zn-line-6); font-size: var(--zn-fs-sm);">
          <td style="padding: 10px 12px; font-weight: 600; color: var(--zn-text-strong);">
            <div style="display:flex; align-items:center; gap:6px;">
              <span aria-hidden="true">📦</span>
              <strong>${escapeHtml(b.container_name || b.id)}</strong>
              ${stackHtml}
            </div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); font-weight: normal; margin-top:2px;">
              ${escapeHtml(t('backup.app_image', 'Image:'))} <code style="font-size: var(--zn-fs-xs); color:var(--zn-text-soft);">${escapeHtml(b.image || 'N/A')}</code>
            </div>
          </td>
          <td style="padding: 10px 12px;">${reasonBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="font-family: var(--font-mono, monospace); font-size: var(--zn-fs-xs); color: var(--zn-text);">${escapeHtml(b.archive_file || b.id)}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-top: 2px;">
              ${sizeStr} • ${escapeHtml(t('backup.app_volumes', '{count, plural, one {# volume} other {# volumes}}', { count: mountsCount }))}
            </div>
          </td>
          <td style="padding: 10px 12px; color: var(--muted); font-size: var(--zn-fs-xs);">
            ${createdDate}
          </td>
          <td style="padding: 10px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect btn-download-app-backup" data-backup-id="${escapeHtml(b.id)}" data-file="${escapeHtml(b.archive_file || 'app_backup.tar.gz')}" title="${t('ui.download_archive_tar_gz', 'Download Archive (.tar.gz)')}">
                ${escapeHtml(t('backup.download', '⬇️ Download'))}
              </button>
              <button class="btn-rect btn-restore-app-backup" data-backup-id="${escapeHtml(b.id)}" data-app-name="${escapeHtml(b.container_name || b.id)}" title="${t('ui.restore_configuration_data', 'Restore Configuration & Data')}">
                ${escapeHtml(t('backup.restore', '🔄 Restore'))}
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
      <div style="overflow-x: auto; background: var(--zn-shade-20); border-radius: 8px; border: 1px solid var(--zn-line-8);">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid var(--zn-line-10); font-size: var(--zn-fs-xs); font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_app', 'App'))}</th>
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_reason', 'Made'))}</th>
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_file', 'File and size'))}</th>
              <th style="padding: 8px 12px;">${escapeHtml(t('backup.col_created', 'Made'))}</th>
              <th style="padding: 8px 12px; text-align: right;">${escapeHtml(t('backup.col_actions', 'Actions'))}</th>
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
          t('backup.app_restore_title', 'Restore the data of "{app}"?', { app: appName }),
          t('backup.app_restore_msg', 'Its settings and data go back to the folders they came from. What is there now is kept in a .pre_restore copy first.'),
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
          { okText: t('backup.app_restore_ok', 'Restore'), cancelText: t('common.cancel', 'Cancel') }
        );
      });
    });

    // Delete action
    mount.querySelectorAll('.btn-delete-app-backup').forEach(btn => {
      btn.addEventListener('click', () => {
        const backupId = btn.dataset.backupId;
        const filename = btn.dataset.file;
        showConfirmToast(
          t('backup.app_delete_title', 'Delete this app backup?'),
          t('backup.app_delete_msg', '{file} is deleted for good.', { file: filename }),
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
          { okText: t('backup.app_delete_ok', 'Delete'), cancelText: t('common.cancel', 'Cancel'), destructive: true }
        );
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: var(--lt-t-f43f5eff, #f43f5e); font-size: var(--zn-fs-sm);">${escapeHtml(t('backup.apps_failed', 'The app backups couldn\'t be loaded: {error}', { error: err.message }))}</div>`;
  }
}
