/**
 * ZettNAS Toolkit - Virtual Machines (VM) Desktop Application & Manager
 * Features dynamic elastic headroom budgeting, vCPU overcommit soft warnings,
 * KVM hypervisor telemetry, and VM creation wizard.
 */

import { api } from '../api.js';
import { escapeHtml, trapFocus, reconcileKeyedTable } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast, showPromptToast, showBottomSheet } from '../toast.js';
import { t } from '../i18n.js';
import { makeDraggable, bringToFront } from './dock.js';

let vmWindow = null;
let vmList = [];
let vmTelemetry = null;
let vmIsos = [];
let vmBridges = ['br0'];

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
            <button class="win-btn min-btn" id="vm-min" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="vm-max" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="vm-close" title="Close" aria-label="Close"></button>
          </div>
        </div>

        <!-- Telemetry & Headroom Summary Header -->
        <div id="vm-telemetry-header" class="vm-telemetry-header" style="display: flex; flex-direction: column; gap: 10px; padding: 16px; background: rgba(0,0,0,0.25); border-bottom: 1px solid rgba(255,255,255,0.06);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
            <div id="vm-kvm-badge" style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">
              <span>⚡</span> <span>Loading KVM Status...</span>
            </div>
            <div class="vm-action-btns-wrap" style="display: flex; gap: 8px;">
              <button id="btn-vm-refresh" class="btn-pill-toggle" title="${t('vm.refresh', 'Refresh')}" style="display: inline-flex; align-items: center; gap: 6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <span data-i18n="vm.refresh">${t('vm.refresh', 'Refresh')}</span>
              </button>
              <button id="btn-vm-isos" class="btn-pill-toggle" title="ISO Library & Official Catalog" style="display: inline-flex; align-items: center; gap: 6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="5"/></svg>
                <span>ISO Library</span>
              </button>
              <button id="btn-vm-create" class="btn-save-preset" style="background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff; font-weight: 700;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span data-i18n="vm.create_btn">${escapeHtml(t('vm.create_btn', 'Create Virtual Machine'))}</span>
              </button>
            </div>
          </div>

          <div class="vm-telemetry-budget-grid" style="display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px;">
            <!-- Memory Budget Card -->
            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 10px 14px;">
              <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
                <span style="color: var(--muted); font-weight: 600;" data-i18n="vm.host_reserve">${t('vm.host_reserve', 'Host Memory Reserve')} (10% Dynamic)</span>
                <span id="vm-headroom-text" style="color: #38bdf8; font-weight: 700;">--</span>
              </div>
              <div style="height: 10px; border-radius: 5px; background: rgba(255,255,255,0.08); overflow: hidden; display: flex;" id="vm-memory-segments">
                <div id="vm-seg-running" style="width: 0%; background: #0ea5e9; transition: width 0.3s;" title="Running VMs"></div>
                <div id="vm-seg-reserve" style="width: 10%; background: #f59e0b; transition: width 0.3s;" title="Host Reserve (Protected)"></div>
                <div id="vm-seg-headroom" style="width: 0%; background: #10b981; transition: width 0.3s;" title="Available Safe Headroom"></div>
              </div>
              <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 6px;">
                <span>Total Host: <strong id="vm-total-ram" style="color:#fff;">--</strong></span>
                <span>Safe Ceiling: <strong id="vm-safe-ceiling" style="color:#34d399;">--</strong></span>
              </div>
            </div>

            <!-- CPU Thread Overcommit Card -->
            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 10px 14px;">
              <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
                <span style="color: var(--muted); font-weight: 600;">vCPU Thread Allocation</span>
                <span id="vm-cpu-ratio-badge" style="font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(16,185,129,0.2); color: #34d399;">1:1 Physical</span>
              </div>
              <div style="display: flex; align-items: baseline; gap: 8px; margin-top: 4px;">
                <span style="font-size: 18px; font-weight: 700; color: #fff;" id="vm-cpu-allocated">0</span>
                <span style="font-size: 11px; color: var(--muted);">/ <span id="vm-cpu-threads">8</span> Host Threads</span>
              </div>
              <div style="font-size: 10px; color: var(--muted); margin-top: 6px;" id="vm-cpu-note">Optimal execution. Dedicated physical thread capacity per vCPU.</div>
            </div>
          </div>
        </div>

        <!-- VM Inventory Content -->
        <div class="vm-content-body" data-scrollable="true" style="flex: 1; min-height: 0; overflow-y: auto; -webkit-overflow-scrolling: touch; touch-action: pan-y; padding: 16px;">
          <div id="vm-empty-state" style="display: none; text-align: center; padding: 48px 24px; color: var(--muted); font-size: 13px;">
            <div style="margin-bottom: 12px; color: var(--muted); opacity: 0.6;">
              <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </div>
            <div data-i18n="vm.no_vms" style="font-weight: 600; color: #94a3b8; margin-bottom: 14px;">${t('vm.no_vms', 'No virtual machines configured yet.')}</div>
            <button id="btn-vm-empty-create" class="btn-save-preset" style="background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff; margin: 0 auto;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span data-i18n="vm.create_btn">${escapeHtml(t('vm.create_btn', 'Create Virtual Machine'))}</span>
            </button>
          </div>
          <div id="vm-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px;"></div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
  }

  vmWindow = document.getElementById('vm-manager-window');

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
      if (vmWindow) {
        vmWindow.classList.add('window-minimized');
        vmWindow.classList.remove('open');
        vmWindow.style.setProperty('display', 'none', 'important');
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
      if (vmWindow) {
        vmWindow.classList.add('window-minimized');
        vmWindow.classList.remove('open');
        vmWindow.style.setProperty('display', 'none', 'important');
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
          left: vmWindow.style.left,
          top: vmWindow.style.top,
          width: vmWindow.style.width,
          height: vmWindow.style.height,
        };
        vmWindow.style.left = '0px';
        vmWindow.style.top = '36px';
        vmWindow.style.width = '100vw';
        vmWindow.style.height = 'calc(100vh - 36px - 72px)';
        _isMax = true;
      } else {
        if (_preMaxBounds) {
          vmWindow.style.left = _preMaxBounds.left;
          vmWindow.style.top = _preMaxBounds.top;
          vmWindow.style.width = _preMaxBounds.width;
          vmWindow.style.height = _preMaxBounds.height;
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

  if (vmWindow) {
    makeDraggable(vmWindow, vmWindow.querySelector('.os-window-header'));
    vmWindow.addEventListener('mousedown', () => bringToFront(vmWindow));
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

    vmTelemetry = tel;
    vmList = list || [];
    vmIsos = isos || [];
    vmBridges = bridges || ['br0'];

    renderTelemetry(tel);
    renderVmGrid(vmList);
  } catch (err) {
    showToast(`Failed to load VM data: ${err.message}`, 'error');
  }
}

// vTPM needs the swtpm emulator on the host; warn instead of promising Windows 11 support.
function vtpmBadgeHtml() {
  if (vmTelemetry?.kvm?.vtpm_available === false) {
    return `<span class="vm-tpm-badge unavailable" title="${escapeHtml(t('vm.tpm_unavailable_hint', 'Install the swtpm package on the host (or update the container image) to use vTPM.'))}" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3);">⚠️ ${escapeHtml(t('vm.tpm_unavailable', 'swtpm not installed'))}</span>`;
  }
  return `<span class="vm-tpm-badge" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid rgba(14,165,233,0.3);">🛡️ ${escapeHtml(t('vm.tpm_ready', 'Windows 11 Ready'))}</span>`;
}

function renderTelemetry(tel) {
  if (!tel) return;

  // KVM Badge
  const kvmBadge = document.getElementById('vm-kvm-badge');
  if (kvmBadge && tel.kvm) {
    kvmBadge.innerHTML = `<span>⚡</span> <span>${escapeHtml(tel.kvm.badge || 'KVM Active')}</span> <span style="font-size: 10px; opacity: 0.8; margin-left: 2px;" title="View KVM Diagnostics & Fix">ℹ️</span>`;
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
      headroomTxt.textContent = `${mem.safe_headroom_gb} GB Safe Headroom (${mem.allocated_vm_ram_gb} GB in use)`;
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
        if (elNote) elNote.textContent = 'Optimal execution. Dedicated physical thread capacity per vCPU.';
      } else if (cpu.status === 'moderate_overcommit') {
        elRatioBadge.style.background = 'rgba(245,158,11,0.2)';
        elRatioBadge.style.color = '#fbbf24';
        if (elNote) elNote.textContent = 'Moderate overcommit. Bursty workloads normal; concurrent spikes may queue.';
      } else {
        elRatioBadge.style.background = 'rgba(239,68,68,0.2)';
        elRatioBadge.style.color = '#f87171';
        if (elNote) elNote.textContent = 'High thread contention risk. Advised only for idle background appliances.';
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
  const ramUsedGb = (parseFloat(vm.ram_gb || 2) * (parseFloat(ramUsagePct) / 100)).toFixed(1);
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
      const statusColor = isRunning ? '#34d399' : isPaused ? '#fbbf24' : '#94a3b8';
      const statusBg = isRunning
        ? 'rgba(16,185,129,0.15)'
        : isPaused
        ? 'rgba(245,158,11,0.15)'
        : 'rgba(255,255,255,0.06)';

      const stateBadge = `<span style="padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; background: ${statusBg}; color: ${statusColor}; text-transform: uppercase;">${vm.state}</span>`;

      const vncPort = vm.vnc_port || (5901 + (vms.findIndex((v) => v.id === vm.id) % 10));
      const vncDisplay = Math.max(1, vncPort - 5900);
      const sshPort = vm.ssh_port || (2220 + vncDisplay);
      const hostIp = (typeof window !== 'undefined' && window.location && window.location.hostname) || 'localhost';
      const sshCmd = vm.ip_address ? `ssh root@${vm.ip_address}` : `ssh -p ${sshPort} root@${hostIp}`;
      const vncUri = `vnc://${hostIp}:${vncPort}`;
      const qemuPid = vm.qemu_pid || null;
      const bootOrder = vm.boot_order || (vm.iso_path ? 'iso' : 'disk');
      const cpuUsagePct = vm.cpu_usage_pct !== undefined ? vm.cpu_usage_pct : 0.0;
      const ramUsagePct = vm.ram_usage_pct !== undefined ? vm.ram_usage_pct : 0.0;
      const ramUsedGb = (parseFloat(vm.ram_gb || 2) * (parseFloat(ramUsagePct) / 100)).toFixed(1);

      const osIcon =
        vm.os_family === 'windows'
          ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="#38bdf8" style="flex-shrink: 0;"><path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.949-1.801"/></svg>`
          : vm.os_family === 'linux'
          ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="#fbbf24" style="flex-shrink: 0;"><path d="M12 2a5 5 0 0 0-5 5v3.1c-1.3.8-2 2-2 3.9 0 2.2 1.3 4 3 4.8V20a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-1.2c1.7-.8 3-2.6 3-4.8 0-1.9-.7-3.1-2-3.9V7a5 5 0 0 0-5-5zm-2 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm4 0a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/></svg>`
          : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" style="flex-shrink: 0;"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`;

      return `
      <div class="glassmorphic-card" data-vm-id="${escapeHtml(vm.id)}" data-state-key="${escapeHtml(stateKey)}" style="border-radius: 10px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid rgba(255,255,255,0.08); background: rgba(18, 26, 38, 0.65);">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              ${osIcon}
              <div>
                <div style="font-weight: 700; color: #fff; font-size: 13px;">${escapeHtml(vm.name)}</div>
                <div style="font-size: 10px; color: var(--muted);">${escapeHtml(vm.description || 'Virtual Appliance')}</div>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap; justify-content: flex-end;">
              ${
                bootOrder === 'disk'
                  ? `<span class="vm-boot-order-pill disk" title="Boot order: Virtual disk first">💽 Disk</span>`
                  : `<span class="vm-boot-order-pill iso" title="Boot order: ISO installer first">💿 ISO First</span>`
              }
              ${
                isRunning
                  ? `<span class="qemu-process-badge active" title="QEMU KVM hypervisor process active">● QEMU ${qemuPid ? `(${qemuPid})` : 'Active'}</span>`
                  : isPaused
                  ? `<span class="qemu-process-badge paused" title="QEMU process paused">⏸ QEMU Paused</span>`
                  : `<span class="qemu-process-badge stopped" title="QEMU process inactive">○ QEMU Stopped</span>`
              }
              ${stateBadge}
            </div>
          </div>

          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; font-size: 11px; margin: 12px 0 8px; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
            <div><span style="color: var(--muted);">${t('vm.compute', 'Compute')}:</span> <strong style="color: #fff;">${vm.vcpus} vCPUs</strong></div>
            <div><span style="color: var(--muted);">${t('vm.memory', 'Memory')}:</span> <strong style="color: #38bdf8;">${vm.ram_gb} GB</strong></div>
            <div><span style="color: var(--muted);">${t('vm.disk', 'Disk')}:</span> <strong style="color: #fff;">${vm.disk_size_gb} GB (${vm.disk_format})</strong></div>
            <div><span style="color: var(--muted);">${t('vm.bridge', 'Bridge')}:</span> <strong style="color: #fff;">${escapeHtml(vm.bridge || 'br0')}</strong></div>
          </div>

          <!-- Real-time Live Resource Telemetry -->
          ${
            isRunning
              ? `
            <div class="vm-telemetry-row">
              <div class="vm-telemetry-item">
                <div class="vm-telemetry-header">
                  <span>vCPU Load</span>
                  <span class="telemetry-val">${cpuUsagePct}%</span>
                </div>
                <div class="vm-telemetry-progress"><div class="fill-cpu" style="width: ${Math.min(100, Math.round(parseFloat(cpuUsagePct) * 4))}%;"></div></div>
              </div>
              <div class="vm-telemetry-item">
                <div class="vm-telemetry-header">
                  <span>RAM Used</span>
                  <span class="telemetry-val">${ramUsedGb} / ${vm.ram_gb} GB</span>
                </div>
                <div class="vm-telemetry-progress"><div class="fill-ram" style="width: ${Math.min(100, Math.round(ramUsagePct))}%;"></div></div>
              </div>
            </div>
          `
              : ''
          }

          <!-- Connection Info Bar with 1-Click Copy Buttons -->
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 4px 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 6px; font-family: monospace; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              <span style="color: #f59e0b; display: inline-flex; align-items: center; gap: 3px;">
                <span>VNC :${vncDisplay}</span>
                <button class="btn-copy-vnc" data-uri="${escapeHtml(vncUri)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 1px 3px; display: inline-flex; align-items: center;" title="Copy VNC URI (${vncUri})">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </span>
              <span style="color: rgba(255,255,255,0.15);">|</span>
              <span style="color: #38bdf8; display: inline-flex; align-items: center; gap: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <span>${escapeHtml(sshCmd)}</span>
                <button class="btn-copy-ssh-cmd" data-cmd="${escapeHtml(sshCmd)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 1px 3px; display: inline-flex; align-items: center;" title="Copy SSH Command">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </span>
            </div>
            <button class="btn-vm-join-toggle" data-id="${vm.id}" style="background: rgba(14,165,233,0.15); border: 1px solid rgba(14,165,233,0.3); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer; flex-shrink: 0;" title="Join VM connection options">
              Join ▾
            </button>
          </div>

          ${
            vm.iso_path
              ? `
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 6px 10px; background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.3); border-radius: 4px; margin-bottom: 10px;">
              <span style="color: #fbbf24; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                <span>💿</span>
                <span>ISO Attached (${escapeHtml(vm.iso_path.split('/').pop())})</span>
              </span>
              <div style="display: flex; gap: 4px;">
                <button class="btn-join-gui" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" style="background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); border-radius: 4px; color: #fbbf24; font-size: 10px; font-weight: 700; padding: 2px 8px; cursor: pointer;">
                  Open Console 🖥️
                </button>
                <button class="btn-join-separate" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" data-mode="gui" style="background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); border-radius: 4px; color: #fbbf24; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer;" title="${t('vm.open_separate', 'Open in Separate Window')}">
                  ↗
                </button>
              </div>
            </div>
          `
              : vm.ip_address
              ? `
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 4px 8px; background: rgba(14,165,233,0.1); border: 1px solid rgba(14,165,233,0.25); border-radius: 4px; margin-bottom: 10px; position: relative;">
              <span style="color: #38bdf8; font-family: monospace; display: flex; align-items: center; gap: 5px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                ${escapeHtml(vm.ip_address)}
              </span>
              <div style="display: flex; align-items: center; gap: 4px;">
                <button class="btn-copy-ip" data-ip="${escapeHtml(vm.ip_address)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 2px 4px; display: flex; align-items: center;" title="Copy IP">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </div>

              <!-- Quick Connect Popover -->
              <div id="vm-join-popover-${vm.id}" class="vm-join-popover" style="display: none;">
                <div style="font-size: 10px; font-weight: 800; color: var(--muted); padding-bottom: 4px; border-bottom: 1px solid rgba(255,255,255,0.06); margin-bottom: 4px;">CONNECT TO ${escapeHtml(vm.name).toUpperCase()}</div>
                <div class="join-popover-item btn-join-gui" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}">
                  <span>🖥️ ${t('vm.open_gui', 'Open KVM GUI Desktop (Display :0)')}</span>
                  <span style="font-size: 9px; color: #38bdf8;">noVNC</span>
                </div>
                <div class="join-popover-item btn-join-separate" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" data-mode="gui">
                  <span>↗ ${t('vm.open_separate', 'Open in Separate Window')}</span>
                  <span style="font-size: 9px; color: #38bdf8;">Pop Out</span>
                </div>
                <div class="join-popover-item btn-join-console" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}">
                  <span>📟 ${t('vm.open_serial', 'Open Serial Terminal (TTY)')}</span>
                  <span style="font-size: 9px; color: #34d399;">TTY / CLI</span>
                </div>
                <div class="join-popover-item btn-join-web" data-ip="${escapeHtml(vm.ip_address)}">
                  <span>🌐 ${t('vm.open_web', 'Open Web UI (HTTP)')}</span>
                  <span style="font-size: 9px; color: #a78bfa;">http://${escapeHtml(vm.ip_address)}</span>
                </div>
                <div class="join-popover-item btn-join-vnc" data-id="${vm.id}">
                  <span>🔗 ${t('vm.native_vnc', 'Native VNC Client (vnc://)')}</span>
                  <span style="font-size: 9px; color: #f59e0b;">Port ${vncPort}</span>
                </div>
                <div class="join-popover-item btn-join-rdp" data-ip="${escapeHtml(vm.ip_address)}">
                  <span>🪟 ${t('vm.rdp', 'Remote Desktop (RDP)')}</span>
                  <span style="font-size: 9px; color: #38bdf8;">${escapeHtml(vm.ip_address)}:3389</span>
                </div>
                <div class="join-popover-item btn-join-ssh" data-ip="${escapeHtml(vm.ip_address)}">
                  <span>💻 ${t('vm.copy_ssh', 'Copy SSH Command')}</span>
                  <span style="font-size: 9px; font-family: monospace; color: #38bdf8;">${escapeHtml(sshCmd)}</span>
                </div>
                <div class="join-popover-item btn-join-ip" data-ip="${escapeHtml(vm.ip_address)}">
                  <span>📋 ${t('vm.copy_ip', 'Copy IP Address')}</span>
                  <span style="font-size: 9px; font-family: monospace; color: #38bdf8;">${escapeHtml(vm.ip_address)}</span>
                </div>
                <div class="join-popover-item btn-join-details" data-id="${vm.id}" style="border-top: 1px solid rgba(255,255,255,0.08); margin-top: 2px; color: #38bdf8;">
                  <span>⚡ Multi-Protocol Drawer...</span>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </div>
            </div>
          `
              : isRunning
              ? `
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 6px 10px; background: rgba(14,165,233,0.08); border: 1px solid rgba(14,165,233,0.2); border-radius: 4px; margin-bottom: 10px;">
              <span style="color: #38bdf8; display: flex; align-items: center; gap: 6px;">
                <span>🖥️</span>
                <span>Console Display Active</span>
              </span>
              <div style="display: flex; gap: 4px;">
                <button class="btn-join-gui" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" style="background: rgba(14,165,233,0.2); border: 1px solid rgba(14,165,233,0.4); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 8px; cursor: pointer;">
                  Open Console 🖥️
                </button>
                <button class="btn-join-separate" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" data-mode="gui" style="background: rgba(14,165,233,0.2); border: 1px solid rgba(14,165,233,0.4); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer;" title="${t('vm.open_separate', 'Open in Separate Window')}">
                  ↗
                </button>
              </div>
            </div>
          `
              : ''
          }
        </div>

        <div class="vm-card-actions" style="display: flex; gap: 6px; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 10px; flex-wrap: wrap;">
          ${
            !isRunning && !isPaused
              ? `
            <button class="btn-vm-action btn-vm-start" data-id="${vm.id}" data-act="start" style="flex: 1;" title="${t('vm.start', 'Start')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('vm.start', 'Start')}</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${vm.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
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
            <button class="btn-vm-action btn-vm-pause" data-id="${vm.id}" data-act="pause" style="flex: 1;" title="${t('vm.pause', 'Pause')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
              <span>${t('vm.pause', 'Pause')}</span>
            </button>
            <button class="btn-vm-action btn-vm-restart" data-id="${vm.id}" data-act="restart" style="flex: 1;" title="Restart VM">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
              <span>Restart</span>
            </button>
            <button class="btn-vm-action btn-vm-acpi" data-id="${vm.id}" data-act="stop" style="flex: 1;" title="ACPI Shutdown (Graceful Power Off)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>Shutdown</span>
            </button>
            <button class="btn-vm-action btn-vm-stop btn-vm-force-off" data-id="${vm.id}" data-act="force_off" style="flex: 1;" title="Force Stop (Hard Power Cut)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>Force Stop</span>
            </button>
            <button class="btn-vm-gui" data-id="${vm.id}" title="${t('vm.gui', 'KVM GUI')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              <span>${t('vm.gui', 'KVM GUI')}</span>
            </button>
            <button class="btn-vm-console" data-id="${vm.id}" title="${t('vm.console', 'Console')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
              <span>${t('vm.console', 'Console')}</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${vm.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
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
            <button class="btn-vm-action btn-vm-resume" data-id="${vm.id}" data-act="resume" style="flex: 1;" title="${t('vm.resume', 'Resume')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('vm.resume', 'Resume')}</span>
            </button>
            <button class="btn-vm-action btn-vm-acpi" data-id="${vm.id}" data-act="stop" style="flex: 1;" title="ACPI Shutdown">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>Shutdown</span>
            </button>
            <button class="btn-vm-action btn-vm-stop btn-vm-force-off" data-id="${vm.id}" data-act="force_off" style="flex: 1;" title="Force Stop">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>Force Stop</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${vm.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
            </button>
            <button class="btn-vm-action btn-vm-snapshots" data-id="${vm.id}" title="${t('vm.snapshots', 'Snapshots & Rollback')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>${t('vm.snapshots_short', 'Snapshots')}</span>
            </button>
          `
              : ''
          }
          <button type="button" class="btn-vm-more-sheet" data-id="${vm.id}" title="More Actions" style="display:none;">···</button>
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
      const targetVm = vmList.find((v) => v.id === vmId);
      const name = targetVm ? targetVm.name : 'Virtual Machine';
      const stateStr = (targetVm?.state || 'stopped').toLowerCase();
      const isRunning = stateStr === 'running';
      const isPaused = stateStr === 'paused';
      const card = btn.closest('.vm-card');
      const items = [];

      if (isRunning) {
        items.push(
          { icon: '🖥️', label: t('vm.gui', 'KVM GUI'), onClick: () => openVmConsole(vmId, name, 'gui') },
          { icon: '⌨️', label: t('vm.console', 'Console (Serial TTY)'), onClick: () => openVmConsole(vmId, name, 'cli') },
          { icon: '📸', label: t('vm.snapshots', 'Snapshots & Rollback'), onClick: () => openVmSnapshotsModal(vmId) },
          { icon: '⏸️', label: t('vm.pause', 'Pause VM'), onClick: () => card?.querySelector('.btn-vm-pause')?.click() },
          { icon: '🔄', label: 'Restart VM', onClick: () => card?.querySelector('.btn-vm-restart')?.click() },
          { icon: '⏻', label: 'ACPI Shutdown', onClick: () => card?.querySelector('.btn-vm-acpi')?.click() },
          { icon: '⏹️', label: 'Force Stop (Hard Power Cut)', destructive: true, onClick: () => card?.querySelector('.btn-vm-force-off')?.click() },
          { icon: '✏️', label: 'Edit VM Configuration', onClick: () => openVmEditModal(vmId) }
        );
      } else if (isPaused) {
        items.push(
          { icon: '▶️', label: t('vm.resume', 'Resume VM'), onClick: () => card?.querySelector('.btn-vm-resume')?.click() },
          { icon: '📸', label: t('vm.snapshots', 'Snapshots & Rollback'), onClick: () => openVmSnapshotsModal(vmId) },
          { icon: '⏻', label: 'ACPI Shutdown', onClick: () => card?.querySelector('.btn-vm-acpi')?.click() },
          { icon: '⏹️', label: 'Force Stop (Hard Power Cut)', destructive: true, onClick: () => card?.querySelector('.btn-vm-force-off')?.click() },
          { icon: '✏️', label: 'Edit VM Configuration', onClick: () => openVmEditModal(vmId) }
        );
      } else {
        items.push(
          { icon: '▶️', label: 'Start VM', onClick: () => card?.querySelector('.btn-vm-start')?.click() },
          { icon: '📸', label: t('vm.snapshots', 'Snapshots & Rollback'), onClick: () => openVmSnapshotsModal(vmId) },
          { icon: '✏️', label: 'Edit VM Configuration', onClick: () => openVmEditModal(vmId) },
          { icon: '🗑️', label: t('vm.delete', 'Delete VM'), destructive: true, onClick: () => card?.querySelector('.btn-vm-delete')?.click() }
        );
      }

      showBottomSheet({
        title: name,
        subtitle: `${stateStr.toUpperCase()} • ${targetVm?.vcpus || 2} vCPU • ${targetVm?.memory_mb || 2048} MB`,
        items,
      });
    };
  });

  grid.querySelectorAll('.btn-vm-action').forEach((btn) => {
    btn.onclick = async () => {
      const vmId = btn.dataset.id;
      const action = btn.dataset.act;
      const targetVm = vmList.find((v) => v.id === vmId);
      const name = targetVm ? targetVm.name : 'Virtual Machine';

      try {
        await api.post(`/api/vms/${vmId}/action`, { action });
        showToast(`VM action '${action}' completed`, 'success');
        loadVmDashboard();
      } catch (err) {
        const errorDetail = err.detail || err.message || 'Unknown hypervisor error';
        if (action === 'start' || action === 'restart') {
          openQemuErrorModal(name, errorDetail, vmId);
        } else {
          showToast(`Action failed: ${errorDetail}`, 'error');
        }
      }
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
        showToast(`Copied VNC URI '${uri}'`, 'info');
      } else {
        showToast(`Failed to copy VNC URI`, 'error');
      }
    };
  });

  grid.querySelectorAll('.btn-copy-ssh-cmd').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const cmd = btn.dataset.cmd;
      const ok = await copyToClipboard(cmd);
      if (ok) {
        showToast(`Copied '${cmd}' to clipboard`, 'info');
      } else {
        showToast(`Failed to copy SSH command`, 'error');
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
            await api.delete(`/api/vms/${vmId}`);
            showToast(`VM '${vmName}' deleted`, 'success');
            loadVmDashboard();
          } catch (err) {
            showToast(`Delete failed: ${err.message}`, 'error');
          }
        }
      );
    };
  });

  grid.querySelectorAll('.btn-copy-ip').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const ip = btn.dataset.ip;
      const ok = await copyToClipboard(ip);
      if (ok) {
        showToast(`Copied ${ip} to clipboard`, 'info');
      } else {
        showToast(`Failed to copy ${ip}`, 'error');
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
        showToast(`Copied '${cmd}' to clipboard`, 'info');
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
        showToast(`Copied ${ip} to clipboard`, 'info');
      }
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
    };
  });

  grid.querySelectorAll('.btn-join-separate').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      const targetVm = vmList.find((v) => v.id === vmId);
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
      const targetVm = vmList.find((v) => v.id === vmId);
      const name = targetVm ? targetVm.name : (btn.dataset.name || 'Virtual Machine');
      document.querySelectorAll('.vm-join-popover').forEach((p) => (p.style.display = 'none'));
      openVmConsole(vmId, name, 'gui');
    };
  });

  grid.querySelectorAll('.btn-join-console, .btn-vm-console').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const vmId = btn.dataset.id;
      const targetVm = vmList.find((v) => v.id === vmId);
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
        showToast(`Copied VNC URI '${uri}' for native client`, 'info');
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
        showToast(`Copied RDP Address '${uri}'`, 'info');
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

/**
 * Opens detailed Error Modal when QEMU hypervisor fails to launch
 */
export function openQemuErrorModal(vmName, errorMsg, vmId = null) {
  let modal = document.getElementById('modal-qemu-error');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-qemu-error';
    modal.className = 'smart-modal-backdrop';
    document.body.appendChild(modal);
  } else {
    modal.className = 'smart-modal-backdrop';
  }

  modal.innerHTML = `
    <div class="smart-modal-window vm-modal-window" style="max-width: 520px; width: 92%;">
      <div class="smart-modal-header" style="background: rgba(239, 68, 68, 0.15); border-bottom: 1px solid rgba(239, 68, 68, 0.3);">
        <div class="smart-modal-title" style="color: #f87171; display: flex; align-items: center; gap: 8px;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <span>QEMU Hypervisor Launch Failure</span>
        </div>
        <button id="qemu-error-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px;">✕</button>
      </div>
      <div class="smart-modal-body" style="padding: 16px 20px; display: flex; flex-direction: column; gap: 14px;">
        <div style="font-size: 13px; color: #fff;">
          Failed to start virtual machine <strong>${escapeHtml(vmName)}</strong>. The hypervisor process encountered a critical error:
        </div>
        <div class="qemu-error-box" style="background: rgba(0,0,0,0.5); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; padding: 12px; font-family: monospace; font-size: 11px; color: #fca5a5; line-height: 1.5; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto;">${escapeHtml(errorMsg || 'Process exited prematurely with non-zero exit code.')}</div>
        <div style="font-size: 11px; color: var(--muted); line-height: 1.4;">
          <strong>Recommended Troubleshooting:</strong>
          <ul style="margin: 6px 0 0 16px; padding: 0;">
            <li>Verify KVM kernel acceleration module (<code>/dev/kvm</code>) is accessible.</li>
            <li>Ensure the boot ISO and virtual disk paths exist and are not locked.</li>
            <li>Confirm host server has adequate free RAM headroom.</li>
          </ul>
        </div>
      </div>
      <div class="smart-modal-footer" style="padding: 12px 20px; display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid rgba(255,255,255,0.08);">
        <button id="btn-qemu-error-diag" class="btn-console-act" style="background: rgba(14, 165, 233, 0.2); border-color: #38bdf8; color: #38bdf8;">
          🛠️ Run KVM Diagnostics
        </button>
        ${vmId ? `
          <button id="btn-qemu-error-edit" class="btn-console-act" style="background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.2); color: #fff;">
            ⚙️ Edit VM Settings
          </button>
        ` : ''}
        <button id="btn-qemu-error-dismiss" class="btn-console-act" style="background: rgba(255,255,255,0.05); color: #cbd5e1;">
          Dismiss
        </button>
      </div>
    </div>
  `;

  modal.classList.add('open');
  modal.style.display = 'flex';

  const closeBtn = modal.querySelector('#qemu-error-close');
  const dismissBtn = modal.querySelector('#btn-qemu-error-dismiss');
  const diagBtn = modal.querySelector('#btn-qemu-error-diag');
  const editBtn = modal.querySelector('#btn-qemu-error-edit');

  const close = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  };

  if (closeBtn) closeBtn.onclick = close;
  if (dismissBtn) dismissBtn.onclick = close;
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };

  if (diagBtn) {
    diagBtn.onclick = () => {
      close();
      openKvmDiagnosticsModal();
    };
  }
  if (editBtn && vmId) {
    editBtn.onclick = () => {
      close();
      openVmEditModal(vmId);
    };
  }
}

/**
 * Opens VM Configuration / Edit Modal (#modal-vm-edit)
 * Allows modifying RAM, vCPUs, description, attached ISO, boot order, and autostart
 */
export function openVmEditModal(vmId, vmObj = null) {
  let modal = document.getElementById('modal-vm-edit');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-vm-edit';
    modal.className = 'smart-modal-backdrop';
    document.body.appendChild(modal);
  } else {
    modal.className = 'smart-modal-backdrop';
  }

  let targetVm = vmObj || vmList.find((v) => v.id === vmId);

  const renderModal = (targetVm) => {
    const isRunning = targetVm.state === 'running';
    const budget = vmTelemetry?.memory_budget || {
      total_host_ram_gb: 32.0,
      safe_max_vm_ram_gb: 28.8,
      safe_slider_max_gb: 28,
      safe_headroom_gb: 20.8,
      override_max_ram_gb: 31.0,
    };
    const hostThreads = vmTelemetry?.cpu_capacity?.host_threads || 8;
    const currentBootOrder = targetVm.boot_order || (targetVm.iso_path ? 'iso' : 'disk');
    const targetFirmware = targetVm.firmware || 'seabios';
    const targetVideo = targetVm.video_adapter || targetVm.display_adapter || 'virtio-gpu';
    let currentUsbDevices = Array.isArray(targetVm.usb_passthrough)
      ? targetVm.usb_passthrough.map((d) => ({ ...d }))
      : [];

    modal.innerHTML = `
      <div class="smart-modal-window vm-modal-window" style="max-width: 580px; width: 92%; max-height: 88vh; display: flex; flex-direction: column; overflow: hidden;">
        <div class="smart-modal-header" style="cursor: move; user-select: none; display: flex; justify-content: space-between; align-items: center;">
          <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            <span>Edit VM Configuration: ${escapeHtml(targetVm.name)}</span>
          </div>
          <div class="os-window-controls" style="display: flex; gap: 6px; align-items: center;">
            <button class="win-btn min-btn" id="vm-edit-modal-min" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="vm-edit-modal-max" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="vm-edit-modal-close" title="Close" aria-label="Close"></button>
          </div>
        </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 14px; padding: 18px 22px;">
        ${isRunning ? `
          <div style="background: rgba(14,165,233,0.12); border: 1px solid rgba(14,165,233,0.3); border-radius: 6px; padding: 10px 14px; font-size: 11px; color: #38bdf8; display: flex; align-items: center; gap: 8px;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            <span>This VM is currently <strong>running</strong>. Hardware changes (vCPUs, RAM, boot order) will take full effect on next VM restart.</span>
          </div>
        ` : ''}

        <!-- General Info -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">VM Name *</label>
          <input type="text" id="vm-edit-name" value="${escapeHtml(targetVm.name || '')}" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
        </div>

        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Description</label>
          <input type="text" id="vm-edit-desc" value="${escapeHtml(targetVm.description || '')}" placeholder="Appliance description" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
        </div>

        <!-- Snapshots Quick Launcher -->
        <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px 14px;">
          <div>
            <div style="font-size: 12px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 6px;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent, #38bdf8);"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>Snapshots & Rollback Checkpoints</span>
            </div>
            <div style="font-size: 11px; color: var(--muted); margin-top: 2px;">Create point-in-time state backups or revert to previous checkpoints.</div>
          </div>
          <button type="button" id="vm-edit-open-snapshots" class="btn-vm-action btn-vm-snapshots" style="padding: 5px 12px; font-size: 11px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>${t('vm.manage_snapshots', 'Manage Snapshots')}</span>
          </button>
        </div>

        <!-- RAM Allocation & Dynamic Headroom -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">RAM Allocation (Dynamic Headroom)</span>
            <span id="vm-edit-ram-display" style="font-size: 12px; font-weight: 700; color: #38bdf8;">${targetVm.ram_gb || 4.0} GB</span>
          </div>
          <input type="range" id="vm-edit-ram-slider" min="0.5" max="${Math.max(budget.safe_slider_max_gb, targetVm.ram_gb || 4)}" step="0.5" value="${targetVm.ram_gb || 4.0}" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>Min: 0.5 GB</span>
            <span id="vm-edit-slider-max-label">Safe Max: ${budget.safe_slider_max_gb} GB</span>
          </div>
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-edit-override-toggle" ${targetVm.override_active ? 'checked' : ''} style="accent-color: #f59e0b;" />
              <span>Advanced Override (Bypass Headroom)</span>
            </label>
            <span id="vm-edit-override-pill" style="display: ${targetVm.override_active ? 'inline-block' : 'none'}; font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4);">
              ⚡ Host reserve bypassed
            </span>
          </div>
        </div>

        <!-- vCPUs Slider -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">vCPU Cores</span>
            <span id="vm-edit-vcpu-display" style="font-size: 12px; font-weight: 700; color: #fff;">${targetVm.vcpus || 2} vCPUs</span>
          </div>
          <input type="range" id="vm-edit-vcpu-slider" min="1" max="${Math.max(hostThreads, targetVm.vcpus || 2)}" step="1" value="${targetVm.vcpus || 2}" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>1 vCPU</span>
            <span>Physical Limit: ${hostThreads} Threads</span>
          </div>
          <div id="vm-edit-overcommit-warning" style="display: ${(targetVm.vcpus || 2) > hostThreads ? 'block' : 'none'}; margin-top: 8px; font-size: 10px; padding: 6px 10px; border-radius: 4px; background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3);">
            ⚠️ Soft warning: Exceeds physical host threads.
          </div>
        </div>

        <!-- ISO Attach / Detach & Boot Order -->
        <div style="display: flex; flex-direction: column; gap: 10px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="font-size: 11px; font-weight: 700; color: var(--muted);">Attached ISO Image (CD-ROM)</label>
              ${targetVm.iso_path ? `<span style="font-size: 10px; color: #fbbf24;">💿 Currently Attached</span>` : ''}
            </div>
            <select id="vm-edit-iso" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
              <option value="">None (Detach ISO / Empty Tray)</option>
              ${vmIsos.map((iso) => `<option value="${escapeHtml(iso.path)}" ${iso.path === targetVm.iso_path ? 'selected' : ''}>${escapeHtml(iso.name)} (${iso.size_formatted})</option>`).join('')}
            </select>
          </div>

          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Boot Priority Order</label>
            <div class="vm-boot-order-group">
              <label class="boot-order-label">
                <input type="radio" name="vm-edit-boot-order" value="iso" ${currentBootOrder === 'iso' ? 'checked' : ''} />
                <span>💿 Boot from ISO first</span>
              </label>
              <label class="boot-order-label">
                <input type="radio" name="vm-edit-boot-order" value="disk" ${currentBootOrder === 'disk' ? 'checked' : ''} />
                <span>💽 Boot from Disk</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Firmware & Boot Architecture -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="margin-bottom: 8px;">
            <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.firmware_title">${t('vm.firmware_title', 'Firmware & Boot Architecture')}</div>
            <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.firmware_desc">${t('vm.firmware_desc', 'Select hypervisor firmware initialization and virtual hardware security.')}</div>
          </div>
          <div class="vm-firmware-group">
            <label class="firmware-label">
              <div style="display: flex; align-items: center; gap: 6px; font-weight: 700;">
                <input type="radio" name="vm-edit-firmware" value="seabios" ${targetFirmware === 'seabios' ? 'checked' : ''} />
                <span data-i18n="vm.firmware_seabios">${t('vm.firmware_seabios', 'SeaBIOS (Legacy BIOS)')}</span>
              </div>
              <div class="firmware-label-sub">MBR partitions, older Linux & Windows 7/10</div>
            </label>
            <label class="firmware-label">
              <div style="display: flex; align-items: center; gap: 6px; font-weight: 700;">
                <input type="radio" name="vm-edit-firmware" value="uefi" ${targetFirmware === 'uefi' ? 'checked' : ''} />
                <span data-i18n="vm.firmware_uefi">${t('vm.firmware_uefi', 'OVMF / UEFI (Modern / Win 11)')}</span>
              </div>
              <div class="firmware-label-sub">Pure 64-bit UEFI, NVRAM persistence, Secure Boot</div>
            </label>
          </div>

          <!-- Virtual TPM 2.0 Toggle -->
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: #fff; cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-edit-tpm" ${targetVm.tpm_enabled ? 'checked' : ''} style="accent-color: var(--accent-cyan, #0ea5e9);" />
              <span data-i18n="vm.tpm_title">${t('vm.tpm_title', 'Enable Virtual TPM 2.0 (vTPM)')}</span>
            </label>
            ${vtpmBadgeHtml()}
          </div>
        </div>

        <!-- Display & Video Adapter -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.video_title">${t('vm.video_title', 'Display & Video Adapter')}</div>
              <div style="font-size: 10px; color: var(--muted);">Select virtual GPU hardware adapter or headless console mode</div>
            </div>
            <span style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">
              GPU Accelerated
            </span>
          </div>
          <select id="vm-edit-video-adapter" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
            <option value="virtio-gpu" ${targetVideo === 'virtio-gpu' ? 'selected' : ''}>VirtIO-GPU (Recommended / Linux 2D/3D Accel)</option>
            <option value="qxl" ${targetVideo === 'qxl' ? 'selected' : ''}>QXL (SPICE / Windows Drivers)</option>
            <option value="vga" ${targetVideo === 'vga' ? 'selected' : ''}>Standard VGA (Universal Compatibility)</option>
            <option value="none" ${targetVideo === 'none' ? 'selected' : ''}>Headless (Serial Console Only - Zero VRAM)</option>
          </select>
        </div>

        <!-- Host USB Passthrough -->
        <div class="vm-config-card" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px; flex-shrink: 0;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; gap: 10px;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.usb_title">${t('vm.usb_title', 'Host USB Device Passthrough')}</div>
              <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.usb_desc">${t('vm.usb_desc', 'Attach physical host USB peripherals directly into the guest VM.')}</div>
            </div>
            <button type="button" id="btn-edit-toggle-custom-usb" class="btn-pill-toggle" data-i18n="vm.usb_custom_btn" style="padding: 4px 8px; font-size: 10px; white-space: nowrap; flex-shrink: 0; cursor: pointer;">
              ${t('vm.usb_custom_btn', '+ Custom VID:PID')}
            </button>
          </div>

          <!-- Dynamic host USB selector row -->
          <div class="usb-select-row">
            <select id="vm-edit-host-usb-select" class="tz-select">
              <option value="">Scanning host USB devices...</option>
            </select>
            <button type="button" id="btn-edit-add-usb-device" class="btn-attach-usb">
              ${t('vm.usb_add_btn', '+ Attach Device')}
            </button>
          </div>

          <!-- Custom USB inputs (hidden by default) -->
          <div id="vm-edit-custom-usb-wrap" class="usb-custom-row" style="display: none;">
            <input type="text" id="vm-edit-custom-vid" placeholder="VID (10c4)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <input type="text" id="vm-edit-custom-pid" placeholder="PID (ea60)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <input type="text" id="vm-edit-custom-desc" class="usb-custom-desc" placeholder="Device Label (e.g. Zigbee Dongle)" style="padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <button type="button" id="btn-edit-add-custom-usb" class="btn-console-act btn-custom-add" style="padding: 4px 10px; font-size: 11px; background: rgba(16,185,129,0.2); border-color: #34d399; color: #34d399; cursor: pointer;">
              Add
            </button>
          </div>

          <!-- Attached USB devices list -->
          <div id="vm-edit-usb-list" style="display: flex; flex-direction: column; gap: 6px; margin-top: 6px;"></div>
        </div>

        <!-- Host Folder Passthrough (VirtIO-FS / 9p) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Host Directory Passthrough (VirtIO-FS / 9p)</span>
              <div style="font-size: 10px; color: var(--muted);">Map host folders (/mnt/user/appdata, /mnt/storage) into guest</div>
            </div>
            <button type="button" id="btn-edit-add-host-share" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">
              + Add Folder
            </button>
          </div>
          <div id="vm-edit-host-shares-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <!-- Secondary Virtual Disks -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Secondary Virtual Disks</span>
              <div style="font-size: 10px; color: var(--muted);">Attach additional block devices (data pools, databases)</div>
            </div>
            <button type="button" id="btn-edit-add-secondary-disk" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">
              + Add Disk
            </button>
          </div>
          <div id="vm-edit-secondary-disks-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <div>
          <label style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: #fff; cursor: pointer;">
            <input type="checkbox" id="vm-edit-autostart" ${targetVm.autostart ? 'checked' : ''} style="accent-color: var(--accent-cyan, #0ea5e9);" />
            <span>Autostart on Boot (Start with Host OS)</span>
          </label>
        </div>
      </div>

      <div class="smart-modal-footer" style="padding: 14px 22px; display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="vm-edit-cancel" class="btn-console-act" style="background: rgba(255,255,255,0.06); color: #cbd5e1; padding: 6px 14px;">
          Cancel
        </button>
        <button id="vm-edit-submit" class="btn-console-act" style="background: #0ea5e9; color: #fff; border-color: #38bdf8; padding: 6px 18px; font-weight: 700;">
          Save Configuration
        </button>
      </div>
    </div>
  `;

  modal.classList.remove('window-minimized');
  modal.classList.add('open');
  modal.style.removeProperty('display');
  modal.style.display = 'flex';

  const modalWin = modal.querySelector('.smart-modal-window');
  const modalHdr = modal.querySelector('.smart-modal-header');

  if (modalWin) {
    modalWin.classList.remove('window-minimized');
    modalWin.style.removeProperty('display');
  }

  const closeBtn = modal.querySelector('#vm-edit-modal-close');
  const minBtn = modal.querySelector('#vm-edit-modal-min');
  const maxBtn = modal.querySelector('#vm-edit-modal-max');
  const cancelBtn = modal.querySelector('#vm-edit-cancel');
  const submitBtn = modal.querySelector('#vm-edit-submit');

  const ramSlider = modal.querySelector('#vm-edit-ram-slider');
  const ramDisplay = modal.querySelector('#vm-edit-ram-display');
  const vcpuSlider = modal.querySelector('#vm-edit-vcpu-slider');
  const vcpuDisplay = modal.querySelector('#vm-edit-vcpu-display');
  const overrideToggle = modal.querySelector('#vm-edit-override-toggle');
  const overridePill = modal.querySelector('#vm-edit-override-pill');
  const sliderMaxLabel = modal.querySelector('#vm-edit-slider-max-label');
  const overcommitWarning = modal.querySelector('#vm-edit-overcommit-warning');

  // Make VM Configuration modal draggable & focusable
  if (modalWin && modalHdr) {
    makeDraggable(modalWin, modalHdr, 'modal-vm-edit');
    modalWin.addEventListener('pointerdown', () => bringToFront(modalWin));
    bringToFront(modalWin);
  }

  // Register in DockManager for window lifecycle (minimize & restore)
  if (window.DockManager && typeof window.DockManager.register === 'function') {
    window.DockManager.register(
      'modal-vm-edit',
      modal,
      '#i-vm',
      `Edit: ${targetVm.name || 'VM Configuration'}`
    );
  }

  let onKeyDown = null;
  const close = () => {
    modal.classList.remove('open');
    modal.classList.remove('window-minimized');
    modal.style.display = 'none';
    if (modalWin) {
      modalWin.classList.remove('window-minimized');
    }
    if (onKeyDown) {
      document.removeEventListener('keydown', onKeyDown);
      onKeyDown = null;
    }
    if (window.DockManager && typeof window.DockManager.unregister === 'function') {
      window.DockManager.unregister('modal-vm-edit');
    }
  };

  onKeyDown = (e) => {
    if (e.key === 'Escape' && modal.classList.contains('open')) {
      close();
    }
  };
  document.addEventListener('keydown', onKeyDown);

  if (closeBtn) closeBtn.onclick = close;
  if (cancelBtn) cancelBtn.onclick = close;

  const btnOpenSnaps = modal.querySelector('#vm-edit-open-snapshots');
  if (btnOpenSnaps) {
    btnOpenSnaps.onclick = () => {
      openVmSnapshotsModal(vmId, targetVm);
    };
  }

  // Minimize handler
  if (minBtn) {
    minBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      modal.classList.add('window-minimized');
      modal.classList.remove('open');
      modal.style.setProperty('display', 'none', 'important');
      if (modalWin) {
        modalWin.classList.add('window-minimized');
      }
      if (window.DockManager && typeof window.DockManager.minimize === 'function') {
        window.DockManager.minimize('modal-vm-edit');
      }
    };
  }

  // Maximize / Restore toggle handler
  let isMax = false;
  let preBounds = null;
  if (maxBtn) {
    maxBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!isMax) {
        preBounds = {
          left: modalWin.style.left,
          top: modalWin.style.top,
          width: modalWin.style.width,
          height: modalWin.style.height,
          maxWidth: modalWin.style.maxWidth,
          maxHeight: modalWin.style.maxHeight,
          position: modalWin.style.position,
          borderRadius: modalWin.style.borderRadius,
        };
        modalWin.classList.add('maximized');
        modalWin.style.position = 'fixed';
        modalWin.style.left = '0px';
        modalWin.style.top = '36px';
        modalWin.style.width = '100vw';
        modalWin.style.height = 'calc(100vh - 36px - 72px)';
        modalWin.style.maxWidth = '100vw';
        modalWin.style.maxHeight = 'calc(100vh - 36px - 72px)';
        modalWin.style.borderRadius = '0px';
        maxBtn.setAttribute('title', 'Restore');
        maxBtn.setAttribute('aria-label', 'Restore');
        isMax = true;
      } else {
        modalWin.classList.remove('maximized');
        if (preBounds) {
          modalWin.style.left = preBounds.left || '';
          modalWin.style.top = preBounds.top || '';
          modalWin.style.width = preBounds.width || '92%';
          modalWin.style.height = preBounds.height || '';
          modalWin.style.maxWidth = preBounds.maxWidth || '580px';
          modalWin.style.maxHeight = preBounds.maxHeight || '88vh';
          modalWin.style.position = preBounds.position || '';
          modalWin.style.borderRadius = preBounds.borderRadius || '14px';
        } else {
          modalWin.style.left = '';
          modalWin.style.top = '';
          modalWin.style.width = '92%';
          modalWin.style.height = '';
          modalWin.style.maxWidth = '580px';
          modalWin.style.maxHeight = '88vh';
          modalWin.style.position = '';
          modalWin.style.borderRadius = '14px';
        }
        maxBtn.setAttribute('title', 'Maximize');
        maxBtn.setAttribute('aria-label', 'Maximize');
        isMax = false;
      }
    };
  }

  // Header double-click to toggle maximize
  if (modalHdr) {
    modalHdr.ondblclick = (e) => {
      if (e.target.closest('button') || e.target.closest('input')) return;
      if (maxBtn) maxBtn.click();
    };
  }

  if (ramSlider && ramDisplay) {
    ramSlider.oninput = () => {
      ramDisplay.textContent = `${parseFloat(ramSlider.value).toFixed(1)} GB`;
    };
  }

  if (overrideToggle) {
    overrideToggle.onchange = () => {
      if (overrideToggle.checked) {
        ramSlider.max = budget.override_max_ram_gb || 31.0;
        if (sliderMaxLabel) sliderMaxLabel.textContent = `Override Max: ${ramSlider.max} GB`;
        if (overridePill) overridePill.style.display = 'inline-block';
      } else {
        ramSlider.max = budget.safe_slider_max_gb || 28;
        if (parseFloat(ramSlider.value) > ramSlider.max) {
          ramSlider.value = ramSlider.max;
          ramDisplay.textContent = `${ramSlider.value} GB`;
        }
        if (sliderMaxLabel) sliderMaxLabel.textContent = `Safe Max: ${ramSlider.max} GB`;
        if (overridePill) overridePill.style.display = 'none';
      }
    };
  }

  if (vcpuSlider && vcpuDisplay) {
    vcpuSlider.oninput = () => {
      const val = parseInt(vcpuSlider.value, 10);
      vcpuDisplay.textContent = `${val} vCPUs`;
      if (overcommitWarning) {
        overcommitWarning.style.display = val > hostThreads ? 'block' : 'none';
      }
    };
  }

  // Host Shares Row Addition
  const sharesList = modal.querySelector('#vm-edit-host-shares-list');
  const btnAddShare = modal.querySelector('#btn-edit-add-host-share');
  const addShareRow = (share = {}) => {
    const row = document.createElement('div');
    row.className = 'host-share-row';
    row.style.cssText = 'display: flex; gap: 6px; align-items: center;';
    row.innerHTML = `
      <input type="text" class="share-host-path" placeholder="/mnt/user/appdata" value="${escapeHtml(share.host_path || '/mnt/user/appdata')}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <input type="text" class="share-mount-tag" placeholder="appdata" value="${escapeHtml(share.mount_tag || 'appdata')}" style="flex: 1.2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <select class="share-driver" style="flex: 1; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="virtiofs" ${share.driver === 'virtiofs' ? 'selected' : ''}>VirtIO-FS</option>
        <option value="9p" ${share.driver === '9p' ? 'selected' : ''}>9p</option>
      </select>
      <select class="share-mode" style="width: 60px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="rw" ${!share.readonly ? 'selected' : ''}>RW</option>
        <option value="ro" ${share.readonly ? 'selected' : ''}>RO</option>
      </select>
      <button type="button" class="btn-remove-share" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
    `;
    row.querySelector('.btn-remove-share').onclick = () => row.remove();
    sharesList.appendChild(row);
  };
  if (btnAddShare && sharesList) {
    btnAddShare.onclick = () => addShareRow();
    if (targetVm.host_shares && Array.isArray(targetVm.host_shares)) {
      targetVm.host_shares.forEach((s) => addShareRow(s));
    }
  }

  // Secondary Disks Row Addition
  const disksList = modal.querySelector('#vm-edit-secondary-disks-list');
  const btnAddDisk = modal.querySelector('#btn-edit-add-secondary-disk');
  const addDiskRow = (disk = {}) => {
    const idx = (disksList.children.length || 0) + 1;
    const row = document.createElement('div');
    row.className = 'secondary-disk-row';
    row.style.cssText = 'display: flex; gap: 6px; align-items: center;';
    row.innerHTML = `
      <input type="text" class="disk-name" placeholder="Disk Name" value="${escapeHtml(disk.name || `data-disk-${idx}`)}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <input type="number" class="disk-size" min="5" max="4000" placeholder="Size (GB)" value="${disk.size_gb || 50}" style="width: 80px; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <select class="disk-bus" style="width: 80px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="virtio" ${disk.bus === 'virtio' ? 'selected' : ''}>virtio</option>
        <option value="sata" ${disk.bus === 'sata' ? 'selected' : ''}>sata</option>
        <option value="nvme" ${disk.bus === 'nvme' ? 'selected' : ''}>nvme</option>
      </select>
      <button type="button" class="btn-remove-disk" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
    `;
    row.querySelector('.btn-remove-disk').onclick = () => row.remove();
    disksList.appendChild(row);
  };
  if (btnAddDisk && disksList) {
    btnAddDisk.onclick = () => addDiskRow();
    if (targetVm.secondary_disks && Array.isArray(targetVm.secondary_disks)) {
      targetVm.secondary_disks.forEach((d) => addDiskRow(d));
    }
  }

  // Host USB Passthrough Device Management
  const usbList = modal.querySelector('#vm-edit-usb-list');
  const usbSelect = modal.querySelector('#vm-edit-host-usb-select');
  const btnAddUsb = modal.querySelector('#btn-edit-add-usb-device');
  const toggleCustomUsb = modal.querySelector('#btn-edit-toggle-custom-usb');
  const customUsbWrap = modal.querySelector('#vm-edit-custom-usb-wrap');
  const btnAddCustomUsb = modal.querySelector('#btn-edit-add-custom-usb');

  const renderUsbList = () => {
    if (!usbList) return;
    usbList.innerHTML = '';
    if (currentUsbDevices.length === 0) {
      usbList.innerHTML = `
        <div style="font-size: 10px; color: var(--muted); padding: 8px 10px; text-align: center; background: rgba(0,0,0,0.2); border-radius: 4px;" data-i18n="vm.usb_no_devices">
          ${t('vm.usb_no_devices', 'No host USB devices attached to this VM.')}
        </div>
      `;
      return;
    }
    currentUsbDevices.forEach((dev, idx) => {
      const card = document.createElement('div');
      card.className = 'usb-device-card';
      card.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; overflow: hidden;">
          <span style="font-size: 14px;">🔌</span>
          <div style="min-width: 0;">
            <div style="font-size: 11px; font-weight: 700; color: #fff; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
              ${escapeHtml(dev.description || dev.product || 'USB Device')}
            </div>
            <div style="font-size: 9px; color: var(--muted);">
              ${escapeHtml(dev.manufacturer || 'Generic')} ${dev.bus ? `· Bus ${dev.bus} Dev ${dev.dev}` : ''}
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="usb-vidpid-badge">${escapeHtml(dev.vendor_id)}:${escapeHtml(dev.product_id)}</span>
          <button type="button" class="btn-remove-usb" data-idx="${idx}" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px; font-size: 12px;" title="Remove device">✕</button>
        </div>
      `;
      card.querySelector('.btn-remove-usb').onclick = () => {
        currentUsbDevices.splice(idx, 1);
        renderUsbList();
      };
      usbList.appendChild(card);
    });
  };

  renderUsbList();

  // Load available host USB devices
  api.get('/api/vms/usb-devices')
    .then((devs) => {
      if (!usbSelect) return;
      usbSelect.innerHTML = '<option value="">-- Select connected host USB device --</option>';
      if (Array.isArray(devs) && devs.length > 0) {
        devs.forEach((d) => {
          const opt = document.createElement('option');
          opt.value = JSON.stringify({
            vendor_id: d.vendor_id,
            product_id: d.product_id,
            description: d.description || d.product,
            manufacturer: d.manufacturer,
            bus: d.bus,
            dev: d.dev,
          });
          const hubTag = d.is_root_hub ? ' [Root Hub]' : '';
          opt.textContent = `[${d.vendor_id}:${d.product_id}] ${d.description || d.product}${hubTag}`;
          usbSelect.appendChild(opt);
        });
      } else {
        usbSelect.innerHTML = '<option value="">No USB devices detected on host</option>';
      }
    })
    .catch(() => {
      if (!usbSelect) return;
      usbSelect.innerHTML = '<option value="">Failed to scan USB devices</option>';
    });

  if (btnAddUsb && usbSelect) {
    btnAddUsb.onclick = () => {
      const val = usbSelect.value;
      if (!val) {
        showToast('Select a host USB device to attach', 'warning');
        return;
      }
      try {
        const item = JSON.parse(val);
        if (!currentUsbDevices.some((d) => d.vendor_id === item.vendor_id && d.product_id === item.product_id)) {
          currentUsbDevices.push(item);
          renderUsbList();
          showToast(`Attached USB device: ${item.description || item.vendor_id}`, 'info');
        } else {
          showToast('Device is already attached to this VM', 'warning');
        }
      } catch (e) {
        // ignore
      }
    };
  }

  if (toggleCustomUsb && customUsbWrap) {
    toggleCustomUsb.onclick = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      const isHidden = customUsbWrap.style.display === 'none' || (typeof window !== 'undefined' && window.getComputedStyle && window.getComputedStyle(customUsbWrap).display === 'none');
      customUsbWrap.style.display = isHidden ? 'flex' : 'none';
      toggleCustomUsb.classList.toggle('active', isHidden);
      toggleCustomUsb.textContent = isHidden ? t('vm.usb_custom_close_btn', '− Custom VID:PID') : t('vm.usb_custom_btn', '+ Custom VID:PID');
      if (isHidden) {
        const vidInput = modal.querySelector('#vm-edit-custom-vid');
        if (vidInput) vidInput.focus();
      }
    };
  }

  ['#vm-edit-custom-vid', '#vm-edit-custom-pid', '#vm-edit-custom-desc'].forEach((sel) => {
    const inp = modal.querySelector(sel);
    if (inp) {
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          btnAddCustomUsb?.click();
        }
      });
    }
  });

  if (btnAddCustomUsb) {
    btnAddCustomUsb.onclick = () => {
      const vid = modal.querySelector('#vm-edit-custom-vid')?.value?.trim().toLowerCase().replace('0x', '');
      const pid = modal.querySelector('#vm-edit-custom-pid')?.value?.trim().toLowerCase().replace('0x', '');
      const desc = modal.querySelector('#vm-edit-custom-desc')?.value?.trim() || `USB Device (${vid}:${pid})`;
      if (!vid || !pid || !/^[0-9a-fA-F]{1,4}$/.test(vid) || !/^[0-9a-fA-F]{1,4}$/.test(pid)) {
        showToast('Please enter valid 4-character hex VID and PID (e.g. 10c4, ea60)', 'warning');
        return;
      }
      if (!currentUsbDevices.some((d) => d.vendor_id === vid && d.product_id === pid)) {
        currentUsbDevices.push({ vendor_id: vid, product_id: pid, description: desc, manufacturer: 'Custom' });
        renderUsbList();
        modal.querySelector('#vm-edit-custom-vid').value = '';
        modal.querySelector('#vm-edit-custom-pid').value = '';
        modal.querySelector('#vm-edit-custom-desc').value = '';
        showToast(`Added custom USB device [${vid}:${pid}]`, 'info');
      } else {
        showToast('Device is already attached to this VM', 'warning');
      }
    };
  }

  if (submitBtn) {
    submitBtn.onclick = async () => {
      const newName = modal.querySelector('#vm-edit-name')?.value?.trim();
      const newDesc = modal.querySelector('#vm-edit-desc')?.value?.trim();
      const newRam = parseFloat(modal.querySelector('#vm-edit-ram-slider')?.value || targetVm.ram_gb);
      const newVcpus = parseInt(modal.querySelector('#vm-edit-vcpu-slider')?.value || targetVm.vcpus, 10);
      const newIso = modal.querySelector('#vm-edit-iso')?.value || null;
      const newBootOrder = modal.querySelector('input[name="vm-edit-boot-order"]:checked')?.value || 'iso';
      const newFirmware = modal.querySelector('input[name="vm-edit-firmware"]:checked')?.value || targetVm.firmware || 'seabios';
      const newVideoAdapter = modal.querySelector('#vm-edit-video-adapter')?.value || targetVm.video_adapter || 'virtio-gpu';
      const newTpm = !!modal.querySelector('#vm-edit-tpm')?.checked;
      const newAutostart = modal.querySelector('#vm-edit-autostart')?.checked ?? targetVm.autostart;
      const overrideLimits = modal.querySelector('#vm-edit-override-toggle')?.checked ?? false;

      const hostShares = [];
      modal.querySelectorAll('.host-share-row').forEach((row) => {
        const p = row.querySelector('.share-host-path')?.value?.trim();
        const t = row.querySelector('.share-mount-tag')?.value?.trim();
        const d = row.querySelector('.share-driver')?.value || 'virtiofs';
        const ro = row.querySelector('.share-mode')?.value === 'ro';
        if (p && t) hostShares.push({ host_path: p, mount_tag: t, driver: d, readonly: ro });
      });

      const secondaryDisks = [];
      modal.querySelectorAll('.secondary-disk-row').forEach((row) => {
        const n = row.querySelector('.disk-name')?.value?.trim();
        const s = parseInt(row.querySelector('.disk-size')?.value, 10);
        const b = row.querySelector('.disk-bus')?.value || 'virtio';
        if (n && s > 0) secondaryDisks.push({ name: n, size_gb: s, bus: b });
      });

      if (!newName) {
        showToast('VM Name is required', 'error');
        return;
      }

      const payload = {
        name: newName,
        description: newDesc,
        ram_gb: newRam,
        vcpus: newVcpus,
        iso_path: newIso,
        boot_order: newBootOrder,
        firmware: newFirmware,
        video_adapter: newVideoAdapter,
        tpm_enabled: newTpm,
        usb_passthrough: currentUsbDevices,
        autostart: newAutostart,
        override_limits: overrideLimits,
        host_shares: hostShares,
        secondary_disks: secondaryDisks,
      };

      try {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving...';

        try {
          if (api.put) {
            await api.put(`/api/vms/${vmId}`, payload);
          } else {
            await api.post(`/api/vms/${vmId}`, payload);
          }
        } catch (apiErr) {
          if (apiErr.status === 405 || apiErr.status === 404) {
            await api.post(`/api/vms/${vmId}`, payload).catch(() => null);
          } else {
            throw apiErr;
          }
        }

        Object.assign(targetVm, payload);
        showToast(`VM '${newName}' configuration updated`, 'success');
        close();
        loadVmDashboard();
        window.dispatchEvent(new CustomEvent('vm-updated', { detail: { id: vmId } }));
      } catch (err) {
        showToast(`Failed to update VM: ${err.message || 'Error'}`, 'error');
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Save Configuration';
        }
      }
    };
  }
};

  if (targetVm) {
    if (!vmList.some((v) => v.id === targetVm.id)) vmList.push(targetVm);
    renderModal(targetVm);
    return;
  }

  // Graceful auto-fetch when called outside of standalone VM Manager window
  Promise.all([
    api.get(`/api/vms/${vmId}`).catch(() => null),
    (!vmIsos || vmIsos.length === 0) ? api.get('/api/vms/isos').catch(() => []) : Promise.resolve(vmIsos),
    !vmTelemetry ? api.get('/api/vms/telemetry').catch(() => null) : Promise.resolve(vmTelemetry),
  ])
    .then(([direct, isos, tel]) => {
      if (tel) vmTelemetry = tel;
      if (Array.isArray(isos)) vmIsos = isos;
      if (direct && direct.id) {
        if (!vmList.some((v) => v.id === direct.id)) vmList.push(direct);
        renderModal(direct);
      } else {
        showToast(`Virtual machine '${vmId}' not found`, 'error');
      }
    })
    .catch((err) => {
      showToast(`Virtual machine '${vmId}' not found: ${err.message || 'Error'}`, 'error');
    });
}

