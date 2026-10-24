/**
 * Invite links (Batch 6): administrators create them in Users; the invited person opens
 * /#/invite/<token> while signed out, picks a username and password, and signs in.
 */
import { api } from '../api.js';
import { escapeHtml, copyTextToClipboard } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';

const ROLES = () => [
  ['share_user', t('invite.role_member', 'Family member')],
  ['kid', t('invite.role_kid', 'Kid')],
  ['guest', t('invite.role_guest', 'Guest (read-only)')],
];

export function invitesHtml(invites) {
  const names = Object.fromEntries(ROLES());
  const rows = invites.length
    ? invites
        .map(
          (i) => `<li class="invite-row${i.active ? '' : ' is-used'}">
        <span class="invite-role">${escapeHtml(names[i.role_id] || i.role_id)}</span>
        <span class="invite-meta">${escapeHtml(i.note || '')} · ${escapeHtml(t('invite.uses', '{u} of {m} used', { u: i.uses, m: i.max_uses }))} · ${escapeHtml(
          t('invite.expires', 'until {d}', { d: formatDateTime(i.expires_at * 1000) }),
        )}</span>
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
      <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('invite.create', 'Create invite link'))}</button>
    </form>
    <div class="invite-link" data-invite-link hidden></div>`;
}

export async function renderInvites(mount) {
  if (!mount) return;
  try {
    const { invites } = await api.get('/api/invites');
    mount.innerHTML = invitesHtml(invites || []);
  } catch (e) {
    mount.hidden = true; // not allowed to manage users
    return;
  }
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

export function inviteTokenFromHash(hash) {
  const m = /^#\/invite\/([A-Za-z0-9_-]{16,100})$/.exec(hash || '');
  return m ? m[1] : null;
}

/** Shows the sign-up form when the page was opened from an invite link. */
export async function initInviteLanding() {
  const token = inviteTokenFromHash(window.location.hash);
  if (!token) return false;
  const dlg = document.createElement('dialog');
  dlg.className = 'invite-landing';
  dlg.setAttribute('aria-labelledby', 'invite-landing-title');
  document.body.appendChild(dlg);
  let info;
  try {
    info = await fetch(`/api/invite/${encodeURIComponent(token)}`).then((r) => (r.ok ? r.json() : Promise.reject(r)));
  } catch (e) {
    dlg.innerHTML = `<h2 id="invite-landing-title">${escapeHtml(t('invite.invalid_title', 'This invite has expired'))}</h2>
      <p>${escapeHtml(t('invite.invalid', 'Ask whoever sent it for a new link.'))}</p>`;
    dlg.showModal?.();
    return true;
  }
  dlg.innerHTML = `<h2 id="invite-landing-title">${escapeHtml(t('invite.welcome', 'You are invited to this NAS'))}</h2>
    <p>${escapeHtml(t('invite.as', 'Your account will be: {role}', { role: info.role }))}</p>
    <form data-invite-accept class="invite-accept">
      <label>${escapeHtml(t('invite.username', 'Username'))}<input name="username" required minlength="2" maxlength="32" pattern="[a-z_][a-z0-9_.\\-]*" autocomplete="username"></label>
      <label>${escapeHtml(t('invite.display', 'Your name'))}<input name="display_name" maxlength="80" autocomplete="name"></label>
      <label>${escapeHtml(t('invite.password', 'Password (8 characters or more)'))}<input name="password" type="password" required minlength="8" autocomplete="new-password"></label>
      <label>${escapeHtml(t('invite.password2', 'Password again'))}<input name="password2" type="password" required minlength="8" autocomplete="new-password"></label>
      <p class="invite-error" role="alert" hidden></p>
      <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('invite.join', 'Create my account'))}</button>
    </form>`;
  const err = dlg.querySelector('.invite-error');
  dlg.querySelector('[data-invite-accept]').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    if (f.get('password') !== f.get('password2')) {
      err.hidden = false;
      err.textContent = t('setup.err_no_match', 'New password and confirmation do not match.');
      return;
    }
    const r = await fetch(`/api/invite/${encodeURIComponent(token)}/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: String(f.get('username')).toLowerCase(), display_name: f.get('display_name'), password: f.get('password') }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      err.hidden = false;
      err.textContent = body.detail || body.message || t('invite.failed', 'That did not work; try another username.');
      return;
    }
    dlg.close();
    history.replaceState(null, '', window.location.pathname);
    const u = document.getElementById('login-username');
    if (u) u.value = body.username;
    showToast(t('invite.done', 'Account created. Sign in with your new password.'), 'success');
  });
  dlg.showModal?.();
  return true;
}
