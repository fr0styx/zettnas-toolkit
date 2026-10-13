import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  downloadDiagnosticsBundle,
  previewDiagnosticsSummary,
  copySupportMarkdown,
  openDiagnosticsPreviewModal,
  closeDiagnosticsPreviewModal,
} from '../components/management.js';
import { api } from '../api.js';

describe('Diagnostics UX & Observability Frontend Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = `
      <div id="btn-download-diagnostics">
        <span id="btn-download-diagnostics-icon">📦</span>
        <span id="btn-download-diagnostics-text">Download Diagnostics Bundle</span>
      </div>
      <div id="diagnostics-preview-modal-overlay" style="display: none;">
        <div id="diagnostics-preview-grid"></div>
        <pre id="diagnostics-preview-md"></pre>
      </div>
    `;
  });

  it('downloadDiagnosticsBundle collects telemetry and invokes downloadBlob with POST', async () => {
    const downloadBlobSpy = vi.spyOn(api, 'downloadBlob').mockResolvedValue('test_diagnostics.zip');

    await downloadDiagnosticsBundle();

    expect(downloadBlobSpy).toHaveBeenCalledWith(
      '/api/system/diagnostics-bundle',
      'zettnas_diagnostics.zip',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
    );
  });

  it('openDiagnosticsPreviewModal and closeDiagnosticsPreviewModal toggle overlay state and populate grid', () => {
    const mockSummary = {
      chassis: 'Zettlab D6',
      uptime_hours: 14.5,
      memory: { used_percent: 45, total_bytes: 34359738368 },
      storage: { pools_count: 2, disks_count: 6, standby_count: 4 },
      docker: { total: 10, running: 9, restarting: 0, dead: 0 },
      vms: { active_vm_count: 1, total_vm_count: 2 },
      support_markdown: '### Support Diagnostics\n- Version: 1.7.0',
    };

    openDiagnosticsPreviewModal(mockSummary);

    const overlay = document.getElementById('diagnostics-preview-modal-overlay');
    expect(overlay.style.display).toBe('flex');

    const mdEl = document.getElementById('diagnostics-preview-md');
    expect(mdEl.textContent).toContain('### Support Diagnostics');

    const grid = document.getElementById('diagnostics-preview-grid');
    expect(grid.innerHTML).toContain('Zettlab D6');
    expect(grid.innerHTML).toContain('45% Used');
    expect(grid.innerHTML).toContain('2 Pools');

    closeDiagnosticsPreviewModal();
    expect(overlay.style.display).toBe('none');
  });

  it('copySupportMarkdown fetches diagnostics-summary and copies markdown', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      support_markdown: '### ZettNAS Diagnostics Markdown',
    });

    // Mock document.execCommand
    document.execCommand = vi.fn().mockReturnValue(true);

    await copySupportMarkdown();

    expect(api.get).toHaveBeenCalledWith('/api/system/diagnostics-summary');
  });
});
