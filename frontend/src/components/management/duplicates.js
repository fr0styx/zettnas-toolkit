// Duplicates (AI-35): files kept more than once, from the index (/api/media/duplicates): photos
// that look the same, a re-saved or resized copy included, and files with the same content. A
// window lists each set with its thumbnails and where each copy is; a copy can go to its share's
// recycle bin (restorable for 30 days). The last copy of a set never offers it.
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { html } from '../../html.js';
import { formatBytes } from '../../format.js';
import { showToast, showConfirmToast } from '../../toast.js';

const WIN_ID = 'ai-duplicates';
const BTN_ID = 'ai-duplicates-btn';
let _data = null;

const folderOf = (p) => p.slice(0, p.lastIndexOf('/')) || '/';

function fileRow(f, group) {
  const last = group.files.length < 2;
  return html`<li class="dup-file">
    ${group.kind === 'photo' ? html`<img class="dup-thumb" src="/api/media/thumbnail/${f.file_id}" alt="" loading="lazy">` : ''}
    <span class="dup-where"><strong>${f.name}</strong><span class="zn-muted">${folderOf(f.path)}</span></span>
    <span class="zn-muted">${formatBytes(f.size)}</span>
    ${last ? '' : html`<button type="button" class="btn-pill-toggle is-small" data-dup-bin="${f.path}">${t('dup.to_bin', 'Move to recycle bin')}</button>`}
  </li>`;
}

function groupHtml(g) {
  const label = g.kind === 'photo' ? t('dup.photo_group', 'Photos that look the same') : t('dup.file_group', 'Identical files');
  return html`<section class="dup-group">
    <div class="zn-row zn-row--between"><strong>${label}</strong><span class="zn-muted">${t('dup.saves', '{size} to free', { size: formatBytes(g.wasted_bytes) })}</span></div>
    <ul class="dup-files">${g.files.map((f) => fileRow(f, g))}</ul>
  </section>`;
}

export function duplicatesHtml(data) {
  if (!data) return html`<p class="zn-muted">${t('dup.load_failed', "Couldn't load the duplicates.")}</p>`;
  const groups = data.groups || [];
  if (!groups.length) return html`<p class="zn-muted">${t('dup.none', 'No duplicates found. Copies are found as folders are indexed.')}</p>`;
  const more = (data.total_groups || 0) > groups.length;
  return html`<p>${t('dup.summary', '{groups, plural, one {# set of copies} other {# sets of copies}}; {size} could be freed.', { groups: data.total_groups, size: formatBytes(data.wasted_bytes) })}</p>
    ${more ? html`<p class="zn-muted">${t('dup.more', 'Showing the {shown} largest of {total}.', { shown: groups.length, total: data.total_groups })}</p>` : ''}
    ${groups.map(groupHtml)}`;
}

function closeWindow(host) {
  host.classList.remove('open');
}

function dupWindow() {
  let host = document.getElementById(WIN_ID);
  if (host) return host;
  host = document.createElement('div');
  host.id = WIN_ID;
  host.className = 'smart-modal-backdrop';
  host.style.zIndex = '10020'; // above Mission Control
  host.innerHTML = html`<div class="smart-modal-window dup-window" role="dialog" aria-modal="true" aria-labelledby="ai-duplicates-title" data-dock-icon="#i-files">
    <div class="smart-modal-header">
      <span class="smart-modal-title" id="ai-duplicates-title"><svg class="ic" aria-hidden="true"><use href="#i-files"/></svg> ${t('dup.title', 'Duplicate files')}</span>
      <div class="os-window-controls">
        <button type="button" class="win-btn close-btn" data-close title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
      </div>
    </div>
    <div class="smart-modal-body dup-body"></div>
  </div>`;
  document.body.appendChild(host);
  host.querySelector('[data-close]').addEventListener('click', () => closeWindow(host));
  host.addEventListener('click', (e) => {
    if (e.target === host) closeWindow(host);
    const b = e.target.closest('[data-dup-bin]');
    if (b) askToBin(host, b.dataset.dupBin);
  });
  host.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeWindow(host);
  });
  return host;
}

function render(host) {
  host.querySelector('.dup-body').innerHTML = duplicatesHtml(_data);
  const btn = document.getElementById(BTN_ID);
  if (btn) btn.innerHTML = buttonLabel(_data);
}

/** Takes a copy out of the list; a set left with one file is no longer a duplicate. */
export function dropFile(data, path) {
  if (!data) return data;
  let freed = 0;
  const groups = [];
  for (const g of data.groups || []) {
    const files = g.files.filter((f) => f.path !== path);
    if (files.length === g.files.length) {
      groups.push(g);
      continue;
    }
    freed += g.files.find((f) => f.path === path)?.size || 0;
    if (files.length > 1) groups.push({ ...g, files, wasted_bytes: files.reduce((s, f) => s + f.size, 0) - Math.max(...files.map((f) => f.size)) });
  }
  const gone = (data.groups || []).length - groups.length;
  return { ...data, groups, total_groups: Math.max(0, (data.total_groups || 0) - gone), wasted_bytes: Math.max(0, (data.wasted_bytes || 0) - freed) };
}

function askToBin(host, path) {
  const name = path.slice(path.lastIndexOf('/') + 1);
  showConfirmToast(
    t('dup.confirm_title', 'Move to recycle bin?'),
    t('dup.confirm_msg', '{name} goes to its share\'s recycle bin, where you can restore it for 30 days. The other copies stay.', { name }),
    async () => {
      try {
        await api.post('/api/fs/delete', { path });
        _data = dropFile(_data, path);
        render(host);
        showToast(t('dup.moved', 'Moved to the recycle bin'), 'success');
      } catch (e) {
        showToast(t('dup.failed', "Couldn't move it: {error}", { error: e?.message || '' }));
      }
    },
    null,
    { okText: t('dup.to_bin', 'Move to recycle bin') },
  );
}

export async function loadDuplicates() {
  try {
    _data = await api.get('/api/media/duplicates?limit=200');
  } catch {
    _data = null;
  }
  return _data;
}

export async function openDuplicates() {
  const host = dupWindow();
  host.querySelector('.dup-body').innerHTML = html`<p class="zn-muted">${t('dup.loading', 'Looking for copies…')}</p>`;
  host.classList.add('open');
  await loadDuplicates();
  render(host);
  host.querySelector('[data-close]').focus();
  return host;
}

function buttonLabel(data) {
  const n = data?.total_groups || 0;
  return n
    ? html`${t('dup.button', 'Duplicates')} <span class="zn-muted">${formatBytes(data.wasted_bytes)}</span>`
    : html`${t('dup.button', 'Duplicates')}`;
}

/** Adds the Duplicates button after the document filters; it shows how much copies take. */
export async function installDuplicatesButton(root = document) {
  const anchor = root.getElementById('ai-doc-filters') || root.getElementById('ai-search-sort-select')?.parentElement;
  if (!anchor || root.getElementById(BTN_ID)) return;
  const btn = Object.assign(document.createElement('button'), { id: BTN_ID, type: 'button', className: 'btn-pill-toggle is-small' });
  btn.addEventListener('click', () => openDuplicates());
  anchor.insertAdjacentElement('afterend', btn);
  btn.innerHTML = buttonLabel(null);
  btn.innerHTML = buttonLabel(await loadDuplicates());
}

export function _reset() {
  _data = null;
}
