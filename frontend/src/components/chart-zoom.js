// X-axis zoom and pan for the metrics chart (ARC-15), on pointer events: wheel zooms around
// the cursor, a drag pans, two fingers pinch. It replaces chartjs-plugin-zoom, which pulled in
// the unmaintained hammerjs. Options live under plugins.znZoom:
//   { wheelSpeed: 0.08, minPoints: 5, onChange: (chart, zoomed) => {} }
// chart.resetZoom() shows every point again.

const PAN_THRESHOLD_PX = 5;

function pointCount(chart) {
  return (chart.data && chart.data.labels && chart.data.labels.length) || 0;
}

/** The visible index window [lo, hi] (whole numbers, inclusive). */
export function windowOf(chart) {
  const n = pointCount(chart);
  const x = chart.options.scales && chart.options.scales.x ? chart.options.scales.x : {};
  const lo = Number.isFinite(x.min) ? x.min : 0;
  const hi = Number.isFinite(x.max) ? x.max : Math.max(0, n - 1);
  return [lo, hi];
}

function setWindow(chart, lo, hi) {
  const n = pointCount(chart);
  const last = Math.max(0, n - 1);
  let span = hi - lo;
  const minSpan = Math.min(last, Math.max(1, (chart.options.plugins?.znZoom?.minPoints ?? 5) - 1));
  if (span < minSpan) {
    const mid = (lo + hi) / 2;
    lo = mid - minSpan / 2;
    hi = mid + minSpan / 2;
    span = minSpan;
  }
  if (span >= last) {
    lo = 0;
    hi = last;
  } else {
    if (lo < 0) {
      hi -= lo;
      lo = 0;
    }
    if (hi > last) {
      lo -= hi - last;
      hi = last;
    }
  }
  const x = (chart.options.scales.x = chart.options.scales.x || {});
  const full = Math.round(lo) <= 0 && Math.round(hi) >= last;
  x.min = full ? undefined : Math.round(lo);
  x.max = full ? undefined : Math.round(hi);
  chart.update('none');
  chart.options.plugins?.znZoom?.onChange?.(chart, !full);
}

/** Zoom by `factor` (< 1 zooms in) around the data index `anchor`. */
export function zoomAround(chart, factor, anchor) {
  const [lo, hi] = windowOf(chart);
  const a = Math.min(hi, Math.max(lo, anchor));
  setWindow(chart, a - (a - lo) * factor, a + (hi - a) * factor);
}

/** Move the window by `delta` data points (positive shows later points). */
export function panBy(chart, delta) {
  const [lo, hi] = windowOf(chart);
  setWindow(chart, lo + delta, hi + delta);
}

function indexAt(chart, px) {
  const scale = chart.scales && chart.scales.x;
  if (!scale) return windowOf(chart)[0];
  const [lo, hi] = windowOf(chart);
  const width = Math.max(1, scale.right - scale.left);
  return lo + ((px - scale.left) / width) * (hi - lo);
}

function pointsPerPixel(chart) {
  const scale = chart.scales && chart.scales.x;
  const [lo, hi] = windowOf(chart);
  return scale ? (hi - lo) / Math.max(1, scale.right - scale.left) : 0;
}

export const znZoomPlugin = {
  id: 'znZoom',
  afterInit(chart) {
    const canvas = chart.canvas;
    if (!canvas || typeof canvas.addEventListener !== 'function') return;
    const opts = () => chart.options.plugins?.znZoom || {};
    const pointers = new Map();
    let drag = null;
    let pinch = null;

    const local = (e) => {
      const r = canvas.getBoundingClientRect();
      return e.clientX - r.left;
    };
    const onWheel = (e) => {
      if (opts().enabled === false) return;
      e.preventDefault();
      const speed = opts().wheelSpeed ?? 0.08;
      zoomAround(chart, e.deltaY < 0 ? 1 - speed : 1 + speed, indexAt(chart, local(e)));
    };
    const onDown = (e) => {
      if (opts().enabled === false) return;
      pointers.set(e.pointerId, local(e));
      if (pointers.size === 1) {
        drag = { x: local(e), moved: false };
      } else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { dist: Math.abs(a - b) || 1, mid: indexAt(chart, (a + b) / 2) };
        drag = null;
      }
    };
    const onMove = (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, local(e));
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const dist = Math.abs(a - b) || 1;
        zoomAround(chart, pinch.dist / dist, pinch.mid);
        pinch.dist = dist;
      } else if (drag) {
        const dx = local(e) - drag.x;
        if (!drag.moved && Math.abs(dx) < PAN_THRESHOLD_PX) return;
        drag.moved = true;
        panBy(chart, -dx * pointsPerPixel(chart));
        drag.x = local(e);
      }
    };
    const onUp = (e) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (pointers.size === 0) drag = null;
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.style.touchAction = 'pan-y'; // vertical scrolling stays with the page
    chart.resetZoom = () => setWindow(chart, 0, Math.max(0, pointCount(chart) - 1));
    chart._znZoomCleanup = () => {
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointercancel', onUp);
    };
  },
  afterDestroy(chart) {
    chart._znZoomCleanup?.();
  },
};
