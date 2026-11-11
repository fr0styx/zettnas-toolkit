/** NUX-20: the AI settings panel's model list, Hugging Face search, folders and sync status go through t(). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  renderAiLlmRecommendations,
  searchHuggingFaceModels,
  pullHuggingFaceModel,
  renderAiLearningResultsData,
  updateAiSyncProgressUi,
  renderAiWatchedFoldersAndShares,
  flushAiIndex,
  syncAiWatchedFolders,
  runAiPathIndex,
  updateAiReindexProgress,
  renderAiPreviewInspector,
  runAiVisualSearch,
  runAiRagAsk,
} from '../components/management/ai.js';
import { api } from '../api.js';
import { showConfirmToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const byId = (id) => document.getElementById(id);
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('AI settings words (NUX-20)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <span id="ai-active-llm-pill"></span><span id="ai-active-llm-label"></span>
      <button class="ai-hf-filter-btn" data-hf-filter="all"></button>
      <button class="ai-hf-filter-btn" data-hf-filter="compatible"></button>
      <div id="ai-llm-recommendations-grid"></div><div id="ai-hf-search-status"></div>
      <div id="ai-learn-failed-list"></div>
      <span id="ai-standby-guard-text"></span><span id="ai-standby-guard-badge"></span>
      <span id="ai-watched-dropdown-summary"></span><span id="ai-watched-dropdown-count-badge"></span>
      <div id="ai-discovered-shares-list"></div><div id="ai-index-run-feedback"></div>`;
    vi.spyOn(api, 'get').mockResolvedValue({});
  });
  afterEach(() => vi.restoreAllMocks());

  it('describes the models and the one in use', () => {
    renderAiLlmRecommendations({
      models: [
        { id: 'm1', name: 'Small', vram_or_ram_gb: 4, min_ram_gb: 8, active: true },
        { id: 'm2', name: 'Tiny', est_ram_gb: 1 },
      ],
    }, 'm1');
    expect(byId('ai-active-llm-pill').title).toBe('Model in use: m1. It answers in Ask Kib and AI search.');
    expect(document.querySelector('[data-hf-filter="all"]').textContent).toBe('2026+ Releases (2)');
    expect(document.querySelector('[data-hf-filter="compatible"]').textContent).toBe('✅ Fits Hardware (2)');
    const grid = byId('ai-llm-recommendations-grid').textContent;
    expect(grid).toContain('~4 GB Model (8GB+ Host)');
    expect(grid).toContain('~1 GB Model');
  });

  it('reports a Hugging Face search and a pull, good or bad', async () => {
    api.get.mockResolvedValueOnce({ models: [{ id: 'a', name: 'A' }, { id: 'b', name: 'B', hardware_warning: true }] });
    await searchHuggingFaceModels('qwen');
    expect(byId('ai-hf-search-status').textContent).toBe('🤗 Showing 2 Hugging Face release models (1 fit your hardware, 1 flagged with hardware warning).');
    api.get.mockRejectedValueOnce(new Error('offline'));
    await searchHuggingFaceModels('qwen');
    expect(byId('ai-hf-search-status').textContent).toBe('⚠️ Hugging Face Hub search error: offline');

    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ hardware_warning: true, warning_message: 'too big', model: { hf_repo: 'org/big' } });
    await pullHuggingFaceModel('org/big');
    expect(byId('ai-hf-search-status').textContent).toBe('⚠️ Pulled org/big — too big');
    post.mockResolvedValueOnce({ model: {} });
    await pullHuggingFaceModel('org/small');
    expect(byId('ai-hf-search-status').textContent).toBe('✅ Pulled org/small from Hugging Face (Fits your hardware).');
    post.mockRejectedValueOnce(new Error('denied'));
    await pullHuggingFaceModel('org/small');
    expect(byId('ai-hf-search-status').textContent).toBe('⚠️ Failed to pull from Hugging Face: denied');
  });

  it('shows learning results, the standby guard and empty folder lists', () => {
    renderAiLearningResultsData({});
    expect(byId('ai-learn-failed-list').textContent).toBe('✓ All learned files succeeded with 0 errors.');
    updateAiSyncProgressUi({}, { sleeping_disks_count: 3, running_disks_count: 1 });
    // the real counts, and no "0 wakeups": nothing counts them (SET-15, AI 2)
    expect(byId('ai-standby-guard-text').textContent).toBe('Drives: 1 awake, 3 asleep');
    expect(byId('ai-standby-guard-badge').title).not.toMatch(/wakeups/i);
    renderAiWatchedFoldersAndShares([], []);
    expect(byId('ai-watched-dropdown-summary').textContent).toBe('No folders checked — click to select folders for RAG');
    expect(byId('ai-watched-dropdown-count-badge').textContent).toBe('0 Checked');
    expect(byId('ai-discovered-shares-list').textContent).toBe('No NAS folders discovered yet. Use Browse or Add Folder below.');
  });

  it('says when emptying the index or a sync fails', async () => {
    flushAiIndex();
    const onConfirm = showConfirmToast.mock.calls.at(-1)[2];
    vi.spyOn(api, 'post').mockRejectedValue(new Error('locked'));
    await onConfirm();
    expect(byId('ai-index-run-feedback').textContent).toBe('✕ Flush failed: locked');

    renderAiWatchedFoldersAndShares(['/mnt/user/docs', '/mnt/user/photos'], []);
    const run = syncAiWatchedFolders(true, true);
    expect(byId('ai-index-run-feedback').textContent).toBe('⏳ Starting spindown-safe sync across 2 watched folders...');
    await run;
    await flush();
    expect(byId('ai-index-run-feedback').textContent).toBe('⚠️ Sync failed: locked');
  });

  it('still works when the panel is not on screen', async () => {
    document.body.innerHTML = '';
    flushAiIndex();
    vi.spyOn(api, 'post').mockRejectedValue(new Error('locked'));
    await expect(showConfirmToast.mock.calls.at(-1)[2]()).resolves.toBeNull();
    await expect(syncAiWatchedFolders()).resolves.toBeNull();
    document.body.innerHTML = '<div id="ai-hf-search-status"></div>';
    api.post.mockResolvedValueOnce({ hardware_warning: true, warning_message: 'slow' });
    await pullHuggingFaceModel('org/x');
    expect(byId('ai-hf-search-status').textContent).toBe('⚠️ Pulled org/x — slow');
  });

  it('reports indexing a folder and the re-index progress', async () => {
    document.body.innerHTML = '<button id="btn-ai-run-index"></button><div id="ai-index-run-feedback"></div><span id="mgmt-sidebar-ai-badge"></span><span id="topbar-ai-accel-text"></span>';
    const post = vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('busy'));
    const run = runAiPathIndex('/mnt/user/docs');
    expect(byId('ai-index-run-feedback').textContent).toBe('⏳ Scanning /mnt/user/docs (Spindown-Safe Incremental Indexer)...');
    expect(byId('btn-ai-run-index').textContent.trim()).toBe('⏳ Indexing...');
    await run;
    expect(byId('ai-index-run-feedback').textContent).toBe('⚠️ Indexing failed: busy');
    post.mockResolvedValueOnce(null);
    await runAiPathIndex(['/a', '/b']);
    updateAiReindexProgress({ total: 10, completed: 4, eta_sec: 30 });
    expect(byId('mgmt-sidebar-ai-badge').textContent).toBe('40% Re-index');
    expect(byId('topbar-ai-accel-text').textContent).toBe('Re-indexing 40% • ETA: 30s');
  });

  it('labels the file inspector', () => {
    document.body.innerHTML = '<div id="ai-preview-inspector-pane"></div>';
    renderAiPreviewInspector({ file_id: 1, file_path: '/mnt/user/a.pdf', file_category: 'documents', match_reason: 'Keyword', is_favorite: true });
    let pane = byId('ai-preview-inspector-pane').textContent;
    for (const w of ['Location:', 'Match Mode:', 'Keyword', 'Open File', 'Open Location', 'Download', '⭐ Favorited', 'Share File Path / Link']) expect(pane).toContain(w);
    renderAiPreviewInspector({ file_id: 2, file_path: '/mnt/user/b.jpg' });
    pane = byId('ai-preview-inspector-pane').textContent;
    expect(pane).toContain('Semantic Vector');
    expect(pane).toContain('☆ Favorite');
  });

  it('explains a visual search, or why it found nothing', async () => {
    document.body.innerHTML = '<div id="ai-visual-intent-banner"></div><div><div id="ai-visual-results-grid"></div></div>';
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ results: [], parsed_intent: { auto_colors: ['red'], auto_scenes: ['beach'] } });
    const run = runAiVisualSearch('red beach');
    expect(byId('ai-visual-results-grid').textContent).toBe('🔍 Searching visual & multi-modal index...');
    await run;
    const banner = byId('ai-visual-intent-banner').textContent;
    for (const w of ['Parsed Visual Intent:', 'Color:', 'red', 'Scene:', 'beach', 'Mode:']) expect(banner).toContain(w);
    expect(banner).not.toContain('Wakeups'); // a fixed promise nothing measured (SET-15, AI 2)
    expect(byId('ai-visual-results-grid').textContent.trim()).toBe('No matching files found for red beach. Click Sync Shares above or configure folders in the ⚙️ AI Configuration tab.');
    post.mockResolvedValueOnce({ results: [], parsed_intent: {} });
    await runAiVisualSearch('cat');
    expect(byId('ai-visual-intent-banner').textContent).not.toContain('Color:');
    post.mockRejectedValueOnce(new Error('no index'));
    await runAiVisualSearch('cat');
    expect(byId('ai-visual-results-grid').textContent).toBe('Visual search failed: no index');
    post.mockRejectedValueOnce('down');
    await runAiVisualSearch('cat');
    expect(byId('ai-visual-results-grid').textContent).toBe('Visual search failed: down');
  });

  it('shows a recipe answer with or without its details, and a failed question', async () => {
    document.body.innerHTML = '<div id="ai-rag-answer-container"></div><button id="btn-ai-rag-ask"></button>';
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({
      answer: 'Boil pasta.',
      citations: [{ file_path: '/mnt/user/r.md', file_name: 'r.md', excerpt: 'pasta' }],
      structured_cards: [
        { type: 'recipe', title: 'Pasta', prep_time: '5 min', cook_time: '10 min', servings: '2', ingredients: ['pasta'], steps: ['boil'] },
        { type: 'recipe', title: 'Plain' },
      ],
    });
    const run = runAiRagAsk('pasta');
    expect(byId('btn-ai-rag-ask').textContent.trim()).toBe('⏳ Thinking...');
    await run;
    const out = byId('ai-rag-answer-container').textContent;
    for (const w of ['Prep: 5 min', 'Cook: 10 min', 'Serves: 2', 'Ingredients', 'Instructions', 'Grounded Document Citations (1)', 'Cached']) expect(out).toContain(w);
    post.mockRejectedValueOnce(new Error('model asleep'));
    await runAiRagAsk('pasta');
    expect(byId('ai-rag-answer-container').textContent).toBe('RAG Query Error: model asleep');
    post.mockRejectedValueOnce('offline');
    await runAiRagAsk('pasta');
    expect(byId('ai-rag-answer-container').textContent).toBe('RAG Query Error: offline');
  });
});
