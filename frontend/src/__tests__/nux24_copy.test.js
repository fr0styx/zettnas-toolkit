import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));

import { showConfirmToast } from '../toast.js';
import { api } from '../api.js';
import { handlePendingUsb, resetUsbOffer } from '../components/usb-offer.js';
import { renderShareFolders } from '../components/share-folder-picker.js';

describe('smaller copy gaps (NUX-24)', () => {
  beforeEach(() => {
    showConfirmToast.mockClear();
    resetUsbOffer?.();
  });

  it('says where imported photos go', () => {
    handlePendingUsb({ path: '/mnt/disks/cam', name: 'cam', backups: [], media: true, import_dest: '/mnt/user/Photos/', ts: 77 });
    expect(showConfirmToast.mock.calls[0][1]).toContain('/mnt/user/Photos/');
  });

  it('opens Shares when there are none to pick', async () => {
    const mount = document.createElement('div');
    window.openManagementSection = vi.fn();
    api.get.mockResolvedValue({ folders: [{ key: 'media', label: 'Media library' }], shares: [] });
    await renderShareFolders(mount, 'jellyfin', () => {});
    const go = [...mount.querySelectorAll('button')].find((b) => b.textContent === 'Open Shares');
    go.click();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-storage-shares');
    delete window.openManagementSection;
  });
});
