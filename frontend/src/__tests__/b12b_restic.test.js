import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { reposHtml, renderOffsite } = await import('../components/offsite-backup.js');

const repo = {
  id: 'usb',
  name: 'USB',
  location: '/mnt/user/backups',
  paths: ['/mnt/user/a'],
  keep: { daily: 7, weekly: 4, monthly: 12 },
  initialized: true,
  kit_saved_at: 1,
  same_disk: true,
  last_unreadable: 2,
};

describe('B12b (REL-16): off-site backups say what to watch', () => {
  beforeEach(() => vi.clearAllMocks());

  it('flags a backup on the same storage and files it could not read', () => {
    const html = reposHtml({ available: true, repos: [repo] });
    expect(html).toContain('Same storage as the folders it protects');
    expect(html).toContain('2 files could not be read');
    const fine = reposHtml({ available: true, repos: [{ ...repo, same_disk: false, last_unreadable: 0 }] });
    expect(fine).not.toContain('Same storage');
    expect(fine).not.toContain('could not be read');
  });

  it('Back up now starts a job and says where to follow it', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/offsite' ? { available: true, repos: [repo] } : { shares: [] }));
    api.post.mockResolvedValue({ status: 'started', job: 'job:1' });
    const mount = document.createElement('div');
    document.body.appendChild(mount);
    await renderOffsite(mount);
    mount.querySelector('[data-off="backup"]').click();
    await vi.waitFor(() => expect(toast.showToast).toHaveBeenCalledWith('Backup started; it shows in Jobs.', 'info'));
    expect(api.post).toHaveBeenCalledWith('/api/offsite/repos/usb/backup', {});
  });
});
