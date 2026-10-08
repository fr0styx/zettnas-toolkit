import { describe, it, expect, beforeEach, vi } from 'vitest';
import { api } from '../api.js';
import {
  initContainerModal,
  switchContainerTab,
  openContainerInspector,
  executeTerminalCmd,
  clearTerminal,
} from '../components/container-modal.js';
import {
  fetchAndRenderAppCatalog,
  renderAppCatalogGrid,
  _resetCatalogStateForTesting,
} from '../components/management.js';

describe('Phase 3: Container App Catalog & Web Terminal', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="os-dock-container"></div>
      <div id="i-chip"></div>
      <div id="mgmt-pane-docker">
        <button id="btn-view-docker-containers" class="active"></button>
        <button id="btn-view-docker-catalog"></button>
        <div id="docker-view-containers-wrap"></div>
        <div id="docker-view-catalog-wrap" style="display:none;">
          <input type="text" id="catalog-search-input">
          <button class="catalog-filter-btn" data-cat="all"></button>
          <button class="catalog-filter-btn" data-cat="media"></button>
          <div id="docker-catalog-grid"></div>
        </div>
      </div>
    `;
    vi.restoreAllMocks();
    _resetCatalogStateForTesting();
  });

  it('renders Web Terminal tab in container inspector modal', () => {
    initContainerModal();
    const termBtn = document.querySelector('.ci-tab-btn[data-tab="terminal"]');
    expect(termBtn).toBeTruthy();
    expect(termBtn.textContent).toContain('Web Terminal');

    const termPane = document.getElementById('ci-pane-terminal');
    expect(termPane).toBeTruthy();

    const termInput = document.getElementById('ci-term-input');
    const termOutput = document.getElementById('ci-term-output');
    expect(termInput).toBeTruthy();
    expect(termOutput).toBeTruthy();
  });

  it('switches to terminal tab and handles clear', async () => {
    initContainerModal();
    await switchContainerTab('terminal');

    const termPane = document.getElementById('ci-pane-terminal');
    expect(termPane.style.display).toBe('block');

    const termOutput = document.getElementById('ci-term-output');
    termOutput.innerHTML = '<div>Some old command output</div>';
    clearTerminal();
    expect(termOutput.textContent).toContain('Interactive Container Terminal Ready');
  });

  it('executes terminal command via container exec API', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      output: 'bin  etc  lib  root  usr  var',
      cmd: ['ls', '-la'],
    });

    await openContainerInspector('container123', 'test-app');
    await switchContainerTab('terminal');

    const input = document.getElementById('ci-term-input');
    const output = document.getElementById('ci-term-output');
    input.value = 'ls -la';

    await executeTerminalCmd();

    expect(postSpy).toHaveBeenCalledWith('/api/docker/containers/container123/exec', { cmd: 'ls -la' });
    expect(output.textContent).toContain('bin  etc  lib  root  usr  var');
  });

  it('fetches and renders app catalog cards with category filters', async () => {
    const mockCatalog = [
      {
        id: 'jellyfin',
        name: 'Jellyfin Media Server',
        category: 'media',
        description: 'Free, open-source media streaming system.',
        image: 'jellyfin/jellyfin:latest',
        default_port: 8096,
      },
      {
        id: 'vaultwarden',
        name: 'Vaultwarden',
        category: 'utilities',
        description: 'Lightweight password manager.',
        image: 'vaultwarden/server:latest',
        default_port: 8080,
      },
    ];

    vi.spyOn(api, 'get').mockResolvedValue(mockCatalog);

    await fetchAndRenderAppCatalog();

    const grid = document.getElementById('docker-catalog-grid');
    expect(grid).toBeTruthy();
    expect(grid.querySelectorAll('.catalog-app-card').length).toBe(2);
    expect(grid.textContent).toContain('Jellyfin Media Server');
    expect(grid.textContent).toContain('Vaultwarden');
    expect(grid.textContent).toContain(':8096');
  });
});