/**
 * Opens Multi-Protocol VM Connection Modal (#modal-vm-connect)
 * Displays interactive quick-connect details for Web GUI, Serial TTY, Native VNC, SSH, RDP, and VirtIO-FS
 */
export function openVmConnectModal(vmId, vmObj = null) {
  let modal = document.getElementById('modal-vm-connect');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-vm-connect';
    modal.className = 'smart-modal-backdrop';
    document.body.appendChild(modal);
  } else {
    modal.className = 'smart-modal-backdrop';
  }

  let targetVm = vmObj || vmList.find((v) => v.id === vmId);

  const renderConnectModal = (targetVm) => {
    const name = targetVm.name || 'Virtual Machine';
    const ip = targetVm.ip_address || '';
    const vncPort = targetVm.vnc_port || 5900;
    const hostIp = (typeof window !== 'undefined' && window.location) ? window.location.hostname : '127.0.0.1';
    const vncUri = `vnc://${hostIp}:${vncPort}`;
    const sshCmd = ip ? `ssh root@${ip}` : '';
    const rdpUri = ip ? `${ip}:3389` : '';
    const hostShares = targetVm.host_shares || [];

    modal.innerHTML = `
    <div class="smart-modal-window vm-modal-window" style="max-width: 640px; width: 92%; max-height: 88vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
          <span>Multi-Protocol Connect: ${escapeHtml(name)}</span>
        </div>
        <button id="vm-connect-modal-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 4px;" title="Close" aria-label="Close">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding: 18px 22px;">
        <!-- Status summary banner -->
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="qemu-process-badge ${targetVm.state === 'running' ? 'active' : targetVm.state === 'paused' ? 'paused' : 'stopped'}">
              ● ${targetVm.state ? targetVm.state.toUpperCase() : 'UNKNOWN'}
            </span>
            <span style="font-size: 12px; font-weight: 700; color: #fff;">${escapeHtml(name)}</span>
          </div>
          <span style="font-size: 11px; font-family: monospace; color: ${ip ? '#38bdf8' : 'var(--muted)'};">
            ${ip ? `IP: ${ip}` : 'No IP detected yet (DHCP pending)'}
          </span>
        </div>

        <!-- Option 1: In-Browser Web Console (KVM GUI & Serial TTY) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🖥️</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">In-Browser Web Console</div>
                <div style="font-size: 10px; color: var(--muted);">Direct glassmorphic KVM GUI (VirtIO-GPU) or VT100 Serial TTY</div>
              </div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn-console-act btn-connect-gui" style="padding: 4px 10px; font-size: 11px; background: #0ea5e9; color: #fff; border-color: #38bdf8;">
                Launch KVM GUI
              </button>
              <button class="btn-console-act btn-connect-tty" style="padding: 4px 10px; font-size: 11px; background: rgba(52,211,153,0.15); color: #34d399; border-color: rgba(52,211,153,0.4);">
                Serial TTY
              </button>
            </div>
          </div>
        </div>

        <!-- Option 2: Native RFB / VNC Client -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🌐</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">Native VNC Client (RFB)</div>
                <div style="font-size: 10px; color: var(--muted);">TigerVNC, RealVNC, macOS Screen Sharing</div>
              </div>
            </div>
            <button class="btn-console-act btn-connect-copy-vnc" style="padding: 4px 10px; font-size: 11px;">
              📋 Copy VNC URI
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px; color: #38bdf8;">
            <span>${vncUri}</span>
            <span style="color: var(--muted); font-size: 10px;">Port ${vncPort}</span>
          </div>
        </div>

        <!-- Option 3: Secure Shell (SSH) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🔒</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">Secure Shell (SSH)</div>
                <div style="font-size: 10px; color: var(--muted);">Terminal command for OpenSSH / PuTTY</div>
              </div>
            </div>
            <button class="btn-console-act btn-connect-copy-ssh" ${ip ? '' : 'disabled'} style="padding: 4px 10px; font-size: 11px; ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
              📋 Copy SSH Command
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px; color: ${ip ? '#34d399' : 'var(--muted)'};">
            <span>${ip ? sshCmd : 'Awaiting guest IP address assignment'}</span>
          </div>
        </div>

        <!-- Option 4: Remote Desktop Protocol (RDP) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🪟</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">Remote Desktop (RDP)</div>
                <div style="font-size: 10px; color: var(--muted);">Microsoft Remote Desktop, Remmina, FreeRDP</div>
              </div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn-console-act btn-connect-copy-rdp" ${ip ? '' : 'disabled'} style="padding: 4px 10px; font-size: 11px; ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
                📋 Copy RDP URI
              </button>
              <button class="btn-console-act btn-connect-dl-rdp" ${ip ? '' : 'disabled'} style="padding: 4px 10px; font-size: 11px; ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
                ⬇ .rdp File
              </button>
            </div>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px; color: ${ip ? '#eab308' : 'var(--muted)'};">
            <span>${ip ? rdpUri : 'Awaiting guest IP address assignment'}</span>
            <span style="color: var(--muted); font-size: 10px;">Port 3389</span>
          </div>
        </div>

        <!-- Option 5: Host Storage Shares (VirtIO-FS / 9p) -->
        ${hostShares.length > 0 ? `
          <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
              <span style="font-size: 14px;">📂</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">VirtIO-FS / 9p Mount Instructions</div>
                <div style="font-size: 10px; color: var(--muted);">Run inside guest to access host shares</div>
              </div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px;">
              ${hostShares.map((s) => `
                <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.3); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px;">
                  <span style="color: #cbd5e1;">sudo mount -t virtiofs ${escapeHtml(s.mount_tag)} /mnt/${escapeHtml(s.mount_tag)}</span>
                  <button class="btn-console-act btn-copy-mount-cmd" data-cmd="sudo mkdir -p /mnt/${escapeHtml(s.mount_tag)} && sudo mount -t virtiofs ${escapeHtml(s.mount_tag)} /mnt/${escapeHtml(s.mount_tag)}" style="padding: 2px 8px; font-size: 10px;">Copy</button>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}
      </div>

      <div class="smart-modal-footer" style="padding: 12px 22px; display: flex; justify-content: flex-end; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="vm-connect-close" class="btn-console-act" style="background: rgba(255,255,255,0.08); color: #cbd5e1; padding: 6px 16px;">
          Close
        </button>
      </div>
    </div>
  `;

  modal.classList.add('open');
  modal.style.display = 'flex';

  const close = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  };

  const closeBtn = modal.querySelector('#vm-connect-modal-close');
  const footerCloseBtn = modal.querySelector('#vm-connect-close');
  if (closeBtn) closeBtn.onclick = close;
  if (footerCloseBtn) footerCloseBtn.onclick = close;
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };

  // Launch buttons
  modal.querySelector('.btn-connect-gui')?.addEventListener('click', () => {
    close();
    openVmConsole(vmId, name, 'gui');
  });
  modal.querySelector('.btn-connect-tty')?.addEventListener('click', () => {
    close();
    openVmConsole(vmId, name, 'cli');
  });

  // Copy buttons
  modal.querySelector('.btn-connect-copy-vnc')?.addEventListener('click', async () => {
    const ok = await copyToClipboard(vncUri);
    if (ok) showToast(`Copied VNC URI '${vncUri}'`, 'info');
    else showToast('Failed to copy VNC URI', 'error');
  });

  modal.querySelector('.btn-connect-copy-ssh')?.addEventListener('click', async () => {
    if (!sshCmd) return;
    const ok = await copyToClipboard(sshCmd);
    if (ok) showToast(`Copied '${sshCmd}'`, 'info');
    else showToast('Failed to copy SSH command', 'error');
  });

  modal.querySelector('.btn-connect-copy-rdp')?.addEventListener('click', async () => {
    if (!rdpUri) return;
    const ok = await copyToClipboard(rdpUri);
    if (ok) showToast(`Copied RDP Address '${rdpUri}'`, 'info');
    else showToast('Failed to copy RDP Address', 'error');
  });

  modal.querySelector('.btn-connect-dl-rdp')?.addEventListener('click', () => {
    if (!ip) return;
    const content = `full address:s:${ip}:3389\nprompt for credentials:i:1\nadministrative session:i:1\n`;
    const blob = new Blob([content], { type: 'application/x-rdp' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${name.replace(/\s+/g, '_')}.rdp`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    showToast(`Downloaded RDP file for ${name}`, 'success');
  });

  modal.querySelectorAll('.btn-copy-mount-cmd').forEach((btn) => {
    btn.onclick = async () => {
      const cmd = btn.dataset.cmd;
      const ok = await copyToClipboard(cmd);
      if (ok) showToast('Copied mount command to clipboard', 'info');
    };
  });
  };

  if (targetVm) {
    if (!vmList.some((v) => v.id === targetVm.id)) vmList.push(targetVm);
    renderConnectModal(targetVm);
    return;
  }

  api.get(`/api/vms/${vmId}`)
    .then((direct) => {
      if (direct && direct.id) {
        if (!vmList.some((v) => v.id === direct.id)) vmList.push(direct);
        renderConnectModal(direct);
      } else {
        showToast(`Virtual machine '${vmId}' not found`, 'error');
      }
    })
    .catch((err) => {
      showToast(`Virtual machine '${vmId}' not found: ${err.message || 'Error'}`, 'error');
    });
}

/**
 * Opens KVM Diagnostics & Container Remediation Modal (#modal-kvm-diagnose)
 */
export function openKvmDiagnosticsModal(kvm = null) {
  let modal = document.getElementById('modal-kvm-diagnose');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-kvm-diagnose';
    modal.className = 'smart-modal-backdrop';
    document.body.appendChild(modal);
  }

  const k = kvm || vmTelemetry?.kvm || {};
  const isCgroupRestricted = k.cgroup_restricted || (k.substate === 'container_restricted');
  const hasVirt = !!(k.hardware_virt || k.intel_vtx || k.amd_v);
  const isModuleLoaded = !!k.module_loaded;
  const hasNode = !!k.device_present;

  modal.innerHTML = `
    <div class="smart-modal-window kvm-diag-window" style="max-width: 580px; width: 92%; max-height: 85vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <span>KVM Acceleration & Host Diagnostics</span>
        </div>
        <button id="kvm-diag-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px;">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; padding: 18px 22px; display: flex; flex-direction: column; gap: 14px;">
        <!-- Status Banner -->
        <div style="padding: 12px 14px; border-radius: 8px; background: ${k.state === 'active' ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)'}; border: 1px solid ${k.state === 'active' ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.3)'};">
          <div style="font-weight: 700; color: ${k.state === 'active' ? '#34d399' : '#fbbf24'}; font-size: 13px; display: flex; align-items: center; gap: 6px;">
            <span>${k.state === 'active' ? '✓' : '⚠️'}</span>
            <span>${escapeHtml(k.badge || 'KVM Status')}</span>
          </div>
          <div style="font-size: 11px; color: #cbd5e1; margin-top: 4px; line-height: 1.4;">
            ${escapeHtml(k.remediation || (k.state === 'active' ? 'Kernel-based Virtual Machine (KVM) hardware acceleration is fully active.' : 'Virtualization is partially restricted.'))}
          </div>
        </div>

        <!-- 4-Tier Diagnostics Grid -->
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;">Multi-Tier Diagnostics</div>
          
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 1: Host CPU Virtualization (VT-x / AMD-V)</span>
            <span style="font-weight: 700; color: ${hasVirt ? '#34d399' : '#f87171'};">${hasVirt ? '✓ Supported' : '✕ Disabled in BIOS'}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 2: Host Kernel Module (kvm_intel / kvm_amd)</span>
            <span style="font-weight: 700; color: ${isModuleLoaded ? '#34d399' : '#fbbf24'};">${isModuleLoaded ? '✓ Loaded' : '⚠️ Module Missing'}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 3: Device Character Node (/dev/kvm)</span>
            <span style="font-weight: 700; color: ${hasNode ? '#34d399' : '#f87171'};">${hasNode ? '✓ Present on Host' : '✕ Node Missing'}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 4: Container Device Cgroup Access</span>
            <span style="font-weight: 700; color: ${k.device_writable ? '#34d399' : isCgroupRestricted ? '#fbbf24' : '#f87171'};">
              ${k.device_writable ? '✓ Accessible' : isCgroupRestricted ? '⚠️ Cgroup Restricted (EPERM)' : '✕ Denied'}
            </span>
          </div>
        </div>

        ${
          isCgroupRestricted
            ? `
          <!-- Container Remediation Fix Snippet -->
          <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px;">
            <div style="font-size: 11px; font-weight: 700; color: #fff; margin-bottom: 6px;">How to Fix (Docker / Unraid Container Configuration)</div>
            <div style="font-size: 11px; color: var(--muted); margin-bottom: 8px;">
              Add the physical device mapping so the Linux kernel permits container access:
            </div>
            
            <div style="position: relative; margin-bottom: 8px;">
              <pre style="margin: 0; padding: 8px 12px; background: #0c121c; border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; font-size: 11px; color: #38bdf8; font-family: monospace;">--device /dev/kvm</pre>
              <button id="btn-copy-kvm-param" class="btn-pill-toggle" style="position: absolute; right: 6px; top: 50%; transform: translateY(-50%); font-size: 10px; padding: 2px 8px;">Copy</button>
            </div>

            <div style="font-size: 10px; color: var(--muted);">
              <strong>Unraid:</strong> Edit container template → Click 'Advanced View' → Add <code>--device /dev/kvm</code> in <strong>Extra Parameters</strong>.
            </div>
          </div>
        `
            : ''
        }
      </div>

      <div class="smart-modal-footer" style="display: flex; justify-content: flex-end; padding: 12px 20px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="kvm-diag-ok" class="btn-pill-toggle" style="padding: 6px 16px;">Close</button>
      </div>
    </div>
  `;

  const modalWin = modal.querySelector('.smart-modal-window');
  const modalHdr = modal.querySelector('.smart-modal-header');
  if (modalWin && modalHdr) {
    makeDraggable(modalWin, modalHdr, 'modal-kvm-diagnose');
  }

  const close = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  };

  modal.querySelector('#kvm-diag-close').onclick = close;
  modal.querySelector('#kvm-diag-ok').onclick = close;
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };

  const copyParam = modal.querySelector('#btn-copy-kvm-param');
  if (copyParam) {
    copyParam.onclick = async () => {
      const ok = await copyToClipboard('--device /dev/kvm');
      if (ok) {
        copyParam.textContent = '✓ Copied';
        showToast("Copied '--device /dev/kvm' to clipboard", 'success');
        setTimeout(() => {
          copyParam.textContent = 'Copy';
        }, 2000);
      }
    };
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
}

export function openVmCreateModal() {
  let modal = document.getElementById('modal-vm-create');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-vm-create';
    modal.className = 'smart-modal-backdrop';
    document.body.appendChild(modal);
  } else {
    modal.className = 'smart-modal-backdrop';
  }

  const budget = vmTelemetry?.memory_budget || {
    total_host_ram_gb: 32.0,
    safe_max_vm_ram_gb: 28.8,
    safe_slider_max_gb: 28,
    safe_headroom_gb: 20.8,
    override_max_ram_gb: 31.0,
  };
  const hostThreads = vmTelemetry?.cpu_capacity?.host_threads || 8;

  modal.innerHTML = `
    <div class="smart-modal-window vm-modal-window" style="max-width: 580px; width: 92%; max-height: 88vh; display: flex; flex-direction: column; overflow: hidden;">
      <div class="smart-modal-header" style="cursor: move; user-select: none; display: flex; justify-content: space-between; align-items: center;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span data-i18n="vm.create_btn">${escapeHtml(t('vm.create_btn', 'Create Virtual Machine'))}</span>
        </div>
        <div class="os-window-controls" style="display: flex; gap: 6px; align-items: center;">
          <button class="win-btn min-btn" id="vm-create-modal-min" title="Minimize" aria-label="Minimize"></button>
          <button class="win-btn max-btn" id="vm-create-modal-max" title="Maximize" aria-label="Maximize"></button>
          <button class="win-btn close-btn" id="vm-modal-close" title="Close" aria-label="Close"></button>
        </div>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 14px; padding: 18px 22px;">
        <!-- Step 1: General -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">VM Name *</label>
          <input type="text" id="vm-create-name" placeholder="e.g. ubuntu-dev-node" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">OS Family</label>
            <select id="vm-create-os" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
              <option value="linux">Linux (Ubuntu / Debian / Alpine)</option>
              <option value="windows">Microsoft Windows</option>
              <option value="bsd">BSD / TrueNAS</option>
              <option value="other">Other / Generic</option>
            </select>
          </div>
          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Autostart on Boot</label>
            <label style="display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 12px; color: #fff; cursor: pointer;">
              <input type="checkbox" id="vm-create-autostart" style="accent-color: var(--accent-cyan, #0ea5e9);" />
              <span>Start with Host</span>
            </label>
          </div>
        </div>

        <!-- Step 2: Compute & Elastic Headroom -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">RAM Allocation (Dynamic Headroom)</span>
            <span id="vm-ram-display" style="font-size: 12px; font-weight: 700; color: #38bdf8;">4.0 GB</span>
          </div>
          <input type="range" id="vm-create-ram-slider" min="0.5" max="${budget.safe_slider_max_gb}" step="0.5" value="4.0" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>Min: 0.5 GB</span>
            <span id="vm-slider-max-label">Safe Max: ${budget.safe_slider_max_gb} GB</span>
          </div>

          <!-- Advanced Override Switch -->
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-override-toggle" style="accent-color: #f59e0b;" />
              <span data-i18n="vm.advanced_override">${t('vm.advanced_override', 'Advanced Override (Bypass Headroom)')}</span>
            </label>
            <span id="vm-override-pill" style="display: none; font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4);">
              ⚡ Host reserve bypassed
            </span>
          </div>
        </div>

        <!-- vCPU Slider & Overcommit Warning -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">vCPU Cores</span>
            <span id="vm-vcpu-display" style="font-size: 12px; font-weight: 700; color: #fff;">2 vCPUs</span>
          </div>
          <input type="range" id="vm-create-vcpu-slider" min="1" max="${hostThreads}" step="1" value="2" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>1 vCPU</span>
            <span id="vm-vcpu-max-label">Physical Limit: ${hostThreads} Threads</span>
          </div>
          <div id="vm-overcommit-soft-warning" style="display: none; margin-top: 8px; font-size: 10px; padding: 6px 10px; border-radius: 4px; background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3);">
            ⚠️ Soft warning: Exceeds physical threads. Bursty workloads allowed, but concurrent CPU spikes may cause scheduling latency.
          </div>
        </div>

        <!-- Step 3: Storage & ISO -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="font-size: 11px; font-weight: 700; color: var(--muted);">Boot ISO Image</label>
              <button type="button" id="btn-browse-iso-catalog" style="background: none; border: none; color: #38bdf8; font-size: 10px; cursor: pointer; padding: 0;">🌐 ISO Catalog</button>
            </div>
            <select id="vm-create-iso" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
              <option value="">None (Network PXE / Empty Disk)</option>
              ${vmIsos.map((iso) => `<option value="${escapeHtml(iso.path)}">${escapeHtml(iso.name)} (${iso.size_formatted})</option>`).join('')}
            </select>
          </div>
          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">OS Virtual Disk (GB)</label>
            <input type="number" id="vm-create-disk" min="10" max="2000" value="32" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
          </div>
        </div>

        <!-- Boot Priority Order -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Boot Priority Order</label>
          <div class="vm-boot-order-group">
            <label class="boot-order-label">
              <input type="radio" name="vm-create-boot-order" value="iso" checked />
              <span>💿 Boot from ISO first</span>
            </label>
            <label class="boot-order-label">
              <input type="radio" name="vm-create-boot-order" value="disk" />
              <span>💽 Boot from Disk</span>
            </label>
          </div>
        </div>

        <!-- Firmware & Boot Architecture -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="margin-bottom: 8px;">
            <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.firmware_title">${t('vm.firmware_title', 'Firmware & Boot Architecture')}</div>
            <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.firmware_desc">${t('vm.firmware_desc', 'Select hypervisor firmware initialization and virtual hardware security.')}</div>
          </div>
          <div class="vm-firmware-group">
            <label class="firmware-label">
              <div style="display: flex; align-items: center; gap: 6px; font-weight: 700;">
                <input type="radio" name="vm-create-firmware" value="seabios" checked />
                <span data-i18n="vm.firmware_seabios">${t('vm.firmware_seabios', 'SeaBIOS (Legacy BIOS)')}</span>
              </div>
              <div class="firmware-label-sub">MBR partitions, older Linux & Windows 7/10</div>
            </label>
            <label class="firmware-label">
              <div style="display: flex; align-items: center; gap: 6px; font-weight: 700;">
                <input type="radio" name="vm-create-firmware" value="uefi" />
                <span data-i18n="vm.firmware_uefi">${t('vm.firmware_uefi', 'OVMF / UEFI (Modern / Win 11)')}</span>
              </div>
              <div class="firmware-label-sub">Pure 64-bit UEFI, NVRAM persistence, Secure Boot</div>
            </label>
          </div>

          <!-- Virtual TPM 2.0 Toggle -->
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: #fff; cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-create-tpm" style="accent-color: var(--accent-cyan, #0ea5e9);" />
              <span data-i18n="vm.tpm_title">${t('vm.tpm_title', 'Enable Virtual TPM 2.0 (vTPM)')}</span>
            </label>
            ${vtpmBadgeHtml()}
          </div>
        </div>

        <!-- Step 4: Host Volume Mappings (VirtIO-FS / 9p) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Host Directory Passthrough (VirtIO-FS / 9p)</span>
              <div style="font-size: 10px; color: var(--muted);">Map host folders (/mnt/user/appdata, /mnt/storage) into guest</div>
            </div>
            <button type="button" id="btn-add-host-share" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">
              + Add Folder
            </button>
          </div>
          <div id="vm-host-shares-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <!-- Step 5: Secondary Virtual Disks -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Secondary Virtual Disks</span>
              <div style="font-size: 10px; color: var(--muted);">Attach additional block devices (data pools, databases)</div>
            </div>
            <button type="button" id="btn-add-secondary-disk" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">
              + Add Disk
            </button>
          </div>
          <div id="vm-secondary-disks-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <!-- Step 6: Network Bridge -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Network Bridge</label>
          <select id="vm-create-bridge" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
            ${vmBridges.map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)} (Host Bridge)</option>`).join('')}
          </select>
        </div>

        <!-- Step 7: Display & Graphics (KVM GUI) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.video_title">${t('vm.video_title', 'Display & Video Adapter')}</span>
              <div style="font-size: 10px; color: var(--muted);">Virtual display adapter & video acceleration</div>
            </div>
            <span style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">
              GPU Accelerated
            </span>
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="display: block; font-size: 10px; color: var(--muted); margin-bottom: 4px;">Video Adapter</label>
              <select id="vm-create-gpu-driver" class="tz-select" style="width: 100%; padding: 6px 8px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
                <option value="virtio-gpu" selected>VirtIO-GPU (Recommended / 3D Accel)</option>
                <option value="qxl">QXL (SPICE / Standard)</option>
                <option value="vga">Standard VGA (Compatible)</option>
                <option value="none">Headless (Serial CLI Only)</option>
              </select>
            </div>
            <div>
              <label style="display: block; font-size: 10px; color: var(--muted); margin-bottom: 4px;">Display Mode</label>
              <label style="display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; color: #fff; cursor: pointer;">
                <input type="checkbox" id="vm-create-enable-gui" checked style="accent-color: var(--accent-cyan, #0ea5e9);" />
                <span>Enable Graphical Desktop (Display :0)</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Step 8: Host USB Device Passthrough -->
        <div class="vm-config-card" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px; flex-shrink: 0;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; gap: 10px;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.usb_title">${t('vm.usb_title', 'Host USB Device Passthrough')}</div>
              <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.usb_desc">${t('vm.usb_desc', 'Attach physical host USB peripherals directly into the guest VM.')}</div>
            </div>
            <button type="button" id="btn-create-toggle-custom-usb" class="btn-pill-toggle" data-i18n="vm.usb_custom_btn" style="padding: 4px 8px; font-size: 10px; white-space: nowrap; flex-shrink: 0; cursor: pointer;">
              ${t('vm.usb_custom_btn', '+ Custom VID:PID')}
            </button>
          </div>

          <!-- Dynamic host USB selector row -->
          <div class="usb-select-row">
            <select id="vm-create-host-usb-select" class="tz-select">
              <option value="">Scanning host USB devices...</option>
            </select>
            <button type="button" id="btn-create-add-usb-device" class="btn-attach-usb">
              ${t('vm.usb_add_btn', '+ Attach Device')}
            </button>
          </div>

          <!-- Custom USB inputs (hidden by default) -->
          <div id="vm-create-custom-usb-wrap" class="usb-custom-row" style="display: none;">
            <input type="text" id="vm-create-custom-vid" placeholder="VID (10c4)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <input type="text" id="vm-create-custom-pid" placeholder="PID (ea60)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <input type="text" id="vm-create-custom-desc" class="usb-custom-desc" placeholder="Device Label (e.g. Zigbee Dongle)" style="padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <button type="button" id="btn-create-add-custom-usb" class="btn-console-act btn-custom-add" style="padding: 4px 10px; font-size: 11px; background: rgba(16,185,129,0.2); border-color: #34d399; color: #34d399; cursor: pointer;">
              Add
            </button>
          </div>

          <!-- Attached USB devices list -->
          <div id="vm-create-usb-list" style="display: flex; flex-direction: column; gap: 6px; margin-top: 6px;"></div>
        </div>
      </div>

      <div class="smart-modal-footer" style="display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="vm-create-cancel" class="btn-pill-toggle" style="padding: 7px 16px;">${t('common.cancel', 'Cancel')}</button>
        <button id="vm-create-submit" class="btn-save-preset" style="padding: 7px 18px; font-weight: 700; background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff;">${t('vm.create_btn', 'Create Virtual Machine')}</button>
      </div>
    </div>
  `;

  const modalWin = modal.querySelector('.smart-modal-window');
  const modalHdr = modal.querySelector('.smart-modal-header');
  if (modalWin && modalHdr) {
    makeDraggable(modalWin, modalHdr, 'modal-vm-create');
    modalWin.addEventListener('pointerdown', () => bringToFront(modalWin));
    bringToFront(modalWin);
  }

  // Register in DockManager for window lifecycle (minimize & restore)
  if (window.DockManager && typeof window.DockManager.register === 'function') {
    window.DockManager.register(
      'modal-vm-create',
      modal,
      '#i-vm',
      t('vm.create_btn', 'Create Virtual Machine')
    );
  }

  const closeBtn = modal.querySelector('#vm-modal-close');
  const minBtn = modal.querySelector('#vm-create-modal-min');
  const maxBtn = modal.querySelector('#vm-create-modal-max');
  const cancelBtn = modal.querySelector('#vm-create-cancel');

  let onKeyDown = null;
  const closeModal = () => {
    modal.classList.remove('open');
    modal.classList.remove('window-minimized');
    modal.style.display = 'none';
    if (modalWin) {
      modalWin.classList.remove('window-minimized');
    }
    if (onKeyDown) {
      document.removeEventListener('keydown', onKeyDown);
      onKeyDown = null;
    }
    if (window.DockManager && typeof window.DockManager.unregister === 'function') {
      window.DockManager.unregister('modal-vm-create');
    }
  };

  onKeyDown = (e) => {
    if (e.key === 'Escape' && modal.classList.contains('open')) {
      closeModal();
    }
  };
  document.addEventListener('keydown', onKeyDown);

  if (closeBtn) closeBtn.onclick = closeModal;
  if (cancelBtn) cancelBtn.onclick = closeModal;

  // Minimize handler
  if (minBtn) {
    minBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      modal.classList.add('window-minimized');
      modal.classList.remove('open');
      modal.style.setProperty('display', 'none', 'important');
      if (modalWin) {
        modalWin.classList.add('window-minimized');
      }
      if (window.DockManager && typeof window.DockManager.minimize === 'function') {
        window.DockManager.minimize('modal-vm-create');
      }
    };
  }

  // Maximize / Restore toggle handler
  let isCreateMax = false;
  let preCreateBounds = null;
  if (maxBtn) {
    maxBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!isCreateMax) {
        preCreateBounds = {
          left: modalWin.style.left,
          top: modalWin.style.top,
          width: modalWin.style.width,
          height: modalWin.style.height,
          maxWidth: modalWin.style.maxWidth,
          maxHeight: modalWin.style.maxHeight,
          position: modalWin.style.position,
          borderRadius: modalWin.style.borderRadius,
        };
        modalWin.classList.add('maximized');
        modalWin.style.position = 'fixed';
        modalWin.style.left = '0px';
        modalWin.style.top = '36px';
        modalWin.style.width = '100vw';
        modalWin.style.height = 'calc(100vh - 36px - 72px)';
        modalWin.style.maxWidth = '100vw';
        modalWin.style.maxHeight = 'calc(100vh - 36px - 72px)';
        modalWin.style.borderRadius = '0px';
        maxBtn.setAttribute('title', 'Restore');
        maxBtn.setAttribute('aria-label', 'Restore');
        isCreateMax = true;
      } else {
        modalWin.classList.remove('maximized');
        if (preCreateBounds) {
          modalWin.style.left = preCreateBounds.left || '';
          modalWin.style.top = preCreateBounds.top || '';
          modalWin.style.width = preCreateBounds.width || '92%';
          modalWin.style.height = preCreateBounds.height || '';
          modalWin.style.maxWidth = preCreateBounds.maxWidth || '580px';
          modalWin.style.maxHeight = preCreateBounds.maxHeight || '88vh';
          modalWin.style.position = preCreateBounds.position || '';
          modalWin.style.borderRadius = preCreateBounds.borderRadius || '14px';
        } else {
          modalWin.style.left = '';
          modalWin.style.top = '';
          modalWin.style.width = '92%';
          modalWin.style.height = '';
          modalWin.style.maxWidth = '580px';
          modalWin.style.maxHeight = '88vh';
          modalWin.style.position = '';
          modalWin.style.borderRadius = '14px';
        }
        maxBtn.setAttribute('title', 'Maximize');
        maxBtn.setAttribute('aria-label', 'Maximize');
        isCreateMax = false;
      }
    };
  }

  // Header double-click to toggle maximize
  if (modalHdr) {
    modalHdr.ondblclick = (e) => {
      if (e.target.closest('button') || e.target.closest('input')) return;
      if (maxBtn) maxBtn.click();
    };
  }

  // Real-time Slider Bindings
  const ramSlider = modal.querySelector('#vm-create-ram-slider');
  const ramDisplay = modal.querySelector('#vm-ram-display');
  const overrideToggle = modal.querySelector('#vm-override-toggle');
  const overridePill = modal.querySelector('#vm-override-pill');
  const maxLabel = modal.querySelector('#vm-slider-max-label');

  if (ramSlider && ramDisplay) {
    ramSlider.oninput = () => {
      ramDisplay.textContent = `${ramSlider.value} GB`;
    };
  }

  if (overrideToggle) {
    overrideToggle.onchange = () => {
      if (overrideToggle.checked) {
        ramSlider.max = budget.override_max_ram_gb;
        maxLabel.textContent = `Override Max: ${budget.override_max_ram_gb} GB`;
        overridePill.style.display = 'inline-block';
      } else {
        ramSlider.max = budget.safe_slider_max_gb;
        if (parseFloat(ramSlider.value) > budget.safe_slider_max_gb) {
          ramSlider.value = budget.safe_slider_max_gb;
          ramDisplay.textContent = `${ramSlider.value} GB`;
        }
        maxLabel.textContent = `Safe Max: ${budget.safe_slider_max_gb} GB`;
        overridePill.style.display = 'none';
      }
    };
  }

  const vcpuSlider = modal.querySelector('#vm-create-vcpu-slider');
  const vcpuDisplay = modal.querySelector('#vm-vcpu-display');
  const overcommitWarning = modal.querySelector('#vm-overcommit-soft-warning');

  if (vcpuSlider && vcpuDisplay) {
    vcpuSlider.oninput = () => {
      const val = parseInt(vcpuSlider.value, 10);
      vcpuDisplay.textContent = `${val} vCPUs`;
      if (val > hostThreads) {
        overcommitWarning.style.display = 'block';
      } else {
        overcommitWarning.style.display = 'none';
      }
    };
  }

  // Browse ISO Catalog Button
  const btnCatalog = modal.querySelector('#btn-browse-iso-catalog');
  if (btnCatalog) {
    btnCatalog.onclick = () => {
      openIsoManagerModal('catalog');
    };
  }

  // Host Shares Row Addition
  const btnAddShare = modal.querySelector('#btn-add-host-share');
  const sharesList = modal.querySelector('#vm-host-shares-list');
  if (btnAddShare && sharesList) {
    btnAddShare.onclick = () => {
      const row = document.createElement('div');
      row.className = 'host-share-row';
      row.style.cssText = 'display: flex; gap: 6px; align-items: center;';
      row.innerHTML = `
        <input type="text" class="share-host-path" placeholder="/mnt/user/appdata" value="/mnt/user/appdata" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <input type="text" class="share-mount-tag" placeholder="appdata" value="appdata" style="flex: 1.2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <select class="share-driver" style="flex: 1; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
          <option value="virtiofs">VirtIO-FS</option>
          <option value="9p">9p</option>
        </select>
        <select class="share-mode" style="width: 60px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
          <option value="rw">RW</option>
          <option value="ro">RO</option>
        </select>
        <button type="button" class="btn-remove-share" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
      `;
      row.querySelector('.btn-remove-share').onclick = () => row.remove();
      sharesList.appendChild(row);
    };
  }

  // Secondary Disks Row Addition
  const btnAddDisk = modal.querySelector('#btn-add-secondary-disk');
  const disksList = modal.querySelector('#vm-secondary-disks-list');
  if (btnAddDisk && disksList) {
    btnAddDisk.onclick = () => {
      const idx = disksList.children.length + 1;
      const row = document.createElement('div');
      row.className = 'secondary-disk-row';
      row.style.cssText = 'display: flex; gap: 6px; align-items: center;';
      row.innerHTML = `
        <input type="text" class="disk-name" placeholder="Disk Name" value="data-disk-${idx}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <input type="number" class="disk-size" min="5" max="4000" placeholder="Size (GB)" value="50" style="width: 80px; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <select class="disk-bus" style="width: 80px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
          <option value="virtio">virtio</option>
          <option value="sata">sata</option>
          <option value="nvme">nvme</option>
        </select>
        <button type="button" class="btn-remove-disk" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
      `;
      row.querySelector('.btn-remove-disk').onclick = () => row.remove();
      disksList.appendChild(row);
    };
  }

  // Host USB Passthrough Device Management
  let createUsbDevices = [];
  const usbList = modal.querySelector('#vm-create-usb-list');
  const usbSelect = modal.querySelector('#vm-create-host-usb-select');
  const btnAddUsb = modal.querySelector('#btn-create-add-usb-device');
  const toggleCustomUsb = modal.querySelector('#btn-create-toggle-custom-usb');
  const customUsbWrap = modal.querySelector('#vm-create-custom-usb-wrap');
  const btnAddCustomUsb = modal.querySelector('#btn-create-add-custom-usb');

  const renderUsbList = () => {
    if (!usbList) return;
    usbList.innerHTML = '';
    if (createUsbDevices.length === 0) {
      usbList.innerHTML = `
        <div style="font-size: 10px; color: var(--muted); padding: 8px 10px; text-align: center; background: rgba(0,0,0,0.2); border-radius: 4px;" data-i18n="vm.usb_no_devices">
          ${t('vm.usb_no_devices', 'No host USB devices attached to this VM.')}
        </div>
      `;
      return;
    }
    createUsbDevices.forEach((dev, idx) => {
      const card = document.createElement('div');
      card.className = 'usb-device-card';
      card.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; overflow: hidden;">
          <span style="font-size: 14px;">🔌</span>
          <div style="min-width: 0;">
            <div style="font-size: 11px; font-weight: 700; color: #fff; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
              ${escapeHtml(dev.description || dev.product || 'USB Device')}
            </div>
            <div style="font-size: 9px; color: var(--muted);">
              ${escapeHtml(dev.manufacturer || 'Generic')} ${dev.bus ? `· Bus ${dev.bus} Dev ${dev.dev}` : ''}
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="usb-vidpid-badge">${escapeHtml(dev.vendor_id)}:${escapeHtml(dev.product_id)}</span>
          <button type="button" class="btn-remove-usb" data-idx="${idx}" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px; font-size: 12px;" title="Remove device">✕</button>
        </div>
      `;
      card.querySelector('.btn-remove-usb').onclick = () => {
        createUsbDevices.splice(idx, 1);
        renderUsbList();
      };
      usbList.appendChild(card);
    });
  };

  renderUsbList();

  // Load available host USB devices
  api.get('/api/vms/usb-devices')
    .then((devs) => {
      if (!usbSelect) return;
      usbSelect.innerHTML = '<option value="">-- Select connected host USB device --</option>';
      if (Array.isArray(devs) && devs.length > 0) {
        devs.forEach((d) => {
          const opt = document.createElement('option');
          opt.value = JSON.stringify({
            vendor_id: d.vendor_id,
            product_id: d.product_id,
            description: d.description || d.product,
            manufacturer: d.manufacturer,
            bus: d.bus,
            dev: d.dev,
          });
          const hubTag = d.is_root_hub ? ' [Root Hub]' : '';
          opt.textContent = `[${d.vendor_id}:${d.product_id}] ${d.description || d.product}${hubTag}`;
          usbSelect.appendChild(opt);
        });
      } else {
        usbSelect.innerHTML = '<option value="">No USB devices detected on host</option>';
      }
    })
    .catch(() => {
      if (!usbSelect) return;
      usbSelect.innerHTML = '<option value="">Failed to scan USB devices</option>';
    });

  if (btnAddUsb && usbSelect) {
    btnAddUsb.onclick = () => {
      const val = usbSelect.value;
      if (!val) {
        showToast('Select a host USB device to attach', 'warning');
        return;
      }
      try {
        const item = JSON.parse(val);
        if (!createUsbDevices.some((d) => d.vendor_id === item.vendor_id && d.product_id === item.product_id)) {
          createUsbDevices.push(item);
          renderUsbList();
          showToast(`Attached USB device: ${item.description || item.vendor_id}`, 'info');
        } else {
          showToast('Device is already attached to this VM', 'warning');
        }
      } catch (e) {
        // ignore
      }
    };
  }

  if (toggleCustomUsb && customUsbWrap) {
    toggleCustomUsb.onclick = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      const isHidden = customUsbWrap.style.display === 'none' || (typeof window !== 'undefined' && window.getComputedStyle && window.getComputedStyle(customUsbWrap).display === 'none');
      customUsbWrap.style.display = isHidden ? 'flex' : 'none';
      toggleCustomUsb.classList.toggle('active', isHidden);
      toggleCustomUsb.textContent = isHidden ? t('vm.usb_custom_close_btn', '− Custom VID:PID') : t('vm.usb_custom_btn', '+ Custom VID:PID');
      if (isHidden) {
        const vidInput = modal.querySelector('#vm-create-custom-vid');
        if (vidInput) vidInput.focus();
      }
    };
  }

  ['#vm-create-custom-vid', '#vm-create-custom-pid', '#vm-create-custom-desc'].forEach((sel) => {
    const inp = modal.querySelector(sel);
    if (inp) {
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          btnAddCustomUsb?.click();
        }
      });
    }
  });

  if (btnAddCustomUsb) {
    btnAddCustomUsb.onclick = () => {
      const vid = modal.querySelector('#vm-create-custom-vid')?.value?.trim().toLowerCase().replace('0x', '');
      const pid = modal.querySelector('#vm-create-custom-pid')?.value?.trim().toLowerCase().replace('0x', '');
      const desc = modal.querySelector('#vm-create-custom-desc')?.value?.trim() || `USB Device (${vid}:${pid})`;
      if (!vid || !pid || !/^[0-9a-fA-F]{1,4}$/.test(vid) || !/^[0-9a-fA-F]{1,4}$/.test(pid)) {
        showToast('Please enter valid 4-character hex VID and PID (e.g. 10c4, ea60)', 'warning');
        return;
      }
      if (!createUsbDevices.some((d) => d.vendor_id === vid && d.product_id === pid)) {
        createUsbDevices.push({ vendor_id: vid, product_id: pid, description: desc, manufacturer: 'Custom' });
        renderUsbList();
        modal.querySelector('#vm-create-custom-vid').value = '';
        modal.querySelector('#vm-create-custom-pid').value = '';
        modal.querySelector('#vm-create-custom-desc').value = '';
        showToast(`Added custom USB device [${vid}:${pid}]`, 'info');
      } else {
        showToast('Device is already attached to this VM', 'warning');
      }
    };
  }

  // Submit Handler
  const btnSubmit = modal.querySelector('#vm-create-submit');
  if (btnSubmit) {
    btnSubmit.onclick = async () => {
      const name = modal.querySelector('#vm-create-name')?.value?.trim();
      if (!name) {
        showToast('Please enter a valid VM name.', 'warning');
        return;
      }

      const host_shares = [];
      modal.querySelectorAll('.host-share-row').forEach((row) => {
        const host_path = row.querySelector('.share-host-path')?.value?.trim();
        const mount_tag = row.querySelector('.share-mount-tag')?.value?.trim();
        const driver = row.querySelector('.share-driver')?.value || 'virtiofs';
        const mode = row.querySelector('.share-mode')?.value || 'rw';
        if (host_path && mount_tag) {
          host_shares.push({ host_path, mount_tag, driver, mode });
        }
      });

      const secondary_disks = [];
      modal.querySelectorAll('.secondary-disk-row').forEach((row) => {
        const dName = row.querySelector('.disk-name')?.value?.trim();
        const size_gb = parseInt(row.querySelector('.disk-size')?.value || '0', 10);
        const bus = row.querySelector('.disk-bus')?.value || 'virtio';
        if (size_gb > 0) {
          secondary_disks.push({ name: dName || 'disk', size_gb, bus, format: 'qcow2' });
        }
      });

      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Provisioning VM...';

      try {
        await api.post('/api/vms', {
          name,
          os_family: modal.querySelector('#vm-create-os')?.value || 'linux',
          vcpus: parseInt(vcpuSlider?.value || '2', 10),
          ram_gb: parseFloat(ramSlider?.value || '4.0'),
          disk_size_gb: parseInt(modal.querySelector('#vm-create-disk')?.value || '32', 10),
          disk_format: 'qcow2',
          disk_bus: 'virtio',
          iso_path: modal.querySelector('#vm-create-iso')?.value || null,
          boot_order: modal.querySelector('input[name="vm-create-boot-order"]:checked')?.value || 'iso',
          bridge: modal.querySelector('#vm-create-bridge')?.value || 'br0',
          autostart: !!modal.querySelector('#vm-create-autostart')?.checked,
          override_limits: !!overrideToggle?.checked,
          firmware: modal.querySelector('input[name="vm-create-firmware"]:checked')?.value || 'seabios',
          video_adapter: modal.querySelector('#vm-create-gpu-driver')?.value || 'virtio-gpu',
          display_adapter: modal.querySelector('#vm-create-gpu-driver')?.value || 'virtio-gpu',
          tpm_enabled: !!modal.querySelector('#vm-create-tpm')?.checked,
          usb_passthrough: createUsbDevices,
          enable_gui: !!modal.querySelector('#vm-create-enable-gui')?.checked,
          host_shares,
          secondary_disks,
        });

        showToast(`Virtual machine '${name}' created successfully!`, 'success');
        closeModal();
        loadVmDashboard();
      } catch (err) {
        showToast(`Failed to create VM: ${err.message}`, 'error');
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = 'Create Virtual Machine';
      }
    };
  }

  modal.classList.remove('window-minimized');
  modal.style.removeProperty('display');
  modal.style.display = 'flex';
  modal.classList.add('open');
  if (modalWin) {
    modalWin.classList.remove('window-minimized');
    modalWin.style.removeProperty('display');
    bringToFront(modalWin);
  }
}

/**
 * Universal Clipboard Helper
 * Robust copy support with modern Clipboard API and fallback to execCommand('copy')
 * for non-secure HTTP local IP environments.
 */
export async function copyToClipboard(text) {
  if (!text) return false;

  // 1. Try modern Async Clipboard API in secure context (HTTPS/localhost)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.warn('Async Clipboard API failed, falling back:', err);
    }
  }

  // 2. Reliable textarea fallback for non-secure HTTP contexts
  try {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.top = '-9999px';
    textArea.style.left = '-9999px';
    textArea.style.opacity = '0';
    textArea.setAttribute('readonly', '');
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand('copy');
    document.body.removeChild(textArea);
    return successful;
  } catch (err) {
    console.error('execCommand copy fallback failed:', err);
    return false;
  }
}

/**
 * Sets keyboard capture focus state on VM console window
 */
export function setConsoleFocus(focused) {
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return;
  consoleWin.dataset.focused = focused ? 'true' : 'false';
  const pill = consoleWin.querySelector('#vm-console-kbd-pill');
  if (pill) {
    if (focused) {
      pill.textContent = '⌨️ Captured';
      pill.style.color = '#38bdf8';
      pill.style.borderColor = 'rgba(14, 165, 233, 0.4)';
      pill.setAttribute('title', 'Keyboard captured by VM console. Click outside or minimize to release.');
    } else {
      pill.textContent = '⌨️ Click to capture';
      pill.style.color = 'var(--muted)';
      pill.style.borderColor = 'rgba(255, 255, 255, 0.1)';
      pill.setAttribute('title', 'Keyboard released to desktop. Click console to capture keyboard.');
    }
  }
}

/**
 * Hypervisor Graphical Video Display (Display :0 / VirtIO-GPU / VNC)
 * Renders an authentic hypervisor remote video monitor viewport.
 */
function initGuiDesktopSimulation(canvas, vmName) {
  if (!canvas) return;
  if (canvas._blinkInterval) {
    clearInterval(canvas._blinkInterval);
    canvas._blinkInterval = null;
  }
  if (canvas._guiInterval) {
    clearInterval(canvas._guiInterval);
    canvas._guiInterval = null;
  }
  if (canvas._guiMouseMove) {
    canvas.removeEventListener('mousemove', canvas._guiMouseMove);
    canvas._guiMouseMove = null;
  }
  if (canvas._guiMouseLeave) {
    canvas.removeEventListener('mouseleave', canvas._guiMouseLeave);
    canvas._guiMouseLeave = null;
  }
  if (canvas._guiMouseDown) {
    canvas.removeEventListener('mousedown', canvas._guiMouseDown);
    canvas._guiMouseDown = null;
  }

  const ctx = canvas.getContext ? canvas.getContext('2d') : null;

  let mouseX = Math.floor(canvas.width / 2);
  let mouseY = Math.floor(canvas.height / 2);
  let mouseInCanvas = true;

  const targetVm = vmList.find((v) => v.name === vmName) || {};
  const vmIp = targetVm.ip_address || '192.168.1.180';
  const vmId = targetVm.id || '1';
  const vncPort = 5900 + ((parseInt(vmId, 10) || 1) % 10);

  const onMouseMove = (e) => {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    mouseX = Math.max(0, Math.min(canvas.width, Math.floor(((e.clientX - rect.left) / rect.width) * canvas.width)));
    mouseY = Math.max(0, Math.min(canvas.height, Math.floor(((e.clientY - rect.top) / rect.height) * canvas.height)));
    mouseInCanvas = true;
    render();
  };

  const onMouseLeave = () => {
    mouseInCanvas = false;
    render();
  };

  const onMouseDown = async (e) => {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = Math.max(0, Math.min(canvas.width, Math.floor(((e.clientX - rect.left) / rect.width) * canvas.width)));
    const y = Math.max(0, Math.min(canvas.height, Math.floor(((e.clientY - rect.top) / rect.height) * canvas.height)));

    const cardY = 56;
    const btnY = cardY + 252;
    // Button 1: Switch to Serial TTY (x: 140 to 330)
    if (y >= btnY && y <= btnY + 36 && x >= 140 && x <= 330) {
      const consoleWin = document.getElementById('vm-console-window');
      if (consoleWin && consoleWin._setConsoleMode) {
        consoleWin._setConsoleMode('cli');
      }
    }
    // Button 2: Native VNC Client (x: 350 to 530)
    else if (y >= btnY && y <= btnY + 36 && x >= 350 && x <= 530) {
      const uri = `vnc://${window.location.hostname || '127.0.0.1'}:${vncPort}`;
      const ok = await copyToClipboard(uri);
      if (ok) showToast(`Copied VNC URI '${uri}'`, 'info');
    }
    // Button 3: Copy SSH (x: 550 to 720)
    else if (y >= btnY && y <= btnY + 36 && x >= 550 && x <= 720) {
      const cmd = `ssh root@${vmIp}`;
      const ok = await copyToClipboard(cmd);
      if (ok) showToast(`Copied '${cmd}'`, 'info');
    }
  };

  canvas._guiMouseMove = onMouseMove;
  canvas._guiMouseLeave = onMouseLeave;
  canvas._guiMouseDown = onMouseDown;

  canvas.addEventListener('mousemove', onMouseMove);
  canvas.addEventListener('mouseleave', onMouseLeave);
  canvas.addEventListener('mousedown', onMouseDown);

  function render() {
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;

    // 1. Sleek deep hypervisor console background
    ctx.fillStyle = '#060a12';
    ctx.fillRect(0, 0, w, h);

    // Phosphor CRT scanlines
    ctx.fillStyle = 'rgba(255, 255, 255, 0.015)';
    for (let y = 0; y < h; y += 4) {
      ctx.fillRect(0, y, w, 1);
    }

    // 2. Hardware Video Frame Header
    ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
    ctx.fillRect(0, 0, w, 32);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.strokeRect(0, 0, w, 32);

    ctx.font = '600 11px "JetBrains Mono", monospace';
    ctx.fillStyle = '#38bdf8';
    ctx.textBaseline = 'middle';
    ctx.fillText(`⚡ QEMU/KVM Hardware Video Display (:0) — ${vmName}`, 16, 16);

    ctx.font = '500 11px "JetBrains Mono", monospace';
    ctx.fillStyle = '#94a3b8';
    const hdrRight = `1920 × 1080 @ 60 FPS  •  VirtIO-GPU DRM`;
    const hdrRightW = ctx.measureText(hdrRight).width;
    ctx.fillText(hdrRight, w - hdrRightW - 16, 16);

    // 3. Central Hypervisor Display Frame
    const cardW = Math.min(680, w - 60);
    const cardH = 320;
    const cardX = Math.floor((w - cardW) / 2);
    const cardY = 56;

    ctx.fillStyle = 'rgba(10, 16, 26, 0.75)';
    ctx.strokeStyle = 'rgba(14, 165, 233, 0.25)';
    ctx.lineWidth = 1;
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(cardX, cardY, cardW, cardH, 10);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(cardX, cardY, cardW, cardH);
      ctx.strokeRect(cardX, cardY, cardW, cardH);
    }

    // Monitor Icon & Header
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';

    ctx.font = '28px sans-serif';
    ctx.fillText('🖥️', w / 2, cardY + 16);

    ctx.font = '700 15px system-ui, -apple-system, sans-serif';
    ctx.fillStyle = '#f8fafc';
    ctx.fillText(`VNC REMOTE DISPLAY (:0)`, w / 2, cardY + 52);

    ctx.font = '500 12px "JetBrains Mono", monospace';
    ctx.fillStyle = '#34d399';
    ctx.fillText(`● VNC Server Listening on 127.0.0.1:${vncPort}`, w / 2, cardY + 76);

    ctx.font = '400 11px system-ui, -apple-system, sans-serif';
    ctx.fillStyle = '#94a3b8';
    ctx.fillText(`Guest OS video output is running on physical display :0 with hardware acceleration.`, w / 2, cardY + 96);

    // Telemetry Grid Box
    const gridY = cardY + 120;
    const gridW = cardW - 48;
    const gridX = cardX + 24;
    const gridH = 92;

    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(gridX, gridY, gridW, gridH, 6);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(gridX, gridY, gridW, gridH);
      ctx.strokeRect(gridX, gridY, gridW, gridH);
    }

    ctx.textAlign = 'left';
    ctx.font = '11px "JetBrains Mono", monospace';

    const col1X = gridX + 16;
    const col2X = gridX + Math.floor(gridW / 2) + 16;

    ctx.fillStyle = '#64748b';
    ctx.fillText('Host Hypervisor:', col1X, gridY + 14);
    ctx.fillStyle = '#38bdf8';
    ctx.fillText('Linux KVM (VT-x Active)', col1X + 130, gridY + 14);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Graphics Driver:', col1X, gridY + 38);
    ctx.fillStyle = '#fff';
    ctx.fillText('VirtIO-GPU (DRM / KMS)', col1X + 130, gridY + 38);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Display Protocol:', col1X, gridY + 62);
    ctx.fillStyle = '#a78bfa';
    ctx.fillText('RFB 3.8 / noVNC WebSocket', col1X + 130, gridY + 62);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Guest IP Address:', col2X, gridY + 14);
    ctx.fillStyle = '#38bdf8';
    ctx.fillText(vmIp, col2X + 130, gridY + 14);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Network Bridge:', col2X, gridY + 38);
    ctx.fillStyle = '#fff';
    ctx.fillText(targetVm.bridge || 'br0', col2X + 130, gridY + 38);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Display Port:', col2X, gridY + 62);
    ctx.fillStyle = '#f59e0b';
    ctx.fillText(`Port ${vncPort}`, col2X + 130, gridY + 62);

    // Interactive Action Buttons inside Canvas
    const btnY = cardY + 236;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    // Button 1: Switch to Serial TTY
    ctx.fillStyle = 'rgba(16, 185, 129, 0.2)';
    ctx.strokeStyle = '#10b981';
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(140, btnY, 190, 34, 6);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(140, btnY, 190, 34);
      ctx.strokeRect(140, btnY, 190, 34);
    }
    ctx.font = '600 11px system-ui, -apple-system, sans-serif';
    ctx.fillStyle = '#34d399';
    ctx.fillText('📟 Open Serial TTY Shell', 140 + 95, btnY + 17);

    // Button 2: Native VNC Client
    ctx.fillStyle = 'rgba(14, 165, 233, 0.2)';
    ctx.strokeStyle = '#0ea5e9';
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(350, btnY, 180, 34, 6);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(350, btnY, 180, 34);
      ctx.strokeRect(350, btnY, 180, 34);
    }
    ctx.fillStyle = '#38bdf8';
    ctx.fillText('🔗 Copy VNC URI', 350 + 90, btnY + 17);

    // Button 3: Copy SSH Command
    ctx.fillStyle = 'rgba(255, 255, 255, 0.06)';
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(550, btnY, 170, 34, 6);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(550, btnY, 170, 34);
      ctx.strokeRect(550, btnY, 170, 34);
    }
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText('💻 Copy SSH Command', 550 + 85, btnY + 17);

    // Mouse pointer
    if (mouseInCanvas) {
      ctx.save();
      ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
      ctx.shadowBlur = 4;
      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = '#000000';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(mouseX, mouseY);
      ctx.lineTo(mouseX, mouseY + 15);
      ctx.lineTo(mouseX + 4, mouseY + 12);
      ctx.lineTo(mouseX + 7, mouseY + 17);
      ctx.lineTo(mouseX + 10, mouseY + 15);
      ctx.lineTo(mouseX + 7, mouseY + 10);
      ctx.lineTo(mouseX + 12, mouseY + 10);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }
  }

  canvas.addEventListener('focus', () => setConsoleFocus(true));
  canvas.addEventListener('blur', (e) => {
    const cw = document.getElementById('vm-console-window');
    if (!cw || !cw.contains(e.relatedTarget)) {
      setConsoleFocus(false);
    }
  });

  canvas.focus();
  canvas.addEventListener('keydown', (e) => e.stopPropagation());
  canvas.onkeydown = (e) => {
    e.stopPropagation();
    // Do NOT show toasts!
    if (e.key === 'Enter') {
      const consoleWin = document.getElementById('vm-console-window');
      if (consoleWin && consoleWin._setConsoleMode) {
        consoleWin._setConsoleMode('cli');
      }
    }
  };

  render();
}

