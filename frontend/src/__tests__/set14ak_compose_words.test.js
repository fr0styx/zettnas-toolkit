import { describe, it, expect, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { lintCompose, composeRiskSummary } from '../compose-lint.js';

afterEach(async () => {
  await setLanguage('en');
});

describe('the Compose safety check in the reader\'s language (SET-14, Apps)', () => {
  it('English stays as it was', () => {
    const f = lintCompose('services:\n  a:\n    privileged: true\n');
    expect(f[0].text).toBe('privileged: full access to the host');
    expect(composeRiskSummary(f)).toBe('Line 3: privileged: full access to the host');
  });

  it('German', async () => {
    await setLanguage('de');
    const f = lintCompose('    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock\n');
    expect(composeRiskSummary(f)).toMatch(/^Zeile 2: bindet den Docker-Socket ein/);
  });
});
