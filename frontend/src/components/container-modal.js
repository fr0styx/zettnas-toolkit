/**
 * ZettNAS Toolkit - Container Inspector & Docker Compose Viewer Modal
 * Provides tabbed inspection: Overview Telemetry, Ports & Web Access,
 * Mounts (with File Explorer deep-link), Masked Environment Variables,
 * Dynamic Docker Compose Synthesizer, and Live Log Console.
 */

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { escapeHtml, trapFocus } from '../utils.js';
import { t } from '../i18n.js';
import { bringToFront, makeDraggable, DockManager } from './dock.js';
import { ZettEventBus } from '../event-bus.js';

let _activeCid = null;
let _activeCname = null;
let _activeComposeData = null;
let _activeLogLines = [];
let _activeLogFilter = '';
let _autoScrollLogs = true;
let _unbindFocusTrap = null;
let _activeTab = 'overview';
let _termHistory = [];
let _termHistoryIdx = -1;
let _activeDetails = null;

export function initContainerModal() {
  if (document.getElementById('container-inspector-overlay')) return;

  const overlayHtml = `
    <div id="container-inspector-overlay" class="smart-modal-backdrop" style="display:none; z-index:10010;">
      <div id="container-inspector-window" class="smart-modal-window container-inspector-window" style="width:780px; max-width:95vw; height:580px; max-height:92vh; display:flex; flex-direction:column;">
        <!-- Header -->
        <div id="container-inspector-header" class="smart-modal-header" style="cursor:move; user-select:none; display:flex; justify-content:space-between; align-items:center;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:16px;">📦</span>
            <span id="ci-header-title" style="font-weight:700; color:#fff; font-size:13px;">Container Inspector</span>
            <code id="ci-header-id" style="font-size:10px; color:var(--muted); font-family:var(--font-mono, monospace);"></code>
            <span id="ci-header-state" class="ci-state-pill" style="display:none;"></span>
          </div>
          <div class="os-window-controls" style="display:flex; gap:6px; align-items:center;">
            <button class="win-btn min-btn" id="ci-min-btn" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="ci-max-btn" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="ci-close-btn" title="Close" aria-label="Close"></button>
          </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="ci-nav-tabs" style="display:flex; gap:4px; padding:8px 14px; background:rgba(0,0,0,0.3); border-bottom:1px solid rgba(255,255,255,0.08); overflow-x:auto;">
          <button class="btn-pill-toggle ci-tab-btn active" data-tab="overview">📊 Overview</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="ports">🌐 Ports & Web</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="mounts">📁 Mounts & Storage</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="env">🔑 Environment</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="compose">📜 Docker Compose</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="logs">📄 Live Logs</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="terminal">💻 Web Terminal</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="edit">✏️ Edit Container</button>
        </div>

        <!-- Tab Content Panes -->
        <div class="ci-panes-container" style="flex:1; overflow-y:auto; padding:14px; box-sizing:border-box;">
          <!-- 1. Overview Tab -->
          <div id="ci-pane-overview" class="ci-pane" style="display:block;">
            <div id="ci-overview-loading" style="text-align:center; padding:30px; color:var(--muted);">Loading details...</div>
            <div id="ci-overview-content" style="display:none;"></div>
          </div>

          <!-- 2. Ports Tab -->
          <div id="ci-pane-ports" class="ci-pane" style="display:none;">
            <div id="ci-ports-content"></div>
          </div>

          <!-- 3. Mounts Tab -->
          <div id="ci-pane-mounts" class="ci-pane" style="display:none;">
            <div id="ci-mounts-content"></div>
          </div>

          <!-- 4. Environment Tab -->
          <div id="ci-pane-env" class="ci-pane" style="display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:8px;">
              <input type="text" id="ci-env-search" placeholder="Filter variables..." class="tz-text-input" style="font-size:11px; padding:3px 8px; width:220px;">
              <span id="ci-env-stats" style="font-size:10px; color:var(--muted);"></span>
            </div>
            <div id="ci-env-content"></div>
          </div>

          <!-- 5. Compose Tab -->
          <div id="ci-pane-compose" class="ci-pane" style="display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <span id="ci-compose-source-badge" class="ci-badge" style="font-size:9.5px; padding:2px 7px; border-radius:4px; font-weight:700;"></span>
                <label style="display:flex; align-items:center; gap:5px; font-size:10.5px; color:var(--muted); cursor:pointer;">
                  <input type="checkbox" id="ci-compose-mask-toggle" checked style="cursor:pointer;">
                  Mask Secrets
                </label>
              </div>
              <div style="display:flex; gap:6px;">
                <button class="btn-pill-toggle" id="ci-compose-copy-btn">📋 Copy YAML</button>
                <button class="btn-pill-toggle" id="ci-compose-download-btn">⬇️ Download .yml</button>
              </div>
            </div>
            <div style="position:relative; background:#080c14; border:1px solid rgba(255,255,255,0.1); border-radius:6px; overflow:hidden;">
              <pre style="margin:0; padding:12px; max-height:360px; overflow:auto; font-family:var(--font-mono, monospace); font-size:11px; color:#e2e8f0; line-height:1.5;"><code id="ci-compose-code">Generating Docker Compose definition...</code></pre>
            </div>
          </div>

          <!-- 6. Logs Tab -->
          <div id="ci-pane-logs" class="ci-pane" style="display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <select id="ci-logs-tail-select" class="tz-select-input" style="font-size:11px; padding:2px 6px;">
                  <option value="50">Last 50 lines</option>
                  <option value="100">Last 100 lines</option>
                  <option value="200" selected>Last 200 lines</option>
                  <option value="500">Last 500 lines</option>
                  <option value="1000">Last 1000 lines</option>
                </select>
                <input type="text" id="ci-logs-filter-input" placeholder="Filter output..." class="tz-text-input" style="font-size:11px; padding:3px 8px; width:160px;">
                <label style="display:flex; align-items:center; gap:4px; font-size:10px; color:var(--muted); cursor:pointer;">
                  <input type="checkbox" id="ci-logs-autoscroll" checked> Auto-scroll
                </label>
              </div>
              <div style="display:flex; gap:6px;">
                <button class="btn-pill-toggle" id="ci-logs-refresh-btn">🔄 Refresh</button>
                <button class="btn-pill-toggle" id="ci-logs-copy-btn">📋 Copy Logs</button>
              </div>
            </div>
            <div id="ci-logs-terminal" style="background:#05080f; border:1px solid rgba(255,255,255,0.1); border-radius:6px; height:340px; overflow-y:auto; padding:10px; font-family:var(--font-mono, monospace); font-size:10.5px; line-height:1.45; color:#cbd5e1;">
              <div style="color:var(--muted); text-align:center; padding:20px;">Fetching logs...</div>
            </div>
          </div>

          <!-- 7. Web Terminal Tab -->
          <div id="ci-pane-terminal" class="ci-pane" style="display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="ci-badge" style="font-size:10px; background:rgba(34,197,94,0.15); color:#22c55e; border:1px solid rgba(34,197,94,0.3); padding:2px 8px; border-radius:4px; font-weight:700;">LIVE EXEC</span>
                <span style="font-size:11px; color:var(--muted);">In-browser container command execution</span>
              </div>
              <div style="display:flex; gap:6px;">
                <button class="btn-pill-toggle" id="ci-term-clear-btn">🧹 Clear</button>
              </div>
            </div>
            <div id="ci-term-output" style="background:#030712; border:1px solid rgba(255,255,255,0.12); border-radius:6px 6px 0 0; height:310px; overflow-y:auto; padding:12px; font-family:var(--font-mono, monospace); font-size:11px; line-height:1.45; color:#a7f3d0; white-space:pre-wrap; word-break:break-word;">
              <span style="color:#64748b;"># Interactive Container Terminal Ready. Type commands below (e.g. ls -la, uname -a, ps aux)...</span>
            </div>
            <div style="display:flex; background:#0f172a; border:1px solid rgba(255,255,255,0.12); border-top:none; border-radius:0 0 6px 6px; padding:6px 10px; gap:8px; align-items:center;">
              <span style="color:#10b981; font-family:var(--font-mono, monospace); font-weight:bold; font-size:12px;">$</span>
              <input type="text" id="ci-term-input" placeholder="Type a command and press Enter..." style="flex:1; background:transparent; border:none; outline:none; color:#f8fafc; font-family:var(--font-mono, monospace); font-size:11.5px;" autocomplete="off" spellcheck="false">
              <button class="btn-pill-toggle" id="ci-term-send-btn" style="padding:2px 10px; font-size:11px;">Run</button>
            </div>
          </div>

          <!-- 8. Edit Container Tab -->
          <div id="ci-pane-edit" class="ci-pane" style="display:none;">
            <div id="cie-form-host">
              <div style="text-align:center; padding:30px; color:var(--muted);">Loading container configuration...</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;

  document.body.insertAdjacentHTML('beforeend', overlayHtml);

  const overlay = document.getElementById('container-inspector-overlay');
  const win = document.getElementById('container-inspector-window');
  const header = document.getElementById('container-inspector-header');
  const closeBtn = document.getElementById('ci-close-btn');
  const minBtn = document.getElementById('ci-min-btn');
  const maxBtn = document.getElementById('ci-max-btn');

  // Make draggable
  makeDraggable(win, header, 'container-inspector');

  // Register in DockManager (initially closed/minimized until container selected)
  if (DockManager && !DockManager.windows['container-inspector']) {
    DockManager.register('container-inspector', overlay, '#i-chip', 'Container Inspector', true);
  }

  // Close & Minimize
  closeBtn.addEventListener('click', closeContainerInspector);
  minBtn.addEventListener('click', () => {
    if (DockManager) DockManager.minimize('container-inspector');
  });

  // Maximize toggle
  let isMax = false;
  maxBtn.addEventListener('click', () => {
    isMax = !isMax;
    if (isMax) {
      win.style.width = '96vw';
      win.style.height = '94vh';
      win.style.top = '3vh';
      win.style.left = '2vw';
    } else {
      win.style.width = '780px';
      win.style.height = '580px';
      win.style.top = '100px';
      win.style.left = '180px';
    }
  });

  // Tab switching
  overlay.querySelectorAll('.ci-tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      switchContainerTab(btn.dataset.tab);
    });
  });

  // Compose toggle & copy
  const maskToggle = document.getElementById('ci-compose-mask-toggle');
  if (maskToggle) {
    maskToggle.addEventListener('change', () => {
      renderComposeCode();
    });
  }

  const copyComposeBtn = document.getElementById('ci-compose-copy-btn');
  if (copyComposeBtn) {
    copyComposeBtn.addEventListener('click', () => {
      const codeEl = document.getElementById('ci-compose-code');
      if (codeEl && codeEl.textContent) {
        navigator.clipboard.writeText(codeEl.textContent).then(() => {
          showToast('Docker Compose YAML copied to clipboard!', 'success');
        });
      }
    });
  }

  const downloadComposeBtn = document.getElementById('ci-compose-download-btn');
  if (downloadComposeBtn) {
    downloadComposeBtn.addEventListener('click', () => {
      const codeEl = document.getElementById('ci-compose-code');
      if (!codeEl || !codeEl.textContent) return;
      const blob = new Blob([codeEl.textContent], { type: 'text/yaml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${_activeCname || 'docker'}-compose.yml`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(`Downloaded ${_activeCname}-compose.yml`, 'info');
    });
  }

  // Logs controls
  const tailSelect = document.getElementById('ci-logs-tail-select');
  if (tailSelect) {
    tailSelect.addEventListener('change', () => {
      if (_activeCid) loadContainerLogs(_activeCid);
    });
  }

  const logRefreshBtn = document.getElementById('ci-logs-refresh-btn');
  if (logRefreshBtn) {
    logRefreshBtn.addEventListener('click', () => {
      if (_activeCid) loadContainerLogs(_activeCid);
    });
  }

  const logCopyBtn = document.getElementById('ci-logs-copy-btn');
  if (logCopyBtn) {
    logCopyBtn.addEventListener('click', () => {
      const text = _activeLogLines.map((l) => (l.ts ? `${l.ts} ` : '') + l.msg).join('\n');
      navigator.clipboard.writeText(text).then(() => {
        showToast('Container logs copied to clipboard.', 'success');
      });
    });
  }

  const logFilterInput = document.getElementById('ci-logs-filter-input');
  if (logFilterInput) {
    logFilterInput.addEventListener('input', (e) => {
      _activeLogFilter = (e.target.value || '').toLowerCase();
      renderLogsOutput();
    });
  }

  const autoscrollCb = document.getElementById('ci-logs-autoscroll');
  if (autoscrollCb) {
    autoscrollCb.addEventListener('change', (e) => {
      _autoScrollLogs = e.target.checked;
    });
  }

  // Env search input
  const envSearchInput = document.getElementById('ci-env-search');
  if (envSearchInput) {
    envSearchInput.addEventListener('input', (e) => {
      const query = (e.target.value || '').toLowerCase();
      document.querySelectorAll('#ci-env-content tr').forEach((row) => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(query) ? '' : 'none';
      });
    });
  }

  // Terminal controls
  const termClearBtn = document.getElementById('ci-term-clear-btn');
  if (termClearBtn) {
    termClearBtn.addEventListener('click', clearTerminal);
  }

  const termSendBtn = document.getElementById('ci-term-send-btn');
  if (termSendBtn) {
    termSendBtn.addEventListener('click', executeTerminalCmd);
  }

  const termInput = document.getElementById('ci-term-input');
  if (termInput) {
    termInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        executeTerminalCmd();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (_termHistory.length && _termHistoryIdx > 0) {
          _termHistoryIdx--;
          termInput.value = _termHistory[_termHistoryIdx];
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (_termHistoryIdx < _termHistory.length - 1) {
          _termHistoryIdx++;
          termInput.value = _termHistory[_termHistoryIdx];
        } else {
          _termHistoryIdx = _termHistory.length;
          termInput.value = '';
        }
      }
    });
  }
}

