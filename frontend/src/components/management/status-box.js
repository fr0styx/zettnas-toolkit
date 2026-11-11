// The Overview's status box (SET-12): one box, five states, each with an icon and a word.
//
// It used to be two boxes that could contradict each other (a green "Everything is fine" above an
// amber "No copy of your files outside this NAS yet"). A failed request removed the box, which
// reads as "nothing wrong". A check that crashed on the server was dropped, and the rest was
// drawn as fine. A failing drive and a late backup differed by the colour of a thin border.

import { escapeHtml } from '../../utils.js';
import { formatDateTime } from '../../format.js';
import { t } from '../../i18n.js';
import { hasScope } from '../../route-access.js';

export const LEVELS = ['checking', 'unknown', 'fine', 'look', 'problem'];

const WORD = {
  critical: () => t('overview.word_problem', 'Problem'),
  warning: () => t('overview.word_look', 'Needs a look'),
};
const ICON = { critical: '✕', warning: '!' };

/** Whether this person can set up a copy outside the NAS: "Protect this NAS" is shown only then. */
export function canProtect(user) {
  if (!user) return true; // not known yet: shown until the account is, as for the pages
  return ['backup:manage', 'system:config'].some((s) => hasScope(user.scopes, s));
}

/** The copy outside the NAS as a row of the same list, when there is none or it is old. */
export function protectionRow(p, user) {
  if (!p || !p.level || p.level === 'good') return null;
  const when = p.last_good ? formatDateTime(p.last_good * 1000) : '';
  const text = p.level === 'none'
    ? t('protect.none', 'No copy of your files outside this NAS yet.')
    : t('protect.stale', 'Your newest copy outside this NAS is from {when}.', { when: when || '?' });
  return { level: 'warning', text, protect: canProtect(user), tellAdmin: !canProtect(user) };
}

/**
 * What the box shows.
 * @param {{ summary?: any, protection?: any, error?: any, user?: any, rowText?: (item: any) => string, canOpen?: (place: string) => boolean }} input
 * @returns {{ level: string, rows: any[], unchecked: number, copies: any, reason: string }}
 */
export function statusState({ summary, protection, error, user, rowText, canOpen } = {}) {
  if (error) return { level: 'unknown', rows: [], unchecked: 0, copies: null, reason: String(error.message || error || '') };
  if (!summary) return { level: 'checking', rows: [], unchecked: 0, copies: null, reason: '' };
  const rows = (summary.items || []).map((i) => ({
    level: i.level === 'critical' ? 'critical' : 'warning',
    text: rowText ? rowText(i) : String(i.kind || ''),
    open: i.open && (!canOpen || canOpen(i.open)) ? i.open : null,
  }));
  const copy = protectionRow(protection, user);
  if (copy) rows.push(copy);
  const unchecked = (summary.unchecked || []).length;
  let level = 'fine';
  if (rows.some((r) => r.level === 'critical')) level = 'problem';
  else if (rows.length || unchecked) level = 'look';
  return { level, rows, unchecked, copies: protection && protection.level === 'good' ? protection : null, reason: '' };
}

function rowHtml(r) {
  const word = `<span class="ov-word"><span aria-hidden="true">${ICON[r.level]}</span> ${escapeHtml(WORD[r.level]())}</span>`;
  const tell = r.tellAdmin ? ` ${escapeHtml(t('overview.tell_admin', 'Tell the person who manages Kiboto.'))}` : '';
  let button = '';
  if (r.protect) {
    button = `<button type="button" class="btn-pill-toggle" data-ov-protect>${escapeHtml(t('protect.title', 'Protect this NAS'))}</button>`;
  } else if (r.open) {
    button = `<button type="button" class="btn-pill-toggle" data-ov-open="${escapeHtml(r.open)}" aria-label="${escapeHtml(t('overview.open_for', 'Open: {what}', { what: r.text }))}">${escapeHtml(t('overview.open', 'Open'))}</button>`;
  }
  return `<li class="ov-item ov-${r.level === 'critical' ? 'crit' : 'warn'}">${word}<span class="ov-text">${escapeHtml(r.text)}${tell}</span>${button}</li>`;
}

/** The box as markup. */
export function statusBoxHtml(state) {
  const s = state || { level: 'checking', rows: [], unchecked: 0 };
  if (s.level === 'checking') {
    return `<div class="ov-status ov-neutral" aria-busy="true"><strong><span aria-hidden="true">…</span> ${escapeHtml(t('overview.checking', 'Checking how things are'))}</strong>
      <span>${escapeHtml(t('overview.checking_desc', 'Drives, backups, power and the rest.'))}</span></div>`;
  }
  if (s.level === 'unknown') {
    return `<div class="ov-status ov-unknown" role="alert"><strong><span aria-hidden="true">?</span> ${escapeHtml(t('overview.unknown', 'Kiboto could not check how things are'))}</strong>
      <span>${escapeHtml(s.reason || t('overview.unknown_desc', 'The status could not be read. That does not mean all is well.'))}</span>
      <button type="button" class="btn-pill-toggle" data-ov-retry>${escapeHtml(t('common.try_again', 'Try again'))}</button></div>`;
  }
  const missed = s.unchecked
    ? `<span class="ov-missed">${escapeHtml(t('overview.unchecked', '{n, plural, one {One check did not run} other {# checks did not run}}, so this may not be the whole picture.', { n: s.unchecked }))}</span>`
    : '';
  if (s.level === 'fine') {
    const copies = s.copies
      ? `<span>🛡 ${escapeHtml(t('protect.good', '{n, plural, one {# current copy} other {# current copies}} outside this NAS', { n: s.copies.copies }))}${s.copies.last_good ? `. ${escapeHtml(t('protect.newest', 'The newest is from {when}.', { when: formatDateTime(s.copies.last_good * 1000) }))}` : ''}</span>`
      : '';
    return `<div class="ov-status ov-ok"><strong><span aria-hidden="true">✓</span> ${escapeHtml(t('overview.all_good', 'Everything is fine'))}</strong>
      <span>${escapeHtml(t('overview.all_good_desc', 'Nothing needs your attention.'))}</span>${copies}</div>`;
  }
  const n = s.rows.length;
  const problem = s.level === 'problem';
  const lead = problem ? `<span aria-hidden="true">✕</span> ${escapeHtml(t('overview.word_problem', 'Problem'))}` : `<span aria-hidden="true">!</span> ${escapeHtml(t('overview.word_look', 'Needs a look'))}`;
  const count = n ? `: ${escapeHtml(t('overview.attention', '{n, plural, one {# thing needs your attention} other {# things need your attention}}', { n }))}` : '';
  return `<div class="ov-status ${problem ? 'ov-problem' : 'ov-attention'}"><strong>${lead}${count}</strong>${missed}
    ${n ? `<ul>${s.rows.map(rowHtml).join('')}</ul>` : ''}</div>`;
}

/** The status in one sentence, for screen readers. */
export function statusSaid(state) {
  const s = state || {};
  if (s.level === 'checking') return t('overview.checking', 'Checking how things are');
  if (s.level === 'unknown') return t('overview.unknown', 'Kiboto could not check how things are');
  const n = (s.rows || []).length;
  if (s.level === 'fine') return t('a11y.status_ok', 'All is well.');
  const said = t('a11y.status_items', '{n, plural, one {# thing needs attention} other {# things need attention}}', { n: Math.max(n, 1) });
  return s.level === 'problem' ? `${t('overview.word_problem', 'Problem')}: ${said}` : said;
}
