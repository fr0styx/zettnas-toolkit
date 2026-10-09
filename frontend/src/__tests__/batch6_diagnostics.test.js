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

    expect(downloadSpy).toHaveBeenCalledWith('/api/system/diagnostics-bundle', 'zettnas_diagnostics.zip');
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
});
