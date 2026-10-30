/**
 * Choosing a share for an app's folder at install (FEAT-06): Syncthing's synced folders,
 * Nextcloud's files or a music library can live on a share the family already uses instead
 * of a new folder inside the app's own folder.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}

/** The folder names the built-in templates use, in the reader's language. */
function folderLabel(label) {
  const names = {
    'Media library': t('catalog.sf_media', 'Media library'),
    'TV shows': t('catalog.sf_tv', 'TV shows'),
    Movies: t('catalog.sf_movies', 'Movies'),
    Music: t('catalog.sf_music', 'Music'),
    Audiobooks: t('catalog.sf_audiobooks', 'Audiobooks'),
    Podcasts: t('catalog.sf_podcasts', 'Podcasts'),
    Books: t('catalog.sf_books', 'Books'),
    Library: t('catalog.sf_library', 'Library'),
    'Comics and books': t('catalog.sf_comics', 'Comics and books'),
    'Photo library': t('catalog.sf_photos', 'Photo library'),
    'Original photos': t('catalog.sf_originals', 'Original photos'),
    Files: t('catalog.sf_files', 'Files'),
    'Synced folders': t('catalog.sf_synced', 'Synced folders'),
    'Files to browse': t('catalog.sf_browse', 'Files to browse'),
  };
  return names[label] || label;
}

/**
 * Fills `mount` with one choice per app folder that can live on a share, and hides it when
 * the app has none. `onChange` runs when a choice changes (to refresh the Compose preview).
 */
export async function renderShareFolders(mount, appId, onChange) {
  if (!mount) return;
  mount.replaceChildren();
  mount.hidden = true;
  let info;
  try {
    info = await api.get(`/api/docker/catalog/${encodeURIComponent(appId)}/share-folders`);
  } catch {
    return; // the install still works with the app's own folders
  }
  const folders = (info && info.folders) || [];
  if (!folders.length) return;
  const shares = info.shares || [];
  mount.hidden = false;
  mount.append(el('div', { className: 'adm-label', textContent: t('catalog.sf_title', 'Keep on a share') }));
  for (const f of folders) {
    const sel = el('select', { id: `adm-share-${f.key}`, className: 'tz-text-input adm-share-select', disabled: !shares.length });
    sel.dataset.shareFolder = f.key;
    sel.append(el('option', { value: '', textContent: t('catalog.sf_own', "In the app's own folder") }));
    for (const s of shares) sel.append(el('option', { value: s.name, textContent: s.name }));
    sel.onchange = () => onChange && onChange();
    mount.append(el('div', { className: 'adm-share-row' }, el('label', { htmlFor: sel.id, textContent: folderLabel(f.label) }), sel));
  }
  const hint = shares.length
    ? t('catalog.sf_hint', 'The app sees everything in the share you pick, and the files stay there if you remove the app.')
    : t('catalog.sf_none', 'No shares yet. Create one under Shares to keep these files on it.');
  mount.append(el('div', { className: 'adm-hint', textContent: hint }));
  if (!shares.length) {
    const go = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('catalog.sf_open_shares', 'Open Shares') });
    go.addEventListener('click', () => /** @type {any} */ (window).openManagementSection?.('mgmt-pane-storage-shares'));
    mount.append(go);
  }
}

/** {app folder: share name} for the shares picked; an empty object keeps the app's own folders. */
export function shareFolderPicks(mount) {
  const out = {};
  for (const sel of mount ? mount.querySelectorAll('select[data-share-folder]') : []) {
    if (sel.value) out[sel.dataset.shareFolder] = sel.value;
  }
  return out;
}
