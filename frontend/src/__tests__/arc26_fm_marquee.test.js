/** ARC-26: rubber-band selection in the file manager (FmMarqueeController). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { FmMarqueeController } from '../components/file-manager-helpers.js';

const rect = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height });
function pointer(type, x, y, extra = {}) {
  const e = new MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true, ...extra });
  Object.defineProperty(e, 'pointerType', { value: extra.pointerType || 'mouse' });
  Object.defineProperty(e, 'pointerId', { value: 1 });
  return e;
}

function setup(selected = []) {
  document.body.innerHTML = '<div id="vp"><div class="fm-row" data-path="/a" data-name="a"></div><div class="fm-row" data-path="/b" data-name="b"></div><div class="fm-row" data-path="/up" data-name=".."></div><button class="fm-act-btn"></button></div><div id="box"></div>';
  const viewport = document.getElementById('vp');
  viewport.getBoundingClientRect = () => rect(0, 0, 300, 300);
  viewport.setPointerCapture = vi.fn();
  viewport.releasePointerCapture = vi.fn(() => { throw new Error('not captured'); });
  const [a, b, up] = viewport.querySelectorAll('.fm-row');
  a.getBoundingClientRect = () => rect(10, 10, 100, 20);
  b.getBoundingClientRect = () => rect(10, 100, 100, 20);
  up.getBoundingClientRect = () => rect(10, 50, 100, 20);
  const fm = {
    viewport,
    marqueeBox: document.getElementById('box'),
    selectedPaths: new Set(selected),
    clearSelection: vi.fn(function () { this.selectedPaths = new Set(); }),
    updateRowSelectionUI: vi.fn(),
    updateSelectionToolbar: vi.fn(),
    inspector: { update: vi.fn() },
  };
  return { fm, ctl: new FmMarqueeController(fm), viewport };
}

describe('rubber-band selection', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('selects what the box touches, never the parent-folder row', () => {
    const { fm, viewport } = setup(['/old']);
    viewport.dispatchEvent(pointer('pointerdown', 0, 0));
    window.dispatchEvent(pointer('pointermove', 2, 2)); // under the threshold: nothing yet
    expect(fm.clearSelection).not.toHaveBeenCalled();
    window.dispatchEvent(pointer('pointermove', 150, 80));
    expect(fm.clearSelection).toHaveBeenCalled();
    expect([...fm.selectedPaths]).toEqual(['/a']);
    expect(fm.marqueeBox.style.display).toBe('block');
    expect(fm.marqueeBox.style.width).toBe('150px');
    window.dispatchEvent(pointer('pointermove', 150, 290)); // near the bottom edge: scrolls
    expect([...fm.selectedPaths].sort()).toEqual(['/a', '/b']);
    window.dispatchEvent(pointer('pointerup', 150, 290));
    expect(fm.marqueeBox.style.display).toBe('none');
    expect(fm._suppressNextViewportClick).toBe(true);
    vi.advanceTimersByTime(400);
    expect(fm._suppressNextViewportClick).toBe(false);
    window.dispatchEvent(pointer('pointermove', 10, 10)); // after release: ignored
    window.dispatchEvent(pointer('pointerup', 10, 10));
    expect(fm.inspector.update).toHaveBeenCalled();
  });

  it('Ctrl adds to the selection and toggles what was already chosen', () => {
    const { fm, viewport } = setup(['/a', '/z']);
    viewport.dispatchEvent(pointer('pointerdown', 0, 0, { ctrlKey: true }));
    window.dispatchEvent(pointer('pointermove', 150, 130));
    expect([...fm.selectedPaths].sort()).toEqual(['/b', '/z']);
    expect(fm.clearSelection).not.toHaveBeenCalled();
    window.dispatchEvent(pointer('pointermove', 150, 5)); // near the top edge
    window.dispatchEvent(pointer('pointerup', 150, 5));
  });

  it('a click without dragging does not swallow the next click', () => {
    const { fm, viewport } = setup();
    viewport.dispatchEvent(pointer('pointerdown', 40, 40));
    window.dispatchEvent(pointer('pointerup', 40, 40));
    expect(fm._suppressNextViewportClick).toBeUndefined();
  });

  it('starts only for the left mouse button on empty space', () => {
    const { fm, viewport } = setup();
    viewport.dispatchEvent(pointer('pointerdown', 0, 0, { pointerType: 'touch' }));
    viewport.dispatchEvent(pointer('pointerdown', 0, 0, { button: 2 }));
    viewport.querySelector('.fm-act-btn').dispatchEvent(pointer('pointerdown', 0, 0));
    window.dispatchEvent(pointer('pointermove', 200, 200));
    expect(fm.updateRowSelectionUI).not.toHaveBeenCalled();
    expect(viewport.setPointerCapture).not.toHaveBeenCalled();
  });

  it('works without a box element or an inspector, and without a viewport', () => {
    const { fm, viewport } = setup();
    fm.marqueeBox = null;
    fm.inspector = null;
    viewport.dispatchEvent(pointer('pointerdown', 0, 0));
    window.dispatchEvent(pointer('pointermove', 150, 80));
    window.dispatchEvent(pointer('pointerup', 150, 80));
    expect(fm.selectedPaths.has('/a')).toBe(true);
    expect(() => new FmMarqueeController({ viewport: null })).not.toThrow();
    expect(viewport).toBeTruthy();
  });
});
