import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchAndRenderAppBackups } from '../components/management.js';
import { openContainerDeleteModal } from '../components/container-modal.js';
import { api } from '../api.js';

describe('Application Backups & Recovery UI (21a, 21b, 21c)', () => {
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
  // 1. fetchAndRenderAppBackups
  // =========================================================================

  it('renders empty state when no application backups exist', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({ backups: [] });
    const mount = document.createElement('div');
    container.appendChild(mount);

    await fetchAndRenderAppBackups(mount);

    expect(mount.innerHTML).toContain('No Application Backups Found');
    expect(mount.innerHTML).toContain('Backups are automatically created');
  });

  it('renders application backups table with uninstall and on-demand badges, file details, and action buttons', async () => {
    const mockBackups = [
      {
        id: 'app_uptimekuma_20261010_120000',
        container_name: 'uptime-kuma',
        container_id: 'c1234567890a',
        image: 'louislam/uptime-kuma:latest',
        stack: 'monitoring',
        reason: 'uninstall',
        archive_file: 'app_uptimekuma_20261010_120000.tar.gz',
        archive_size_formatted: '15.4 MB',
        mounts_count: 1,
        created_at_epoch: 1791650000,
      },
      {
        id: 'app_plex_20261010_130000',
        container_name: 'plex',
        container_id: 'c9876543210b',
        image: 'linuxserver/plex:latest',
        stack: '',
        reason: 'on_demand',
        archive_file: 'app_plex_20261010_130000.tar.gz',
        archive_size_formatted: '2.1 MB',
        mounts_count: 2,
        created_at_epoch: 1791653600,
      },
    ];

    vi.spyOn(api, 'get').mockResolvedValueOnce({ backups: mockBackups });
    const mount = document.createElement('div');
    container.appendChild(mount);

    // Also create the filter select
    const filterSelect = document.createElement('select');
    filterSelect.id = 'app-backups-filter-app';
    container.appendChild(filterSelect);

    await fetchAndRenderAppBackups(mount);

    // Verify table contents
    expect(mount.innerHTML).toContain('uptime-kuma');
    expect(mount.innerHTML).toContain('monitoring');
    expect(mount.innerHTML).toContain('Auto-Archive (Uninstall)');
    expect(mount.innerHTML).toContain('15.4 MB');

    expect(mount.innerHTML).toContain('plex');
    expect(mount.innerHTML).toContain('On-Demand');
    expect(mount.innerHTML).toContain('2.1 MB');

    // Verify action buttons
    const downloadBtns = mount.querySelectorAll('.btn-download-app-backup');
    const restoreBtns = mount.querySelectorAll('.btn-restore-app-backup');
    const deleteBtns = mount.querySelectorAll('.btn-delete-app-backup');
    expect(downloadBtns.length).toBe(2);
    expect(restoreBtns.length).toBe(2);
    expect(deleteBtns.length).toBe(2);

    // Verify filter select options
    expect(filterSelect.innerHTML).toContain('All Applications (Box-Wide)');
    expect(filterSelect.innerHTML).toContain('uptime-kuma');
    expect(filterSelect.innerHTML).toContain('plex');
  });

  it('triggers downloadBlob when download button is clicked', async () => {
    const mockBackups = [
      {
        id: 'app_test_123',
        container_name: 'test-app',
        archive_file: 'app_test_123.tar.gz',
        reason: 'on_demand',
      },
    ];

    vi.spyOn(api, 'get').mockResolvedValueOnce({ backups: mockBackups });
    const downloadSpy = vi.spyOn(api, 'downloadBlob').mockResolvedValueOnce('app_test_123.tar.gz');

    const mount = document.createElement('div');
    container.appendChild(mount);
    await fetchAndRenderAppBackups(mount);

    const btn = mount.querySelector('.btn-download-app-backup');
    expect(btn).not.toBeNull();
    btn.click();

    expect(downloadSpy).toHaveBeenCalledWith('/api/backup/apps/app_test_123/download', 'app_test_123.tar.gz');
  });

  // =========================================================================
  // 2. openContainerDeleteModal archive checkbox (Requirement 21a)
  // =========================================================================

  it('renders archive checkbox in container destroy modal and sends archive_data: true by default', async () => {
    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValueOnce({
      success: true,
      container_id: 'cid123',
      archived: true,
      archive: { id: 'app_test_archive' },
    });

    const onDeleted = vi.fn();
    openContainerDeleteModal('cid123', 'my-test-container', 'test:latest', onDeleted);

    const modal = document.getElementById('container-delete-modal-overlay');
    expect(modal).not.toBeNull();

    // Verify archive checkbox is present and checked by default
    const archiveCheckbox = document.getElementById('cdm-archive');
    expect(archiveCheckbox).not.toBeNull();
    expect(archiveCheckbox.checked).toBe(true);

    // Click confirm destroy
    const confirmBtn = document.getElementById('cdm-confirm-btn');
    expect(confirmBtn).not.toBeNull();
    confirmBtn.click();

    // Verify API called with archive_data=true
    expect(deleteSpy).toHaveBeenCalledWith(
      expect.stringContaining('archive_data=true')
    );
  });

  it('sends archive_data: false when archive checkbox is unchecked in destroy modal', async () => {
    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValueOnce({
      success: true,
      container_id: 'cid456',
      archived: false,
    });

    openContainerDeleteModal('cid456', 'unwanted-app', 'test:latest');

    const archiveCheckbox = document.getElementById('cdm-archive');
    archiveCheckbox.checked = false;

    const confirmBtn = document.getElementById('cdm-confirm-btn');
    confirmBtn.click();

    expect(deleteSpy).toHaveBeenCalledWith(
      expect.stringContaining('archive_data=false')
    );
  });
});
