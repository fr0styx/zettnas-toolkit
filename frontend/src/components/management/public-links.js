/**
 * Share links from anywhere (NFEAT-2): the card in Network → File Sharing Services that publishes
 * only the share links through Tailscale Funnel.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';
import { funnelStepsHtml, recheckWhileOpen } from './funnel-steps.js';
import '../../styles/80-public-apps.css'; // the steps' styles

const $ = (id) => document.getElementById(id);

/** The status line under the title. */
export function publicLinksStatus(st) {
  if (st.error) return st.error;
  if (!st.tailscale) return t('pl.no_tailscale', 'Needs Tailscale: connect it in Network → WireGuard & Tailscale first.');
  if (st.pending) return t('funnel.waiting_links', 'Share links go on the internet as soon as both are done.');
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
  let steps = $('pl-funnel-steps');
  if (!steps) {
    steps = document.createElement('div');
    steps.id = 'pl-funnel-steps';
    $('pl-status').insertAdjacentElement('afterend', steps);
  }
  steps.innerHTML = funnelStepsHtml(st.funnel);
  renderPortAlert(st);
  const approve = /** @type {HTMLAnchorElement} */ ($('pl-approve'));
  approve.hidden = !st.approval_url;
  approve.href = st.approval_url || '#';
}

/** Red, with a way out: the port is on the internet with more than the share links (SET-02). */
function renderPortAlert(st) {
  let alert = $('pl-port-alert');
  const others = st.port_public ? st.also_public || [] : [];
  const own = st.own_page_public || [];
  if (!others.length && !own.length) {
    if (alert) alert.hidden = true;
    return;
  }
  if (!alert) {
    alert = document.createElement('div');
    alert.id = 'pl-port-alert';
    alert.className = 'zn-alert zn-alert--danger';
    alert.setAttribute('role', 'alert');
    $('pl-status').insertAdjacentElement('afterend', alert);
  }
  alert.hidden = false;
  alert.textContent = '';
  const text = document.createElement('span');
  text.textContent = own.length
    ? `⚠ ${t('pl.own_public', 'Problem: Kiboto’s own sign-in page is on the internet, on port {port}. An older switch did this.', { port: own[0] })}`
    : `⚠ ${t('pl.also_public', 'Problem: this port is on the internet and also serves {what}. Anyone on the internet can reach that.', { what: others.join(', ') })}`;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn-pill-toggle is-danger is-small';
  btn.textContent = t('pl.take_off', 'Take off the internet');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      renderPublicLinks(await api.post('/api/network/public-links/close-port', own.length ? { port: own[0] } : {}));
    } catch (err) {
      showToast(/** @type {Error} */ (err).message, 'error');
      btn.disabled = false;
    }
  });
  alert.append(text, btn);
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
  await refreshPublicLinks();
}

/** Reads the card again, and again every few seconds while the owner's steps are open. */
export async function refreshPublicLinks(started = Date.now()) {
  try {
    const st = await api.get('/api/network/public-links');
    renderPublicLinks(st);
    if ($('pl-card')) recheckWhileOpen(st.funnel, refreshPublicLinks, undefined, started);
  } catch (err) {
    $('pl-status').textContent = /** @type {Error} */ (err).message || '';
  }
}
