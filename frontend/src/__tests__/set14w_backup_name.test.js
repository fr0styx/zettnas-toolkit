import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { openContainerInspector, switchContainerTab, _resetContainerModalForTesting } from '../components/container-modal.js';
import { api } from '../api.js';

beforeEach(() => {
  _resetContainerModalForTesting();
  vi.restoreAllMocks();
});
afterEach(() => _resetContainerModalForTesting());

describe('the Edit tab names the backup it keeps (SET-14, Apps 26)', () => {
  it('the app name is filled in', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.includes('/details')
        ? { cid: 'c1', overview: { id: 'c1', name: 'jellyfin', image: 'x:latest', state: 'running', running: true }, resources: {}, mounts: [], ports: [], networks: [], env: [] }
        : {}
    );
    await openContainerInspector('c1', 'jellyfin');
    await switchContainerTab('edit');
    const label = document.getElementById('cie-cb-backup')?.parentElement?.textContent || '';
    expect(label).toContain('jellyfin.backup');
    expect(label).not.toContain('{name}');
  });
});
