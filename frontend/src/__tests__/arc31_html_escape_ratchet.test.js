/**
 * ARC-31: values put into HTML templates (innerHTML, outerHTML, insertAdjacentHTML) are escaped.
 * Each file may not gain an unescaped ${value}: wrap it in escapeHtml(), or build the element
 * with textContent. Numbers, t(), icons and other HTML builders count as safe. After removing
 * some, record the new numbers: KIBOTO_UPDATE_HTML_BASELINE=1 npx vitest run arc31_html_escape
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import * as acorn from 'acorn';

const ROOT = resolve(__dirname, '..', '..', '..');
const SRC = join(ROOT, 'frontend', 'src');
const BASELINE = join(ROOT, 'frontend', 'scripts', 'html-escape-baseline.json');

const SAFE_CALL = /^(escapeHtml|escapeAttr|esc|t|ico|iconHtml|html|raw|formatBytes|formatSize|formatDateTime|formatDate|formatTime|formatNumber|formatFixed|formatPercent|String|Number|Math\.\w+|encodeURIComponent|parseInt|parseFloat|JSON\.stringify|emptyStateHtml|emptyRowHtml|uiButton|uiCard|uiField|uiPaneHeader)$/;
const SAFE_NAME = /^(i|n|idx|count|pct|percent|width|height|px|size)$/;

function walk(node, fn) {
  if (!node || typeof node.type !== 'string') return;
  fn(node);
  for (const key of Object.keys(node)) {
    const v = node[key];
    if (Array.isArray(v)) v.forEach((c) => walk(c, fn));
    else if (v && typeof v.type === 'string') walk(v, fn);
  }
}

/** The ${...} values in HTML templates of one source that nothing escapes. */
export function unescapedValues(src) {
  const ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', locations: true });
  const found = [];
  const check = (tpl) => {
    if (!tpl || tpl.type !== 'TemplateLiteral') return;
    for (const e of tpl.expressions) {
      const code = src.slice(e.start, e.end);
      if (e.type === 'Literal' || e.type === 'TemplateLiteral' || e.type === 'ConditionalExpression' || e.type === 'LogicalExpression') continue;
      if (e.type === 'CallExpression') {
        const callee = src.slice(e.callee.start, e.callee.end);
        if (SAFE_CALL.test(callee) || /\.(map|join)$/.test(callee) || /Html$/i.test(callee) || /\.(toFixed|toLocaleString)$/.test(callee)) continue;
      }
      if (SAFE_NAME.test(code)) continue;
      found.push({ line: e.loc.start.line, code });
    }
  };
  walk(ast, (node) => {
    if (node.type === 'AssignmentExpression' && node.left.type === 'MemberExpression' && ['innerHTML', 'outerHTML'].includes(node.left.property?.name)) check(node.right);
    if (node.type === 'CallExpression' && node.callee.type === 'MemberExpression' && node.callee.property?.name === 'insertAdjacentHTML') check(node.arguments[1]);
  });
  return found;
}

function sourceFiles(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return ['__tests__', 'locales'].includes(f) ? [] : sourceFiles(p);
    return f.endsWith('.js') ? [p] : [];
  });
}

describe('HTML templates escape what they insert (ARC-31)', () => {
  it('finds an unescaped value and accepts escaped ones', () => {
    const src = "el.innerHTML = `<b>${name}</b><i>${escapeHtml(name)}</i>${t('k', 'x')}${count}`; el.insertAdjacentHTML('beforeend', `${user.bio}`);";
    expect(unescapedValues(src).map((f) => f.code)).toEqual(['name', 'user.bio']);
  });

  it('no file gains unescaped values', () => {
    const now = {};
    for (const file of sourceFiles(SRC)) {
      const n = unescapedValues(readFileSync(file, 'utf8')).length;
      if (n) now[relative(ROOT, file)] = n;
    }
    if (process.env.KIBOTO_UPDATE_HTML_BASELINE) {
      writeFileSync(BASELINE, JSON.stringify(Object.fromEntries(Object.entries(now).sort()), null, 2) + '\n');
      return;
    }
    const base = JSON.parse(readFileSync(BASELINE, 'utf8'));
    const grown = Object.entries(now).filter(([f, n]) => n > (base[f] ?? 0)).map(([f, n]) => `${f}: ${n} (baseline ${base[f] ?? 0})`);
    expect(grown, 'escape the new ${...} with escapeHtml() or set textContent instead').toEqual([]);
  });
});
