import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

describe('restoring a machine backup (SET-14, VMs 13)', () => {
  it('the page passes on the confirmation it asked for', () => {
    const src = readFileSync('frontend/src/components/vm/snapshots.js', 'utf8');
    expect(src).toMatch(/backups\/\$\{encodeURIComponent\(bId\)\}\/restore`, \{\}, \{ confirmed: true \}/);
  });
});
