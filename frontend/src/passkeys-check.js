/** Whether this page can use passkeys (RES-3), kept apart so the sign-in page loads only this much
 * until someone actually uses a passkey (passkeys.js loads then). */

/** Whether this page can use passkeys at all. */
export function passkeysAvailable(win = window) {
  const host = String(win?.location?.hostname || '');
  const isIp = /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.includes(':') || host.startsWith('[');
  return Boolean(win && win.PublicKeyCredential && win.isSecureContext && host && !isIp);
}
