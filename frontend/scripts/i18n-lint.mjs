// Translation lint (FE-13, FE-14). Fails when:
//  - code formats dates or numbers with toLocale*String() instead of format.js;
//  - code or markup uses a key that en.js doesn't define;
//  - a language is missing a key, or has keys en.js doesn't;
//  - a translation drops or invents a {placeholder};
//  - more toasts show hard-coded text than the recorded baseline (it can only go down);
//  - a file has more hard-coded English than its recorded baseline (UX-9, UX-12, UX-21; it can only
//    go down): titles, placeholders, aria-labels, textContent writes, and the text between tags in
//    HTML and in JS templates, ALL-CAPS labels and text around ${} included.
// Run with --update-baseline after converting strings to t() or data-i18n-*; --list prints them.
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readable, textNodes } from './i18n-text.mjs';

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

const visible = readable; // text a person reads, as opposed to ids, file names or acronyms
const UI_ATTR = /\s(title|placeholder|aria-label)="((?:[^"<>{}$]|\$\{[^{}]*\})*)"/g;
const UI_ASSIGN = /\.(?:textContent|innerText|title|placeholder)\s*=\s*(['"`])((?:(?!\1)[^\\$]|\\.|\$\{[^{}`]*\})*)\1\s*;/g;
const holes = (text) => text.replace(/\$\{[^{}]*\}/g, '\u0000'); // ${...} is not text
const LIST = process.argv.includes('--list'); // print each hard-coded string

function hardcodedUi(src, rel = '') {
  let n = 0;
  const hit = (text) => {
    n++;
    if (LIST) console.log(`${rel}: ${text.trim().slice(0, 100)}`);
  };
  for (const m of src.matchAll(UI_ATTR)) {
    const before = src.slice(Math.max(0, m.index - 400), m.index);
    const tag = before.slice(before.lastIndexOf('<')) + src.slice(m.index, src.indexOf('>', m.index));
    if (/\bt\(\s*['"]/.test(m[2])) continue; // a string that calls t() mid-way
    if (/\sdata-sample\b/.test(tag)) continue; // a sample value, the same in every language
    if (/^\$\{[^{}]*\}$/.test(m[2])) continue; // the whole value comes from code
    if (!tag.includes(`data-i18n-${m[1]}`) && visible(holes(m[2]))) hit(m[0]);
  }
  for (const m of src.matchAll(UI_ASSIGN)) if (visible(holes(m[2]))) hit(m[0]);
  for (const text of textNodes(src, rel)) hit(text);
  return n;
}

const windowsDir = join(ROOT, 'frontend/src/windows');
const files = [...walk(join(ROOT, 'frontend/src')), join(ROOT, 'frontend/index.html'),
  ...readdirSync(windowsDir).filter((f) => f.endsWith('.html')).map((f) => join(windowsDir, f))];
let rawToasts = 0;
let rawUi = 0;
const perFile = {};
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
  const ui = hardcodedUi(src, rel);
  rawUi += ui;
  if (ui) perFile[rel] = ui;
  if (!rel.endsWith('format.js')) {
    for (const m of src.matchAll(/\.toLocale(?:Date|Time)?String\(/g)) {
      const line = src.slice(0, m.index).split('\n').length;
      errors.push(`${rel}:${line}: use formatDateTime/formatDate/formatTime/formatNumber from format.js, not toLocale*String() (FE-14)`);
    }
  }
}

// {name} and the ICU plural {name, plural, ...} both count as the placeholder "name"
const placeholders = (s) => [...new Set([...String(s).matchAll(/\{([a-zA-Z0-9_]+)(?:\}|, plural,)/g)].map((m) => m[1]))].sort().join(',');
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

let baseline = { raw_toasts: Infinity, hardcoded_ui: Infinity, per_file: null };
try {
  baseline = JSON.parse(readFileSync(BASELINE, 'utf8'));
} catch (e) {
  /* first run */
}
if (process.argv.includes('--update-baseline')) {
  const sorted = Object.fromEntries(Object.entries(perFile).sort(([x], [y]) => x.localeCompare(y)));
  writeFileSync(BASELINE, JSON.stringify({ raw_toasts: rawToasts, hardcoded_ui: rawUi, per_file: sorted }, null, 2) + '\n');
  console.log(`baseline: ${rawToasts} toasts and ${rawUi} UI strings with hard-coded text`);
} else {
  if (rawToasts > baseline.raw_toasts) {
    errors.push(`${rawToasts} toasts use hard-coded text (baseline ${baseline.raw_toasts}); use t('key', 'English text')`);
  }
  // per file, so translating one screen can't hide new English in another (UX-21)
  for (const [rel, n] of Object.entries(perFile)) {
    const allowed = baseline.per_file ? baseline.per_file[rel] ?? 0 : Infinity;
    if (n > allowed) {
      errors.push(`${rel}: ${n} hard-coded English strings (baseline ${allowed}); use t('key', 'English text'), data-i18n, or data-i18n-title / -placeholder / -aria-label (npm run lint:i18n -- --list shows them)`);
    }
  }
}

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`);
  console.error(`\n${errors.length} translation problem(s).`);
  process.exit(1);
}
console.log(`i18n lint: ${Object.keys(en).length} keys in 5 languages, all used keys defined; ${rawToasts} hard-coded toasts (baseline ${baseline.raw_toasts}); ${rawUi} hard-coded UI strings (baseline ${baseline.hardcoded_ui}).`);
