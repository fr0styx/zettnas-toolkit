import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ current: '/mnt/user', dirs: [], roots: ['/mnt/user'] }),
    post: vi.fn().mockResolvedValue({ success: true }),
    postRaw: vi.fn().mockResolvedValue({ ok: true }),
  },
  auth: { getToken: vi.fn().mockReturnValue('') },
  ApiError: class ApiError extends Error {},
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

describe('explorer uploads', () => {
  it('sends small files the way the upload API expects (folder and name in the query, file as body)', async () => {
    const { FileManagerWindow, fsUploadUrl } = await import('../components/file-manager.js');
    const { api } = await import('../api.js');
    const fm = new FileManagerWindow('fm-test', 'fm-test', '/mnt/user/Photos');
    fm.loadPath = vi.fn();
    const file = new File(['hello'], 'holiday photo.jpg', { type: 'image/jpeg' });
    await fm.uploadFiles([file], '/mnt/user/Photos');
    expect(api.postRaw).toHaveBeenCalledWith('/api/fs/upload?path=%2Fmnt%2Fuser%2FPhotos&filename=holiday%20photo.jpg', file);
    expect(fsUploadUrl('/a b', 'c&d')).toBe('/api/fs/upload?path=%2Fa%20b&filename=c%26d');
  });

  it('api.postRaw exists in the real API client', async () => {
    const real = await vi.importActual('../api.js');
    expect(typeof real.api.postRaw).toBe('function');
  });
});
