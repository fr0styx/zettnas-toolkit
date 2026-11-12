/**
 * The Overview after its status box (SET-20, Overview 5): three tiles, Storage, Apps and Backup,
 * each with one line read from what the page already has (the live readings and the copies
 * answer, so no drive wakes), then Getting started for whoever sets the NAS up. The ten cards of
 * links it replaces were 1,329 px tall for one link each (overview report B4, B7, B8).
 */
import { api } from '../../api.js';
import { ZettEventBus } from '../../event-bus.js';
import { formatDateTime } from '../../format.js';
import { t } from '../../i18n.js';
import { state } from '../../state.js';

const HEALTHY = new Set(['', 'ok', 'passed', 'healthy', 'good', 'standby']);
const STOPPED = new Set(['exited', 'dead']);

let _driveIssues = null; // drives the status box warns about (its Drive Health verdicts); null until it answered

/** Drives the status answer names (failing, warning or needing attention). */
export function driveIssues(summary) {
  if (!summary || !Array.isArray(summary.items)) return null;
  return summary.items.filter((i) => String(i.kind || '').startsWith('drive_')).length;
}

/** "1.2 TB of 4 TB used · 3 drives, all healthy", or what needs a look. Health is claimed only
 *  once the status box has answered, so the tile never says "healthy" beside a warning row. */
export function storageLine(stats, issues = _driveIssues) {
  const used = stats?.storage?.used ? t('ov.tile_used', '{used} of {total} used', { used: stats.storage.used, total: stats.storage.total }) : '';
  const disks = Array.isArray(stats?.disks) ? stats.disks : [];
  const bad = Math.max(issues || 0, disks.filter((d) => !HEALTHY.has(String(d.health || '').toLowerCase())).length);
  let health = '';
  if (bad) health = t('ov.tile_drives_bad', '{count, plural, one {# drive needs a look} other {# drives need a look}}', { count: bad });
  else if (disks.length && issues === 0) health = t('ov.tile_drives_ok', '{count, plural, one {# drive, healthy} other {# drives, all healthy}}', { count: disks.length });
  else if (disks.length) health = t('ov.tile_drives', '{count, plural, one {# drive} other {# drives}}', { count: disks.length });
  return [used, health].filter(Boolean).join(' · ');
}

/** "5 apps, 4 running · 1 stopped". */
export function appsLine(stats) {
  if (!Array.isArray(stats?.docker)) return '';
  const apps = stats.docker.filter((c) => !/^kiboto/.test(String(c.name || '')));
  const running = apps.filter((c) => c.state === 'running').length;
  const stopped = apps.filter((c) => STOPPED.has(c.state)).length;
  const line = t('ov.tile_apps', '{count, plural, one {# app} other {# apps}}, {running} running', { count: apps.length, running });
  return stopped ? `${line} · ${t('ov.tile_apps_stopped', '{count} stopped', { count: stopped })}` : line;
}

/** When the newest copy outside the NAS was made, from the status box's own answer. */
export function backupLine(p) {
  if (!p || !p.level) return '';
  if (p.level === 'none') return t('ov.tile_backup_none', 'No copy outside this NAS yet');
  if (!p.last_good) return t('ov.tile_backup_some', 'Copies outside this NAS');
  return t('ov.tile_backup_when', 'Newest copy outside: {when}', { when: formatDateTime(p.last_good * 1000) });
}

function setLine(root, id, text) {
  const el = root.getElementById(id);
  if (el && text) el.textContent = text;
}

export function updateHubTiles(stats, root = document) {
  if (!stats) return;
  setLine(root, 'mgmt-hub-storage-line', storageLine(stats));
  setLine(root, 'mgmt-hub-apps-line', appsLine(stats));
}

let _listening = false;
/** Fills the Storage and Apps tiles now and with every live reading after. */
export function installHubTiles(root = document) {
  updateHubTiles(state.lastStats, root);
  if (_listening) return;
  _listening = true;
  ZettEventBus.on('stats:updated', (stats) => updateHubTiles(stats, root));
}

/** Getting started on the Overview is for whoever sets the NAS up (overview decision 5). */
export function setsUp(user = /** @type {any} */ (globalThis).kibotoUser) {
  const scopes = (user && user.scopes) || [];
  return !user || ['*', 'system:*', 'system:config'].some((x) => scopes.includes(x));
}

/** The Backup tile's line and Getting started, after the status box has its answer. */
export async function renderHubExtras(root, protection, summary = null) {
  setLine(root, 'mgmt-hub-backup-line', backupLine(protection));
  _driveIssues = driveIssues(summary);
  updateHubTiles(state.lastStats, root);
  const box = root.getElementById('mgmt-hub-getting-started');
  if (!box) return;
  let data = null;
  if (setsUp()) data = await api.get('/api/setup/checklist').catch(() => null);
  const checklistHtml = /** @type {any} */ (window).gettingStartedHtml; // set by getting-started.js (first load)
  if (!data || data.complete || !(data.items || []).length || typeof checklistHtml !== 'function') {
    box.hidden = true;
    return;
  }
  box.innerHTML = checklistHtml(data).replace('id="gs-heading"', 'id="gs-hub-heading"');
  box.querySelector('[data-gs-hide]')?.remove(); // hidden on the desktop is not hidden here
  box.hidden = false;
  if (!box.dataset.wired) {
    box.dataset.wired = '1';
    box.addEventListener('click', (e) => {
      const open = /** @type {HTMLElement | null} */ (/** @type {Element} */ (e.target).closest('[data-gs-open]'));
      if (open) /** @type {any} */ (window).openManagementSection?.(open.dataset.gsOpen);
    });
  }
}
