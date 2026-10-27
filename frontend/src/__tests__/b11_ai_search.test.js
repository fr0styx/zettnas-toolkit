import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
const { api } = await import('../api.js');
const { renderAiAccess, logHtml } = await import('../components/management/ai-access.js');

const ACCESS = {
  roles: [
    { id: 'superadmin', name: 'SuperAdmin', on: true, search: true, locked: true },
    { id: 'kid', name: 'Kid', on: false, search: true, locked: false },
  ],
  log_days: 90,
};

describe('B11 (AI-26): Ask Zetty and AI search per role', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows both switches for each role', () => {
    const card = document.createElement('div');
    renderAiAccess(card, ACCESS, []);
    const ask = card.querySelector('[data-ai-role="kid"][data-ai-feature="roles"]');
    const search = card.querySelector('[data-ai-role="kid"][data-ai-feature="search_roles"]');
    expect([ask.checked, search.checked]).toEqual([false, true]);
    expect(card.querySelector('[data-ai-role="superadmin"][data-ai-feature="search_roles"]').disabled).toBe(true);
  });

  it('saves the AI search switch on its own', async () => {
    api.put.mockResolvedValue(ACCESS);
    const card = document.createElement('div');
    renderAiAccess(card, ACCESS, []);
    const search = card.querySelector('[data-ai-role="kid"][data-ai-feature="search_roles"]');
    search.checked = false;
    search.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 0));
    expect(api.put).toHaveBeenCalledWith('/api/ai/access', { search_roles: { kid: false } });
  });

  it('the log says what kind of request it was', () => {
    const div = document.createElement('div');
    div.innerHTML = String(logHtml([{ ts: 1700000000, username: 'lea', role: 'kid', kind: 'search', model: '', web: false, outcome: 'refused' }]));
    expect(div.textContent).toContain('Search');
  });
});
