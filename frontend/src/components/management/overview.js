/**
 * Mission Control's Overview leads with what needs attention (UX-1), and an Advanced switch
 * keeps virtual machines, network, hardware, power and activity out of the everyday list (UX-2).
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { ROUTES } from '../../router.js';

export const ADVANCED_SECTIONS = ['mgmt-sec-vms', 'mgmt-sec-network', 'mgmt-sec-hardware', 'mgmt-sec-ups', 'mgmt-sec-activity'];
const PREF = 'zettnas_advanced';

export function advancedOn() {
  try {
    return localStorage.getItem(PREF) !== '0'; // on unless chosen off: nobody loses a page they use
  } catch {
    return true;
  }
}

export function setAdvanced(on) {
  try {
    localStorage.setItem(PREF, on ? '1' : '0');
  } catch {
    /* private window: the choice lasts until reload */
  }
  applyAdvanced(on);
}

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
  storage_full: () => t('overview.storage_full', 'Storage is {subject} full.'),
  backup_overdue: () => t('overview.backup_overdue', 'Backup "{subject}" has not finished lately.'),
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
      const text = (MESSAGES[i.kind] || (() => i.kind))().replace('{subject}', i.subject || '');
      const open = ROUTES[i.open] ? `<button type="button" class="btn-pill-toggle" data-ov-open="${escapeHtml(i.open)}">${escapeHtml(t('overview.open', 'Open'))}</button>` : '';
      return `<li class="ov-item ov-${i.level === 'critical' ? 'crit' : 'warn'}"><span>${escapeHtml(text)}</span>${open}</li>`;
    })
    .join('');
  return `<div class="ov-status ov-attention"><strong>${escapeHtml(t('overview.attention', '{n} thing(s) need your attention', { n: summary.items.length }))}</strong><ul>${rows}</ul></div>`;
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
