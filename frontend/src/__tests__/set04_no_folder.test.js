/** SET-04: with no folder chosen the page sends nothing. It used to send the whole pool. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  renderAiWatchedFoldersAndShares,
  syncAiWatchedFolders,
  runAiPathIndex,
} from '../components/management/ai.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const WORDS = 'Kib has no folder to read. Choose a folder first.';

describe('Kib with no folder chosen (SET-04)', () => {
  let post;
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <button id="btn-ai-run-index">Index</button><div id="ai-index-run-feedback"></div>
      <span id="ai-watched-dropdown-summary"></span><span id="ai-watched-dropdown-count-badge"></span>
      <div id="ai-discovered-shares-list"></div>`;
    vi.spyOn(api, 'get').mockResolvedValue({});
    post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'started' });
    renderAiWatchedFoldersAndShares([], []);
  });
  afterEach(() => vi.restoreAllMocks());

  it('"Sync" sends nothing and says why', async () => {
    await expect(syncAiWatchedFolders(true, true)).resolves.toBeNull();
    expect(post).not.toHaveBeenCalled();
    expect(document.getElementById('ai-index-run-feedback').textContent).toBe(WORDS);
    expect(showToast).toHaveBeenCalledWith(WORDS, 'warn');
  });

  it('"Index now" sends nothing, and the button stays as it was', async () => {
    await expect(runAiPathIndex()).resolves.toBeNull();
    await expect(runAiPathIndex('   ')).resolves.toBeNull();
    await expect(runAiPathIndex([])).resolves.toBeNull();
    expect(post).not.toHaveBeenCalled();
    const btn = document.getElementById('btn-ai-run-index');
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toBe('Index');
  });

  it('a folder that is named is still read', async () => {
    await runAiPathIndex('/mnt/user/docs');
    expect(post).toHaveBeenCalledWith('/api/media/index', expect.objectContaining({ path: '/mnt/user/docs', paths: ['/mnt/user/docs'] }));
  });

  it('the watched folders are read once one is chosen', async () => {
    renderAiWatchedFoldersAndShares(['/mnt/user/docs'], []);
    await syncAiWatchedFolders(true, true);
    expect(post).toHaveBeenCalledWith('/api/media/index', expect.objectContaining({ paths: ['/mnt/user/docs'] }));
  });
});
