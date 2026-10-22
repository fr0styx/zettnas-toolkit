/**
 * Share access grid (SEC-10): which user may use which share in the file manager.
 * Rows are shares, columns are users; each cell is "inherit", "none", "read" or "write".
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { showToast } from '../toast.js';

import { t } from '../i18n.js';
const LEVELS = ['none', 'read', 'write'];

function levelSelect(attrs, value, withInherit) {
  const opts = (withInherit ? ['inherit', ...LEVELS] : LEVELS)
    .map((l) => `<option value="${l}"${l === value ? ' selected' : ''}>${l}</option>`)
    .join('');
  return `<select ${attrs} style="background:rgba(0,0,0,0.35); color:#fff; border:1px solid rgba(255,255,255,0.15); border-radius:4px; font-size:11px; padding:2px 4px;">${opts}</select>`;
}

export function buildShareAccessHtml(data, users) {
  const userNames = users.map((u) => String(u.username || '').toLowerCase()).filter(Boolean);
  const head = userNames.map((u) => `<th style="padding:6px 8px; font-size:11px;">${escapeHtml(u)}</th>`).join('');
  const rows = (data.shares || []).map((s) => {
    const cells = userNames
      .map((u) => `<td style="padding:4px 8px;">${levelSelect(`data-share="${escapeHtml(s.name)}" data-user="${escapeHtml(u)}"`, (s.users || {})[u] || 'inherit', true)}</td>`)
      .join('');
    return `<tr style="border-top:1px solid rgba(255,255,255,0.06);">
      <td style="padding:6px 8px; font-weight:700;" title="${escapeHtml(s.path)}">${escapeHtml(s.name)}</td>
      <td style="padding:4px 8px;">${levelSelect(`data-share-default="${escapeHtml(s.name)}"`, s.default || 'inherit', true)}</td>
      ${cells}</tr>`;
  }).join('');
  return `
    <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px; font-size:12px;">
      <span>Everyone else, on shares without a setting:</span>${levelSelect('id="share-access-global"', data.default_level || 'write', false)}
    </div>
    <div style="overflow-x:auto;"><table style="border-collapse:collapse; min-width:420px; font-size:12px;">
      <thead><tr style="color:var(--muted); text-transform:uppercase;"><th style="padding:6px 8px; text-align:left;">Share</th><th style="padding:6px 8px;">Default</th>${head}</tr></thead>
      <tbody>${rows || `<tr><td colspan="${2 + userNames.length}" style="padding:10px; color:var(--muted);">No shares found.</td></tr>`}</tbody>
    </table></div>
    <div style="font-size:11px; color:var(--muted); margin-top:8px;">Admins always have full access. Users always have their own home folder. "inherit" uses the share's Samba user lists, then the share default, then the setting above.</div>`;
}

export function collectShareAccess(root) {
  const out = { default_level: root.querySelector('#share-access-global')?.value || 'write', shares: {} };
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
  backdrop.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.55); z-index:10050; display:flex; align-items:center; justify-content:center;';
  backdrop.innerHTML = `
    <div role="dialog" aria-modal="true" aria-labelledby="share-access-title" style="background:var(--panel, #11161d); border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:16px; max-width:min(900px, 94vw); max-height:86vh; overflow:auto; color:#fff;">
      <div id="share-access-title" style="font-size:14px; font-weight:800; margin-bottom:10px;">Share access</div>
      <div id="share-access-body">${buildShareAccessHtml(data, plain)}</div>
      <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:14px;">
        <button type="button" id="share-access-cancel" class="btn-pill-toggle" style="padding:6px 12px; font-size:11px;">Cancel</button>
        <button type="button" id="share-access-save" class="btn-save-preset" style="padding:6px 14px; font-size:11.5px;">Save</button>
      </div>
    </div>`;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelector('#share-access-cancel').onclick = close;
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
