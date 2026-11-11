/**
 * Kiboto - Virtual Machines (VM) Desktop Application & Manager
 * Features dynamic elastic headroom budgeting, vCPU overcommit soft warnings,
 * KVM hypervisor telemetry, and VM creation wizard.
 *
 * This module keeps the window, dashboard and VM grid; the dialogs, the console, the ISO
 * manager and snapshots live in ./vm/ (ARC-5) and are re-exported here under the same names.
 */

import { api } from '../api.js';
import { escapeHtml, reconcileKeyedTable } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast, showBottomSheet } from '../toast.js';
import { t } from '../i18n.js';
import { makeDraggable, bringToFront } from './dock.js';
import { vmState } from './vm/state.js';
import { openKvmDiagnosticsModal, openVmConnectModal, vmStateLabel } from './vm/connect-modal.js';
import { copyToClipboard, openVmConsole, openVmConsoleSeparateWindow } from './vm/console.js';
import { openVmCreateModal } from './vm/create-modal.js';
import { openQemuErrorModal, openVmEditModal } from './vm/edit-modal.js';
import { openIsoManagerModal } from './vm/iso-manager.js';
import { openVmSnapshotsModal } from './vm/snapshots.js';
import { askPower, isShuttingDown, needsWatching, powerToast, shuttingDownActionsHtml } from './vm/power.js';
import '../styles/vm-lazy.css'; // the VM windows' own sheet loads with this code (PERF-9)
export { kvmChecks, openKvmDiagnosticsModal, openVmConnectModal, vmStateLabel } from './vm/connect-modal.js';
import { formatFixed } from '../format.js';
export { applyTerminalStream, formatAnsiToHtml, parseAnsiToHtml } from './vm/console-ansi.js';
export { _activeRfb, _activeSerialWs, _consoleReconnectAttempts, _handleRfbKeyFallback, _reconnectTimer, _scheduleConsoleReconnect, _sendCtrlCToRfb, _sendKeyToRfb, _serialBuffers, cancelConsoleReconnect, clearConsoleReconnectTimer, copyToClipboard, focusActiveConsole, getActiveConsoleTarget, hideConsoleBanner, openVmConsole, openVmConsoleSeparateWindow, pasteTextToGuestConsole, serialKeyToData, setConsoleFocus, showConsoleBanner } from './vm/console.js';
export { openVmCreateModal } from './vm/create-modal.js';
export { openQemuErrorModal, openVmEditModal } from './vm/edit-modal.js';
export { OFFICIAL_ISO_CATALOG, openIsoManagerModal } from './vm/iso-manager.js';
export { openVmSnapshotsModal } from './vm/snapshots.js';

// An icon next to translated words: screen readers skip it (UX-35)
const ico = (e) => `<span aria-hidden="true">${e}</span>`;

