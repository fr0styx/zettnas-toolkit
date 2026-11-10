/**
 * The hardware helper (SEC-24 step 2): a card in Hardware → Fans that moves the fan and button
 * hardware access out of Kiboto into a small helper container, which alone opens /dev/mem.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';

const $ = (id) => document.getElementById(id);

/** The status line under the title. */
export function hwHelperStatus(st) {
  if (st.error) return st.error;
  if (!st.applies) return t('hwh.not_here', 'This box has no fan or button registers for the helper to serve.');
  if (st.kept_until_update) return t('hwh.kept', 'Off: the helper keeps the fans running until the next update gives Kiboto its own access back.');
  if (!st.enabled) return t('hwh.off', 'Off: Kiboto reaches the fan and button hardware itself.');
  if (!st.running) return t('hwh.starting', 'Starting…');
  if (!st.answering) return t('hwh.not_answering', 'The helper doesn\'t answer: Kiboto uses the hardware itself for now.');
  return st.app_without_raw_access
    ? t('hwh.on_done', 'On: only the helper reaches the fan and button hardware; Kiboto no longer can.')
    : t('hwh.on', 'On: the fans and the button go through the helper. The next update takes the hardware access away from Kiboto itself.');
}

export function hwHelperHtml(st) {
  const on = Boolean(st.enabled);
  return `<div class="nsv-row-3">
      <div>
        <div class="nsv-fs13-bold-strong" id="hwh-title">${escapeHtml(t('hwh.title', 'Hardware helper'))}</div>
        <div class="nsv-xs-muted" id="hwh-status" aria-live="polite">${escapeHtml(hwHelperStatus(st))}</div>
      </div>
      <button type="button" class="btn-pill-toggle${on ? ' active' : ''}" id="hwh-toggle" aria-pressed="${on}" aria-labelledby="hwh-title"${st.applies || on ? '' : ' disabled'}>${escapeHtml(on ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    <div class="nsv-xs-muted-2">${escapeHtml(t('hwh.help', 'Raw access to the hardware (/dev/mem) can read and change any of the computer\'s memory. With the helper, only a tiny container with no network holds it, and it answers just four questions: read the fans, set a fan, read the button, are you there.'))}</div>`;
}

async function put(enabled) {
  try {
    render(await api.put('/api/hardware/helper', { enabled }));
  } catch (err) {
    if (/** @type {any} */ (err).status !== 428) showToast(/** @type {Error} */ (err).message, 'error');
  }
}

function render(st) {
  const card = $('hwh-card');
  if (!card || !st) return;
  card.innerHTML = hwHelperHtml(st);
}

/** Puts the card in the Fans pane once and reads how the helper stands. */
export async function loadHwHelperCard() {
  const pane = $('mgmt-pane-hardware-fans');
  if (!pane) return;
  let card = $('hwh-card');
  if (!card) {
    card = document.createElement('div');
    card.id = 'hwh-card';
    card.className = 'nsv-col-box';
    const intro = pane.querySelector('.mgmt-card-intro');
    if (intro) intro.insertAdjacentElement('afterend', card);
    else pane.prepend(card);
    card.addEventListener('click', (e) => {
      const toggle = /** @type {Element} */ (e.target).closest('#hwh-toggle');
      if (toggle) put(toggle.getAttribute('aria-pressed') !== 'true');
    });
  }
  try {
    render(await api.get('/api/hardware/helper'));
  } catch (err) {
    card.textContent = /** @type {Error} */ (err).message || '';
  }
}
