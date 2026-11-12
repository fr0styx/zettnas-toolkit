import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { publicAppsHtml, loadPublicAppsCard } = await import('../components/management/public-apps.js');

const tick = () => new Promise((r) => setTimeout(r, 0));
const APPS = [
  { name: 'immich_server', ports: [2283], controls_server: false },
  { name: 'dozzle', ports: [9999], controls_server: true },
];
const BASE = { tailscale: true, published: [], free_ports: [10000], apps: APPS };

describe('apps from anywhere (RES-6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="network-services-grid"><div id="pl-card"></div></div>';
  });

  it('says what it needs and what is published', () => {
    expect(publicAppsHtml({ ...BASE, tailscale: false })).toContain('Needs Tailscale');
    expect(publicAppsHtml(BASE)).toContain('No app is on the internet');
    expect(publicAppsHtml({ ...BASE, apps: [] })).toContain('No running app');
    const pub = { name: 'immich_server', funnel_port: 10000, url: 'https://a.ts.net:10000', live: true, controls_server: true };
    const html = publicAppsHtml({ ...BASE, published: [pub], free_ports: [] });
    expect(html).toContain('https://a.ts.net:10000');
    expect(html).toContain('controls the server');
    expect(html).toContain('Every port Funnel can use');
    expect(publicAppsHtml({ ...BASE, published: [{ ...pub, live: false, controls_server: false }] })).toContain('Starting');
    expect(publicAppsHtml({ ...BASE, published: [{ ...pub, approval_url: 'https://login.tailscale.com/f/funnel' }] })).toContain('Allow Funnel');
  });

  it('warns for apps that control the server, publishes and takes off', async () => {
    api.get.mockResolvedValue(BASE);
    await loadPublicAppsCard();
    const card = document.getElementById('pa-card');
    expect(document.getElementById('pl-card').nextElementSibling).toBe(card);
    const select = /** @type {HTMLSelectElement} */ (card.querySelector('select[name="app"]'));
    const warn = /** @type {HTMLElement} */ (card.querySelector('[data-pa-warn]'));
    expect(warn.hidden).toBe(true);
    select.value = 'dozzle|9999';
    select.dispatchEvent(new Event('change'));
    expect(warn.hidden).toBe(false);
    const published = { ...BASE, published: [{ name: 'dozzle', funnel_port: 10000, url: 'https://a.ts.net:10000', live: true }], free_ports: [] };
    api.post.mockResolvedValue(published);
    card.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    expect(api.post).toHaveBeenCalledWith('/api/network/public-apps', { name: 'dozzle', host_port: 9999, funnel_port: 10000 });
    api.delete.mockResolvedValue(BASE);
    card.querySelector('[data-pa-stop]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(api.delete).toHaveBeenCalledWith('/api/network/public-apps/10000');
  });

  it('shows errors, but not the confirmation step', async () => {
    api.get.mockResolvedValue(BASE);
    await loadPublicAppsCard();
    const card = document.getElementById('pa-card');
    api.post.mockRejectedValueOnce(Object.assign(new Error('confirm'), { status: 428 }));
    card.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    expect(toast.showToast).not.toHaveBeenCalled();
    api.post.mockRejectedValueOnce(new Error('Tailscale refused'));
    card.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('Tailscale refused', 'error');
    api.get.mockRejectedValueOnce(new Error('offline'));
    await loadPublicAppsCard();
    expect(document.getElementById('pa-body').textContent).toBe('offline');
  });

  it('does nothing without the services grid', async () => {
    document.body.innerHTML = '';
    await loadPublicAppsCard();
    expect(api.get).not.toHaveBeenCalled();
  });

  it('goes on Away from home when that grid is there (SET-24)', async () => {
    document.body.innerHTML = '<div id="away-cards-grid"></div><div id="network-services-grid"></div>';
    await loadPublicAppsCard();
    expect(document.getElementById('pa-card').parentElement.id).toBe('away-cards-grid');
  });
});
