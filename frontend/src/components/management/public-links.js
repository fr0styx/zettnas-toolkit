/**
 * Share links from anywhere (NFEAT-2): the card in Network → File Sharing Services that publishes
 * only the share links through Tailscale Funnel.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';

const $ = (id) => document.getElementById(id);

/** The status line under the title. */
export function publicLinksStatus(st) {
  if (st.error) return st.error;
  if (!st.tailscale) return t('pl.no_tailscale', 'Needs Tailscale: connect it in Network → WireGuard & Tailscale first.');
  if (st.approval_url) return t('pl.approve', 'Tailscale asks the tailnet owner to allow Funnel first.');
  if (!st.enabled) return t('pl.off', 'Off: share links work at home and on your tailnet.');
  if (!st.live) return t('pl.starting', 'Starting…');
  return t('pl.on', 'On: share links work from anywhere, at {address}.', { address: st.base_url });
}

export function renderPublicLinks(st) {
  if (!$('pl-card') || !st) return;
  const toggle = /** @type {HTMLButtonElement} */ ($('pl-toggle'));
  toggle.setAttribute('aria-pressed', String(Boolean(st.enabled)));
  toggle.classList.toggle('active', Boolean(st.enabled));
  toggle.textContent = st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off');
  toggle.disabled = !st.tailscale && !st.enabled;
  $('pl-status').textContent = publicLinksStatus(st);
  const approve = /** @type {HTMLAnchorElement} */ ($('pl-approve'));
  approve.hidden = !st.approval_url;
  approve.href = st.approval_url || '#';
}

async function put(enabled) {
  try {
    renderPublicLinks(await api.put('/api/network/public-links', { enabled }));
  } catch (err) {
    if (/** @type {any} */ (err).status !== 428) showToast(/** @type {Error} */ (err).message, 'error');
  }
}

/** Loads the card and wires its controls once. */
export async function loadPublicLinksCard() {
  const card = $('pl-card');
  if (!card) return;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    $('pl-toggle').addEventListener('click', () => put($('pl-toggle').getAttribute('aria-pressed') !== 'true'));
  }
  try {
    renderPublicLinks(await api.get('/api/network/public-links'));
  } catch (err) {
    $('pl-status').textContent = /** @type {Error} */ (err).message || '';
  }
}
