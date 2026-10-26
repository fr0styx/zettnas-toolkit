// Escaping HTML templates (ARC-11).
//
//   el.innerHTML = html`<b>${name}</b> ${html`<i>${note}</i>`} ${items.map((i) => html`<li>${i}</li>`)}`;
//
// Every interpolated value is escaped, unless it is itself an html`` result (already safe) or
// wrapped in raw() on purpose (markup you built and trust). Arrays are joined; null, undefined
// and false render as nothing. The result converts to a string wherever one is expected
// (innerHTML, insertAdjacentHTML, string concatenation).
import { escapeHtml } from './utils.js';

export class SafeHtml {
  constructor(value) {
    this.value = value;
  }

  toString() {
    return this.value;
  }
}

/** Markup inserted as is. Only for HTML you built yourself; never for text from users or the API. */
export function raw(markup) {
  return new SafeHtml(String(markup ?? ''));
}

function part(value) {
  if (value instanceof SafeHtml) return value.value;
  if (Array.isArray(value)) return value.map(part).join('');
  if (value === null || value === undefined || value === false) return '';
  return escapeHtml(value);
}

export function html(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) out += part(values[i]) + strings[i + 1];
  return new SafeHtml(out);
}