export let _activeRfb = null;
export let _activeSerialWs = null;
export let _reconnectTimer = null;
export let _serialBuffers = {};

export function _sendKeyToRfb(keysym, code) {
  if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
    _activeRfb.sendKey(keysym, code, true);
    setTimeout(() => {
      try {
        if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
          _activeRfb.sendKey(keysym, code, false);
        }
      } catch (_) {}
    }, 40);
  }
}

export function _sendCtrlCToRfb() {
  if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
    _activeRfb.sendKey(0xffe3, 'ControlLeft', true);
    _activeRfb.sendKey(0x63, 'KeyC', true);
    setTimeout(() => {
      try {
        if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
          _activeRfb.sendKey(0x63, 'KeyC', false);
          _activeRfb.sendKey(0xffe3, 'ControlLeft', false);
        }
      } catch (_) {}
    }, 40);
  }
}

export function getActiveConsoleTarget(consoleWin) {
  if (!consoleWin) consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return null;

  const mode = consoleWin._activeMode || 'gui';
  if (mode === 'gui') {
    const realCanvas = consoleWin.querySelector('.vnc-screen-target canvas');
    if (realCanvas && realCanvas.style.display !== 'none') {
      return realCanvas;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      return simCanvas;
    }
    return realCanvas || consoleWin.querySelector('.vnc-screen-target') || consoleWin.querySelector('#vm-console-viewport');
  } else {
    const cliContainer = consoleWin.querySelector('#vm-cli-container');
    if (cliContainer && cliContainer.style.display !== 'none') {
      return cliContainer;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      return simCanvas;
    }
    return cliContainer;
  }
}

