import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  SUBPANE_MAP,
  fetchAndRenderAiStatus,
  runAiRagAsk,
  runAiVisualSearch,
  runAiPathIndex,
  initAiKnowledgeEngine,
  controlAiSync,
  addAiWatchedFolder,
  removeAiWatchedFolder,
  renderAiWatchedFoldersAndShares,
  renderAiLlmRecommendations,
  selectAiRecommendedModel,
  removeAiModel,
  searchHuggingFaceModels,
  pullHuggingFaceModel,
  openAiLearningResults,
  renderAiPreviewInspector,
  sendAiChatMessage,
  clearAiChatHistory,
  isAiThinkingModel,
  renderAiRagInitialEmptyState,
  flushAiIndex,
  updateAiReindexProgress,
} from '../components/management.js';
import { openFilePreviewModal, closeFilePreviewModal } from '../components/file-preview-modal.js';
import { initSpotlight, filterSpotlightResults } from '../components/spotlight.js';
import { TRANSLATIONS } from '../i18n.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('ZettAI — Multi-Modal Local RAG & Visual Search Frontend Suite', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="topbar-ai-accel-pill">
        <span id="topbar-ai-accel-dot"></span>
        <span id="topbar-ai-accel-label">AI: NPU</span>
      </div>
      <span id="mgmt-sidebar-ai-badge">NPU</span>
      <span id="mgmt-hub-ai-pill">NPU → GPU</span>
      <span id="ai-active-tier-pill"></span>
      <span id="ai-accel-device-label"></span>
      <span id="ai-stat-files">0</span>
      <span id="ai-stat-chunks">0</span>
      <span id="ai-stat-photos">0</span>
      <div id="ai-tier1-status"></div>
      <div id="ai-tier2-status"></div>
      <div id="ai-tier3-status"></div>
      <div id="ai-index-db-summary"></div>
      <span id="ai-sync-state-badge"><span id="ai-sync-state-dot"></span><span id="ai-sync-state-text"></span></span>
      <span id="ai-index-sync-state-pill">IDLE</span>
      <span id="ai-index-current-path"></span>
      <strong id="ai-prog-indexed">0</strong>
      <strong id="ai-prog-unchanged">0</strong>
      <strong id="ai-prog-deferred">0</strong>
      <div id="ai-watched-folders-list"></div>
      <div id="ai-discovered-shares-list"></div>
      <button id="btn-ai-index-pause">Pause</button>
      <button id="btn-ai-index-resume">Resume</button>
      <button id="btn-ai-index-stop">Stop</button>
      <input id="ai-rag-query-input" value="garlic pasta recipe" />
      <button id="btn-ai-rag-ask">✨ Ask NAS</button>
      <div id="ai-rag-answer-container"></div>
      <input id="ai-visual-query-input" value="red car at the beach" />
      <button id="btn-ai-visual-search">🔍 Visual Search</button>
      <div id="ai-color-swatch-bar">
        <button class="ai-color-swatch active" data-color="">All</button>
        <button class="ai-color-swatch" data-color="red">Red</button>
        <button class="ai-color-swatch" data-color="blue">Blue</button>
      </div>
      <div id="ai-scene-pill-bar">
        <button class="ai-scene-pill active" data-scene="">All</button>
        <button class="ai-scene-pill" data-scene="pool">Pool</button>
        <button class="ai-scene-pill" data-scene="beach">Beach</button>
        <button class="ai-scene-pill" data-scene="car">Car</button>
      </div>
      <div id="ai-visual-results-grid"></div>
      <input id="ai-index-path-input" value="/mnt/user/recipes" />
      <input type="checkbox" id="ai-respect-standby-cb" checked />
      <button id="btn-ai-run-index-path">🚀 Index Path Now</button>
    `;
    vi.restoreAllMocks();
  });

  it('maps AI & RAG subpanes accurately in SUBPANE_MAP', () => {
    expect(SUBPANE_MAP['ai']).toEqual({ section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' });
    expect(SUBPANE_MAP['chatbot']).toEqual({ section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' });
    expect(SUBPANE_MAP['rag']).toEqual({ section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-rag' });
    expect(SUBPANE_MAP['mgmt-sec-ai']).toEqual({ section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' });
    expect(SUBPANE_MAP['mgmt-pane-ai-visual']).toEqual({ section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-visual' });
    expect(SUBPANE_MAP['mgmt-pane-ai-index']).toEqual({ section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-index' });
  });

  it('renders Tier 1 NPU hardware status and index stats across topbar, hub, and 3-tier cards', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      status: 'ok',
      hardware: {
        available: true,
        tier: 'NPU_TIER_1',
        tier_number: 1,
        type: 'intel_npu',
        name: 'Intel AI Boost NPU (Core Ultra VPU)',
        device_node: '/dev/accel/accel0',
        execution_provider: 'OpenVINOExecutionProvider',
      },
      index_stats: {
        total_files: 42,
        total_documents: 18,
        total_photos: 24,
        total_chunks: 136,
        deferred_queue_count: 2,
        db_size_bytes: 65536,
        db_path: '/app/data/rag_index.db',
      },
    });

    await fetchAndRenderAiStatus();

    expect(document.getElementById('topbar-ai-accel-label').textContent).toBe('AI: NPU');
    expect(document.getElementById('mgmt-sidebar-ai-badge').textContent).toBe('NPU');
    expect(document.getElementById('mgmt-hub-ai-pill').textContent).toContain('NPU TIER 1');
    expect(document.getElementById('ai-stat-files').textContent).toBe('42');
    expect(document.getElementById('ai-stat-chunks').textContent).toBe('136');
    expect(document.getElementById('ai-stat-photos').textContent).toBe('24');
    expect(document.getElementById('ai-tier1-status').textContent).toContain('ACTIVE: Intel AI Boost NPU');
    expect(document.getElementById('ai-tier2-status').textContent).toContain('Secondary Fallback');
  });

  it('synthesizes grounded RAG answers with structured Recipe Cards and citations', async () => {
    vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      query: 'garlic pasta recipe',
      answer: 'Found **1** relevant document for **"garlic pasta recipe"** [1].',
      elapsed_ms: 4.2,
      hardware: { tier: 'NPU_TIER_1' },
      structured_cards: [
        {
          type: 'recipe',
          title: 'Nonnas Crispy Garlic Olive Oil Pasta',
          prep_time: '10 mins',
          cook_time: '15 mins',
          servings: '4',
          ingredients: ['400g spaghetti', '8 cloves garlic', '1/2 cup extra virgin olive oil'],
          steps: ['Boil salted pasta water.', 'Toast sliced garlic gently in olive oil.'],
        },
      ],
      citations: [
        {
          index: 1,
          file_id: 7,
          file_path: '/mnt/user/recipes/garlic_pasta.md',
          file_name: 'garlic_pasta.md',
          section_title: 'Ingredients',
          excerpt: '400g spaghetti, 8 cloves garlic, olive oil, red pepper flakes',
        },
      ],
      photos: [],
    });

    await runAiRagAsk('garlic pasta recipe');

    const container = document.getElementById('ai-rag-answer-container');
    expect(container.innerHTML).toContain('Nonnas Crispy Garlic Olive Oil Pasta');
    expect(container.innerHTML).toContain('400g spaghetti');
    expect(container.innerHTML).toContain('garlic_pasta.md');
    expect(container.innerHTML).toContain('Standby Safe');
  });

  it('executes visual & color photo search and binds swatch/scene filters', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      status: 'ok',
      results: [
        {
          file_id: 19,
          file_path: '/mnt/user/photos/red_ferrari_beach.jpg',
          file_name: 'red_ferrari_beach.jpg',
          thumbnail_url: '/api/media/thumbnail/19',
          scene_tags: ['car', 'beach', 'outdoor'],
          object_colors: ['red'],
          dominant_colors: ['red', 'blue'],
        },
      ],
    });

    initAiKnowledgeEngine();
    const redSwatch = document.querySelector('.ai-color-swatch[data-color="red"]');
    redSwatch.click();

    await vi.waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        '/api/media/search',
        expect.objectContaining({
          modality: 'photo',
          color: 'red',
        })
      );
    });

    const grid = document.getElementById('ai-visual-results-grid');
    expect(grid.innerHTML).toContain('red_ferrari_beach.jpg');
    expect(grid.innerHTML).toContain('#car');
    expect(grid.innerHTML).toContain('#beach');
  });

  it('opens Standby-Safe QuickLook preview from NVMe RAG cache without calling /api/fs/preview', async () => {
    const getSpy = vi.spyOn(api, 'get');
    await openFilePreviewModal('/mnt/user/recipes/garlic_pasta.md', 'garlic_pasta.md', {
      standbySafe: true,
      fileId: 7,
      excerpt: '400g spaghetti, 8 cloves garlic, olive oil',
    });

    expect(getSpy).not.toHaveBeenCalled();
    const bodyEl = document.getElementById('quicklook-body');
    expect(bodyEl.innerHTML).toContain('Standby Guard Active');
    expect(bodyEl.innerHTML).toContain('400g spaghetti');
    closeFilePreviewModal();
  });

  it('controls Pause, Resume, Stop sync state and manages Watched Folders with live disk standby status', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ status: 'ok', hardware: { tier_number: 1 } });
    const postSpy = vi.spyOn(api, 'post')
      .mockResolvedValueOnce({
        status: 'ok',
        sync_state: 'paused',
        sync_progress: { state: 'paused', is_paused: true, is_scanning: true, indexed_files: 12, deferred_standby: 1 },
      })
      .mockResolvedValueOnce({
        status: 'ok',
        sync_state: 'stopped',
        sync_progress: { state: 'stopped', is_paused: false, is_scanning: false, indexed_files: 12, deferred_standby: 1 },
      })
      .mockResolvedValueOnce({
        status: 'ok',
        watched_paths: ['/mnt/user/apishare', '/mnt/user/recipes'],
        available_folders: [
          { path: '/mnt/user/apishare', name: 'apishare', backing_dev: 'nvme2n1', in_standby: false },
          { path: '/mnt/user/vault', name: 'vault', backing_dev: 'sda', in_standby: true },
        ],
      })
      .mockResolvedValueOnce({
        status: 'ok',
        watched_paths: ['/mnt/user/apishare'],
        available_folders: [
          { path: '/mnt/user/apishare', name: 'apishare', backing_dev: 'nvme2n1', in_standby: false },
          { path: '/mnt/user/vault', name: 'vault', backing_dev: 'sda', in_standby: true },
        ],
      });

    await controlAiSync('pause');
    expect(postSpy).toHaveBeenCalledWith('/api/media/index/control', { action: 'pause' });
    expect(document.getElementById('ai-index-sync-state-pill').textContent).toBe('PAUSED');

    await controlAiSync('stop');
    expect(postSpy).toHaveBeenCalledWith('/api/media/index/control', { action: 'stop' });
    expect(document.getElementById('ai-index-sync-state-pill').textContent).toBe('STOPPED');

    await addAiWatchedFolder('/mnt/user/recipes');
    expect(postSpy).toHaveBeenCalledWith('/api/media/folders', { action: 'add', path: '/mnt/user/recipes' });
    expect(document.getElementById('ai-watched-folders-list').innerHTML).toContain('/mnt/user/recipes');
    expect(document.getElementById('ai-discovered-shares-list').innerHTML).toContain('💤 sda');
    expect(document.getElementById('ai-discovered-shares-list').innerHTML).toContain('🟢 nvme2n1');
    // Custom path /mnt/user/recipes is also merged into the dropdown checklist as checked
    expect(document.getElementById('ai-discovered-shares-list').innerHTML).toContain('/mnt/user/recipes');

    await removeAiWatchedFolder('/mnt/user/recipes');
    expect(postSpy).toHaveBeenCalledWith('/api/media/folders', { action: 'remove', path: '/mnt/user/recipes' });
  });

  it('opens the Watched Folders dropdown and toggles folder checkmarks in-place without closing the menu', async () => {
    document.body.insertAdjacentHTML('beforeend', `
      <div id="ai-watched-folders-dropdown-container">
        <button type="button" id="btn-ai-watched-folders-dropdown" aria-expanded="false">
          <span id="ai-watched-dropdown-summary"></span>
          <span id="ai-watched-dropdown-count-badge">0 Checked</span>
          <span id="ai-watched-dropdown-caret">▾</span>
        </button>
        <div id="ai-watched-folders-dropdown-menu" style="display:none;"></div>
      </div>
    `);
    // Move #ai-discovered-shares-list inside the dropdown menu to match index.html
    const menuEl = document.getElementById('ai-watched-folders-dropdown-menu');
    const sharesEl = document.getElementById('ai-discovered-shares-list');
    menuEl.appendChild(sharesEl);

    initAiKnowledgeEngine();

    renderAiWatchedFoldersAndShares(
      ['/mnt/user/apishare'],
      [
        { path: '/mnt/user/apishare', name: 'apishare', backing_dev: 'nvme2n1', in_standby: false },
        { path: '/mnt/user/vault', name: 'vault', backing_dev: 'sda', in_standby: true },
      ]
    );

    expect(document.getElementById('ai-watched-dropdown-summary').textContent).toBe('/mnt/user/apishare');
    expect(document.getElementById('ai-watched-dropdown-count-badge').textContent).toBe('1 Checked');

    // Click dropdown button to open menu
    const dropdownBtn = document.getElementById('btn-ai-watched-folders-dropdown');
    dropdownBtn.click();
    expect(menuEl.style.display).toBe('block');
    expect(dropdownBtn.getAttribute('aria-expanded')).toBe('true');

    // Click unchecked folder (/mnt/user/vault) inside the dropdown to check & add it for RAG
    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      watched_paths: ['/mnt/user/apishare', '/mnt/user/vault'],
      available_folders: [
        { path: '/mnt/user/apishare', name: 'apishare', backing_dev: 'nvme2n1', in_standby: false },
        { path: '/mnt/user/vault', name: 'vault', backing_dev: 'sda', in_standby: true },
      ],
    });

    const vaultItem = sharesEl.querySelector('.ai-discovered-share-pill[data-folder-path="/mnt/user/vault"]');
    expect(vaultItem).toBeTruthy();
    expect(vaultItem.dataset.watched).toBe('0');
    vaultItem.click();

    await new Promise((r) => setTimeout(r, 10));
    expect(postSpy).toHaveBeenCalledWith('/api/media/folders', { action: 'add', path: '/mnt/user/vault' });
    // Menu stays open so user can check multiple folders in the same dropdown
    expect(menuEl.style.display).toBe('block');
    expect(document.getElementById('ai-watched-dropdown-count-badge').textContent).toBe('2 Checked');
    expect(document.getElementById('ai-watched-dropdown-summary').textContent).toContain('/mnt/user/vault');
    const updatedVaultItem = sharesEl.querySelector('.ai-discovered-share-pill[data-folder-path="/mnt/user/vault"]');
    expect(updatedVaultItem.dataset.watched).toBe('1');
  });

  it('supports ? / ask: / photo: prefixes in Spotlight Cmd+K and localizes across all 5 languages', () => {
    initSpotlight();
    filterSpotlightResults('? garlic pasta recipe');
    const resultsEl = document.getElementById('spotlight-results');
    expect(resultsEl.textContent).toContain('Ask ZettAI RAG: "garlic pasta recipe"');

    filterSpotlightResults('photo: red car in pool');
    expect(resultsEl.textContent).toContain('Visual Search: "red car in pool"');

      // Verify 5-language localization parity
      for (const lang of ['en', 'de', 'zh', 'fr', 'es']) {
        expect(TRANSLATIONS[lang]['mgmt.sidebar_ai']).toBeTruthy();
        expect(TRANSLATIONS[lang]['mgmt.hub_ai_title']).toBeTruthy();
        expect(TRANSLATIONS[lang]['ai.title']).toBeTruthy();
        expect(TRANSLATIONS[lang]['ai.pause_sync']).toBeTruthy();
        expect(TRANSLATIONS[lang]['ai.resume_sync']).toBeTruthy();
        expect(TRANSLATIONS[lang]['ai.stop_sync']).toBeTruthy();
        expect(TRANSLATIONS[lang]['ai.llm_advisor_title']).toBeTruthy();
        expect(TRANSLATIONS[lang]['ai.learning_results_btn']).toBeTruthy();
      }
    });

  it('renders NPU & GPU LLM recommendations, activates models, and opens Split-Pane Preview Inspector', async () => {
    document.body.insertAdjacentHTML('beforeend', `
      <select id="ai-top-model-select"></select>
      <span id="ai-llm-advisor-headline"></span>
      <div id="ai-llm-advisor-summary"></div>
      <div id="ai-llm-recommendations-grid"></div>
      <div id="ai-learning-results-panel" style="display:none;">
        <strong id="ai-learn-succeeded-count">0</strong>
        <strong id="ai-learn-failed-count">0</strong>
        <strong id="ai-learn-deferred-count">0</strong>
        <div id="ai-learn-failed-list"></div>
      </div>
      <div id="ai-search-split-layout">
        <div id="ai-preview-inspector-pane" style="display:none;"></div>
      </div>
    `);

    renderAiLlmRecommendations({
      headline: 'NPU + GPU Hybrid AI Acceleration Detected',
      hardware_summary: 'Primary NPU: Intel AI Boost NPU (/dev/accel/accel0) • Secondary GPU: Intel Arc / QuickSync iGPU • System RAM: 58.4 GB',
      active_model: 'qwen2.5:3b',
      models: [
        {
          id: 'qwen2.5:3b',
          name: 'Qwen2.5 3B Instruct (NPU INT4)',
          category: 'Local LLM',
          params: '3.1B',
          quantization: 'INT4 / Q4_K_M',
          vram_or_ram_gb: 2.1,
          target_device: 'NPU (/dev/accel/accel0)',
          fit_badge: '★ Best for Onboard NPU',
          recommended: true,
          active: true,
          estimated_speed: '35–55 tok/s',
          power_profile: '6–10W NPU Offload',
          use_case: 'Fast grounded RAG Q&A',
          why_recommended: 'Fits inside Intel AI Boost NPU.',
        },
        {
          id: 'qwen2.5vl:7b',
          name: 'Qwen2.5-VL 7B Vision-Language',
          category: 'Vision-Language',
          params: '7.6B',
          quantization: 'Q4_K_M + FP16',
          vram_or_ram_gb: 5.8,
          target_device: 'Hybrid NPU + iGPU',
          fit_badge: '★ Best for NPU + iGPU',
          recommended: true,
          active: false,
          estimated_speed: '16–28 tok/s',
          power_profile: '18–30W Hybrid',
          use_case: 'Deep visual Q&A',
          why_recommended: 'Splits vision encoder onto NPU and language decoder onto iGPU.',
          fits_hardware: true,
          hardware_warning: false,
          hf_repo: 'Qwen/Qwen2.5-VL-7B-Instruct',
        },
        {
          id: 'llama3.3:70b',
          name: 'Meta Llama 3.3 70B Instruct (48GB+ VRAM Server Class)',
          category: 'high_capacity_llm',
          params: '70.6B',
          quantization: 'Q4_K_M',
          vram_or_ram_gb: 43.5,
          min_ram_gb: 96.0,
          target_device: 'Requires 48GB+ VRAM / 96GB+ RAM',
          fit_badge: "⚠️ Doesn't Fit Hardware (96GB+ RAM)",
          fit_status: 'insufficient_ram',
          fits_hardware: false,
          hardware_warning: true,
          warning_severity: 'critical',
          warning_message: 'Hardware Warning: Requires ~43.5 GB model memory (96 GB+ system RAM recommended), which exceeds your host RAM capacity.',
          hf_repo: 'meta-llama/Llama-3.3-70B-Instruct-GGUF',
          recommended: false,
          active: false,
          estimated_speed: '<0.8 tok/s (Swap/CPU)',
          power_profile: 'Server Class (350W+)',
        },
      ],
    }, 'qwen2.5:3b');

    expect(document.getElementById('ai-llm-advisor-headline').textContent).toContain('NPU + GPU Hybrid');
    const gridHtml = document.getElementById('ai-llm-recommendations-grid').innerHTML;
    expect(gridHtml).toContain('Qwen2.5 3B Instruct');
    expect(gridHtml).toContain('★ Best for Onboard NPU');
    expect(gridHtml).not.toContain('Meta Llama 3.3 70B Instruct');
    expect(document.getElementById('ai-top-model-select').innerHTML).not.toContain("[Doesn't Fit Hardware]");

    // Test model activation
    vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      active_model: 'qwen2.5vl:7b',
    });
    vi.spyOn(api, 'get').mockResolvedValueOnce({ status: 'ok', hardware: { tier_number: 1 } });

    await selectAiRecommendedModel('qwen2.5vl:7b');
    expect(api.post).toHaveBeenCalledWith('/api/media/models/select', { model: 'qwen2.5vl:7b', model_id: 'qwen2.5vl:7b' });

    // Test model removal with software UI confirmation dialog (showConfirmToast) instead of browser confirm
    expect(gridHtml).toContain('btn-ai-remove-model');
    let removePromise = null;
    const confirmSpy = vi.spyOn(toast, 'showConfirmToast').mockImplementation((title, msg, onConfirm) => {
      if (typeof onConfirm === 'function') removePromise = onConfirm();
    });

    vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      removed_model: 'qwen2.5vl:7b',
      active_model: 'qwen2.5:3b',
      llm_recommendations: { models: [] },
    });
    vi.spyOn(api, 'get').mockResolvedValueOnce({ status: 'ok', hardware: { tier_number: 1 } });

    const removeBtn = document.querySelector('.btn-ai-remove-model[data-model-id="qwen2.5vl:7b"]');
    expect(removeBtn).not.toBeNull();
    removeBtn.click();
    if (removePromise) await removePromise;

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining('Remove Model'),
      expect.stringContaining('from your ZettAI catalog'),
      expect.any(Function)
    );
    expect(api.post).toHaveBeenCalledWith('/api/media/models/remove', { model: 'qwen2.5vl:7b', model_id: 'qwen2.5vl:7b' });

    // Test Hugging Face Hub search & pull with hardware warning
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      status: 'ok',
      source: 'huggingface_live',
      models: [
        {
          id: 'hf.co/Qwen/Qwen2.5-72B-Instruct-GGUF',
          hf_repo: 'Qwen/Qwen2.5-72B-Instruct-GGUF',
          name: 'Qwen2.5-72B-Instruct-GGUF',
          params: '72B',
          quantization: 'INT4 / Q4_K_M',
          vram_or_ram_gb: 45.4,
          fits_hardware: false,
          hardware_warning: true,
          warning_severity: 'critical',
          fit_badge: "⚠️ Doesn't Fit Hardware (90GB+ RAM)",
          warning_message: 'Hardware Warning: Exceeds host RAM capacity.',
          source: 'huggingface_hub',
        },
      ],
    });
    await searchHuggingFaceModels('Qwen2.5-72B');
    expect(document.getElementById('ai-llm-recommendations-grid').innerHTML).toContain('⚠️ Pull Anyway (Unfit)');

    vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      active_model: 'hf.co/Qwen/Qwen2.5-72B-Instruct-GGUF',
      fits_hardware: false,
      hardware_warning: true,
      warning_message: 'Hardware Warning: Exceeds host RAM capacity.',
      model: { id: 'hf.co/Qwen/Qwen2.5-72B-Instruct-GGUF', name: 'Qwen2.5-72B-Instruct-GGUF', hf_repo: 'Qwen/Qwen2.5-72B-Instruct-GGUF' },
    });
    vi.spyOn(api, 'get').mockResolvedValueOnce({ status: 'ok', hardware: { tier_number: 1 } });
    await pullHuggingFaceModel('https://huggingface.co/Qwen/Qwen2.5-72B-Instruct-GGUF', true);
    expect(api.post).toHaveBeenCalledWith('/api/media/models/huggingface/pull', {
      repo_id: 'https://huggingface.co/Qwen/Qwen2.5-72B-Instruct-GGUF',
      activate: true,
    });

    // Test Split-Pane Preview Inspector
    renderAiPreviewInspector({
      file_id: 19,
      file_path: '/mnt/user/photos/red_ferrari_beach.jpg',
      file_name: 'red_ferrari_beach.jpg',
      file_category: 'photos',
      match_reason: 'Color (red) + Scene (car, beach)',
      is_favorite: true,
    });

    const inspector = document.getElementById('ai-preview-inspector-pane');
    expect(inspector.style.display).toBe('block');
    expect(inspector.innerHTML).toContain('red_ferrari_beach.jpg');
    expect(inspector.innerHTML).toContain('Open Location');
    expect(inspector.innerHTML).toContain('⭐ Favorited');
  });

  it('merges Standby-Safe Auto-Learn toggle and updates live category counts in Type pills without undefined', async () => {
    document.body.insertAdjacentHTML('beforeend', `
      <input type="checkbox" id="ai-index-respect-standby" checked />
      <div id="ai-search-filetype-bar">
        <button class="ai-filetype-chip active" data-filetype="all">All</button>
        <button class="ai-filetype-chip" data-filetype="photos">📷 Images</button>
        <button class="ai-filetype-chip" data-filetype="documents">📄 Documents</button>
      </div>
      <div id="ai-category-summary-cards"></div>
    `);

    initAiKnowledgeEngine();

    vi.spyOn(api, 'get').mockResolvedValue({ status: 'ok', hardware: { tier_number: 1 } });
    const putSpy = vi.spyOn(api, 'put').mockResolvedValueOnce({
      status: 'ok',
      config: { respect_standby: false, auto_learn_on_spinup: false },
    });
    vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      category_groups: {
        images: { count: 4872, items: [] },
        documents: { count: 132, items: [] },
        videos: { count: 0, items: [] },
      },
      results: [
        {
          file_id: 21,
          file_path: '/mnt/user/photos/pool_party.jpg',
          file_name: 'pool_party.jpg',
          file_category: 'photos',
          match_reason: 'Color (blue) + Scene (pool, outdoor, summer)',
        },
      ],
    });

    const standbyCb = document.getElementById('ai-index-respect-standby');
    standbyCb.checked = false;
    standbyCb.dispatchEvent(new Event('change'));

    await vi.waitFor(() => {
      expect(putSpy).toHaveBeenCalledWith(
        '/api/media/config',
        expect.objectContaining({
          respect_standby: false,
          auto_learn_on_spinup: false,
        })
      );
    });

    await runAiVisualSearch('pool');
    const photosChip = document.querySelector('#ai-search-filetype-bar .ai-filetype-chip[data-filetype="photos"]');
    const docsChip = document.querySelector('#ai-search-filetype-bar .ai-filetype-chip[data-filetype="documents"]');
    expect(photosChip.textContent).toContain('(4872)');
    expect(photosChip.textContent).not.toContain('undefined');
    expect(docsChip.textContent).toContain('(132)');
    expect(document.getElementById('ai-visual-results-grid').innerHTML).toContain('max-width: calc(100% - 82px)');
  });

  it('displays LLM execution telemetry proof on RAG answers and runs the AI Chatbot & NAS Copilot with hardware tools and live web browsing', async () => {
    document.body.insertAdjacentHTML('beforeend', `
      <span id="ai-active-llm-pill"><span id="ai-active-llm-label">qwen2.5:3b</span></span>
      <span id="ai-chat-active-model-badge"></span>
      <div id="ai-chat-messages-list"></div>
      <input id="ai-chat-input" value="" />
      <input type="checkbox" id="ai-chat-web-toggle" checked />
      <input type="checkbox" id="ai-chat-tools-toggle" checked />
      <button id="btn-ai-chat-send">Ask Zetty</button>
      <button id="btn-ai-chat-clear">Clear Chat</button>
    `);

    expect(SUBPANE_MAP['mgmt-pane-ai-chat']).toEqual({
      section: 'mgmt-sec-ai',
      pane: 'mgmt-pane-ai-chat',
    });

    // 1. Verify RAG Ask renders the LLM execution proof badge
    vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      query: 'garlic pasta',
      answer: 'Use 6 cloves of garlic and olive oil [1].',
      elapsed_ms: 19.4,
      hardware: { tier: 'NPU_TIER_1', active_tier: 1 },
      llm_telemetry: {
        active_model: 'Qwen/Qwen2.5-7B-Instruct-GGUF',
        accelerator_label: 'NPU_TIER_1 (Intel AI Boost NPU)',
        runtime_mode: 'Built-in ReAct + NPU/GPU Grounded Synthesis',
        tokens_per_sec: 32,
        elapsed_ms: 19.4,
      },
      citations: [
        { index: 1, file_id: 1, file_name: 'garlic_pasta.md', file_path: '/mnt/user/recipes/garlic_pasta.md', excerpt: '6 cloves garlic' },
      ],
    });

    await runAiRagAsk('garlic pasta');
    const answerContainer = document.getElementById('ai-rag-answer-container');
    expect(answerContainer.innerHTML).toContain('Qwen/Qwen2.5-7B-Instruct-GGUF');
    expect(answerContainer.innerHTML).toContain("32 tok/s");

    // 2. Verify AI Chatbot & NAS Copilot sends message, renders tool-call trace pills & verified web sources
    const chatPostSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      reply: '### 🖥️ NAS Telemetry\n- **CPU Load:** `12.4%` (`41°C`)\n- **Standby Disks:** `2` sleeping (0 wakeups)\n\n### 🌐 Web Verification\n- **Linux 6.12 LTS** is the latest long-term kernel.',
      active_model: 'Qwen/Qwen2.5-7B-Instruct-GGUF',
      elapsed_ms: 42.8,
      tools_called: [
        { tool: 'get_system_telemetry', summary: 'CPU 12.4% (41°C), RAM 6.2/32 GB', result: { status: 'ok' } },
        { tool: 'get_disks_and_standby_status', summary: '2 active, 2 sleeping in standby (0 wakeups)', result: { status: 'ok' } },
        { tool: 'browse_internet', summary: '2 web source(s) fetched for "Linux 6.12 LTS"', result: { status: 'ok' } },
      ],
      web_sources: [
        { title: 'Linux kernel — Wikipedia', url: 'https://en.wikipedia.org/wiki/Linux_kernel', snippet: 'Linux 6.12 LTS release', source: 'Wikipedia' },
      ],
      llm_telemetry: {
        active_model: 'Qwen/Qwen2.5-7B-Instruct-GGUF',
        accelerator_label: 'NPU_TIER_1 (Intel AI Boost NPU)',
        runtime_mode: 'Built-in ReAct + NPU/GPU Grounded Synthesis',
        tokens_per_sec: 32,
        elapsed_ms: 42.8,
        zero_disk_wakeups: true,
      },
    });

    await sendAiChatMessage('Check my NAS CPU/disk status and browse the web for Linux 6.12 LTS');
    expect(chatPostSpy).toHaveBeenCalledWith(
      '/api/media/chat',
      expect.objectContaining({
        message: 'Check my NAS CPU/disk status and browse the web for Linux 6.12 LTS',
        allow_web_search: true,
        allow_nas_tools: true,
      })
    );

    const chatList = document.getElementById('ai-chat-messages-list');
    expect(chatList.innerHTML).toContain('Qwen/Qwen2.5-7B-Instruct-GGUF');
    expect(chatList.innerHTML).toContain('get_system_telemetry');
    expect(chatList.innerHTML).toContain('get_disks_and_standby_status');
    expect(chatList.innerHTML).toContain('browse_internet');
    expect(chatList.innerHTML).toContain('Linux kernel — Wikipedia');
    expect(chatList.innerHTML).not.toContain('0 Wakeups');

    // 3. Clear chat history
    clearAiChatHistory();
    expect(chatList.innerHTML).toBe('');
  });

  it('identifies thinking vs standard models and renders dynamic pending state, think disclosures, and code blocks', async () => {
    // 1. Check isAiThinkingModel
    expect(isAiThinkingModel('DeepSeek-R1-Distill-Qwen-1.5B')).toBe(true);
    expect(isAiThinkingModel('Qwen/QwQ-32B')).toBe(true);
    expect(isAiThinkingModel('hf.co/ConwayResearch/Underdog-Saluki-27B')).toBe(true);
    expect(isAiThinkingModel('my-custom-cot-model')).toBe(true);
    expect(isAiThinkingModel('deepseek-llm-67b')).toBe(true);
    expect(isAiThinkingModel('Underdog-Woof-4B-1.1')).toBe(false);
    expect(isAiThinkingModel('llama3.2:3b')).toBe(false);
    expect(isAiThinkingModel('qwen2.5:3b')).toBe(false);

    // 2. Setup DOM without web or tools checkboxes to ensure default background execution
    document.body.innerHTML = `
      <div id="ai-chat-messages-list"></div>
      <input id="ai-chat-input" value="" />
      <button id="btn-ai-chat-send">Ask Zetty</button>
      <button id="btn-ai-chat-clear">Clear Chat</button>
    `;

    // 3. Test sending message with thinking tags and code blocks
    vi.spyOn(api, 'post').mockResolvedValueOnce({
      status: 'ok',
      reply: '<think>\nAnalyzing request and computing solution...\n</think>\nHere is the implementation:\n```rust\nfn main() {\n    println!("Hello ZettNAS!");\n}\n```\nSources:\n[1] Rust Documentation\n',
      active_model: 'DeepSeek-R1-Distill-Qwen-1.5B',
      elapsed_ms: 35.2,
      tools_called: [],
      web_sources: [{ title: 'Rust Docs', url: 'https://rust-lang.org', snippet: 'Rust language' }],
      llm_telemetry: {
        active_model: 'DeepSeek-R1-Distill-Qwen-1.5B',
        accelerator_label: 'GPU_TIER_2 (Intel Arc A380)',
        runtime_mode: 'Built-in ReAct + NPU/GPU Grounded Synthesis',
        tokens_per_sec: 45,
        elapsed_ms: 35.2,
      },
    });

    await sendAiChatMessage('Write a Hello World in Rust');
    const chatList = document.getElementById('ai-chat-messages-list');

    // Verify thinking disclosure rendered
    expect(chatList.innerHTML).toContain('ai-thought-disclosure');
    expect(chatList.innerHTML).toContain('Thought Process');
    expect(chatList.innerHTML).toContain('Analyzing request and computing solution...');

    // Verify code block formatted with language and copy button
    expect(chatList.innerHTML).toContain('ai-chat-code-block');
    expect(chatList.innerHTML).toContain('btn-copy-code');
    expect(chatList.innerHTML).toContain('println!("Hello ZettNAS!");');
    expect(chatList.innerHTML).toContain('rust');

    // Verify text list of Sources was stripped from answer body in favor of web pills
    expect(chatList.innerHTML).not.toContain('Sources:<br/>[1] Rust Documentation');
    expect(chatList.innerHTML).toContain('Rust Docs');
  });

  it('suppresses initial RAG image/document previews until user performs a search, and labels button Ask Zetty', async () => {
    // 1. Verify i18n label is Ask Zetty across all 5 languages
    expect(TRANSLATIONS.en['ai.chat_send_btn']).toBe('Ask Zetty');
    expect(TRANSLATIONS.de['ai.chat_send_btn']).toBe('Zetty fragen');
    expect(TRANSLATIONS.zh['ai.chat_send_btn']).toBe('询问 Zetty');
    expect(TRANSLATIONS.fr['ai.chat_send_btn']).toBe('Demander à Zetty');
    expect(TRANSLATIONS.es['ai.chat_send_btn']).toBe('Preguntar a Zetty');

    // 2. Set up RAG DOM
    document.body.innerHTML = `
      <input id="ai-rag-query-input" value="" />
      <input id="ai-visual-search-input" value="" />
      <div id="ai-visual-results-grid"></div>
      <div id="ai-rag-answer-card" style="display:block;">Previous Answer</div>
      <div id="ai-preview-inspector-pane" style="display:block;">Inspector</div>
      <div id="ai-search-split-layout" style="display:grid; grid-template-columns: minmax(0, 1fr) 360px;"></div>
      <button id="btn-ai-chat-send">Ask Zetty</button>
      <div id="ai-chat-messages-list"></div>
    `;

    // 3. Verify renderAiRagInitialEmptyState renders placeholder and hides inspector/cards
    renderAiRagInitialEmptyState();
    const grid = document.getElementById('ai-visual-results-grid');
    expect(grid.innerHTML).toContain('ai-rag-initial-placeholder');
    expect(grid.innerHTML).toContain('Search Your NAS Knowledge');
    expect(document.getElementById('ai-rag-answer-card').style.display).toBe('none');
    expect(document.getElementById('ai-preview-inspector-pane').style.display).toBe('none');

    // 4. Verify runAiVisualSearch('') does NOT call API when query and filters are empty
    const postSpy = vi.spyOn(api, 'post');
    const emptyRes = await runAiVisualSearch('');
    expect(postSpy).not.toHaveBeenCalled();
    expect(emptyRes.results).toEqual([]);
    expect(grid.innerHTML).toContain('ai-rag-initial-placeholder');

    // 5. Verify sendAiChatMessage resets button label to Ask Zetty
    postSpy.mockResolvedValueOnce({ status: 'ok', reply: 'Hello from Zetty!' });
    await sendAiChatMessage('Hi Zetty');
    expect(document.getElementById('btn-ai-chat-send').innerHTML).toContain('Ask Zetty');
  });

  it('flushAiIndex requests confirmation and flushes RAG database via /api/ai/index/flush with 5-language localization', async () => {
    // 1. Verify 5-language translations exist
    for (const lang of ['en', 'de', 'zh', 'fr', 'es']) {
      expect(TRANSLATIONS[lang]['ai.flush_index_btn']).toBeTruthy();
      expect(TRANSLATIONS[lang]['ai.flush_index_confirm_title']).toBeTruthy();
      expect(TRANSLATIONS[lang]['ai.flush_index_confirm_desc']).toBeTruthy();
      expect(TRANSLATIONS[lang]['ai.flush_index_success_toast']).toBeTruthy();
    }

    // 2. Set up DOM
    document.body.innerHTML = `
      <div id="ai-index-run-feedback"></div>
      <button id="btn-ai-flush-index">Flush Index</button>
      <div id="ai-index-db-summary"></div>
      <div id="topbar-ai-accel-pill"><span id="topbar-ai-accel-label">AI: NPU</span></div>
      <span id="mgmt-sidebar-ai-badge">NPU</span>
      <span id="mgmt-hub-ai-pill">NPU → GPU</span>
      <span id="ai-active-tier-pill"></span>
      <span id="ai-accel-device-label"></span>
      <span id="ai-stat-files">15</span>
      <span id="ai-stat-chunks">48</span>
      <span id="ai-stat-photos">12</span>
      <div id="ai-tier1-status"></div>
      <div id="ai-tier2-status"></div>
      <div id="ai-tier3-status"></div>
      <span id="ai-sync-state-badge"><span id="ai-sync-state-dot"></span><span id="ai-sync-state-text"></span></span>
      <span id="ai-index-sync-state-pill">IDLE</span>
      <span id="ai-index-current-path"></span>
      <strong id="ai-prog-indexed">15</strong>
      <strong id="ai-prog-unchanged">0</strong>
      <strong id="ai-prog-deferred">0</strong>
      <div id="ai-watched-folders-list"></div>
      <div id="ai-discovered-shares-list"></div>
    `;

    let confirmCb = null;
    let confirmOpts = null;
    const confirmSpy = vi.spyOn(toast, 'showConfirmToast').mockImplementation((title, desc, onConfirm, onCancel, opts) => {
      confirmCb = onConfirm;
      confirmOpts = opts;
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      status: 'ok',
      message: 'RAG index and vector database successfully flushed clean.',
      stats: { total_files: 0, total_chunks: 0, total_photos: 0 },
      sync_progress: { state: 'idle', indexed_files: 0 },
    });
    vi.spyOn(api, 'get').mockResolvedValue({
      status: 'ok',
      hardware: { tier_number: 1, name: 'Intel AI Boost NPU' },
      index_stats: { total_files: 0, total_chunks: 0, total_photos: 0 },
      sync_progress: { state: 'idle' },
    });

    // 3. Trigger flushAiIndex directly
    await flushAiIndex();

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining('Flush RAG Index'),
      expect.stringContaining('wipe all indexed documents'),
      expect.any(Function),
      null,
      expect.objectContaining({ isDanger: true })
    );
    expect(confirmOpts.isDanger).toBe(true);

    // 4. Simulate user confirming the dialog
    expect(confirmCb).toBeTypeOf('function');
    await confirmCb();

    expect(postSpy).toHaveBeenCalledWith('/api/ai/index/flush');
    const feedbackEl = document.getElementById('ai-index-run-feedback');
    expect(feedbackEl.textContent).toContain('flushed clean');

    // 5. Test controlAiSync('flush') and controlAiSync('clear')
    confirmSpy.mockClear();
    postSpy.mockClear();

    await controlAiSync('flush');
    expect(confirmSpy).toHaveBeenCalledTimes(1);

    await controlAiSync('clear');
    expect(confirmSpy).toHaveBeenCalledTimes(2);
  });

  it('hydrates embedding model, MRL dimension, runs benchmark and updates reindex progress UI', async () => {
    // 1. Prepare DOM elements
    const container = document.createElement('div');
    container.innerHTML = `
      <select id="ai-embedding-model-select">
        <option value="google/embeddinggemma-2">EmbeddingGemma 2 (768d)</option>
        <option value="google/embeddinggemma-2-270m">EmbeddingGemma 2 270M (512d)</option>
      </select>
      <select id="ai-mrl-dimension-select">
        <option value="768">768-dim</option>
        <option value="512">512-dim</option>
        <option value="256">256-dim</option>
        <option value="128">128-dim</option>
      </select>
      <button id="btn-ai-run-benchmark">Run AI Latency & Throughput Benchmark</button>
      <div id="ai-benchmark-results-card" style="display: none;">
        <span id="bm-latency">--</span>
        <span id="bm-throughput">--</span>
        <span id="bm-tokens">--</span>
        <span id="bm-accel">--</span>
      </div>
      <div id="ai-reindex-progress-container" style="display: none;">
        <div id="ai-reindex-progress-bar" style="width: 0%;"></div>
        <span id="ai-reindex-pct-label">0%</span>
        <span id="ai-reindex-speed-label">0 chunks/s</span>
        <span id="ai-reindex-eta-label">ETA: --</span>
      </div>
    `;
    document.body.appendChild(container);

    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      status: 'ok',
      hardware: { tier_number: 1, name: 'Intel AI Boost NPU' },
      index_stats: { total_files: 10, total_chunks: 50, total_photos: 5 },
      config: {
        embedding_model: 'google/embeddinggemma-2-270m',
        embedding_dim: 512,
      },
      sync_progress: { state: 'idle' },
    });

    const postSpy = vi.spyOn(api, 'post').mockImplementation(async (url, payload) => {
      if (url === '/api/ai/benchmark') {
        return {
          status: 'ok',
          latency_ms: 18.5,
          throughput_chunks_sec: 54.05,
          tokens_per_sec: 1420.2,
          accelerator: 'NPU Tier 1 (Intel AI Boost)',
          zero_disk_wakeups: true,
        };
      }
      return { status: 'ok' };
    });

    // 2. Fetch and render status
    await fetchAndRenderAiStatus();

    const embSelect = document.getElementById('ai-embedding-model-select');
    const mrlSelect = document.getElementById('ai-mrl-dimension-select');
    expect(embSelect.value).toBe('google/embeddinggemma-2-270m');
    expect(mrlSelect.value).toBe('512');

    // 3. Test changing embedding model & MRL dim
    embSelect.value = 'google/embeddinggemma-2';
    embSelect.dispatchEvent(new Event('change'));
    expect(postSpy).toHaveBeenCalledWith('/api/ai/config', { embedding_model: 'google/embeddinggemma-2' });

    mrlSelect.value = '256';
    mrlSelect.dispatchEvent(new Event('change'));
    expect(postSpy).toHaveBeenCalledWith('/api/ai/config', { embedding_dim: 256 });

    // 4. Test running benchmark
    const btnBenchmark = document.getElementById('btn-ai-run-benchmark');
    await btnBenchmark.click();

    expect(postSpy).toHaveBeenCalledWith('/api/ai/benchmark');
    const card = document.getElementById('ai-benchmark-results-card');
    expect(card.style.display).toBe('grid');
    expect(document.getElementById('bm-latency').textContent).toBe('18.5 ms');
    expect(document.getElementById('bm-throughput').textContent).toBe('54.05 chunks/s');
    expect(document.getElementById('bm-tokens').textContent).toBe('1420.2 tok/s');
    expect(document.getElementById('bm-accel').textContent).toBe('NPU Tier 1 (Intel AI Boost)');

    // 5. Test updateAiReindexProgress helper
    updateAiReindexProgress({
      total: 200,
      completed: 100,
      speed: 25.4,
      eta_sec: 4,
    });
    const progContainer = document.getElementById('ai-reindex-progress-container');
    expect(progContainer.style.display).toBe('block');
    expect(document.getElementById('ai-reindex-progress-bar').style.width).toBe('50%');
    expect(document.getElementById('ai-reindex-pct-label').textContent).toBe('50%');
    expect(document.getElementById('ai-reindex-speed-label').textContent).toBe('25.4 chunks/s');
    expect(document.getElementById('ai-reindex-eta-label').textContent).toBe('ETA: 4s');

    // Test idle/complete hides progress
    updateAiReindexProgress({ status: 'idle' });
    expect(progContainer.style.display).toBe('none');

    // Cleanup
    document.body.removeChild(container);
  });
});
