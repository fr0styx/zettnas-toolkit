import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  fetchAndRenderRemoteStorage,
  openWebdavConfigModal,
  openNewCloudRemoteModal,
} from '../components/chassis-visualizer.js';
import { ZettEventBus } from '../event-bus.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

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

  it('handles openNewCloudRemoteModal window controls, textarea tokens, and connection test', async () => {
    // Setup modal markup matching index.html
    const modalHtml = `
      <div id="modal-new-cloud-remote" class="smart-modal-backdrop os-window-overlay" style="display: none;">
        <div class="smart-modal-window os-window cloud-remote-window" id="cloud-remote-window">
          <div class="smart-modal-header" id="cloud-remote-window-header">
            <span id="modal-remote-title">Connect Remote</span>
            <div class="os-window-controls">
              <button class="win-btn min-btn" id="modal-remote-min-btn"></button>
              <button class="win-btn max-btn" id="modal-remote-max-btn"></button>
              <button class="win-btn close-btn" id="modal-remote-close-btn"></button>
            </div>
          </div>
          <form id="new-remote-form">
            <select id="new-remote-provider-select"></select>
            <div id="new-remote-provider-desc"></div>
            <input type="text" id="new-remote-name" />
            <div id="new-remote-dynamic-fields"></div>
            <input type="checkbox" id="new-remote-auto-mount" checked />
            <div id="new-remote-test-result" style="display: none;"></div>
            <div id="new-remote-error-box" style="display: none;"></div>
            <button type="button" id="modal-remote-cancel-btn"></button>
            <button type="button" id="new-remote-test-btn">Test</button>
            <button type="submit" id="new-remote-submit-btn">Save</button>
          </form>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/remotes/providers') {
        return Promise.resolve([
          {
            type: 'onedrive',
            name: 'Microsoft OneDrive & SharePoint',
            category: 'Cloud Drives',
            authorize_cmd: 'rclone authorize "onedrive"',
            fields: [
              { name: 'token', label: 'OAuth2 Token', type: 'textarea', required: true, help: 'Authorize help' },
              { name: 'drive_type', label: 'Drive Type', type: 'select', options: ['personal', 'business'] },
              { name: 'drive_id', label: 'Drive ID', type: 'text' }
            ]
          }
        ]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    const postSpy = vi.spyOn(api, 'post').mockImplementation((url) => {
      if (url === '/api/remotes/test') {
        return Promise.resolve({ success: true, item_count: 5, items_sample: ['file.txt'] });
      }
      if (url === '/api/remotes') {
        return Promise.resolve({ status: 'ok', name: 'my-onedrive', type: 'onedrive' });
      }
      if (url === '/api/remotes/my-onedrive/mount') {
        return Promise.resolve({ status: 'mounted' });
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    const successCb = vi.fn();
    await openNewCloudRemoteModal(successCb);

    const winEl = document.getElementById('cloud-remote-window');
    expect(winEl).not.toBeNull();

    // Verify textarea rendered for token
    const textarea = document.querySelector('#new-remote-dynamic-fields textarea[name="token"]');
    expect(textarea).not.toBeNull();

    // Verify copy button for authorize_cmd rendered
    const copyBtn = document.querySelector('.remote-copy-cmd-btn');
    expect(copyBtn).not.toBeNull();
    expect(copyBtn.getAttribute('data-cmd')).toBe('rclone authorize "onedrive"');

    // Test maximize toggle
    const maxBtn = document.getElementById('modal-remote-max-btn');
    maxBtn.click();
    expect(winEl.dataset.maximized).toBe('true');
    maxBtn.click();
    expect(winEl.dataset.maximized).toBe('false');

    // Test "Test Connection" button
    const testBtn = document.getElementById('new-remote-test-btn');
    textarea.value = '{"access_token":"mock"}';
    testBtn.click();
    await new Promise((r) => setTimeout(r, 20));

    expect(postSpy).toHaveBeenCalledWith('/api/remotes/test', expect.objectContaining({ type: 'onedrive' }));
    const testResult = document.getElementById('new-remote-test-result');
    expect(testResult.textContent).toContain('Connection Verified');

    // Test form submit
    const nameInput = document.getElementById('new-remote-name');
    nameInput.value = 'my-onedrive';
    const form = document.getElementById('new-remote-form');
    form.dispatchEvent(new Event('submit'));
    await new Promise((r) => setTimeout(r, 20));

    expect(postSpy).toHaveBeenCalledWith('/api/remotes', expect.objectContaining({
      name: 'my-onedrive',
      type: 'onedrive',
      parameters: expect.objectContaining({ token: '{"access_token":"mock"}' })
    }));
    expect(postSpy).toHaveBeenCalledWith('/api/remotes/my-onedrive/mount', {});
    expect(successCb).toHaveBeenCalled();
  });

  it('renders In-App Cloud OAuth & QR Code Assistant and exchanges code for token', async () => {
    const modalHtml = `
      <div id="modal-new-cloud-remote" class="smart-modal-backdrop os-window-overlay" style="display: none;">
        <div class="smart-modal-window os-window cloud-remote-window" id="cloud-remote-window">
          <div class="smart-modal-header" id="cloud-remote-window-header">
            <span id="modal-remote-title">Connect Remote</span>
            <div class="os-window-controls">
              <button class="win-btn close-btn" id="modal-remote-close-btn"></button>
            </div>
          </div>
          <form id="new-remote-form">
            <select id="new-remote-provider-select"></select>
            <div id="new-remote-provider-desc"></div>
            <input type="text" id="new-remote-name" />
            <div id="new-remote-dynamic-fields"></div>
            <input type="checkbox" id="new-remote-auto-mount" checked />
            <button type="submit" id="new-remote-submit-btn">Save</button>
          </form>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/remotes/providers') {
        return Promise.resolve([
          {
            type: 'onedrive',
            name: 'Microsoft OneDrive & SharePoint',
            category: 'Cloud Drives',
            authorize_cmd: 'rclone authorize "onedrive"',
            fields: [
              { name: 'token', label: 'OAuth2 Token', type: 'textarea', required: true },
              { name: 'drive_type', label: 'Drive Type', type: 'select', options: ['personal', 'business'] }
            ]
          }
        ]);
      }
      if (url.startsWith('/api/remotes/oauth/status/')) {
        return Promise.resolve({ completed: false, token: null });
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    const postSpy = vi.spyOn(api, 'post').mockImplementation((url, body) => {
      if (url === '/api/remotes/oauth/start') {
        return Promise.resolve({
          status: 'ok',
          session_id: 'zos_test123',
          provider_type: 'onedrive',
          auth_url: 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=test',
          redirect_port: 53682
        });
      }
      if (url === '/api/remotes/oauth/exchange') {
        return Promise.resolve({
          status: 'ok',
          token: '{"access_token":"mock_exchanged_token","expiry":"2026-10-13T00:00:00Z"}',
          drive_type: 'personal',
          session_id: body.session_id
        });
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    await openNewCloudRemoteModal();

    // 1. Assert Assistant Card is mounted
    const card = document.querySelector('.oauth-assistant-card');
    expect(card).not.toBeNull();
    expect(card.textContent).toContain('Connect Microsoft OneDrive');
    expect(card.textContent).toContain('No Terminal Required');

    const browserBtn = document.getElementById('btn-oauth-browser');
    const qrBtn = document.getElementById('btn-oauth-qr');
    expect(browserBtn).not.toBeNull();
    expect(qrBtn).not.toBeNull();
    expect(browserBtn.textContent).toContain('1-Click Authorize with Microsoft');

    // 2. Click QR Code button to trigger OAuth start & SVG generation
    qrBtn.click();
    // the QR library loads on first use (FE-02), so wait for the code to be drawn
    const qrTarget = document.getElementById('oauth-qr-target');
    await vi.waitFor(() => expect(qrTarget.innerHTML).toContain('<svg'), { timeout: 3000 });

    expect(postSpy).toHaveBeenCalledWith('/api/remotes/oauth/start', { provider_type: 'onedrive' });

    const qrBox = document.getElementById('oauth-qr-box');
    expect(qrBox.style.display).toBe('block');

    const step2Box = document.getElementById('oauth-step2-box');
    expect(step2Box.style.display).toBe('block');

    // 3. Paste redirected URL and click Complete Authentication
    const urlInput = document.getElementById('oauth-redirect-url');
    const exchangeBtn = document.getElementById('btn-oauth-exchange');
    urlInput.value = 'http://localhost:53682/?code=M.R3_mock_code&state=mock_state';

    exchangeBtn.click();
    await new Promise((r) => setTimeout(r, 20));

    expect(postSpy).toHaveBeenCalledWith('/api/remotes/oauth/exchange', {
      session_id: 'zos_test123',
      redirect_url: 'http://localhost:53682/?code=M.R3_mock_code&state=mock_state'
    });

    // 4. Assert token textarea was auto-filled
    const tokenTextarea = document.querySelector('textarea[name="token"]');
    expect(tokenTextarea.value).toContain('mock_exchanged_token');

    // 5. Assert status indicator shows success
    const statusEl = document.getElementById('oauth-assistant-status');
    expect(statusEl.textContent).toContain('Authentication Successful');
  });

  it('handles deleting remote storage with showConfirmToast instead of window.confirm', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/webdav/status') {
        return Promise.resolve({ enabled: true, running: false, port: 8084 });
      }
      if (url === '/api/remotes') {
        return Promise.resolve([
          {
            name: 'onedrive-personal',
            type: 'onedrive',
            is_mounted: false,
            mount_path: '/mnt/remotes/onedrive-personal',
          },
        ]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    const confirmSpy = vi.spyOn(toast, 'showConfirmToast').mockImplementation((title, msg, onConfirm) => {
      onConfirm();
    });
    const windowConfirmSpy = vi.spyOn(window, 'confirm');
    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValue({ status: 'ok' });

    await fetchAndRenderRemoteStorage(container);

    const deleteBtn = container.querySelector('.btn-remote-delete');
    expect(deleteBtn).not.toBeNull();
    deleteBtn.click();

    expect(windowConfirmSpy).not.toHaveBeenCalled();
    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining('Delete'),
      expect.stringContaining('onedrive-personal'),
      expect.any(Function),
      null,
      expect.objectContaining({ icon: '🗑️' })
    );
    expect(deleteSpy).toHaveBeenCalledWith('/api/remotes/onedrive-personal');
  });

  it('marks Test Connection button tested-green and displays persistent success banner', async () => {
    const modalHtml = `
      <div id="modal-new-cloud-remote" class="smart-modal-backdrop os-window-overlay" style="display: none;">
        <div class="smart-modal-window os-window cloud-remote-window" id="cloud-remote-window">
          <div class="smart-modal-header" id="cloud-remote-window-header">
            <span id="modal-remote-title">Connect Remote</span>
          </div>
          <form id="new-remote-form">
            <select id="new-remote-provider-select"></select>
            <div id="new-remote-provider-desc"></div>
            <input type="text" id="new-remote-name" />
            <div id="new-remote-dynamic-fields"></div>
            <div id="new-remote-test-result" style="display: none;"></div>
            <div id="new-remote-error-box" style="display: none;"></div>
            <button type="button" id="new-remote-test-btn">Test</button>
            <button type="submit" id="new-remote-submit-btn">Save</button>
          </form>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/api/remotes/providers') {
        return Promise.resolve([
          {
            type: 'onedrive',
            name: 'Microsoft OneDrive',
            fields: [
              { name: 'token', label: 'Token', type: 'textarea' },
              { name: 'drive_id', label: 'Drive ID', type: 'text' }
            ]
          }
        ]);
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    vi.spyOn(api, 'post').mockImplementation((url) => {
      if (url === '/api/remotes/test') {
        return Promise.resolve({ success: true, item_count: 12, items_sample: ['doc.pdf'] });
      }
      return Promise.reject(new Error(`Unknown url: ${url}`));
    });

    await openNewCloudRemoteModal();

    const testBtn = document.getElementById('new-remote-test-btn');
    const testResult = document.getElementById('new-remote-test-result');
    const form = document.getElementById('new-remote-form');

    expect(testBtn.classList.contains('tested-green')).toBe(false);

    testBtn.click();
    await new Promise((r) => setTimeout(r, 20));

    expect(testBtn.classList.contains('tested-green')).toBe(true);
    expect(testBtn.textContent).toContain('Connection Successful');
    expect(testResult.style.display).toBe('block');
    expect(testResult.textContent).toContain('Connection Test Successful');

    // Modifying form resets green state
    form.dispatchEvent(new Event('input'));
    expect(testBtn.classList.contains('tested-green')).toBe(false);
    expect(testBtn.textContent).toContain('Test Connection');
  });
});

