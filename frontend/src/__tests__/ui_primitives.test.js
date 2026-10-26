import { describe, expect, it } from 'vitest';
import { uiButton, uiCard, uiField, uiPaneHeader } from '../ui/primitives.js';

describe('UI primitives (UX-11)', () => {
  it('builds the system button with its variants', () => {
    const html = uiButton({ label: 'Save', variant: 'primary', small: true, id: 'save-btn' });
    expect(html).toBe('<button type="button" id="save-btn" class="btn-pill-toggle is-primary is-small"><span>Save</span></button>');
    expect(uiButton({ label: 'x', variant: 'nonsense' })).toContain('class="btn-pill-toggle"');
    expect(uiButton({ iconName: 'trash', variant: 'danger', block: true, extra: { disabled: true, 'aria-label': 'Delete' } }))
      .toBe('<button type="button" class="btn-pill-toggle is-danger is-block" disabled aria-label="Delete"><svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg></button>');
  });

  it('escapes text', () => {
    expect(uiButton({ label: '<b>' })).toContain('&lt;b&gt;');
    expect(uiPaneHeader({ title: 'A & B', desc: '"q"' })).toContain('A &amp; B');
    expect(uiField({ label: '<i>', control: '<input id="n">', id: 'n' })).toContain('&lt;i&gt;');
  });

  it('builds a field, a card and a pane header', () => {
    expect(uiField({ label: 'Name', control: '<input id="n">', hint: 'Your name', id: 'n' }))
      .toBe('<label class="zn-field" for="n"><span>Name</span><input id="n"><span class="zn-muted">Your name</span></label>');
    expect(uiCard({ title: 'Disks', body: '<p>2</p>', variant: 'boxed' }))
      .toBe('<div class="zn-card zn-card--boxed"><div class="zn-title">Disks</div><p>2</p></div>');
    expect(uiCard({ body: 'x', variant: 'odd' })).toBe('<div class="zn-card">x</div>');
    expect(uiPaneHeader({ title: 'Wallpapers', desc: 'Pick one', iconName: 'screen' }))
      .toBe('<div class="mgmt-card-intro"><div class="mgmt-card-intro-title"><svg class="ic" aria-hidden="true"><use href="#i-screen"/></svg><span>Wallpapers</span></div><div class="mgmt-card-intro-desc">Pick one</div></div>');
  });
});