export function closeContainerInspector() {
  const overlay = document.getElementById('container-inspector-overlay');
  if (overlay) {
    overlay.style.display = 'none';
    overlay.classList.remove('open');
  }
  if (_unbindFocusTrap) {
    _unbindFocusTrap();
    _unbindFocusTrap = null;
  }
  if (DockManager) {
    DockManager.unregister('container-inspector');
  }
  _activeCid = null;
  _activeCname = null;
  _activeComposeData = null;
}

export async function switchContainerTab(tabTarget) {
  const overlay = document.getElementById('container-inspector-overlay');
  if (!overlay) return;
  overlay.querySelectorAll('.ci-tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === tabTarget));
  _activeTab = tabTarget;
  overlay.querySelectorAll('.ci-pane').forEach((p) => {
    p.style.display = p.id === `ci-pane-${tabTarget}` ? 'block' : 'none';
  });

  if (tabTarget === 'compose' && _activeCid) {
    await loadContainerCompose(_activeCid);
  } else if (tabTarget === 'logs' && _activeCid) {
    await loadContainerLogs(_activeCid);
  } else if (tabTarget === 'terminal') {
    const input = document.getElementById('ci-term-input');
    if (input) setTimeout(() => input.focus(), 60);
  } else if (tabTarget === 'edit' && _activeCid) {
    await renderContainerEditTab(_activeCid);
  }
}

export async function executeTerminalCmd() {
  const input = document.getElementById('ci-term-input');
  const output = document.getElementById('ci-term-output');
  if (!input || !output || !_activeCid) return;

  const cmd = input.value.trim();
  if (!cmd) return;

  _termHistory.push(cmd);
  _termHistoryIdx = _termHistory.length;
  input.value = '';

  const timestamp = new Date().toLocaleTimeString();
  const cmdNode = document.createElement('div');
  cmdNode.style.marginTop = '6px';
  cmdNode.innerHTML = `<span style="color:#64748b; font-size:10px;">[${timestamp}]</span> <span style="color:#10b981; font-weight:bold;">$</span> <span style="color:#f1f5f9; font-weight:600;">${escapeHtml(cmd)}</span>`;
  output.appendChild(cmdNode);

  const runningNode = document.createElement('div');
  runningNode.style.color = '#64748b';
  runningNode.style.fontStyle = 'italic';
  runningNode.textContent = 'Executing...';
  output.appendChild(runningNode);
  output.scrollTop = output.scrollHeight;

  try {
    const res = await api.post(`/api/docker/containers/${_activeCid}/exec`, { cmd });
    runningNode.remove();

    const resultNode = document.createElement('div');
    resultNode.style.color = '#a7f3d0';
    resultNode.textContent = res.output || '(No output)';
    output.appendChild(resultNode);
  } catch (err) {
    runningNode.remove();
    const errNode = document.createElement('div');
    errNode.style.color = '#ef4444';
    errNode.textContent = `Error: ${err.message || err}`;
    output.appendChild(errNode);
  }
  output.scrollTop = output.scrollHeight;
}

export function clearTerminal() {
  const output = document.getElementById('ci-term-output');
  if (output) {
    output.innerHTML = '<span style="color:#64748b;"># Interactive Container Terminal Ready. Type commands below (e.g. ls -la, uname -a, ps aux)...</span>';
  }
}


export async function openContainerInspector(cid, cname, initialTab = 'overview') {
  initContainerModal();
  const overlay = document.getElementById('container-inspector-overlay');
  const win = document.getElementById('container-inspector-window');
  if (!overlay || !win) return;

  _activeCid = cid;
  _activeCname = cname || cid;

  // Header texts
  const titleName = document.getElementById('ci-header-title');
  const titleId = document.getElementById('ci-header-id');
  const titleState = document.getElementById('ci-header-state');
  if (titleName) titleName.textContent = _activeCname;
  if (titleId) titleId.textContent = cid.slice(0, 12);
  if (titleState) titleState.style.display = 'none';

  // Restore & bring to front
  overlay.style.removeProperty('display');
  overlay.style.display = 'flex';
  overlay.classList.add('open');
  win.classList.remove('window-minimized');
  bringToFront(win);

  if (DockManager) {
    DockManager.restore('container-inspector');
  }

  if (_unbindFocusTrap) _unbindFocusTrap();
  _unbindFocusTrap = trapFocus(win, closeContainerInspector);

  // Activate requested tab
  const targetTab = initialTab || 'overview';
  const tabBtn = overlay.querySelector(`.ci-tab-btn[data-tab="${targetTab}"]`);
  if (tabBtn) tabBtn.click();
  else switchContainerTab(targetTab);

  // Load details
  await loadContainerDetails(cid);
  if (targetTab === 'edit') {
    await renderContainerEditTab(cid);
  }
}

async function loadContainerDetails(cid) {
  const loadingEl = document.getElementById('ci-overview-loading');
  const contentEl = document.getElementById('ci-overview-content');
  if (loadingEl) loadingEl.style.display = 'block';
  if (contentEl) contentEl.style.display = 'none';

  try {
    const details = await api.get(`/api/docker/containers/${encodeURIComponent(cid)}/details`);
    _activeDetails = details;
    if (loadingEl) loadingEl.style.display = 'none';
    if (!contentEl) return;
    contentEl.style.display = 'block';

    const ov = details.overview || {};
    const res = details.resources || {};
    const stateColor = ov.running ? 'var(--ok2)' : 'var(--muted)';
    const stateBg = ov.running ? 'rgba(37, 194, 160, 0.15)' : 'rgba(255, 255, 255, 0.08)';

    // Update Header state pill
    const titleState = document.getElementById('ci-header-state');
    if (titleState) {
      titleState.textContent = (ov.state || 'unknown').toUpperCase();
      titleState.style.color = stateColor;
      titleState.style.background = stateBg;
      titleState.style.display = 'inline-block';
      titleState.style.padding = '2px 6px';
      titleState.style.borderRadius = '4px';
      titleState.style.fontSize = '9px';
      titleState.style.fontWeight = '700';
    }

    // Hardware badges HTML
    const hwBadges = (details.hardware_badges || []).map(
      (b) => `<span class="docker-hw-badge docker-hw-${escapeHtml(b.id)}">${escapeHtml(b.label)}</span>`
    ).join(' ') || '<span style="color:var(--muted); font-size:11px;">None</span>';

    // Stack pill HTML
    const stackHtml = details.stack
      ? `<span class="docker-stack-pill">📁 ${escapeHtml(details.stack)}</span>`
      : `<span class="docker-origin-pill">${escapeHtml(details.managed_by === 'unraid' ? 'Unraid' : 'Standalone')}</span>`;

    const memMb = res.memory_limit ? Math.round(res.memory_limit / (1024 * 1024)) : 0;
    const cpuCores = res.nano_cpus ? (res.nano_cpus / 1e9).toFixed(1) : 0;
    const currentRestart = ov.restart_policy || 'unless-stopped';

    // Overview Tab Content
    contentEl.innerHTML = `
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:10px; margin-bottom:16px;">
        <div class="ci-metric-card" style="background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.06); padding:10px; border-radius:6px;">
          <div style="font-size:10px; color:var(--muted); text-transform:uppercase; font-weight:700;">State & Uptime</div>
          <div style="font-size:13px; font-weight:700; color:#fff; margin-top:3px;">${escapeHtml(ov.state || 'unknown')}</div>
          <div style="font-size:10px; color:var(--muted); margin-top:2px;">Started: ${escapeHtml(ov.started_at ? new Date(ov.started_at).toLocaleString() : 'N/A')}</div>
        </div>
        <div class="ci-metric-card" style="background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.06); padding:10px; border-radius:6px;">
          <div style="font-size:10px; color:var(--muted); text-transform:uppercase; font-weight:700;">Network IP</div>
          <div style="font-size:13px; font-weight:700; color:var(--accent-cyan,#00f0ff); margin-top:3px;">${escapeHtml(ov.ip_address || 'Host Network')}</div>
          <div style="font-size:10px; color:var(--muted); margin-top:2px;">Mode: ${escapeHtml(ov.network_mode || 'bridge')}</div>
        </div>
        <div class="ci-metric-card" style="background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.06); padding:10px; border-radius:6px;">
          <div style="font-size:10px; color:var(--muted); text-transform:uppercase; font-weight:700;">Hardware & Stack</div>
          <div style="margin-top:4px;">${hwBadges}</div>
          <div style="margin-top:4px;">${stackHtml}</div>
        </div>
      </div>

      <div style="background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.06); border-radius:6px; overflow:hidden; margin-bottom:14px;">
        <table class="copy-history-table" style="margin:0;">
          <tbody>
            <tr><td style="width:140px; color:var(--muted); font-weight:600;">Image</td><td style="font-family:var(--font-mono, monospace); color:#fff;">${escapeHtml(ov.image)}</td></tr>
            <tr><td style="color:var(--muted); font-weight:600;">Full Container ID</td><td style="font-family:var(--font-mono, monospace); font-size:10px; color:var(--muted); word-break:break-all;">${escapeHtml(ov.full_id)}</td></tr>
            <tr><td style="color:var(--muted); font-weight:600;">Restart Policy</td><td><code>${escapeHtml(ov.restart_policy)}</code></td></tr>
            <tr><td style="color:var(--muted); font-weight:600;">Platform / OS</td><td>${escapeHtml(ov.platform)}</td></tr>
            <tr><td style="color:var(--muted); font-weight:600;">Memory Limit</td><td>${res.memory_limit ? (res.memory_limit / (1024 * 1024)).toFixed(0) + ' MB' : 'Unlimited'}</td></tr>
            <tr><td style="color:var(--muted); font-weight:600;">Startup Command</td><td style="font-family:var(--font-mono, monospace); font-size:10px; color:#cbd5e1; word-break:break-all;">${escapeHtml(ov.command)}</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Live Resource Tuning Section (Phase 3) -->
      <div class="ci-metric-card" style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); padding:12px; border-radius:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px;">⚡ Live Resource Tuning (Zero-Downtime)</div>
          <span style="font-size:9.5px; color:var(--accent-cyan,#00f0ff); background:rgba(0,240,255,0.1); padding:2px 6px; border-radius:4px;">Hot-Reloadable</span>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:10px; align-items:end;">
          <div>
            <label style="font-size:10px; color:var(--muted); display:block; margin-bottom:4px;">Memory Limit (MB, 0=Unlimited)</label>
            <input type="number" id="ci-res-mem" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:4px 8px;" value="${memMb}" min="0" step="64">
          </div>
          <div>
            <label style="font-size:10px; color:var(--muted); display:block; margin-bottom:4px;">CPU Cores (0=Unlimited)</label>
            <input type="number" id="ci-res-cpu" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:4px 8px;" value="${cpuCores}" min="0" max="64" step="0.5">
          </div>
          <div>
            <label style="font-size:10px; color:var(--muted); display:block; margin-bottom:4px;">Restart Policy</label>
            <select id="ci-res-restart" class="tz-select-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:4px 6px;">
              <option value="unless-stopped" ${currentRestart === 'unless-stopped' ? 'selected' : ''}>unless-stopped</option>
              <option value="always" ${currentRestart === 'always' ? 'selected' : ''}>always</option>
              <option value="on-failure" ${currentRestart === 'on-failure' ? 'selected' : ''}>on-failure</option>
              <option value="no" ${currentRestart === 'no' ? 'selected' : ''}>no</option>
            </select>
          </div>
          <div>
            <button class="btn-pill-toggle" id="ci-btn-apply-resources" style="width:100%; padding:6px 12px; font-weight:700; color:var(--ok2); border-color:var(--ok2); background:rgba(37,194,160,0.15);">
              💾 Apply Tuning
            </button>
          </div>
        </div>
      </div>

      <!-- Container Management / Danger Zone -->
      <div class="ci-metric-card" style="background:rgba(255,107,107,0.06); border:1px solid rgba(255,107,107,0.22); padding:12px; border-radius:8px; margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div>
            <div style="font-size:11px; font-weight:700; color:#fca5a5; text-transform:uppercase; letter-spacing:0.5px;">⚠️ Danger Zone</div>
            <div style="font-size:10px; color:var(--muted); margin-top:2px;">Restart or permanently destroy this container and its volumes/images.</div>
          </div>
          <div style="display:flex; gap:6px;">
            <button class="btn-pill-toggle" id="ci-btn-restart-action" style="padding:5px 12px; font-size:11px; font-weight:700;">🔄 Restart</button>
            <button class="btn-pill-toggle" id="ci-btn-destroy-action" style="padding:5px 12px; font-size:11px; font-weight:700; color:#fff; background:var(--crit, #ff6b6b); border-color:var(--crit, #ff6b6b); cursor:pointer;">🗑️ Destroy Container</button>
          </div>
        </div>
      </div>
    `;

    // Wire Resource Tuning button
    const applyResBtn = document.getElementById('ci-btn-apply-resources');
    if (applyResBtn) {
      applyResBtn.addEventListener('click', async () => {
        const memInput = document.getElementById('ci-res-mem');
        const cpuInput = document.getElementById('ci-res-cpu');
        const restartInput = document.getElementById('ci-res-restart');
        const memVal = memInput ? parseInt(memInput.value, 10) : 0;
        const cpuVal = cpuInput ? parseFloat(cpuInput.value) : 0;
        const restartVal = restartInput ? restartInput.value : null;

        applyResBtn.disabled = true;
        applyResBtn.textContent = 'Applying...';
        try {
          await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/resources`, {
            memory_mb: isNaN(memVal) ? 0 : memVal,
            nano_cpus: isNaN(cpuVal) ? 0 : cpuVal,
            restart_policy: restartVal,
          });
          showToast('Resource limits updated with zero downtime!', 'success');
          await loadContainerDetails(cid);
        } catch (err) {
          showToast(`Resource update failed: ${err.message}`, 'error');
        } finally {
          applyResBtn.disabled = false;
          applyResBtn.textContent = '💾 Apply Tuning';
        }
      });
    }

    // Wire Danger Zone buttons
    const destroyActionBtn = document.getElementById('ci-btn-destroy-action');
    if (destroyActionBtn) {
      destroyActionBtn.addEventListener('click', () => {
        openContainerDeleteModal(cid, ov.name || _activeCname, ov.image, () => {
          closeContainerInspector();
        });
      });
    }

    const restartActionBtn = document.getElementById('ci-btn-restart-action');
    if (restartActionBtn) {
      restartActionBtn.addEventListener('click', async () => {
        restartActionBtn.disabled = true;
        showToast(`Restarting ${_activeCname}...`, 'info');
        try {
          await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: 'restart' });
          showToast(`Container "${_activeCname}" restarted.`, 'success');
          await loadContainerDetails(cid);
        } catch (err) {
          showToast(`Restart failed: ${err.message}`, 'error');
        } finally {
          restartActionBtn.disabled = false;
        }
      });
    }

    // Populate Ports Tab
    renderPortsTab(details);

    // Populate Mounts Tab
    renderMountsTab(details);

    // Populate Environment Tab
    renderEnvTab(details);
  } catch (err) {
    if (loadingEl) loadingEl.innerHTML = `<span style="color:var(--crit);">Failed to load container details: ${escapeHtml(err.message)}</span>`;
  }
}

function renderPortsTab(details) {
  const container = document.getElementById('ci-ports-content');
  if (!container) return;

  const currentHost = typeof window !== 'undefined' && window.location.hostname ? window.location.hostname : 'localhost';
  const webUrl = details.webui_url ? details.webui_url.replace('[HOST]', currentHost) : null;

  const webuiBanner = webUrl
    ? `
      <div style="margin-bottom:14px; padding:12px; background:rgba(0, 240, 255, 0.08); border:1px solid rgba(0, 240, 255, 0.25); border-radius:6px; display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div style="font-weight:700; color:#fff; font-size:12px;">Web Interface Detected</div>
          <div style="font-size:10px; color:var(--muted); margin-top:2px;">Service exposed on port ${details.primary_port}</div>
        </div>
        <a href="${escapeHtml(webUrl)}" target="_blank" rel="noopener noreferrer" class="btn-webui-badge" style="font-size:11px; padding:4px 10px;">
          🌐 Open Web UI ↗
        </a>
      </div>
    `
    : '';

  const portsList = details.ports || [];
  let tableHtml = '';
  if (portsList.length === 0) {
    tableHtml = '<div style="text-align:center; padding:20px; color:var(--muted);">No published port mappings configured for this container.</div>';
  } else {
    tableHtml = `
      <div style="background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.06); border-radius:6px; overflow:hidden;">
        <table class="copy-history-table" style="margin:0;">
          <thead>
            <tr>
              <th>Host Binding</th>
              <th>Container Port</th>
              <th>Protocol</th>
              <th>Web Access</th>
            </tr>
          </thead>
          <tbody>
            ${portsList.map((p) => {
              const isWeb = p.public_port === details.primary_port;
              const directLink = p.public_port
                ? `<a href="http://${currentHost}:${p.public_port}/" target="_blank" rel="noopener noreferrer" style="color:var(--accent-cyan,#00f0ff); font-size:10px;">http://${currentHost}:${p.public_port} ↗</a>`
                : '—';
              return `
                <tr>
                  <td style="font-family:var(--font-mono, monospace); font-weight:700; color:#fff;">${p.public_port ? `${p.ip || '0.0.0.0'}:${p.public_port}` : '<span style="color:var(--muted);">None</span>'}</td>
                  <td style="font-family:var(--font-mono, monospace);">${p.private_port}</td>
                  <td><span class="ci-proto-tag" style="padding:1px 5px; border-radius:3px; background:rgba(255,255,255,0.08); font-size:9.5px; text-transform:uppercase;">${escapeHtml(p.type || 'tcp')}</span></td>
                  <td>${isWeb ? '<span style="color:var(--ok2); font-weight:700; font-size:10px;">✓ Primary Web UI</span>' : directLink}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>

      <!-- Port Reconfiguration Section (Phase 3) -->
      <div class="ci-metric-card" style="margin-top:14px; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); padding:12px; border-radius:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px;">🔄 Reconfigure Ports (Atomic Clone & Recreate)</div>
          <span style="font-size:9.5px; color:var(--warn); background:rgba(245,158,11,0.12); padding:2px 6px; border-radius:4px;">Rollback Protected</span>
        </div>
        <p style="font-size:10px; color:var(--muted); margin:0 0 10px 0;">
          Modify host port bindings. An atomic recreation stops, clones, and starts the container with updated ports while preserving all volume mounts.
        </p>
        <div style="display:flex; flex-direction:column; gap:8px;">
          ${portsList.map((p, idx) => `
            <div style="display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.03); padding:6px 10px; border-radius:6px;">
              <span style="font-size:11px; color:#fff; font-family:var(--font-mono, monospace); width:130px;">Container :${p.private_port}/${p.type || 'tcp'}</span>
              <span style="color:var(--muted);">➔</span>
              <label style="font-size:10px; color:var(--muted);">Host Port:</label>
              <input type="number" class="tz-text-input ci-port-input" data-idx="${idx}" data-cp="${p.private_port}" data-proto="${p.type || 'tcp'}" value="${p.public_port || ''}" style="width:90px; font-size:11px; padding:3px 6px;">
              <span id="ci-port-check-${idx}" style="font-size:10px; color:var(--muted);"></span>
            </div>
          `).join('')}
          <div style="margin-top:6px;">
            <button class="btn-pill-toggle" id="ci-btn-apply-ports" style="padding:6px 14px; font-weight:700; color:var(--accent-cyan,#00f0ff); border-color:var(--accent-cyan,#00f0ff); background:rgba(0,240,255,0.12);">
              🚀 Recreate Container with New Ports
            </button>
          </div>
        </div>
      </div>
    `;
  }

  container.innerHTML = webuiBanner + tableHtml;

  // Wire Port availability checks and apply button
  const foundInputs = container.querySelectorAll('.ci-port-input');
  foundInputs.forEach((input) => {
    const handleInput = async (e) => {
      const idx = input.dataset.idx;
      const proto = input.dataset.proto;
      const targetVal = e && e.target ? e.target.value : input.value;
      const val = parseInt(targetVal, 10);
      const statusEl = document.getElementById(`ci-port-check-${idx}`);
      if (!statusEl) return;
      if (isNaN(val) || val <= 0 || val > 65535) {
        statusEl.textContent = 'Invalid port';
        statusEl.style.color = 'var(--crit)';
        return;
      }
      statusEl.textContent = 'Checking...';
      statusEl.style.color = 'var(--muted)';
      try {
        const chk = await api.get(`/api/docker/check_port?port=${val}&proto=${proto}`);
        if (chk && chk.available) {
          statusEl.textContent = '✓ Available';
          statusEl.style.color = 'var(--ok2)';
        } else {
          statusEl.textContent = '⚠️ In Use';
          statusEl.style.color = 'var(--warn)';
        }
      } catch (err) {
        console.error('[check_port error]', err);
        statusEl.textContent = '';
      }
    };
    input.addEventListener('input', handleInput);
  });

  const applyPortsBtn = document.getElementById('ci-btn-apply-ports');
  if (applyPortsBtn) {
    applyPortsBtn.addEventListener('click', async () => {
      const cname = details.overview?.name || details.cid;
      const confirmed = window.confirm(`Recreate container "${cname}" with updated port mappings?\n\nA 2-3 second recreation will occur. Volumes and persistent data will remain 100% intact.`);
      if (!confirmed) return;

      const portInputs = container.querySelectorAll('.ci-port-input');
      const newPorts = [];
      portInputs.forEach((inp) => {
        const cp = parseInt(inp.dataset.cp, 10);
        const proto = inp.dataset.proto || 'tcp';
        const hp = parseInt(inp.value, 10);
        newPorts.push({
          container_port: cp,
          host_port: isNaN(hp) ? null : hp,
          proto: proto,
          host_ip: '0.0.0.0'
        });
      });

      applyPortsBtn.disabled = true;
      applyPortsBtn.textContent = 'Recreating container...';
      showToast(`Recreating container "${cname}" with new ports...`, 'info');

      try {
        const targetId = details.cid || details.overview?.id;
        const res = await api.post(`/api/docker/containers/${encodeURIComponent(targetId)}/ports`, {
          ports: newPorts,
          keep_backup: false
        });
        showToast(res.message || 'Container recreated successfully!', 'success');
        await loadContainerDetails(targetId);
      } catch (err) {
        showToast(`Port reconfiguration failed: ${err.message}`, 'error');
      } finally {
        applyPortsBtn.disabled = false;
        applyPortsBtn.textContent = '🚀 Recreate Container with New Ports';
      }
    });
  }
}

function renderMountsTab(details) {
  const container = document.getElementById('ci-mounts-content');
  if (!container) return;

  const mounts = details.mounts || [];
  if (mounts.length === 0) {
    container.innerHTML = '<div style="text-align:center; padding:20px; color:var(--muted);">No storage mounts mapped to this container.</div>';
    return;
  }

  container.innerHTML = `
    <div style="background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.06); border-radius:6px; overflow:hidden;">
      <table class="copy-history-table" style="margin:0;">
        <thead>
          <tr>
            <th>Host Path</th>
            <th>Container Target</th>
            <th>Mode</th>
            <th>Type</th>
            <th style="text-align:right;">File Manager</th>
          </tr>
        </thead>
        <tbody>
          ${mounts.map((m) => {
            const isFmNavigable = m.source && (m.source.startsWith('/mnt/') || m.source.startsWith('/'));
            const appdataBadge = m.is_appdata
              ? '<span style="display:inline-block; margin-left:4px; padding:1px 4px; border-radius:3px; font-size:8.5px; font-weight:700; background:rgba(167, 139, 250, 0.2); color:#c4b5fd;">APPDATA</span>'
              : '';
            const btnHtml = isFmNavigable
              ? `<button class="btn-pill-toggle btn-reveal-fm" data-path="${escapeHtml(m.source)}" style="font-size:9.5px; padding:2px 7px;">📁 Open in Explorer</button>`
              : '—';

            return `
              <tr>
                <td style="font-family:var(--font-mono, monospace); font-size:10.5px; color:#fff; word-break:break-all;">
                  ${escapeHtml(m.source)} ${appdataBadge}
                </td>
                <td style="font-family:var(--font-mono, monospace); font-size:10.5px; color:var(--muted);">${escapeHtml(m.destination)}</td>
                <td><span style="font-size:9.5px; font-weight:700; text-transform:uppercase; color:${m.rw ? 'var(--ok2)' : 'var(--warn)'};">${escapeHtml(m.mode)}</span></td>
                <td style="font-size:9.5px; color:var(--muted);">${escapeHtml(m.type)}</td>
                <td style="text-align:right;">${btnHtml}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;

  // Wire Reveal in File Explorer buttons
  container.querySelectorAll('.btn-reveal-fm').forEach((btn) => {
    btn.addEventListener('click', () => {
      const path = btn.dataset.path;
      if (!path) return;
      ZettEventBus.emit('window:open', { id: 'file-manager-window', path: path });
      showToast(`Navigated File Explorer to ${path}`, 'info');
    });
  });
}

function renderEnvTab(details) {
  const container = document.getElementById('ci-env-content');
  const statsEl = document.getElementById('ci-env-stats');
  if (!container) return;

  const envs = details.env || [];
  if (statsEl) {
    statsEl.textContent = `${envs.length} Variables (${envs.filter((e) => e.is_secret).length} Sensitive)`;
  }

  if (envs.length === 0) {
    container.innerHTML = '<div style="text-align:center; padding:20px; color:var(--muted);">No custom environment variables found.</div>';
    return;
  }

  const envSecretStore = new Map();
  envs.forEach((e, idx) => {
    envSecretStore.set(idx, {
      raw: e.value,
      masked: e.masked_value,
      isSecret: e.is_secret,
    });
  });

  container.innerHTML = `
    <div style="background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.06); border-radius:6px; overflow:hidden;">
      <table class="copy-history-table" style="margin:0;">
        <thead>
          <tr>
            <th style="width:220px;">Variable Name</th>
            <th>Value</th>
            <th style="width:60px; text-align:right;">Action</th>
          </tr>
        </thead>
        <tbody>
          ${envs.map((e, idx) => {
            const isSec = e.is_secret;
            const secBadge = isSec ? '<span style="font-size:8.5px; padding:1px 4px; border-radius:3px; background:rgba(239, 68, 68, 0.15); color:#f87171; margin-left:4px;">SECRET</span>' : '';
            return `
              <tr>
                <td style="font-family:var(--font-mono, monospace); font-weight:700; color:#fff;">
                  ${escapeHtml(e.key)} ${secBadge}
                </td>
                <td style="font-family:var(--font-mono, monospace); font-size:10.5px; word-break:break-all;">
                  <span id="env-val-${idx}">${escapeHtml(e.masked_value)}</span>
                </td>
                <td style="text-align:right;">
                  ${isSec ? `<button class="btn-toggle-secret btn-pill-toggle" data-idx="${idx}" style="font-size:9.5px; padding:1px 5px;" title="Toggle show/hide">👁️</button>` : ''}
                  <button class="btn-copy-env btn-pill-toggle" data-idx="${idx}" style="font-size:9.5px; padding:1px 5px;" title="Copy value">📋</button>
                </td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;

  // Wire secret reveal toggle
  container.querySelectorAll('.btn-toggle-secret').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx, 10);
      const entry = envSecretStore.get(idx);
      const span = document.getElementById(`env-val-${idx}`);
      if (!span || !entry) return;
      const isCurrentlyMasked = span.textContent === entry.masked;
      span.textContent = isCurrentlyMasked ? entry.raw : entry.masked;
      btn.textContent = isCurrentlyMasked ? '🔒' : '👁️';
    });
  });

  // Wire copy buttons
  container.querySelectorAll('.btn-copy-env').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx, 10);
      const entry = envSecretStore.get(idx);
      const val = entry ? entry.raw : '';
      if (!val) return;
      navigator.clipboard.writeText(val).then(() => {
        showToast('Value copied to clipboard.', 'success');
      });
    });
  });
}

