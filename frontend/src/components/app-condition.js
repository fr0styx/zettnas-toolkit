/**
 * How the state of an app, and of the list of apps, is said (SET-14).
 * The list had two looks: green for "running", grey for everything else. "Up 2 days (unhealthy)"
 * was green; a crashed app and one caught in a restart loop were the same quiet grey as an app
 * somebody had stopped. A chip above the list read "Docker Socket Active • Live Sync", as fixed
 * text. The server now says what state each app is in (backend/hardware/docker_condition.py)
 * and whether the list can be trusted; this module turns both into words.
 */
import { t } from '../i18n.js';
import { formatTime } from '../format.js';

// condition -> [look, icon, key, English]
const VIEWS = {
  running: ['ok', '✓', 'appst.running', 'Running'],
  starting: ['info', '…', 'appst.starting', 'Starting'],
  unhealthy: ['warn', '⚠', 'overview.word_look', 'Needs a look'],
  restarting: ['warn', '⚠', 'appst.restarting', 'Keeps restarting'],
  crashed: ['crit', '✕', 'appst.crashed', 'Stopped unexpectedly'],
  dead: ['crit', '✕', 'appst.crashed', 'Stopped unexpectedly'],
  stopped: ['muted', '■', 'appst.stopped', 'Stopped'],
  paused: ['muted', '⏸', 'appst.paused', 'Paused'],
  created: ['muted', '○', 'appst.created', 'Not started yet'],
  removing: ['muted', '…', 'appst.removing', 'Being removed'],
  unknown: ['muted', '?', 'appst.unknown', 'Unknown'],
};
const NEEDS_LOOK = ['unhealthy', 'restarting', 'crashed', 'dead'];
const UP = ['running', 'starting', 'unhealthy'];

/** The app's condition: the server's word, or for a server from before, what its state allows. */
export function conditionOf(c) {
  if (c && VIEWS[c.condition]) return c.condition;
  const state = c && c.state;
  if (state === 'running') return 'running';
  if (state === 'exited') return 'stopped'; // why it ended is not known: no alarm from a guess
  return VIEWS[state] ? state : 'unknown';
}

export const needsLook = (c) => NEEDS_LOOK.includes(conditionOf(c));
/** What a row offers: Stop for everything that runs or tries to, Resume for a paused app, else Start. */
export const canStop = (c) => [...UP, 'restarting', 'paused'].includes(conditionOf(c));
export const canRestart = (c) => UP.includes(conditionOf(c));
export const canResume = (c) => conditionOf(c) === 'paused';
export const canStart = (c) => !canStop(c) && conditionOf(c) !== 'removing';

/** Why, in a sentence, where the server knows: under the word, and read out with it. */
function reasonOf(c, condition) {
  if (condition === 'unhealthy') return t('appst.why_unhealthy', 'It runs, but its own health check fails.');
  if (condition === 'restarting') {
    return t('appst.why_restarting', 'It stops and is started again, {count, plural, one {# time} other {# times}} so far.', { count: c.restart_count || 1 });
  }
  if (condition === 'crashed' || condition === 'dead') {
    if (c.reason === 'out_of_memory') return t('appst.why_memory', 'It was ended for using more memory than it may.');
    if (c.exit_code != null) return t('appst.why_exit', 'It ended by itself with error {code}.', { code: c.exit_code });
    return t('appst.why_ended', 'It ended without anyone stopping it.');
  }
  if (condition === 'stopped' && c.reason === 'stopped_outside') return t('appst.why_outside', 'It was stopped outside Kiboto.');
  return '';
}

/** One app as the list draws it: {condition, look, icon, word, why}. */
export function conditionView(c) {
  const condition = conditionOf(c);
  const [look, icon, key, english] = VIEWS[condition];
  return { condition, look, icon, word: t(key, english), why: reasonOf(c || {}, condition) };
}

/** The sentence above the list, from what is true: {look, text}. `docker` is the server's
 *  docker_state; `failed` says that the list itself could not be read. */
