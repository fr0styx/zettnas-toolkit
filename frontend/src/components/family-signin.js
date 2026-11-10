/**
 * One family sign-in for the apps (NFEAT-6): the Users card that turns Pocket ID on, keeps its
 * people in step with Kiboto's, sends sign-in links and connects apps.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { escapeHtml } from '../utils.js';

const esc = escapeHtml;

function offHtml(st) {
  const why = st.https_ready
    ? ''
    : `<div class="nsv-xs-muted-2">${esc(t('fs.needs_https', 'Passkeys need https: turn on HTTPS in Network → Use from anywhere first.'))}</div>`;
  return `<p class="nsv-xs-muted">${esc(t('fs.intro', 'One sign-in with a passkey for the family\'s apps (Immich, Nextcloud, Paperless, Audiobookshelf, Jellyfin), run by Kiboto with Pocket ID.'))}</p>${why}
    <button type="button" class="btn-pill-toggle is-primary is-small" data-fs="on"${st.https_ready ? '' : ' disabled'}>${esc(t('fs.turn_on', 'Turn on family sign-in'))}</button>`;
}

function appsHtml(apps) {
  if (!apps.length) return `<div class="nsv-xs-muted-2">${esc(t('fs.no_apps', 'None of the apps it can connect is running here yet.'))}</div>`;
  return `<ul class="fs-apps">${apps
    .map((a) => `<li><strong>${esc(a.name)}</strong> ${
      a.connected
        ? `<span class="nsv-xs-muted">${esc(t('fs.connected', 'connected'))}</span>
           <button type="button" class="btn-pill-toggle is-small" data-fs-connect="${esc(a.key)}">${esc(t('fs.new_secret', 'New secret'))}</button>
           <button type="button" class="btn-pill-toggle is-small is-danger" data-fs-disconnect="${esc(a.key)}">${esc(t('fs.disconnect', 'Disconnect'))}</button>`
        : `<button type="button" class="btn-pill-toggle is-small is-primary" data-fs-connect="${esc(a.key)}">${esc(t('fs.connect', 'Connect'))}</button>`
    }</li>`)
    .join('')}</ul>`;
}

function peopleHtml(users) {
  return `<ul class="fs-people">${users
    .filter((u) => u.status === 'active')
    .map((u) => `<li><span>${esc(u.display_name || u.username)}</span>
      <button type="button" class="btn-pill-toggle is-small" data-fs-link="${esc(String(u.id))}">${esc(t('fs.link', 'Send a sign-in link'))}</button></li>`)
    .join('')}</ul>`;
}

/** The card's body. */
export function familySigninHtml(st, users) {
  if (!st.enabled) return offHtml(st);
  const state = st.running ? t('fs.running', 'Running') : t('fs.starting', 'Starting…');
  const open = st.url ? ` · <a href="${esc(st.url)}" target="_blank" rel="noopener">${esc(t('fs.open', 'Open Pocket ID'))}</a>` : '';
  return `<div class="nsv-xs-muted">${esc(state)} · ${esc(t('fs.people', '{count, plural, one {# person} other {# people}}', { count: st.people }))}${open}</div>
    <h4 class="fs-h">${esc(t('fs.people_h', 'People'))}</h4>
    <div class="nsv-xs-muted-2">${esc(t('fs.people_help', 'Everyone with a Kiboto account has one here. Pocket ID has no passwords: send each person a link that signs them in once, to add a passkey on their phone.'))}</div>
    ${peopleHtml(users)}
    <button type="button" class="btn-pill-toggle is-small" data-fs="sync">${esc(t('fs.sync', 'Update people now'))}</button>
    <h4 class="fs-h">${esc(t('fs.apps_h', 'Apps'))}</h4>${appsHtml(st.apps)}
    <div data-fs-result aria-live="polite"></div>
    <button type="button" class="btn-pill-toggle is-small is-danger" data-fs="off">${esc(t('fs.turn_off', 'Turn off'))}</button>`;
}

/** What to paste into the app after connecting it (the secret is shown this once). */
export function connectedHtml(r) {
  const row = (label, value) => `<div class="fs-row"><span>${esc(label)}</span><code>${esc(value)}</code>
    <button type="button" class="btn-pill-toggle is-small" data-fs-copy="${esc(value)}">${esc(t('fs.copy', 'Copy'))}</button></div>`;
  return `<div class="fs-result"><strong>${esc(t('fs.paste_into', 'Paste into {app}:', { app: r.name }))}</strong>
    ${row(t('fs.issuer', 'Issuer URL'), r.issuer)}${row(t('fs.client_id', 'Client ID'), r.client_id)}${row(t('fs.secret', 'Client secret'), r.client_secret)}
    <div class="nsv-xs-muted">${esc(r.where)}</div>
    <div class="pa-warn">${esc(t('fs.secret_once', 'The secret is shown only now. Lost it? Press New secret.'))}</div></div>`;
}

let last = { st: null, users: [] };

function render(mount, st, users = last.users) {
  last = { st, users };
  mount.innerHTML = familySigninHtml(st, users);
}

async function act(mount, fn) {
  try {
    const st = await fn();
    render(mount, st);
    return st;
  } catch (err) {
    if (/** @type {any} */ (err).status !== 428) showToast(/** @type {Error} */ (err).message, 'error');
    return null;
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(t('fs.copied', 'Copied.'), 'success');
  } catch {
    showToast(t('fs.copy_failed', 'Copying didn\'t work here; select the text and copy it.'), 'error');
  }
}

async function onClick(mount, e) {
  const el = /** @type {Element} */ (e.target);
  const hit = (attr) => el.closest(`[${attr}]`)?.getAttribute(attr);
  const action = hit('data-fs');
  if (action === 'on') act(mount, () => api.put('/api/family-signin', { enabled: true }));
  if (action === 'off') act(mount, () => api.put('/api/family-signin', { enabled: false }));
  if (action === 'sync') act(mount, () => api.post('/api/family-signin/sync', {}));
  const value = hit('data-fs-copy');
  if (value) copy(value);
  const link = hit('data-fs-link');
  if (link) {
    try {
      const r = await api.post(`/api/family-signin/users/${encodeURIComponent(link)}/link`, {});
      await copy(r.url);
    } catch (err) {
      showToast(/** @type {Error} */ (err).message, 'error');
    }
  }
  const app = hit('data-fs-connect');
  if (app) {
    try {
      const r = await api.post(`/api/family-signin/apps/${encodeURIComponent(app)}`, {});
      render(mount, await api.get('/api/family-signin'));
      const box = mount.querySelector('[data-fs-result]');
      if (box) box.innerHTML = connectedHtml(r);
    } catch (err) {
      if (/** @type {any} */ (err).status !== 428) showToast(/** @type {Error} */ (err).message, 'error');
    }
  }
  const off = hit('data-fs-disconnect');
  if (off) act(mount, () => api.delete(`/api/family-signin/apps/${encodeURIComponent(off)}`));
}

/** Fills the card in the Users pane and wires it once. */
export async function renderFamilySignin(mount) {
  if (!mount.dataset.bound) {
    mount.dataset.bound = '1';
    mount.classList.add('fs-card');
    mount.addEventListener('click', (e) => onClick(mount, e));
  }
  try {
    const [st, list] = await Promise.all([api.get('/api/family-signin'), api.get('/api/users')]);
    render(mount, st, list.users || []);
  } catch (err) {
    mount.textContent = /** @type {Error} */ (err).message || '';
  }
}
