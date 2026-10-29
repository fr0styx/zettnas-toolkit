/**
 * Offsite backup with restic: versioned, deduplicated, encrypted (Batch 6).
 */
import { api } from '../api.js';
import { escapeHtml, copyTextToClipboard } from '../utils.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';
import { formatBytes, formatDateTime } from '../format.js';

const when = (ts) => (ts ? formatDateTime(ts * 1000) : t('offsite.never', 'never'));

export function reposHtml(data) {
  if (!data.available) {
    return `<p class="offsite-note">${escapeHtml(t('offsite.unavailable', 'This image has no restic; update ZettNAS to use offsite backups.'))}</p>`;
  }
  const rows = (data.repos || [])
    .map(
      (r) => `<li class="offsite-repo">
      <div class="offsite-repo-main">
        <span class="offsite-repo-name">${escapeHtml(r.name)}</span>
        <span class="offsite-meta">${escapeHtml(r.location)} · ${escapeHtml(t('offsite.folders_n', '{n} folders', { n: r.paths.length }))} · ${escapeHtml(
          t('offsite.keep_rule', 'keeps {d} daily, {w} weekly, {m} monthly', { d: r.keep.daily, w: r.keep.weekly, m: r.keep.monthly }),
        )}</span>
        <span class="offsite-meta">${escapeHtml(t('offsite.last', 'Last backup {b} · last check {c}', { b: when(r.last_backup), c: when(r.last_check) }))}${
          r.last_result && r.last_result !== 'ok' ? ` · <strong>${escapeHtml(r.last_result)}</strong>` : ''
        }${r.initialized && !r.kit_saved_at ? ` · <strong class="offsite-kit-missing">${escapeHtml(t('offsite.kit_missing', 'Recovery kit not saved'))}</strong>` : ''}${
          r.last_unreadable ? ` · <strong>${escapeHtml(t('offsite.unreadable', '{n} files could not be read', { n: r.last_unreadable }))}</strong>` : ''
        }</span>
        ${r.append_only ? `<span class="offsite-meta">${escapeHtml(t('offsite.append_only', 'The backup server only adds versions (append-only), so old ones stay there until its owner removes them.'))}</span>` : ''}
        ${r.same_disk ? `<span class="offsite-meta"><strong>${escapeHtml(t('offsite.same_disk', 'Same storage as the folders it protects: a failed disk, a theft or a fire takes both. Use a USB disk, another NAS or the cloud.'))}</strong></span>` : ''}
      </div>
      <div class="offsite-actions">
        <button type="button" class="btn-pill-toggle is-small is-primary" data-off="backup" data-id="${escapeHtml(r.id)}">${escapeHtml(t('offsite.backup_now', 'Back up now'))}</button>
        <button type="button" class="btn-pill-toggle is-small" data-off="versions" data-id="${escapeHtml(r.id)}">${escapeHtml(t('offsite.versions', 'Versions'))}</button>
        <button type="button" class="btn-pill-toggle is-small" data-off="check" data-id="${escapeHtml(r.id)}">${escapeHtml(t('offsite.verify', 'Verify'))}</button>
        <button type="button" class="btn-pill-toggle is-small" data-off="kit" data-id="${escapeHtml(r.id)}">${escapeHtml(t('offsite.kit', 'Recovery kit'))}</button>
        <button type="button" class="btn-pill-toggle is-small is-danger" data-off="forget" data-id="${escapeHtml(r.id)}">${escapeHtml(t('offsite.forget', 'Forget'))}</button>
      </div>
    </li>`,
    )
    .join('');
  return `<ul class="offsite-list">${rows || `<li class="offsite-note">${escapeHtml(t('offsite.none', 'No offsite backup yet.'))}</li>`}</ul>`;
}

export function formHtml(shares) {
  return `<form class="offsite-form" data-off-form>
    <label>${escapeHtml(t('offsite.name', 'Name'))}<input name="name" required maxlength="80" placeholder="${escapeHtml(t('offsite.name_ph', 'USB disk at the office'))}"></label>
    <label>${escapeHtml(t('offsite.destination', 'Destination'))}<input name="location" required placeholder="/mnt/disks/usb/zettnas · rclone:mycloud:zettnas · rest:http://friend-nas:8000/backup/"></label>
    <div class="offsite-rest" data-off-rest hidden>
      <label>${escapeHtml(t('offsite.rest_user', 'User name on the backup server'))}<input name="rest_user" maxlength="64" autocomplete="off"></label>
      <label>${escapeHtml(t('offsite.rest_password', 'Password on the backup server'))}<input name="rest_password" type="password" maxlength="256" autocomplete="new-password"></label>
    </div>
    <fieldset><legend>${escapeHtml(t('offsite.what', 'Folders to back up'))}</legend>${shares
      .map((s) => `<label class="offsite-check"><input type="checkbox" name="paths" value="${escapeHtml(s.path)}"> ${escapeHtml(s.name)}</label>`)
      .join('')}</fieldset>
    <label>${escapeHtml(t('offsite.daily', 'Daily versions'))}<input name="daily" type="number" min="0" max="1000" value="7"></label>
    <label>${escapeHtml(t('offsite.weekly', 'Weekly'))}<input name="weekly" type="number" min="0" max="1000" value="4"></label>
    <label>${escapeHtml(t('offsite.monthly', 'Monthly'))}<input name="monthly" type="number" min="0" max="1000" value="12"></label>
    <label>${escapeHtml(t('offsite.hour', 'Every day at'))}<input name="hour" type="number" min="0" max="23" value="2"></label>
    <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('offsite.add', 'Add offsite backup'))}</button>
  </form>`;
}

