/**
 * Apps from anywhere (RES-6): the card in Network → File Sharing Services that puts a chosen app on
 * the internet through Tailscale Funnel, on a port of its own. Kiboto's own page never goes there.
 */
import { api } from '../../api.js';
import { installNeedsTailscale, needsTailscaleHtml } from './needs-tailscale.js';
import '../../styles/80-public-apps.css'; // loads with the card, not on every page
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';
import { funnelStepsHtml, recheckWhileOpen } from './funnel-steps.js';

const $ = (id) => document.getElementById(id);

/** One published app: its address, and whether Funnel serves it yet. */
export function publishedHtml(p) {
  const state = p.approval_url
    ? `<a href="${escapeHtml(p.approval_url)}" target="_blank" rel="noopener">${escapeHtml(t('pa.approve', 'Allow Funnel in Tailscale first'))}</a>`
    : p.live
      ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">${escapeHtml(p.url)}</a>`
      : escapeHtml(t('pa.starting', 'Starting…'));
  return `<li class="pa-item"><span><strong>${escapeHtml(p.name)}</strong> · ${state}${
    p.controls_server ? ` <span class="pa-warn">${escapeHtml(t('pa.controls_short', 'controls the server'))}</span>` : ''
  }</span>
    <button type="button" class="btn-pill-toggle is-small is-danger" data-pa-stop="${escapeHtml(String(p.funnel_port))}">${escapeHtml(t('pa.stop', 'Take off the internet'))}</button></li>`;
}

/** The card's body: what is published, and the form to publish another. */
export function publicAppsHtml(st) {
  if (!st.tailscale) {
    return (installNeedsTailscale(), needsTailscaleHtml(escapeHtml));
  }
  const list = st.published.length
    ? `<ul class="pa-list">${st.published.map(publishedHtml).join('')}</ul>`
    : `<div class="nsv-xs-muted">${escapeHtml(t('pa.none_published', 'No app is on the internet.'))}</div>`;
  let form;
  if (!st.free_ports.length) {
    form = `<div class="nsv-xs-muted-2">${escapeHtml(t('pa.full', 'Every port Funnel can use for apps is taken; take one off to publish another.'))}</div>`;
  } else if (!st.apps.length) {
    form = `<div class="nsv-xs-muted-2">${escapeHtml(t('pa.no_apps', 'No running app publishes a port to put on the internet.'))}</div>`;
  } else {
    const options = st.apps
      .flatMap((a) => a.ports.map((port) => `<option value="${escapeHtml(`${a.name}|${port}`)}" data-controls="${a.controls_server ? '1' : ''}">${escapeHtml(t('pa.app_port', '{name} (port {port})', { name: a.name, port }))}</option>`))
      .join('');
    const ports = st.free_ports.map((p) => `<option value="${p}">${p}</option>`).join('');
    form = `<form class="pa-form" data-pa-form>
      <label>${escapeHtml(t('pa.app_l', 'App'))} <select name="app">${options}</select></label>
      <label>${escapeHtml(t('pa.port_l', 'Internet port'))} <select name="port">${ports}</select></label>
      <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('pa.publish', 'Put on the internet'))}</button>
      <div class="pa-warn" data-pa-warn hidden>${escapeHtml(t('pa.controls_warn', 'This app controls the server: whoever gets past its sign-in can change or erase everything. Publish it only with a strong password and two-step sign-in in the app.'))}</div>
    </form>`;
  }
  const waiting = st.pending
    ? t('funnel.waiting_app', 'Kiboto puts {name} on the internet as soon as both are done.', { name: st.pending.name })
    : '';
  return `${funnelStepsHtml(st.funnel, waiting)}${list}${form}<div class="nsv-xs-muted-2">${escapeHtml(t('pa.help', 'Anyone with the address reaches the app\'s own sign-in page, so publish only apps that have one. Kiboto\'s own page never goes on the internet.'))}</div>`;
}

function cardShell() {
  let card = $('pa-card');
  if (card) return card;
  const grid = $('network-services-grid');
  if (!grid) return null;
  card = document.createElement('div');
  card.className = 'nsv-col-box';
  card.id = 'pa-card';
  card.innerHTML = `<div class="nsv-row-4"><span class="nsv-fs18" aria-hidden="true">🚪</span>
    <div class="nsv-fs13-bold-strong">${escapeHtml(t('pa.title', 'Apps from anywhere'))}</div></div>
    <div id="pa-body" aria-live="polite">…</div>`;
  const after = $('pl-card');
  if (after && after.parentNode === grid) after.after(card);
  else grid.appendChild(card);
  return card;
}

export function renderPublicApps(st) {
  const body = $('pa-body');
  if (!body || !st) return;
  body.innerHTML = publicAppsHtml(st);
  const form = /** @type {HTMLFormElement | null} */ (body.querySelector('[data-pa-form]'));
  const warn = /** @type {HTMLElement | null} */ (body.querySelector('[data-pa-warn]'));
  const select = /** @type {HTMLSelectElement | null} */ (form ? form.elements.namedItem('app') : null);
  const syncWarn = () => {
    if (warn && select) warn.hidden = select.selectedOptions[0]?.getAttribute('data-controls') !== '1';
  };
  select?.addEventListener('change', syncWarn);
  syncWarn();
}

async function act(fn) {
  try {
    renderPublicApps(await fn());
  } catch (err) {
    if (/** @type {any} */ (err).status !== 428) showToast(/** @type {Error} */ (err).message, 'error');
  }
}

/** Loads the card and wires its controls once. */
export async function loadPublicAppsCard() {
  const card = cardShell();
  if (!card) return;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    card.addEventListener('submit', (e) => {
      e.preventDefault();
      const f = new FormData(/** @type {HTMLFormElement} */ (e.target));
      const [name, port] = String(f.get('app') || '').split('|');
      act(() => api.post('/api/network/public-apps', { name, host_port: Number(port), funnel_port: Number(f.get('port')) }));
    });
    card.addEventListener('click', (e) => {
      const stop = /** @type {Element} */ (e.target).closest('[data-pa-stop]');
      if (stop) act(() => api.delete(`/api/network/public-apps/${encodeURIComponent(stop.getAttribute('data-pa-stop') || '')}`));
    });
  }
  await refreshPublicApps();
}

/** Reads the card again, and again every few seconds while the owner's steps are open. */
export async function refreshPublicApps(started = Date.now()) {
  try {
    const st = await api.get('/api/network/public-apps');
    renderPublicApps(st);
    if ($('pa-card')) recheckWhileOpen(st.funnel, refreshPublicApps, undefined, started, $('pa-card'));
  } catch (err) {
    const body = $('pa-body');
    if (body) body.textContent = /** @type {Error} */ (err).message || '';
  }
}
