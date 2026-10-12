/**
 * ZettNAS Toolkit - Virtual Machines (VM) Desktop Application & Manager
 * Features dynamic elastic headroom budgeting, vCPU overcommit soft warnings,
 * KVM hypervisor telemetry, and VM creation wizard.
 */

import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast, showConfirmToast } from '../toast.js';
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
        <div id="vm-telemetry-header" class="vm-telemetry-header" style="padding: 16px; background: rgba(0,0,0,0.25); border-bottom: 1px solid rgba(255,255,255,0.06);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
            <div id="vm-kvm-badge" style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">
              <span>⚡</span> <span>Loading KVM Status...</span>
            </div>
            <div style="display: flex; gap: 8px;">
              <button id="btn-vm-refresh" class="btn-pill-toggle" title="${t('vm.refresh', 'Refresh')}" style="display: inline-flex; align-items: center; gap: 6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <span data-i18n="vm.refresh">${t('vm.refresh', 'Refresh')}</span>
              </button>
              <button id="btn-vm-create" class="btn-save-preset" style="background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff; font-weight: 700;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span data-i18n="vm.create_btn">${escapeHtml(t('vm.create_btn', 'Create Virtual Machine'))}</span>
              </button>
            </div>
          </div>

          <div style="display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px;">
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
        <div class="vm-content-body" style="flex: 1; overflow-y: auto; padding: 16px;">
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
    minBtn.onclick = () => {
      if (window.DockManager) window.DockManager.minimize('vm');
    };
  }
  if (closeBtn) {
    closeBtn.onclick = () => {
      if (window.DockManager) window.DockManager.close('vm');
      else if (vmWindow) vmWindow.style.display = 'none';
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

function renderTelemetry(tel) {
  if (!tel) return;

  // KVM Badge
  const kvmBadge = document.getElementById('vm-kvm-badge');
  if (kvmBadge && tel.kvm) {
    kvmBadge.innerHTML = `<span>⚡</span> <span>${escapeHtml(tel.kvm.badge || 'KVM Active')}</span>`;
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

  grid.innerHTML = vms
    .map((vm) => {
      const isRunning = vm.state === 'running';
      const isPaused = vm.state === 'paused';
      const statusColor = isRunning ? '#34d399' : isPaused ? '#fbbf24' : '#94a3b8';
      const statusBg = isRunning
        ? 'rgba(16,185,129,0.15)'
        : isPaused
        ? 'rgba(245,158,11,0.15)'
        : 'rgba(255,255,255,0.06)';

      const stateBadge = `<span style="padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; background: ${statusBg}; color: ${statusColor}; text-transform: uppercase;">${vm.state}</span>`;

      const osIcon =
        vm.os_family === 'windows'
          ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="#38bdf8" style="flex-shrink: 0;"><path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.949-1.801"/></svg>`
          : vm.os_family === 'linux'
          ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="#fbbf24" style="flex-shrink: 0;"><path d="M12 2a5 5 0 0 0-5 5v3.1c-1.3.8-2 2-2 3.9 0 2.2 1.3 4 3 4.8V20a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-1.2c1.7-.8 3-2.6 3-4.8 0-1.9-.7-3.1-2-3.9V7a5 5 0 0 0-5-5zm-2 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm4 0a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/></svg>`
          : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" style="flex-shrink: 0;"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`;

      return `
      <div class="glassmorphic-card" style="border-radius: 10px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid rgba(255,255,255,0.08); background: rgba(18, 26, 38, 0.65);">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              ${osIcon}
              <div>
                <div style="font-weight: 700; color: #fff; font-size: 13px;">${escapeHtml(vm.name)}</div>
                <div style="font-size: 10px; color: var(--muted);">${escapeHtml(vm.description || 'Virtual Appliance')}</div>
              </div>
            </div>
            ${stateBadge}
          </div>

          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; font-size: 11px; margin: 12px 0; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
            <div><span style="color: var(--muted);">${t('vm.compute', 'Compute')}:</span> <strong style="color: #fff;">${vm.vcpus} vCPUs</strong></div>
            <div><span style="color: var(--muted);">${t('vm.memory', 'Memory')}:</span> <strong style="color: #38bdf8;">${vm.ram_gb} GB</strong></div>
            <div><span style="color: var(--muted);">${t('vm.disk', 'Disk')}:</span> <strong style="color: #fff;">${vm.disk_size_gb} GB (${vm.disk_format})</strong></div>
            <div><span style="color: var(--muted);">${t('vm.bridge', 'Bridge')}:</span> <strong style="color: #fff;">${escapeHtml(vm.bridge || 'br0')}</strong></div>
          </div>

          ${
            vm.ip_address
              ? `
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 4px 8px; background: rgba(14,165,233,0.1); border: 1px solid rgba(14,165,233,0.25); border-radius: 4px; margin-bottom: 10px;">
              <span style="color: #38bdf8; font-family: monospace; display: flex; align-items: center; gap: 5px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                ${escapeHtml(vm.ip_address)}
              </span>
              <button class="btn-copy-ip" data-ip="${escapeHtml(vm.ip_address)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 2px 4px; display: flex; align-items: center;" title="Copy IP">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              </button>
            </div>
          `
              : ''
          }
        </div>

        <div style="display: flex; gap: 6px; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 10px; flex-wrap: wrap;">
          ${
            !isRunning && !isPaused
              ? `
            <button class="btn-vm-action btn-vm-start" data-id="${vm.id}" data-act="start" style="flex: 1;" title="${t('vm.start', 'Start')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('vm.start', 'Start')}</span>
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
            <button class="btn-vm-action btn-vm-stop" data-id="${vm.id}" data-act="stop" style="flex: 1;" title="${t('vm.stop', 'Stop')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>${t('vm.stop', 'Stop')}</span>
            </button>
            <button class="btn-vm-console" data-id="${vm.id}" title="${t('vm.console', 'Console')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              <span>${t('vm.console', 'Console')}</span>
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
            <button class="btn-vm-action btn-vm-stop" data-id="${vm.id}" data-act="stop" style="flex: 1;" title="${t('vm.stop', 'Stop')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>${t('vm.stop', 'Stop')}</span>
            </button>
          `
              : ''
          }
          ${
            !isRunning && !isPaused
              ? `
            <button class="btn-vm-delete" data-id="${vm.id}" data-name="${escapeHtml(vm.name)}" title="${t('vm.delete', 'Delete')}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
              <span>${t('vm.delete', 'Delete')}</span>
            </button>
          `
              : ''
          }
        </div>
      </div>
    `;
    })
    .join('');

  // Attach Action Handlers
  grid.querySelectorAll('.btn-vm-action').forEach((btn) => {
    btn.onclick = async () => {
      const vmId = btn.dataset.id;
      const action = btn.dataset.act;
      try {
        await api.post(`/api/vms/${vmId}/action`, { action });
        showToast(`VM action '${action}' completed`, 'success');
        loadVmDashboard();
      } catch (err) {
        showToast(`Action failed: ${err.message}`, 'error');
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
    btn.onclick = () => {
      navigator.clipboard.writeText(btn.dataset.ip);
      showToast(`Copied ${btn.dataset.ip} to clipboard`, 'info');
    };
  });

  grid.querySelectorAll('.btn-vm-console').forEach((btn) => {
    btn.onclick = () => {
      showToast('Connecting to VM noVNC Web Console...', 'info');
    };
  });
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
    <div class="smart-modal-window vm-modal-window" style="max-width: 580px; width: 92%; max-height: 88vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span data-i18n="vm.create_btn">${escapeHtml(t('vm.create_btn', 'Create Virtual Machine'))}</span>
        </div>
        <button id="vm-modal-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 4px;" title="Close" aria-label="Close">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; padding: 18px 22px;">
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
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Boot ISO / Installation Image</label>
            <select id="vm-create-iso" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
              <option value="">None (Network PXE / Empty Disk)</option>
              ${vmIsos.map((iso) => `<option value="${escapeHtml(iso.path)}">${escapeHtml(iso.name)} (${iso.size_formatted})</option>`).join('')}
            </select>
          </div>
          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Virtual Disk Size (GB)</label>
            <input type="number" id="vm-create-disk" min="10" max="2000" value="32" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
          </div>
        </div>

        <!-- Step 4: Network Bridge -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Network Bridge</label>
          <select id="vm-create-bridge" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
            ${vmBridges.map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)} (Host Bridge)</option>`).join('')}
          </select>
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
  }

  let onKeyDown = null;
  const closeModal = () => {
    modal.classList.remove('open');
    modal.style.display = 'none';
    if (onKeyDown) {
      document.removeEventListener('keydown', onKeyDown);
      onKeyDown = null;
    }
  };

  onKeyDown = (e) => {
    if (e.key === 'Escape' && modal.classList.contains('open')) {
      closeModal();
    }
  };
  document.addEventListener('keydown', onKeyDown);

  modal.onclick = (e) => {
    if (e.target === modal) closeModal();
  };

  const closeBtn = modal.querySelector('#vm-modal-close');
  if (closeBtn) closeBtn.onclick = closeModal;

  const cancelBtn = modal.querySelector('#vm-create-cancel');
  if (cancelBtn) cancelBtn.onclick = closeModal;

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

  // Submit Handler
  const btnSubmit = modal.querySelector('#vm-create-submit');
  if (btnSubmit) {
    btnSubmit.onclick = async () => {
      const name = modal.querySelector('#vm-create-name')?.value?.trim();
      if (!name) {
        showToast('Please enter a valid VM name.', 'warning');
        return;
      }

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
          bridge: modal.querySelector('#vm-create-bridge')?.value || 'br0',
          autostart: !!modal.querySelector('#vm-create-autostart')?.checked,
          override_limits: !!overrideToggle?.checked,
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

  modal.style.display = 'flex';
  modal.classList.add('open');
}
