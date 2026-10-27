// Document filters (B8): chips for the auto-tags search knows (a bill, a payslip, a year...),
// each with how many of the files you may see carry it. Choosing chips narrows the results to
// documents that carry all of them. The tags are made as files are indexed (backend/services/rag_tags.py).
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { html } from '../../html.js';

const BOX_ID = 'ai-doc-filters';
const selected = new Set();

const LABELS = {
  bill: () => t('tags.bill', 'Bills & receipts'),
  bank: () => t('tags.bank', 'Bank'),
  payslip: () => t('tags.payslip', 'Payslips'),
  contract: () => t('tags.contract', 'Contracts'),
  insurance: () => t('tags.insurance', 'Insurance'),
  tax: () => t('tags.tax', 'Tax'),
  medical: () => t('tags.medical', 'Health'),
  manual: () => t('tags.manual', 'Manuals & warranties'),
  school: () => t('tags.school', 'School'),
  travel: () => t('tags.travel', 'Travel'),
  home: () => t('tags.home', 'Home & rent'),
  car: () => t('tags.car', 'Car'),
  recipe: () => t('tags.recipe', 'Recipes'),
};

export const selectedTags = () => [...selected];

export function tagLabel(tag) {
  if (tag.startsWith('year:')) return tag.slice(5);
  return (LABELS[tag] || (() => tag))();
}

function chip(item) {
  const on = selected.has(item.tag);
  return html`<button type="button" class="btn-pill-toggle is-small${on ? ' is-active' : ''}" data-doc-tag="${item.tag}" aria-pressed="${on ? 'true' : 'false'}">${tagLabel(item.tag)} <span class="zn-muted">${item.count}</span></button>`;
}

export function filtersHtml(data) {
  const kinds = (data && data.kinds) || [];
  const years = ((data && data.years) || []).slice(0, 8);
  if (!kinds.length && !years.length) return html``;
  return html`<span class="zn-muted">${t('tags.title', 'Filter documents:')}</span>${kinds.map(chip)}${years.length ? html`<span class="zn-muted">·</span>${years.map(chip)}` : ''}${
    selected.size ? html`<button type="button" class="btn-pill-toggle is-small" data-doc-tag-clear>${t('tags.clear', 'Clear')}</button>` : ''
  }`;
}

export async function installDocFilters(root = document, onChange = () => {}) {
  const anchor = root.getElementById('ai-search-sort-select')?.parentElement;
  if (!anchor) return;
  let box = root.getElementById(BOX_ID);
  if (!box) {
    box = Object.assign(document.createElement('div'), { id: BOX_ID, className: 'zn-row' });
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', t('tags.group', 'Document filters'));
    anchor.insertAdjacentElement('afterend', box);
    box.addEventListener('click', (e) => {
      const b = e.target.closest('[data-doc-tag], [data-doc-tag-clear]');
      if (!b) return;
      if (b.hasAttribute('data-doc-tag-clear')) selected.clear();
      else if (selected.has(b.dataset.docTag)) selected.delete(b.dataset.docTag);
      else selected.add(b.dataset.docTag);
      box.innerHTML = filtersHtml(box._data);
      onChange(selectedTags());
    });
  }
  try {
    box._data = await api.get('/api/ai/tags');
  } catch {
    box._data = null;
  }
  box.innerHTML = filtersHtml(box._data);
}

export function _reset() {
  selected.clear();
}
