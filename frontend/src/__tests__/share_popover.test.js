import { describe, it, expect } from 'vitest';
import { placePopover } from '../components/file-manager.js';

function pop(w, h) {
  const el = document.createElement('div');
  Object.defineProperty(el, 'offsetWidth', { value: w });
  Object.defineProperty(el, 'offsetHeight', { value: h });
  return el;
}

describe('share link pop-over placement', () => {
  it('opens below the clicked button with right edges aligned', () => {
    window.innerWidth = 1500; window.innerHeight = 1000;
    const el = pop(480, 400);
    placePopover(el, { left: 1180, right: 1200, top: 240, bottom: 260 });
    expect(el.style.left).toBe('720px');
    expect(el.style.top).toBe('268px');
  });
  it('flips above when there is no room below, and stays on screen', () => {
    window.innerWidth = 1500; window.innerHeight = 900;
    const el = pop(480, 400);
    placePopover(el, { left: 1180, right: 1200, top: 700, bottom: 720 });
    expect(el.style.top).toBe('292px');
    const edge = pop(480, 400);
    placePopover(edge, { left: 100, right: 120, top: 50, bottom: 70 });
    expect(edge.style.left).toBe('12px');
  });
});
