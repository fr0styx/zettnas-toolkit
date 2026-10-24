/**
 * Transfers panel: progress for copy, move, merge, duplicate, archive, upload and delete.
 *
 * Server tasks (/api/fs/transfer/async, /api/fs/archive/*) stream their progress over
 * /api/fs/transfers/stream; uploads and deletes run in the browser and report here directly.
 * One panel and one stream serve every File Explorer window. The panel is a pop-up window
 * (dialog-chrome.js gives it the title bar) that opens by itself when an operation takes
 * longer than a moment, and a toast reports how each operation ended.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { ZettEventBus } from '../event-bus.js';
import { escapeHtml } from '../utils.js';
import { formatBytes } from '../format.js';

const SHOW_AFTER_MS = 700; // quick operations finish without the panel popping up
const ACTIVE = new Set(['pending', 'running', 'paused']);
const ICON = { copy: '⧉', move: '➜', duplicate: '⧉', archive_create: '🗜️', archive_extract: '📦', upload: '⬆', delete: '🗑️', trash: '🗑️' };

const baseName = (p) => String(p || '').replace(/\/+$/, '').split('/').pop() || '/';

/** "1:05" or "1:02:05" */
export function formatDuration(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

/** What a task is doing, in words: "Copying 3 item(s) to Movies". */
export function taskLabel(task) {
  if (task.label) return task.label;
  const count = (task.sources || []).length || 1;
  const dest = baseName(task.destination);
  switch (task.kind || task.action) {
    case 'move': return t('transfers.moving', 'Moving {count} item(s) to {dest}', { count, dest });
    case 'duplicate': return t('transfers.duplicating', 'Duplicating {count} item(s)', { count });
    case 'archive_create': return t('transfers.zipping', 'Creating {name}', { name: baseName(task.destination) });
    case 'archive_extract': return t('transfers.extracting', 'Extracting {name}', { name: baseName((task.sources || [])[0]) });
    default: return t('transfers.copying', 'Copying {count} item(s) to {dest}', { count, dest });
  }
}

/** The status line under the title. */
export function taskStatus(task) {
  const s = task.status;
  if (s === 'completed') {
    const skipped = task.result?.skipped || 0;
    const base = skipped ? t('transfers.done_skipped', 'Done, {count} skipped', { count: skipped }) : t('transfers.done', 'Done');
    return task.error ? `${base}. ${task.error}` : base;
  }
  if (s === 'failed') return t('transfers.failed', 'Failed: {error}', { error: task.error || '?' });
  if (s === 'cancelled') return t('transfers.cancelled', 'Cancelled');
  const parts = [];
  if (s === 'paused') parts.push(t('transfers.paused', 'Paused'));
  if (task.total_files > 1) {
    parts.push(t('transfers.progress_files', '{done} of {total} files', { done: task.processed_files || 0, total: task.total_files }));
  }
  if (task.total_bytes > 0) {
    parts.push(t('transfers.progress_bytes', '{done} of {total}', { done: formatBytes(task.processed_bytes || 0), total: formatBytes(task.total_bytes) }));
  }
  if (!parts.length && s !== 'paused') parts.push(t('transfers.counting', 'Counting files…'));
  if (s === 'running' && task.speed_bps > 1024) parts.push(`${formatBytes(task.speed_bps)}/s`);
  if (s === 'running' && task.eta_seconds > 0) parts.push(t('transfers.time_left', '{time} left', { time: formatDuration(task.eta_seconds) }));
  return parts.join(' · ');
}

class TransferCenter {
  constructor() {
    this.tasks = new Map(); // id -> task (server tasks and local ones)
    this.watch = new Map(); // id -> { onDone, toast } for operations started in this browser
    this.local = new Map(); // id -> { cancel }
    this.host = null;
    this.source = null;
    this._seq = 0;
    this._renderQueued = false;
  }

  // ---------- panel ----------

  ensureDom() {
    if (this.host && this.host.isConnected) return this.host;
    let host = document.getElementById('fm-transfers-cockpit');
    if (!host) {
      host = document.createElement('div');
      host.id = 'fm-transfers-cockpit';
      host.style.display = 'none';
      host.innerHTML = `
        <div class="smart-modal-window fm-transfers-window" role="dialog" aria-labelledby="fm-transfers-title" data-dock-icon="#i-upload">
          <div class="smart-modal-header">
            <span class="smart-modal-title" id="fm-transfers-title"><span aria-hidden="true">⇄</span> ${escapeHtml(t('transfers.title', 'Transfers'))}</span>
            <div style="display:flex; align-items:center; gap:10px;">
              <button type="button" class="fm-transfers-clear" id="fm-cockpit-clear-btn">${escapeHtml(t('transfers.clear', 'Clear finished'))}</button>
              <div class="os-window-controls">
                <button type="button" class="win-btn close-btn" id="fm-cockpit-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
              </div>
            </div>
          </div>
          <div class="smart-modal-body fm-cockpit-body" aria-live="polite"></div>
        </div>`;
      document.body.appendChild(host);
    }
    host.className = 'dlg-modeless fm-transfers-layer';
    host.querySelector('#fm-cockpit-close-btn').onclick = () => this.toggle(false);
    host.querySelector('#fm-cockpit-clear-btn').onclick = () => this.clearFinished();
    host.querySelector('.fm-cockpit-body').onclick = (e) => this.onAction(e);
    this.host = host;
    this.render();
    return host;
  }

  get isOpen() {
    return !!(this.host && this.host.classList.contains('open') && this.host.style.display !== 'none');
  }

  toggle(show = null) {
    const host = this.ensureDom();
    const open = show === null ? !this.isOpen : show;
    host.style.display = open ? 'flex' : 'none';
    host.classList.toggle('open', open);
    document.querySelectorAll('.fm-btn-transfers-toggle').forEach((b) => b.classList.toggle('active', open));
    if (open) this.render();
    return open;
  }

  async clearFinished() {
    for (const [id, task] of this.tasks) {
      if (!ACTIVE.has(task.status)) this.tasks.delete(id);
    }
    try {
      await api.delete('/api/fs/transfers/completed');
    } catch (_) {
      // nothing to clear on the server, or no permission: the list is cleared here anyway
    }
    this.render();
  }

  async onAction(e) {
    const btn = e.target instanceof Element ? e.target.closest('button[data-act]') : null;
    if (!btn) return;
    e.stopPropagation();
    const { act, id } = btn.dataset;
    if (this.local.has(id)) {
      if (act === 'cancel') this.local.get(id).cancel?.();
      return;
    }
    try {
      await api.post(`/api/fs/transfers/${encodeURIComponent(id)}/${act}`, {});
    } catch (err) {
      showToast(t('transfers.action_failed', 'Could not {action} this transfer: {error}', { action: act, error: err.message }), 'error');
    }
  }

  queueRender() {
    if (this._renderQueued) return;
    this._renderQueued = true;
    (window.requestAnimationFrame || ((fn) => setTimeout(fn, 16)))(() => {
      this._renderQueued = false;
      this.render();
    });
  }

  render() {
    const list = Array.from(this.tasks.values()).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const active = list.filter((tk) => ACTIVE.has(tk.status)).length;
    document.querySelectorAll('.fm-transfers-count-badge').forEach((badge) => {
      badge.textContent = active ? String(active) : '';
      badge.style.display = active ? 'inline-block' : 'none';
    });
    const body = this.host?.querySelector('.fm-cockpit-body');
    if (!body) return;
    if (!list.length) {
      body.innerHTML = `<div class="fm-transfers-empty">${escapeHtml(t('transfers.empty', 'No transfers'))}</div>`;
      return;
    }
    body.innerHTML = list.slice(0, 20).map((task) => this.cardHtml(task)).join('');
  }

  cardHtml(task) {
    const s = task.status;
    const known = task.total_bytes > 0 || task.total_files > 0;
    let pct = Number(task.percent) || 0;
    if (task.total_bytes > 0) pct = Math.max(pct, (task.processed_bytes / task.total_bytes) * 100);
    else if (task.total_files > 0) pct = Math.max(pct, (task.processed_files / task.total_files) * 100);
    pct = s === 'completed' ? 100 : Math.max(0, Math.min(100, pct));
    const indeterminate = ACTIVE.has(s) && !known;
    const isLocal = this.local.has(task.id);
    const id = escapeHtml(task.id);
    const btn = (act, label, glyph) =>
      `<button type="button" class="fm-task-btn" data-act="${act}" data-id="${id}" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}">${glyph}</button>`;
    let buttons = '';
    if (!isLocal && s === 'running') buttons += btn('pause', t('transfers.pause', 'Pause'), '⏸');
    if (!isLocal && s === 'paused') buttons += btn('resume', t('transfers.resume', 'Resume'), '▶');
    if (ACTIVE.has(s) && (!isLocal || this.local.get(task.id)?.cancel)) buttons += btn('cancel', t('transfers.cancel', 'Cancel'), '✕');
    const current = ACTIVE.has(s) && task.current_file ? `<div class="fm-task-file" title="${escapeHtml(task.current_file)}">${escapeHtml(task.current_file)}</div>` : '';
    return `
      <div class="fm-task-card is-${escapeHtml(s)}" data-task-id="${id}">
        <div class="fm-task-head">
          <span class="fm-task-icon" aria-hidden="true">${ICON[task.kind || task.action] || '⇄'}</span>
          <span class="fm-task-title" title="${escapeHtml(taskLabel(task))}">${escapeHtml(taskLabel(task))}</span>
          <span class="fm-task-pct">${s === 'completed' ? '✓' : ACTIVE.has(s) && known ? `${Math.floor(pct)}%` : ''}</span>
        </div>
        <div class="fm-task-bar${indeterminate ? ' is-indeterminate' : ''}" role="progressbar" aria-label="${escapeHtml(taskLabel(task))}"
             aria-valuemin="0" aria-valuemax="100" ${indeterminate ? '' : `aria-valuenow="${Math.floor(pct)}"`}>
          <div class="fm-task-fill"${indeterminate ? '' : ` style="width:${pct}%"`}></div>
        </div>
        ${current}
        <div class="fm-task-foot">
          <span class="fm-task-status">${escapeHtml(taskStatus(task))}</span>
          <span class="fm-task-btns">${buttons}</span>
        </div>
      </div>`;
  }

  // ---------- server tasks ----------

  connect() {
    if (this.source || typeof EventSource === 'undefined') return;
    try {
      this.source = new EventSource('/api/fs/transfers/stream');
      this.source.addEventListener('snapshot', (e) => {
        try {
          for (const task of JSON.parse(e.data).tasks || []) this.update(task);
        } catch (_) {
          // a malformed event: the next update brings the full task again
        }
      });
      this.source.addEventListener('task_update', (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data && data.task) this.update(data.task);
        } catch (_) {
          // as above
        }
      });
    } catch (_) {
      this.source = null;
    }
  }

  update(task) {
    const prev = this.tasks.get(task.id);
    const merged = { ...prev, ...task };
    if (prev?.label && !task.label) merged.label = prev.label;
    this.tasks.set(task.id, merged);
    if (!ACTIVE.has(merged.status)) this.finished(merged);
    this.queueRender();
  }

  /** Follows an operation started here: opens the panel if it takes a while, reports how it ended. */
  follow(task, { label = '', onDone = null } = {}) {
    if (label) task.label = label;
    if (!task.created_at) task.created_at = Date.now() / 1000;
    this.watch.set(task.id, { onDone });
    this.update(task);
    setTimeout(() => {
      const now = this.tasks.get(task.id);
      if (now && ACTIVE.has(now.status) && !this.isOpen) this.toggle(true);
    }, SHOW_AFTER_MS);
  }

  finished(task) {
    const w = this.watch.get(task.id);
    if (!w) return;
    this.watch.delete(task.id);
    const label = taskLabel(task);
    if (task.status === 'completed' && !task.error) {
      showToast(t('transfers.toast_done', '{label}: done', { label }), 'success');
    } else if (task.status === 'completed') {
      showToast(t('transfers.toast_partial', '{label}: finished with problems. {error}', { label, error: task.error }), 'warning');
    } else if (task.status === 'failed') {
      showToast(t('transfers.toast_failed', '{label} failed: {error}', { label, error: task.error || '?' }), 'error');
    }
    ZettEventBus.emit('fm:refresh');
    if (typeof w.onDone === 'function') {
      try {
        w.onDone(task);
      } catch (_) {
        // a caller's follow-up must not break the panel
      }
    }
  }

  /** Starts a background copy, move, merge or duplicate and follows it. */
  async startTransfer({ sources, destinationDir, action = 'copy', policy = 'merge', targetNames = null, kind = '', label = '', onDone = null }) {
    this.connect();
    const body = { sources, destination_dir: destinationDir, action, collision_policy: policy };
    if (targetNames) body.target_names = targetNames;
    if (kind) body.kind = kind;
    try {
      const res = await api.post('/api/fs/transfer/async', body);
      this.follow(res.task || { id: res.task_id, status: 'pending', action, sources, destination: destinationDir, kind }, { label, onDone });
      return res.task_id;
    } catch (err) {
      showToast(t('transfers.start_failed', 'Could not start: {error}', { error: err.message }), 'error');
      return null;
    }
  }

  /** Follows a server task started elsewhere (archive create/extract). */
  followServerTask(res, fallback, opts = {}) {
    this.connect();
    this.follow(res.task || { id: res.task_id, status: 'pending', ...fallback }, opts);
  }

  // ---------- browser-side operations (uploads, deletes) ----------

  /** Shows an operation that runs in the browser; returns a handle to report progress. */
  startLocal({ kind, label, totalFiles = 0, totalBytes = 0, cancel = null }) {
    const id = `local-${++this._seq}`;
    this.local.set(id, { cancel });
    const task = {
      id, kind, action: kind, label, status: 'running', created_at: Date.now() / 1000,
      total_files: totalFiles, processed_files: 0, total_bytes: totalBytes, processed_bytes: 0, percent: 0, current_file: '',
    };
    const started = Date.now();
    this.follow(task, { label });
    const self = this;
    return {
      id,
      progress({ files, bytes, current } = {}) {
        const tk = self.tasks.get(id);
        if (!tk || !ACTIVE.has(tk.status)) return;
        if (files != null) tk.processed_files = files;
        if (bytes != null) tk.processed_bytes = bytes;
        if (current != null) tk.current_file = current;
        const elapsed = (Date.now() - started) / 1000;
        if (tk.total_bytes) {
          tk.percent = (tk.processed_bytes / tk.total_bytes) * 100;
          tk.speed_bps = elapsed > 0.5 ? tk.processed_bytes / elapsed : 0;
          tk.eta_seconds = tk.speed_bps > 1024 ? (tk.total_bytes - tk.processed_bytes) / tk.speed_bps : null;
        } else if (tk.total_files) {
          tk.percent = (tk.processed_files / tk.total_files) * 100;
        }
        self.queueRender();
      },
      finish(status = 'completed', error = null) {
        const tk = self.tasks.get(id);
        if (!tk) return;
        self.update({ ...tk, status, error, percent: status === 'completed' ? 100 : tk.percent, speed_bps: 0, eta_seconds: null });
        self.local.set(id, {});
      },
    };
  }
}

export const transferCenter = new TransferCenter();

if (typeof window !== 'undefined') window.transferCenter = transferCenter;
