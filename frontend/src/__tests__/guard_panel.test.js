import { describe, it, expect, vi, beforeEach } from 'vitest';

const calls = [];
vi.mock('../api.js', () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === '/api/security/ransomware') {
        return { enabled: true, canaries: false, canary_count: 0, frozen: true, frozen_at: 1761100000, reason: '150 renames or deletes in 60 seconds', source: { user: 'bob', ip: '192.168.1.50' } };
      }
      return [{ ip: '192.168.1.50', reason: 'ransomware guard', until: 1761186400 }];
    }),
    put: vi.fn(async (...a) => calls.push(['put', ...a])),
    post: vi.fn(async (...a) => calls.push(['post', ...a])),
    delete: vi.fn(async (...a) => calls.push(['delete', ...a])),
  },
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

describe('ransomware guard panel (M4, M5)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="sec-guard-card"></div>';
    calls.length = 0;
  });

  it('shows the freeze with its source and lists blocked addresses', async () => {
    const { renderGuardPanel } = await import('../components/guard-panel.js');
    await renderGuardPanel();
    const card = document.getElementById('sec-guard-card');
    expect(card.querySelector('[role="alert"]').textContent).toContain('192.168.1.50');
    expect(card.querySelector('.guard-blocks code').textContent).toBe('192.168.1.50');
    card.querySelector('.guard-blocks button').click();
    await vi.waitFor(() => expect(calls).toContainEqual(['delete', '/api/security/ip-blocks/192.168.1.50']));
  });

  it('saves the guard-file toggle', async () => {
    const { renderGuardPanel } = await import('../components/guard-panel.js');
    await renderGuardPanel();
    const boxes = document.querySelectorAll('#sec-guard-card input[type="checkbox"]');
    boxes[1].checked = true;
    boxes[1].dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(calls).toContainEqual(['put', '/api/security/ransomware', { canaries: true }]));
  });
});
