// The new-VM wizard.
// Part of vm-manager.js, split out by ARC-5.

import { api } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';
import { makeDraggable, bringToFront } from '../dock.js';
import { vmState } from './state.js';
import { openIsoManagerModal } from './iso-manager.js';
import { vtpmBadgeHtml } from './shared.js';
import { loadVmDashboard } from '../vm-manager.js';

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

  const budget = vmState.telemetry?.memory_budget || {
    total_host_ram_gb: 32.0,
    safe_max_vm_ram_gb: 28.8,
    safe_slider_max_gb: 28,
    safe_headroom_gb: 20.8,
    override_max_ram_gb: 31.0,
  };
  const hostThreads = vmState.telemetry?.cpu_capacity?.host_threads || 8;

  modal.innerHTML = `
    <div class="smart-modal-window vm-modal-window" style="max-width: 580px; width: 92%; max-height: 88vh; display: flex; flex-direction: column; overflow: hidden;">
      <div class="smart-modal-header" style="cursor: move; user-select: none; display: flex; justify-content: space-between; align-items: center;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span data-i18n="vm.create_btn">${escapeHtml(t('vm.create_btn', 'Create Virtual Machine'))}</span>
        </div>
        <div class="os-window-controls" style="display: flex; gap: 6px; align-items: center;">
          <button class="win-btn min-btn" id="vm-create-modal-min" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
          <button class="win-btn max-btn" id="vm-create-modal-max" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
          <button class="win-btn close-btn" id="vm-modal-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
        </div>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 14px; padding: 18px 22px;">
        <!-- Step 1: General -->
        <div>
          <label for="vm-create-name" style="display: block; font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted); margin-bottom: 6px;">VM Name *</label>
          <input type="text" id="vm-create-name" placeholder="e.g. ubuntu-dev-node" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-12); color: var(--zn-text-strong); font-size: var(--zn-fs-xs); box-sizing: border-box;" />
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div>
            <label for="vm-create-os" style="display: block; font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted); margin-bottom: 6px;">OS Family</label>
            <select id="vm-create-os" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: var(--lt-b-1e293bff, #1e293b); border: 1px solid var(--zn-line-12); color: var(--zn-text-strong); font-size: var(--zn-fs-xs); box-sizing: border-box;">
              <option value="linux">Linux (Ubuntu / Debian / Alpine)</option>
              <option value="windows">Microsoft Windows</option>
              <option value="bsd">BSD / TrueNAS</option>
              <option value="other">Other / Generic</option>
            </select>
          </div>
          <div>
            <label style="display: block; font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted); margin-bottom: 6px;">Autostart on Boot</label>
            <label style="display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: var(--zn-fs-xs); color: var(--zn-text-strong); cursor: pointer;">
              <input type="checkbox" id="vm-create-autostart" style="accent-color: var(--accent-cyan, #0ea5e9);" />
              <span>Start with Host</span>
            </label>
          </div>
        </div>

        <!-- Step 2: Compute & Elastic Headroom -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">RAM Allocation (Dynamic Headroom)</span>
            <span id="vm-ram-display" style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-accent);">4.0 GB</span>
          </div>
          <input type="range" id="vm-create-ram-slider" min="0.5" max="${budget.safe_slider_max_gb}" step="0.5" value="4.0" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: var(--zn-fs-xs); color: var(--muted); margin-top: 4px;">
            <span>Min: 0.5 GB</span>
            <span id="vm-slider-max-label">Safe Max: ${budget.safe_slider_max_gb} GB</span>
          </div>

          <!-- Advanced Override Switch -->
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--zn-line-5); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: var(--zn-fs-xs); color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-override-toggle" style="accent-color: #f59e0b;" />
              <span data-i18n="vm.advanced_override">${t('vm.advanced_override', 'Advanced Override (Bypass Headroom)')}</span>
            </label>
            <span id="vm-override-pill" style="display: none; font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.2); color: var(--zn-text-warn); border: 1px solid rgba(245,158,11,0.4);">
              ⚡ Host reserve bypassed
            </span>
          </div>
        </div>

        <!-- vCPU Slider & Overcommit Warning -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">vCPU Cores</span>
            <span id="vm-vcpu-display" style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">2 vCPUs</span>
          </div>
          <input type="range" id="vm-create-vcpu-slider" min="1" max="${hostThreads}" step="1" value="2" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: var(--zn-fs-xs); color: var(--muted); margin-top: 4px;">
            <span>1 vCPU</span>
            <span id="vm-vcpu-max-label">Physical Limit: ${hostThreads} Threads</span>
          </div>
          <div id="vm-overcommit-soft-warning" style="display: none; margin-top: 8px; font-size: var(--zn-fs-xs); padding: 6px 10px; border-radius: 4px; background: rgba(245,158,11,0.15); color: var(--zn-text-warn); border: 1px solid rgba(245,158,11,0.3);">
            ⚠️ Soft warning: Exceeds physical threads. Bursty workloads allowed, but concurrent CPU spikes may cause scheduling latency.
          </div>
        </div>

        <!-- Step 3: Storage & ISO -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label for="vm-create-iso" style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted);">Boot ISO Image</label>
              <button type="button" id="btn-browse-iso-catalog" style="background: none; border: none; color: var(--zn-text-accent); font-size: var(--zn-fs-xs); cursor: pointer; padding: 0;">🌐 ISO Catalog</button>
            </div>
            <select id="vm-create-iso" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: var(--lt-b-1e293bff, #1e293b); border: 1px solid var(--zn-line-12); color: var(--zn-text-strong); font-size: var(--zn-fs-xs); box-sizing: border-box;">
              <option value="">None (Network PXE / Empty Disk)</option>
              ${vmState.isos.map((iso) => `<option value="${escapeHtml(iso.path)}">${escapeHtml(iso.name)} (${iso.size_formatted})</option>`).join('')}
            </select>
          </div>
          <div>
            <label for="vm-create-disk" style="display: block; font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted); margin-bottom: 6px;">OS Virtual Disk (GB)</label>
            <input type="number" id="vm-create-disk" min="10" max="2000" value="32" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-12); color: var(--zn-text-strong); font-size: var(--zn-fs-xs); box-sizing: border-box;" />
          </div>
        </div>

        <!-- Boot Priority Order -->
        <div>
          <label style="display: block; font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted); margin-bottom: 6px;">Boot Priority Order</label>
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
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 12px;">
          <div style="margin-bottom: 8px;">
            <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);" data-i18n="vm.firmware_title">${t('vm.firmware_title', 'Firmware & Boot Architecture')}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted);" data-i18n="vm.firmware_desc">${t('vm.firmware_desc', 'Select hypervisor firmware initialization and virtual hardware security.')}</div>
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
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--zn-line-5); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: var(--zn-fs-xs); color: var(--zn-text-strong); cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-create-tpm" style="accent-color: var(--accent-cyan, #0ea5e9);" />
              <span data-i18n="vm.tpm_title">${t('vm.tpm_title', 'Enable Virtual TPM 2.0 (vTPM)')}</span>
            </label>
            ${vtpmBadgeHtml()}
          </div>
        </div>

        <!-- Step 4: Host Volume Mappings (VirtIO-FS / 9p) -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">Host Directory Passthrough (VirtIO-FS / 9p)</span>
              <div style="font-size: var(--zn-fs-xs); color: var(--muted);">Map host folders (/mnt/user/appdata, /mnt/storage) into guest</div>
            </div>
            <button type="button" id="btn-add-host-share" class="btn-pill-toggle is-small">
              + Add Folder
            </button>
          </div>
          <div id="vm-host-shares-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <!-- Step 5: Secondary Virtual Disks -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">Secondary Virtual Disks</span>
              <div style="font-size: var(--zn-fs-xs); color: var(--muted);">Attach additional block devices (data pools, databases)</div>
            </div>
            <button type="button" id="btn-add-secondary-disk" class="btn-pill-toggle is-small">
              + Add Disk
            </button>
          </div>
          <div id="vm-secondary-disks-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <!-- Step 6: Network Bridge -->
        <div>
          <label for="vm-create-bridge" style="display: block; font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted); margin-bottom: 6px;">Network Bridge</label>
          <select id="vm-create-bridge" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: var(--lt-b-1e293bff, #1e293b); border: 1px solid var(--zn-line-12); color: var(--zn-text-strong); font-size: var(--zn-fs-xs); box-sizing: border-box;">
            ${vmState.bridges.map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)} (Host Bridge)</option>`).join('')}
          </select>
        </div>

        <!-- Step 7: Display & Graphics (KVM GUI) -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);" data-i18n="vm.video_title">${t('vm.video_title', 'Display & Video Adapter')}</span>
              <div style="font-size: var(--zn-fs-xs); color: var(--muted);">Virtual display adapter & video acceleration</div>
            </div>
            <span style="font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.15); color: var(--zn-text-ok); border: 1px solid rgba(16,185,129,0.3);">
              GPU Accelerated
            </span>
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label for="vm-create-gpu-driver" style="display: block; font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 4px;">Video Adapter</label>
              <select id="vm-create-gpu-driver" class="tz-select" style="width: 100%; padding: 6px 8px; border-radius: 4px; background: var(--lt-b-1e293bff, #1e293b); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);">
                <option value="virtio-gpu" selected>VirtIO-GPU (Recommended / 3D Accel)</option>
                <option value="qxl">QXL (SPICE / Standard)</option>
                <option value="vga">Standard VGA (Compatible)</option>
                <option value="none">Headless (Serial CLI Only)</option>
              </select>
            </div>
            <div>
              <label style="display: block; font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 4px;">Display Mode</label>
              <label style="display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: var(--zn-fs-xs); color: var(--zn-text-strong); cursor: pointer;">
                <input type="checkbox" id="vm-create-enable-gui" checked style="accent-color: var(--accent-cyan, #0ea5e9);" />
                <span>Enable Graphical Desktop (Display :0)</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Step 8: Host USB Device Passthrough -->
        <div class="vm-config-card" style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 12px; flex-shrink: 0;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; gap: 10px;">
            <div>
              <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);" data-i18n="vm.usb_title">${t('vm.usb_title', 'Host USB Device Passthrough')}</div>
              <div style="font-size: var(--zn-fs-xs); color: var(--muted);" data-i18n="vm.usb_desc">${t('vm.usb_desc', 'Attach physical host USB peripherals directly into the guest VM.')}</div>
            </div>
            <button type="button" id="btn-create-toggle-custom-usb" class="btn-pill-toggle" data-i18n="vm.usb_custom_btn" style="flex-shrink: 0;">
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
            <input type="text" id="vm-create-custom-vid" placeholder="VID (10c4)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: var(--zn-shade-40); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
            <input type="text" id="vm-create-custom-pid" placeholder="PID (ea60)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: var(--zn-shade-40); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
            <input type="text" id="vm-create-custom-desc" class="usb-custom-desc" placeholder="${t('ui.device_label_e_g_zigbee', 'Device Label (e.g. Zigbee Dongle)')}" style="padding: 5px 8px; border-radius: 4px; background: var(--zn-shade-40); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
            <button type="button" id="btn-create-add-custom-usb" class="btn-console-act btn-custom-add" style="padding: 4px 10px; font-size: var(--zn-fs-xs); background: rgba(16,185,129,0.2); border-color: #34d399; color: var(--zn-text-ok); cursor: pointer;">
              Add
            </button>
          </div>

          <!-- Attached USB devices list -->
          <div id="vm-create-usb-list" style="display: flex; flex-direction: column; gap: 6px; margin-top: 6px;"></div>
        </div>
      </div>

      <div class="smart-modal-footer" style="display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid var(--zn-line-8); background: var(--zn-shade-20);">
        <button id="vm-create-cancel" class="btn-pill-toggle">${t('common.cancel', 'Cancel')}</button>
        <button id="vm-create-submit" class="btn-save-preset" style="padding: 7px 18px; font-weight: 700; background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: var(--zn-text-strong);">${t('vm.create_btn', 'Create Virtual Machine')}</button>
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
        <input type="text" class="share-host-path" placeholder="/mnt/user/appdata" value="/mnt/user/appdata" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
        <input type="text" class="share-mount-tag" placeholder="appdata" value="appdata" style="flex: 1.2; padding: 6px 8px; border-radius: 4px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
        <select class="share-driver" style="flex: 1; padding: 6px 4px; border-radius: 4px; background: var(--lt-b-1e293bff, #1e293b); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);">
          <option value="virtiofs">VirtIO-FS</option>
          <option value="9p">9p</option>
        </select>
        <select class="share-mode" style="width: 60px; padding: 6px 4px; border-radius: 4px; background: var(--lt-b-1e293bff, #1e293b); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);">
          <option value="rw">RW</option>
          <option value="ro">RO</option>
        </select>
        <button type="button" class="btn-remove-share" style="background: none; border: none; color: var(--zn-text-crit); cursor: pointer; padding: 2px 6px;">✕</button>
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
        <input type="text" class="disk-name" placeholder="${t('ui.disk_name', 'Disk Name')}" value="data-disk-${idx}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
        <input type="number" class="disk-size" min="5" max="4000" placeholder="${t('ui.size_gb', 'Size (GB)')}" value="50" style="width: 80px; padding: 6px 8px; border-radius: 4px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);" />
        <select class="disk-bus" style="width: 80px; padding: 6px 4px; border-radius: 4px; background: var(--lt-b-1e293bff, #1e293b); border: 1px solid var(--zn-line-10); color: var(--zn-text-strong); font-size: var(--zn-fs-xs);">
          <option value="virtio">virtio</option>
          <option value="sata">sata</option>
          <option value="nvme">nvme</option>
        </select>
        <button type="button" class="btn-remove-disk" style="background: none; border: none; color: var(--zn-text-crit); cursor: pointer; padding: 2px 6px;">✕</button>
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
        <div style="font-size: var(--zn-fs-xs); color: var(--muted); padding: 8px 10px; text-align: center; background: var(--zn-shade-20); border-radius: 4px;" data-i18n="vm.usb_no_devices">
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
            <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
              ${escapeHtml(dev.description || dev.product || 'USB Device')}
            </div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted);">
              ${escapeHtml(dev.manufacturer || 'Generic')} ${dev.bus ? `· Bus ${dev.bus} Dev ${dev.dev}` : ''}
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="usb-vidpid-badge">${escapeHtml(dev.vendor_id)}:${escapeHtml(dev.product_id)}</span>
          <button type="button" class="btn-remove-usb" data-idx="${idx}" style="background: none; border: none; color: var(--zn-text-crit); cursor: pointer; padding: 2px 6px; font-size: var(--zn-fs-xs);" title="${t('ui.remove_device', 'Remove device')}">✕</button>
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
        showToast(t('toast.select_a_host_usb_device_to', 'Select a host USB device to attach'), 'warning');
        return;
      }
      try {
        const item = JSON.parse(val);
        if (!createUsbDevices.some((d) => d.vendor_id === item.vendor_id && d.product_id === item.product_id)) {
          createUsbDevices.push(item);
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
        showToast(t('toast.please_enter_valid_4_character_hex', 'Please enter valid 4-character hex VID and PID (e.g. 10c4, ea60)'), 'warning');
        return;
      }
      if (!createUsbDevices.some((d) => d.vendor_id === vid && d.product_id === pid)) {
        createUsbDevices.push({ vendor_id: vid, product_id: pid, description: desc, manufacturer: 'Custom' });
        renderUsbList();
        modal.querySelector('#vm-create-custom-vid').value = '';
        modal.querySelector('#vm-create-custom-pid').value = '';
        modal.querySelector('#vm-create-custom-desc').value = '';
        showToast(t('toast.added_custom_usb_device', 'Added custom USB device [{vid}:{pid}]', { vid: vid, pid: pid }), 'info');
      } else {
        showToast(t('toast.device_is_already_attached_to_this', 'Device is already attached to this VM'), 'warning');
      }
    };
  }

  // Submit Handler
  const btnSubmit = modal.querySelector('#vm-create-submit');
  if (btnSubmit) {
    btnSubmit.onclick = async () => {
      const name = modal.querySelector('#vm-create-name')?.value?.trim();
      if (!name) {
        showToast(t('toast.please_enter_a_valid_vm_name', 'Please enter a valid VM name.'), 'warning');
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
      btnSubmit.textContent = t('ui.provisioning_vm', 'Provisioning VM...');

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

        showToast(t('toast.virtual_machine_created_successfully', 'Virtual machine \'{name}\' created successfully!', { name: name }), 'success');
        closeModal();
        loadVmDashboard();
      } catch (err) {
        showToast(t('toast.failed_to_create_vm', 'Failed to create VM: {error}', { error: err.message }), 'error');
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = t('vm.create_btn', 'Create Virtual Machine');
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
