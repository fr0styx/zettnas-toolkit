// "Help improve ZettNAS": the opt-in anonymous weekly report (docs/HEALTH_SIGNAL.md).
// Off by default; the card shows exactly what would be sent before you turn it on.
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { formatDateTime } from '../../format.js';
import { uiCard } from '../../ui/primitives.js';

const CARD_ID = 'health-signal-card';

function lastSentText(ts) {
  if (!ts) return t('health.never', 'Not sent yet.');
  return t('health.last_sent', 'Last sent: {when}').replace('{when}', formatDateTime(ts * 1000));
}

export function renderHealthSignal(card, status) {
  const available = !!status.available;
  const body =
    `<p class="zn-muted">${escapeHtml(t('health.desc', 'Once a week, send the app version, platform, processor type, a range for the number of drives and which features are in use. No names, addresses, files or serial numbers. Turning it off forgets the random id.'))}</p>` +
    `<label class="zn-toggle"><input type="checkbox" id="health-signal-switch" role="switch"${status.enabled ? ' checked' : ''}${available ? '' : ' disabled'}>` +
    `<span>${escapeHtml(t('health.switch', 'Send an anonymous weekly report'))}</span></label>` +
    (available ? '' : `<p class="zn-muted">${escapeHtml(t('health.unavailable', 'Not available in this version yet.'))}</p>`) +
    `<details class="hs-details"><summary>${escapeHtml(t('health.preview', 'See exactly what is sent'))}</summary>` +
    `<pre class="hs-preview">${escapeHtml(JSON.stringify(status.preview, null, 2))}</pre></details>` +
    `<p class="zn-muted" id="health-signal-last">${escapeHtml(status.enabled ? lastSentText(status.last_sent) : '')}</p>`;
  card.innerHTML = uiCard({ title: t('health.title', 'Help improve ZettNAS'), body, variant: 'boxed' });
  const sw = card.querySelector('#health-signal-switch');
  sw?.addEventListener('change', async () => {
    sw.disabled = true;
    try {
      const next = await api.put('/api/system/health-signal', { enabled: sw.checked });
      renderHealthSignal(card, next);
    } catch {
      sw.checked = !sw.checked;
      sw.disabled = false;
    }
  });
}

/** Adds the card under Software Updates in Mission Control. */
export async function installHealthSignal(root = document) {
  const updates = root.getElementById('update-status-box')?.closest('.drawer-card');
  if (!updates || root.getElementById(CARD_ID)) return;
  const card = document.createElement('div');
  card.id = CARD_ID;
  updates.insertAdjacentElement('afterend', card);
  try {
    renderHealthSignal(card, await api.get('/api/system/health-signal'));
  } catch {
    card.remove();
  }
}
