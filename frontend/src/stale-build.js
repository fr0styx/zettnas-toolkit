/**
 * After an update, a page that was open before it still runs the old code. Parts that load
 * on first use (the file viewer, the Apps and VM windows, editors) ask for files of the old
 * version, which the server no longer has, and the click did nothing. This notices those
 * failures and offers a reload instead.
 */
import { showConfirmToast } from "./toast.js";
import { t } from "./i18n.js";

// Chrome, Safari and Firefox word a failed module download differently
const CHUNK_ERROR = /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS|Loading (CSS )?chunk [\w-]+ failed/i;
const QUIET_MS = 60000;
let _shownAt = 0;

export function isStaleBuildError(reason) {
  const msg = reason && (reason.message || String(reason));
  return Boolean(msg && CHUNK_ERROR.test(msg));
}

export function offerReload(win = window) {
  const now = Date.now();
  if (now - _shownAt < QUIET_MS) return false; // one offer per minute, however many clicks fail
  _shownAt = now;
  showConfirmToast(
    t("update.reload_title", "ZettNAS was updated"),
    t("update.reload_body", "This page is from the previous version, so some parts cannot open. Reload to use the new version."),
    () => win.location.reload(),
    null,
    { okText: t("update.reload_now", "Reload"), cancelText: t("update.reload_later", "Later") },
  );
  return true;
}

export function installStaleBuildGuard(win = window) {
  // Vite reports a failed on-demand load here before the import rejects
  win.addEventListener("vite:preloadError", (e) => {
    e.preventDefault?.();
    offerReload(win);
  });
  win.addEventListener("unhandledrejection", (e) => {
    if (isStaleBuildError(e.reason)) {
      e.preventDefault?.();
      offerReload(win);
    }
  });
}

export function _resetStaleBuildForTesting() {
  _shownAt = 0;
}
