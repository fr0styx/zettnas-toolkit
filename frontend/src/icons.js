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

import EMOJI_ICONS from './icons/emoji-icons.json';

export const SPRITE_URL = '/zi-sprite.svg';
const SVG_NS = 'http://www.w3.org/2000/svg';

// Places whose text is content, not interface
// (closest() also matches their descendants)
const SKIP_SELECTOR = [
  'script', 'style', 'textarea', 'input', 'select', 'option', 'pre', 'code', 'kbd', 'samp',
  '[contenteditable]', '[data-no-icons]', '.ai-chat-msg', '.fm-name', '.xterm', '#screen', '#mini-lcd-canvas',
].join(',');
// Tooltips and placeholders are cleaned everywhere except in what people wrote
const ATTR_SKIP_SELECTOR = '[data-no-icons], .ai-chat-msg, .fm-name, #screen, #mini-lcd-canvas';
const TEXT_ATTRS = ['title', 'placeholder', 'aria-label'];

// Readable names for icon-only buttons without a title
const ICON_LABELS = {
  'trash-2': 'Delete', x: 'Close', 'circle-x': 'Close', pencil: 'Edit', 'refresh-cw': 'Refresh',
  'clipboard-list': 'Copy', search: 'Search', settings: 'Settings', eye: 'Show', 'eye-off': 'Hide',
  download: 'Download', upload: 'Upload', plus: 'Add', check: 'Done', play: 'Start', pause: 'Pause',
  square: 'Stop', 'arrow-right': 'Open', save: 'Save', link: 'Link', maximize: 'Full screen',
  'folder-open': 'Open folder', 'corner-left-up': 'Up one level',
};

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// Variation selector (U+FE0F) after the emoji goes with it
const KEYS = Object.keys(EMOJI_ICONS).sort((a, b) => b.length - a.length);
const EMOJI_RE = new RegExp(`(?:${KEYS.map(escapeRe).join('|')})️?`, 'gu');
const HAS_EMOJI = new RegExp(`(?:${KEYS.map(escapeRe).join('|')})`, 'u');

export function iconFor(emoji) {
  return EMOJI_ICONS[emoji.replace(/️/g, '')] || null;
}

function hrefFor(name) {
  return name.startsWith('@') ? `#${name.slice(1)}` : `${SPRITE_URL}#zi-${name}`;
}

/** An icon as markup, for templates that build HTML. */
export function iconHtml(name, extraClass = '') {
  if (name.startsWith('@dot-')) {
    return `<span class="zi zi-dot zi-dot-${name.slice(5)}${extraClass ? ` ${extraClass}` : ''}" aria-hidden="true"></span>`;
  }
  return `<svg class="zi${extraClass ? ` ${extraClass}` : ''}" data-zi="${name}" aria-hidden="true" focusable="false"><use href="${hrefFor(name)}"></use></svg>`;
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
  const label = host.getAttribute('title') || ICON_LABELS[iconName] || iconName.replace(/-/g, ' ');
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
  parent.replaceChild(frag, node);
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
    cleanAttributes(root);
    if (skipped(root)) return;
  }
  const texts = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) {
      if (HAS_EMOJI.test(n.nodeValue)) texts.push(n);
    } else if (n.attributes.length) {
      cleanAttributes(n);
    }
  }
  texts.forEach(convertTextNode);
}

let observer = null;

/** Converts the page now and every change from here on. Not on the LCD page. */
export function startIconizer(doc = document) {
  if (observer || !doc.body) return observer;
  const params = new URLSearchParams(doc.location?.search || '');
  if (params.has('lcd_token') || params.get('mode') === 'lcd' || doc.body.classList.contains('lcd-direct')) return null;
  iconizeTree(doc.body);
  observer = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'childList') {
        r.addedNodes.forEach(iconizeTree);
      } else if (r.type === 'characterData') {
        convertTextNode(r.target);
      } else if (r.type === 'attributes') {
        cleanAttributes(r.target);
      }
    }
  });
  observer.observe(doc.body, {
    childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: TEXT_ATTRS,
  });
  return observer;
}

export function stopIconizer() {
  observer?.disconnect();
  observer = null;
}
