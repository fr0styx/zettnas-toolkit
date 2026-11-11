/**
 * What the Event Log, the bell, the bell's preview and the entry dialog show of an entry
 * (SET-13). Each had its own copy: the log used the reader's language, the bell and the dialog
 * the server's English, and the dialog guessed the page an entry belongs to from English words
 * in its text ("could not copy" opened the card settings for a failed backup).
 */
import { eventLook } from './event-level.js';
import { eventText } from './event-text.js';
import { t, getLanguage } from './i18n.js';
import { formatTime } from './format.js';
import { ROUTES } from './router.js';

const LOOKS = {
  error: { icon: '❌', color: 'var(--crit)', word: ['overview.word_problem', 'Problem'] },
  warning: { icon: '⚠️', color: 'var(--warn)', word: ['overview.word_look', 'Needs a look'] },
  success: { icon: '✅', color: 'var(--ok2)', word: ['events.level.success', 'Done'] },
  info: { icon: 'ℹ️', color: 'var(--zn-text)', word: ['events.level.info', 'Information'] },
};

// the name of each place an entry can lead to: the words the sidebar already uses
const PLACE_NAMES = {
  ai: ['mgmt.sidebar_ai', 'AI'],
  alerts: ['events.place.alerts', 'Notifications'],
  apps: ['dock.containers', 'Apps'],
  backup: ['mgmt.sidebar_backup', 'Backup'],
  cards: ['mgmt.sidebar_copy', 'Card copies'],
  drives: ['dh.title', 'Drive Health'],
  events: ['mgmt.sidebar_events', 'Event Log'],
  files: ['mgmt.sidebar_files', 'Files'],
  hardware: ['mgmt.sidebar_hardware', 'Hardware'],
  network: ['mgmt.sidebar_network', 'Network'],
  power: ['mgmt.sidebar_ups', 'Power'],
  settings: ['mgmt.sidebar_system', 'Settings'],
  shares: ['mgmt.sidebar_shares', 'Shares'],
  storage: ['mgmt.sidebar_storage', 'Storage'],
  users: ['mgmt.sidebar_users', 'Users'],
  vms: ['mgmt.sidebar_vms', 'Virtual machines'],
};

/** When an entry was last reported: a repeat moves it up. */
export const eventWhen = (e) => (e && (e.last_ts || e.ts)) || 0;

/** Whether an entry asks for someone's attention: a problem, or something to look at. */
export const needsALook = (e) => ['error', 'warning'].includes(eventLook(e && e.level));

/** "3 times, the last at 14:02" for an entry that was reported again; '' otherwise. */
export function repeatedText(e) {
  const count = Number(e && e.count) || 1;
  if (count < 2) return '';
  return t('events.repeated', '{count, plural, one {# time} other {# times}}, the last at {time}', { count, time: formatTime(e.last_ts, undefined, '') });
}

/** One entry as every list draws it: the look of its level, its text in the reader's language. */
export function eventView(e) {
  const look = eventLook(e && e.level);
  const { icon, color, word } = LOOKS[look];
  const text = eventText(e);
  return { look, icon, color, word: t(word[0], word[1]), title: text.title, message: text.message, when: eventWhen(e), repeated: repeatedText(e) };
}

/** How long ago, in the person's language: "5 minutes ago". */
export function agoText(ts, now = Date.now() / 1000) {
  const diff = Math.max(0, Math.floor(now - ts));
  if (diff < 10) return t('time.just_now', 'Just now');
  const unit = diff < 60 ? 'second' : diff < 3600 ? 'minute' : diff < 86400 ? 'hour' : 'day';
  const n = Math.floor(diff / { second: 1, minute: 60, hour: 3600, day: 86400 }[unit]);
  try {
    return new Intl.RelativeTimeFormat(getLanguage(), { numeric: 'always' }).format(-n, unit);
  } catch {
    return `${n} ${unit}`;
  }
}

/** The page that deals with an entry: the link the server gave it, else the Event Log. */
export function eventPlace(e) {
  const route = e && e.link && ROUTES[e.link] && PLACE_NAMES[e.link] ? e.link : 'events';
  const [key, fallback] = PLACE_NAMES[route];
  const name = t(key, fallback);
  return { route, name, label: t('events.open_page', 'Open {page}', { page: name }), open: () => ROUTES[route]() };
}
