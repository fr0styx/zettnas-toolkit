import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchAndRenderNetworkShares } from '../components/chassis-visualizer.js';
import { api } from '../api.js';

const share = (name, own) => ({ name, comment: '', security: 'private', export_smb: true, mountpoint: `/mnt/${name}`, used_bytes: 5e11, free_bytes: 5e11, total_bytes: 1e12, used_pct: 50, usage_is_own: own });

beforeEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '<div id="mount"></div><span id="mgmt-shares-platform-badge"></span>';
});

describe('a usage bar only where the figure is the folder\'s own (SET-14, Shares 12)', () => {
  it('own figures get a bar, pool figures only the pool\'s free space', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('shares')) return { shares: [share('own', true), share('pooled', false)], is_observer_mode: false };
      if (url.includes('platform')) return { platform: 'generic_linux', capabilities: { can_manage_shares: true } };
      return {};
    });
    const mount = document.getElementById('mount');
    await fetchAndRenderNetworkShares(mount);
    const cards = [...mount.querySelectorAll('.share-card, [data-share]')];
    const text = mount.textContent;
    expect(text).toContain('free on its pool');
    expect(mount.querySelectorAll('.share-progress-fill').length).toBe(1);
    expect(cards.length === 0 || cards.length === 2).toBe(true);
  });
});
