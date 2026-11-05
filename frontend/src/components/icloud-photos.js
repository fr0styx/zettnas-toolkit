/**
 * Download from iCloud Photos (NFEAT-3, D14): sign in with an Apple ID and the code Apple sends,
 * then bring every photo home into a folder, by year and month. The password is used once and
 * not kept; the download runs as a job.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { formatDateTime } from '../format.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import '../styles/photo-import-lazy.css';

const ID = 'modal-photo-import'; // one photo dialog at a time, sharing its look

function close() {
  document.getElementById(ID)?.remove();
}

function shell(body) {
  close();
  const modal = document.createElement('div');
  modal.id = ID;
  modal.className = 'dlg-modeless open';
  modal.innerHTML = `
    <div class="smart-modal-window phi-window" role="dialog" aria-labelledby="ic-title" data-dock-icon="#i-image">
      <div class="smart-modal-header">
        <span class="smart-modal-title" id="ic-title"><span aria-hidden="true">☁️</span> ${escapeHtml(t('ic.title', 'Download from iCloud Photos'))}</span>
        <div class="os-window-controls">
          <button type="button" id="ic-close" class="win-btn close-btn" title="${escapeHtml(t('diagnostics.close_btn', 'Close'))}" aria-label="${escapeHtml(t('diagnostics.close_btn', 'Close'))}"></button>
        </div>
      </div>
      <div class="smart-modal-body phi-body" id="ic-body"></div>
    </div>`;
  // built from escaped pieces by the views below (ARC-31)
  /** @type {HTMLElement} */ (modal.querySelector('#ic-body')).innerHTML = body;
  document.body.appendChild(modal);
  modal.querySelector('#ic-close').addEventListener('click', close);
  modal.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
  });
  return modal;
}

const actions = (...buttons) => `<div class="phi-actions">${buttons.join('')}</div>`;
const button = (id, label, primary = false) =>
  `<button type="button" class="btn-pill-toggle${primary ? ' active is-primary' : ''}" id="${id}">${escapeHtml(label)}</button>`;

/** What the last download did, in a sentence. */
export function lastDownloadText(last) {
  if (!last) return '';
  return t('ic.last', 'Last download {when}: {imported} brought home, {duplicates} already there.', {
    when: formatDateTime(last.at * 1000),
    imported: last.imported || 0,
    duplicates: last.duplicates || 0,
  });
}

function signInView(folder, st) {
  const modal = shell(`
    ${st.error ? `<p class="phi-found">${escapeHtml(t('ic.again', 'Apple asks you to sign in again.'))}</p>` : ''}
    <label class="phi-label" for="ic-id">${escapeHtml(t('ic.apple_id', 'Apple ID'))}</label>
    <div class="phi-row"><input class="phi-input" id="ic-id" type="email" autocomplete="username" spellcheck="false" value="${escapeHtml(st.apple_id || '')}" /></div>
    <label class="phi-label" for="ic-pw">${escapeHtml(t('ic.password', 'Password'))}</label>
    <div class="phi-row"><input class="phi-input" id="ic-pw" type="password" autocomplete="current-password" /></div>
    <p class="phi-note">${escapeHtml(t('ic.pw_note', 'The password is used for this sign-in only and is not kept. If Advanced Data Protection is on, turn on "Access iCloud Data on the Web" in the iPhone\'s iCloud settings first.'))}</p>
    ${actions(button('ic-cancel', t('common.cancel', 'Cancel')), button('ic-sign-in', t('ic.sign_in', 'Sign in'), true))}`);
  modal.querySelector('#ic-cancel').addEventListener('click', close);
  const go = /** @type {HTMLButtonElement} */ (modal.querySelector('#ic-sign-in'));
  const submit = async () => {
    const appleId = /** @type {HTMLInputElement} */ (modal.querySelector('#ic-id')).value.trim();
    const pw = /** @type {HTMLInputElement} */ (modal.querySelector('#ic-pw'));
    go.disabled = true;
    try {
      render(folder, await api.post('/api/media/icloud/sign-in', { apple_id: appleId, password: pw.value }));
    } catch (err) {
      pw.value = '';
      go.disabled = false;
      showToast(/** @type {Error} */ (err).message, 'error');
    }
  };
  go.addEventListener('click', submit);
  modal.querySelector('#ic-pw').addEventListener('keydown', (/** @type {KeyboardEvent} */ e) => { if (e.key === 'Enter') submit(); });
  /** @type {HTMLElement} */ (modal.querySelector(st.apple_id ? '#ic-pw' : '#ic-id')).focus();
}

