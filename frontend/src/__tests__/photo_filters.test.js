import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn() } }));
const { api } = await import('../api.js');
const pf = await import('../components/management/photo-filters.js');

const FACETS = {
  years: [{ value: '2024', count: 120 }, { value: '2023', count: 80 }],
  places: [{ value: 'Rome, Lazio, Italy', count: 40 }, { value: 'Paris, Île-de-France, France', count: 12 }],
};

describe('AI-24: photo filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pf._reset();
    document.body.innerHTML = '<div><select id="ai-search-sort-select"></select></div><div id="ai-doc-filters"></div>';
  });

  it('shows the years and towns with their counts after the document filters', async () => {
    api.get.mockResolvedValue(FACETS);
    await pf.installPhotoFilters(document);
    const box = document.getElementById('ai-photo-filters');
    expect(box.previousElementSibling.id).toBe('ai-doc-filters');
    expect(api.get).toHaveBeenCalledWith('/api/ai/photo-facets');
    expect(box.textContent).toContain('Photos from:');
    expect(box.textContent).toContain('2024 120');
    expect(box.textContent).toContain('Rome 40');
    expect(box.querySelector('[data-photo-place="Rome, Lazio, Italy"]').title).toBe('Rome, Lazio, Italy');
  });

  it('picks one year and one place, toggles them and clears them', async () => {
    api.get.mockResolvedValue(FACETS);
    const onChange = vi.fn();
    await pf.installPhotoFilters(document, onChange);
    const box = document.getElementById('ai-photo-filters');
    box.querySelector('[data-photo-taken="2024"]').click();
    box.querySelector('[data-photo-taken="2023"]').click();
    box.querySelector('[data-photo-place="Rome, Lazio, Italy"]').click();
    expect(pf.selectedPhotoFilters()).toEqual({ taken: '2023', place: 'Rome, Lazio, Italy' });
    expect(onChange).toHaveBeenLastCalledWith({ taken: '2023', place: 'Rome, Lazio, Italy' });
    expect(box.querySelector('[data-photo-taken="2023"]').getAttribute('aria-pressed')).toBe('true');
    box.querySelector('[data-photo-taken="2023"]').click();
    expect(pf.selectedPhotoFilters().taken).toBeNull();
    box.querySelector('[data-photo-clear]').click();
    expect(pf.hasPhotoFilters()).toBe(false);
  });

  it('shows nothing when no photo has a date or place, or the server fails', async () => {
    api.get.mockResolvedValue({ years: [], places: [] });
    await pf.installPhotoFilters(document);
    expect(document.getElementById('ai-photo-filters').textContent).toBe('');
    api.get.mockRejectedValue(new Error('down'));
    await pf.installPhotoFilters(document);
    expect(document.getElementById('ai-photo-filters').textContent).toBe('');
    expect(document.querySelectorAll('#ai-photo-filters').length).toBe(1);
  });
});
