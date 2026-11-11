/**
 * Uploads into the File Explorer (SET-05). One path for the Upload button, the phone's "+" and a
 * drop of files or folders: progress and Cancel in the transfer centre, and every failure said.
 * A drop used to take a second, weaker path: one request per file, no progress, no cancel, and a
 * failed file showed nothing.
 *
 * A name that is taken is never replaced without a question. The person is asked each time:
 * Replace, Keep both or Skip, with a tick to use the answer for the rest of this upload (the
 * owner's decision S16). The server answers 409 "name_taken" before it stores a byte.
 */
import { api, ApiError } from '../api.js';
import { escapeHtml } from '../utils.js';
import { showToast } from '../toast.js';
import { t } from '../i18n.js';
import { transferCenter } from './transfer-center.js';

export const CHUNK_SIZE = 16 * 1024 * 1024;

/**
 * @typedef {{ file: File, dir: string }} UploadItem
 * @typedef {'ask' | 'keep_both' | 'replace'} OnConflict
 * @typedef {{ choice: 'replace' | 'keep_both' | 'skip', forRest: boolean }} Answer
 */

/**
 * The address of a small upload: the folder and the name in the query, the file as the body.
 * @param {string} dir
 * @param {string} name
 * @param {OnConflict} [onConflict]
 */
export function uploadUrl(dir, name, onConflict) {
  const base = `/api/fs/upload?path=${encodeURIComponent(dir)}&filename=${encodeURIComponent(name)}`;
  return onConflict ? `${base}&on_conflict=${onConflict}` : base;
}

/**
 * True for the server's "a file of that name is already there".
 * @param {any} err
 */
export function isNameTaken(err) {
  return Boolean(err) && err.status === 409 && err.error === 'name_taken';
}

/**
 * Sends one file. Throws what the server answered; a taken name throws before any byte is sent.
 * @param {File} file
 * @param {string} dir
 * @param {OnConflict} onConflict
 * @param {(sent: number) => void} onProgress
 * @param {() => boolean} isCancelled
 */
export async function sendOne(file, dir, onConflict, onProgress, isCancelled) {
  if (file.size <= CHUNK_SIZE) {
    const res = await api.postRaw(uploadUrl(dir, file.name, onConflict), file);
    if (!res.ok) throw await ApiError.from(res);
    return;
  }
  const init = await api.post('/api/fs/upload/init', {
    filename: file.name,
    destination_dir: dir,
    total_size: file.size,
    chunk_size: CHUNK_SIZE,
    on_conflict: onConflict,
  });
  if (!init || !init.upload_id) throw new Error(t('fm.upload_no_start', 'The upload could not be started.'));
  const id = encodeURIComponent(init.upload_id);
  for (let c = 0, start = 0; start < file.size; c++, start += CHUNK_SIZE) {
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const res = await api.postRaw(`/api/fs/upload/chunk?upload_id=${id}&chunk_index=${c}`, file.slice(start, end), {
      headers: { 'Content-Type': 'application/octet-stream' },
    });
    if (!res.ok) throw await ApiError.from(res);
    onProgress(end);
    if (isCancelled()) throw new Error('cancelled');
  }
  await api.post('/api/fs/upload/complete', { upload_id: init.upload_id });
}

/**
 * Asks what to do with a file whose name is taken. Closing the dialog skips that one file.
 * @param {string} name
 * @param {string} dir
 * @returns {Promise<Answer>}
 */
