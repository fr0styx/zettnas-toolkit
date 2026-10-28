// Photo filters (AI-24): chips for the years and places the photos were taken, from their EXIF
// date and GPS position, each with how many photos you may see carry it. One year and one place
// at a time; the search keeps the photos that match (backend/services/photo_place.py).
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { html } from '../../html.js';

const BOX_ID = 'ai-photo-filters';
const chosen = { taken: null, place: null };

export const selectedPhotoFilters = () => ({ ...chosen });
export const hasPhotoFilters = () => Boolean(chosen.taken || chosen.place);

function chip(kind, item) {
  const on = chosen[kind] === item.value;
  const label = kind === 'place' ? item.value.split(',')[0] : item.value;
  return html`<button type="button" class="btn-pill-toggle is-small${on ? ' active' : ''}" data-photo-${kind}="${item.value}" aria-pressed="${on ? 'true' : 'false'}" title="${item.value}">${label} <span class="zn-muted">${item.count}</span></button>`;
}

export function photoFiltersHtml(data) {
  const years = ((data && data.years) || []).slice(0, 10);
  const places = ((data && data.places) || []).slice(0, 12);
  if (!years.length && !places.length) return html``;
  return html`<span class="zn-muted">${t('photo_filters.title', 'Photos from:')}</span>${years.map((y) => chip('taken', y))}${
    places.length ? html`<span class="zn-muted">·</span>${places.map((p) => chip('place', p))}` : ''
  }${hasPhotoFilters() ? html`<button type="button" class="btn-pill-toggle is-small" data-photo-clear>${t('tags.clear', 'Clear')}</button>` : ''}`;
}

export async function installPhotoFilters(root = document, onChange = () => {}) {
  const anchor = root.getElementById('ai-doc-filters') || root.getElementById('ai-search-sort-select')?.parentElement;
  if (!anchor) return;
  let box = root.getElementById(BOX_ID);
  if (!box) {
    box = Object.assign(document.createElement('div'), { id: BOX_ID, className: 'zn-row' });
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', t('photo_filters.group', 'Photo filters'));
    anchor.insertAdjacentElement('afterend', box);
    box.addEventListener('click', (e) => {
      const b = e.target.closest('[data-photo-taken], [data-photo-place], [data-photo-clear]');
      if (!b) return;
      if (b.hasAttribute('data-photo-clear')) {
        chosen.taken = null;
        chosen.place = null;
      } else {
        const kind = b.hasAttribute('data-photo-taken') ? 'taken' : 'place';
        const value = b.dataset[kind === 'taken' ? 'photoTaken' : 'photoPlace'];
        chosen[kind] = chosen[kind] === value ? null : value;
      }
      box.innerHTML = photoFiltersHtml(box._data);
      onChange(selectedPhotoFilters());
    });
  }
  try {
    box._data = await api.get('/api/ai/photo-facets');
  } catch {
    box._data = null;
  }
  box.innerHTML = photoFiltersHtml(box._data);
}

export function _reset() {
  chosen.taken = null;
  chosen.place = null;
}
