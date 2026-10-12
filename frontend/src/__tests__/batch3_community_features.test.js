import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initFileManager,
  openFileManager,
} from '../components/file-manager.js';
import {
  fetchAndRenderStorageTopology,
} from '../components/chassis-visualizer.js';
import { api } from '../api.js';

describe('Batch 3 Community Features Suite', () => {
  let container;

  beforeEach(() => {
    window._fmInitialized = false;
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    window._fmInitialized = false;
    container?.remove();
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  describe('Feature 1: High-Contrast File Explorer Row Highlights & Checkbox Multi-Select', () => {
    it('renders master checkbox in header and individual row checkboxes', async () => {
      // Mock API responses for File Manager
      vi.spyOn(api, 'get').mockImplementation((url) => {
        if (url.startsWith('/api/browse')) {
          return Promise.resolve({
            current: '/mnt/user',
            roots: ['/mnt/user'],
            dirs: [
              { name: '..', is_dir: true, path: '/mnt', size: 0 },
              { name: 'backup_archive.tar.gz', is_dir: false, path: '/mnt/user/backup_archive.tar.gz', size: 1073741824 },
              { name: 'photos', is_dir: true, path: '/mnt/user/photos', size: 4096 },
              { name: 'document.pdf', is_dir: false, path: '/mnt/user/document.pdf', size: 5242880 },
            ],
          });
        }
        return Promise.reject(new Error(`Unknown url: ${url}`));
      });

      initFileManager();
      openFileManager('/mnt/user');

      // Wait for rendering
      await vi.waitFor(() => {
        const headerChk = document.getElementById('fm-select-all-checkbox');
        expect(headerChk).not.toBeNull();
        const rowCheckboxes = document.querySelectorAll('.fm-row-checkbox');
        expect(rowCheckboxes.length).toBe(3);
      });

      const headerChk = document.getElementById('fm-select-all-checkbox');
      expect(headerChk).not.toBeNull();

      const rowCheckboxes = document.querySelectorAll('.fm-row-checkbox');

      // Test individual checkbox click selects item and updates selection bar
      const fileChk = document.querySelector('.fm-row-checkbox[data-path*="backup_archive"]');
      expect(fileChk).not.toBeNull();
      fileChk.click();

      const selBar = document.getElementById('fm-selection-bar');
      expect(selBar.style.display).not.toBe('none');

      const countSpan = document.getElementById('fm-selected-count');
      expect(countSpan.textContent).toContain('1 selected');
      expect(countSpan.textContent).toContain('1 GB');

      // Master checkbox should now be indeterminate
      expect(headerChk.indeterminate).toBe(true);

      // Select another item
      const folderChk = document.querySelector('.fm-row-checkbox[data-path*="photos"]');
      expect(folderChk).not.toBeNull();
      folderChk.click();
      expect(countSpan.textContent).toContain('2 selected');

      // Test master checkbox select-all
      headerChk.click();
      expect(headerChk.checked).toBe(true);
      expect(countSpan.textContent).toContain('3 selected');

      // Selection toolbar action shortcuts exist
      const moveBtn = document.getElementById('fm-bulk-move-btn');
      expect(moveBtn).not.toBeNull();
      expect(moveBtn.textContent).toContain('Move To...');

      const zipBtn = document.getElementById('fm-bulk-zip-btn');
      expect(zipBtn).not.toBeNull();
      expect(zipBtn.textContent).toContain('Download');
    });
  });

  describe('Feature 2: External JBOD USB/TB Storage Pool Lifecycle (Export & Import)', () => {
    it('renders Safely Eject button for detachable pools and triggers export API', async () => {
      vi.spyOn(api, 'get').mockImplementation((url) => {
        if (url === '/api/storage/pools') {
          return Promise.resolve({
            platform: 'generic_linux',
            is_observer_mode: false,
            pools: [
              {
                id: 'ext_das_pool',
                name: 'ext_das_pool',
                fs_type: 'zfs',
                fs_profile: 'raidz1',
                status: 'HEALTHY',
                used_bytes: 500000,
                total_bytes: 1000000,
                free_bytes: 500000,
                used_pct: 50,
                members: [
                  { name: 'sda', device: 'sda', role: 'data', size_bytes: 500000, status: 'OK' },
                ],
              },
            ],
          });
        }
        if (url === '/api/storage/platform') {
          return Promise.resolve({
            platform: 'generic_linux',
            capabilities: { can_create_pools: true, can_export_pools: true },
          });
        }
        if (url === '/api/storage/pools/discover') {
          return Promise.resolve({ discovered_pools: [] });
        }
        return Promise.reject(new Error(`Unknown url: ${url}`));
      });

      const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
        status: 'exported',
        message: 'Pool safely exported.',
        safe_to_disconnect: true,
      });

      // Mock window.confirm
      vi.spyOn(window, 'confirm').mockReturnValue(true);

      await fetchAndRenderStorageTopology(container);

      const ejectBtn = container.querySelector('.btn-pool-export');
      expect(ejectBtn).not.toBeNull();
      expect(ejectBtn.textContent).toContain('Safely Eject');

      ejectBtn.click();

      await vi.waitFor(() => {
        expect(postSpy).toHaveBeenCalledWith('/api/storage/pools/ext_das_pool/export', { force: false });
      });
    });

    it('renders external pool discovery banner with Import Pool action', async () => {
      vi.spyOn(api, 'get').mockImplementation((url) => {
        if (url === '/api/storage/pools') {
          return Promise.resolve({
            platform: 'generic_linux',
            is_observer_mode: false,
            pools: [],
          });
        }
        if (url === '/api/storage/platform') {
          return Promise.resolve({
            platform: 'generic_linux',
            capabilities: { can_create_pools: true },
          });
        }
        if (url === '/api/storage/pools/discover') {
          return Promise.resolve({
            discovered_pools: [
              {
                pool_id: 'usb_backup_vault',
                fs_type: 'zfs',
                status: 'ONLINE',
                detachable: true,
              },
            ],
          });
        }
        return Promise.reject(new Error(`Unknown url: ${url}`));
      });

      const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
        status: 'imported',
        pool_id: 'usb_backup_vault',
      });

      await fetchAndRenderStorageTopology(container);

      const banner = container.querySelector('.external-pools-banner');
      expect(banner).not.toBeNull();
      expect(banner.textContent).toContain('External Storage Pool Detected:');
      expect(banner.textContent).toContain('usb_backup_vault');

      const importBtn = banner.querySelector('.btn-import-external-pool');
      expect(importBtn).not.toBeNull();
      expect(importBtn.textContent).toContain('Import Pool');

      importBtn.click();

      await vi.waitFor(() => {
        expect(postSpy).toHaveBeenCalledWith('/api/storage/pools/import', {
          pool_id: 'usb_backup_vault',
          fs_type: 'zfs',
        });
      });
    });
  });
});
