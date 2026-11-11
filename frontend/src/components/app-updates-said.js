/**
 * What the update check and "Update all" say (SET-14). "Check for updates" answered "All
 * containers are up to date!" without Docker, and also when a registry could not be reached;
 * "Update all" always said "All container updates dispatched.", whatever failed.
 */
import { t } from '../i18n.js';

const names = (list) => list.map((x) => (typeof x === 'string' ? x : x.name)).filter(Boolean).join(', ');

/** [text, kind] for the answer of POST /api/docker/updates/check. */
export function checkSaid(res) {
  const r = res || {};
  if (r.checked === false) return [t('appupd.not_checked', 'The update check could not run: Docker did not answer.'), 'error'];
  const count = r.updates_available_count || 0;
  if (count > 0) return [t('appupd.found', '{count, plural, one {# app has an update.} other {# apps have an update.}}', { count }), 'warn'];
  const unchecked = Array.isArray(r.unchecked) ? r.unchecked : [];
  if (unchecked.length) {
    return [
      t('appupd.partial', 'No update found. {count, plural, one {# app} other {# apps}} could not be checked, because the place its image comes from did not answer: {names}', { count: unchecked.length, names: names(unchecked) }),
      'warn',
    ];
  }
  return [t('appupd.none', 'Every app is up to date.'), 'success'];
}

/** [text, kind] for the answer of POST /api/docker/updates/apply-all. */
export function updateAllSaid(res) {
  const r = res || {};
  const updated = Array.isArray(r.updated) ? r.updated : [];
  const failed = Array.isArray(r.failed) ? r.failed : [];
  if (failed.length) {
    const why = failed.map((f) => `${f.name}: ${f.error || '?'}`).join('; ');
    return [t('appupd.some_failed', '{done} updated. Not updated: {why}', { done: updated.length, why }), 'error'];
  }
  if (!updated.length) return [t('appupd.nothing', 'Nothing was updated.'), 'info'];
  return [t('appupd.done', '{count, plural, one {# app was updated} other {# apps were updated}}: {names}', { count: updated.length, names: names(updated) }), 'success'];
}
