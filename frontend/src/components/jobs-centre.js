/**
 * Jobs centre (Batch 4): everything running and recently finished, from /api/jobs, with
 * progress and cancel. A top-bar button shows how many jobs are running.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { formatDateTime } from '../format.js';
import { t } from '../i18n.js';
import { applyWindowSnap, bringToFront, makeDraggable, restoreWindowSnap } from './dock.js';
import { showToast } from '../toast.js';

const BADGE_POLL_MS = 15000;
const OPEN_POLL_MS = 2000;
const DOCK_ID = 'jobs';
let _badgeTimer = null;
let _openTimer = null;
let _win = null;

const KIND = {
  transfer: ['jobs.kind_transfer', 'File transfer'],
  media_import: ['jobs.kind_media_import', 'Media import'],
  ai_reindex: ['jobs.kind_ai_reindex', 'AI index'],
  cloud_sync: ['jobs.kind_cloud_sync', 'Cloud sync'],
  backup: ['jobs.kind_backup', 'Backup'],
};
const STATUS = {
  queued: ['jobs.status_queued', 'Waiting'],
  running: ['jobs.status_running', 'Running'],
  paused: ['jobs.status_paused', 'Paused'],
  done: ['jobs.status_done', 'Done'],
  error: ['jobs.status_error', 'Failed'],
  cancelled: ['jobs.status_cancelled', 'Cancelled'],
};
const label = (map, key) => (map[key] ? t(map[key][0], map[key][1]) : key);

export function jobRowHtml(job, active) {
  const pct = typeof job.percent === 'number' ? Math.max(0, Math.min(100, job.percent)) : null;
  const bar = active
    ? `<div class="jobs-bar" role="progressbar" aria-label="${escapeHtml(job.title)}" aria-valuemin="0" aria-valuemax="100"${
        pct === null ? '' : ` aria-valuenow="${Math.round(pct)}"`
      }><span class="jobs-bar-fill${pct === null ? ' is-indeterminate' : ''}" style="width:${pct === null ? 40 : pct}%"></span></div>`
    : '';
  const when = active ? '' : `<span class="jobs-when">${escapeHtml(formatDateTime(job.finished_at ? job.finished_at * 1000 : null, undefined, ''))}</span>`;
  const cancel = active && job.can_cancel
    ? `<button type="button" class="jobs-cancel" data-job-cancel="${escapeHtml(job.id)}">${escapeHtml(t('jobs.cancel', 'Cancel'))}</button>`
    : '';
  const detail = job.error || job.detail || '';
  return `<li class="jobs-row is-${escapeHtml(job.status)}">
    <div class="jobs-row-head">
      <span class="jobs-kind">${escapeHtml(label(KIND, job.kind))}</span>
      <span class="jobs-title">${escapeHtml(job.title)}</span>
      <span class="jobs-status">${escapeHtml(label(STATUS, job.status))}${pct !== null && active ? ` · ${Math.round(pct)}%` : ''}</span>
      ${when}${cancel}
    </div>
    ${bar}
    ${detail ? `<div class="jobs-detail">${escapeHtml(detail)}</div>` : ''}
  </li>`;
}

export function renderJobs(data, root = document) {
  const active = (data && data.active) || [];
  const history = ((data && data.history) || []).slice(0, 30);
  const run = root.getElementById ? root.getElementById('jobs-active-list') : root.querySelector('#jobs-active-list');
  const rec = root.getElementById ? root.getElementById('jobs-history-list') : root.querySelector('#jobs-history-list');
  if (run) {
    run.innerHTML = active.length
      ? active.map((j) => jobRowHtml(j, true)).join('')
      : `<li class="jobs-empty">${escapeHtml(t('jobs.none_running', 'Nothing is running. Copies, imports, backups and AI indexing show up here.'))}</li>`;
  }
  if (rec) {
    rec.innerHTML = history.length
      ? history.map((j) => jobRowHtml(j, false)).join('')
      : `<li class="jobs-empty">${escapeHtml(t('jobs.none_recent', 'No finished jobs yet.'))}</li>`;
  }
  setJobsBadge(active.length);
}

export function setJobsBadge(n) {
  const badge = document.getElementById('topbar-jobs-count');
  const btn = document.getElementById('topbar-jobs-btn');
  if (badge) {
    badge.textContent = String(n);
    badge.hidden = n === 0;
  }
  if (btn) {
    btn.classList.toggle('has-jobs', n > 0);
    btn.setAttribute('aria-label', n > 0 ? t('jobs.button_running', '{n} jobs running', { n }) : t('jobs.title', 'Jobs'));
  }
}

export async function refreshJobs() {
  try {
    const data = await api.get('/api/jobs');
    renderJobs(data);
    return data;
  } catch (e) {
    return null;
  }
}

function ensureWindow() {
  if (_win) return _win;
  _win = document.getElementById('jobs-centre-window');
  if (!_win) {
    const el = document.createElement('div');
    el.id = 'jobs-centre-window';
    el.className = 'os-window jobs-centre-window';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-labelledby', 'jobs-centre-title');
    el.hidden = true;
    el.innerHTML = `
      <div class="os-window-header">
        <div class="os-window-title" id="jobs-centre-title">${escapeHtml(t('jobs.title', 'Jobs'))}</div>
        <div class="os-window-controls">
          <button class="win-btn min-btn" id="jobs-centre-min" title="${escapeHtml(t('window.minimize', 'Minimize'))}" aria-label="${escapeHtml(t('window.minimize', 'Minimize'))}"></button>
          <button class="win-btn max-btn" id="jobs-centre-max" title="${escapeHtml(t('ui.maximize', 'Maximize'))}" aria-label="${escapeHtml(t('ui.maximize', 'Maximize'))}"></button>
          <button class="win-btn close-btn" id="jobs-centre-close" title="${escapeHtml(t('window.close', 'Close'))}" aria-label="${escapeHtml(t('window.close', 'Close'))}"></button>
        </div>
      </div>
      <div class="jobs-body">
        <h3 class="jobs-heading">${escapeHtml(t('jobs.running', 'Running'))}</h3>
        <ul id="jobs-active-list" class="jobs-list" aria-live="polite"></ul>
        <h3 class="jobs-heading">${escapeHtml(t('jobs.recent', 'Recent'))}</h3>
        <ul id="jobs-history-list" class="jobs-list"></ul>
      </div>`;
    document.body.appendChild(el);
    _win = el;
  }
  const on = (sel, fn) =>
    _win.querySelector(sel)?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation(); // not a drag of the title bar
      fn();
    });
  on('#jobs-centre-close', closeJobsCentre);
  on('#jobs-centre-min', minimizeJobsCentre);
  on('#jobs-centre-max', toggleMaximizeJobsCentre);
  _win.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-job-cancel]');
    if (!btn) return;
    btn.disabled = true;
    try {
      await api.post(`/api/jobs/${encodeURIComponent(btn.dataset.jobCancel)}/cancel`, {});
      showToast(t('jobs.cancelling', 'Cancelling…'), 'info');
    } catch (err) {
      showToast(t('jobs.cancel_failed', 'That job can no longer be cancelled.'), 'error');
    }
    refreshJobs();
  });
  try {
    makeDraggable(_win, _win.querySelector('.os-window-header'));
  } catch (e) {
    /* window manager not ready (tests) */
  }
  return _win;
}

