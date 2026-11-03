/** NUX-20: the Docker settings panel, its cleanup and template-source windows read in the person's language. */
import { describe, it, expect, beforeAll, afterAll, beforeEach, vi } from 'vitest';
import { setLanguage } from '../i18n.js';
import { api } from '../api.js';
import {
  openDockerPruneModal,
  openAppSourcesModal,
  fetchAndRenderAppCatalog,
  setDockerSort,
  updateDockerTableHeaderUI,
  _resetCatalogStateForTesting,
} from '../components/management.js';

describe('Docker settings in German (NUX-20)', () => {
  beforeAll(async () => { await setLanguage('de'); });
  afterAll(async () => { await setLanguage('en'); });
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="mgmt-pane-docker">
        <table><thead><tr><th class="sortable-th" data-sort-col="name"><span class="docker-sort-indicator"></span></th></tr></thead></table>
        <div id="docker-catalog-grid"></div>
      </div>`;
    vi.restoreAllMocks();
    _resetCatalogStateForTesting();
  });

  it('titles the sort arrow', () => {
    setDockerSort('name', 'desc');
    updateDockerTableHeaderUI();
    expect(document.querySelector('.docker-sort-indicator').title).toBe('Absteigend sortiert');
  });

  it('explains every cleanup choice', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    await openDockerPruneModal();
    const modal = document.getElementById('docker-prune-modal-overlay');
    expect(modal.textContent).toContain('Docker aufräumen');
    expect(modal.textContent).toContain('Verwaiste Images entfernen');
    expect(modal.textContent).toContain('Entfernt unbenannte „none“-Build-Schichten');
    expect(modal.textContent).toContain('Freigebbar');
    expect(document.getElementById('dpm-cancel-btn').textContent).toBe('Abbrechen');
    expect(document.getElementById('dpm-confirm-btn').textContent).toContain('Aufräumen und Platz schaffen');
  });

  it('lists template sources, or says there are none or that they could not be loaded', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue([]);
    await openAppSourcesModal();
    const list = () => document.getElementById('asm-sources-list');
    await vi.waitFor(() => expect(list().textContent).toContain('Noch keine Vorlagenquellen.'));
    const modal = document.getElementById('app-sources-modal-overlay') || document.body;
    expect(modal.textContent).toContain('Quellen für App-Vorlagen');
    expect(modal.textContent).toContain('Eingerichtete Quellen (');

    get.mockResolvedValue([
      { id: 'a', name: 'Eins', url: 'https://example.com/a.json', enabled: true, status: 'ok', item_count: 3, last_synced: Date.now() / 1000 },
      { id: 'b', name: 'Zwei', url: 'https://example.com/b.json', enabled: true, status: 'error', error: 'kaputt' },
    ]);
    await openAppSourcesModal();
    await vi.waitFor(() => expect(list().textContent).toContain('Synchronisiert ('));
    expect(list().textContent).toContain('Fehler');

    get.mockRejectedValue(new Error('weg'));
    await openAppSourcesModal();
    await vi.waitFor(() => expect(list().textContent).toContain('Quellen konnten nicht geladen werden: weg'));
  });

  it('says when the catalog could not be loaded', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'));
    await fetchAndRenderAppCatalog();
    expect(document.getElementById('docker-catalog-grid').textContent).toBe('Katalog konnte nicht geladen werden: offline');
  });
});
