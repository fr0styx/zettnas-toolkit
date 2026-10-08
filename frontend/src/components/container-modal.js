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
  }
}

export async function openContainerInspector(cid, cname) {
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

  // Default to Overview tab
  const overviewTabBtn = overlay.querySelector('.ci-tab-btn[data-tab="overview"]');
  if (overviewTabBtn) overviewTabBtn.click();

  // Load details
  await loadContainerDetails(cid);
}

async function loadContainerDetails(cid) {
  const loadingEl = document.getElementById('ci-overview-loading');
  const contentEl = document.getElementById('ci-overview-content');
  if (loadingEl) loadingEl.style.display = 'block';
  if (contentEl) contentEl.style.display = 'none';

  try {
    const details = await api.get(`/api/docker/containers/${encodeURIComponent(cid)}/details`);
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
            restart_policy: restartVal
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
                  <span id="env-val-${idx}" data-raw="${escapeHtml(e.value)}" data-masked="${escapeHtml(e.masked_value)}">${escapeHtml(e.masked_value)}</span>
                </td>
                <td style="text-align:right;">
                  ${isSec ? `<button class="btn-toggle-secret btn-pill-toggle" data-idx="${idx}" style="font-size:9.5px; padding:1px 5px;" title="Toggle show/hide">👁️</button>` : ''}
                  <button class="btn-copy-env btn-pill-toggle" data-val="${escapeHtml(e.value)}" style="font-size:9.5px; padding:1px 5px;" title="Copy value">📋</button>
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
      const idx = btn.dataset.idx;
      const span = document.getElementById(`env-val-${idx}`);
      if (!span) return;
      const isCurrentlyMasked = span.textContent === span.dataset.masked;
      span.textContent = isCurrentlyMasked ? span.dataset.raw : span.dataset.masked;
      btn.textContent = isCurrentlyMasked ? '🔒' : '👁️';
    });
  });

  // Wire copy buttons
  container.querySelectorAll('.btn-copy-env').forEach((btn) => {
    btn.addEventListener('click', () => {
      const val = btn.dataset.val;
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

