import { describe, it, expect, vi } from 'vitest';
import { FileManagerWindow } from '../components/file-manager.js';
import { api, ApiError } from '../api.js';

describe('a folder on a sleeping disk', () => {
  it('is not opened when waking is declined, and can be woken from the window', async () => {
    const fm = Object.create(FileManagerWindow.prototype);
    fm.list = document.createElement('div');
    fm.pathInput = document.createElement('input');
    fm.fileList = [{ name: 'x' }];
    const get = vi.spyOn(api, 'get').mockRejectedValueOnce(new ApiError('Cancelled', { status: 428, error: 'cancelled' }));
    await fm.loadPath('/mnt/user/vault');
    expect(fm.list.textContent).toContain("disk is asleep");
    expect(fm.pathInput.value).toBe('/mnt/user/vault');
    expect(fm.fileList).toEqual([]);
    get.mockRejectedValueOnce(new Error('stop'));
    fm.list.querySelector('button').click();
    expect(get).toHaveBeenLastCalledWith('/api/browse?path=%2Fmnt%2Fuser%2Fvault&dirs_only=0', expect.anything());
    get.mockRestore();
  });
});
