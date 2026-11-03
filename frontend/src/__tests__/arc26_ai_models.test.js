/** ARC-26: the AI model list: which models show, in which order, and the one in use. */
import { describe, it, expect, beforeEach } from 'vitest';
import { renderAiLlmRecommendations } from '../components/management/ai.js';

const byId = (id) => document.getElementById(id);
const order = () => [...byId('ai-top-model-select').options].map((o) => o.value);
const sortBy = (v) => {
  byId('ai-models-sort-select').value = v;
  byId('ai-models-sort-select').dispatchEvent(new Event('change'));
};
const MODELS = [
  { id: 'a', name: 'A', release_timestamp: 1_780_000_000, downloads: 10, est_ram_gb: 8, recommended: false },
  { id: 'b', name: 'B', release_timestamp: 1_770_000_000, downloads: 900, est_ram_gb: 2, recommended: true, target_device: 'GPU (iGPU)/x' },
  { id: 'c', name: 'C', release_timestamp: 1_775_000_000, downloads: 50, vram_or_ram_gb: 4 },
  { id: 'old', name: 'Old', release_timestamp: 1_740_000_000 },
  { id: 'big', name: 'Big', release_timestamp: 1_781_000_000, fits_hardware: false },
  { id: 'old2', name: 'Old2', release_date_str: 'March 2025' },
];

describe('AI model list', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <span id="ai-llm-advisor-headline"></span><span id="ai-llm-advisor-summary"></span>
      <select id="ai-models-sort-select"><option value="date">d</option><option value="recommended">r</option><option value="downloads">n</option><option value="size_asc">s</option><option value="size_desc">S</option></select>
      <select id="ai-top-model-select"></select><div id="ai-llm-recommendations-grid"></div>
      <span id="ai-active-llm-label"></span><span id="ai-active-llm-pill"></span><span id="ai-chat-active-model-badge"></span>
      <button class="ai-hf-filter-btn" data-hf-filter="all"></button><button class="ai-hf-filter-btn" data-hf-filter="compatible"></button>
      <button class="ai-hf-filter-btn" data-hf-filter="warning"></button>`;
  });

  it('shows 2026 models that fit, newest first, and the one in use', () => {
    renderAiLlmRecommendations({ models: MODELS, headline: 'Good fit', hardware_summary: '16 GB RAM' }, 'b');
    expect(order()).toEqual(['a', 'c', 'b']);
    expect(byId('ai-top-model-select').value).toBe('b');
    expect(byId('ai-llm-advisor-headline').textContent).toBe('Good fit');
    expect(byId('ai-active-llm-label').textContent).toBe('b');
    expect(byId('ai-chat-active-model-badge').textContent).toBe('🤖 b (GPU)');
    expect(document.querySelector('[data-hf-filter="warning"]').style.display).toBe('none');
    expect(document.querySelector('[data-hf-filter="all"]').textContent).toContain('3');
    expect(byId('ai-llm-recommendations-grid').children.length).toBe(3);
  });

  it('keeps a model that does not fit when it is the one in use', () => {
    renderAiLlmRecommendations({ models: MODELS }, 'big');
    expect(order()).toContain('big');
  });

  it('sorts by recommendation, downloads and size', () => {
    renderAiLlmRecommendations({ models: MODELS }, 'a');
    sortBy('recommended');
    expect(order()[0]).toBe('b');
    sortBy('downloads');
    expect(order()).toEqual(['b', 'c', 'a']);
    sortBy('size_asc');
    expect(order()).toEqual(['b', 'c', 'a']);
    sortBy('size_desc');
    expect(order()).toEqual(['a', 'c', 'b']);
    sortBy('date');
    expect(order()).toEqual(['a', 'c', 'b']);
  });

  it('stays empty without models', () => {
    renderAiLlmRecommendations({ models: [] }, '');
    expect(byId('ai-llm-recommendations-grid').innerHTML).toBe('');
    renderAiLlmRecommendations();
  });
});