export function isRestLocation(value) {
  return String(value || '').trim().startsWith('rest:');
}

/** The REST server's user and password, sent only for a rest: destination. */
export function restSignIn(f) {
  if (!isRestLocation(f.get('location'))) return {};
  return { rest_user: String(f.get('rest_user') || '').trim(), rest_password: String(f.get('rest_password') || '') };
}

function slug(name) {
  return (
    String(name)
      .toLowerCase()
      .normalize('NFKD')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 40) || `backup-${Date.now()}`
  );
}

/** REL-17: without its key nobody can read the backup, so the full kit leaves the NAS right away,
 * and the Overview keeps asking until it has been saved. */
export async function offerRecoveryKit(repo, onSaved = null) {
  let kit;
  try {
    kit = await api.get(`/api/offsite/repos/${encodeURIComponent(repo.id)}/kit`);
  } catch (e) {
    showToast(t('offsite.added', 'Offsite backup ready. Keep a copy of its recovery key somewhere safe.'), 'success');
    return;
  }
  const saved = async () => {
    await api.post(`/api/offsite/repos/${encodeURIComponent(repo.id)}/kit-saved`, {}).catch(() => {});
    if (onSaved) onSaved();
  };
  showConfirmToast(
    t('offsite.kit_title', 'Save the recovery key now'),
    t('offsite.kit_msg_full', 'Without this kit nobody can read the backup, not even you, if this NAS is lost or broken. It holds the key, where the backup is and how to restore it. Keep it outside the NAS: in a password manager, on a USB stick or printed.'),
    async () => {
      downloadText(kit.filename || `zettnas-recovery-${repo.id}.txt`, kit.text);
      await saved();
    },
    async () => {
      await copyTextToClipboard(kit.text);
      showToast(t('offsite.kit_copied', 'Recovery kit copied. Paste it into your password manager.'), 'info');
      await saved();
    },
    { okText: t('offsite.kit_download', 'Download recovery kit'), cancelText: t('offsite.kit_copy_all', 'Copy the kit') }
  );
}

export function recoveryKitText(repo, key) {
  return [
    'ZettNAS off-site backup: recovery kit',
    `Name: ${repo.name || repo.id}`,
    `Location: ${repo.location}`,
    `Recovery key: ${key}`,
    '',
    'To get your files back on any computer with restic installed:',
    `  export RESTIC_PASSWORD='${key}'`,
    `  restic -r '${repo.location}' snapshots`,
    `  restic -r '${repo.location}' restore latest --target ./restored`,
    'A cloud location also needs its access keys (the same ones set up in ZettNAS).',
    'Keep this file somewhere other than the NAS.',
    '',
  ].join('\n');
}

