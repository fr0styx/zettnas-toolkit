import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { fetchAndRenderSecurityPosture } from '../components/management/security.js';

afterEach(() => vi.restoreAllMocks());

describe('security check rows (SET-14, Settings finding 25)', () => {
  it('a row is no button; Review / Configure is one, named after its row', async () => {
    document.body.innerHTML = '<span id="sec-advisor-score-badge"></span><div id="sec-advisor-items"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ score: 80, grade: 'B', checks: [
      { id: 'snapshots_off', name: 'Some shared folders have no snapshots', passed: false, penalty: 5, severity: 'low', details: 'x', fix: 'snapshots_off' },
    ] });
    await fetchAndRenderSecurityPosture();
    const row = document.querySelector('.sec-advisor-item');
    expect(row.getAttribute('role')).toBeNull();
    expect(row.hasAttribute('tabindex')).toBe(false);
    const action = row.querySelector('button.sec-advisor-action-pill');
    expect(action).not.toBeNull();
    expect(action.getAttribute('aria-label')).toBe('Configure: Some shared folders have no snapshots');
    expect(row.querySelectorAll('button')).toHaveLength(2); // the fix and the action, side by side
  });
});
