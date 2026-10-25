/**
 * Previous versions of a file (missing feature 7): the copies its snapshots keep, newest first,
 * to open, restore beside the file, or put back in its place.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml, trapFocus } from '../utils.js';
import { formatBytes, formatDateTime } from '../format.js';
import { showToast, showConfirmToast } from '../toast.js';

const DIALOG_ID = 'fm-versions-dialog';

function close(dialog, release, opener) {
  release?.();
  dialog.remove();
  if (opener && opener.isConnected) opener.focus({ preventScroll: true });
}

export function versionUrl(path, id) {
  return `/api/fs/versions/download?path=${encodeURIComponent(path)}&version=${encodeURIComponent(id)}`;
}

export function versionsHtml(name, versions) {
  if (!versions.length) {
    return `<p class="fm-versions-empty">${escapeHtml(t('fm.versions_none', 'No earlier versions of {name}. They appear once the folder it is in has snapshots (Storage → Snapshots).', { name }))}</p>`;
  }
  return `<ul class="fm-versions-list">${versions
    .map(
      (v) => `<li class="fm-versions-row" data-version="${escapeHtml(v.id)}">
        <div class="fm-versions-when"><strong>${escapeHtml(formatDateTime(v.mtime))}</strong>
          <span>${escapeHtml(formatBytes(v.size))} · ${escapeHtml(t('fm.versions_kept', 'kept {when}', { when: formatDateTime(v.created) }))}</span></div>
        <div class="fm-versions-actions">
          <button type="button" class="btn-pill-toggle" data-act="open">${escapeHtml(t('fm.versions_open', 'Open'))}</button>
          <button type="button" class="btn-pill-toggle" data-act="copy">${escapeHtml(t('fm.versions_restore_copy', 'Restore a copy'))}</button>
          <button type="button" class="btn-pill-toggle" data-act="replace">${escapeHtml(t('fm.versions_replace', 'Replace current'))}</button>
        </div>
      </li>`,
    )
    .join('')}</ul>`;
}

export async function openPreviousVersions(path, name, onChange = null) {
  document.getElementById(DIALOG_ID)?.remove();
  const opener = document.activeElement;
  const dialog = document.createElement('div');
  dialog.id = DIALOG_ID;
  dialog.className = 'fm-versions-dialog';
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-labelledby', `${DIALOG_ID}-title`);
  dialog.innerHTML = `<div class="fm-versions-card">
      <div class="fm-versions-head"><h2 id="${DIALOG_ID}-title">${escapeHtml(t('fm.versions_title', 'Previous versions of {name}', { name }))}</h2>
        <button type="button" class="win-btn close-btn" data-act="close" aria-label="${escapeHtml(t('diagnostics.close_btn', 'Close'))}"></button></div>
      <div class="fm-versions-body" aria-live="polite">${escapeHtml(t('fm.versions_loading', 'Looking for earlier versions…'))}</div>
    </div>`;
  document.body.appendChild(dialog);
  let release = null;
  const done = () => close(dialog, release, opener);
  release = trapFocus(dialog, done);
  dialog.querySelector('[data-act="close"]').focus();

  const body = dialog.querySelector('.fm-versions-body');
  let versions;
  try {
    versions = (await api.get(`/api/fs/versions?path=${encodeURIComponent(path)}`))?.versions || [];
  } catch (err) {
    body.textContent = t('fm.versions_failed', 'Could not look for earlier versions: {error}', { error: err.message });
    return dialog;
  }
  body.innerHTML = versionsHtml(name, versions);

  dialog.addEventListener('click', async (e) => {
    if (e.target === dialog) return done();
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'close') return done();
    const id = btn.closest('[data-version]')?.dataset.version;
    if (!id) return;
    if (act === 'open') {
      window.open(versionUrl(path, id), '_blank', 'noopener');
      return;
    }
    const restore = async (overwrite) => {
      try {
        const res = await api.post('/api/fs/versions/restore', { path, version: id, overwrite });
        showToast(
          overwrite
            ? t('fm.versions_replaced', '{name} is back to the earlier version', { name })
            : t('fm.versions_copied', 'Restored as {file}', { file: String(res?.path || '').split('/').pop() }),
          'success',
        );
        done();
        onChange?.();
      } catch (err) {
        showToast(t('toast.restore_failed', 'Restore failed: {error}', { error: err.message }), 'error');
      }
    };
    if (act === 'copy') restore(false);
    else if (act === 'replace') {
      showConfirmToast(
        t('fm.versions_replace_title', 'Replace {name}?', { name }),
        t('fm.versions_replace_msg', 'The file as it is now is replaced by this earlier version.'),
        () => restore(true),
        null,
        { okText: t('fm.versions_replace', 'Replace current'), destructive: true },
      );
    }
  });
  return dialog;
}
