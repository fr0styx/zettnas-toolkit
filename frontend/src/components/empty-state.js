/**
 * One empty state for every list (UX-11): what this place is for, and the next step.
 * `action.target` is the id of the button that does it (clicked through dom-actions'
 * click-target), or `action.id` names a new button the caller binds itself.
 */
import { escapeHtml } from '../utils.js';

export function emptyStateHtml({ icon = '', title, body = '', action = null, compact = false } = {}) {
  let button = '';
  if (action && action.label) {
    const attrs = action.target
      ? ` data-action="click-target" data-target="${escapeHtml(action.target)}"`
      : '';
    const id = action.id ? ` id="${escapeHtml(action.id)}"` : '';
    button = `<button type="button" class="btn-pill-toggle is-primary empty-state-action"${id}${attrs}>${escapeHtml(action.label)}</button>`;
  }
  return `<div class="empty-state${compact ? ' is-compact' : ''}" role="status">
    ${icon ? `<div class="empty-state-icon" aria-hidden="true">${icon}</div>` : ''}
    <div class="empty-state-title">${escapeHtml(title)}</div>
    ${body ? `<div class="empty-state-body">${escapeHtml(body)}</div>` : ''}
    ${button}
  </div>`;
}

/** The same, as a table row spanning `colspan` columns. */
export function emptyRowHtml(colspan, opts) {
  return `<tr class="empty-state-row"><td colspan="${Number(colspan) || 1}">${emptyStateHtml({ compact: true, ...opts })}</td></tr>`;
}
