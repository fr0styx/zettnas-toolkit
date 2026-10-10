/**
 * ZettNAS Toolkit - Docker Stack Inspector & Setup Editor Subsystem
 * Allows users to inspect, modify, save, and redeploy Docker Compose stacks.
 * Hardware & OS agnostic.
 */

import { api } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';
import { escapeHtml } from '../utils.js';
import { DockManager } from './dock.js';
import { openContainerModal } from './container-modal.js';

let _activeStackName = null;
let _activeStackDetails = null;

export function initStackModal() {
  if (document.getElementById('stack-inspector-overlay')) return;

  const overlayHtml = `
    <div id="stack-inspector-overlay" class="smart-modal-backdrop" style="display:none; z-index:10015;">
      <div id="stack-inspector-window" class="smart-modal-window stack-inspector-window" style="width:840px; max-width:96vw; height:640px; max-height:92vh; display:flex; flex-direction:column;">
        
        <!-- Header -->
        <div id="stack-inspector-header" class="smart-modal-header" style="cursor:move; user-select:none; display:flex; justify-content:space-between; align-items:center;">
          <div style="display:flex; align-items:center; gap:8px; min-width:0;">
            <span style="font-size:16px;">📁</span>
            <span id="stack-header-title" style="font-weight:700; color:#fff; font-size:13.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Stack Inspector</span>
            <span id="stack-header-origin" class="ci-badge" style="font-size:9.5px; padding:2px 7px; border-radius:4px; font-weight:700; background:rgba(14,165,233,0.15); color:var(--accent-cyan, #38bdf8); border:1px solid rgba(56,189,248,0.3);">Compose Stack</span>
            <span id="stack-header-status" class="ci-state-pill" style="display:none;"></span>
          </div>
          <div class="os-window-controls" style="display:flex; gap:6px; align-items:center;">
            <button class="win-btn min-btn" id="stack-min-btn" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="stack-max-btn" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="stack-close-btn" title="Close" aria-label="Close"></button>
          </div>
        </div>

        <!-- Quick Actions Bar & Path Info -->
        <div style="padding:8px 14px; background:rgba(0,0,0,0.45); border-bottom:1px solid rgba(255,255,255,0.06); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div style="display:flex; align-items:center; gap:8px; font-size:11px; color:var(--muted); min-width:0; overflow:hidden;">
            <span>📂</span>
            <span id="stack-path-label" style="font-family:var(--font-mono, monospace); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:420px;"></span>
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            <button class="btn-pill-toggle" id="stack-action-start" style="font-size:11px; padding:3px 9px; color:var(--ok2, #10b981);">▶ Start</button>
            <button class="btn-pill-toggle" id="stack-action-stop" style="font-size:11px; padding:3px 9px; color:var(--err2, #ef4444);">⏹ Stop</button>
            <button class="btn-pill-toggle" id="stack-action-restart" style="font-size:11px; padding:3px 9px;">↻ Restart</button>
            <button class="btn-pill-toggle" id="stack-action-redeploy" style="font-size:11px; padding:3px 9px; background:rgba(14,165,233,0.2); border-color:rgba(56,189,248,0.4); color:#38bdf8;">⬆️ Redeploy / Up</button>
          </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="ci-nav-tabs" style="display:flex; gap:4px; padding:8px 14px; background:rgba(0,0,0,0.3); border-bottom:1px solid rgba(255,255,255,0.08);">
          <button class="btn-pill-toggle stack-tab-btn active" data-tab="compose">📄 Compose Setup (compose.yaml)</button>
          <button class="btn-pill-toggle stack-tab-btn" data-tab="env">⚙️ Environment (.env)</button>
          <button class="btn-pill-toggle stack-tab-btn" data-tab="services">📦 Services & Containers (<span id="stack-tab-services-count">0</span>)</button>
        </div>

        <!-- Tab Content Panes -->
        <div class="stack-panes-container" style="flex:1; overflow-y:auto; padding:14px; box-sizing:border-box; display:flex; flex-direction:column;">
          
          <!-- 1. Compose Tab -->
          <div id="stack-pane-compose" class="stack-pane" style="display:flex; flex-direction:column; flex:1; gap:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-size:11.5px; color:var(--muted);">Edit the Docker Compose YAML definition. Changes are applied when saved or redeployed.</span>
              <div style="display:flex; gap:6px;">
                <button class="btn-pill-toggle" id="stack-compose-copy-btn">📋 Copy YAML</button>
                <button class="btn-pill-toggle" id="stack-compose-reset-btn">↺ Reload</button>
              </div>
            </div>
            <div style="flex:1; min-height:280px; position:relative; background:#080c14; border:1px solid rgba(255,255,255,0.12); border-radius:6px; display:flex;">
              <textarea id="stack-compose-editor" spellcheck="false" style="flex:1; width:100%; height:100%; min-height:280px; background:transparent; border:none; outline:none; resize:none; padding:12px; color:#f1f5f9; font-family:var(--font-mono, monospace); font-size:11.5px; line-height:1.55; box-sizing:border-box; tab-size:2;"></textarea>
            </div>
          </div>

          <!-- 2. Env Tab -->
          <div id="stack-pane-env" class="stack-pane" style="display:none; flex-direction:column; flex:1; gap:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-size:11.5px; color:var(--muted);">Environment variables (.env) passed into this compose stack during runtime.</span>
              <button class="btn-pill-toggle" id="stack-env-copy-btn">📋 Copy .env</button>
            </div>
            <div style="flex:1; min-height:280px; position:relative; background:#080c14; border:1px solid rgba(255,255,255,0.12); border-radius:6px; display:flex;">
              <textarea id="stack-env-editor" spellcheck="false" placeholder="# KEY=VALUE" style="flex:1; width:100%; height:100%; min-height:280px; background:transparent; border:none; outline:none; resize:none; padding:12px; color:#f1f5f9; font-family:var(--font-mono, monospace); font-size:11.5px; line-height:1.55; box-sizing:border-box;"></textarea>
            </div>
          </div>

          <!-- 3. Services Tab -->
          <div id="stack-pane-services" class="stack-pane" style="display:none; flex-direction:column; flex:1; gap:10px;">
            <div id="stack-services-list" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(340px, 1fr)); gap:10px;"></div>
          </div>

        </div>

        <!-- Footer Controls -->
        <div style="padding:10px 14px; background:rgba(0,0,0,0.5); border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center;">
          <div id="stack-modal-msg" style="font-size:11px; color:var(--muted);"></div>
          <div style="display:flex; gap:8px;">
            <button class="btn-pill-toggle" id="stack-cancel-btn">Cancel</button>
            <button class="btn-pill-toggle" id="stack-save-btn" style="background:rgba(255,255,255,0.1); font-weight:600;">Save Configuration</button>
            <button class="btn-pill-toggle" id="stack-save-redeploy-btn" style="background:var(--brand, #00f0ff); color:#000; font-weight:700; border-color:var(--brand, #00f0ff);">Save & Redeploy Stack</button>
          </div>
        </div>
      </div>
    </div>
  `;

  document.body.insertAdjacentHTML('beforeend', overlayHtml);
  const overlay = document.getElementById('stack-inspector-overlay');
  const win = document.getElementById('stack-inspector-window');

  // Register with DockManager
  if (DockManager && typeof DockManager.register === 'function') {
    DockManager.register('stack-inspector', overlay, '#i-grid', 'Stack Inspector', true);
  }

  // Window drag handling
  const header = document.getElementById('stack-inspector-header');
  let isDragging = false;
  let startX = 0, startY = 0, origX = 0, origY = 0;

  header.addEventListener('mousedown', (e) => {
    if (e.target.closest('.os-window-controls')) return;
    isDragging = true;
    startX = e.clientX;
    startY = e.clientY;
    const rect = win.getBoundingClientRect();
    origX = rect.left;
    origY = rect.top;
    win.style.position = 'fixed';
    win.style.left = `${origX}px`;
    win.style.top = `${origY}px`;
    win.style.margin = '0';

    const onMove = (ev) => {
      if (!isDragging) return;
      win.style.left = `${origX + (ev.clientX - startX)}px`;
      win.style.top = `${origY + (ev.clientY - startY)}px`;
    };
    const onUp = () => {
      isDragging = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  });

  // Window controls
  document.getElementById('stack-close-btn')?.addEventListener('click', closeStackModal);
  document.getElementById('stack-cancel-btn')?.addEventListener('click', closeStackModal);

  document.getElementById('stack-min-btn')?.addEventListener('click', () => {
    if (DockManager && typeof DockManager.minimize === 'function') {
      DockManager.minimize('stack-inspector');
    } else {
      closeStackModal();
    }
  });

  document.getElementById('stack-max-btn')?.addEventListener('click', () => {
    win.classList.toggle('maximized');
    if (win.classList.contains('maximized')) {
      win.style.width = '100vw';
      win.style.height = '100vh';
      win.style.maxWidth = '100vw';
      win.style.maxHeight = '100vh';
      win.style.left = '0';
      win.style.top = '0';
      win.style.borderRadius = '0';
    } else {
      win.style.width = '840px';
      win.style.height = '640px';
      win.style.maxWidth = '96vw';
      win.style.maxHeight = '92vh';
      win.style.borderRadius = '12px';
      win.style.left = '';
      win.style.top = '';
    }
  });

  // Tab switching
  overlay.querySelectorAll('.stack-tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      switchStackTab(target);
    });
  });

  // Action buttons
  document.getElementById('stack-action-start')?.addEventListener('click', () => triggerStackAction('start'));
  document.getElementById('stack-action-stop')?.addEventListener('click', () => triggerStackAction('stop'));
  document.getElementById('stack-action-restart')?.addEventListener('click', () => triggerStackAction('restart'));
  document.getElementById('stack-action-redeploy')?.addEventListener('click', () => triggerStackAction('redeploy'));

  // Save buttons
  document.getElementById('stack-save-btn')?.addEventListener('click', () => saveStack(false));
  document.getElementById('stack-save-redeploy-btn')?.addEventListener('click', () => saveStack(true));

  // Copy buttons
  document.getElementById('stack-compose-copy-btn')?.addEventListener('click', () => {
    const val = document.getElementById('stack-compose-editor')?.value || '';
    navigator.clipboard.writeText(val).then(() => showToast('Compose YAML copied to clipboard', 'info'));
  });

  document.getElementById('stack-env-copy-btn')?.addEventListener('click', () => {
    const val = document.getElementById('stack-env-editor')?.value || '';
    navigator.clipboard.writeText(val).then(() => showToast('.env copied to clipboard', 'info'));
  });

  document.getElementById('stack-compose-reset-btn')?.addEventListener('click', () => {
    if (_activeStackName) openStackModal(_activeStackName);
  });
}

