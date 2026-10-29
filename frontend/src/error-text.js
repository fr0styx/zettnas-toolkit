/**
 * Error codes in plain words (UX-14): every API error says what happened (the server's detail)
 * and what to do next, keyed by the error slug the server sends (backend/errors.py).
 */
import { getLanguage, t } from './i18n.js';

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

// UX-22: what each error code means, in the person's language. The server's own sentence
// (English) goes under "Details". In English the server's sentence is shown as it is: it says
// more than the code does.
const MESSAGES = {
  bad_request: () => t('err.bad_request', "The server couldn't use that request."),
  invalid_request: () => t('err.bad_request', "The server couldn't use that request."),
  unauthorized: () => t('err.unauthorized', "You're signed out. Sign in again."),
  session_required: () => t('err.session_required', 'Please sign in first.'),
  forbidden: () => t('err.forbidden', "You don't have permission to do that."),
  not_found: () => t('err.not_found', "That wasn't found."),
  method_not_allowed: () => t('err.bad_request', "The server couldn't use that request."),
  conflict: () => t('err.conflict', 'That clashes with something that already exists.'),
  payload_too_large: () => t('err.payload_too_large', 'That is too large to send.'),
  unsupported_media_type: () => t('err.unsupported', "The server can't use that kind of file."),
  validation_error: () => t('err.validation_error', "Some of the values aren't valid."),
  rate_limited: () => t('err.rate_limited', 'Too many attempts.'),
  internal_error: () => t('err.internal_error', 'Something went wrong on the server.'),
  unavailable: () => t('err.unavailable', "That part of the server isn't available right now."),
  timeout: () => t('err.timeout', "The server didn't answer in time."),
  network: () => t('err.network', "The server couldn't be reached."),
  invalid_credentials: () => t('err.invalid_credentials', 'The name or password is wrong.'),
  weak_password: () => t('err.weak_password', 'That password is too weak.'),
  role_too_high: () => t('err.role_too_high', "You can't give someone more rights than you have."),
  invalid_mfa_code: () => t('err.invalid_mfa_code', 'That sign-in code is wrong or has expired.'),
  invalid_mfa_token: () => t('err.invalid_mfa_token', 'The sign-in step expired. Start again.'),
  csrf_blocked: () => t('err.csrf_blocked', 'The request was blocked for safety. Reload the page and try again.'),
  account_disabled: () => t('err.account_disabled', 'This account is turned off.'),
  vm_start_failed: () => t('err.vm_start_failed', "The virtual machine didn't start."),
  user_exists: () => t('err.user_exists', 'Someone with that name already exists.'),
  password_change_required: () => t('err.password_change_required', 'Change your password before you continue.'),
  idp_account: () => t('err.idp_account', 'This account signs in through your identity provider.'),
  disks_not_safe: () => t('err.disks_not_safe', "The disks aren't in a safe state for that."),
  confirmation_required: () => t('err.confirmation_required', 'Please confirm this first.'),
  bad_action: () => t('err.bad_action', "That action isn't available."),
  ai_search_off_for_role: () => t('err.ai_search_off_for_role', 'AI search is turned off for your account. An administrator can turn it on in AI settings.'),
};

// The server's own words for a message shown in another language, for the toast's "Details"
const DETAILS = new Map();

function rememberDetails(message, detail) {
  if (!detail || message.includes(detail)) return;
  if (DETAILS.size >= 50) DETAILS.delete(DETAILS.keys().next().value);
  DETAILS.set(message, detail);
}

/** The server's wording behind an error message, when the message is a translation. */
export function detailsFor(message) {
  return DETAILS.get(String(message || '')) || '';
}

function byStatus(body) {
  const code = Number(body && body.code) || 0;
  if (code >= 500) return MESSAGES.internal_error();
  if (code >= 400) return t('err.request_failed', "The request couldn't be completed.");
  return '';
}

/** "What happened. What to do." */
export function explain(detail, error, body = null) {
  // whole messages the interface knows in every language
  if (error === 'ai_off_for_role') return t('err.ai_off_for_role', 'Zetty is turned off for your account. An administrator can turn it on in AI settings.');
  const what = String(detail || '').trim();
  const step = nextStep(error, body);
  if (getLanguage() !== 'en') {
    const known = MESSAGES[error] ? MESSAGES[error]() : byStatus(body);
    if (known) {
      const message = step ? `${known.replace(/[.!]?$/, '.')} ${step}` : known;
      rememberDetails(message, what);
      return message;
    }
  }
  if (!step || what.includes(step)) return what;
  return what ? `${what.replace(/[.!]?$/, '.')} ${step}` : step;
}
