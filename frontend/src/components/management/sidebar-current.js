// Which sidebar entry stands for the open page (SET-12).
// A page with tabs can have an entry per tab ("Users" and "Backup" are tabs of one page). Only
// opening a page chose the entry, so a click on the Users tab left "Settings" highlighted.
import { markCurrent } from '../tab-a11y.js';
import { NO_ACCESS } from '../../hide-marks.js';

const ENTRIES = '.mgmt-sidebar-item';

/** The entry of a page: the one for its tab when there is one, else the page's own. */
export function entryFor(sectionId, paneId, root = document) {
  const items = Array.from(root.querySelectorAll(ENTRIES));
  const el = /** @param {Element} b */ (b) => /** @type {HTMLElement} */ (b);
  return (
    (paneId && items.find((b) => el(b).dataset.mgmtPane === paneId)) ||
    items.find((b) => el(b).dataset.mgmtTarget === sectionId && !el(b).dataset.mgmtPane) ||
    null
  );
}

/** Highlights the entry of the open page and returns it. */
export function highlightEntry(sectionId, paneId, root = document) {
  const current = entryFor(sectionId, paneId, root);
  const items = root.querySelectorAll(ENTRIES);
  markCurrent(items, (b) => b === current);
  items.forEach((b) => b.classList.toggle('active', b === current));
  return current;
}

/** Whether this person's rights hide the page: it is then not opened, whatever asked for it
 *  (a link, an alert, the page remembered from before a reload). */
export function mayNotOpen(sectionId, paneId, root = document) {
  return Boolean(entryFor(sectionId, paneId, root)?.hasAttribute(NO_ACCESS));
}