export function closeStackModal() {
  const overlay = document.getElementById('stack-inspector-overlay');
  if (overlay) {
    overlay.style.display = 'none';
    overlay.classList.remove('open');
  }
}

export function switchStackTab(tabTarget) {
  const overlay = document.getElementById('stack-inspector-overlay');
  if (!overlay) return;

  overlay.querySelectorAll('.stack-tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === tabTarget));
  overlay.querySelectorAll('.stack-pane').forEach((p) => {
    const isTarget = p.id === `stack-pane-${tabTarget}`;
    p.style.display = isTarget ? 'flex' : 'none';
  });
}

export async function openStackModal(stackName) {
  initStackModal();

  _activeStackName = stackName;
  const overlay = document.getElementById('stack-inspector-overlay');
  const win = document.getElementById('stack-inspector-window');
  if (!overlay || !win) return;

  overlay.style.display = 'flex';
  overlay.classList.add('open');
  switchStackTab('compose');

  document.getElementById('stack-header-title').textContent = `Stack: ${stackName}`;
  document.getElementById('stack-header-status').style.display = 'none';
  document.getElementById('stack-compose-editor').value = 'Loading stack configuration...';
  document.getElementById('stack-env-editor').value = '';
  document.getElementById('stack-modal-msg').textContent = 'Fetching stack setup...';

  try {
    const data = await api.get(`/api/docker/stacks/${encodeURIComponent(stackName)}`);
    _activeStackDetails = data;
    renderStackDetails(data);
  } catch (err) {
    document.getElementById('stack-modal-msg').textContent = `Failed loading stack: ${err.message}`;
    showToast(`Failed loading stack: ${err.message}`, 'error');
  }
}

function renderStackDetails(data) {
  document.getElementById('stack-header-title').textContent = `Stack: ${data.name}`;

  // Origin pill
  const originEl = document.getElementById('stack-header-origin');
  if (originEl) {
    originEl.textContent = data.origin ? `${data.origin.toUpperCase()}` : 'COMPOSE';
  }

  // Status pill
  const statusEl = document.getElementById('stack-header-status');
  if (statusEl) {
    statusEl.style.display = 'inline-flex';
    statusEl.className = 'ci-state-pill';
    const isRunning = data.status === 'running';
    const isPartial = data.status === 'partial';
    statusEl.style.background = isRunning ? 'rgba(16,185,129,0.15)' : (isPartial ? 'rgba(245,158,11,0.15)' : 'rgba(239,68,68,0.15)');
    statusEl.style.color = isRunning ? '#10b981' : (isPartial ? '#f59e0b' : '#ef4444');
    statusEl.style.border = `1px solid ${isRunning ? 'rgba(16,185,129,0.3)' : (isPartial ? 'rgba(245,158,11,0.3)' : 'rgba(239,68,68,0.3)')}`;
    statusEl.textContent = `● ${data.running_count}/${data.total_count} Running`;
  }

  // Path label
  const pathLabel = document.getElementById('stack-path-label');
  if (pathLabel) {
    const displayPath = data.config_file || data.working_dir || (data.location_type === 'synthesized' ? 'Live Synthesized Specification' : 'Docker Compose Project');
    pathLabel.textContent = displayPath;
    pathLabel.title = displayPath;
  }

  // Services count
  const countEl = document.getElementById('stack-tab-services-count');
  if (countEl) {
    countEl.textContent = (data.containers || []).length;
  }

  // Fill textareas
  document.getElementById('stack-compose-editor').value = data.compose_yaml || '';
  document.getElementById('stack-env-editor').value = data.env_content || '';
  document.getElementById('stack-modal-msg').textContent = data.has_real_file ? 'Loaded from on-disk configuration' : 'Reconstructed live from running services';

  // Render Services list
  renderServicesList(data.containers || []);
}

function renderServicesList(containers) {
  const containerEl = document.getElementById('stack-services-list');
  if (!containerEl) return;

  if (!containers.length) {
    containerEl.innerHTML = '<div style="color:var(--muted); font-size:12px; grid-column:1/-1;">No active containers detected for this stack.</div>';
    return;
  }

  let html = '';
  containers.forEach((c) => {
    const isRunning = c.state === 'running';
    const stateBadge = isRunning
      ? '<span style="font-size:10px; color:#10b981; font-weight:700;">● Running</span>'
      : '<span style="font-size:10px; color:#ef4444; font-weight:700;">● Stopped</span>';

    const portsHtml = (c.ports || []).map((p) => {
      const hp = p.host_port ? `${p.host_port}➔` : '';
      return `<code style="font-size:9.5px; background:rgba(255,255,255,0.06); padding:1px 4px; border-radius:3px;">${hp}${p.container_port}/${p.proto}</code>`;
    }).join(' ') || '<span style="font-size:10px; color:var(--muted);">Host Network / None</span>';

    html += `
      <div class="drawer-card" style="padding:12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px; display:flex; flex-direction:column; gap:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="font-weight:700; color:#fff; font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            ${escapeHtml(c.service || c.name)}
          </div>
          <div>${stateBadge}</div>
        </div>

        <div style="font-size:10.5px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.image)}">
          🖼️ ${escapeHtml(c.image)}
        </div>

        <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
          <span style="font-size:10px; color:var(--muted);">Ports:</span>
          ${portsHtml}
        </div>

        <div style="display:flex; justify-content:flex-end; gap:6px; margin-top:4px;">
          ${c.webui_url ? `<a href="${escapeHtml(c.webui_url)}" target="_blank" rel="noopener noreferrer" class="btn-pill-toggle" style="font-size:10px; padding:2px 8px; text-decoration:none; color:var(--accent-cyan, #38bdf8);">🌐 WebUI</a>` : ''}
          <button class="btn-pill-toggle stack-inspect-container-btn" data-cid="${escapeHtml(c.id)}" style="font-size:10px; padding:2px 8px;">🔍 Inspect Container</button>
        </div>
      </div>
    `;
  });

  containerEl.innerHTML = html;

  containerEl.querySelectorAll('.stack-inspect-container-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cid = btn.dataset.cid;
      if (cid) openContainerModal(cid);
    });
  });
}

