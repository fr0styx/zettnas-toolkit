// Converts the emoji in static markup to icons when the app is built (PERF-8).
//
// index.html and the window templates (src/windows/*.html) hold most of the interface's emoji.
// The page used to find and swap them as the markup arrived, walking every node. The build now
// writes the icons into the markup, by the rules the page uses (src/icons-rules.js), and marks
// it so the page does not walk it again. Text the page adds later is still converted there.
//
// Only the emoji are touched: the rest of the source keeps its exact formatting.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse, parseFragment } from 'parse5';
import {
  ATTR_SKIP, BUILT_ATTR, SKIP, TEXT_ATTRS, emojiMatchers, iconMarkup, iconOnlyLabel,
} from '../src/icons-rules.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const MAP = JSON.parse(readFileSync(join(HERE, '..', 'src', 'icons', 'emoji-icons.json'), 'utf8'));
const { all: EMOJI_RE, any: HAS_EMOJI } = emojiMatchers(MAP);
const SPRITE_URL = '/zi-sprite.svg';

const iconFor = (emoji) => MAP[emoji.replace(/️/g, '')] || null;
const stripEmoji = (text) => String(text).replace(EMOJI_RE, '').replace(/\s{2,}/g, ' ').trim();
const escAttr = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
const attrOf = (el, name) => el.attrs?.find((a) => a.name === name)?.value;

function matches(el, rules) {
  if (!el.tagName) return false;
  if (rules.tags.includes(el.tagName)) return true;
  if (rules.attrs.some((a) => attrOf(el, a) !== undefined)) return true;
  if (rules.ids.includes(attrOf(el, 'id'))) return true;
  const cls = (attrOf(el, 'class') || '').split(/\s+/);
  return rules.classes.some((c) => cls.includes(c));
}

const kids = (node) => (node.tagName === 'template' ? node.content.childNodes : node.childNodes || []);

/** All text below a node, without the mapped emoji (what an icon-only button shows as words). */
function wordsBelow(node) {
  if (node.nodeName === '#text') return node.value.replace(EMOJI_RE, '');
  return kids(node).map(wordsBelow).join('');
}

function convert(src, root, offset = 0) {
  const edits = []; // [start, end, text]
  const labelled = new Set();

  function textEdit(node, parents) {
    const loc = node.sourceCodeLocation;
    if (!loc) return;
    const raw = src.slice(loc.startOffset - offset, loc.endOffset - offset);
    if (!HAS_EMOJI.test(raw)) return;
    let out = '';
    let last = 0;
    let firstIcon = null;
    EMOJI_RE.lastIndex = 0;
    for (let m = EMOJI_RE.exec(raw); m; m = EMOJI_RE.exec(raw)) {
      const name = iconFor(m[0]);
      if (!name) continue;
      out += raw.slice(last, m.index) + iconMarkup(name, SPRITE_URL);
      firstIcon = firstIcon || name;
      last = m.index + m[0].length;
    }
    if (!firstIcon) return;
    out += raw.slice(last);
    // the icon and its words stay together (in a flex or grid row they could be spread apart)
    if (raw.replace(EMOJI_RE, '').trim()) out = `<span class="zi-run">${out}</span>`;
    edits.push([loc.startOffset, loc.endOffset, out]);
    // an icon-only button gets a name
    const host = [...parents].reverse().find((p) => ['button', 'a'].includes(p.tagName) || attrOf(p, 'role') === 'button');
    if (!host || labelled.has(host) || attrOf(host, 'aria-label') || attrOf(host, 'aria-labelledby')) return;
    if (wordsBelow(host).trim()) return;
    labelled.add(host);
    const label = iconOnlyLabel(stripEmoji(attrOf(host, 'title') || ''), firstIcon);
    // last, as the page adds it (before the start tag closes)
    const tag = host.sourceCodeLocation.startTag;
    const at = src[tag.endOffset - 2] === "/" ? tag.endOffset - 2 : tag.endOffset - 1;
    edits.push([at, at, ` aria-label="${escAttr(label)}"`]);
  }

  function walk(node, parents, skipText, skipAttrs) {
    if (node.nodeName === '#text') {
      if (!skipText) textEdit(node, parents);
      return;
    }
    if (!node.tagName && node.nodeName !== '#document-fragment') return;
    let st = skipText;
    let sa = skipAttrs;
    if (node.tagName) {
      sa = sa || matches(node, ATTR_SKIP);
      st = st || matches(node, SKIP);
      const loc = node.sourceCodeLocation;
      if (!sa && loc?.attrs) {
        for (const a of TEXT_ATTRS) {
          const v = attrOf(node, a);
          if (v && HAS_EMOJI.test(v)) {
            const clean = stripEmoji(v);
            if (clean !== v) edits.push([loc.attrs[a].startOffset, loc.attrs[a].endOffset, `${a}="${escAttr(clean)}"`]);
          }
        }
      }
    }
    const next = node.tagName ? [...parents, node] : parents;
    for (const k of kids(node)) walk(k, next, st, sa);
  }

  walk(root, [], false, false);
  return edits;
}

function apply(src, edits, offset = 0) {
  let out = src;
  for (const [s, e, text] of edits.sort((a, b) => b[0] - a[0] || b[1] - a[1])) {
    out = out.slice(0, s - offset) + text + out.slice(e - offset);
  }
  return out;
}

function markTag(el) {
  const at = el.sourceCodeLocation.startTag.startOffset + 1 + el.tagName.length;
  return [at, at, ` ${BUILT_ATTR}`];
}

/** A window template: its emoji as icons, each top-level element marked as converted. */
export function iconizeFragment(src) {
  const frag = parseFragment(src, { sourceCodeLocationInfo: true });
  const edits = convert(src, frag);
  for (const el of frag.childNodes) if (el.tagName && el.sourceCodeLocation) edits.push(markTag(el));
  return apply(src, edits);
}

/** index.html: the body's emoji as icons, the body marked as converted. */
export function iconizeDocument(src) {
  const doc = parse(src, { sourceCodeLocationInfo: true });
  const html = doc.childNodes.find((n) => n.tagName === 'html');
  const body = html?.childNodes.find((n) => n.tagName === 'body');
  if (!body?.sourceCodeLocation) return src;
  const edits = convert(src, body);
  edits.push(markTag(body));
  return apply(src, edits);
}

/** The Vite plugin: index.html and the window templates imported with ?raw. */
export function iconsAtBuildTime() {
  return {
    name: 'zettnas-icons-at-build-time',
    enforce: 'pre',
    transformIndexHtml: { order: 'pre', handler: (html) => iconizeDocument(html) },
    load(id) {
      const m = /^(.*\/src\/windows\/[^/]+\.html)\?raw$/.exec(id);
      if (!m) return null;
      return `export default ${JSON.stringify(iconizeFragment(readFileSync(m[1], 'utf8')))};`;
    },
  };
}