// The window manager shows windows with an inline display, so the hidden attribute alone
// does not hide this one: hiding sets display none too, showing removes it.
function isShown() {
  return Boolean(_win && !_win.hidden && _win.style.display !== 'none' && !_win.classList.contains('window-minimized'));
}

function dock() {
  return typeof window !== 'undefined' ? window.DockManager : null;
}

export function openJobsCentre() {
  const win = ensureWindow();
  win.hidden = false;
  win.classList.remove('window-minimized');
  win.style.removeProperty('display');
  const dm = dock();
  if (dm) {
    try {
      // also brings it back when it was minimized to the dock
      dm.register(DOCK_ID, win, '#i-chip', t('jobs.title', 'Jobs'));
      if (dm.windows?.[DOCK_ID]) dm.windows[DOCK_ID].onClose = closeJobsCentre; // closing from the dock
    } catch (e) {
      /* optional */
    }
  }
  win.style.display = 'flex';
  try {
    bringToFront(win);
  } catch (e) {
    /* tests */
  }
  refreshJobs();
  clearInterval(_openTimer);
  // a minimized window keeps its place in the dock but stops asking for updates
  _openTimer = setInterval(() => {
    if (isShown()) refreshJobs();
  }, OPEN_POLL_MS);
}

export function closeJobsCentre() {
  if (_win) {
    _win.hidden = true;
    _win.classList.remove('open', 'active-window');
    _win.style.setProperty('display', 'none', 'important');
  }
  const dm = dock();
  if (dm?.windows?.[DOCK_ID]) {
    try {
      dm.unregister(DOCK_ID);
    } catch (e) {
      /* optional */
    }
  }
  clearInterval(_openTimer);
  _openTimer = null;
}

/** Parks the window in the dock; its dock icon or the top-bar button brings it back. */
export function minimizeJobsCentre() {
  const dm = dock();
  if (!_win || !dm?.windows?.[DOCK_ID]) {
    closeJobsCentre();
    return;
  }
  dm.minimize(DOCK_ID);
}

export function toggleMaximizeJobsCentre() {
  if (!_win) return;
  if (_win.dataset.snapped === 'maximize') restoreWindowSnap(_win, DOCK_ID);
  else applyWindowSnap(_win, 'maximize', DOCK_ID);
}

export function initJobsCentre() {
  const pills = document.querySelector('.suite-telemetry-pills');
  if (pills && !document.getElementById('topbar-jobs-btn')) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'topbar-jobs-btn';
    btn.className = 'topbar-jobs-btn';
    btn.title = t('jobs.title', 'Jobs');
    btn.setAttribute('aria-label', t('jobs.title', 'Jobs'));
    btn.innerHTML = `<span class="topbar-jobs-icon" aria-hidden="true">⇅</span><span id="topbar-jobs-count" class="topbar-jobs-count" hidden>0</span>`;
    btn.addEventListener('click', openJobsCentre);
    pills.insertBefore(btn, pills.firstChild);
  }
  window.openJobsCentre = openJobsCentre;
  clearInterval(_badgeTimer);
  refreshJobs();
  _badgeTimer = setInterval(() => {
    if (!document.hidden) refreshJobs();
  }, BADGE_POLL_MS);
}

export function _resetJobsCentreForTesting() {
  clearInterval(_badgeTimer);
  clearInterval(_openTimer);
  _badgeTimer = null;
  _openTimer = null;
  _win = null;
}
