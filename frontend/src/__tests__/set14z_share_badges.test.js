import { describe, it, expect, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { setLanguage } from '../i18n.js';
import { shareSecurityBadge } from '../components/chassis-visualizer.js';

afterEach(async () => {
  await setLanguage('en');
});

describe('share badges and Create Share (SET-14, Shares 18 and 19)', () => {
  it('private is the safe state, no password the warning, both in words', async () => {
    expect(shareSecurityBadge('private')).toContain('sec-private');
    expect(shareSecurityBadge('private')).toContain('Private');
    expect(shareSecurityBadge('public')).toContain('sec-public');
    expect(shareSecurityBadge('public')).toContain('No password');
    expect(shareSecurityBadge('secure')).toContain('sec-private');
    await setLanguage('de');
    expect(shareSecurityBadge('public')).toContain('Kein Passwort');
    expect(shareSecurityBadge('private')).not.toMatch(/PRIVATE|PUBLIC/);
  });

  it('the warning colour belongs to no password', () => {
    const css = readFileSync('frontend/src/styles/29-storage-pools-remote.css', 'utf8');
    const rule = (sel) => css.slice(css.indexOf(sel), css.indexOf('}', css.indexOf(sel)));
    expect(rule('.share-sec-badge.sec-public {')).toContain('245, 166, 35');
    expect(rule('.share-sec-badge.sec-secure {')).toContain('59, 245, 139');
  });

  it('Create Share is wired in one place', () => {
    const mg = readFileSync('frontend/src/components/management.js', 'utf8');
    expect(mg).not.toContain("getElementById('btn-create-network-share')");
  });
});
