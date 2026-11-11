/**
 * Mission Control's Overview leads with what needs attention (UX-1), and an Advanced switch
 * keeps virtual machines, network, hardware, power and activity out of the everyday list (UX-2).
 */
import { api } from '../../api.js';
import { html } from '../../html.js';
import { formatBytes } from '../../format.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { ROUTES } from '../../router.js';
import { ADVANCED_SECTIONS, advancedOn, saveAdvanced } from '../../advanced.js';
import { ZettEventBus } from '../../event-bus.js';
import { announceChange } from '../../a11y.js';
import { currentUser } from '../../route-access.js';
import { ADVANCED_OFF, leavePage, mark, tidyHeadings } from '../../hide-marks.js';
import { showToast } from '../../toast.js';
import { statusBoxHtml, statusSaid, statusState } from './status-box.js';

export { ADVANCED_SECTIONS, advancedOn };

/** The switch in Mission Control: saved to the person's account (UX-23). */
export async function setAdvanced(on) {
  applyAdvanced(on);
  if (!on) leaveAdvancedPage();
  const saved = await saveAdvanced(on, api);
  // a failed save was silent, so the choice came back at the next sign-in
  if (saved === false) showToast(t('mgmt.advanced_not_saved', 'That choice could not be saved to your account. It holds in this browser for now.'), 'error');
  return saved;
}

/** Switching Advanced off while on one of its pages goes back to the Overview: the page stayed
 *  open with nothing highlighted in the sidebar. */
export function leaveAdvancedPage(root = document) {
  return leavePage(ADVANCED_OFF, root);
}

ZettEventBus.on?.('advanced:changed', ({ on } = {}) => applyAdvanced(on));

/** Shows or hides the advanced places in the sidebar and on the Overview. */
export function applyAdvanced(on = advancedOn(), root = document) {
  root.querySelectorAll('.mgmt-sidebar-item, .mgmt-app-card').forEach((el) => {
    // one reason among others: it wrote `hidden` itself and so showed what the person's rights hide
    if (ADVANCED_SECTIONS.includes(el.dataset.mgmtTarget)) mark(el, ADVANCED_OFF, !on);
  });
  tidyHeadings(root);
  const sw = root.getElementById ? root.getElementById('mgmt-advanced-switch') : null;
  if (sw) sw.checked = on;
}

export function installAdvancedSwitch(root = document) {
  const nav = root.querySelector('.mgmt-sidebar-nav');
  if (!nav || root.getElementById('mgmt-advanced-switch')) return applyAdvanced();
  const row = document.createElement('label');
  row.className = 'mgmt-advanced-row';
  // the texts carry their keys, so a change of language reaches them; the icon is what a narrow
  // sidebar shows, where the switch was a bare checkbox with no name (SET-12)
  row.title = t('mgmt.advanced', 'Advanced');
  row.setAttribute('data-i18n-title', 'mgmt.advanced');
  row.innerHTML = `<input type="checkbox" id="mgmt-advanced-switch" role="switch">
    <svg class="mgmt-sidebar-svg mgmt-advanced-icon" aria-hidden="true"><use href="#i-sliders"/></svg>
    <span><strong data-i18n="mgmt.advanced">${escapeHtml(t('mgmt.advanced', 'Advanced'))}</strong>
    <small data-i18n="mgmt.advanced_desc">${escapeHtml(t('mgmt.advanced_desc', 'Virtual machines, network, hardware, power, activity'))}</small></span>`;
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
  service_stalled: () => t('overview.service_stalled', 'The {subject} service has stopped responding. Restart Kiboto if it does not recover.'),
  kit_not_saved: () => t('overview.kit_not_saved', 'Recovery kit not saved for "{subject}": without it the backup cannot be read.'),
  writes_frozen: () => t('overview.writes_frozen', 'Changes to files are paused: something looked like ransomware.'),
  on_battery: () => t('overview.on_battery', 'The server is running on battery power.'),
  too_hot: () => t('overview.too_hot', 'The server is too hot.'),
  default_password: () => t('overview.default_password', 'The first-time password is still in use.'),
  timezone_unset: () => t('overview.timezone_unset_clock', "The server's time zone isn't set, so nightly work (backups, checks, AI indexing) runs at night by London winter time (UTC), which may be daytime where you are."),
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
  const text = msg.replace('{subject}', subject || i.kind || '').replace('{detail}', detail);
  // someone who can't fix it is told who can (NUX-5)
  return i.tell_admin ? `${text} ${t('overview.tell_admin', 'Tell the person who manages Kiboto.')}` : text;
}

/** The status box as markup: one box for the alerts and the copy outside the NAS (status-box.js). */
export function statusHtml(summary, protection = null, user = currentUser()) {
  return statusBoxHtml(statusState({ summary, protection, user, rowText: itemText, canOpen: (place) => Boolean(ROUTES[place]) }));
}

/** REL-15: what the Recycle Bins hold, from the index (no disk is read). The copies outside the
 *  NAS are part of the status box now: they were a second box that could contradict the first. */
export function protectionHtml(p) {
  if (!p || !p.recycle_bytes) return '';
  return html`<p class="offsite-meta">${t('protect.recycle', 'The Recycle Bins hold {size}; each item goes after 30 days.', { size: formatBytes(p.recycle_bytes) })}</p>`;
}

/** The status in one sentence, for screen readers (UX-28). */
export function statusSentence(summary, protection = null, user = currentUser()) {
  return statusSaid(statusState({ summary, protection, user, rowText: itemText }));
}

const STATUS_EVERY_MS = 60000;
let _statusTimer = null;

/** The box is read again once a minute while the Overview is on screen (it was read once per visit). */
function keepStatusCurrent(root) {
  if (_statusTimer || typeof setInterval !== 'function') return;
  _statusTimer = setInterval(() => {
    const hub = root.getElementById('management-hub-view');
    if (hub && hub.offsetParent !== null && !document.hidden) renderStatusSummary(root);
  }, STATUS_EVERY_MS);
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
      if (/** @type {Element} */ (e.target).closest('[data-ov-retry]')) {
        renderStatusSummary(root);
        return;
      }
      const btn = e.target.closest('[data-ov-open]');
      if (btn && ROUTES[btn.dataset.ovOpen]) ROUTES[btn.dataset.ovOpen]();
    });
  }
  // "checking" stands where the answer will: the page no longer jumps when it arrives
  if (!box.dataset.read) box.innerHTML = statusBoxHtml(statusState({}));
  box.hidden = false;
  keepStatusCurrent(root);
  let summary;
  try {
    summary = await api.get('/api/system/status-summary');
  } catch (err) {
    // no box read as "nothing wrong": it now says that the status is not known, and why
    const state = statusState({ error: err });
    box.innerHTML = statusBoxHtml(state);
    delete box.dataset.read;
    announceChange('status-summary', statusSaid(state));
    return null;
  }
  let protection = null;
  try {
    protection = await api.get('/api/system/protection');
  } catch {
    // not allowed or not reachable: the status alone still shows
  }
  box.dataset.read = '1';
  box.innerHTML = statusHtml(summary, protection) + protectionHtml(protection);
  announceChange('status-summary', statusSentence(summary, protection)); // UX-28: only when it changes
  return summary;
}
