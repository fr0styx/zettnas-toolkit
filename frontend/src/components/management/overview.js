/**
 * Mission Control's Overview leads with what needs attention (UX-1), and an Advanced switch
 * keeps virtual machines, network, hardware, power and activity out of the everyday list (UX-2).
 */
import { api } from '../../api.js';
import { html } from '../../html.js';
import { formatBytes, formatDateTime } from '../../format.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { ROUTES } from '../../router.js';
import { ADVANCED_SECTIONS, advancedOn, saveAdvanced } from '../../advanced.js';
import { ZettEventBus } from '../../event-bus.js';
import { announceChange } from '../../a11y.js';

export { ADVANCED_SECTIONS, advancedOn };

/** The switch in Mission Control: saved to the person's account (UX-23). */
export function setAdvanced(on) {
  applyAdvanced(on);
  return saveAdvanced(on, api);
}

ZettEventBus.on?.('advanced:changed', ({ on } = {}) => applyAdvanced(on));

/** Shows or hides the advanced places in the sidebar and on the Overview. */
export function applyAdvanced(on = advancedOn(), root = document) {
  root.querySelectorAll('.mgmt-sidebar-item, .mgmt-app-card').forEach((el) => {
    if (ADVANCED_SECTIONS.includes(el.dataset.mgmtTarget)) el.hidden = !on;
  });
  const sw = root.getElementById ? root.getElementById('mgmt-advanced-switch') : null;
  if (sw) sw.checked = on;
}

export function installAdvancedSwitch(root = document) {
  const nav = root.querySelector('.mgmt-sidebar-nav');
  if (!nav || root.getElementById('mgmt-advanced-switch')) return applyAdvanced();
  const row = document.createElement('label');
  row.className = 'mgmt-advanced-row';
  row.innerHTML = `<input type="checkbox" id="mgmt-advanced-switch" role="switch">
    <span><strong>${escapeHtml(t('mgmt.advanced', 'Advanced'))}</strong>
    <small>${escapeHtml(t('mgmt.advanced_desc', 'Virtual machines, network, hardware, power, activity'))}</small></span>`;
  nav.appendChild(row);
  row.querySelector('input').addEventListener('change', (e) => setAdvanced(e.target.checked));
  applyAdvanced();
}

const MESSAGES = {
  drive_failing: () => t('overview.drive_failing', 'Drive {subject} is failing. Copy what is on it elsewhere and replace it.'),
  drive_warning: () => t('overview.drive_warning', 'Drive {subject} shows early warning signs.'),
  drive_attention: () => t('overview.drive_attention', 'Drive {subject} needs attention: {detail}.'),
  storage_full: () => t('overview.storage_full', 'Storage is {subject} full.'),
  pool_degraded: () => t('overview.pool_degraded', 'Storage pool {subject} is degraded: your data has less protection.'),
  disk_disabled: () => t('overview.disk_disabled', 'Disk {subject} is out of the pool. Replace or reconnect it.'),
  disk_errors: () => t('overview.disk_errors', 'Disk {subject} reports read or write errors.'),
  pool_full: () => t('overview.pool_full', 'Storage pool {subject} is {detail} full.'),
  scrub_errors: () => t('overview.scrub_errors', 'The last check of {subject} found errors in the data.'),
  backup_overdue: () => t('overview.backup_overdue', 'Backup "{subject}" has not finished lately.'),
  snapshot_overdue: () => t('overview.snapshot_overdue', 'Snapshots of {subject} have not been taken lately.'),
  scrub_overdue: () => t('overview.scrub_overdue', '{subject} has not been checked for errors lately.'),
  service_stalled: () => t('overview.service_stalled', 'The {subject} service has stopped responding. Restart ZettNAS if it does not recover.'),
  kit_not_saved: () => t('overview.kit_not_saved', 'Recovery kit not saved for "{subject}": without it the backup cannot be read.'),
  writes_frozen: () => t('overview.writes_frozen', 'Changes to files are paused: something looked like ransomware.'),
  on_battery: () => t('overview.on_battery', 'The server is running on battery power.'),
  too_hot: () => t('overview.too_hot', 'The server is too hot.'),
  default_password: () => t('overview.default_password', 'The first-time password is still in use.'),
  timezone_unset: () => t('overview.timezone_unset', "The server's time zone isn't set, so nightly work (backups, checks, AI indexing) runs at night in UTC."),
};

// The background services by what they do (NUX-19); an unknown one keeps its name
const SERVICES = {
  BackupScheduler: () => t('overview.svc_backup_scheduler', 'backup schedule'),
  BackupWatch: () => t('overview.svc_backup_watch', 'backup check'),
  ButtonListener: () => t('overview.svc_buttons', 'front-panel buttons'),
  DataGuard: () => t('overview.svc_data_guard', 'settings check'),
  DockerProxy: () => t('overview.svc_docker_proxy', 'app connection'),
  FanWatchdog: () => t('overview.svc_fans', 'fan control'),
  LcdRenderer: () => t('overview.svc_lcd', 'front display'),
  PhotoVectors: () => t('overview.svc_photo_vectors', 'photo search'),
  RansomwareGuard: () => t('overview.svc_ransomware', 'ransomware guard'),
  SmartPoller: () => t('overview.svc_smart', 'drive health check'),
  StatsCollector: () => t('overview.svc_stats', 'system statistics'),
  TaskScheduler: () => t('overview.svc_tasks', 'task scheduler'),
  VisionCaptioner: () => t('overview.svc_vision', 'photo descriptions'),
};

