/**
 * "Use from anywhere" (COMP-01): join Tailscale, or a Headscale server of your own, scan the
 * sign-in link with the phone, turn on HTTPS addresses for ZettNAS and Immich, and scan the
 * address to open ZettNAS on the phone. No port is opened on the router.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

const CARD_ID = 'remote-access-card';
const POLL_MS = 3000;
const POLL_LIMIT = 100; // five minutes to sign in

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (v === true) n.setAttribute(k, '');
    else if (v !== false && v !== null && v !== undefined) n.setAttribute(k, String(v));
  }
  children.flat().forEach((c) => c !== null && c !== undefined && c !== false && n.append(c));
  return n;
}

const button = (label, action, primary = false) =>
  el('button', { type: 'button', class: `btn-pill-toggle is-small${primary ? ' is-primary' : ''}`, 'data-remote': action, text: label });

export async function qrSvg(text) {
  try {
    const { default: QRCode } = await import('qrcode');
    return await QRCode.toString(text, { type: 'svg', margin: 1, width: 148, color: { dark: '#000000', light: '#ffffff' } });
  } catch {
    return '';
  }
}

async function qrBox(text, label) {
  const box = el('div', { class: 'remote-qr', role: 'img', 'aria-label': label });
  box.innerHTML = await qrSvg(text); // SVG drawn by the qrcode library from our own text
  return box;
}

/** The port this page was opened on: Tailscale forwards HTTPS to it. */
export function appPort(loc = window.location) {
  return Number(loc.port) || (loc.protocol === 'https:' ? 443 : 80);
}

function connectForm() {
  const own = el('input', { type: 'radio', name: 'remote-kind', value: 'headscale' });
  const server = el('input', { name: 'login_server', type: 'url', placeholder: 'https://headscale.example.com', autocomplete: 'off' });
  const key = el('input', { name: 'auth_key', type: 'password', autocomplete: 'off' });
  const ownFields = el(
    'div',
    { class: 'remote-own', hidden: true },
    el('label', {}, t('remote.server', 'Headscale address'), server),
    el('label', {}, t('remote.key', 'Pre-auth key (optional)'), key),
  );
  const form = el(
    'form',
    { class: 'remote-form', 'data-remote-form': '' },
    el('p', { class: 'zn-muted', text: t('remote.intro', 'Open ZettNAS and your photos on your phone away from home, through a private network between your devices. Nothing is opened on your router.') }),
    el(
      'fieldset',
      {},
      el('legend', { text: t('remote.how', 'How to connect') }),
      el('label', { class: 'remote-choice' }, el('input', { type: 'radio', name: 'remote-kind', value: 'tailscale', checked: true }), t('remote.tailscale', 'Tailscale (free account with Google, Apple, Microsoft or GitHub)')),
      el('label', { class: 'remote-choice' }, own, t('remote.headscale', 'My own Headscale server (no account anywhere)')),
    ),
    ownFields,
    el('button', { type: 'submit', class: 'btn-pill-toggle is-primary', text: t('remote.connect', 'Connect') }),
  );
  form.addEventListener('change', () => {
    ownFields.hidden = !own.checked;
  });
  return form;
}

/** What the person sends: no login server for Tailscale, the Headscale address otherwise. */
export function connectBody(form) {
  const f = new FormData(form);
  if (f.get('remote-kind') !== 'headscale') return { login_server: '', auth_key: '' };
  return { login_server: String(f.get('login_server') || '').trim(), auth_key: String(f.get('auth_key') || '').trim() };
}

async function signInView(s) {
  return el(
    'div',
    { class: 'zn-row remote-step' },
    await qrBox(s.auth_url, t('remote.signin_qr', 'Sign-in link as a QR code')),
    el(
      'div',
      { class: 'remote-text' },
      el('p', { text: t('remote.signin', 'Sign in to add this NAS to your network: scan the code with your phone, or open the link here. This card updates when it is done.') }),
      el('a', { href: s.auth_url, target: '_blank', rel: 'noopener noreferrer', class: 'btn-pill-toggle is-primary is-small', text: t('remote.open_signin', 'Open the sign-in page') }),
    ),
  );
}

