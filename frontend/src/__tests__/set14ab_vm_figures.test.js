import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { hasMeasuredLoad } from '../components/vm-manager.js';

describe('no invented figures on a machine card (SET-14, VMs 17)', () => {
  it('meters only for measured figures', () => {
    expect(hasMeasuredLoad({ cpu_usage_pct: 12, ram_usage_pct: 40 })).toBe(true);
    expect(hasMeasuredLoad({ state: 'running', ram_gb: 4 })).toBe(false);
    expect(hasMeasuredLoad(null)).toBe(false);
  });

  it('the phone menu reads the memory the server sends', () => {
    const src = readFileSync('frontend/src/components/vm-manager.js', 'utf8');
    expect(src).not.toContain('memory_mb || 2048');
  });
});
