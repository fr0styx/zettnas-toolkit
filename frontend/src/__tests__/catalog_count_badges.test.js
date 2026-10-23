import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { get: vi.fn() },
  auth: { getToken: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

import { api } from '../api.js';
import { refreshCatalogCountBadges } from '../components/management.js';

describe('App catalog count badges', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <span id="catalog-total-badge">…</span>
      <span id="catalog-total-badge-tab">…</span>
      <span id="catalog-all-count">…</span>`;
  });

  it('show the number of apps the server lists, before the catalog is opened', async () => {
    api.get.mockResolvedValueOnce(Array.from({ length: 79 }, (_, i) => ({ id: `app${i}` })));
    await refreshCatalogCountBadges();
    for (const id of ['catalog-total-badge', 'catalog-total-badge-tab', 'catalog-all-count']) {
      expect(document.getElementById(id).textContent).toBe('79');
    }
    expect(api.get).toHaveBeenCalledWith('/api/docker/catalog');
  });
});
