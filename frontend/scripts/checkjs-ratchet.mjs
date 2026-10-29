// Type checking of the frontend (ARC-31): TypeScript checks the plain JavaScript (jsconfig.json,
// checkJs) and this script holds each file to the number of errors it has today. A file may only
// go down; a new file starts at zero. JSDoc types (/** @param {string} name */) are the usual fix.
//
//   npm run lint:types                 fail when a file has more errors than its baseline
//   npm run lint:types -- --list FILE  show the errors in one file
//   npm run lint:types -- --update     record the lower numbers after a clean-up
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = process.cwd();
const BASELINE = join(ROOT, 'frontend/scripts/checkjs-baseline.json');

/** "frontend/src/x.js(12,5): error TS2339: ..." lines -> { file: count } */
export function perFile(output) {
  const counts = {};
  for (const line of String(output).split('\n')) {
    const m = /^(.+?\.js)\(\d+,\d+\): error TS\d+:/.exec(line.trim());
    if (m) counts[m[1]] = (counts[m[1]] || 0) + 1;
  }
  return counts;
}

export function over(now, base) {
  return Object.entries(now)
    .filter(([file, n]) => n > (base[file] ?? 0))
    .map(([file, n]) => `${file}: ${n} type errors (baseline ${base[file] ?? 0})`);
}

function run() {
  try {
    return execFileSync(join(ROOT, 'node_modules/.bin/tsc'), ['-p', 'jsconfig.json', '--pretty', 'false'], {
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
    });
  } catch (e) {
    return String(e.stdout || '') + String(e.stderr || ''); // tsc exits 2 when it finds errors
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const out = run();
  const now = perFile(out);
  const list = process.argv.indexOf('--list');
  if (list > 0) {
    const want = process.argv[list + 1] || '';
    for (const line of out.split('\n')) if (line.startsWith(want)) console.log(line);
    process.exit(0);
  }
  const total = Object.values(now).reduce((a, b) => a + b, 0);
  if (process.argv.includes('--update')) {
    const sorted = Object.fromEntries(Object.entries(now).sort(([a], [b]) => a.localeCompare(b)));
    writeFileSync(BASELINE, JSON.stringify(sorted, null, 1) + '\n');
    console.log(`checkjs baseline: ${total} errors in ${Object.keys(now).length} files`);
    process.exit(0);
  }
  const base = JSON.parse(readFileSync(BASELINE, 'utf8'));
  const problems = over(now, base);
  for (const p of problems) console.error(`✗ ${p}`);
  if (problems.length) {
    console.error('Add JSDoc types or fix the code; npm run lint:types -- --list <file> shows the errors.');
    process.exit(1);
  }
  const baseTotal = Object.values(base).reduce((a, b) => a + b, 0);
  console.log(`✓ type errors: ${total} (baseline ${baseTotal}); no file got worse`);
}