function httpsHint(s) {
  if (s.https) return null;
  if (s.login_server) {
    return el('p', { class: 'zn-muted', text: t('remote.no_https_headscale', 'Headscale gives no HTTPS certificates, so the addresses start with http://. The connection is still encrypted end to end by the private network.') });
  }
  return el('p', { class: 'zn-muted', text: t('remote.no_https', 'For https:// addresses, turn on MagicDNS and HTTPS certificates on the DNS page of the Tailscale admin console, then press "Turn on HTTPS".') });
}

async function connectedView(s) {
  const zettnas = (s.addresses || {}).zettnas || '';
  const immich = (s.addresses || {}).immich || '';
  const list = el(
    'ul',
    { class: 'zn-list remote-addresses' },
    zettnas ? el('li', {}, `${t('remote.addr_zettnas', 'ZettNAS')}: `, el('code', { text: zettnas })) : null,
    immich ? el('li', {}, `${t('remote.addr_immich', 'Immich (photo backup)')}: `, el('code', { text: immich })) : null,
  );
  const actions = el(
    'div',
    { class: 'zn-row remote-actions' },
    zettnas.startsWith('https://') ? null : button(t('remote.publish', 'Turn on HTTPS'), 'publish', true),
    button(t('remote.disconnect', 'Disconnect'), 'disconnect'),
  );
  return el(
    'div',
    { class: 'remote-step' },
    el('p', { text: t('remote.connected', 'Connected as {name}. On a phone with the Tailscale app signed in to the same network, scan the code to open ZettNAS.', { name: s.name || (s.ips || [])[0] || '' }) }),
    el('div', { class: 'zn-row' }, zettnas ? await qrBox(zettnas, t('remote.addr_qr', 'ZettNAS address as a QR code')) : null, list),
    httpsHint(s),
    actions,
  );
}

/** The card's body for a status from GET /api/network/remote-access. */
export async function remoteBody(s) {
  if (s.state === 'Running') return connectedView(s);
  if (s.state === 'NeedsLogin' && s.auth_url) return signInView(s);
  return connectForm();
}

export async function renderRemoteAccess(card, s = null, polls = 0) {
  let status = s;
  if (!status) {
    try {
      status = await api.get('/api/network/remote-access');
    } catch {
      card.hidden = true;
      return;
    }
  }
  card.hidden = false;
  card.replaceChildren(el('div', { class: 'zn-card zn-card--boxed' }, el('div', { class: 'zn-title', text: t('remote.title', 'Use from anywhere') }), await remoteBody(status)));
  card.querySelector('[data-remote-form]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const next = await api.post('/api/network/remote-access/connect', connectBody(/** @type {HTMLFormElement} */ (e.currentTarget)));
      await renderRemoteAccess(card, next);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  card.querySelectorAll('[data-remote]').forEach((b) =>
    b.addEventListener('click', async () => {
      const action = /** @type {HTMLElement} */ (b).dataset.remote;
      try {
        const body = action === 'publish' ? { app_port: appPort() } : {};
        const next = await api.post(`/api/network/remote-access/${action}`, body);
        if (next.approval_url) {
          window.open(next.approval_url, '_blank', 'noopener');
          showToast(t('remote.approve', 'Allow HTTPS for this NAS on the Tailscale page that opened, then press "Turn on HTTPS" again.'), 'info');
        }
        await renderRemoteAccess(card, next);
      } catch (err) {
        showToast(err.message || String(err), 'error');
      }
    }),
  );
  if (status.state === 'NeedsLogin' && polls < POLL_LIMIT) {
    setTimeout(async () => {
      if (!card.isConnected) return;
      try {
        const next = await api.get('/api/network/remote-access');
        if (next.state !== 'NeedsLogin' || next.auth_url !== status.auth_url) await renderRemoteAccess(card, next);
        else await renderRemoteAccess(card, status, polls + 1);
      } catch {
        // keep the sign-in view; the next open of the pane asks again
      }
    }, POLL_MS);
  }
}

/** Puts the card above the Tailscale details in Network → Tailscale & WireGuard. */
export async function installRemoteAccess(mount) {
  if (!mount) return;
  let card = document.getElementById(CARD_ID);
  if (!card) {
    card = el('div', { id: CARD_ID });
    mount.append(card);
  }
  await renderRemoteAccess(card);
}
