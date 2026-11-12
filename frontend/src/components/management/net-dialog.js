/**
 * The Network page's dialogs work with a keyboard (network report F3): opening one moves focus
 * into it, Tab stays inside, Escape closes it, and closing gives focus back to what opened it.
 * None of the eight did any of that.
 */
import { trapFocus } from '../../utils.js';

const OPEN = new Map(); // overlay -> { release, opener }
const FIRST = 'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])';

/** Shows the dialog in `overlay`; `close` is what Escape runs (the dialog's own close). */
export function showNetDialog(overlay, close) {
  overlay.classList.add('open');
  overlay.style.display = 'flex';
  if (OPEN.has(overlay)) return;
  const opener = document.activeElement;
  const win = overlay.querySelector('.smart-modal-window') || overlay;
  if (!win.hasAttribute('tabindex')) win.setAttribute('tabindex', '-1');
  const first = /** @type {HTMLElement | null} */ (win.querySelector(FIRST));
  (first || /** @type {HTMLElement} */ (win)).focus({ preventScroll: true });
  OPEN.set(overlay, { release: trapFocus(win, () => close()), opener });
}

/** Hides it and gives focus back to what opened it. */
export function hideNetDialog(overlay) {
  if (!overlay) return;
  overlay.classList.remove('open');
  overlay.style.display = 'none';
  const was = OPEN.get(overlay);
  if (!was) return;
  OPEN.delete(overlay);
  was.release();
  const opener = /** @type {HTMLElement | null} */ (was.opener);
  if (opener && opener.isConnected && typeof opener.focus === 'function') opener.focus({ preventScroll: true });
}
