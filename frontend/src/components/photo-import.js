/**
 * Bring photos home (NFEAT-3): a Google Takeout or an iCloud Photos export, as .zip parts or
 * unpacked, filed by year and month into a folder on the NAS. The import runs as a job.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { formatBytes } from '../format.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import '../styles/photo-import-lazy.css';

const ID = 'modal-photo-import';

/** What the export holds, in a sentence. */
export function foundText(info) {
  const counts = { photos: info.photos || 0, videos: info.videos || 0, size: formatBytes(info.bytes || 0) };
  if (!counts.photos && !counts.videos) return t('phi.none', 'There are no photos or videos in it.');
  const what = {
    google: t('phi.found_google', 'A Google Photos export'),
    icloud: t('phi.found_icloud', 'An iCloud Photos export'),
  }[info.kind] || t('phi.found_folder', 'A folder');
  return t(
    'phi.found',
    '{what}: {photos, plural, one {# photo} other {# photos}} and {videos, plural, one {# video} other {# videos}} ({size}).',
    { what, ...counts },
  );
}

function close() {
  document.getElementById(ID)?.remove();
}

/** Opens the dialog for the export at `path` (a .zip or a folder). */
export async function openPhotoImport(path) {
  close();
  const modal = document.createElement('div');
  modal.id = ID;
  modal.className = 'dlg-modeless open';
  modal.innerHTML = `
    <div class="smart-modal-window phi-window" role="dialog" aria-labelledby="phi-title" data-dock-icon="#i-image">
      <div class="smart-modal-header">
        <span class="smart-modal-title" id="phi-title"><span aria-hidden="true">🏠</span> ${escapeHtml(t('phi.title', 'Bring photos home'))}</span>
        <div class="os-window-controls">
          <button type="button" id="phi-close" class="win-btn close-btn" title="${escapeHtml(t('diagnostics.close_btn', 'Close'))}" aria-label="${escapeHtml(t('diagnostics.close_btn', 'Close'))}"></button>
        </div>
      </div>
      <div class="smart-modal-body phi-body">
        <p class="phi-found" id="phi-found" aria-live="polite">${escapeHtml(t('phi.looking', 'Looking at the export…'))}</p>
        <label class="phi-label" for="phi-dest">${escapeHtml(t('phi.dest', 'Put the photos in'))}</label>
        <div class="phi-row">
          <input class="phi-input" id="phi-dest" type="text" spellcheck="false" />
          <button type="button" class="btn-pill-toggle" id="phi-browse">${escapeHtml(t('phi.browse', 'Choose…'))}</button>
        </div>
        <p class="phi-note">${escapeHtml(t('phi.note', 'Each photo goes into a folder for the year and month it was taken. Photos already there are skipped, and the export is not changed.'))}</p>
        <div class="phi-actions">
          <button type="button" class="btn-pill-toggle" id="phi-cancel">${escapeHtml(t('common.cancel', 'Cancel'))}</button>
          <button type="button" class="btn-pill-toggle active is-primary" id="phi-start" disabled>${escapeHtml(t('phi.start', 'Bring them home'))}</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  const $ = (sel) => /** @type {HTMLElement} */ (modal.querySelector(sel));
  const dest = /** @type {HTMLInputElement} */ ($('#phi-dest'));
  const start = /** @type {HTMLButtonElement} */ ($('#phi-start'));
  $('#phi-close').addEventListener('click', close);
  $('#phi-cancel').addEventListener('click', close);
  modal.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
  });
  $('#phi-browse').addEventListener('click', () => {
    const browse = /** @type {any} */ (window).openFolderBrowser;
    if (typeof browse === 'function') browse(dest.value || path, (picked) => { if (picked) dest.value = picked; });
  });
  start.addEventListener('click', async () => {
    start.disabled = true;
    try {
      await api.post('/api/media/photo-import', { source: path, destination: dest.value.trim() });
      showToast(t('phi.started', 'The import started. You can follow it in Jobs.'), 'success');
      close();
    } catch (err) {
      showToast(/** @type {Error} */ (err).message || t('phi.failed', 'The import could not start.'), 'error');
      start.disabled = false;
    }
  });
  try {
    const info = await api.get(`/api/media/photo-import/inspect?path=${encodeURIComponent(path)}`);
    $('#phi-found').textContent = foundText(info);
    dest.value = info.destination || '';
    start.disabled = !(info.photos || info.videos);
  } catch (err) {
    $('#phi-found').textContent = /** @type {Error} */ (err).message || t('phi.failed_read', 'The export could not be read.');
  }
  dest.focus();
}
