import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn() } }));
const { api } = await import('../api.js');
const { installDocFilters, selectedTags, filtersHtml, tagLabel, _reset } = await import('../components/management/doc-filters.js');

const TAGS = { kinds: [{ tag: 'bill', count: 12 }, { tag: 'tax', count: 3 }], years: [{ tag: 'year:2025', count: 9 }] };

describe('Document filters', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div><select id="ai-search-sort-select"></select></div>';
    vi.clearAllMocks();
    _reset();
  });

  it('shows a chip per tag with its count, and years', async () => {
    api.get.mockResolvedValue(TAGS);
    await installDocFilters(document);
    const box = document.getElementById('ai-doc-filters');
    expect(box.textContent).toContain('Bills & receipts');
    expect(box.textContent).toContain('12');
    expect(box.textContent).toContain('2025');
    expect(api.get).toHaveBeenCalledWith('/api/ai/tags');
  });

  it('narrows the search by the chosen chips and clears them', async () => {
    api.get.mockResolvedValue(TAGS);
    const onChange = vi.fn();
    await installDocFilters(document, onChange);
    const box = document.getElementById('ai-doc-filters');
    box.querySelector('[data-doc-tag="bill"]').click();
    box.querySelector('[data-doc-tag="year:2025"]').click();
    expect(selectedTags()).toEqual(['bill', 'year:2025']);
    expect(onChange).toHaveBeenLastCalledWith(['bill', 'year:2025']);
    expect(box.querySelector('[data-doc-tag="bill"]').getAttribute('aria-pressed')).toBe('true');
    box.querySelector('[data-doc-tag="bill"]').click();
    expect(selectedTags()).toEqual(['year:2025']);
    box.querySelector('[data-doc-tag-clear]').click();
    expect(selectedTags()).toEqual([]);
  });

  it('shows nothing when no document has a tag yet, or the server says no', async () => {
    expect(String(filtersHtml({ kinds: [], years: [] }))).toBe('');
    api.get.mockRejectedValue(new Error('403'));
    await installDocFilters(document);
    expect(document.getElementById('ai-doc-filters').textContent).toBe('');
    expect(tagLabel('year:2024')).toBe('2024');
    expect(tagLabel('something_new')).toBe('something_new');
  });
});
