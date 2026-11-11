/**
 * Kiboto - Container Inspector & Docker Compose Viewer Modal
 * Provides tabbed inspection: Overview Telemetry, Ports & Web Access,
 * Mounts (with File Explorer deep-link), Masked Environment Variables,
 * Dynamic Docker Compose Synthesizer, and Live Log Console.
 */

import { api, auth } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';
import { escapeHtml, trapFocus, copyText } from '../utils.js';
import '../styles/containers-lazy.css'; // the inspector's own sheet loads with this code (NUX-15)
import { t } from '../i18n.js';
import { bringToFront, makeDraggable, DockManager } from './dock.js';
import { ZettEventBus } from '../event-bus.js';
import { openStackModal } from './stack-modal.js';
import { createTerminalView } from './terminal-view.js';

import { formatDateTime, formatFixed, formatTime } from '../format.js';
import { setIconLabel } from '../ui/primitives.js';

// An icon next to translated words: screen readers skip it and the words stay plain (UX-35)
const ico = (e) => `<span aria-hidden="true">${e}</span>`;
let _activeCid = null;
let _activeCname = null;
let _activeComposeData = null;
let _activeLogLines = [];
let _activeLogFilter = '';
let _autoScrollLogs = true;
let _logEventSource = null;
let _unbindFocusTrap = null;
let _activeTab = 'overview';
let _termHistory = [];
let _termHistoryIdx = -1;
let _activeDetails = null;
let _activeTermWs = null;
let _termView = null;
let _termViewCid = null;
const TERM_READY_MSG = '# Interactive Container Terminal Ready. Type commands below (e.g. ls -la, uname -a, ps aux)...';

