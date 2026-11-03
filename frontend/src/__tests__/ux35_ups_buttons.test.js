/** UX-35: the UPS drawer's Refresh and Test Connection buttons get their icon from the markup. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { initUpsDrawerControls } from '../components/management/ups.js';
import { api } from '../api.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const byId = (id) => document.getElementById(id);
const icon = (el) => el.querySelector('span[aria-hidden="true"]')?.textContent;

describe('UPS drawer buttons (UX-35)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<button id="btn-refresh-ups"></button><button id="btn-ups-test-conn"></button>';
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('Refresh comes back with its icon after refreshing', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    await initUpsDrawerControls();
    byId('btn-refresh-ups').click();
    await vi.waitFor(() => expect(byId('btn-refresh-ups').disabled).toBe(false));
    expect(byId('btn-refresh-ups').textContent).toBe('🔄 Refresh');
    expect(icon(byId('btn-refresh-ups'))).toBe('🔄');
  });

  it('Test Connection resets to its label after success, failure and an error', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    const post = vi.spyOn(api, 'post');
    await initUpsDrawerControls();
    vi.useFakeTimers();
    const btn = byId('btn-ups-test-conn');
    for (const outcome of [{ connected: true, model: 'X' }, { connected: false, error: 'down' }, new Error('boom')]) {
      if (outcome instanceof Error) post.mockRejectedValueOnce(outcome);
      else post.mockResolvedValueOnce(outcome);
      btn.click();
      await vi.advanceTimersByTimeAsync(50);
      expect(btn.textContent).not.toBe('🔌 Test Connection');
      await vi.advanceTimersByTimeAsync(3000);
      expect(btn.textContent).toBe('🔌 Test Connection');
      expect(icon(btn)).toBe('🔌');
    }
  });
});
