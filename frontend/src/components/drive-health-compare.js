/**
 * Drive Health: every drive side by side in one sortable table (health, temperature, age, size,
 * warranty), to see at a glance which one is hottest, oldest or out of warranty. A row opens
 * that drive. Built from what the list already has: nothing is read from the drives for it.
 */
import { t } from '../i18n.js';
import { formatBytes } from '../format.js';
import { labelText, monthsLeft, warrantyText } from './drive-health-report.js';

const SEVERITY = { now: 0, soon: 1, watch: 2, unknown: 3, ok: 4 };
const YEAR_HOURS = 8766;

/** The columns: header text, the cell text, and the value to sort by. */
export function columns(notes) {
  const note = (d) => (d.serial && notes && notes[d.serial]) || {};
  return [
    { key: 'name', head: t('dh.c_drive', 'Drive'), text: (d) => `${d.model || d.dev} (${d.dev})`, value: (d) => String(d.model || d.dev).toLowerCase() },
    { key: 'health', head: t('dh.c_health', 'Health'), text: (d) => labelText(d), value: (d) => SEVERITY[d.verdict] ?? 3 },
    { key: 'temp', head: t('dh.c_temp', 'Temperature'), text: (d) => (d.temp != null ? `${Math.round(d.temp)} °C` : '–'), value: (d) => (d.temp != null ? -d.temp : Infinity) },
    {
      key: 'age',
      head: t('dh.c_age', 'Powered on'),
      text: (d) => (d.power_on_hours ? t('dh.a_years', '{y, plural, one {# year} other {# years}}', { y: Math.round((d.power_on_hours / YEAR_HOURS) * 10) / 10 }) : '–'),
      value: (d) => (d.power_on_hours ? -d.power_on_hours : Infinity),
    },
    { key: 'size', head: t('dh.c_size', 'Size'), text: (d) => (d.capacity_bytes ? formatBytes(d.capacity_bytes) : '–'), value: (d) => -(Number(d.capacity_bytes) || 0) },
    {
      key: 'warranty',
      head: t('dh.n_warranty', 'Warranty'),
      text: (d) => (note(d).warranty_until ? warrantyText(note(d).warranty_until) : '–'),
      value: (d) => (note(d).warranty_until ? monthsLeft(note(d).warranty_until) : Infinity),
    },
  ];
}

/** The drives in the order of `key` (worst, hottest, oldest, biggest or soonest first), then by name. */
export function sortDrives(drives, notes, key = 'health', reverse = false) {
  const cols = columns(notes);
  const col = cols.find((c) => c.key === key) || cols[1];
  const byName = cols[0].value;
  const out = [...(drives || [])].sort((a, b) => {
    const x = col.value(a);
    const y = col.value(b);
    if (x < y) return -1;
    if (x > y) return 1;
    return byName(a) < byName(b) ? -1 : byName(a) > byName(b) ? 1 : 0;
  });
  return reverse ? out.reverse() : out;
}

/**
 * The table, as an element. `onPick(dev)` opens a drive; a header button sorts by its column
 * (again: the other way round).
 */
export function compareTable(drives, notes, onPick, key = 'health', reverse = false) {
  const box = document.createElement('div');
  box.className = 'dh-compare';
  const title = document.createElement('h3');
  title.className = 'dh-title';
  title.textContent = t('dh.compare', 'All drives side by side');
  const table = document.createElement('table');
  table.className = 'dh-readings dh-compare-table';
  const head = document.createElement('tr');
  for (const c of columns(notes)) {
    const th = document.createElement('th');
    th.scope = 'col';
    if (c.key === key) th.setAttribute('aria-sort', reverse ? 'descending' : 'ascending');
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'dh-sort';
    b.textContent = c.head;
    b.addEventListener('click', () => box.replaceWith(compareTable(drives, notes, onPick, c.key, c.key === key ? !reverse : false)));
    th.append(b);
    head.append(th);
  }
  const thead = document.createElement('thead');
  thead.append(head);
  const body = document.createElement('tbody');
  const cols = columns(notes);
  for (const d of sortDrives(drives, notes, key, reverse)) {
    const tr = document.createElement('tr');
    tr.className = `dh-compare-row is-${d.verdict || 'unknown'}`;
    cols.forEach((c, i) => {
      const cell = document.createElement(i === 0 ? 'th' : 'td');
      if (i === 0) {
        cell.scope = 'row';
        const open = document.createElement('button');
        open.type = 'button';
        open.className = 'dh-sort';
        open.textContent = c.text(d);
        open.addEventListener('click', () => onPick(d.dev));
        cell.append(open);
      } else if (c.key === 'health') {
        const pill = document.createElement('span');
        pill.className = `dh-pill is-${d.verdict || 'unknown'}`;
        pill.textContent = c.text(d);
        cell.append(pill);
      } else {
        cell.textContent = c.text(d);
      }
      tr.append(cell);
    });
    body.append(tr);
  }
  table.append(thead, body);
  const hint = document.createElement('p');
  hint.className = 'dh-hint';
  hint.textContent = t('dh.compare_hint', 'Sort by a column; choose a drive to open it.');
  box.append(title, hint, table);
  return box;
}
