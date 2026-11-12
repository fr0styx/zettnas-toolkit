/**
 * Your Kiboto boxes (RES-9, COMP-14): the card in Network → File Sharing Services that pairs boxes
 * over the tailnet, shows each paired box at a glance and sets up backups on each other's box.
 */
import { api } from '../../api.js';
import { installNeedsTailscale, needsTailscaleHtml } from './needs-tailscale.js';
import '../../styles/83-fleet.css'; // loads with the card, not on every page
import { formatBytes, formatDateTime } from '../../format.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';

const $ = (id) => document.getElementById(id);
const esc = escapeHtml;

/** One paired box's summary in a line or two, or why it can't be seen. */
export function summaryHtml(s) {
  if (!s) return '';
  if (s.error) return `<div class="pa-warn">${esc(t('fleet.unreachable', 'Not answering: {why}', { why: s.error }))}</div>`;
  const total = (s.storage || []).reduce((n, d) => n + (d.total || 0), 0);
  const free = (s.storage || []).reduce((n, d) => n + (d.free || 0), 0);
  const days = s.uptime ? Math.floor(s.uptime / 86400) : null;
  const parts = [
    t('fleet.version', 'Kiboto {v}', { v: s.version || '?' }),
    total ? t('fleet.free', '{free} free of {total}', { free: formatBytes(free), total: formatBytes(total) }) : '',
    days !== null ? t('fleet.up', '{count, plural, one {up # day} other {up # days}}', { count: days }) : '',
  ].filter(Boolean);
  const backups = (s.backups || []).map((b) => {
    const when = b.last_backup ? formatDateTime(b.last_backup * 1000) : t('fleet.never', 'never');
    const bad = b.last_result && b.last_result !== 'ok';
    return `<li class="${bad ? 'pa-warn' : ''}">${esc(b.name)} · ${esc(when)}${bad ? ` · ${esc(b.last_result)}` : ''}</li>`;
  });
  return `<div class="nsv-xs-muted">${esc(parts.join(' · '))}</div>${
    backups.length ? `<ul class="fleet-backups">${backups.join('')}</ul>` : `<div class="nsv-xs-muted-2">${esc(t('fleet.no_backups', 'No off-site backups there.'))}</div>`
  }`;
}

function peerHtml(p) {
  const id = esc(p.id);
  const open = p.address ? ` <a href="${esc(p.address)}" target="_blank" rel="noopener">${esc(t('fleet.open', 'Open'))}</a>` : '';
  const backup = p.backup_repo
    ? `<div class="nsv-xs-muted-2">${esc(t('fleet.backs_up', 'This box backs up there: Backup → Off-site.'))}</div>`
    : `<button type="button" class="btn-pill-toggle is-small" data-fleet-backup="${id}">${esc(t('fleet.backup_there', 'Back up to this box'))}</button>`;
  return `<li class="fleet-peer"><div><strong>${esc(p.name)}</strong>${open}</div>${summaryHtml(p.summary)}
    <label class="nsv-xs-muted"><input type="checkbox" data-fleet-offer="${id}"${p.offer_space ? ' checked' : ''}> ${esc(t('fleet.offer', 'Let it back up here'))}</label>
    <div class="fleet-actions">${backup}
    <button type="button" class="btn-pill-toggle is-small is-danger" data-fleet-forget="${id}">${esc(t('fleet.unpair', 'Unpair'))}</button></div>
    <div data-fleet-pick="${id}" hidden></div></li>`;
}

/** The card's body. */
export function fleetHtml(st) {
  if (!st.address) return (installNeedsTailscale(), needsTailscaleHtml(esc));
  const list = st.peers.length
    ? `<ul class="pa-list">${st.peers.map(peerHtml).join('')}</ul>`
    : `<div class="nsv-xs-muted">${esc(t('fleet.none', 'No other Kiboto box is paired with this one.'))}</div>`;
  return `${list}
    <div class="fleet-pair"><button type="button" class="btn-pill-toggle is-small" data-fleet="code">${esc(t('fleet.show_code', 'Pair this box'))}</button>
    <div data-fleet-code aria-live="polite"></div></div>
    <form class="fleet-form" data-fleet-add>
      <input name="address" placeholder="https://…" aria-label="${esc(t('fleet.address', 'The other box\'s Tailscale address'))}">
      <input name="code" placeholder="${esc(t('fleet.code_ph', 'XXXX-XXXX-XXXX-XXXX'))}" autocomplete="off" aria-label="${esc(t('fleet.code', 'Its pairing code'))}">
      <button type="submit" class="btn-pill-toggle is-primary is-small">${esc(t('fleet.pair', 'Pair with that box'))}</button></form>
    <div class="nsv-xs-muted-2">${esc(t('fleet.help', 'Boxes talk over your tailnet only. A paired box sees the other\'s name, version, free space and backups, nothing else. Backups on a box are append-only and encrypted with the sender\'s key.'))}</div>`;
}

