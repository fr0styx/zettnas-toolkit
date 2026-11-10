/**
 * Family from anywhere (NFEAT-1): the card in Network → File Sharing Services that invites each
 * Kiboto user to reach this NAS (and nothing else) through their own Tailscale account, with a
 * guided page to send them.
 */
import { api } from '../../api.js';
import '../../styles/80-public-apps.css'; // the list and warning styles it shares with Apps from anywhere
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';

const $ = (id) => document.getElementById(id);
const esc = escapeHtml;

const STATE_TEXT = {
  invited: ['fa.invited', 'Invited, not joined yet'],
  expired: ['fa.expired', 'Invite expired'],
  joined: ['fa.joined', 'Joined'],
  online: ['fa.online', 'Joined · online now'],
};

/** What the person is sent: the guided page when it opens from anywhere, else Tailscale's link with the steps. */
export function inviteMessage(p) {
  if (p.page_url) return t('fa.msg_page', "Hi {name}! Here's your way into our Kiboto from anywhere: {url}", { name: p.name, url: p.page_url });
  return t('fa.msg_plain', "Hi {name}! To reach our Kiboto from anywhere: 1) install the Tailscale app, 2) sign in with Google, Apple or Microsoft, 3) open this invite: {url}", { name: p.name, url: p.invite_url });
}

function keyHtml(st) {
  if (st.has_key) {
    const left = st.key_days_left;
    const when = left === null || left === undefined ? t('fa.key_kept', 'Tailscale API key kept.') : t('fa.key_left', 'Tailscale API key kept; it runs out in {count, plural, one {# day} other {# days}}.', { count: Math.max(0, left) });
    return `<div class="${st.key_expiring ? 'pa-warn' : 'nsv-xs-muted'}">${esc(when)}${st.key_expiring ? ` ${esc(t('fa.key_soon', 'Make a new one before then, or new invites stop working.'))}` : ''}
      <button type="button" class="btn-pill-toggle is-small" data-fa="replace-key">${esc(t('fa.replace', 'Replace'))}</button>
      <button type="button" class="btn-pill-toggle is-small is-danger" data-fa="forget-key">${esc(t('fa.forget', 'Remove'))}</button></div>`;
  }
  return `<form class="fa-key" data-fa-key><div class="nsv-xs-muted">${esc(t('fa.key_steps', 'Once: open Tailscale\'s Keys page, make an API access key (it lasts up to 90 days) and paste it here. Kiboto keeps it sealed and only uses it to make invites.'))}
    <a href="${esc(st.keys_page)}" target="_blank" rel="noopener">${esc(t('fa.keys_page', 'Open the Keys page'))}</a></div>
    <input type="password" name="key" autocomplete="off" placeholder="tskey-api-…" aria-label="${esc(t('fa.key_label', 'Tailscale API access key'))}">
    <button type="submit" class="btn-pill-toggle is-primary is-small">${esc(t('fa.save_key', 'Save key'))}</button></form>`;
}

function personHtml(user, p, canInvite) {
  const name = esc(user.display_name || user.username);
  const id = esc(String(user.id));
  if (!p || p.state === 'expired') {
    const note = p ? `<span class="nsv-xs-muted">${esc(t(...STATE_TEXT.expired))}</span>` : '';
    return `<li class="pa-item"><span><strong>${name}</strong> ${note}</span>${
      canInvite ? `<button type="button" class="btn-pill-toggle is-small is-primary" data-fa-invite="${id}">${esc(t('fa.invite', 'Invite'))}</button>` : ''
    }</li>`;
  }
  const state = esc(t(...STATE_TEXT[p.state]));
  const who = p.login ? ` · ${esc(p.login)}` : '';
  const actions = p.state === 'invited'
    ? `<button type="button" class="btn-pill-toggle is-small" data-fa-copy="${id}">${esc(t('fa.copy', 'Copy message'))}</button>
       <button type="button" class="btn-pill-toggle is-small" data-fa-qr="${id}">${esc(t('fa.qr', 'QR code'))}</button>
       <button type="button" class="btn-pill-toggle is-small is-danger" data-fa-revoke="${id}">${esc(t('fa.withdraw', 'Withdraw'))}</button>`
    : `<button type="button" class="btn-pill-toggle is-small is-danger" data-fa-revoke="${id}">${esc(t('fa.revoke', 'Remove access'))}</button>`;
  return `<li class="pa-item"><span><strong>${name}</strong> · ${state}${who}</span><span>${actions}</span><div class="remote-qr" data-fa-qrbox="${id}" hidden></div></li>`;
}

