// What the emoji-to-icon conversion leaves alone and how it names icon-only buttons (UX-14).
// Shared by the page (icons.js) and the build (frontend/scripts/icons-build.mjs), so markup
// converted at build time and text converted in the page follow the same rules.

// Places whose text is content, not interface (their descendants too)
export const SKIP = {
  tags: ['script', 'style', 'textarea', 'input', 'select', 'option', 'pre', 'code', 'kbd', 'samp'],
  attrs: ['contenteditable', 'data-no-icons'],
  classes: ['ai-chat-msg', 'fm-name', 'xterm'],
  ids: ['screen', 'mini-lcd-canvas'],
};
// Tooltips and placeholders are cleaned everywhere except in what people wrote
export const ATTR_SKIP = { tags: [], attrs: ['data-no-icons'], classes: ['ai-chat-msg', 'fm-name'], ids: ['screen', 'mini-lcd-canvas'] };

export const TEXT_ATTRS = ['title', 'placeholder', 'aria-label'];

// Markup converted at build time carries this, so the page does not walk it again
export const BUILT_ATTR = 'data-icons-built';

// Readable names for icon-only buttons without a title
export const ICON_LABELS = {
  'trash-2': 'Delete', x: 'Close', 'circle-x': 'Close', pencil: 'Edit', 'refresh-cw': 'Refresh',
  'clipboard-list': 'Copy', search: 'Search', settings: 'Settings', eye: 'Show', 'eye-off': 'Hide',
  download: 'Download', upload: 'Upload', plus: 'Add', check: 'Done', play: 'Start', pause: 'Pause',
  square: 'Stop', 'arrow-right': 'Open', save: 'Save', link: 'Link', maximize: 'Full screen',
  'folder-open': 'Open folder', 'corner-left-up': 'Up one level',
};

/** A rule set as a CSS selector (for closest()). */
export function selectorOf(rules) {
  return [
    ...rules.tags,
    ...rules.attrs.map((a) => `[${a}]`),
    ...rules.classes.map((c) => `.${c}`),
    ...rules.ids.map((i) => `#${i}`),
  ].join(',');
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** The matchers for an emoji map: every mapped emoji (with its variation selector), and any. */
export function emojiMatchers(map) {
  const keys = Object.keys(map).sort((a, b) => b.length - a.length);
  return {
    all: new RegExp(`(?:${keys.map(escapeRe).join('|')})️?`, 'gu'),
    any: new RegExp(`(?:${keys.map(escapeRe).join('|')})`, 'u'),
  };
}

export function hrefFor(name, spriteUrl) {
  return name.startsWith('@') ? `#${name.slice(1)}` : `${spriteUrl}#zi-${name}`;
}

/** An icon as markup. */
export function iconMarkup(name, spriteUrl, extraClass = '') {
  if (name.startsWith('@dot-')) {
    return `<span class="zi zi-dot zi-dot-${name.slice(5)}${extraClass ? ` ${extraClass}` : ''}" aria-hidden="true"></span>`;
  }
  return `<svg class="zi${extraClass ? ` ${extraClass}` : ''}" data-zi="${name}" aria-hidden="true" focusable="false"><use href="${hrefFor(name, spriteUrl)}"></use></svg>`;
}

/** The name an icon-only button gets: its title, a known label, or the icon's name. */
export function iconOnlyLabel(title, iconName) {
  return title || ICON_LABELS[iconName] || iconName.replace(/-/g, ' ');
}
