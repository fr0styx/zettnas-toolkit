// Emoji used as icons are drawn as SVG icons (UX-14).
//
// The interface has emoji in markup, translations, toasts and data (folder icons, status
// marks). Instead of rewriting each place, the page swaps every mapped emoji for an icon
// from /zi-sprite.svg as text reaches the document, before it is painted. Icons follow the
// text colour, size with the font, and are hidden from screen readers; an icon-only button
// gets a name from its title or the icon. Tooltips and placeholders lose their emoji.
//
// Left alone: what people wrote (AI chat, file names, editors, code, logs) and the LCD page.
// The map lives in icons/emoji-icons.json; frontend/scripts/build-icons.mjs builds the sprite.
// index.html and the window templates are converted when the app is built (PERF-8,
// frontend/scripts/icons-build.mjs, same rules from icons-rules.js); that markup is marked and
// not walked again here.

import EMOJI_ICONS from './icons/emoji-icons.json';
import { watchDom } from './dom-watch.js';
import {
  ATTR_SKIP, BUILT_ATTR, SKIP, TEXT_ATTRS, emojiMatchers, hrefFor as hrefIn, iconMarkup, iconOnlyLabel, selectorOf,
} from './icons-rules.js';

export const SPRITE_URL = '/zi-sprite.svg';
const SVG_NS = 'http://www.w3.org/2000/svg';

const SKIP_SELECTOR = selectorOf(SKIP); // closest() also matches their descendants
const ATTR_SKIP_SELECTOR = selectorOf(ATTR_SKIP);
const FLEX_OR_GRID = /flex|grid/;

const { all: EMOJI_RE, any: HAS_EMOJI } = emojiMatchers(EMOJI_ICONS);

export function iconFor(emoji) {
  return EMOJI_ICONS[emoji.replace(/️/g, '')] || null;
}

function hrefFor(name) {
  return hrefIn(name, SPRITE_URL);
}

/** An icon as markup, for templates that build HTML. */
export function iconHtml(name, extraClass = '') {
  return iconMarkup(name, SPRITE_URL, extraClass);
}

/** An icon as an element. */
export function iconEl(name) {
  if (name.startsWith('@dot-')) {
    const dot = document.createElement('span');
    dot.className = `zi zi-dot zi-dot-${name.slice(5)}`;
    dot.setAttribute('aria-hidden', 'true');
    return dot;
  }
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'zi');
  svg.setAttribute('data-zi', name);
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', hrefFor(name));
  svg.appendChild(use);
  return svg;
}

/** Text without mapped emoji (for tooltips, placeholders and labels). */
export function stripEmoji(text) {
  return String(text).replace(EMOJI_RE, '').replace(/\s{2,}/g, ' ').trim();
}

function skipped(el) {
  return !el || el.closest?.(SKIP_SELECTOR) !== null;
}

function nameIconOnly(parent, iconName) {
  const host = parent.closest('button, a, [role="button"]');
  if (!host || host.getAttribute('aria-label') || host.getAttribute('aria-labelledby')) return;
  if ((host.textContent || '').trim()) return;
  const label = iconOnlyLabel(host.getAttribute('title'), iconName);
  host.setAttribute('aria-label', label);
}

function convertTextNode(node) {
  const text = node.nodeValue;
  if (!text || !HAS_EMOJI.test(text)) return;
  const parent = node.parentElement;
  if (skipped(parent)) return;
  const frag = document.createDocumentFragment();
  let last = 0;
  let firstIcon = null;
  EMOJI_RE.lastIndex = 0;
  for (let m = EMOJI_RE.exec(text); m; m = EMOJI_RE.exec(text)) {
    const name = iconFor(m[0]);
    if (!name) continue;
    if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
    frag.appendChild(iconEl(name));
    firstIcon = firstIcon || name;
    last = m.index + m[0].length;
  }
  if (!firstIcon) return;
  if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
  // "👁️ QuickLook" was one piece of text. In a flex or grid row the icon and the words would
  // become separate items and could be spread apart (space-between), so they stay together.
  const hasWords = Array.from(frag.childNodes).some((n) => n.nodeType === Node.TEXT_NODE && n.nodeValue.trim());
  let replacement = frag;
  if (hasWords && FLEX_OR_GRID.test(String(window.getComputedStyle(parent).display))) {
    replacement = document.createElement('span');
    replacement.className = 'zi-run';
    replacement.appendChild(frag);
  }
  parent.replaceChild(replacement, node);
  nameIconOnly(parent, firstIcon);
}

function cleanAttributes(el) {
  if (!el?.closest || el.closest(ATTR_SKIP_SELECTOR)) return;
  for (const attr of TEXT_ATTRS) {
    const v = el.getAttribute(attr);
    if (v && HAS_EMOJI.test(v)) {
      const clean = stripEmoji(v);
      if (clean !== v) el.setAttribute(attr, clean);
    }
  }
}

/** Converts the emoji in an element and everything below it. */
export function iconizeTree(root) {
  if (!root) return;
  if (root.nodeType === Node.TEXT_NODE) {
    convertTextNode(root);
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
  if (root.nodeType === Node.ELEMENT_NODE) {
    if (root.hasAttribute(BUILT_ATTR)) return; // converted when the app was built
    cleanAttributes(root);
    if (skipped(root)) return;
  }
  const texts = [];
  const notBuilt = {
    acceptNode: (n) => (n.nodeType === Node.ELEMENT_NODE && n.hasAttribute(BUILT_ATTR) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  };
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, notBuilt);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) {
      if (HAS_EMOJI.test(n.nodeValue)) texts.push(n);
    } else if (n.attributes.length) {
      cleanAttributes(n);
    }
  }
  texts.forEach(convertTextNode);
}

let unwatch = null;

/** Converts the page now and every change from here on. Not on the LCD page. */
export function startIconizer(doc = document) {
  if (unwatch || !doc.body) return unwatch;
  const params = new URLSearchParams(doc.location?.search || '');
  if (params.has('lcd_token') || params.get('mode') === 'lcd' || doc.body.classList.contains('lcd-direct')) return null;
  iconizeTree(doc.body);
  unwatch = watchDom({
    characterData: true,
    attributes: TEXT_ATTRS,
    onRecords: (records) => {
      for (const r of records) {
      if (r.type === 'childList') {
        r.addedNodes.forEach(iconizeTree);
      } else if (r.type === 'characterData') {
        convertTextNode(r.target);
      } else if (r.type === 'attributes') {
        cleanAttributes(r.target);
      }
      }
    },
  });
  return unwatch;
}

export function stopIconizer() {
  unwatch?.();
  unwatch = null;
}