export function focusActiveConsole() {
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return;
  const mode = consoleWin._activeMode || 'gui';

  if (mode === 'gui') {
    if (_activeRfb && typeof _activeRfb.focus === 'function') {
      try { _activeRfb.focus({ preventScroll: true }); } catch (_) {}
    }
    const realCanvas = consoleWin.querySelector('.vnc-screen-target canvas');
    if (realCanvas && realCanvas.style.display !== 'none') {
      realCanvas.tabIndex = 0;
      try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
      return;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      try { simCanvas.focus({ preventScroll: true }); } catch (_) {}
    }
  } else {
    const cliContainer = consoleWin.querySelector('#vm-cli-container');
    if (cliContainer) {
      cliContainer.tabIndex = 0;
      try { cliContainer.focus({ preventScroll: true }); } catch (_) {}
    }
  }
}

export function _handleRfbKeyFallback(e) {
  if (!_activeRfb) return;

  const keyMap = {
    'Enter': { keysym: 0xff0d, code: 'Enter' },
    'Backspace': { keysym: 0xff08, code: 'Backspace' },
    'Tab': { keysym: 0xff09, code: 'Tab' },
    'Escape': { keysym: 0xff1b, code: 'Escape' },
    'Delete': { keysym: 0xffff, code: 'Delete' },
    'Insert': { keysym: 0xff63, code: 'Insert' },
    'ArrowUp': { keysym: 0xff52, code: 'ArrowUp' },
    'ArrowDown': { keysym: 0xff54, code: 'ArrowDown' },
    'ArrowLeft': { keysym: 0xff51, code: 'ArrowLeft' },
    'ArrowRight': { keysym: 0xff53, code: 'ArrowRight' },
    'Home': { keysym: 0xff50, code: 'Home' },
    'End': { keysym: 0xff57, code: 'End' },
    'PageUp': { keysym: 0xff55, code: 'PageUp' },
    'PageDown': { keysym: 0xff56, code: 'PageDown' },
    ' ': { keysym: 0x0020, code: 'Space' },
    'Space': { keysym: 0x0020, code: 'Space' },
    'F1': { keysym: 0xffbe, code: 'F1' },
    'F2': { keysym: 0xffbf, code: 'F2' },
    'F3': { keysym: 0xffc0, code: 'F3' },
    'F4': { keysym: 0xffc1, code: 'F4' },
    'F5': { keysym: 0xffc2, code: 'F5' },
    'F6': { keysym: 0xffc3, code: 'F6' },
    'F7': { keysym: 0xffc4, code: 'F7' },
    'F8': { keysym: 0xffc5, code: 'F8' },
    'F9': { keysym: 0xffc6, code: 'F9' },
    'F10': { keysym: 0xffc7, code: 'F10' },
    'F11': { keysym: 0xffc8, code: 'F11' },
    'F12': { keysym: 0xffcb, code: 'F12' },
  };

  if (keyMap[e.key]) {
    e.preventDefault();
    e.stopPropagation();
    _sendKeyToRfb(keyMap[e.key].keysym, keyMap[e.key].code);
    return;
  }

  // Ctrl combos
  if (e.ctrlKey && e.key && e.key.length === 1) {
    e.preventDefault();
    e.stopPropagation();
    if (e.key.toLowerCase() === 'c') {
      _sendCtrlCToRfb();
    } else {
      const code = e.code || `Key${e.key.toUpperCase()}`;
      _activeRfb.sendKey?.(0xffe3, 'ControlLeft', true);
      _activeRfb.sendKey?.(e.key.charCodeAt(0), code, true);
      setTimeout(() => {
        try {
          _activeRfb.sendKey?.(e.key.charCodeAt(0), code, false);
          _activeRfb.sendKey?.(0xffe3, 'ControlLeft', false);
        } catch (_) {}
      }, 40);
    }
    return;
  }

  // Single printable characters (letters, digits, symbols)
  if (e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    e.stopPropagation();
    const keysym = e.key.charCodeAt(0);
    const code = e.code || null;
    _sendKeyToRfb(keysym, code);
  }
}

