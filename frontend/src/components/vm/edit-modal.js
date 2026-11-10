// The VM settings dialog and the QEMU error dialog.
// Part of vm-manager.js, split out by ARC-5.

import { api } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';

// An icon next to translated words: screen readers skip it (UX-35)
const ico = (e) => `<span aria-hidden="true">${e}</span>`;
import { makeDraggable, bringToFront } from '../dock.js';
import { vmState } from './state.js';
import { openKvmDiagnosticsModal } from './connect-modal.js';
import { vtpmBadgeHtml } from './shared.js';
import { openVmSnapshotsModal } from './snapshots.js';
import { loadVmDashboard } from '../vm-manager.js';
import { formatFixed } from '../../format.js';

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
    <div class="smart-modal-window vm-modal-window vme-size">
      <div class="smart-modal-header" style="background: rgba(239, 68, 68, 0.15); border-bottom: 1px solid rgba(239, 68, 68, 0.3);">
        <div class="smart-modal-title vme-row-crit">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <span>${t('vmd.fail_title', 'The virtual machine could not start')}</span>
        </div>
        <button id="qemu-error-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px;">✕</button>
      </div>
      <div class="smart-modal-body vme-col">
        <div class="vme-fs13-strong">
          ${t('vmd.fail_msg', '{name} could not start. The hypervisor reported this error:', { name: `<strong>${escapeHtml(vmName)}</strong>` })}
        </div>
        <div class="qemu-error-box" style="background: var(--lt-b-00000080, rgba(0,0,0,0.5)); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; padding: 12px; font-family: monospace; font-size: var(--zn-fs-xs); color: var(--lt-t-fca5a5ff, #fca5a5); line-height: 1.5; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto;">${escapeHtml(errorMsg || t('vmd.fail_exit', 'The process stopped early with an error code.'))}</div>
        <div class="vme-xs-muted">
          <strong>${t('vmd.try_this', 'What to try:')}</strong>
          <ul class="vme-x">
            <li>${t('vmd.try_kvm', 'Check that KVM acceleration ({path}) is available.', { path: '<code>/dev/kvm</code>' })}</li>
            <li>${t('vmd.try_paths', 'Check that the boot ISO and the virtual disk exist and are not in use.')}</li>
            <li>${t('vmd.try_ram', 'Check that the server has enough free memory.')}</li>
          </ul>
        </div>
      </div>
      <div class="smart-modal-footer vme-row-box">
        <button id="btn-qemu-error-diag" class="btn-console-act" style="background: rgba(51, 205, 184, 0.2); border-color: #4fd8c4; color: var(--zn-text-accent);">
          ${ico('🛠️')} ${t('vmd.run_diag', 'Run KVM checks')}
        </button>
        ${vmId ? `
          <button id="btn-qemu-error-edit" class="btn-console-act vme-strong-box">
            ${ico('⚙️')} ${t('vmd.edit_settings', 'Edit VM settings')}
          </button>
        ` : ''}
        <button id="btn-qemu-error-dismiss" class="btn-console-act vme-soft-box">
          ${t('vmd.dismiss', 'Dismiss')}
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

  let targetVm = vmObj || vmState.list.find((v) => v.id === vmId);

  const renderModal = (targetVm) => {
    const isRunning = targetVm.state === 'running';
    const budget = vmState.telemetry?.memory_budget || {
      total_host_ram_gb: 32.0,
      safe_max_vm_ram_gb: 28.8,
      safe_slider_max_gb: 28,
      safe_headroom_gb: 20.8,
      override_max_ram_gb: 31.0,
    };
    const hostThreads = vmState.telemetry?.cpu_capacity?.host_threads || 8;
    const currentBootOrder = targetVm.boot_order || (targetVm.iso_path ? 'iso' : 'disk');
    const targetFirmware = targetVm.firmware || 'seabios';
    const targetVideo = targetVm.video_adapter || targetVm.display_adapter || 'virtio-gpu';
    let currentUsbDevices = Array.isArray(targetVm.usb_passthrough)
      ? targetVm.usb_passthrough.map((d) => ({ ...d }))
      : [];
    let currentPciDevices = Array.isArray(targetVm.pci_passthrough)
      ? targetVm.pci_passthrough.map((d) => ({ ...d }))
      : [];

    modal.innerHTML = `
      <div class="smart-modal-window vm-modal-window vme-col-2">
        <div class="smart-modal-header vme-row">
          <div class="smart-modal-title vme-row-2">
            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            <span>${escapeHtml(t('vmd.edit_title', 'Edit VM: {name}', { name: targetVm.name }))}</span>
          </div>
          <div class="os-window-controls vme-row-3">
            <button class="win-btn min-btn" id="vm-edit-modal-min" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
            <button class="win-btn max-btn" id="vm-edit-modal-max" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
            <button class="win-btn close-btn" id="vm-edit-modal-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

      <div class="smart-modal-body vme-col-3">
        ${isRunning ? `
          <div style="background: rgba(51,205,184,0.12); border: 1px solid rgba(51,205,184,0.3); border-radius: 6px; padding: 10px 14px; font-size: var(--zn-fs-xs); color: var(--zn-text-accent); display: flex; align-items: center; gap: 8px;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            <span>${t('vmd.running_note', 'This VM is running. Hardware changes (vCPUs, memory, boot order) take effect when it next restarts.')}</span>
          </div>
        ` : ''}

        <!-- General Info -->
        <div>
          <label class="vme-xs-bold-muted" for="vm-edit-name">${t('vmd.name_label', 'VM name *')}</label>
          <input class="vme-xs-strong-box" type="text" id="vm-edit-name" value="${escapeHtml(targetVm.name || '')}" />
        </div>

        <div>
          <label class="vme-xs-bold-muted" for="vm-edit-desc">${t('vmd.desc_label', 'Description')}</label>
          <input class="vme-xs-strong-box" type="text" id="vm-edit-desc" value="${escapeHtml(targetVm.description || '')}" placeholder="${t('ui.appliance_description', 'Appliance description')}" />
        </div>

        <!-- Snapshots Quick Launcher -->
        <div class="vme-row-box-2">
          <div>
            <div class="vme-row-xs-bold-strong">
              <svg class="vme-accent" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>${t('vmd.snaps_title', 'Snapshots')}</span>
            </div>
            <div class="vme-xs-muted-2">${t('vmd.snaps_desc', 'Save the VM’s state now, or go back to a saved one.')}</div>
          </div>
          <button type="button" id="vm-edit-open-snapshots" class="btn-vm-action btn-vm-snapshots vme-xs-bold" style="display: inline-flex;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>${t('vm.manage_snapshots', 'Manage Snapshots')}</span>
          </button>
        </div>

        <!-- RAM Allocation & Dynamic Headroom -->
        <div class="vme-box">
          <div class="vme-row-4">
            <span class="vme-xs-bold-strong">${t('vmd.ram_title', 'Memory (leaves room for the NAS)')}</span>
            <span class="vme-xs-bold-accent" id="vm-edit-ram-display">${targetVm.ram_gb || 4.0} GB</span>
          </div>
          <input type="range" id="vm-edit-ram-slider" min="0.5" max="${Math.max(budget.safe_slider_max_gb, targetVm.ram_gb || 4)}" step="0.5" value="${targetVm.ram_gb || 4.0}" style="width: 100%; accent-color: var(--accent-cyan, #33cdb8); cursor: pointer;" />
          <div class="vme-row-xs-muted">
            <span>${t('vmd.ram_min', 'Min: 0.5 GB')}</span>
            <span id="vm-edit-slider-max-label">${t('vmd.ram_safe', 'Safe max: {gb} GB', { gb: budget.safe_slider_max_gb })}</span>
          </div>
          <div class="vme-row-box-3">
            <label class="vme-row-xs-muted-2">
              <input type="checkbox" id="vm-edit-override-toggle" ${targetVm.override_active ? 'checked' : ''} style="accent-color: #f59e0b;" />
              <span>${t('vmd.override', 'Advanced: ignore the NAS’s reserve')}</span>
            </label>
            <span id="vm-edit-override-pill" style="display: ${targetVm.override_active ? 'inline-block' : 'none'}; font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.2); color: var(--zn-text-warn); border: 1px solid rgba(245,158,11,0.4);">
              ${ico('⚡')} ${t('vmd.bypassed', 'NAS reserve ignored')}
            </span>
          </div>
        </div>

        <!-- vCPUs Slider -->
        <div class="vme-box">
          <div class="vme-row-4">
            <span class="vme-xs-bold-strong">${t('vmd.vcpus', 'vCPU cores')}</span>
            <span class="vme-xs-bold-strong" id="vm-edit-vcpu-display">${targetVm.vcpus || 2} vCPUs</span>
          </div>
          <input type="range" id="vm-edit-vcpu-slider" min="1" max="${Math.max(hostThreads, targetVm.vcpus || 2)}" step="1" value="${targetVm.vcpus || 2}" style="width: 100%; accent-color: var(--accent-cyan, #33cdb8); cursor: pointer;" />
          <div class="vme-row-xs-muted">
            <span>1 vCPU</span>
            <span>${t('vmd.thread_limit', 'Physical limit: {count, plural, one {# thread} other {# threads}}', { count: hostThreads })}</span>
          </div>
          <div id="vm-edit-overcommit-warning" style="display: ${(targetVm.vcpus || 2) > hostThreads ? 'block' : 'none'}; margin-top: 8px; font-size: var(--zn-fs-xs); padding: 6px 10px; border-radius: 4px; background: rgba(245,158,11,0.15); color: var(--zn-text-warn); border: 1px solid rgba(245,158,11,0.3);">
            ${ico('⚠️')} ${t('vmd.over_threads', 'More cores than the host has threads: busy moments may slow the VM down.')}
          </div>
        </div>

        <!-- ISO Attach / Detach & Boot Order -->
        <div class="vme-col-box">
          <div>
            <div class="vme-row-5">
              <label class="vme-xs-bold-muted-2" for="vm-edit-iso">${t('vmd.iso_label', 'ISO image (CD-ROM)')}</label>
              ${targetVm.iso_path ? `<span class="vme-xs-warn">${ico('💿')} ${t('vmd.iso_attached', 'Attached')}</span>` : ''}
            </div>
            <select id="vm-edit-iso" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: var(--lt-b-1a2629ff, #1a2629); border: 1px solid var(--zn-line-12); color: var(--zn-text-strong); font-size: var(--zn-fs-xs); box-sizing: border-box;">
              <option value="">${t('vmd.iso_none', 'None (empty drive)')}</option>
              ${vmState.isos.map((iso) => `<option value="${escapeHtml(iso.path)}" ${iso.path === targetVm.iso_path ? 'selected' : ''}>${escapeHtml(iso.name)} (${iso.size_formatted})</option>`).join('')}
            </select>
          </div>

          <div>
            <label class="vme-xs-bold-muted">${t('vmd.boot_order', 'Boot order')}</label>
            <div class="vm-boot-order-group">
              <label class="boot-order-label">
                <input type="radio" name="vm-edit-boot-order" value="iso" ${currentBootOrder === 'iso' ? 'checked' : ''} />
                <span>${ico('💿')} ${t('vmd.boot_iso', 'Boot from the ISO first')}</span>
              </label>
              <label class="boot-order-label">
                <input type="radio" name="vm-edit-boot-order" value="disk" ${currentBootOrder === 'disk' ? 'checked' : ''} />
                <span>${ico('💽')} ${t('vmd.boot_disk', 'Boot from the disk')}</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Firmware & Boot Architecture -->
        <div class="vme-box">
          <div class="vme-x-2">
            <div class="vme-xs-bold-strong" data-i18n="vm.firmware_title">${t('vm.firmware_title', 'Firmware & Boot Architecture')}</div>
            <div class="vme-xs-muted-3" data-i18n="vm.firmware_desc">${t('vm.firmware_desc', 'Select hypervisor firmware initialization and virtual hardware security.')}</div>
          </div>
          <div class="vm-firmware-group">
            <label class="firmware-label">
              <div class="vme-row-bold">
                <input type="radio" name="vm-edit-firmware" value="seabios" ${targetFirmware === 'seabios' ? 'checked' : ''} />
                <span data-i18n="vm.firmware_seabios">${t('vm.firmware_seabios', 'SeaBIOS (Legacy BIOS)')}</span>
              </div>
              <div class="firmware-label-sub">${t('vmd.bios_sub', 'MBR partitions, older Linux and Windows 7/10')}</div>
            </label>
            <label class="firmware-label">
              <div class="vme-row-bold">
                <input type="radio" name="vm-edit-firmware" value="uefi" ${targetFirmware === 'uefi' ? 'checked' : ''} />
                <span data-i18n="vm.firmware_uefi">${t('vm.firmware_uefi', 'OVMF / UEFI (Modern / Win 11)')}</span>
              </div>
              <div class="firmware-label-sub">${t('vmd.uefi_sub', '64-bit UEFI, saved settings, Secure Boot')}</div>
            </label>
          </div>

          <!-- Virtual TPM 2.0 Toggle -->
          <div class="vme-row-box-3">
            <label class="vme-row-xs-strong">
              <input type="checkbox" id="vm-edit-tpm" ${targetVm.tpm_enabled ? 'checked' : ''} style="accent-color: var(--accent-cyan, #33cdb8);" />
              <span data-i18n="vm.tpm_title">${t('vm.tpm_title', 'Enable Virtual TPM 2.0 (vTPM)')}</span>
            </label>
            ${vtpmBadgeHtml()}
          </div>
        </div>

        <!-- Display & Video Adapter -->
        <div class="vme-box">
          <div class="vme-row-4">
            <div>
              <div class="vme-xs-bold-strong" data-i18n="vm.video_title">${t('vm.video_title', 'Display & Video Adapter')}</div>
              <div class="vme-xs-muted-3">${t('vmd.video_desc', 'Choose the virtual graphics card, or a text console only')}</div>
            </div>
            <span style="font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.15); color: var(--zn-text-ok); border: 1px solid rgba(16,185,129,0.3);">
              ${t('vmd.gpu_accel', 'GPU accelerated')}
            </span>
          </div>
          <select id="vm-edit-video-adapter" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: var(--lt-b-1a2629ff, #1a2629); border: 1px solid var(--zn-line-12); color: var(--zn-text-strong); font-size: var(--zn-fs-xs); box-sizing: border-box;">
            <option value="virtio-gpu" ${targetVideo === 'virtio-gpu' ? 'selected' : ''}>${t('vmd.v_virtio', 'VirtIO-GPU (recommended, 2D/3D acceleration on Linux)')}</option>
            <option value="qxl" ${targetVideo === 'qxl' ? 'selected' : ''}>${t('vmd.v_qxl', 'QXL (SPICE, Windows drivers)')}</option>
            <option value="vga" ${targetVideo === 'vga' ? 'selected' : ''}>${t('vmd.v_vga', 'Standard VGA (works everywhere)')}</option>
            <option value="none" ${targetVideo === 'none' ? 'selected' : ''}>${t('vmd.v_none', 'Headless (serial console only, no video memory)')}</option>
          </select>
        </div>

        <!-- Host USB Passthrough -->
        <div class="vm-config-card vme-box-2">
          <div class="vme-row-6">
            <div>
              <div class="vme-xs-bold-strong" data-i18n="vm.usb_title">${t('vm.usb_title', 'Host USB Device Passthrough')}</div>
              <div class="vme-xs-muted-3" data-i18n="vm.usb_desc">${t('vm.usb_desc', 'Attach physical host USB peripherals directly into the guest VM.')}</div>
            </div>
            <button type="button" id="btn-edit-toggle-custom-usb" class="btn-pill-toggle vme-x-3" data-i18n="vm.usb_custom_btn">
              ${t('vm.usb_custom_btn', '+ Custom VID:PID')}
            </button>
          </div>

          <!-- Dynamic host USB selector row -->
          <div class="usb-select-row">
            <select id="vm-edit-host-usb-select" class="tz-select">
              <option value="">${t('vmd.usb_scanning', 'Looking for USB devices…')}</option>
            </select>
            <button type="button" id="btn-edit-add-usb-device" class="btn-attach-usb">
              ${t('vm.usb_add_btn', '+ Attach Device')}
            </button>
          </div>

          <!-- Custom USB inputs (hidden by default) -->
          <div id="vm-edit-custom-usb-wrap" class="usb-custom-row" style="display: none;">
            <input class="vme-xs-strong-box-2" type="text" id="vm-edit-custom-vid" placeholder="VID (10c4)" data-sample maxlength="4" />
            <input class="vme-xs-strong-box-2" type="text" id="vm-edit-custom-pid" placeholder="PID (ea60)" data-sample maxlength="4" />
            <input type="text" id="vm-edit-custom-desc" class="usb-custom-desc vme-xs-strong-box-3" placeholder="${t('ui.device_label_e_g_zigbee', 'Device Label (e.g. Zigbee Dongle)')}" />
            <button type="button" id="btn-edit-add-custom-usb" class="btn-console-act btn-custom-add" style="padding: 4px 10px; font-size: var(--zn-fs-xs); background: rgba(16,185,129,0.2); border-color: #34d399; color: var(--zn-text-ok); cursor: pointer;">
              ${t('vmd.add', 'Add')}
            </button>
          </div>

          <!-- Attached USB devices list -->
          <div class="vme-x-4" id="vm-edit-usb-list" style="display: flex;"></div>
        </div>

        <!-- Host PCI / GPU Passthrough (VFIO) -->
        <div class="vm-config-card vm-pci-card vme-box-2">
          <div class="vme-x-2">
            <div class="vme-xs-bold-strong" data-i18n="vm.pci_title">${t('vm.pci_title', 'PCI / GPU Passthrough (VFIO)')}</div>
            <div class="vme-xs-muted-3" data-i18n="vm.pci_desc">${t('vm.pci_desc', 'Give the VM exclusive use of a host PCI device such as a GPU. The device must be bound to the vfio-pci driver on the host.')}</div>
          </div>
          <div class="vme-x-5" id="vm-edit-pci-list" style="display: flex;"></div>
        </div>

        <!-- Host Folder Passthrough (VirtIO-FS / 9p) -->
        <div class="vme-box">
          <div class="vme-row-4">
            <div>
              <span class="vme-xs-bold-strong">${t('vmd.folders_title', 'Host folders in the VM (VirtIO-FS / 9p)')}</span>
              <div class="vme-xs-muted-3">${t('vmd.folders_desc', 'Show host folders (/mnt/user/appdata, /mnt/storage) inside the VM')}</div>
            </div>
            <button type="button" id="btn-edit-add-host-share" class="btn-pill-toggle is-small">
              + ${t('ci.add_mount', 'Add folder')}
            </button>
          </div>
          <div class="vme-x-6" id="vm-edit-host-shares-list" style="display: flex;"></div>
        </div>

        <!-- Secondary Virtual Disks -->
        <div class="vme-box">
          <div class="vme-row-4">
            <div>
              <span class="vme-xs-bold-strong">${t('vmd.disks_title', 'More virtual disks')}</span>
              <div class="vme-xs-muted-3">${t('vmd.disks_desc', 'Attach more disks (data, databases)')}</div>
            </div>
            <button type="button" id="btn-edit-add-secondary-disk" class="btn-pill-toggle is-small">
              + ${t('vmd.add_disk', 'Add disk')}
            </button>
          </div>
          <div class="vme-x-6" id="vm-edit-secondary-disks-list" style="display: flex;"></div>
        </div>

        <div>
          <label class="vme-row-xs-strong-2">
            <input type="checkbox" id="vm-edit-autostart" ${targetVm.autostart ? 'checked' : ''} style="accent-color: var(--accent-cyan, #33cdb8);" />
            <span>${t('vmd.autostart', 'Start with the NAS')}</span>
          </label>
        </div>
      </div>

      <div class="smart-modal-footer vme-row-box-4">
        <button id="vm-edit-cancel" class="btn-console-act vme-soft-box-2">
          ${t('common.cancel', 'Cancel')}
        </button>
        <button id="vm-edit-submit" class="btn-console-act" style="background: #0a7a70; color: #fff; border-color: #33cdb8; padding: 6px 18px; font-weight: 700;">
          ${t('ui.save_configuration', 'Save Configuration')}
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
        maxBtn.setAttribute('title', t('vmd.restore', 'Restore'));
        maxBtn.setAttribute('aria-label', t('vmd.restore', 'Restore'));
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
        maxBtn.setAttribute('title', t('ui.maximize', 'Maximize'));
        maxBtn.setAttribute('aria-label', t('ui.maximize', 'Maximize'));
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
      ramDisplay.textContent = `${formatFixed(parseFloat(ramSlider.value), 1)} GB`;
    };
  }

  if (overrideToggle) {
    overrideToggle.onchange = () => {
      if (overrideToggle.checked) {
        ramSlider.max = budget.override_max_ram_gb || 31.0;
        if (sliderMaxLabel) sliderMaxLabel.textContent = t('vmd.ram_override', 'Override max: {gb} GB', { gb: ramSlider.max });
        if (overridePill) overridePill.style.display = 'inline-block';
      } else {
        ramSlider.max = budget.safe_slider_max_gb || 28;
        if (parseFloat(ramSlider.value) > ramSlider.max) {
          ramSlider.value = ramSlider.max;
          ramDisplay.textContent = `${ramSlider.value} GB`;
        }
        if (sliderMaxLabel) sliderMaxLabel.textContent = t('vmd.ram_safe', 'Safe max: {gb} GB', { gb: ramSlider.max });
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
      <input type="text" class="share-host-path vme-xs-strong-box-grow" placeholder="/mnt/user/appdata" value="${escapeHtml(share.host_path || '/mnt/user/appdata')}" />
      <input type="text" class="share-mount-tag vme-xs-strong-box-grow-2" placeholder="appdata" value="${escapeHtml(share.mount_tag || 'appdata')}" />
      <select class="share-driver" style="flex: 1; padding: 6px 4px; border-radius: 4px; background: var(--lt-b-1a2629ff, #1a2629); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);">
        <option value="virtiofs" ${share.driver === 'virtiofs' ? 'selected' : ''}>${'VirtIO-FS'}</option>
        <option value="9p" ${share.driver === '9p' ? 'selected' : ''}>9p</option>
      </select>
      <select class="share-mode" style="width: 60px; padding: 6px 4px; border-radius: 4px; background: var(--lt-b-1a2629ff, #1a2629); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);">
        <option value="rw" ${!share.readonly ? 'selected' : ''}>RW</option>
        <option value="ro" ${share.readonly ? 'selected' : ''}>RO</option>
      </select>
      <button type="button" class="btn-remove-share vme-crit-box">✕</button>
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
      <input type="text" class="disk-name vme-xs-strong-box-grow" placeholder="${t('ui.disk_name', 'Disk Name')}" value="${escapeHtml(disk.name || `data-disk-${idx}`)}" />
      <input type="number" class="disk-size vme-xs-strong-box-4" min="5" max="4000" placeholder="${t('ui.size_gb', 'Size (GB)')}" value="${disk.size_gb || 50}" />
      <select class="disk-bus" style="width: 80px; padding: 6px 4px; border-radius: 4px; background: var(--lt-b-1a2629ff, #1a2629); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);">
        <option value="virtio" ${disk.bus === 'virtio' ? 'selected' : ''}>virtio</option>
        <option value="sata" ${disk.bus === 'sata' ? 'selected' : ''}>sata</option>
        <option value="nvme" ${disk.bus === 'nvme' ? 'selected' : ''}>nvme</option>
      </select>
      <button type="button" class="btn-remove-disk vme-crit-box">✕</button>
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

  // Host PCI / GPU passthrough (VFIO). Only devices the host has bound to vfio-pci
  // can be picked; the rest show the driver they are on, so a host GPU, NIC or
  // disk controller is never handed to a VM by accident.
  const pciList = modal.querySelector('#vm-edit-pci-list');
  const PCI_CLASS_LABELS = {
    '0300': 'GPU', '0302': 'GPU', '0380': 'GPU', '0403': 'Audio', '0200': 'Network',
    '0280': 'Wi-Fi', '0108': 'NVMe', '0106': 'SATA', '0104': 'RAID', '0c03': 'USB',
  };
  const PCI_HIDDEN_CLASSES = new Set(['0600', '0601', '0604']); // host/ISA/PCI bridges
  const pciNote = (text, warn = false) =>
    `<div class="vm-pci-note${warn ? ' warn' : ''}" style="font-size: var(--zn-fs-xs); padding: 6px 10px; border-radius: 4px; background: ${warn ? 'rgba(245,158,11,0.12)' : 'rgba(0,0,0,0.2)'}; color: ${warn ? '#fbbf24' : 'var(--muted)'};">${escapeHtml(text)}</div>`;
  const renderPciList = (data) => {
    if (!pciList) return;
    if (!data || !data.iommu_enabled) {
      pciList.innerHTML = pciNote(t('vm.pci_no_iommu', 'IOMMU is not enabled on this host, so PCI passthrough is unavailable.'), true);
      return;
    }
    const selected = new Set(currentPciDevices.map((d) => d.slot));
    const rows = [];
    if (data.vfio_available === false) {
      rows.push(pciNote(t('vm.pci_vfio_missing', '/dev/vfio is not available; pass it to the container to use PCI passthrough.'), true));
    }
    for (const group of data.groups || []) {
      const devs = (group.devices || []).filter((d) => !PCI_HIDDEN_CLASSES.has(String(d.class_code || '').slice(0, 4)));
      if (devs.length === 0) continue;
      if (devs.length > 1) {
        rows.push(`<div class="vm-pci-group-note vme-xs-muted-4">${escapeHtml(t('vm.pci_group_note', 'IOMMU group {group}: pass all of its devices together', { group: group.group_id }))}</div>`);
      }
      for (const dev of devs) {
        const slot = String(dev.slot || '').replace(/^0000:/, '').toLowerCase();
        const kind = PCI_CLASS_LABELS[String(dev.class_code || '').slice(0, 4)] || 'PCI';
        const ready = Boolean(dev.vfio_ready);
        const checked = selected.has(slot);
        const driverText = ready
          ? 'vfio-pci'
          : t('vm.pci_needs_vfio', 'On {driver}; bind to vfio-pci first', { driver: dev.driver || t('vm.pci_no_driver', 'no driver') });
        rows.push(`
          <label class="vm-pci-row${ready ? '' : ' disabled'}" style="display: flex; align-items: center; gap: 8px; font-size: var(--zn-fs-xs); padding: 4px 8px; border-radius: 4px; background: var(--zn-shade-20); cursor: ${ready || checked ? 'pointer' : 'not-allowed'}; opacity: ${ready || checked ? '1' : '0.6'};">
            <input type="checkbox" class="vm-pci-check" data-slot="${escapeHtml(slot)}" data-name="${escapeHtml(`${kind} ${dev.name || ''}`.trim())}" ${checked ? 'checked' : ''} ${ready || checked ? '' : 'disabled'} />
            <span class="vme-bold-strong">${escapeHtml(kind)}</span>
            <span class="vme-accent-mono">${escapeHtml(slot)}</span>
            <span class="vme-muted-grow">${escapeHtml(dev.name || '')}</span>
            <span class="vm-pci-driver" style="font-size: var(--zn-fs-xs); color: ${ready ? '#34d399' : '#fbbf24'}; white-space: nowrap;">${escapeHtml(driverText)}</span>
          </label>
        `);
      }
    }
    if (rows.length === 0) rows.push(pciNote(t('vm.pci_none', 'No passthrough-capable PCI devices found.')));
    pciList.innerHTML = rows.join('');
    pciList.querySelectorAll('.vm-pci-check').forEach((cb) => {
      cb.onchange = () => {
        const slot = cb.dataset.slot;
        currentPciDevices = currentPciDevices.filter((d) => d.slot !== slot);
        if (cb.checked) currentPciDevices.push({ slot, name: cb.dataset.name || '' });
      };
    });
  };
  if (pciList) {
    pciList.innerHTML = pciNote(t('vm.pci_scanning', 'Scanning host PCI devices...'));
    api
      .get('/api/vms/iommu-groups')
      .then(renderPciList)
      .catch(() => {
        pciList.innerHTML = pciNote(t('vm.pci_scan_failed', 'Failed to scan host PCI devices.'), true);
      });
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
        <div class="vme-xs-muted-box-center" data-i18n="vm.usb_no_devices">
          ${t('vm.usb_no_devices', 'No host USB devices attached to this VM.')}
        </div>
      `;
      return;
    }
    currentUsbDevices.forEach((dev, idx) => {
      const card = document.createElement('div');
      card.className = 'usb-device-card';
      card.innerHTML = `
        <div class="vme-row-7">
          <span class="vme-fs14">🔌</span>
          <div class="vme-size-2">
            <div class="vme-xs-bold-strong-2">
              ${escapeHtml(dev.description || dev.product || 'USB Device')}
            </div>
            <div class="vme-xs-muted-3">
              ${escapeHtml(dev.manufacturer || 'Generic')} ${dev.bus ? `· Bus ${dev.bus} Dev ${dev.dev}` : ''}
            </div>
          </div>
        </div>
        <div class="vme-row-2">
          <span class="usb-vidpid-badge">${escapeHtml(dev.vendor_id)}:${escapeHtml(dev.product_id)}</span>
          <button type="button" class="btn-remove-usb vme-xs-crit-box" data-idx="${idx}" title="${t('ui.remove_device', 'Remove device')}">✕</button>
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
      usbSelect.innerHTML = '<option value="">' + t('vmd.usb_pick', '— Choose a USB device —') + '</option>';
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
        usbSelect.innerHTML = '<option value="">' + t('vmd.usb_none', 'No USB devices found') + '</option>';
      }
    })
    .catch(() => {
      if (!usbSelect) return;
      usbSelect.innerHTML = '<option value="">' + t('vmd.usb_failed', 'Could not look for USB devices') + '</option>';
    });

  if (btnAddUsb && usbSelect) {
    btnAddUsb.onclick = () => {
      const val = usbSelect.value;
      if (!val) {
        showToast(t('toast.select_a_host_usb_device_to', 'Select a host USB device to attach'), 'warning');
        return;
      }
      try {
        const item = JSON.parse(val);
        if (!currentUsbDevices.some((d) => d.vendor_id === item.vendor_id && d.product_id === item.product_id)) {
          currentUsbDevices.push(item);
          renderUsbList();
          showToast(t('toast.attached_usb_device', 'Attached USB device: {description}', { description: item.description || item.vendor_id }), 'info');
        } else {
          showToast(t('toast.device_is_already_attached_to_this', 'Device is already attached to this VM'), 'warning');
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
        showToast(t('toast.please_enter_valid_4_character_hex', 'Please enter valid 4-character hex VID and PID (e.g. 10c4, ea60)'), 'warning');
        return;
      }
      if (!currentUsbDevices.some((d) => d.vendor_id === vid && d.product_id === pid)) {
        currentUsbDevices.push({ vendor_id: vid, product_id: pid, description: desc, manufacturer: 'Custom' });
        renderUsbList();
        modal.querySelector('#vm-edit-custom-vid').value = '';
        modal.querySelector('#vm-edit-custom-pid').value = '';
        modal.querySelector('#vm-edit-custom-desc').value = '';
        showToast(t('toast.added_custom_usb_device', 'Added custom USB device [{vid}:{pid}]', { vid: vid, pid: pid }), 'info');
      } else {
        showToast(t('toast.device_is_already_attached_to_this', 'Device is already attached to this VM'), 'warning');
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
        showToast(t('toast.vm_name_is_required', 'VM Name is required'), 'error');
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
        pci_passthrough: currentPciDevices,
        autostart: newAutostart,
        override_limits: overrideLimits,
        host_shares: hostShares,
        secondary_disks: secondaryDisks,
      };

      try {
        submitBtn.disabled = true;
        submitBtn.textContent = t('ui.saving', 'Saving...');

        await api.put(`/api/vms/${vmId}`, payload);

        Object.assign(targetVm, payload);
        showToast(t('toast.vm_configuration_updated', 'VM \'{newName}\' configuration updated', { newName: newName }), 'success');
        close();
        loadVmDashboard();
        window.dispatchEvent(new CustomEvent('vm-updated', { detail: { id: vmId } }));
      } catch (err) {
        showToast(t('toast.failed_to_update_vm', 'Failed to update VM: {error}', { error: err.message || 'Error' }), 'error');
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = t('ui.save_configuration', 'Save Configuration');
        }
      }
    };
  }
};

  if (targetVm) {
    if (!vmState.list.some((v) => v.id === targetVm.id)) vmState.list.push(targetVm);
    renderModal(targetVm);
    return;
  }

  // Graceful auto-fetch when called outside of standalone VM Manager window
  Promise.all([
    api.get(`/api/vms/${vmId}`).catch(() => null),
    (!vmState.isos || vmState.isos.length === 0) ? api.get('/api/vms/isos').catch(() => []) : Promise.resolve(vmState.isos),
    !vmState.telemetry ? api.get('/api/vms/telemetry').catch(() => null) : Promise.resolve(vmState.telemetry),
  ])
    .then(([direct, isos, tel]) => {
      if (tel) vmState.telemetry = tel;
      if (Array.isArray(isos)) vmState.isos = isos;
      if (direct && direct.id) {
        if (!vmState.list.some((v) => v.id === direct.id)) vmState.list.push(direct);
        renderModal(direct);
      } else {
        showToast(t('toast.virtual_machine_not_found', 'Virtual machine \'{vmId}\' not found', { vmId: vmId }), 'error');
      }
    })
    .catch((err) => {
      showToast(t('toast.virtual_machine_not_found_2', 'Virtual machine \'{vmId}\' not found: {error}', { vmId: vmId, error: err.message || 'Error' }), 'error');
    });
}
