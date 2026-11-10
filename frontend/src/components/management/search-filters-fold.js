/**
 * The AI search's extra filters (document kinds and years, photo years and places, duplicates) in one
 * "Filters" line under the search row, closed until asked for, with how many are on. Each filter
 * module puts its row in here and reports how many of its chips are chosen.
 */
import { t } from '../../i18n.js';

const FOLD_ID = 'ai-more-filters';
const OPEN_KEY = 'kiboto_ai_filters_open';
const active = new Map();

function wasOpen() {
  try {
    return localStorage.getItem(OPEN_KEY) === '1';
  } catch {
    return false;
  }
}

function label() {
  const n = [...active.values()].reduce((a, b) => a + b, 0);
  return n ? t('ai.filters_n', 'Filters · {n}', { n }) : t('ai.filters', 'Filters');
}

/** The fold's body to put a filter row in, made under the search row the first time; null where the
 * page has no search row (the filter then sits where it always did). */
export function filtersFold(root = document) {
  const existing = root.getElementById(FOLD_ID);
  if (existing) return existing.querySelector('.ai-more-body');
  const row = root.getElementById('ai-search-sort-select')?.closest('.rag-row-2');
  if (!row) return null;
  const fold = document.createElement('details');
  fold.id = FOLD_ID;
  fold.className = 'ai-more-filters';
  fold.open = wasOpen();
  const summary = document.createElement('summary');
  summary.className = 'btn-pill-toggle is-small';
  summary.textContent = label();
  const body = document.createElement('div');
  body.className = 'ai-more-body';
  fold.append(summary, body);
  fold.addEventListener('toggle', () => {
    try {
      localStorage.setItem(OPEN_KEY, fold.open ? '1' : '0');
    } catch {
      /* private window: it opens closed next time */
    }
  });
  row.insertAdjacentElement('afterend', fold);
  return body;
}

/** A filter module says how many of its chips are on; the summary shows the total. */
export function reportActive(source, count, root = document) {
  active.set(source, Number(count) || 0);
  const summary = root.querySelector(`#${FOLD_ID} > summary`);
  if (summary) summary.textContent = label();
}

/** Puts el in the fold, or after anchor where there is no fold. */
export function placeFilter(el, anchor, root = document) {
  const body = filtersFold(root);
  if (body) body.appendChild(el);
  else anchor.insertAdjacentElement('afterend', el);
}

export function _reset() {
  active.clear();
}
