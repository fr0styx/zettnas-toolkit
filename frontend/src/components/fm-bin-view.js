// The File Explorer's Recycle Bin view (NUX-17): each item says where it was, the date column
// says when it was deleted, and a bar says how long items stay, with "Empty all" for those who
// may empty the bins (typed confirmation: it covers every share, for everyone).
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showConfirmToast, showToast } from '../toast.js';

function setLabel(col, text) {
  if (!col) return;
  const node = [...col.childNodes].find((n) => n.nodeType === 3 && n.nodeValue.trim());
  if (node) node.nodeValue = `${text} `;
}

/** Type → From and Modified → Deleted while the bin is open; back again elsewhere. */
export function binColumns(fm, inBin) {
  setLabel(fm.colType, inBin ? t('fm.col_from', 'From') : t('fm.col_type', 'Type'));
  setLabel(fm.colMtime, inBin ? t('fm.col_deleted', 'Deleted') : t('fm.col_mtime', 'Modified'));
}

export function mayEmpty(user) {
  const scopes = (user && user.scopes) || [];
  return scopes.includes('*') || scopes.includes('shares:manage') || scopes.includes('storage:admin');
}

export function emptyAll(onDone) {
  const word = t('fm.empty_word', 'EMPTY');
  showConfirmToast(
    t('fm.empty_bins_title', 'Empty every Recycle Bin'),
    t('fm.empty_bins_msg', "This permanently deletes what the Recycle Bin of every share holds, for everyone. It can't be undone. Type {word} to confirm.", { word }),
    async () => {
      try {
        await api.delete('/api/fs/trash/empty', { confirmed: true });
        showToast(t('toast.trash_emptied_storage_reclaimed', 'Recycle Bin emptied. The space is free again.'), 'success');
        onDone();
      } catch (err) {
        showToast(err.message, 'error');
      }
    },
    null,
    { destructive: true, typeToConfirm: word, okText: t('fm.empty_bins', 'Empty all Recycle Bins'), allowHtml: false },
  );
}

/** The bar above the list in the bin: how long items stay, and Empty all. */
export function binBar(fm, inBin, onEmptied) {
  const header = fm.colMtime && fm.colMtime.closest('.fm-header-row');
  let bar = fm.windowEl && fm.windowEl.querySelector('.fm-bin-bar');
  if (!inBin) {
    if (bar) bar.hidden = true;
    return null;
  }
  if (!bar && header) {
    bar = document.createElement('div');
    bar.className = 'fm-bin-bar';
    const note = document.createElement('span');
    note.className = 'fm-bin-note';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-pill-toggle is-small is-danger fm-bin-empty';
    btn.addEventListener('click', () => emptyAll(onEmptied));
    bar.append(note, btn);
    header.before(bar);
  }
  if (!bar) return null;
  bar.hidden = false;
  bar.querySelector('.fm-bin-note').textContent = t('fm.bin_note', 'Items stay here for 30 days after they are deleted, then they go for good.');
  const btn = /** @type {HTMLButtonElement} */ (bar.querySelector('.fm-bin-empty'));
  btn.textContent = t('fm.empty_bins', 'Empty all Recycle Bins');
  btn.hidden = true; // until the account's rights are known
  // session.js is loaded when needed: the File Explorer stays importable on its own
  bar.ready = import('./session.js').then((m) => {
    btn.hidden = !mayEmpty(m.getCurrentUser());
  }, () => {});
  return bar;
}
