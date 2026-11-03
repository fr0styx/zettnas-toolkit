/**
 * A separate password for the shared folders over the network (SMB), for accounts with two-step
 * sign-in (B11, SEC-28): SMB can't ask for a code, so since 1.12 the account password no longer
 * opens the shares. The password is shown once; making a new one replaces it.
 */
import { apiFetch } from '../api.js';
import { t } from '../i18n.js';
import { showToast, showPromptToast } from '../toast.js';
import { copyText } from '../utils.js';

/** Shows the new password once, with a copy button. */
export function renderSmbPassword(box, { username, password }) {
  if (!box) return;
  const note = document.createElement('p');
  note.className = 'smb-pw-note';
  note.textContent = t(
    'smb.shown_once',
    'Your shared folders password. It is shown only now: when your computer asks for a password to open the shared folders, enter the username {username} and this password. Making a new one replaces it.',
    { username },
  );
  const code = document.createElement('code');
  code.className = 'smb-pw-value';
  code.textContent = password;
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'btn-pill-toggle is-small';
  copy.textContent = t('smb.copy', 'Copy');
  copy.addEventListener('click', async () => {
    try {
      await copyText(password);
      copy.textContent = t('smb.copied', 'Copied');
    } catch {
      const range = document.createRange();
      range.selectNodeContents(code);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
    }
  });
  const row = document.createElement('div');
  row.className = 'smb-pw-row';
  row.append(code, copy);
  box.replaceChildren(note, row);
  box.hidden = false;
}

/** Asks the server for a new password; null when it was refused (the reason is shown). */
export async function makeSmbPassword(currentPassword, box) {
  let res;
  try {
    res = await apiFetch('/api/auth/me/smb-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ current_password: currentPassword }),
    });
  } catch {
    showToast(t('smb.failed', 'The password could not be made.'), 'error');
    return null;
  }
  const data = (await res.json().catch(() => null)) || {};
  if (!res.ok) {
    showToast(data.detail || t('smb.failed', 'The password could not be made.'), 'error');
    return null;
  }
  renderSmbPassword(box, data);
  return data;
}

/** The button: asks for the account password first. */
export function askForSmbPassword(box = document.getElementById('smb-password-box')) {
  showPromptToast(
    t('smb.title', 'Shared folders password'),
    t('smb.pwd_prompt', 'Enter your account password to make a password for the shared folders (SMB):'),
    '',
    (pwd) => (pwd ? makeSmbPassword(pwd, box) : undefined),
    null,
    { inputType: 'password', okText: t('smb.make_ok', 'Make it'), cancelText: t('common.cancel', 'Cancel') },
  );
}
