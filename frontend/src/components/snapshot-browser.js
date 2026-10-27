/**
 * Snapshot schedules per share, and browsing and restoring files from a snapshot (Batch 6).
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';
import { formatBytes, formatDateTime } from '../format.js';

const EVERY = () => ({
  hourly: t('snap.every_hourly', 'Every hour'),
  daily: t('snap.every_daily', 'Every day'),
  weekly: t('snap.every_weekly', 'Every week'),
});

export function schedulesHtml(schedules, shares) {
  const every = EVERY();
  const rows = schedules.length
    ? schedules
        .map(
          (s) => `<li class="snap-sched-row">
      <span class="snap-sched-share">${escapeHtml(s.share)}</span>
      <span>${escapeHtml(every[s.every] || s.every)} · ${escapeHtml(t('snap.keep_n', 'keep {n}', { n: s.keep }))}${
            s.immutable_days ? ` · <svg class="ic" aria-hidden="true"><use href="#i-shield"/></svg> ${escapeHtml(t('snap.locked_days', 'locked {n} days', { n: s.immutable_days }))}` : ''
          }</span>
      <span class="snap-sched-last">${s.last_run ? escapeHtml(formatDateTime(s.last_run * 1000)) : escapeHtml(t('snap.not_yet', 'not run yet'))}${
            s.last_result && s.last_result !== 'ok' ? ` · ${escapeHtml(s.last_result)}` : ''
          }</span>
      <button type="button" class="btn-pill-toggle is-small" data-snap-run="${escapeHtml(s.share)}">${escapeHtml(t('snap.run_now', 'Snapshot now'))}</button>
      <button type="button" class="btn-pill-toggle is-small is-danger" data-snap-unschedule="${escapeHtml(s.share)}">${escapeHtml(t('snap.remove', 'Remove'))}</button>
    </li>`,
        )
        .join('')
    : `<li class="snap-sched-empty">${escapeHtml(t('snap.no_schedules', 'No share is snapshotted on a schedule yet.'))}</li>`;
  const options = shares.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
  return `<ul class="snap-sched-list">${rows}</ul>
    <form class="snap-sched-form" data-snap-form>
      <label>${escapeHtml(t('snap.share', 'Share'))}<select name="share" required>${options}</select></label>
      <label>${escapeHtml(t('snap.how_often', 'How often'))}<select name="every">${Object.entries(every)
        .map(([k, v]) => `<option value="${k}"${k === 'daily' ? ' selected' : ''}>${escapeHtml(v)}</option>`)
        .join('')}</select></label>
      <label>${escapeHtml(t('snap.keep', 'Keep'))}<input name="keep" type="number" min="1" max="1000" value="14"></label>
      <label title="${escapeHtml(t('snap.lock_help', 'Days each snapshot cannot be deleted, even by an administrator; protects against ransomware.'))}">${escapeHtml(
        t('snap.lock', 'Lock for days'),
      )}<input name="immutable_days" type="number" min="0" max="3650" value="0"></label>
      <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('snap.add_schedule', 'Snapshot this share'))}</button>
    </form>`;
}

export async function renderSnapshotSchedules(mount) {
  if (!mount) return;
  let schedules;
  let shares;
  try {
    const [s, sh] = await Promise.all([api.get('/api/snapshots/schedules'), api.get('/api/storage/shares').catch(() => ({ shares: [] }))]);
    schedules = s.schedules || [];
    shares = (sh.shares || []).map((x) => x.name).filter(Boolean);
    if (s.available === false) {
      // REL-4: no schedule is offered where snapshots can't be taken
      mount.textContent = t('snap.unavailable', "Snapshots aren't available on this host: the btrfs and ZFS tools are missing.");
      return;
    }
  } catch (e) {
    mount.textContent = t('snap.load_failed', 'Snapshot schedules could not be loaded.');
    return;
  }
  mount.innerHTML = schedulesHtml(schedules, shares);
  mount.querySelector('[data-snap-form]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api.put('/api/snapshots/schedules', {
        share: f.get('share'),
        every: f.get('every'),
        keep: Number(f.get('keep')),
        immutable_days: Number(f.get('immutable_days')),
      });
      showToast(t('snap.saved', 'Snapshots scheduled.'), 'success');
      renderSnapshotSchedules(mount);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  mount.querySelectorAll('[data-snap-run]').forEach((b) =>
    b.addEventListener('click', async () => {
      const res = await api.post(`/api/snapshots/schedules/${encodeURIComponent(b.dataset.snapRun)}/run`, {});
      showToast(res.ok ? t('snap.taken', 'Snapshot {name} taken.', { name: res.name }) : t('snap.failed', 'The snapshot failed: {why}', { why: res.detail || '' }), res.ok ? 'success' : 'error');
      renderSnapshotSchedules(mount);
    }),
  );
  mount.querySelectorAll('[data-snap-unschedule]').forEach((b) =>
    b.addEventListener('click', async () => {
      await api.delete(`/api/snapshots/schedules/${encodeURIComponent(b.dataset.snapUnschedule)}`);
      renderSnapshotSchedules(mount);
    }),
  );
}

export function entriesHtml(listing) {
  const up = listing.path
    ? `<li><button type="button" class="snap-entry is-dir" data-snap-open="${escapeHtml(listing.path.split('/').slice(0, -1).join('/'))}">↩ ${escapeHtml(t('snap.up', 'Up one folder'))}</button></li>`
    : '';
  const rows = listing.entries
    .map((e) => {
      const rel = (listing.path ? `${listing.path}/` : '') + e.name;
      return `<li class="snap-entry-row">
        ${
          e.is_dir
            ? `<button type="button" class="snap-entry is-dir" data-snap-open="${escapeHtml(rel)}"><svg class="ic" aria-hidden="true"><use href="#i-storage"/></svg> ${escapeHtml(e.name)}</button>`
            : `<span class="snap-entry">${escapeHtml(e.name)} <span class="snap-entry-meta">${escapeHtml(formatBytes(e.size))}</span></span>`
        }
        <button type="button" class="btn-pill-toggle is-small" data-snap-restore="${escapeHtml(rel)}">${escapeHtml(t('snap.restore_copy', 'Restore a copy'))}</button>
        <button type="button" class="btn-pill-toggle is-small is-danger" data-snap-replace="${escapeHtml(rel)}">${escapeHtml(t('snap.replace', 'Replace current'))}</button>
      </li>`;
    })
    .join('');
  return `<p class="snap-path">/${escapeHtml(listing.path || '')}</p><ul class="snap-entries">${up}${rows}</ul>`;
}

export async function openSnapshotBrowser(name) {
  let dlg = document.getElementById('snapshot-browser');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'snapshot-browser';
    dlg.className = 'snapshot-browser';
    dlg.setAttribute('aria-labelledby', 'snapshot-browser-title');
    document.body.appendChild(dlg);
  }
  const body = () => dlg.querySelector('.snap-body');
  dlg.innerHTML = `<header class="snap-head"><h2 id="snapshot-browser-title">${escapeHtml(t('snap.browse_title', 'Files in {name}', { name }))}</h2>
    <button type="button" class="btn-pill-toggle is-ghost is-small" data-snap-close>${escapeHtml(t('diagnostics.close_btn', 'Close'))}</button></header>
    <p class="snap-help">${escapeHtml(t('snap.browse_help', 'Restore a copy puts the old version next to the current one; nothing is overwritten.'))}</p>
    <div class="snap-body"></div>`;
  const show = async (path) => {
    try {
      body().innerHTML = entriesHtml(await api.get(`/api/snapshots/${encodeURIComponent(name)}/browse?path=${encodeURIComponent(path || '')}`));
    } catch (e) {
      body().textContent = e.message || String(e);
    }
  };
  dlg.onclick = async (e) => {
    const open = e.target.closest('[data-snap-open]');
    const restore = e.target.closest('[data-snap-restore]');
    const replace = e.target.closest('[data-snap-replace]');
    if (e.target.closest('[data-snap-close]')) dlg.close();
    else if (open) show(open.dataset.snapOpen);
    else if (restore || replace) {
      const rel = (restore || replace).dataset[restore ? 'snapRestore' : 'snapReplace'];
      const go = async () => {
        try {
          const res = await api.post(`/api/snapshots/${encodeURIComponent(name)}/restore`, { path: rel, overwrite: Boolean(replace) });
          showToast(t('snap.restored', 'Restored as {path}', { path: res.restored }), 'success');
        } catch (err) {
          showToast(err.message || String(err), 'error');
        }
      };
      if (replace) showConfirmToast(t('snap.replace_confirm', 'Replace the current {path} with the version from this snapshot?', { path: rel }), go);
      else go();
    }
  };
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  show('');
}
