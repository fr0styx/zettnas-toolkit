/**
 * Kiboto - Docker Stack Inspector & Setup Editor Subsystem
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
import '../styles/stack-lazy.css'; // the inspector's own sheet loads with this code (NUX-15)

// An icon next to translated words: screen readers skip it (UX-35)
const ico = (e) => `<span aria-hidden="true">${e}</span>`;
let _activeStackName = null;
let _activeStackDetails = null;
let _fromCopilot = false; // compose text came from an AI answer (AI-22)

export function initStackModal() {
  if (document.getElementById('stack-inspector-overlay')) return;

  const overlayHtml = `
    <div id="stack-inspector-overlay" class="smart-modal-backdrop" style="display:none; z-index:10015;">
      <div id="stack-inspector-window" class="smart-modal-window stack-inspector-window stk-size" style="display: flex;">
        
        <!-- Header -->
        <div id="stack-inspector-header" class="smart-modal-header stk-x" style="display: flex;">
          <div class="stk-row">
            <span class="stk-fs16">📁</span>
            <span class="stk-fs135-bold-strong" id="stack-header-title">${t('stk.title', 'Stack Inspector')}</span>
            <span id="stack-header-origin" class="ci-badge" style="font-size:var(--zn-fs-xs); padding:2px 7px; border-radius:4px; font-weight:700; background:rgba(51,205,184,0.15); color:var(--lt-ink-brand, var(--accent-cyan, #4fd8c4)); border:1px solid rgba(79,216,196,0.3);">${t('stk.badge', 'Compose stack')}</span>
            <span id="stack-header-status" class="ci-state-pill" style="display:none;"></span>
          </div>
          <div class="os-window-controls stk-row-2">
            <button class="win-btn min-btn" id="stack-min-btn" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
            <button class="win-btn max-btn" id="stack-max-btn" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
            <button class="win-btn close-btn" id="stack-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Quick Actions Bar & Path Info -->
        <div style="padding:8px 14px; background:var(--lt-b-00000073, rgba(0,0,0,0.45)); border-bottom:1px solid var(--zn-line-6); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div class="stk-row-xs-muted">
            <span aria-hidden="true">📂</span>
            <span class="stk-mono" id="stack-path-label"></span>
          </div>
          <div class="stk-row-2">
            <button class="btn-pill-toggle is-small" id="stack-action-start" style="color: var(--ok2, #10b981);">${ico('▶')} ${t('vm.start', 'Start')}</button>
            <button class="btn-pill-toggle is-danger is-small" id="stack-action-stop">${ico('⏹')} ${t('stk.stop', 'Stop')}</button>
            <button class="btn-pill-toggle is-small" id="stack-action-restart">${ico('↻')} ${t('vmm.restart', 'Restart')}</button>
            <button class="btn-pill-toggle is-small" id="stack-action-redeploy" style="background: rgba(51,205,184,0.2); border-color: rgba(79,216,196,0.4); color: var(--zn-text-accent);">${ico('⬆️')} ${t('stk.redeploy', 'Redeploy')}</button>
          </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="ci-nav-tabs stk-row-box">
          <button class="btn-pill-toggle stack-tab-btn active" data-tab="compose">${ico('📄')} ${t('stk.tab_compose', 'Compose file (compose.yaml)')}</button>
          <button class="btn-pill-toggle stack-tab-btn" data-tab="env">${ico('⚙️')} ${t('stk.tab_env', 'Environment (.env)')}</button>
          <button class="btn-pill-toggle stack-tab-btn" data-tab="services">${ico('📦')} ${t('stk.tab_services', 'Services')} (<span id="stack-tab-services-count">0</span>)</button>
        </div>

        <!-- Tab Content Panes -->
        <div class="stack-panes-container stk-col">
          
          <!-- 1. Compose Tab -->
          <div id="stack-pane-compose" class="stack-pane stk-grow" style="display: flex;">
            <div class="stk-row-3">
              <span class="stk-xs-muted">${t('stk.compose_hint', 'Edit the Compose file. Changes apply when you save or redeploy.')}</span>
              <div class="stk-row-4">
                <button class="btn-pill-toggle" id="stack-compose-copy-btn">${ico('📋')} ${t('stk.copy_yaml', 'Copy YAML')}</button>
                <button class="btn-pill-toggle" id="stack-compose-reset-btn">${ico('↺')} ${t('stk.reload', 'Reload')}</button>
              </div>
            </div>
            <div style="flex:1; min-height:280px; position:relative; background:var(--lt-b-091213ff, #091213); border:1px solid var(--zn-line-12); border-radius:6px; display:flex;">
              <textarea class="stk-xs-mono-box-grow" id="stack-compose-editor" spellcheck="false"></textarea>
            </div>
          </div>

          <!-- 2. Env Tab -->
          <div id="stack-pane-env" class="stack-pane stk-grow" style="display: none;">
            <div class="stk-row-3">
              <span class="stk-xs-muted">${t('stk.env_hint', 'Environment variables (.env) the stack’s containers get when they start.')}</span>
              <button class="btn-pill-toggle" id="stack-env-copy-btn">${ico('📋')} ${t('stk.copy_env', 'Copy .env')}</button>
            </div>
            <div style="flex:1; min-height:280px; position:relative; background:var(--lt-b-091213ff, #091213); border:1px solid var(--zn-line-12); border-radius:6px; display:flex;">
              <textarea class="stk-xs-mono-box-grow-2" id="stack-env-editor" spellcheck="false" placeholder="# KEY=VALUE"></textarea>
            </div>
          </div>

          <!-- 3. Services Tab -->
          <div id="stack-pane-services" class="stack-pane stk-grow-2" style="display: none;">
            <div class="stk-x-2" id="stack-services-list" style="display: grid;"></div>
          </div>

        </div>

        <!-- Footer Controls -->
        <div style="padding:10px 14px; background:var(--lt-b-00000080, rgba(0,0,0,0.5)); border-top:1px solid var(--zn-line-8); display:flex; justify-content:space-between; align-items:center;">
          <div class="stk-xs-muted" id="stack-modal-msg"></div>
          <div class="stk-row-5">
            <button class="btn-pill-toggle" id="stack-cancel-btn">${t('common.cancel', 'Cancel')}</button>
            <button class="btn-pill-toggle stk-box" id="stack-save-btn">${t('stk.save', 'Save')}</button>
            <button class="btn-pill-toggle is-primary" id="stack-save-redeploy-btn">${t('stk.save_redeploy', 'Save and redeploy')}</button>
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
    DockManager.register('stack-inspector', overlay, '#i-grid', t('stk.title', 'Stack Inspector'), true);
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
    // closed, not just minimized: the dock and its Home button leave it alone until it is opened again
    if (DockManager.windows['stack-inspector']) DockManager.windows['stack-inspector'].closed = true;
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
    document.getElementById('stack-header-title').textContent = t('stk.deploy_title', 'Deploy stack: {name}', { name: _activeStackName });
    const statusPill = document.getElementById('stack-header-status');
    if (statusPill) statusPill.style.display = 'none';
    const originPill = document.getElementById('stack-header-origin');
    if (originPill) originPill.textContent = t('stk.from_ai', 'AI template');
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
        ? t('stk.review_risky', 'Review before deploying. This AI-written stack asks for host access:\n{risks}', { risks: composeRiskSummary(risks) })
        : t('stk.review', 'Loaded an AI-written Compose file. Review it, then click “Save and redeploy”.');
      msgEl.style.whiteSpace = 'pre-line';
      msgEl.style.color = risks.some((r) => r.level === 'danger') ? '#fca5a5' : '';
    }
    return;
  }

  document.getElementById('stack-header-title').textContent = t('stk.stack', 'Stack: {name}', { name: _activeStackName });
  document.getElementById('stack-header-status').style.display = 'none';
  document.getElementById('stack-compose-editor').value = t('stk.loading', 'Loading the stack…');
  document.getElementById('stack-env-editor').value = '';
  document.getElementById('stack-modal-msg').textContent = t('ui.fetching_stack_setup', 'Fetching stack setup...');

  try {
    const data = await api.get(`/api/docker/stacks/${encodeURIComponent(_activeStackName)}`);
    _activeStackDetails = data;
    renderStackDetails(data);
  } catch (err) {
    document.getElementById('stack-modal-msg').textContent = t('stk.load_failed', 'Could not load the stack: {error}', { error: err.message });
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
  showToast(t('toast.copilot_compose_stack_loaded_ready_to', 'The stack from Kib\'s answer is loaded. Check it, then deploy.'), 'success');
}

if (typeof window !== 'undefined') {
  window.deployComposeStackSnippet = deployComposeStackSnippet;
}

function renderStackDetails(data) {
  document.getElementById('stack-header-title').textContent = t('stk.stack', 'Stack: {name}', { name: data.name });

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
    statusEl.textContent = `● ${t('stk.running', '{running}/{total} Running', { running: data.running_count, total: data.total_count })}`;
  }

  // Path label
  const pathLabel = document.getElementById('stack-path-label');
  if (pathLabel) {
    const displayPath = data.config_file || data.working_dir || (data.location_type === 'synthesized' ? t('stk.synth', 'Rebuilt from the running containers') : t('stk.project', 'Docker Compose project'));
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
  document.getElementById('stack-modal-msg').textContent = data.has_real_file ? t('stk.from_disk', 'Loaded from the Compose file on disk') : t('stk.synth', 'Rebuilt from the running containers');

  // Render Services list
  renderServicesList(data.containers || []);
}

function renderServicesList(containers) {
  const containerEl = document.getElementById('stack-services-list');
  if (!containerEl) return;

  if (!containers.length) {
    containerEl.innerHTML = '<div class="stk-xs-muted-2">' + escapeHtml(t('stk.no_containers', 'No containers found for this stack.')) + '</div>';
    return;
  }

  let html = '';
  containers.forEach((c) => {
    const isRunning = c.state === 'running';
    const stateBadge = isRunning
      ? '<span style="font-size:var(--zn-fs-xs); color:var(--lt-t-10b981ff, #10b981); font-weight:700;">● ' + escapeHtml(t('stk.svc_running', 'Running')) + '</span>'
      : '<span style="font-size:var(--zn-fs-xs); color:var(--lt-t-ef4444ff, #ef4444); font-weight:700;">● ' + escapeHtml(t('stk.svc_stopped', 'Stopped')) + '</span>';

    const portsHtml = (c.ports || []).map((p) => {
      const hp = p.host_port ? `${p.host_port}➔` : '';
      return `<code class="stk-xs-box">${hp}${p.container_port}/${p.proto}</code>`;
    }).join(' ') || '<span class="stk-xs-muted">' + escapeHtml(t('stk.no_ports', 'Host network / none')) + '</span>';

    html += `
      <div class="drawer-card stk-col-box">
        <div class="stk-row-3">
          <div class="stk-xs-bold-strong">
            ${escapeHtml(c.service || c.name)}
          </div>
          <div>${stateBadge}</div>
        </div>

        <div class="stk-xs-muted-3" title="${escapeHtml(c.image)}">
          🖼️ ${escapeHtml(c.image)}
        </div>

        <div class="stk-row-6">
          <span class="stk-xs-muted">${t('stk.ports', 'Ports:')}</span>
          ${portsHtml}
        </div>

        <div class="stk-row-7">
          ${c.webui_url ? `<a href="${escapeHtml(c.webui_url)}" target="_blank" rel="noopener noreferrer" class="btn-pill-toggle" style="font-size:var(--zn-fs-xs); padding:2px 8px; text-decoration:none; color:var(--lt-ink-brand, var(--accent-cyan, #4fd8c4));">${ico('🌐')} ${t('stk.webui', 'Web UI')}</a>` : ''}
          <button class="btn-pill-toggle stack-inspect-container-btn is-small" data-cid="${escapeHtml(c.id)}">${ico('🔍')} ${t('stk.inspect', 'Container details')}</button>
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
        t('stk.risk_title', 'Deploy a stack with host access?'),
        t('stk.risk_msg', 'This Compose file came from an AI answer and asks for:\n{risks}', { risks: composeRiskSummary(risks) }),
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
      if (msgEl) msgEl.textContent = t('viso.error', 'Error: {error}', { error: res.error });
      showToast(res.error || t('stk.save_failed', 'Could not save the stack'), 'error');
    }
  } catch (err) {
    if (msgEl) msgEl.textContent = t('viso.error', 'Error: {error}', { error: err.message });
    showToast(t('toast.save_failed', 'Save failed: {error}', { error: err.message }), 'error');
  }
}

async function triggerStackAction(action) {
  if (!_activeStackName) return;

  const msgEl = document.getElementById('stack-modal-msg');
  if (action === 'redeploy' || action === 'stop') {
    showToast(t('toast.executing_stack', 'Executing stack {action}...', { action: action }), 'info');
  }

  if (msgEl) msgEl.textContent = t('stk.doing', 'Running “{action}”…', { action });

  try {
    const res = await api.post(`/api/docker/stacks/${encodeURIComponent(_activeStackName)}/action`, { action });
    if (res.success) {
      showToast(t('toast.stack_action_completed', 'Stack action \'{action}\' completed!', { action: action }), 'success');
      if (msgEl) msgEl.textContent = t('stk.done', '“{action}” done', { action });
      // Refresh stack details
      await openStackModal(_activeStackName);
    } else {
      if (msgEl) msgEl.textContent = t('stk.failed', '“{action}” failed: {error}', { action, error: res.error });
      showToast(res.error || t('stk.failed_short', '“{action}” failed', { action }), 'error');
    }
  } catch (err) {
    if (msgEl) msgEl.textContent = t('stk.failed', '“{action}” failed: {error}', { action, error: err.message });
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
        <div class="smart-modal-header stk-row-8">
          <div class="stk-row-9">
            <span class="stk-fs16">📁</span>
            <span class="stk-fs135-bold-strong-2">${t('stk.picker_title', 'Docker Compose stacks')}</span>
            <span id="stack-picker-badge" class="ci-badge" style="font-size:var(--zn-fs-xs); padding:2px 7px; border-radius:4px; font-weight:700; background:rgba(51,205,184,0.15); color:var(--lt-ink-brand, var(--accent-cyan, #4fd8c4)); border:1px solid rgba(79,216,196,0.3);">${t('stk.count', '{count, plural, one {# Stack} other {# Stacks}}', { count: 0 })}</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn close-btn" id="stack-picker-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Toolbar & Filter -->
        <div class="stk-col-box-2">
          <div class="stk-xs-muted">${t('stk.picker_hint', 'Pick a stack to see its services, edit its Compose file, or start and stop it:')}</div>
          <div class="stk-row-10">
            <span class="stk-xs-muted-4">🔍</span>
            <input type="text" id="stack-picker-search" placeholder="${t('ui.filter_stacks_by_name_service', 'Filter stacks by name, service, or path...')}" class="tz-text-input stk-xs-strong-box">
          </div>
        </div>

        <!-- Stacks List Container -->
        <div class="stk-grow-3" id="stack-picker-list" style="display: flex;">
        </div>

        <!-- Footer -->
        <div style="padding:10px 16px; background:var(--lt-b-00000080, rgba(0,0,0,0.5)); border-top:1px solid var(--zn-line-8); display:flex; justify-content:space-between; align-items:center;">
          <span class="stk-xs-muted-5">${t('stk.picker_foot', 'Click a stack to open it')}</span>
          <button class="btn-pill-toggle" id="stack-picker-cancel-btn">${t('common.cancel', 'Cancel')}</button>
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
  if (badge) badge.textContent = t('stk.count', '{count, plural, one {# Stack} other {# Stacks}}', { count: stacks.length });

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
        <div class="stk-xs-muted-center">
          ${escapeHtml(t('stk.no_match', 'No Compose stacks match "{q}"', { q: query }))}
        </div>
      `;
      return;
    }

    listContainer.innerHTML = filtered.map((s) => {
      const isAllRunning = s.running_count === s.total_count && s.total_count > 0;
      const isNoneRunning = s.running_count === 0;

      let statusPill;
      if (isAllRunning) {
        statusPill = `<span style="display:inline-flex; align-items:center; gap:5px; font-size:var(--zn-fs-xs); color:var(--ok2, #10b981); background:rgba(16,185,129,0.12); padding:2px 8px; border-radius:12px; border:1px solid rgba(16,185,129,0.3); font-weight:600;"><span style="width:6px; height:6px; border-radius:50%; background:var(--ok2, #10b981); box-shadow:0 0 6px var(--ok2, #10b981);"></span> ${t('stk.running', '{running}/{total} Running', { running: s.running_count, total: s.total_count })}</span>`;
      } else if (isNoneRunning) {
        statusPill = `<span class="stk-row-xs-muted-box"><span class="stk-box-2"></span> ${t('stk.stopped_n', 'Stopped ({count})', { count: s.total_count })}</span>`;
      } else {
        statusPill = `<span style="display:inline-flex; align-items:center; gap:5px; font-size:var(--zn-fs-xs); color:var(--warn, #f5a623); background:rgba(245,166,35,0.12); padding:2px 8px; border-radius:12px; border:1px solid rgba(245,166,35,0.3); font-weight:600;"><span style="width:6px; height:6px; border-radius:50%; background:var(--warn, #f5a623); box-shadow:0 0 6px var(--warn, #f5a623);"></span> ${t('stk.running', '{running}/{total} Running', { running: s.running_count, total: s.total_count })}</span>`;
      }

      const servicesHtml = (s.services || []).slice(0, 6).map((svc) => `
        <span class="ci-badge stk-xs-soft-mono-box">${escapeHtml(svc)}</span>
      `).join('');

      const moreCount = (s.services || []).length > 6 ? ` <span class="stk-xs-muted">${t('stk.more', '+{count} more', { count: s.services.length - 6 })}</span>` : '';

      const pathStr = s.working_dir || s.config_files || t('stk.daemon', 'Managed by Docker');

      return `
        <div class="stack-picker-card" data-stack="${escapeHtml(s.name)}" style="background:var(--zn-glaze-3); border:1px solid var(--lt-r-ffffff17, rgba(255,255,255,0.09)); border-radius:8px; padding:10px 14px; cursor:pointer; transition:all 0.16s cubic-bezier(0.16, 1, 0.3, 1); display:flex; flex-direction:column; gap:6px;">
          <div class="stk-row-11">
            <div class="stk-row">
              <span class="stk-fs14">📁</span>
              <strong class="stk-fs135-strong">${escapeHtml(s.name)}</strong>
              <span class="ci-badge" style="font-size:var(--zn-fs-xs); padding:1px 5px; border-radius:3px; background:rgba(51,205,184,0.12); color:var(--lt-ink-brand, var(--accent-cyan, #4fd8c4)); border:1px solid rgba(79,216,196,0.25); text-transform:uppercase;">${escapeHtml(s.origin || 'Compose')}</span>
            </div>
            ${statusPill}
          </div>
          <div class="stk-xs-muted-mono">
            📂 ${escapeHtml(pathStr)}
          </div>
          ${servicesHtml ? `
            <div class="stk-row-12">
              <span class="stk-xs-muted-6">${t('stk.services', 'Services:')}</span>
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
        card.style.borderColor = 'rgba(79,216,196,0.45)';
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