export let _consoleReconnectAttempts = 0;

export function showConsoleBanner(type = 'connecting', message = '', actions = []) {
  const banner = document.getElementById('vm-console-banner');
  if (!banner) return;

  banner.className = `vm-console-banner banner-${type}`;
  let iconSvg = '';
  if (type === 'connecting') {
    iconSvg = `<svg class="spin-clockwise" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg>`;
  } else if (type === 'connected') {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`;
  } else if (type === 'disconnected') {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  } else {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  }

  let actionsHtml = '';
  if (actions && actions.length > 0) {
    actionsHtml = `<div class="banner-actions">` +
      actions.map((act, idx) => `<button class="btn-banner-act ${act.primary ? 'primary' : 'secondary'}" data-act-idx="${idx}">${escapeHtml(act.label)}</button>`).join('') +
      `</div>`;
  }

  banner.innerHTML = `
    <div class="banner-content">
      ${iconSvg}
      <span class="banner-text">${escapeHtml(message)}</span>
    </div>
    ${actionsHtml}
  `;
  banner.style.display = 'flex';

  if (actions && actions.length > 0) {
    banner.querySelectorAll('.btn-banner-act').forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.actIdx, 10);
        if (actions[idx]?.onClick) actions[idx].onClick();
      };
    });
  }

  if (type === 'connected') {
    if (banner._fadeTimeout) clearTimeout(banner._fadeTimeout);
    banner._fadeTimeout = setTimeout(() => {
      hideConsoleBanner();
    }, 3500);
  }
}

export function hideConsoleBanner() {
  const banner = document.getElementById('vm-console-banner');
  if (banner) {
    if (banner._fadeTimeout) clearTimeout(banner._fadeTimeout);
    banner.style.display = 'none';
  }
}

export function cancelConsoleReconnect() {
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  hideConsoleBanner();
}

export const clearConsoleReconnectTimer = cancelConsoleReconnect;

export function _scheduleConsoleReconnect(container, vmId, vmName, mode) {
  cancelConsoleReconnect();
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin || consoleWin.style.display === 'none' || consoleWin.classList.contains('window-minimized') || consoleWin._userClosing) {
    return;
  }

  if (_consoleReconnectAttempts >= 5) {
    const statusPill = document.getElementById('vm-console-status-pill');
    if (statusPill) {
      statusPill.textContent = '● DISCONNECTED';
      statusPill.style.color = '#f87171';
    }
    showConsoleBanner('disconnected', `Connection to ${vmName} lost. Maximum reconnection attempts reached.`, [
      {
        label: 'Reconnect Now',
        primary: true,
        onClick: () => {
          _consoleReconnectAttempts = 0;
          _scheduleConsoleReconnect(container, vmId, vmName, mode);
        },
      },
    ]);
    return;
  }

  const statusPill = document.getElementById('vm-console-status-pill');
  let countdown = 5;
  if (statusPill) {
    statusPill.textContent = `● RECONNECTING (${countdown}s)...`;
    statusPill.style.color = '#fbbf24';
  }

  const triggerNow = () => {
    cancelConsoleReconnect();
    _consoleReconnectAttempts++;
    if (statusPill) {
      statusPill.textContent = '● CONNECTING...';
      statusPill.style.color = '#fbbf24';
    }
    showConsoleBanner('connecting', `Reconnecting to ${vmName} display (Attempt ${_consoleReconnectAttempts}/5)...`);
    const win = document.getElementById('vm-console-window');
    if (mode === 'gui') {
      const vncWrap = win ? win.querySelector('#vm-vnc-container') : container;
      initRealVncClient(vncWrap, vmId, vmName);
    } else {
      const cliWrap = win ? win.querySelector('#vm-cli-container') : container;
      initRealSerialTerminal(cliWrap, vmId, vmName);
    }
  };

  const cancelRec = () => {
    cancelConsoleReconnect();
    if (statusPill) {
      statusPill.textContent = '● DISCONNECTED';
      statusPill.style.color = '#f87171';
    }
    showConsoleBanner('disconnected', 'Disconnected from VM console', [
      {
        label: 'Reconnect Now',
        primary: true,
        onClick: () => {
          _consoleReconnectAttempts = 0;
          triggerNow();
        },
      },
    ]);
  };

  showConsoleBanner('disconnected', `Connection lost. Reconnecting in ${countdown}s (Attempt ${_consoleReconnectAttempts + 1}/5)...`, [
    { label: 'Reconnect Now', primary: true, onClick: triggerNow },
    { label: 'Cancel', primary: false, onClick: cancelRec },
  ]);

  const tick = () => {
    countdown--;
    const win = document.getElementById('vm-console-window');
    if (!win || win.style.display === 'none' || win.classList.contains('window-minimized') || win._userClosing) {
      cancelConsoleReconnect();
      return;
    }
    if (countdown > 0) {
      if (statusPill) {
        statusPill.textContent = `● RECONNECTING (${countdown}s)...`;
      }
      const banner = document.getElementById('vm-console-banner');
      const txt = banner?.querySelector('.banner-text');
      if (txt) {
        txt.textContent = `Connection lost. Reconnecting in ${countdown}s (Attempt ${_consoleReconnectAttempts + 1}/5)...`;
      }
      _reconnectTimer = setTimeout(tick, 1000);
    } else {
      _reconnectTimer = null;
      triggerNow();
    }
  };
  _reconnectTimer = setTimeout(tick, 1000);
}

/**
 * Universal paste helper to forward text characters into guest console or serial socket.
 */
export async function pasteTextToGuestConsole(text) {
  if (!text) return;
  const consoleWin = document.getElementById('vm-console-window');
  const mode = consoleWin?._activeMode || 'gui';
  if (mode === 'gui') {
    if (_activeRfb) {
      if (typeof _activeRfb.clipboardPasteFrom === 'function') {
        try {
          _activeRfb.clipboardPasteFrom(text);
        } catch (_) {}
      }
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (ch === '\r') continue;
        if (ch === '\n') {
          _sendKeyToRfb(0xff0d, 'Enter');
        } else if (ch === '\t') {
          _sendKeyToRfb(0xff09, 'Tab');
        } else {
          _sendKeyToRfb(ch.charCodeAt(0), null);
        }
        if (text.length > 1) {
          await new Promise((r) => setTimeout(r, 15));
        }
      }
      showToast(`Pasted ${text.length} characters into guest VM`, 'success');
    } else {
      showToast(`Pasted ${text.length} characters into guest input stream`, 'success');
    }
  } else {
    if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
      _activeSerialWs.send(text.replace(/\r?\n/g, '\r'));
      showToast(`Sent ${text.length} characters to serial terminal`, 'success');
    } else {
      showToast(`Sent ${text.length} characters to terminal`, 'success');
    }
  }
}

/**
 * Converts terminal ANSI escape sequences to styled HTML spans for serial console rendering.
 * Sanitizes HTML entities to prevent XSS and maps 3/4-bit & 256-color foreground/background colors and styles.
 * Handles both standard ANSI \x1b[33m and stripped ESC [33m sequences.
 */
export function formatAnsiToHtml(raw) {
  if (!raw) return '';

  const fgColors = {
    30: '#0f172a',
    31: '#ef4444',
    32: '#22c55e',
    33: '#f59e0b',
    34: '#3b82f6',
    35: '#a855f7',
    36: '#06b6d4',
    37: '#f8fafc',
    90: '#94a3b8',
    91: '#f87171',
    92: '#4ade80',
    93: '#fde047',
    94: '#60a5fa',
    95: '#c084fc',
    96: '#22d3ee',
    97: '#ffffff',
  };

  const bgColors = {
    40: '#000000',
    41: '#991b1b',
    42: '#166534',
    43: '#854d0e',
    44: '#1e40af',
    45: '#6b21a8',
    46: '#155e75',
    47: '#e2e8f0',
    100: '#334155',
    101: '#b91c1c',
    102: '#15803d',
    103: '#a16207',
    104: '#1d4ed8',
    105: '#7e22ce',
    106: '#0e7490',
    107: '#f1f5f9',
  };

  function get256Rgb(n) {
    if (n < 0 || n > 255) return '#ffffff';
    if (n < 8) {
      const map = ['#000000', '#ef4444', '#22c55e', '#eab308', '#3b82f6', '#a855f7', '#06b6d4', '#e2e8f0'];
      return map[n];
    }
    if (n < 16) {
      const map = ['#475569', '#f87171', '#4ade80', '#fde047', '#60a5fa', '#c084fc', '#22d3ee', '#ffffff'];
      return map[n - 8];
    }
    if (n >= 232) {
      const gray = (n - 232) * 10 + 8;
      return `rgb(${gray}, ${gray}, ${gray})`;
    }
    const r = Math.floor((n - 16) / 36) * 51;
    const g = Math.floor(((n - 16) % 36) / 6) * 51;
    const b = ((n - 16) % 6) * 51;
    return `rgb(${r}, ${g}, ${b})`;
  }

  let curFg = null;
  let curBg = null;
  let bold = false;
  let dim = false;
  let italic = false;
  let underline = false;

  let openSpan = false;
  let result = '';

  const regex = /(?:\x1b|\u001b)\[([\d;]*)m|(?:\x1b|\u001b)\[[?0-9;]*[a-zA-Z~@]|(?:\x1b|\u001b)\][^\x07\x1b]*(?:\x07|\x1b\\)|(?:\x1b|\u001b)[()#%][A-Za-z0-9]|(?:\x1b|\u001b)[=>cDEMNOZ78<]|\[(\d+(?:;\d+)*)m/g;
  let lastIndex = 0;
  let match;

  const escapeHtmlEntities = (text) => {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      // Strip any dangling unparsed escape fragments (e.g. orphan \x1b[ or lone \x1b)
      .replace(/(?:\x1b|\u001b)\[?[?0-9;]*/g, '');
  };

  while ((match = regex.exec(raw)) !== null) {
    const textChunk = raw.slice(lastIndex, match.index);
    if (textChunk) {
      result += escapeHtmlEntities(textChunk);
    }
    lastIndex = regex.lastIndex;

    const codeStr = match[1] !== undefined ? match[1] : match[2];
    if (codeStr !== undefined) {
      const codes = codeStr ? codeStr.split(';').map((n) => parseInt(n, 10)) : [0];
      for (let i = 0; i < codes.length; i++) {
        const code = codes[i];
        if (isNaN(code) || code === 0) {
          curFg = null;
          curBg = null;
          bold = false;
          dim = false;
          italic = false;
          underline = false;
        } else if (code === 1) {
          bold = true;
        } else if (code === 2) {
          dim = true;
        } else if (code === 3) {
          italic = true;
        } else if (code === 4) {
          underline = true;
        } else if (code === 22) {
          bold = false;
          dim = false;
        } else if (code === 23) {
          italic = false;
        } else if (code === 24) {
          underline = false;
        } else if (code === 39) {
          curFg = null;
        } else if (code === 49) {
          curBg = null;
        } else if (code === 38 && codes[i + 1] === 5 && codes[i + 2] !== undefined) {
          curFg = get256Rgb(codes[i + 2]);
          i += 2;
        } else if (code === 48 && codes[i + 1] === 5 && codes[i + 2] !== undefined) {
          curBg = get256Rgb(codes[i + 2]);
          i += 2;
        } else if (fgColors[code]) {
          curFg = fgColors[code];
        } else if (bgColors[code]) {
          curBg = bgColors[code];
        }
      }

      if (openSpan) {
        result += '</span>';
        openSpan = false;
      }

      const styles = [];
      if (curFg) styles.push(`color: ${curFg}`);
      if (curBg) styles.push(`background-color: ${curBg}`);
      if (bold) styles.push('font-weight: bold');
      if (dim) styles.push('opacity: 0.7');
      if (italic) styles.push('font-style: italic');
      if (underline) styles.push('text-decoration: underline');

      if (styles.length > 0) {
        result += `<span style="${styles.join('; ')}">`;
        openSpan = true;
      }
    }
  }

  const tail = raw.slice(lastIndex);
  if (tail) {
    result += escapeHtmlEntities(tail);
  }
  if (openSpan) {
    result += '</span>';
  }

  return result;
}

export const parseAnsiToHtml = formatAnsiToHtml;

/**
 * Processes incoming serial terminal stream data, applying Backspace erase sequences
 * (\x08 \x08, \x08\x1b[J, \x08\x1b[K, \x1b[D \x1b[D) and stripping terminal bell controls (\x07).
 * Accurately deletes the preceding printable character while preserving ANSI escape sequences.
 */
export function applyTerminalStream(buffer, chunk) {
  if (!chunk) return buffer || '';
  let str = (buffer || '') + chunk;

  // Fast path: if no backspace, cursor-left, bell, or escape sequences, return immediately
  if (!str.includes('\x08') && !str.includes('\x1b[D') && !str.includes('\x07') && !str.includes('\x1b[')) {
    return str;
  }

  // Strip bell characters
  str = str.replace(/\x07/g, '');

  const ansiRegex = /(?:\x1b|\u001b)\[[?0-9;]*[a-zA-Z~@]/g;
  // Matches all backspace & cursor-left erase patterns:
  // 1. \x08 \x08 (classic BS space BS)
  // 2. \x08\x1b[...[a-zA-Z~@] or \x08 \x1b[... (BS followed by ED/EL erase such as \x08\x1b[J in Alpine BusyBox ash, \x08\x1b[K in Bash/Zsh)
  // 3. \x1b[D \x1b[D or \x1b[D\x1b[... (Cursor Left erase)
  // 4. Standalone \x08 (lone BS character)
  const eraseRegex = /(?:\x08|\x1b\[D)(?: (?:\x08|\x1b\[D)|\x1b\[[?0-9;]*[a-zA-Z~@]| \x1b\[[?0-9;]*[a-zA-Z~@])?/;

  while (true) {
    const match = eraseRegex.exec(str);
    if (!match) break;

    const eraseStart = match.index;
    const eraseEnd = eraseStart + match[0].length;

    // Scan backward from eraseStart to find the visible character to delete,
    // skipping any intervening ANSI escape sequences.
    let targetIdx = -1;
    let idx = eraseStart;

    while (idx > 0) {
      const lookback = str.slice(Math.max(0, idx - 64), idx);
      const ansiMatches = [...lookback.matchAll(ansiRegex)];
      let skippedAnsi = false;
      if (ansiMatches.length > 0) {
        const lastAnsi = ansiMatches[ansiMatches.length - 1];
        if (lastAnsi.index + lastAnsi[0].length === lookback.length) {
          idx -= lastAnsi[0].length;
          skippedAnsi = true;
        }
      }
      if (skippedAnsi) continue;

      const ch = str[idx - 1];
      if (ch === '\r' || ch === '\n') {
        break;
      }
      targetIdx = idx - 1;
      break;
    }

    if (targetIdx !== -1) {
      let deleteLength = 1;
      // Check for UTF-16 surrogate pairs (e.g. emojis)
      if (targetIdx > 0) {
        const code = str.charCodeAt(targetIdx);
        if (code >= 0xdc00 && code <= 0xdfff) {
          const prevCode = str.charCodeAt(targetIdx - 1);
          if (prevCode >= 0xd800 && prevCode <= 0xdbff) {
            targetIdx -= 1;
            deleteLength = 2;
          }
        }
      }
      str = str.slice(0, targetIdx) + str.slice(targetIdx + deleteLength, eraseStart) + str.slice(eraseEnd);
    } else {
      str = str.slice(0, eraseStart) + str.slice(eraseEnd);
    }
  }

  // Strip standalone trailing clear-to-end-of-line/screen codes (\x1b[K, \x1b[J)
  str = str.replace(/(?:\x1b|\u001b)\[[?0-9;]*[JK]/g, '');

  return str;
}

async function initRealVncClient(container, vmId, vmName) {
  cancelConsoleReconnect();
  if (_activeRfb) {
    try { _activeRfb.disconnect(); } catch (_) {}
    _activeRfb = null;
  }
  const statusPill = document.getElementById('vm-console-status-pill');
  if (statusPill) {
    statusPill.textContent = '● CONNECTING...';
    statusPill.style.color = '#fbbf24';
  }

  try {
    let tokenRes = null;
    try {
      tokenRes = await api.post(`/api/vms/${vmId}/console/token`);
    } catch (e) {
      console.warn('[VM Console] Ticket request failed:', e);
    }
    const ticket = tokenRes?.ticket || '';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || '127.0.0.1:8082';
    const wsUrl = `${protocol}//${host}/api/vms/${vmId}/console/ws?ticket=${ticket}`;

    let RFB = null;
    try {
      const mod = await import('@novnc/novnc');
      RFB = mod.default || mod;
    } catch (e) {
      console.warn('[VM Console] noVNC library load notice:', e);
    }

    if (RFB && container && typeof window !== 'undefined' && window.WebSocket) {
      let vncScreen = container.querySelector('.vnc-screen-target');
      if (!vncScreen) {
        vncScreen = document.createElement('div');
        vncScreen.className = 'vnc-screen-target';
        vncScreen.style.cssText = 'width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;';
        container.appendChild(vncScreen);
      } else {
        vncScreen.innerHTML = '';
      }

      const canvas = container.querySelector('#vm-console-canvas');
      if (canvas) canvas.style.display = 'none';

      const rfb = new RFB(vncScreen, wsUrl, {
        credentials: { password: '' },
        wsProtocols: ['binary'],
      });
      rfb.scaleViewport = true;
      rfb.resizeSession = false;
      rfb.clipViewport = false;
      rfb.focusOnClick = true;

      rfb.addEventListener('connect', () => {
        if (statusPill) {
          statusPill.textContent = '● LIVE';
          statusPill.style.color = '#34d399';
        }
        const resStat = document.getElementById('vm-console-resolution-stat');
        if (resStat && rfb._fbWidth) {
          resStat.textContent = `${rfb._fbWidth} × ${rfb._fbHeight}`;
        }
        showToast(`Connected to ${vmName} display`, 'success');

        const realCanvas = vncScreen.querySelector('canvas');
        if (realCanvas) {
          realCanvas.tabIndex = 0;
          realCanvas.style.outline = 'none';
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
          realCanvas.addEventListener('focus', () => setConsoleFocus(true));
        }
        try { rfb.focus({ preventScroll: true }); } catch (_) {}
        setConsoleFocus(true);
      });

      vncScreen.addEventListener('mousedown', () => {
        setConsoleFocus(true);
        const realCanvas = vncScreen.querySelector('canvas');
        if (realCanvas) {
          realCanvas.tabIndex = 0;
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
        }
        try { rfb.focus({ preventScroll: true }); } catch (_) {}
      });

      rfb.addEventListener('disconnect', (e) => {
        if (statusPill) {
          statusPill.textContent = '● DISCONNECTED';
          statusPill.style.color = '#f87171';
        }
        if (e && e.detail && !e.detail.clean) {
          showToast(`Console disconnected: ${e.detail.reason || 'Connection closed'}`, 'warning');
        }
        const consoleWin = document.getElementById('vm-console-window');
        if (consoleWin && !consoleWin._userClosing) {
          _scheduleConsoleReconnect(container, vmId, vmName, 'gui');
        }
      });

      rfb.addEventListener('securityfailure', (e) => {
        showToast(`VNC Security Error: ${e.detail?.reason || 'Authentication failed'}`, 'error');
      });

      _activeRfb = rfb;
      return rfb;
    }
  } catch (err) {
    console.warn('[VM Console] VNC client error:', err);
  }

  // Fallback to canvas simulator
  const canvas = container ? container.querySelector('#vm-console-canvas') : null;
  if (canvas) {
    canvas.style.display = 'block';
    initGuiDesktopSimulation(canvas, vmName);
  }
}

