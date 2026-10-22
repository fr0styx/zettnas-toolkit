// CSS budget (FE-18): the number of !important declarations and button class names may
// only go down. Run with --update after lowering them to record the new baseline.
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = 'frontend';
const BASELINE = 'frontend/scripts/css-budget.json';

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === '__tests__' || name.startsWith('.')) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(css|js|html)$/.test(name)) out.push(p);
  }
  return out;
}

const files = walk(join(ROOT, 'src')).concat([join(ROOT, 'index.html')]);
let important = 0;
const buttonClasses = new Set();
for (const f of files) {
  const src = readFileSync(f, 'utf8');
  important += (src.match(/!important/g) || []).length;
  if (f.endsWith('.css')) {
    for (const m of src.matchAll(/\.((?:btn|button)[-_][\w-]+)/g)) buttonClasses.add(m[1]);
  }
}
const now = { important, buttonClasses: buttonClasses.size };
if (process.argv.includes('--update')) {
  writeFileSync(BASELINE, JSON.stringify(now, null, 2) + '\n');
  console.log('css budget baseline updated:', now);
  process.exit(0);
}
const base = JSON.parse(readFileSync(BASELINE, 'utf8'));
let failed = false;
for (const k of Object.keys(now)) {
  if (now[k] > base[k]) {
    console.error(`✗ ${k}: ${now[k]} (budget ${base[k]}). Use a component class or a more specific selector instead.`);
    failed = true;
  } else if (now[k] < base[k]) {
    console.log(`✓ ${k}: ${now[k]} (budget ${base[k]}); run "npm run lint:css -- --update" to lower the budget`);
  } else {
    console.log(`✓ ${k}: ${now[k]} (budget ${base[k]})`);
  }
}
process.exit(failed ? 1 : 0);
