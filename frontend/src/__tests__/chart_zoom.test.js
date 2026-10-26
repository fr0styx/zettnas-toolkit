import { describe, expect, it, vi } from 'vitest';
import { panBy, windowOf, zoomAround, znZoomPlugin } from '../components/chart-zoom.js';

function fakeChart(n = 101, extra = {}) {
  return {
    data: { labels: Array.from({ length: n }, (_, i) => String(i)) },
    options: { scales: { x: {} }, plugins: { znZoom: { minPoints: 5, ...extra } } },
    scales: { x: { left: 0, right: 1000 } },
    update: vi.fn(),
  };
}

describe('chart zoom without hammerjs (ARC-15)', () => {
  it('zooms around a point and stays inside the data', () => {
    const c = fakeChart();
    zoomAround(c, 0.5, 50);
    expect(windowOf(c)).toEqual([25, 75]);
    zoomAround(c, 0.01, 30); // never fewer than minPoints
    const [lo, hi] = windowOf(c);
    expect(hi - lo).toBe(4);
    zoomAround(c, 100, 50); // zooming far out shows everything
    expect(c.options.scales.x.min).toBeUndefined();
    expect(windowOf(c)).toEqual([0, 100]);
  });

  it('pans within the data and reports whether it is zoomed', () => {
    const changes = [];
    const c = fakeChart(101, { onChange: (_c, zoomed) => changes.push(zoomed) });
    zoomAround(c, 0.2, 50);
    panBy(c, 1000);
    expect(windowOf(c)[1]).toBe(100);
    panBy(c, -1000);
    expect(windowOf(c)[0]).toBe(0);
    expect(changes.every(Boolean)).toBe(true);
  });

  it('wires wheel, drag and pinch on the canvas, and resets', () => {
    const canvas = new EventTarget();
    canvas.style = {};
    canvas.getBoundingClientRect = () => ({ left: 0 });
    const c = { ...fakeChart(), canvas };
    znZoomPlugin.afterInit(c);
    expect(canvas.style.touchAction).toBe('pan-y');

    const wheel = Object.assign(new Event('wheel', { cancelable: true }), { deltaY: -1, clientX: 500 });
    canvas.dispatchEvent(wheel);
    expect(wheel.defaultPrevented).toBe(true);
    const [lo, hi] = windowOf(c);
    expect(hi - lo).toBeLessThan(100);

    const ev = (type, id, x) => Object.assign(new Event(type), { pointerId: id, clientX: x });
    canvas.dispatchEvent(ev('pointerdown', 1, 500));
    canvas.dispatchEvent(ev('pointermove', 1, 502)); // under the threshold: no pan
    expect(windowOf(c)).toEqual([lo, hi]);
    canvas.dispatchEvent(ev('pointermove', 1, 300)); // drag left: later points
    expect(windowOf(c)[0]).toBeGreaterThan(lo);
    canvas.dispatchEvent(ev('pointerdown', 2, 600)); // a second finger: pinch
    const before = windowOf(c);
    canvas.dispatchEvent(ev('pointermove', 2, 900)); // fingers apart: zoom in
    const after = windowOf(c);
    expect(after[1] - after[0]).toBeLessThan(before[1] - before[0]);
    canvas.dispatchEvent(ev('pointerup', 2, 900));
    canvas.dispatchEvent(ev('pointerup', 1, 300));

    c.resetZoom();
    expect(windowOf(c)).toEqual([0, 100]);
    znZoomPlugin.afterDestroy(c);
  });
});