async function loadContainerCompose(cid) {
  const codeEl = document.getElementById('ci-compose-code');
  const badgeEl = document.getElementById('ci-compose-source-badge');
  if (codeEl) codeEl.textContent = 'Generating Docker Compose definition...';

  try {
    const data = await api.get(`/api/docker/containers/${encodeURIComponent(cid)}/compose`);
    _activeComposeData = data;

    if (badgeEl) {
      if (data.source === 'disk') {
        badgeEl.textContent = '📄 Read from Disk';
        badgeEl.style.color = '#38bdf8';
        badgeEl.style.background = 'rgba(56, 189, 248, 0.15)';
      } else {
        badgeEl.textContent = '✨ Synthesized Compose Spec v3.8';
        badgeEl.style.color = 'var(--ok2)';
        badgeEl.style.background = 'rgba(37, 194, 160, 0.15)';
      }
    }

    renderComposeCode();
  } catch (err) {
    if (codeEl) codeEl.textContent = `# Error generating compose: ${err.message}`;
  }
}

function renderComposeCode() {
  const codeEl = document.getElementById('ci-compose-code');
  const maskToggle = document.getElementById('ci-compose-mask-toggle');
  if (!codeEl || !_activeComposeData) return;

  const mask = maskToggle ? maskToggle.checked : true;
  codeEl.textContent = mask ? _activeComposeData.masked_yaml : _activeComposeData.compose_yaml;
}

