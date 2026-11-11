/**
 * What the history chart shows of its data (SET-13). The chart drew values nobody measured (a
 * sleeping drive as a flat line), cut off what lay outside two fixed axes, named three fans after
 * one machine, and showed nothing at all when it had nothing.
 */
import { t } from '../i18n.js';
import { formatDateTime, formatTime } from '../format.js';

export const REFRESH_MS = 5 * 60 * 1000; // a sample is stored every five minutes
const AVERAGED = { '7d': 30, '30d': 120 }; // minutes each point stands for

/** The time under a point: the hour for a day or less, the day and hour beyond. */
export function pointLabel(ts, range) {
  if (!AVERAGED[range]) return formatTime(ts, undefined, '');
  /** @type {any} */
  const dayAndHour = { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' };
  return formatDateTime(ts, dayAndHour, '');
}

/** The names of the drives in the data, sorted. */
export function driveNames(data) {
  const names = new Set();
  for (const d of data || []) for (const disk of d.disks || []) if (disk && disk.name) names.add(disk.name);
  return [...names].sort();
}

/** One drive's temperatures, one per point. A point at which it slept, or was not there, is a gap. */
export function driveSeries(data, name) {
  return (data || []).map((d) => {
    const disk = (d.disks || []).find((x) => x && x.name === name);
    return disk && !disk.standby && typeof disk.temp === 'number' ? disk.temp : null;
  });
}

/** How many fans the data has, and each one's speeds. */
export function fanSeries(data) {
  const count = Math.max(0, ...(data || []).map((d) => (Array.isArray(d.fans) ? d.fans.length : 0)));
  return Array.from({ length: count }, (_, i) => ({
    label: t('mch.fan_n', 'Fan {n}', { n: i + 1 }),
    data: (data || []).map((d) => (d.fans && typeof d.fans[i] === 'number' ? d.fans[i] : null)),
  }));
}

/** An axis that holds every value: from `floor` (or lower) to the highest value and some room.
 *  The drive axis was fixed at 15 to 65 °C and the fan axis at 0 to 3,500 RPM; anything beyond
 *  left the chart. */
export function axisRange(series, { floor = 0, step = 5, room = 0.1 } = {}) {
  const values = series.flat().filter((v) => typeof v === 'number' && Number.isFinite(v));
  if (!values.length) return {};
  const lo = Math.min(floor, ...values);
  const hi = Math.max(...values);
  const span = Math.max(hi - lo, step);
  return { min: Math.floor(lo / step) * step, max: Math.ceil((hi + span * room) / step) * step };
}

/** What the row of values above the chart is: a stored sample, not a live reading. */
export function readingNote(data, range) {
  const last = data && data[data.length - 1];
  if (!last) return '';
  const time = formatTime(last.ts, undefined, '');
  return AVERAGED[range]
    ? t('mch.avg_note', 'Average of the {minutes} minutes up to {time}', { minutes: AVERAGED[range], time })
    : t('mch.sample_note', 'Stored reading from {time}', { time });
}

/** The row of values: [name, value, look] per reading; a sleeping drive says so. */
export function readingPills(data) {
  const last = data && data[data.length - 1];
  if (!last) return [];
  const pills = [
    [t('mch.cpu', 'Processor'), `${last.cpu_temp} °C · ${last.cpu_util} %`, ''],
    [t('mch.mem', 'Memory'), `${last.mem_pct} %`, ''],
  ];
  for (const d of last.disks || []) {
    if (!d || !d.name) continue;
    if (d.standby) pills.push([d.name, t('mch.asleep', 'Asleep'), 'muted']);
    else if (typeof d.temp === 'number') pills.push([d.name, `${d.temp} °C`, d.temp > 50 ? 'hot' : 'ok']);
    else pills.push([d.name, t('mch.no_reading', 'No reading'), 'muted']);
  }
  (last.fans || []).forEach((rpm, i) => {
    pills.push([t('mch.fan_n', 'Fan {n}', { n: i + 1 }), typeof rpm === 'number' ? `${rpm} RPM` : t('mch.no_reading', 'No reading'), typeof rpm === 'number' ? '' : 'muted']);
  });
  return pills;
}

/** Colours for the chart's text and grid from the theme: fixed light greys were unreadable in
 *  light mode (1.4:1 for the legend). */
export function chartColors(root = document.documentElement) {
  const css = typeof getComputedStyle === 'function' ? getComputedStyle(root) : null;
  const pick = (name, fallback) => (css && css.getPropertyValue(name).trim()) || fallback;
  return { text: pick('--fg', '#c9d6d7'), muted: pick('--muted', '#95a8ab'), grid: pick('--track', 'rgba(255,255,255,0.08)'), panel: pick('--card', 'rgba(14, 27, 29, 0.95)') };
}
