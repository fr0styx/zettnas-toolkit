import { describe, it, expect } from 'vitest';
import { setIconLabel } from '../ui/primitives.js';

describe('setIconLabel keeps icons out of the words (UX-35)', () => {
  it('puts the icon in an aria-hidden span and keeps the visible text', () => {
    const btn = document.createElement('button');
    btn.textContent = 'old';
    setIconLabel(btn, '⏳', 'Backing up...');
    expect(btn.textContent).toBe('⏳ Backing up...');
    const mark = btn.querySelector('span[aria-hidden="true"]');
    expect(mark.textContent).toBe('⏳');
    expect(btn.childNodes[1].nodeValue).toBe(' Backing up...');
  });

  it('does nothing without an element', () => {
    expect(() => setIconLabel(null, '⏳', 'x')).not.toThrow();
  });

  it('treats the words as text, not markup', () => {
    const el = document.createElement('div');
    setIconLabel(el, '✨', '<b>bold</b>');
    expect(el.querySelector('b')).toBeNull();
    expect(el.textContent).toBe('✨ <b>bold</b>');
  });
});
