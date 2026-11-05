/**
 * Share access grid (SEC-10): which user may use which share in the file manager.
 * Rows are shares, columns are users; each cell is "inherit", "none", "read" or "write".
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { showToast } from '../toast.js';

import { t } from '../i18n.js';
const LEVELS = ['none', 'read', 'write'];

/** Gives one person these levels ({share: 'read'|'write'}), keeping every other grant (B11, SEC-21). */
export async function grantShares(person, levels) {
  const picked = Object.entries(levels || {}).filter(([, lvl]) => LEVELS.includes(lvl) && lvl !== 'none');
  if (!person || !picked.length) return false;
  const current = await api.get('/api/storage/share-access');
  const shares = {};
  for (const sh of current?.shares || []) {
    shares[sh.name] = { users: { ...(sh.users || {}) }, ...(sh.default ? { default: sh.default } : {}) };
  }
  const who = String(person).toLowerCase();
  for (const [name, lvl] of picked) {
    shares[name] = { ...(shares[name] || {}), users: { ...(shares[name]?.users || {}), [who]: lvl } };
  }
  await api.put('/api/storage/share-access', { shares });
  return true;
}

/** One row per share with a none/read/write choice, for the "Add a person" dialog. */
export function shareChoicesHtml(shares) {
  const label = {
    none: t('share.level_none', 'No access'),
    read: t('share.level_read', 'Can view'),
    write: t('share.level_write', 'Can view and change'),
  };
  return (shares || []).map((s) => `
    <div class="add-user-share-row">
      <span class="add-user-share-name" title="${escapeHtml(s.path || '')}">${escapeHtml(s.name)}</span>
      <select class="add-user-share-level" data-add-user-share="${escapeHtml(s.name)}" aria-label="${escapeHtml(s.name)}">
        ${LEVELS.map((l) => `<option value="${l}"${l === 'none' ? ' selected' : ''}>${escapeHtml(label[l])}</option>`).join('')}
      </select>
    </div>`).join('');
}

function levelSelect(attrs, value, withInherit) {
  const opts = (withInherit ? ['inherit', ...LEVELS] : LEVELS)
    .map((l) => `<option value="${l}"${l === value ? ' selected' : ''}>${l}</option>`)
    .join('');
  return `<select class="sha-xs-strong-box" ${attrs}>${opts}</select>`;
}

export function buildShareAccessHtml(data, users) {
  const userNames = users.map((u) => String(u.username || '').toLowerCase()).filter(Boolean);
  const head = userNames.map((u) => `<th class="sha-xs">${escapeHtml(u)}</th>`).join('');
  const rows = (data.shares || []).map((s) => {
    const cells = userNames
      .map((u) => `<td class="sha-x">${levelSelect(`data-share="${escapeHtml(s.name)}" data-user="${escapeHtml(u)}"`, (s.users || {})[u] || 'inherit', true)}</td>`)
      .join('');
    return `<tr class="sha-box">
      <td class="sha-bold" title="${escapeHtml(s.path)}">${escapeHtml(s.name)}</td>
      <td class="sha-x">${levelSelect(`data-share-default="${escapeHtml(s.name)}"`, s.default || 'inherit', true)}</td>
      ${cells}</tr>`;
  }).join('');
  return `
    <div class="sha-row-xs">
      <span>${t('sa.everyone_else', 'Everyone else, on shares without a setting:')}</span>${levelSelect('id="share-access-global"', data.default_level || 'none', false)}
    </div>
    <div class="sha-x-2"><table class="sha-xs-box">
      <thead><tr class="sha-muted"><th class="sha-x-3">${t('sa.share', 'Share')}</th><th class="sha-x-4">${t('sa.default', 'Default')}</th>${head}</tr></thead>
      <tbody>${rows || `<tr><td class="sha-muted-2" colspan="${2 + userNames.length}">${t('sa.no_shares', 'No shares found.')}</td></tr>`}</tbody>
    </table></div>
    <div class="sha-xs-muted">${t('sa.help', `Admins always have full access. Users always have their own home folder. "inherit" uses the share's Samba user lists, then the share default, then the setting above.`)}</div>`;
}

export function collectShareAccess(root) {
  const out = { default_level: root.querySelector('#share-access-global')?.value || 'none', shares: {} };
  root.querySelectorAll('[data-share-default]').forEach((sel) => {
    const name = sel.dataset.shareDefault;
    out.shares[name] = out.shares[name] || { users: {} };
    if (sel.value !== 'inherit') out.shares[name].default = sel.value;
  });
  root.querySelectorAll('select[data-share][data-user]').forEach((sel) => {
    const name = sel.dataset.share;
    out.shares[name] = out.shares[name] || { users: {} };
    if (sel.value !== 'inherit') out.shares[name].users[sel.dataset.user] = sel.value;
  });
  return out;
}

export async function openShareAccessModal() {
  let data;
  let users;
  try {
    [data, users] = await Promise.all([api.get('/api/storage/share-access'), api.get('/api/users')]);
  } catch (err) {
    showToast(t('toast.could_not_load_share_access', 'Could not load share access: {error}', { error: err.message }), 'error');
    return;
  }
  const list = Array.isArray(users) ? users : users?.users || [];
  const plain = list.filter((u) => !['superadmin', 'storage_admin'].includes(u.role_id || u.role));

  let backdrop = document.getElementById('share-access-modal');
  if (backdrop) backdrop.remove();
  backdrop = document.createElement('div');
  backdrop.id = 'share-access-modal';
  backdrop.className = 'smart-modal-backdrop open';
  backdrop.style.zIndex = '10050';
  backdrop.innerHTML = `
    <div class="smart-modal-window share-access-window sha-size" role="dialog" aria-modal="true" aria-labelledby="share-access-title">
      <div class="smart-modal-header">
        <span class="smart-modal-title" id="share-access-title"><svg class="ic ic-sm"><use href="#i-users"/></svg> ${t('sa.title', 'Share access')}</span>
        <div class="os-window-controls">
          <button type="button" id="share-access-close" class="win-btn close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
        </div>
      </div>
      <div class="smart-modal-body">
        <div id="share-access-body">${buildShareAccessHtml(data, plain)}</div>
        <div class="sha-row">
          <button type="button" id="share-access-cancel" class="btn-pill-toggle">${t('common.cancel', 'Cancel')}</button>
          <button type="button" id="share-access-save" class="btn-save-preset sha-xs-2">${t('common.save', 'Save')}</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelector('#share-access-cancel').onclick = close;
  backdrop.querySelector('#share-access-close').onclick = close;
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
  backdrop.querySelector('#share-access-save').onclick = async () => {
    try {
      await api.put('/api/storage/share-access', collectShareAccess(backdrop));
      showToast(t('toast.share_access_saved', 'Share access saved.'), 'success');
      close();
    } catch (err) {
      showToast(t('toast.could_not_save', 'Could not save: {error}', { error: err.message }), 'error');
    }
  };
}
