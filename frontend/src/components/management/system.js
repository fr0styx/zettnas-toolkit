/**
 * Mission Control: System info, updates, revert, diagnostics bundle.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { bringToFront } from '../dock.js';
import { api } from '../../api.js';
import { showToast, showConfirmToast, showPromptToast } from '../../toast.js';
import { escapeHtml, copyTextToClipboard } from '../../utils.js';
import { t } from '../../i18n.js';
import { collectClientEnvironment, getClientLogs } from '../../client-logger.js';
import { formatDateTime, formatTime } from '../../format.js';

const UPDATE_CHANNELS = ['stable', 'beta', 'edge'];
let _currentUpdateChannel = 'stable';
try {
  const saved = localStorage.getItem('zettnas_update_channel');
  if (UPDATE_CHANNELS.includes(saved)) _currentUpdateChannel = saved;
} catch (e) {}

let _lastUpdateData = null;

export async function setUpdateChannel(channel) {
  _currentUpdateChannel = UPDATE_CHANNELS.includes(channel) ? channel : 'stable';
  try {
    localStorage.setItem('zettnas_update_channel', _currentUpdateChannel);
  } catch (e) {}
  syncUpdateChannelUI();
  return fetchAndRenderSystemAbout(true, _currentUpdateChannel);
}

function syncUpdateChannelUI() {
  const looks = {
    stable: ['rgba(37, 194, 160, 0.25)', '#25c2a0'],
    beta: ['rgba(245, 183, 49, 0.22)', '#f5b731'],
    edge: ['rgba(14, 165, 233, 0.25)', '#38bdf8'],
  };
  for (const ch of UPDATE_CHANNELS) {
    const btn = document.getElementById(`btn-channel-${ch}`);
    if (!btn) continue;
    const on = ch === _currentUpdateChannel;
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.style.background = on ? looks[ch][0] : 'transparent';
    btn.style.color = on ? looks[ch][1] : 'var(--muted)';
  }
}

export async function fetchAndRenderSystemAbout(force = false, channelOverride = null) {
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

  const btnCheck = document.getElementById('btn-check-updates');
  const btnIcon = document.getElementById('btn-check-updates-icon');
  const btnText = document.getElementById('btn-check-updates-text');

  // Lock button width to prevent horizontal layout shift, keeping Stable/Edge toggle static in place
  if (btnCheck && btnCheck.offsetWidth > 0) {
    btnCheck.style.minWidth = `${Math.max(152, btnCheck.offsetWidth)}px`;
  }

  const channel = channelOverride || _currentUpdateChannel || 'stable';
  syncUpdateChannelUI();

  if (btnIcon && btnText) {
    btnIcon.textContent = '⏳';
    btnText.textContent = t('ui.checking', 'Checking...');
  }
  if (btnCheck) {
    btnCheck.disabled = true;
  }

  // 1. Fetch system about telemetry
  try {
    const about = await api.get('/api/system/about');
    if (about) {
      const commitTag = about.commit ? ` (${about.commit})` : '';
      const channelLabel = channel === 'edge' ? 'Edge (Rolling)' : channel === 'beta' ? t('updates.channel_beta_label', 'Beta (7-day test)') : (about.release_channel || 'Stable');
      if (versionBadge) versionBadge.textContent = `${about.tag || 'v' + about.version}${commitTag} • ${channelLabel}`;
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

  // 2. How the last update ended: a rollback is shown until the next successful update (OPS-7)
  showLastUpdateResult();

  // 3. Fetch update status
  try {
    const data = await api.get(`/api/system/updates?channel=${channel}${force ? '&force=true' : ''}`);
    _lastUpdateData = data;
    refreshPreviousVersions();
    if (data) {
      const isEdge = data.channel === 'edge';
      const applyBtn = document.getElementById('btn-apply-system-update');
      const applyText = document.getElementById('btn-apply-update-text');

      if (data.update_available) {
        if (statusIcon) statusIcon.textContent = '🚀';
        if (statusTitle) {
          statusTitle.textContent = isEdge
            ? `Update Available (Edge): ${data.latest_version}`
            : `Update Available: ${data.latest_tag || 'v' + data.latest_version}`;
          statusTitle.style.color = 'var(--warn, #f5a623)';
        }
        if (statusDesc) {
          statusDesc.textContent = isEdge
            ? `Newer commit features are available on the main branch.`
            : `A newer release of ZettNAS Workbench is available on GitHub.`;
        }
        if (detailsBox) detailsBox.style.display = 'block';
        if (releaseTitle) releaseTitle.textContent = data.release_name || `Release ${data.latest_tag}`;
        if (releaseLink) releaseLink.href = data.release_url || 'https://github.com/fr0styx/zettnas-toolkit/releases';
        if (releaseNotes) releaseNotes.textContent = data.release_notes || 'No release notes provided.';

        if (applyBtn && applyText) {
          applyBtn.style.display = 'flex';
          applyText.textContent = isEdge
            ? `Install Latest Commit (${data.latest_version})`
            : `Install Release ${data.latest_tag || 'v' + data.latest_version}`;
        }
      } else {
        if (statusIcon) statusIcon.textContent = '✅';
        if (statusTitle) {
          statusTitle.textContent = isEdge
            ? `ZettNAS Workbench is up to date with main`
            : `ZettNAS Workbench is up to date`;
          statusTitle.style.color = 'var(--ok2, #25c2a0)';
        }
        if (statusDesc) {
          statusDesc.textContent = isEdge
            ? `You are running the latest commit on the main branch (${data.latest_version || data.current_commit || 'latest'}).`
            : `You are running the latest stable release (${data.latest_tag || 'v' + data.current_version}).`;
        }
        if (detailsBox) detailsBox.style.display = 'none';
        if (applyBtn) applyBtn.style.display = 'none';
      }
      if (lastCheckedEl && data.checked_at) {
        const timeStr = formatTime(data.checked_at);
        lastCheckedEl.textContent = `Checked: ${timeStr}`;
      }
    }
  } catch (err) {
    if (statusIcon) statusIcon.textContent = '⚠️';
    if (statusTitle) {
      statusTitle.textContent = t('ui.unable_to_check_for_updates', 'Unable to check for updates');
      statusTitle.style.color = 'var(--crit, #ff6b6b)';
    }
    if (statusDesc) statusDesc.textContent = err.message || 'Offline or network request failed.';
  } finally {
    if (btnIcon && btnText) {
      btnIcon.textContent = '🔄';
      btnText.textContent = t('updates.check_btn', 'Check for Updates');
    }
    if (btnCheck) {
      btnCheck.disabled = false;
    }
  }
}

// The newest version this install can go back to (a pre-update snapshot whose image is still on the host).
let _previousVersion = null;

/** Backup job form: a settings backup (OPS-8) has a passphrase and a folder or remote, no source share. */
export function syncBackupJobForm() {
  const kind = document.getElementById('backup-job-kind')?.value || 'data';
  const isConfig = kind === 'config';
  const dest = document.getElementById('backup-job-dest-type');
  const sub = document.getElementById('backup-job-subvolume');
  const subWrap = document.getElementById('backup-subvolume-wrap');
  const cfg = document.getElementById('backup-config-fields');
  const local = document.getElementById('backup-local-fields');
  const remote = document.getElementById('backup-remote-fields');
  if (subWrap) subWrap.hidden = isConfig;
  if (sub) sub.required = !isConfig;
  if (cfg) cfg.hidden = !isConfig;
  if (dest) {
    const folderOpt = dest.querySelector('option[value="local_folder"]');
    const snapOpt = dest.querySelector('option[value="local_snapshot"]');
    if (folderOpt) folderOpt.hidden = !isConfig;
    if (snapOpt) snapOpt.hidden = isConfig;
    if (isConfig && dest.value === 'local_snapshot') dest.value = 'local_folder';
    if (!isConfig && dest.value === 'local_folder') dest.value = 'remote';
  }
  const value = dest ? dest.value : 'remote';
  if (local) local.hidden = !(isConfig && value === 'local_folder');
  if (remote) remote.style.display = value === 'remote' ? 'flex' : 'none';
}

