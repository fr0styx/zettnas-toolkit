import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
vi.mock('../components/offsite-backup.js', () => ({ renderOffsite: vi.fn(), offerRecoveryKit: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const offsite = await import('../components/offsite-backup.js');
const { migrateJob, fetchAndRenderBackupJobs } = await import('../components/management/backup.js');

describe('B12b (REL-9): a copy job moves to an off-site backup', () => {
  beforeEach(() => vi.clearAllMocks());

  it('asks first, moves it and offers the recovery kit', async () => {
    api.post.mockResolvedValue({ status: 'migrated', repo: { id: 'from-j1' } });
    const done = vi.fn();
    migrateJob('j1', done);
    expect(api.post).not.toHaveBeenCalled();
    const [, , onOk] = toast.showConfirmToast.mock.calls[0];
    await onOk();
    expect(api.post).toHaveBeenCalledWith('/api/backup/schedule/j1/migrate', {});
    expect(done).toHaveBeenCalled();
    expect(offsite.offerRecoveryKit).toHaveBeenCalledWith({ id: 'from-j1' });
  });

  it('offers the move only on cloud copies of folders, and shows a skipped run', async () => {
    const mount = document.createElement('div');
    api.get.mockResolvedValue({ jobs: [
      { id: 'j1', name: 'Photos', kind: 'data', destination_type: 'remote', remote_name: 'cloud', last_status: 'skipped', last_error: 'frozen' },
      { id: 'j2', name: 'Settings', kind: 'config', destination_type: 'remote', remote_name: 'cloud' },
      { id: 'j3', name: 'Moved', kind: 'data', destination_type: 'remote', migrated_to: 'from-j3' },
    ] });
    await fetchAndRenderBackupJobs(mount);
    expect([...mount.querySelectorAll('.btn-migrate-backup-job')].map((b) => b.dataset.jobId)).toEqual(['j1']);
    expect(mount.querySelector('.backup-skipped').textContent).toBe('Skipped');
  });
});
