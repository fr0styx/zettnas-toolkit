// Changing your own password (SET-10).
// The form in Settings acted on the built-in administrator's account, whoever was signed in: a
// second administrator who entered their own current password changed the built-in account's
// password and signed everyone out, and a family member or a kid was refused outright.
// It now acts on the signed-in person, through the per-account route, for every role.

import { api } from '../api.js';

/**
 * @param {string} currentPassword
 * @param {string} newPassword
 * @returns {Promise<any>} the server's answer
 */
export async function changeOwnPassword(currentPassword, newPassword) {
  const me = await api.get('/api/auth/me');
  if (!me || !me.id) throw new Error('Not signed in.');
  return api.post(`/api/users/${encodeURIComponent(me.id)}/password`, {
    current_password: currentPassword,
    new_password: newPassword,
  });
}
