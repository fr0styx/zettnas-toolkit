// Translation lint (FE-13, FE-14). Fails when:
//  - code formats dates or numbers with toLocale*String() instead of format.js;
//  - code or markup uses a key that en.js doesn't define;
//  - a language is missing a key, or has keys en.js doesn't;
//  - a translation drops or invents a {placeholder};
//  - more toasts show hard-coded text than the recorded baseline (it can only go down).
// Run with --update-baseline after converting toasts to t().
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = process.cwd();
const BASELINE = join(ROOT, 'frontend/scripts/i18n-baseline.json');
const { ALL_TRANSLATIONS } = await import(pathToFileURL(join(ROOT, 'frontend/src/locales/all.js')).href);
const en = ALL_TRANSLATIONS.en;
const errors = [];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name !== '__tests__' && name !== 'locales') yield* walk(p);
    } else if (p.endsWith('.js')) yield p;
  }
}

const files = [...walk(join(ROOT, 'frontend/src')), join(ROOT, 'frontend/index.html')];
let rawToasts = 0;
for (const file of files) {
  const src = readFileSync(file, 'utf8');
  const rel = file.slice(ROOT.length + 1);
  const used = [
    ...[...src.matchAll(/\bt\(\s*(['"`])([a-z0-9_.-]+)\1/gi)].map((m) => m[2]),
    ...[...src.matchAll(/data-i18n(?:-title|-placeholder|-aria-label)?="([^"$]+)"/g)].map((m) => m[1]),
  ];
  for (const key of new Set(used)) {
    if (/[._]$/.test(key)) continue; // a prefix completed at runtime, e.g. t('settings.theme_' + name)
    if (!(key in en)) errors.push(`${rel}: key "${key}" is not defined in locales/en.js`);
  }
  rawToasts += [...src.matchAll(/showToast\(\s*['"`]/g)].length;
  if (!rel.endsWith('format.js')) {
    for (const m of src.matchAll(/\.toLocale(?:Date|Time)?String\(/g)) {
      const line = src.slice(0, m.index).split('\n').length;
      errors.push(`${rel}:${line}: use formatDateTime/formatDate/formatTime/formatNumber from format.js, not toLocale*String() (FE-14)`);
    }
  }
}

const placeholders = (s) => [...String(s).matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map((m) => m[1]).sort().join(',');
for (const [lang, dict] of Object.entries(ALL_TRANSLATIONS)) {
  if (lang === 'en') continue;
  for (const key of Object.keys(en)) {
    if (!(key in dict)) errors.push(`locales/${lang}.js: missing "${key}"`);
    else if (placeholders(dict[key]) !== placeholders(en[key])) {
      errors.push(`locales/${lang}.js: "${key}" has placeholders {${placeholders(dict[key])}}, en has {${placeholders(en[key])}}`);
    }
  }
  for (const key of Object.keys(dict)) if (!(key in en)) errors.push(`locales/${lang}.js: "${key}" is not in en.js`);
}

let baseline = { raw_toasts: Infinity };
try {
  baseline = JSON.parse(readFileSync(BASELINE, 'utf8'));
} catch (e) {
  /* first run */
}
if (process.argv.includes('--update-baseline')) {
  writeFileSync(BASELINE, JSON.stringify({ raw_toasts: rawToasts }, null, 2) + '\n');
  console.log(`baseline: ${rawToasts} toasts with hard-coded text`);
} else if (rawToasts > baseline.raw_toasts) {
  errors.push(`${rawToasts} toasts use hard-coded text (baseline ${baseline.raw_toasts}); use t('key', 'English text')`);
}

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`);
  console.error(`\n${errors.length} translation problem(s).`);
  process.exit(1);
}
console.log(`i18n lint: ${Object.keys(en).length} keys in 5 languages, all used keys defined; ${rawToasts} hard-coded toasts (baseline ${baseline.raw_toasts}).`);
