/**
 * Drive Health: every S.M.A.R.T. value of a drive, each with how it moved over the last 30 days,
 * and the drives that were taken out of the box. Both come from what is stored, so a sleeping
 * drive is shown without waking it.
 */
import { t } from '../i18n.js';
import { formatBytes, formatDateTime } from '../format.js';
import { lineChart } from './drive-charts.js';
import { labelText, warrantyText } from './drive-health-report.js';

const when = (ts) => (ts ? formatDateTime(ts * 1000, undefined, '') : '');

// Raw values that only ever mean trouble when they grow (Backblaze's five, plus a few more)
const WATCHED = new Set(['5', '10', '184', '187', '188', '196', '197', '198', '199', 'nvme.media_errors', 'nvme.critical_warning']);

/** "Reallocated_Sector_Ct" -> "Reallocated sector ct"; NVMe "media_errors" -> "Media errors". */
export function prettyName(name) {
  const text = String(name || '').replace(/_/g, ' ').trim();
  return text ? text[0].toUpperCase() + text.slice(1).toLowerCase() : '';
}

/** The values in table order (ATA ids by number, then NVMe fields), with whether each moved. */
export function valueRows(attrs) {
  const rows = Object.entries(attrs || {}).map(([attr, a]) => {
    const first = a.points && a.points.length ? a.points[0][1] : a.raw;
    return { attr, ...a, moved: a.raw !== first, rose: WATCHED.has(attr) && a.raw > first, low: a.thresh != null && a.value != null && a.thresh > 0 && a.value <= a.thresh };
  });
  const order = (r) => (/^\d+$/.test(r.attr) ? Number(r.attr) : 1000);
  return rows.sort((x, y) => order(x) - order(y) || x.attr.localeCompare(y.attr));
}

const cell = (tag, text, cls = '') => {
  const c = document.createElement(tag);
  c.textContent = text == null ? '–' : String(text);
  if (cls) c.className = cls;
  return c;
};

/** The "Every value" table, as an element; a row whose value moved gets a small chart of it. */
export function valuesTable(attrs) {
  const rows = valueRows(attrs);
  const box = document.createElement('div');
  box.className = 'dh-values';
  if (!rows.length) {
    box.append(cell('p', t('dh.v_none', 'Shown after the drive has been read while awake; the values build up from then on.'), 'dh-hint'));
    return box;
  }
  const table = document.createElement('table');
  table.className = 'dh-readings dh-values-table';
  const head = document.createElement('tr');
  for (const h of [t('dh.v_id', 'ID'), t('dh.v_name', 'Name'), t('dh.v_norm', 'Normalized'), t('dh.v_worst', 'Worst'), t('dh.v_thresh', 'Threshold'), t('dh.v_raw', 'Raw'), t('dh.v_trend', '30 days')]) {
    const th = cell('th', h);
    th.scope = 'col';
    head.append(th);
  }
  const thead = document.createElement('thead');
  thead.append(head);
  const body = document.createElement('tbody');
  for (const r of rows) {
    const tr = document.createElement('tr');
    if (r.rose || r.low) tr.className = 'is-rising';
    const name = cell('th', prettyName(r.name) || r.attr);
    name.scope = 'row';
    tr.append(cell('td', /^\d+$/.test(r.attr) ? r.attr : ''), name, cell('td', r.value), cell('td', r.worst), cell('td', r.thresh), cell('td', r.raw));
    const trend = document.createElement('td');
    if (r.moved && r.points.length > 1) {
      const label = t('dh.v_moved', '{name}: from {a} to {b}', { name: prettyName(r.name), a: r.points[0][1], b: r.raw });
      trend.append(lineChart(r.points, { label, height: 24, width: 120, className: r.rose ? 'is-rising' : '' }));
    } else {
      trend.textContent = t('dh.v_steady', 'steady');
      trend.className = 'dh-hint';
    }
    tr.append(trend);
    body.append(tr);
  }
  table.append(thead, body);
  const hint = cell('p', t('dh.v_hint', 'Highlighted: a value that only means trouble went up, or a normalized value reached its threshold.'), 'dh-hint');
  box.append(table, hint);
  return box;
}

/** The "Taken out" list for the side panel; `onForget(serial)` drops a drive's record. */
export function takenOutBox(drives, notes, onForget) {
  const box = document.createElement('details');
  box.className = 'dh-retired';
  if (!drives || !drives.length) {
    box.hidden = true;
    return box;
  }
  const summary = document.createElement('summary');
  summary.textContent = t('dh.retired', 'Taken out ({n})', { n: drives.length });
  const list = document.createElement('ul');
  list.className = 'dh-retired-list';
  for (const d of drives) {
    const li = document.createElement('li');
    const name = cell('strong', d.model || d.serial);
    const n = (notes && notes[d.serial]) || {};
    const bits = [
      d.serial,
      d.capacity_bytes ? formatBytes(d.capacity_bytes) : '',
      d.label_key ? labelText(d) : '',
      t('dh.retired_seen', 'last seen {date}', { date: when(d.last_seen) }),
      n.warranty_until ? `${t('dh.n_warranty', 'Warranty')}: ${warrantyText(n.warranty_until)}` : '',
    ].filter(Boolean);
    const meta = cell('span', bits.join(' · '), 'dh-card-meta');
    const forget = document.createElement('button');
    forget.type = 'button';
    forget.className = 'btn-pill-toggle is-small';
    forget.textContent = t('dh.retired_forget', 'Forget');
    forget.setAttribute('aria-label', t('dh.retired_forget_one', 'Forget {name}', { name: d.model || d.serial }));
    forget.addEventListener('click', () => onForget(d.serial));
    li.append(name, meta, forget);
    list.append(li);
  }
  const hint = cell('p', t('dh.retired_hint', 'Drives that were in this box before. Put one back in and it is shown with its history again.'), 'dh-hint');
  box.append(summary, hint, list);
  return box;
}
