import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { forgetAiFolder, renderAiWatchedFoldersAndShares } from '../components/management.js';

describe('forget folder (AI-20)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('posts the folder and drops it from the watched list', async () => {
    document.body.innerHTML = '<div id="ai-watched-folders-list"></div>';
    renderAiWatchedFoldersAndShares(['/mnt/user/a', '/mnt/user/b'], []);
    expect(document.querySelectorAll('.btn-ai-forget-folder').length).toBe(2);
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', removed: { files: 3 } });
    await forgetAiFolder('/mnt/user/a');
    expect(post).toHaveBeenCalledWith('/api/ai/index/forget', { path: '/mnt/user/a' });
    const left = [...document.querySelectorAll('.ai-watched-folder-chip')].map((el) => el.dataset.folderPath);
    expect(left).toEqual(['/mnt/user/b']);
  });
});