export function askNameTaken(name, dir) {
  return new Promise((resolve) => {
    const folder = dir.replace(/\/+$/, '').split('/').pop() || dir;
    const modal = document.createElement('div');
    modal.className = 'smart-modal-backdrop open fm-upload-taken';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'fm-upload-taken-title');
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="fm-collision-dialog glassmorphic-card fmx-x-3">
        <h3 class="fmx-row-fs16-bold-strong" id="fm-upload-taken-title">${escapeHtml(t('fm.upload_taken_title', '“{name}” is already there', { name }))}</h3>
        <p class="fmx-xs-muted">${escapeHtml(t('fm.upload_taken_msg', 'A file with this name is already in “{folder}”. “Replace” puts the one that is there in the Recycle Bin. “Keep Both” saves the new one under a numbered name.', { folder }))}</p>
        <label class="fmx-row-xs-muted"><input type="checkbox" class="fm-upload-for-rest" /> <span>${escapeHtml(t('fm.upload_for_rest', 'Do the same for the rest of this upload'))}</span></label>
        <div class="fmx-row-9">
          <button type="button" class="btn-pill-toggle fmx-box-2" data-choice="skip">${escapeHtml(t('fm.skip', 'Skip'))}</button>
          <button type="button" class="btn-pill-toggle is-primary" data-choice="keep_both">${escapeHtml(t('fm.keep_both', 'Keep Both'))}</button>
          <button type="button" class="btn-pill-toggle is-danger" data-choice="replace">${escapeHtml(t('fm.upload_replace', 'Replace'))}</button>
        </div>
      </div>`;
    const back = /** @type {HTMLElement | null} */ (document.activeElement);
    /** @param {Answer['choice']} choice */
    const done = (choice) => {
      const forRest = Boolean(/** @type {HTMLInputElement | null} */ (modal.querySelector('.fm-upload-for-rest'))?.checked);
      modal.remove();
      back?.focus?.();
      resolve({ choice, forRest: choice === 'skip' && !forRest ? false : forRest });
    };
    modal.addEventListener('click', (e) => {
      const btn = /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (e.target).closest('[data-choice]'));
      if (btn) done(/** @type {Answer['choice']} */ (btn.dataset.choice));
    });
    modal.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      modal.remove();
      back?.focus?.();
      resolve({ choice: 'skip', forRest: false }); // Escape skips this one file and decides nothing more
    });
    document.body.appendChild(modal);
    /** @type {HTMLElement | null} */ (modal.querySelector('[data-choice="keep_both"]'))?.focus(); // the answer that loses nothing
  });
}

/**
 * Uploads every item, one after the other, and reports what happened.
 * @param {UploadItem[]} items
 * @param {{ ask?: (name: string, dir: string) => Promise<Answer>, label?: string }} [options]
 * @returns {Promise<{ uploaded: number, skipped: number, failed: number, cancelled: boolean }>}
 */
export async function uploadAll(items, { ask = askNameTaken, label = '' } = {}) {
  const totalBytes = items.reduce((sum, i) => sum + (i.file.size || 0), 0);
  let cancelled = false;
  const job = transferCenter.startLocal({
    kind: 'upload',
    label: label || t('transfers.uploading', 'Uploading {count} file(s) to {dest}', { count: items.length, dest: (items[0]?.dir || '').split('/').pop() || '/' }),
    totalFiles: items.length,
    totalBytes,
    cancel: () => { cancelled = true; },
  });
  /** @type {Answer['choice'] | null} */
  let forRest = null;
  let uploaded = 0;
  let skipped = 0;
  let doneBytes = 0;
  /** @type {string[]} */
  const errors = [];

  for (let i = 0; i < items.length && !cancelled; i++) {
    const { file, dir } = items[i];
    job.progress({ current: file.name });
    /** @type {OnConflict} */
    let policy = forRest === 'replace' || forRest === 'keep_both' ? forRest : 'ask';
    for (;;) {
      try {
        await sendOne(file, dir, policy, (sent) => job.progress({ bytes: doneBytes + sent }), () => cancelled);
        uploaded++;
      } catch (err) {
        if (cancelled) break;
        if (isNameTaken(err) && policy === 'ask') {
          const answer = forRest === 'skip' ? { choice: /** @type {const} */ ('skip'), forRest: true } : await ask(file.name, dir);
          if (answer.forRest) forRest = answer.choice;
          if (answer.choice !== 'skip') {
            policy = answer.choice;
            continue; // send it again, now with the answer
          }
          skipped++;
        } else {
          errors.push(`${file.name}: ${err instanceof Error ? err.message : String(err)}`);
        }
      }
      break;
    }
    doneBytes += file.size || 0;
    job.progress({ files: i + 1, bytes: doneBytes });
  }

  const failed = errors.length;
  if (cancelled) job.finish('cancelled');
  else if (failed && !uploaded) job.finish('failed', errors[0]);
  else job.finish('completed', failed ? t('fm.upload_some_failed', '{count, plural, one {# file could not be uploaded: {first}} other {# files could not be uploaded. The first: {first}}}', { count: failed, first: errors[0] }) : null);
  // a failed upload says so, also when the transfer centre is closed
  if (failed && !cancelled) showToast(t('fm.upload_some_failed', '{count, plural, one {# file could not be uploaded: {first}} other {# files could not be uploaded. The first: {first}}}', { count: failed, first: errors[0] }), 'error');
  else if (skipped && !cancelled) showToast(t('fm.upload_skipped', '{count, plural, one {# file was skipped: its name was taken} other {# files were skipped: their names were taken}}', { count: skipped }), 'info');
  return { uploaded, skipped, failed, cancelled };
}

/**
 * The folders a dropped folder needs, parents first, then its files as upload items.
 * @param {{ file: File, relPath: string }[]} entries what a drop of folders gives
 * @param {string} baseDir
 * @returns {{ dirs: string[], items: UploadItem[] }}
 */
export function planDrop(entries, baseDir) {
  const base = baseDir.replace(/\/+$/, '');
  /** @type {Set<string>} */
  const dirs = new Set();
  const items = entries.map(({ file, relPath }) => {
    const parts = String(relPath || file.name).split('/').filter(Boolean).slice(0, -1);
    let dir = base;
    for (const part of parts) {
      dir = `${dir}/${part}`;
      dirs.add(dir);
    }
    return { file, dir };
  });
  return { dirs: [...dirs].sort((a, b) => a.split('/').length - b.split('/').length || a.localeCompare(b)), items };
}
