import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

describe('the Apprise dialog keeps its switch (SET-14, Settings 1)', () => {
  const src = readFileSync('frontend/src/components/management/notifications.js', 'utf8');
  it('reads, saves and shows the switch', () => {
    expect(src).toContain('cfg.apprise_enabled = enabled;');
    expect(src).toMatch(/\.checked = cfg\.apprise_enabled !== false;/);
    expect(src).toContain("rawCount > 0 && cfg.apprise_enabled !== false");
  });
});
