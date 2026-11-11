// One block for the four states a part of a page can be in besides showing its data (SET-11):
// loading, could not load, nothing there, and "you can look but not change".
// The pages had a way of their own for each, or none: a failed load was drawn as "nothing there",
// as a sample value, or as good news.

import { t } from '../i18n.js';

const DEFAULT_TEXT = {
  loading: () => t('state.loading', 'Loading…'),
  failed: () => t('state.failed', 'This could not be loaded.'),
  empty: () => t('state.empty', 'Nothing here yet.'),
  readonly: () => t('state.readonly', 'You can look at this, but only an administrator can change it.'),
};

/**
 * Builds the block.
 * @param {'loading' | 'failed' | 'empty' | 'readonly'} kind
 * @param {{ text?: string, detail?: string, retry?: () => unknown, action?: { label: string, run: () => unknown } }} [opts]
 * @returns {HTMLElement}
 */
export function stateBlock(kind, opts = {}) {
  const known = Object.prototype.hasOwnProperty.call(DEFAULT_TEXT, kind) ? kind : 'failed';
  const box = document.createElement('div');
  box.className = `state-block is-${known}`;
  // a failure is announced at once, the others when the reader gets there
  box.setAttribute('role', known === 'failed' ? 'alert' : known === 'readonly' ? 'note' : 'status');
  if (known === 'loading') box.setAttribute('aria-busy', 'true');
  const said = document.createElement('p');
  said.className = 'state-block-text';
  said.textContent = opts.text || DEFAULT_TEXT[known]();
  box.append(said);
  if (opts.detail) {
    const more = document.createElement('p');
    more.className = 'state-block-detail';
    more.textContent = opts.detail;
    box.append(more);
  }
  if (known === 'failed' && typeof opts.retry === 'function') {
    box.append(button(t('common.try_again', 'Try again'), opts.retry, 'data-try-again'));
  }
  if (known === 'empty' && opts.action && typeof opts.action.run === 'function') {
    box.append(button(opts.action.label, opts.action.run, 'data-state-action'));
  }
  return box;
}

function button(label, run, mark) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn-pill-toggle';
  btn.setAttribute(mark, '');
  btn.textContent = label;
  btn.addEventListener('click', () => run());
  return btn;
}

/**
 * Puts the block in place of whatever `container` shows.
 * @param {HTMLElement | null} container
 * @param {'loading' | 'failed' | 'empty' | 'readonly'} kind
 * @param {Parameters<typeof stateBlock>[1]} [opts]
 * @returns {HTMLElement | null}
 */
export function showState(container, kind, opts = {}) {
  if (!container) return null;
  const block = stateBlock(kind, opts);
  container.replaceChildren(block);
  return block;
}

/** Adds the "look but not change" note above a part, once. */
export function markReadOnly(container, text) {
  if (!container || container.querySelector(':scope > .state-block.is-readonly')) return null;
  const block = stateBlock('readonly', { text });
  container.prepend(block);
  return block;
}
