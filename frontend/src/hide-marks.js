// Why something is hidden (SET-12).
// Two things hide places in Settings: the person's rights, and the Advanced switch. Each wrote the
// `hidden` attribute itself, on the same elements, so switching Advanced on showed a family member
// the pages their rights had hidden. An element is now hidden while any reason says so.

export const NO_ACCESS = 'data-no-access';
export const ADVANCED_OFF = 'data-advanced-off';
export const EMPTY_GROUP = 'data-empty-group';
const REASONS = [NO_ACCESS, ADVANCED_OFF, EMPTY_GROUP];

/**
 * Sets or clears one reason on an element and hides it while any reason is left. Something that
 * was hidden by other code, with no reason of ours, is left as it is.
 * @param {Element | null} el
 * @param {string} reason
 * @param {boolean} on
 */
export function mark(el, reason, on) {
  const node = /** @type {HTMLElement | null} */ (el);
  if (!node) return;
  const ours = REASONS.some((r) => node.hasAttribute(r));
  if (on) {
    if (node.hidden && !ours) return;
    node.setAttribute(reason, '');
    node.hidden = true;
  } else if (node.hasAttribute(reason)) {
    node.removeAttribute(reason);
    node.hidden = REASONS.some((r) => node.hasAttribute(r));
  }
}

/** Goes back to the Overview when the open Settings page is one this reason hides now. */
export function leavePage(reason, root = document) {
  const active = root.querySelector('.mgmt-sidebar-item.active');
  if (!active || !active.hasAttribute(reason)) return false;
  /** @type {HTMLElement | null} */ (root.querySelector('.mgmt-sidebar-item[data-mgmt-target="management-hub-view"]'))?.click();
  return true;
}

/** Hides a sidebar heading that has nothing left under it, and shows it again when it has. */
export function tidyHeadings(root = document) {
  root.querySelectorAll('.mgmt-sidebar-category').forEach((heading) => {
    let any = false;
    let shown = false;
    for (let el = heading.nextElementSibling; el && !el.classList.contains('mgmt-sidebar-category'); el = el.nextElementSibling) {
      if (!el.classList.contains('mgmt-sidebar-item')) continue;
      any = true;
      if (!(/** @type {HTMLElement} */ (el)).hidden) shown = true;
    }
    mark(heading, EMPTY_GROUP, any && !shown);
  });
}