export async function showLastUpdateResult() {
  const box = document.getElementById('update-last-result');
  if (!box) return;
  try {
    const r = await api.get('/api/system/updates/last-result');
    if (r && (r.result === 'rolled_back' || r.result === 'not_applied')) {
      const when = r.at ? formatDateTime(r.at * 1000, undefined, '') : '';
      const key = r.result === 'rolled_back' ? 'updates.last_rolled_back' : 'updates.last_not_applied';
      const fallback = r.result === 'rolled_back'
        ? 'The last update ({when}) did not start cleanly and was rolled back: {reason}'
        : 'The last update ({when}) was not applied: {reason}';
      box.textContent = t(key, fallback).replace('{when}', when).replace('{reason}', r.reason || '');
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  } catch (e) {
    box.hidden = true;
  }
}

export async function refreshPreviousVersions() {
  const btn = document.getElementById('btn-revert-system-update');
  const label = document.getElementById('btn-revert-update-text');
  if (!btn) return null;
  try {
    const res = await api.get('/api/system/updates/previous');
    _previousVersion = (res?.previous || []).find((p) => p.image_available) || null;
  } catch (e) {
    _previousVersion = null;
  }
  btn.style.display = _previousVersion ? 'flex' : 'none';
  if (_previousVersion && label) {
    label.textContent = _previousVersion.version ? `Revert to v${_previousVersion.version}` : 'Revert to previous version';
  }
  return _previousVersion;
}

export async function revertSystemUpdate() {
  const prev = _previousVersion || (await refreshPreviousVersions());
  if (!prev) {
    showToast(t('toast.no_previous_version_is_available_on', 'No previous version is available on this host.'), 'error');
    return;
  }
  const name = prev.version ? `v${prev.version}` : 'the previous version';
  showPromptToast(
    'Revert to previous version',
    `Go back to ${name}? Settings, users and other data return to how they were before the last update, so changes made since then are lost (a snapshot of the current data is kept). Enter your password to confirm.`,
    '',
    async (password) => {
      if (!password) return;
      const overlay = document.getElementById('update-progress-overlay');
      const title = document.getElementById('update-progress-title');
      const desc = document.getElementById('update-progress-desc');
      try {
        const res = await api.post('/api/system/updates/revert', { snapshot_id: prev.id, current_password: password }, { confirmed: true });
        if (overlay) overlay.style.display = 'block';
        if (title) title.textContent = `Reverting to ${name}...`;
        if (desc) desc.textContent = res?.message || 'Restoring the previous version and reconnecting...';
        let attempts = 0;
        let wentDown = false;
        const timer = setInterval(async () => {
          attempts++;
          try {
            const h = await fetch('/api/health', { cache: 'no-store' });
            if (h.ok && (wentDown || attempts >= 8)) {
              clearInterval(timer);
              setTimeout(() => window.location.reload(), 1200);
            }
          } catch (e) {
            wentDown = true;
            if (attempts >= 80) {
              clearInterval(timer);
              if (desc) desc.textContent = t('ui.please_refresh_the_page_once', 'Please refresh the page once ZettNAS has restarted.');
            }
          }
        }, 1500);
      } catch (err) {
        showToast(t('toast.revert_failed', 'Revert failed: {error}', { error: err.message }), 'error');
      }
    },
    null,
    { inputType: 'password', okText: 'Revert', placeholder: 'Your password' }
  );
}

export async function applySystemUpdate() {
  const applyBtn = document.getElementById('btn-apply-system-update');
  const progressOverlay = document.getElementById('update-progress-overlay');
  const progressTitle = document.getElementById('update-progress-title');
  const progressDesc = document.getElementById('update-progress-desc');

  const channel = _currentUpdateChannel || 'stable';
  const targetTag = _lastUpdateData?.latest_tag || _lastUpdateData?.latest_version || 'latest';

  showConfirmToast(
    t('updates.confirm_title', 'Apply System Update'),
    t(
      'updates.confirm_msg',
      `Update ZettNAS Workbench to ${targetTag} now? The container will pull the updated image and restart. Your data and settings are safely preserved.`
    ),
    async () => {
      if (applyBtn) applyBtn.disabled = true;
      if (progressOverlay) progressOverlay.style.display = 'block';
      if (progressTitle) progressTitle.textContent = t('updates.installing', 'Downloading & Applying Update...');
      if (progressDesc) progressDesc.textContent = t('ui.pulling_container_image_layers_from', 'Pulling container image layers from GHCR...');

      try {
        const targetImage = channel === 'edge'
          ? 'ghcr.io/fr0styx/zettnas-toolkit:edge'
          : 'ghcr.io/fr0styx/zettnas-toolkit:latest';
        const res = await api.post('/api/system/updates/apply', { channel, target_image: targetImage }, { confirmed: true });
        showToast(res?.message || 'Update initiated. Reconnecting...', 'info');

        if (res && res.auto_restarting === false) {
          if (progressTitle) progressTitle.textContent = t('ui.image_pulled', '📦 Image Pulled');
          if (progressDesc) {
            progressDesc.innerHTML = `${escapeHtml(res.message || 'Latest image downloaded.')}<br><br><span style="color:var(--brand,#00f0ff);font-weight:600;">Please restart the container in Unraid or Docker to finalize.</span>`;
          }
          if (applyBtn) applyBtn.disabled = false;
          return;
        }

        if (progressDesc) progressDesc.textContent = res?.message || 'Restarting container and reconnecting...';

        // Poll health endpoint until back online
        let attempts = 0;
        let hasGoneDown = false;
        const maxAttempts = 60;
        const interval = setInterval(async () => {
          attempts++;
          try {
            const h = await fetch('/api/health', { cache: 'no-store' });
            // Only declare update complete after the old container has dropped offline, or after grace period
            if (h.ok && (hasGoneDown || attempts >= 8)) {
              clearInterval(interval);
              if (progressTitle) progressTitle.textContent = t('ui.update_complete', '🎉 Update Complete!');
              if (progressDesc) progressDesc.textContent = t('ui.reloading_zettnas_workbench', 'Reloading ZettNAS Workbench...');
              showToast(t('updates.updated_success', 'ZettNAS updated successfully!'), 'success');
              setTimeout(() => window.location.reload(), 1200);
            }
          } catch (e) {
            hasGoneDown = true;
            if (progressDesc) progressDesc.textContent = t('ui.container_restarting_with_updated_image', 'Container restarting with updated image...');
            if (attempts >= maxAttempts) {
              clearInterval(interval);
              if (progressDesc) progressDesc.textContent = t('ui.please_refresh_the_page_once_2', 'Please refresh the page once the container has restarted.');
              if (applyBtn) applyBtn.disabled = false;
            }
          }
        }, 1500);
      } catch (err) {
        showToast(t('toast.update_failed', 'Update failed: {error}', { error: err.message }), 'error');
        if (progressOverlay) progressOverlay.style.display = 'none';
        if (applyBtn) applyBtn.disabled = false;
      }
    },
    null,
    { isUpdate: true }
  );
}

export async function downloadDiagnosticsBundle() {
  const btn = document.getElementById('btn-download-diagnostics');
  const btnIcon = document.getElementById('btn-download-diagnostics-icon');
  const btnText = document.getElementById('btn-download-diagnostics-text');

  if (btn) btn.disabled = true;
  if (btnIcon) btnIcon.textContent = '⏳';
  if (btnText) btnText.textContent = t('diagnostics.generating', 'Generating Archive...');

  showToast(t('diagnostics.toast_generating', 'Generating diagnostics bundle (scrubbing secrets)...'), 'info');

  try {
    const clientEnv = collectClientEnvironment();
    const frontendLogs = getClientLogs();
    const payload = {
      client_environment: clientEnv,
      frontend_logs: frontendLogs,
    };

    let filename;
    try {
      filename = await api.downloadBlob('/api/system/diagnostics-bundle', 'zettnas_diagnostics.zip', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (postErr) {
      // Graceful fallback to GET if POST route is rejected by proxy
      filename = await api.downloadBlob('/api/system/diagnostics-bundle', 'zettnas_diagnostics.zip');
    }
    showToast(t('diagnostics.download_success', 'Diagnostics bundle downloaded successfully') + ` (${filename}).`, 'success');
  } catch (err) {
    showToast(t('diagnostics.download_failed', 'Failed to download diagnostics') + `: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (btnIcon) btnIcon.textContent = '📦';
    if (btnText) btnText.textContent = t('diagnostics.download_btn', 'Download Diagnostics Bundle');
  }
}

export function closeDiagnosticsPreviewModal() {
  const overlay = document.getElementById('diagnostics-preview-modal-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
}

export function openDiagnosticsPreviewModal(data) {
  const overlay = document.getElementById('diagnostics-preview-modal-overlay');
  const banner = document.getElementById('diagnostics-preview-banner');
  const grid = document.getElementById('diagnostics-preview-grid');
  const mdEl = document.getElementById('diagnostics-preview-md');
  if (!overlay || !data) return;

  if (mdEl) {
    mdEl.textContent = data.support_markdown || 'No summary generated.';
  }

  if (banner) {
    const status = data.executive_status || 'HEALTHY';
    const alerts = Array.isArray(data.alerts) ? data.alerts : [];

    let borderColor = 'rgba(37, 194, 160, 0.3)';
    let bgColor = 'rgba(37, 194, 160, 0.08)';
    let badgeColor = 'var(--accent, #25c2a0)';
    let icon = '🟢';
    let title = t('diagnostics.status_healthy', 'SYSTEM HEALTHY');
    let desc = t('diagnostics.status_healthy_desc', 'All hardware parameters, storage arrays, and containers are operating normally.');

    if (status === 'CRITICAL') {
      borderColor = 'rgba(239, 68, 68, 0.5)';
      bgColor = 'rgba(239, 68, 68, 0.12)';
      badgeColor = '#ef4444';
      icon = '🚨';
      title = t('diagnostics.status_critical', 'CRITICAL ISSUES DETECTED');
      desc = t('diagnostics.status_critical_desc', 'Hardware failure, degraded drive arrays, or thermal clamp thresholds reached.');
    } else if (status === 'ATTENTION_REQUIRED') {
      borderColor = 'rgba(245, 158, 11, 0.4)';
      bgColor = 'rgba(245, 158, 11, 0.1)';
      badgeColor = '#f59e0b';
      icon = '⚠️';
      title = t('diagnostics.status_attention', 'ATTENTION REQUIRED');
      desc = t('diagnostics.status_attention_desc', 'Non-critical system warnings, restarting containers, or hardware bus notices.');
    }

    let alertItemsHtml = '';
    if (alerts.length > 0) {
      alertItemsHtml = `
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; flex-direction: column; gap: 4px;">
          ${alerts
            .map(
              (a) => `
            <div style="font-size: 11px; color: #f1f5f9; display: flex; align-items: flex-start; gap: 6px;">
              <span style="font-size: 11px; margin-top: 2px;">${a.level === 'critical' ? '🔴' : '🟡'}</span>
              <span>${escapeHtml(a.message || '')}</span>
            </div>
          `
            )
            .join('')}
        </div>
      `;
    }

    banner.innerHTML = `
      <div style="padding: 10px 14px; background: ${bgColor}; border: 1px solid ${borderColor}; border-radius: 8px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 14px;">${icon}</span>
            <span style="font-size: 12px; font-weight: 800; color: ${badgeColor}; letter-spacing: 0.5px;">${escapeHtml(title)}</span>
          </div>
          <span style="font-size: 11px; color: var(--muted); font-family: monospace;">ZettOS Kernel ${escapeHtml(data.platform || '')}</span>
        </div>
        <div style="font-size: 11px; color: var(--muted); margin-top: 3px;">${escapeHtml(desc)}</div>
        ${alertItemsHtml}
      </div>
    `;
    banner.style.display = 'block';
  }

  if (grid) {
    const memory = data.memory || {};
    const storage = data.storage || {};
    const docker = data.docker || {};
    const vms = data.vms || {};

    const memPct = memory.pct !== undefined ? memory.pct : (memory.used_percent || 0);
    const memTotalGb = memory.total_gb !== undefined ? memory.total_gb : Math.round((memory.total_bytes || 0) / (1024 ** 3));
    const memUsedGb = memory.used_gb !== undefined ? memory.used_gb : Math.round((memory.used_bytes || 0) / (1024 ** 3));

    grid.innerHTML = `
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Host & OS</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${escapeHtml(data.chassis || 'Appliance')}</div>
        <div style="font-size:11px; color:var(--muted); margin-top:1px;">Uptime: ${data.uptime_hours || 0}h</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Memory</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${memPct}% Used</div>
        <div style="font-size:11px; color:var(--muted); margin-top:1px;">${memUsedGb} / ${memTotalGb} GB RAM</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Storage</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${storage.pools_count || 0} Pools</div>
        <div style="font-size:11px; color:${(storage.degraded_disks?.length || 0) > 0 ? 'var(--crit)' : 'var(--muted)'}; margin-top:1px;">${storage.disks_count || 0} Drives (${storage.standby_count || 0} standby)</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Docker Fleet</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${docker.running || 0} / ${docker.total || 0} Running</div>
        <div style="font-size:11px; color:${(docker.restarting || 0) > 0 ? 'var(--crit)' : 'var(--muted)'}; margin-top:1px;">${docker.restarting || 0} Restarting, ${docker.dead || 0} Dead</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Virtual Machines</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${vms.active_vm_count || 0} / ${vms.total_vm_count || 0} Active</div>
        <div style="font-size:11px; color:var(--muted); margin-top:1px;">Headroom: Safe</div>
      </div>
    `;
  }

  overlay.style.display = 'flex';
  overlay.classList.remove('window-minimized');
  overlay.classList.add('open');

  const win = overlay.querySelector('.smart-modal-window');
  if (win && typeof bringToFront === 'function') {
    bringToFront(win);
  }
}

export async function previewDiagnosticsSummary() {
  const btn = document.getElementById('btn-preview-diagnostics');
  const origHtml = btn ? btn.innerHTML : '';
  try {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span class="ci-spinner" style="display:inline-block; width:12px; height:12px; border:2px solid rgba(255,255,255,0.3); border-top-color:#fff; border-radius:50%; animation:spin 0.8s linear infinite;"></span> <span>${t('diagnostics.loading_preview', 'Loading Preview...')}</span>`;
    }
    const data = await api.get('/api/system/diagnostics-summary');
    openDiagnosticsPreviewModal(data);
  } catch (err) {
    showToast(t('toast.failed_to_load_diagnostics_preview', 'Failed to load diagnostics preview: {error}', { error: err.message }), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

export async function copySupportMarkdown() {
  const btn = document.getElementById('btn-copy-support-md');
  const previewCopyBtn = document.getElementById('btn-diag-preview-copy');
  const targetBtn = (previewCopyBtn && document.activeElement === previewCopyBtn) ? previewCopyBtn : btn;
  const origHtml = targetBtn ? targetBtn.innerHTML : '';
  try {
    const mdEl = document.getElementById('diagnostics-preview-md');
    let md = '';
    if (mdEl && mdEl.textContent && mdEl.textContent.trim().length > 0 && mdEl.textContent !== 'No summary generated.') {
      md = mdEl.textContent;
    } else {
      if (targetBtn) {
        targetBtn.disabled = true;
        targetBtn.innerHTML = `<span class="ci-spinner" style="display:inline-block; width:12px; height:12px; border:2px solid rgba(255,255,255,0.3); border-top-color:#fff; border-radius:50%; animation:spin 0.8s linear infinite;"></span> <span>${t('diagnostics.copying_md', 'Copying...')}</span>`;
      }
      const data = await api.get('/api/system/diagnostics-summary');
      md = data?.support_markdown || '';
    }
    if (!md) throw new Error('No support markdown generated');

    const copied = await copyTextToClipboard(md);
    if (copied) {
      showToast(t('diagnostics.copied', 'Support markdown copied to clipboard!'), 'success');
    } else {
      throw new Error('Clipboard copy failed');
    }
  } catch (err) {
    showToast(t('toast.failed_to_copy_support_markdown', 'Failed to copy support markdown: {error}', { error: err.message }), 'error');
  } finally {
    if (targetBtn) {
      targetBtn.disabled = false;
      targetBtn.innerHTML = origHtml;
    }
  }
}
