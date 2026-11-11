// The File Explorer's Recycle Bin view (NUX-17): each item says where it was, the date column
// says when it was deleted, and a bar says how long items stay, with "Empty all" for those who
// may empty the bins (typed confirmation: it covers every share, for everyone).
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showConfirmToast, showToast } from '../toast.js';
import { hasScope } from '../route-access.js';
import { formatDate } from '../format.js';

function setLabel(col, key, fallback) {
  if (!col) return;
  const label = col.querySelector('.fm-col-label');
  if (label) { // the key goes with the words, so a language pass keeps "From" in the bin
    label.setAttribute('data-i18n', key);
    label.textContent = t(key, fallback);
    return;
  }
  const node = [...col.childNodes].find((n) => n.nodeType === 3 && n.nodeValue.trim());
  if (node) node.nodeValue = `${t(key, fallback)} `;
}

/** Type → From and Modified → Deleted while the bin is open; back again elsewhere. */
export function binColumns(fm, inBin) {
  if (inBin) {
    setLabel(fm.colType, 'fm.col_from', 'From');
    setLabel(fm.colMtime, 'fm.col_deleted', 'Deleted');
  } else {
    setLabel(fm.colType, 'fm.col_type', 'Type');
    setLabel(fm.colMtime, 'fm.col_mtime', 'Modified');
  }
}

/** Who may empty every bin. The rights are read the way the server reads them: the storage
 *  administrator holds "shares:*", which a look for the exact words missed (SET-05). */
export function mayEmpty(user) {
  const scopes = (user && user.scopes) || [];
  return hasScope(scopes, 'shares:manage') || hasScope(scopes, 'storage:admin');
}

const DAY = 86400;

/**
 * True for an item of the bin that goes for good within the next `days` days.
 * @param {{ leaves_at?: number }} file
 */
export function goesSoon(file, days = 7, now = Date.now() / 1000) {
  const at = Number(file && file.leaves_at) || 0;
  return at > 0 && at <= now + days * DAY;
}

/**
 * "Goes today" or "Goes 14 Nov": the tag on an item that leaves the bin within a week.
 * @param {{ leaves_at?: number }} file
 */
export function goesLabel(file, now = Date.now() / 1000) {
  const at = Number(file.leaves_at) || 0;
  if (at - now < DAY) return t('fm.bin_goes_today', 'Goes within a day');
  return t('fm.bin_goes', 'Goes {date}', { date: formatDate(at) });
}

/**
 * What the bar says: both rules, and how many items go in the next days.
 * @param {{ keep_days?: number, max_percent_of_disk?: number, soon_days?: number }} rules
 * @param {number} soon
 */
export function binNote(rules = {}, soon = 0) {
  const days = rules.keep_days || 30;
  const percent = rules.max_percent_of_disk || 10;
  const text = t('fm.bin_note', 'Items stay here for {days} days after they are deleted, then they go for good. A bin that grows past {percent}% of its drive lets its oldest items go sooner, but never within a day.', { days, percent });
  if (!soon) return text;
  return `${text} ${t('fm.bin_soon', '{count, plural, one {# item goes in the next {days} days.} other {# items go in the next {days} days.}}', { count: soon, days: rules.soon_days || 7 })}`;
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

/** The bar above the list in the bin: how long items stay, how many go soon, and Empty all. */
export function binBar(fm, inBin, onEmptied, info = {}) {
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
  bar.querySelector('.fm-bin-note').textContent = binNote(info.rules, info.soon);
  bar.classList.toggle('has-soon', Boolean(info.soon));
  const btn = /** @type {HTMLButtonElement} */ (bar.querySelector('.fm-bin-empty'));
  btn.textContent = t('fm.empty_bins', 'Empty all Recycle Bins');
  btn.hidden = true; // until the account's rights are known
  // session.js is loaded when needed: the File Explorer stays importable on its own
  bar.ready = import('./session.js').then((m) => {
    btn.hidden = !mayEmpty(m.getCurrentUser());
  }, () => {});
  return bar;
}
