/**
 * Bring back a whole Kiboto from its off-site backup's recovery kit (RES-7): connect the backup,
 * bring back the settings (Kiboto restarts to apply them), then put the files back where they were.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';

/** The kit step: paste it or pick the file. */
export function kitHtml() {
  return `<p class="snap-help">${escapeHtml(t('restorebox.kit_help', 'Paste the recovery kit of your off-site backup, or choose the file you saved. Kiboto only reads the backup; it changes nothing in it.'))}</p>
    <label class="setup-label" for="restorebox-kit">${escapeHtml(t('restorebox.kit_label', 'Recovery kit'))}</label>
    <textarea id="restorebox-kit" class="input-text restorebox-kit" rows="8" spellcheck="false" autocomplete="off"></textarea>
    <div class="restorebox-row">
      <input type="file" id="restorebox-file" accept=".txt,text/plain" aria-label="${escapeHtml(t('restorebox.kit_file', 'Recovery kit file'))}">
      <button type="button" class="btn-pill-toggle is-primary" data-rb="connect">${escapeHtml(t('restorebox.connect', 'Connect the backup'))}</button>
    </div>`;
}

/** What is in the backup, and the two steps: settings first, then files. */
export function planHtml(state) {
  const { repo, versions = [], settings = [] } = state;
  const newest = versions[0];
  const copy = settings[0];
  const settingsLine = copy
    ? t('restorebox.settings_from', 'Settings saved {when}', { when: formatDateTime(copy.time) })
    : t('restorebox.no_settings', 'This backup holds no copy of the settings (it was made before Kiboto 2.0). Restore an uploaded settings backup instead, or set people and shares up again.');
  const filesLine = newest
    ? t('restorebox.files_from', 'Files backed up {when}: {paths}', { when: formatDateTime(newest.time), paths: (newest.paths || []).join(', ') })
    : t('restorebox.no_versions', 'This backup has no versions yet.');
  return `<p class="restorebox-name"><strong>${escapeHtml(repo.name || repo.id)}</strong> <span class="offsite-meta">${escapeHtml(repo.location || '')}</span></p>
    <ol class="restorebox-steps">
      <li><p>${escapeHtml(settingsLine)}</p>
        <p class="snap-help">${escapeHtml(t('restorebox.settings_help', 'People, passwords, shares, apps and backups come back as they were. Kiboto restarts to apply them; then sign in with your old password.'))}</p>
        <button type="button" class="btn-pill-toggle is-primary" data-rb="settings"${copy ? '' : ' disabled'}>${escapeHtml(t('restorebox.settings_btn', 'Bring back the settings'))}</button></li>
      <li><p>${escapeHtml(filesLine)}</p>
        <p class="snap-help">${escapeHtml(t('restorebox.files_help', 'Every folder goes back where it was. Files that are already there stay as they are, so this can run again if it stops.'))}</p>
        <button type="button" class="btn-pill-toggle" data-rb="files"${newest ? '' : ' disabled'}>${escapeHtml(t('restorebox.files_btn', 'Bring back the files'))}</button></li>
    </ol>`;
}

/** Waits for Kiboto to go down and come back after the restart, then reloads the page. */
export async function waitForRestart({ fetchImpl = fetch, reload = () => window.location.reload(), sleep = (ms) => new Promise((r) => setTimeout(r, ms)), tries = 90 } = {}) {
  let wentDown = false;
  for (let i = 0; i < tries; i += 1) {
    await sleep(2000);
    let up;
    try {
      up = (await fetchImpl('/api/health', { cache: 'no-store' })).ok;
    } catch {
      up = false;
    }
    if (!up) wentDown = true;
    else if (wentDown) {
      reload();
      return true;
    }
  }
  return false;
}

/** Closes the dialog (an open attribute where showModal is missing). */
export function closeDialog(dlg) {
  if (typeof dlg.close === 'function') dlg.close();
  else dlg.removeAttribute('open');
}

