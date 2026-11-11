/** SET-04: the status timer of the Kib page stops when nobody is looking at the page. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { updateAiSyncProgressUi } from '../components/management/ai.js';
import { api } from '../api.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

describe('the status timer of the Kib page (SET-04)', () => {
  let get;
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <div id="management-modal-overlay" style="display: flex;">
        <div id="mgmt-sec-ai" style="display: block;"><span id="ai-standby-guard-text"></span></div>
      </div>`;
    get = vi.spyOn(api, 'get').mockResolvedValue({ sync_progress: { state: 'running' } });
  });
  afterEach(() => {
    updateAiSyncProgressUi({ state: 'idle' });
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  const asks = () => get.mock.calls.filter((c) => c[0] === '/api/media/status').length;

  it('asks while reading runs and the page is open', async () => {
    updateAiSyncProgressUi({ state: 'running' });
    await vi.advanceTimersByTimeAsync(3100);
    expect(asks()).toBe(2);
  });

  it('stops once Settings is closed, and does not start again by itself', async () => {
    updateAiSyncProgressUi({ state: 'running' });
    document.getElementById('management-modal-overlay').style.display = 'none';
    await vi.advanceTimersByTimeAsync(9000);
    expect(asks()).toBe(0);
  });

  it('stops when another section of Settings is opened', async () => {
    updateAiSyncProgressUi({ state: 'running' });
    await vi.advanceTimersByTimeAsync(1600);
    expect(asks()).toBe(1);
    document.getElementById('mgmt-sec-ai').style.display = 'none';
    await vi.advanceTimersByTimeAsync(9000);
    expect(asks()).toBe(1);
  });
});
