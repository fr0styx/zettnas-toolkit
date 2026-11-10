/**
 * "Require two-step sign-in" per role, in Mission Control → Security (administrators).
 * People in a ticked role who haven't turned it on can sign in only to set it up.
 */
import { api } from '../../api.js';
import { showToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { formatRole } from '../role-names.js';

export const POLICY_ROLES = ['superadmin', 'storage_admin', 'app_operator', 'backup_operator', 'auditor', 'share_user', 'kid', 'guest'];

export function mfaPolicyHtml(view) {
  const required = new Set(view?.required_roles || []);
  const missing = view?.without_two_step || {};
  const rows = POLICY_ROLES.map((role) => {
    const count = missing[role] || 0;
    const note = count ? ` <span class="immich-note">${escapeHtml(t('sec.mfa_policy_missing', '{count} without it', { count }))}</span>` : '';
    return `<label><input type="checkbox" data-mfa-role="${escapeHtml(role)}"${required.has(role) ? ' checked' : ''}> ${escapeHtml(formatRole(role))}${note}</label>`;
  }).join('');
  return `<h4>${escapeHtml(t('sec.mfa_policy_title', 'Require two-step sign-in'))}</h4>
    <p class="immich-note">${escapeHtml(t('sec.mfa_policy_desc', 'People in the roles you tick must turn on two-step sign-in. Until they do, they can sign in only to set it up.'))}</p>
    <div class="sec-col-xs">${rows}</div>`;
}

export function selectedRoles(root) {
  return [...root.querySelectorAll('input[data-mfa-role]')].filter((box) => box.checked).map((box) => box.dataset.mfaRole);
}

export async function renderMfaPolicy() {
  const anchor = document.getElementById('sec-advisor-card');
  if (!anchor) return;
  let box = document.getElementById('sec-mfa-policy');
  if (!box) {
    box = document.createElement('div');
    box.id = 'sec-mfa-policy';
    box.className = 'sec-advisor-card';
    anchor.after(box);
  }
  let view;
  try {
    view = await api.get('/api/security/mfa-policy');
  } catch {
    box.hidden = true; // not an administrator, or an older server
    return;
  }
  box.hidden = false;
  box.innerHTML = mfaPolicyHtml(view);
  box.onchange = async (e) => {
    const changed = /** @type {HTMLInputElement | null} */ (/** @type {Element} */ (e.target).closest('input[data-mfa-role]'));
    if (!changed) return;
    try {
      const next = await api.put('/api/security/mfa-policy', { required_roles: selectedRoles(box) });
      box.innerHTML = mfaPolicyHtml(next);
      showToast(t('sec.mfa_policy_saved', 'Saved.'), 'success');
    } catch (err) {
      changed.checked = !changed.checked;
      showToast(err?.message || t('sec.mfa_policy_failed', "That didn't save."), 'error');
    }
  };
}