function dialog() {
  let dlg = /** @type {HTMLDialogElement | null} */ (document.getElementById('restore-box'));
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'restore-box';
    dlg.className = 'snapshot-browser restorebox';
    document.body.appendChild(dlg);
  }
  return dlg;
}

/** Opens the restore. With a repo id the backup is already connected (Backup → Off-site). */
export async function openRestoreBox(repoId = null, onDone = null) {
  const dlg = dialog();
  /** @type {{repo: any, versions: any[], settings: any[]}} */
  let state = { repo: null, versions: [], settings: [] };
  dlg.innerHTML = `<header class="snap-head"><h2>${escapeHtml(t('restorebox.title', 'Restore from a recovery kit'))}</h2>
    <button type="button" class="btn-pill-toggle is-ghost is-small" data-close>${escapeHtml(t('diagnostics.close_btn', 'Close'))}</button></header>
    <div class="snap-body">${repoId ? escapeHtml(t('ui.loading', 'Loading...')) : kitHtml()}</div>`;
  const body = () => /** @type {HTMLElement} */ (dlg.querySelector('.snap-body'));
  const show = () => {
    body().innerHTML = planHtml(state);
  };
  dlg.onchange = async (e) => {
    const input = /** @type {HTMLInputElement} */ (e.target);
    if (input.id !== 'restorebox-file' || !input.files?.[0]) return;
    const area = /** @type {HTMLTextAreaElement | null} */ (dlg.querySelector('#restorebox-kit'));
    if (area) area.value = await input.files[0].text();
  };
  dlg.onclick = async (e) => {
    const el = /** @type {Element} */ (e.target);
    if (el.closest('[data-close]')) {
      closeDialog(dlg);
      return;
    }
    const btn = /** @type {HTMLButtonElement | null} */ (el.closest('[data-rb]'));
    if (!btn) return;
    const act = btn.getAttribute('data-rb');
    btn.disabled = true;
    try {
      if (act === 'connect') {
        const kit = /** @type {HTMLTextAreaElement} */ (dlg.querySelector('#restorebox-kit')).value;
        state = await api.post('/api/offsite/connect-kit', { kit });
        show();
        if (onDone) onDone();
        return;
      }
      const id = encodeURIComponent(state.repo.id);
      if (act === 'settings') {
        const r = await api.post(`/api/offsite/repos/${id}/restore-settings`, { snapshot: 'latest' });
        body().innerHTML = `<p>${escapeHtml(
          r.restarting
            ? t('restorebox.restarting', 'The settings are back. Kiboto is restarting to apply them; this page reloads by itself. Then sign in with your old password and open Backup → Off-site → Bring back everything for the files.')
            : t('restorebox.restart_needed', 'The settings are back. Restart the Kiboto container to apply them, then sign in with your old password and open Backup → Off-site → Bring back everything for the files.'),
        )}</p>`;
        if (r.restarting) waitForRestart();
      } else if (act === 'files') {
        const r = await api.post(`/api/offsite/repos/${id}/restore-all`, { snapshot: 'latest' });
        showToast(t('restorebox.files_started', 'Bringing back {n, plural, one {# folder} other {# folders}}; it shows in Jobs.', { n: (r.paths || []).length }), 'info');
        closeDialog(dlg);
      }
    } catch (err) {
      showToast(err.message || String(err), 'error');
    } finally {
      btn.disabled = false;
    }
  };
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  if (repoId) {
    try {
      const id = encodeURIComponent(repoId);
      const [{ repos = [] }, { snapshots = [] }, { copies = [] }] = await Promise.all([
        api.get('/api/offsite'),
        api.get(`/api/offsite/repos/${id}/snapshots`),
        api.get(`/api/offsite/repos/${id}/settings-copies`),
      ]);
      state = { repo: repos.find((r) => r.id === repoId) || { id: repoId }, versions: snapshots, settings: copies };
      show();
    } catch (err) {
      body().textContent = err.message || String(err);
    }
  }
  return dlg;
}