export function itemText(i) {
  const subject = i.kind === 'service_stalled' && SERVICES[i.subject] ? SERVICES[i.subject]() : i.subject || '';
  const msg = MESSAGES[i.kind] ? MESSAGES[i.kind]() : t('overview.unknown_item', 'Something needs attention: {subject}.');
  const detail = i.detail_key ? t(i.detail_key, i.detail || '', i.detail_params || {}) : i.detail || '';
  return msg.replace('{subject}', subject || i.kind || '').replace('{detail}', detail);
}

export function statusHtml(summary) {
  if (!summary || summary.ok || !(summary.items || []).length) {
    return `<div class="ov-status ov-ok"><strong>✓ ${escapeHtml(t('overview.all_good', 'Everything is fine'))}</strong>
      <span>${escapeHtml(t('overview.all_good_desc', 'Nothing needs your attention.'))}</span></div>`;
  }
  const rows = summary.items
    .map((i) => {
      const text = itemText(i);
      const open = ROUTES[i.open] ? `<button type="button" class="btn-pill-toggle" data-ov-open="${escapeHtml(i.open)}" aria-label="${escapeHtml(t('overview.open_for', 'Open: {what}', { what: text }))}">${escapeHtml(t('overview.open', 'Open'))}</button>` : '';
      return `<li class="ov-item ov-${i.level === 'critical' ? 'crit' : 'warn'}"><span>${escapeHtml(text)}</span>${open}</li>`;
    })
    .join('');
  return `<div class="ov-status ov-attention"><strong>${escapeHtml(t('overview.attention', '{n, plural, one {# thing needs your attention} other {# things need your attention}}', { n: summary.items.length }))}</strong><ul>${rows}</ul></div>`;
}

/** FEAT-01: the copies outside this NAS, and a way to make one when there is none lately. */
export function protectionHtml(p) {
  if (!p || !p.level) return '';
  return html`${protectionTile(p)}${recycleLine(p)}`;
}

/** REL-15: what the Recycle Bins hold, from the index (no disk is read). */
function recycleLine(p) {
  if (!p.recycle_bytes) return '';
  return html`<p class="offsite-meta">${t('protect.recycle', 'The Recycle Bins hold {size}; each item goes after 30 days.', { size: formatBytes(p.recycle_bytes) })}</p>`;
}

function protectionTile(p) {
  const when = p.last_good ? formatDateTime(p.last_good * 1000) : '';
  if (p.level === 'good') {
    return html`<div class="ov-status ov-ok"><strong>🛡 ${t('protect.good', '{n, plural, one {# current copy} other {# current copies}} outside this NAS', { n: p.copies })}</strong>
      <span>${t('protect.newest', 'The newest is from {when}.', { when })}</span></div>`;
  }
  const text = p.level === 'none' ? t('protect.none', 'No copy of your files outside this NAS yet.') : t('protect.stale', 'Your newest copy outside this NAS is from {when}.', { when: when || '?' });
  return html`<div class="ov-status ov-attention"><strong>${text}</strong>
    <button type="button" class="btn-pill-toggle" data-ov-protect>${t('protect.title', 'Protect this NAS')}</button></div>`;
}

/** The status in one sentence, for screen readers (UX-28). */
export function statusSentence(summary) {
  const n = ((summary && summary.items) || []).length;
  return n
    ? t('a11y.status_items', '{n, plural, one {# thing needs attention} other {# things need attention}}', { n })
    : t('a11y.status_ok', 'All is well.');
}

export async function renderStatusSummary(root = document) {
  const hub = root.getElementById('management-hub-view');
  if (!hub) return null;
  let box = root.getElementById('mgmt-status-summary');
  if (!box) {
    box = document.createElement('section');
    box.id = 'mgmt-status-summary';
    box.className = 'mgmt-status-summary';
    box.setAttribute('aria-label', t('overview.status_label', 'Status'));
    hub.insertBefore(box, hub.firstChild);
    box.addEventListener('click', (e) => {
      if (e.target.closest('[data-ov-protect]')) {
        import('../protect-nas.js').then((m) => m.openProtectGuide()).catch(() => {});
        return;
      }
      const btn = e.target.closest('[data-ov-open]');
      if (btn && ROUTES[btn.dataset.ovOpen]) ROUTES[btn.dataset.ovOpen]();
    });
  }
  let summary;
  try {
    summary = await api.get('/api/system/status-summary');
  } catch {
    box.hidden = true; // not allowed or not reachable: the Overview still works
    return null;
  }
  let protection = null;
  try {
    protection = await api.get('/api/system/protection');
  } catch {
    // not allowed or not reachable: the status alone still shows
  }
  box.hidden = false;
  box.innerHTML = statusHtml(summary) + protectionHtml(protection);
  announceChange('status-summary', statusSentence(summary)); // UX-28: only when it changes
  return summary;
}
