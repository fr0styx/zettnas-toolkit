import fs from 'node:fs';
import path from 'node:path';

// Mission Control's markup lives in src/windows/management-window.html and is inserted into
// the page when first needed (FE-04). Tests that check the page's markup read both, put
// together the way the browser ends up with them.
const FRONTEND = path.resolve(__dirname, '..', '..', '..');

export function readIndexHtml() {
  const page = fs.readFileSync(path.join(FRONTEND, 'index.html'), 'utf8');
  const mc = fs.readFileSync(path.join(FRONTEND, 'src', 'windows', 'management-window.html'), 'utf8');
  const drawer = fs.readFileSync(path.join(FRONTEND, 'src', 'windows', 'drawer.html'), 'utf8');
  return page
    .replace(/<template id="management-window-slot">[\s\S]*?<\/template>/, mc)
    .replace('<template id="led-drawer-slot"></template>', drawer);
}
