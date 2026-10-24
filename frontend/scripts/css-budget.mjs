// CSS budget (FE-18, UX-6): the number of !important declarations, button class names and
// inline style attributes may only go down; new markup uses classes and the shared tokens. Run with --update after lowering them to record the new baseline.
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
let inlineStyles = 0;
const buttonClasses = new Set();
for (const f of files) {
  const src = readFileSync(f, 'utf8');
  important += (src.match(/!important/g) || []).length;
  if (!f.endsWith('.css')) inlineStyles += (src.match(/\sstyle=["'`]|\.style\.cssText\s*=/g) || []).length;
  if (f.endsWith('.css')) {
    for (const m of src.matchAll(/\.((?:btn|button)[-_][\w-]+)/g)) buttonClasses.add(m[1]);
  }
}
const now = { important, buttonClasses: buttonClasses.size, inlineStyles };
if (process.argv.includes('--update')) {
  writeFileSync(BASELINE, JSON.stringify(now, null, 2) + '\n');
  console.log('css budget baseline updated:', now);
  process.exit(0);
}
const base = JSON.parse(readFileSync(BASELINE, 'utf8'));
let failed = false;
for (const k of Object.keys(now)) {
  if (now[k] > (base[k] ?? 0)) {
    console.error(`✗ ${k}: ${now[k]} (budget ${base[k] ?? 0}). Use a component class, a token or a more specific selector instead.`);
    failed = true;
  } else if (now[k] < base[k]) {
    console.log(`✓ ${k}: ${now[k]} (budget ${base[k]}); run "npm run lint:css -- --update" to lower the budget`);
  } else {
    console.log(`✓ ${k}: ${now[k]} (budget ${base[k]})`);
  }
}
process.exit(failed ? 1 : 0);