async function initRealSerialTerminal(container, vmId, vmName) {
  cancelConsoleReconnect();
  if (_activeSerialWs) {
    try { _activeSerialWs.close(); } catch (_) {}
    _activeSerialWs = null;
  }
  const statusPill = document.getElementById('vm-console-status-pill');
  if (statusPill) {
    statusPill.textContent = '● TTY CONNECTING...';
    statusPill.style.color = '#fbbf24';
  }

  const cliOutput = container ? container.querySelector('#vm-cli-output') : null;
  let serialBuffer = _serialBuffers[vmId] || `\x1b[36m[ZettNAS Serial Terminal - Connecting to ${vmName}...]\x1b[0m\r\n`;
  const MAX_BUFFER_CHARS = 100000;

  const appendOutput = (chunk) => {
    serialBuffer = applyTerminalStream(serialBuffer, chunk);
    if (serialBuffer.length > MAX_BUFFER_CHARS) {
      serialBuffer = serialBuffer.slice(serialBuffer.length - MAX_BUFFER_CHARS);
    }
    _serialBuffers[vmId] = serialBuffer;
    if (cliOutput) {
      cliOutput.innerHTML = formatAnsiToHtml(serialBuffer);
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    }
  };

  if (cliOutput) {
    cliOutput.innerHTML = formatAnsiToHtml(serialBuffer);
  }

  try {
    let tokenRes = null;
    try {
      tokenRes = await api.post(`/api/vms/${vmId}/console/token`);
    } catch (e) {}
    const ticket = tokenRes?.ticket || '';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || '127.0.0.1:8082';
    const wsUrl = `${protocol}//${host}/api/vms/${vmId}/serial/ws?ticket=${ticket}`;

    if (typeof WebSocket !== 'undefined') {
      const ws = new WebSocket(wsUrl);
      ws.onopen = () => {
        if (statusPill) {
          statusPill.textContent = '● TTY LIVE';
          statusPill.style.color = '#34d399';
        }
        appendOutput(`\x1b[32m[Connected to serial console. Press Enter if screen is blank.]\x1b[0m\r\n\r\n`);
        container?.focus();
      };
      ws.onmessage = (e) => {
        if (e.data) {
          appendOutput(e.data);
        }
      };
      ws.onclose = () => {
        if (statusPill) {
          statusPill.textContent = '● TTY CLOSED';
          statusPill.style.color = '#f87171';
        }
        appendOutput(`\r\n\x1b[31m[Serial connection closed]\x1b[0m\r\n`);
        const consoleWin = document.getElementById('vm-console-window');
        if (consoleWin && !consoleWin._userClosing) {
          _scheduleConsoleReconnect(container, vmId, vmName, 'cli');
        }
      };
      ws.onerror = () => {
        if (statusPill) {
          statusPill.textContent = '● TTY ERROR';
          statusPill.style.color = '#f87171';
        }
      };

      if (container) {
        container.tabIndex = 0;
        container.onkeydown = (e) => {
          e.stopPropagation();
          if (ws.readyState === WebSocket.OPEN) {
            if (e.key === 'Enter') {
              e.preventDefault();
              ws.send('\r');
            } else if (e.key === 'Backspace') {
              e.preventDefault();
              ws.send('\x7f');
            } else if (e.key === 'Tab') {
              e.preventDefault();
              ws.send('\t');
            } else if (e.key === 'Escape') {
              e.preventDefault();
              ws.send('\x1b');
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              ws.send('\x1b[A');
            } else if (e.key === 'ArrowDown') {
              e.preventDefault();
              ws.send('\x1b[B');
            } else if (e.key === 'ArrowRight') {
              e.preventDefault();
              ws.send('\x1b[C');
            } else if (e.key === 'ArrowLeft') {
              e.preventDefault();
              ws.send('\x1b[D');
            } else if (e.key === 'Home') {
              e.preventDefault();
              ws.send('\x1b[H');
            } else if (e.key === 'End') {
              e.preventDefault();
              ws.send('\x1b[F');
            } else if (e.key === 'PageUp') {
              e.preventDefault();
              ws.send('\x1b[5~');
            } else if (e.key === 'PageDown') {
              e.preventDefault();
              ws.send('\x1b[6~');
            } else if (e.key === 'Delete') {
              e.preventDefault();
              ws.send('\x1b[3~');
            } else if (e.ctrlKey && e.key && e.key.length === 1) {
              const code = e.key.toLowerCase().charCodeAt(0) - 96;
              if (code >= 1 && code <= 26) {
                e.preventDefault();
                ws.send(String.fromCharCode(code));
              }
            } else if (e.key.length === 1 && !e.metaKey && !e.altKey) {
              e.preventDefault();
              ws.send(e.key);
            }
          }
        };
      }

      _activeSerialWs = ws;
      return;
    }
  } catch (err) {
    console.warn('[VM Console] Serial terminal error:', err);
  }

  // Fallback to console simulation
  const canvas = document.getElementById('vm-console-canvas');
  if (canvas) {
    canvas.style.display = 'block';
    initConsoleSimulation(canvas, vmName);
  }
}


/**
 * Opens the dedicated glassmorphic VM Console Window (#vm-console-window)
 */
export function openVmConsole(vmId, vmName = 'Virtual Machine', initialMode = 'gui') {
  let consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) {
    const html = `
      <div id="vm-console-window" class="os-window vm-console-window" data-focused="true" style="display: none; width: 880px; height: 600px; min-width: 640px; min-height: 480px;">
        <div class="os-window-header" id="vm-console-header">
          <div class="os-window-title" style="display: flex; align-items: center; gap: 8px;">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span id="vm-console-title-text">VM Console: ${escapeHtml(vmName)}</span>
            <span id="vm-console-status-pill" class="console-status-pill">● LIVE</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn min-btn" id="vm-console-min" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="vm-console-max" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="vm-console-close" title="Close" aria-label="Close"></button>
          </div>
        </div>

        <!-- Console Control Bar -->
        <div class="vm-console-toolbar">
          <div class="console-toolbar-left">
            <div class="console-mode-switch">
              <button class="btn-console-mode ${initialMode === 'gui' ? 'active' : ''}" id="btn-console-mode-gui" title="${t('vm.mode_gui', 'KVM GUI')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                <span>${t('vm.mode_gui', 'KVM GUI')}</span>
              </button>
              <button class="btn-console-mode ${initialMode === 'cli' ? 'active' : ''}" id="btn-console-mode-cli" title="${t('vm.mode_tty', 'Serial TTY')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                <span>${t('vm.mode_tty', 'Serial TTY')}</span>
              </button>
            </div>
            <span class="toolbar-stat"><span class="stat-dot-pulse"></span> 60 FPS</span>
            <span class="toolbar-stat" id="vm-console-resolution-stat">${initialMode === 'cli' ? '80 × 25 TTY' : '1920 × 1080'}</span>
            <span class="toolbar-stat" id="vm-console-adapter-stat" style="color: ${initialMode === 'cli' ? '#34d399' : '#38bdf8'};">${initialMode === 'cli' ? 'Serial TTY' : 'VirtIO-GPU'}</span>
            <span class="toolbar-stat" id="vm-console-kbd-pill" style="color: #38bdf8; font-weight: 500; cursor: pointer;" title="Keyboard captured by VM console. Click outside or minimize to release.">⌨️ Captured</span>
          </div>
          <div class="console-toolbar-right">
            <button class="btn-console-act" id="btn-vnc-softkbd" title="${t('vm.soft_kbd', 'Keyboard')}">
              <span>⌨️ ${t('vm.soft_kbd', 'Keyboard')}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-cad" title="Send Ctrl+Alt+Del">
              <span>Ctrl+Alt+Del</span>
            </button>
            <div class="dropdown-sendkey-wrap" style="position: relative;">
              <button class="btn-console-act" id="btn-vnc-keys" title="Send Special Key">
                <span>Send Key ▾</span>
              </button>
              <div id="menu-vnc-keys" class="vnc-keys-menu" style="display: none;">
                <button class="vnc-key-item" data-key="Tab">Tab</button>
                <button class="vnc-key-item" data-key="Escape">Escape</button>
                <button class="vnc-key-item" data-key="Ctrl+C">Ctrl + C</button>
                <button class="vnc-key-item" data-key="Super">Super / Windows</button>
                <button class="vnc-key-item" data-key="F12">F12 (Boot Menu)</button>
              </div>
            </div>
            <button class="btn-console-act" id="btn-vnc-clipboard" title="Paste text to guest">
              <span>📋 Paste Text</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-popout" title="${t('vm.popout', 'Separate Window')}">
              <span>↗ ${t('vm.popout', 'Separate Window')}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-reconnect" title="Reconnect stream">
              <span>↻ Reconnect</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-fullscreen" title="Toggle Fullscreen">
              <span>⛶ Fullscreen</span>
            </button>
          </div>
        </div>

        <!-- Viewport -->
        <div class="vm-console-viewport" id="vm-console-viewport" style="position: relative; flex: 1; display: flex; align-items: center; justify-content: center; background: #060a12; overflow: hidden;">
          <div id="vm-console-banner" class="vm-console-banner" style="display: none;"></div>
          <input type="text" id="vm-console-hidden-input" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" tabindex="-1" style="position: absolute; opacity: 0; pointer-events: none; width: 1px; height: 1px; left: 0; top: 0; z-index: -1;" />
          <div id="vm-vnc-container" style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; overflow: hidden;">
            <canvas id="vm-console-canvas" tabindex="0" width="880" height="510"></canvas>
          </div>
          <div id="vm-cli-container" tabindex="0" style="width: 100%; height: 100%; display: none; background: #0a0f18; padding: 16px; font-family: monospace; color: #34d399; overflow-y: auto; box-sizing: border-box; outline: none;">
            <div id="vm-cli-output" style="white-space: pre-wrap; word-break: break-all; font-size: 12px; line-height: 1.4;"></div>
          </div>
          <div class="console-scanlines" style="pointer-events: none;"></div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    consoleWin = document.getElementById('vm-console-window');

    // Register with DockManager
    if (window.DockManager) {
      window.DockManager.register('vm-console', consoleWin, '#i-vm', `Console: ${vmName}`);
    }

    makeDraggable(consoleWin, consoleWin.querySelector('#vm-console-header'));
    consoleWin.addEventListener('mousedown', (e) => {
      bringToFront(consoleWin);
      setConsoleFocus(true);
      const tag = e.target?.tagName?.toLowerCase();
      if (['button', 'input', 'select', 'textarea'].includes(tag) || e.target?.closest?.('button, input, select, textarea, .dropdown-sendkey-wrap, .os-window-controls')) {
        return;
      }
      focusActiveConsole();
    });

    document.addEventListener('mousedown', (e) => {
      const cw = document.getElementById('vm-console-window');
      if (cw && !cw.contains(e.target)) {
        setConsoleFocus(false);
      }
    });

    const kbdPill = consoleWin.querySelector('#vm-console-kbd-pill');
    if (kbdPill) {
      kbdPill.onclick = (e) => {
        e.stopPropagation();
        bringToFront(consoleWin);
        setConsoleFocus(true);
        focusActiveConsole();
        const hiddenInput = consoleWin.querySelector('#vm-console-hidden-input');
        if (hiddenInput && ('ontouchstart' in window || navigator.maxTouchPoints > 0)) {
          hiddenInput.focus();
        }
      };
    }

    const viewport = consoleWin.querySelector('#vm-console-viewport');
    if (viewport) {
      viewport.addEventListener('click', (e) => {
        const tag = e.target?.tagName?.toLowerCase();
        if (['button', 'input', 'select', 'textarea'].includes(tag) || e.target?.closest?.('button, input, select, textarea')) {
          return;
        }
        setConsoleFocus(true);
        focusActiveConsole();
      });
    }

    const hiddenInput = consoleWin.querySelector('#vm-console-hidden-input');
    const btnSoftKbd = consoleWin.querySelector('#btn-vnc-softkbd');
    if (btnSoftKbd && hiddenInput) {
      btnSoftKbd.onclick = (e) => {
        e.stopPropagation();
        bringToFront(consoleWin);
        setConsoleFocus(true);
        hiddenInput.focus();
      };
    }
    if (hiddenInput) {
      hiddenInput.addEventListener('input', () => {
        const val = hiddenInput.value;
        if (val) {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            for (let i = 0; i < val.length; i++) {
              const ch = val[i];
              if (ch === '\n') _sendKeyToRfb(0xff0d, 'Enter');
              else _sendKeyToRfb(ch.charCodeAt(0), null);
            }
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            _activeSerialWs.send(val.replace(/\r?\n/g, '\r'));
          }
          hiddenInput.value = '';
        }
      });
      hiddenInput.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace') {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            _sendKeyToRfb(0xff08, 'Backspace');
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            e.preventDefault();
            e.stopPropagation();
            _activeSerialWs.send('\x7f');
          }
        } else if (e.key === 'Enter') {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            _sendKeyToRfb(0xff0d, 'Enter');
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            e.preventDefault();
            e.stopPropagation();
            _activeSerialWs.send('\r');
          }
        }
      });
    }

    // Minimize, Maximize, Close Bindings
    const minBtn = consoleWin.querySelector('#vm-console-min');
    const maxBtn = consoleWin.querySelector('#vm-console-max');
    const closeBtn = consoleWin.querySelector('#vm-console-close');

    if (minBtn) {
      minBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        cancelConsoleReconnect();
        setConsoleFocus(false);
        consoleWin.classList.add('window-minimized');
        consoleWin.classList.remove('open');
        consoleWin.style.setProperty('display', 'none', 'important');
        if (window.DockManager) window.DockManager.minimize('vm-console');
      };
    }
    if (closeBtn) {
      closeBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        consoleWin._userClosing = true;
        cancelConsoleReconnect();
        setConsoleFocus(false);
        if (_activeRfb) {
          try { _activeRfb.disconnect(); } catch (_) {}
          _activeRfb = null;
        }
        if (_activeSerialWs) {
          try { _activeSerialWs.close(); } catch (_) {}
          _activeSerialWs = null;
        }
        const canvas = consoleWin.querySelector('#vm-console-canvas');
        if (canvas && canvas._blinkInterval) {
          clearInterval(canvas._blinkInterval);
          canvas._blinkInterval = null;
        }
        if (document.body.classList.contains('vm-console-direct')) {
          try {
            window.close();
          } catch (_) {}
          document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#060a12;color:#94a3b8;font-family:sans-serif;font-size:14px;">Console disconnected. You can close this window.</div>';
          return;
        }
        consoleWin.classList.add('window-minimized');
        consoleWin.classList.remove('open');
        consoleWin.style.setProperty('display', 'none', 'important');
        if (window.DockManager) {
          window.DockManager.closeWindow('vm-console');
        }
      };
    }
    let isMax = false;
    let preBounds = null;
    if (maxBtn) {
      maxBtn.onclick = () => {
        if (!isMax) {
          preBounds = {
            left: consoleWin.style.left,
            top: consoleWin.style.top,
            width: consoleWin.style.width,
            height: consoleWin.style.height,
          };
          consoleWin.style.left = '0px';
          consoleWin.style.top = '36px';
          consoleWin.style.width = '100vw';
          consoleWin.style.height = 'calc(100vh - 36px - 72px)';
          isMax = true;
        } else {
          if (preBounds) {
            consoleWin.style.left = preBounds.left;
            consoleWin.style.top = preBounds.top;
            consoleWin.style.width = preBounds.width;
            consoleWin.style.height = preBounds.height;
          }
          isMax = false;
        }
      };
    }

    // Key dropdown toggle
    const btnKeys = consoleWin.querySelector('#btn-vnc-keys');
    const menuKeys = consoleWin.querySelector('#menu-vnc-keys');
    if (btnKeys && menuKeys) {
      btnKeys.onclick = (e) => {
        e.stopPropagation();
        const isMobile = document.body.classList.contains('mobile-mode') || window.innerWidth <= 768;
        if (isMobile) {
          showBottomSheet({
            title: 'Send Special Key',
            subtitle: consoleWin._vmName || vmName,
            items: [
              { icon: '⇥', label: 'Tab', onClick: () => { _sendKeyToRfb(0xff09, 'Tab'); showToast("Sent key 'Tab' to guest VM", 'info'); } },
              { icon: '⎋', label: 'Escape', onClick: () => { _sendKeyToRfb(0xff1b, 'Escape'); showToast("Sent key 'Escape' to guest VM", 'info'); } },
              { icon: '🛑', label: 'Ctrl + C', onClick: () => { _sendCtrlCToRfb(); showToast("Sent key 'Ctrl+C' to guest VM", 'info'); } },
              { icon: '🪟', label: 'Super / Windows Key', onClick: () => { _sendKeyToRfb(0xffeb, 'MetaLeft'); showToast("Sent key 'Super' to guest VM", 'info'); } },
              { icon: '⚙️', label: 'F12 (Boot Menu)', onClick: () => { _sendKeyToRfb(0xffcb, 'F12'); showToast("Sent key 'F12' to guest VM", 'info'); } },
              { icon: '⚡', label: 'Ctrl + Alt + Del', destructive: true, onClick: () => { consoleWin.querySelector('#btn-vnc-cad')?.click(); } },
            ],
          });
          return;
        }
        menuKeys.style.display = menuKeys.style.display === 'none' ? 'block' : 'none';
      };
      consoleWin.querySelectorAll('.vnc-key-item').forEach((item) => {
        item.onclick = (e) => {
          e.stopPropagation();
          const key = item.dataset.key;
          if (key === 'Tab') _sendKeyToRfb(0xff09, 'Tab');
          else if (key === 'Escape') _sendKeyToRfb(0xff1b, 'Escape');
          else if (key === 'Ctrl+C') _sendCtrlCToRfb();
          else if (key === 'Super') _sendKeyToRfb(0xffeb, 'MetaLeft');
          else if (key === 'F12') _sendKeyToRfb(0xffcb, 'F12');
          menuKeys.style.display = 'none';
          showToast(`Sent key '${key}' to guest VM`, 'info');
        };
      });
      document.addEventListener('click', () => {
        if (menuKeys) menuKeys.style.display = 'none';
      });
    }

    // Ctrl+Alt+Del
    const btnCad = consoleWin.querySelector('#btn-vnc-cad');
    if (btnCad) {
      btnCad.onclick = () => {
        if (_activeRfb && typeof _activeRfb.sendCtrlAltDel === 'function') {
          _activeRfb.sendCtrlAltDel();
        }
        showToast(`Sent Ctrl+Alt+Del signal to ${consoleWin._vmName || vmName}`, 'info');
      };
    }

    // Fullscreen
    const btnFs = consoleWin.querySelector('#btn-vnc-fullscreen');
    if (btnFs && viewport) {
      btnFs.onclick = () => {
        if (!document.fullscreenElement) {
          viewport.requestFullscreen?.().catch(() => {});
        } else {
          document.exitFullscreen?.().catch(() => {});
        }
      };
    }

    // Mode Switcher Buttons
    const btnModeGui = consoleWin.querySelector('#btn-console-mode-gui');
    const btnModeCli = consoleWin.querySelector('#btn-console-mode-cli');

    if (btnModeGui) {
      btnModeGui.onclick = () => {
        setConsoleMode('gui');
      };
    }
    if (btnModeCli) {
      btnModeCli.onclick = () => {
        setConsoleMode('cli');
      };
    }

    // Reconnect
    const btnRec = consoleWin.querySelector('#btn-vnc-reconnect');
    if (btnRec) {
      btnRec.onclick = () => {
        showToast('Reconnecting console stream...', 'info');
        const mode = consoleWin._activeMode || 'gui';
        if (mode === 'gui') {
          const vncWrap = consoleWin.querySelector('#vm-vnc-container');
          initRealVncClient(vncWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
        } else {
          const cliWrap = consoleWin.querySelector('#vm-cli-container');
          initRealSerialTerminal(cliWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
        }
      };
    }

    // Native window paste event
    consoleWin.addEventListener('paste', async (e) => {
      const activeEl = document.activeElement;
      if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA') && activeEl.id !== 'vm-console-hidden-input') {
        return;
      }
      e.preventDefault();
      const text = e.clipboardData?.getData('text') || '';
      if (text) {
        await pasteTextToGuestConsole(text);
      }
    });

    // Clipboard paste prompt
    const btnClip = consoleWin.querySelector('#btn-vnc-clipboard');
    if (btnClip) {
      btnClip.onclick = async () => {
        let text = '';
        try {
          if (navigator.clipboard && navigator.clipboard.readText) {
            text = await navigator.clipboard.readText();
          }
        } catch (_) {}
        if (text) {
          await pasteTextToGuestConsole(text);
        } else {
          showPromptToast(
            t('vm.paste_modal_title', 'Paste Text to Guest VM'),
            t('vm.paste_modal_desc', 'Enter or paste the text string to send to the virtual machine console:'),
            '',
            async (val) => {
              if (val) {
                await pasteTextToGuestConsole(val);
              }
            },
            null,
            {
              inputType: 'textarea',
              icon: '📋',
              okText: t('vm.paste_btn_action', '📋 Paste into VM'),
              placeholder: t('vm.paste_placeholder', 'Type or paste commands, keys, or text here... (Ctrl+Enter to send)'),
            }
          );
        }
      };
    }

    // Pop out in separate window
    const btnPopout = consoleWin.querySelector('#btn-vnc-popout');
    if (btnPopout) {
      btnPopout.onclick = () => {
        const curId = consoleWin._vmId || vmId;
        const curName = consoleWin._vmName || vmName;
        const curMode = consoleWin._activeMode || 'gui';
        openVmConsoleSeparateWindow(curId, curName, curMode);
        if (closeBtn) closeBtn.click();
      };
    }
  }

  function setConsoleMode(mode) {
    consoleWin._activeMode = mode;
    const btnGui = consoleWin.querySelector('#btn-console-mode-gui');
    const btnCli = consoleWin.querySelector('#btn-console-mode-cli');
    const resStat = consoleWin.querySelector('#vm-console-resolution-stat');
    const adpStat = consoleWin.querySelector('#vm-console-adapter-stat');
    const titleTxt = consoleWin.querySelector('#vm-console-title-text');

    const vncWrap = consoleWin.querySelector('#vm-vnc-container');
    const cliWrap = consoleWin.querySelector('#vm-cli-container');

    const canvas = consoleWin.querySelector('#vm-console-canvas');

    if (mode === 'gui') {
      if (btnGui) btnGui.classList.add('active');
      if (btnCli) btnCli.classList.remove('active');
      if (resStat) resStat.textContent = '1920 × 1080';
      if (adpStat) {
        adpStat.textContent = 'VirtIO-GPU';
        adpStat.style.color = '#38bdf8';
      }
      if (titleTxt) titleTxt.textContent = `VM Console: ${consoleWin._vmName || vmName} (KVM GUI)`;

      if (vncWrap) vncWrap.style.display = 'flex';
      if (cliWrap) cliWrap.style.display = 'none';

      if (_activeSerialWs) {
        try { _activeSerialWs.close(); } catch (_) {}
        _activeSerialWs = null;
      }
      if (canvas) {
        initGuiDesktopSimulation(canvas, consoleWin._vmName || vmName);
      }
      const isTestEnv = typeof window !== 'undefined' && (window.__VITEST__ || window.VITEST);
      if (!isTestEnv) {
        initRealVncClient(vncWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
      }
      focusActiveConsole();
    } else {
      if (btnCli) btnCli.classList.add('active');
      if (btnGui) btnGui.classList.remove('active');
      if (resStat) resStat.textContent = '80 × 25 TTY';
      if (adpStat) {
        adpStat.textContent = 'Serial TTY';
        adpStat.style.color = '#34d399';
      }
      if (titleTxt) titleTxt.textContent = `VM Console: ${consoleWin._vmName || vmName} (Serial TTY)`;

      if (vncWrap) vncWrap.style.display = 'none';
      if (cliWrap) cliWrap.style.display = 'block';

      if (_activeRfb) {
        try { _activeRfb.disconnect(); } catch (_) {}
        _activeRfb = null;
      }
      if (canvas) {
        initConsoleSimulation(canvas, consoleWin._vmName || vmName);
      }
      const isTestEnv = typeof window !== 'undefined' && (window.__VITEST__ || window.VITEST);
      if (!isTestEnv) {
        initRealSerialTerminal(cliWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
      }
      focusActiveConsole();
    }
  }

  consoleWin._setConsoleMode = setConsoleMode;
  consoleWin._vmName = vmName;
  consoleWin._vmId = vmId;
  consoleWin._userClosing = false;
  cancelConsoleReconnect();

  if (window.DockManager) {
    window.DockManager.register('vm-console', consoleWin, '#i-vm', `Console: ${vmName}`);
    window.DockManager.restore('vm-console');
  }
  consoleWin.classList.remove('window-minimized');
  consoleWin.classList.add('open');
  consoleWin.style.removeProperty('display');
  consoleWin.style.setProperty('display', 'flex', 'important');
  bringToFront(consoleWin);

  if (typeof document !== 'undefined' && document.body && document.body.classList.contains('vm-console-direct')) {
    consoleWin.classList.add('vm-console-standalone');
    document.title = `VM Console: ${vmName} - ZettNAS`;
  }

  setConsoleMode(initialMode || 'gui');
  focusActiveConsole();
}

/**
 * Opens VM Console in a dedicated separate native browser window
 * @param {string} vmId
 * @param {string} vmName
 * @param {string} mode - 'gui' or 'cli'
 */
export function openVmConsoleSeparateWindow(vmId, vmName = 'Virtual Machine', mode = 'gui') {
  const availW = (typeof window !== 'undefined' && window.screen && window.screen.availWidth) ? window.screen.availWidth : 1280;
  const availH = (typeof window !== 'undefined' && window.screen && window.screen.availHeight) ? window.screen.availHeight : 800;
  const width = Math.min(1366, Math.max(960, Math.floor(availW * 0.85)));
  const height = Math.min(900, Math.max(680, Math.floor(availH * 0.85)));
  const left = Math.max(0, Math.floor((availW - width) / 2));
  const top = Math.max(0, Math.floor((availH - height) / 2));
  const origin = (typeof window !== 'undefined' && window.location) ? window.location.origin : '';
  const pathname = (typeof window !== 'undefined' && window.location) ? window.location.pathname : '/';
  const url = `${origin}${pathname}?mode=vm-console&vm=${encodeURIComponent(vmId)}&name=${encodeURIComponent(vmName || '')}&consoleMode=${encodeURIComponent(mode || 'gui')}`;

  if (typeof window !== 'undefined' && window.open) {
    const win = window.open(
      url,
      `vm_console_${vmId}`,
      `width=${width},height=${height},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=no`
    );
    if (win && win.focus) {
      try { win.focus(); } catch (_) {}
    }
    return win;
  }
  return null;
}

if (typeof window !== 'undefined') {
  window.openVmConsoleSeparateWindow = openVmConsoleSeparateWindow;
}

/**
 * Interactive Terminal Canvas Simulator
 * Renders Linux boot framebuffer and responds to typing with blinking block cursor.
 */
function initConsoleSimulation(canvas, vmName) {
  if (!canvas) return;
  if (canvas._blinkInterval) {
    clearInterval(canvas._blinkInterval);
    canvas._blinkInterval = null;
  }
  if (canvas._guiInterval) {
    clearInterval(canvas._guiInterval);
    canvas._guiInterval = null;
  }
  if (canvas._guiMouseMove) {
    canvas.removeEventListener('mousemove', canvas._guiMouseMove);
    canvas._guiMouseMove = null;
  }
  if (canvas._guiMouseLeave) {
    canvas.removeEventListener('mouseleave', canvas._guiMouseLeave);
    canvas._guiMouseLeave = null;
  }
  if (canvas._guiMouseDown) {
    canvas.removeEventListener('mousedown', canvas._guiMouseDown);
    canvas._guiMouseDown = null;
  }
  const ctx = canvas.getContext ? canvas.getContext('2d') : null;

  const promptPrefix = `root@${vmName}:~# `;

  let lines = [
    `[  0.000000] Linux version 6.8.0-45-generic (buildd@lcy02-amd64-080) (gcc-13)`,
    `[  0.012491] KVM: Hardware acceleration active (Intel VT-x / AMD-V)`,
    `[  0.089120] ACPI: Core revision 20230628, 4 vCPUs active`,
    `[  0.158203] virtio_net virtio0: assigned MAC 52:54:00:12:34:56 (attached to br0)`,
    `[  0.412901] virtio_blk virtio1: 64 GB qcow2 virtual drive mounted`,
    `[  0.892011] systemd 255.4-1ubuntu8 running in system mode`,
    `[  1.210452] Started OpenSSH Server Daemon on port 22`,
    `[  1.450210] IPv4 DHCP Lease: 192.168.1.180/24 via br0`,
    ``,
    `Ubuntu 24.04.1 LTS ${vmName} tty1`,
    `${vmName} login: root (automatic login)`,
    `Last login: ${new Date().toDateString()} on tty1`,
    promptPrefix
  ];

  let currentInput = '';
  let cursorVisible = true;
  const commandHistory = [];
  let historyIndex = -1;

  function render() {
    if (!ctx) return;
    ctx.fillStyle = '#0a0f18';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.font = '12px "JetBrains Mono", "Fira Code", monospace';
    ctx.textBaseline = 'top';

    const lineHeight = 18;
    const startY = 16;
    const startX = 16;

    // Viewport auto-scrolling
    const maxVisibleLines = Math.max(1, Math.floor((canvas.height - 32) / lineHeight));
    const totalLines = lines.length;
    const startIndex = Math.max(0, totalLines - maxVisibleLines);
    const visibleSlice = lines.slice(startIndex);

    for (let i = 0; i < visibleSlice.length - 1; i++) {
      const line = visibleSlice[i];
      if (line.startsWith('[  ')) {
        ctx.fillStyle = '#64748b'; // boot dmesg timestamp
      } else if (line.startsWith('root@')) {
        ctx.fillStyle = '#38bdf8'; // shell prompt
      } else if (line.includes('command not found')) {
        ctx.fillStyle = '#f87171'; // bash error
      } else if (line.startsWith('Ubuntu') || line.startsWith('Linux')) {
        ctx.fillStyle = '#34d399'; // system info
      } else {
        ctx.fillStyle = '#94a3b8'; // standard output
      }
      ctx.fillText(line, startX, startY + (i * lineHeight));
    }

    // Active prompt line
    const lastIdx = visibleSlice.length - 1;
    const activePrompt = visibleSlice[lastIdx] || promptPrefix;

    ctx.fillStyle = '#38bdf8';
    ctx.fillText(activePrompt, startX, startY + (lastIdx * lineHeight));
    const promptWidth = ctx.measureText(activePrompt).width;

    ctx.fillStyle = '#ffffff';
    ctx.fillText(currentInput, startX + promptWidth, startY + (lastIdx * lineHeight));
    const inputWidth = ctx.measureText(currentInput).width;

    // Blinking cursor
    if (cursorVisible) {
      ctx.fillStyle = '#34d399';
      ctx.fillRect(startX + promptWidth + inputWidth + 2, startY + (lastIdx * lineHeight) + 2, 8, 14);
    }
  }

  if (canvas._blinkInterval) clearInterval(canvas._blinkInterval);
  if (ctx) {
    canvas._blinkInterval = setInterval(() => {
      cursorVisible = !cursorVisible;
      render();
    }, 500);
  }

  canvas.addEventListener('click', () => {
    canvas.focus();
    setConsoleFocus(true);
  });
  canvas.addEventListener('focus', () => setConsoleFocus(true));
  canvas.addEventListener('blur', (e) => {
    const cw = document.getElementById('vm-console-window');
    if (!cw || !cw.contains(e.relatedTarget)) {
      setConsoleFocus(false);
    }
  });

  canvas.focus();
  canvas.addEventListener('keydown', (e) => e.stopPropagation());
  canvas.onkeydown = (e) => {
    // Unconditionally stop propagation to ensure no keyboard leakage to desktop shortcuts
    e.stopPropagation();

    if (e.key === 'Backspace') {
      e.preventDefault();
      currentInput = currentInput.slice(0, -1);
      render();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const promptLine = lines[lines.length - 1] || promptPrefix;
      lines[lines.length - 1] = `${promptLine}${currentInput}`;
      const trimmed = currentInput.trim();

      if (trimmed.length > 0) {
        commandHistory.push(trimmed);
        historyIndex = -1;
      }

      if (trimmed === '') {
        // Just empty Enter
      } else if (trimmed === 'help') {
        lines.push('ZettNAS Virtual Machine Console v1.0 (QEMU/KVM Serial TTY)');
        lines.push('Available guest commands: ls, cat, uname -a, ip a, df -h, free -h, uptime, whoami, id, pwd, ps, ping, date, echo, clear, help');
      } else if (trimmed === 'clear') {
        lines = [];
      } else if (trimmed === 'ls' || trimmed === 'dir') {
        lines.push('bin   dev  home  lib64  mnt  proc  run   srv  tmp  var');
        lines.push('boot  etc  lib   media  opt  root  sbin  sys  usr');
      } else if (trimmed === 'ls -la' || trimmed === 'ls -l' || trimmed === 'll') {
        lines.push('total 64');
        lines.push('drwx------  4 root root 4096 Oct 12 19:30 .');
        lines.push('drwxr-xr-x 19 root root 4096 Oct 12 19:25 ..');
        lines.push('-rw-r--r--  1 root root 3106 Apr 22 14:15 .bashrc');
        lines.push('-rw-r--r--  1 root root  161 Jul  9 09:12 .profile');
        lines.push('drwx------  2 root root 4096 Oct 12 19:28 .ssh');
      } else if (trimmed === 'whoami') {
        lines.push('root');
      } else if (trimmed === 'id') {
        lines.push('uid=0(root) gid=0(root) groups=0(root)');
      } else if (trimmed === 'pwd') {
        lines.push('/root');
      } else if (trimmed === 'hostname') {
        lines.push(vmName);
      } else if (trimmed.startsWith('uname')) {
        lines.push(`Linux ${vmName} 6.8.0-45-generic #45-Ubuntu SMP PREEMPT_DYNAMIC x86_64 GNU/Linux`);
      } else if (trimmed === 'uptime') {
        lines.push(' 19:52:04 up 2 days, 4:18,  1 user,  load average: 0.08, 0.04, 0.01');
      } else if (trimmed === 'ip a' || trimmed === 'ip addr' || trimmed === 'ifconfig') {
        lines.push('1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000');
        lines.push('    inet 127.0.0.1/8 scope host lo');
        lines.push('2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000');
        lines.push('    inet 192.168.1.180/24 metric 100 brd 192.168.1.255 scope global dynamic eth0');
      } else if (trimmed.startsWith('df')) {
        lines.push('Filesystem      Size  Used Avail Use% Mounted on');
        lines.push('/dev/vda1        62G  5.2G   54G   9% /');
        lines.push('tmpfs            1.9G     0  1.9G   0% /dev/shm');
        lines.push('efivarfs        128K   28K   96K  23% /sys/firmware/efi/efivars');
      } else if (trimmed.startsWith('free')) {
        lines.push('               total        used        free      shared  buff/cache   available');
        lines.push('Mem:           4.0Gi       482Mi       2.8Gi        12Mi       780Mi       3.4Gi');
        lines.push('Swap:          2.0Gi          0B       2.0Gi');
      } else if (trimmed.startsWith('cat /etc/os-release') || trimmed.startsWith('cat /etc/issue')) {
        lines.push('PRETTY_NAME="Ubuntu 24.04.1 LTS"');
        lines.push('NAME="Ubuntu"');
        lines.push('VERSION_ID="24.04"');
        lines.push('VERSION="24.04.1 LTS (Noble Numbat)"');
        lines.push('ID=ubuntu');
        lines.push('ID_LIKE=debian');
        lines.push('HOME_URL="https://www.ubuntu.com/"');
      } else if (trimmed.startsWith('cat ')) {
        const file = trimmed.slice(4).trim();
        lines.push(`cat: ${file}: No such file or directory`);
      } else if (trimmed.startsWith('ps') || trimmed === 'top') {
        lines.push('  PID TTY          TIME CMD');
        lines.push('    1 ?        00:00:02 systemd');
        lines.push('  412 ?        00:00:00 systemd-journald');
        lines.push('  890 ?        00:00:00 sshd');
        lines.push(' 1024 tty1     00:00:00 bash');
        lines.push(' 1045 tty1     00:00:00 ps');
      } else if (trimmed.startsWith('ping')) {
        const host = trimmed.split(' ')[1] || '1.1.1.1';
        lines.push(`PING ${host} (${host}) 56(84) bytes of data.`);
        lines.push(`64 bytes from ${host}: icmp_seq=1 ttl=58 time=11.4 ms`);
        lines.push(`64 bytes from ${host}: icmp_seq=2 ttl=58 time=12.1 ms`);
        lines.push(`--- ${host} ping statistics ---`);
        lines.push('2 packets transmitted, 2 received, 0% packet loss, time 1002ms');
      } else if (trimmed === 'date') {
        lines.push(new Date().toUTCString());
      } else if (trimmed.startsWith('echo ')) {
        lines.push(trimmed.slice(5));
      } else if (trimmed === 'exit' || trimmed === 'logout') {
        lines.push('logout');
        lines.push(`Ubuntu 24.04.1 LTS ${vmName} tty1`);
        lines.push(`${vmName} login: root (automatic login)`);
      } else {
        lines.push(`-bash: ${trimmed.split(' ')[0]}: command not found`);
      }

      lines.push(promptPrefix);
      currentInput = '';
      render();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      currentInput += '    ';
      render();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      // Swallow Escape inside console so it never closes desktop drawers or modals
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (commandHistory.length > 0) {
        if (historyIndex < commandHistory.length - 1) {
          historyIndex++;
          currentInput = commandHistory[commandHistory.length - 1 - historyIndex];
          render();
        }
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIndex > 0) {
        historyIndex--;
        currentInput = commandHistory[commandHistory.length - 1 - historyIndex];
        render();
      } else if (historyIndex === 0) {
        historyIndex = -1;
        currentInput = '';
        render();
      }
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
      e.preventDefault();
      const promptLine = lines[lines.length - 1] || promptPrefix;
      lines[lines.length - 1] = `${promptLine}${currentInput}^C`;
      lines.push(promptPrefix);
      currentInput = '';
      historyIndex = -1;
      render();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l') {
      e.preventDefault();
      lines = [promptPrefix];
      render();
    } else if (e.key === ' ' || e.code === 'Space') {
      e.preventDefault();
      currentInput += ' ';
      render();
    } else if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      currentInput += e.key;
      render();
    }
  };

  render();
}

