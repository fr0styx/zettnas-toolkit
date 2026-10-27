/**
 * Mission Control's Overview leads with what needs attention (UX-1), and an Advanced switch
 * keeps virtual machines, network, hardware, power and activity out of the everyday list (UX-2).
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { ROUTES } from '../../router.js';
import { ADVANCED_SECTIONS, advancedOn, saveAdvanced } from '../../advanced.js';
import { ZettEventBus } from '../../event-bus.js';

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
};

export function statusHtml(summary) {
  if (!summary || summary.ok || !(summary.items || []).length) {
    return `<div class="ov-status ov-ok"><strong>✓ ${escapeHtml(t('overview.all_good', 'Everything is fine'))}</strong>
      <span>${escapeHtml(t('overview.all_good_desc', 'Nothing needs your attention.'))}</span></div>`;
  }
  const rows = summary.items
    .map((i) => {
      const text = (MESSAGES[i.kind] || (() => i.kind))().replace('{subject}', i.subject || '').replace('{detail}', i.detail_key ? t(i.detail_key, i.detail || '', i.detail_params || {}) : i.detail || '');
      const open = ROUTES[i.open] ? `<button type="button" class="btn-pill-toggle" data-ov-open="${escapeHtml(i.open)}">${escapeHtml(t('overview.open', 'Open'))}</button>` : '';
      return `<li class="ov-item ov-${i.level === 'critical' ? 'crit' : 'warn'}"><span>${escapeHtml(text)}</span>${open}</li>`;
    })
    .join('');
  return `<div class="ov-status ov-attention"><strong>${escapeHtml(t('overview.attention', '{n, plural, one {# thing needs your attention} other {# things need your attention}}', { n: summary.items.length }))}</strong><ul>${rows}</ul></div>`;
}

export async function renderStatusSummary(root = document) {
  const hub = root.getElementById('management-hub-view');
  if (!hub) return null;
  let box = root.getElementById('mgmt-status-summary');
  if (!box) {
    box = document.createElement('section');
    box.id = 'mgmt-status-summary';
    box.className = 'mgmt-status-summary';
    box.setAttribute('aria-live', 'polite');
    box.setAttribute('aria-label', t('overview.status_label', 'Status'));
    hub.insertBefore(box, hub.firstChild);
    box.addEventListener('click', (e) => {
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
  box.hidden = false;
  box.innerHTML = statusHtml(summary);
  return summary;
}
