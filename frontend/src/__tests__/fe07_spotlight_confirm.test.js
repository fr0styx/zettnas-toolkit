import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiDelete = vi.fn();
const apiPost = vi.fn();
const confirms = [];
const toasts = [];

vi.mock('../api.js', () => ({ api: { delete: (...a) => apiDelete(...a), post: (...a) => apiPost(...a), get: vi.fn() } }));
vi.mock('../toast.js', () => ({
  showToast: (msg, type) => toasts.push({ msg, type }),
  showConfirmToast: (title, msg, onConfirm, onCancel) => confirms.push({ title, onConfirm, onCancel }),
}));

const { parseNaturalLanguageAction } = await import('../components/spotlight.js');

describe('FE-07: destructive Spotlight actions', () => {
  beforeEach(() => {
    apiDelete.mockReset();
    apiPost.mockReset();
    confirms.length = 0;
    toasts.length = 0;
  });

  it('asks before emptying the trash and does nothing on cancel', async () => {
    const action = parseNaturalLanguageAction('>trash empty');
    const done = action.run();
    expect(apiDelete).not.toHaveBeenCalled();
    expect(confirms).toHaveLength(1);
    confirms[0].onCancel();
    await done;
    expect(apiDelete).not.toHaveBeenCalled();
  });

  it('reports a failed empty as an error, not a success', async () => {
    apiDelete.mockRejectedValue(new Error('boom'));
    const done = parseNaturalLanguageAction('>trash empty').run();
    await confirms[0].onConfirm();
    await done;
    expect(apiDelete).toHaveBeenCalledWith('/api/fs/trash/empty', { confirmed: true });
    expect(toasts.map((t) => t.type)).toEqual(['error']);
  });

  it('asks before stopping a container', async () => {
    apiPost.mockResolvedValue({});
    const done = parseNaturalLanguageAction('>isolate container web').run();
    expect(apiPost).not.toHaveBeenCalled();
    await confirms[0].onConfirm();
    await done;
    expect(apiPost).toHaveBeenCalledWith('/api/docker/containers/web/stop');
  });
});
