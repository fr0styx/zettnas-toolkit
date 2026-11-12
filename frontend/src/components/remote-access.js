/**
 * "Use from anywhere" (COMP-01): join Tailscale, or a Headscale server of your own, scan the
 * sign-in link with the phone, turn on HTTPS addresses for Kiboto, Immich and the other apps, and scan the
 * address to open Kiboto on the phone. No port is opened on the router.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { pollWhileOpen } from '../poll-while-open.js';
import { stateBlock } from './state-block.js';
import { installExposure, renderExposure, LINE_ID } from './exposure-line.js';

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

/** What "Turn on HTTPS" sends. The port only from a plain page at home: on the HTTPS address the
 *  browser's port is Tailscale's 443, not the port Kiboto listens on, and the server keeps the one
 *  it knows (SET-02). */
export function publishBody(loc = window.location) {
  return loc.protocol === 'http:' ? { app_port: appPort(loc) } : {};
}

function connectForm() {
  const own = el('input', { type: 'radio', name: 'remote-kind', value: 'headscale' });
  const nb = el('input', { type: 'radio', name: 'remote-kind', value: 'netbird' });
  const nbFields = el(
    'div',
    { class: 'remote-own', hidden: true },
    el('label', {}, t('remote.netbird_key', 'Setup key'), el('input', { name: 'setup_key', type: 'password', autocomplete: 'off' })),
    el('label', {}, t('remote.netbird_server', 'Your own NetBird server (optional)'), el('input', { name: 'management_url', type: 'url', placeholder: 'https://netbird.example.com', autocomplete: 'off' })),
  );
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
    el('p', { class: 'kb-muted', text: t('remote.intro', 'Open Kiboto and your photos on your phone away from home, through a private network between your devices. Nothing is opened on your router.') }),
    el(
      'fieldset',
      {},
      el('legend', { text: t('remote.how', 'How to connect') }),
      el('label', { class: 'remote-choice' }, el('input', { type: 'radio', name: 'remote-kind', value: 'tailscale', checked: true }), t('remote.tailscale', 'Tailscale (free account with Google, Apple, Microsoft or GitHub)')),
      el('label', { class: 'remote-choice' }, own, t('remote.headscale', 'My own Headscale server (no account anywhere)')),
      el('label', { class: 'remote-choice' }, nb, t('remote.netbird', 'NetBird (free account, or your own NetBird server)')),
    ),
    ownFields,
    nbFields,
    el('button', { type: 'submit', class: 'btn-pill-toggle is-primary', text: t('remote.connect', 'Connect') }),
  );
  form.addEventListener('change', () => {
    ownFields.hidden = !own.checked;
    nbFields.hidden = !nb.checked;
  });
  return form;
}

/** What NetBird's connect sends, or null when another way was chosen (SET-16N). */
export function netbirdBody(form) {
  const f = new FormData(form);
  if (f.get('remote-kind') !== 'netbird') return null;
  return { setup_key: String(f.get('setup_key') || '').trim(), management_url: String(f.get('management_url') || '').trim() };
}

/** Connected through NetBird: the address as a QR code, its devices, and Disconnect. */
export async function netbirdView(nb, loc = window.location) {
  const url = `http://${nb.ip}:${appPort(loc)}`;
  return el(
    'div',
    { class: 'remote-step' },
    el('p', { text: t('remote.netbird_connected', 'Connected to NetBird as {name}. On a phone with the NetBird app signed in to the same network, scan the code to open Kiboto.', { name: nb.name || nb.ip }) }),
    el('div', { class: 'kb-row' }, await qrBox(url, t('remote.addr_qr', 'Kiboto address as a QR code')), el('ul', { class: 'kb-list remote-addresses' }, el('li', {}, `${t('remote.addr_kiboto', 'Kiboto')}: `, link(url, url)), el('li', { text: t('remote.netbird_devices', '{n, plural, one {# device} other {# devices}} connected', { n: nb.peers_connected || 0 }) }))),
    el('p', { class: 'kb-muted', text: t('remote.netbird_plain', 'NetBird gives no HTTPS addresses, so the address starts with http://. The connection is still encrypted end to end.') }),
    el('div', { class: 'kb-row remote-actions' }, el('button', { type: 'button', class: 'btn-pill-toggle is-small', 'data-netbird': 'disconnect', text: t('remote.disconnect', 'Disconnect') })),
  );
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
    { class: 'kb-row remote-step' },
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
    return el('p', { class: 'kb-muted', text: t('remote.no_https_headscale', 'Headscale gives no HTTPS certificates, so the addresses start with http://. The connection is still encrypted end to end by the private network.') });
  }
  return el('p', { class: 'kb-muted', text: t('remote.no_https', 'For https:// addresses, turn on MagicDNS and HTTPS certificates on the DNS page of the Tailscale admin console, then press "Turn on HTTPS".') });
}

const APPS_OPEN_KEY = 'kiboto_remote_apps_open';

/** Whether this browser last left the app list open (a per-viewer convenience). */
function appsOpen() {
  try {
    return localStorage.getItem(APPS_OPEN_KEY) === '1';
  } catch {
    return false;
  }
}

/** The port of an address, to tell apps apart at a glance (":8096"), or '' for the default port. */
export function portLabel(url) {
  try {
    const p = new URL(url).port;
    return p ? `:${p}` : '';
  } catch {
    return '';
  }
}

/** Kiboto's address (under its name before the rebrand on older servers). */
const kibotoAddress = (addresses) => addresses.kiboto || addresses.zettnas || '';

const link = (url, text) => el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', title: url, text });

