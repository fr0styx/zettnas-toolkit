/**
 * ZettNAS Toolkit - Docker Stack Inspector & Setup Editor Subsystem
 * Allows users to inspect, modify, save, and redeploy Docker Compose stacks.
 * Hardware & OS agnostic.
 */

import { api } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';
import { escapeHtml, copyText } from '../utils.js';
import { DockManager, bringToFront } from './dock.js';
import { openContainerModal } from './container-modal.js';
import { lintCompose, composeRiskSummary } from '../compose-lint.js';

import { t } from '../i18n.js';
let _activeStackName = null;
let _activeStackDetails = null;
let _fromCopilot = false; // compose text came from an AI answer (AI-22)

export function initStackModal() {
  if (document.getElementById('stack-inspector-overlay')) return;

  const overlayHtml = `
    <div id="stack-inspector-overlay" class="smart-modal-backdrop" style="display:none; z-index:10015;">
      <div id="stack-inspector-window" class="smart-modal-window stack-inspector-window" style="width:840px; max-width:96vw; height:640px; max-height:92vh; display:flex; flex-direction:column;">
        
        <!-- Header -->
        <div id="stack-inspector-header" class="smart-modal-header" style="cursor:move; user-select:none; display:flex; justify-content:space-between; align-items:center;">
          <div style="display:flex; align-items:center; gap:8px; min-width:0;">
            <span style="font-size:16px;">📁</span>
            <span id="stack-header-title" style="font-weight:700; color:var(--lt-t-ffffffff, #fff); font-size:13.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Stack Inspector</span>
            <span id="stack-header-origin" class="ci-badge" style="font-size:var(--zn-fs-xs); padding:2px 7px; border-radius:4px; font-weight:700; background:rgba(14,165,233,0.15); color:var(--lt-ink-brand, var(--accent-cyan, #38bdf8)); border:1px solid rgba(56,189,248,0.3);">Compose Stack</span>
            <span id="stack-header-status" class="ci-state-pill" style="display:none;"></span>
          </div>
          <div class="os-window-controls" style="display:flex; gap:6px; align-items:center;">
            <button class="win-btn min-btn" id="stack-min-btn" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
            <button class="win-btn max-btn" id="stack-max-btn" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
            <button class="win-btn close-btn" id="stack-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Quick Actions Bar & Path Info -->
        <div style="padding:8px 14px; background:var(--lt-b-00000073, rgba(0,0,0,0.45)); border-bottom:1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06)); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div style="display:flex; align-items:center; gap:8px; font-size:var(--zn-fs-xs); color:var(--muted); min-width:0; overflow:hidden;">
            <span aria-hidden="true">📂</span>
            <span id="stack-path-label" style="font-family:var(--font-mono, monospace); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:420px;"></span>
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            <button class="btn-pill-toggle is-small" id="stack-action-start" style="color: var(--ok2, #10b981);">▶ Start</button>
            <button class="btn-pill-toggle is-danger is-small" id="stack-action-stop">⏹ Stop</button>
            <button class="btn-pill-toggle is-small" id="stack-action-restart">↻ Restart</button>
            <button class="btn-pill-toggle is-small" id="stack-action-redeploy" style="background: rgba(14,165,233,0.2); border-color: rgba(56,189,248,0.4); color: var(--lt-t-38bdf8ff, #38bdf8);">⬆️ Redeploy / Up</button>
          </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="ci-nav-tabs" style="display:flex; gap:4px; padding:8px 14px; background:var(--lt-b-0000004c, rgba(0,0,0,0.3)); border-bottom:1px solid var(--lt-r-ffffff14, rgba(255,255,255,0.08));">
          <button class="btn-pill-toggle stack-tab-btn active" data-tab="compose">📄 Compose Setup (compose.yaml)</button>
          <button class="btn-pill-toggle stack-tab-btn" data-tab="env">⚙️ Environment (.env)</button>
          <button class="btn-pill-toggle stack-tab-btn" data-tab="services">📦 Services & Containers (<span id="stack-tab-services-count">0</span>)</button>
        </div>

        <!-- Tab Content Panes -->
        <div class="stack-panes-container" style="flex:1; overflow-y:auto; padding:14px; box-sizing:border-box; display:flex; flex-direction:column;">
          
          <!-- 1. Compose Tab -->
          <div id="stack-pane-compose" class="stack-pane" style="display:flex; flex-direction:column; flex:1; gap:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-size:var(--zn-fs-xs); color:var(--muted);">Edit the Docker Compose YAML definition. Changes are applied when saved or redeployed.</span>
              <div style="display:flex; gap:6px;">
                <button class="btn-pill-toggle" id="stack-compose-copy-btn">📋 Copy YAML</button>
                <button class="btn-pill-toggle" id="stack-compose-reset-btn">↺ Reload</button>
              </div>
            </div>
            <div style="flex:1; min-height:280px; position:relative; background:var(--lt-b-080c14ff, #080c14); border:1px solid var(--lt-r-ffffff1f, rgba(255,255,255,0.12)); border-radius:6px; display:flex;">
              <textarea id="stack-compose-editor" spellcheck="false" style="flex:1; width:100%; height:100%; min-height:280px; background:transparent; border:none; outline:none; resize:none; padding:12px; color:var(--lt-t-f1f5f9ff, #f1f5f9); font-family:var(--font-mono, monospace); font-size:var(--zn-fs-xs); line-height:1.55; box-sizing:border-box; tab-size:2;"></textarea>
            </div>
          </div>

          <!-- 2. Env Tab -->
          <div id="stack-pane-env" class="stack-pane" style="display:none; flex-direction:column; flex:1; gap:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-size:var(--zn-fs-xs); color:var(--muted);">Environment variables (.env) passed into this compose stack during runtime.</span>
              <button class="btn-pill-toggle" id="stack-env-copy-btn">📋 Copy .env</button>
            </div>
            <div style="flex:1; min-height:280px; position:relative; background:var(--lt-b-080c14ff, #080c14); border:1px solid var(--lt-r-ffffff1f, rgba(255,255,255,0.12)); border-radius:6px; display:flex;">
              <textarea id="stack-env-editor" spellcheck="false" placeholder="# KEY=VALUE" style="flex:1; width:100%; height:100%; min-height:280px; background:transparent; border:none; outline:none; resize:none; padding:12px; color:var(--lt-t-f1f5f9ff, #f1f5f9); font-family:var(--font-mono, monospace); font-size:var(--zn-fs-xs); line-height:1.55; box-sizing:border-box;"></textarea>
            </div>
          </div>

          <!-- 3. Services Tab -->
          <div id="stack-pane-services" class="stack-pane" style="display:none; flex-direction:column; flex:1; gap:10px;">
            <div id="stack-services-list" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(340px, 1fr)); gap:10px;"></div>
          </div>

        </div>

        <!-- Footer Controls -->
        <div style="padding:10px 14px; background:var(--lt-b-00000080, rgba(0,0,0,0.5)); border-top:1px solid var(--lt-r-ffffff14, rgba(255,255,255,0.08)); display:flex; justify-content:space-between; align-items:center;">
          <div id="stack-modal-msg" style="font-size:var(--zn-fs-xs); color:var(--muted);"></div>
          <div style="display:flex; gap:8px;">
            <button class="btn-pill-toggle" id="stack-cancel-btn">Cancel</button>
            <button class="btn-pill-toggle" id="stack-save-btn" style="background: var(--lt-b-ffffff1a, rgba(255,255,255,0.1));">Save Configuration</button>
            <button class="btn-pill-toggle is-primary" id="stack-save-redeploy-btn">Save & Redeploy Stack</button>
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

  win.addEventListener('mousedown', () => bringToFront(win));

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
    copyText(val).then(() => showToast(t('toast.compose_yaml_copied_to_clipboard', 'Compose YAML copied to clipboard'), 'info'));
  });

  document.getElementById('stack-env-copy-btn')?.addEventListener('click', () => {
    const val = document.getElementById('stack-env-editor')?.value || '';
    copyText(val).then(() => showToast(t('toast.env_copied_to_clipboard', '.env copied to clipboard'), 'info'));
  });

  document.getElementById('stack-compose-reset-btn')?.addEventListener('click', () => {
    if (_activeStackName) openStackModal(_activeStackName);
  });
}

export function closeStackModal() {
  const overlay = document.getElementById('stack-inspector-overlay');
  const win = document.getElementById('stack-inspector-window');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.setProperty('display', 'none', 'important');
    if (win) {
      win.style.setProperty('display', 'none', 'important');
    }
  }
  if (DockManager && typeof DockManager.minimize === 'function') {
    DockManager.minimize('stack-inspector');
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

export async function openStackModal(stackName, initialYaml = null) {
  initStackModal();

  _activeStackName = typeof stackName === 'string' ? stackName : (stackName?.name || 'new-stack');
  _fromCopilot = initialYaml !== null;
  const overlay = document.getElementById('stack-inspector-overlay');
  const win = document.getElementById('stack-inspector-window');
  if (!overlay || !win) return;

  overlay.style.removeProperty('display');
  overlay.style.display = 'flex';
  overlay.classList.remove('window-minimized');
  overlay.classList.add('open');

  win.style.removeProperty('display');
  win.classList.remove('window-minimized');

  bringToFront(win);

  if (DockManager && typeof DockManager.restore === 'function') {
    DockManager.restore('stack-inspector');
  }

  overlay.style.display = 'flex';
  win.style.display = 'flex';

  switchStackTab('compose');

  if (initialYaml !== null) {
    document.getElementById('stack-header-title').textContent = `Deploy Stack: ${_activeStackName}`;
    const statusPill = document.getElementById('stack-header-status');
    if (statusPill) statusPill.style.display = 'none';
    const originPill = document.getElementById('stack-header-origin');
    if (originPill) originPill.textContent = 'COPILOT TEMPLATE';
    const pathLabel = document.getElementById('stack-path-label');
    if (pathLabel) pathLabel.textContent = t('ui.ready_to_deploy_via_compose', 'Ready to Deploy via Compose Engine');
    const composeEd = document.getElementById('stack-compose-editor');
    if (composeEd) composeEd.value = initialYaml;
    const envEd = document.getElementById('stack-env-editor');
    if (envEd) envEd.value = '';
    const msgEl = document.getElementById('stack-modal-msg');
    const risks = lintCompose(initialYaml);
    if (msgEl) {
      msgEl.textContent = risks.length
        ? `Review before deploying. This AI-written stack asks for host access:\n${composeRiskSummary(risks)}`
        : 'Loaded an AI-written Compose file. Review it, then click "Save & Redeploy Stack".';
      msgEl.style.whiteSpace = 'pre-line';
      msgEl.style.color = risks.some((r) => r.level === 'danger') ? '#fca5a5' : '';
    }
    return;
  }

  document.getElementById('stack-header-title').textContent = `Stack: ${_activeStackName}`;
  document.getElementById('stack-header-status').style.display = 'none';
  document.getElementById('stack-compose-editor').value = 'Loading stack configuration...';
  document.getElementById('stack-env-editor').value = '';
  document.getElementById('stack-modal-msg').textContent = t('ui.fetching_stack_setup', 'Fetching stack setup...');

  try {
    const data = await api.get(`/api/docker/stacks/${encodeURIComponent(_activeStackName)}`);
    _activeStackDetails = data;
    renderStackDetails(data);
  } catch (err) {
    document.getElementById('stack-modal-msg').textContent = `Failed loading stack: ${err.message}`;
    showToast(t('toast.failed_loading_stack', 'Failed loading stack: {error}', { error: err.message }), 'error');
  }
}

export function deployComposeStackSnippet(yamlCode) {
  if (!yamlCode) return;
  let deducedName = 'copilot-stack';
  const matchContainer = yamlCode.match(/container_name:\s*([a-zA-Z0-9_-]+)/);
  if (matchContainer && matchContainer[1]) {
    deducedName = matchContainer[1];
  } else {
    const matchService = yamlCode.match(/services:\s*\r?\n\s+([a-zA-Z0-9_-]+):/);
    if (matchService && matchService[1]) {
      deducedName = matchService[1];
    }
  }
  openStackModal(deducedName, yamlCode);
  showToast(t('toast.copilot_compose_stack_loaded_ready_to', 'Copilot Compose stack loaded. Ready to deploy!'), 'success');
}

if (typeof window !== 'undefined') {
  window.deployComposeStackSnippet = deployComposeStackSnippet;
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
    containerEl.innerHTML = '<div style="color:var(--muted); font-size:var(--zn-fs-xs); grid-column:1/-1;">No active containers detected for this stack.</div>';
    return;
  }

  let html = '';
  containers.forEach((c) => {
    const isRunning = c.state === 'running';
    const stateBadge = isRunning
      ? '<span style="font-size:var(--zn-fs-xs); color:var(--lt-t-10b981ff, #10b981); font-weight:700;">● Running</span>'
      : '<span style="font-size:var(--zn-fs-xs); color:var(--lt-t-ef4444ff, #ef4444); font-weight:700;">● Stopped</span>';

    const portsHtml = (c.ports || []).map((p) => {
      const hp = p.host_port ? `${p.host_port}➔` : '';
      return `<code style="font-size:var(--zn-fs-xs); background:var(--lt-b-ffffff0f, rgba(255,255,255,0.06)); padding:1px 4px; border-radius:3px;">${hp}${p.container_port}/${p.proto}</code>`;
    }).join(' ') || '<span style="font-size:var(--zn-fs-xs); color:var(--muted);">Host Network / None</span>';

    html += `
      <div class="drawer-card" style="padding:12px; background:var(--lt-b-ffffff08, rgba(255,255,255,0.03)); border:1px solid var(--lt-r-ffffff14, rgba(255,255,255,0.08)); border-radius:8px; display:flex; flex-direction:column; gap:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="font-weight:700; color:var(--lt-t-ffffffff, #fff); font-size:var(--zn-fs-xs); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            ${escapeHtml(c.service || c.name)}
          </div>
          <div>${stateBadge}</div>
        </div>

        <div style="font-size:var(--zn-fs-xs); color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.image)}">
          🖼️ ${escapeHtml(c.image)}
        </div>

        <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
          <span style="font-size:var(--zn-fs-xs); color:var(--muted);">Ports:</span>
          ${portsHtml}
        </div>

        <div style="display:flex; justify-content:flex-end; gap:6px; margin-top:4px;">
          ${c.webui_url ? `<a href="${escapeHtml(c.webui_url)}" target="_blank" rel="noopener noreferrer" class="btn-pill-toggle" style="font-size:var(--zn-fs-xs); padding:2px 8px; text-decoration:none; color:var(--lt-ink-brand, var(--accent-cyan, #38bdf8));">🌐 WebUI</a>` : ''}
          <button class="btn-pill-toggle stack-inspect-container-btn is-small" data-cid="${escapeHtml(c.id)}">🔍 Inspect Container</button>
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

  // AI-written compose files with host-level access need an explicit OK (AI-22).
  const risks = lintCompose(composeVal);
  if (_fromCopilot && risks.length) {
    const ok = await new Promise((resolve) => {
      showConfirmToast(
        'Deploy a stack with host access?',
        `This Compose file came from an AI answer and asks for:\n${composeRiskSummary(risks)}`,
        () => resolve(true),
        () => resolve(false),
      );
    });
    if (!ok) {
      if (msgEl) msgEl.textContent = t('ui.not_deployed', 'Not deployed.');
      return;
    }
  }

  if (msgEl) msgEl.textContent = t('ui.saving_configuration', 'Saving configuration...');

  try {
    const res = await api.post(`/api/docker/stacks/${encodeURIComponent(_activeStackName)}/save`, {
      compose_yaml: composeVal,
      env_content: envVal,
    });

    if (res.success) {
      showToast(t('toast.stack_configuration_saved_successfully', 'Stack configuration saved successfully!'), 'success');
      if (msgEl) msgEl.textContent = t('ui.configuration_saved', 'Configuration saved');

      if (redeployAfterSave) {
        await triggerStackAction('redeploy');
      }
    } else {
      if (msgEl) msgEl.textContent = `Error: ${res.error}`;
      showToast(res.error || 'Failed saving stack', 'error');
    }
  } catch (err) {
    if (msgEl) msgEl.textContent = `Error: ${err.message}`;
    showToast(t('toast.save_failed', 'Save failed: {error}', { error: err.message }), 'error');
  }
}

async function triggerStackAction(action) {
  if (!_activeStackName) return;

  const msgEl = document.getElementById('stack-modal-msg');
  if (action === 'redeploy' || action === 'stop') {
    showToast(t('toast.executing_stack', 'Executing stack {action}...', { action: action }), 'info');
  }

  if (msgEl) msgEl.textContent = `Executing ${action}...`;

  try {
    const res = await api.post(`/api/docker/stacks/${encodeURIComponent(_activeStackName)}/action`, { action });
    if (res.success) {
      showToast(t('toast.stack_action_completed', 'Stack action \'{action}\' completed!', { action: action }), 'success');
      if (msgEl) msgEl.textContent = `Action '${action}' successful`;
      // Refresh stack details
      await openStackModal(_activeStackName);
    } else {
      if (msgEl) msgEl.textContent = `Action failed: ${res.error}`;
      showToast(res.error || `Action '${action}' failed`, 'error');
    }
  } catch (err) {
    if (msgEl) msgEl.textContent = `Action error: ${err.message}`;
    showToast(t('toast.stack_action_failed', 'Stack action failed: {error}', { error: err.message }), 'error');
  }
}

export async function openStackPickerModal(stacksInput = null) {
  initStackModal();
  let stacks = Array.isArray(stacksInput) ? stacksInput : (stacksInput?.stacks || null);

  if (!stacks) {
    try {
      const res = await api.get('/api/docker/stacks');
      stacks = Array.isArray(res) ? res : (res?.stacks || []);
    } catch {
      stacks = [];
    }
  }
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
            <span style="font-weight:700; color:var(--lt-t-ffffffff, #fff); font-size:13.5px;">Docker Compose Stacks</span>
            <span id="stack-picker-badge" class="ci-badge" style="font-size:var(--zn-fs-xs); padding:2px 7px; border-radius:4px; font-weight:700; background:rgba(14,165,233,0.15); color:var(--lt-ink-brand, var(--accent-cyan, #38bdf8)); border:1px solid rgba(56,189,248,0.3);">0 Stacks</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn close-btn" id="stack-picker-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Toolbar & Filter -->
        <div style="padding:12px 16px; background:var(--lt-b-00000059, rgba(0,0,0,0.35)); border-bottom:1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06)); display:flex; flex-direction:column; gap:8px;">
          <div style="font-size:var(--zn-fs-xs); color:var(--muted);">Select a Docker Compose stack to inspect services, modify setup YAML, or manage lifecycle:</div>
          <div style="position:relative; display:flex; align-items:center;">
            <span style="position:absolute; left:10px; font-size:var(--zn-fs-xs); color:var(--muted); pointer-events:none;">🔍</span>
            <input type="text" id="stack-picker-search" placeholder="${t('ui.filter_stacks_by_name_service', 'Filter stacks by name, service, or path...')}" class="tz-text-input" style="width:100%; padding:7px 10px 7px 30px; font-size:var(--zn-fs-xs); background:var(--lt-b-00000066, rgba(0,0,0,0.4)); border:1px solid var(--lt-r-ffffff1f, rgba(255,255,255,0.12)); border-radius:6px; color:var(--lt-t-ffffffff, #fff); outline:none; box-sizing:border-box;">
          </div>
        </div>

        <!-- Stacks List Container -->
        <div id="stack-picker-list" style="flex:1; overflow-y:auto; padding:12px 16px; display:flex; flex-direction:column; gap:8px; min-height:160px; max-height:450px;">
        </div>

        <!-- Footer -->
        <div style="padding:10px 16px; background:var(--lt-b-00000080, rgba(0,0,0,0.5)); border-top:1px solid var(--lt-r-ffffff14, rgba(255,255,255,0.08)); display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:var(--zn-fs-xs); color:var(--muted); font-style:italic;">Click any stack card to open setup editor</span>
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
        <div style="text-align:center; padding:32px 16px; color:var(--muted); font-size:var(--zn-fs-xs);">
          No Compose stacks match "${escapeHtml(query)}"
        </div>
      `;
      return;
    }

    listContainer.innerHTML = filtered.map((s) => {
      const isAllRunning = s.running_count === s.total_count && s.total_count > 0;
      const isNoneRunning = s.running_count === 0;

      let statusPill;
      if (isAllRunning) {
        statusPill = `<span style="display:inline-flex; align-items:center; gap:5px; font-size:var(--zn-fs-xs); color:var(--ok2, #10b981); background:rgba(16,185,129,0.12); padding:2px 8px; border-radius:12px; border:1px solid rgba(16,185,129,0.3); font-weight:600;"><span style="width:6px; height:6px; border-radius:50%; background:var(--ok2, #10b981); box-shadow:0 0 6px var(--ok2, #10b981);"></span> ${s.running_count}/${s.total_count} Running</span>`;
      } else if (isNoneRunning) {
        statusPill = `<span style="display:inline-flex; align-items:center; gap:5px; font-size:var(--zn-fs-xs); color:var(--muted); background:var(--lt-b-ffffff0f, rgba(255,255,255,0.06)); padding:2px 8px; border-radius:12px; border:1px solid var(--lt-r-ffffff1a, rgba(255,255,255,0.1));"><span style="width:6px; height:6px; border-radius:50%; background:var(--muted);"></span> Stopped (${s.total_count})</span>`;
      } else {
        statusPill = `<span style="display:inline-flex; align-items:center; gap:5px; font-size:var(--zn-fs-xs); color:var(--warn, #f5a623); background:rgba(245,166,35,0.12); padding:2px 8px; border-radius:12px; border:1px solid rgba(245,166,35,0.3); font-weight:600;"><span style="width:6px; height:6px; border-radius:50%; background:var(--warn, #f5a623); box-shadow:0 0 6px var(--warn, #f5a623);"></span> ${s.running_count}/${s.total_count} Running</span>`;
      }

      const servicesHtml = (s.services || []).slice(0, 6).map((svc) => `
        <span class="ci-badge" style="font-size:var(--zn-fs-xs); padding:2px 6px; border-radius:4px; background:var(--lt-b-ffffff0f, rgba(255,255,255,0.06)); color:var(--lt-t-cbd5e1ff, #cbd5e1); border:1px solid var(--lt-r-ffffff1a, rgba(255,255,255,0.1)); font-family:var(--font-mono, monospace);">${escapeHtml(svc)}</span>
      `).join('');

      const moreCount = (s.services || []).length > 6 ? ` <span style="font-size:var(--zn-fs-xs); color:var(--muted);">+${s.services.length - 6} more</span>` : '';

      const pathStr = s.working_dir || s.config_files || 'Managed by Docker daemon';

      return `
        <div class="stack-picker-card" data-stack="${escapeHtml(s.name)}" style="background:var(--lt-b-ffffff08, rgba(255,255,255,0.03)); border:1px solid var(--lt-r-ffffff17, rgba(255,255,255,0.09)); border-radius:8px; padding:10px 14px; cursor:pointer; transition:all 0.16s cubic-bezier(0.16, 1, 0.3, 1); display:flex; flex-direction:column; gap:6px;">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
            <div style="display:flex; align-items:center; gap:8px; min-width:0;">
              <span style="font-size:14px;">📁</span>
              <strong style="font-size:13.5px; color:var(--lt-t-ffffffff, #fff); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(s.name)}</strong>
              <span class="ci-badge" style="font-size:var(--zn-fs-xs); padding:1px 5px; border-radius:3px; background:rgba(14,165,233,0.12); color:var(--lt-ink-brand, var(--accent-cyan, #38bdf8)); border:1px solid rgba(56,189,248,0.25); text-transform:uppercase;">${escapeHtml(s.origin || 'Compose')}</span>
            </div>
            ${statusPill}
          </div>
          <div style="font-size:var(--zn-fs-xs); color:var(--muted); font-family:var(--font-mono, monospace); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            📂 ${escapeHtml(pathStr)}
          </div>
          ${servicesHtml ? `
            <div style="display:flex; align-items:center; flex-wrap:wrap; gap:4px; margin-top:2px;">
              <span style="font-size:var(--zn-fs-xs); color:var(--muted); margin-right:2px;">Services:</span>
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
  overlay.style.removeProperty('display');
  overlay.style.display = 'flex';
  overlay.classList.add('open');
  if (searchInput) {
    setTimeout(() => searchInput.focus(), 50);
  }
}

export function _resetStackModalForTesting() {
  _activeStackName = null;
  _fromCopilot = false;
  _activeStackDetails = null;
  const overlay = document.getElementById('stack-inspector-overlay');
  if (overlay) overlay.remove();
  const picker = document.getElementById('stack-picker-overlay');
  if (picker) picker.remove();
}
