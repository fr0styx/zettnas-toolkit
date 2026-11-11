// A page part that could not be read says so, with "Try again"; and "Refresh" speaks after the
// answer (SET-09). The Storage page drew an invented picture when a call failed (a layout named
// by the number of drives, the system drive labelled as parity, everything green), and its
// Refresh buttons said "refreshed" at once, whatever came back.

import { escapeHtml } from '../utils.js';
import { showToast } from '../toast.js';
import { t } from '../i18n.js';

/**
 * Draws "could not be read" with a Try again button into `container`.
 * @param {HTMLElement} container
 * @param {string} text what could not be read, as a sentence
 * @param {() => unknown} retry
 */
export function showReadError(container, text, retry) {
  container.innerHTML = `
    <div class="cv-muted-center read-error" role="alert">
      <p>${escapeHtml(text)}</p>
      <button type="button" class="btn-pill-toggle" data-try-again>${escapeHtml(t('common.try_again', 'Try again'))}</button>
    </div>`;
  const btn = container.querySelector('[data-try-again]');
  if (btn) btn.addEventListener('click', () => retry());
}

/**
 * Runs a refresh and says how it went. `run` answers false when it could not read its data.
 * @param {() => unknown} run
 * @param {string} okText
 * @param {string} [failText]
 * @returns {Promise<boolean>}
 */
export async function refreshAndSay(run, okText, failText) {
  let ok;
  try {
    ok = (await run()) !== false;
  } catch (err) {
    ok = false;
  }
  if (ok) showToast(okText, 'info');
  else showToast(failText || t('refresh.failed', 'Could not refresh. What you see may be out of date.'), 'error');
  return ok;
}
