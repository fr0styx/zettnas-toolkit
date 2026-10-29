/** ARC-31: the type-check ratchet reads tsc's output per file and fails only on files that got worse. */
import { describe, it, expect } from 'vitest';
import { perFile, over } from '../../scripts/checkjs-ratchet.mjs';

describe('checkJs ratchet (ARC-31)', () => {
  it('counts errors per file', () => {
    const out = [
      "frontend/src/a.js(3,7): error TS2339: Property 'x' does not exist on type 'Y'.",
      'frontend/src/a.js(9,1): error TS2554: Expected 1 arguments, but got 2.',
      'frontend/src/b.js(1,1): error TS7006: Parameter implicitly has an any type.',
      'Found 3 errors.',
    ].join('\n');
    expect(perFile(out)).toEqual({ 'frontend/src/a.js': 2, 'frontend/src/b.js': 1 });
  });

  it('fails only on files above their baseline, new files start at zero', () => {
    expect(over({ 'a.js': 2, 'b.js': 1 }, { 'a.js': 3, 'b.js': 1 })).toEqual([]);
    expect(over({ 'a.js': 4 }, { 'a.js': 3 })).toEqual(['a.js: 4 type errors (baseline 3)']);
    expect(over({ 'new.js': 1 }, {})).toEqual(['new.js: 1 type errors (baseline 0)']);
  });
});
