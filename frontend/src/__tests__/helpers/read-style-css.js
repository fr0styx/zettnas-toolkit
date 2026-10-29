import fs from 'node:fs';
import path from 'node:path';

// style.css only imports the files under styles/ (FE-18). Tests that check CSS rules
// read the combined text, in cascade order, the way the build sees it.
const SRC = path.resolve(__dirname, '..', '..');

function inline(file) {
  const css = fs.readFileSync(file, 'utf8');
  return css.replace(/@import\s+['"](\.[^'"]+)['"];?/g, (_, rel) => inline(path.resolve(path.dirname(file), rel)));
}

// The windows' own sheets load with their code, after every global sheet (ARC-12, PERF-9)
const LAZY = ['management-lazy.css', 'vm-lazy.css', 'files-lazy.css', 'viewer-lazy.css'];

export function readStyleCss() {
  return [inline(path.join(SRC, 'style.css')), ...LAZY.map((f) => inline(path.join(SRC, 'styles', f)))].join('\n');
}
