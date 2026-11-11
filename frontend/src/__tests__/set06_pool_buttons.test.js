/** SET-06: a pool's check is asked first, says what the server answered, and is offered only where the platform can do it. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchAndRenderStorageTopology } from '../components/chassis-visualizer.js';
import { api } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
}));

const pool = { id: 'sdc1', name: 'media', pool_type: 'btrfs_raid', fs_type: 'btrfs', mountpoint: '/mnt/pools/media', members: [], total_bytes: 10, used_bytes: 1 };

async function draw(flags = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/api/storage/pools') return Promise.resolve({ platform: 'generic_linux', is_observer_mode: false, pools: [pool], ...flags });
    if (url === '/api/storage/platform') return Promise.resolve({ platform: 'generic_linux', capabilities: { is_observer_mode: false } });
    return Promise.resolve({});
  });
  await fetchAndRenderStorageTopology(container);
  return container;
}

describe('a pool’s check (SET-06)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('is offered where the platform can check, and not where it cannot', async () => {
    expect((await draw({ can_trigger_scrub: true })).querySelector('.btn-pool-scrub')).not.toBeNull();
    expect((await draw({ can_trigger_scrub: false })).querySelector('.btn-pool-scrub')).toBeNull();
    expect((await draw()).querySelector('.btn-pool-scrub')).not.toBeNull(); // an older server says nothing: as before
  });

  it('is asked first, by the pool’s name, and nothing is sent until the answer', async () => {
    const container = await draw({ can_trigger_scrub: true });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'started' });
    container.querySelector('.btn-pool-scrub').click();
    expect(post).not.toHaveBeenCalled();
    const [title, msg, yes, , options] = showConfirmToast.mock.calls[0];
    expect(title).toBe('Check this pool for errors');
    expect(msg).toContain('Check “media” for errors now?');
    expect(msg).toContain('can take hours');
    expect(options).toEqual({ okText: 'Start the check', destructive: false });
    await yes();
    expect(post).toHaveBeenCalledWith('/api/storage/scrub', { pool_id: 'sdc1', action: 'start' });
    expect(showToast).toHaveBeenCalledWith('The check of “media” was started.', 'info');
  });

  it('says why when the check was not started', async () => {
    const container = await draw({ can_trigger_scrub: true });
    vi.spyOn(api, 'post').mockRejectedValue(new Error('media is ext4, which has no check of its own. Nothing was started.'));
    container.querySelector('.btn-pool-scrub').click();
    await showConfirmToast.mock.calls[0][2]();
    expect(showToast).toHaveBeenCalledWith('The check of “media” was not started: media is ext4, which has no check of its own. Nothing was started.', 'error');
  });
});
