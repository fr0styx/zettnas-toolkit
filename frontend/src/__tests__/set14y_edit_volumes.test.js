import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { openContainerInspector, switchContainerTab, _resetContainerModalForTesting } from '../components/container-modal.js';
import { api } from '../api.js';

beforeEach(() => {
  _resetContainerModalForTesting();
  vi.restoreAllMocks();
});
afterEach(() => _resetContainerModalForTesting());

describe('the Edit form keeps a volume a volume (SET-14, Apps 26)', () => {
  it('a named volume shows its name, a folder its path', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.includes('/details')
        ? {
            cid: 'c1',
            overview: { id: 'c1', name: 'jellyfin', image: 'x:latest', state: 'running', running: true },
            resources: {},
            ports: [],
            networks: [],
            env: [],
            mounts: [
              { type: 'volume', name: 'jf-cache', source: '/var/lib/docker/volumes/jf-cache/_data', destination: '/cache', mode: 'z', rw: true },
              { type: 'bind', name: '', source: '/mnt/user/appdata/jellyfin', destination: '/config', mode: 'rw', rw: true },
            ],
          }
        : {}
    );
    await openContainerInspector('c1', 'jellyfin');
    await switchContainerTab('edit');
    const rows = [...document.querySelectorAll('.cie-mount-row')];
    expect(rows.map((r) => r.querySelector('.cie-src-input').value)).toEqual(['jf-cache', '/mnt/user/appdata/jellyfin']);
    expect(rows.map((r) => r.dataset.kind)).toEqual(['volume', 'bind']);
    expect(rows[0].textContent).toContain('Volume:');
    expect(rows[0].querySelector('.cie-mode-input').value).toBe('rw'); // "z" is not read-only
  });
});
