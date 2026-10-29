/**
 * Small line charts for Drive Health's history (temperature, error counters), drawn as SVG
 * elements. Colours come from the theme (currentColor and CSS classes), so they work in light
 * and dark.
 */
const NS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

/** The points of a series scaled into a w x h box (time on x, value on y). */
export function scale(points, w, h, pad = 4) {
  if (!points || !points.length) return [];
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  let y0 = Math.min(...ys);
  let y1 = Math.max(...ys);
  if (y0 === y1) {
    y0 -= 1;
    y1 += 1;
  }
  const sx = x1 === x0 ? 0 : (w - 2 * pad) / (x1 - x0);
  const sy = (h - 2 * pad) / (y1 - y0);
  return points.map(([x, y]) => [x1 === x0 ? w / 2 : pad + (x - x0) * sx, h - pad - (y - y0) * sy]);
}

/** A line chart with an accessible name; `label` says what it shows in words. */
export function lineChart(points, { width = 320, height = 80, label = '', className = '' } = {}) {
  const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, width: '100%', height, role: 'img', class: `dh-chart ${className}`.trim() });
  if (label) {
    const title = svgEl('title');
    title.textContent = label;
    svg.append(title);
  }
  const scaled = scale(points, width, height);
  if (scaled.length === 1) {
    svg.append(svgEl('circle', { cx: scaled[0][0], cy: scaled[0][1], r: 3, class: 'dh-chart-dot' }));
  } else if (scaled.length > 1) {
    const r = (v) => Math.round(v * 10) / 10;
    const d = scaled.map(([x, y], i) => `${i ? 'L' : 'M'}${r(x)} ${r(y)}`).join(' ');
    svg.append(svgEl('path', { d, class: 'dh-chart-line', fill: 'none' }));
  }
  return svg;
}
