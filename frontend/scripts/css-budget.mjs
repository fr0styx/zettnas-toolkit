// CSS budget (FE-18, UX-6, UX-14): the number of !important declarations, button class names,
// inline style attributes and emoji without an icon may only go down; new markup uses classes,
// the shared tokens and the SVG sprite. Emoji with an entry in src/icons/emoji-icons.json are
// drawn as icons by icons.js; any other emoji in the sources, translations included, counts. Run with --update after lowering them to record the new baseline.
// UX-32: !important is also held per file (a new file starts at zero), and the number of places
// that build markup with the UI primitives (uiButton, uiField, uiCard, uiPaneHeader) may only go up.
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = 'frontend';
const BASELINE = 'frontend/scripts/css-budget.json';
const SLACK = 10; // a budget may be at most this far above today's count (NARC-3): lower it with --update
const SLACK_PER_FILE = 2;

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
let emojiIcons = 0;
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]/gu;
const ICONS = JSON.parse(readFileSync(join(ROOT, 'src', 'icons', 'emoji-icons.json'), 'utf8'));
const buttonClasses = new Set();
const importantPerFile = {};
let primitiveUses = 0;
for (const f of files) {
  const src = readFileSync(f, 'utf8');
  const imp = (src.match(/!important/g) || []).length;
  important += imp;
  if (imp) importantPerFile[f.replaceAll('\\', '/')] = imp;
  if (f.endsWith('.js') && !f.replaceAll('\\', '/').endsWith('ui/primitives.js')) {
    primitiveUses += (src.match(/\bui(?:Button|Field|Card|PaneHeader)\(/g) || []).length;
  }
  if (!f.endsWith('.css')) inlineStyles += (src.match(/\sstyle=["'`]|\.style\.cssText\s*=/g) || []).length;
  if (!f.endsWith('.css') && !f.endsWith('.json')) {
    for (const m of src.matchAll(EMOJI)) if (!ICONS[m[0]]) emojiIcons += 1;
  }
  if (f.endsWith('.css')) {
    for (const m of src.matchAll(/\.((?:btn|button)[-_][\w-]+)/g)) buttonClasses.add(m[1]);
  }
}
const now = { important, buttonClasses: buttonClasses.size, inlineStyles, emojiIcons };
if (process.argv.includes('--update')) {
  const sorted = Object.fromEntries(Object.entries(importantPerFile).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(BASELINE, JSON.stringify({ ...now, primitiveUses, importantPerFile: sorted }, null, 2) + '\n');
  console.log('css budget baseline updated:', { ...now, primitiveUses });
  process.exit(0);
}
const base = JSON.parse(readFileSync(BASELINE, 'utf8'));
let failed = false;
if (base.importantPerFile) {
  for (const [f, n] of Object.entries(importantPerFile)) {
    if ((base.importantPerFile[f] ?? 0) - n > SLACK_PER_FILE) {
      console.error(`✗ ${f}: ${n} !important, budget still ${base.importantPerFile[f]}: run "npm run lint:css -- --update"`);
      failed = true;
    }
    if (n > (base.importantPerFile[f] ?? 0)) {
      console.error(`✗ ${f}: ${n} !important (budget ${base.importantPerFile[f] ?? 0}). Use a more specific selector or a token instead.`);
      failed = true;
    }
  }
}
if (primitiveUses < (base.primitiveUses ?? 0)) {
  console.error(`✗ primitiveUses: ${primitiveUses} (at least ${base.primitiveUses}). Markup built with uiButton/uiField/uiCard/uiPaneHeader was replaced by hand-written markup.`);
  failed = true;
} else {
  console.log(`✓ primitiveUses: ${primitiveUses} (at least ${base.primitiveUses ?? 0})`);
}
for (const k of Object.keys(now)) {
  if (now[k] > (base[k] ?? 0)) {
    console.error(`✗ ${k}: ${now[k]} (budget ${base[k] ?? 0}). Use a component class, a token or a more specific selector instead.`);
    failed = true;
  } else if (base[k] - now[k] > SLACK) {
    console.error(`✗ ${k}: ${now[k]}, budget still ${base[k]}: run "npm run lint:css -- --update" to lower it`);
    failed = true;
  } else if (now[k] < base[k]) {
    console.log(`✓ ${k}: ${now[k]} (budget ${base[k]}); run "npm run lint:css -- --update" to lower the budget`);
  } else {
    console.log(`✓ ${k}: ${now[k]} (budget ${base[k]})`);
  }
}
process.exit(failed ? 1 : 0);
