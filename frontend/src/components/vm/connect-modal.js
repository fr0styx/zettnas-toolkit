// How to connect to a VM (VNC, SPICE, SSH) and the KVM diagnostics dialog.
// Part of vm-manager.js, split out by ARC-5.

import { api } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';
import { makeDraggable } from '../dock.js';
import { vmState } from './state.js';
import { copyToClipboard, openVmConsole } from './console.js';

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

  let targetVm = vmObj || vmState.list.find((v) => v.id === vmId);

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
        <button id="vm-connect-modal-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 4px;" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding: 18px 22px;">
        <!-- Status summary banner -->
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-8); border-radius: 8px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="qemu-process-badge ${targetVm.state === 'running' ? 'active' : targetVm.state === 'paused' ? 'paused' : 'stopped'}">
              ● ${targetVm.state ? targetVm.state.toUpperCase() : 'UNKNOWN'}
            </span>
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${escapeHtml(name)}</span>
          </div>
          <span style="font-size: var(--zn-fs-xs); font-family: monospace; color: ${ip ? '#38bdf8' : 'var(--muted)'};">
            ${ip ? `IP: ${ip}` : 'No IP detected yet (DHCP pending)'}
          </span>
        </div>

        <!-- Option 1: In-Browser Web Console (KVM GUI & Serial TTY) -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🖥️</span>
              <div>
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">In-Browser Web Console</div>
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">Direct glassmorphic KVM GUI (VirtIO-GPU) or VT100 Serial TTY</div>
              </div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn-console-act btn-connect-gui" style="padding: 4px 10px; font-size: var(--zn-fs-xs); background: #0ea5e9; color: #fff; border-color: #38bdf8;">
                Launch KVM GUI
              </button>
              <button class="btn-console-act btn-connect-tty" style="padding: 4px 10px; font-size: var(--zn-fs-xs); background: rgba(52,211,153,0.15); color: var(--zn-text-ok); border-color: rgba(52,211,153,0.4);">
                Serial TTY
              </button>
            </div>
          </div>
        </div>

        <!-- Option 2: Native RFB / VNC Client -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🌐</span>
              <div>
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">Native VNC Client (RFB)</div>
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">TigerVNC, RealVNC, macOS Screen Sharing</div>
              </div>
            </div>
            <button class="btn-console-act btn-connect-copy-vnc" style="padding: 4px 10px; font-size: var(--zn-fs-xs);">
              📋 Copy VNC URI
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--zn-shade-35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: var(--zn-fs-xs); color: var(--zn-text-accent);">
            <span>${vncUri}</span>
            <span style="color: var(--muted); font-size: var(--zn-fs-xs);">Port ${vncPort}</span>
          </div>
        </div>

        <!-- Option 3: Secure Shell (SSH) -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🔒</span>
              <div>
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">Secure Shell (SSH)</div>
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">Terminal command for OpenSSH / PuTTY</div>
              </div>
            </div>
            <button class="btn-console-act btn-connect-copy-ssh" ${ip ? '' : `disabled title="${escapeHtml(t('vm.why_no_ip', 'Waiting for the VM to get a network address'))}"`} style="padding: 4px 10px; font-size: var(--zn-fs-xs); ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
              📋 Copy SSH Command
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--zn-shade-35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: var(--zn-fs-xs); color: ${ip ? '#34d399' : 'var(--muted)'};">
            <span>${ip ? sshCmd : 'Awaiting guest IP address assignment'}</span>
          </div>
        </div>

        <!-- Option 4: Remote Desktop Protocol (RDP) -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🪟</span>
              <div>
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">Remote Desktop (RDP)</div>
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">Microsoft Remote Desktop, Remmina, FreeRDP</div>
              </div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn-console-act btn-connect-copy-rdp" ${ip ? '' : `disabled title="${escapeHtml(t('vm.why_no_ip', 'Waiting for the VM to get a network address'))}"`} style="padding: 4px 10px; font-size: var(--zn-fs-xs); ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
                📋 Copy RDP URI
              </button>
              <button class="btn-console-act btn-connect-dl-rdp" ${ip ? '' : `disabled title="${escapeHtml(t('vm.why_no_ip', 'Waiting for the VM to get a network address'))}"`} style="padding: 4px 10px; font-size: var(--zn-fs-xs); ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
                ⬇ .rdp File
              </button>
            </div>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--zn-shade-35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: var(--zn-fs-xs); color: ${ip ? '#eab308' : 'var(--muted)'};">
            <span>${ip ? rdpUri : 'Awaiting guest IP address assignment'}</span>
            <span style="color: var(--muted); font-size: var(--zn-fs-xs);">Port 3389</span>
          </div>
        </div>

        <!-- Option 5: Host Storage Shares (VirtIO-FS / 9p) -->
        ${hostShares.length > 0 ? `
          <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
              <span style="font-size: 14px;">📂</span>
              <div>
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">VirtIO-FS / 9p Mount Instructions</div>
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">Run inside guest to access host shares</div>
              </div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px;">
              ${hostShares.map((s) => `
                <div style="display: flex; justify-content: space-between; align-items: center; background: var(--zn-shade-30); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: var(--zn-fs-xs);">
                  <span style="color: var(--zn-text-soft);">sudo mount -t virtiofs ${escapeHtml(s.mount_tag)} /mnt/${escapeHtml(s.mount_tag)}</span>
                  <button class="btn-console-act btn-copy-mount-cmd" data-cmd="sudo mkdir -p /mnt/${escapeHtml(s.mount_tag)} && sudo mount -t virtiofs ${escapeHtml(s.mount_tag)} /mnt/${escapeHtml(s.mount_tag)}" style="padding: 2px 8px; font-size: var(--zn-fs-xs);">Copy</button>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}
      </div>

      <div class="smart-modal-footer" style="padding: 12px 22px; display: flex; justify-content: flex-end; border-top: 1px solid var(--zn-line-8); background: var(--zn-shade-20);">
        <button id="vm-connect-close" class="btn-console-act" style="background: var(--zn-glaze-8); color: var(--zn-text-soft); padding: 6px 16px;">
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
    if (ok) showToast(t('toast.copied_vnc_uri_2', 'Copied VNC URI \'{vncUri}\'', { vncUri: vncUri }), 'info');
    else showToast(t('toast.failed_to_copy_vnc_uri', 'Failed to copy VNC URI'), 'error');
  });

  modal.querySelector('.btn-connect-copy-ssh')?.addEventListener('click', async () => {
    if (!sshCmd) return;
    const ok = await copyToClipboard(sshCmd);
    if (ok) showToast(t('toast.copied_2', 'Copied \'{sshCmd}\'', { sshCmd: sshCmd }), 'info');
    else showToast(t('toast.failed_to_copy_ssh_command', 'Failed to copy SSH command'), 'error');
  });

  modal.querySelector('.btn-connect-copy-rdp')?.addEventListener('click', async () => {
    if (!rdpUri) return;
    const ok = await copyToClipboard(rdpUri);
    if (ok) showToast(t('toast.copied_rdp_address', 'Copied RDP Address \'{rdpUri}\'', { rdpUri: rdpUri }), 'info');
    else showToast(t('toast.failed_to_copy_rdp_address', 'Failed to copy RDP Address'), 'error');
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
    showToast(t('toast.downloaded_rdp_file_for', 'Downloaded RDP file for {name}', { name: name }), 'success');
  });

  modal.querySelectorAll('.btn-copy-mount-cmd').forEach((btn) => {
    btn.onclick = async () => {
      const cmd = btn.dataset.cmd;
      const ok = await copyToClipboard(cmd);
      if (ok) showToast(t('toast.copied_mount_command_to_clipboard', 'Copied mount command to clipboard'), 'info');
    };
  });
  };

  if (targetVm) {
    if (!vmState.list.some((v) => v.id === targetVm.id)) vmState.list.push(targetVm);
    renderConnectModal(targetVm);
    return;
  }

  api.get(`/api/vms/${vmId}`)
    .then((direct) => {
      if (direct && direct.id) {
        if (!vmState.list.some((v) => v.id === direct.id)) vmState.list.push(direct);
        renderConnectModal(direct);
      } else {
        showToast(t('toast.virtual_machine_not_found', 'Virtual machine \'{vmId}\' not found', { vmId: vmId }), 'error');
      }
    })
    .catch((err) => {
      showToast(t('toast.virtual_machine_not_found_2', 'Virtual machine \'{vmId}\' not found: {error}', { vmId: vmId, error: err.message || 'Error' }), 'error');
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

  const k = kvm || vmState.telemetry?.kvm || {};
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
          <div style="font-size: var(--zn-fs-xs); color: var(--zn-text-soft); margin-top: 4px; line-height: 1.4;">
            ${escapeHtml(k.remediation || (k.state === 'active' ? 'Kernel-based Virtual Machine (KVM) hardware acceleration is fully active.' : 'Virtualization is partially restricted.'))}
          </div>
        </div>

        <!-- 4-Tier Diagnostics Grid -->
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;">Multi-Tier Diagnostics</div>
          
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 6px; font-size: var(--zn-fs-xs);">
            <span>Tier 1: Host CPU Virtualization (VT-x / AMD-V)</span>
            <span style="font-weight: 700; color: ${hasVirt ? '#34d399' : '#f87171'};">${hasVirt ? '✓ Supported' : '✕ Disabled in BIOS'}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 6px; font-size: var(--zn-fs-xs);">
            <span>Tier 2: Host Kernel Module (kvm_intel / kvm_amd)</span>
            <span style="font-weight: 700; color: ${isModuleLoaded ? '#34d399' : '#fbbf24'};">${isModuleLoaded ? '✓ Loaded' : '⚠️ Module Missing'}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 6px; font-size: var(--zn-fs-xs);">
            <span>Tier 3: Device Character Node (/dev/kvm)</span>
            <span style="font-weight: 700; color: ${hasNode ? '#34d399' : '#f87171'};">${hasNode ? '✓ Present on Host' : '✕ Node Missing'}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 6px; font-size: var(--zn-fs-xs);">
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
          <div style="background: var(--zn-shade-30); border: 1px solid var(--zn-line-8); border-radius: 8px; padding: 12px;">
            <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong); margin-bottom: 6px;">How to Fix (Docker / Unraid Container Configuration)</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 8px;">
              Add the physical device mapping so the Linux kernel permits container access:
            </div>
            
            <div style="position: relative; margin-bottom: 8px;">
              <pre style="margin: 0; padding: 8px 12px; background: var(--lt-b-0c121cff, #0c121c); border: 1px solid var(--zn-line-10); border-radius: 4px; font-size: var(--zn-fs-xs); color: var(--zn-text-accent); font-family: monospace;">--device /dev/kvm</pre>
              <button id="btn-copy-kvm-param" class="btn-pill-toggle" style="position: absolute; right: 6px; top: 50%; transform: translateY(-50%); font-size: var(--zn-fs-xs); padding: 2px 8px;">Copy</button>
            </div>

            <div style="font-size: var(--zn-fs-xs); color: var(--muted);">
              <strong>Unraid:</strong> Edit container template → Click 'Advanced View' → Add <code>--device /dev/kvm</code> in <strong>Extra Parameters</strong>.
            </div>
          </div>
        `
            : ''
        }
      </div>

      <div class="smart-modal-footer" style="display: flex; justify-content: flex-end; padding: 12px 20px; border-top: 1px solid var(--zn-line-8); background: var(--zn-shade-20);">
        <button id="kvm-diag-ok" class="btn-pill-toggle">Close</button>
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
        copyParam.textContent = t('ui.copied_2', '✓ Copied');
        showToast(t('toast.copied_device_dev_kvm_to_clipboard', "Copied '--device /dev/kvm' to clipboard"), 'success');
        setTimeout(() => {
          copyParam.textContent = t('catalog.copy', 'Copy');
        }, 2000);
      }
    };
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
}
