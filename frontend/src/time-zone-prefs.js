/**
 * Time zones: each person's clock is their own ("auto" = their browser's zone, or one they
 * pick), kept on their account so it follows them to every device. A server that has no time
 * zone takes the first administrator's browser zone, so night work runs at their night.
 */
import { api } from './api.js';

let _checkedServer = false;

/** The zone this browser is in. */
export function browserZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** "auto" (or nothing) means the browser's zone. */
export function resolveZone(tz) {
  return !tz || tz === 'auto' ? browserZone() : tz;
}

/** Keeps the person's clock on their account. Never throws: the clock still works locally. */
export function savePersonZone(tz, format) {
  return api
    .put('/api/auth/me/preferences', { timezone: tz || 'auto', clock_format: format === '12' ? '12' : '24' })
    .catch(() => null);
}

/** Once per page: an administrator signed in to a server with no time zone gives it theirs. */
export async function detectServerZone(user) {
  if (_checkedServer || !user) return null;
  const scopes = user.scopes || [];
  if (!(scopes.includes('*') || scopes.includes('system:config'))) return null;
  _checkedServer = true;
  try {
    const id = await api.get('/api/system/identity');
    if (!id || id.timezone) return null;
    return await api.post('/api/system/identity/detected-timezone', { timezone: browserZone() });
  } catch {
    return null; // Settings -> Time and language still sets it by hand
  }
}

export function _resetForTests() {
  _checkedServer = false;
}