/** The folders to back up to a paired box. */
export function pickHtml(id, shares) {
  if (!shares.length) return `<div class="nsv-xs-muted">${esc(t('fleet.no_shares', 'No shares to back up.'))}</div>`;
  return `<form data-fleet-paths="${esc(id)}">${shares
    .map((s) => `<label class="offsite-check"><input type="checkbox" name="paths" value="${esc(s.path)}"> ${esc(s.name)}</label>`)
    .join('')}<button type="submit" class="btn-pill-toggle is-primary is-small">${esc(t('fleet.start_backup', 'Set up the backup'))}</button></form>`;
}

function render(st) {
  const body = $('fleet-body');
  if (body) body.innerHTML = fleetHtml(st);
}

async function act(fn) {
  try {
    const st = await fn();
    render(st);
    return st;
  } catch (err) {
    if (/** @type {any} */ (err).status !== 428) showToast(/** @type {Error} */ (err).message, 'error');
    return null;
  }
}

async function showCode(box) {
  try {
    const c = await api.post('/api/fleet/pairing', {});
    box.innerHTML = `<div class="fleet-code"><strong>${esc(c.code)}</strong></div>
      <div class="nsv-xs-muted">${esc(t('fleet.code_how', 'On the other box, enter this address and code within 10 minutes: {address}', { address: c.address }))}</div>`;
  } catch (err) {
    showToast(/** @type {Error} */ (err).message, 'error');
  }
}

async function onClick(e) {
  const el = /** @type {Element} */ (e.target);
  const hit = (attr) => el.closest(`[${attr}]`)?.getAttribute(attr);
  if (hit('data-fleet') === 'code') {
    const box = document.querySelector('[data-fleet-code]');
    if (box) await showCode(box);
  }
  const forget = hit('data-fleet-forget');
  if (forget) act(() => api.delete(`/api/fleet/peers/${encodeURIComponent(forget)}`));
  const backup = hit('data-fleet-backup');
  const pick = backup ? /** @type {HTMLElement | null} */ (document.querySelector(`[data-fleet-pick="${CSS.escape(backup)}"]`)) : null;
  if (pick && backup) {
    const sh = await api.get('/api/storage/shares').catch(() => ({ shares: [] }));
    pick.innerHTML = pickHtml(backup, sh.shares || []);
    pick.hidden = false;
  }
}

function onChange(e) {
  const box = /** @type {HTMLInputElement} */ (e.target);
  const id = box.getAttribute('data-fleet-offer');
  if (!id) return;
  act(() => api.put(`/api/fleet/peers/${encodeURIComponent(id)}/offer`, { enabled: box.checked })).then((st) => {
    if (!st) box.checked = !box.checked;
  });
}

function onSubmit(e) {
  e.preventDefault();
  const form = /** @type {HTMLFormElement} */ (e.target);
  const f = new FormData(form);
  if (form.hasAttribute('data-fleet-add')) {
    const address = String(f.get('address') || '').trim();
    const code = String(f.get('code') || '').trim();
    if (address && code) act(() => api.post('/api/fleet/peers', { address, code }));
    return;
  }
  const id = form.getAttribute('data-fleet-paths');
  const paths = f.getAll('paths').map(String);
  if (id && paths.length) {
    act(() => api.post(`/api/fleet/peers/${encodeURIComponent(id)}/backup`, { paths })).then((st) => {
      if (st) showToast(t('fleet.backup_set', 'Set up: it runs with your other off-site backups.'), 'success');
    });
  }
}

function cardShell() {
  let card = $('fleet-card');
  if (card) return card;
  const grid = $('backup-fleet-grid') || $('network-services-grid'); // on Backup since SET-24
  if (!grid) return null;
  card = document.createElement('div');
  card.className = 'nsv-col-box';
  card.id = 'fleet-card';
  card.innerHTML = `<div class="nsv-row-4"><span class="nsv-fs18" aria-hidden="true">🗄️</span>
    <div class="nsv-fs13-bold-strong">${esc(t('fleet.title', 'Your Kiboto boxes'))}</div></div>
    <div id="fleet-body" aria-live="polite">…</div>`;
  grid.appendChild(card);
  return card;
}

/** Loads the card and wires it once. */
export async function loadFleetCard() {
  const card = cardShell();
  if (!card) return;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    card.addEventListener('click', onClick);
    card.addEventListener('change', onChange);
    card.addEventListener('submit', onSubmit);
  }
  try {
    render(await api.get('/api/fleet'));
  } catch (err) {
    const body = $('fleet-body');
    if (body) body.textContent = /** @type {Error} */ (err).message || '';
  }
}
