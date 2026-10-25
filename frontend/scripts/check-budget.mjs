// Fails the build if the first page load (index.html plus every script and stylesheet it
// loads or preloads) is over budget, measured as the Brotli bytes the browser downloads.
import { existsSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = process.argv[2] || 'static';
const BUDGET = Number(process.env.FIRST_LOAD_BUDGET_BYTES || 250_000);

const size = (p) => (existsSync(`${p}.br`) ? statSync(`${p}.br`).size : statSync(p).size);
const html = readFileSync(join(ROOT, 'index.html'), 'utf8');
const urls = [...new Set([...html.matchAll(/(?:src|href)="(\/assets\/[^"]+\.(?:js|css))"/g)].map((m) => m[1]))];
const rows = [['index.html', size(join(ROOT, 'index.html'))], ...urls.map((u) => [u, size(join(ROOT, u))])];
const total = rows.reduce((n, [, s]) => n + s, 0);
rows.sort((a, b) => b[1] - a[1]).slice(0, 8).forEach(([u, s]) => console.log(`${(s / 1000).toFixed(1).padStart(8)} kB  ${u}`));
console.log(`first load: ${(total / 1000).toFixed(1)} kB (budget ${(BUDGET / 1000).toFixed(0)} kB)`);
if (total > BUDGET) {
  console.error('First load is over budget.');
  process.exit(1);
}