/** The card's body from the status and the Kiboto users. */
export function familyAccessHtml(st, users) {
  if (!st.tailscale) return `<div class="nsv-xs-muted">${esc(t('pl.no_tailscale', 'Needs Tailscale: connect it in Network → WireGuard & Tailscale first.'))}</div>`;
  if (st.headscale) return `<div class="nsv-xs-muted">${esc(t('fa.headscale', 'This NAS uses your own Headscale server: give each person a key from it instead. Share invites are a Tailscale service.'))}</div>`;
  const byUser = new Map(st.people.map((p) => [String(p.user_id), p]));
  const rows = users.filter((u) => u.status === 'active').map((u) => personHtml(u, byUser.get(String(u.id)), st.has_key)).join('');
  const pageNote = st.public_page ? '' : `<div class="nsv-xs-muted-2">${esc(t('fa.no_public', 'Turn on "Share links from anywhere" so the invite page opens from anywhere; until then the message carries Tailscale\'s own link and the steps.'))}</div>`;
  return `${keyHtml(st)}<ul class="pa-list">${rows}</ul>${pageNote}<div class="nsv-xs-muted-2">${esc(t('fa.help', 'Each person gets their own free Tailscale account and sees only this NAS, nothing else on your network. They still sign in to Kiboto with their own name and password.'))}</div>`;
}

let last = { st: null, users: [] };

function render(st, users = last.users) {
  last = { st, users };
  const body = $('fa-body');
  if (body) body.innerHTML = familyAccessHtml(st, users);
}

async function act(fn) {
  try {
    const st = await fn();
    render(st);
    if (st.remove_share_at) {
      showToast(t('fa.remove_share', 'Kiboto no longer lists them. To cut their connection too, remove the share in Tailscale: Machines → this NAS → Sharing.'), 'info');
      window.open(st.remove_share_at, '_blank', 'noopener');
    }
    return st;
  } catch (err) {
    if (/** @type {any} */ (err).status !== 428) showToast(/** @type {Error} */ (err).message, 'error');
    return null;
  }
}

const personFor = (id) => (last.st?.people || []).find((p) => String(p.user_id) === id);

async function onClick(e) {
  const el = /** @type {Element} */ (e.target);
  const hit = (attr) => el.closest(`[${attr}]`)?.getAttribute(attr);
  const action = hit('data-fa');
  if (action === 'forget-key') act(() => api.delete('/api/network/family-access/key'));
  if (action === 'replace-key' && last.st) render({ ...last.st, has_key: false });
  const invite = hit('data-fa-invite');
  if (invite) act(() => api.post('/api/network/family-access/invites', { user_id: invite }));
  const revoke = hit('data-fa-revoke');
  if (revoke) act(() => api.delete(`/api/network/family-access/invites/${encodeURIComponent(revoke)}`));
  const copy = hit('data-fa-copy');
  if (copy && personFor(copy)) {
    try {
      await navigator.clipboard.writeText(inviteMessage(personFor(copy)));
      showToast(t('fa.copied', 'Copied: paste it into a message to them.'), 'success');
    } catch {
      showToast(t('fa.copy_failed', 'Copying didn\'t work here; open the QR code instead.'), 'error');
    }
  }
  const qr = hit('data-fa-qr');
  const box = qr ? /** @type {HTMLElement | null} */ (document.querySelector(`[data-fa-qrbox="${CSS.escape(qr)}"]`)) : null;
  const p = qr ? personFor(qr) : null;
  if (box && p) {
    box.hidden = !box.hidden;
    if (!box.hidden && !box.innerHTML) {
      const { qrSvg } = await import('../remote-access.js');
      box.innerHTML = await qrSvg(p.page_url || p.invite_url); // SVG drawn by the qrcode library from our own text
    }
  }
}

function cardShell() {
  let card = $('fa-card');
  if (card) return card;
  const grid = $('network-services-grid');
  if (!grid) return null;
  card = document.createElement('div');
  card.className = 'nsv-col-box';
  card.id = 'fa-card';
  card.innerHTML = `<div class="nsv-row-4"><span class="nsv-fs18" aria-hidden="true">👪</span>
    <div class="nsv-fs13-bold-strong">${esc(t('fa.title', 'Family from anywhere'))}</div></div>
    <div id="fa-body" aria-live="polite">…</div>`;
  grid.appendChild(card);
  return card;
}

/** Loads the card and wires it once. */
export async function loadFamilyAccessCard() {
  const card = cardShell();
  if (!card) return;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    card.addEventListener('click', onClick);
    card.addEventListener('submit', (e) => {
      e.preventDefault();
      const key = String(new FormData(/** @type {HTMLFormElement} */ (e.target)).get('key') || '').trim();
      if (key) act(() => api.put('/api/network/family-access/key', { key }));
    });
  }
  try {
    const [st, list] = await Promise.all([api.get('/api/network/family-access'), api.get('/api/users')]);
    render(st, list.users || []);
  } catch (err) {
    const body = $('fa-body');
    if (body) body.textContent = /** @type {Error} */ (err).message || '';
  }
}