/** Kiboto and Immich as links; every other app folded away in a grid, since there can be many. */
export function addressesView(addresses = {}, open = appsOpen()) {
  const kiboto = kibotoAddress(addresses);
  const immich = addresses.immich || '';
  const apps = [...(addresses.apps || [])].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const main = el(
    'ul',
    { class: 'kb-list remote-addresses' },
    kiboto ? el('li', {}, `${t('remote.addr_kiboto', 'Kiboto')}: `, link(kiboto, kiboto)) : null,
    immich ? el('li', {}, `${t('remote.addr_immich', 'Immich (photo backup)')}: `, link(immich, immich)) : null,
  );
  if (!apps.length) return el('div', { class: 'remote-addr-col' }, main);
  const fold = el(
    'details',
    { class: 'remote-apps', open },
    el('summary', { text: t('remote.apps_n', '{n, plural, one {# app} other {# apps}} on your tailnet', { n: apps.length }) }),
    el(
      'ul',
      { class: 'remote-app-grid' },
      ...apps.map((a) => el('li', {}, link(a.url, a.name), el('span', { class: 'remote-app-port', text: portLabel(a.url) }))),
    ),
  );
  fold.addEventListener('toggle', () => {
    try {
      localStorage.setItem(APPS_OPEN_KEY, fold.open ? '1' : '0');
    } catch {
      /* private window: it just opens closed next time */
    }
  });
  return el('div', { class: 'remote-addr-col' }, main, fold);
}

async function connectedView(s) {
  const kiboto = kibotoAddress(s.addresses || {});
  const apps = (s.addresses || {}).apps || [];
  const list = addressesView(s.addresses || {});
  // an app installed after HTTPS was turned on still has a plain address (NFEAT-5)
  const newApps = s.https && apps.some((a) => !a.url.startsWith('https://'));
  const actions = el(
    'div',
    { class: 'kb-row remote-actions' },
    !kiboto.startsWith('https://') ? button(t('remote.publish', 'Turn on HTTPS'), 'publish', true)
      : newApps ? button(t('remote.publish_apps', 'Turn on HTTPS for new apps'), 'publish', true) : null,
    button(t('remote.disconnect', 'Disconnect'), 'disconnect'),
  );
  return el(
    'div',
    { class: 'remote-step' },
    el('p', { text: t('remote.connected', 'Connected as {name}. On a phone with the Tailscale app signed in to the same network, scan the code to open Kiboto.', { name: s.name || (s.ips || [])[0] || '' }) }),
    el('div', { class: 'kb-row' }, kiboto ? await qrBox(kiboto, t('remote.addr_qr', 'Kiboto address as a QR code')) : null, list),
    httpsHint(s),
    actions,
  );
}

/** The card's body for a status from GET /api/network/remote-access. */
export async function remoteBody(s, nb = null) {
  if (s.state === 'Running') return connectedView(s);
  if (nb && nb.state === 'Connected' && nb.ip) return netbirdView(nb);
  if (s.state === 'NeedsLogin' && s.auth_url) return signInView(s);
  return connectForm();
}

export async function renderRemoteAccess(card, s = null) {
  let status = s;
  if (!status) {
    try {
      status = await api.get('/api/network/remote-access');
    } catch (err) {
      showLoadFailed(card, err);
      return;
    }
  }
  card.hidden = false;
  const nb = status.state === 'Running' ? null : await api.get('/api/network/remote-access/netbird').catch(() => null);
  card.replaceChildren(el('div', { class: 'kb-card kb-card--boxed' }, el('div', { class: 'kb-title', text: t('remote.title', 'Use from anywhere') }), await remoteBody(status, nb)));
  card.querySelector('[data-remote-form]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = /** @type {HTMLFormElement} */ (e.currentTarget);
    try {
      const viaNetbird = netbirdBody(form);
      if (viaNetbird) {
        await api.post('/api/network/remote-access/netbird/connect', viaNetbird);
        await renderRemoteAccess(card);
        return;
      }
      const next = await api.post('/api/network/remote-access/connect', connectBody(form));
      await renderRemoteAccess(card, next);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  card.querySelector('[data-netbird]')?.addEventListener('click', async () => {
    try {
      await api.post('/api/network/remote-access/netbird/disconnect', {});
      await renderRemoteAccess(card);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  card.querySelectorAll('[data-remote]').forEach((b) =>
    b.addEventListener('click', async () => {
      const action = /** @type {HTMLElement} */ (b).dataset.remote;
      try {
        const body = action === 'publish' ? publishBody() : {};
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
  refreshExposure();
  if (status.state === 'NeedsLogin') pollWhileOpen(card, () => signInDone(card, status), { ms: POLL_MS, limit: POLL_LIMIT });
}

/** The card when its state can't be read: says so, with Try again (network report F1: it vanished). */
export function showLoadFailed(card, err) {
  card.hidden = false;
  const text = t('remote.load_failed', "Kiboto couldn't read how this NAS is reached from away.");
  card.replaceChildren(stateBlock('failed', { text, detail: String(err?.message || ''), retry: () => renderRemoteAccess(card) }));
}

/** The line above the card says again what reaches the NAS, after the card changed. */
export function refreshExposure() {
  const line = document.getElementById(LINE_ID);
  if (line) renderExposure(line);
}

/** One sign-in check: true (and the card drawn again) once Tailscale moved on. */
export async function signInDone(card, status) {
  const next = await api.get('/api/network/remote-access');
  if (next.state === 'NeedsLogin' && next.auth_url === status.auth_url) return false;
  await renderRemoteAccess(card, next);
  return true;
}

/** Puts the card above the Tailscale details in Network → Tailscale & WireGuard. */
export async function installRemoteAccess(mount) {
  if (!mount) return;
  let card = document.getElementById(CARD_ID);
  if (!card) {
    card = el('div', { id: CARD_ID });
    mount.append(card);
  }
  installExposure(mount);
  await renderRemoteAccess(card);
}
