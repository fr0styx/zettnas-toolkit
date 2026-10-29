import { describe, it, expect, vi, beforeEach } from 'vitest';

const posts = [];
vi.mock('../api.js', () => ({
  api: {
    get: vi.fn(async () => ({
      results: [
        { name: 'qwen2.5:3b', ok: true, tokens_per_s: 45, first_token_s: 1.2, doc_first_token_s: 26.6, placement: 'CPU' },
        { name: 'gemma3:12b', ok: true, tokens_per_s: 18, first_token_s: 2.5, placement: 'GPU' },
      ],
      finished_at: 1761100000,
      recommended: { fast: 'qwen2.5:3b', balanced: 'gemma3:12b' },
      job: { state: 'done' },
    })),
    post: vi.fn(async (...a) => {
      posts.push(a);
      return { active_model: 'gemma3:12b' };
    }),
  },
}));
const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast }));

describe('model benchmark card (D2)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="ai-model-bench-card" hidden></div>';
    posts.length = 0;
  });

  it('lists results and applies the balanced tier', async () => {
    const { renderModelBench } = await import('../components/model-bench.js');
    await renderModelBench();
    const card = document.getElementById('ai-model-bench-card');
    expect(card.hidden).toBe(false);
    expect(card.querySelectorAll('.zn-table tr').length).toBe(3);
    // the long document question: measured for the first model, a dash where it is missing
    const rows = [...card.querySelectorAll('.zn-table tr')].map((tr) => [...tr.children].map((c) => c.textContent));
    expect(rows[0]).toContain('Long question');
    expect(rows[1][3]).toBe('26.6 s');
    expect(rows[2][3]).toBe('—');
    const use = [...card.querySelectorAll('.zn-row button')].find((b) => b.textContent.includes('balanced'));
    use.click();
    await vi.waitFor(() => expect(posts).toContainEqual(['/api/ai/models/benchmark/apply', { tier: 'balanced' }]));
    // the click handler finishes with its message; let that and anything it logs settle before the
    // worker closes (a log still in flight at teardown fails the whole run)
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining('gemma3:12b'), 'success'));
    await new Promise((r) => setTimeout(r, 50));
  });
});