async function saveStack(redeployAfterSave = false) {
  if (!_activeStackName) return;

  const composeVal = document.getElementById('stack-compose-editor')?.value || '';
  const envVal = document.getElementById('stack-env-editor')?.value || '';
  const msgEl = document.getElementById('stack-modal-msg');

  if (msgEl) msgEl.textContent = 'Saving configuration...';

  try {
    const res = await api.post(`/api/docker/stacks/${encodeURIComponent(_activeStackName)}/save`, {
      compose_yaml: composeVal,
      env_content: envVal,
    });

    if (res.success) {
      showToast('Stack configuration saved successfully!', 'success');
      if (msgEl) msgEl.textContent = 'Configuration saved';

      if (redeployAfterSave) {
        await triggerStackAction('redeploy');
      }
    } else {
      if (msgEl) msgEl.textContent = `Error: ${res.error}`;
      showToast(res.error || 'Failed saving stack', 'error');
    }
  } catch (err) {
    if (msgEl) msgEl.textContent = `Error: ${err.message}`;
    showToast(`Save failed: ${err.message}`, 'error');
  }
}

async function triggerStackAction(action) {
  if (!_activeStackName) return;

  const msgEl = document.getElementById('stack-modal-msg');
  if (action === 'redeploy' || action === 'stop') {
    showToast(`Executing stack ${action}...`, 'info');
  }

  if (msgEl) msgEl.textContent = `Executing ${action}...`;

  try {
    const res = await api.post(`/api/docker/stacks/${encodeURIComponent(_activeStackName)}/action`, { action });
    if (res.success) {
      showToast(`Stack action '${action}' completed!`, 'success');
      if (msgEl) msgEl.textContent = `Action '${action}' successful`;
      // Refresh stack details
      await openStackModal(_activeStackName);
    } else {
      if (msgEl) msgEl.textContent = `Action failed: ${res.error}`;
      showToast(res.error || `Action '${action}' failed`, 'error');
    }
  } catch (err) {
    if (msgEl) msgEl.textContent = `Action error: ${err.message}`;
    showToast(`Stack action failed: ${err.message}`, 'error');
  }
}