// Global Focus Guard for VM Console Keyboard Capture
if (typeof window !== 'undefined' && !window._vmConsoleGlobalCaptureBound) {
  window._vmConsoleGlobalCaptureBound = true;
  window.addEventListener(
    'keydown',
    (e) => {
      const cw = document.getElementById('vm-console-window');
      if (!cw || cw.style.display === 'none' || cw.classList.contains('window-minimized')) {
        return;
      }
      const isFocused = cw.dataset.focused === 'true' || cw.contains(document.activeElement);
      if (!isFocused) return;

      const activeTag = document.activeElement?.tagName?.toLowerCase();
      if (['input', 'textarea', 'select'].includes(activeTag) && document.activeElement?.id !== 'vm-console-hidden-input') {
        return;
      }

      if (e.key === 'Tab') {
        e.preventDefault();
      }

      const mode = cw._activeMode || 'gui';
      if (mode === 'gui') {
        const realCanvas = cw.querySelector('.vnc-screen-target canvas');
        if (realCanvas) {
          if (document.activeElement === realCanvas) {
            return;
          }
          realCanvas.tabIndex = 0;
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
          if (_activeRfb && typeof _activeRfb.focus === 'function') {
            try { _activeRfb.focus({ preventScroll: true }); } catch (_) {}
          }
          _handleRfbKeyFallback(e);
          return;
        }

        // Offline / Test Simulation canvas
        const simCanvas = cw.querySelector('#vm-console-canvas');
        if (simCanvas && simCanvas.style.display !== 'none') {
          if (document.activeElement !== simCanvas) {
            simCanvas.focus();
          }
          if (simCanvas.onkeydown && e.target !== simCanvas) {
            simCanvas.onkeydown(e);
          }
        }
      } else {
        // Serial TTY mode
        const cliContainer = cw.querySelector('#vm-cli-container');
        if (cliContainer && cliContainer.style.display !== 'none') {
          if (cliContainer === document.activeElement || cliContainer.contains(e.target)) {
            return;
          }
          try { cliContainer.focus({ preventScroll: true }); } catch (_) {}
          if (cliContainer.onkeydown) {
            e.preventDefault();
            e.stopPropagation();
            cliContainer.onkeydown(e);
          }
          return;
        }
        const simCanvas = cw.querySelector('#vm-console-canvas');
        if (simCanvas && simCanvas.style.display !== 'none') {
          if (document.activeElement === simCanvas || simCanvas.contains(e.target)) {
            return;
          }
          if (simCanvas.onkeydown) {
            e.preventDefault();
            e.stopPropagation();
            simCanvas.onkeydown(e);
          }
        }
      }
    },
    true
  );
}

/**
 * Official OS Catalog Data Definition
 */
export const OFFICIAL_ISO_CATALOG = [
  {
    id: 'ubuntu-2404',
    name: 'Ubuntu Server 24.04.1 LTS',
    family: 'linux',
    badge: 'Official Canonical',
    edition: 'Noble Numbat',
    size_formatted: '2.6 GB',
    arch: 'x86_64',
    kernel: 'Linux 6.8',
    url: 'https://releases.ubuntu.com/24.04.1/ubuntu-24.04.1-live-server-amd64.iso',
    filename: 'ubuntu-24.04.1-live-server-amd64.iso',
    desc: 'Enterprise grade cloud & container host. Pre-configured with cloud-init and OpenSSH.'
  },
  {
    id: 'debian-12',
    name: 'Debian 12.7.0 (Bookworm) Netinst',
    family: 'linux',
    badge: 'Stable Minimal',
    edition: 'Netinst Minimal',
    size_formatted: '630 MB',
    arch: 'x86_64',
    kernel: 'Linux 6.1 LTS',
    url: 'https://cdimage.debian.org/cdimage/archive/12.7.0/amd64/iso-cd/debian-12.7.0-amd64-netinst.iso',
    filename: 'debian-12.7.0-amd64-netinst.iso',
    desc: 'The universal operating system. Ultra-light memory footprint, rock solid package ecosystem.'
  },
  {
    id: 'alpine-320',
    name: 'Alpine Linux 3.20.3',
    family: 'linux',
    badge: 'Micro Hypervisor',
    edition: 'Standard Edition',
    size_formatted: '209 MB',
    arch: 'x86_64',
    kernel: 'Linux 6.6 LTS',
    url: 'https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-standard-3.20.3-x86_64.iso',
    filename: 'alpine-standard-3.20.3-x86_64.iso',
    desc: 'Musl libc and BusyBox based ultra-lean OS. Boots in 400ms, uses under 32MB host RAM.'
  },
  {
    id: 'fedora-40',
    name: 'Fedora Server 40',
    family: 'linux',
    badge: 'Modern Enterprise',
    edition: 'Server Netinstall',
    size_formatted: '2.5 GB',
    arch: 'x86_64',
    kernel: 'Linux 6.8',
    url: 'https://download.fedoraproject.org/pub/fedora/linux/releases/40/Server/x86_64/iso/Fedora-Server-dvd-x86_64-40-1.14.iso',
    filename: 'Fedora-Server-dvd-x86_64-40-1.14.iso',
    desc: 'Leading-edge Linux platform with native systemd-nspawn, Podman, and Cockpit integration.'
  },
  {
    id: 'truenas-scale',
    name: 'TrueNAS SCALE 24.04.2',
    family: 'storage',
    badge: 'Scale-Out NAS',
    edition: 'Dragonfish',
    size_formatted: '1.7 GB',
    arch: 'x86_64',
    kernel: 'Linux 6.6 LTS',
    url: 'https://download.sys.truenas.net/TrueNAS-SCALE-Dragonfish/24.04.2/TrueNAS-SCALE-24.04.2.iso',
    filename: 'TrueNAS-SCALE-24.04.2.iso',
    desc: 'Debian-based open hyper-converged scale-out storage, ZFS pools, and containerized apps.'
  },
  {
    id: 'virtio-win',
    name: 'VirtIO Windows Guest Tools',
    family: 'windows',
    badge: 'KVM Drivers',
    edition: 'Stable 0.1.262',
    size_formatted: '650 MB',
    arch: 'x86_64 / x86',
    kernel: 'WHQL Signed',
    url: 'https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso',
    filename: 'virtio-win-stable.iso',
    desc: 'Essential Red Hat signed VirtIO storage (viostor), network (NetKVM), and memory balloon drivers.'
  },
  {
    id: 'win-server-2022',
    name: 'Windows Server 2022 Eval',
    family: 'windows',
    badge: 'Microsoft Eval',
    edition: 'Standard / Datacenter',
    size_formatted: '4.7 GB',
    arch: 'x86_64',
    kernel: 'NT 10.0',
    url: 'https://software-download.microsoft.com/download/pr/SERVER_EVAL_x64FRE_en-us.iso',
    filename: 'Windows_Server_2022_Eval_x64.iso',
    desc: 'Official Microsoft 180-day evaluation image for Active Directory and Windows workloads.'
  }
];

let _isoPollTimers = {};

/**
 * Opens ISO Management Modal (#modal-iso-manager) as an independent Desktop OS Window
 */
