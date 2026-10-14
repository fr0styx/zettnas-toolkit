import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { downloadDiagnosticsBundle } from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('Batch 6: Observability, Structured Logging & Diagnostics Export', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.innerHTML = `
      <div id="mgmt-pane-about">
        <button id="btn-download-diagnostics" class="btn-pill-toggle">
          <span id="btn-download-diagnostics-icon">📦</span>
          <span id="btn-download-diagnostics-text">Download Diagnostics Bundle</span>
        </button>
      </div>
    `;
    document.body.appendChild(container);
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});
  });

  afterEach(() => {
    container?.remove();
    vi.restoreAllMocks();
  });

  it('renders download button with initial label and icon', () => {
    const btn = document.getElementById('btn-download-diagnostics');
    const icon = document.getElementById('btn-download-diagnostics-icon');
    const text = document.getElementById('btn-download-diagnostics-text');

    expect(btn).not.toBeNull();
    expect(btn.disabled).toBe(false);
    expect(icon.textContent).toBe('📦');
    expect(text.textContent).toBe('Download Diagnostics Bundle');
  });

  it('successfully triggers downloadBlob and notifies user with toast', async () => {
    const mockFilename = 'zettnas_diagnostics_20261009_172000.zip';
    const downloadSpy = vi.spyOn(api, 'downloadBlob').mockImplementation(async () => {
      // Simulate button loading state during request
      const btn = document.getElementById('btn-download-diagnostics');
      const icon = document.getElementById('btn-download-diagnostics-icon');
      const text = document.getElementById('btn-download-diagnostics-text');
      expect(btn.disabled).toBe(true);
      expect(icon.textContent).toBe('⏳');
      expect(text.textContent).toBe('Generating Archive...');
      return mockFilename;
    });

    await downloadDiagnosticsBundle();

    expect(downloadSpy).toHaveBeenCalledWith(
      '/api/system/diagnostics-bundle',
      'zettnas_diagnostics.zip',
      expect.objectContaining({ method: 'POST' })
    );
    expect(toast.showToast).toHaveBeenCalledWith('Generating diagnostics bundle (scrubbing secrets)...', 'info');
    expect(toast.showToast).toHaveBeenCalledWith(`Diagnostics bundle downloaded successfully (${mockFilename}).`, 'success');

    // Restored state
    const btn = document.getElementById('btn-download-diagnostics');
    const icon = document.getElementById('btn-download-diagnostics-icon');
    const text = document.getElementById('btn-download-diagnostics-text');
    expect(btn.disabled).toBe(false);
    expect(icon.textContent).toBe('📦');
    expect(text.textContent).toBe('Download Diagnostics Bundle');
  });

  it('handles download failure gracefully and re-enables button', async () => {
    vi.spyOn(api, 'downloadBlob').mockRejectedValue(new Error('503 Service Unavailable'));

    await downloadDiagnosticsBundle();

    expect(toast.showToast).toHaveBeenCalledWith('Failed to download diagnostics: 503 Service Unavailable', 'error');

    const btn = document.getElementById('btn-download-diagnostics');
    const icon = document.getElementById('btn-download-diagnostics-icon');
    const text = document.getElementById('btn-download-diagnostics-text');
    expect(btn.disabled).toBe(false);
    expect(icon.textContent).toBe('📦');
    expect(text.textContent).toBe('Download Diagnostics Bundle');
  });

  it('api.downloadBlob creates anchor element and triggers download', async () => {
    const fakeBlob = new Blob(['zip-content'], { type: 'application/zip' });
    const mockRes = {
      ok: true,
      status: 200,
      headers: {
        get: (h) => (h === 'content-disposition' ? 'attachment; filename="diagnostics_test.zip"' : null),
      },
      blob: async () => fakeBlob,
    };

    vi.spyOn(window, 'fetch').mockResolvedValue(mockRes);

    const createObjectURLMock = vi.fn().mockReturnValue('blob:http://localhost/fake-uuid');
    const revokeObjectURLMock = vi.fn();
    window.URL.createObjectURL = createObjectURLMock;
    window.URL.revokeObjectURL = revokeObjectURLMock;

    let clicked = false;
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName) => {
      const el = origCreateElement(tagName);
      if (tagName === 'a') {
        el.click = () => { clicked = true; };
      }
      return el;
    });

    const result = await api.downloadBlob('/api/system/diagnostics-bundle', 'default.zip');

    expect(result).toBe('diagnostics_test.zip');
    expect(createObjectURLMock).toHaveBeenCalledWith(fakeBlob);
    expect(clicked).toBe(true);
    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:http://localhost/fake-uuid');
  });

  it('openDiagnosticsPreviewModal renders executive health banner and correct memory RAM metrics', async () => {
    const { openDiagnosticsPreviewModal } = await import('../components/management.js');

    const modalContainer = document.createElement('div');
    modalContainer.innerHTML = `
      <div id="diagnostics-preview-modal-overlay" style="display:none;">
        <div id="diagnostics-preview-banner" style="display:none;"></div>
        <div id="diagnostics-preview-grid"></div>
        <pre id="diagnostics-preview-md"></pre>
      </div>
    `;
    document.body.appendChild(modalContainer);

    const mockData = {
      executive_status: 'ATTENTION_REQUIRED',
      alerts: [
        { level: 'warning', message: 'Containers requiring attention: zettnas-samba' },
      ],
      platform: 'Linux 6.18.54-Unraid',
      chassis: 'Zettlab D6 Ultra (6-Bay)',
      uptime_hours: 4.2,
      memory: {
        used_gb: 7.2,
        total_gb: 58.4,
        pct: 12,
      },
      storage: {
        pools_count: 4,
        disks_count: 5,
        standby_count: 1,
      },
      docker: {
        total: 23,
        running: 11,
        restarting: 1,
        dead: 0,
      },
      vms: {
        active_vm_count: 0,
        total_vm_count: 2,
      },
      support_markdown: '### ZettNAS Toolkit Support Diagnostics\n- Memory Usage: 12% (7.2 GB of 58.4 GB RAM)',
    };

    openDiagnosticsPreviewModal(mockData);

    const overlay = document.getElementById('diagnostics-preview-modal-overlay');
    const banner = document.getElementById('diagnostics-preview-banner');
    const grid = document.getElementById('diagnostics-preview-grid');
    const md = document.getElementById('diagnostics-preview-md');

    expect(overlay.style.display).toBe('flex');
    expect(banner.style.display).toBe('block');
    expect(banner.textContent).toContain('ATTENTION REQUIRED');
    expect(banner.textContent).toContain('zettnas-samba');
    expect(grid.innerHTML).toContain('12% Used');
    expect(grid.innerHTML).toContain('7.2 / 58.4 GB RAM');
    expect(md.textContent).toContain('Memory Usage: 12%');

    modalContainer.remove();
  });
});
