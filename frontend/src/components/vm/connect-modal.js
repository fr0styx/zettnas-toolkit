// How to connect to a VM (VNC, SPICE, SSH) and the KVM diagnostics dialog.
// Part of vm-manager.js, split out by ARC-5.

import { api } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';
import { makeDraggable } from '../dock.js';
import { vmState } from './state.js';
import { copyToClipboard, openVmConsole } from './console.js';

const STATE_KEYS = { running: 'vmm.st_running', paused: 'vmm.st_paused', stopped: 'vmm.st_stopped', shutoff: 'vmm.st_stopped' };
const STATE_WORDS = { running: 'Running', paused: 'Paused', stopped: 'Stopped', shutoff: 'Stopped' };

/** A VM's state in words ("running" -> "Running"); an unknown state is shown as it came. */
export function vmStateLabel(state) {
  const s = String(state || '').toLowerCase();
  if (!s) return t('vmm.st_unknown', 'Unknown');
  return STATE_KEYS[s] ? t(STATE_KEYS[s], STATE_WORDS[s]) : s;
}

/** The four KVM checks: label, result in words, icon and colour (ok, warn or crit). */
export function kvmChecks(k) {
  const restricted = !!(k.cgroup_restricted || k.substate === 'container_restricted');
  const virt = !!(k.hardware_virt || k.intel_vtx || k.amd_v);
  const mod = !!k.module_loaded;
  const node = !!k.device_present;
  let access = { tone: 'crit', icon: '✕', text: t('vmc.denied', 'Denied') };
  if (k.device_writable) access = { tone: 'ok', icon: '✓', text: t('vmc.allowed', 'Allowed') };
  else if (restricted) access = { tone: 'warn', icon: '⚠️', text: t('vmc.cgroup', 'Blocked by the container (EPERM)') };
  const pass = (text) => ({ tone: 'ok', icon: '✓', text });
  return [
    { label: t('vmc.t1', '1. The processor supports virtualization (VT-x / AMD-V)'), ...(virt ? pass(t('vmc.supported', 'Supported')) : { tone: 'crit', icon: '✕', text: t('vmc.bios_off', 'Turned off in the BIOS') }) },
    { label: t('vmc.t2', '2. The kernel module is loaded (kvm_intel / kvm_amd)'), ...(mod ? pass(t('vmc.loaded', 'Loaded')) : { tone: 'warn', icon: '⚠️', text: t('vmc.mod_missing', 'Module missing') }) },
    { label: t('vmc.t3', '3. The device /dev/kvm exists'), ...(node ? pass(t('vmc.present', 'Present')) : { tone: 'crit', icon: '✕', text: t('vmc.node_missing', 'Missing') }) },
    { label: t('vmc.t4', '4. The container may use /dev/kvm'), ...access },
  ];
}

