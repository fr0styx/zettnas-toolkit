/**
 * File activity in Security (FEAT-12): who deleted, moved, renamed, restored or uploaded what,
 * searchable, 90 days kept. Shown to accounts that may read the audit log.
 */
import { api, ApiError } from '../api.js';
import { t } from '../i18n.js';
import { formatDateTime } from '../format.js';

/** What each action is called in the list. */
export function actionLabel(action) {
  const names = {
    delete: t('activity.delete', 'Moved to the Recycle Bin'),
    delete_permanent: t('activity.delete_permanent', 'Deleted for good'),
    rename: t('activity.rename', 'Renamed'),
    move: t('activity.move', 'Moved'),
    copy: t('activity.copy', 'Copied'),
    restore: t('activity.restore', 'Restored'),
    empty_bin: t('activity.empty_bin', 'Emptied the Recycle Bin'),
    upload: t('activity.upload', 'Uploaded'),
    mkdir: t('activity.mkdir', 'New folder'),
    archive: t('activity.archive', 'Archived'),
    extract: t('activity.extract', 'Extracted'),
  };
  return names[action] || action;
}

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else n.setAttribute(k, v);
  }
  children.flat().forEach((c) => c !== null && c !== undefined && n.append(c));
  return n;
}

/** One row of the table, built from text nodes only. */
export function activityRow(item) {
  const what = el('td', {}, el('div', { class: 'is-mono', text: item.path || '—' }));
  if (item.target) what.append(el('div', { class: 'zn-sub is-mono', text: `→ ${item.target}` }));
  if (item.detail) what.append(el('div', { class: 'zn-sub', text: item.detail }));
  const who = el('td', {}, el('div', { class: 'is-strong', text: item.username || '—' }));
  const sub = [item.ip, item.via].filter(Boolean).join(' · ');
  if (sub) who.append(el('div', { class: 'zn-sub', text: sub }));
  return el(
    'tr',
    {},
    el('td', { class: 'is-muted', text: formatDateTime(item.ts) }),
    who,
    el('td', {}, el('span', { class: `zn-tag zn-tag--${item.action === 'delete_permanent' || item.action === 'empty_bin' ? 'crit' : 'plain'}`, text: actionLabel(item.action) })),
    what
  );
}

export function activityQuery({ q = '', user = '', action = '', before = null } = {}) {
  const p = new URLSearchParams();
  if (q.trim()) p.set('q', q.trim());
  if (user.trim()) p.set('user', user.trim());
  if (action) p.set('action', action);
  if (before) p.set('before', String(before));
  p.set('limit', '100');
  return `/api/fs/activity?${p}`;
}

export async function renderFileActivity(host = document.getElementById('file-activity-mount')) {
  if (!host) return;
  const q = el('input', { type: 'search', class: 'tz-select-input', placeholder: t('activity.search', 'Search a file or folder'), 'aria-label': t('activity.search', 'Search a file or folder') });
  const user = el('input', { type: 'search', class: 'tz-select-input', placeholder: t('activity.user', 'Person'), 'aria-label': t('activity.user', 'Person') });
  const action = el('select', { class: 'tz-select-input', 'aria-label': t('activity.action', 'What happened') }, el('option', { value: '', text: t('activity.any', 'Anything') }));
  const body = el('tbody');
  const more = el('button', { type: 'button', class: 'btn-pill-toggle', text: t('activity.more', 'Older') });
  more.hidden = true;
  const table = el('div', { class: 'zn-datatable-wrap' }, el('table', { class: 'zn-datatable zn-datatable--compact' },
    el('thead', {}, el('tr', {}, ...[t('activity.when', 'When'), t('activity.who', 'Who'), t('activity.what', 'What'), t('activity.file', 'File')].map((h) => el('th', { text: h })))),
    body));
  let next = null;

  async function load(append = false) {
    if (!append) next = null;
    let res;
    try {
      res = await api.get(activityQuery({ q: q.value, user: user.value, action: action.value, before: append ? next : null }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        host.hidden = true; // only for accounts that may read the audit log
        return;
      }
      body.replaceChildren(el('tr', {}, el('td', { colspan: '4', class: 'zn-datatable-msg is-crit', text: t('activity.load_failed', "Couldn't load the file activity.") })));
      return;
    }
    if (action.options.length === 1) {
      (res.actions || []).forEach((a) => action.append(el('option', { value: a, text: actionLabel(a) })));
    }
    const rows = (res.items || []).map(activityRow);
    if (append) body.append(...rows);
    else body.replaceChildren(...(rows.length ? rows : [el('tr', {}, el('td', { colspan: '4', class: 'zn-datatable-msg', text: t('activity.none', 'Nothing in the last 90 days matches.') }))]));
    next = res.next_before;
    more.hidden = !next;
  }

  let timer = null;
  const later = () => { clearTimeout(timer); timer = setTimeout(() => load(false), 300); };
  q.addEventListener('input', later);
  user.addEventListener('input', later);
  action.addEventListener('change', () => load(false));
  more.addEventListener('click', () => load(true));

  host.hidden = false;
  host.replaceChildren(
    el('div', { class: 'zn-title', text: t('activity.title', 'File activity') }),
    el('div', { class: 'zn-sub is-spaced', text: t('activity.intro', 'Who deleted, moved, renamed, restored or uploaded what in the File Explorer or through the API. Kept for 90 days.') }),
    el('div', { class: 'zn-activity-filters' }, q, user, action),
    table,
    more
  );
  await load(false);
}
