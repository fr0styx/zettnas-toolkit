// "Back up my phone" (B8): the Immich app backs up a phone's photos to this server. The card
// shows Immich's address as a QR code to scan in the app, and the four steps; with sign-in passed
// through (Immich connected to ZettNAS's sign-in, M3) the app's "Sign in with ZettNAS" button
// does the rest. Without Immich it points to the app catalog.
import { api } from '../api.js';
import { t } from '../i18n.js';
import { html, raw } from '../html.js';
import { uiCard } from '../ui/primitives.js';

const CARD_ID = 'phone-backup-card';

export function phoneBackupHtml(s, qrSvg = '') {
  const url = (s && (s.url || s.detected)) || '';
  if (!url) {
    return html`<p class="zn-muted">${t('phone.no_immich', 'Immich backs up the photos and videos on your phone to this server, automatically. Install it from the app catalog first.')}</p>
      <button type="button" class="btn-pill-toggle is-primary" data-phone-open="catalog">${t('phone.open_catalog', 'Open the app catalog')}</button>`;
  }
  const signIn = s.sso
    ? t('phone.step3_sso', 'Tap "Sign in with ZettNAS" and use your ZettNAS account.')
    : t('phone.step3', 'Sign in with your Immich account.');
  return html`<div class="zn-row phone-backup">
      <div class="phone-qr" aria-hidden="true">${raw(qrSvg)}</div>
      <ol class="zn-list phone-steps">
        <li>${t('phone.step1', 'Install the Immich app on your phone (App Store or Google Play).')}</li>
        <li>${t('phone.step2', 'Open it and scan this code, or type the address:')} <code>${url}</code></li>
        <li>${signIn}</li>
        <li>${t('phone.step4', 'Tap the cloud icon and turn on backup. Photos you take from now on are copied here.')}</li>
      </ol>
    </div>
    <p class="zn-muted">${t('phone.away', 'Away from home, the phone backs up when it can reach this server, for example through Tailscale (Network).')}</p>
    ${s.phone_done
      ? html`<p class="zn-muted">✓ ${t('phone.done_note', 'You said your phone backs up here.')}</p>`
      : html`<button type="button" class="btn-pill-toggle" data-phone-done>${t('phone.done', 'Done, my phone backs up')}</button>`}`;
}

async function qrFor(url) {
  try {
    const { default: QRCode } = await import('qrcode');
    return await QRCode.toString(url, { type: 'svg', margin: 1, width: 132, color: { dark: '#000000', light: '#ffffff' } });
  } catch {
    return '';
  }
}

export async function renderPhoneBackup(card) {
  let s;
  try {
    s = await api.get('/api/immich');
  } catch {
    card.hidden = true;
    return;
  }
  const url = s.url || s.detected || '';
  const qr = url ? await qrFor(url) : '';
  card.innerHTML = uiCard({ title: t('phone.title', 'Back up my phone'), body: String(phoneBackupHtml(s, qr)), variant: 'boxed' });
  card.querySelector('[data-phone-done]')?.addEventListener('click', async () => {
    try {
      await api.put('/api/immich/phone', { done: true });
    } finally {
      renderPhoneBackup(card);
    }
  });
  card.querySelector('[data-phone-open]')?.addEventListener('click', (e) => {
    window.openManagementSection?.(e.currentTarget.dataset.phoneOpen);
  });
}

/** Adds the card after the Immich settings in AI settings → Index. */
export async function installPhoneBackup(mount) {
  if (!mount) return;
  let card = document.getElementById(CARD_ID);
  if (!card) {
    card = Object.assign(document.createElement('div'), { id: CARD_ID });
    mount.insertAdjacentElement('afterend', card);
  }
  await renderPhoneBackup(card);
}
