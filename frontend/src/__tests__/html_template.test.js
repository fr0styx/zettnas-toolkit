import { describe, expect, it } from 'vitest';
import { html, raw, SafeHtml } from '../html.js';

describe('html`` escaping templates (ARC-11)', () => {
  it('escapes every value', () => {
    const name = '<img src=x onerror=alert(1)>';
    expect(String(html`<b>${name}</b>`)).toBe('<b>&lt;img src=x onerror=alert(1)&gt;</b>');
    expect(String(html`<a title="${'"quoted" & \'single\''}">x</a>`)).toBe(
      '<a title="&quot;quoted&quot; &amp; &#039;single&#039;">x</a>'
    );
    expect(String(html`${42} ${0}`)).toBe('42 0');
  });

  it('keeps nested templates, joins arrays, drops empty values', () => {
    const items = ['a<', 'b'];
    const out = html`<ul>${items.map((i) => html`<li>${i}</li>`)}</ul>${null}${undefined}${false}`;
    expect(out).toBeInstanceOf(SafeHtml);
    expect(String(out)).toBe('<ul><li>a&lt;</li><li>b</li></ul>');
  });

  it('inserts raw() markup as is, and works with innerHTML', () => {
    const el = document.createElement('div');
    el.innerHTML = html`<p>${raw('<em>trusted</em>')} ${'<em>not</em>'}</p>`;
    expect(el.querySelector('em').textContent).toBe('trusted');
    expect(el.querySelectorAll('em').length).toBe(1);
    expect(String(raw(null))).toBe('');
  });
});
