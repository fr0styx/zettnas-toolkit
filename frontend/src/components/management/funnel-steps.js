/**
 * What Tailscale Funnel needs that only the tailnet's owner can switch on (HTTPS certificates, Funnel
 * for this device), as a checklist that ticks itself: both Funnel cards (share links, apps) show it
 * until Tailscale reports both done, and look again every few seconds meanwhile.
 */
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';

export const RECHECK_MS = 5000;
export const RECHECK_FOR_MS = 15 * 60 * 1000;

function step(done, text, url, help) {
  const mark = done ? '✓' : '○';
  const link = !done && url
    ? ` <a class="btn-pill-toggle is-small" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t('funnel.open', 'Open'))}</a>`
    : '';
  return `<li class="funnel-step${done ? ' is-done' : ''}"><span class="funnel-mark" aria-hidden="true">${mark}</span>
    <span><strong>${escapeHtml(text)}</strong>${help ? ` <span class="nsv-xs-muted">${escapeHtml(help)}</span>` : ''}</span>${link}</li>`;
}

/** The steps still to do (nothing once Funnel can be used), and what waits for them. */
export function funnelStepsHtml(f, waiting = '') {
  if (!f || f.ready || !f.connected) return '';
  if (f.headscale) {
    return `<div class="funnel-steps nsv-xs-muted">${escapeHtml(t('funnel.headscale', 'Funnel is a Tailscale service: with your own Headscale server, nothing can be put on the internet this way.'))}</div>`;
  }
  return `<div class="funnel-steps" role="group" aria-label="${escapeHtml(t('funnel.title', 'Before Funnel works'))}">
    <div class="nsv-xs-muted">${escapeHtml(t('funnel.owner', 'Two switches in Tailscale that only the tailnet\'s owner can turn on, one click each. This list ticks itself.'))}</div>
    <ol class="funnel-list">
      ${step(f.https, t('funnel.step_https', 'Turn on HTTPS certificates'), f.dns_url, t('funnel.step_https_help', 'Tailscale admin → DNS → Enable HTTPS'))}
      ${step(f.funnel, t('funnel.step_allow', 'Allow Funnel for this device'), f.approve_url, '')}
    </ol>
    ${waiting ? `<div class="nsv-xs-muted funnel-waiting">${escapeHtml(waiting)}</div>` : ''}
  </div>`;
}

/** Looks again every few seconds while steps are open (for a while), then stops by itself. */
export function recheckWhileOpen(f, reload, timers = { setTimeout, clearTimeout }, started = Date.now()) {
  if (!f || f.ready || !f.connected || f.headscale) return null;
  if (Date.now() - started > RECHECK_FOR_MS) return null;
  return timers.setTimeout(() => reload(started), RECHECK_MS);
}
