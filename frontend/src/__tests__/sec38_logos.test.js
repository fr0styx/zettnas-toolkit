/** SEC-38: catalog logos come through ZettNAS, never straight from a third party. */
import { describe, it, expect } from 'vitest';
import { catalogCardHtml, logoSrc } from '../components/catalog-view.js';

describe('catalog logos (SEC-38)', () => {
  it('sends logos from the web through ZettNAS', () => {
    const url = 'https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/jellyfin.png';
    expect(logoSrc(url)).toBe(`/api/docker/catalog/logo?url=${encodeURIComponent(url)}`);
    expect(logoSrc('/static/img/x.png')).toBe('/static/img/x.png');
    expect(logoSrc('')).toBe('');
    const html = catalogCardHtml({ id: 'a', name: 'A', category: 'media', logo: url });
    expect(html).not.toContain('src="https://');
    expect(html).toContain('/api/docker/catalog/logo?url=');
  });
});
