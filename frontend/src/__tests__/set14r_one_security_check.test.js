import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { setLanguage } from '../i18n.js';
import { checkState, fetchAndRenderSecurityPosture } from '../components/management/security.js';

afterEach(async () => {
  vi.restoreAllMocks();
  await setLanguage('en');
});

const ROWS = [
  { id: 'default_password', name: 'Default Administrator Password', passed: true, penalty: 0, severity: 'info', details: 'Custom administrator password set' },
  { id: 'sec_default_admin', name: "Default 'admin' account", passed: false, penalty: 0, severity: 'low', details: 'still on' },
  { id: 'admin_mfa', name: 'Administrator Two-Factor Authentication (2FA)', passed: false, penalty: 15, severity: 'high', details: 'lack' },
];

describe('one security check (SET-14)', () => {
  it('a row is passed, a suggestion or a finding', () => {
    expect(ROWS.map(checkState)).toEqual(['ok', 'tip', 'look']);
    // a low finding that costs points is a finding, not a suggestion (unused app keys, snapshots off)
    expect(checkState({ passed: false, penalty: 15, severity: 'low' })).toBe('look');
  });

  it('the rows say their state in the reader\'s language', async () => {
    document.body.innerHTML = '<span id="sec-advisor-score-badge"></span><div id="sec-advisor-items"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ score: 85, grade: 'B', checks: ROWS, issues: [] });
    await setLanguage('de');
    await fetchAndRenderSecurityPosture();
    const words = [...document.querySelectorAll('.sec-advisor-status-badge')].map((e) => e.textContent);
    expect(words).toEqual(['Bestanden', 'Vorschlag', 'Handlungsbedarf']);
    expect(document.getElementById('sec-advisor-items').textContent).not.toMatch(/PASSED|NEEDS ACTION/);
  });
});
