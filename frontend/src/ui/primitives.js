// UI primitives (UX-11): Button, Field, Card and PaneHeader as HTML builders.
//
// They write the classes the app already styles (see docs/UI_PRIMITIVES.md), so new markup
// looks like the rest without inline styles:
//   Button     .btn-pill-toggle (+ is-primary | is-danger | is-ghost, is-small, is-block)
//   Field      .kb-field: a label above its control, with an optional hint
//   Card       .kb-card (+ kb-card--boxed | kb-card--divided), with an optional .kb-title
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
  const hintHtml = hint ? html`<span class="kb-muted">${hint}</span>` : '';
  return String(html`<label class="kb-field"${forAttr}><span>${label}</span>${raw(control)}${hintHtml}</label>`);
}

export function uiCard({ title = '', body = '', variant = '' } = {}) {
  const cls = ['kb-card'];
  if (variant === 'boxed' || variant === 'divided') cls.push(`kb-card--${variant}`);
  const head = title ? html`<div class="kb-title">${title}</div>` : '';
  return String(html`<div class="${cls.join(' ')}">${head}${raw(body)}</div>`);
}

export function uiPaneHeader({ title = '', desc = '', iconName = '' } = {}) {
  const d = desc ? html`<div class="mgmt-card-intro-desc">${desc}</div>` : '';
  return String(
    html`<div class="mgmt-card-intro"><div class="mgmt-card-intro-title">${icon(iconName)}<span>${title}</span></div>${d}</div>`
  );
}

/**
 * Writes "icon words" into el with the icon in an aria-hidden span (UX-35): the icon stays out
 * of the translated text and screen readers read only the words. textContent stays "icon words".
 */
export function setIconLabel(el, icon, text) {
  if (!el) return;
  const mark = document.createElement('span');
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = icon;
  el.replaceChildren(mark, ` ${text}`);
}
