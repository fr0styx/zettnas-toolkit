import { describe, it, expect, vi, beforeEach } from 'vitest';
import { executeTransferWithConflictCheck, showCollisionModal } from '../components/file-manager.js';
import { api } from '../api.js';

vi.mock('../api.js', () => ({
  api: {
    post: vi.fn(),
    get: vi.fn(),
  },
  auth: {
    getToken: vi.fn().mockReturnValue('test-token'),
  },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
}));

describe('File Manager Merge & DnD Parity', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('prevents dropping a folder into itself or its own subfolder', async () => {
    const { showToast } = await import('../toast.js');
    await executeTransferWithConflictCheck(['/mnt/user/downloads'], '/mnt/user/downloads/subfolder', 'move');

    expect(showToast).toHaveBeenCalledWith(
      expect.stringContaining('Cannot move an item into itself'),
      'warning'
    );
    expect(api.post).not.toHaveBeenCalled();
  });

  it('performs direct transfer when no conflicts exist', async () => {
    api.post.mockImplementation((url) => {
      if (url === '/api/fs/conflict-check') {
        return Promise.resolve({ has_conflict: false, conflicts: [] });
      }
      if (url === '/api/fs/transfer') {
        return Promise.resolve({ status: 'ok', transferred: 2 });
      }
      return Promise.resolve({});
    });

    await executeTransferWithConflictCheck(['/mnt/user/a.txt', '/mnt/user/b.txt'], '/mnt/user/destination', 'copy');

    expect(api.post).toHaveBeenCalledWith('/api/fs/conflict-check', {
      sources: ['/mnt/user/a.txt', '/mnt/user/b.txt'],
      destination_dir: '/mnt/user/destination',
    });
    expect(api.post).toHaveBeenCalledWith('/api/fs/transfer', {
      sources: ['/mnt/user/a.txt', '/mnt/user/b.txt'],
      destination_dir: '/mnt/user/destination',
      action: 'copy',
      collision_policy: 'merge',
    });
  });

  it('renders collision modal with Merge option when a directory conflicts', () => {
    showCollisionModal({
      sources: ['/mnt/user/photos'],
      destinationDir: '/mnt/user/backup',
      action: 'move',
      conflicts: [
        {
          name: 'photos',
          is_dir: true,
          source: '/mnt/user/photos',
          destination: '/mnt/user/backup/photos',
        },
      ],
    });

    const modal = document.getElementById('modal-fm-collision');
    expect(modal).not.toBeNull();
    expect(modal.classList.contains('open')).toBe(true);
    expect(modal.querySelector('#fm-collision-merge')).not.toBeNull();
    expect(modal.querySelector('#fm-collision-overwrite')).not.toBeNull();
    expect(modal.querySelector('#fm-collision-skip')).not.toBeNull();
  });

  it('renders collision modal with Keep Both option when only files conflict', () => {
    showCollisionModal({
      sources: ['/mnt/user/notes.txt'],
      destinationDir: '/mnt/user/docs',
      action: 'copy',
      conflicts: [
        {
          name: 'notes.txt',
          is_dir: false,
          dest_size: 1024,
          source: '/mnt/user/notes.txt',
          destination: '/mnt/user/docs/notes.txt',
        },
      ],
    });

    const modal = document.getElementById('modal-fm-collision');
    expect(modal).not.toBeNull();
    expect(modal.querySelector('#fm-collision-keep-both')).not.toBeNull();
  });

  it('triggers transfer with selected policy upon button click', async () => {
    api.post.mockResolvedValue({ status: 'ok', transferred: 1 });
    const onResolved = vi.fn();

    showCollisionModal({
      sources: ['/mnt/user/folderA'],
      destinationDir: '/mnt/user/folderB',
      action: 'move',
      conflicts: [{ name: 'folderA', is_dir: true }],
      onResolved,
    });

    const btnMerge = document.getElementById('fm-collision-merge');
    expect(btnMerge).not.toBeNull();
    btnMerge.click();

    // Allow promise tick
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/fs/transfer', {
        sources: ['/mnt/user/folderA'],
        destination_dir: '/mnt/user/folderB',
        action: 'move',
        collision_policy: 'merge',
      });
    });
  });
});
