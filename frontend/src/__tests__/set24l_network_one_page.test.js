import { describe, it, expect, vi, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const get = vi.fn((url) => Promise.resolve(url.includes('ports') ? { ports: [] } : { status: 'ok', summary: {}, interfaces: [], docker_networks: [] }));
vi.mock('../api.js', () => ({ api: { get, post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
const loadNasNameCard = vi.fn();
vi.mock('../components/management/nas-name.js', () => ({ loadNasNameCard }));

const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

describe('SET-24 l: Network is one page, Away from home its own', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = html;
  });

  it('Network has no tabs, only titled sections in the planned order', () => {
    const sec = /** @type {HTMLElement} */ (document.getElementById('mgmt-sec-network'));
    expect(sec.querySelector('.mgmt-inner-tab, .mgmt-sticky-subnav')).toBeNull();
    expect(sec.querySelectorAll('.mgmt-tab-pane').length).toBe(1);
    const titles = [...sec.querySelectorAll('.net-page-section h3')].map((h) => h.getAttribute('data-i18n'));
    expect(titles).toEqual(['net.home_title', 'net.ports_hw_title', 'net.wiring_title', 'net.answers_title']);
    for (const s of sec.querySelectorAll('.net-page-section')) {
      expect(document.getElementById(/** @type {string} */ (s.getAttribute('aria-labelledby')))).not.toBeNull();
    }
  });

  it('keeps every part the page code fills, and drops the Virtual Fleet tile', () => {
    for (const id of ['nas-name-card', 'net-home', 'net-port-rows', 'network-bridges-container', 'network-vlan-tbody', 'net-listening-ports-tbody', 'net-ports-search', 'btn-refresh-net-ports']) {
      expect(document.getElementById(id)?.closest('#mgmt-pane-network'), id).not.toBeNull();
    }
    for (const id of ['net-kpi-docker', 'net-kpi-ip', 'network-switch-faceplate', 'network-physical-tbody']) expect(document.getElementById(id), id).toBeNull(); // SET-24 m
    expect(html).not.toContain('mw.virtual_fleet');
  });

  it('Away from home is its own page, opened from its sidebar entry', () => {
    const away = /** @type {HTMLElement} */ (document.getElementById('mgmt-sec-away'));
    expect(away.classList.contains('mgmt-detail-card')).toBe(true);
    expect(away.querySelector('#mgmt-pane-network-wireguard')).not.toBeNull();
    expect(away.querySelector('#remote-access-mount')).not.toBeNull();
    const entry = document.querySelector('.mgmt-sidebar-item[data-route="away"]');
    expect(entry?.getAttribute('data-mgmt-target')).toBe('mgmt-sec-away');
    expect(entry?.getAttribute('data-mgmt-pane')).toBe('mgmt-pane-network-wireguard');
  });

  it('opening Network loads the layout, the name card and what answers together', async () => {
    const { loadNetworkPage } = await import('../components/management/network.js');
    loadNetworkPage();
    await vi.waitFor(() => expect(loadNasNameCard).toHaveBeenCalledTimes(1));
    expect(get).toHaveBeenCalledWith('/api/system/network-topology');
    expect(get).toHaveBeenCalledWith('/api/network/ports/listening');
  });

  it('old links to the Network tabs land on the right page', async () => {
    const { SUBPANE_MAP } = await import('../components/management.js');
    expect(SUBPANE_MAP['mgmt-pane-network-wireguard']).toEqual({ section: 'mgmt-sec-away', pane: 'mgmt-pane-network-wireguard' });
    expect(SUBPANE_MAP['mgmt-sec-away']).toEqual({ section: 'mgmt-sec-away', pane: 'mgmt-pane-network-wireguard' });
    expect(SUBPANE_MAP['mgmt-pane-network-ports']).toEqual({ section: 'mgmt-sec-network', pane: 'mgmt-pane-network' });
    expect(SUBPANE_MAP.ports).toEqual({ section: 'mgmt-sec-network', pane: 'mgmt-pane-network' });
    expect(SUBPANE_MAP['mgmt-pane-network-services']).toEqual({ section: 'mgmt-sec-network', pane: 'mgmt-pane-network' });
  });
});
