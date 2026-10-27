/**
 * Error codes in plain words (UX-14): every API error says what happened (the server's detail)
 * and what to do next, keyed by the error slug the server sends (backend/errors.py).
 */
import { t } from './i18n.js';

const NEXT_STEP = {
  forbidden: () => t('err.next_forbidden', 'Ask the owner of this server if you need access.'),
  not_found: () => t('err.next_not_found', 'Refresh the page: it may have been moved or deleted.'),
  conflict: () => t('err.next_conflict', 'Choose another name, or refresh to see the current state.'),
  payload_too_large: () => t('err.next_too_large', 'Try a smaller file, or upload from File Explorer, which sends large files in parts.'),
  rate_limited: () => t('err.next_rate_limited', 'Wait a minute, then try again.'),
  unavailable: () => t('err.next_unavailable', 'That part of the server is starting or stopped. Try again in a moment.'),
  timeout: () => t('err.next_timeout', 'The server may be busy. Try again; if it keeps happening, check that it is running.'),
};

/** The sentence to add after the server's message, or ''. */
export function nextStep(error, body = null) {
  if (error === 'internal_error') {
    const ref = body && body.reference ? String(body.reference) : '';
    return ref
      ? t('err.next_internal_ref', 'Try again. If it keeps happening, download a diagnostics bundle (Settings → About) and mention reference {ref}.', { ref })
      : t('err.next_internal', 'Try again. If it keeps happening, download a diagnostics bundle (Settings → About).');
  }
  const fn = NEXT_STEP[error];
  return fn ? fn() : '';
}

/** "What happened. What to do." */
export function explain(detail, error, body = null) {
  // whole messages the interface knows in every language
  if (error === 'ai_off_for_role') return t('err.ai_off_for_role', 'Zetty is turned off for your account. An administrator can turn it on in AI settings.');
  const what = String(detail || '').trim();
  const step = nextStep(error, body);
  if (!step || what.includes(step)) return what;
  return what ? `${what.replace(/[.!]?$/, '.')} ${step}` : step;
}
