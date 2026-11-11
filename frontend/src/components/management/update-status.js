// The update status on Settings → About (SET-10).
// A check that failed (no internet, GitHub refusing) read "Kiboto is up to date". And "Revert to
// previous version" sat inside the box that is hidden when Kiboto is up to date, so after an
// update it could not be reached.

import { t } from '../../i18n.js';

/**
 * Whether the answer of the update check is a failed check.
 * @param {any} data the answer of GET /api/system/updates
 */
export const checkFailed = (data) => !!(data && data.error && !data.update_available);

/**
 * What the status line says after a failed check.
 * @param {any} data
 * @returns {{ icon: string, title: string, desc: string }}
 */
export function checkFailedText(data) {
  return {
    icon: '⚠️',
    title: t('sysu.check_failed', 'Could not check for updates'),
    desc: t('sysu.check_failed_desc', 'Kiboto {version} is running. The check did not get an answer ({error}), so a newer version may exist.', {
      version: data?.current_version ? `v${data.current_version}` : '',
      error: String(data?.error || '').slice(0, 120),
    }),
  };
}

/**
 * Moves the Revert button out of the box that is hidden when no update is waiting.
 * @param {HTMLElement | null} button
 * @param {HTMLElement | null} hiddenBox
 * @returns {boolean} whether it was moved
 */
export function keepRevertReachable(button, hiddenBox) {
  if (!button || !hiddenBox || !hiddenBox.contains(button)) return false;
  hiddenBox.insertAdjacentElement('afterend', button);
  return true;
}
