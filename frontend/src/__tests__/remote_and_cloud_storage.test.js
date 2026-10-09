import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  fetchAndRenderRemoteStorage,
  openWebdavConfigModal,
  openNewCloudRemoteModal,
} from '../components/chassis-visualizer.js';
import { ZettEventBus } from '../event-bus.js';
import { api } from '../api.js';

describe('Sprint 4: Remote & Cloud Storage Subsystem (Frontend)', () => {
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

  it('renders WebDAV server card with operational indicator and quick connect commands', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/webdav/status') {
        return Promise.resolve({
          enabled: true,
          running: true,
          pid: 14205,
          port: 8084,
          root_path: '/mnt/user',
          read_only: false,
          username: 'admin',
          auth_enabled: true,
          direct_url: 'http://10.40.30.249:8084/',
          proxy_url: '/webdav/',
          quick_connect: {
            macos: "open 'http://admin@10.40.30.249:8084/'",
            windows: "net use Z: http://10.40.30.249:8084/ /user:admin",
            ios: "http://10.40.30.249:8084/",
            linux: "gio mount dav://admin@10.40.30.249:8084/",
          },
        });
      }
      if (url === '/api/remotes') {
        return Promise.resolve([]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    await fetchAndRenderRemoteStorage(container);

    expect(container.textContent).toContain('Universal WebDAV File Server');
    expect(container.textContent).toContain('RUNNING (PID: 14205)');
    expect(container.textContent).toContain('8084');
    expect(container.textContent).toContain('/mnt/user');
    expect(container.textContent).toContain('macOS Finder');
    expect(container.textContent).toContain('Windows Map Network Drive');
    expect(container.textContent).toContain('No Cloud Remotes Connected');
  });

  it('renders connected cloud remotes with mount badges and file explorer button', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/webdav/status') {
        return Promise.resolve({
          enabled: true,
          running: false,
          port: 8084,
          root_path: '/mnt/user',
          read_only: false,
          username: 'admin',
          auth_enabled: true,
          quick_connect: {},
        });
      }
      if (url === '/api/remotes') {
        return Promise.resolve([
          {
            name: 'google-drive-photos',
            type: 'drive',
            is_mounted: true,
            mount_path: '/mnt/remotes/google-drive-photos',
            parameters: { scope: 'drive.readonly' },
          },
          {
            name: 'backup-s3',
            type: 's3',
            is_mounted: false,
            mount_path: '/mnt/remotes/backup-s3',
            parameters: { provider: 'AWS', region: 'us-east-1' },
          },
        ]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    const eventSpy = vi.fn();
    ZettEventBus.on('window:open', eventSpy);

    await fetchAndRenderRemoteStorage(container);

    expect(container.textContent).toContain('google-drive-photos');
    expect(container.textContent).toContain('Mounted at /mnt/remotes/google-drive-photos');
    expect(container.textContent).toContain('backup-s3');
    expect(container.textContent).toContain('Not Mounted');

    // Clicking "Open in File Explorer" triggers ZettEventBus
    const revealBtn = container.querySelector('.btn-remote-reveal');
    expect(revealBtn).not.toBeNull();
    revealBtn.click();

    expect(eventSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'file-manager-window',
        path: '/mnt/remotes/google-drive-photos',
      }),
      expect.anything()
    );
  });

  it('supports mounting and unmounting remote storage via API', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/webdav/status') {
        return Promise.resolve({ enabled: true, running: true, port: 8084 });
      }
      if (url === '/api/remotes') {
        return Promise.resolve([
          {
            name: 'my-b2-bucket',
            type: 'b2',
            is_mounted: false,
            mount_path: '/mnt/remotes/my-b2-bucket',
          },
        ]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'mounted' });

    await fetchAndRenderRemoteStorage(container);

    const mountBtn = container.querySelector('.btn-remote-mount');
    expect(mountBtn).not.toBeNull();
    mountBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/remotes/my-b2-bucket/mount', {});
  });

  it('populates and submits WebDAV configuration modal', async () => {
    // Setup modal markup
    const modalHtml = `
      <div id="modal-webdav-config" class="smart-modal-backdrop" style="display: none;">
        <form id="webdav-config-form">
          <input type="number" id="webdav-cfg-port" />
          <input type="text" id="webdav-cfg-root" />
          <input type="text" id="webdav-cfg-user" />
          <input type="password" id="webdav-cfg-pass" />
          <input type="checkbox" id="webdav-cfg-auth-toggle" />
          <input type="checkbox" id="webdav-cfg-readonly-toggle" />
          <button id="modal-webdav-close-btn" type="button"></button>
          <button id="modal-webdav-cancel-btn" type="button"></button>
          <button type="submit">Save</button>
        </form>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });
    const successCb = vi.fn();

    openWebdavConfigModal(
      {
        port: 8084,
        root_path: '/mnt/user',
        username: 'admin',
        auth_enabled: true,
        read_only: false,
      },
      successCb
    );

    const modal = document.getElementById('modal-webdav-config');
    expect(modal.style.display).toBe('flex');

    const portInput = document.getElementById('webdav-cfg-port');
    expect(portInput.value).toBe('8084');
    portInput.value = '9090';

    const form = document.getElementById('webdav-config-form');
    form.dispatchEvent(new Event('submit'));

    await new Promise((r) => setTimeout(r, 20));

    expect(postSpy).toHaveBeenCalledWith(
      '/api/webdav/config',
      expect.objectContaining({
        port: 9090,
        root_path: '/mnt/user',
        username: 'admin',
      })
    );
    expect(successCb).toHaveBeenCalled();
    expect(modal.style.display).toBe('none');
  });
});
