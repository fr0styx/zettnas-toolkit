/**
 * Sign-in hours in the edit-person dialog (COMP-13): which days and times a family account may
 * be signed in. The server enforces them; this only edits them.
 */
import { t } from '../i18n.js';
import { currentLocale } from '../format.js';

/** Monday first, as the server counts (0 = Monday). */
export function dayNames(locale = currentLocale()) {
  const fmt = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' });
  return [5, 6, 7, 8, 9, 10, 11].map((d) => fmt.format(new Date(Date.UTC(2024, 1, d)))); // 5 Feb 2024 was a Monday
}

/** The fields' state -> what PUT /api/users/{id} takes ({} removes the limit). */
export function readHours(box) {
  if (!box.querySelector('[data-hours-on]').checked) return {};
  return {
    days: [...box.querySelectorAll('[data-hours-day]')].filter((c) => c.checked).map((c) => Number(c.value)),
    start: box.querySelector('[data-hours-start]').value,
    end: box.querySelector('[data-hours-end]').value,
  };
}

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (v === true) n.setAttribute(k, '');
    else if (v !== false && v !== null && v !== undefined) n.setAttribute(k, v);
  }
  children.flat().forEach((c) => c !== null && c !== undefined && n.append(c));
  return n;
}

/** Builds the fields into `box` for this person; returns a function that says whether they changed. */
export function installSigninHours(box, user, { canBeLimited = true } = {}) {
  if (!box) return () => false;
  box.hidden = !canBeLimited;
  const hours = user?.signin_hours || null;
  const days = new Set(hours ? hours.days : [0, 1, 2, 3, 4]);
  const on = el('input', { type: 'checkbox', 'data-hours-on': true });
  on.checked = Boolean(hours);
  const dayBoxes = dayNames().map((n, i) => {
    const c = el('input', { type: 'checkbox', 'data-hours-day': true, value: String(i) });
    c.checked = days.has(i);
    return el('label', { class: 'zn-hours-day' }, c, el('span', { text: n }));
  });
  const start = el('input', { type: 'time', class: 'tz-select-input', 'data-hours-start': true });
  start.value = hours ? hours.start : '07:00';
  const end = el('input', { type: 'time', class: 'tz-select-input', 'data-hours-end': true });
  end.value = hours ? hours.end : '20:00';
  const fields = el('div', { class: 'zn-hours', 'data-hours-fields': true },
    el('div', { class: 'zn-hours-days', role: 'group', 'aria-label': t('hours.days', 'Days') }, dayBoxes),
    el('div', { class: 'zn-hours-times' },
      el('label', {}, t('hours.from', 'From'), ' ', start),
      el('label', {}, t('hours.until', 'Until'), ' ', end)),
    el('div', { class: 'zn-sub', text: t('hours.hint', "Server time. Outside these hours this person can't sign in, and an open session stops until they start again.") }));
  fields.hidden = !hours;
  box.replaceChildren(el('label', { class: 'zn-toggle' }, on, el('span', { text: t('hours.only_at', 'Only at these times') })), fields);
  let changed = false;
  on.addEventListener('change', () => { fields.hidden = !on.checked; });
  box.addEventListener('change', () => { changed = true; });
  return () => changed;
}
