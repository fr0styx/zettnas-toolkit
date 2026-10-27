import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { rollbackShare } = await import('../components/snapshot-browser.js');

describe('B12a (FEAT-02): roll a share back to a snapshot', () => {
  beforeEach(() => vi.clearAllMocks());

  it('asks the server, which asks to confirm, and names the safety snapshot', async () => {
    api.post.mockResolvedValue({ safety_snapshot: 'photos@before-rollback-20261027-2200' });
    const after = vi.fn();
    await rollbackShare('photos@auto-20261027-1000', after);
    expect(api.post).toHaveBeenCalledWith('/api/snapshots/photos%40auto-20261027-1000/rollback', {});
    expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('photos@before-rollback-20261027-2200'), 'success');
    expect(after).toHaveBeenCalled();
  });

  it('a cancelled confirmation says nothing', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('cancelled'), { error: 'cancelled' }));
    await rollbackShare('photos@auto-1');
    expect(toast.showToast).not.toHaveBeenCalled();
  });
});
