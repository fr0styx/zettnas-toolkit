// "Lost phone or tablet?" in a person's edit dialog (Users decision 8, SET-19 stage 2): sign them
// out on every device and, if asked, turn off their two-step code so they can set it up on a new
// phone. The server asks for the administrator's own password and tells the person.
import { api } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';

/** The section's inside, closed: nothing happens until someone opens it and presses the button. */
export function lostDeviceHtml(name) {
  return `<summary>${escapeHtml(t('lost.title', 'Lost phone or tablet?'))}</summary>
    <p class="usr-xs-muted">${escapeHtml(t('lost.help', 'Sign {name} out on every device. If their two-step code was on that phone, turn it off too, so they can set it up on a new one. They are told.', { name }))}</p>
    <label class="lost-row"><input type="checkbox" data-lost-sign-out checked> ${escapeHtml(t('lost.sign_out', 'Sign out on every device'))}</label>
    <label class="lost-row"><input type="checkbox" data-lost-two-step> ${escapeHtml(t('lost.two_step', 'Turn off two-step sign-in'))}</label>
    <label class="lost-row">${escapeHtml(t('lost.own_pw', 'Your own password'))} <input type="password" class="tz-text-input" autocomplete="current-password" data-lost-pw></label>
    <button type="button" class="btn-pill-toggle is-small is-danger" data-lost-go>${escapeHtml(t('lost.go', 'Do this now'))}</button>`;
}

/** What was done, in one sentence for the toast. */
export function lostDoneText(r, name, signedOut) {
  const parts = [];
  if (r.sessions_ended) parts.push(t('lost.done_signed_out', '{n, plural, one {Ended # session of {name}.} other {Ended # sessions of {name}.}}', { n: r.sessions_ended, name }));
  else if (signedOut) parts.push(t('lost.done_none', '{name} was not signed in anywhere.', { name }));
  if (r.two_step_off) parts.push(t('lost.done_two_step', 'Two-step sign-in is off for {name}.', { name }));
  if (r.sessions_ended || r.two_step_off) {
    parts.push(r.told ? t('lost.done_told', 'They were told.') : t('lost.done_not_told', 'Kiboto could not tell them: they have no alerts or email set up.'));
  }
  return parts.join(' ');
}

/** Sends the request; the password field is emptied either way. */
export async function submitLostDevice(box, user) {
  const pw = /** @type {HTMLInputElement} */ (box.querySelector('[data-lost-pw]'));
  const signOut = /** @type {HTMLInputElement} */ (box.querySelector('[data-lost-sign-out]')).checked;
  const twoStep = /** @type {HTMLInputElement} */ (box.querySelector('[data-lost-two-step]')).checked;
  if (!signOut && !twoStep) {
    showToast(t('lost.choose', 'Choose at least one of the two.'), 'error');
    return null;
  }
  const password = pw.value;
  pw.value = '';
  try {
    const r = await api.post(`/api/users/${encodeURIComponent(user.id)}/lost-device`, { current_password: password, sign_out: signOut, turn_off_two_step: twoStep });
    showToast(lostDoneText(r, user.username, signOut), 'success');
    return r;
  } catch (err) {
    showToast(/** @type {Error} */ (err).message, 'error');
    return null;
  }
}

/** Adds the section under the dialog; hidden for the person's own account (My account does that). */
export function installLostDeviceFor(modal, user, me = null) {
  if (!modal || !user) return null;
  let box = /** @type {HTMLDetailsElement | null} */ (modal.querySelector('#lost-device'));
  if (!box) {
    box = document.createElement('details');
    box.id = 'lost-device';
    box.className = 'lost-device';
    (modal.querySelector('#passkeys-reset') || modal.querySelector('form') || modal).insertAdjacentElement('afterend', box);
  }
  box.open = false;
  box.hidden = Boolean(me && me.id === user.id);
  box.innerHTML = lostDeviceHtml(user.username);
  const section = box;
  /** @type {HTMLElement} */ (box.querySelector('[data-lost-go]')).onclick = () => submitLostDevice(section, user);
  return box;
}
