/**
 * Two-way sync between a folder here and a cloud folder (FEAT-06): add a pair, see its dry
 * run (what goes each way, what is deleted, what is kept twice), approve it, then it runs.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
}

function button(label, act, id, primary = false) {
  const b = el('button', { type: 'button', className: `btn-pill-toggle is-small${primary ? ' is-primary' : ''}`, textContent: label });
  b.dataset.sync = act;
  b.dataset.id = id;
  return b;
}

/** One line about a dry run: counts each way, deletions and conflicts. */
export function previewText(p) {
  if (!p) return t('sync2.no_preview', 'No preview yet.');
  if (!p.ok) return t('sync2.preview_failed', 'The preview failed: {why}', { why: p.error || '' });
  const parts = [
    t('sync2.to_cloud', '{n, plural, one {# file} other {# files}} to the cloud', { n: p.to_remote || 0 }),
    t('sync2.to_here', '{n, plural, one {# file} other {# files}} to this NAS', { n: p.to_local || 0 }),
  ];
  const deletes = (p.delete_remote || 0) + (p.delete_local || 0);
  if (deletes) parts.push(t('sync2.deletes', '{n, plural, one {# deletion} other {# deletions}}', { n: deletes }));
  if (p.conflicts) parts.push(t('sync2.conflicts', '{n, plural, one {# file changed on both sides (kept twice)} other {# files changed on both sides (kept twice)}}', { n: p.conflicts }));
  const lead = p.first_run ? t('sync2.first_run', 'First run, copies only: ') : '';
  return lead + parts.join(' · ');
}

export function pairRow(p) {
  const row = el('li', { className: 'offsite-repo' });
  const main = el('div', { className: 'offsite-repo-main' });
  main.append(el('span', { className: 'offsite-repo-name', textContent: p.name }));
  main.append(el('span', { className: 'offsite-meta', textContent: `${p.local} ⇄ ${p.remote}` }));
  main.append(el('span', { className: 'offsite-meta', textContent: previewText(p.preview) }));
  const state = p.state === 'active'
    ? t('sync2.state_active', 'On, every {n} h · last run {when}', { n: p.every_hours, when: p.last_run ? formatDateTime(p.last_run * 1000) : t('offsite.never', 'never') })
    : t('sync2.state_waiting', 'Waiting for you to check the preview and turn it on');
  main.append(el('span', { className: 'offsite-meta', textContent: state }));
  if (p.last_result && p.last_result !== 'ok') main.append(el('strong', { className: 'offsite-meta', textContent: p.last_result }));
  const actions = el('div', { className: 'offsite-actions' });
  actions.append(button(t('sync2.preview', 'Preview'), 'preview', p.id, p.state !== 'active'));
  if (p.state === 'previewed' && p.preview && p.preview.ok) actions.append(button(t('sync2.approve', 'Turn on'), 'approve', p.id, true));
  if (p.state === 'active') actions.append(button(t('sync2.run', 'Sync now'), 'run', p.id));
  actions.append(button(t('offsite.forget', 'Forget'), 'delete', p.id));
  row.append(main, actions);
  return row;
}

function form() {
  const f = el('form', { className: 'offsite-form' });
  f.dataset.syncForm = '1';
  const field = (label, name, extra = {}) => el('label', {}, label, el('input', { name, required: true, ...extra }));
  f.append(
    field(t('sync2.name', 'Name'), 'name', { maxLength: 80 }),
    field(t('sync2.local', 'Folder here'), 'local', { placeholder: '/mnt/user/documents' }),
    field(t('sync2.remote', 'Cloud folder'), 'remote', { placeholder: 'gdrive:documents' }),
    field(t('sync2.every', 'Every (hours)'), 'every_hours', { type: 'number', min: 1, max: 168, value: '6' }),
    el('button', { type: 'submit', className: 'btn-pill-toggle is-primary', textContent: t('sync2.add', 'Add two-way sync') }),
  );
  return f;
}

function slug(name) {
  return String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'sync';
}

export async function renderTwoWaySync(mount) {
  let data;
  try {
    data = await api.get('/api/sync/pairs');
  } catch (err) {
    mount.textContent = err.message || String(err);
    return;
  }
  const list = el('ul', { className: 'offsite-list' });
  for (const p of data.pairs || []) list.append(pairRow(p));
  if (!(data.pairs || []).length) list.append(el('li', { className: 'offsite-note', textContent: t('sync2.none', 'No two-way sync yet.') }));
  mount.replaceChildren(list, form());
  mount.querySelector('[data-sync-form]').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(/** @type {HTMLFormElement} */ (e.target));
    try {
      await api.put('/api/sync/pairs', { id: slug(f.get('name')), name: f.get('name'), local: f.get('local'), remote: f.get('remote'), every_hours: Number(f.get('every_hours') || 6) });
      renderTwoWaySync(mount);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  mount.onclick = async (e) => {
    const b = e.target.closest('[data-sync]');
    if (!b) return;
    const id = encodeURIComponent(b.dataset.id);
    try {
      if (b.dataset.sync === 'delete') await api.delete(`/api/sync/pairs/${id}`);
      else {
        b.disabled = true;
        await api.post(`/api/sync/pairs/${id}/${b.dataset.sync}`, {});
      }
      renderTwoWaySync(mount);
    } catch (err) {
      b.disabled = false;
      showToast(err.message || String(err), 'error');
    }
  };
}
