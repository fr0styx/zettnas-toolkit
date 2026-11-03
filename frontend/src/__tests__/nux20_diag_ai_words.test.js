/** NUX-20: the diagnostics summary grid and the AI search category chips read as translatable words. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { openDiagnosticsPreviewModal } from '../components/management/system.js';
import { runAiVisualSearch } from '../components/management/ai.js';
import { api } from '../api.js';

describe('diagnostics and AI category words (NUX-20)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('labels the diagnostics summary, with or without numbers', () => {
    document.body.innerHTML = '<div id="diagnostics-preview-modal-overlay"><div class="smart-modal-window"></div></div><div id="diagnostics-preview-grid"></div>';
    openDiagnosticsPreviewModal({});
    const grid = () => document.getElementById('diagnostics-preview-grid').textContent;
    for (const w of ['Host & OS', 'Uptime: 0h', 'Memory', 'Storage', '0 Pools', 'Docker Fleet', 'Virtual Machines', 'Headroom: Safe']) expect(grid()).toContain(w);
    openDiagnosticsPreviewModal({ uptime_hours: 5, storage: { pools_count: 1 } });
    expect(grid()).toContain('Uptime: 5h');
    expect(grid()).toContain('1 Pool');
  });

  it('names the search categories', async () => {
    document.body.innerHTML = `<div id="ai-search-filetype-bar">
      ${['photos', 'videos', 'audio', 'documents', 'folders'].map((k) => `<button class="ai-filetype-chip" data-filetype="${k}"></button>`).join('')}
    </div><div><div id="ai-visual-results-grid"></div></div>`;
    vi.spyOn(api, 'post').mockResolvedValue({ results: [], category_groups: { images: 2, videos: 0, audio: 0, documents: 1, folders: 0 } });
    await runAiVisualSearch('beach');
    const bar = document.getElementById("ai-search-filetype-bar").textContent;
    for (const w of ["Images (2)", "Videos (0)", "Audio (0)", "Documents (1)", "Folders (0)"]) expect(bar).toContain(w);
  });
});
