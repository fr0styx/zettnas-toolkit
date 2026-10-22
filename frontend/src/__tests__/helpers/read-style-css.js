import fs from 'node:fs';
import path from 'node:path';

// style.css only imports the files under styles/ (FE-18). Tests that check CSS rules
// read the combined text, in cascade order, the way the build sees it.
const SRC = path.resolve(__dirname, '..', '..');

function inline(file) {
  const css = fs.readFileSync(file, 'utf8');
  return css.replace(/@import\s+['"](\.[^'"]+)['"];?/g, (_, rel) => inline(path.resolve(path.dirname(file), rel)));
}

export function readStyleCss() {
  return inline(path.join(SRC, 'style.css'));
}
