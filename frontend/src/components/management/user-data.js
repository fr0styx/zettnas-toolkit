// "Your data": download everything ZettNAS keeps about an account, or have its chats, Zetty log
// and search data forgotten (B8, backend/services/user_data.py). In Security for your own account;
// in the Edit user dialog for an administrator (a kid's account, for example).
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { html } from '../../html.js';
import { uiCard } from '../../ui/primitives.js';
import { showToast } from '../../toast.js';

const CARD_ID = 'user-data-card';

export function userDataHtml(user, own) {
  const desc = own
    ? t('udata.desc_own', 'Download what ZettNAS keeps about you: your account, chats with Zetty, when you asked it, and which of your files search learned. Or have your chats, that log and the search data forgotten; your files stay.')
    : t('udata.desc_other', "Download or erase what ZettNAS keeps about {name}: chats with Zetty, when they asked it, and which of their files search learned. Erasing leaves their files and account in place.", { name: user.display_name || user.username });
  return html`<p class="zn-muted">${desc}</p>
    <div class="zn-row">
      <button type="button" class="btn-pill-toggle" data-udata="export">${t('udata.export', 'Download data')}</button>
      <button type="button" class="btn-pill-toggle" data-udata="erase">${t('udata.erase', 'Erase chats, Zetty log and search data')}</button>
    </div>`;
}

function saveJson(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function renderUserData(card, user, own) {
  card.innerHTML = uiCard({ title: t('udata.title', 'Your data'), body: String(userDataHtml(user, own)), variant: 'divided' });
  card.querySelector('[data-udata="export"]')?.addEventListener('click', async (e) => {
    e.target.disabled = true;
    try {
      const data = await api.get(`/api/users/${encodeURIComponent(user.id)}/export`);
      saveJson(`zettnas-data-${user.username}-${new Date().toISOString().slice(0, 10)}.json`, data);
    } catch (err) {
      if (err?.error === 'cancelled') return;
      showToast(t('udata.export_failed', 'Could not download the data: {error}', { error: err.message }), 'error');
    } finally {
      e.target.disabled = false;
    }
  });
  card.querySelector('[data-udata="erase"]')?.addEventListener('click', async (e) => {
    e.target.disabled = true;
    try {
      // the server asks for confirmation first (428), which api.js turns into the confirm dialog
      await api.post(`/api/users/${encodeURIComponent(user.id)}/erase-data`, { parts: ['chats', 'ai_log', 'index'] });
      showToast(t('udata.erased', 'Chats, Zetty log and search data erased.'), 'success');
    } catch (err) {
      if (err?.error !== 'cancelled') showToast(t('udata.erase_failed', 'Could not erase: {error}', { error: err.message }), 'error');
    } finally {
      e.target.disabled = false;
    }
  });
}

/** Security pane: the card for your own account, after the sign-in cards. */
export async function installMyData(root = document) {
  const anchor = root.getElementById('sec-ldap-card');
  if (!anchor || root.getElementById(CARD_ID)) return;
  let me;
  try {
    me = await api.get('/api/auth/me');
  } catch {
    return;
  }
  const user = me.user || me;
  if (!user || !user.id) return;
  const card = Object.assign(document.createElement('div'), { id: CARD_ID, className: 'zn-card zn-card--divided' });
  anchor.insertAdjacentElement('afterend', card);
  renderUserData(card, user, true);
}

/** Edit user dialog: the same card for the account being edited. */
export function installUserDataFor(modal, user) {
  if (!modal || !user) return;
  let card = modal.querySelector(`#${CARD_ID}-edit`);
  if (!card) {
    card = Object.assign(document.createElement('div'), { id: `${CARD_ID}-edit` });
    (modal.querySelector('form') || modal).insertAdjacentElement('afterend', card);
  }
  renderUserData(card, user, false);
}
