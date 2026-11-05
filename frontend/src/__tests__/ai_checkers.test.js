import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { bindCheckersForm } = await import('../components/management/ai-checkers.js');

const FORM = `<form id="ai-rerank-form">
  <input id="ai-rerank-endpoint"><input id="ai-rerank-model">
</form>`;
const tick = () => new Promise((r) => setTimeout(r, 0));

describe('The reranker in AI settings', () => {
  beforeEach(() => {
    document.body.innerHTML = FORM;
    vi.clearAllMocks();
  });

  it('shows what is saved and empty fields for what is not', () => {
    bindCheckersForm(document, { rerank_endpoint: 'http://zettnas-xenc:8000/v3/rerank', rerank_model: null });
    expect(document.getElementById('ai-rerank-endpoint').value).toBe('http://zettnas-xenc:8000/v3/rerank');
    expect(document.getElementById('ai-rerank-model').value).toBe('');
  });

  it('saves both with one button, once however often the pane opens', async () => {
    api.post.mockResolvedValue({});
    bindCheckersForm(document, {});
    bindCheckersForm(document, {});
    document.getElementById('ai-rerank-endpoint').value = ' http://zettnas-xenc:8000/v3/rerank ';
    document.getElementById('ai-rerank-form').dispatchEvent(new Event('submit', { cancelable: true }));
    await tick();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith('/api/ai/config', {
      rerank_endpoint: 'http://zettnas-xenc:8000/v3/rerank',
      rerank_model: '',
    });
    expect(showToast).toHaveBeenCalledWith('Reranker saved', 'success');
  });

  it('says why when saving fails, and does nothing without the form', async () => {
    api.post.mockRejectedValue(new Error('The reranker must be an http(s) URL.'));
    bindCheckersForm(document, {});
    document.getElementById('ai-rerank-form').dispatchEvent(new Event('submit', { cancelable: true }));
    await tick();
    expect(showToast.mock.calls[0][0]).toContain('must be an http(s) URL');
    document.body.innerHTML = '';
    expect(() => bindCheckersForm(document, {})).not.toThrow();
  });

  it('works with a page that has only the address field', async () => {
    document.getElementById('ai-rerank-model').remove();
    api.post.mockResolvedValue({});
    bindCheckersForm(document, { rerank_model: 'bge-reranker-v2-m3' });
    document.getElementById('ai-rerank-form').dispatchEvent(new Event('submit', { cancelable: true }));
    await tick();
    expect(api.post).toHaveBeenCalledWith('/api/ai/config', { rerank_endpoint: '' });
  });
});
