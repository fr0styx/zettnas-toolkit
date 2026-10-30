/**
 * An activity-log entry in the reader's language (NUX-3). The server keeps its English text for
 * the log file and, for entries that have one, the message keys and values it was made from
 * (details.title_key, msg_key, params). A value may itself be a reference to translate
 * ({key, default, params}: a drive's label inside "Drive sdb: Replace soon").
 */
import { t } from './i18n.js';

function resolve(params) {
  const out = {};
  for (const [k, v] of Object.entries(params || {})) {
    out[k] = v && typeof v === 'object' && 'key' in v ? t(v.key, v.default || '', resolve(v.params)) : v;
  }
  return out;
}

/** {title, message} of an event, translated when it says how. */
export function eventText(e) {
  const d = (e && e.details) || {};
  if (!d.title_key && !d.msg_key) return { title: (e && e.title) || '', message: (e && e.message) || '' };
  const p = resolve(d.params);
  return {
    title: d.title_key ? t(d.title_key, e.title || '', p) : e.title || '',
    message: d.msg_key ? t(d.msg_key, e.message || '', p) : e.message || '',
  };
}
