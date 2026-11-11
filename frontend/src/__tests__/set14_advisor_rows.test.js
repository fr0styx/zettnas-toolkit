// SET-14: every row of the security check leads somewhere.
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn().mockResolvedValue({ checks: [], issues: [] }), post: vi.fn().mockResolvedValue({ message: 'Fixed.' }) } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showDangerConfirm: vi.fn() }));
const { api } = await import('../api.js');
const { FIXABLE, handleSecurityAdvisorClick } = await import('../components/management/security.js');

describe('the rows of the security check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.openManagementWindow = vi.fn();
  });

  it('a row with a one-click fix offers the fix', async () => {
    for (const id of FIXABLE) handleSecurityAdvisorClick(id);
    await Promise.resolve();
    expect(api.post.mock.calls.map((c) => c[0])).toEqual(FIXABLE.map((id) => `/api/system/security-posture/fix/${id}`));
  });

  it('every other row opens a place; none does nothing', () => {
    for (const id of ['ldap_plaintext', 'ldap_unverified', 'sso_http_issuer', 'proxy_sso_local_accounts', 'something_new']) {
      handleSecurityAdvisorClick(id);
    }
    expect(window.openManagementWindow).toHaveBeenCalledTimes(5);
    expect(window.openManagementWindow).toHaveBeenLastCalledWith('mgmt-sec-system-group', 'mgmt-pane-security');
    handleSecurityAdvisorClick('ai_runtime_exposure');
    expect(window.openManagementWindow).toHaveBeenLastCalledWith('mgmt-sec-ai', 'mgmt-pane-ai-rag');
  });

  it('the fixable list matches the server\'s fixes', async () => {
    const { readFileSync } = await import('node:fs');
    const server = readFileSync('backend/services/safe_defaults_advisor.py', 'utf8');
    const fixes = [...server.matchAll(/"fix": "([a-z_]+)"/g)].map((m) => m[1]);
    expect([...fixes].sort()).toEqual([...FIXABLE].sort());
  });
});
