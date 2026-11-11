// SET-09: a part of the Storage page that could not be read says so, and "Refresh" speaks after
// the answer. Looking for pools on other drives is a button, not something every opening does.
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { refreshAndSay, showReadError } from '../components/refresh-say.js';
import { fetchAndRenderChassisTwin, fetchAndRenderStorageTopology, foundPoolsHtml, lookForPools } from '../components/chassis-visualizer.js';

const POOLS = { pools: [{ id: 'tank', name: 'tank', fs_type: 'zfs', status: 'HEALTHY', members: [] }] };

describe('Refresh speaks after the answer', () => {
  beforeEach(() => vi.clearAllMocks());

  it('says "refreshed" only once the data is there', async () => {
    let done;
    const run = vi.fn(() => new Promise((resolve) => { done = resolve; }));
    const said = refreshAndSay(run, 'Drive bays refreshed.');
    await Promise.resolve();
    expect(showToast).not.toHaveBeenCalled();
    done(true);
    expect(await said).toBe(true);
    expect(showToast).toHaveBeenCalledWith('Drive bays refreshed.', 'info');
  });

  it('says when it could not refresh: a false answer or an error', async () => {
    expect(await refreshAndSay(async () => false, 'ok')).toBe(false);
    expect(showToast).toHaveBeenLastCalledWith('Could not refresh. What you see may be out of date.', 'error');
    expect(await refreshAndSay(async () => { throw new Error('x'); }, 'ok', 'Not this time.')).toBe(false);
    expect(showToast).toHaveBeenLastCalledWith('Not this time.', 'error');
  });

  it('draws "could not be read" with a Try again button that retries', () => {
    const box = document.createElement('div');
    const retry = vi.fn();
    showReadError(box, 'The drive bays could not be read.', retry);
    expect(box.querySelector('[role="alert"]').textContent).toContain('The drive bays could not be read.');
    box.querySelector('[data-try-again]').click();
    expect(retry).toHaveBeenCalledTimes(1);
  });
});

describe('no invented picture, no scan on opening', () => {
  beforeEach(() => vi.clearAllMocks());

  it('the bay picture says so when it could not be read, instead of drawing a guess', async () => {
    vi.spyOn(api, 'request').mockRejectedValue(new Error('offline'));
    const box = document.createElement('div');
    expect(await fetchAndRenderChassisTwin(box)).toBe(false);
    expect(box.textContent).toContain('The drive bays could not be read.');
    expect(box.querySelector('.chassis-bay, .bay-slot')).toBeNull();
  });

  it('the pools are read without looking at every drive, and a failure is said', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/storage/pools') return POOLS;
      if (url === '/api/storage/platform') return { capabilities: {}, can_look_for_pools: false };
      throw new Error(`unexpected ${url}`);
    });
    const box = document.createElement('div');
    expect(await fetchAndRenderStorageTopology(box)).toBe(true);
    expect(get.mock.calls.map((c) => c[0])).not.toContain('/api/storage/pools/discover');
    expect(box.querySelector('[data-look-for-pools]')).toBeNull(); // not offered where it cannot work

    get.mockRejectedValue(new Error('offline'));
    expect(await fetchAndRenderStorageTopology(box)).toBe(false);
    expect(box.textContent).toContain('The storage pools could not be read.');
    expect(box.textContent).not.toContain('PARITY');
  });

  it('says when there is no pool, and offers the look for pools only where the server allows it', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/storage/pools' ? { pools: [] } : { capabilities: {}, can_look_for_pools: true }));
    const box = document.createElement('div');
    await fetchAndRenderStorageTopology(box);
    expect(box.textContent).toContain('No storage pool was found here.');
    expect(box.querySelector('[data-look-for-pools]')).not.toBeNull();
  });

  it('looking for pools shows what was found once, or says that nothing was', async () => {
    const box = document.createElement('div');
    box.innerHTML = '<div class="external-pools-banner">old</div>';
    const get = vi.spyOn(api, 'get').mockResolvedValue({ discovered_pools: [{ pool_id: 'backup<1>', fs_type: 'zfs', status: 'ONLINE' }] });
    await lookForPools(box, null);
    expect(get).toHaveBeenCalledWith('/api/storage/pools/discover');
    expect(box.querySelectorAll('.external-pools-banner')).toHaveLength(1); // they piled up, one per Refresh
    expect(box.querySelector('.btn-import-external-pool').dataset.poolId).toBe('backup<1>');
    expect(box.innerHTML).not.toContain('backup<1>'); // escaped

    get.mockResolvedValue({ discovered_pools: [] });
    await lookForPools(box, null);
    expect(box.querySelectorAll('.external-pools-banner')).toHaveLength(0);
    expect(showToast).toHaveBeenLastCalledWith('No other pool was found.', 'info');

    get.mockRejectedValue(new Error('refused'));
    await lookForPools(box, null);
    expect(showToast).toHaveBeenLastCalledWith('Could not look for pools: refused', 'error');
    expect(foundPoolsHtml(null)).toBe('');
  });
});