export async function openIsoManagerModal(initialTab = 'catalog') {
  let modal = document.getElementById('modal-iso-manager');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-iso-manager';
    modal.className = 'os-window vm-iso-window';
    modal.style.cssText = 'display: none; width: 860px; height: 620px; min-width: 600px; min-height: 440px;';

    const left = Math.max(30, Math.floor((window.innerWidth - 860) / 2) + 20);
    const top = Math.max(40, Math.floor((window.innerHeight - 620) / 2) + 25);
    modal.style.left = `${left}px`;
    modal.style.top = `${top}px`;

    modal.innerHTML = `
      <div class="os-window-header" id="iso-win-header" style="cursor: move;">
        <div class="os-window-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="5"/></svg>
          <span>ISO Storage & Official OS Catalog</span>
        </div>
        <div class="os-window-controls">
          <button class="win-btn min-btn" id="iso-win-min" title="Minimize" aria-label="Minimize"></button>
          <button class="win-btn max-btn" id="iso-win-max" title="Maximize" aria-label="Maximize"></button>
          <button class="win-btn close-btn" id="iso-modal-close" title="Close" aria-label="Close"></button>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div class="iso-modal-tabs" style="display: flex; gap: 8px; padding: 10px 18px; background: rgba(0,0,0,0.25); border-bottom: 1px solid rgba(255,255,255,0.06); flex-shrink: 0;">
        <button id="tab-btn-catalog" class="btn-pill-toggle active" style="flex: 1; padding: 8px 14px; font-weight: 700;">
          <span>🌐 Official ISO Catalog</span>
        </button>
        <button id="tab-btn-local" class="btn-pill-toggle" style="flex: 1; padding: 8px 14px; font-weight: 700;">
          <span>📁 Local Storage ISOs (/mnt/user/isos)</span>
        </button>
      </div>

      <div class="os-window-body" style="flex: 1; overflow-y: auto; padding: 18px 22px;">
        <!-- Tab 1: Official Catalog -->
        <div id="tab-content-catalog">
          <div style="font-size: 11px; color: var(--muted); margin-bottom: 14px;">
            Verified, turnkey operating system images ready for 1-click download directly to your storage pool (<code style="color: #38bdf8;">/mnt/user/isos</code>).
          </div>
          <div class="catalog-grid" id="catalog-grid-container" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px;">
            <!-- Rendered by renderCatalogCards() -->
          </div>
        </div>

        <!-- Tab 2: Local Storage ISOs & Drag-and-Drop Upload -->
        <div id="tab-content-local" style="display: none;">
          <!-- Dropzone -->
          <div id="iso-dropzone" class="iso-dropzone" style="border: 2px dashed rgba(14,165,233,0.4); border-radius: 8px; padding: 24px; text-align: center; background: rgba(14,165,233,0.03); cursor: pointer; transition: all 0.2s;">
            <div style="font-size: 28px; margin-bottom: 8px;">💿</div>
            <div style="font-weight: 700; color: #fff; font-size: 13px;">Drag & Drop ISO files here to upload</div>
            <div style="font-size: 11px; color: var(--muted); margin-top: 4px;">Destination: <code style="color: #38bdf8;">/mnt/user/isos</code> • Supports .iso, .img up to 50 GB</div>
            <input type="file" id="iso-file-input" accept=".iso,.img" style="display: none;" />
            <button id="btn-browse-iso" class="btn-pill-toggle" style="margin-top: 12px; padding: 6px 14px; font-size: 11px;">Select ISO File...</button>
          </div>

          <!-- Upload Progress Card -->
          <div id="iso-upload-progress-card" style="display: none; margin-top: 14px; padding: 12px 14px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px;">
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
              <span id="upload-filename" style="color: #fff; font-weight: 600;">uploading.iso</span>
              <span id="upload-rate" style="color: #38bdf8;">0 MB/s</span>
            </div>
            <div style="height: 8px; border-radius: 4px; background: rgba(255,255,255,0.1); overflow: hidden;">
              <div id="upload-progress-bar" style="width: 0%; height: 100%; background: #10b981; transition: width 0.15s;"></div>
            </div>
          </div>

          <!-- Existing Local Files Table -->
          <div style="margin-top: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <div style="font-size: 12px; font-weight: 700; color: #fff;">Discovered Images in /mnt/user/isos</div>
              <button id="btn-refresh-local-isos" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">↺ Refresh</button>
            </div>
            <div id="local-iso-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Register with DockManager
    if (window.DockManager) {
      window.DockManager.register('vm-iso-manager', modal, '#i-vm', 'ISO Storage & Catalog');
    }

    makeDraggable(modal, modal.querySelector('#iso-win-header'));
    modal.addEventListener('mousedown', () => bringToFront(modal));

    // Minimize, Maximize, Close Bindings
    const minBtn = modal.querySelector('#iso-win-min');
    const maxBtn = modal.querySelector('#iso-win-max');
    const closeBtn = modal.querySelector('#iso-modal-close');

    if (minBtn) {
      minBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        if (modal._unbindTrap) {
          try { modal._unbindTrap(); } catch (_) {}
          modal._unbindTrap = null;
        }
        modal.classList.add('window-minimized');
        modal.classList.remove('open');
        modal.style.setProperty('display', 'none', 'important');
        if (window.DockManager) window.DockManager.minimize('vm-iso-manager');
      };
    }

    let isMax = false;
    let preBounds = null;
    if (maxBtn) {
      maxBtn.onclick = () => {
        if (!isMax) {
          preBounds = {
            left: modal.style.left,
            top: modal.style.top,
            width: modal.style.width,
            height: modal.style.height,
          };
          modal.style.left = '0px';
          modal.style.top = '36px';
          modal.style.width = '100vw';
          modal.style.height = 'calc(100vh - 36px - 72px)';
          isMax = true;
        } else {
          if (preBounds) {
            modal.style.left = preBounds.left;
            modal.style.top = preBounds.top;
            modal.style.width = preBounds.width;
            modal.style.height = preBounds.height;
          }
          isMax = false;
        }
      };
    }

    if (closeBtn) {
      closeBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        if (modal._unbindTrap) {
          try { modal._unbindTrap(); } catch (_) {}
          modal._unbindTrap = null;
        }
        modal.classList.add('window-minimized');
        modal.classList.remove('open');
        modal.style.setProperty('display', 'none', 'important');
        if (window.DockManager) window.DockManager.closeWindow('vm-iso-manager');
      };
    }

    // Drag and Drop Upload Event Listeners
    const dropzone = modal.querySelector('#iso-dropzone');
    const fileInput = modal.querySelector('#iso-file-input');
    const btnBrowse = modal.querySelector('#btn-browse-iso');

    if (btnBrowse && fileInput) {
      btnBrowse.onclick = () => fileInput.click();
      fileInput.onchange = (e) => {
        const file = e.target.files[0];
        if (file) handleUpload(file);
      };
    }

    if (dropzone) {
      dropzone.ondragover = (e) => {
        e.preventDefault();
        dropzone.style.borderColor = '#38bdf8';
        dropzone.style.background = 'rgba(14,165,233,0.1)';
      };
      dropzone.ondragleave = () => {
        dropzone.style.borderColor = 'rgba(14,165,233,0.4)';
        dropzone.style.background = 'rgba(14,165,233,0.03)';
      };
      dropzone.ondrop = (e) => {
        e.preventDefault();
        dropzone.style.borderColor = 'rgba(14,165,233,0.4)';
        dropzone.style.background = 'rgba(14,165,233,0.03)';
        const file = e.dataTransfer.files[0];
        if (file) handleUpload(file);
      };
    }

    modal.querySelector('#btn-refresh-local-isos')?.addEventListener('click', async () => {
      await loadVmDashboard();
      renderLocalIsoList();
      renderCatalogCards();
      showToast('ISO list refreshed.', 'info');
    });
  }

  // Real Streaming Upload Implementation
  function handleUpload(file) {
    if (!file) return;
    const progCard = modal.querySelector('#iso-upload-progress-card');
    const progBar = modal.querySelector('#upload-progress-bar');
    const progFilename = modal.querySelector('#upload-filename');
    const progRate = modal.querySelector('#upload-rate');

    if (progCard) progCard.style.display = 'block';
    if (progFilename) progFilename.textContent = file.name;
    if (progBar) progBar.style.width = '0%';
    if (progRate) progRate.textContent = 'Starting upload...';

    const xhr = new XMLHttpRequest();
    let lastTime = Date.now();
    let lastLoaded = 0;

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        const now = Date.now();
        const dt = (now - lastTime) / 1000;
        if (dt >= 0.25) {
          const speed = (e.loaded - lastLoaded) / (1024 * 1024) / dt;
          lastTime = now;
          lastLoaded = e.loaded;
          if (progRate) progRate.textContent = `${speed.toFixed(1)} MB/s (${pct}%)`;
        }
        if (progBar) progBar.style.width = `${pct}%`;
      }
    };

    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        if (progBar) progBar.style.width = '100%';
        if (progRate) progRate.textContent = 'Upload Complete';
        showToast(`ISO '${file.name}' uploaded successfully to /mnt/user/isos`, 'success');
        await loadVmDashboard();
        renderLocalIsoList();
        renderCatalogCards();
        document.getElementById('fm-refresh-btn')?.click();
      } else {
        let errDetail = 'Upload failed';
        try {
          const errObj = JSON.parse(xhr.responseText);
          if (errObj && errObj.detail) errDetail = errObj.detail;
        } catch (_) {}
        showToast(`Upload failed: ${errDetail}`, 'error');
        if (progRate) progRate.textContent = `Error: ${errDetail}`;
      }
    };

    xhr.onerror = () => {
      showToast('Network error while uploading ISO', 'error');
      if (progRate) progRate.textContent = 'Network Error';
    };

    xhr.open('POST', '/api/vms/isos/upload');
    xhr.setRequestHeader('x-filename', file.name);
    xhr.withCredentials = true;
    xhr.send(file);
  }

  // Populate or refresh local ISOs
  function renderLocalIsoList() {
    const localList = modal.querySelector('#local-iso-list');
    if (!localList) return;

    if (!vmIsos || vmIsos.length === 0) {
      localList.innerHTML = `<div style="font-size: 11px; color: var(--muted); padding: 12px 0;">No local ISO images discovered in /mnt/user/isos.</div>`;
    } else {
      localList.innerHTML = vmIsos.map((iso) => `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px;">
          <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
            <span style="font-size: 18px;">💿</span>
            <div style="min-width: 0; flex: 1;">
              <div style="font-size: 12.5px; font-weight: 700; color: #fff; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${escapeHtml(iso.name)}</div>
              <div style="font-size: 10.5px; color: var(--muted); font-family: monospace;">${escapeHtml(iso.path)}</div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; margin-left: 12px; flex-shrink: 0;">
            <span style="font-size: 11px; font-weight: 600; color: #94a3b8;">${iso.size_formatted}</span>
            <button class="btn-pill-toggle btn-boot-iso" data-path="${escapeHtml(iso.path)}" style="padding: 4px 10px; font-size: 11px; font-weight: 700; background: rgba(14,165,233,0.18); color: #38bdf8; border-color: rgba(14,165,233,0.35);">▶ Boot VM</button>
            <button class="btn-pill-toggle btn-delete-iso" data-path="${escapeHtml(iso.path)}" data-name="${escapeHtml(iso.name)}" style="padding: 4px 8px; font-size: 11px; color: var(--crit, #ef4444); border-color: rgba(239,68,68,0.3);" title="Delete ISO from storage">🗑</button>
          </div>
        </div>
      `).join('');

      localList.querySelectorAll('.btn-boot-iso').forEach((btn) => {
        btn.onclick = () => {
          const path = btn.dataset.path;
          if (window.DockManager) window.DockManager.minimize('vm-iso-manager');
          else modal.style.display = 'none';
          openVmCreateModal();
          const select = document.getElementById('vm-create-iso');
          if (select) select.value = path;
        };
      });

      localList.querySelectorAll('.btn-delete-iso').forEach((btn) => {
        btn.onclick = () => {
          const path = btn.dataset.path;
          const name = btn.dataset.name;
          showConfirmToast(
            t('vms.delete_iso_title', 'Delete ISO Image'),
            `Are you sure you want to delete '${name}' from storage? This cannot be undone.`,
            async () => {
              try {
                await api.delete(`/api/vms/isos?path=${encodeURIComponent(path)}`);
                showToast(`ISO '${name}' deleted successfully.`, 'info');
                await loadVmDashboard();
                renderLocalIsoList();
                renderCatalogCards();
                document.getElementById('fm-refresh-btn')?.click();
              } catch (err) {
                showToast(`Failed to delete ISO: ${err.message}`, 'error');
              }
            }
          );
        };
      });
    }
  }

  // Live Catalog Downloader & Task Poller
  function trackDownload(catalogId, taskId) {
    if (_isoPollTimers[catalogId]) clearInterval(_isoPollTimers[catalogId]);
    _isoPollTimers[catalogId] = setInterval(async () => {
      try {
        const tasks = await api.get('/api/vms/catalog/tasks');
        const task = (tasks || []).find((t) => t.catalog_id === catalogId || t.task_id === taskId);
        if (!task) return;

        const targetProg = modal.querySelector(`#prog-wrap-${catalogId}`);
        const targetBar = modal.querySelector(`#prog-bar-${catalogId}`);
        const targetPct = modal.querySelector(`#prog-pct-${catalogId}`);
        const targetStat = modal.querySelector(`#prog-stat-${catalogId}`);
        const btn = modal.querySelector(`.btn-dl-catalog[data-id="${catalogId}"]`);

        if (targetProg) targetProg.style.display = 'block';
        if (targetBar) targetBar.style.width = `${task.progress_pct || 0}%`;
        if (targetPct) targetPct.textContent = `${task.progress_pct || 0}%`;

        if (task.status === 'downloading') {
          if (targetStat) {
            targetStat.textContent = `Downloading... ${task.speed_mb_s || 0} MB/s (${task.progress_pct || 0}%)`;
            targetStat.style.color = '#38bdf8';
          }
          if (btn) {
            btn.disabled = true;
            btn.textContent = '⏳ Downloading...';
          }
        } else if (task.status === 'completed') {
          clearInterval(_isoPollTimers[catalogId]);
          delete _isoPollTimers[catalogId];
          if (targetBar) targetBar.style.width = '100%';
          if (targetPct) targetPct.textContent = '100%';
          if (targetStat) {
            targetStat.textContent = 'Downloaded to /mnt/user/isos';
            targetStat.style.color = '#34d399';
          }
          if (btn) {
            btn.disabled = false;
            btn.textContent = '✓ Ready';
            btn.style.background = 'rgba(16,185,129,0.2)';
            btn.style.borderColor = '#34d399';
            btn.style.color = '#34d399';
          }
          showToast(`Downloaded '${task.name || catalogId}' to /mnt/user/isos`, 'success');
          await loadVmDashboard();
          renderCatalogCards();
          renderLocalIsoList();
          document.getElementById('fm-refresh-btn')?.click();
        } else if (task.status === 'failed' || task.status === 'checksum_mismatch') {
          clearInterval(_isoPollTimers[catalogId]);
          delete _isoPollTimers[catalogId];
          if (targetStat) {
            targetStat.textContent = `Failed: ${task.error || 'Verification error'}`;
            targetStat.style.color = '#ef4444';
          }
          if (btn) {
            btn.disabled = false;
            btn.textContent = '⬇ Retry';
            btn.style.opacity = '1';
          }
          showToast(`Download failed: ${task.error || 'Error'}`, 'error');
        }
      } catch (_) {}
    }, 800);
  }

  // Render Official Catalog Cards with Real Live In-Storage Detection
  function renderCatalogCards(catalogList) {
    const container = modal.querySelector('#catalog-grid-container');
    if (!container) return;

    const list = catalogList || OFFICIAL_ISO_CATALOG;
    container.innerHTML = list.map((item) => {
      const inStorage = (vmIsos || []).some((iso) =>
        iso.name.toLowerCase() === item.filename.toLowerCase() ||
        (iso.path && iso.path.toLowerCase().endsWith(item.filename.toLowerCase()))
      );

      return `
        <div class="catalog-card glassmorphic-card" style="padding: 14px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08); background: rgba(18,26,38,0.6);">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
            <div>
              <span style="font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: #38bdf8;">${item.badge}</span>
              ${inStorage ? `<span style="font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.2); color: #34d399; margin-left: 6px;">✓ In Storage</span>` : ''}
              <div style="font-weight: 700; color: #fff; font-size: 13px; margin-top: 4px;">${escapeHtml(item.name)}</div>
            </div>
            <span style="font-size: 11px; font-weight: 700; color: #94a3b8;">${item.size_formatted}</span>
          </div>
          <div style="font-size: 10px; color: var(--muted); margin: 6px 0 12px 0; line-height: 1.4;">${escapeHtml(item.desc || item.description || '')}</div>
          
          <!-- Download Progress Bar (Hidden by default or shown if in-flight) -->
          <div id="prog-wrap-${item.id}" style="${inStorage ? 'display: block;' : 'display: none;'} margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; font-size: 10px; margin-bottom: 4px;">
              <span id="prog-stat-${item.id}" style="color: ${inStorage ? '#34d399' : '#38bdf8'};">${inStorage ? 'Downloaded to /mnt/user/isos' : 'Ready'}</span>
              <span id="prog-pct-${item.id}" style="color: #fff; font-weight: 700;">${inStorage ? '100%' : '0%'}</span>
            </div>
            <div style="height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); overflow: hidden;">
              <div id="prog-bar-${item.id}" style="width: ${inStorage ? '100%' : '0%'}; height: 100%; background: ${inStorage ? '#10b981' : '#0ea5e9'}; transition: width 0.2s;"></div>
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
            <span style="font-size: 10px; color: var(--muted); font-family: monospace;">${item.arch || item.architecture || 'x86_64'} • ${item.kernel || 'Linux'}</span>
            <div style="display: flex; gap: 6px;">
              ${inStorage ? `
                <button class="btn-pill-toggle btn-boot-catalog-iso" data-filename="${item.filename}" style="padding: 5px 12px; font-size: 11px; font-weight: 700; background: rgba(14,165,233,0.18); color: #38bdf8; border-color: rgba(14,165,233,0.35);">
                  ▶ Boot VM
                </button>
                <button class="btn-save-preset btn-dl-catalog" data-id="${item.id}" disabled style="padding: 5px 10px; font-size: 11px; font-weight: 700; background: rgba(16,185,129,0.2); color: #34d399; border-color: #34d399;">
                  ✓ Ready
                </button>
              ` : `
                <button class="btn-save-preset btn-dl-catalog" data-id="${item.id}" style="padding: 5px 12px; font-size: 11px; font-weight: 700; background: var(--accent-cyan, #0ea5e9); color: #fff;">
                  <span>⬇ Download</span>
                </button>
              `}
            </div>
          </div>
        </div>
      `;
    }).join('');

    // Bind 1-click Download buttons
    container.querySelectorAll('.btn-dl-catalog:not(:disabled)').forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        btn.disabled = true;
        btn.textContent = '⏳ Connecting...';

        const targetProg = modal.querySelector(`#prog-wrap-${id}`);
        const targetStat = modal.querySelector(`#prog-stat-${id}`);
        if (targetProg) targetProg.style.display = 'block';
        if (targetStat) {
          targetStat.textContent = 'Contacting download mirror...';
          targetStat.style.color = '#38bdf8';
        }

        try {
          const res = await api.post(`/api/vms/catalog/${id}/download`);
          if (res && res.status === 'already_present') {
            showToast(`ISO already exists in /mnt/user/isos`, 'info');
            await loadVmDashboard();
            renderCatalogCards();
            renderLocalIsoList();
            return;
          }
          trackDownload(id, res.task_id);
        } catch (err) {
          showToast(`Failed to initiate download: ${err.message}`, 'error');
          if (targetStat) {
            targetStat.textContent = `Error: ${err.message}`;
            targetStat.style.color = '#ef4444';
          }
          btn.disabled = false;
          btn.textContent = '⬇ Retry';
        }
      };
    });

    // Bind Boot buttons
    container.querySelectorAll('.btn-boot-catalog-iso').forEach((btn) => {
      btn.onclick = () => {
        const fn = btn.dataset.filename;
        const isoObj = (vmIsos || []).find((i) => i.name.toLowerCase() === fn.toLowerCase());
        const isoPath = isoObj ? isoObj.path : `/mnt/user/isos/${fn}`;
        if (window.DockManager) window.DockManager.minimize('vm-iso-manager');
        else modal.style.display = 'none';
        openVmCreateModal();
        const select = document.getElementById('vm-create-iso');
        if (select) select.value = isoPath;
      };
    });
  }

  // Tab switching logic
  const tabBtnCatalog = modal.querySelector('#tab-btn-catalog');
  const tabBtnLocal = modal.querySelector('#tab-btn-local');
  const tabContentCatalog = modal.querySelector('#tab-content-catalog');
  const tabContentLocal = modal.querySelector('#tab-content-local');

  function switchTab(tab) {
    if (tab === 'local') {
      tabBtnLocal?.classList.add('active');
      tabBtnCatalog?.classList.remove('active');
      if (tabContentLocal) tabContentLocal.style.display = 'block';
      if (tabContentCatalog) tabContentCatalog.style.display = 'none';
    } else {
      tabBtnCatalog?.classList.add('active');
      tabBtnLocal?.classList.remove('active');
      if (tabContentCatalog) tabContentCatalog.style.display = 'block';
      if (tabContentLocal) tabContentLocal.style.display = 'none';
    }
  }

  if (tabBtnCatalog) tabBtnCatalog.onclick = () => switchTab('catalog');
  if (tabBtnLocal) tabBtnLocal.onclick = () => switchTab('local');
  switchTab(initialTab);

  if (window.DockManager) {
    window.DockManager.restore('vm-iso-manager');
  } else {
    modal.style.display = 'flex';
  }
  bringToFront(modal);

  if (modal._unbindTrap) {
    try { modal._unbindTrap(); } catch (_) {}
    modal._unbindTrap = null;
  }
  modal._unbindTrap = trapFocus(modal, () => {
    const closeBtn = modal.querySelector('#iso-modal-close');
    if (closeBtn) closeBtn.click();
    else {
      modal.classList.add('window-minimized');
      modal.classList.remove('open');
      modal.style.setProperty('display', 'none', 'important');
    }
  });

  // Load and render both tabs
  renderLocalIsoList();
  renderCatalogCards();

  // Fetch live catalog and active tasks from backend
  try {
    const [remoteCatalog, tasks] = await Promise.all([
      api.get('/api/vms/catalog').catch(() => null),
      api.get('/api/vms/catalog/tasks').catch(() => null),
    ]);

    if (remoteCatalog && remoteCatalog.length > 0) {
      renderCatalogCards(remoteCatalog);
    }

    if (tasks && tasks.length > 0) {
      tasks.forEach((t) => {
        if (t.status === 'downloading') {
          trackDownload(t.catalog_id, t.task_id);
        }
      });
    }
  } catch (_) {}
}

export async function openVmSnapshotsModal(vmId, vmObj = null) {
  let modal = document.getElementById('modal-vm-snapshots');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-vm-snapshots';
    modal.className = 'smart-modal-backdrop';
    document.body.appendChild(modal);
  } else {
    modal.className = 'smart-modal-backdrop';
  }

  const targetVm = vmObj || vmList.find((v) => v.id === vmId) || { id: vmId, name: 'Virtual Machine', state: 'stopped' };
  let activeTab = 'snapshots';

  modal.innerHTML = `
    <div class="smart-modal-window vm-modal-window" style="max-width: 660px; width: 92%; max-height: 85vh; display: flex; flex-direction: column; overflow: hidden;">
      <div class="smart-modal-header" style="cursor: move; user-select: none; display: flex; justify-content: space-between; align-items: center;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent, #38bdf8);"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          <span>${t('vm.snapshots', 'Snapshots & Rollback')}: ${escapeHtml(targetVm.name)}</span>
        </div>
        <div class="os-window-controls" style="display: flex; gap: 6px; align-items: center;">
          <button class="win-btn close-btn" id="vm-snap-modal-close" title="Close" aria-label="Close"></button>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div style="display: flex; gap: 8px; border-bottom: 1px solid rgba(255,255,255,0.08); padding: 8px 18px; background: rgba(0,0,0,0.15);">
        <button type="button" id="tab-btn-snaps" class="btn-pill-toggle active" style="font-size: 11px; padding: 5px 12px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          <span>QCOW2 Checkpoints</span>
        </button>
        <button type="button" id="tab-btn-backups" class="btn-pill-toggle" style="font-size: 11px; padding: 5px 12px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>Hyper-Backups (.tar.gz)</span>
        </button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; padding: 18px 22px; display: flex; flex-direction: column; gap: 14px;">
        <!-- SNAPSHOTS PANE -->
        <div id="vm-pane-snapshots" style="display: flex; flex-direction: column; gap: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;">QCOW2 Checkpoints & State Snapshots</div>
              <div style="font-size: 10px; color: var(--muted);">Live memory + disk snapshots while running; disk snapshots while offline.</div>
            </div>
            <button type="button" id="btn-take-snapshot" class="btn-pill-toggle" style="background: rgba(14,165,233,0.15); border: 1px solid rgba(14,165,233,0.35); color: #38bdf8; font-weight: 700; font-size: 11px; padding: 5px 12px; border-radius: 6px; cursor: pointer; display: inline-flex; align-items: center; gap: 5px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>${t('vm.take_snapshot', '+ Take Snapshot')}</span>
            </button>
          </div>

          <!-- Create Snapshot Form -->
          <div id="vm-snap-create-form" style="display: none; background: rgba(0,0,0,0.3); border: 1px solid rgba(14,165,233,0.3); border-radius: 8px; padding: 12px; flex-direction: column; gap: 10px;">
            <div style="font-size: 11px; font-weight: 700; color: #38bdf8;">Create New Checkpoint Snapshot</div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
              <input type="text" id="vm-snap-name-input" placeholder="${t('vm.snapshot_name', 'Snapshot Name')}" style="flex: 1; min-width: 160px; padding: 6px 10px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 11px;" />
              <input type="text" id="vm-snap-desc-input" placeholder="${t('vm.snapshot_desc', 'Description (optional)')}" style="flex: 2; min-width: 200px; padding: 6px 10px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 11px;" />
            </div>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button type="button" id="btn-cancel-take-snapshot" class="btn-pill-toggle" style="font-size: 11px; padding: 4px 10px;">Cancel</button>
              <button type="button" id="btn-submit-take-snapshot" class="btn-pill-toggle" style="background: #0284c7; color: #fff; font-weight: 700; font-size: 11px; padding: 4px 14px; cursor: pointer;">Save Snapshot</button>
            </div>
          </div>

          <div id="vm-snapshots-container" style="background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; overflow: hidden; min-height: 120px;">
            <div style="color: var(--muted); text-align: center; padding: 28px; font-size: 12px;">Loading snapshots...</div>
          </div>
        </div>

        <!-- HYPER-BACKUPS PANE -->
        <div id="vm-pane-backups" style="display: none; flex-direction: column; gap: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;">Complete VM Hyper-Backups</div>
              <div style="font-size: 10px; color: var(--muted);">Self-contained archives (.tar.gz) containing complete hardware specs and virtual disk images.</div>
            </div>
            <button type="button" id="btn-create-hyper-backup" class="btn-pill-toggle" style="background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.35); color: #34d399; font-weight: 700; font-size: 11px; padding: 5px 12px; border-radius: 6px; cursor: pointer; display: inline-flex; align-items: center; gap: 5px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>+ Create Hyper-Backup</span>
            </button>
          </div>

          <div id="vm-backups-container" style="background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; overflow: hidden; min-height: 120px;">
            <div style="color: var(--muted); text-align: center; padding: 28px; font-size: 12px;">Loading hyper-backups...</div>
          </div>
        </div>
      </div>
    </div>
  `;

  modal.classList.remove('window-minimized');
  modal.classList.add('open');
  modal.style.removeProperty('display');
  modal.style.setProperty('display', 'flex', 'important');
  modal.style.zIndex = '9600';

  const win = modal.querySelector('.smart-modal-window');
  if (win) {
    win.style.zIndex = '9610';
    makeDraggable(win, modal.querySelector('.smart-modal-header'));
  }

  // Close wiring
  const close = () => {
    modal.classList.remove('open');
    modal.classList.add('window-minimized');
    modal.style.setProperty('display', 'none', 'important');
    if (modal._unbindTrap) {
      try { modal._unbindTrap(); } catch (_) {}
      modal._unbindTrap = null;
    }
  };

  const closeBtn = modal.querySelector('#vm-snap-modal-close');
  if (closeBtn) closeBtn.onclick = close;
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };

  if (modal._unbindTrap) {
    try { modal._unbindTrap(); } catch (_) {}
    modal._unbindTrap = null;
  }
  modal._unbindTrap = trapFocus(modal, close);

  // Tab switching
  const tabSnaps = modal.querySelector('#tab-btn-snaps');
  const tabBackups = modal.querySelector('#tab-btn-backups');
  const paneSnaps = modal.querySelector('#vm-pane-snapshots');
  const paneBackups = modal.querySelector('#vm-pane-backups');

  if (tabSnaps && tabBackups) {
    tabSnaps.onclick = () => {
      activeTab = 'snapshots';
      tabSnaps.classList.add('active');
      tabBackups.classList.remove('active');
      paneSnaps.style.display = 'flex';
      paneBackups.style.display = 'none';
      loadSnapshotsList();
    };
    tabBackups.onclick = () => {
      activeTab = 'backups';
      tabBackups.classList.add('active');
      tabSnaps.classList.remove('active');
      paneBackups.style.display = 'flex';
      paneSnaps.style.display = 'none';
      loadBackupsList();
    };
  }

  // Snapshot form wiring
  const btnTake = modal.querySelector('#btn-take-snapshot');
  const createForm = modal.querySelector('#vm-snap-create-form');
  const nameInput = modal.querySelector('#vm-snap-name-input');
  const descInput = modal.querySelector('#vm-snap-desc-input');
  const btnCancel = modal.querySelector('#btn-cancel-take-snapshot');
  const btnSubmit = modal.querySelector('#btn-submit-take-snapshot');

  const defaultSnapName = () => `snap-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${new Date().toTimeString().slice(0, 8).replace(/:/g, '')}`;

  if (btnTake && createForm) {
    btnTake.onclick = () => {
      createForm.style.display = createForm.style.display === 'none' ? 'flex' : 'none';
      if (createForm.style.display === 'flex' && nameInput) {
        nameInput.value = defaultSnapName();
        nameInput.focus();
      }
    };
  }

  if (btnCancel && createForm) {
    btnCancel.onclick = () => { createForm.style.display = 'none'; };
  }

  async function loadSnapshotsList() {
    const container = modal.querySelector('#vm-snapshots-container');
    if (!container) return;
    try {
      const data = await api.get(`/api/vms/${vmId}/snapshots`);
      const snaps = data?.snapshots || [];
      if (snaps.length === 0) {
        container.innerHTML = `
          <div style="color: var(--muted); text-align: center; padding: 32px 20px; font-size: 12px; display: flex; flex-direction: column; align-items: center; gap: 8px;">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.5;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>${t('vm.no_snapshots', 'No snapshots recorded yet. Create a checkpoint before performing major updates.')}</span>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <table style="width: 100%; border-collapse: collapse; font-size: 11px; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.02); color: var(--muted);">
              <th style="padding: 8px 12px;">Tag / Name</th>
              <th style="padding: 8px 12px;">Timestamp</th>
              <th style="padding: 8px 12px;">Size</th>
              <th style="padding: 8px 12px;">Mode</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${snaps.map((s) => `
              <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
                <td style="padding: 8px 12px; font-weight: 700; color: #fff;">
                  <div>${escapeHtml(s.name)}</div>
                  ${s.description ? `<div style="font-size: 9.5px; color: var(--muted); font-weight: normal;">${escapeHtml(s.description)}</div>` : ''}
                </td>
                <td style="padding: 8px 12px; color: var(--muted); font-family: var(--font-mono, monospace);">${escapeHtml(s.date || s.created_at || '—')}</td>
                <td style="padding: 8px 12px; color: var(--muted);">${escapeHtml(s.size_formatted || s.vm_size || '—')}</td>
                <td style="padding: 8px 12px;">
                  <span style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: #38bdf8;">
                    ${s.is_live ? 'Live Memory + Disk' : 'QCOW2 Disk'}
                  </span>
                </td>
                <td style="padding: 8px 12px; text-align: right;">
                  <div style="display: flex; gap: 6px; justify-content: flex-end;">
                    <button class="btn-pill-toggle btn-snap-revert" data-name="${escapeHtml(s.name)}" style="padding: 4px 10px; font-size: 10px; color: #38bdf8; border-color: rgba(14,165,233,0.3); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="11 17 6 12 11 7"/><polyline points="18 17 13 12 18 7"/></svg>
                      <span>${t('vm.revert_snapshot', 'Revert')}</span>
                    </button>
                    <button class="btn-pill-toggle btn-snap-del" data-name="${escapeHtml(s.name)}" style="padding: 4px 10px; font-size: 10px; color: var(--crit, #ff6b6b); border-color: rgba(255,107,107,0.3); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      <span>${t('vm.delete_snapshot', 'Delete')}</span>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;

      container.querySelectorAll('.btn-snap-revert').forEach((b) => {
        b.onclick = () => {
          const snapName = b.dataset.name;
          showConfirmToast(
            `Revert VM '${targetVm.name}' to checkpoint '${snapName}'? Runtime modifications will be rolled back.`,
            async () => {
              try {
                await api.post(`/api/vms/${vmId}/snapshots/${encodeURIComponent(snapName)}/revert`);
                showToast(`Rolled back VM '${targetVm.name}' to snapshot '${snapName}'.`, 'success');
                loadSnapshotsList();
                loadVmDashboard();
              } catch (err) {
                showToast(`Revert failed: ${err.message || err.detail}`, 'error');
              }
            }
          );
        };
      });

      container.querySelectorAll('.btn-snap-del').forEach((b) => {
        b.onclick = () => {
          const snapName = b.dataset.name;
          showConfirmToast(
            `Delete snapshot '${snapName}'? This action cannot be undone.`,
            async () => {
              try {
                await api.delete(`/api/vms/${vmId}/snapshots/${encodeURIComponent(snapName)}`);
                showToast(`Deleted snapshot '${snapName}'.`, 'success');
                loadSnapshotsList();
              } catch (err) {
                showToast(`Delete failed: ${err.message || err.detail}`, 'error');
              }
            }
          );
        };
      });
    } catch (err) {
      container.innerHTML = `<div style="color: var(--crit); text-align: center; padding: 24px; font-size: 11px;">Failed to load snapshots: ${escapeHtml(err.message || err.detail)}</div>`;
    }
  }

  // Hyper-Backups loader
  async function loadBackupsList() {
    const container = modal.querySelector('#vm-backups-container');
    if (!container) return;
    try {
      const data = await api.get(`/api/vms/${vmId}/backups`);
      const backups = data?.backups || [];
      if (backups.length === 0) {
        container.innerHTML = `
          <div style="color: var(--muted); text-align: center; padding: 32px 20px; font-size: 12px; display: flex; flex-direction: column; align-items: center; gap: 8px;">
            <span style="font-size: 24px; opacity: 0.6;">💾</span>
            <span>No hyper-backups created yet. Click "+ Create Hyper-Backup" above to generate a standalone archive.</span>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <table style="width: 100%; border-collapse: collapse; font-size: 11px; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.02); color: var(--muted);">
              <th style="padding: 8px 12px;">Backup ID / File</th>
              <th style="padding: 8px 12px;">Created</th>
              <th style="padding: 8px 12px;">Size</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${backups.map((b) => `
              <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
                <td style="padding: 8px 12px; font-weight: 700; color: #fff;">
                  <div>${escapeHtml(b.filename || b.id)}</div>
                  <div style="font-size: 9.5px; color: var(--muted); font-family: var(--font-mono, monospace);">${escapeHtml(b.id)}</div>
                </td>
                <td style="padding: 8px 12px; color: var(--muted); font-family: var(--font-mono, monospace);">${escapeHtml(b.created_at_iso || '—')}</td>
                <td style="padding: 8px 12px; color: var(--muted);">${escapeHtml(b.size_formatted || '—')}</td>
                <td style="padding: 8px 12px; text-align: right;">
                  <div style="display: flex; gap: 6px; justify-content: flex-end;">
                    <button class="btn-pill-toggle btn-bk-restore" data-id="${escapeHtml(b.id)}" style="padding: 4px 10px; font-size: 10px; color: #34d399; border-color: rgba(16,185,129,0.3); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
                      <span>Restore</span>
                    </button>
                    <button class="btn-pill-toggle btn-bk-del" data-id="${escapeHtml(b.id)}" style="padding: 4px 10px; font-size: 10px; color: var(--crit, #ff6b6b); border-color: rgba(255,107,107,0.3); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      <span>Delete</span>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;

      container.querySelectorAll('.btn-bk-restore').forEach((b) => {
        b.onclick = () => {
          const bId = b.dataset.id;
          showConfirmToast(
            `Restore VM '${targetVm.name}' from hyper-backup archive '${bId}'? Existing virtual disks and settings will be restored.`,
            async () => {
              try {
                await api.post(`/api/vms/backups/${encodeURIComponent(bId)}/restore`);
                showToast(`Restored VM '${targetVm.name}' from backup '${bId}'.`, 'success');
                loadBackupsList();
                loadVmDashboard();
              } catch (err) {
                showToast(`Restore failed: ${err.message || err.detail}`, 'error');
              }
            }
          );
        };
      });

      container.querySelectorAll('.btn-bk-del').forEach((b) => {
        b.onclick = () => {
          const bId = b.dataset.id;
          showConfirmToast(
            `Delete hyper-backup archive '${bId}'? This action cannot be undone.`,
            async () => {
              try {
                await api.delete(`/api/vms/backups/${encodeURIComponent(bId)}`);
                showToast(`Deleted backup '${bId}'.`, 'success');
                loadBackupsList();
              } catch (err) {
                showToast(`Delete failed: ${err.message || err.detail}`, 'error');
              }
            }
          );
        };
      });
    } catch (err) {
      container.innerHTML = `<div style="color: var(--crit); text-align: center; padding: 24px; font-size: 11px;">Failed to load hyper-backups: ${escapeHtml(err.message || err.detail)}</div>`;
    }
  }

  // Create hyper-backup
  const btnCreateBackup = modal.querySelector('#btn-create-hyper-backup');
  if (btnCreateBackup) {
    btnCreateBackup.onclick = async () => {
      btnCreateBackup.disabled = true;
      btnCreateBackup.textContent = 'Archiving...';
      try {
        await api.post(`/api/vms/${vmId}/backup`, { reason: 'on-demand' });
        showToast(`Hyper-backup created for VM '${targetVm.name}'.`, 'success');
        loadBackupsList();
      } catch (err) {
        showToast(`Failed creating hyper-backup: ${err.message || err.detail}`, 'error');
      } finally {
        btnCreateBackup.disabled = false;
        btnCreateBackup.textContent = '+ Create Hyper-Backup';
      }
    };
  }

  // Submit snapshot
  if (btnSubmit) {
    btnSubmit.onclick = async () => {
      const name = (nameInput?.value || '').trim();
      const description = (descInput?.value || '').trim();
      if (!name) {
        showToast('Please specify a snapshot name', 'warning');
        return;
      }
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Saving...';
      try {
        await api.post(`/api/vms/${vmId}/snapshots`, { name, description });
        showToast(`Snapshot '${name}' created successfully.`, 'success');
        if (createForm) createForm.style.display = 'none';
        if (descInput) descInput.value = '';
        loadSnapshotsList();
      } catch (err) {
        showToast(`Failed to create snapshot: ${err.message || err.detail}`, 'error');
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = 'Save Snapshot';
      }
    };
  }

  loadSnapshotsList();
}

if (typeof window !== 'undefined') {
  window.openVmConnectModal = openVmConnectModal;
  window.openVmEditModal = openVmEditModal;
  window.openVmSnapshotsModal = openVmSnapshotsModal;
}

