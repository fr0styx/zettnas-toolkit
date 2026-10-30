// A card that couldn't load says so in a sentence and offers Retry (NUX-14), instead of
// replacing itself with the bare error.
import { t } from '../i18n.js';

/** Shows "couldn't load" with the reason and a Retry button that calls `retry`. */
export function showLoadError(mount, err, retry) {
  const box = document.createElement('div');
  box.className = 'zn-load-error';
  box.setAttribute('role', 'alert');
  const text = document.createElement('p');
  const reason = (err && err.message) || String(err || '');
  text.textContent = t('ui.load_failed', "This couldn't be loaded: {reason}", { reason });
  const again = document.createElement('button');
  again.type = 'button';
  again.className = 'btn-pill-toggle is-small';
  again.textContent = t('ui.retry', 'Try again');
  again.addEventListener('click', () => retry());
  box.append(text, again);
  mount.replaceChildren(box);
  return box;
}
