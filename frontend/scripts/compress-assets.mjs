// Writes .br and .gz copies of the built text assets so the server can send them
// compressed without spending CPU per request (FE-01). Uses Node's built-in zlib.
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, extname } from 'node:path';

const ROOT = process.argv[2] || 'static';
const TYPES = new Set(['.js', '.css', '.html', '.svg', '.json', '.map', '.txt', '.webmanifest']);
const MIN_BYTES = 1024;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else yield p;
  }
}

let raw = 0;
let br = 0;
let files = 0;
for (const file of walk(ROOT)) {
  if (!TYPES.has(extname(file)) || file.endsWith('.br') || file.endsWith('.gz')) continue;
  const data = readFileSync(file);
  if (data.length < MIN_BYTES) continue;
  const b = brotliCompressSync(data, {
    params: { [constants.BROTLI_PARAM_QUALITY]: 11, [constants.BROTLI_PARAM_SIZE_HINT]: data.length },
  });
  writeFileSync(`${file}.br`, b);
  writeFileSync(`${file}.gz`, gzipSync(data, { level: 9 }));
  raw += data.length;
  br += b.length;
  files += 1;
}
console.log(`compressed ${files} files: ${(raw / 1e6).toFixed(2)} MB -> ${(br / 1e6).toFixed(2)} MB brotli`);
