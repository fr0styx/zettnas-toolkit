/**
 * Installable app and phone share sheet (M1).
 *
 * Registers the service worker, and after files arrive from the share sheet
 * (the worker saves them to the Inbox and comes back to /?shared=N) says how many.
 */
import { t } from './i18n.js';
import { showToast } from './toast.js';

export function sharedResultMessage(params) {
  const shared = params.get('shared');
  if (shared === null) return null;
  if (shared === 'login') {
    return { text: t('pwa.share_login', 'Sign in, then share the files again.'), type: 'warn' };
  }
  if (shared === 'error') {
    return { text: t('pwa.share_error', 'The shared files could not be read.'), type: 'error' };
  }
  const saved = parseInt(shared, 10) || 0;
  const failed = parseInt(params.get('failed') || '0', 10) || 0;
  if (failed) {
    return { text: t('pwa.share_partial', '{saved} saved to your Inbox, {failed} failed.', { saved, failed }), type: 'warn' };
  }
  return { text: t('pwa.share_saved', '{saved} saved to your Inbox folder.', { saved }), type: 'success' };
}

export function initPwa(win = window) {
  const nav = win.navigator;
  if (nav && 'serviceWorker' in nav && win.location.protocol !== 'file:') {
    nav.serviceWorker.register('/sw.js').catch((e) => console.warn('Service worker not registered:', e));
  }
  const params = new URLSearchParams(win.location.search);
  const msg = sharedResultMessage(params);
  if (msg) {
    showToast(msg.text, msg.type);
    params.delete('shared');
    params.delete('failed');
    const q = params.toString();
    win.history.replaceState(null, '', win.location.pathname + (q ? `?${q}` : '') + win.location.hash);
  }
}
