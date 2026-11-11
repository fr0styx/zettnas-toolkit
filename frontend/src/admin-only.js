/**
 * An administrator's set-up is for administrators (SET-03, the owner's decision S9): the security
 * check, the protection and sign-in settings, the alert set-up, API tokens and single sign-on. The
 * server refuses everyone else the data; these cards, marked data-admin-only, are not drawn for
 * them either, and their loaders are not started.
 */
import { currentUser, hasScope } from './route-access.js';

/** True for a person who may change settings; also before anyone is known (nothing is shown then). */
export function isAdministrator(user = currentUser()) {
  return !user || hasScope(user.scopes, 'system:config');
}

/**
 * Hides every admin-only card under `root` for a person who is not an administrator.
 * @param {ParentNode | null} [root]
 * @returns {boolean} true when the cards were hidden
 */
export function hideAdminOnly(root = document, user = currentUser()) {
  if (isAdministrator(user)) return false;
  (root || document).querySelectorAll('[data-admin-only]').forEach((el) => el.setAttribute('hidden', ''));
  return true;
}
