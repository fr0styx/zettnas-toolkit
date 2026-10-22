/**
 * "Notifications on this device" (M1): subscribes this browser to the NAS's alerts.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

export function pushSupport(win = window) {
  const nav = win.navigator;
  if (!nav || !('serviceWorker' in nav) || !('PushManager' in win) || !('Notification' in win)) {
    const ios = /iPhone|iPad/.test(nav ? nav.userAgent : '');
    return { ok: false, reason: ios ? 'ios-install' : 'unsupported' };
  }
  return { ok: true };
}

export function keyBytes(b64url) {
  const s = (b64url + '='.repeat((4 - (b64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

async function currentSubscription() {
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

export async function enablePush() {
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') throw new Error(t('push.denied', 'Notifications are blocked for this site in the browser settings.'));
  const { key } = await api.get('/api/push/vapid-public-key');
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  await api.post('/api/push/subscribe', sub.toJSON());
}

export async function disablePush() {
  const sub = await currentSubscription();
  if (sub) {
    await api.post('/api/push/unsubscribe', { endpoint: sub.endpoint }).catch(() => {});
    await sub.unsubscribe();
  }
}

export async function renderPushCard() {
  const host = document.getElementById('push-device-card');
  if (!host) return;
  const support = pushSupport();
  const title = Object.assign(document.createElement('div'), { className: 'zn-title', textContent: t('push.title', '📱 Notifications on this device') });
  const desc = Object.assign(document.createElement('div'), { className: 'zn-muted' });
  host.replaceChildren(title, desc);
  if (!support.ok) {
    desc.textContent = support.reason === 'ios-install'
      ? t('push.ios', 'On iPhone and iPad, add ZettNAS to the home screen first (Share → Add to Home Screen), open it from there, then turn this on.')
      : t('push.unsupported', 'This browser cannot receive notifications.');
    return;
  }
  desc.textContent = t('push.desc', 'Disk failures, ransomware alerts and other critical events appear on this phone or computer, even when ZettNAS is closed.');
  const sub = await currentSubscription().catch(() => null);
  const row = Object.assign(document.createElement('div'), { className: 'zn-row' });
  const toggle = Object.assign(document.createElement('button'), {
    type: 'button',
    className: 'btn-pill-toggle',
    textContent: sub ? t('push.turn_off', 'Turn off on this device') : t('push.turn_on', 'Turn on for this device'),
  });
  toggle.addEventListener('click', async () => {
    try {
      if (sub) await disablePush();
      else await enablePush();
      showToast(sub ? t('push.off', 'Notifications turned off on this device') : t('push.on', 'Notifications turned on'), 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    renderPushCard();
  });
  row.append(toggle);
  if (sub) {
    const test = Object.assign(document.createElement('button'), { type: 'button', className: 'btn-pill-toggle', textContent: t('push.test', 'Send a test') });
    test.addEventListener('click', async () => {
      try {
        await api.post('/api/push/test', {});
        showToast(t('push.test_sent', 'Test sent. It should appear in a few seconds.'), 'info');
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
    row.append(test);
  }
  host.append(row);
}
