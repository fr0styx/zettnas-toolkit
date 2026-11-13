/**
 * Invite links, the administrators' side (Batch 6, SET-19): the list and the form in People, with
 * the folders and sign-in hours an invite gives. It loads with People; invites.js keeps the invited
 * person's page, which the first page needs.
 */
import { api } from '../api.js';
import { escapeHtml, copyTextToClipboard } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';
import { ROLES } from './invites.js';

const LEVELS = () => [
  ['', t('invite.folder_none', 'No access')],
  ['read', t('invite.folder_read', 'Can open')],
  ['write', t('invite.folder_write', 'Can change')],
];

/** What an invite gives besides its role, for its row (SET-19). */
export function inviteExtrasText(invite) {
  const parts = [];
  const n = Object.keys(invite.shares || {}).length;
  if (n) parts.push(t('invite.folders_n', '{n, plural, one {# folder} other {# folders}}', { n }));
  if (invite.signin_hours) parts.push(t('invite.with_hours', 'with sign-in hours'));
  return parts.join(' · ');
}

/** One choice per shared folder; "No access" by default. */
export function inviteSharesHtml(shares) {
  return shares
    .map(
      (s) => `<label class="invite-share">${escapeHtml(s.name)}<select data-share="${escapeHtml(s.name)}">${LEVELS()
        .map(([v, name]) => `<option value="${v}">${escapeHtml(name)}</option>`)
        .join('')}</select></label>`,
    )
    .join('');
}

/** {folder: level} for the folders given any access. */
export function readInviteShares(form) {
  const out = {};
  form.querySelectorAll('[data-share]').forEach((sel) => {
    if (sel.value) out[sel.dataset.share] = sel.value;
  });
  return out;
}

/** The hours box as the server wants them: null when off. */
export function hoursOrNull(hours) {
  return hours && Object.keys(hours).length ? hours : null;
}

export function invitesHtml(invites, shares = []) {
  const names = Object.fromEntries(ROLES());
  const rows = invites.length
    ? invites
        .map(
          (i) => `<li class="invite-row${i.active ? '' : ' is-used'}">
        <span class="invite-role">${escapeHtml(names[i.role_id] || i.role_id)}</span>
        <span class="invite-meta">${escapeHtml(i.note || '')} · ${escapeHtml(t('invite.uses', '{u} of {m} used', { u: i.uses, m: i.max_uses }))} · ${escapeHtml(
          t('invite.expires', 'until {d}', { d: formatDateTime(i.expires_at * 1000) }),
        )}${inviteExtrasText(i) ? ` · ${escapeHtml(inviteExtrasText(i))}` : ''}</span>
        ${i.active ? `<button type="button" class="btn-pill-toggle is-small is-danger" data-invite-revoke="${escapeHtml(i.id)}">${escapeHtml(t('invite.revoke', 'Revoke'))}</button>` : ''}
      </li>`,
        )
        .join('')
    : `<li class="invite-meta">${escapeHtml(t('invite.none', 'No invites yet.'))}</li>`;
  return `<ul class="invite-list">${rows}</ul>
    <form class="invite-form" data-invite-form>
      <label>${escapeHtml(t('invite.role', 'As'))}<select name="role_id">${ROLES()
        .map(([id, name]) => `<option value="${id}">${escapeHtml(name)}</option>`)
        .join('')}</select></label>
      <label>${escapeHtml(t('invite.note', 'For'))}<input name="note" maxlength="120" placeholder="${escapeHtml(t('invite.note_ph', 'Grandma'))}"></label>
      <label>${escapeHtml(t('invite.days', 'Valid for days'))}<input name="days" type="number" min="1" max="90" value="7"></label>
      <label>${escapeHtml(t('invite.quota', 'Space (GB, 0 = no limit)'))}<input name="quota_gb" type="number" min="0" value="0"></label>
      <fieldset class="invite-shares"${shares.length ? '' : ' hidden'}><legend>${escapeHtml(t('invite.folders', 'Shared folders'))}</legend>${inviteSharesHtml(shares)}</fieldset>
      <fieldset class="invite-hours"><legend>${escapeHtml(t('invite.hours', 'Sign-in hours'))}</legend><div data-invite-hours></div></fieldset>
      <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('invite.create', 'Create invite link'))}</button>
    </form>
    <div class="invite-link" data-invite-link hidden></div>`;
}

export async function renderInvites(mount) {
  if (!mount) return;
  try {
    const [{ invites }, access] = await Promise.all([api.get('/api/invites'), api.get('/api/storage/share-access').catch(() => null)]);
    mount.innerHTML = invitesHtml(invites || [], access?.shares || []); // folders only for who manages them
  } catch (e) {
    mount.hidden = true; // not allowed to manage users
    return;
  }
  const hoursBox = mount.querySelector('[data-invite-hours]');
  const hours = await import('./signin-hours.js');
  hours.installSigninHours(hoursBox, null);
  mount.querySelector('[data-invite-form]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const res = await api.post('/api/invites', {
        role_id: f.get('role_id'),
        note: f.get('note'),
        days: Number(f.get('days')),
        quota_gb: Number(f.get('quota_gb')),
        max_uses: 1,
        shares: readInviteShares(e.target), // SET-19: what comes with the role
        signin_hours: hoursOrNull(hours.readHours(hoursBox)),
      });
      const url = `${window.location.origin}${window.location.pathname}${res.link.replace(/^\//, '')}`;
      await renderInvites(mount);
      const box = mount.querySelector('[data-invite-link]');
      box.hidden = false;
      box.innerHTML = `<p>${escapeHtml(t('invite.share_once', 'Send this link to them. It works once and is shown only now:'))}</p>
        <code>${escapeHtml(url)}</code>
        <button type="button" class="btn-pill-toggle is-small" data-invite-copy>${escapeHtml(t('ui.copy_url', 'Copy URL'))}</button>`;
      box.querySelector('[data-invite-copy]').onclick = () => copyTextToClipboard(url).then(() => showToast(t('ui.copied', 'Copied'), 'info'));
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  mount.querySelectorAll('[data-invite-revoke]').forEach((b) =>
    b.addEventListener('click', async () => {
      await api.delete(`/api/invites/${encodeURIComponent(b.dataset.inviteRevoke)}`);
      renderInvites(mount);
    }),
  );
}