function codeView(folder) {
  const modal = shell(`
    <p class="phi-found">${escapeHtml(t('ic.code_sent', 'Apple sent a code to your iPhone, iPad or Mac.'))}</p>
    <label class="phi-label" for="ic-code">${escapeHtml(t('ic.code', 'Code'))}</label>
    <div class="phi-row"><input class="phi-input" id="ic-code" inputmode="numeric" autocomplete="one-time-code" maxlength="12" /></div>
    ${actions(button('ic-cancel', t('common.cancel', 'Cancel')), button('ic-verify', t('ic.verify', 'Continue'), true))}`);
  modal.querySelector('#ic-cancel').addEventListener('click', close);
  const go = /** @type {HTMLButtonElement} */ (modal.querySelector('#ic-verify'));
  const submit = async () => {
    go.disabled = true;
    try {
      render(folder, await api.post('/api/media/icloud/code', { code: /** @type {HTMLInputElement} */ (modal.querySelector('#ic-code')).value }));
    } catch (err) {
      go.disabled = false;
      showToast(/** @type {Error} */ (err).message, 'error');
    }
  };
  go.addEventListener('click', submit);
  modal.querySelector('#ic-code').addEventListener('keydown', (/** @type {KeyboardEvent} */ e) => { if (e.key === 'Enter') submit(); });
  /** @type {HTMLElement} */ (modal.querySelector('#ic-code')).focus();
}

function readyView(folder, st) {
  const modal = shell(`
    <p class="phi-found">${escapeHtml(t('ic.signed_in', 'Signed in as {apple_id}.', { apple_id: st.apple_id }))}</p>
    ${st.downloading ? `<p class="phi-note">${escapeHtml(t('ic.running', 'A download is running. You can follow it in Jobs.'))}</p>` : ''}
    <label class="phi-label" for="ic-dest">${escapeHtml(t('phi.dest', 'Put the photos in'))}</label>
    <div class="phi-row">
      <input class="phi-input" id="ic-dest" type="text" spellcheck="false" value="${escapeHtml(folder)}" />
      ${button('ic-browse', t('phi.browse', 'Choose…'))}
    </div>
    <p class="phi-note">${escapeHtml(t('ic.note', 'Every photo goes into a folder for the year and month it was taken. Photos brought home before are not downloaded again.'))}</p>
    ${st.last_download ? `<p class="phi-note" id="ic-last">${escapeHtml(lastDownloadText(st.last_download))}</p>` : ''}
    ${actions(button('ic-sign-out', t('ic.sign_out', 'Sign out')), button('ic-start', t('ic.start', 'Download'), true))}`);
  const dest = /** @type {HTMLInputElement} */ (modal.querySelector('#ic-dest'));
  const start = /** @type {HTMLButtonElement} */ (modal.querySelector('#ic-start'));
  start.disabled = Boolean(st.downloading);
  modal.querySelector('#ic-browse').addEventListener('click', () => {
    const browse = /** @type {any} */ (window).openFolderBrowser;
    if (typeof browse === 'function') browse(dest.value || folder, (picked) => { if (picked) dest.value = picked; });
  });
  start.addEventListener('click', async () => {
    start.disabled = true;
    try {
      await api.post('/api/media/icloud/download', { destination: dest.value.trim() });
      showToast(t('phi.started', 'The import started. You can follow it in Jobs.'), 'success');
      close();
    } catch (err) {
      start.disabled = false;
      showToast(/** @type {Error} */ (err).message, 'error');
    }
  });
  modal.querySelector('#ic-sign-out').addEventListener('click', async () => {
    try {
      render(folder, await api.delete('/api/media/icloud'));
    } catch (err) {
      showToast(/** @type {Error} */ (err).message, 'error');
    }
  });
}

function render(folder, st) {
  if (st.needs_code) codeView(folder);
  else if (st.signed_in) readyView(folder, st);
  else signInView(folder, st);
}

/** Opens the dialog; `folder` is where the photos go unless the person picks another. */
export async function openICloudPhotos(folder) {
  shell(`<p class="phi-found">${escapeHtml(t('ic.looking', 'Checking the iCloud sign-in…'))}</p>`);
  try {
    render(folder, await api.get('/api/media/icloud'));
  } catch (err) {
    const body = document.getElementById('ic-body');
    if (body) body.textContent = /** @type {Error} */ (err).message;
  }
}