export function appsSummary(list, docker = null, failed = '') {
  const apps = Array.isArray(list) ? list : [];
  if (failed) return { look: 'crit', text: t('appst.sum_failed', 'The list of apps could not be read: {error}', { error: failed }) };
  if (docker && docker.available === false) {
    return { look: 'muted', text: t('appst.sum_no_docker', 'Apps cannot run on this server: Docker was not found.') };
  }
  if (docker && docker.answering === false) {
    const time = docker.as_of ? formatTime(docker.as_of, undefined, '') : '';
    return {
      look: 'crit',
      text: docker.stale && time
        ? t('appst.sum_stale', 'Docker is not answering. This list is from {time} and may be out of date.', { time })
        : t('appst.sum_silent', 'Docker is not answering, so the apps cannot be listed right now.'),
    };
  }
  if (!apps.length) return { look: 'muted', text: t('appst.sum_none', 'No apps yet.') };
  const ended = apps.filter((c) => ['crashed', 'dead'].includes(conditionOf(c))).length;
  if (ended) return { look: 'crit', text: t('appst.sum_ended', '{count, plural, one {# app stopped unexpectedly.} other {# apps stopped unexpectedly.}}', { count: ended }) };
  const look = apps.filter(needsLook).length;
  if (look) return { look: 'warn', text: t('appst.sum_look', '{count, plural, one {# app needs a look.} other {# apps need a look.}}', { count: look }) };
  const running = apps.filter((c) => UP.includes(conditionOf(c))).length;
  if (running === apps.length) return { look: 'ok', text: t('appst.sum_all', '{count, plural, one {The app is running.} other {All # apps are running.}}', { count: running }) };
  return { look: 'ok', text: t('appst.sum_some', '{running} of {total, plural, one {# app} other {# apps}} are running; the others are stopped.', { running, total: apps.length }) };
}

// what an action on one app says: [while it runs, when it worked, when it failed]
const SAID = {
  start: [['appact.start_doing', 'Starting {name}…'], ['appact.start_done', '{name} is running.'], ['appact.start_failed', '{name} could not be started: {error}']],
  stop: [['appact.stop_doing', 'Stopping {name}…'], ['appact.stop_done', '{name} is stopped.'], ['appact.stop_failed', '{name} could not be stopped: {error}']],
  restart: [['appact.restart_doing', 'Restarting {name}…'], ['appact.restart_done', '{name} was restarted.'], ['appact.restart_failed', '{name} could not be restarted: {error}']],
  pause: [['appact.pause_doing', 'Pausing {name}…'], ['appact.pause_done', '{name} is paused.'], ['appact.pause_failed', '{name} could not be paused: {error}']],
  unpause: [['appact.resume_doing', 'Resuming {name}…'], ['appact.resume_done', '{name} runs again.'], ['appact.resume_failed', '{name} could not be resumed: {error}']],
};

/** The message for an action on an app. The raw action word was pasted into every language:
 *  'Container "jellyfin" successfully stoped.', "jellyfin: stop erledigt". */
export function actionSaid(action, phase, name, error = '') {
  const texts = SAID[action] || SAID.restart;
  const [key, english] = texts[{ doing: 0, done: 1, failed: 2 }[phase] ?? 0];
  return t(key, english, { name, error });
}

// the same for a selection of apps
const BULK = {
  start: [['appbulk.start_doing', 'Starting {count, plural, one {# app} other {# apps}}…'], ['appbulk.start_done', '{successful} of {total} started.']],
  stop: [['appbulk.stop_doing', 'Stopping {count, plural, one {# app} other {# apps}}…'], ['appbulk.stop_done', '{successful} of {total} stopped.']],
  restart: [['appbulk.restart_doing', 'Restarting {count, plural, one {# app} other {# apps}}…'], ['appbulk.restart_done', '{successful} of {total} restarted.']],
  pause: [['appbulk.pause_doing', 'Pausing {count, plural, one {# app} other {# apps}}…'], ['appbulk.pause_done', '{successful} of {total} paused.']],
  unpause: [['appbulk.resume_doing', 'Resuming {count, plural, one {# app} other {# apps}}…'], ['appbulk.resume_done', '{successful} of {total} resumed.']],
};

/** The message for an action on several apps: 'Executing bulk stop on 3 containers...' pasted the
 *  action word into every language. */
export function bulkSaid(action, phase, values = {}) {
  if (phase === 'failed') return t('appbulk.failed', 'That did not work: {error}', values);
  const [key, english] = (BULK[action] || BULK.restart)[phase === 'done' ? 1 : 0];
  return t(key, english, values);
}
