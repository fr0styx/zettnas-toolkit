import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn() } }));
const { api } = await import('../api.js');
const fold = await import('../components/management/search-filters-fold.js');
const docs = await import('../components/management/doc-filters.js');
const photos = await import('../components/management/photo-filters.js');

const PAGE = '<div class="rag-row-2"><div><select id="ai-search-sort-select"></select></div></div><div id="ai-history-bar"></div>';
const tick = () => new Promise((r) => setTimeout(r, 0));

describe('the AI search filters fold away (one line under the search row)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fold._reset();
    docs._reset();
    photos._reset();
    localStorage.clear();
    document.body.innerHTML = PAGE;
  });

  it('puts the document and photo filters in one closed "Filters" line', async () => {
    api.get.mockImplementation(async (url) => (url.includes('tags') ? { kinds: [{ tag: 'bill', count: 3 }], years: [] } : { years: [{ value: '2024', count: 5 }], places: [] }));
    await docs.installDocFilters(document, () => {});
    await photos.installPhotoFilters(document, () => {});
    const box = document.getElementById('ai-more-filters');
    expect(box.tagName).toBe('DETAILS');
    expect(box.open).toBe(false);
    expect(document.querySelector('.rag-row-2').nextElementSibling).toBe(box);
    expect(box.querySelector('#ai-doc-filters')).not.toBeNull();
    expect(box.querySelector('#ai-photo-filters')).not.toBeNull();
    expect(box.querySelector('summary').textContent).toBe('Filters');
  });

  it('counts the filters that are on, and remembers being opened', async () => {
    api.get.mockImplementation(async (url) => (url.includes('tags') ? { kinds: [{ tag: 'bill', count: 3 }], years: [] } : { years: [{ value: '2024', count: 5 }], places: [{ value: 'Lisbon', count: 2 }] }));
    await docs.installDocFilters(document, () => {});
    await photos.installPhotoFilters(document, () => {});
    document.querySelector('[data-doc-tag="bill"]').click();
    document.querySelector('[data-photo-taken="2024"]').click();
    await tick();
    expect(document.querySelector('#ai-more-filters > summary').textContent).toBe('Filters · 2');
    const box = document.getElementById('ai-more-filters');
    box.open = true;
    box.dispatchEvent(new Event('toggle'));
    expect(localStorage.getItem('kiboto_ai_filters_open')).toBe('1');
    document.body.innerHTML = PAGE;
    fold.filtersFold(document);
    expect(document.getElementById('ai-more-filters').open).toBe(true);
  });

  it('keeps the old place where the page has no search row', () => {
    document.body.innerHTML = '<div id="anchor"></div>';
    const el = document.createElement('span');
    fold.placeFilter(el, document.getElementById('anchor'));
    expect(document.getElementById('anchor').nextElementSibling).toBe(el);
    expect(fold.filtersFold(document)).toBeNull();
    fold.reportActive('documents', 1);
  });
});
