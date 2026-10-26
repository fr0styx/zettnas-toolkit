// UI primitives (UX-11): Button, Field, Card and PaneHeader as HTML builders.
//
// They write the classes the app already styles (see docs/UI_PRIMITIVES.md), so new markup
// looks like the rest without inline styles:
//   Button     .btn-pill-toggle (+ is-primary | is-danger | is-ghost, is-small, is-block)
//   Field      .zn-field: a label above its control, with an optional hint
//   Card       .zn-card (+ zn-card--boxed | zn-card--divided), with an optional .zn-title
//   PaneHeader .mgmt-card-intro: the icon, title and one-line description atop a pane
//
// Text arguments are escaped. `html` arguments (body, control) are trusted markup.
import { escapeHtml } from '../utils.js';

const VARIANTS = new Set(['primary', 'danger', 'ghost']);

function attrs(extra) {
  return Object.entries(extra || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== false)
    .map(([k, v]) => (v === true ? ` ${k}` : ` ${k}="${escapeHtml(String(v))}"`))
    .join('');
}

function icon(name) {
  return name ? `<svg class="ic" aria-hidden="true"><use href="#i-${escapeHtml(name)}"/></svg>` : '';
}

export function uiButton({ label = '', variant = '', small = false, block = false, iconName = '', type = 'button', id, i18n, extra } = {}) {
  const cls = ['btn-pill-toggle'];
  if (VARIANTS.has(variant)) cls.push(`is-${variant}`);
  if (small) cls.push('is-small');
  if (block) cls.push('is-block');
  const a = attrs({ type, id, class: cls.join(' '), 'data-i18n': i18n, ...extra });
  return `<button${a}>${icon(iconName)}${label ? `<span>${escapeHtml(label)}</span>` : ''}</button>`;
}

export function uiField({ label = '', control = '', hint = '', id } = {}) {
  const forAttr = id ? ` for="${escapeHtml(id)}"` : '';
  const hintHtml = hint ? `<span class="zn-muted">${escapeHtml(hint)}</span>` : '';
  return `<label class="zn-field"${forAttr}><span>${escapeHtml(label)}</span>${control}${hintHtml}</label>`;
}

export function uiCard({ title = '', body = '', variant = '' } = {}) {
  const cls = ['zn-card'];
  if (variant === 'boxed' || variant === 'divided') cls.push(`zn-card--${variant}`);
  const head = title ? `<div class="zn-title">${escapeHtml(title)}</div>` : '';
  return `<div class="${cls.join(' ')}">${head}${body}</div>`;
}

export function uiPaneHeader({ title = '', desc = '', iconName = '' } = {}) {
  const d = desc ? `<div class="mgmt-card-intro-desc">${escapeHtml(desc)}</div>` : '';
  return (
    `<div class="mgmt-card-intro"><div class="mgmt-card-intro-title">${icon(iconName)}` +
    `<span>${escapeHtml(title)}</span></div>${d}</div>`
  );
}
