/** ARC-26: opening the app store at a search (Spotlight, Getting started) and the port-taken note. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { presetCatalogSearch, renderAppCatalogGrid, portTakenHtml } from '../components/management/docker.js';

describe('app store search preset', () => {
  afterEach(() => vi.useRealTimers());

  it('waits for the store tab to be wired, then opens it with the search', () => {
    vi.useFakeTimers();
    document.body.innerHTML = '<input id="catalog-search-input"><button id="docker-inner-tab-catalog"></button><div id="docker-catalog-grid"></div>';
    const tab = document.getElementById('docker-inner-tab-catalog');
    const clicks = vi.fn();
    tab.addEventListener('click', clicks);
    presetCatalogSearch('Jellyfin', 5);
    expect(document.getElementById('catalog-search-input').value).toBe('Jellyfin');
    expect(clicks).not.toHaveBeenCalled();
    tab.dataset.bound = '1';
    vi.advanceTimersByTime(100);
    expect(clicks).toHaveBeenCalledTimes(1);
    expect(document.getElementById('docker-catalog-grid').textContent).toBe('No apps match your search.');
  });

  it('gives up after its tries, and copes without the search box', () => {
    vi.useFakeTimers();
    document.body.innerHTML = '';
    presetCatalogSearch(null, 2);
    vi.advanceTimersByTime(1000);
    expect(() => renderAppCatalogGrid()).not.toThrow();
  });

  it('says which app holds the port, and opens the Advanced section', () => {
    document.body.innerHTML = '<details id="adm-advanced"></details>';
    expect(portTakenHtml(8096, 8097, 'Emby')).toContain('Port 8096 is already used by Emby, so this app uses port 8097.');
    expect(document.getElementById('adm-advanced').open).toBe(true);
    expect(portTakenHtml(80, 81)).toContain('Port 80 is already in use, so this app uses port 81.');
  });
});
