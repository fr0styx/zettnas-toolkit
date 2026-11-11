/** SET-04: a sleep switch the server refused goes back, so "Sync" cannot run with it. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { initAiKnowledgeEngine } from '../components/management/ai.js';
import { confirmTextFor } from '../confirm-text.js';
import { api, ApiError } from '../api.js';
import { showToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('the sleep switch on the Kib page (SET-04)', () => {
  let box;
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<input type="checkbox" id="ai-index-respect-standby" checked />';
    vi.spyOn(api, 'get').mockResolvedValue({});
    initAiKnowledgeEngine();
    box = document.getElementById('ai-index-respect-standby');
  });
  afterEach(() => vi.restoreAllMocks());

  const untick = async () => {
    box.checked = false;
    box.dispatchEvent(new Event('change'));
    await flush();
    await flush();
  };

  it('goes back when the server refuses, and says why', async () => {
    vi.spyOn(api, 'put').mockRejectedValue(new Error('Reading folders on sleeping drives needs an administrator.'));
    await untick();
    expect(box.checked).toBe(true);
    expect(showToast).toHaveBeenCalledTimes(1);
    expect(showToast.mock.calls[0][1]).toBe('error');
  });

  it('goes back, with no error, when the question is answered with No', async () => {
    vi.spyOn(api, 'put').mockRejectedValue(new ApiError('Cancelled', { status: 428, error: 'cancelled' }));
    await untick();
    expect(box.checked).toBe(true);
    expect(showToast).not.toHaveBeenCalled();
  });

  it('stays off once the server took it', async () => {
    vi.spyOn(api, 'put').mockResolvedValue({ respect_standby: false });
    await untick();
    expect(box.checked).toBe(false);
    expect(showToast.mock.calls.at(-1)[1]).toBe('info');
  });

  it('the question is in plain words', () => {
    const text = confirmTextFor({ action: 'ai.read_sleeping', target: 'settings' });
    expect(JSON.stringify(text)).toContain('Let Kib read folders on sleeping drives?');
  });
});