export function initContainerModal() {
  if (document.getElementById('container-inspector-overlay')) return;

  const overlayHtml = `
    <div id="container-inspector-overlay" class="smart-modal-backdrop" style="display:none; z-index:10010;">
      <div id="container-inspector-window" class="smart-modal-window container-inspector-window ci-window" style="display: flex;">
        <!-- Header -->
        <div id="container-inspector-header" class="smart-modal-header ci-head" style="display: flex;">
          <div class="ci-row">
            <span class="ci-fs16">📦</span>
            <span class="ci-fs13-bold-strong" id="ci-header-title">${t('ci.title', 'Container details')}</span>
            <code class="ci-xs-muted-mono" id="ci-header-id"></code>
            <span id="ci-header-state" class="ci-state-pill" style="display:none;"></span>
          </div>
          <div class="os-window-controls ci-row-2">
            <button class="win-btn min-btn" id="ci-min-btn" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
            <button class="win-btn max-btn" id="ci-max-btn" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
            <button class="win-btn close-btn" id="ci-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="ci-nav-tabs ci-row-box">
          <button class="btn-pill-toggle ci-tab-btn active" data-tab="overview">${ico('📊')} ${t('ci.tab_overview', 'Overview')}</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="ports">${ico('🌐')} ${t('ci.tab_ports', 'Ports & web')}</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="mounts">${ico('📁')} ${t('ci.tab_mounts', 'Folders & storage')}</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="env">${ico('🔑')} ${t('ci.tab_env', 'Environment')}</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="compose">${ico('📜')} ${t('ci.tab_compose', 'Docker Compose')}</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="logs">${ico('📄')} ${t('ci.tab_logs', 'Live logs')}</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="terminal">${ico('💻')} ${t('ci.tab_terminal', 'Terminal')}</button>
          <button class="btn-pill-toggle ci-tab-btn" data-tab="edit">${ico('✏️')} ${t('ci.tab_edit', 'Edit container')}</button>
        </div>

        <!-- Tab Content Panes -->
        <div class="ci-panes-container ci-grow">
          <!-- 1. Overview Tab -->
          <div id="ci-pane-overview" class="ci-pane" style="display:block;">
            <div class="ci-muted-center" id="ci-overview-loading">${t('ci.loading', 'Loading details…')}</div>
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
            <div class="ci-row-3">
              <input type="text" id="ci-env-search" placeholder="${t('ui.filter_variables', 'Filter variables...')}" class="tz-text-input ci-xs">
              <span class="ci-xs-muted" id="ci-env-stats"></span>
            </div>
            <div id="ci-env-content"></div>
          </div>

          <!-- 5. Compose Tab -->
          <div id="ci-pane-compose" class="ci-pane" style="display:none;">
            <div class="ci-row-4">
              <div class="ci-row">
                <span id="ci-compose-source-badge" class="ci-badge ci-xs-bold-box"></span>
                <label class="ci-row-xs-muted">
                  <input class="ci-x-2" type="checkbox" id="ci-compose-mask-toggle" checked>
                  ${t('ci.mask', 'Hide secrets')}
                </label>
              </div>
              <div class="ci-row-5">
                <button class="btn-pill-toggle" id="ci-compose-copy-btn">${ico('📋')} ${t('ci.copy_yaml', 'Copy YAML')}</button>
                <button class="btn-pill-toggle" id="ci-compose-download-btn">${ico('⬇️')} ${t('ci.download_yml', 'Download .yml')}</button>
              </div>
            </div>
            <div style="position:relative; background:var(--lt-b-091213ff, #091213); border:1px solid var(--kb-line-10); border-radius:6px; overflow:hidden;">
              <pre class="ci-xs-mono"><code id="ci-compose-code">Generating Docker Compose definition...</code></pre>
            </div>
          </div>

          <!-- 6. Logs Tab -->
          <div id="ci-pane-logs" class="ci-pane" style="display:none;">
            <div class="ci-row-4">
              <div class="ci-row">
                <select id="ci-logs-tail-select" class="tz-select-input ci-xs-2">
                  ${[50, 100, 200, 500, 1000].map((n) => `<option value="${n}" ${n === 200 ? 'selected' : ''}>${t('ci.last_lines', '{n, plural, one {Last # line} other {Last # lines}}', { n })}</option>`).join('')}
                </select>
                <input type="text" id="ci-logs-filter-input" placeholder="${t('ui.filter_output', 'Filter output...')}" class="tz-text-input ci-xs-3">
                <label class="ci-row-xs-muted-2">
                  <input type="checkbox" id="ci-logs-autoscroll" checked> ${t('ci.autoscroll', 'Auto-scroll')}
                </label>
                <label style="display:flex; align-items:center; gap:4px; font-size:var(--kb-fs-xs); color:var(--lt-ink-brand, var(--accent-cyan, #33cdb8)); cursor:pointer; font-weight:600;" title="${t('ui.stream_live_container_logs_continuously', 'Stream live container logs continuously via SSE')}">
                  <input type="checkbox" id="ci-logs-stream-toggle"> <span>${t('ci.follow', 'Follow live')}</span>
                </label>
              </div>
              <div class="ci-row-5">
                <button class="btn-pill-toggle" id="ci-logs-refresh-btn">${ico('🔄')} ${t('common.refresh', 'Refresh')}</button>
                <button class="btn-pill-toggle" id="ci-logs-copy-btn">${ico('📋')} ${t('ci.copy_logs', 'Copy logs')}</button>
              </div>
            </div>
            <div id="ci-logs-terminal" style="background:var(--lt-b-060d0eff, #060d0e); border:1px solid var(--kb-line-10); border-radius:6px; height:340px; overflow-y:auto; padding:10px; font-family:var(--font-mono, monospace); font-size:var(--kb-fs-xs); line-height:1.45; color:var(--kb-text-soft);">
              <div class="ci-logs-note ci-muted-center-2">${t('ci.fetching_logs', 'Fetching logs…')}</div>
            </div>
          </div>

          <!-- 7. Web Terminal Tab -->
          <div id="ci-pane-terminal" class="ci-pane" style="display:none;">
            <div class="ci-row-4">
              <div class="ci-row">
                <span class="ci-badge" style="font-size:var(--kb-fs-xs); background:rgba(34,197,94,0.15); color:var(--lt-t-22c55eff, #22c55e); border:1px solid rgba(34,197,94,0.3); padding:2px 8px; border-radius:4px; font-weight:700;">${t('ci.live_exec', 'LIVE EXEC')}</span>
                <span class="ci-xs-muted">${t('ci.exec_desc', 'Run commands in the container from the browser')}</span>
              </div>
              <div class="ci-row-5">
                <button class="btn-pill-toggle" id="ci-term-clear-btn">${ico('🧹')} ${t('ci.clear', 'Clear')}</button>
              </div>
            </div>
            <div id="ci-term-output" style="background:var(--lt-b-030712ff, #030712); border:1px solid var(--kb-line-12); border-radius:6px 6px 0 0; height:310px; padding:6px 4px 6px 8px; box-sizing:border-box; overflow:hidden;"></div>
            <div class="ci-term-mobile-keybar" style="display:flex; gap:6px; overflow-x:auto; background:var(--lt-b-0c1c1fff, #0c1c1f); border-left:1px solid var(--kb-line-12); border-right:1px solid var(--kb-line-12); padding:5px 8px; scrollbar-width:none;">
              ${['ls -la', 'ps aux', 'df -h'].map((c) => `<button type="button" class="btn-pill-toggle ci-term-key-btn is-small ci-x-3" data-cmd="${c}">${c}</button>`).join('')}
              <button type="button" class="btn-pill-toggle ci-term-key-btn is-small ci-x-3" data-key="ArrowUp">${ico('↑')} ${t('ci.prev', 'Previous')}</button>
              <button type="button" class="btn-pill-toggle ci-term-key-btn is-small ci-x-3" data-key="ArrowDown">${ico('↓')} ${t('common.next', 'Next')}</button>
              <button type="button" class="btn-pill-toggle ci-term-key-btn is-small ci-x-3" data-key="clear">${ico('🧹')} ${t('ci.clear', 'Clear')}</button>
            </div>
            <div style="display:flex; background:var(--lt-b-0e1c1eff, #0e1c1e); border:1px solid var(--kb-line-12); border-top:none; border-radius:0 0 6px 6px; padding:6px 10px; gap:8px; align-items:center;">
              <span style="color:var(--lt-t-10b981ff, #10b981); font-family:var(--font-mono, monospace); font-weight:bold; font-size:var(--kb-fs-xs);">$</span>
              <input type="text" id="ci-term-input" placeholder="${t('ui.type_a_command_and_press', 'Type a command and press Enter...')}" style="flex:1; background:transparent; border:none; outline:none; color:var(--lt-t-f5f9f9ff, #f5f9f9); font-family:var(--font-mono, monospace); font-size:var(--kb-fs-xs);" autocomplete="off" spellcheck="false">
              <button class="btn-pill-toggle is-small" id="ci-term-send-btn">${t('ci.run', 'Run')}</button>
            </div>
          </div>

          <!-- 8. Edit Container Tab -->
          <div id="ci-pane-edit" class="ci-pane" style="display:none;">
            <div id="cie-form-host">
              <div class="ci-muted-center">${t('ci.loading_config', 'Loading the container settings…')}</div>
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
    DockManager.register('container-inspector', overlay, '#i-chip', t('ci.title', 'Container details'), true);
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
        copyText(codeEl.textContent).then(() => {
          showToast(t('toast.docker_compose_yaml_copied_to_clipboard', 'Docker Compose YAML copied to clipboard!'), 'success');
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
      showToast(t('toast.downloaded_compose_yml', 'Downloaded {activeCname}-compose.yml', { activeCname: _activeCname }), 'info');
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
      copyText(text).then(() => {
        showToast(t('toast.container_logs_copied_to_clipboard', 'Container logs copied to clipboard.'), 'success');
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

  const streamToggle = document.getElementById('ci-logs-stream-toggle');
  if (streamToggle) {
    streamToggle.addEventListener('change', (e) => {
      if (e.target.checked) {
        if (_activeCid) startLogStream(_activeCid);
      } else {
        stopLogStream();
        if (_activeCid) loadContainerLogs(_activeCid);
      }
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

  overlay.querySelectorAll('.ci-term-key-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cmd = btn.dataset.cmd;
      const key = btn.dataset.key;
      if (cmd && termInput) {
        termInput.value = cmd;
        executeTerminalCmd();
      } else if (key === 'ArrowUp' && termInput) {
        if (_termHistory.length && _termHistoryIdx > 0) {
          _termHistoryIdx--;
          termInput.value = _termHistory[_termHistoryIdx];
        }
        termInput.focus();
      } else if (key === 'ArrowDown' && termInput) {
        if (_termHistoryIdx < _termHistory.length - 1) {
          _termHistoryIdx++;
          termInput.value = _termHistory[_termHistoryIdx];
        } else {
          _termHistoryIdx = _termHistory.length;
          termInput.value = '';
        }
        termInput.focus();
      } else if (key === 'clear') {
        clearTerminal();
      }
    });
  });
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
  if (_activeTermWs) {
    try { _activeTermWs.close(); } catch (_) {}
    _activeTermWs = null;
  }
  stopLogStream();
  _activeCid = null;
  _activeCname = null;
  _activeComposeData = null;
}

function sendTermResize(cols, rows) {
  if (_activeTermWs && _activeTermWs.readyState === WebSocket.OPEN) {
    try {
      _activeTermWs.send(JSON.stringify({ type: 'resize', cols, rows }));
    } catch (_) {}
  }
}

function ensureContainerTermView() {
  const host = document.getElementById('ci-term-output');
  if (!host) return null;
  const intact = host.querySelector('.zt-terminal-fallback, .zt-terminal-xterm');
  if (_termView && _termView.host === host && intact) return _termView;
  if (_termView) _termView.dispose();
  _termView = createTerminalView(host, {
    // Keystrokes go to the shell as binary frames, so they can never be
    // mistaken for a JSON control message on the server.
    onData: (d) => {
      if (_activeTermWs && _activeTermWs.readyState === WebSocket.OPEN) {
        _activeTermWs.send(new TextEncoder().encode(d));
      }
    },
    onResize: (cols, rows) => sendTermResize(cols, rows),
  });
  _termView.writeln(`\x1b[90m${TERM_READY_MSG}\x1b[0m`);
  return _termView;
}

export function connectContainerTerminalWs(cid) {
  if (typeof WebSocket === 'undefined') return;
  if (_activeTermWs) {
    try { _activeTermWs.close(); } catch (_) {}
    _activeTermWs = null;
  }

  const view = ensureContainerTermView();
  if (!view || !cid) return;
  if (_termViewCid !== cid) {
    view.clear();
    view.writeln(`\x1b[90m${TERM_READY_MSG}\x1b[0m`);
    _termViewCid = cid;
  }

  const proto = (typeof window !== 'undefined' && window.location.protocol === 'https:') ? 'wss:' : 'ws:';
  const host = typeof window !== 'undefined' ? window.location.host : '127.0.0.1:8082';
  const token = auth.getToken() || '';
  const wsUrl = `${proto}//${host}/api/docker/containers/${encodeURIComponent(cid)}/terminal/ws`;

  try {
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    _activeTermWs = ws;

    ws.onopen = () => {
      const { cols, rows } = view.size();
      sendTermResize(cols, rows);
    };

    ws.onmessage = (event) => {
      view.write(typeof event.data === 'string' ? event.data : new Uint8Array(event.data));
    };

    ws.onerror = (err) => {
      console.warn('[ContainerTerminal] WebSocket connection error:', err);
    };

    ws.onclose = () => {
      if (_activeTermWs === ws) {
        _activeTermWs = null;
        view.writeln('\r\n\x1b[90m[terminal session closed]\x1b[0m');
      }
    };
  } catch (e) {
    console.warn('[ContainerTerminal] Failed to open WebSocket:', e);
  }
}

export async function switchContainerTab(tabTarget) {
  const overlay = document.getElementById('container-inspector-overlay');
  if (!overlay) return;
  overlay.querySelectorAll('.ci-tab-btn').forEach((b) => {
    const isActive = b.dataset.tab === tabTarget;
    b.classList.toggle('active', isActive);
    if (isActive && typeof b.scrollIntoView === 'function') {
      try { b.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
    }
  });
  _activeTab = tabTarget;
  overlay.querySelectorAll('.ci-pane').forEach((p) => {
    p.style.display = p.id === `ci-pane-${tabTarget}` ? 'block' : 'none';
  });

  if (tabTarget !== 'logs') {
    stopLogStream();
  }

  if (tabTarget === 'compose' && _activeCid) {
    await loadContainerCompose(_activeCid);
  } else if (tabTarget === 'logs' && _activeCid) {
    await loadContainerLogs(_activeCid);
  } else if (tabTarget === 'terminal') {
    if (_activeCid) connectContainerTerminalWs(_activeCid);
    const input = document.getElementById('ci-term-input');
    if (input) setTimeout(() => input.focus(), 60);
  } else if (tabTarget === 'edit' && _activeCid) {
    await renderContainerEditTab(_activeCid);
  }
}

export async function executeTerminalCmd() {
  const input = document.getElementById('ci-term-input');
  const view = ensureContainerTermView();
  if (!input || !view || !_activeCid) return;

  const cmd = input.value.trim();
  if (!cmd) return;

  _termHistory.push(cmd);
  _termHistoryIdx = _termHistory.length;
  input.value = '';

  if (_activeTermWs && _activeTermWs.readyState === WebSocket.OPEN) {
    _activeTermWs.send(new TextEncoder().encode(cmd + '\r'));
    return;
  }

  // No live session: run once through the exec API and print the result.
  const timestamp = formatTime(new Date(), { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  view.writeln(`\x1b[90m[${timestamp}]\x1b[0m \x1b[32;1m$\x1b[0m ${cmd}`);
  try {
    const res = await api.post(`/api/docker/containers/${_activeCid}/exec`, { cmd });
    view.write(String(res.output || '(No output)').replace(/\r?\n/g, '\r\n'));
    view.write('\r\n');
  } catch (err) {
    view.writeln(`\x1b[31mError: ${err.message || err}\x1b[0m`);
  }
}

export function clearTerminal() {
  const view = ensureContainerTermView();
  if (view) {
    view.clear();
    view.writeln(`\x1b[90m${TERM_READY_MSG}\x1b[0m`);
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
    const stateBg = ov.running ? 'rgba(51, 205, 184, 0.15)' : 'rgba(255, 255, 255, 0.08)';

    // Update Header state pill
    const titleState = document.getElementById('ci-header-state');
    if (titleState) {
      titleState.textContent = (ov.state || 'unknown').toUpperCase();
      titleState.style.color = stateColor;
      titleState.style.background = stateBg;
      titleState.style.display = 'inline-block';
      titleState.style.padding = '2px 6px';
      titleState.style.borderRadius = '4px';
      titleState.style.fontSize = 'var(--kb-fs-xs)';
      titleState.style.fontWeight = '700';
    }

    // Hardware badges HTML
    const hwBadges = (details.hardware_badges || []).map(
      (b) => `<span class="docker-hw-badge docker-hw-${escapeHtml(b.id)}">${escapeHtml(b.label)}</span>`
    ).join(' ') || `<span class="ci-xs-muted-2">${t('ci.none', 'None')}</span>`;

    // Stack pill HTML
    const stackHtml = details.stack
      ? `<span class="docker-stack-pill clickable-stack-pill ci-x-2" data-stack="${escapeHtml(details.stack)}" title="${escapeHtml(t('ci.open_stack', 'Open and edit the stack {name}', { name: details.stack }))}">${ico('📁')} ${escapeHtml(details.stack)} <span class="ci-xs-4">${t('ci.edit_stack', '(edit stack)')}</span></span>`
      : `<span class="docker-origin-pill">${escapeHtml(details.managed_by === 'unraid' ? 'Unraid' : t('mgmt.docker_filter_standalone', 'Standalone'))}</span>`;

    const memMb = res.memory_limit ? Math.round(res.memory_limit / (1024 * 1024)) : 0;
    const cpuCores = res.nano_cpus ? (res.nano_cpus / 1e9).toFixed(1) : 0;
    const currentRestart = ov.restart_policy || 'unless-stopped';

    // Overview Tab Content
    contentEl.innerHTML = `
      <div class="ci-grid">
        <div class="ci-metric-card ci-box">
          <div class="ci-xs-bold-muted">${t('ci.state_uptime', 'State & uptime')}</div>
          <div class="ci-fs13-bold-strong-2">${escapeHtml(ov.state || 'unknown')}</div>
          <div class="ci-xs-muted-3">${escapeHtml(t('ci.started', 'Started: {when}', { when: formatDateTime(ov.started_at, undefined, 'N/A') }))}</div>
        </div>
        <div class="ci-metric-card ci-box">
          <div class="ci-xs-bold-muted">${t('ci.network_ip', 'Network IP')}</div>
          <div style="font-size:13px; font-weight:700; color:var(--lt-ink-brand, var(--accent-cyan, #33cdb8)); margin-top:3px;">${escapeHtml(ov.ip_address || 'Host Network')}</div>
          <div class="ci-xs-muted-3">${escapeHtml(t('ci.mode', 'Mode: {mode}', { mode: ov.network_mode || 'bridge' }))}</div>
        </div>
        <div class="ci-metric-card ci-box">
          <div class="ci-xs-bold-muted">${t('ci.hw_stack', 'Hardware & stack')}</div>
          <div class="ci-x-4">${hwBadges}</div>
          <div class="ci-x-4">${stackHtml}</div>
        </div>
      </div>

      <div class="ci-box-2">
        <table class="copy-history-table ci-x-5">
          <tbody>
            <tr><td class="ci-semi-muted">${t('ci.image', 'Image')}</td><td class="ci-strong-mono">${escapeHtml(ov.image)}</td></tr>
            <tr><td class="ci-semi-muted-2">${t('ci.full_id', 'Full container ID')}</td><td class="ci-xs-muted-mono-2">${escapeHtml(ov.full_id)}</td></tr>
            <tr><td class="ci-semi-muted-2">${t('ci.restart_policy', 'Restart policy')}</td><td><code>${escapeHtml(ov.restart_policy)}</code></td></tr>
            <tr><td class="ci-semi-muted-2">${t('ci.platform', 'Platform / OS')}</td><td>${escapeHtml(ov.platform)}</td></tr>
            <tr><td class="ci-semi-muted-2">${t('ci.memory_limit', 'Memory limit')}</td><td>${res.memory_limit ? formatFixed(res.memory_limit / (1024 * 1024), 0) + ' MB' : 'Unlimited'}</td></tr>
            <tr><td class="ci-semi-muted-2">${t('ci.startup_cmd', 'Startup command')}</td><td class="ci-xs-soft-mono">${escapeHtml(ov.command)}</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Live Resource Tuning Section (Phase 3) -->
      <div class="ci-metric-card ci-box-3">
        <div class="ci-row-6">
          <div class="ci-xs-bold-strong">${ico('⚡')} ${t('ci.tuning', 'Live resource limits (no downtime)')}</div>
          <span style="font-size:var(--kb-fs-xs); color:var(--lt-ink-brand, var(--accent-cyan, #33cdb8)); background:var(--lt-b-33cdb81a, rgba(51,205,184,0.1)); padding:2px 6px; border-radius:4px;">${t('ci.hot', 'Applies at once')}</span>
        </div>
        <div class="ci-grid-2">
          <div>
            <label class="ci-xs-muted-4" for="ci-res-mem">${t('ci.mem_mb', 'Memory limit (MB, 0 = no limit)')}</label>
            <input type="number" id="ci-res-mem" class="tz-text-input ci-xs-5" value="${memMb}" min="0" step="64">
          </div>
          <div>
            <label class="ci-xs-muted-4" for="ci-res-cpu">${t('ci.cpu', 'CPU cores (0 = no limit)')}</label>
            <input type="number" id="ci-res-cpu" class="tz-text-input ci-xs-5" value="${cpuCores}" min="0" max="64" step="0.5">
          </div>
          <div>
            <label class="ci-xs-muted-4" for="ci-res-restart">${t('ci.restart_policy', 'Restart policy')}</label>
            <select id="ci-res-restart" class="tz-select-input ci-xs-6">
              <option value="unless-stopped" ${currentRestart === 'unless-stopped' ? 'selected' : ''}>unless-stopped</option>
              <option value="always" ${currentRestart === 'always' ? 'selected' : ''}>always</option>
              <option value="on-failure" ${currentRestart === 'on-failure' ? 'selected' : ''}>on-failure</option>
              <option value="no" ${currentRestart === 'no' ? 'selected' : ''}>no</option>
            </select>
          </div>
          <div>
            <button class="btn-pill-toggle is-block" id="ci-btn-apply-resources" style="color: var(--ok2); border-color: var(--ok2); background: rgba(51,205,184,0.15);">
              ${ico('💾')} ${t('ci.apply', 'Apply')}
            </button>
          </div>
        </div>
      </div>

      <!-- App Backup & Recovery Section -->
      <div class="ci-metric-card" style="background:rgba(249,115,22,0.05); border:1px solid rgba(249,115,22,0.25); padding:12px; border-radius:8px; margin-top:12px;">
        <div class="ci-row-7">
          <div>
            <div style="font-size:var(--kb-fs-xs); font-weight:700; color:var(--lt-t-fb923cff, #fb923c); text-transform:uppercase; letter-spacing:0.5px; display:flex; align-items:center; gap:6px;">
              <span aria-hidden="true">💾</span>
              <span>${t('ci.backup_title', 'App data & settings backup')}</span>
            </div>
            <div class="ci-xs-muted-3">
              ${t('ci.backup_desc', 'Make a portable backup (.tar.gz) of this container’s settings and app data folders now.')}
            </div>
          </div>
          <div>
            <button class="btn-pill-toggle ci-btn-backup-orange" id="ci-btn-backup-action" style="color: var(--lt-t-fb923cff, #fb923c); border-color: rgba(249,115,22,0.4); background: rgba(249,115,22,0.12);">
              ${ico('💾')} ${t('ci.backup_now', 'Back up the app now')}
            </button>
          </div>
        </div>
      </div>

      <!-- Container Management / Danger Zone -->
      <div class="ci-metric-card" style="background:rgba(255,107,107,0.06); border:1px solid rgba(255,107,107,0.22); padding:12px; border-radius:8px; margin-top:12px;">
        <div class="ci-row-7">
          <div>
            <div style="font-size:var(--kb-fs-xs); font-weight:700; color:var(--lt-t-fca5a5ff, #fca5a5); text-transform:uppercase; letter-spacing:0.5px;">${ico('⚠️')} ${t('ci.danger', 'Danger zone')}</div>
            <div class="ci-xs-muted-3">${t('ci.danger_desc', 'Restart this container, or delete it with its volumes and images.')}</div>
          </div>
          <div class="ci-row-5">
            <button class="btn-pill-toggle" id="ci-btn-restart-action">${ico('🔄')} ${t('chassis.restart', 'Restart')}</button>
            <button class="btn-pill-toggle is-danger ci-strong" id="ci-btn-destroy-action">${ico('🗑️')} ${t('ci.destroy', 'Delete container')}</button>
          </div>
        </div>
      </div>
    `;

    // Wire Stack Click
    contentEl.querySelectorAll('.clickable-stack-pill').forEach((pill) => {
      pill.addEventListener('click', (e) => {
        e.stopPropagation();
        const stName = pill.dataset.stack;
        if (stName) openStackModal(stName);
      });
    });

    // Wire App Backup button
    const backupActionBtn = document.getElementById('ci-btn-backup-action');
    if (backupActionBtn) {
      backupActionBtn.addEventListener('click', async () => {
        backupActionBtn.disabled = true;
        setIconLabel(backupActionBtn, '⏳', t('ui.backing_up', 'Backing up...'));
        showToast(t('toast.creating_backup_for', 'Creating backup for {activeCname}...', { activeCname: _activeCname }), 'info');
        try {
          const res = await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/backup`);
          // the server names the file `filename` and its size `size_human`: every message said "archive.tar.gz" (SET-14)
          const archiveName = res?.backup?.filename || res?.backup?.archive_file || 'archive.tar.gz';
          const sizeStr = res?.backup?.size_human || res?.backup?.archive_size_formatted || '';
          showToast(t('toast.app_backed_up', 'App "{name}" backed up ({archive}).', { name: _activeCname, archive: sizeStr ? `${archiveName}, ${sizeStr}` : archiveName }), 'success');
        } catch (err) {
          showToast(t('toast.backup_failed', 'Backup failed: {error}', { error: err.message }), 'error');
        } finally {
          backupActionBtn.disabled = false;
          setIconLabel(backupActionBtn, '💾', t('ci.backup_now', 'Back up the app now')); // the label it started with
        }
      });
    }

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
        applyResBtn.textContent = t('ui.applying', 'Applying...');
        try {
          await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/resources`, {
            memory_mb: isNaN(memVal) ? 0 : memVal,
            nano_cpus: isNaN(cpuVal) ? 0 : cpuVal,
            restart_policy: restartVal,
          });
          showToast(t('toast.resource_limits_updated_with_zero_downtime', 'Resource limits updated with zero downtime!'), 'success');
          await loadContainerDetails(cid);
        } catch (err) {
          showToast(t('toast.resource_update_failed', 'Resource update failed: {error}', { error: err.message }), 'error');
        } finally {
          applyResBtn.disabled = false;
          setIconLabel(applyResBtn, '💾', t('ui.apply_tuning', 'Apply Tuning'));
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
        showToast(t('toast.restarting', 'Restarting {activeCname}...', { activeCname: _activeCname }), 'info');
        try {
          await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: 'restart' });
          showToast(t('toast.container_restarted', 'Container "{activeCname}" restarted.', { activeCname: _activeCname }), 'success');
          await loadContainerDetails(cid);
        } catch (err) {
          showToast(t('toast.restart_failed', 'Restart failed: {error}', { error: err.message }), 'error');
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
    if (loadingEl) loadingEl.innerHTML = `<span class="ci-crit">${escapeHtml(t('ci.load_failed', 'Could not load the container details: {error}', { error: err.message }))}</span>`;
  }
}

export const openContainerModal = openContainerInspector;

function renderPortsTab(details) {
  const container = document.getElementById('ci-ports-content');
  if (!container) return;

  const currentHost = typeof window !== 'undefined' && window.location.hostname ? window.location.hostname : 'localhost';
  const webUrl = details.webui_url ? details.webui_url.replace('[HOST]', currentHost) : null;
  const isHostNet = details.overview?.network_mode === 'host' || (details.ports || []).some((p) => p.ip === 'host' || p.is_host_network);

  const hostBanner = isHostNet
    ? `
      <div style="margin-bottom:14px; padding:12px; background:rgba(79, 216, 196, 0.08); border:1px solid rgba(79, 216, 196, 0.25); border-radius:6px; display:flex; align-items:flex-start; gap:10px;">
        <span class="ci-fs16-2">⚡</span>
        <div>
          <div class="ci-xs-bold-accent">${t('ci.host_net', 'Host network mode')}</div>
          <div class="ci-xs-soft">
            ${t('ci.host_net_desc', 'This container uses the host’s network directly, without Docker’s bridge or port forwarding: its services listen on the host’s own addresses.')}
          </div>
        </div>
      </div>
    `
    : '';

  const webuiBanner = webUrl
    ? `
      <div style="margin-bottom:14px; padding:12px; background:var(--lt-b-33cdb814, rgba(51, 205, 184, 0.08)); border:1px solid var(--lt-r-33cdb840, rgba(51, 205, 184, 0.25)); border-radius:6px; display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div class="ci-xs-bold-strong-2">${t('ci.webui', 'Web page found')}</div>
          <div class="ci-xs-muted-3">${isHostNet ? t('ci.webui_port_host', 'On port {port} (host network)', { port: details.primary_port }) : t('ci.webui_port', 'On port {port}', { port: details.primary_port })}</div>
        </div>
        <a href="${escapeHtml(webUrl)}" target="_blank" rel="noopener noreferrer" class="btn-webui-badge ci-xs-7">
          ${ico('🌐')} ${t('ci.open_webui', 'Open the web page')} ↗
        </a>
      </div>
    `
    : '';

  const portsList = details.ports || [];
  let tableHtml;
  if (portsList.length === 0) {
    tableHtml = `<div class="ci-muted-center-3">${isHostNet ? 'No exposed ports declared in image metadata. Container listens directly on host interfaces.' : 'No published port mappings configured for this container.'}</div>`;
  } else {
    tableHtml = `
      <div class="ci-box-4">
        <table class="copy-history-table ci-x-5">
          <thead>
            <tr>
              <th>${t('ci.col_host_binding', 'Host binding')}</th>
              <th>${t('ci.col_container_port', 'Container port')}</th>
              <th>${t('ci.col_protocol', 'Protocol')}</th>
              <th>${t('ci.col_web', 'Web access')}</th>
            </tr>
          </thead>
          <tbody>
            ${portsList.map((p) => {
              const isWeb = p.public_port === details.primary_port;
              const isHost = p.ip === 'host' || p.is_host_network;
              const hostLabel = isHost
                ? `<span class="ci-bold-accent">${t('ci.host_direct', 'Host direct (:{port})', { port: p.public_port })}</span>`
                : (p.public_port ? `${escapeHtml(p.ip || '0.0.0.0')}:${p.public_port}` : `<span class="ci-muted">${t('ci.none', 'None')}</span>`);
              const directLink = p.public_port
                ? `<a href="http://${currentHost}:${p.public_port}/" target="_blank" rel="noopener noreferrer" style="color:var(--lt-ink-brand, var(--accent-cyan, #33cdb8)); font-size:var(--kb-fs-xs);">http://${currentHost}:${p.public_port} ↗</a>`
                : '—';
              return `
                <tr>
                  <td class="ci-xs-mono-2">${hostLabel}</td>
                  <td class="ci-mono">${p.private_port || '—'}</td>
                  <td><span class="ci-proto-tag ci-xs-box">${escapeHtml(p.type || 'tcp')}</span></td>
                  <td>${isWeb ? `<span class="ci-xs-bold-ok">${ico('✓')} ${t('ci.primary_web', 'Main web page')}</span>` : directLink}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>

      ${isHostNet ? `
        <div class="ci-metric-card" style="margin-top:14px; background:rgba(79,216,196,0.04); border:1px solid rgba(79,216,196,0.2); padding:12px; border-radius:8px;">
          <div class="ci-xs-bold-accent-2">${ico('⚡')} ${t('ci.host_active', 'Host network in use')}</div>
          <p class="ci-xs-soft-2">
            ${t('ci.host_active_desc', 'Port forwarding does not apply in host mode. To map your own host ports (for example {example}), change {mode} to bridge mode in the compose file or the container settings.', { example: '<code>8085:8080</code>', mode: '<code>network_mode: host</code>' })}
          </p>
        </div>
      ` : `
        <!-- Port Reconfiguration Section (Phase 3) -->
        <div class="ci-metric-card ci-box-5">
          <div class="ci-row-8">
            <div class="ci-xs-bold-strong">${ico('🔄')} ${t('ci.reconfigure', 'Change ports (the container is copied and recreated)')}</div>
            <span style="font-size:var(--kb-fs-xs); color:var(--warn); background:rgba(245,158,11,0.12); padding:2px 6px; border-radius:4px;">${t('ci.rollback', 'Rolls back on failure')}</span>
          </div>
          <p class="ci-xs-muted-5">
            ${t('ci.reconfigure_desc', 'Change the host ports. The container is stopped, copied and started with the new ports; every mounted folder stays.')}
          </p>
          <div class="ci-col">
            ${portsList.map((p, idx) => `
              <div class="ci-row-box-2">
                <span class="ci-xs-strong-mono">${t('ci.container_port_row', 'Container :{port}/{proto}', { port: p.private_port, proto: p.type || 'tcp' })}</span>
                <span class="ci-muted">➔</span>
                <label class="ci-xs-muted">${t('ci.host_port', 'Host port:')}</label>
                <input type="number" class="tz-text-input ci-port-input ci-xs-8" data-idx="${idx}" data-cp="${p.private_port}" data-proto="${p.type || 'tcp'}" value="${p.public_port || ''}">
                <span class="ci-xs-muted" id="ci-port-check-${idx}"></span>
              </div>
            `).join('')}
            <div class="ci-x-6">
              <button class="btn-pill-toggle" id="ci-btn-apply-ports" style="color: var(--lt-ink-brand, var(--accent-cyan, #33cdb8)); border-color: var(--accent-cyan,#33cdb8); background: var(--lt-b-33cdb81f, rgba(51,205,184,0.12));">
                ${ico('🚀')} ${t('ci.recreate_ports', 'Recreate the container with the new ports')}
              </button>
            </div>
          </div>
        </div>
      `}
    `;
  }

  container.innerHTML = hostBanner + webuiBanner + tableHtml;

  // Wire Port availability checks and apply button
  const _portCheckTimers = {};
  const foundInputs = container.querySelectorAll('.ci-port-input');
  foundInputs.forEach((input) => {
    const handleInput = (e) => {
      const idx = input.dataset.idx;
      const proto = input.dataset.proto || 'tcp';
      const targetVal = e && e.target ? e.target.value : input.value;
      const val = parseInt(targetVal, 10);
      const statusEl = document.getElementById(`ci-port-check-${idx}`);
      if (!statusEl) return;
      if (isNaN(val) || val <= 0 || val > 65535) {
        statusEl.innerHTML = '<span class="ci-port-badge badge-crit" style="color:var(--crit); font-size:var(--kb-fs-xs); padding:2px 6px; border-radius:4px; background:rgba(239,68,68,0.12);">' + t('ci.port_invalid', 'Invalid port') + '</span>';
        return;
      }
      statusEl.innerHTML = '<span class="ci-xs-muted-2">' + t('ci.checking', 'Checking…') + '</span>';

      clearTimeout(_portCheckTimers[idx]);
      _portCheckTimers[idx] = setTimeout(async () => {
        try {
          const chk = await api.get(`/api/docker/check_port?port=${val}&proto=${proto}`);
          if (chk && chk.available) {
            statusEl.innerHTML = `<span class="ci-port-badge badge-ok" style="color:var(--ok2); font-weight:600; font-size:var(--kb-fs-xs); padding:2px 6px; border-radius:4px; background:rgba(34,197,94,0.12);">${ico('✓')} ${t('ci.port_free', 'Port {port} is free', { port: val })}</span>`;
          } else {
            const taken = chk && chk.in_use_by
              ? t('ci.port_used_by', 'Port {port} is in use by {name}', { port: val, name: chk.in_use_by })
              : t('ci.port_used', 'Port {port} is in use', { port: val });
            statusEl.innerHTML = `<span class="ci-port-badge badge-warn" style="color:var(--crit); font-weight:600; font-size:var(--kb-fs-xs); padding:2px 6px; border-radius:4px; background:rgba(239,68,68,0.15);">${ico('⚠️')} ${escapeHtml(taken)}</span>`;
          }
        } catch (err) {
          console.error('[check_port error]', err);
          statusEl.innerHTML = '';
        }
      }, 250);
    };
    input.addEventListener('input', handleInput);
  });

  const applyPortsBtn = document.getElementById('ci-btn-apply-ports');
  if (applyPortsBtn) {
    applyPortsBtn.addEventListener('click', () => {
      const cname = details.overview?.name || details.cid;
      showConfirmToast(
        `${escapeHtml(t('ci.recreate_ports_q', 'Recreate container "{name}" with the new port mappings?', { name: cname })).replace(escapeHtml(cname), () => `<strong>${escapeHtml(cname)}</strong>`)}<br><br><span class="ci-xs-muted">${escapeHtml(t('ci.recreate_note', 'The container is recreated in 2–3 seconds. Volumes and saved data stay as they are.'))}</span>`,
        async () => {
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
          applyPortsBtn.textContent = t('ui.recreating_container', 'Recreating container...');
          showToast(t('toast.recreating_container_with_new_ports', 'Recreating container "{cname}" with new ports...', { cname: cname }), 'info');

          try {
            const targetId = details.cid || details.overview?.id;
            const res = await api.post(`/api/docker/containers/${encodeURIComponent(targetId)}/ports`, {
              ports: newPorts,
              keep_backup: false
            });
            showToast(res.message || 'Container recreated successfully!', 'success');
            await loadContainerDetails(targetId);
          } catch (err) {
            showToast(t('toast.port_reconfiguration_failed', 'Port reconfiguration failed: {error}', { error: err.message }), 'error');
          } finally {
            applyPortsBtn.disabled = false;
            setIconLabel(applyPortsBtn, '🚀', t('ui.recreate_container_with_new_ports', 'Recreate Container with New Ports'));
          }
        },
        null,
        {
          okText: '🚀 Recreate Container',
          cancelText: t('common.cancel', 'Cancel')
        }
      );
    });
  }
}

function renderMountsTab(details) {
  const container = document.getElementById('ci-mounts-content');
  if (!container) return;

  const mounts = details.mounts || [];
  if (mounts.length === 0) {
    container.innerHTML = '<div class="ci-muted-center-3">' + escapeHtml(t('ci.no_mounts', 'No folders are mounted in this container.')) + '</div>';
    return;
  }

  container.innerHTML = `
    <div class="ci-box-4">
      <table class="copy-history-table ci-x-5">
        <thead>
          <tr>
            <th>${t('ci.col_host_path', 'Host path')}</th>
            <th>${t('ci.col_target', 'In the container')}</th>
            <th>${t('ci.col_mode', 'Mode')}</th>
            <th>${t('ci.col_type', 'Type')}</th>
            <th class="ci-x-7">${t('ci.col_files', 'Files')}</th>
          </tr>
        </thead>
        <tbody>
          ${mounts.map((m) => {
            const isFmNavigable = m.source && (m.source.startsWith('/mnt/') || m.source.startsWith('/'));
            const appdataBadge = m.is_appdata
              ? '<span style="display:inline-block; margin-left:4px; padding:1px 4px; border-radius:3px; font-size:var(--kb-fs-xs); font-weight:700; background:rgba(167, 139, 250, 0.2); color:var(--lt-t-c4b5fdff, #c4b5fd);">' + t('ci.appdata_badge', 'APP DATA') + '</span>'
              : '';
            const btnHtml = isFmNavigable
              ? `<button class="btn-pill-toggle btn-reveal-fm is-small" data-path="${escapeHtml(m.source)}">${ico('📁')} ${t('ui.open_in_file_explorer', 'Open in File Explorer')}</button>`
              : '—';

            return `
              <tr>
                <td class="ci-xs-strong-mono-2">
                  ${escapeHtml(m.source)} ${appdataBadge}
                </td>
                <td class="ci-xs-muted-mono-3">${escapeHtml(m.destination)}</td>
                <td><span style="font-size:var(--kb-fs-xs); font-weight:700; text-transform:uppercase; color:${m.rw ? 'var(--ok2)' : 'var(--warn)'};">${escapeHtml(m.mode)}</span></td>
                <td class="ci-xs-muted">${escapeHtml(m.type)}</td>
                <td class="ci-x-7">${btnHtml}</td>
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
      showToast(t('toast.navigated_file_explorer_to', 'Navigated File Explorer to {path}', { path: path }), 'info');
    });
  });
}

function renderEnvTab(details) {
  const container = document.getElementById('ci-env-content');
  const statsEl = document.getElementById('ci-env-stats');
  if (!container) return;

  const envs = details.env || [];
  if (statsEl) {
    statsEl.textContent = t('ci.vars', '{count, plural, one {# variable} other {# variables}} ({hidden} hidden)', { count: envs.length, hidden: envs.filter((e) => e.is_secret).length });
  }

  if (envs.length === 0) {
    container.innerHTML = '<div class="ci-muted-center-3">' + escapeHtml(t('ci.no_env', 'No environment variables of its own.')) + '</div>';
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
    <div class="ci-box-4">
      <table class="copy-history-table ci-x-5">
        <thead>
          <tr>
            <th class="ci-size-2">${t('ci.col_var', 'Variable')}</th>
            <th>${t('ci.col_value', 'Value')}</th>
            <th class="ci-size-3">${t('chassis.col_action', 'Action')}</th>
          </tr>
        </thead>
        <tbody>
          ${envs.map((e, idx) => {
            const isSec = e.is_secret;
            const secBadge = isSec ? '<span style="font-size:var(--kb-fs-xs); padding:1px 4px; border-radius:3px; background:rgba(239, 68, 68, 0.15); color:var(--kb-text-crit); margin-left:4px;">SECRET</span>' : '';
            return `
              <tr>
                <td class="ci-bold-strong-mono">
                  ${escapeHtml(e.key)} ${secBadge}
                </td>
                <td class="ci-xs-mono-3">
                  <span id="env-val-${idx}">${escapeHtml(e.masked_value)}</span>
                </td>
                <td class="ci-x-7">
                  ${isSec ? `<button class="btn-toggle-secret btn-pill-toggle is-small" data-idx="${idx}" title="${t('ui.toggle_show_hide', 'Toggle show/hide')}">👁️</button>` : ''}
                  <button class="btn-copy-env btn-pill-toggle is-small" data-idx="${idx}" title="${t('ui.copy_value', 'Copy value')}">📋</button>
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
      copyText(val).then(() => {
        showToast(t('toast.value_copied_to_clipboard', 'Value copied to clipboard.'), 'success');
      });
    });
  });
}

async function loadContainerCompose(cid) {
  const codeEl = document.getElementById('ci-compose-code');
  const badgeEl = document.getElementById('ci-compose-source-badge');
  if (codeEl) codeEl.textContent = t('ui.generating_docker_compose_definition', 'Generating Docker Compose definition...');

  try {
    const data = await api.get(`/api/docker/containers/${encodeURIComponent(cid)}/compose`);
    _activeComposeData = data;

    if (badgeEl) {
      if (data.source === 'disk') {
        setIconLabel(badgeEl, '📄', t('ui.read_from_disk', 'Read from Disk'));
        badgeEl.style.color = '#4fd8c4';
        badgeEl.style.background = 'rgba(79, 216, 196, 0.15)';
      } else {
        setIconLabel(badgeEl, '✨', t('ui.synthesized_compose_spec_v3_8', 'Synthesized Compose Spec v3.8'));
        badgeEl.style.color = 'var(--ok2)';
        badgeEl.style.background = 'rgba(51, 205, 184, 0.15)';
      }
    }

    renderComposeCode();
  } catch (err) {
    if (codeEl) codeEl.textContent = `# ${t('ci.compose_failed', 'Could not make the compose file: {error}', { error: err.message })}`;
  }
}

async function renderComposeCode() {
  const codeEl = document.getElementById('ci-compose-code');
  const maskToggle = document.getElementById('ci-compose-mask-toggle');
  if (!codeEl || !_activeComposeData) return;

  const mask = maskToggle ? maskToggle.checked : true;
  if (!mask && (!_activeComposeData.compose_yaml || _activeComposeData.compose_yaml === _activeComposeData.masked_yaml)) {
    try {
      const data = await api.get(`/api/docker/containers/${encodeURIComponent(_activeCid)}/compose?unmask=true`);
      _activeComposeData = data;
    } catch (e) {
      showToast(t('toast.cannot_unmask_insufficient_permissions', 'Cannot unmask: insufficient permissions.'), 'error');
    }
  }
  codeEl.textContent = mask ? _activeComposeData.masked_yaml : (_activeComposeData.compose_yaml || _activeComposeData.masked_yaml);
}

export function stopLogStream() {
  if (_logEventSource) {
    try {
      _logEventSource.close();
    } catch (_) {}
    _logEventSource = null;
  }
}

export function startLogStream(cid) {
  stopLogStream();
  if (!cid) return;
  const tailSelect = document.getElementById('ci-logs-tail-select');
  const tail = tailSelect ? tailSelect.value : 100;
  const url = `/api/docker/containers/${encodeURIComponent(cid)}/logs/stream?tail=${tail}&follow=1`;

  // A stream starts with the app's last lines, so the buffer starts empty: the next app's lines were
  // appended to the previous one's, and each reconnect repeated the tail (SET-14, Apps 26)
  _activeLogLines = [];
  const terminal = document.getElementById('ci-logs-terminal');
  if (terminal) {
    terminal.innerHTML = '<div class="ci-logs-note ci-muted-center-2">' + t('ci.connecting', 'Connecting to the live log…') + '</div>';
  }

  try {
    const source = new EventSource(url);
    _logEventSource = source;
    // the server says when the log ends (a stopped app) or fails; without this the browser
    // reconnected every few seconds and the last lines came again
    source.addEventListener('done', () => {
      if (_logEventSource !== source) return;
      stopLogStream();
      appendLogNote(t('ci.log_ended', 'The live log has ended: the app is not running.'));
    });
    source.addEventListener('error', (e) => {
      if (_logEventSource !== source || !(/** @type {any} */ (e).data)) return; // a dropped connection retries by itself
      let why = '';
      try {
        why = JSON.parse(/** @type {any} */ (e).data).error || '';
      } catch (_) {}
      stopLogStream();
      appendLogNote(t('ci.logs_failed', 'Could not read the logs: {error}', { error: why }));
    });
    source.onmessage = (e) => {
      if (_logEventSource !== source) return; // a line from the app shown before
      try {
        const item = JSON.parse(e.data);
        if (item && item.msg !== undefined) {
          _activeLogLines.push(item);
          if (_activeLogLines.length > 2000) {
            _activeLogLines.splice(0, _activeLogLines.length - 2000);
          }
          appendLogLine(item);
        }
      } catch (_) {}
    };
    _logEventSource.onerror = () => {
      // Automatic retry handled by EventSource
    };
  } catch (err) {
    console.warn('[Docker Logs] SSE stream error:', err);
  }
}

/** A muted line under the log (the stream ended or failed). */
function appendLogNote(text) {
  const terminal = document.getElementById('ci-logs-terminal');
  if (!terminal) return;
  const placeholder = terminal.querySelector('.ci-logs-note');
  if (placeholder && _activeLogLines.length === 0) terminal.innerHTML = '';
  const row = document.createElement('div');
  row.className = 'ci-logs-note ci-logs-end';
  row.textContent = text;
  terminal.appendChild(row);
}

export function appendLogLine(l) {
  const terminal = document.getElementById('ci-logs-terminal');
  if (!terminal) return;
  const placeholder = terminal.querySelector('.ci-logs-note:not(.ci-logs-end)');
  if (placeholder) {
    placeholder.remove();
  }
  if (_activeLogFilter) {
    const textMatch = (l.msg || '').toLowerCase().includes(_activeLogFilter) || (l.ts || '').toLowerCase().includes(_activeLogFilter);
    if (!textMatch) return;
  }
  const tsHtml = l.ts ? `<span style="color:var(--lt-t-33cdb8ff, #33cdb8); opacity:0.6; margin-right:6px;">${escapeHtml(l.ts.slice(11, 19))}</span>` : '';
  const color = l.stream === 'stderr' ? '#f87171' : '#e6efef';
  const row = document.createElement('div');
  row.style.cssText = `white-space:pre-wrap; word-break:break-all; color:${color}; margin-bottom:2px;`;
  row.innerHTML = `${tsHtml}${escapeHtml(l.msg)}`;
  terminal.appendChild(row);

  if (_autoScrollLogs) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

async function loadContainerLogs(cid) {
  const isStreamActive = document.getElementById('ci-logs-stream-toggle')?.checked;
  if (isStreamActive) {
    startLogStream(cid);
    return;
  }
  stopLogStream();
  const terminal = document.getElementById('ci-logs-terminal');
  const tailSelect = document.getElementById('ci-logs-tail-select');
  const tail = tailSelect ? tailSelect.value : 200;

  if (terminal) terminal.innerHTML = '<div class="ci-logs-note ci-muted-center-2">' + t('ci.fetching_logs', 'Fetching logs…') + '</div>';

  try {
    const res = await api.get(`/api/docker/containers/${encodeURIComponent(cid)}/logs?tail=${tail}`);
    _activeLogLines = res.lines || [];
    renderLogsOutput();
  } catch (err) {
    if (terminal) terminal.innerHTML = `<div class="ci-logs-note ci-crit-center">${escapeHtml(t('ci.logs_failed', 'Could not read the logs: {error}', { error: err.message }))}</div>`;
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
    terminal.innerHTML = '<div class="ci-logs-note ci-muted-center-2">' + t('ci.no_logs', 'No log lines for this period.') + '</div>';
    return;
  }

  terminal.innerHTML = lines
    .map((l) => {
      const tsHtml = l.ts ? `<span style="color:var(--lt-t-33cdb8ff, #33cdb8); opacity:0.6; margin-right:6px;">${escapeHtml(l.ts.slice(11, 19))}</span>` : '';
      const color = l.stream === 'stderr' ? '#f87171' : '#e6efef';
      return `<div style="white-space:pre-wrap; word-break:break-all; color:${color}; margin-bottom:2px;">${tsHtml}${escapeHtml(l.msg)}</div>`;
    })
    .join('');

  if (_autoScrollLogs) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

/** What a finished delete says. The message about the copy looked for a field the server does
 *  not send, so every delete read "permanently destroyed", also when a copy had been made. */
export function removedSaid(res, name, imageAsked = false) {
  const said = res?.archived
    ? t('ci.removed_copy', '{name} was removed. A copy of its set-up and data folders is under Backup.', { name })
    : t('ci.removed', '{name} was removed.', { name });
  if (imageAsked && res && !res.image_removed) {
    return `${said} ${t('ci.image_kept', 'Its image was kept: {why}', { why: res.image_error || t('ci.image_in_use', 'another app uses it') })}`;
  }
  return said;
}

export function openContainerDeleteModal(cid, cname, imageRef = '', onDeleted = null) {
  let modal = document.getElementById('container-delete-modal-overlay');
  if (!modal) {
    const html = `
      <div id="container-delete-modal-overlay" class="smart-modal-backdrop" style="display:none; z-index:10020;">
        <div id="container-delete-modal-window" class="smart-modal-window ci-size-4" style="display: flex;">
          <div class="smart-modal-header ci-row-9">
            <div class="ci-row">
              <span class="ci-fs18">⚠️</span>
              <span style="font-weight:700; color:var(--crit, #ff6b6b); font-size:13px;">${t('ci.destroy', 'Delete container')}</span>
            </div>
            <button class="win-btn close-btn" id="cdm-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
          <div class="ci-col-2">
            <div class="ci-xs-soft-3">
              ${t('ci.delete_q', 'Delete the container {name} ({id}) for good?', {
                name: '<strong class="ci-strong" id="cdm-cname"></strong>',
                id: '<code id="cdm-cid" style="font-family:var(--font-mono, monospace); font-size:var(--kb-fs-xs); color:var(--lt-ink-brand, var(--accent-cyan, #33cdb8));"></code>',
              })}
            </div>
            <div style="background:rgba(255,107,107,0.08); border:1px solid rgba(255,107,107,0.25); border-radius:6px; padding:10px 12px; font-size:var(--kb-fs-xs); color:var(--lt-t-fca5a5ff, #fca5a5); line-height:1.4;">
              ${ico('⚠️')} <strong>${t('ci.warning', 'Warning:')}</strong> ${t('ci.delete_warn', 'The container is stopped and removed from Docker. Anything saved only inside the container is lost.')}
            </div>
            <div class="ci-col-box">
              <label style="display:flex; align-items:center; gap:8px; font-size:var(--kb-fs-xs); color:var(--lt-t-fb923cff, #fb923c); font-weight:600; cursor:pointer;">
                <input class="ci-x-2" type="checkbox" id="cdm-archive" checked>
                <span>${t('ci.opt_archive', 'Archive the app data and settings (kept in the backup library, never deleted)')}</span>
              </label>
              <label class="ci-row-xs">
                <input class="ci-x-2" type="checkbox" id="cdm-force" checked>
                <span>${t('ci.opt_force', 'Stop the container first if it is running')}</span>
              </label>
              <label class="ci-row-xs">
                <input class="ci-x-2" type="checkbox" id="cdm-volumes" checked>
                <span>${t('ci.opt_volumes', 'Delete its anonymous volumes (frees space)')}</span>
              </label>
              <label class="ci-row-xs">
                <input class="ci-x-2" type="checkbox" id="cdm-image">
                <span>${t('ci.opt_image', 'Also delete the container image')} <code class="ci-xs-muted-2" id="cdm-image-tag"></code></span>
              </label>
            </div>
          </div>
          <div class="ci-row-box-3">
            <button class="btn-pill-toggle" id="cdm-cancel-btn">${t('common.cancel', 'Cancel')}</button>
            <button class="btn-pill-toggle is-danger ci-strong-box" id="cdm-confirm-btn">
              ${ico('💥')} ${t('ci.destroy', 'Delete container')}
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
  setIconLabel(confirmBtn, '💥', t('ui.destroy_container', 'Destroy Container'));

  confirmBtn.onclick = async () => {
    const archiveData = document.getElementById('cdm-archive')?.checked ?? true;
    const force = document.getElementById('cdm-force').checked;
    const removeVolumes = document.getElementById('cdm-volumes').checked;
    const removeImage = document.getElementById('cdm-image').checked;

    confirmBtn.disabled = true;
    confirmBtn.textContent = t('ui.destroying', 'Destroying...');

    try {
      const url = `/api/docker/containers/${encodeURIComponent(cid)}?force=${force}&remove_volumes=${removeVolumes}&remove_image=${removeImage}&archive_data=${archiveData}`;
      const res = await api.delete(url, { confirmed: true });
      showToast(removedSaid(res, cname, removeImage), 'success');
      modal.classList.remove('open');
      modal.style.display = 'none';

      if (typeof onDeleted === 'function') {
        onDeleted();
      }
    } catch (err) {
      showToast(t('toast.failed_to_destroy_container', 'Failed to destroy container: {error}', { error: err.message }), 'error');
      confirmBtn.disabled = false;
      setIconLabel(confirmBtn, '💥', t('ui.destroy_container', 'Destroy Container'));
    }
  };
}

async function renderContainerEditTab(cid) {
  const hostEl = document.getElementById('cie-form-host');
  if (!hostEl) return;

  // The form always starts from the real values (SET-07). It was filled from the details the
  // Overview had loaded, where secrets are dots: "Save and recreate" then wrote the dots of a
  // password inside an address into the new container.
  hostEl.innerHTML = '<div class="ci-muted-center">' + t('ci.loading_config', 'Loading the container settings…') + '</div>';
  let details;
  try {
    details = await api.get(`/api/docker/containers/${encodeURIComponent(cid)}/details?unmask=true`);
  } catch (e) {
    hostEl.innerHTML = `<div class="ci-crit-2">${escapeHtml(t('ci.load_failed', 'Could not load the container details: {error}', { error: e.message }))}</div>`;
    return;
  }

  const ov = details.overview || {};
  const currentName = ov.name || _activeCname || '';
  const currentImage = ov.image || '';
  const currentNetwork = ov.network_mode || 'bridge';
  const currentRestart = ov.restart_policy || 'unless-stopped';
  const isToolkit = ['kiboto', 'zettnas-toolkit', 'zettnas'].includes(currentName) || (cid && window.location.hostname && cid.startsWith(window.location.hostname));

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
    <div class="cie-form-wrap ci-x-8">
      <!-- Guidance Notice -->
      <div style="background:rgba(51,205,184,0.08); border:1px solid rgba(51,205,184,0.25); border-radius:6px; padding:10px 12px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div class="ci-xs-bold-accent">${ico('✏️')} ${t('ci.editor', 'Container settings')}</div>
          <div class="ci-xs-muted-3">
            ${t('ci.editor_desc', 'Saving copies the container with the new settings and switches over; if that fails, the old one comes back. Every setting is checked before the container is touched.')}
          </div>
        </div>
        ${isToolkit ? `<span class="ci-badge" style="background:rgba(239,68,68,0.15); color:var(--lt-t-fca5a5ff, #fca5a5); font-size:var(--kb-fs-xs); padding:2px 8px; border-radius:4px; font-weight:700;">${t('ci.self_protected', 'SELF-PROTECTED')}</span>` : ''}
      </div>

      ${isToolkit ? `
        <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); border-radius:6px; padding:12px; margin-bottom:14px; color:var(--lt-t-fca5a5ff, #fca5a5); font-size:var(--kb-fs-xs);">
          ${ico('⚠️')} ${t('ci.self_note', 'Kiboto can’t recreate its own container from here. Change its settings in Docker Compose or the host’s template, so running connections are not cut.')}
        </div>
      ` : ''}

      <!-- Section 1: General Settings -->
      <div class="ci-metric-card ci-box-6">
        <div class="ci-xs-bold-strong-3">${t('ci.general', 'General settings')}</div>
        <div class="ci-grid-3">
          <div>
            <label class="ci-xs-semi-muted" for="cie-input-name">${t('ci.name_label', 'Container name')}</label>
            <input type="text" id="cie-input-name" class="tz-text-input ci-xs-9" value="${escapeHtml(currentName)}" ${isToolkit ? 'disabled' : ''}>
          </div>
          <div>
            <label class="ci-xs-semi-muted" for="cie-input-image">${t('ci.image_label', 'Image and tag')}</label>
            <input type="text" id="cie-input-image" class="tz-text-input ci-xs-9" value="${escapeHtml(currentImage)}" ${isToolkit ? 'disabled' : ''}>
          </div>
          <div>
            <label class="ci-xs-semi-muted" for="cie-select-network">${t('ci.network_label', 'Network mode')}</label>
            <select id="cie-select-network" class="tz-select-input ci-xs-6" ${isToolkit ? 'disabled' : ''}>
              <option value="bridge" ${currentNetwork === 'bridge' ? 'selected' : ''}>${t('ci.net_bridge', 'bridge (default)')}</option>
              <option value="host" ${currentNetwork === 'host' ? 'selected' : ''}>${t('ci.net_host', 'host (the host’s network)')}</option>
              <option value="none" ${currentNetwork === 'none' ? 'selected' : ''}>${t('ci.net_none', 'none (no network)')}</option>
              ${currentNetwork && !['bridge', 'host', 'none'].includes(currentNetwork) ? `<option value="${escapeHtml(currentNetwork)}" selected>${escapeHtml(t('ci.net_custom', '{name} (custom)', { name: currentNetwork }))}</option>` : ''}
            </select>
          </div>
          <div>
            <label class="ci-xs-semi-muted" for="cie-select-restart">${t('ci.restart_policy', 'Restart policy')}</label>
            <select id="cie-select-restart" class="tz-select-input ci-xs-6" ${isToolkit ? 'disabled' : ''}>
              <option value="unless-stopped" ${currentRestart === 'unless-stopped' ? 'selected' : ''}>${t('ci.restart_recommended', 'unless-stopped (recommended)')}</option>
              <option value="always" ${currentRestart === 'always' ? 'selected' : ''}>always</option>
              <option value="on-failure" ${currentRestart === 'on-failure' ? 'selected' : ''}>on-failure</option>
              <option value="no" ${currentRestart === 'no' ? 'selected' : ''}>no</option>
            </select>
          </div>
        </div>
        <div class="ci-x-9">
          <label class="ci-row-xs-soft">
            <input class="ci-x-2" type="checkbox" id="cie-cb-pull" ${isToolkit ? 'disabled' : ''}>
            <span>${t('ci.pull', 'Pull the newest image before recreating')}</span>
          </label>
        </div>
      </div>

      <!-- Section 2: Port Mappings -->
      <div class="ci-metric-card ci-box-6">
        <div class="ci-row-8">
          <div class="ci-xs-bold-strong">${t('ci.ports_title', 'Port bindings')}</div>
          <button class="btn-pill-toggle ci-xs-10" id="cie-btn-add-port" ${isToolkit ? `disabled title="${escapeHtml(t('container.why_self', 'Kiboto cannot rebuild its own container; change it in Docker Compose'))}"` : ''}>+ ${t('ci.add_port', 'Add port')}</button>
        </div>
        <div class="ci-x-10" id="cie-ports-container" style="display: flex;"></div>
      </div>

      <!-- Section 3: Volume Mounts & Paths -->
      <div class="ci-metric-card ci-box-6">
        <div class="ci-row-8">
          <div class="ci-xs-bold-strong">${t('ci.mounts_title', 'Mounted folders')}</div>
          <button class="btn-pill-toggle ci-xs-10" id="cie-btn-add-mount" ${isToolkit ? `disabled title="${escapeHtml(t('container.why_self', 'Kiboto cannot rebuild its own container; change it in Docker Compose'))}"` : ''}>+ ${t('ci.add_mount', 'Add folder')}</button>
        </div>
        <div class="ci-x-10" id="cie-mounts-container" style="display: flex;"></div>
      </div>

      <!-- Section 4: Environment Variables -->
      <div class="ci-metric-card ci-box-6">
        <div class="ci-row-10">
          <div class="ci-xs-bold-strong">${t('ci.env_title', 'Environment variables')}</div>
          <div class="ci-row-2">
            <input type="text" id="cie-env-filter" placeholder="${t('ui.filter_variables', 'Filter variables...')}" class="tz-text-input ci-xs-11">
            <button class="btn-pill-toggle ci-xs-10" id="cie-btn-add-env" ${isToolkit ? `disabled title="${escapeHtml(t('container.why_self', 'Kiboto cannot rebuild its own container; change it in Docker Compose'))}"` : ''}>+ ${t('ci.add_var', 'Add variable')}</button>
          </div>
        </div>
        <div class="ci-x-11" id="cie-env-container" style="display: flex;"></div>
      </div>

      <!-- Footer Actions -->
      <div class="ci-row-box-4">
        <label class="ci-row-xs-muted-3">
          <input class="ci-x-2" type="checkbox" id="cie-cb-backup" ${isToolkit ? 'disabled' : ''}>
          <span>${t('ci.keep_backup', 'Keep a backup container (the old one stays as {name}.backup)')}</span>
        </label>
        <div class="ci-row-11">
          <button class="btn-pill-toggle" id="cie-btn-cancel">${t('common.cancel', 'Cancel')}</button>
          <button class="btn-pill-toggle" id="cie-btn-save" style="font-weight:700; background:var(--brand, #33cdb8); color:var(--accent-contrast-fg, #0c1517); border:none; padding:6px 16px;" ${isToolkit ? `disabled title="${escapeHtml(t('container.why_self', 'Kiboto cannot rebuild its own container; change it in Docker Compose'))}"` : ''}>
            ${ico('💾')} ${t('ci.save_recreate', 'Save and recreate the container')}
          </button>
        </div>
      </div>
      <div class="ci-xs-box-2" id="cie-status-msg" style="display: none;"></div>
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
      <span class="ci-xs-muted-6">${t('ci.row_container', 'Container:')}</span>
      <input type="number" class="tz-text-input cie-cp-input ci-xs-12" placeholder="80" value="${p.container_port || ''}">
      <span class="ci-xs-muted">/</span>
      <select class="tz-select-input cie-proto-input ci-xs-13">
        <option value="tcp" ${p.proto === 'udp' ? '' : 'selected'}>TCP</option>
        <option value="udp" ${p.proto === 'udp' ? 'selected' : ''}>UDP</option>
      </select>
      <span class="ci-muted">➔</span>
      <span class="ci-xs-muted">${t('ci.row_host', 'Host:')}</span>
      <input type="number" class="tz-text-input cie-hp-input ci-xs-12" placeholder="8080" value="${p.host_port || ''}">
      <input type="text" class="tz-text-input cie-ip-input ci-xs-12" placeholder="0.0.0.0" value="${p.host_ip || '0.0.0.0'}" title="${t('ui.host_ip', 'Host IP')}">
      <button class="btn-pill-toggle cie-row-del is-danger is-small" title="${t('ai.remove_model_btn', 'Remove')}">🗑️</button>
    `;
    row.querySelector('.cie-row-del').onclick = () => row.remove();
    portsBox.appendChild(row);
  }

  function addMountRow(m = {}) {
    const row = document.createElement('div');
    row.className = 'cie-mount-row';
    row.style.cssText = 'display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.03); padding:6px 10px; border-radius:6px;';
    row.innerHTML = `
      <span class="ci-xs-muted-6">${t('ci.row_host_path', 'Host path:')}</span>
      <input type="text" class="tz-text-input cie-src-input ci-xs-mono-grow" placeholder="/mnt/user/appdata/app" value="${escapeHtml(m.source || '')}">
      <span class="ci-muted">➔</span>
      <span class="ci-xs-muted-6">${t('ci.row_container', 'Container:')}</span>
      <input type="text" class="tz-text-input cie-dst-input ci-xs-mono-grow" placeholder="/config" value="${escapeHtml(m.destination || '')}">
      <select class="tz-select-input cie-mode-input ci-xs-13">
        <option value="rw" ${m.mode === 'ro' ? '' : 'selected'}>rw</option>
        <option value="ro" ${m.mode === 'ro' ? 'selected' : ''}>ro</option>
      </select>
      <button class="btn-pill-toggle cie-row-del is-danger is-small" title="${t('ai.remove_model_btn', 'Remove')}">🗑️</button>
    `;
    row.querySelector('.cie-row-del').onclick = () => row.remove();
    mountsBox.appendChild(row);
  }

  function addEnvRow(e = {}) {
    const row = document.createElement('div');
    row.className = 'cie-env-row';
    row.style.cssText = 'display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.03); padding:4px 8px; border-radius:6px;';
    row.innerHTML = `
      <input type="text" class="tz-text-input cie-key-input ci-xs-bold-mono" placeholder="KEY" value="${escapeHtml(e.key || '')}">
      <span class="ci-muted">=</span>
      <input type="text" class="tz-text-input cie-val-input ci-xs-mono-grow" placeholder="value" value="${escapeHtml(e.value || '')}">
      <button class="btn-pill-toggle cie-row-del is-danger is-small" title="${t('ai.remove_model_btn', 'Remove')}">🗑️</button>
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
      showToast(t('toast.container_name_and_image_cannot_be', 'Container name and image cannot be empty.'), 'warn');
      return;
    }

    showConfirmToast(
      `${escapeHtml(t('ci.save_recreate_q', 'Save changes and recreate container "{name}"?', { name })).replace(escapeHtml(name), () => `<strong>${escapeHtml(name)}</strong>`)}<br><br><span class="ci-xs-muted">${escapeHtml(t('ci.save_note', 'The container is stopped and recreated with the new settings. Volumes and folders stay as they are.'))}</span>`,
      async () => {
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
        setIconLabel(saveBtn, '⏳', t('ui.recreating_container_2', 'Recreating Container...'));
        statusMsg.style.display = 'block';
        statusMsg.style.background = 'rgba(51,205,184,0.15)';
        statusMsg.style.color = '#4fd8c4';
        statusMsg.textContent = t('ui.validating_configuration_creating_backup_and', 'Validating configuration, creating backup, and recreating container...');

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

          statusMsg.style.background = 'rgba(51,205,184,0.15)';
          statusMsg.style.color = 'var(--ok2, #33cdb8)';
          statusMsg.textContent = `✓ ${res.message || 'Container recreated successfully!'}`;
          showToast(t('toast.container_successfully_recreated', 'Container "{target_name}" successfully recreated!', { target_name: res.target_name || name }), 'success');

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
          statusMsg.textContent = t('ci.error', 'Error: {error}', { error: err.message });
          showToast(t('toast.recreation_failed', 'Recreation failed: {error}', { error: err.message }), 'error');
        } finally {
          saveBtn.disabled = false;
          setIconLabel(saveBtn, '💾', t('ui.save_recreate_container', 'Save & Recreate Container'));
        }
      },
      null,
      {
        okText: '💾 Save & Recreate',
        cancelText: t('common.cancel', 'Cancel')
      }
    );
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