export function initVmManager() {
  if (window._vmManagerInitialized) return;
  window._vmManagerInitialized = true;

  const vmIcon = document.getElementById('vm-desktop-icon');
  const openVm = (e) => {
    if (e && e.type === 'touchend') e.preventDefault();
    if (window.DockManager) {
      if (!window.DockManager.windows['vm']) {
        const win = document.getElementById('vm-manager-window');
        if (win) {
          window.DockManager.register('vm', win, '#i-vm', t('dock.vm_manager', 'Virtual Machines'));
        }
      }
      window.DockManager.restore('vm');
    }
    ZettEventBus.emit('window:open', { id: 'vm-manager-window' });
    loadVmDashboard();
  };

  if (vmIcon) {
    vmIcon.addEventListener('click', openVm);
    vmIcon.addEventListener('touchend', openVm);
    vmIcon.addEventListener('dblclick', openVm);
    vmIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openVm();
      }
    });
  }

  window.openVmManager = openVm;

  // Inject Window DOM if not already present
  if (!document.getElementById('vm-manager-window')) {
    const html = `
      <div id="vm-manager-window" class="os-window vm-manager-window" style="display: none; width: 920px; height: 600px; min-width: 640px; min-height: 420px;">
        <div class="os-window-header">
          <div class="os-window-title">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span data-i18n="dock.vm_manager">${t('dock.vm_manager', 'Virtual Machines')}</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn min-btn" id="vm-min" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
            <button class="win-btn max-btn" id="vm-max" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
            <button class="win-btn close-btn" id="vm-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Telemetry & Headroom Summary Header -->
        <div id="vm-telemetry-header" class="vm-telemetry-header vmm-box" style="display: flex;">
          <div class="vmm-row">
            <div id="vm-kvm-badge" style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: var(--zn-fs-xs); font-weight: 600; background: rgba(16,185,129,0.15); color: var(--zn-text-ok); border: 1px solid rgba(16,185,129,0.3);">
              <span aria-hidden="true">⚡</span> <span>${t('vmm.loading_kvm', 'Checking virtualization support…')}</span>
            </div>
            <div class="vm-action-btns-wrap vmm-row-2">
              <button id="btn-vm-refresh" class="btn-pill-toggle" title="${t('vm.refresh', 'Refresh')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <span data-i18n="vm.refresh">${t('vm.refresh', 'Refresh')}</span>
              </button>
              <button id="btn-vm-isos" class="btn-pill-toggle" title="${t('ui.iso_library_official_catalog', 'ISO Library & Official Catalog')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="5"/></svg>
                <span>${t('vmm.iso_library', 'ISO library')}</span>
              </button>
              <button id="btn-vm-create" class="btn-save-preset" style="background: var(--brand); border-color: rgba(51, 205, 184, 0.4); color: var(--accent-contrast-fg); font-weight: 700;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span data-i18n="vm.create_btn">${escapeHtml(t('vm.create_btn', 'Create Virtual Machine'))}</span>
              </button>
            </div>
          </div>

          <div class="vm-telemetry-budget-grid vmm-grid">
            <!-- Memory Budget Card -->
            <div class="vmm-box-2">
              <div class="vmm-row-xs">
                <span class="vmm-semi-muted" data-i18n="vm.host_reserve">${t('vm.host_reserve', 'Host Memory Reserve')} ${t('vmm.reserve_pct', '(10% of memory)')}</span>
                <span class="vmm-bold-accent" id="vm-headroom-text">--</span>
              </div>
              <div class="vmm-box-3" style="display: flex;" id="vm-memory-segments">
                <div id="vm-seg-running" style="width: 0%; background: #33cdb8; transition: width 0.3s;" title="${t('ui.running_vms', 'Running VMs')}"></div>
                <div id="vm-seg-reserve" style="width: 10%; background: #f59e0b; transition: width 0.3s;" title="${t('ui.host_reserve_protected', 'Host Reserve (Protected)')}"></div>
                <div id="vm-seg-headroom" style="width: 0%; background: #10b981; transition: width 0.3s;" title="${t('ui.available_safe_headroom', 'Available Safe Headroom')}"></div>
              </div>
              <div class="vmm-row-xs-muted">
                <span>${t('vmm.total_host', 'Total memory:')} <strong class="vmm-strong" id="vm-total-ram">--</strong></span>
                <span>${t('vmm.safe_ceiling', 'Safe limit for VMs:')} <strong class="vmm-ok" id="vm-safe-ceiling">--</strong></span>
              </div>
            </div>

            <!-- CPU Thread Overcommit Card -->
            <div class="vmm-box-2">
              <div class="vmm-row-xs">
                <span class="vmm-semi-muted">${t('vmm.vcpu_alloc', 'vCPU threads in use')}</span>
                <span id="vm-cpu-ratio-badge" style="font-size: var(--zn-fs-xs); padding: 1px 6px; border-radius: 4px; background: rgba(16,185,129,0.2); color: var(--zn-text-ok);">${t('vmm.ratio_default', '1:1 physical')}</span>
              </div>
              <div class="vmm-row-3">
                <span class="vmm-fs18-bold-strong" id="vm-cpu-allocated">0</span>
                <span class="vmm-xs-muted">/ <span id="vm-cpu-threads">8</span> ${t('vmm.host_threads', 'host threads')}</span>
              </div>
              <div class="vmm-xs-muted-2" id="vm-cpu-note">${t('ui.optimal_execution_dedicated_physical_thread', 'Optimal execution. Dedicated physical thread capacity per vCPU.')}</div>
            </div>
          </div>
        </div>

        <!-- VM Inventory Content -->
        <div class="vm-content-body vmm-grow" data-scrollable="true">
          <div class="vmm-fs13-muted-center" id="vm-empty-state" style="display: none;">
            <div class="vmm-muted">
              <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </div>
            <div class="vmm-semi-muted-2" data-i18n="vm.no_vms">${t('vm.no_vms', 'No virtual machines configured yet.')}</div>
            <button id="btn-vm-empty-create" class="btn-save-preset" style="background: var(--brand); border-color: rgba(51, 205, 184, 0.4); color: var(--accent-contrast-fg); margin: 0 auto;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span data-i18n="vm.create_btn">${escapeHtml(t('vm.create_btn', 'Create Virtual Machine'))}</span>
            </button>
          </div>
          <div class="vmm-x" id="vm-grid" style="display: grid;"></div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
  }

  vmState.window = document.getElementById('vm-manager-window');

  // Window Controls
  const minBtn = document.getElementById('vm-min');
  const maxBtn = document.getElementById('vm-max');
  const closeBtn = document.getElementById('vm-close');

  if (minBtn) {
    minBtn.onclick = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (vmState.window) {
        vmState.window.classList.add('window-minimized');
        vmState.window.classList.remove('open');
        vmState.window.style.setProperty('display', 'none', 'important');
      }
      if (window.DockManager) window.DockManager.minimize('vm');
    };
  }
  if (closeBtn) {
    closeBtn.onclick = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (vmState.window) {
        vmState.window.classList.add('window-minimized');
        vmState.window.classList.remove('open');
        vmState.window.style.setProperty('display', 'none', 'important');
      }
      if (window.DockManager) window.DockManager.closeWindow('vm');
    };
  }

  let _isMax = false;
  let _preMaxBounds = null;
  if (maxBtn) {
    maxBtn.onclick = () => {
      if (!_isMax) {
        _preMaxBounds = {
          left: vmState.window.style.left,
          top: vmState.window.style.top,
          width: vmState.window.style.width,
          height: vmState.window.style.height,
        };
        vmState.window.style.left = '0px';
        vmState.window.style.top = '36px';
        vmState.window.style.width = '100vw';
        vmState.window.style.height = 'calc(100vh - 36px - 72px)';
        _isMax = true;
      } else {
        if (_preMaxBounds) {
          vmState.window.style.left = _preMaxBounds.left;
          vmState.window.style.top = _preMaxBounds.top;
          vmState.window.style.width = _preMaxBounds.width;
          vmState.window.style.height = _preMaxBounds.height;
        }
        _isMax = false;
      }
    };
  }

  const btnCreate = document.getElementById('btn-vm-create');
  if (btnCreate) btnCreate.onclick = () => openVmCreateModal();

  const btnIsos = document.getElementById('btn-vm-isos');
  if (btnIsos) btnIsos.onclick = () => openIsoManagerModal('catalog');

  const btnEmptyCreate = document.getElementById('btn-vm-empty-create');
  if (btnEmptyCreate) btnEmptyCreate.onclick = () => openVmCreateModal();

  const btnRefresh = document.getElementById('btn-vm-refresh');
  if (btnRefresh) btnRefresh.onclick = () => loadVmDashboard();

  if (vmState.window) {
    makeDraggable(vmState.window, vmState.window.querySelector('.os-window-header'));
    vmState.window.addEventListener('mousedown', () => bringToFront(vmState.window));
  }
}

export async function loadVmDashboard() {
  try {
    const [tel, list, isos, bridges] = await Promise.all([
      api.get('/api/vms/telemetry'),
      api.get('/api/vms'),
      api.get('/api/vms/isos'),
      api.get('/api/vms/bridges'),
    ]);

    vmState.telemetry = tel;
    vmState.list = list || [];
    vmState.isos = isos || [];
    vmState.bridges = bridges || ['br0'];

    renderTelemetry(tel);
    renderVmGrid(vmState.list);
    watchShutdowns(vmState.list);
  } catch (err) {
    showToast(t('toast.failed_to_load_vm_data', 'Failed to load VM data: {error}', { error: err.message }), 'error');
  }
}

let _shutdownWatch = null;

/** While a machine shuts down the list is read again every five seconds, so the card changes by
 *  itself when the system inside has finished, and offers "Turn off now" when it has not. */
function watchShutdowns(vms) {
  if (_shutdownWatch) clearTimeout(_shutdownWatch);
  _shutdownWatch = null;
  const open = vmState.window && vmState.window.style.display !== 'none' && document.body.contains(vmState.window);
  if (!open || !needsWatching(vms)) return;
  _shutdownWatch = setTimeout(() => { _shutdownWatch = null; loadVmDashboard(); }, 5000);
}

function renderTelemetry(tel) {
  if (!tel) return;

  // KVM Badge
  const kvmBadge = document.getElementById('vm-kvm-badge');
  // The core image has no QEMU (OPS-11): say so instead of failing on start
  if (kvmBadge && tel.kvm && tel.kvm.qemu_available === false) {
    kvmBadge.textContent = `⚠️ ${t('vm.core_image', 'No VM support in the core image')}`;
    kvmBadge.title = t('vm.core_image_hint', 'Switch to the full image (tag latest instead of latest-core) to run virtual machines.');
    kvmBadge.style.cursor = 'default';
    kvmBadge.onclick = null;
    kvmBadge.style.background = 'rgba(245,158,11,0.15)';
    kvmBadge.style.color = '#fbbf24';
    kvmBadge.style.borderColor = 'rgba(245,158,11,0.3)';
  } else if (kvmBadge && tel.kvm) {
    kvmBadge.innerHTML = `<span aria-hidden="true">⚡</span> <span>${escapeHtml(tel.kvm.badge || 'KVM Active')}</span> <span class="vmm-xs" title="${t('ui.view_kvm_diagnostics_fix', 'View KVM Diagnostics & Fix')}">ℹ️</span>`;
    kvmBadge.style.cursor = 'pointer';
    kvmBadge.onclick = () => openKvmDiagnosticsModal(tel.kvm);
    if (tel.kvm.state === 'active') {
      kvmBadge.style.background = 'rgba(16,185,129,0.15)';
      kvmBadge.style.color = '#34d399';
      kvmBadge.style.borderColor = 'rgba(16,185,129,0.3)';
    } else if (tel.kvm.state === 'restricted') {
      kvmBadge.style.background = 'rgba(245,158,11,0.15)';
      kvmBadge.style.color = '#fbbf24';
      kvmBadge.style.borderColor = 'rgba(245,158,11,0.3)';
    } else {
      kvmBadge.style.background = 'rgba(239,68,68,0.15)';
      kvmBadge.style.color = '#f87171';
      kvmBadge.style.borderColor = 'rgba(239,68,68,0.3)';
    }
  }

  // Memory Segments
  const mem = tel.memory_budget;
  if (mem) {
    const total = mem.total_host_ram_gb || 32.0;
    const runningPct = Math.min(100, Math.round((mem.allocated_vm_ram_gb / total) * 100));
    const reservePct = Math.min(100, Math.round((mem.host_reserve_gb / total) * 100));
    const headroomPct = Math.max(0, 100 - runningPct - reservePct);

    const segRunning = document.getElementById('vm-seg-running');
    const segReserve = document.getElementById('vm-seg-reserve');
    const segHeadroom = document.getElementById('vm-seg-headroom');

    if (segRunning) segRunning.style.width = `${runningPct}%`;
    if (segReserve) segReserve.style.width = `${reservePct}%`;
    if (segHeadroom) segHeadroom.style.width = `${headroomPct}%`;

    const headroomTxt = document.getElementById('vm-headroom-text');
    if (headroomTxt) {
      headroomTxt.textContent = t('vmm.headroom', '{free} GB free for VMs ({used} GB in use)', { free: mem.safe_headroom_gb, used: mem.allocated_vm_ram_gb });
    }

    const totalRam = document.getElementById('vm-total-ram');
    if (totalRam) totalRam.textContent = `${mem.total_host_ram_gb} GB`;

    const safeCeiling = document.getElementById('vm-safe-ceiling');
    if (safeCeiling) safeCeiling.textContent = `${mem.safe_max_vm_ram_gb} GB`;
  }

  // CPU Capacity
  const cpu = tel.cpu_capacity;
  if (cpu) {
    const elAllocated = document.getElementById('vm-cpu-allocated');
    const elThreads = document.getElementById('vm-cpu-threads');
    const elRatioBadge = document.getElementById('vm-cpu-ratio-badge');
    const elNote = document.getElementById('vm-cpu-note');

    if (elAllocated) elAllocated.textContent = cpu.allocated_vcpus;
    if (elThreads) elThreads.textContent = cpu.host_threads;

    if (elRatioBadge) {
      elRatioBadge.textContent = cpu.badge || `${cpu.overcommit_ratio}x`;
      if (cpu.status === 'nominal') {
        elRatioBadge.style.background = 'rgba(16,185,129,0.2)';
        elRatioBadge.style.color = '#34d399';
        if (elNote) elNote.textContent = t('ui.optimal_execution_dedicated_physical_thread', 'Optimal execution. Dedicated physical thread capacity per vCPU.');
      } else if (cpu.status === 'moderate_overcommit') {
        elRatioBadge.style.background = 'rgba(245,158,11,0.2)';
        elRatioBadge.style.color = '#fbbf24';
        if (elNote) elNote.textContent = t('ui.moderate_overcommit_bursty_workloads_normal', 'Moderate overcommit. Bursty workloads normal; concurrent spikes may queue.');
      } else {
        elRatioBadge.style.background = 'rgba(239,68,68,0.2)';
        elRatioBadge.style.color = '#f87171';
        if (elNote) elNote.textContent = t('ui.high_thread_contention_risk_advised', 'High thread contention risk. Advised only for idle background appliances.');
      }
    }
  }
}

// Fields that change the card's layout or content. When none of these change,
// only the live CPU/RAM numbers are patched so popovers, focus and selection survive.
function vmCardStructKey(vm, vms) {
  return [
    vms.findIndex((v) => v.id === vm.id),
    vm.state,
    vm.qemu_pid,
    vm.name,
    vm.turn_off_offered,
    vm.description,
    vm.os_family,
    vm.boot_order,
    vm.iso_path,
    vm.ip_address,
    vm.vcpus,
    vm.ram_gb,
    vm.disk_size_gb,
    vm.disk_format,
    vm.bridge,
    vm.vnc_port,
    vm.ssh_port,
  ].join('|');
}

function vmCardFromHtml(html) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html.trim();
  return tpl.content.firstElementChild;
}

function patchVmCardTelemetry(card, vm) {
  const cpuUsagePct = vm.cpu_usage_pct !== undefined ? vm.cpu_usage_pct : 0.0;
  const ramUsagePct = vm.ram_usage_pct !== undefined ? vm.ram_usage_pct : 0.0;
  const ramUsedGb = formatFixed(parseFloat(vm.ram_gb || 2) * (parseFloat(ramUsagePct) / 100), 1);
  const vals = card.querySelectorAll('.vm-telemetry-row .telemetry-val');
  if (vals[0]) vals[0].textContent = `${cpuUsagePct}%`;
  if (vals[1]) vals[1].textContent = `${ramUsedGb} / ${vm.ram_gb} GB`;
  const cpuFill = card.querySelector('.vm-telemetry-row .fill-cpu');
  if (cpuFill) cpuFill.style.width = `${Math.min(100, Math.round(parseFloat(cpuUsagePct) * 4))}%`;
  const ramFill = card.querySelector('.vm-telemetry-row .fill-ram');
  if (ramFill) ramFill.style.width = `${Math.min(100, Math.round(ramUsagePct))}%`;
}

function renderVmGrid(vms) {
  const grid = document.getElementById('vm-grid');
  const emptyState = document.getElementById('vm-empty-state');
  if (!grid) return;

  if (!vms || vms.length === 0) {
    grid.innerHTML = '';
    if (emptyState) emptyState.style.display = 'block';
    return;
  }

  if (emptyState) emptyState.style.display = 'none';

  // Keyed reconciliation (AGENTS.md §1.3): keep each card node between refreshes,
  // rebuild a single card only when its structure changes.
  let needsBinding = false;
  reconcileKeyedTable(
    grid,
    vms,
    (vm) => vm.id,
    (vm) => {
      const card = vmCardFromHtml(buildVmCardHtml(vm, vms));
      card.dataset.structKey = vmCardStructKey(vm, vms);
      needsBinding = true;
      return card;
    },
    (card, vm) => {
      const structKey = vmCardStructKey(vm, vms);
      if (card.dataset.structKey === structKey) {
        patchVmCardTelemetry(card, vm);
        return;
      }
      const fresh = vmCardFromHtml(buildVmCardHtml(vm, vms));
      card.innerHTML = fresh.innerHTML;
      for (const { name, value } of Array.from(fresh.attributes)) card.setAttribute(name, value);
      card.dataset.structKey = structKey;
      needsBinding = true;
    },
  );

  if (needsBinding) bindVmGridHandlers(grid);
}

function buildVmCardHtml(vm, vms) {
      const stateKey = `${vm.state}|${vm.qemu_pid}|${vm.cpu_usage_pct}|${vm.ram_usage_pct}|${vm.ip_address}|${vm.vcpus}|${vm.ram_gb}|${vm.disk_size_gb}|${vm.name}`;
      const isRunning = vm.state === 'running';
      const isPaused = vm.state === 'paused';
      const isShutting = isShuttingDown(vm);
      const statusColor = isRunning ? '#34d399' : isPaused || isShutting ? '#fbbf24' : '#95a8ab';
      const statusBg = isRunning
        ? 'rgba(16,185,129,0.15)'
        : isPaused || isShutting
        ? 'rgba(245,158,11,0.15)'
        : 'rgba(255,255,255,0.06)';

      const stateBadge = `<span style="padding: 2px 7px; border-radius: 4px; font-size: var(--zn-fs-xs); font-weight: 700; background: ${statusBg}; color: ${statusColor}; text-transform: uppercase;">${escapeHtml(vmStateLabel(vm.state))}</span>`;

      const vncPort = vm.vnc_port || (5901 + (vms.findIndex((v) => v.id === vm.id) % 10));
      const vncDisplay = Math.max(1, vncPort - 5900);
      const hostIp = (typeof window !== 'undefined' && window.location && window.location.hostname) || 'localhost';
      const sshCmd = vm.ip_address ? `ssh root@${vm.ip_address}` : '';
      const vncUri = `vnc://${hostIp}:${vncPort}`;
      const qemuPid = vm.qemu_pid || null;
      const bootOrder = vm.boot_order || (vm.iso_path ? 'iso' : 'disk');
      const cpuUsagePct = vm.cpu_usage_pct !== undefined ? vm.cpu_usage_pct : 0.0;
      const ramUsagePct = vm.ram_usage_pct !== undefined ? vm.ram_usage_pct : 0.0;
      const ramUsedGb = formatFixed(parseFloat(vm.ram_gb || 2) * (parseFloat(ramUsagePct) / 100), 1);

      const osIcon =
        vm.os_family === 'windows'
          ? `<svg class="vmm-x-2" width="18" height="18" viewBox="0 0 24 24" fill="#4fd8c4"><path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.949-1.801"/></svg>`
          : vm.os_family === 'linux'
          ? `<svg class="vmm-x-2" width="18" height="18" viewBox="0 0 24 24" fill="#fbbf24"><path d="M12 2a5 5 0 0 0-5 5v3.1c-1.3.8-2 2-2 3.9 0 2.2 1.3 4 3 4.8V20a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-1.2c1.7-.8 3-2.6 3-4.8 0-1.9-.7-3.1-2-3.9V7a5 5 0 0 0-5-5zm-2 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm4 0a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/></svg>`
          : `<svg class="vmm-x-2" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#95a8ab" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`;

      return `
      <div class="glassmorphic-card" data-vm-id="${escapeHtml(vm.id)}" data-state-key="${escapeHtml(stateKey)}" style="border-radius: 10px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid var(--zn-line-8); background: var(--lt-b-132225a6, rgba(19, 34, 37, 0.65));">
        <div>
          <div class="vmm-row-4">
            <div class="vmm-row-5">
              ${osIcon}
              <div>
                <div class="vmm-fs13-bold-strong">${escapeHtml(vm.name)}</div>
                <div class="vmm-xs-muted">${escapeHtml(vm.description || t('vmm.appliance', 'Virtual machine'))}</div>
              </div>
            </div>
            <div class="vmm-row-6">
              ${
                bootOrder === 'disk'
                  ? `<span class="vm-boot-order-pill disk" title="${t('ui.boot_order_virtual_disk_first', 'Boot order: Virtual disk first')}">${ico('💽')} ${t('vmm.boot_disk', 'Disk')}</span>`
                  : `<span class="vm-boot-order-pill iso" title="${t('ui.boot_order_iso_installer_first', 'Boot order: ISO installer first')}">${ico('💿')} ${t('vmm.boot_iso', 'ISO first')}</span>`
              }
              ${
                isRunning || isShutting
                  ? `<span class="qemu-process-badge active" title="${t('ui.qemu_kvm_hypervisor_process_active', 'Virtual machine service running')}">${ico('●')} QEMU ${qemuPid ? `(${qemuPid})` : t('vmm.active', 'active')}</span>`
                  : isPaused
                  ? `<span class="qemu-process-badge paused" title="${t('ui.qemu_process_paused', 'QEMU process paused')}">${ico('⏸')} ${t('vmm.qemu_paused', 'QEMU paused')}</span>`
                  : `<span class="qemu-process-badge stopped" title="${t('ui.qemu_process_inactive', 'QEMU process inactive')}">${ico('○')} ${t('vmm.qemu_stopped', 'QEMU stopped')}</span>`
              }
              ${stateBadge}
            </div>
          </div>

          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; font-size: var(--zn-fs-xs); margin: 12px 0 8px; background: var(--zn-shade-30); padding: 8px; border-radius: 6px; border: 1px solid var(--lt-r-ffffff0a, rgba(255,255,255,0.04));">
            <div><span class="vmm-muted-2">${t('vm.compute', 'Compute')}:</span> <strong class="vmm-strong">${vm.vcpus} vCPUs</strong></div>
            <div><span class="vmm-muted-2">${t('vm.memory', 'Memory')}:</span> <strong class="vmm-accent">${vm.ram_gb} GB</strong></div>
            <div><span class="vmm-muted-2">${t('vm.disk', 'Disk')}:</span> <strong class="vmm-strong">${vm.disk_size_gb} GB (${vm.disk_format})</strong></div>
            <div><span class="vmm-muted-2">${t('vm.bridge', 'Bridge')}:</span> <strong class="vmm-strong">${escapeHtml(vm.bridge || 'br0')}</strong></div>
          </div>

          <!-- Real-time Live Resource Telemetry -->
          ${
            isRunning
              ? `
            <div class="vm-telemetry-row">
              <div class="vm-telemetry-item">
                <div class="vm-telemetry-header">
                  <span>${t('vmm.cpu_load', 'vCPU load')}</span>
                  <span class="telemetry-val">${cpuUsagePct}%</span>
                </div>
                <div class="vm-telemetry-progress"><div class="fill-cpu" style="width: ${Math.min(100, Math.round(parseFloat(cpuUsagePct) * 4))}%;"></div></div>
              </div>
              <div class="vm-telemetry-item">
                <div class="vm-telemetry-header">
                  <span>${t('vmm.ram_used', 'Memory used')}</span>
                  <span class="telemetry-val">${ramUsedGb} / ${vm.ram_gb} GB</span>
                </div>
                <div class="vm-telemetry-progress"><div class="fill-ram" style="width: ${Math.min(100, Math.round(ramUsagePct))}%;"></div></div>
              </div>
            </div>
          `
              : ''
          }

          <!-- Connection Info Bar with 1-Click Copy Buttons -->
          <div class="vmm-row-xs-box">
            <div class="vmm-row-xs-mono">
              <span style="color: var(--lt-t-f59e0bff, #f59e0b); display: inline-flex; align-items: center; gap: 3px;">
                <span>VNC :${vncDisplay}</span>
                <button class="btn-copy-vnc vmm-row-muted-box" data-uri="${escapeHtml(vncUri)}" title="${escapeHtml(t('vmm.copy_vnc', 'Copy the VNC address ({uri})', { uri: vncUri }))}">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </span>
              <span style="color: var(--lt-t-ffffff26, rgba(255,255,255,0.15));${sshCmd ? '' : ' display:none;'}">|</span>
              <span class="vmm-row-accent"${sshCmd ? '' : ' hidden'}>
                <span>${escapeHtml(sshCmd)}</span>
                <button class="btn-copy-ssh-cmd vmm-row-muted-box" data-cmd="${escapeHtml(sshCmd)}" title="${t('vm.copy_ssh', 'Copy SSH Command')}">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </span>
            </div>
            <button class="btn-vm-join-toggle" data-id="${vm.id}" style="background: rgba(51,205,184,0.15); border: 1px solid rgba(51,205,184,0.3); border-radius: 4px; color: var(--zn-text-accent); font-size: var(--zn-fs-xs); font-weight: 700; padding: 2px 6px; cursor: pointer; flex-shrink: 0;" title="${t('ui.join_vm_connection_options', 'Join VM connection options')}">
              ${t('vmm.join', 'Connect')} ${ico('▾')}
            </button>
          </div>

          ${
            vm.iso_path
              ? `
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: var(--zn-fs-xs); padding: 6px 10px; background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.3); border-radius: 4px; margin-bottom: 10px;">
              <span class="vmm-row-semi-warn">
                <span aria-hidden="true">💿</span>
                <span>${escapeHtml(t('vmm.iso_attached', 'ISO inserted ({name})', { name: vm.iso_path.split('/').pop() }))}</span>
              </span>
              <div class="vmm-row-7">
                <button class="btn-join-gui" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" style="background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); border-radius: 4px; color: var(--zn-text-warn); font-size: var(--zn-fs-xs); font-weight: 700; padding: 2px 8px; cursor: pointer;">
                  ${t('vmm.open_console', 'Open console')} ${ico('🖥️')}
                </button>
                <button class="btn-join-separate" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" data-mode="gui" style="background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); border-radius: 4px; color: var(--zn-text-warn); font-size: var(--zn-fs-xs); font-weight: 700; padding: 2px 6px; cursor: pointer;" title="${t('vm.open_separate', 'Open in Separate Window')}">
                  ↗
                </button>
              </div>
            </div>
          `
              : vm.ip_address
              ? `
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: var(--zn-fs-xs); padding: 4px 8px; background: rgba(51,205,184,0.1); border: 1px solid rgba(51,205,184,0.25); border-radius: 4px; margin-bottom: 10px; position: relative;">
              <span class="vmm-row-accent-mono">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                ${escapeHtml(vm.ip_address)}
              </span>
              <div class="vmm-row-8">
                <button class="btn-copy-ip vmm-row-muted-box-2" data-ip="${escapeHtml(vm.ip_address)}" title="${t('ui.copy_ip', 'Copy IP')}">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </div>

              <!-- Quick Connect Popover -->
              <div id="vm-join-popover-${vm.id}" class="vm-join-popover" style="display: none;">
                <div class="vmm-xs-bold-muted-box">${escapeHtml(t('vmm.connect_to', 'Connect to {name}', { name: vm.name }))}</div>
                <div class="join-popover-item btn-join-gui" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}">
                  <span>🖥️ ${t('vm.open_gui', 'Open KVM GUI Desktop (Display :0)')}</span>
                  <span class="vmm-xs-accent" translate="no">noVNC</span>
                </div>
                <div class="join-popover-item btn-join-separate" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" data-mode="gui">
                  <span>↗ ${t('vm.open_separate', 'Open in Separate Window')}</span>
                  <span class="vmm-xs-accent">${t('vmm.pop_out', 'Pop out')}</span>
                </div>
                <div class="join-popover-item btn-join-console" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}">
                  <span>📟 ${t('vm.open_serial', 'Open Serial Terminal (TTY)')}</span>
                  <span class="vmm-xs-ok" translate="no">TTY / CLI</span>
                </div>
                <div class="join-popover-item btn-join-web" data-ip="${escapeHtml(vm.ip_address)}">
                  <span>🌐 ${t('vm.open_web', 'Open Web UI (HTTP)')}</span>
                  <span style="font-size: var(--zn-fs-xs); color: var(--lt-t-a78bfaff, #a78bfa);">http://${escapeHtml(vm.ip_address)}</span>
                </div>
                <div class="join-popover-item btn-join-vnc" data-id="${vm.id}">
                  <span>🔗 ${t('vm.native_vnc', 'Native VNC Client (vnc://)')}</span>
                  <span style="font-size: var(--zn-fs-xs); color: var(--lt-t-f59e0bff, #f59e0b);">${t('vmm.port', 'Port {port}', { port: vncPort })}</span>
                </div>
                <div class="join-popover-item btn-join-rdp" data-ip="${escapeHtml(vm.ip_address)}">
                  <span>🪟 ${t('vm.rdp', 'Remote Desktop (RDP)')}</span>
                  <span class="vmm-xs-accent">${escapeHtml(vm.ip_address)}:3389</span>
                </div>
                <div class="join-popover-item btn-join-ssh" data-ip="${escapeHtml(vm.ip_address)}">
                  <span>💻 ${t('vm.copy_ssh', 'Copy SSH Command')}</span>
                  <span class="vmm-xs-accent-mono">${escapeHtml(sshCmd)}</span>
                </div>
                <div class="join-popover-item btn-join-ip" data-ip="${escapeHtml(vm.ip_address)}">
                  <span>📋 ${t('vm.copy_ip', 'Copy IP Address')}</span>
                  <span class="vmm-xs-accent-mono">${escapeHtml(vm.ip_address)}</span>
                </div>
                <div class="join-popover-item btn-join-details vmm-accent-box" data-id="${vm.id}">
                  <span>${ico('⚡')} ${t('vmm.drawer', 'All ways to connect…')}</span>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </div>
            </div>
          `
              : isRunning
              ? `
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: var(--zn-fs-xs); padding: 6px 10px; background: rgba(51,205,184,0.08); border: 1px solid rgba(51,205,184,0.2); border-radius: 4px; margin-bottom: 10px;">
              <span class="vmm-row-accent-2">
                <span aria-hidden="true">🖥️</span>
                <span>${t('vmm.console_active', 'Display is on')}</span>
              </span>
              <div class="vmm-row-7">
                <button class="btn-join-gui" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" style="background: rgba(51,205,184,0.2); border: 1px solid rgba(51,205,184,0.4); border-radius: 4px; color: var(--zn-text-accent); font-size: var(--zn-fs-xs); font-weight: 700; padding: 2px 8px; cursor: pointer;">
                  ${t('vmm.open_console', 'Open console')} ${ico('🖥️')}
                </button>
                <button class="btn-join-separate" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" data-mode="gui" style="background: rgba(51,205,184,0.2); border: 1px solid rgba(51,205,184,0.4); border-radius: 4px; color: var(--zn-text-accent); font-size: var(--zn-fs-xs); font-weight: 700; padding: 2px 6px; cursor: pointer;" title="${t('vm.open_separate', 'Open in Separate Window')}">
                  ↗
                </button>
              </div>
            </div>
          `
              : ''
          }
        </div>

        <div class="vm-card-actions vmm-row-box">
          ${isShutting ? shuttingDownActionsHtml(vm) : ''}
          ${
            !isRunning && !isPaused && !isShutting
              ? `
            <button class="btn-vm-action btn-vm-start vmm-grow-2" data-id="${vm.id}" data-act="start" title="${t('vm.start', 'Start')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('vm.start', 'Start')}</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${vm.id}" title="${t('ui.edit_vm_configuration', 'Edit VM Configuration')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>${t('vmm.edit', 'Edit')}</span>
            </button>
            <button class="btn-vm-action btn-vm-snapshots" data-id="${vm.id}" title="${t('vm.snapshots', 'Snapshots & Rollback')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>${t('vm.snapshots_short', 'Snapshots')}</span>
            </button>
            <button class="btn-vm-action btn-vm-delete" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" title="${t('vm.delete', 'Delete')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
              <span>${t('vm.delete', 'Delete')}</span>
            </button>
          `
              : ''
          }
          ${
            isRunning
              ? `
            <button class="btn-vm-action btn-vm-pause vmm-grow-2" data-id="${vm.id}" data-act="pause" title="${t('vm.pause', 'Pause')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
              <span>${t('vm.pause', 'Pause')}</span>
            </button>
            <button class="btn-vm-action btn-vm-restart vmm-grow-2" data-id="${vm.id}" data-act="restart" title="${t('ui.restart_vm', 'Restart VM')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
              <span>${t('vmm.restart', 'Restart')}</span>
            </button>
            <button class="btn-vm-action btn-vm-acpi vmm-grow-2" data-id="${vm.id}" data-act="stop" title="${t('ui.acpi_shutdown_graceful_power_off', 'ACPI Shutdown (Graceful Power Off)')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>${t('vmm.shutdown', 'Shut down')}</span>
            </button>
            <button class="btn-vm-action btn-vm-stop btn-vm-force-off vmm-grow-2" data-id="${vm.id}" data-act="force_off" title="${t('vmm.force_off', 'Turn off now (like pulling the plug)')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>${t('vmm.force_stop', 'Turn off now')}</span>
            </button>
            <button class="btn-vm-gui" data-id="${vm.id}" title="${t('vm.gui', 'KVM GUI')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              <span>${t('vm.gui', 'KVM GUI')}</span>
            </button>
            <button class="btn-vm-console" data-id="${vm.id}" title="${t('vm.console', 'Console')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
              <span>${t('vm.console', 'Console')}</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${vm.id}" title="${t('ui.edit_vm_configuration', 'Edit VM Configuration')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>${t('vmm.edit', 'Edit')}</span>
            </button>
            <button class="btn-vm-action btn-vm-snapshots" data-id="${vm.id}" title="${t('vm.snapshots', 'Snapshots & Rollback')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>${t('vm.snapshots_short', 'Snapshots')}</span>
            </button>
          `
              : ''
          }
          ${
            isPaused
              ? `
            <button class="btn-vm-action btn-vm-resume vmm-grow-2" data-id="${vm.id}" data-act="resume" title="${t('vm.resume', 'Resume')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('vm.resume', 'Resume')}</span>
            </button>
            <button class="btn-vm-action btn-vm-acpi vmm-grow-2" data-id="${vm.id}" data-act="stop" title="${t('ui.acpi_shutdown', 'ACPI Shutdown')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>${t('vmm.shutdown', 'Shut down')}</span>
            </button>
            <button class="btn-vm-action btn-vm-stop btn-vm-force-off vmm-grow-2" data-id="${vm.id}" data-act="force_off" title="${t('vmm.force_off', 'Turn off now (like pulling the plug)')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>${t('vmm.force_stop', 'Turn off now')}</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${vm.id}" title="${t('ui.edit_vm_configuration', 'Edit VM Configuration')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>${t('vmm.edit', 'Edit')}</span>
            </button>
            <button class="btn-vm-action btn-vm-snapshots" data-id="${vm.id}" title="${t('vm.snapshots', 'Snapshots & Rollback')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>${t('vm.snapshots_short', 'Snapshots')}</span>
            </button>
          `
              : ''
          }
          <button type="button" class="btn-vm-more-sheet" data-id="${vm.id}" title="${t('ui.more_actions', 'More Actions')}" style="display:none;">···</button>
        </div>
      </div>
    `;
}

// Handlers use `onclick =`, so re-running this on kept cards never double-binds.
function bindVmGridHandlers(grid) {
  // Attach Action Handlers
  grid.querySelectorAll('.btn-vm-more-sheet').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      const targetVm = vmState.list.find((v) => v.id === vmId);
      const name = targetVm ? targetVm.name : t('vmm.appliance', 'Virtual machine');
      const stateStr = (targetVm?.state || 'stopped').toLowerCase();
      const isRunning = stateStr === 'running';
      const isPaused = stateStr === 'paused';
      const card = btn.closest('[data-vm-id]'); // the menu's items click the card's own buttons
      const items = [];

      if (stateStr === 'shutting_down') {
        // nothing to press while the system inside finishes; after two minutes, "Turn off now"
        if (targetVm?.turn_off_offered) {
          items.push({ icon: '⏹️', label: t('vmm.force_off', 'Turn off now (like pulling the plug)'), destructive: true, onClick: () => card?.querySelector('.btn-vm-force-off')?.click() });
        }
        items.push({ icon: '📸', label: t('vm.snapshots', 'Snapshots & Rollback'), onClick: () => openVmSnapshotsModal(vmId) });
      } else if (isRunning) {
        items.push(
          { icon: '🖥️', label: t('vm.gui', 'KVM GUI'), onClick: () => openVmConsole(vmId, name, 'gui') },
          { icon: '⌨️', label: t('vm.console', 'Console (Serial TTY)'), onClick: () => openVmConsole(vmId, name, 'cli') },
          { icon: '📸', label: t('vm.snapshots', 'Snapshots & Rollback'), onClick: () => openVmSnapshotsModal(vmId) },
          { icon: '⏸️', label: t('vm.pause', 'Pause VM'), onClick: () => card?.querySelector('.btn-vm-pause')?.click() },
          { icon: '🔄', label: t('vmm.restart_vm', 'Restart VM'), onClick: () => card?.querySelector('.btn-vm-restart')?.click() },
          { icon: '⏻', label: t('vmm.acpi', 'Shut down (ACPI)'), onClick: () => card?.querySelector('.btn-vm-acpi')?.click() },
          { icon: '⏹️', label: t('vmm.force_off', 'Turn off now (like pulling the plug)'), destructive: true, onClick: () => card?.querySelector('.btn-vm-force-off')?.click() },
          { icon: '✏️', label: t('vmd.edit_settings', 'Edit VM settings'), onClick: () => openVmEditModal(vmId) }
        );
      } else if (isPaused) {
        items.push(
          { icon: '▶️', label: t('vm.resume', 'Resume VM'), onClick: () => card?.querySelector('.btn-vm-resume')?.click() },
          { icon: '📸', label: t('vm.snapshots', 'Snapshots & Rollback'), onClick: () => openVmSnapshotsModal(vmId) },
          { icon: '⏻', label: t('vmm.acpi', 'Shut down (ACPI)'), onClick: () => card?.querySelector('.btn-vm-acpi')?.click() },
          { icon: '⏹️', label: t('vmm.force_off', 'Turn off now (like pulling the plug)'), destructive: true, onClick: () => card?.querySelector('.btn-vm-force-off')?.click() },
          { icon: '✏️', label: t('vmd.edit_settings', 'Edit VM settings'), onClick: () => openVmEditModal(vmId) }
        );
      } else {
        items.push(
          { icon: '▶️', label: t('vmm.start_vm', 'Start VM'), onClick: () => card?.querySelector('.btn-vm-start')?.click() },
          { icon: '📸', label: t('vm.snapshots', 'Snapshots & Rollback'), onClick: () => openVmSnapshotsModal(vmId) },
          { icon: '✏️', label: t('vmd.edit_settings', 'Edit VM settings'), onClick: () => openVmEditModal(vmId) },
          { icon: '🗑️', label: t('vm.delete', 'Delete VM'), destructive: true, onClick: () => card?.querySelector('.btn-vm-delete')?.click() }
        );
      }

      showBottomSheet({
        title: name,
        subtitle: `${vmStateLabel(stateStr)} • ${targetVm?.vcpus || 2} vCPU • ${targetVm?.memory_mb || 2048} MB`,
        items,
      });
    };
  });

  grid.querySelectorAll('.btn-vm-action').forEach((btn) => {
    btn.onclick = async () => {
      const vmId = btn.dataset.id;
      const action = btn.dataset.act;
      const targetVm = vmState.list.find((v) => v.id === vmId);
      const name = targetVm ? targetVm.name : 'Virtual Machine';

      // Shut down, Turn off now and Restart are asked about first. "Shut down" used to end the
      // machine after two seconds; it now only asks the system inside (SET-07).
      askPower(action, name, async () => {
        try {
          const res = await api.post(`/api/vms/${vmId}/action`, { action });
          const said = powerToast(action, res?.state, name);
          showToast(said.text, said.tone);
          loadVmDashboard();
        } catch (err) {
          const errorDetail = err.detail || err.message || 'Unknown hypervisor error';
          if (action === 'start' || action === 'restart') {
            openQemuErrorModal(name, errorDetail, vmId);
          } else {
            showToast(t('toast.action_failed', 'Action failed: {errorDetail}', { errorDetail: errorDetail }), 'error');
          }
        }
      });
    };
  });

  grid.querySelectorAll('.btn-vm-edit').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      openVmEditModal(vmId);
    };
  });

  grid.querySelectorAll('.btn-vm-snapshots').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      openVmSnapshotsModal(vmId);
    };
  });

  grid.querySelectorAll('.btn-copy-vnc').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const uri = btn.dataset.uri;
      const ok = await copyToClipboard(uri);
      if (ok) {
        showToast(t('toast.copied_vnc_uri', 'Copied VNC URI \'{uri}\'', { uri: uri }), 'info');
      } else {
        showToast(t('toast.failed_to_copy_vnc_uri', `Failed to copy VNC URI`), 'error');
      }
    };
  });

  grid.querySelectorAll('.btn-copy-ssh-cmd').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const cmd = btn.dataset.cmd;
      const ok = await copyToClipboard(cmd);
      if (ok) {
        showToast(t('toast.copied_to_clipboard', 'Copied \'{cmd}\' to clipboard', { cmd: cmd }), 'info');
      } else {
        showToast(t('toast.failed_to_copy_ssh_command', `Failed to copy SSH command`), 'error');
      }
    };
  });

  grid.querySelectorAll('.btn-vm-delete').forEach((btn) => {
    btn.onclick = () => {
      const vmId = btn.dataset.id;
      const vmName = btn.dataset.name;
      showConfirmToast(
        t('vm.delete', 'Delete'),
        `${t('vm.delete_confirm', 'Are you sure you want to delete virtual machine')} '${vmName}'?`,
        async () => {
          try {
            await api.delete(`/api/vms/${vmId}`, { confirmed: true });
            showToast(t('toast.vm_deleted', 'VM \'{vmName}\' deleted', { vmName: vmName }), 'success');
            loadVmDashboard();
          } catch (err) {
            showToast(t('toast.delete_failed', 'Delete failed: {error}', { error: err.message }), 'error');
          }
        },
        null,
        { okText: t('vm.delete_vm', 'Delete VM'), destructive: true, typeToConfirm: vmName }
      );
    };
  });

  grid.querySelectorAll('.btn-copy-ip').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const ip = btn.dataset.ip;
      const ok = await copyToClipboard(ip);
      if (ok) {
        showToast(t('toast.copied_to_clipboard_4', 'Copied {ip} to clipboard', { ip: ip }), 'info');
      } else {
        showToast(t('toast.failed_to_copy_2', 'Failed to copy {ip}', { ip: ip }), 'error');
      }
    };
  });

  grid.querySelectorAll('.btn-vm-join-toggle').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      const popover = document.getElementById(`vm-join-popover-${vmId}`);
      if (popover) {
        const isHidden = popover.style.display === 'none';
        document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
        popover.style.display = isHidden ? 'flex' : 'none';
      }
    };
  });

  grid.querySelectorAll('.btn-join-ssh').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const ip = btn.dataset.ip;
      const cmd = `ssh root@${ip}`;
      const ok = await copyToClipboard(cmd);
      if (ok) {
        showToast(t('toast.copied_to_clipboard', 'Copied \'{cmd}\' to clipboard', { cmd: cmd }), 'info');
      }
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
    };
  });

  grid.querySelectorAll('.btn-join-ip').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const ip = btn.dataset.ip;
      const ok = await copyToClipboard(ip);
      if (ok) {
        showToast(t('toast.copied_to_clipboard_4', 'Copied {ip} to clipboard', { ip: ip }), 'info');
      }
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
    };
  });

  grid.querySelectorAll('.btn-join-separate').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      const targetVm = vmState.list.find((v) => v.id === vmId);
      const name = targetVm ? targetVm.name : (btn.dataset.name || 'Virtual Machine');
      const mode = btn.dataset.mode || 'gui';
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
      openVmConsoleSeparateWindow(vmId, name, mode);
    };
  });

  grid.querySelectorAll('.btn-vm-gui, .btn-join-gui').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      const targetVm = vmState.list.find((v) => v.id === vmId);
      const name = targetVm ? targetVm.name : (btn.dataset.name || 'Virtual Machine');
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
      openVmConsole(vmId, name, 'gui');
    };
  });

  grid.querySelectorAll('.btn-join-console, .btn-vm-console').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      const targetVm = vmState.list.find((v) => v.id === vmId);
      const name = targetVm ? targetVm.name : (btn.dataset.name || 'Virtual Machine');
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
      openVmConsole(vmId, name, 'cli');
    };
  });

  grid.querySelectorAll('.btn-join-web').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const ip = btn.dataset.ip;
      if (ip) {
        window.open(`http://${ip}`, '_blank');
      }
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
    };
  });

  grid.querySelectorAll('.btn-join-vnc').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      const port = 5900 + ((parseInt(vmId, 10) || 1) % 10);
      const uri = `vnc://${window.location.hostname || '127.0.0.1'}:${port}`;
      const ok = await copyToClipboard(uri);
      if (ok) {
        showToast(t('toast.copied_vnc_uri_for_native_client', 'Copied VNC URI \'{uri}\' for native client', { uri: uri }), 'info');
      }
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
    };
  });

  grid.querySelectorAll('.btn-join-rdp').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const ip = btn.dataset.ip;
      const uri = `${ip}:3389`;
      const ok = await copyToClipboard(uri);
      if (ok) {
        showToast(t('toast.copied_rdp_address_2', 'Copied RDP Address \'{uri}\'', { uri: uri }), 'info');
      }
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
    };
  });

  grid.querySelectorAll('.btn-join-details').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
      openVmConnectModal(vmId);
    };
  });

  if (!window._vmJoinDismissRegistered) {
    window._vmJoinDismissRegistered = true;
    document.addEventListener('click', () => {
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
    });
  }
}
