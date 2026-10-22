import { describe, it, expect } from 'vitest';
import { filterCatalog, catalogChipsHtml, catalogCardHtml, isInstalled, imageRepo } from '../components/catalog-view.js';

const apps = [
  { id: 'caddy', name: 'Caddy', category: 'network', description: 'Reverse proxy with automatic HTTPS', image: 'caddy:2', tags: ['letsencrypt'], default_port: 80 },
  { id: 'npm', name: 'Nginx Proxy Manager', category: 'network', description: 'Reverse proxy with a web UI', image: 'jc21/nginx-proxy-manager:latest', default_port: 81 },
  { id: 'immich', name: 'Immich', category: 'photos', description: 'Photo backup', image: 'ghcr.io/immich-app/immich-server:release', type: 'stack', default_port: 2283 },
  { id: 'x', name: 'Community app', category: 'utilities', description: 'From a source', image: 'foo/bar:1', source_name: 'Community', security_rating: 'review_required', default_port: 1 },
];

describe('catalog view', () => {
  it('searches every word across name, description, image, tags and category', () => {
    expect(filterCatalog(apps, 'all', 'reverse proxy').map((a) => a.id)).toEqual(['caddy', 'npm']);
    expect(filterCatalog(apps, 'all', 'letsencrypt').map((a) => a.id)).toEqual(['caddy']);
    expect(filterCatalog(apps, 'all', 'network security').map((a) => a.id)).toEqual(['caddy', 'npm']);
    expect(filterCatalog(apps, 'photos', '').map((a) => a.id)).toEqual(['immich']);
  });

  it('builds chips only for categories that have apps, with counts', () => {
    const div = document.createElement('div');
    div.innerHTML = catalogChipsHtml(apps, 'network', 'catalog-filter-btn', 'catalog-all-count');
    const chips = [...div.querySelectorAll('button')].map((b) => [b.dataset.cat, b.textContent, b.classList.contains('active')]);
    expect(chips).toEqual([
      ['all', 'All Apps4', false],
      ['photos', 'Photos1', false],
      ['network', 'Network & Security2', true],
      ['utilities', 'Utilities1', false],
    ]);
    expect(div.querySelector('#catalog-all-count').textContent).toBe('4');
  });

  it('marks installed apps by image, ignoring tags and registry defaults', () => {
    expect(imageRepo('docker.io/library/caddy:2.8')).toBe('caddy');
    expect(isInstalled(apps[0], [{ image: 'caddy:latest' }])).toBe(true);
    expect(isInstalled(apps[1], [{ image: 'caddy:latest' }])).toBe(false);
    const div = document.createElement('div');
    div.innerHTML = catalogCardHtml(apps[0], { installed: true });
    expect(div.querySelector('.catalog-app-card').classList.contains('is-installed')).toBe(true);
    expect(div.querySelector('.btn-deploy-app').dataset.appid).toBe('caddy');
    expect(div.textContent).toContain('Install again');
  });

  it('labels stacks, built-in and community templates', () => {
    const div = document.createElement('div');
    div.innerHTML = catalogCardHtml(apps[2]) + catalogCardHtml(apps[3]);
    const [immich, community] = div.querySelectorAll('.catalog-app-card');
    expect(immich.textContent).toContain('Stack');
    expect(immich.textContent).toContain('Built-in');
    expect(community.textContent).toContain('Community');
    expect(community.textContent).toContain('Review');
    expect(community.textContent).not.toContain('Built-in');
  });
});
