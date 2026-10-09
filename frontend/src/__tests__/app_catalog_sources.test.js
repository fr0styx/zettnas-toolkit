import { describe, it, expect, beforeEach, vi } from 'vitest';
import { api } from '../api.js';
import {
  fetchAndRenderAppCatalog,
  fetchCatalogSources,
  renderAppCatalogGrid,
  openAppSourcesModal,
  _resetCatalogStateForTesting,
} from '../components/management.js';

describe('App Catalog Sources (Portainer v2/v3 & Custom Sources)', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="mgmt-pane-docker">
        <button id="btn-view-docker-containers" class="active"></button>
        <button id="btn-view-docker-catalog">📦 App Catalog <span id="catalog-total-badge">0</span></button>
        <div id="docker-view-containers-wrap"></div>
        <div id="docker-view-catalog-wrap" style="display:none;">
          <input type="text" id="catalog-search-input">
          <button id="btn-manage-app-sources">🌐 Sources <span id="catalog-sources-count-badge">1</span></button>
          <button class="catalog-filter-btn active" data-cat="all">All Apps <span id="catalog-all-count">0</span></button>
          <button class="catalog-filter-btn" data-cat="media">Media</button>
          <button class="catalog-filter-btn" data-cat="utilities">Utilities</button>
          <div id="docker-catalog-grid"></div>
        </div>
      </div>
    `;
    vi.restoreAllMocks();
    _resetCatalogStateForTesting();
  });

  it('fetches catalog sources and updates source badge count', async () => {
    const mockSources = [
      { id: 'builtin', name: 'ZettNAS Curated Suite', enabled: true, item_count: 25 },
      { id: 'lissy93', name: 'Lissy93 Templates', enabled: true, item_count: 796 },
    ];
    vi.spyOn(api, 'get').mockResolvedValue(mockSources);

    const sources = await fetchCatalogSources();
    expect(sources).toHaveLength(2);

    const badge = document.getElementById('catalog-sources-count-badge');
    expect(badge.textContent).toBe('2');
  });

  it('renders custom source badges and logos in app catalog grid', async () => {
    const mockCatalog = [
      {
        id: 'builtin_jellyfin',
        name: 'Jellyfin',
        category: 'media',
        description: 'Media streaming',
        image: 'jellyfin/jellyfin:latest',
        default_port: 8096,
        source_name: 'Built-in',
        logo: '',
      },
      {
        id: 'lissy93_adguard',
        name: 'AdGuard Home',
        category: 'utilities',
        description: 'Network-wide ad blocking',
        image: 'adguard/adguardhome:latest',
        default_port: 3000,
        source_name: 'Lissy93 Templates',
        logo: 'https://example.com/adguard.png',
        type: 'standalone',
      },
      {
        id: 'lissy93_activepieces',
        name: 'Activepieces',
        category: 'automation',
        description: 'Workflow automation',
        image: '',
        default_port: 38080,
        source_name: 'Lissy93 Templates',
        logo: 'https://example.com/activepieces.png',
        type: 'stack',
      },
    ];

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/docker/catalog') return Promise.resolve(mockCatalog);
      if (url === '/api/docker/catalog/sources') {
        return Promise.resolve([
          { id: 'builtin', name: 'Built-in', enabled: true },
          { id: 'lissy93', name: 'Lissy93 Templates', enabled: true },
        ]);
      }
      return Promise.resolve([]);
    });

    await fetchAndRenderAppCatalog();

    const grid = document.getElementById('docker-catalog-grid');
    const cards = grid.querySelectorAll('.catalog-app-card');
    expect(cards).toHaveLength(3);

    // Verify source badges
    expect(grid.textContent).toContain('Built-in');
    expect(grid.textContent).toContain('Lissy93 Templates');
    expect(grid.textContent).toContain('Stack');

    // Verify image/logo
    const imgEl = grid.querySelector('img[src="https://example.com/adguard.png"]');
    expect(imgEl).toBeTruthy();

    // Verify count badges
    const totalBadge = document.getElementById('catalog-total-badge');
    expect(totalBadge.textContent).toBe('3');
  });

  it('opens sources modal and handles adding and syncing sources', async () => {
    const mockSources = [
      { id: 'builtin', name: 'Built-in', url: 'builtin', enabled: true, item_count: 25, status: 'ok', last_synced: 1000 },
    ];

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/docker/catalog/sources') return Promise.resolve(mockSources);
      if (url === '/api/docker/catalog') return Promise.resolve([]);
      return Promise.resolve([]);
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      status: 'ok',
      source: { id: 'test_src', name: 'Test Source', enabled: true, item_count: 10, status: 'ok' },
    });

    await openAppSourcesModal();

    const modal = document.getElementById('app-sources-modal-overlay');
    expect(modal).toBeTruthy();
    expect(modal.style.display).toBe('flex');

    // Test Quick Preset click
    const btnLissy = document.getElementById('asm-btn-add-lissy');
    expect(btnLissy).toBeTruthy();
    btnLissy.click();

    expect(postSpy).toHaveBeenCalledWith('/api/docker/catalog/sources', {
      name: 'Lissy93 Templates',
      url: 'https://raw.githubusercontent.com/Lissy93/portainer-templates/main/templates.json',
    });
  });
});
