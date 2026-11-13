/**
 * Invite links (Batch 6): administrators create them in Users; the invited person opens
 * /#/invite/<token> while signed out, picks a username and password, and signs in.
 */
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

export const ROLES = () => [
  ['share_user', t('invite.role_member', 'Family member')],
  ['kid', t('invite.role_kid', 'Kid')],
  ['guest', t('invite.role_guest', 'Guest (read-only)')],
];

export function inviteTokenFromHash(hash) {
  const m = /^#\/invite\/([A-Za-z0-9_-]{16,100})$/.exec(hash || '');
  return m ? m[1] : null;
}

/** The role of an invite in the reader's language ("Family member", not "ShareUser"). */
export function inviteRoleName(info) {
  return Object.fromEntries(ROLES())[info?.role_id] || info?.role || '';
}

/**
 * Shows the sign-up form when the page was opened from an invite link. `textsReady` is the promise of the language loading: the
 * page was drawn before the texts were there, so it was in English whatever the language (SET-10).
 * @param {Promise<unknown>} [textsReady]
 */
export async function initInviteLanding(textsReady) {
  const token = inviteTokenFromHash(window.location.hash);
  if (!token) return false;
  try {
    await textsReady;
  } catch (e) {
    /* the page is then drawn in English */
  }
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
    <p>${escapeHtml(t('invite.as', 'Your account will be: {role}', { role: inviteRoleName(info) }))}</p>
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