async function loadContainerLogs(cid) {
  const terminal = document.getElementById('ci-logs-terminal');
  const tailSelect = document.getElementById('ci-logs-tail-select');
  const tail = tailSelect ? tailSelect.value : 200;

  if (terminal) terminal.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px;">Fetching logs...</div>';

  try {
    const res = await api.get(`/api/docker/containers/${encodeURIComponent(cid)}/logs?tail=${tail}`);
    _activeLogLines = res.lines || [];
    renderLogsOutput();
  } catch (err) {
    if (terminal) terminal.innerHTML = `<div style="color:var(--crit); text-align:center; padding:20px;">Failed to read logs: ${escapeHtml(err.message)}</div>`;
  }
}

function renderLogsOutput() {
  const terminal = document.getElementById('ci-logs-terminal');
  if (!terminal) return;

  const lines = _activeLogLines.filter((l) => {
    if (!_activeLogFilter) return true;
    return (l.msg || '').toLowerCase().includes(_activeLogFilter) || (l.ts || '').toLowerCase().includes(_activeLogFilter);
  });

  if (lines.length === 0) {
    terminal.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px;">No logs recorded for this period.</div>';
    return;
  }

  terminal.innerHTML = lines
    .map((l) => {
      const tsHtml = l.ts ? `<span style="color:#00f0ff; opacity:0.6; margin-right:6px;">${escapeHtml(l.ts.slice(11, 19))}</span>` : '';
      const color = l.stream === 'stderr' ? '#f87171' : '#e2e8f0';
      return `<div style="white-space:pre-wrap; word-break:break-all; color:${color}; margin-bottom:2px;">${tsHtml}${escapeHtml(l.msg)}</div>`;
    })
    .join('');

  if (_autoScrollLogs) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

export function openContainerDeleteModal(cid, cname, imageRef = '', onDeleted = null) {
  let modal = document.getElementById('container-delete-modal-overlay');
  if (!modal) {
    const html = `
      <div id="container-delete-modal-overlay" class="smart-modal-backdrop" style="display:none; z-index:10020;">
        <div id="container-delete-modal-window" class="smart-modal-window" style="width:480px; max-width:92vw; display:flex; flex-direction:column;">
          <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:18px;">⚠️</span>
              <span style="font-weight:700; color:var(--crit, #ff6b6b); font-size:13px;">Destroy Container</span>
            </div>
            <button class="win-btn close-btn" id="cdm-close-btn" title="Close" aria-label="Close"></button>
          </div>
          <div style="padding:16px; display:flex; flex-direction:column; gap:14px;">
            <div style="font-size:12px; line-height:1.5; color:#cbd5e1;">
              Are you sure you want to permanently delete container <strong id="cdm-cname" style="color:#fff;"></strong> (<code id="cdm-cid" style="font-family:var(--font-mono, monospace); font-size:10.5px; color:var(--accent-cyan, #00f0ff);"></code>)?
            </div>
            <div style="background:rgba(255,107,107,0.08); border:1px solid rgba(255,107,107,0.25); border-radius:6px; padding:10px 12px; font-size:11px; color:#fca5a5; line-height:1.4;">
              ⚠️ <strong>Warning:</strong> This container will be stopped and removed from the host Docker daemon. Any unsaved data inside the container layer will be lost.
            </div>
            <div style="display:flex; flex-direction:column; gap:8px; background:rgba(0,0,0,0.2); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.06);">
              <label style="display:flex; align-items:center; gap:8px; font-size:11px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="cdm-force" checked style="cursor:pointer;">
                <span>Force stop container if currently running</span>
              </label>
              <label style="display:flex; align-items:center; gap:8px; font-size:11px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="cdm-volumes" checked style="cursor:pointer;">
                <span>Delete associated anonymous volumes (reclaim storage)</span>
              </label>
              <label style="display:flex; align-items:center; gap:8px; font-size:11px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="cdm-image" style="cursor:pointer;">
                <span>Also delete container image <code id="cdm-image-tag" style="color:var(--muted); font-size:10px;"></code></span>
              </label>
            </div>
          </div>
          <div style="padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="cdm-cancel-btn">Cancel</button>
            <button class="btn-pill-toggle" id="cdm-confirm-btn" style="background:var(--crit, #ff6b6b); color:#fff; border:none; padding:6px 16px; font-weight:700; cursor:pointer;">
              💥 Destroy Container
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('container-delete-modal-overlay');

    const closeModal = () => {
      modal.classList.remove('open');
      modal.style.display = 'none';
    };
    document.getElementById('cdm-close-btn').onclick = (e) => {
      e.preventDefault();
      closeModal();
    };
    document.getElementById('cdm-cancel-btn').onclick = (e) => {
      e.preventDefault();
      closeModal();
    };
    modal.onclick = (e) => {
      if (e.target === modal) closeModal();
    };
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
    });
  }

  document.getElementById('cdm-cname').textContent = cname || cid;
  document.getElementById('cdm-cid').textContent = (cid || '').slice(0, 12);
  const imgLabel = document.getElementById('cdm-image-tag');
  if (imgLabel) imgLabel.textContent = imageRef ? `(${imageRef})` : '';

  modal.classList.add('open');
  modal.style.display = 'flex';

  const confirmBtn = document.getElementById('cdm-confirm-btn');
  confirmBtn.disabled = false;
  confirmBtn.textContent = '💥 Destroy Container';

  confirmBtn.onclick = async () => {
    const force = document.getElementById('cdm-force').checked;
    const removeVolumes = document.getElementById('cdm-volumes').checked;
    const removeImage = document.getElementById('cdm-image').checked;

    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Destroying...';

    try {
      const url = `/api/docker/containers/${encodeURIComponent(cid)}?force=${force}&remove_volumes=${removeVolumes}&remove_image=${removeImage}`;
      await api.delete(url);
      showToast(`Container "${cname}" permanently destroyed.`, 'success');
      modal.classList.remove('open');
      modal.style.display = 'none';

      if (typeof onDeleted === 'function') {
        onDeleted();
      }
    } catch (err) {
      showToast(`Failed to destroy container: ${err.message}`, 'error');
      confirmBtn.disabled = false;
      confirmBtn.textContent = '💥 Destroy Container';
    }
  };
}

async function renderContainerEditTab(cid) {
  const hostEl = document.getElementById('cie-form-host');
  if (!hostEl) return;

  if (!_activeDetails || (_activeDetails.overview && _activeDetails.overview.id !== cid && _activeDetails.overview.full_id !== cid)) {
    hostEl.innerHTML = '<div style="text-align:center; padding:30px; color:var(--muted);">Loading container configuration...</div>';
    try {
      _activeDetails = await api.get(`/api/docker/containers/${encodeURIComponent(cid)}/details`);
    } catch (e) {
      hostEl.innerHTML = `<div style="color:var(--crit); padding:20px;">Failed to load container details: ${escapeHtml(e.message)}</div>`;
      return;
    }
  }

  const details = _activeDetails;
  const ov = details.overview || {};
  const currentName = ov.name || _activeCname || '';
  const currentImage = ov.image || '';
  const currentNetwork = ov.network_mode || 'bridge';
  const currentRestart = ov.restart_policy || 'unless-stopped';
  const isToolkit = currentName === 'zettnas-toolkit' || currentName === 'zettnas' || (cid && window.location.hostname && cid.startsWith(window.location.hostname));

  const portsList = (details.ports || []).map((p) => ({
    container_port: p.private_port,
    host_port: p.public_port || '',
    proto: (p.type || 'tcp').toLowerCase(),
    host_ip: p.ip || '0.0.0.0',
  }));

  const mountsList = (details.mounts || []).map((m) => ({
    source: m.source || '',
    destination: m.destination || '',
    mode: m.mode || (m.rw ? 'rw' : 'ro') || 'rw',
  }));

  const envList = (details.env || []).map((e) => ({
    key: e.key || '',
    value: e.value != null ? String(e.value) : '',
    sensitive: Boolean(e.sensitive),
  }));

  hostEl.innerHTML = `
    <div class="cie-form-wrap" style="padding:4px 2px;">
      <!-- Guidance Notice -->
      <div style="background:rgba(14,165,233,0.08); border:1px solid rgba(14,165,233,0.25); border-radius:6px; padding:10px 12px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div style="font-weight:700; color:#38bdf8; font-size:12px;">✏️ Container Configuration Editor</div>
          <div style="font-size:10.5px; color:var(--muted); margin-top:2px;">
            Zero-downtime atomic clone-and-recreate with automated rollback. All settings are validated before touching the container.
          </div>
        </div>
        ${isToolkit ? `<span class="ci-badge" style="background:rgba(239,68,68,0.15); color:#fca5a5; font-size:9.5px; padding:2px 8px; border-radius:4px; font-weight:700;">SELF-PROTECTED</span>` : ''}
      </div>

      ${isToolkit ? `
        <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); border-radius:6px; padding:12px; margin-bottom:14px; color:#fca5a5; font-size:11px;">
          ⚠️ The active ZettNAS Toolkit container cannot be recreated from within the web interface. Please modify its configuration in Docker Compose or your host template to avoid severing active agent connections.
        </div>
      ` : ''}

      <!-- Section 1: General Settings -->
      <div class="ci-metric-card" style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); padding:12px; border-radius:8px; margin-bottom:14px;">
        <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:10px;">General Settings</div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px;">
          <div>
            <label style="font-size:10px; color:var(--muted); display:block; margin-bottom:4px; font-weight:600;">CONTAINER NAME</label>
            <input type="text" id="cie-input-name" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:5px 8px;" value="${escapeHtml(currentName)}" ${isToolkit ? 'disabled' : ''}>
          </div>
          <div>
            <label style="font-size:10px; color:var(--muted); display:block; margin-bottom:4px; font-weight:600;">IMAGE REPO & TAG</label>
            <input type="text" id="cie-input-image" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:5px 8px;" value="${escapeHtml(currentImage)}" ${isToolkit ? 'disabled' : ''}>
          </div>
          <div>
            <label style="font-size:10px; color:var(--muted); display:block; margin-bottom:4px; font-weight:600;">NETWORK MODE</label>
            <select id="cie-select-network" class="tz-select-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:4px 6px;" ${isToolkit ? 'disabled' : ''}>
              <option value="bridge" ${currentNetwork === 'bridge' ? 'selected' : ''}>bridge (Default)</option>
              <option value="host" ${currentNetwork === 'host' ? 'selected' : ''}>host (Direct Host Network)</option>
              <option value="none" ${currentNetwork === 'none' ? 'selected' : ''}>none (Isolated)</option>
              ${currentNetwork && !['bridge', 'host', 'none'].includes(currentNetwork) ? `<option value="${escapeHtml(currentNetwork)}" selected>${escapeHtml(currentNetwork)} (Custom)</option>` : ''}
            </select>
          </div>
          <div>
            <label style="font-size:10px; color:var(--muted); display:block; margin-bottom:4px; font-weight:600;">RESTART POLICY</label>
            <select id="cie-select-restart" class="tz-select-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:4px 6px;" ${isToolkit ? 'disabled' : ''}>
              <option value="unless-stopped" ${currentRestart === 'unless-stopped' ? 'selected' : ''}>unless-stopped (Recommended)</option>
              <option value="always" ${currentRestart === 'always' ? 'selected' : ''}>always</option>
              <option value="on-failure" ${currentRestart === 'on-failure' ? 'selected' : ''}>on-failure</option>
              <option value="no" ${currentRestart === 'no' ? 'selected' : ''}>no</option>
            </select>
          </div>
        </div>
        <div style="margin-top:10px;">
          <label style="display:flex; align-items:center; gap:6px; font-size:10.5px; color:#cbd5e1; cursor:pointer;">
            <input type="checkbox" id="cie-cb-pull" style="cursor:pointer;" ${isToolkit ? 'disabled' : ''}>
            <span>Pull latest image layers from registry before recreate</span>
          </label>
        </div>
      </div>

      <!-- Section 2: Port Mappings -->
      <div class="ci-metric-card" style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); padding:12px; border-radius:8px; margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px;">Port Bindings</div>
          <button class="btn-pill-toggle" id="cie-btn-add-port" style="font-size:10px; padding:2px 8px;" ${isToolkit ? 'disabled' : ''}>+ Add Port</button>
        </div>
        <div id="cie-ports-container" style="display:flex; flex-direction:column; gap:6px;"></div>
      </div>

      <!-- Section 3: Volume Mounts & Paths -->
      <div class="ci-metric-card" style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); padding:12px; border-radius:8px; margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px;">Storage Mounts & Paths (Binds)</div>
          <button class="btn-pill-toggle" id="cie-btn-add-mount" style="font-size:10px; padding:2px 8px;" ${isToolkit ? 'disabled' : ''}>+ Add Mount</button>
        </div>
        <div id="cie-mounts-container" style="display:flex; flex-direction:column; gap:6px;"></div>
      </div>

      <!-- Section 4: Environment Variables -->
      <div class="ci-metric-card" style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); padding:12px; border-radius:8px; margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:6px;">
          <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px;">Environment Variables</div>
          <div style="display:flex; gap:6px; align-items:center;">
            <input type="text" id="cie-env-filter" placeholder="Filter variables..." class="tz-text-input" style="font-size:10px; padding:2px 6px; width:130px;">
            <button class="btn-pill-toggle" id="cie-btn-add-env" style="font-size:10px; padding:2px 8px;" ${isToolkit ? 'disabled' : ''}>+ Add Variable</button>
          </div>
        </div>
        <div id="cie-env-container" style="display:flex; flex-direction:column; gap:6px; max-height:280px; overflow-y:auto;"></div>
      </div>

      <!-- Footer Actions -->
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.08);">
        <label style="display:flex; align-items:center; gap:6px; font-size:10.5px; color:var(--muted); cursor:pointer;">
          <input type="checkbox" id="cie-cb-backup" style="cursor:pointer;" ${isToolkit ? 'disabled' : ''}>
          <span>Keep backup container (retains previous state as {name}.backup)</span>
        </label>
        <div style="display:flex; gap:8px;">
          <button class="btn-pill-toggle" id="cie-btn-cancel">Cancel</button>
          <button class="btn-pill-toggle" id="cie-btn-save" style="font-weight:700; background:var(--brand, #0ea5e9); color:#fff; border:none; padding:6px 16px;" ${isToolkit ? 'disabled' : ''}>
            💾 Save & Recreate Container
          </button>
        </div>
      </div>
      <div id="cie-status-msg" style="display:none; margin-top:10px; padding:8px 12px; border-radius:6px; font-size:11px;"></div>
    </div>
  `;

  // Render initial rows
  const portsBox = document.getElementById('cie-ports-container');
  const mountsBox = document.getElementById('cie-mounts-container');
  const envBox = document.getElementById('cie-env-container');

  function addPortRow(p = {}) {
    const row = document.createElement('div');
    row.className = 'cie-port-row';
    row.style.cssText = 'display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.03); padding:6px 10px; border-radius:6px;';
    row.innerHTML = `
      <span style="font-size:10px; color:var(--muted); width:65px;">Container:</span>
      <input type="number" class="tz-text-input cie-cp-input" placeholder="80" value="${p.container_port || ''}" style="width:75px; font-size:11px; padding:3px 6px;">
      <span style="font-size:10px; color:var(--muted);">/</span>
      <select class="tz-select-input cie-proto-input" style="font-size:11px; padding:2px 4px;">
        <option value="tcp" ${p.proto === 'udp' ? '' : 'selected'}>TCP</option>
        <option value="udp" ${p.proto === 'udp' ? 'selected' : ''}>UDP</option>
      </select>
      <span style="color:var(--muted);">➔</span>
      <span style="font-size:10px; color:var(--muted);">Host:</span>
      <input type="number" class="tz-text-input cie-hp-input" placeholder="8080" value="${p.host_port || ''}" style="width:75px; font-size:11px; padding:3px 6px;">
      <input type="text" class="tz-text-input cie-ip-input" placeholder="0.0.0.0" value="${p.host_ip || '0.0.0.0'}" style="width:75px; font-size:10px; padding:3px 6px;" title="Host IP">
      <button class="btn-pill-toggle cie-row-del" title="Remove" style="color:#fca5a5; padding:2px 6px;">🗑️</button>
    `;
    row.querySelector('.cie-row-del').onclick = () => row.remove();
    portsBox.appendChild(row);
  }

  function addMountRow(m = {}) {
    const row = document.createElement('div');
    row.className = 'cie-mount-row';
    row.style.cssText = 'display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.03); padding:6px 10px; border-radius:6px;';
    row.innerHTML = `
      <span style="font-size:10px; color:var(--muted); width:65px;">Host Path:</span>
      <input type="text" class="tz-text-input cie-src-input" placeholder="/mnt/user/appdata/app" value="${escapeHtml(m.source || '')}" style="flex:1; font-size:11px; padding:3px 6px; font-family:var(--font-mono, monospace);">
      <span style="color:var(--muted);">➔</span>
      <span style="font-size:10px; color:var(--muted); width:65px;">Container:</span>
      <input type="text" class="tz-text-input cie-dst-input" placeholder="/config" value="${escapeHtml(m.destination || '')}" style="flex:1; font-size:11px; padding:3px 6px; font-family:var(--font-mono, monospace);">
      <select class="tz-select-input cie-mode-input" style="font-size:11px; padding:2px 4px;">
        <option value="rw" ${m.mode === 'ro' ? '' : 'selected'}>rw</option>
        <option value="ro" ${m.mode === 'ro' ? 'selected' : ''}>ro</option>
      </select>
      <button class="btn-pill-toggle cie-row-del" title="Remove" style="color:#fca5a5; padding:2px 6px;">🗑️</button>
    `;
    row.querySelector('.cie-row-del').onclick = () => row.remove();
    mountsBox.appendChild(row);
  }

  function addEnvRow(e = {}) {
    const row = document.createElement('div');
    row.className = 'cie-env-row';
    row.style.cssText = 'display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.03); padding:4px 8px; border-radius:6px;';
    row.innerHTML = `
      <input type="text" class="tz-text-input cie-key-input" placeholder="KEY" value="${escapeHtml(e.key || '')}" style="width:180px; font-size:11px; padding:3px 6px; font-family:var(--font-mono, monospace); font-weight:700;">
      <span style="color:var(--muted);">=</span>
      <input type="text" class="tz-text-input cie-val-input" placeholder="value" value="${escapeHtml(e.value || '')}" style="flex:1; font-size:11px; padding:3px 6px; font-family:var(--font-mono, monospace);">
      <button class="btn-pill-toggle cie-row-del" title="Remove" style="color:#fca5a5; padding:2px 6px;">🗑️</button>
    `;
    row.querySelector('.cie-row-del').onclick = () => row.remove();
    envBox.appendChild(row);
  }

  portsList.forEach(addPortRow);
  mountsList.forEach(addMountRow);
  envList.forEach(addEnvRow);

  // Wire add buttons
  document.getElementById('cie-btn-add-port').onclick = () => addPortRow();
  document.getElementById('cie-btn-add-mount').onclick = () => addMountRow();
  document.getElementById('cie-btn-add-env').onclick = () => addEnvRow();

  // Wire env search
  document.getElementById('cie-env-filter').oninput = (ev) => {
    const q = (ev.target.value || '').toLowerCase();
    envBox.querySelectorAll('.cie-env-row').forEach((r) => {
      const keyVal = (r.querySelector('.cie-key-input').value || '').toLowerCase();
      r.style.display = keyVal.includes(q) ? 'flex' : 'none';
    });
  };

  // Wire Cancel
  document.getElementById('cie-btn-cancel').onclick = () => {
    switchContainerTab('overview');
  };

  // Wire Save
  const saveBtn = document.getElementById('cie-btn-save');
  const statusMsg = document.getElementById('cie-status-msg');

  saveBtn.onclick = async () => {
    const name = document.getElementById('cie-input-name').value.trim();
    const image = document.getElementById('cie-input-image').value.trim();
    const network_mode = document.getElementById('cie-select-network').value;
    const restart_policy = document.getElementById('cie-select-restart').value;
    const pull_image = document.getElementById('cie-cb-pull').checked;
    const keep_backup = document.getElementById('cie-cb-backup').checked;

    if (!name || !image) {
      showToast('Container name and image cannot be empty.', 'warn');
      return;
    }

    if (!confirm(`Save changes and recreate container '${name}'? The container will be atomically restarted.`)) {
      return;
    }

    // Collect port bindings
    const portBindings = [];
    portsBox.querySelectorAll('.cie-port-row').forEach((r) => {
      const cp = parseInt(r.querySelector('.cie-cp-input').value, 10);
      const hp = parseInt(r.querySelector('.cie-hp-input').value, 10);
      const proto = r.querySelector('.cie-proto-input').value;
      const host_ip = r.querySelector('.cie-ip-input').value.trim() || '0.0.0.0';
      if (cp && cp > 0) {
        portBindings.push({
          container_port: cp,
          host_port: hp && hp > 0 ? hp : null,
          proto,
          host_ip,
        });
      }
    });

    // Collect mounts
    const binds = [];
    mountsBox.querySelectorAll('.cie-mount-row').forEach((r) => {
      const src = r.querySelector('.cie-src-input').value.trim();
      const dst = r.querySelector('.cie-dst-input').value.trim();
      const mode = r.querySelector('.cie-mode-input').value;
      if (src && dst) {
        binds.push(`${src}:${dst}:${mode}`);
      }
    });

    // Collect env
    const envVars = [];
    envBox.querySelectorAll('.cie-env-row').forEach((r) => {
      const k = r.querySelector('.cie-key-input').value.trim();
      const v = r.querySelector('.cie-val-input').value;
      if (k) {
        envVars.push(`${k}=${v}`);
      }
    });

    saveBtn.disabled = true;
    saveBtn.textContent = '⏳ Recreating Container...';
    statusMsg.style.display = 'block';
    statusMsg.style.background = 'rgba(14,165,233,0.15)';
    statusMsg.style.color = '#38bdf8';
    statusMsg.textContent = 'Validating configuration, creating backup, and recreating container...';

    try {
      const res = await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/recreate`, {
        name,
        image,
        network_mode,
        restart_policy,
        pull_image,
        keep_backup,
        port_bindings: portBindings,
        binds,
        env: envVars,
      });

      statusMsg.style.background = 'rgba(37,194,160,0.15)';
      statusMsg.style.color = 'var(--ok2, #25c2a0)';
      statusMsg.textContent = `✓ ${res.message || 'Container recreated successfully!'}`;
      showToast(`Container "${res.target_name || name}" successfully recreated!`, 'success');

      // Refresh details
      _activeCid = res.new_id || name;
      _activeCname = res.target_name || name;
      const titleName = document.getElementById('ci-header-title');
      const titleId = document.getElementById('ci-header-id');
      if (titleName) titleName.textContent = _activeCname;
      if (titleId) titleId.textContent = _activeCid.slice(0, 12);

      await loadContainerDetails(_activeCid);
      setTimeout(() => {
        switchContainerTab('overview');
      }, 1200);

      // Notify parent list to refresh
      ZettEventBus.emit('docker:containers:refresh');
    } catch (err) {
      statusMsg.style.background = 'rgba(239,68,68,0.15)';
      statusMsg.style.color = '#fca5a5';
      statusMsg.textContent = `Error: ${err.message}`;
      showToast(`Recreation failed: ${err.message}`, 'error');
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = '💾 Save & Recreate Container';
    }
  };
}

export function _resetContainerModalForTesting() {
  _activeCid = null;
  _activeCname = null;
  _activeComposeData = null;
  _activeLogLines = [];
  _activeLogFilter = '';
  _autoScrollLogs = true;
  _activeTab = 'overview';
  if (_unbindFocusTrap) {
    _unbindFocusTrap();
    _unbindFocusTrap = null;
  }
  const overlay = document.getElementById('container-inspector-overlay');
  if (overlay) overlay.remove();
}

if (typeof window !== 'undefined') {
  window.openContainerInspector = openContainerInspector;
}

