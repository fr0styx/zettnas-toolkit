// NUX-15: the AI answers (knowledge search, chat replies, chat markdown) use classes from
// Mission Control's sheet instead of inline styles; each part still renders with them.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { runAiRagAsk, selectAiConversation, _formatChatMarkdown } from '../components/management/ai.js';
import { api } from '../api.js';

beforeEach(() => {
  vi.restoreAllMocks();
});
afterEach(() => {
  document.body.innerHTML = '';
});

describe('AI answers on classes (NUX-15)', () => {
  it('shows a recipe card in a knowledge answer', async () => {
    document.body.innerHTML = `<input id="ai-rag-query-input"><select id="ai-rag-scope-select"><option value="all" selected>all</option></select>
      <button id="btn-ai-rag-ask"></button><div id="ai-rag-empty-state"></div><div id="ai-rag-answer-container"></div>
      <div id="ai-rag-answer-card"></div><div id="ai-rag-structured-card"></div><div id="ai-rag-citations-grid"></div>`;
    vi.spyOn(api, 'post').mockResolvedValue({
      answer_markdown: 'Mix it.', citations: [],
      structured_cards: [{ type: 'recipe', title: 'Pancakes', ingredients: ['flour'], steps: ['Fry'], prep_time: '5 min' }, { type: 'recipe' }],
    });
    await runAiRagAsk('pancakes');
    const html = document.body.innerHTML;
    expect(html).toContain('ai-structured-recipe-card');
    const titles = new Set([...document.querySelectorAll('.airg-fs135-bold-strong')].map((n) => n.textContent));
    expect([...titles].sort()).toEqual(['Pancakes', 'Structured Recipe Card']);
  });

  it('shows photo cards in a saved chat, with and without a thumbnail', async () => {
    document.body.innerHTML = '<div id="ai-chat-active-title"></div><div id="ai-chat-messages-list"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({
      conversation: { id: 'p1', title: 'Beach', messages: [
        { role: 'user', content: 'Beach photos?' },
        { role: 'assistant', content: 'Two photos.', photos: [{ path: '/srv/a.jpg', name: 'a.jpg', file_id: 7 }, { path: '/srv/b.jpg', name: 'b.jpg' }] },
      ] },
    });
    await selectAiConversation('p1');
    const cards = document.querySelectorAll('.ai-chat-photo-card');
    expect(cards).toHaveLength(2);
    expect(cards[0].querySelector('img.aicm-size').getAttribute('src')).toBe('/api/media/thumbnail/7');
    expect(cards[1].querySelector('.aicm-row-fs20')).not.toBeNull();
  });

  it('turns file references into links, with and without a line', () => {
    const html = _formatChatMarkdown('See [^1: /srv/notes.txt#L12] and [^2: /srv/todo.md].');
    const box = document.createElement('div');
    box.innerHTML = html;
    const pills = box.querySelectorAll('.ai-citation-inline-pill');
    expect([...pills].map((p) => p.dataset.path)).toEqual(['/srv/notes.txt', '/srv/todo.md']);
    expect(pills[0].textContent).toContain('L12');
  });
});
