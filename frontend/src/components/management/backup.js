/**
 * Mission Control: Backup tasks, pool snapshots, app backups.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { api } from '../../api.js';
import { showToast, showConfirmToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { formatBytes, formatDateTime } from '../../format.js';
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
        ? `<span class="badge zn-tag zn-tag--info">☁️ ${escapeHtml(job.remote_name || 'Cloud')}:${escapeHtml(job.remote_path || '')}</span>`
        : job.destination_type === 'local_folder'
          ? `<span class="badge zn-tag zn-tag--ok">📁 ${escapeHtml(job.local_path || '')}</span>`
          : `<span class="badge zn-tag zn-tag--ok">📸 ${escapeHtml(t('backup.dest_snapshot', 'Snapshot on this server'))}</span>`;

      const schedBadge = `<span class="badge zn-tag zn-tag--plain">${escapeHtml(job.schedule || 'daily')}</span>`;
      
      let statusHtml;
      if (job.last_status === 'running') {
        statusHtml = `<span class="zn-state zn-state--busy"><span class="spinner-inline zn-spinner-sm"></span> ${escapeHtml(t('backup.state_running', 'Running…'))}</span>`;
      } else if (job.last_status === 'success') {
        statusHtml = `<span class="zn-state zn-state--ok">${escapeHtml(t('backup.state_ok', '✓ Done'))}</span>`;
      } else if (job.last_status === 'skipped') {
        statusHtml = `<span class="backup-skipped" title="${escapeHtml(job.last_error || '')}">${escapeHtml(t('backup.skipped', 'Skipped'))}</span>`;
      } else if (job.last_status === 'error') {
        statusHtml = `<span class="zn-state zn-state--crit" title="${escapeHtml(job.last_error || '')}">${escapeHtml(t('backup.state_failed', '⚠ Failed'))}</span>`;
      } else {
        statusHtml = `<span class="zn-state zn-state--idle">${escapeHtml(t('backup.state_idle', 'Not run yet'))}</span>`;
      }

      const lastRunStr = formatDateTime(job.last_run_at, undefined, t('common.never', 'Never'));

      return `
        <tr>
          <td class="is-strong">
            <div>${escapeHtml(job.name)}</div>
            <div class="zn-sub">${isSettings
              ? escapeHtml(t('backup.kind_config_source', 'ZettNAS settings (encrypted)'))
              : `${escapeHtml(t('backup.source_folder', 'Folder:'))} <code>${escapeHtml(job.source_subvolume || '@shares')}</code>`}</div>
          </td>
          <td>${destBadge}</td>
          <td>
            <div class="zn-inline zn-inline--wrap">
              ${schedBadge}
              <span class="zn-sub">${escapeHtml(t('backup.keep_n', 'Keep {count}', { count: job.retention_count || 7 }))}</span>
            </div>
          </td>
          <td>
            <div>${statusHtml}</div>
            <div class="zn-sub">${lastRunStr}</div>
          </td>
          <td class="is-end">
            <div class="zn-actions">
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
      <div class="zn-datatable-wrap">
        <table class="zn-datatable">
          <thead>
            <tr>
              <th>${escapeHtml(t('backup.col_job', 'What'))}</th>
              <th>${escapeHtml(t('backup.col_where', 'Where to'))}</th>
              <th>${escapeHtml(t('backup.col_when', 'When and how many'))}</th>
              <th>${escapeHtml(t('backup.col_last', 'Last run'))}</th>
              <th class="is-end">${escapeHtml(t('backup.col_actions', 'Actions'))}</th>
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
          btn.innerHTML = `<span class="spinner-inline zn-spinner-xs"></span>`;
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
    mount.innerHTML = `<div class="zn-load-error">${escapeHtml(t('backup.jobs_failed', 'The backup jobs couldn\'t be loaded: {error}', { error: err.message }))}</div>`;
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
  const sync2 = document.getElementById('two-way-sync-mount');
  if (sync2) import('../two-way-sync.js').then((m) => m.renderTwoWaySync(sync2)); // FEAT-06

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
        <tr>
          <td class="is-strong">
            <span class="is-mono">📸 ${escapeHtml(s.name)}</span>
          </td>
          <td class="is-muted">
            ${escapeHtml(s.path || '')}
          </td>
          <td class="is-muted">
            ${createdDate}
          </td>
          <td class="is-end">
            <div class="zn-actions">
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
      <div class="zn-datatable-wrap">
        <table class="zn-datatable zn-datatable--compact">
          <thead>
            <tr>
              <th>${escapeHtml(t('backup.col_snap', 'Snapshot'))}</th>
              <th>${escapeHtml(t('backup.col_path', 'Folder'))}</th>
              <th>${escapeHtml(t('backup.col_created', 'Made'))}</th>
              <th class="is-end">${escapeHtml(t('backup.col_actions', 'Actions'))}</th>
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
    mount.innerHTML = `<div class="zn-load-error">${escapeHtml(t('backup.snaps_failed', 'The snapshots couldn\'t be loaded: {error}', { error: err.message }))}</div>`;
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
        ? `<span class="badge zn-tag zn-tag--crit">⚠️ ${escapeHtml(t('backup.app_reason_uninstall', 'When removed'))}</span>`
        : `<span class="badge zn-tag zn-tag--warn">💾 ${escapeHtml(t('backup.app_reason_manual', 'By hand'))}</span>`;

      const createdDate = formatDateTime(b.created_at_epoch || b.created_at, undefined, 'N/A');
      const sizeStr = b.archive_size_formatted || (b.archive_size_bytes ? formatBytes(b.archive_size_bytes) : '--');
      const stackHtml = b.stack ? `<span class="zn-sub" style="margin-left:6px;">(${escapeHtml(t('backup.app_stack', 'Stack:'))} <code>${escapeHtml(b.stack)}</code>)</span>` : '';
      const mountsCount = b.mounts_count || (b.mounts ? b.mounts.length : 0);

      return `
        <tr>
          <td class="is-strong">
            <div class="zn-inline">
              <span aria-hidden="true">📦</span>
              <strong>${escapeHtml(b.container_name || b.id)}</strong>
              ${stackHtml}
            </div>
            <div class="zn-sub is-spaced">
              ${escapeHtml(t('backup.app_image', 'Image:'))} <code class="zn-sub" style="color:var(--zn-text-soft);">${escapeHtml(b.image || 'N/A')}</code>
            </div>
          </td>
          <td>${reasonBadge}</td>
          <td>
            <div class="is-mono zn-sub" style="color: var(--zn-text);">${escapeHtml(b.archive_file || b.id)}</div>
            <div class="zn-sub is-spaced">
              ${sizeStr} • ${escapeHtml(t('backup.app_volumes', '{count, plural, one {# volume} other {# volumes}}', { count: mountsCount }))}
            </div>
          </td>
          <td class="is-muted">
            ${createdDate}
          </td>
          <td class="is-end">
            <div class="zn-actions">
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
      <div class="zn-datatable-wrap">
        <table class="zn-datatable">
          <thead>
            <tr>
              <th>${escapeHtml(t('backup.col_app', 'App'))}</th>
              <th>${escapeHtml(t('backup.col_reason', 'Made'))}</th>
              <th>${escapeHtml(t('backup.col_file', 'File and size'))}</th>
              <th>${escapeHtml(t('backup.col_created', 'Made'))}</th>
              <th class="is-end">${escapeHtml(t('backup.col_actions', 'Actions'))}</th>
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
              showToast(t('toast.app_successfully_restored_paths_restored', 'App "{appName}" successfully restored ({extracted_count} paths restored)!', { appName: appName, extracted_count: res.extracted_count || 0 }), 'success');
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
    mount.innerHTML = `<div class="zn-load-error">${escapeHtml(t('backup.apps_failed', 'The app backups couldn\'t be loaded: {error}', { error: err.message }))}</div>`;
  }
}