export function openStackPickerModal(stacks = []) {
  initStackModal();
  let overlay = document.getElementById('stack-picker-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'stack-picker-overlay';
    overlay.className = 'smart-modal-backdrop';
    overlay.style.cssText = 'display:none; z-index:10020;';
    overlay.innerHTML = `
      <div id="stack-picker-window" class="smart-modal-window" style="width:620px; max-width:95vw; max-height:86vh; display:flex; flex-direction:column; overflow:hidden; box-shadow: 0 25px 70px rgba(0,0,0,0.85);">
        <!-- Header -->
        <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center; user-select:none; cursor:move;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:16px;">📁</span>
            <span style="font-weight:700; color:#fff; font-size:13.5px;">Docker Compose Stacks</span>
            <span id="stack-picker-badge" class="ci-badge" style="font-size:9.5px; padding:2px 7px; border-radius:4px; font-weight:700; background:rgba(14,165,233,0.15); color:var(--accent-cyan, #38bdf8); border:1px solid rgba(56,189,248,0.3);">0 Stacks</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn close-btn" id="stack-picker-close-btn" title="Close" aria-label="Close"></button>
          </div>
        </div>

        <!-- Toolbar & Filter -->
        <div style="padding:12px 16px; background:rgba(0,0,0,0.35); border-bottom:1px solid rgba(255,255,255,0.06); display:flex; flex-direction:column; gap:8px;">
          <div style="font-size:11.5px; color:var(--muted);">Select a Docker Compose stack to inspect services, modify setup YAML, or manage lifecycle:</div>
          <div style="position:relative; display:flex; align-items:center;">
            <span style="position:absolute; left:10px; font-size:12px; color:var(--muted); pointer-events:none;">🔍</span>
            <input type="text" id="stack-picker-search" placeholder="Filter stacks by name, service, or path..." class="tz-text-input" style="width:100%; padding:7px 10px 7px 30px; font-size:12px; background:rgba(0,0,0,0.4); border:1px solid rgba(255,255,255,0.12); border-radius:6px; color:#fff; outline:none; box-sizing:border-box;">
          </div>
        </div>

        <!-- Stacks List Container -->
        <div id="stack-picker-list" style="flex:1; overflow-y:auto; padding:12px 16px; display:flex; flex-direction:column; gap:8px; min-height:160px; max-height:450px;">
        </div>

        <!-- Footer -->
        <div style="padding:10px 16px; background:rgba(0,0,0,0.5); border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:11px; color:var(--muted); font-style:italic;">Click any stack card to open setup editor</span>
          <button class="btn-pill-toggle" id="stack-picker-cancel-btn">Cancel</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const closePicker = () => {
      overlay.style.display = 'none';
      overlay.classList.remove('open');
    };

    overlay.querySelector('#stack-picker-close-btn')?.addEventListener('click', closePicker);
    overlay.querySelector('#stack-picker-cancel-btn')?.addEventListener('click', closePicker);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closePicker();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && overlay.style.display !== 'none') {
        closePicker();
      }
    });
  }

  const badge = overlay.querySelector('#stack-picker-badge');
  if (badge) badge.textContent = `${stacks.length} Stack${stacks.length === 1 ? '' : 's'}`;

  const searchInput = overlay.querySelector('#stack-picker-search');
  const listContainer = overlay.querySelector('#stack-picker-list');

  const renderFilteredCards = (query = '') => {
    if (!listContainer) return;
    const filtered = stacks.filter((s) => {
      if (!query) return true;
      const matchName = (s.name || '').toLowerCase().includes(query);
      const matchPath = (s.working_dir || s.config_files || '').toLowerCase().includes(query);
      const matchServices = (s.services || []).some((svc) => (svc || '').toLowerCase().includes(query));
      return matchName || matchPath || matchServices;
    });

    if (filtered.length === 0) {
      listContainer.innerHTML = `
        <div style="text-align:center; padding:32px 16px; color:var(--muted); font-size:12px;">
          No Compose stacks match "${escapeHtml(query)}"
        </div>
      `;
      return;
    }

    listContainer.innerHTML = filtered.map((s) => {
      const isAllRunning = s.running_count === s.total_count && s.total_count > 0;
      const isNoneRunning = s.running_count === 0;

      let statusPill = '';
      if (isAllRunning) {
        statusPill = `<span style="display:inline-flex; align-items:center; gap:5px; font-size:10.5px; color:var(--ok2, #10b981); background:rgba(16,185,129,0.12); padding:2px 8px; border-radius:12px; border:1px solid rgba(16,185,129,0.3); font-weight:600;"><span style="width:6px; height:6px; border-radius:50%; background:var(--ok2, #10b981); box-shadow:0 0 6px var(--ok2, #10b981);"></span> ${s.running_count}/${s.total_count} Running</span>`;
      } else if (isNoneRunning) {
        statusPill = `<span style="display:inline-flex; align-items:center; gap:5px; font-size:10.5px; color:var(--muted); background:rgba(255,255,255,0.06); padding:2px 8px; border-radius:12px; border:1px solid rgba(255,255,255,0.1);"><span style="width:6px; height:6px; border-radius:50%; background:var(--muted);"></span> Stopped (${s.total_count})</span>`;
      } else {
        statusPill = `<span style="display:inline-flex; align-items:center; gap:5px; font-size:10.5px; color:var(--warn, #f5a623); background:rgba(245,166,35,0.12); padding:2px 8px; border-radius:12px; border:1px solid rgba(245,166,35,0.3); font-weight:600;"><span style="width:6px; height:6px; border-radius:50%; background:var(--warn, #f5a623); box-shadow:0 0 6px var(--warn, #f5a623);"></span> ${s.running_count}/${s.total_count} Running</span>`;
      }

      const servicesHtml = (s.services || []).slice(0, 6).map((svc) => `
        <span class="ci-badge" style="font-size:9.5px; padding:2px 6px; border-radius:4px; background:rgba(255,255,255,0.06); color:#cbd5e1; border:1px solid rgba(255,255,255,0.1); font-family:var(--font-mono, monospace);">${escapeHtml(svc)}</span>
      `).join('');

      const moreCount = (s.services || []).length > 6 ? ` <span style="font-size:9.5px; color:var(--muted);">+${s.services.length - 6} more</span>` : '';

      const pathStr = s.working_dir || s.config_files || 'Managed by Docker daemon';

      return `
        <div class="stack-picker-card" data-stack="${escapeHtml(s.name)}" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.09); border-radius:8px; padding:10px 14px; cursor:pointer; transition:all 0.16s cubic-bezier(0.16, 1, 0.3, 1); display:flex; flex-direction:column; gap:6px;">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
            <div style="display:flex; align-items:center; gap:8px; min-width:0;">
              <span style="font-size:14px;">📁</span>
              <strong style="font-size:13.5px; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(s.name)}</strong>
              <span class="ci-badge" style="font-size:9px; padding:1px 5px; border-radius:3px; background:rgba(14,165,233,0.12); color:var(--accent-cyan, #38bdf8); border:1px solid rgba(56,189,248,0.25); text-transform:uppercase;">${escapeHtml(s.origin || 'Compose')}</span>
            </div>
            ${statusPill}
          </div>
          <div style="font-size:11px; color:var(--muted); font-family:var(--font-mono, monospace); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            📂 ${escapeHtml(pathStr)}
          </div>
          ${servicesHtml ? `
            <div style="display:flex; align-items:center; flex-wrap:wrap; gap:4px; margin-top:2px;">
              <span style="font-size:10px; color:var(--muted); margin-right:2px;">Services:</span>
              ${servicesHtml}${moreCount}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');

    // Bind card clicks & hover effects
    listContainer.querySelectorAll('.stack-picker-card').forEach((card) => {
      card.addEventListener('mouseenter', () => {
        card.style.background = 'rgba(255,255,255,0.07)';
        card.style.borderColor = 'rgba(56,189,248,0.45)';
        card.style.transform = 'translateY(-1px)';
        card.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
      });
      card.addEventListener('mouseleave', () => {
        card.style.background = 'rgba(255,255,255,0.03)';
        card.style.borderColor = 'rgba(255,255,255,0.09)';
        card.style.transform = 'translateY(0)';
        card.style.boxShadow = 'none';
      });
      card.addEventListener('click', () => {
        const stackName = card.dataset.stack;
        if (stackName) {
          overlay.style.display = 'none';
          overlay.classList.remove('open');
          openStackModal(stackName);
        }
      });
    });
  };

  if (searchInput) {
    searchInput.value = '';
    searchInput.oninput = () => renderFilteredCards(searchInput.value.toLowerCase().trim());
  }

  renderFilteredCards();
  overlay.style.display = 'flex';
  overlay.classList.add('open');
  if (searchInput) {
    setTimeout(() => searchInput.focus(), 50);
  }
}

export function _resetStackModalForTesting() {
  _activeStackName = null;
  _activeStackDetails = null;
  const overlay = document.getElementById('stack-inspector-overlay');
  if (overlay) overlay.remove();
  const picker = document.getElementById('stack-picker-overlay');
  if (picker) picker.remove();
}
