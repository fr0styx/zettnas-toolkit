/**
 * Passkeys in the browser (RES-3): turn the server's options into what navigator.credentials needs,
 * turn the answer back into JSON, and sign in with one. Browsers offer passkeys only on a secure page
 * with a name (https://<name>, or localhost), never on http://<an IP address>.
 */

/** Whether this page can use passkeys at all. */
export function passkeysAvailable(win = window) {
  const host = String(win?.location?.hostname || '');
  const isIp = /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.includes(':') || host.startsWith('[');
  return Boolean(win && win.PublicKeyCredential && win.isSecureContext && host && !isIp);
}

/** base64url text → ArrayBuffer */
export function fromB64(text) {
  const s = String(text || '').replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(s + '==='.slice((s.length + 3) % 4));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

/** ArrayBuffer (or a view) → base64url text */
export function toB64(buf) {
  const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

const withIds = (list) => (list || []).map((c) => ({ ...c, id: fromB64(c.id) }));

/** The server's creation options ({publicKey: …}, base64url) as navigator.credentials.create wants them. */
export function creationOptions(publicKey) {
  return {
    ...publicKey,
    challenge: fromB64(publicKey.challenge),
    user: { ...publicKey.user, id: fromB64(publicKey.user.id) },
    excludeCredentials: withIds(publicKey.excludeCredentials),
  };
}

/** The server's request options as navigator.credentials.get wants them. */
export function requestOptions(publicKey) {
  const out = { ...publicKey, challenge: fromB64(publicKey.challenge) };
  if (publicKey.allowCredentials) out.allowCredentials = withIds(publicKey.allowCredentials);
  return out;
}

/** A PublicKeyCredential as the JSON the server reads (the browser's own toJSON when it has one). */
export function credentialJSON(cred) {
  if (typeof cred.toJSON === 'function') return cred.toJSON();
  const r = cred.response;
  const response = { clientDataJSON: toB64(r.clientDataJSON) };
  if (r.attestationObject) response.attestationObject = toB64(r.attestationObject);
  if (r.authenticatorData) response.authenticatorData = toB64(r.authenticatorData);
  if (r.signature) response.signature = toB64(r.signature);
  if (r.userHandle) response.userHandle = toB64(r.userHandle);
  return {
    id: cred.id,
    rawId: toB64(cred.rawId),
    type: cred.type,
    response,
    clientExtensionResults: typeof cred.getClientExtensionResults === 'function' ? cred.getClientExtensionResults() : {},
  };
}

async function postJSON(fetchImpl, url, body) {
  const res = await fetchImpl(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.detail || data.message || `HTTP ${res.status}`), { status: res.status, data });
  return data;
}

/** Signs in with a passkey: alone, or with the token the password step gave (the second step).
 * Returns the sign-in answer (status ok, token, user), as /api/auth/login does. */
export async function passkeySignIn({ mfaToken = '', rememberMe = true, fetchImpl = window.fetch.bind(window), credentials = navigator.credentials } = {}) {
  const opts = await postJSON(fetchImpl, '/api/auth/passkey/login/options', { mfa_token: mfaToken, remember_me: rememberMe });
  const cred = await credentials.get({ publicKey: requestOptions(opts.options.publicKey) });
  if (!cred) throw new Error('No passkey was chosen.');
  return postJSON(fetchImpl, '/api/auth/passkey/login', { ticket: opts.ticket, credential: credentialJSON(cred) });
}

/** Makes a passkey for the signed-in person (api: the app's API client) and saves it under name. */
export async function addPasskey(api, name, credentials = navigator.credentials) {
  const opts = await api.post('/api/auth/passkeys/options', {});
  const cred = await credentials.create({ publicKey: creationOptions(opts.options.publicKey) });
  if (!cred) throw new Error('No passkey was made.');
  return api.post('/api/auth/passkeys', { ticket: opts.ticket, credential: credentialJSON(cred), name });
}