// An icon next to translated words: screen readers skip it (UX-35)
const ico = (e) => `<span aria-hidden="true">${e}</span>`;

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
    const name = targetVm.name || t('vmm.appliance', 'Virtual machine');
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
          <span>${escapeHtml(t('vmm.connect_to', 'Connect to {name}', { name }))}</span>
        </div>
        <button id="vm-connect-modal-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 4px;" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding: 18px 22px;">
        <!-- Status summary banner -->
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-8); border-radius: 8px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="qemu-process-badge ${targetVm.state === 'running' ? 'active' : targetVm.state === 'paused' ? 'paused' : 'stopped'}">
              ${ico('●')} ${escapeHtml(vmStateLabel(targetVm.state))}
            </span>
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${escapeHtml(name)}</span>
          </div>
          <span style="font-size: var(--zn-fs-xs); font-family: monospace; color: ${ip ? '#38bdf8' : 'var(--muted)'};">
            ${ip ? `IP: ${escapeHtml(ip)}` : t('vmc.no_ip', 'No network address yet (waiting for DHCP)')}
          </span>
        </div>

        <!-- Option 1: In-Browser Web Console (KVM GUI & Serial TTY) -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🖥️</span>
              <div>
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${t('vmc.web_title', 'Console in the browser')}</div>
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${t('vmc.web_desc', 'The VM’s desktop (VirtIO-GPU) or its serial text terminal')}</div>
              </div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn-console-act btn-connect-gui" style="padding: 4px 10px; font-size: var(--zn-fs-xs); background: #0ea5e9; color: #fff; border-color: #38bdf8;">
                ${t('vmc.launch_gui', 'Open the desktop')}
              </button>
              <button class="btn-console-act btn-connect-tty" style="padding: 4px 10px; font-size: var(--zn-fs-xs); background: rgba(52,211,153,0.15); color: var(--zn-text-ok); border-color: rgba(52,211,153,0.4);">
                ${t('vmc.tty', 'Serial terminal')}
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
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${t('vmc.vnc_title', 'VNC app (RFB)')}</div>
                <div translate="no" style="font-size: var(--zn-fs-xs); color: var(--muted);">TigerVNC, RealVNC, macOS Screen Sharing</div>
              </div>
            </div>
            <button class="btn-console-act btn-connect-copy-vnc" style="padding: 4px 10px; font-size: var(--zn-fs-xs);">
              ${ico('📋')} ${t('vmc.copy_vnc', 'Copy VNC address')}
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--zn-shade-35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: var(--zn-fs-xs); color: var(--zn-text-accent);">
            <span>${vncUri}</span>
            <span style="color: var(--muted); font-size: var(--zn-fs-xs);">${t('vmm.port', 'Port {port}', { port: vncPort })}</span>
          </div>
        </div>

        <!-- Option 3: Secure Shell (SSH) -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🔒</span>
              <div>
                <div translate="no" style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">Secure Shell (SSH)</div>
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${t('vmc.ssh_desc', 'A terminal command for OpenSSH or PuTTY')}</div>
              </div>
            </div>
            <button class="btn-console-act btn-connect-copy-ssh" ${ip ? '' : `disabled title="${escapeHtml(t('vm.why_no_ip', 'Waiting for the VM to get a network address'))}"`} style="padding: 4px 10px; font-size: var(--zn-fs-xs); ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
              ${ico('📋')} ${t('vm.copy_ssh', 'Copy SSH Command')}
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--zn-shade-35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: var(--zn-fs-xs); color: ${ip ? '#34d399' : 'var(--muted)'};">
            <span>${ip ? escapeHtml(sshCmd) : t('vm.why_no_ip', 'Waiting for the VM to get a network address')}</span>
          </div>
        </div>

        <!-- Option 4: Remote Desktop Protocol (RDP) -->
        <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🪟</span>
              <div>
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${t('vm.rdp', 'Remote Desktop (RDP)')}</div>
                <div translate="no" style="font-size: var(--zn-fs-xs); color: var(--muted);">Microsoft Remote Desktop, Remmina, FreeRDP</div>
              </div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn-console-act btn-connect-copy-rdp" ${ip ? '' : `disabled title="${escapeHtml(t('vm.why_no_ip', 'Waiting for the VM to get a network address'))}"`} style="padding: 4px 10px; font-size: var(--zn-fs-xs); ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
                ${ico('📋')} ${t('vmc.copy_rdp', 'Copy RDP address')}
              </button>
              <button class="btn-console-act btn-connect-dl-rdp" ${ip ? '' : `disabled title="${escapeHtml(t('vm.why_no_ip', 'Waiting for the VM to get a network address'))}"`} style="padding: 4px 10px; font-size: var(--zn-fs-xs); ${ip ? '' : 'opacity: 0.5; cursor: not-allowed;'}">
                ${ico('⬇')} ${t('vmc.dl_rdp', '.rdp file')}
              </button>
            </div>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--zn-shade-35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: var(--zn-fs-xs); color: ${ip ? '#eab308' : 'var(--muted)'};">
            <span>${ip ? escapeHtml(rdpUri) : t('vm.why_no_ip', 'Waiting for the VM to get a network address')}</span>
            <span style="color: var(--muted); font-size: var(--zn-fs-xs);">${t('vmm.port', 'Port {port}', { port: 3389 })}</span>
          </div>
        </div>

        <!-- Option 5: Host Storage Shares (VirtIO-FS / 9p) -->
        ${hostShares.length > 0 ? `
          <div style="background: var(--zn-glaze-2); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 12px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
              <span style="font-size: 14px;">📂</span>
              <div>
                <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${t('vmc.mount_title', 'Mount the shared folders (VirtIO-FS / 9p)')}</div>
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${t('vmc.mount_desc', 'Run this inside the VM to reach the folders shared with it')}</div>
              </div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px;">
              ${hostShares.map((s) => `
                <div style="display: flex; justify-content: space-between; align-items: center; background: var(--zn-shade-30); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: var(--zn-fs-xs);">
                  <span translate="no" style="color: var(--zn-text-soft);">sudo mount -t virtiofs ${escapeHtml(s.mount_tag)} /mnt/${escapeHtml(s.mount_tag)}</span>
                  <button class="btn-console-act btn-copy-mount-cmd" data-cmd="sudo mkdir -p /mnt/${escapeHtml(s.mount_tag)} && sudo mount -t virtiofs ${escapeHtml(s.mount_tag)} /mnt/${escapeHtml(s.mount_tag)}" style="padding: 2px 8px; font-size: var(--zn-fs-xs);">${t('catalog.copy', 'Copy')}</button>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}
      </div>

      <div class="smart-modal-footer" style="padding: 12px 22px; display: flex; justify-content: flex-end; border-top: 1px solid var(--zn-line-8); background: var(--zn-shade-20);">
        <button id="vm-connect-close" class="btn-console-act" style="background: var(--zn-glaze-8); color: var(--zn-text-soft); padding: 6px 16px;">
          ${t('diagnostics.close_btn', 'Close')}
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

  modal.innerHTML = `
    <div class="smart-modal-window kvm-diag-window" style="max-width: 580px; width: 92%; max-height: 85vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <span>${t('vmc.kvm_title', 'Virtualization checks (KVM)')}</span>
        </div>
        <button id="kvm-diag-close" class="modal-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px;">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; padding: 18px 22px; display: flex; flex-direction: column; gap: 14px;">
        <!-- Status Banner -->
        <div style="padding: 12px 14px; border-radius: 8px; background: ${k.state === 'active' ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)'}; border: 1px solid ${k.state === 'active' ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.3)'};">
          <div style="font-weight: 700; color: ${k.state === 'active' ? '#34d399' : '#fbbf24'}; font-size: 13px; display: flex; align-items: center; gap: 6px;">
            <span aria-hidden="true">${k.state === 'active' ? '✓' : '⚠️'}</span>
            <span>${escapeHtml(k.badge || t('vmc.kvm_status', 'KVM status'))}</span>
          </div>
          <div style="font-size: var(--zn-fs-xs); color: var(--zn-text-soft); margin-top: 4px; line-height: 1.4;">
            ${escapeHtml(k.remediation || (k.state === 'active' ? t('vmc.kvm_ok', 'Hardware acceleration (KVM) is fully on.') : t('vmc.kvm_partial', 'Virtualization is partly restricted.')))}
          </div>
        </div>

        <!-- 4-Tier Diagnostics Grid -->
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;">${t('vmc.checks', 'Checks')}</div>
          ${kvmChecks(k).map((c) => `
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 6px; font-size: var(--zn-fs-xs);">
            <span>${c.label}</span>
            <span style="font-weight: 700; color: var(--zn-text-${c.tone});">${ico(c.icon)} ${c.text}</span>
          </div>`).join('')}
        </div>

        ${
          isCgroupRestricted
            ? `
          <!-- Container Remediation Fix Snippet -->
          <div style="background: var(--zn-shade-30); border: 1px solid var(--zn-line-8); border-radius: 8px; padding: 12px;">
            <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong); margin-bottom: 6px;">${t('vmc.fix_title', 'How to fix it (Docker or Unraid container settings)')}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 8px;">
              ${t('vmc.fix_desc', 'Pass the device through so the kernel lets the container use it:')}
            </div>
            
            <div style="position: relative; margin-bottom: 8px;">
              <pre style="margin: 0; padding: 8px 12px; background: var(--lt-b-0c121cff, #0c121c); border: 1px solid var(--zn-line-10); border-radius: 4px; font-size: var(--zn-fs-xs); color: var(--zn-text-accent); font-family: monospace;">--device /dev/kvm</pre>
              <button id="btn-copy-kvm-param" class="btn-pill-toggle" style="position: absolute; right: 6px; top: 50%; transform: translateY(-50%); font-size: var(--zn-fs-xs); padding: 2px 8px;">${t('catalog.copy', 'Copy')}</button>
            </div>

            <div style="font-size: var(--zn-fs-xs); color: var(--muted);">
              <strong>Unraid:</strong> ${t('vmc.fix_unraid', 'Edit the container template, turn on Advanced View, and add the flag above under Extra Parameters.')}
            </div>
          </div>
        `
            : ''
        }
      </div>

      <div class="smart-modal-footer" style="display: flex; justify-content: flex-end; padding: 12px 20px; border-top: 1px solid var(--zn-line-8); background: var(--zn-shade-20);">
        <button id="kvm-diag-ok" class="btn-pill-toggle">${t('diagnostics.close_btn', 'Close')}</button>
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
