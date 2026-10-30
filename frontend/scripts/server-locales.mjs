// Writes backend/locales/<lang>.json: the UI strings the server sends itself (alerts pushed to
// a phone or e-mailed, Drive Health's labels and findings in them), so they read in the
// household's language (NUX-3). Run `node frontend/scripts/server-locales.mjs` after changing
// those strings; frontend/src/__tests__/server_locales.test.js fails while a copy is stale.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const SERVER_PREFIXES = ['alert.', 'dh.label.', 'dh.f.'];
export const LANGS = ['en', 'de', 'es', 'fr', 'zh'];

/** The strings the server needs, by key, sorted. */
export function serverStrings(all) {
  const out = {};
  for (const key of Object.keys(all).sort()) {
    if (SERVER_PREFIXES.some((p) => key.startsWith(p))) out[key] = all[key];
  }
  return out;
}

/** The file's text for one language. */
export function serverJson(all) {
  return `${JSON.stringify(serverStrings(all), null, 1)}\n`;
}

const here = dirname(fileURLToPath(import.meta.url));
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const out = join(here, '..', '..', 'backend', 'locales');
  mkdirSync(out, { recursive: true });
  for (const lang of LANGS) {
    const mod = await import(pathToFileURL(join(here, '..', 'src', 'locales', `${lang}.js`)).href);
    writeFileSync(join(out, `${lang}.json`), serverJson(mod.default));
  }
  console.log(`wrote backend/locales for ${LANGS.join(', ')}`);
}
