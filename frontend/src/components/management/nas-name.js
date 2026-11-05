/**
 * Find this NAS by name (NFEAT-8): the card in Network → File Sharing Services that turns
 * <name>.local on or off and changes the name; the old name keeps answering.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';

const $ = (id) => document.getElementById(id);

/** The status line under the title. */
export function nasNameStatus(st) {
  if (st.error) return st.error;
  if (!st.enabled) return t('nas_name.off', 'Off: computers find the NAS only by its address.');
  if (!st.running) return t('nas_name.starting', 'Starting…');
  return t('nas_name.on', 'On: {address} on this network.', { address: st.address });
}

export function renderNasName(st) {
  const card = $('nas-name-card');
  if (!card || !st) return;
  const toggle = /** @type {HTMLButtonElement} */ ($('nas-name-toggle'));
  toggle.setAttribute('aria-pressed', String(Boolean(st.enabled)));
  toggle.classList.toggle('active', Boolean(st.enabled));
  toggle.textContent = st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off');
  $('nas-name-status').textContent = nasNameStatus(st);
  const input = /** @type {HTMLInputElement} */ ($('nas-name-input'));
  if (document.activeElement !== input) input.value = st.name || '';
  const link = /** @type {HTMLAnchorElement} */ ($('nas-name-link'));
  link.hidden = !(st.enabled && st.running);
  link.href = st.url || '#';
  link.textContent = st.url || '';
  const old = $('nas-name-old');
  old.hidden = !(st.also_answers && st.also_answers.length);
  old.textContent = old.hidden
    ? ''
    : t('nas_name.old', 'Also still answers to {names}, so older bookmarks keep working.', {
      names: st.also_answers.map((n) => `${n}.local`).join(', '),
    });
}

async function put(body) {
  try {
    renderNasName(await api.put('/api/network/nas-name', body));
  } catch (err) {
    showToast(/** @type {Error} */ (err).message || t('nas_name.failed', 'The name could not be changed.'), 'error');
  }
}

/** Loads the card and wires its controls once. */
export async function loadNasNameCard() {
  const card = $('nas-name-card');
  if (!card) return;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    $('nas-name-toggle').addEventListener('click', () => {
      put({ enabled: $('nas-name-toggle').getAttribute('aria-pressed') !== 'true' });
    });
    $('nas-name-save').addEventListener('click', () => {
      put({ name: /** @type {HTMLInputElement} */ ($('nas-name-input')).value.trim() });
    });
    $('nas-name-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') $('nas-name-save').click();
    });
  }
  try {
    renderNasName(await api.get('/api/network/nas-name'));
  } catch (err) {
    $('nas-name-status').textContent = /** @type {Error} */ (err).message || '';
  }
}
