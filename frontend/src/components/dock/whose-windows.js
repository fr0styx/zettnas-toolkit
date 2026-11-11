// Whose windows these are (SET-12).
// The windows that come back after a reload were remembered per browser, and signing out left
// every window open behind the sign-in page: the next person on a shared computer got the last
// person's pages. The remembered list now carries a name, and signing out closes the windows.
import { currentUser } from '../../route-access.js';

/** The name stored with the list; '' while the account is not known. */
export function ownerName() {
  return currentUser()?.username || '';
}

/** Whether a remembered list is this person's. A list without a name, or an account that is not
 *  known yet, counts as theirs: a reload keeps the same session. */
export function isMine(stored) {
  const me = ownerName();
  return !me || !stored?.who || stored.who === me;
}

/** Signing out: every window closes and the remembered list goes. */
export function forgetWindows(dock, key, storage = localStorage) {
  for (const [id, win] of Object.entries(dock?.windows || {})) {
    if (!win || win.closed) continue;
    try {
      dock.closeWindow(id);
    } catch (e) {
      console.warn('A window did not close at sign-out:', id, e);
    }
  }
  try {
    storage.removeItem(key);
  } catch {
    /* private window */
  }
}
