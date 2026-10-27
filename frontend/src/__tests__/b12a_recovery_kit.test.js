import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { offerRecoveryKit, reposHtml } = await import('../components/offsite-backup.js');

describe('B12a (REL-17): the recovery kit must be saved', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:kit');
    globalThis.URL.revokeObjectURL = vi.fn();
  });

  it('downloading the full kit records it as saved', async () => {
    api.get.mockResolvedValue({ filename: 'zettnas-recovery-usb.txt', text: 'Recovery key: abc' });
    api.post.mockResolvedValue({});
    const onSaved = vi.fn();
    await offerRecoveryKit({ id: 'usb' }, onSaved);
    expect(api.get).toHaveBeenCalledWith('/api/offsite/repos/usb/kit');
    const [, , download] = toast.showConfirmToast.mock.calls[0];
    await download();
    expect(api.post).toHaveBeenCalledWith('/api/offsite/repos/usb/kit-saved', {});
    expect(onSaved).toHaveBeenCalled();
  });

  it('a backup whose kit was never saved says so', () => {
    const repo = { id: 'usb', name: 'USB', location: '/mnt/disks/usb', paths: ['/mnt/user/a'], keep: { daily: 7, weekly: 4, monthly: 12 }, initialized: true };
    expect(reposHtml({ available: true, repos: [repo] })).toContain('Recovery kit not saved');
    expect(reposHtml({ available: true, repos: [{ ...repo, kit_saved_at: 1 }] })).not.toContain('Recovery kit not saved');
  });
});
