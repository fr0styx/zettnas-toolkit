/**
 * Kids' rules in one place (NUX-18): for each kid and guest account, when they may sign in and
 * whether their devices are filtered, plus whether kids may ask Kib or use AI search. Each
 * rule is still stored where it was (the person, the family filter, AI access); this card shows
 * them together and changes them from here.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { html } from '../html.js';
import { dayNames } from './signin-hours.js';
import { formatRole } from './role-names.js';

export const KID_ROLES = ['kid', 'guest'];

/** "Mon–Fri 07:00–20:00", or "Any time" without a limit. */
export function hoursText(hours, names = dayNames()) {
  if (!hours || !Array.isArray(hours.days)) return t('kids.any_time', 'Any time');
  const days = [...hours.days].sort((a, b) => a - b);
  let when;
  if (days.length === 7) when = t('kids.every_day', 'Every day');
  else if (days.length > 2 && days[days.length - 1] - days[0] === days.length - 1) when = `${names[days[0]]}–${names[days[days.length - 1]]}`;
  else when = days.map((d) => names[d]).join(', ');
  return `${when} ${hours.start}–${hours.end}`;
}

const roleName = (roleId) => formatRole(roleId);

/** One switch per kid role and feature; null when AI access isn't the viewer's to change. */
export function aiSwitchesHtml(access) {
  const roles = (access?.roles || []).filter((r) => KID_ROLES.includes(r.id));
  if (!roles.length) return null;
  return html`<div class="kids-ai" role="group" aria-label="${t('kids.ai', 'Kib, the AI helper')}">
    ${roles.map(
      (r) => html`<div class="kids-ai-row"><span class="kids-ai-role">${roleName(r.id)}</span>
        <label class="kb-toggle"><input type="checkbox" role="switch" data-kids-ai="roles" data-role="${r.id}" ${r.on ? 'checked' : ''}><span>${t('ai.access_ask', 'Ask Kib')}</span></label>
        <label class="kb-toggle"><input type="checkbox" role="switch" data-kids-ai="search_roles" data-role="${r.id}" ${r.search !== false ? 'checked' : ''}><span>${t('ai.access_search', 'AI search')}</span></label></div>`,
    )}</div>`;
}

function filterText(people, username) {
  const saved = (people || {})[username];
  const n = saved?.devices?.length || 0;
  return n ? t('ff.filtered', '{n, plural, one {# device filtered} other {# devices filtered}}', { n }) : t('ff.not_filtered', 'Not filtered');
}

/** The card's contents: the accounts, then the AI switches. `filter` is null without AdGuard access. */
export function kidsRulesHtml(users, access, filter) {
  const kids = (users || []).filter((u) => KID_ROLES.includes(u.role_id));
  const rows = kids.length
    ? html`<table class="kb-datatable kids-table"><thead><tr>
        <th>${t('users.col_person', 'Person')}</th><th>${t('kids.col_hours', 'May sign in')}</th>
        <th>${t('kids.col_devices', 'Their devices')}</th><th></th></tr></thead>
      <tbody>${kids.map(
        (u) => html`<tr data-kid="${u.id}"><td>${u.display_name || u.username} <span class="kb-muted">${roleName(u.role_id)}</span></td>
          <td>${hoursText(u.signin_hours)}</td>
          <td>${filter ? filterText(filter.people, u.username) : '—'}</td>
          <td class="kids-actions"><button type="button" class="btn-pill-toggle is-small" data-kids-edit="${u.id}">${t('kids.change_hours', 'Change hours')}</button>
            ${filter ? html`<button type="button" class="btn-pill-toggle is-small" data-kids-filter>${t('kids.change_devices', 'Filter devices')}</button>` : ''}</td></tr>`,
      )}</tbody></table>`
    : html`<p class="kb-muted">${t('kids.none', 'No kid or guest accounts yet. Add a person with the Kid role to set their rules here.')}</p>`;
  const ai = aiSwitchesHtml(access);
  return html`${rows}
    ${ai ? html`<h5 class="kids-sub">${t('kids.ai', 'Kib, the AI helper')}</h5>${ai}` : ''}
    <p class="kids-more"><button type="button" class="btn-pill-toggle is-small" data-kids-shares>${t('kids.shares', 'Which shared folders they can open')}</button></p>`;
}

/**
 * Fills the mount for these accounts. onEdit(userId) opens the person's dialog (sign-in hours);
 * onShares() opens the shared folders dialog.
 * @param {HTMLElement | null} mount
 * @param {Array<Record<string, any>>} users
 * @param {{ onEdit?: (id: string) => void, onShares?: () => void }} [opts]
 */
export async function renderKidsRules(mount, users, { onEdit, onShares } = {}) {
  if (!mount) return;
  const [access, filter] = await Promise.all([
    api.get('/api/ai/access').catch(() => null),
    api.get('/api/family-filter').catch(() => null),
  ]);
  mount.innerHTML = String(kidsRulesHtml(users, access, filter));
  mount.onclick = (e) => {
    const b = /** @type {HTMLElement} */ (e.target).closest('button');
    if (!b) return;
    if (b.dataset.kidsEdit && onEdit) onEdit(b.dataset.kidsEdit);
    else if ('kidsShares' in b.dataset && onShares) onShares();
    else if ('kidsFilter' in b.dataset) document.getElementById('ff-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  mount.querySelectorAll('[data-kids-ai]').forEach((sw) => {
    const box = /** @type {HTMLInputElement} */ (sw);
    box.addEventListener('change', async () => {
      box.disabled = true;
      try {
        await api.put('/api/ai/access', { [box.dataset.kidsAi]: { [box.dataset.role]: box.checked } });
      } catch {
        box.checked = !box.checked;
      }
      box.disabled = false;
    });
  });
}
