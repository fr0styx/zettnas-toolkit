// UI primitives (UX-11): Button, Field, Card and PaneHeader as HTML builders.
//
// They write the classes the app already styles (see docs/UI_PRIMITIVES.md), so new markup
// looks like the rest without inline styles:
//   Button     .btn-pill-toggle (+ is-primary | is-danger | is-ghost, is-small, is-block)
//   Field      .zn-field: a label above its control, with an optional hint
//   Card       .zn-card (+ zn-card--boxed | zn-card--divided), with an optional .zn-title
//   PaneHeader .mgmt-card-intro: the icon, title and one-line description atop a pane
//
// Text arguments are escaped (html``). body and control are markup: pass an html`` result.
import { escapeHtml } from '../utils.js';
import { html, raw } from '../html.js';

const VARIANTS = new Set(['primary', 'danger', 'ghost']);

function attrs(extra) {
  return Object.entries(extra || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== false)
    .map(([k, v]) => (v === true ? ` ${k}` : ` ${k}="${escapeHtml(String(v))}"`))
    .join('');
}

function icon(name) {
  return name ? html`<svg class="ic" aria-hidden="true"><use href="#i-${name}"/></svg>` : '';
}

export function uiButton({ label = '', variant = '', small = false, block = false, iconName = '', type = 'button', id, i18n, extra } = {}) {
  const cls = ['btn-pill-toggle'];
  if (VARIANTS.has(variant)) cls.push(`is-${variant}`);
  if (small) cls.push('is-small');
  if (block) cls.push('is-block');
  const a = attrs({ type, id, class: cls.join(' '), 'data-i18n': i18n, ...extra });
  return String(html`<button${raw(a)}>${icon(iconName)}${label ? html`<span>${label}</span>` : ''}</button>`);
}

export function uiField({ label = '', control = '', hint = '', id } = {}) {
  const forAttr = id ? html` for="${id}"` : '';
  const hintHtml = hint ? html`<span class="zn-muted">${hint}</span>` : '';
  return String(html`<label class="zn-field"${forAttr}><span>${label}</span>${raw(control)}${hintHtml}</label>`);
}

export function uiCard({ title = '', body = '', variant = '' } = {}) {
  const cls = ['zn-card'];
  if (variant === 'boxed' || variant === 'divided') cls.push(`zn-card--${variant}`);
  const head = title ? html`<div class="zn-title">${title}</div>` : '';
  return String(html`<div class="${cls.join(' ')}">${head}${raw(body)}</div>`);
}

export function uiPaneHeader({ title = '', desc = '', iconName = '' } = {}) {
  const d = desc ? html`<div class="mgmt-card-intro-desc">${desc}</div>` : '';
  return String(
    html`<div class="mgmt-card-intro"><div class="mgmt-card-intro-title">${icon(iconName)}<span>${title}</span></div>${d}</div>`
  );
}
