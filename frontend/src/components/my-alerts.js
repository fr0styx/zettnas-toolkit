/**
 * Each person's own alerts, and the daily summary setting (Batch 6).
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

const EVENT_NAMES = () => ({
  ups: t('alerts.ev_ups', 'Power cuts'),
  security: t('alerts.ev_security', 'Security'),
  backup: t('alerts.ev_backup', 'Backups'),
  smart: t('alerts.ev_smart', 'Disk health'),
  storage: t('alerts.ev_storage', 'Storage pools'),
  health: t('alerts.ev_health', 'Weekly health report'),
  temp: t('alerts.ev_temp', 'Temperatures'),
  fan: t('alerts.ev_fan', 'Fans'),
  copy: t('alerts.ev_copy', 'Copies and imports'),
  container: t('alerts.ev_container', 'Apps'),
  camera: t('alerts.ev_camera', 'Cameras'),
  general: t('alerts.ev_general', 'Everything else'),
});

export function myAlertsHtml(route, events) {
  const names = EVENT_NAMES();
  return `<form class="my-alerts" data-my-alerts>
    <label>${escapeHtml(t('alerts.ntfy', 'My ntfy topic'))}<input name="ntfy_topic" value="${escapeHtml(route.ntfy_topic || '')}" maxlength="64" placeholder="my-phone"></label>
    <label>${escapeHtml(t('alerts.email', 'My e-mail'))}<input name="email" type="email" value="${escapeHtml(route.email || '')}"></label>
    <label>${escapeHtml(t('alerts.min', 'From'))}<select name="min_level">${[
      ['info', t('alerts.lv_info', 'Everything')],
      ['warning', t('alerts.lv_warning', 'Warnings and up')],
      ['critical', t('alerts.lv_critical', 'Only critical')],
    ]
      .map(([v, n]) => `<option value="${v}"${route.min_level === v ? ' selected' : ''}>${escapeHtml(n)}</option>`)
      .join('')}</select></label>
    <fieldset><legend>${escapeHtml(t('alerts.kinds', 'About'))}</legend>${events
      .map(
        (e) => `<label class="my-alerts-check"><input type="checkbox" name="events" value="${escapeHtml(e)}"${(route.events || []).includes(e) ? ' checked' : ''}> ${escapeHtml(names[e] || e)}</label>`,
      )
      .join('')}</fieldset>
    <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('alerts.save', 'Save my alerts'))}</button>
  </form>`;
}

export async function renderMyAlerts(mount) {
  if (!mount) return;
  try {
    const { route, events } = await api.get('/api/notifications/me');
    mount.innerHTML = myAlertsHtml(route, events);
  } catch (e) {
    mount.hidden = true;
    return;
  }
  mount.querySelector('[data-my-alerts]').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api.put('/api/notifications/me', {
        ntfy_topic: f.get('ntfy_topic'),
        email: f.get('email'),
        min_level: f.get('min_level'),
        events: f.getAll('events'),
      });
      showToast(t('alerts.saved', 'Your alerts are saved.'), 'success');
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
}
