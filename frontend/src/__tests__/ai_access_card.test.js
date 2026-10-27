import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
const { api } = await import('../api.js');
const { installAiAccess, renderAiAccess, logHtml } = await import('../components/management/ai-access.js');
const { explain } = await import('../error-text.js');

const ACCESS = {
  roles: [
    { id: 'superadmin', name: 'SuperAdmin', on: true, locked: true },
    { id: 'share_user', name: 'ShareUser', on: true, locked: false },
    { id: 'kid', name: 'Kid', on: false, locked: false },
  ],
  log_days: 90,
};
const LOG = [{ ts: 1700000000, username: 'lea', role: 'kid', model: '', web: false, outcome: 'refused', ms: 0 }];

describe('Who can use Zetty', () => {
  beforeEach(() => {
    document.body.innerHTML = '<form id="ai-rerank-form"></form>';
    vi.clearAllMocks();
  });

  it('shows a switch per role, kids off and the superadmin locked on', () => {
    const card = document.createElement('div');
    renderAiAccess(card, ACCESS, LOG);
    const kid = card.querySelector('[data-ai-role="kid"]');
    const admin = card.querySelector('[data-ai-role="superadmin"]');
    expect(kid.checked).toBe(false);
    expect(admin.checked && admin.disabled).toBe(true);
    expect(card.textContent).toContain('Who asked Zetty');
    expect(card.textContent).toContain('lea (kid)');
    expect(card.textContent).toContain('Turned off for them');
  });

  it('saves a switch and shows the answer', async () => {
    api.put.mockResolvedValue({ ...ACCESS, roles: ACCESS.roles.map((r) => (r.id === 'kid' ? { ...r, on: true } : r)) });
    const card = document.createElement('div');
    renderAiAccess(card, ACCESS, LOG);
    const kid = card.querySelector('[data-ai-role="kid"]');
    kid.checked = true;
    kid.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 0));
    expect(api.put).toHaveBeenCalledWith('/api/ai/access', { roles: { kid: true } });
    expect(card.querySelector('[data-ai-role="kid"]').checked).toBe(true);
  });

  it('puts back a switch the server refused', async () => {
    api.put.mockRejectedValue(new Error('no'));
    const card = document.createElement('div');
    renderAiAccess(card, ACCESS, LOG);
    const kid = card.querySelector('[data-ai-role="kid"]');
    kid.checked = true;
    kid.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 0));
    expect(kid.checked).toBe(false);
  });

  it('is added under the reranker for administrators only', async () => {
    api.get.mockImplementation(async (url) => (url.startsWith('/api/ai/access') ? ACCESS : { requests: LOG }));
    await installAiAccess(document);
    expect(document.getElementById('ai-access-card')).not.toBeNull();
    document.body.innerHTML = '<form id="ai-rerank-form"></form>';
    api.get.mockRejectedValue(new Error('403'));
    await installAiAccess(document);
    expect(document.getElementById('ai-access-card')).toBeNull();
  });

  it('escapes names from the log and says so when it is empty', () => {
    expect(String(logHtml([{ ...LOG[0], username: '<b>x</b>' }]))).not.toContain('<b>x</b>');
    expect(String(logHtml([]))).toContain('Nobody has asked Zetty yet');
  });

  it('tells someone whose role is off what to do', () => {
    expect(explain('anything', 'ai_off_for_role')).toContain('An administrator can turn it on in AI settings');
  });
});
