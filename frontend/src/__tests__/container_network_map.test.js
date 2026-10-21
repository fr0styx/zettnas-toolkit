import { describe, it, expect, vi, beforeEach } from 'vitest';
import { layoutNetworkMap, renderNetworkMapSvg, openNetworkMap } from '../components/container-network-map.js';
import { api } from '../api.js';

vi.mock('../api.js', () => ({
  api: { get: vi.fn() },
  auth: { hasToken: vi.fn().mockReturnValue(true) },
}));

const TOPO = {
  networks: [
    { name: 'arr_default', driver: 'bridge', subnet: '172.20.0.0/16', gateway: '172.20.0.1', container_count: 2 },
    { name: 'bridge', driver: 'bridge', subnet: '172.17.0.0/16', container_count: 2 },
    { name: 'empty_net', driver: 'bridge', container_count: 0 },
  ],
  containers: [
    { name: 'zz-bridge-only', state: 'exited', networks: [{ network: 'bridge', ip: '172.17.0.4' }], ports: [] },
    { name: 'sonarr', state: 'running', networks: [{ network: 'arr_default', ip: '172.20.0.3' }], ports: [{ public: 8989, private: 8989, type: 'tcp' }] },
    { name: 'gluetun', state: 'running', networks: [{ network: 'arr_default', ip: '172.20.0.2' }, { network: 'bridge', ip: '172.17.0.2' }], ports: [] },
    { name: 'qbit', state: 'running', networks: [], shares_with: 'gluetun', ports: [] },
  ],
};

describe('Container network map', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('orders containers by their first network and links shared stacks', () => {
    const layout = layoutNetworkMap(TOPO);
    expect(layout.containers.map((c) => c.name)).toEqual(['gluetun', 'sonarr', 'qbit', 'zz-bridge-only']);
    const netEdges = layout.edges.filter((e) => e.kind === 'net');
    expect(netEdges).toHaveLength(4);
    expect(netEdges.find((e) => e.container === 'gluetun' && e.network === 'bridge').ip).toBe('172.17.0.2');
    expect(layout.edges.filter((e) => e.kind === 'shares')).toEqual([
      expect.objectContaining({ container: 'qbit', target: 'gluetun' }),
    ]);
    // every node fits inside the drawing
    for (const n of [...layout.networks, ...layout.containers]) {
      expect(n.y).toBeGreaterThan(0);
      expect(n.y).toBeLessThan(layout.height);
    }
  });

  it('copes with an empty or malformed topology', () => {
    expect(layoutNetworkMap(null)).toMatchObject({ networks: [], containers: [], edges: [] });
  });

  it('escapes names in the SVG', () => {
    const svg = renderNetworkMapSvg(
      layoutNetworkMap({ networks: [{ name: '<img onerror=x>', container_count: 1 }], containers: [{ name: '"><script>', networks: [{ network: '<img onerror=x>', ip: '1.2.3.4' }] }] })
    );
    expect(svg).not.toContain('<img');
    expect(svg).not.toContain('<script>');
  });

  it('opens, renders the map, and highlights a network on click', async () => {
    api.get.mockResolvedValue(TOPO);
    await openNetworkMap();
    const overlay = document.getElementById('netmap-overlay');
    expect(overlay.style.display).toBe('flex');
    expect(api.get).toHaveBeenCalledWith('/api/docker/networks/topology');
    expect(overlay.querySelectorAll('.nm-net')).toHaveLength(3);
    expect(overlay.querySelectorAll('.nm-ctr')).toHaveLength(4);
    expect(overlay.querySelector('#netmap-summary').textContent).toBe('3 networks · 4 containers');

    overlay.querySelector('.nm-net[data-net="bridge"] rect').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    const bridgeEdge = overlay.querySelector('.nm-edge[data-net="bridge"]');
    const arrEdge = overlay.querySelector('.nm-edge[data-net="arr_default"]');
    expect(Number(bridgeEdge.getAttribute('opacity'))).toBeGreaterThan(0.5);
    expect(Number(arrEdge.getAttribute('opacity'))).toBeLessThan(0.2);
    expect(overlay.querySelector('.nm-ctr[data-ctr="sonarr"]').getAttribute('opacity')).toBe('0.35');
    expect(overlay.querySelector('.nm-ctr[data-ctr="gluetun"]').getAttribute('opacity')).toBe('1');
  });

  it('shows an error when the topology cannot be loaded', async () => {
    api.get.mockRejectedValue(new Error('503'));
    await openNetworkMap();
    expect(document.querySelector('#netmap-overlay .netmap-error')).not.toBeNull();
  });
});