function downloadText(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function renderOffsite(mount) {
  if (!mount) return;
  let data;
  let shares;
  try {
    data = await api.get('/api/offsite');
    const sh = await api.get('/api/storage/shares').catch(() => ({ shares: [] }));
    shares = (sh.shares || []).filter((s) => s.mountpoint).map((s) => ({ name: s.name, path: s.mountpoint }));
  } catch (e) {
    mount.textContent = e.message || String(e);
    return;
  }
  mount.innerHTML = reposHtml(data) + (data.available ? formHtml(shares) : '');
  const form = mount.querySelector('[data-off-form]');
  const location = /** @type {HTMLInputElement | null} */ (form?.querySelector('[name="location"]') || null);
  const restBox = /** @type {HTMLElement | null} */ (form?.querySelector('[data-off-rest]') || null);
  if (location && restBox) {
    // FEAT-08: a restic REST server (another ZettNAS's backup-target app) takes a sign-in
    location.addEventListener('input', () => {
      restBox.hidden = !isRestLocation(location.value);
    });
  }
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(/** @type {HTMLFormElement} */ (e.target));
    const body = {
      id: slug(f.get('name')),
      name: f.get('name'),
      location: f.get('location'),
      paths: f.getAll('paths'),
      keep: { daily: Number(f.get('daily')), weekly: Number(f.get('weekly')), monthly: Number(f.get('monthly')) },
      hour: Number(f.get('hour')),
      ...restSignIn(f),
    };
    try {
      await api.put('/api/offsite/repos', body);
      await api.post(`/api/offsite/repos/${encodeURIComponent(body.id)}/init`, {});
      renderOffsite(mount);
      await offerRecoveryKit(body);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  mount.onclick = async (e) => {
    const b = e.target.closest('[data-off]');
    if (!b) return;
    const id = encodeURIComponent(b.dataset.id);
    const act = b.dataset.off;
    try {
      if (act === 'backup') {
        await api.post(`/api/offsite/repos/${id}/backup`, {});
        showToast(t('offsite.started', 'Backup started; it shows in Jobs.'), 'info');
      } else if (act === 'check') {
        await api.post(`/api/offsite/repos/${id}/check`, {});
        showToast(t('offsite.verified', 'The backup is readable and complete.'), 'success');
      } else if (act === 'kit') {
        await offerRecoveryKit({ id: b.dataset.id }, () => renderOffsite(mount));
        return;
      } else if (act === 'forget') {
        showConfirmToast(t('offsite.forget_confirm', 'Forget this backup in ZettNAS? The backup itself stays where it is.'), async () => {
          await api.delete(`/api/offsite/repos/${id}`);
          renderOffsite(mount);
        });
        return;
      } else if (act === 'versions') {
        openVersions(b.dataset.id);
        return;
      }
      renderOffsite(mount);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };
}

export function versionsHtml(versions) {
  return `<ul class="offsite-list">${versions
    .map(
      (v) => `<li class="offsite-version"><span>${escapeHtml(formatDateTime(v.time))}</span><span class="offsite-meta">${escapeHtml(v.paths.join(', '))}</span>
        <button type="button" class="btn-pill-toggle is-small" data-ver="${escapeHtml(v.id)}" data-path="${escapeHtml(v.paths[0] || '/')}">${escapeHtml(t('offsite.open', 'Open'))}</button></li>`,
    )
    .join('')}</ul>`;
}

export function filesHtml(entries, path) {
  const parent = path.split('/').slice(0, -1).join('/') || '/';
  return `<p class="offsite-meta">${escapeHtml(path)}</p><ul class="offsite-list">
    <li><button type="button" class="btn-pill-toggle is-small is-ghost" data-open="${escapeHtml(parent)}">↩ ${escapeHtml(t('snap.up', 'Up one folder'))}</button></li>
    ${entries
      .map(
        (e) => `<li class="offsite-file">${
          e.is_dir
            ? `<button type="button" class="snap-entry is-dir" data-open="${escapeHtml(e.path)}">${escapeHtml(e.name)}/</button>`
            : `<span class="snap-entry">${escapeHtml(e.name)} <span class="offsite-meta">${escapeHtml(formatBytes(e.size))}</span></span>`
        }
        <button type="button" class="btn-pill-toggle is-small" data-restore="${escapeHtml(e.path)}">${escapeHtml(t('offsite.restore', 'Restore'))}</button></li>`,
      )
      .join('')}</ul>`;
}

async function openVersions(repoId) {
  let dlg = document.getElementById('offsite-versions');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'offsite-versions';
    dlg.className = 'snapshot-browser';
    document.body.appendChild(dlg);
  }
  const id = encodeURIComponent(repoId);
  let version = null;
  dlg.innerHTML = `<header class="snap-head"><h2>${escapeHtml(t('offsite.versions_title', 'Backup versions'))}</h2>
    <button type="button" class="btn-pill-toggle is-ghost is-small" data-close>${escapeHtml(t('diagnostics.close_btn', 'Close'))}</button></header>
    <p class="snap-help">${escapeHtml(t('offsite.restore_help', 'Restored files go into a "Restored from backup" folder next to the originals; nothing is overwritten.'))}</p>
    <div class="snap-body">${escapeHtml(t('ui.loading', 'Loading...'))}</div>`;
  const body = () => dlg.querySelector('.snap-body');
  const showFiles = async (path) => {
    const { entries } = await api.get(`/api/offsite/repos/${id}/snapshots/${encodeURIComponent(version)}/browse?path=${encodeURIComponent(path)}`);
    body().innerHTML = filesHtml(entries, path);
  };
  dlg.onclick = async (e) => {
    try {
      if (e.target.closest('[data-close]')) return dlg.close();
      const ver = e.target.closest('[data-ver]');
      const open = e.target.closest('[data-open]');
      const rest = e.target.closest('[data-restore]');
      if (ver) {
        version = ver.dataset.ver;
        await showFiles(ver.dataset.path);
      } else if (open) await showFiles(open.dataset.open);
      else if (rest) {
        const path = rest.dataset.restore;
        const dir = path.split('/').slice(0, -1).join('/');
        const target = `${dir || ''}/Restored from backup ${new Date().toISOString().slice(0, 10)}`;
        const r = await api.post(`/api/offsite/repos/${id}/snapshots/${encodeURIComponent(version)}/restore`, { path, target });
        showToast(t('offsite.restore_started', 'Restoring into {path}; it shows in Jobs.', { path: r.restored_to }), 'info');
      }
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  try {
    const { snapshots } = await api.get(`/api/offsite/repos/${id}/snapshots`);
    body().innerHTML = snapshots.length ? versionsHtml(snapshots) : escapeHtml(t('offsite.no_versions', 'No versions yet: run a backup first.'));
  } catch (err) {
    body().textContent = err.message || String(err);
  }
}
