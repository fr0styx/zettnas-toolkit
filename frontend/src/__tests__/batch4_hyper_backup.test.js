import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  fetchAndRenderBackupJobs,
  fetchAndRenderSystemSnapshots,
} from '../components/management.js';
import { api } from '../api.js';

describe('Batch 4: Hyper-Backup Orchestrator & Snapshot Manager UI', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.id = 'test-container';
    document.body.appendChild(container);
  });

  afterEach(() => {
    container?.remove();
    document.querySelectorAll('.smart-modal-backdrop').forEach((m) => m.remove());
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. Hyper-Backup Scheduled Jobs
  // =========================================================================

  it('renders empty state when no hyper-backup jobs are configured', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({ jobs: [] });
    const mount = document.createElement('div');
    container.appendChild(mount);

    await fetchAndRenderBackupJobs(mount);

    expect(mount.innerHTML).toContain('No Backup Pipelines Configured');
    expect(mount.innerHTML).toContain('Configure First Pipeline');
  });

  it('renders scheduled backup jobs table with pipeline badges and run/delete actions', async () => {
    const mockJobs = [
      {
        id: 'job-1',
        name: 'Daily Photo Offsite Sync',
        source_pool: 'default',
        source_subvolume: 'photos',
        destination_type: 'remote',
        remote_name: 'b2-vault',
        remote_path: 'backups/photos',
        schedule: 'daily',
        retention_count: 7,
        enabled: true,
        last_status: 'success',
        last_run_at: 1773000000,
      },
      {
        id: 'job-2',
        name: 'Local Hourly Snapshot',
        source_pool: 'default',
        source_subvolume: 'documents',
        destination_type: 'local_snapshot',
        remote_name: '',
        remote_path: '',
        schedule: 'hourly',
        retention_count: 24,
        enabled: true,
        last_status: 'running',
        last_run_at: null,
      },
    ];

    vi.spyOn(api, 'get').mockResolvedValueOnce({ jobs: mockJobs });
    const mount = document.createElement('div');
    container.appendChild(mount);

    await fetchAndRenderBackupJobs(mount);

    expect(mount.innerHTML).toContain('Daily Photo Offsite Sync');
    expect(mount.innerHTML).toContain('b2-vault:backups/photos');
    expect(mount.innerHTML).toContain('Local Hourly Snapshot');
    expect(mount.innerHTML).toContain('Local Snapshot');
    expect(mount.innerHTML).toContain('Keep 7');
    expect(mount.innerHTML).toContain('Keep 24');
    expect(mount.innerHTML).toContain('Success');
    expect(mount.innerHTML).toContain('Running...');

    const runButtons = mount.querySelectorAll('.btn-run-backup-job');
    const deleteButtons = mount.querySelectorAll('.btn-delete-backup-job');
    expect(runButtons.length).toBe(2);
    expect(deleteButtons.length).toBe(2);
  });

  it('triggers immediate execution when Run button is clicked', async () => {
    const mockJobs = [
      {
        id: 'job-99',
        name: 'Manual Sync Test',
        source_subvolume: 'shares',
        destination_type: 'local_snapshot',
        schedule: 'manual',
        retention_count: 5,
        last_status: 'idle',
      },
    ];

    vi.spyOn(api, 'get').mockResolvedValue({ jobs: mockJobs });
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });

    const mount = document.createElement('div');
    container.appendChild(mount);

    await fetchAndRenderBackupJobs(mount);

    const runBtn = mount.querySelector('.btn-run-backup-job');
    expect(runBtn).not.toBeNull();
    runBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/backup/schedule/job-99/run');
  });

  // =========================================================================
  // 2. Storage Pool Snapshots & Revert
  // =========================================================================

  it('renders active snapshots with Revert and Delete buttons', async () => {
    const mockSnaps = [
      {
        name: 'shares_20261009_120000',
        path: '/mnt/user/@snapshots/shares_20261009_120000',
        created_at: 1773000000,
        pool_id: 'default',
      },
      {
        name: 'documents_daily',
        path: '/mnt/user/@snapshots/documents_daily',
        created_at: 1773000100,
        pool_id: 'default',
      },
    ];

    vi.spyOn(api, 'get').mockResolvedValueOnce({ snapshots: mockSnaps });
    const mount = document.createElement('div');
    container.appendChild(mount);

    await fetchAndRenderSystemSnapshots(mount);

    expect(mount.innerHTML).toContain('shares_20261009_120000');
    expect(mount.innerHTML).toContain('documents_daily');

    const restoreButtons = mount.querySelectorAll('.btn-sys-restore-snap');
    const deleteButtons = mount.querySelectorAll('.btn-sys-delete-snap');
    expect(restoreButtons.length).toBe(2);
    expect(deleteButtons.length).toBe(2);
  });

  it('renders empty notice when no snapshots exist', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({ snapshots: [] });
    const mount = document.createElement('div');
    container.appendChild(mount);

    await fetchAndRenderSystemSnapshots(mount);

    expect(mount.innerHTML).toContain('No active filesystem snapshots found');
  });
});
