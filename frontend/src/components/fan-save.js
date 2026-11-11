// Saving a change of the fan settings (SET-08).
// The Fans tab sent its whole picture with every change: the mode it had last drawn, the whole
// curve and two fixed temperatures. A switch flipped here undid a mode chosen on the Host tab.
// And a change the server refused looked applied: the control had moved, the error was only logged.

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { t } from '../i18n.js';

/**
 * Sends only the fields in `change`. On success `onSaved` gets the settings as the server now
 * holds them. On a refusal or an error the person is told and `reread` puts the controls back.
 * @param {Record<string, unknown>} change
 * @param {{ onSaved?: (data: any) => void, reread?: () => unknown }} [hooks]
 * @returns {Promise<any | null>} the saved settings, or null when nothing was saved
 */
export async function saveFans(change, hooks = {}) {
  try {
    const data = await api.post('/api/fans', change);
    hooks.onSaved?.(data);
    return data;
  } catch (err) {
    const error = (err && (err.detail || err.message)) || String(err);
    showToast(t('fan.not_saved', 'The fan setting was not changed: {error}', { error }), 'error');
    await hooks.reread?.();
    return null;
  }
}

/** What a click on a mode button sends: the mode, and nothing else. */
export const modeChange = (profile) => ({ profile });

/** What the manual slider sends. */
export const manualChange = (pct) => ({ profile: 'manual', manual_pct: Number(pct) });
