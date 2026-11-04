// AI-21: a citation from a PDF says which page it is on.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { citationPage, runAiRagAsk, selectAiConversation } from '../components/management/ai.js';
import { api } from '../api.js';

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '';
});

describe('citation pages (AI-21)', () => {
  it('names the page of a PDF passage and nothing otherwise', () => {
    expect(citationPage({ page: 4 })).toBe('p. 4');
    expect(citationPage({ page: 0 })).toBe('');
    expect(citationPage({})).toBe('');
  });

  it('shows the page on search and chat sources', async () => {
    const cite = { path: '/srv/lease.pdf', name: 'lease.pdf', breadcrumb: 'Rent', excerpt: 'Rent is due monthly.', score: 0.9, page: 3 };
    document.body.innerHTML = `<input id="ai-rag-query-input"><select id="ai-rag-scope-select"><option value="all" selected>all</option></select>
      <button id="btn-ai-rag-ask"></button><div id="ai-rag-empty-state"></div><div id="ai-rag-answer-container"></div>
      <div id="ai-rag-answer-card"></div><div id="ai-rag-structured-card"></div><div id="ai-rag-citations-grid"></div>
      <div id="ai-chat-active-title"></div><div id="ai-chat-messages-list"></div>`;
    vi.spyOn(api, 'post').mockResolvedValue({ answer_markdown: 'Monthly [1].', citations: [cite] });
    await runAiRagAsk('when is rent due?');
    expect(document.querySelector('.ai-citation-card').textContent).toContain('Rent · p. 3');
    vi.spyOn(api, 'get').mockResolvedValue({ conversation: { id: 'r1', title: 'Rent', messages: [
      { role: 'user', content: 'Rent?' }, { role: 'assistant', content: 'Monthly [1].', citations: [cite] }] } });
    await selectAiConversation('r1');
    expect(document.getElementById('ai-chat-messages-list').textContent).toContain('Rent · p. 3');
  });
});
