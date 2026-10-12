import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  fetchAndRenderRemoteStorage,
  fetchAndRenderNetworkShares,
  openSftpUsersModal,
  buildSftpCardHtml,
} from '../components/chassis-visualizer.js';
import { api } from '../api.js';

describe('Feature 4: Inbound SFTP Subsystem Card & User Management', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    container?.remove();
    document.querySelectorAll('.smart-modal-backdrop').forEach((m) => m.remove());
    vi.restoreAllMocks();
  });

  it('buildSftpCardHtml produces complete glassmorphic SFTP card with telemetry and quick connect items', () => {
    const html = buildSftpCardHtml(
      { running: true, port: 2222 },
      2,
      'alice'
    );

    expect(html).toContain('Inbound SFTP Subsystem');
    expect(html).toContain('RUNNING (Port 2222)');
    expect(html).toContain('Stop SFTP');
    expect(html).toContain('Manage Users (2)');
    expect(html).toContain('Line-Rate Port: <strong style="color:#fff;">2222</strong>');
    expect(html).toContain('internal-sftp');
    expect(html).toContain('Chroot Jail (/home/%u)');
    expect(html).toContain('Prohibited (No PTY)');
    expect(html).toContain('sftp://alice@');
    expect(html).toContain('sftp -P 2222 alice@');
    expect(html).toContain('sshfs -p 2222 alice@');
  });

  it('renders Inbound SFTP card in Remote & Cloud Storage subtab', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/webdav/status') {
        return Promise.resolve({
          enabled: true,
          running: true,
          port: 8084,
          root_path: '/mnt/user',
          read_only: false,
          username: 'admin',
          auth_enabled: true,
          quick_connect: {},
        });
      }
      if (url === '/api/remotes') {
        return Promise.resolve([]);
      }
      if (url === '/api/sftp/status') {
        return Promise.resolve({
          running: true,
          port: 2222,
          mode: 'host_sshd',
        });
      }
      if (url === '/api/sftp/users') {
        return Promise.resolve([
          { username: 'backups', read_only: false, home_dir: '/home/backups' },
        ]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    await fetchAndRenderRemoteStorage(container);

    const sftpCard = container.querySelector('#mgmt-sftp-subsystem-card');
    expect(sftpCard).not.toBeNull();
    expect(sftpCard.textContent).toContain('Inbound SFTP Subsystem');
    expect(sftpCard.textContent).toContain('RUNNING (Port 2222)');
    expect(sftpCard.textContent).toContain('Manage Users (1)');
    expect(sftpCard.textContent).toContain('sftp://backups@');
  });

  it('renders Inbound SFTP card in Network Shares subtab', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/storage/shares') {
        return Promise.resolve({
          shares: [
            {
              name: 'media',
              mountpoint: '/mnt/user/media',
              used_bytes: 1000,
              total_bytes: 5000,
              free_bytes: 4000,
              used_pct: 20,
              security: 'public',
              export_smb: true,
              export_nfs: false,
            },
          ],
          is_observer_mode: false,
          platform: 'generic_linux',
        });
      }
      if (url === '/api/storage/platform') {
        return Promise.resolve({
          platform: 'generic_linux',
          capabilities: { can_manage_shares: true },
        });
      }
      if (url === '/api/sftp/status') {
        return Promise.resolve({
          running: false,
          port: 2222,
          mode: 'disabled',
        });
      }
      if (url === '/api/sftp/users') {
        return Promise.resolve([]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    await fetchAndRenderNetworkShares(container);

    const sftpCard = container.querySelector('#mgmt-sftp-subsystem-card');
    expect(sftpCard).not.toBeNull();
    expect(sftpCard.textContent).toContain('Inbound SFTP Subsystem');
    expect(sftpCard.textContent).toContain('STOPPED');
    expect(sftpCard.textContent).toContain('Start SFTP');
    expect(sftpCard.textContent).toContain('Manage Users (0)');
  });

  it('opens and populates SFTP Users modal with direct array payload', async () => {
    // Inject modal into DOM
    document.body.innerHTML += `
      <div id="modal-sftp-users" class="smart-modal-backdrop" style="display: none;">
        <div class="smart-modal-window">
          <div class="smart-modal-header"></div>
          <button id="modal-sftp-close-btn"></button>
          <button id="modal-sftp-close-bottom-btn"></button>
          <div id="sftp-status-text"></div>
          <button id="btn-sftp-toggle-service"></button>
          <span id="sftp-quick-connect-hint"></span>
          <button id="btn-copy-sftp-cmd"></button>
          <div id="sftp-users-list"></div>
          <form id="sftp-add-user-form">
            <input id="sftp-new-username" />
            <input id="sftp-new-password" />
            <input type="checkbox" id="sftp-new-readonly" />
            <button type="submit">Create</button>
          </form>
        </div>
      </div>
    `;

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/sftp/status') {
        return Promise.resolve({ running: true, port: 2222 });
      }
      if (url === '/api/sftp/users') {
        return Promise.resolve([
          { username: 'chroot_alice', read_only: true, home_dir: '/home/chroot_alice' },
          { username: 'sync_bob', read_only: false, home_dir: '/home/sync_bob' },
        ]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    const refreshCb = vi.fn();
    await openSftpUsersModal(refreshCb);

    const modal = document.getElementById('modal-sftp-users');
    expect(modal.style.display).toBe('flex');

    const usersList = document.getElementById('sftp-users-list');
    expect(usersList.textContent).toContain('chroot_alice');
    expect(usersList.textContent).toContain('Read-Only');
    expect(usersList.textContent).toContain('sync_bob');
    expect(usersList.textContent).toContain('Read/Write');

    const hint = document.getElementById('sftp-quick-connect-hint');
    expect(hint.textContent).toContain('sftp -P 2222 chroot_alice@');
  });

  it('triggers SFTP toggle API call from server card toggle button', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/webdav/status') return Promise.resolve({ running: false, port: 8084 });
      if (url === '/api/remotes') return Promise.resolve([]);
      if (url === '/api/sftp/status') return Promise.resolve({ running: false, port: 2222 });
      if (url === '/api/sftp/users') return Promise.resolve([]);
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ running: true, port: 2222 });

    await fetchAndRenderRemoteStorage(container);

    const toggleBtn = container.querySelector('#btn-sftp-header-toggle');
    expect(toggleBtn).not.toBeNull();
    expect(toggleBtn.textContent).toContain('Start SFTP');

    toggleBtn.click();

    await vi.waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith('/api/sftp/toggle', { enabled: true });
    });
  });
});
