import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(p, 'utf8');

describe('no invented power values (SET-15, Power B5)', () => {
  it('the page, the top bar and the widget never fill in 120 V, 900 W or 100 %', () => {
    const ups = read('frontend/src/components/management/ups.js');
    expect(ups).not.toContain("'120.0 V'");
    expect(ups).not.toContain('|| 900');
    expect(ups).not.toMatch(/battery_charge_pct : 100\)/);
    expect(read('frontend/src/components/dashboard.js')).not.toMatch(/ups\.charge \?\? 100/);
    expect(read('frontend/src/components/widgets.js')).not.toMatch(/ups\.charge \?\? 100/);
    expect(read('frontend/src/components/widgets.js')).not.toContain("stats.ups.status || 'ONLINE'");
  });
});
