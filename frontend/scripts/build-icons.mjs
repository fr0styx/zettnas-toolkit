// Builds frontend/public/zi-sprite.svg, the icons that replace emoji (UX-14), from
// lucide-static (a pinned dev dependency) and frontend/src/icons/emoji-icons.json.
//   node frontend/scripts/build-icons.mjs          write the sprite
//   node frontend/scripts/build-icons.mjs --check  exit 1 when it is out of date
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

const MAP = 'frontend/src/icons/emoji-icons.json';
const OUT = 'frontend/public/zi-sprite.svg';
const require = createRequire(import.meta.url);
const pkgDir = dirname(require.resolve('lucide-static/package.json'));
const { version } = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf8'));
const license = readFileSync(join(pkgDir, 'LICENSE'), 'utf8').trim();

const names = [...new Set(Object.values(JSON.parse(readFileSync(MAP, 'utf8'))))]
  .filter((n) => !n.startsWith('@'))
  .sort();

const symbols = names.map((name) => {
  const file = join(pkgDir, 'icons', `${name}.svg`);
  if (!existsSync(file)) throw new Error(`lucide-static ${version} has no icon "${name}"`);
  const body = readFileSync(file, 'utf8')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/^[\s\S]*?<svg[^>]*>/, '')
    .replace(/<\/svg>\s*$/, '')
    .replace(/\s*\n\s*/g, '')
    .trim();
  return `<symbol id="zi-${name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</symbol>`;
});

const sprite = [
  '<svg xmlns="http://www.w3.org/2000/svg">',
  `<!-- Icons from Lucide (lucide-static ${version}), built by frontend/scripts/build-icons.mjs; do not edit.`,
  // a comment may not contain "--": space out every run of dashes
  license.replace(/-{2,}/g, (run) => run.split('').join(' ')),
  '-->',
  ...symbols,
  '</svg>',
  '',
].join('\n');

if (process.argv.includes('--check')) {
  const current = existsSync(OUT) ? readFileSync(OUT, 'utf8') : '';
  if (current !== sprite) {
    console.error(`✗ ${OUT} is out of date: run "npm run icons"`);
    process.exit(1);
  }
  console.log(`✓ ${OUT}: ${names.length} icons`);
} else {
  writeFileSync(OUT, sprite);
  console.log(`wrote ${OUT}: ${names.length} icons`);
}
