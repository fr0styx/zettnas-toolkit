import { syncWidgetSettingsUI } from './widgets.js';
import { syncDesktopThemeUI, openDrawer } from './settings.js';
import { openContainerInspector, openContainerDeleteModal } from './container-modal.js';
import { openStackModal, openStackPickerModal } from './stack-modal.js';
import { ZettEventBus } from '../event-bus.js';
import { fetchAndRenderChassisTwin, renderStorageTopologyTree, fetchAndRenderStorageTopology, fetchAndRenderNetworkShares, fetchAndRenderRemoteStorage, openNewCloudRemoteModal, openCreateStoragePoolModal, openCreateNetworkShareModal, openSnapshotsModal, triggerLocateDisk, getThermalLevel } from './chassis-visualizer.js';
/**
 * ZettNAS Toolkit - System Management Window Controller
 * Manages the dedicated System Management desktop window, hub app grid,
 * category navigation, and card views (Wallpaper, Metrics, Events, Security).
 */
import { fetchAndRenderMetrics } from './metrics-chart.js';
import { bringToFront, DockManager, makeDraggable, saveWindowBounds, saveOpenWindowsState, showDockToast } from './dock.js';
import { state } from '../state.js';
import { api } from '../api.js';
import { initNetworkPortsInspector, fetchListeningPorts } from './network-manager.js';
import { showToast, showConfirmToast, showBottomSheet } from '../toast.js';
import { trapFocus, escapeHtml, copyTextToClipboard, reconcileKeyedTable } from '../utils.js';
import { t, getLanguage } from '../i18n.js';
import { collectClientEnvironment, getClientLogs } from '../client-logger.js';
import QRCode from 'qrcode';

let _activeProfile = 'balanced';
let _unbindMgmtTrap = null;

export const SUBPANE_MAP = {
  // --- Pillar 1: Dashboard & Telemetry ---
  'dashboard': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'activity': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'telemetry': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'mgmt-sec-activity': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'mgmt-sec-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'mgmt-pane-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },

  // --- Pillar 2: Storage & Disks ---
  'storage': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-chassis-twin' },
  'mgmt-sec-storage': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-chassis-twin' },
  'mgmt-pane-chassis-twin': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-chassis-twin' },
  'mgmt-pane-chassis': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-sec-pools': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-pane-pools': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'storage-pools': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-pane-storage-topo': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-pane-storage-shares': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-shares' },
  'mgmt-pane-storage-remotes': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-remotes' },
  'mgmt-pane-storage-disks': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-disks' },
  'mgmt-sec-copy': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-copy' },
  'mgmt-pane-copy': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-copy' },
  'mgmt-pane-storage-ingest': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-copy' },
  'mgmt-sec-ingest': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-copy' },
  'mgmt-pane-storage-replication': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-replication' },

  // --- Pillar 3: Containers & Apps ---
  'containers': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'docker': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'apps': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-sec-docker': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-pane-docker': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-sec-catalog': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-pane-docker-compose': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-pane-docker-catalog': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-pane-docker-prune': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },

  // --- Pillar 4: Virtual Machines ---
  'vms': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'vm': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'vm-manager': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'mgmt-sec-vms': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'mgmt-pane-vms-list': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'mgmt-pane-vms-create': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-create' },
  'mgmt-pane-vms-kvm': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-kvm' },

  // --- Pillar 5: Network & Sharing ---
  'network': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'mgmt-sec-network': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'mgmt-pane-network': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'mgmt-pane-network-physical': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'mgmt-pane-network-wireguard': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network-wireguard' },
  'mgmt-pane-network-docker': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network-docker' },
  'mgmt-pane-network-services': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network-services' },
  'mgmt-pane-network-ports': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network-ports' },
  'ports': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network-ports' },

  // --- Pillar 6: Hardware & Profiles ---
  'hardware': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-sec-hardware': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-pane-hardware': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-sec-services': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' }, // Backward compat
  'mgmt-sec-unraid': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-pane-unraid': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-pane-hardware-fans': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-hardware-fans' },
  'mgmt-pane-hardware-led': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-hardware-led' },
  'mgmt-pane-hardware-lcd': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-hardware-lcd' },
  'mgmt-pane-hardware-ups': { section: 'mgmt-sec-ups', pane: null },

  // --- Pillar 7: Power & Battery (Dedicated 1st-Class Section) ---
  'power': { section: 'mgmt-sec-ups', pane: null },
  'mgmt-sec-ups': { section: 'mgmt-sec-ups', pane: null },
  'ups': { section: 'mgmt-sec-ups', pane: null },
  'mgmt-pane-ups': { section: 'mgmt-sec-ups', pane: null },

  // --- Pillar 7: System & Identity ---
  'system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-sec-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' },
  'mgmt-sec-system-group': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-pane-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' },
  'mgmt-sec-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-pane-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-sec-users': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-users' },
  'mgmt-pane-users': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-users' },
  'mgmt-sec-backups': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' },
  'mgmt-pane-backups': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' },
  'mgmt-sec-notifications': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-notifications' },
  'mgmt-pane-notifications': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-notifications' },
  'mgmt-sec-events': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-events' },
  'mgmt-pane-events': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-events' },
  'mgmt-sec-language': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'mgmt-pane-language': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'mgmt-sec-about': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-about' },
  'mgmt-pane-about': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-about' },

  // --- Appearance (Preserving Wallpaper section compatibility) ---
  'appearance': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
  'mgmt-sec-wallpaper': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
  'mgmt-pane-wallpaper': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
  'mgmt-pane-widgets': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-widgets' },
  'mgmt-pane-theme': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' },
  'mgmt-sec-theme': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' },
  'mgmt-pane-glass': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-glass' },
  'mgmt-sec-glass': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-glass' },
  'mgmt-pane-dock': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-dock' },
  'mgmt-sec-dock': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-dock' },
  'mgmt-pane-screensaver': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-screensaver' },
  'mgmt-sec-screensaver': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-screensaver' },
};

export function updateManagementTelemetry(stats) {
  if (!stats) return;
  const overlay = document.getElementById('management-modal-overlay');
  if (overlay && (!overlay.classList.contains('open') || overlay.classList.contains('window-minimized') || overlay.style.display === 'none')) {
    return;
  }
  const unraid = stats.unraid;
  const unraidGrid = document.querySelector('.unraid-details-grid');
  const genericGrid = document.querySelector('.generic-details-grid');
  const hostLabel = document.getElementById('mgmt-host-status-label');

  if (unraid && unraid.available) {
    if (unraidGrid) unraidGrid.style.display = 'grid';
    if (genericGrid) genericGrid.style.display = 'none';
    if (hostLabel) hostLabel.textContent = t('mgmt.unraid_status_label');

    const stateEl = document.getElementById('mgmt-unraid-state');
    const srvEl = document.getElementById('mgmt-unraid-server');
    const verEl = document.getElementById('mgmt-unraid-version');
    const disksEl = document.getElementById('mgmt-unraid-disks');
    const parityEl = document.getElementById('mgmt-unraid-parity');
    const moverEl = document.getElementById('mgmt-unraid-mover');

    if (stateEl) {
      stateEl.textContent = unraid.state;
      stateEl.style.color = unraid.color?.startsWith('green') ? 'var(--ok2)' : 'var(--warn)';
    }
    if (srvEl) {
      const chassisName = stats.chassis_label || stats.motherboard?.board || (stats.chassis ? stats.chassis.toUpperCase() : 'D6U');
      srvEl.textContent = `${unraid.server_name || stats.name || 'NAS'} (${unraid.model || chassisName})`;
    }
    if (verEl) verEl.textContent = `Unraid ${unraid.version || ''}`;
    if (disksEl) {
      const d = unraid.disks || {};
      disksEl.textContent = `${d.total || 0} Disks (${d.disabled || 0} disabled, ${d.invalid || 0} invalid)`;
    }
    if (parityEl) {
      const p = unraid.parity_check || {};
      if (p.active) {
        parityEl.textContent = `Active (${p.action || 'Sync'} ${p.progress_pct || 0}%) • ${p.errors || 0} Errors`;
        parityEl.style.color = 'var(--accent-cyan,#00f0ff)';
      } else {
        parityEl.textContent = `Completed / Idle • ${p.errors || 0} Errors`;
        parityEl.style.color = 'var(--ok2)';
      }
    }
    if (moverEl) {
      const m = unraid.mover || {};
      if (m.active) {
        moverEl.textContent = `Active (${m.remain_files || 0} files left)`;
        moverEl.style.color = 'var(--warn)';
      } else {
        moverEl.textContent = 'Idle';
        moverEl.style.color = 'var(--muted)';
      }
    }
  } else {
    if (unraidGrid) unraidGrid.style.display = 'none';
    if (genericGrid) genericGrid.style.display = 'grid';
    if (hostLabel) hostLabel.textContent = t('mgmt.generic_status_label');

    const osNameEl = document.getElementById('mgmt-generic-os');
    const hostEl = document.getElementById('mgmt-generic-host');
    const uptimeEl = document.getElementById('mgmt-generic-uptime');
    const cpuEl = document.getElementById('mgmt-generic-cpu');
    const loadEl = document.getElementById('mgmt-generic-load');
    const engineEl = document.getElementById('mgmt-generic-engine');

    const distroName = stats.os?.distro || stats.system?.os || stats.system?.distro || 'Linux';
    if (osNameEl) osNameEl.textContent = distroName;
    if (hostEl) hostEl.textContent = stats.system?.hostname || stats.name || 'ZettNAS Host';
    if (uptimeEl) uptimeEl.textContent = stats.system?.uptime_str || stats.os?.uptime || 'Active';
    if (cpuEl) {
      const cpuName = stats.cpu?.model ? stats.cpu.model.replace(/\(R\)|\(TM\)/g, '').trim() : 'x86_64 / ARM64';
      const coresStr = stats.cpu?.cores ? ` (${stats.cpu.cores}T)` : '';
      cpuEl.textContent = `${cpuName}${coresStr}`;
    }
    if (loadEl) {
      if (Array.isArray(stats.cpu?.load_avg)) {
        loadEl.textContent = stats.cpu.load_avg.map(v => Number(v).toFixed(2)).join(', ');
      } else {
        loadEl.textContent = stats.cpu?.load_avg || 'Normal';
      }
    }
    if (engineEl) engineEl.textContent = stats.storage?.engine || 'Btrfs / OpenZFS';
  }

  // Option D: Motherboard & DMI
  const boardEl = document.getElementById('mgmt-board-name');
  const biosEl = document.getElementById('mgmt-bios-ver');
  const govEl = document.getElementById('mgmt-cpu-gov');
  const cpuCoresEl = document.getElementById('mgmt-cpu-cores');

  if (stats.motherboard) {
    if (boardEl) boardEl.textContent = `${stats.motherboard.vendor || ''} ${stats.motherboard.board || 'Standard PC'}`.trim();
    if (biosEl) {
      const bDate = stats.motherboard.bios_date ? ` (${stats.motherboard.bios_date})` : '';
      biosEl.textContent = `${stats.motherboard.bios_version || 'N/A'}${bDate}`;
    }
  }
  if (govEl) govEl.textContent = stats.cpu?.governor || 'performance';
  if (cpuCoresEl) {
    const cores = stats.cpu?.cores || 1;
    cpuCoresEl.textContent = `${cores} Threads / Cores`;
  }

  // Option D: GPU Hardware Transcode Engine
  if (stats.gpu) {
    const gpuBadge = document.getElementById('mgmt-gpu-status-badge');
    const gpuNameEl = document.getElementById('mgmt-gpu-name');
    const gpuDriverEl = document.getElementById('mgmt-gpu-driver');
    const gpuNodeEl = document.getElementById('mgmt-gpu-node');
    const gpuAccelEl = document.getElementById('mgmt-gpu-accel');
    const gpuCodecsEl = document.getElementById('mgmt-gpu-codecs-list');

    if (gpuBadge) {
      if (stats.gpu.ready) {
        gpuBadge.textContent = 'ACCELERATION ACTIVE';
        gpuBadge.style.color = 'var(--ok2)';
        gpuBadge.style.borderColor = 'rgba(37,194,160,0.35)';
      } else {
        gpuBadge.textContent = 'SOFTWARE ONLY';
        gpuBadge.style.color = 'var(--muted)';
        gpuBadge.style.borderColor = 'rgba(255,255,255,0.1)';
      }
    }
    if (gpuNameEl) gpuNameEl.textContent = stats.gpu.model || 'No GPU Detected';
    if (gpuDriverEl) gpuDriverEl.textContent = `Driver: ${stats.gpu.driver || 'none'}`;
    if (gpuNodeEl) {
      gpuNodeEl.textContent = stats.gpu.render_node || 'No render node';
      gpuNodeEl.style.display = stats.gpu.render_node ? 'inline-block' : 'none';
    }
    if (gpuAccelEl) gpuAccelEl.textContent = stats.gpu.acceleration || 'Software CPU Only';
    if (gpuCodecsEl && Array.isArray(stats.gpu.codecs)) {
      if (stats.gpu.codecs.length > 0) {
        gpuCodecsEl.innerHTML = stats.gpu.codecs.map(c => `<span class="gpu-codec-tag">${escapeHtml(c)}</span>`).join('');
      } else {
        gpuCodecsEl.innerHTML = `<span class="gpu-codec-tag" style="color:var(--muted); border-color:rgba(255,255,255,0.1);">CPU Decode Only</span>`;
      }
    }
  }

  // NPU Neural Acceleration Engine
  if (stats.npu) {
    const npuContainer = document.getElementById('mgmt-npu-container');
    const npuBadge = document.getElementById('mgmt-npu-status-badge');
    const npuNameEl = document.getElementById('mgmt-npu-name');
    const npuDriverEl = document.getElementById('mgmt-npu-driver');
    const npuNodeEl = document.getElementById('mgmt-npu-node');
    const npuClockEl = document.getElementById('mgmt-npu-clock');
    const npuAccelEl = document.getElementById('mgmt-npu-accel');
    const npuFrameworksEl = document.getElementById('mgmt-npu-frameworks-list');

    if (npuContainer) {
      npuContainer.style.display = stats.npu.present ? 'block' : 'none';
    }
    if (npuBadge) {
      if (stats.npu.ready) {
        npuBadge.textContent = 'NPU ACTIVE';
        npuBadge.style.color = '#c084fc';
        npuBadge.style.borderColor = 'rgba(168,85,247,0.35)';
      } else {
        npuBadge.textContent = 'NPU OFFLINE';
        npuBadge.style.color = 'var(--muted)';
        npuBadge.style.borderColor = 'rgba(255,255,255,0.1)';
      }
    }
    if (npuNameEl) npuNameEl.textContent = stats.npu.model || 'No NPU Detected';
    if (npuDriverEl) npuDriverEl.textContent = `Driver: ${stats.npu.driver || 'none'}`;
    if (npuNodeEl) {
      npuNodeEl.textContent = stats.npu.render_node || 'No node';
      npuNodeEl.style.display = stats.npu.render_node ? 'inline-block' : 'none';
    }
    if (npuClockEl) {
      const maxF = stats.npu.max_freq_mhz || 0;
      npuClockEl.textContent = maxF > 0 ? `${maxF} MHz` : 'Dynamic Clock';
    }
    if (npuAccelEl) npuAccelEl.textContent = stats.npu.acceleration || 'AI Acceleration Ready';
    if (npuFrameworksEl && Array.isArray(stats.npu.frameworks)) {
      if (stats.npu.frameworks.length > 0) {
        npuFrameworksEl.innerHTML = stats.npu.frameworks
          .map(
            f =>
              `<span class="gpu-codec-tag" style="background:rgba(168,85,247,0.12); color:#c084fc; border-color:rgba(168,85,247,0.25);">${escapeHtml(f)}</span>`
          )
          .join('');
      } else {
        npuFrameworksEl.innerHTML = `<span class="gpu-codec-tag" style="color:var(--muted); border-color:rgba(255,255,255,0.1);">CPU Fallback</span>`;
      }
    }
  }

  // Update Docker pill in Hub and Left Sidebar
  if (stats.docker && Array.isArray(stats.docker)) {
    const runningCount = stats.docker.filter(c => c.state === 'running').length;
    const dockPill = document.getElementById('mgmt-hub-docker-pill');
    if (dockPill) dockPill.textContent = `${runningCount} Active`;
    const sideDockBadge = document.getElementById('mgmt-sidebar-docker-badge');
    if (sideDockBadge) {
      sideDockBadge.textContent = `${runningCount} Active`;
      sideDockBadge.style.display = 'inline-block';
    }
  }

  // Update Storage pill in Hub and Left Sidebar
  if (stats.disks && Array.isArray(stats.disks)) {
    const storagePill = document.getElementById('mgmt-hub-storage-pill');
    if (storagePill) storagePill.textContent = `${stats.disks.length} Drives`;
    const sideStorageBadge = document.getElementById('mgmt-sidebar-storage-badge');
    if (sideStorageBadge) {
      sideStorageBadge.textContent = `${stats.disks.length} Drives`;
      sideStorageBadge.style.display = 'inline-block';
    }

    // Live update Disks Inventory table if currently rendered
    const diskTbody = document.getElementById('mgmt-disks-inventory-tbody');
    if (diskTbody) {
      const existingRows = diskTbody.querySelectorAll('tr[data-dev]');
      if (existingRows.length > 0) {
        stats.disks.forEach((d) => {
          const devName = d.dev || d.name;
          if (!devName) return;
          const row = diskTbody.querySelector(`tr[data-dev="${devName}"]`);
          if (row) {
            const isStandby = Boolean(d.standby || d.health === 'standby');
            const thermal = getThermalLevel(d.temp, isStandby);
            const healthStr = isStandby ? 'STANDBY' : (d.health ? String(d.health).toUpperCase() : 'OK');
            
            const healthTag = row.querySelector('.bay-health-tag');
            if (healthTag) {
              healthTag.className = `bay-health-tag ${thermal.cls}`;
              healthTag.textContent = healthStr;
            }
            const tempPill = row.querySelector('.bay-temp-pill');
            if (tempPill) {
              tempPill.style.color = thermal.color;
              tempPill.style.borderColor = thermal.color;
              tempPill.textContent = thermal.text;
            }
            const sizeTd = row.children[3];
            if (sizeTd && (d.size_formatted || d.size)) {
              sizeTd.textContent = d.size_formatted || d.size;
            }
          }
        });
      }
    }
  }

  // Update Network pill in Hub and Left Sidebar
  if (stats.net || stats.ip || stats.network) {
    let ifaceLabel = 'Online';
    if (stats.network?.interfaces && Array.isArray(stats.network.interfaces)) {
      const activePhys = stats.network.interfaces.filter((i) => {
        const isUp = i.operstate === 'up' || i.carrier === 1;
        const isVirtual = /^(lo|docker\d*|veth|br-|virbr|tailscale|wg\d*)/i.test(i.iface || i.name || '');
        return isUp && !isVirtual;
      });
      if (activePhys.length > 0) {
        ifaceLabel = `${activePhys.length} Active`;
      } else if (stats.net?.iface) {
        ifaceLabel = stats.net.iface.toUpperCase();
      }
    } else if (stats.net?.iface) {
      ifaceLabel = stats.net.iface.toUpperCase();
    }

    const netPill = document.getElementById('mgmt-hub-net-pill');
    if (netPill) netPill.textContent = ifaceLabel;
    const sideNetBadge = document.getElementById('mgmt-sidebar-net-badge');
    if (sideNetBadge) {
      sideNetBadge.textContent = ifaceLabel;
      sideNetBadge.style.display = 'inline-block';
    }
  }

  // Update Virtual Machines pill in Hub and Left Sidebar
  if (stats.vms && Array.isArray(stats.vms)) {
    const runningCount = stats.vms.filter(v => v.state === 'running').length;
    const vmsPill = document.getElementById('mgmt-hub-vms-pill');
    if (vmsPill) vmsPill.textContent = `${runningCount} Running`;
    const sideVmsBadge = document.getElementById('mgmt-sidebar-vms-badge');
    if (sideVmsBadge) {
      sideVmsBadge.textContent = `${stats.vms.length} VMs`;
      sideVmsBadge.style.display = stats.vms.length > 0 ? 'inline-block' : 'none';
    }
  }

  // Update UPS pill, sidebar badge, and telemetry if active
  if (stats.ups) {
    renderUpsTelemetry(stats.ups);
  }

  if (stats.fan_control && stats.fan_control.profile) {
    const prof = stats.fan_control.profile.toLowerCase();
    if (['auto', 'quiet', 'balanced', 'performance'].includes(prof) && prof !== _activeProfile) {
      _activeProfile = prof;
      document.querySelectorAll('.profile-btn').forEach((b) => {
        const isAct = b.dataset.profile === prof;
        b.classList.toggle('active', isAct);
        b.setAttribute('aria-checked', isAct ? 'true' : 'false');
      });
    }
    const currentPill = document.getElementById('unraid-profile-current-pill');
    if (currentPill) {
      currentPill.textContent = `ACTIVE: ${prof === 'auto' ? 'AUTO DYNAMIC' : prof.toUpperCase()}`;
      currentPill.style.color = prof === 'performance' ? 'var(--warn)' : 'var(--ok2)';
    }
  }

  // Peripheral Auto-Hiding (AGENTS.md §1.1)
  const hasLcd = Boolean(stats?.peripherals?.fb_active) || Boolean(stats?.hardware?.has_lcd) || Boolean(stats?.lcd?.page !== undefined);
  const hasLed = Boolean(stats?.peripherals?.led_ready) || Boolean(stats?.hardware?.has_mcu) || Boolean(stats?.peripherals?.led_port);

  const ledTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-hardware-led"]');
  if (ledTab) ledTab.style.display = hasLed ? '' : 'none';

  const lcdTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-hardware-lcd"]');
  if (lcdTab) lcdTab.style.display = hasLcd ? '' : 'none';
}

let _dockerContainersList = [];
let _dockerFilter = 'all';
let _dockerSearchQuery = '';
let _dockerUpdatesCache = null;

let _dockerSortCol = null;
let _dockerSortDir = 'asc';
try {
  const savedCol = localStorage.getItem('zettnas_docker_sort_col');
  const savedDir = localStorage.getItem('zettnas_docker_sort_dir');
  if (savedCol && ['name', 'hardware', 'cpu', 'ports', 'status'].includes(savedCol)) {
    _dockerSortCol = savedCol;
  }
  if (savedDir && ['asc', 'desc'].includes(savedDir)) {
    _dockerSortDir = savedDir;
  }
} catch (e) {}

let _catalogList = [];
let _catalogCat = 'all';
let _catalogSearchQuery = '';
let _catalogSources = [];

export function setDockerSort(col, dir) {
  _dockerSortCol = col;
  if (dir) _dockerSortDir = dir;
  try {
    if (col) {
      localStorage.setItem('zettnas_docker_sort_col', _dockerSortCol);
      localStorage.setItem('zettnas_docker_sort_dir', _dockerSortDir);
    } else {
      localStorage.removeItem('zettnas_docker_sort_col');
      localStorage.removeItem('zettnas_docker_sort_dir');
    }
  } catch (e) {}
  renderDockerContainersTable();
}

export function getDockerSort() {
  return { col: _dockerSortCol, dir: _dockerSortDir };
}

export function getContainerPortSortValue(c) {
  if (!c) return 0;
  if (c.primary_port && Number(c.primary_port) > 0) {
    return Number(c.primary_port);
  }
  if (Array.isArray(c.ports) && c.ports.length > 0) {
    const pubPorts = c.ports
      .map((p) => Number(p.public_port))
      .filter((p) => !isNaN(p) && p > 0);
    if (pubPorts.length > 0) return Math.min(...pubPorts);
  }
  return 0;
}

export function getContainerStatusRank(c) {
  if (!c) return 0;
  const state = (c.state || '').toLowerCase();
  if (state === 'running') return 3;
  if (state === 'restarting') return 2;
  if (state === 'paused') return 1;
  return 0;
}

export function sortDockerContainers(list, col = 'name', dir = 'asc') {
  if (!Array.isArray(list) || list.length <= 1 || !col) return list;

  list.sort((a, b) => {
    switch (col) {
      case 'hardware': {
        const hwA = (a.hardware_badges || []).map((x) => x.label || x.id || '').filter(Boolean).join(' ');
        const hwB = (b.hardware_badges || []).map((x) => x.label || x.id || '').filter(Boolean).join(' ');
        if (hwA && !hwB) return dir === 'desc' ? -1 : 1;
        if (!hwA && hwB) return dir === 'desc' ? 1 : -1;
        if (hwA !== hwB) {
          const cmp = hwA.localeCompare(hwB);
          return dir === 'desc' ? -cmp : cmp;
        }
        return (a.name || '').localeCompare(b.name || '');
      }

      case 'cpu': {
        const cpuA = Number(a.cpu_pct) || 0;
        const cpuB = Number(b.cpu_pct) || 0;
        if (cpuA !== cpuB) {
          return dir === 'desc' ? cpuB - cpuA : cpuA - cpuB;
        }
        const memA = Number(a.mem_used) || 0;
        const memB = Number(b.mem_used) || 0;
        if (memA !== memB) {
          return dir === 'desc' ? memB - memA : memA - memB;
        }
        return (a.name || '').localeCompare(b.name || '');
      }

      case 'ports': {
        const portA = getContainerPortSortValue(a);
        const portB = getContainerPortSortValue(b);
        if (portA > 0 && portB === 0) return -1;
        if (portA === 0 && portB > 0) return 1;
        if (portA !== portB) {
          return dir === 'desc' ? portB - portA : portA - portB;
        }
        return (a.name || '').localeCompare(b.name || '');
      }

      case 'status': {
        const rankA = getContainerStatusRank(a);
        const rankB = getContainerStatusRank(b);
        if (rankA !== rankB) {
          return dir === 'desc' ? rankA - rankB : rankB - rankA;
        }
        const statusCmp = (a.status || '').localeCompare(b.status || '');
        if (statusCmp !== 0) {
          return dir === 'desc' ? -statusCmp : statusCmp;
        }
        return (a.name || '').localeCompare(b.name || '');
      }

      case 'name':
      default: {
        const nameA = (a.name || a.id || '').toLowerCase();
        const nameB = (b.name || b.id || '').toLowerCase();
        const cmp = nameA.localeCompare(nameB);
        if (cmp !== 0) return dir === 'desc' ? -cmp : cmp;
        const stackA = (a.stack || a.managed_by || '').toLowerCase();
        const stackB = (b.stack || b.managed_by || '').toLowerCase();
        const sCmp = stackA.localeCompare(stackB);
        return dir === 'desc' ? -sCmp : sCmp;
      }
    }
  });

  return list;
}

export function updateDockerTableHeaderUI() {
  const containerPane = document.getElementById('mgmt-pane-docker');
  if (!containerPane) return;
  const sortHeaders = containerPane.querySelectorAll('th.sortable-th');
  sortHeaders.forEach((th) => {
    const col = th.dataset.sortCol;
    const indicator = th.querySelector('.docker-sort-indicator');
    if (col === _dockerSortCol) {
      th.classList.add('active-sort');
      th.setAttribute('aria-sort', _dockerSortDir === 'asc' ? 'ascending' : 'descending');
      if (indicator) {
        indicator.textContent = _dockerSortDir === 'asc' ? '▲' : '▼';
        indicator.title = _dockerSortDir === 'asc' ? 'Sorted Ascending' : 'Sorted Descending';
      }
    } else {
      th.classList.remove('active-sort');
      th.setAttribute('aria-sort', 'none');
      if (indicator) {
        indicator.textContent = '';
        indicator.title = '';
      }
    }
  });
}

export function _resetDockerStateForTesting() {
  stopDockerAutoRefresh();
  const containerPane = document.getElementById('mgmt-pane-docker');
  if (containerPane) containerPane._dockerEventsBound = false;
  _dockerContainersList = [];
  _dockerFilter = 'all';
  _dockerSearchQuery = '';
  _dockerUpdatesCache = null;
  _dockerSortCol = null;
  _dockerSortDir = 'asc';
  try {
    localStorage.removeItem('zettnas_docker_sort_col');
    localStorage.removeItem('zettnas_docker_sort_dir');
  } catch (e) {}
}

export function _resetCatalogStateForTesting() {
  _catalogList = [];
  _catalogCat = 'all';
  _catalogSearchQuery = '';
  _catalogSources = [];
}

function _bindDockerEvents() {
  const containerPane = document.getElementById('mgmt-pane-docker');
  if (!containerPane || containerPane._dockerEventsBound) return;

  const launchWinBtn = document.getElementById('btn-mgmt-docker-launch-window');
  if (launchWinBtn) {
    launchWinBtn.addEventListener('click', () => {
      if (typeof window.openContainersManager === 'function') {
        window.openContainersManager();
      } else if (typeof window.openContainersWindow === 'function') {
        window.openContainersWindow();
      }
    });
  }

  const searchInput = document.getElementById('docker-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      _dockerSearchQuery = (e.target.value || '').trim().toLowerCase();
      renderDockerContainersTable();
    });
  }

  const filterBtns = containerPane.querySelectorAll('.docker-filter-btn');
  filterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      filterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _dockerFilter = btn.dataset.filter || 'all';
      renderDockerContainersTable();
    });
  });

  // Toggle between Containers Table and App Catalog
  const btnContainers = document.getElementById('btn-view-docker-containers');
  const btnCatalog = document.getElementById('btn-view-docker-catalog');
  const wrapContainers = document.getElementById('docker-view-containers-wrap');
  const wrapCatalog = document.getElementById('docker-view-catalog-wrap');

  if (btnContainers && btnCatalog) {
    const showContainersView = () => {
      btnContainers.style.display = 'none';
      btnContainers.classList.remove('active');
      btnCatalog.classList.remove('active');
      if (wrapContainers) wrapContainers.style.display = 'block';
      if (wrapCatalog) wrapCatalog.style.display = 'none';
    };

    const showCatalogView = () => {
      btnCatalog.classList.add('active');
      btnContainers.style.display = 'inline-flex';
      btnContainers.textContent = '← Back to Containers';
      btnContainers.classList.remove('active');
      if (wrapContainers) wrapContainers.style.display = 'none';
      if (wrapCatalog) wrapCatalog.style.display = 'block';
      fetchAndRenderAppCatalog();
    };

    btnContainers.addEventListener('click', showContainersView);
    btnCatalog.addEventListener('click', () => {
      if (wrapCatalog && wrapCatalog.style.display === 'block') {
        showContainersView();
      } else {
        showCatalogView();
      }
    });
  }

  // Catalog category filter pills
  const catFilterBtns = containerPane.querySelectorAll('.catalog-filter-btn');
  catFilterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      catFilterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _catalogCat = btn.dataset.cat || 'all';
      renderAppCatalogGrid();
    });
  });

  // Catalog search input
  const catSearchInput = document.getElementById('catalog-search-input');
  if (catSearchInput) {
    catSearchInput.addEventListener('input', (e) => {
      _catalogSearchQuery = (e.target.value || '').trim().toLowerCase();
      renderAppCatalogGrid();
    });
  }

  // Prune button
  const btnPrune = document.getElementById('btn-docker-prune');
  if (btnPrune) {
    btnPrune.addEventListener('click', () => {
      openDockerPruneModal();
    });
  }

  // Sources button
  const btnSources = document.getElementById('btn-manage-app-sources');
  if (btnSources) {
    btnSources.addEventListener('click', () => {
      openAppSourcesModal();
    });
  }

  // Sideload button
  const btnSideload = document.getElementById('btn-sideload-app-package');
  if (btnSideload) {
    btnSideload.addEventListener('click', () => {
      openSideloadAppModal();
    });
  }

  // Check for updates button
  const btnCheckUpdates = document.getElementById('btn-docker-check-updates');
  if (btnCheckUpdates) {
    btnCheckUpdates.addEventListener('click', async () => {
      btnCheckUpdates.disabled = true;
      const originalHtml = btnCheckUpdates.innerHTML;
      btnCheckUpdates.innerHTML = '<span>⏳</span> <span>Checking updates...</span>';
      try {
        const res = await api.post('/api/docker/updates/check');
        _dockerUpdatesCache = res;
        const count = res.updates_available_count || 0;
        updateDockerUpdatesToolbarUI(count);
        if (count > 0) {
          showToast(`Update check complete: ${count} container update${count > 1 ? 's' : ''} available!`, 'warn');
        } else {
          showToast('All containers are up to date!', 'success');
        }
        await fetchAndRenderDockerContainers(false);
      } catch (err) {
        showToast(`Update check failed: ${err.message}`, 'error');
      } finally {
        btnCheckUpdates.disabled = false;
        btnCheckUpdates.innerHTML = originalHtml;
      }
    });
  }

  // Update all button
  const btnUpdateAll = document.getElementById('btn-docker-update-all');
  if (btnUpdateAll) {
    btnUpdateAll.addEventListener('click', () => {
      const count = _dockerUpdatesCache?.updates_available_count || 0;
      showConfirmToast(
        'Update All Containers',
        `Update all <strong>${count} containers</strong> with available image updates?<br><br><span style="font-size:11.5px; color:var(--muted);">Each container will be repulled and recreated with automated rollback protection if startup fails.</span>`,
        async () => {
          btnUpdateAll.disabled = true;
          btnUpdateAll.innerHTML = '<span>⏳</span> <span>Updating all...</span>';
          showToast(`Starting batch update for ${count} containers...`, 'info');
          try {
            const res = await api.post('/api/docker/updates/apply-all');
            const updatedCount = res.total_updated || (res.updated || []).length;
            showToast(`Batch update complete: ${updatedCount} updated, ${(res.failed || []).length} failed.`, updatedCount > 0 ? 'success' : 'warn');
            await refreshDockerUpdatesStatus();
            await fetchAndRenderDockerContainers();
          } catch (err) {
            showToast(`Batch update failed: ${err.message}`, 'error');
          } finally {
            btnUpdateAll.disabled = false;
            updateDockerUpdatesToolbarUI();
          }
        },
        null,
        {
          okText: '⬆️ Update All Now',
          cancelText: 'Cancel',
          isUpdate: true,
        }
      );
    });
  }

  // Manage Stacks button
  const btnStacksMenu = document.getElementById('btn-docker-stacks-menu');
  if (btnStacksMenu) {
    btnStacksMenu.addEventListener('click', async () => {
      try {
        const stacks = await api.get('/api/docker/stacks');
        if (!stacks || !stacks.length) {
          showToast('No active Compose stacks found.', 'info');
          return;
        }
        openStackPickerModal(stacks);
      } catch (err) {
        showToast(`Failed loading stacks: ${err.message}`, 'error');
      }
    });
  }

  // Sortable column headers
  const sortHeaders = containerPane.querySelectorAll('th.sortable-th');
  sortHeaders.forEach((th) => {
    const col = th.dataset.sortCol;
    if (!col) return;

    const handleSort = () => {
      if (_dockerSortCol === col) {
        _dockerSortDir = _dockerSortDir === 'asc' ? 'desc' : 'asc';
      } else {
        _dockerSortCol = col;
        _dockerSortDir = (col === 'cpu' || col === 'hardware') ? 'desc' : 'asc';
      }
      try {
        localStorage.setItem('zettnas_docker_sort_col', _dockerSortCol);
        localStorage.setItem('zettnas_docker_sort_dir', _dockerSortDir);
      } catch (e) {}
      renderDockerContainersTable();
    };

    th.addEventListener('click', handleSort);
    th.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleSort();
      }
    });
  });

  ZettEventBus.on('docker:containers-updated', () => {
    fetchAndRenderDockerContainers();
  });

  ZettEventBus.on('docker:containers:refresh', () => {
    fetchAndRenderDockerContainers();
    refreshDockerUpdatesStatus();
  });

  containerPane._dockerEventsBound = true;
}

export async function refreshDockerUpdatesStatus() {
  try {
    const res = await api.get('/api/docker/updates/status');
    _dockerUpdatesCache = res;
    updateDockerUpdatesToolbarUI(res.updates_available_count || 0);
    renderDockerContainersTable();
  } catch (e) {}
}

export function updateDockerUpdatesToolbarUI(count) {
  const btnUpdateAll = document.getElementById('btn-docker-update-all');
  const badge = document.getElementById('docker-updates-count-badge');
  const filterUpd = document.getElementById('btn-docker-filter-updates');
  const cUpd = document.getElementById('docker-count-updates');
  if (badge) badge.textContent = count;
  if (cUpd) cUpd.textContent = count;
  if (filterUpd) {
    filterUpd.style.display = count > 0 ? 'inline-flex' : 'none';
  }
  if (btnUpdateAll) {
    btnUpdateAll.style.display = count > 0 ? 'inline-flex' : 'none';
  }
}

export function renderDockerContainersTable() {
  const tbody = document.getElementById('docker-containers-tbody');
  if (!tbody) return;

  // Compute counts
  const totalCount = _dockerContainersList.length;
  const runningCount = _dockerContainersList.filter((c) => c.state === 'running').length;
  const stoppedCount = _dockerContainersList.filter((c) => c.state !== 'running').length;
  const composeCount = _dockerContainersList.filter((c) => c.managed_by === 'compose' || Boolean(c.stack)).length;
  const standaloneCount = _dockerContainersList.filter((c) => c.managed_by !== 'compose' && !c.stack).length;
  const updatesCount = _dockerContainersList.filter((c) => {
    const info = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
    return Boolean(info?.has_update);
  }).length;

  const cAll = document.getElementById('docker-count-all');
  if (cAll) cAll.textContent = totalCount;
  const cRun = document.getElementById('docker-count-running');
  if (cRun) cRun.textContent = runningCount;
  const cStop = document.getElementById('docker-count-stopped');
  if (cStop) cStop.textContent = stoppedCount;
  const cUpd = document.getElementById('docker-count-updates');
  if (cUpd) cUpd.textContent = updatesCount;
  const filterUpd = document.getElementById('btn-docker-filter-updates');
  if (filterUpd) filterUpd.style.display = updatesCount > 0 ? 'inline-flex' : 'none';
  const cComp = document.getElementById('docker-count-compose');
  if (cComp) cComp.textContent = composeCount;
  const cStand = document.getElementById('docker-count-standalone');
  if (cStand) cStand.textContent = standaloneCount;

  const pill = document.getElementById('mgmt-hub-docker-pill');
  if (pill) pill.textContent = `${runningCount} Active`;
  const sideBadge = document.getElementById('mgmt-sidebar-docker-badge');
  if (sideBadge) {
    sideBadge.textContent = `${runningCount} Active`;
    sideBadge.style.display = 'inline-block';
  }

  if (totalCount === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:20px;">${t('mgmt.docker_none', 'No Docker containers detected or socket not connected.')}</td></tr>`;
    return;
  }

  // Filter list
  const filtered = _dockerContainersList.filter((c) => {
    // Check tab filter
    if (_dockerFilter === 'running' && c.state !== 'running') return false;
    if (_dockerFilter === 'stopped' && c.state === 'running') return false;
    if (_dockerFilter === 'updates') {
      const updateInfo = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
      if (!updateInfo?.has_update) return false;
    }
    if (_dockerFilter === 'compose' && c.managed_by !== 'compose' && !c.stack) return false;
    if (_dockerFilter === 'standalone' && (c.managed_by === 'compose' || Boolean(c.stack))) return false;

    // Check search query
    if (_dockerSearchQuery) {
      const q = _dockerSearchQuery;
      const matchName = (c.name || '').toLowerCase().includes(q);
      const matchImage = (c.image || '').toLowerCase().includes(q);
      const matchStack = (c.stack || '').toLowerCase().includes(q);
      const matchService = (c.service || '').toLowerCase().includes(q);
      const matchPort = (c.ports || []).some(
        (p) => String(p.public_port).includes(q) || String(p.private_port).includes(q)
      );
      if (!matchName && !matchImage && !matchStack && !matchService && !matchPort) {
        return false;
      }
    }
    return true;
  });

  // Sort list if sort column active
  if (_dockerSortCol) {
    sortDockerContainers(filtered, _dockerSortCol, _dockerSortDir);
  }
  updateDockerTableHeaderUI();

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:20px;">${t('mgmt.docker_no_matching', 'No containers match your search or filter.')}</td></tr>`;
    return;
  }

  const currentHost = typeof window !== 'undefined' && window.location.hostname ? window.location.hostname : 'localhost';

  if (tbody.firstElementChild && tbody.firstElementChild.querySelector('td[colspan]')) {
    tbody.innerHTML = '';
  }

  bindDockerTableEvents(tbody);

  reconcileKeyedTable(
    tbody,
    filtered,
    (c) => c.id || c.name,
    (c) => createContainerRow(c, currentHost),
    (tr, c) => updateContainerRow(tr, c, currentHost)
  );
}

function buildContainerRowInner(c, currentHost) {
  const isRunning = c.state === 'running';
  const badgeColor = isRunning ? 'var(--ok2)' : 'var(--muted)';
  const badgeBg = isRunning ? 'rgba(37, 194, 160, 0.15)' : 'rgba(255, 255, 255, 0.05)';
  const idShort = c.id ? c.id.slice(0, 12) : '';

  // Column 1: Stack & Name
  let stackHtml = '';
  if (c.stack) {
    stackHtml = `<span class="docker-stack-pill clickable-stack-pill" data-stack="${escapeHtml(c.stack)}" title="Open & Edit Stack: ${escapeHtml(c.stack)}" style="cursor:pointer;">📁 ${escapeHtml(c.stack)}</span>`;
  } else {
    const originLabel = c.managed_by === 'unraid' ? 'Unraid' : 'Standalone';
    stackHtml = `<span class="docker-origin-pill">${originLabel}</span>`;
  }

  // Column 2: Hardware Badges
  let hwHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
  if (c.hardware_badges && c.hardware_badges.length > 0) {
    hwHtml = c.hardware_badges
      .map(
        (b) =>
          `<span class="docker-hw-badge docker-hw-${escapeHtml(b.id)}" title="${escapeHtml(b.label)}">${escapeHtml(b.label)}</span>`
      )
      .join('');
  }

  // Column 3: Telemetry (CPU / RAM)
  let telemHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
  if (isRunning) {
    const cpuStr = `${(c.cpu_pct || 0).toFixed(1)}%`;
    const memStr = c.mem_used ? `${(c.mem_used / (1024 * 1024)).toFixed(0)} MB` : '--';
    telemHtml = `<span class="docker-telemetry-pill"><span class="telem-cpu">${cpuStr}</span><span style="opacity:0.4;">•</span><span class="telem-mem">${memStr}</span></span>`;
  }

  // Column 4: Ports & Web UI
  let portsHtml = '<span style="color:var(--muted); font-size:10px;">—</span>';
  const portParts = [];
  if (c.webui_url && c.primary_port) {
    const resolvedUrl = c.webui_url.replace('[HOST]', currentHost);
    if (/^https?:\/\//i.test(resolvedUrl)) {
      portParts.push(
        `<a href="${escapeHtml(resolvedUrl)}" target="_blank" rel="noopener noreferrer" class="btn-webui-badge" title="Open Web UI (Port ${escapeHtml(String(c.primary_port))})">🌐 :${escapeHtml(String(c.primary_port))} ↗</a>`
      );
    }
  }
  // Additional public ports
  const otherPorts = (c.ports || []).filter(
    (p) => p.public_port && p.public_port !== c.primary_port
  );
  if (otherPorts.length > 0) {
    const otherTags = otherPorts
      .slice(0, 3)
      .map((p) => `<span class="docker-port-tag">:${p.public_port}</span>`)
      .join('');
    portParts.push(otherTags);
  }
  if (portParts.length > 0) {
    portsHtml = portParts.join(' ');
  }

  // Column 5: Status & Uptime
  const statusHtml = `
    <div style="display:flex; align-items:center; gap:6px;">
      <span class="docker-state-badge" style="display:inline-block; padding:2px 6px; border-radius:4px; font-size:9.5px; font-weight:700; background:${badgeBg}; color:${badgeColor}; text-transform:uppercase;">${escapeHtml(c.state)}</span>
      <span class="docker-status-text" style="font-size:10px; color:#cbd5e1; max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
    </div>
  `;

  // Column 6: Actions
  const updateInfo = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
  const hasUpdate = Boolean(updateInfo?.has_update);
  const updateBadge = hasUpdate
    ? `<button class="ci-badge badge-update-ready btn-container-act btn-docker-update-badge" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="update-single" title="Click to update ${escapeHtml(c.name)} to latest image">⬆️ UPDATE</button>`
    : '';

  const inspectBtn = `<button class="btn-container-act btn-docker-inspect" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="inspect" title="Inspect ${escapeHtml(c.name)}">🔍</button>`;
  const editBtn = `<button class="btn-container-act btn-docker-edit" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="edit" title="Edit ${escapeHtml(c.name)}">✏️</button>`;
  const stackBtn = c.stack
    ? `<button class="btn-container-act btn-docker-stack" data-action="stack" data-stack="${escapeHtml(c.stack)}" title="Open & Edit Stack: ${escapeHtml(c.stack)}">📁</button>`
    : '';
  const updateBtn = hasUpdate
    ? `<button class="btn-container-act btn-docker-update-single" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="update-single" title="Update ${escapeHtml(c.name)} to latest image">⬆️</button>`
    : '';
  const backupBtn = `<button class="btn-container-act btn-docker-backup" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="backup" title="Backup App Data & Config">💾</button>`;
  const deleteBtn = `<button class="btn-container-act btn-docker-delete" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-image="${escapeHtml(c.image || '')}" data-action="delete" title="Destroy / Delete ${escapeHtml(c.name)}">🗑️</button>`;
  const moreBtn = `<button class="btn-container-act btn-docker-more-sheet" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="more-sheet" title="More Actions">···</button>`;
  const actions = isRunning
    ? `
      ${inspectBtn}
      ${editBtn}
      ${stackBtn}
      ${updateBtn}
      ${backupBtn}
      <button class="btn-container-act btn-docker-restart" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="restart" title="Restart ${escapeHtml(c.name)}">🔄</button>
      <button class="btn-container-act btn-docker-stop" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="stop" title="Stop ${escapeHtml(c.name)}">⏹</button>
      ${deleteBtn}
      ${moreBtn}
    `
    : `
      ${inspectBtn}
      ${editBtn}
      ${stackBtn}
      ${updateBtn}
      ${backupBtn}
      <button class="btn-container-act btn-docker-start" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="start" title="Start ${escapeHtml(c.name)}">▶</button>
      ${deleteBtn}
      ${moreBtn}
    `;

  return `
    <td>
      <div style="display:flex; align-items:baseline; gap:6px;">
        <button class="btn-docker-name-link" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" style="background:none; border:none; padding:0; color:#fff; font-size:11.5px; font-weight:700; cursor:pointer; text-align:left; font-family:inherit;" title="Inspect ${escapeHtml(c.name)}">${escapeHtml(c.name)}</button>
        <code style="font-size:9px; color:var(--muted); font-family:var(--font-mono, monospace);">${escapeHtml(idShort)}</code>
        ${updateBadge}
      </div>
      <div>${stackHtml}</div>
    </td>
    <td>${hwHtml}</td>
    <td class="docker-telemetry-cell">${telemHtml}</td>
    <td>${portsHtml}</td>
    <td class="docker-status-cell">${statusHtml}</td>
    <td class="docker-actions-cell" style="text-align:right; white-space:nowrap;">${actions}</td>
  `;
}

function createContainerRow(c, currentHost) {
  const tr = document.createElement('tr');
  const key = c.id || c.name || '';
  tr.dataset.key = key;
  tr.dataset.id = c.id || '';
  tr.dataset.name = c.name || '';
  tr.dataset.state = c.state || '';
  const updateInfo = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
  tr.dataset.hasUpdate = updateInfo?.has_update ? '1' : '0';
  tr.innerHTML = buildContainerRowInner(c, currentHost);
  return tr;
}

function updateContainerRow(tr, c, currentHost) {
  const updateInfo = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
  const hasUpdate = Boolean(updateInfo?.has_update);
  const prevHasUpdate = tr.dataset.hasUpdate === '1';

  tr.dataset.id = c.id || '';
  tr.dataset.name = c.name || '';

  if (tr.dataset.state !== c.state || prevHasUpdate !== hasUpdate || !tr.children.length) {
    tr.dataset.state = c.state || '';
    tr.dataset.hasUpdate = hasUpdate ? '1' : '0';
    tr.innerHTML = buildContainerRowInner(c, currentHost);
    return;
  }

  const isRunning = c.state === 'running';
  const telemCell = tr.querySelector('.docker-telemetry-cell');
  if (telemCell) {
    if (isRunning) {
      const cpuStr = `${(c.cpu_pct || 0).toFixed(1)}%`;
      const memStr = c.mem_used ? `${(c.mem_used / (1024 * 1024)).toFixed(0)} MB` : '--';
      const cpuEl = telemCell.querySelector('.telem-cpu');
      const memEl = telemCell.querySelector('.telem-mem');
      if (cpuEl && memEl) {
        cpuEl.textContent = cpuStr;
        memEl.textContent = memStr;
      } else {
        telemCell.innerHTML = `<span class="docker-telemetry-pill"><span class="telem-cpu">${cpuStr}</span><span style="opacity:0.4;">•</span><span class="telem-mem">${memStr}</span></span>`;
      }
    } else {
      telemCell.innerHTML = '<span style="color:var(--muted); font-size:10px;">—</span>';
    }
  }

  const statusText = tr.querySelector('.docker-status-text');
  if (statusText && statusText.textContent !== c.status) {
    statusText.textContent = c.status;
    statusText.title = c.status;
  }
}

function bindDockerTableEvents(tbody) {
  if (tbody._dockerTableEventsBound) return;
  tbody._dockerTableEventsBound = true;

  tbody.addEventListener('click', async (e) => {
    const stackPill = e.target.closest('.clickable-stack-pill, .open-stack-btn');
    if (stackPill) {
      e.stopPropagation();
      const stackName = stackPill.dataset.stack;
      if (stackName) {
        openStackModal(stackName);
        return;
      }
    }

    const actBtn = e.target.closest('.btn-container-act');
    if (actBtn) {
      e.stopPropagation();
      const cid = actBtn.dataset.id;
      const cname = actBtn.dataset.name;
      const act = actBtn.dataset.action;

      if (act === 'stack') {
        const stackName = actBtn.dataset.stack;
        if (stackName) openStackModal(stackName);
        return;
      }

      if (!cid || !act) return;

      if (act === 'more-sheet') {
        const c = _dockerContainersList.find((item) => (item.id === cid || item.name === cname));
        if (!c) return;
        const updateInfo = _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id];
        const hasUpdate = Boolean(updateInfo?.has_update);

        const items = [
          {
            icon: '🔍',
            label: t('docker.inspect', 'Inspect & Overview'),
            onClick: () => openContainerInspector(cid, cname, 'overview'),
          },
          {
            icon: '📋',
            label: t('docker.logs', 'View Container Logs'),
            onClick: () => openContainerInspector(cid, cname, 'logs'),
          },
          {
            icon: '📟',
            label: t('docker.terminal', 'Web Terminal Console'),
            onClick: () => openContainerInspector(cid, cname, 'terminal'),
          },
          {
            icon: '✏️',
            label: t('docker.edit', 'Edit Configuration'),
            onClick: () => openContainerInspector(cid, cname, 'edit'),
          },
        ];

        if (c.stack) {
          items.push({
            icon: '📁',
            label: `Manage Stack: ${c.stack}`,
            onClick: () => openStackModal(c.stack),
          });
        }

        if (hasUpdate) {
          items.push({
            icon: '⬆️',
            label: 'Update to Latest Image',
            onClick: () => {
              actBtn.parentElement.querySelector('[data-action="update-single"]')?.click();
            },
          });
        }

        items.push({
          icon: '💾',
          label: 'Backup App Data & Config',
          onClick: () => {
            actBtn.parentElement.querySelector('[data-action="backup"]')?.click();
          },
        });

        items.push({
          icon: '🗑️',
          label: `Delete "${cname}"`,
          destructive: true,
          onClick: () => {
            openContainerDeleteModal(cid, cname, c.image || '', () => {
              fetchAndRenderDockerContainers();
            });
          },
        });

        showBottomSheet({
          title: cname,
          subtitle: `State: ${(c.state || '').toUpperCase()} • ${c.image || 'Docker Container'}`,
          items,
        });
        return;
      }

      if (act === 'inspect') {
        openContainerInspector(cid, cname);
        return;
      }

      if (act === 'edit') {
        openContainerInspector(cid, cname, 'edit');
        return;
      }

      if (act === 'update-single') {
        showConfirmToast(
          `Update Container "${cname}"`,
          `Pull the latest image and update <strong>${escapeHtml(cname)}</strong> to its newest release?<br><br><span style="font-size:11.5px; color:var(--muted);">All volumes, persistent paths, and environment settings will be preserved intact.</span>`,
          async () => {
            actBtn.disabled = true;
            const originalContent = actBtn.innerHTML;
            actBtn.innerHTML = '⏳';
            showToast(`Updating "${cname}" to latest image...`, 'info');
            try {
              await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/update-image`);
              showToast(`Container "${cname}" updated and restarted successfully!`, 'success');
              await refreshDockerUpdatesStatus();
              await fetchAndRenderDockerContainers();
            } catch (err) {
              showToast(`Update failed: ${err.message}`, 'error');
              actBtn.disabled = false;
              actBtn.innerHTML = originalContent;
            }
          },
          null,
          {
            okText: '⬆️ Update Now',
            cancelText: 'Cancel',
            isUpdate: true,
          }
        );
        return;
      }

      if (act === 'backup') {
        actBtn.disabled = true;
        const originalContent = actBtn.innerHTML;
        actBtn.innerHTML = '⏳';
        showToast(`Creating backup for ${cname}...`, 'info');
        try {
          const res = await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/backup`);
          const archiveName = res?.backup?.archive_file || 'archive.tar.gz';
          const sizeStr = res?.backup?.archive_size_formatted || '';
          showToast(`App "${cname}" backed up successfully (${archiveName}${sizeStr ? ' - ' + sizeStr : ''})!`, 'success');
        } catch (err) {
          showToast(`Backup failed: ${err.message}`, 'error');
        } finally {
          actBtn.disabled = false;
          actBtn.innerHTML = originalContent;
        }
        return;
      }

      if (act === 'delete') {
        openContainerDeleteModal(cid, cname, actBtn.dataset.image || '', () => {
          fetchAndRenderDockerContainers();
        });
        return;
      }

      actBtn.disabled = true;
      actBtn.style.opacity = '0.5';
      showToast(`${act.toUpperCase()} request sent for ${cname}...`, 'info');

      try {
        await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: act });
        showToast(`Container "${cname}" successfully ${act}ed.`, 'success');
        await fetchAndRenderDockerContainers();
      } catch (err) {
        showToast(`Failed to ${act} container: ${err.message}`, 'error');
        actBtn.disabled = false;
        actBtn.style.opacity = '1';
      }
      return;
    }

    const nameLink = e.target.closest('.btn-docker-name-link');
    if (nameLink) {
      e.stopPropagation();
      const cid = nameLink.dataset.id;
      const cname = nameLink.dataset.name;
      if (cid) openContainerInspector(cid, cname);
    }
  });
}

let _dockerAutoRefreshTimer = null;
let _isDockerAutoRefreshing = false;
let _dockerAutoRefreshCount = 0;

export function startDockerAutoRefresh() {
  if (_dockerAutoRefreshTimer) return;
  _dockerAutoRefreshTimer = setInterval(async () => {
    if (typeof document !== 'undefined' && document.hidden) return;
    const mgmtWin = document.getElementById('management-window');
    if (mgmtWin && (mgmtWin.style.display === 'none' || mgmtWin.classList.contains('minimized') || mgmtWin.classList.contains('window-minimized'))) {
      return;
    }
    const dockerSec = document.getElementById('mgmt-sec-docker');
    if (!dockerSec) return;
    if (dockerSec.style.display === 'none') return;
    const style = typeof window !== 'undefined' && window.getComputedStyle ? window.getComputedStyle(dockerSec) : null;
    if (style && style.display === 'none') return;

    if (_isDockerAutoRefreshing) return;
    _isDockerAutoRefreshing = true;
    try {
      _dockerAutoRefreshCount++;
      if (_dockerAutoRefreshCount % 6 === 0) {
        refreshDockerUpdatesStatus().catch(() => {});
      }
      await fetchAndRenderDockerContainers(true);
    } catch (e) {
      console.warn('Docker background auto-refresh poll error:', e);
    } finally {
      _isDockerAutoRefreshing = false;
    }
  }, 5000);
}

export function stopDockerAutoRefresh() {
  if (_dockerAutoRefreshTimer) {
    clearInterval(_dockerAutoRefreshTimer);
    _dockerAutoRefreshTimer = null;
  }
}

export async function fetchAndRenderDockerContainers(isBackground = false) {
  _bindDockerEvents();
  const tbody = document.getElementById('docker-containers-tbody');
  const cwTbody = document.getElementById('cw-docker-containers-tbody');
  if (!tbody && !cwTbody) return;
  try {
    const [list] = await Promise.all([
      api.get('/api/docker/containers'),
      (!isBackground || !_dockerUpdatesCache) ? refreshDockerUpdatesStatus().catch(() => {}) : Promise.resolve(),
    ]);
    _dockerContainersList = Array.isArray(list) ? list : [];
    if (tbody) renderDockerContainersTable();
    if (typeof window.renderContainersWindowTable === 'function') {
      window.renderContainersWindowTable(_dockerContainersList);
    }
  } catch (err) {
    if (!isBackground || _dockerContainersList.length === 0) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
      if (cwTbody) cwTbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
    } else {
      console.warn('Silent docker refresh error:', err);
    }
  }
}

export async function fetchCatalogSources() {
  try {
    const sources = await api.get('/api/docker/catalog/sources');
    _catalogSources = Array.isArray(sources) ? sources : [];
    updateCatalogSourcesBadge();
    return _catalogSources;
  } catch (err) {
    console.error('Failed to fetch catalog sources:', err);
    return [];
  }
}

export function updateCatalogSourcesBadge() {
  const badge = document.getElementById('catalog-sources-count-badge');
  if (badge) {
    const enabledCount = _catalogSources.filter((s) => s.enabled !== false).length;
    badge.textContent = enabledCount || _catalogSources.length || '1';
  }
}

export async function fetchAndRenderAppCatalog() {
  _bindDockerEvents();
  const grid = document.getElementById('docker-catalog-grid');
  if (!grid) return;
  try {
    const [list, sources] = await Promise.all([
      api.get('/api/docker/catalog'),
      api.get('/api/docker/catalog/sources').catch(() => []),
    ]);
    _catalogList = Array.isArray(list) ? list : [];
    _catalogSources = Array.isArray(sources) ? sources : [];

    const totalBadge = document.getElementById('catalog-total-badge');
    if (totalBadge) totalBadge.textContent = _catalogList.length;
    const allCount = document.getElementById('catalog-all-count');
    if (allCount) allCount.textContent = _catalogList.length;
    updateCatalogSourcesBadge();

    renderAppCatalogGrid();
  } catch (err) {
    grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; color:var(--crit); padding:20px;">Failed to load catalog: ${escapeHtml(err.message)}</div>`;
  }
}

export function renderAppCatalogGrid() {
  const grid = document.getElementById('docker-catalog-grid');
  if (!grid) return;

  const filtered = _catalogList.filter((app) => {
    if (_catalogCat !== 'all' && app.category !== _catalogCat) return false;
    if (_catalogSearchQuery) {
      const q = _catalogSearchQuery;
      const matchName = (app.name || '').toLowerCase().includes(q);
      const matchDesc = (app.description || '').toLowerCase().includes(q);
      const matchId = (app.id || '').toLowerCase().includes(q);
      const matchImg = (app.image || '').toLowerCase().includes(q);
      const matchSrc = (app.source_name || '').toLowerCase().includes(q);
      if (!matchName && !matchDesc && !matchId && !matchImg && !matchSrc) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--muted); padding:30px;">No applications match your search.</div>';
    return;
  }

  const categoryIcons = {
    media: '🎬',
    photos: '📸',
    cloud: '☁️',
    automation: '⚡',
    utilities: '🛠️',
    downloads: '📥',
    other: '📦',
  };

  grid.innerHTML = filtered.map((app) => {
    const icon = categoryIcons[app.category] || '📦';
    const logoHtml = app.logo
      ? `<img src="${escapeHtml(app.logo)}" alt="${escapeHtml(app.name)}" style="width:24px; height:24px; object-fit:contain; border-radius:4px; vertical-align:middle; flex-shrink:0;" onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='inline';" /><span style="font-size:20px; line-height:1; display:none;">${icon}</span>`
      : `<span style="font-size:20px; line-height:1;">${icon}</span>`;

    const sourceBadge = app.source_name && app.source_name !== 'Built-in'
      ? `<span class="ci-badge" style="font-size:8.5px; background:rgba(14,165,233,0.15); color:#38bdf8; border:1px solid rgba(14,165,233,0.3); padding:1px 5px; border-radius:3px;">${escapeHtml(app.source_name)}</span>`
      : `<span class="ci-badge" style="font-size:8.5px; background:rgba(37,194,160,0.15); color:var(--accent, #25c2a0); border:1px solid rgba(37,194,160,0.3); padding:1px 5px; border-radius:3px;">Built-in</span>`;

    const typeBadge = app.type === 'stack'
      ? `<span class="ci-badge" style="font-size:8.5px; background:rgba(168,85,247,0.15); color:#c084fc; border:1px solid rgba(168,85,247,0.3); padding:1px 5px; border-radius:3px;">Stack</span>`
      : '';

    let securityBadge = '';
    if (app.security_rating === 'verified') {
      securityBadge = `<span class="ci-badge" title="Verified Safe Sandbox" style="font-size:8.5px; background:rgba(34,197,94,0.15); color:#4ade80; border:1px solid rgba(34,197,94,0.3); padding:1px 5px; border-radius:3px;">🛡️ Safe</span>`;
    } else if (app.security_rating === 'review_required') {
      securityBadge = `<span class="ci-badge" title="${escapeHtml((app.security_flags || []).join('; '))}" style="font-size:8.5px; background:rgba(234,179,8,0.15); color:#facc15; border:1px solid rgba(234,179,8,0.3); padding:1px 5px; border-radius:3px;">⚠️ Review</span>`;
    } else if (app.security_rating === 'elevated') {
      securityBadge = `<span class="ci-badge" title="${escapeHtml((app.security_flags || []).join('; '))}" style="font-size:8.5px; background:rgba(239,68,68,0.15); color:#f87171; border:1px solid rgba(239,68,68,0.3); padding:1px 5px; border-radius:3px;">🚨 Elevated</span>`;
    }

    const imageDisplay = app.image || (app.repository ? 'compose-stack' : 'container');

    return `
      <div class="catalog-app-card" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px; display:flex; flex-direction:column; justify-content:space-between; gap:10px; transition:border-color 0.2s, background 0.2s;">
        <div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:6px; margin-bottom:6px;">
            <div style="display:flex; align-items:center; gap:8px; overflow:hidden;">
              ${logoHtml}
              <div style="overflow:hidden;">
                <div style="font-size:12.5px; font-weight:700; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(app.name)}</div>
                <code style="font-size:9.5px; color:var(--muted); font-family:var(--font-mono, monospace); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:block;">${escapeHtml(imageDisplay)}</code>
              </div>
            </div>
            <div style="display:flex; gap:4px; align-items:center; flex-shrink:0;">
              ${typeBadge}
              ${sourceBadge}
              ${securityBadge}
              <span class="ci-badge" style="font-size:9px; text-transform:uppercase; background:rgba(255,255,255,0.06); color:#cbd5e1; padding:2px 6px; border-radius:4px;">${escapeHtml(app.category)}</span>
            </div>
          </div>
          <p style="font-size:11px; color:#94a3b8; line-height:1.4; margin:0 0 6px 0; min-height:32px;">${escapeHtml(app.description)}</p>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid rgba(255,255,255,0.06); padding-top:8px;">
          <span style="font-size:10.5px; font-family:var(--font-mono, monospace); color:var(--accent-cyan, #00f0ff); background:rgba(0,240,255,0.08); padding:2px 6px; border-radius:4px;">Port :${app.default_port}</span>
          <button class="btn-pill-toggle btn-deploy-app" data-appid="${escapeHtml(app.id)}" style="background:var(--brand, #0ea5e9); color:#fff; border:none; padding:3px 10px; font-weight:700; font-size:11px;">Deploy / Stack</button>
        </div>
      </div>
    `;
  }).join('');

  grid.querySelectorAll('.btn-deploy-app').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      openAppDeployModal(btn.dataset.appid);
    });
  });
}

export async function openAppDeployModal(appId) {
  let modal = document.getElementById('app-deploy-modal-overlay');
  if (!modal) {
    const modalHtml = `
      <div id="app-deploy-modal-overlay" class="smart-modal-backdrop" style="display:none;">
        <div id="app-deploy-modal-window" class="smart-modal-window app-deploy-window" style="width:620px; max-width:94vw; max-height:88vh; display:flex; flex-direction:column; position:relative;">
          <div class="smart-modal-header" id="adm-header" style="cursor:move; user-select:none; display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span id="adm-icon" style="font-size:18px;">📦</span>
              <span id="adm-title" style="font-weight:700; color:#fff; font-size:13px;">Deploy Application Stack</span>
            </div>
            <div class="os-window-controls" style="display:flex; gap:6px; align-items:center;">
              <button class="win-btn min-btn" id="adm-min-btn" title="Minimize to Dock" aria-label="Minimize"></button>
              <button class="win-btn close-btn" id="adm-close-btn" title="Close" aria-label="Close"></button>
            </div>
          </div>

          <!-- View 1: Configuration View -->
          <div id="adm-view-config" style="flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:12px;">
            <div id="adm-conflict-banner" style="padding:10px 12px; border-radius:6px; font-size:11px; line-height:1.4;"></div>
            
            <!-- Pre-existing Container Action Choice Box -->
            <div id="adm-existing-box" style="display:none; padding:11px 13px; border-radius:6px; background:rgba(245, 166, 35, 0.09); border:1px solid rgba(245, 166, 35, 0.35); flex-direction:column; gap:8px;">
              <div style="display:flex; align-items:center; justify-content:space-between;">
                <div style="display:flex; align-items:center; gap:6px; color:var(--warn, #f5a623); font-weight:700; font-size:11.5px;">
                  <span>⚠️</span> <span id="adm-existing-title">Pre-existing Container Detected</span>
                </div>
                <span id="adm-existing-status-badge" style="font-size:9.5px; padding:2px 7px; border-radius:4px; background:rgba(255,255,255,0.08); font-family:var(--font-mono, monospace); font-weight:700;">Running</span>
              </div>
              <div id="adm-existing-desc" style="color:#cbd5e1; font-size:11px; line-height:1.4;">
                A container with this name or port already exists on your system. Choose an action:
              </div>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:4px;">
                <button type="button" id="adm-choice-replace-btn" class="btn-pill-toggle" style="justify-content:center; text-align:center; padding:7px 10px; font-size:11px; border:1px solid rgba(235, 87, 87, 0.4); background:rgba(235, 87, 87, 0.12); color:#ff8080; font-weight:700; cursor:pointer;">
                  🔄 Stop &amp; Replace Existing
                </button>
                <button type="button" id="adm-choice-new-btn" class="btn-pill-toggle" style="justify-content:center; text-align:center; padding:7px 10px; font-size:11px; border:2px solid var(--ok2, #25c2a0); background:rgba(37, 194, 160, 0.18); color:var(--ok2, #25c2a0); font-weight:700; cursor:pointer;">
                  ➕ Deploy Alongside (New)
                </button>
              </div>
            </div>

            <div style="display:grid; grid-template-columns:1.2fr 1fr; gap:10px;">
              <div>
                <label style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:4px;">CONTAINER NAME</label>
                <input type="text" id="adm-name-input" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px; font-family:var(--font-mono, monospace);">
              </div>
              <div>
                <label style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:4px;">HOST PORT MAPPING</label>
                <input type="number" id="adm-port-input" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px; font-family:var(--font-mono, monospace);">
              </div>
            </div>
            <div>
              <label style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:4px;">STORAGE ROOT DIRECTORY</label>
              <input type="text" id="adm-storage-input" value="/mnt/user/appdata" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px;">
            </div>
            <div>
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:10.5px; font-weight:700; color:var(--muted);">DOCKER COMPOSE DEFINITION</span>
                <div style="display:flex; gap:6px;">
                  <button class="btn-pill-toggle" id="adm-copy-btn">📋 Copy YAML</button>
                  <button class="btn-pill-toggle" id="adm-download-btn">⬇️ Download</button>
                </div>
              </div>
              <pre id="adm-compose-pre" style="margin:0; background:#080c14; border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:10px; max-height:200px; overflow:auto; font-family:var(--font-mono, monospace); font-size:10.5px; color:#e2e8f0; line-height:1.45;"></pre>
            </div>
          </div>

          <!-- View 2: Live Deployment Progress View -->
          <div id="adm-view-progress" style="display:none; flex:1; overflow-y:auto; padding:18px 16px; flex-direction:column; gap:12px;">
            <div style="display:flex; align-items:center; justify-content:space-between;">
              <div style="display:flex; align-items:center; gap:10px;">
                <span id="adm-progress-spinner" style="font-size:22px; display:inline-block;">⚙️</span>
                <div>
                  <div id="adm-progress-title" style="font-size:13px; font-weight:700; color:#fff;">Deploying Application...</div>
                  <div id="adm-progress-status-text" style="font-size:11px; color:var(--muted); margin-top:2px;">Preparing environment and directories...</div>
                </div>
              </div>
              <div id="adm-progress-pct-badge" style="font-size:13px; font-weight:800; font-family:var(--font-mono, monospace); color:var(--accent-cyan, #00f0ff); background:rgba(0,240,255,0.08); padding:3px 9px; border-radius:6px; border:1px solid rgba(0,240,255,0.2);">0%</div>
            </div>

            <!-- Stylized Progress Bar -->
            <div style="width:100%; height:10px; background:rgba(255,255,255,0.06); border-radius:5px; overflow:hidden; border:1px solid rgba(255,255,255,0.1); position:relative;">
              <div id="adm-progress-bar-fill" style="height:100%; width:0%; background:linear-gradient(90deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); transition:width 0.25s ease; box-shadow:0 0 10px rgba(37,194,160,0.5);"></div>
            </div>

            <!-- Real-time Activity Log Terminal -->
            <div style="margin-top:2px;">
              <div style="font-size:9.5px; font-weight:700; color:var(--muted); margin-bottom:4px; text-transform:uppercase; letter-spacing:0.5px;">Deployment Console Log</div>
              <div id="adm-deploy-logs" style="background:#05080f; border:1px solid rgba(255,255,255,0.1); border-radius:6px; height:160px; overflow-y:auto; padding:10px; font-family:var(--font-mono, monospace); font-size:10.5px; line-height:1.5; color:#cbd5e1;">
                <div style="color:var(--muted);">Waiting for deployment stream to begin...</div>
              </div>
            </div>

            <!-- Success Callout -->
            <div id="adm-success-box" style="display:none; padding:12px 14px; background:rgba(37,194,160,0.12); border:1px solid var(--ok2, #25c2a0); border-radius:6px; align-items:center; justify-content:space-between; gap:12px;">
              <div>
                <div style="font-weight:700; color:var(--ok2, #25c2a0); font-size:12px;">🚀 Container is Live & Running!</div>
                <div id="adm-success-msg" style="font-size:11px; color:#cbd5e1; margin-top:2px;">Your application has been deployed and started successfully.</div>
              </div>
              <a id="adm-webui-launch-btn" href="#" target="_blank" rel="noopener noreferrer" class="btn-pill-toggle" style="background:var(--ok2, #25c2a0); color:#000; font-weight:700; font-size:11px; padding:6px 14px; text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
                🌐 Open Web UI ↗
              </a>
            </div>
          </div>

          <!-- Footer for Config View -->
          <div id="adm-footer-config" style="padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="adm-cancel-btn">Cancel</button>
            <button class="btn-pill-toggle" id="adm-deploy-confirm-btn" style="background:linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); color:#fff; border:none; padding:6px 16px; font-weight:700; cursor:pointer;">
              🚀 Deploy & Launch Container
            </button>
          </div>

          <!-- Footer for Progress View -->
          <div id="adm-footer-progress" style="display:none; padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="adm-back-to-config-btn" style="display:none;">← Reconfigure</button>
            <div style="flex:1;"></div>
            <button class="btn-pill-toggle" id="adm-progress-close-btn" style="display:none; background:var(--ok2, #25c2a0); color:#fff; border:none; padding:6px 16px; font-weight:700;">✓ Done</button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    modal = document.getElementById('app-deploy-modal-overlay');

    const win = document.getElementById('app-deploy-modal-window');
    const header = document.getElementById('adm-header');
    if (win && header) {
      makeDraggable(win, header, 'app-deploy');
    }
    if (win) {
      win.addEventListener('pointerdown', () => {
        bringToFront(win);
      }, { capture: true });
    }

    const minBtn = document.getElementById('adm-min-btn');
    if (minBtn) {
      minBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (DockManager) {
          DockManager.minimize('app-deploy');
        } else {
          modal.classList.add('window-minimized');
          modal.style.display = 'none';
        }
      });
    }

    document.getElementById('adm-close-btn').addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (modal._isDeploying) {
        if (DockManager) {
          DockManager.minimize('app-deploy');
        } else {
          modal.classList.add('window-minimized');
          modal.style.display = 'none';
        }
        showToast(`Deploying ${modal._activeAppId || 'app'} in background. Click Dock icon to restore.`, 'info');
      } else {
        if (modal._close) modal._close();
      }
    });

    document.getElementById('adm-cancel-btn').addEventListener('click', (e) => {
      e.preventDefault();
      if (modal._close) modal._close();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open') && !modal.classList.contains('window-minimized')) {
        if (modal._isDeploying) {
          if (DockManager) DockManager.minimize('app-deploy');
          else modal.classList.add('window-minimized');
          showToast(`Deploying in background. Reopen from Dock anytime.`, 'info');
        } else if (modal._close) {
          modal._close();
        }
      }
    });
  }

  modal._close = () => {
    modal._isDeploying = false;
    modal.classList.remove('open', 'window-minimized');
    modal.style.display = 'none';
    if (DockManager) {
      DockManager.unregister('app-deploy');
    }
    const vc = document.getElementById('adm-view-config');
    const vp = document.getElementById('adm-view-progress');
    const fc = document.getElementById('adm-footer-config');
    const fp = document.getElementById('adm-footer-progress');
    if (vc) vc.style.display = 'flex';
    if (vp) vp.style.display = 'none';
    if (fc) fc.style.display = 'flex';
    if (fp) fp.style.display = 'none';
  };

  // Ensure config view is visible by default and open modal
  modal._activeAppId = appId;
  modal._isDeploying = false;
  modal.classList.remove('window-minimized');
  modal.classList.add('open');
  modal.style.display = 'flex';

  const win = document.getElementById('app-deploy-modal-window');
  if (win) {
    win.classList.remove('window-minimized');
    win.style.removeProperty('display');
    bringToFront(win);
  }

  // Register in DockManager
  if (DockManager) {
    if (!DockManager.windows['app-deploy']) {
      DockManager.register('app-deploy', modal, '#i-chip', `Deploy: ${appId.toUpperCase()}`, false);
    } else {
      DockManager.windows['app-deploy'].title = `Deploy: ${appId.toUpperCase()}`;
      DockManager.restore('app-deploy');
    }
  }

  modal.style.display = 'flex';

  const viewConfig = document.getElementById('adm-view-config');
  const viewProgress = document.getElementById('adm-view-progress');
  const footerConfig = document.getElementById('adm-footer-config');
  const footerProgress = document.getElementById('adm-footer-progress');
  if (viewConfig) viewConfig.style.display = 'flex';
  if (viewProgress) viewProgress.style.display = 'none';
  if (footerConfig) footerConfig.style.display = 'flex';
  if (footerProgress) footerProgress.style.display = 'none';

  let replaceExisting = false;
  let defaultContainerName = appId;
  let suggestedContainerName = appId;
  let defaultPort = 8080;
  let suggestedPort = 8080;
  let existingContainerInfo = null;

  const deployConfirmBtn = document.getElementById('adm-deploy-confirm-btn');
  const banner = document.getElementById('adm-conflict-banner');
  const existingBox = document.getElementById('adm-existing-box');
  const existingBadge = document.getElementById('adm-existing-status-badge');
  const existingDesc = document.getElementById('adm-existing-desc');
  const choiceReplaceBtn = document.getElementById('adm-choice-replace-btn');
  const choiceNewBtn = document.getElementById('adm-choice-new-btn');
  const nameInput = document.getElementById('adm-name-input');
  const portInput = document.getElementById('adm-port-input');
  const storageInput = document.getElementById('adm-storage-input');
  const composePre = document.getElementById('adm-compose-pre');
  const title = document.getElementById('adm-title');

  if (existingBox) existingBox.style.display = 'none';
  if (choiceReplaceBtn) {
    choiceReplaceBtn.style.border = '1px solid rgba(235, 87, 87, 0.4)';
    choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.12)';
    choiceReplaceBtn.style.opacity = '0.75';
    choiceReplaceBtn.style.boxShadow = 'none';
  }
  if (choiceNewBtn) {
    choiceNewBtn.style.border = '2px solid var(--ok2, #25c2a0)';
    choiceNewBtn.style.background = 'rgba(37, 194, 160, 0.18)';
    choiceNewBtn.style.opacity = '1';
    choiceNewBtn.style.boxShadow = '0 0 8px rgba(37,194,160,0.3)';
  }

  if (nameInput) {
    nameInput.value = appId;
    nameInput.style.borderColor = '';
  }
  if (portInput) {
    portInput.value = 8080;
    portInput.style.borderColor = '';
  }

  if (deployConfirmBtn) {
    deployConfirmBtn.disabled = false;
    deployConfirmBtn.style.opacity = '1';
    deployConfirmBtn.style.pointerEvents = 'auto';
    deployConfirmBtn.textContent = '🚀 Deploy & Launch Container';
    deployConfirmBtn.style.background = 'linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0))';
  }

  title.textContent = `Deploy ${appId.toUpperCase()}`;
  banner.innerHTML = '<span style="color:var(--muted);">Probing host ports and container state...</span>';
  banner.style.background = 'rgba(255,255,255,0.04)';
  banner.style.border = '1px solid rgba(255,255,255,0.08)';

  try {
    const resolveData = await api.get(`/api/docker/catalog/${appId}/resolve`);
    defaultPort = resolveData.default_port || 8080;
    suggestedPort = resolveData.suggested_port || defaultPort;
    existingContainerInfo = resolveData.existing_container;
    suggestedContainerName = resolveData.suggested_container_name || appId;
    defaultContainerName = (existingContainerInfo && existingContainerInfo.name) ? existingContainerInfo.name : appId;

    if (existingContainerInfo) {
      if (existingBox) existingBox.style.display = 'flex';
      const isRunning = existingContainerInfo.state === 'running';
      if (existingBadge) {
        existingBadge.textContent = isRunning ? 'RUNNING' : (existingContainerInfo.state || 'EXISTING').toUpperCase();
        existingBadge.style.color = isRunning ? 'var(--ok2, #25c2a0)' : 'var(--muted)';
        existingBadge.style.background = isRunning ? 'rgba(37,194,160,0.15)' : 'rgba(255,255,255,0.08)';
      }
      if (existingDesc) {
        existingDesc.innerHTML = `Found existing container <strong>${existingContainerInfo.name}</strong> (${existingContainerInfo.state || 'present'}). Would you like to stop and replace it, or deploy alongside as a new instance?`;
      }

      // Default to Deploy Alongside
      replaceExisting = false;
      if (nameInput) nameInput.value = suggestedContainerName;
      if (portInput) portInput.value = suggestedPort;

      if (resolveData.conflict_detected) {
        banner.style.background = 'rgba(245, 166, 35, 0.12)';
        banner.style.border = '1px solid var(--warn, #f5a623)';
        const occupier = resolveData.in_use_by ? ` (in use by ${resolveData.in_use_by})` : '';
        banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict Detected:</span> Default port ${defaultPort} is busy${occupier}. Automatically remapped to free port <strong>${suggestedPort}</strong>!`;
      } else {
        banner.style.background = 'rgba(37, 194, 160, 0.12)';
        banner.style.border = '1px solid var(--ok2, #25c2a0)';
        banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ Deploy Alongside:</span> Suggested new container name <strong>${suggestedContainerName}</strong> on available port <strong>${suggestedPort}</strong>.`;
      }
      if (deployConfirmBtn) deployConfirmBtn.textContent = '🚀 Deploy New Instance';
    } else if (resolveData.conflict_detected) {
      if (nameInput) nameInput.value = appId;
      if (portInput) portInput.value = suggestedPort;
      banner.style.background = 'rgba(245, 166, 35, 0.12)';
      banner.style.border = '1px solid var(--warn, #f5a623)';
      const occupier = resolveData.in_use_by ? ` (in use by ${resolveData.in_use_by})` : '';
      banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict Detected:</span> Default port ${defaultPort} is busy${occupier}. Automatically remapped to free port <strong>${suggestedPort}</strong>!`;
    } else {
      if (nameInput) nameInput.value = appId;
      if (portInput) portInput.value = suggestedPort;
      banner.style.background = 'rgba(37, 194, 160, 0.12)';
      banner.style.border = '1px solid var(--ok2, #25c2a0)';
      banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ Ready to Deploy:</span> Port ${suggestedPort} and name <strong>${appId}</strong> are free.`;
    }
  } catch (e) {
    if (nameInput) nameInput.value = appId;
    if (portInput) portInput.value = 8080;
    banner.innerHTML = '<span style="color:var(--muted);">Port status: Default assigned</span>';
  }

  function selectReplaceMode() {
    replaceExisting = true;
    if (nameInput) {
      nameInput.value = defaultContainerName;
      nameInput.style.borderColor = '';
    }
    if (portInput) {
      portInput.value = defaultPort;
      portInput.style.borderColor = '';
    }

    if (choiceReplaceBtn) {
      choiceReplaceBtn.style.border = '2px solid var(--err, #eb5757)';
      choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.22)';
      choiceReplaceBtn.style.opacity = '1';
      choiceReplaceBtn.style.boxShadow = '0 0 8px rgba(235,87,87,0.4)';
    }
    if (choiceNewBtn) {
      choiceNewBtn.style.border = '1px solid rgba(37, 194, 160, 0.4)';
      choiceNewBtn.style.background = 'rgba(37, 194, 160, 0.1)';
      choiceNewBtn.style.opacity = '0.75';
      choiceNewBtn.style.boxShadow = 'none';
    }

    banner.style.background = 'rgba(235, 87, 87, 0.12)';
    banner.style.border = '1px solid var(--err, #eb5757)';
    banner.innerHTML = `<span style="color:#ff8080; font-weight:bold;">⚠️ Stop &amp; Replace Mode:</span> The existing container <strong>${defaultContainerName}</strong> will be cleanly stopped and replaced on port <strong>${defaultPort}</strong>. Persistent data will be preserved.`;

    if (deployConfirmBtn) {
      deployConfirmBtn.textContent = '🔄 Stop, Replace & Launch';
      deployConfirmBtn.style.background = 'linear-gradient(135deg, #e65100, var(--err, #eb5757))';
      deployConfirmBtn.disabled = false;
      deployConfirmBtn.style.opacity = '1';
      deployConfirmBtn.style.pointerEvents = 'auto';
    }

    updateComposePreview();
  }

  function selectNewInstanceMode() {
    replaceExisting = false;
    if (nameInput) {
      nameInput.value = suggestedContainerName;
      nameInput.style.borderColor = '';
    }
    if (portInput) {
      portInput.value = suggestedPort;
      portInput.style.borderColor = '';
    }

    if (choiceNewBtn) {
      choiceNewBtn.style.border = '2px solid var(--ok2, #25c2a0)';
      choiceNewBtn.style.background = 'rgba(37, 194, 160, 0.18)';
      choiceNewBtn.style.opacity = '1';
      choiceNewBtn.style.boxShadow = '0 0 8px rgba(37,194,160,0.3)';
    }
    if (choiceReplaceBtn) {
      choiceReplaceBtn.style.border = '1px solid rgba(235, 87, 87, 0.4)';
      choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.12)';
      choiceReplaceBtn.style.opacity = '0.75';
      choiceReplaceBtn.style.boxShadow = 'none';
    }

    banner.style.background = 'rgba(37, 194, 160, 0.12)';
    banner.style.border = '1px solid var(--ok2, #25c2a0)';
    banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ New Instance Mode:</span> Configuring container <strong>${suggestedContainerName}</strong> on free port <strong>${suggestedPort}</strong> alongside existing instance.`;

    if (deployConfirmBtn) {
      deployConfirmBtn.textContent = '🚀 Deploy New Instance';
      deployConfirmBtn.style.background = 'linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0))';
      deployConfirmBtn.disabled = false;
      deployConfirmBtn.style.opacity = '1';
      deployConfirmBtn.style.pointerEvents = 'auto';
    }

    updateComposePreview();
  }

  if (choiceReplaceBtn) choiceReplaceBtn.onclick = selectReplaceMode;
  if (choiceNewBtn) choiceNewBtn.onclick = selectNewInstanceMode;

  let nameValidationTimer = null;
  async function validateEnteredName() {
    const rawName = nameInput ? nameInput.value.trim() : '';
    if (!rawName) {
      banner.style.background = 'rgba(235, 87, 87, 0.12)';
      banner.style.border = '1px solid var(--err, #eb5757)';
      if (nameInput) nameInput.style.borderColor = 'var(--err, #eb5757)';
      banner.innerHTML = `<span style="color:var(--err, #eb5757); font-weight:bold;">✕ Invalid Name:</span> Container name cannot be empty.`;
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = true;
        deployConfirmBtn.style.opacity = '0.5';
        deployConfirmBtn.style.pointerEvents = 'none';
      }
      return;
    }

    try {
      const check = await api.get(`/api/docker/check_container_name?name=${encodeURIComponent(rawName)}`);
      if (check && check.exists) {
        if (replaceExisting && check.name === defaultContainerName) {
          if (nameInput) nameInput.style.borderColor = '';
          banner.style.background = 'rgba(235, 87, 87, 0.12)';
          banner.style.border = '1px solid var(--err, #eb5757)';
          banner.innerHTML = `<span style="color:#ff8080; font-weight:bold;">⚠️ Stop &amp; Replace Mode:</span> Existing container <strong>${check.name}</strong> will be stopped and replaced.`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = false;
            deployConfirmBtn.style.opacity = '1';
            deployConfirmBtn.style.pointerEvents = 'auto';
          }
        } else {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          if (nameInput) nameInput.style.borderColor = 'var(--warn, #f5a623)';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Container Name In Use:</span> A container named <strong>${check.name}</strong> already exists. Please choose a different name or select 'Stop &amp; Replace'.`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = true;
            deployConfirmBtn.style.opacity = '0.5';
            deployConfirmBtn.style.pointerEvents = 'none';
          }
        }
      } else {
        if (nameInput) nameInput.style.borderColor = '';
        validateEnteredPort();
      }
    } catch (e) {
      if (nameInput) nameInput.style.borderColor = '';
    }
  }

  let portValidationTimer = null;
  async function validateEnteredPort() {
    const val = parseInt(portInput.value, 10);
    if (!val || val < 1 || val > 65535) {
      banner.style.background = 'rgba(235, 87, 87, 0.12)';
      banner.style.border = '1px solid var(--err, #eb5757)';
      portInput.style.borderColor = 'var(--err, #eb5757)';
      banner.innerHTML = `<span style="color:var(--err, #eb5757); font-weight:bold;">✕ Invalid Port:</span> Please enter a valid port between 1 and 65535.`;
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = true;
        deployConfirmBtn.style.opacity = '0.5';
        deployConfirmBtn.style.pointerEvents = 'none';
      }
      return;
    }

    try {
      const check = await api.get(`/api/docker/check_port?port=${val}&proto=tcp`);
      if (check && check.available === false) {
        const cName = nameInput ? nameInput.value.trim() : appId;
        const isOccupiedByTarget = replaceExisting && check.in_use_by && (
          check.in_use_by === `container '${cName}'` ||
          check.in_use_by.includes(cName)
        );

        if (isOccupiedByTarget) {
          banner.style.background = 'rgba(235, 87, 87, 0.12)';
          banner.style.border = '1px solid var(--err, #eb5757)';
          portInput.style.borderColor = '';
          banner.innerHTML = `<span style="color:#ff8080; font-weight:bold;">⚠️ Stop &amp; Replace Mode:</span> Port ${val} is currently bound by <strong>${cName}</strong>, which will be stopped and replaced.`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = false;
            deployConfirmBtn.style.opacity = '1';
            deployConfirmBtn.style.pointerEvents = 'auto';
          }
          return;
        }

        banner.style.background = 'rgba(245, 166, 35, 0.15)';
        banner.style.border = '1px solid var(--warn, #f5a623)';
        portInput.style.borderColor = 'var(--warn, #f5a623)';
        const inUse = check.in_use_by ? ` (in use by ${check.in_use_by})` : '';
        banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict:</span> Port ${val} is already busy${inUse}. Please choose an available port before deploying.`;
        if (deployConfirmBtn) {
          deployConfirmBtn.disabled = true;
          deployConfirmBtn.style.opacity = '0.5';
          deployConfirmBtn.style.pointerEvents = 'none';
        }
      } else {
        banner.style.background = 'rgba(37, 194, 160, 0.12)';
        banner.style.border = '1px solid var(--ok2, #25c2a0)';
        portInput.style.borderColor = '';
        const cName = nameInput ? nameInput.value.trim() : appId;
        banner.innerHTML = `<span style="color:var(--ok2, #25c2a0); font-weight:bold;">✓ Ready to Deploy:</span> Port ${val} is free and ready for container <strong>${cName}</strong>.`;
        if (deployConfirmBtn) {
          deployConfirmBtn.disabled = false;
          deployConfirmBtn.style.opacity = '1';
          deployConfirmBtn.style.pointerEvents = 'auto';
        }
      }
    } catch (err) {
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = false;
        deployConfirmBtn.style.opacity = '1';
        deployConfirmBtn.style.pointerEvents = 'auto';
      }
    }
  }

  async function updateComposePreview() {
    const p = parseInt(portInput.value, 10) || suggestedPort;
    const s = storageInput.value.trim() || '/mnt/user/appdata';
    const cName = nameInput ? nameInput.value.trim() : appId;
    try {
      const comp = await api.post(`/api/docker/catalog/${appId}/compose`, {
        host_port: p,
        storage_root: s,
        container_name: cName,
      });
      composePre.textContent = comp.compose_yaml;
    } catch (err) {
      composePre.textContent = `# Failed to generate compose: ${err.message}`;
    }
  }

  if (nameInput) {
    nameInput.oninput = () => {
      updateComposePreview();
      clearTimeout(nameValidationTimer);
      nameValidationTimer = setTimeout(validateEnteredName, 250);
    };
  }

  portInput.oninput = () => {
    updateComposePreview();
    clearTimeout(portValidationTimer);
    portValidationTimer = setTimeout(validateEnteredPort, 250);
  };
  storageInput.oninput = updateComposePreview;
  await updateComposePreview();

  document.getElementById('adm-copy-btn').onclick = () => {
    copyTextToClipboard(composePre.textContent).then((ok) => {
      if (ok) {
        showToast('Docker Compose YAML copied to clipboard!', 'success');
      } else {
        showToast('Failed to copy to clipboard', 'warn');
      }
    });
  };

  document.getElementById('adm-download-btn').onclick = () => {
    const blob = new Blob([composePre.textContent], { type: 'text/yaml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${appId}-compose.yml`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Downloaded ${appId}-compose.yml`, 'info');
  };

  // Deployment execution with live progress bar and streaming console
  const progressFill = document.getElementById('adm-progress-bar-fill');
  const progressPct = document.getElementById('adm-progress-pct-badge');
  const progressStatus = document.getElementById('adm-progress-status-text');
  const progressTitle = document.getElementById('adm-progress-title');
  const progressSpinner = document.getElementById('adm-progress-spinner');
  const deployLogs = document.getElementById('adm-deploy-logs');
  const successBox = document.getElementById('adm-success-box');
  const webuiBtn = document.getElementById('adm-webui-launch-btn');
  const closeProgressBtn = document.getElementById('adm-progress-close-btn');
  const backConfigBtn = document.getElementById('adm-back-to-config-btn');
  const closeBtn = document.getElementById('adm-close-btn');

  function logDeployLine(msg, type = 'info') {
    if (!deployLogs) return;
    const now = new Date().toTimeString().split(' ')[0];
    const color = type === 'error' ? 'var(--crit, #ff6b6b)' : type === 'success' ? 'var(--ok2, #25c2a0)' : '#cbd5e1';
    const line = document.createElement('div');
    line.style.color = color;
    line.textContent = `[${now}] ${msg}`;
    deployLogs.appendChild(line);
    deployLogs.scrollTop = deployLogs.scrollHeight;
  }

  function handleDeployEvent(data) {
    if (!data) return;

    if (data.percent != null && data.step !== 'error') {
      if (progressFill) progressFill.style.width = `${data.percent}%`;
      if (progressPct) progressPct.textContent = `${data.percent}%`;
      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `${appId.toUpperCase()} (${data.percent}%)`;
        DockManager.render();
      }
    }
    if (data.message) {
      if (progressStatus) progressStatus.textContent = data.message;
      logDeployLine(data.message, data.step === 'error' ? 'error' : data.step === 'success' ? 'success' : 'info');
    }

    if (data.step === 'success') {
      if (progressFill) progressFill.style.width = '100%';
      if (progressPct) {
        progressPct.textContent = '100%';
        progressPct.style.color = 'var(--ok2, #25c2a0)';
      }
      if (progressTitle) progressTitle.textContent = `✓ ${appId.toUpperCase()} Deployed!`;
      if (progressSpinner) {
        progressSpinner.textContent = '✅';
        progressSpinner.style.animation = 'none';
      }

      if (successBox) successBox.style.display = 'flex';
      const webUrl = data.webui_url ? data.webui_url.replace('[HOST]', window.location.hostname) : `http://${window.location.hostname}:${data.port || suggestedPort}`;
      if (webuiBtn) {
        webuiBtn.href = webUrl;
        webuiBtn.textContent = `🌐 Open Web UI (:${data.port || suggestedPort}) ↗`;
      }

      if (closeBtn) {
        closeBtn.disabled = false;
        closeBtn.style.opacity = '1';
        closeBtn.style.pointerEvents = 'auto';
      }
      if (closeProgressBtn) {
        closeProgressBtn.style.display = 'inline-block';
        closeProgressBtn.textContent = '✓ Done';
      }
      modal._isDeploying = false;

      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `✓ ${appId.toUpperCase()} Deployed`;
        DockManager.render();
      }
      if (modal.classList.contains('window-minimized') || (DockManager && DockManager.windows['app-deploy']?.minimized)) {
        showDockToast(`🚀 ${appId.toUpperCase()} stack deployed and running! Click to open.`, 'app-deploy');
      }

      try {
        fetchAndRenderDockerContainers();
      } catch (e) {}

      showToast(`${appId} stack deployed and running!`, 'success');
    } else if (data.step === 'error') {
      modal._isDeploying = false;
      if (progressSpinner) {
        progressSpinner.textContent = '❌';
        progressSpinner.style.animation = 'none';
      }
      if (progressTitle) progressTitle.textContent = 'Deployment Failed';
      if (progressStatus) progressStatus.style.color = 'var(--crit, #ff6b6b)';
      if (progressPct) progressPct.style.color = 'var(--crit, #ff6b6b)';

      if (closeBtn) {
        closeBtn.disabled = false;
        closeBtn.style.opacity = '1';
        closeBtn.style.pointerEvents = 'auto';
      }
      if (backConfigBtn) backConfigBtn.style.display = 'inline-block';
      if (closeProgressBtn) {
        closeProgressBtn.style.display = 'inline-block';
        closeProgressBtn.textContent = 'Close';
      }

      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `❌ ${appId.toUpperCase()} Failed`;
        DockManager.render();
      }
      if (modal.classList.contains('window-minimized') || (DockManager && DockManager.windows['app-deploy']?.minimized)) {
        showDockToast(`❌ ${appId.toUpperCase()} deployment failed! Click to view logs.`, 'app-deploy');
      }

      showToast(`Deployment failed: ${data.message}`, 'error');
    }
  }

  deployConfirmBtn.onclick = async () => {
    const p = parseInt(portInput.value, 10) || suggestedPort;
    const s = storageInput.value.trim() || '/mnt/user/appdata';
    const cName = nameInput ? nameInput.value.trim() : appId;

    if (!replaceExisting) {
      // 1. Verify container name is available
      try {
        const nameCheck = await api.get(`/api/docker/check_container_name?name=${encodeURIComponent(cName)}`);
        if (nameCheck && nameCheck.exists) {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          if (nameInput) nameInput.style.borderColor = 'var(--warn, #f5a623)';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Container Name In Use:</span> A container named <strong>${cName}</strong> already exists. Please choose a unique name or select 'Stop &amp; Replace Existing'.`;
          showToast(`Container '${cName}' already exists. Please rename or select Replace.`, 'warn');
          return;
        }
      } catch (err) {}

      // 2. Verify port availability before starting deployment
      try {
        const check = await api.get(`/api/docker/check_port?port=${p}&proto=tcp`);
        if (check && check.available === false) {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          portInput.style.borderColor = 'var(--warn, #f5a623)';
          const inUse = check.in_use_by ? ` (in use by ${check.in_use_by})` : '';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️ Port Conflict:</span> Port ${p} is already busy${inUse}. Please choose an available port before deploying.`;
          showToast(`Port ${p} is already in use${inUse}. Please change the port.`, 'warn');
          return;
        }
      } catch (err) {}
    }

    modal._isDeploying = true;
    modal._activeAppId = appId;

    // Switch views
    viewConfig.style.display = 'none';
    footerConfig.style.display = 'none';
    viewProgress.style.display = 'flex';
    footerProgress.style.display = 'flex';

    // Keep close button interactive while active
    closeBtn.disabled = false;
    closeBtn.style.opacity = '1';
    closeBtn.style.pointerEvents = 'auto';

    // Reset progress UI
    if (progressFill) progressFill.style.width = '0%';
    if (progressPct) {
      progressPct.textContent = '0%';
      progressPct.style.color = 'var(--accent-cyan, #00f0ff)';
    }
    if (progressTitle) progressTitle.textContent = `Deploying ${cName} Stack...`;
    if (progressStatus) {
      progressStatus.textContent = 'Connecting to Docker daemon...';
      progressStatus.style.color = 'var(--muted)';
    }
    if (progressSpinner) {
      progressSpinner.textContent = '⚙️';
      progressSpinner.style.animation = 'spin 2s linear infinite';
    }
    if (deployLogs) deployLogs.innerHTML = '';
    if (successBox) successBox.style.display = 'none';
    if (closeProgressBtn) closeProgressBtn.style.display = 'none';
    if (backConfigBtn) backConfigBtn.style.display = 'none';

    logDeployLine(`Initiating deployment request for ${cName} (Port :${p}, Storage: ${s}, Replace: ${replaceExisting})...`);

    try {
      const response = await api.request(`/api/docker/catalog/${appId}/deploy`, {
        method: 'POST',
        body: {
          host_port: p,
          storage_root: s,
          container_name: cName,
          replace_existing: replaceExisting,
        },
      });

      if (!response.ok) {
        throw new Error(`Deployment request failed: HTTP ${response.status}`);
      }

      if (!response.body || !response.body.getReader) {
        const text = await response.text();
        const lines = text.split('\n').filter(Boolean);
        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            handleDeployEvent(data);
          } catch (e) {}
        }
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const eventData = JSON.parse(line);
            handleDeployEvent(eventData);
          } catch (err) {
            console.warn('NDJSON parsing error:', err, line);
          }
        }
      }

      if (buffer.trim()) {
        try {
          const eventData = JSON.parse(buffer);
          handleDeployEvent(eventData);
        } catch (e) {}
      }
    } catch (err) {
      modal._isDeploying = false;
      handleDeployEvent({
        step: 'error',
        percent: 0,
        message: err.message || 'Deployment connection failed',
        error: err.message,
        done: true,
      });
    }
  };

  if (backConfigBtn) {
    backConfigBtn.onclick = () => {
      viewProgress.style.display = 'none';
      footerProgress.style.display = 'none';
      viewConfig.style.display = 'flex';
      footerConfig.style.display = 'flex';
    };
  }

  if (closeProgressBtn) {
    closeProgressBtn.onclick = () => {
      modal._isDeploying = false;
      if (modal._close) modal._close();
    };
  }
}

export async function openDockerPruneModal() {
  let modal = document.getElementById('docker-prune-modal-overlay');
  if (!modal) {
    const html = `
      <div id="docker-prune-modal-overlay" class="smart-modal-backdrop" style="display:none; z-index:10020;">
        <div id="docker-prune-modal-window" class="smart-modal-window" style="width:580px; max-width:94vw; max-height:88vh; display:flex; flex-direction:column;">
          <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:18px;">🧹</span>
              <span style="font-weight:700; color:#fff; font-size:13px;">Docker Storage Prune & Cleanup</span>
            </div>
            <button class="win-btn close-btn" id="dpm-close-btn" title="Close" aria-label="Close"></button>
          </div>
          <div style="padding:16px; overflow-y:auto; display:flex; flex-direction:column; gap:12px;">
            <div style="font-size:11px; color:#cbd5e1; line-height:1.4;">
              Reclaim host storage space by pruning unused Docker resources. Safe for running containers.
            </div>

            <!-- Live Disk Usage Breakdown -->
            <div id="dpm-df-summary" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(110px, 1fr)); gap:8px;">
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:9px; color:var(--muted); text-transform:uppercase; font-weight:700;">Images</div>
                <div id="dpm-df-images" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:9px; color:var(--muted); text-transform:uppercase; font-weight:700;">Containers</div>
                <div id="dpm-df-containers" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:9px; color:var(--muted); text-transform:uppercase; font-weight:700;">Volumes</div>
                <div id="dpm-df-volumes" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(0,240,255,0.06); border:1px solid rgba(0,240,255,0.2); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:9px; color:var(--accent-cyan, #00f0ff); text-transform:uppercase; font-weight:700;">Reclaimable</div>
                <div id="dpm-df-reclaimable" style="font-size:12.5px; font-weight:800; color:var(--ok2, #25c2a0); margin-top:2px;">--</div>
              </div>
            </div>

            <!-- Prune Options -->
            <div style="background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:12px; display:flex; flex-direction:column; gap:10px;">
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-containers" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Stopped Containers</strong>
                  <div style="font-size:10px; color:var(--muted);">Deletes all exited, stopped, and dead containers.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-images" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Dangling Images</strong>
                  <div style="font-size:10px; color:var(--muted);">Removes untagged &lt;none&gt; build layers and intermediate images.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-all-images" style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune ALL Unused Images</strong>
                  <div style="font-size:10px; color:var(--muted);">Removes all images not currently referenced by at least one running container.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-volumes" style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Unused Local Volumes</strong>
                  <div style="font-size:10px; color:var(--warn, #f5a623);">Caution: Removes local anonymous volumes not mounted by containers.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-buildcache" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Build Cache & Unused Networks</strong>
                  <div style="font-size:10px; color:var(--muted);">Frees temporary Docker build cache layers and disconnected bridge networks.</div>
                </div>
              </label>
            </div>
          </div>
          <div style="padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="dpm-cancel-btn">Cancel</button>
            <button class="btn-pill-toggle" id="dpm-confirm-btn" style="background:linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); color:#fff; border:none; padding:6px 18px; font-weight:700; cursor:pointer;">
              🧹 Run Prune & Reclaim Storage
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('docker-prune-modal-overlay');

    const closeModal = () => {
      modal.classList.remove('open');
      modal.style.display = 'none';
    };
    document.getElementById('dpm-close-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    document.getElementById('dpm-cancel-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
    });

    const optImages = document.getElementById('dpm-opt-images');
    const optAllImages = document.getElementById('dpm-opt-all-images');
    const syncImageOptions = () => {
      if (optAllImages && optImages) {
        if (optAllImages.checked) {
          optImages.checked = true;
          optImages.disabled = true;
          optImages.parentElement.style.opacity = '0.5';
        } else {
          optImages.disabled = false;
          optImages.parentElement.style.opacity = '1';
        }
      }
    };
    if (optAllImages) optAllImages.onchange = syncImageOptions;
  }

  modal.classList.add('open');
  modal.style.display = 'flex';

  // Fetch live system df metrics
  try {
    const df = await api.get('/api/docker/system/df');
    const imgEl = document.getElementById('dpm-df-images');
    const cntEl = document.getElementById('dpm-df-containers');
    const volEl = document.getElementById('dpm-df-volumes');
    const recEl = document.getElementById('dpm-df-reclaimable');

    if (imgEl && df.images) imgEl.textContent = `${df.images.total_count} (${df.images.unused_count} unused)`;
    if (cntEl && df.containers) cntEl.textContent = `${df.containers.total_count} (${df.containers.stopped_count} stopped)`;
    if (volEl && df.volumes) volEl.textContent = `${df.volumes.total_count} (${df.volumes.unused_count} unused)`;
    if (recEl) recEl.textContent = df.total_reclaimable_human || '0 B';
  } catch (err) {
    console.warn('Failed to load system df:', err);
  }

  const confirmBtn = document.getElementById('dpm-confirm-btn');
  confirmBtn.disabled = false;
  confirmBtn.textContent = '🧹 Run Prune & Reclaim Storage';

  confirmBtn.onclick = async () => {
    const pruneContainers = document.getElementById('dpm-opt-containers').checked;
    const pruneImages = document.getElementById('dpm-opt-images').checked;
    const allImages = document.getElementById('dpm-opt-all-images').checked;
    const pruneVolumes = document.getElementById('dpm-opt-volumes').checked;
    const pruneBuildCache = document.getElementById('dpm-opt-buildcache').checked;

    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Pruning storage...';

    try {
      const res = await api.post('/api/docker/system/prune', {
        prune_containers: pruneContainers,
        prune_images: pruneImages || allImages,
        all_images: allImages,
        prune_volumes: pruneVolumes,
        prune_networks: pruneBuildCache,
        prune_build_cache: pruneBuildCache,
      });

      const details = [];
      if (res.images_deleted_count > 0) details.push(`${res.images_deleted_count} image${res.images_deleted_count > 1 ? 's' : ''}`);
      if (res.containers_deleted_count > 0) details.push(`${res.containers_deleted_count} container${res.containers_deleted_count > 1 ? 's' : ''}`);
      if (res.volumes_deleted_count > 0) details.push(`${res.volumes_deleted_count} volume${res.volumes_deleted_count > 1 ? 's' : ''}`);
      if (res.build_caches_deleted_count > 0) details.push(`${res.build_caches_deleted_count} build cache layer${res.build_caches_deleted_count > 1 ? 's' : ''}`);

      let msg = '';
      if (res.space_reclaimed_bytes > 0) {
        msg = `Prune completed! Reclaimed ${res.space_reclaimed_human}${details.length ? ' (' + details.join(', ') + ')' : ''}.`;
      } else if (details.length > 0) {
        msg = `Prune completed! Removed ${details.join(', ')} (no additional space freed).`;
      } else {
        msg = 'Prune completed: No unused resources were found to remove.';
      }

      showToast(msg, 'success');
      modal.classList.remove('open');
      modal.style.display = 'none';

      await fetchAndRenderDockerContainers();
    } catch (err) {
      showToast(`Prune failed: ${err.message}`, 'error');
      confirmBtn.disabled = false;
      confirmBtn.textContent = '🧹 Run Prune & Reclaim Storage';
    }
  };
}

function formatRelativeTime(ts) {
  if (!ts) return 'Never';
  const sec = Math.floor(Date.now() / 1000 - ts);
  if (sec < 60) return 'Just now';
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export async function openAppSourcesModal() {
  let modal = document.getElementById('app-sources-modal-overlay');
  if (!modal) {
    const html = `
      <div id="app-sources-modal-overlay" class="smart-modal-backdrop" style="display:none; z-index:10020;">
        <div id="app-sources-modal-window" class="smart-modal-window" style="width:680px; max-width:94vw; max-height:88vh; display:flex; flex-direction:column;">
          <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:18px;">🌐</span>
              <span style="font-weight:700; color:#fff; font-size:13px;">App Template Sources</span>
            </div>
            <button class="win-btn close-btn" id="asm-close-btn" title="Close" aria-label="Close"></button>
          </div>
          <div style="padding:16px; overflow-y:auto; display:flex; flex-direction:column; gap:14px;">
            <div style="font-size:11px; color:#cbd5e1; line-height:1.4;">
              Expand your App Catalog with external Portainer v2/v3 or custom JSON template repositories.
            </div>

            <!-- Quick Add Preset Banner -->
            <div id="asm-preset-banner" style="background:linear-gradient(135deg, rgba(14,165,233,0.12), rgba(37,194,160,0.08)); border:1px solid rgba(14,165,233,0.3); border-radius:8px; padding:12px 14px; display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;">
              <div>
                <div style="font-size:12px; font-weight:700; color:#fff; display:flex; align-items:center; gap:6px;">
                  <span>⭐ Lissy93 Portainer Templates</span>
                  <span class="ci-badge" style="font-size:9px; background:rgba(37,194,160,0.2); color:var(--accent);">790+ Apps</span>
                </div>
                <div style="font-size:10.5px; color:#94a3b8; margin-top:2px;">
                  Comprehensive community catalog of self-hosted homelab applications, web tools, and stacks.
                </div>
              </div>
              <button class="btn-pill-toggle" id="asm-btn-add-lissy" style="background:var(--brand, #0ea5e9); color:#fff; border:none; padding:5px 12px; font-weight:700; font-size:11px; white-space:nowrap; cursor:pointer;">
                + Add Lissy93 (790+ Apps)
              </button>
            </div>

            <!-- Add Custom Source Form -->
            <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px; display:flex; flex-direction:column; gap:10px;">
              <div style="font-size:11px; font-weight:700; color:#fff; text-transform:uppercase; letter-spacing:0.5px;">Add Custom Template Source</div>
              <div style="display:grid; grid-template-columns:1fr 2fr auto; gap:8px; align-items:end;">
                <div>
                  <label style="display:block; font-size:9.5px; font-weight:700; color:var(--muted); margin-bottom:3px;">SOURCE NAME</label>
                  <input type="text" id="asm-input-name" placeholder="e.g. Community Apps" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:5px 8px;">
                </div>
                <div>
                  <label style="display:block; font-size:9.5px; font-weight:700; color:var(--muted); margin-bottom:3px;">TEMPLATE URL (JSON)</label>
                  <input type="url" id="asm-input-url" placeholder="https://example.com/templates.json" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:5px 8px;">
                </div>
                <div>
                  <button class="btn-pill-toggle" id="asm-btn-add-custom" style="background:linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); color:#fff; border:none; padding:5px 14px; font-weight:700; font-size:11px; height:28px; white-space:nowrap; cursor:pointer;">
                    + Add & Sync
                  </button>
                </div>
              </div>
              <div id="asm-form-status" style="font-size:10.5px; display:none; padding:4px 6px; border-radius:4px;"></div>
            </div>

            <!-- Active Sources List -->
            <div>
              <div style="font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase; margin-bottom:8px; letter-spacing:0.5px;">
                Configured Sources (<span id="asm-sources-count">0</span>)
              </div>
              <div id="asm-sources-list" style="display:flex; flex-direction:column; gap:8px; max-height:260px; overflow-y:auto;">
                <div style="text-align:center; color:var(--muted); padding:16px;">Loading sources...</div>
              </div>
            </div>
          </div>
          <div style="padding:10px 16px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:flex-end; align-items:center; background:rgba(0,0,0,0.2);">
            <button class="btn-pill-toggle" id="asm-done-btn">Done</button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('app-sources-modal-overlay');

    const closeModal = () => {
      modal.classList.remove('open');
      modal.style.display = 'none';
      fetchAndRenderAppCatalog();
    };
    document.getElementById('asm-close-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    document.getElementById('asm-done-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
    });

    // Wire Lissy93 quick add
    const btnLissy = document.getElementById('asm-btn-add-lissy');
    if (btnLissy) {
      btnLissy.onclick = async () => {
        btnLissy.disabled = true;
        btnLissy.textContent = '⏳ Adding & Syncing...';
        try {
          await api.post('/api/docker/catalog/sources', {
            name: 'Lissy93 Templates',
            url: 'https://raw.githubusercontent.com/Lissy93/portainer-templates/main/templates.json',
          });
          showToast('Lissy93 Portainer templates added (790+ apps)!', 'success');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(`Failed to add Lissy93 templates: ${err.message}`, 'error');
          btnLissy.disabled = false;
          btnLissy.textContent = '+ Add Lissy93 (790+ Apps)';
        }
      };
    }

    // Wire custom add
    const btnCustom = document.getElementById('asm-btn-add-custom');
    if (btnCustom) {
      btnCustom.onclick = async () => {
        const nameInput = document.getElementById('asm-input-name');
        const urlInput = document.getElementById('asm-input-url');
        const statusEl = document.getElementById('asm-form-status');
        const name = (nameInput.value || '').trim();
        const url = (urlInput.value || '').trim();
        if (!name || !url) {
          statusEl.style.display = 'block';
          statusEl.style.background = 'rgba(239,68,68,0.15)';
          statusEl.style.color = '#fca5a5';
          statusEl.textContent = 'Please enter both name and URL.';
          return;
        }
        btnCustom.disabled = true;
        btnCustom.textContent = '⏳ Syncing...';
        statusEl.style.display = 'block';
        statusEl.style.background = 'rgba(14,165,233,0.15)';
        statusEl.style.color = '#38bdf8';
        statusEl.textContent = 'Fetching and caching remote templates...';
        try {
          await api.post('/api/docker/catalog/sources', { name, url });
          nameInput.value = '';
          urlInput.value = '';
          statusEl.style.background = 'rgba(37,194,160,0.15)';
          statusEl.style.color = 'var(--accent)';
          statusEl.textContent = '✓ Source added and synced successfully!';
          showToast(`Added template source "${name}"!`, 'success');
          setTimeout(() => { statusEl.style.display = 'none'; }, 3000);
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          statusEl.style.background = 'rgba(239,68,68,0.15)';
          statusEl.style.color = '#fca5a5';
          statusEl.textContent = `Error: ${err.message}`;
          showToast(`Failed to add source: ${err.message}`, 'error');
        } finally {
          btnCustom.disabled = false;
          btnCustom.textContent = '+ Add & Sync';
        }
      };
    }
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
  await refreshSourcesUI();
}

async function refreshSourcesUI() {
  const listEl = document.getElementById('asm-sources-list');
  const countEl = document.getElementById('asm-sources-count');
  const btnLissy = document.getElementById('asm-btn-add-lissy');
  if (!listEl) return;

  try {
    const sources = await api.get('/api/docker/catalog/sources');
    _catalogSources = Array.isArray(sources) ? sources : [];
    if (countEl) countEl.textContent = _catalogSources.length;
    updateCatalogSourcesBadge();

    // Check if Lissy93 is present
    const hasLissy = _catalogSources.some(
      (s) => (s.url && s.url.includes('Lissy93')) || (s.name && s.name.toLowerCase().includes('lissy'))
    );
    if (btnLissy) {
      if (hasLissy) {
        btnLissy.disabled = true;
        btnLissy.style.background = 'rgba(37,194,160,0.15)';
        btnLissy.style.color = 'var(--accent)';
        btnLissy.style.border = '1px solid rgba(37,194,160,0.3)';
        btnLissy.textContent = '✓ Lissy93 Added';
      } else {
        btnLissy.disabled = false;
        btnLissy.style.background = 'var(--brand, #0ea5e9)';
        btnLissy.style.color = '#fff';
        btnLissy.style.border = 'none';
        btnLissy.textContent = '+ Add Lissy93 (790+ Apps)';
      }
    }

    if (_catalogSources.length === 0) {
      listEl.innerHTML = '<div style="text-align:center; color:var(--muted); padding:16px;">No template sources configured.</div>';
      return;
    }

    listEl.innerHTML = _catalogSources.map((src) => {
      const isBuiltin = src.id === 'builtin';
      const isEnabled = src.enabled !== false;
      const statusBadge = src.status === 'ok'
        ? `<span class="ci-badge" style="font-size:9px; background:rgba(37,194,160,0.15); color:var(--accent);">✓ Synced (${formatRelativeTime(src.last_synced)})</span>`
        : (src.status === 'error'
          ? `<span class="ci-badge" style="font-size:9px; background:rgba(239,68,68,0.15); color:#fca5a5;" title="${escapeHtml(src.error || 'Sync failed')}">⚠️ Error</span>`
          : `<span class="ci-badge" style="font-size:9px; background:rgba(14,165,233,0.15); color:#38bdf8;">🔄 ${escapeHtml(src.status || 'pending')}</span>`);

      const toggleBtnClass = isEnabled ? 'btn-pill-toggle active' : 'btn-pill-toggle';
      const toggleText = isEnabled ? 'Enabled' : 'Disabled';

      return `
        <div class="asm-source-card" data-sourceid="${escapeHtml(src.id)}" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px 12px; display:flex; justify-content:space-between; align-items:center; gap:10px;">
          <div style="overflow:hidden; flex:1;">
            <div style="display:flex; align-items:center; gap:8px;">
              <strong style="font-size:12px; color:#fff;">${escapeHtml(src.name)}</strong>
              <span class="ci-badge" style="font-size:9px; background:rgba(255,255,255,0.06); color:#cbd5e1;">${src.item_count || 0} apps</span>
              ${statusBadge}
            </div>
            <div style="font-size:10px; color:var(--muted); font-family:var(--font-mono, monospace); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px;">
              ${escapeHtml(src.url)}
            </div>
            ${src.error ? `<div style="font-size:10px; color:#fca5a5; margin-top:3px;">${escapeHtml(src.error)}</div>` : ''}
          </div>
          <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
            <button class="${toggleBtnClass} asm-btn-toggle" data-sourceid="${escapeHtml(src.id)}" data-enabled="${isEnabled ? 'true' : 'false'}" style="font-size:10.5px; padding:3px 8px; cursor:pointer;">
              ${toggleText}
            </button>
            <button class="btn-pill-toggle asm-btn-sync" data-sourceid="${escapeHtml(src.id)}" title="Sync Now" style="font-size:11px; padding:3px 8px; cursor:pointer;">
              🔄
            </button>
            ${!isBuiltin ? `
              <button class="btn-pill-toggle asm-btn-delete" data-sourceid="${escapeHtml(src.id)}" title="Delete Source" style="font-size:11px; padding:3px 8px; color:#fca5a5; cursor:pointer;">
                🗑️
              </button>
            ` : ''}
          </div>
        </div>
      `;
    }).join('');

    // Wire toggle buttons
    listEl.querySelectorAll('.asm-btn-toggle').forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.dataset.sourceid;
        const curEnabled = btn.dataset.enabled === 'true';
        btn.disabled = true;
        try {
          await api.post(`/api/docker/catalog/sources/${sid}/toggle`, { enabled: !curEnabled });
          showToast(`Source ${!curEnabled ? 'enabled' : 'disabled'}.`, 'info');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(`Failed to toggle source: ${err.message}`, 'error');
          btn.disabled = false;
        }
      };
    });

    // Wire sync buttons
    listEl.querySelectorAll('.asm-btn-sync').forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.dataset.sourceid;
        btn.disabled = true;
        btn.textContent = '⏳';
        try {
          const res = await api.post(`/api/docker/catalog/sources/${sid}/sync`);
          showToast(`Source synced (${res.source ? res.source.item_count : 0} apps).`, 'success');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(`Failed to sync source: ${err.message}`, 'error');
          btn.disabled = false;
          btn.textContent = '🔄';
        }
      };
    });

    // Wire delete buttons
    listEl.querySelectorAll('.asm-btn-delete').forEach((btn) => {
      btn.onclick = () => {
        const sid = btn.dataset.sourceid;
        showConfirmToast(
          t('catalog.delete_source_title', 'Delete Template Source'),
          t('catalog.delete_source_confirm', 'Are you sure you want to delete this template source and all cached templates?'),
          async () => {
            btn.disabled = true;
            try {
              await api.delete(`/api/docker/catalog/sources/${sid}`);
              showToast('Source deleted successfully.', 'info');
              await refreshSourcesUI();
              fetchAndRenderAppCatalog();
            } catch (err) {
              showToast(`Failed to delete source: ${err.message}`, 'error');
              btn.disabled = false;
            }
          }
        );
      };
    });

  } catch (err) {
    listEl.innerHTML = `<div style="text-align:center; color:var(--crit); padding:16px;">Failed to load sources: ${escapeHtml(err.message)}</div>`;
  }
}

export function openSideloadAppModal() {
  const modal = document.getElementById('modal-sideload-app');
  if (!modal) return;

  const closeBtn = document.getElementById('modal-sideload-close-btn');
  const cancelBtn = document.getElementById('modal-sideload-cancel-btn');
  const tabUrl = document.getElementById('sideload-tab-url');
  const tabPaste = document.getElementById('sideload-tab-paste');
  const urlWrap = document.getElementById('sideload-input-url-wrap');
  const pasteWrap = document.getElementById('sideload-input-paste-wrap');
  const urlInput = document.getElementById('sideload-url-input');
  const contentInput = document.getElementById('sideload-content-input');
  const btnInspect = document.getElementById('btn-sideload-inspect');
  const resultBox = document.getElementById('sideload-inspect-result');
  const btnConfirm = document.getElementById('btn-sideload-confirm');

  let activeTab = 'url';
  let inspectedApp = null;

  function closeModal() {
    modal.style.display = 'none';
    modal.classList.remove('open');
    if (resultBox) resultBox.style.display = 'none';
    if (btnConfirm) {
      btnConfirm.disabled = true;
      btnConfirm.style.opacity = '0.5';
      btnConfirm.style.cursor = 'not-allowed';
    }
  }

  if (closeBtn) closeBtn.onclick = closeModal;
  if (cancelBtn) cancelBtn.onclick = closeModal;
  modal.onclick = (e) => {
    if (e.target === modal) closeModal();
  };

  if (tabUrl && tabPaste) {
    tabUrl.onclick = () => {
      activeTab = 'url';
      tabUrl.classList.add('active');
      tabPaste.classList.remove('active');
      if (urlWrap) urlWrap.style.display = 'block';
      if (pasteWrap) pasteWrap.style.display = 'none';
    };
    tabPaste.onclick = () => {
      activeTab = 'paste';
      tabPaste.classList.add('active');
      tabUrl.classList.remove('active');
      if (urlWrap) urlWrap.style.display = 'none';
      if (pasteWrap) pasteWrap.style.display = 'block';
    };
  }

  if (btnInspect) {
    btnInspect.onclick = async () => {
      const url = activeTab === 'url' ? (urlInput?.value || '').trim() : '';
      const manifest = activeTab === 'paste' ? (contentInput?.value || '').trim() : '';
      if (!url && !manifest) {
        showToast('Please provide a URL or paste manifest YAML/JSON.', 'warning');
        return;
      }
      btnInspect.disabled = true;
      btnInspect.innerHTML = '<span>⏳</span> <span>Validating...</span>';
      try {
        const payload = url ? { url } : { manifest_content: manifest };
        const res = await api.post('/api/docker/catalog/sideload', payload);
        if (res.status === 'ok' && res.app) {
          inspectedApp = res.app;
          renderSideloadInspection(res.app, res.security_rating, res.security_flags, resultBox);
          if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.style.opacity = '1';
            btnConfirm.style.cursor = 'pointer';
          }
        }
      } catch (err) {
        showToast(`Failed to inspect manifest: ${err.message}`, 'error');
        if (resultBox) {
          resultBox.style.display = 'block';
          resultBox.innerHTML = `<div style="color:var(--alert, #ef4444); font-size:12px;">Inspection Failed: ${escapeHtml(err.message)}</div>`;
        }
      } finally {
        btnInspect.disabled = false;
        btnInspect.innerHTML = '🔍 <span>Inspect & Validate</span>';
      }
    };
  }

  if (btnConfirm) {
    btnConfirm.onclick = () => {
      if (!inspectedApp) return;
      showToast(t('catalog.sideload_success', 'Application sideloaded successfully.'), 'success');
      closeModal();
      fetchAndRenderAppCatalog();
    };
  }

  modal.style.display = 'flex';
  modal.classList.add('open');
}

function renderSideloadInspection(app, rating, flags, container) {
  if (!container) return;
  container.style.display = 'block';

  let badgeColor = '#4ade80';
  let badgeBg = 'rgba(34,197,94,0.15)';
  let badgeBorder = 'rgba(34,197,94,0.3)';
  let badgeText = '🛡️ Verified Safe';

  if (rating === 'review_required') {
    badgeColor = '#facc15';
    badgeBg = 'rgba(234,179,8,0.15)';
    badgeBorder = 'rgba(234,179,8,0.3)';
    badgeText = '⚠️ Review Required';
  } else if (rating === 'elevated') {
    badgeColor = '#f87171';
    badgeBg = 'rgba(239,68,68,0.15)';
    badgeBorder = 'rgba(239,68,68,0.3)';
    badgeText = '🚨 Elevated Privileges Risk';
  }

  const flagsHtml = (flags && flags.length > 0)
    ? `<div style="margin-top:8px; font-size:11px; background:rgba(0,0,0,0.3); border-radius:4px; padding:6px 10px;">
        <div style="font-weight:700; color:${badgeColor}; margin-bottom:4px;">Security Audit Findings:</div>
        <ul style="margin:0; padding-left:16px; color:#cbd5e1;">
          ${flags.map((f) => `<li>${escapeHtml(f)}</li>`).join('')}
        </ul>
      </div>`
    : `<div style="margin-top:8px; font-size:11px; color:#4ade80;">✓ Zero high-privilege risk flags detected. Standard isolated container sandbox.</div>`;

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
      <div style="font-weight:700; font-size:13px; color:#fff;">${escapeHtml(app.name)}</div>
      <span class="ci-badge" style="font-size:10px; background:${badgeBg}; color:${badgeColor}; border:1px solid ${badgeBorder}; padding:2px 8px; border-radius:4px;">${badgeText}</span>
    </div>
    <div style="font-size:11px; color:var(--muted); line-height:1.4;">
      <div><strong>Image:</strong> <code>${escapeHtml(app.image || 'compose-stack')}</code></div>
      <div><strong>Type:</strong> ${escapeHtml(app.type || 'standalone')} · <strong>Default Port:</strong> ${escapeHtml(String(app.default_port || 'N/A'))}</div>
    </div>
    ${flagsHtml}
  `;
}

export function renderUpsTelemetry(ups) {
  if (!ups) return;
  const isPermErr = Boolean(ups.permission_error);
  const upsVal = isPermErr
    ? 'Perm Req'
    : (ups.battery_charge_pct != null ? `${ups.battery_charge_pct}%` : (ups.available ? 'Active' : 'Offline'));
  const upsPill = document.getElementById('mgmt-hub-ups-pill');
  if (upsPill) {
    upsPill.textContent = upsVal;
    if (isPermErr) {
      upsPill.style.background = 'rgba(235,87,87,0.15)';
      upsPill.style.color = 'var(--err, #eb5757)';
    } else if (ups.available && ups.battery_charge_pct != null) {
      upsPill.style.background = ups.battery_charge_pct <= 20 ? 'rgba(235,87,87,0.15)' : 'rgba(37,194,160,0.15)';
      upsPill.style.color = ups.battery_charge_pct <= 20 ? 'var(--err, #eb5757)' : 'var(--ok2, #25c2a0)';
    }
  }
  const sideUpsBadge = document.getElementById('mgmt-sidebar-ups-badge');
  if (sideUpsBadge) {
    sideUpsBadge.textContent = upsVal;
    sideUpsBadge.style.display = (ups.available || isPermErr) ? 'inline-block' : 'none';
    if (isPermErr) {
      sideUpsBadge.style.background = 'rgba(235,87,87,0.2)';
      sideUpsBadge.style.color = 'var(--err, #eb5757)';
    }
  }

  const statusEl = document.getElementById('mgmt-ups-status');
  const modelEl = document.getElementById('mgmt-ups-model');
  const chargeEl = document.getElementById('mgmt-ups-charge');
  const runtimeEl = document.getElementById('mgmt-ups-runtime');
  const loadEl = document.getElementById('mgmt-ups-load');
  const linevEl = document.getElementById('mgmt-ups-linev');
  const protocolEl = document.getElementById('mgmt-ups-protocol');
  const battvEl = document.getElementById('mgmt-ups-battv');
  const policyEl = document.getElementById('mgmt-ups-policy');

  if (statusEl) {
    statusEl.textContent = isPermErr ? 'Permission Required' : (ups.status || (ups.available ? 'ONLINE' : 'Offline'));
    statusEl.style.color = isPermErr
      ? 'var(--err, #eb5757)'
      : (ups.available ? (ups.on_battery ? 'var(--warn)' : 'var(--ok2)') : 'var(--muted)');
  }
  if (modelEl) modelEl.textContent = ups.model || 'Generic UPS';
  if (chargeEl) {
    chargeEl.textContent = ups.battery_charge_pct != null ? `${ups.battery_charge_pct}%` : 'N/A';
    chargeEl.style.color = (ups.battery_charge_pct == null || ups.battery_charge_pct > 30) ? 'var(--ok2)' : 'var(--crit)';
  }
  if (runtimeEl) runtimeEl.textContent = ups.time_left_min != null ? `${ups.time_left_min} min` : 'N/A';
  if (loadEl) loadEl.textContent = ups.load_pct != null ? `${ups.load_pct}%` : 'N/A';
  if (linevEl) linevEl.textContent = ups.line_volts != null ? `${ups.line_volts} V` : 'N/A';
  if (protocolEl) protocolEl.textContent = ups.protocol || 'Auto / NIS';
  if (battvEl) battvEl.textContent = ups.battery_volts != null ? `${ups.battery_volts} V` : 'N/A';
  if (policyEl) policyEl.textContent = ups.active_policy ? `Policy: ${ups.active_policy}` : 'Runtime < 5m';

  // Digital Twin Nodes
  const flowContainer = document.getElementById('ups-power-flow-container');
  const twinLinev = document.getElementById('ups-twin-linev');
  const twinGridStatus = document.getElementById('ups-twin-grid-status');
  const twinWatts = document.getElementById('ups-twin-watts');
  const twinBattVolts = document.getElementById('ups-twin-batt-volts');
  const radialFill = document.getElementById('ups-radial-fill');
  const gridDot = document.getElementById('ups-grid-dot');
  const emergencyBanner = document.getElementById('ups-emergency-banner');
  const emergencyCountdown = document.getElementById('ups-emergency-countdown');
  const permBanner = document.getElementById('ups-permission-banner');
  const permMsg = document.getElementById('ups-permission-msg');

  if (permBanner) {
    if (isPermErr) {
      permBanner.style.display = 'flex';
      if (permMsg && ups.permission_detail) {
        permMsg.textContent = ups.permission_detail;
      }
    } else {
      permBanner.style.display = 'none';
    }
  }

  if (twinLinev) twinLinev.textContent = ups.line_volts != null ? `${ups.line_volts} V` : (ups.available ? '120.0 V' : '-- V');
  if (twinGridStatus) {
    twinGridStatus.textContent = ups.on_battery ? 'AC Mains Disconnected' : (ups.line_freq_hz ? `${ups.line_freq_hz} Hz Nominal` : '120V / 60Hz Nominal');
  }
  if (twinWatts) twinWatts.textContent = ups.power_watts != null ? `${ups.power_watts} W` : (ups.load_pct != null ? `${Math.round(ups.load_pct * 9)} W` : '-- W');
  if (twinBattVolts) {
    const vStr = ups.battery_volts != null ? `${ups.battery_volts} V` : '-- V';
    const tStr = ups.battery_temp_c != null ? `${ups.battery_temp_c}°C` : '--°C';
    twinBattVolts.textContent = `${vStr} • ${tStr}`;
  }

  // Radial progress ring (circumference for r=28 is 175.93)
  if (radialFill) {
    const pct = Math.max(0, Math.min(100, ups.battery_charge_pct != null ? ups.battery_charge_pct : 100));
    const offset = 175.93 * (1 - pct / 100);
    radialFill.style.strokeDashoffset = offset;
    radialFill.style.stroke = pct <= 20 ? 'var(--err, #eb5757)' : (pct <= 40 ? 'var(--warn, #f5a623)' : 'var(--ok2, #25c2a0)');
  }

  if (flowContainer) {
    flowContainer.classList.toggle('on-battery', Boolean(ups.on_battery));
    flowContainer.classList.toggle('critical-battery', Boolean(ups.battery_charge_pct != null && ups.battery_charge_pct <= 20));
  }

  if (gridDot) {
    gridDot.className = 'ups-card-status-dot ' + (isPermErr ? 'danger' : (ups.on_battery ? 'danger' : (ups.available ? 'active' : '')));
  }

  if (emergencyBanner) {
    if (ups.on_battery) {
      emergencyBanner.style.display = 'flex';
      if (emergencyCountdown) {
        emergencyCountdown.textContent = ups.time_left_min != null ? `~${ups.time_left_min}m remaining` : 'ON BATTERY';
      }
    } else {
      emergencyBanner.style.display = 'none';
    }
  }
}

export async function fetchAndRenderUpsEvents() {
  const tbody = document.getElementById('ups-events-tbody');
  if (!tbody) return;
  try {
    const res = await api.get('/api/ups/events');
    const events = res && Array.isArray(res.events) ? res.events : [];
    if (!events.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--muted); padding:16px;">No power events or brownouts recorded. All power lines normal.</td></tr>';
      return;
    }
    tbody.innerHTML = events.map(ev => {
      const dateStr = ev.ts ? new Date(ev.ts * 1000).toLocaleString() : '--';
      let typeBadge = `<span class="badge" style="background:rgba(0,240,255,0.15); border:1px solid #00f0ff; color:#00f0ff; padding:2px 8px; border-radius:4px; font-size:11px;">${escapeHtml(ev.event_type)}</span>`;
      if (ev.event_type.includes('OUTAGE') || ev.event_type.includes('FAILSAFE')) {
        typeBadge = `<span class="badge" style="background:rgba(245,166,35,0.15); border:1px solid #f5a623; color:#f5a623; padding:2px 8px; border-radius:4px; font-size:11px;">${escapeHtml(ev.event_type)}</span>`;
      } else if (ev.event_type.includes('SELF_TEST')) {
        typeBadge = `<span class="badge" style="background:rgba(37,194,160,0.15); border:1px solid #25c2a0; color:#25c2a0; padding:2px 8px; border-radius:4px; font-size:11px;">${escapeHtml(ev.event_type)}</span>`;
      }
      const durStr = ev.duration_sec ? `${ev.duration_sec}s` : '--';
      const battDelta = ev.start_battery_pct != null && ev.end_battery_pct != null
        ? `${ev.start_battery_pct}% ➔ ${ev.end_battery_pct}%`
        : (ev.start_battery_pct != null ? `${ev.start_battery_pct}%` : '--');
      const action = ev.action_taken || ev.status || '--';

      return `<tr>
        <td style="font-size:12px; font-variant-numeric:tabular-nums;">${escapeHtml(dateStr)}</td>
        <td>${typeBadge}</td>
        <td style="font-size:12px;">${escapeHtml(durStr)}</td>
        <td style="font-size:12px;">${escapeHtml(battDelta)}</td>
        <td style="font-size:12px; color:var(--text);">${escapeHtml(action)}</td>
      </tr>`;
    }).join('');
  } catch (err) {
    console.debug('Failed to fetch UPS events:', err);
  }
}

export async function fetchAndRenderUpsTelemetry() {
  try {
    const ups = await api.get('/api/ups');
    if (!ups) return;
    renderUpsTelemetry(ups);
    fetchAndRenderUpsEvents();
  } catch (err) {
    console.debug('Failed to fetch UPS telemetry:', err);
  }
}

export function openUpsDrawer() {
  const drawer = document.getElementById('ups-config-drawer');
  const overlay = document.getElementById('ups-drawer-overlay');
  if (!drawer || !overlay) return;
  drawer.style.display = 'flex';
  overlay.style.display = 'block';
  void drawer.offsetWidth;
  drawer.classList.add('open');
  overlay.classList.add('open');
  loadUpsConfigToDrawer();
}
if (typeof window !== 'undefined') window.openUpsDrawer = openUpsDrawer;

export function closeUpsDrawer() {
  const drawer = document.getElementById('ups-config-drawer');
  const overlay = document.getElementById('ups-drawer-overlay');
  if (!drawer || !overlay) return;
  drawer.classList.remove('open');
  overlay.classList.remove('open');
  setTimeout(() => {
    drawer.style.display = 'none';
    overlay.style.display = 'none';
  }, 250);
}
if (typeof window !== 'undefined') window.closeUpsDrawer = closeUpsDrawer;

let upsSaveDebounceTimer = null;
let isUpsLoadingConfig = false;

export function updateUpsConnCardState(mode) {
  const connCard = document.getElementById('ups-drawer-conn-card');
  const badge = document.getElementById('ups-conn-disabled-badge');
  if (!connCard) return;
  const isDirectUsb = (mode === 'usb_hid');
  if (isDirectUsb) {
    connCard.classList.add('disabled');
    connCard.setAttribute('aria-disabled', 'true');
    if (badge) badge.style.display = 'inline-flex';
  } else {
    connCard.classList.remove('disabled');
    connCard.removeAttribute('aria-disabled');
    if (badge) badge.style.display = 'none';
  }
  const inputs = connCard.querySelectorAll('input, button');
  inputs.forEach(el => {
    el.disabled = isDirectUsb;
  });
}
if (typeof window !== 'undefined') window.updateUpsConnCardState = updateUpsConnCardState;

export async function saveUpsConfigFromDrawer() {
  if (isUpsLoadingConfig) return;
  try {
    const mode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
    const host = document.getElementById('ups-cfg-host')?.value.trim() || '127.0.0.1';
    const port = parseInt(document.getElementById('ups-cfg-port')?.value, 10) || 3551;
    const ups_name = document.getElementById('ups-cfg-name')?.value.trim() || 'ups';
    const username = document.getElementById('ups-cfg-user')?.value.trim() || '';
    const passwordRaw = document.getElementById('ups-cfg-pass')?.value || '';
    const password = passwordRaw.startsWith('••') ? undefined : passwordRaw;

    const policy = document.querySelector('input[name="ups-policy"]:checked')?.value || 'runtime_left';
    const runtime_threshold_min = parseInt(document.getElementById('ups-slider-runtime')?.value, 10) || 5;
    const battery_threshold_pct = parseInt(document.getElementById('ups-slider-battery')?.value, 10) || 20;
    const shutdown_timer_sec = parseInt(document.getElementById('ups-slider-timer')?.value, 10) || 300;

    const container_shutdown_timeout_sec = document.getElementById('ups-chk-docker')?.checked ? 45 : 0;
    const poweroff_ups = Boolean(document.getElementById('ups-chk-cutpower')?.checked);

    const payload = {
      enabled: true,
      mode,
      host,
      port,
      ups_name,
      username,
      shutdown_policy: policy,
      runtime_threshold_min,
      battery_threshold_pct,
      shutdown_timer_sec,
      container_shutdown_timeout_sec,
      poweroff_ups
    };
    if (password !== undefined) {
      payload.password = password;
    }

    const statusEl = document.getElementById('ups-save-status');
    if (statusEl) {
      statusEl.textContent = 'Saving…';
      statusEl.style.display = 'inline-flex';
    }

    await api.post('/api/ups/config', payload);

    if (statusEl) {
      statusEl.textContent = '✓ Saved';
      statusEl.style.display = 'inline-flex';
      setTimeout(() => {
        if (statusEl && statusEl.textContent === '✓ Saved') {
          statusEl.style.display = 'none';
        }
      }, 1500);
    }
    fetchAndRenderUpsTelemetry();
  } catch (err) {
    console.warn('Failed to auto-save UPS configuration:', err);
    const statusEl = document.getElementById('ups-save-status');
    if (statusEl) {
      statusEl.textContent = '✗ Error';
      setTimeout(() => {
        if (statusEl) statusEl.style.display = 'none';
      }, 3000);
    }
  }
}
if (typeof window !== 'undefined') window.saveUpsConfigFromDrawer = saveUpsConfigFromDrawer;

export async function loadUpsConfigToDrawer() {
  try {
    isUpsLoadingConfig = true;
    const cfg = await api.get('/api/ups/config');
    if (!cfg) return;

    // Mode selection
    const mode = cfg.mode || 'auto';
    const modeRadios = document.querySelectorAll('input[name="ups-mode"]');
    modeRadios.forEach(r => {
      r.checked = (r.value === mode);
    });

    // Update connection parameters card state (gray out if Direct USB)
    updateUpsConnCardState(mode);

    // Inputs
    const hostEl = document.getElementById('ups-cfg-host');
    const portEl = document.getElementById('ups-cfg-port');
    const nameEl = document.getElementById('ups-cfg-name');
    const userEl = document.getElementById('ups-cfg-user');
    const passEl = document.getElementById('ups-cfg-pass');

    if (hostEl) hostEl.value = cfg.host || '127.0.0.1';
    if (portEl) portEl.value = cfg.port || 3551;
    if (nameEl) nameEl.value = cfg.ups_name || 'ups';
    if (userEl) userEl.value = cfg.username || '';
    if (passEl) passEl.value = cfg.password || '';

    // Shutdown Policy
    const policy = cfg.shutdown_policy || 'runtime_left';
    const policyRadios = document.querySelectorAll('input[name="ups-policy"]');
    policyRadios.forEach(r => {
      r.checked = (r.value === policy);
    });

    // Sliders
    const runtimeSlider = document.getElementById('ups-slider-runtime');
    const runtimeVal = document.getElementById('ups-val-runtime');
    if (runtimeSlider) {
      runtimeSlider.value = cfg.runtime_threshold_min != null ? cfg.runtime_threshold_min : 5;
      if (runtimeVal) runtimeVal.textContent = `${runtimeSlider.value} min`;
    }

    const batterySlider = document.getElementById('ups-slider-battery');
    const batteryVal = document.getElementById('ups-val-battery');
    if (batterySlider) {
      batterySlider.value = cfg.battery_threshold_pct != null ? cfg.battery_threshold_pct : 20;
      if (batteryVal) batteryVal.textContent = `${batterySlider.value} %`;
    }

    const timerSlider = document.getElementById('ups-slider-timer');
    const timerVal = document.getElementById('ups-val-timer');
    if (timerSlider) {
      timerSlider.value = cfg.shutdown_timer_sec != null ? cfg.shutdown_timer_sec : 300;
      if (timerVal) timerVal.textContent = `${timerSlider.value} sec`;
    }

    // Checkboxes
    const chkDocker = document.getElementById('ups-chk-docker');
    if (chkDocker) {
      chkDocker.checked = (cfg.container_shutdown_timeout_sec ?? 45) > 0;
    }

    const chkCutpower = document.getElementById('ups-chk-cutpower');
    if (chkCutpower) {
      chkCutpower.checked = Boolean(cfg.poweroff_ups);
    }
  } catch (err) {
    console.debug('Failed to load UPS config:', err);
  } finally {
    isUpsLoadingConfig = false;
  }
}

export function initUpsDrawerControls() {
  const btnOpen = document.getElementById('btn-open-ups-config');
  btnOpen?.addEventListener('click', (e) => {
    e.preventDefault();
    const cfgSec = document.getElementById('ups-cockpit-config-section');
    if (cfgSec) {
      cfgSec.scrollIntoView({ behavior: 'smooth' });
    } else {
      openUpsDrawer();
    }
  });

  const btnRefresh = document.getElementById('btn-refresh-ups');
  btnRefresh?.addEventListener('click', async () => {
    try {
      btnRefresh.disabled = true;
      btnRefresh.textContent = 'Refreshing...';
      await fetchAndRenderUpsTelemetry();
      await loadUpsConfigToDrawer();
      showToast('UPS telemetry & parameters updated', 'info');
    } catch (err) {
      console.debug('Failed to refresh UPS telemetry:', err);
    } finally {
      btnRefresh.disabled = false;
      btnRefresh.textContent = '🔄 Refresh';
    }
  });

  const btnClose = document.getElementById('btn-close-ups-drawer');
  btnClose?.addEventListener('click', (e) => {
    e.preventDefault();
    closeUpsDrawer();
  });

  const overlay = document.getElementById('ups-drawer-overlay');
  overlay?.addEventListener('click', () => {
    closeUpsDrawer();
  });

  const triggerDebouncedSave = (delay = 200) => {
    clearTimeout(upsSaveDebounceTimer);
    upsSaveDebounceTimer = setTimeout(() => {
      saveUpsConfigFromDrawer();
    }, delay);
  };

  const triggerImmediateSave = () => {
    clearTimeout(upsSaveDebounceTimer);
    saveUpsConfigFromDrawer();
  };

  // Slider value listeners + auto-save
  const runtimeSlider = document.getElementById('ups-slider-runtime');
  const runtimeVal = document.getElementById('ups-val-runtime');
  runtimeSlider?.addEventListener('input', () => {
    if (runtimeVal) runtimeVal.textContent = `${runtimeSlider.value} min`;
    triggerDebouncedSave(200);
  });
  runtimeSlider?.addEventListener('change', () => {
    triggerImmediateSave();
  });

  const batterySlider = document.getElementById('ups-slider-battery');
  const batteryVal = document.getElementById('ups-val-battery');
  batterySlider?.addEventListener('input', () => {
    if (batteryVal) batteryVal.textContent = `${batterySlider.value} %`;
    triggerDebouncedSave(200);
  });
  batterySlider?.addEventListener('change', () => {
    triggerImmediateSave();
  });

  const timerSlider = document.getElementById('ups-slider-timer');
  const timerVal = document.getElementById('ups-val-timer');
  timerSlider?.addEventListener('input', () => {
    if (timerVal) timerVal.textContent = `${timerSlider.value} sec`;
    triggerDebouncedSave(200);
  });
  timerSlider?.addEventListener('change', () => {
    triggerImmediateSave();
  });

  // Policy radio auto-save
  const policyRadios = document.querySelectorAll('input[name="ups-policy"]');
  policyRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      triggerImmediateSave();
    });
  });

  // Checkbox toggles auto-save
  const chkDocker = document.getElementById('ups-chk-docker');
  chkDocker?.addEventListener('change', () => {
    triggerImmediateSave();
  });

  const chkCutpower = document.getElementById('ups-chk-cutpower');
  chkCutpower?.addEventListener('change', () => {
    triggerImmediateSave();
  });

  // Mode radio ports auto-fill, gray-out state, and auto-save
  const modeRadios = document.querySelectorAll('input[name="ups-mode"]');
  modeRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      const portEl = document.getElementById('ups-cfg-port');
      if (radio.value === 'apcupsd_client' && portEl && (portEl.value === '3493' || !portEl.value)) {
        portEl.value = '3551';
      } else if (radio.value === 'nut_client' && portEl && (portEl.value === '3551' || !portEl.value)) {
        portEl.value = '3493';
      }
      updateUpsConnCardState(radio.value);
      triggerImmediateSave();
    });
  });

  // Connection text inputs auto-save
  const connInputs = [
    document.getElementById('ups-cfg-host'),
    document.getElementById('ups-cfg-port'),
    document.getElementById('ups-cfg-name'),
    document.getElementById('ups-cfg-user'),
    document.getElementById('ups-cfg-pass')
  ];
  connInputs.forEach(input => {
    if (!input) return;
    input.addEventListener('change', () => {
      triggerImmediateSave();
    });
    input.addEventListener('input', () => {
      triggerDebouncedSave(600);
    });
  });

  // Auto-Discovery
  const btnDiscover = document.getElementById('btn-ups-discover');
  const discoverContainer = document.getElementById('ups-discover-candidates');
  btnDiscover?.addEventListener('click', async () => {
    try {
      btnDiscover.disabled = true;
      btnDiscover.textContent = 'Scanning...';
      const res = await api.post('/api/ups/discover');
      const candidates = res && Array.isArray(res.candidates) ? res.candidates : [];
      if (!discoverContainer) return;
      if (candidates.length === 0) {
        discoverContainer.innerHTML = `<div style="font-size:11.5px; color:var(--muted); padding:6px 0;">No active UPS daemons or USB devices detected on local ports.</div>`;
        return;
      }
      discoverContainer.innerHTML = candidates.map((cand, idx) => {
        const isUsb = Boolean(cand.is_usb || cand.type === 'usb_hid' || cand.mode === 'usb_hid');
        const isApc = !isUsb && (cand.type === 'apcupsd' || cand.type === 'apcupsd_client' || cand.port === 3551);
        const isNut = !isUsb && (cand.type === 'nut' || cand.type === 'nut_client' || cand.port === 3493);
        const typeLabel = isUsb ? 'Direct USB HID' : (isApc ? 'APCUPSD NIS' : (isNut ? 'NUT Server' : 'USB HID Device'));
        const hostPort = isUsb
          ? (cand.description || `USB ${cand.vendor_id || ''}:${cand.product_id || ''}`)
          : (cand.port ? `${cand.host}:${cand.port}` : (cand.path || cand.host || 'local'));
        const displayTitle = cand.title || cand.label || typeLabel;
        return `<div class="ups-discover-item" data-idx="${idx}" style="display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.08); padding:8px 12px; border-radius:6px; cursor:pointer;">
          <div>
            <div style="font-size:12px; font-weight:600; color:#fff;">${escapeHtml(displayTitle)}</div>
            <div style="font-size:11px; color:var(--muted);">${escapeHtml(typeLabel)} • <code>${escapeHtml(hostPort)}</code></div>
          </div>
          <button type="button" class="btn-rect" style="font-size:11px; padding:3px 8px;">Apply</button>
        </div>`;
      }).join('');

      discoverContainer.querySelectorAll('.ups-discover-item').forEach(item => {
        item.addEventListener('click', () => {
          const idx = parseInt(item.dataset.idx, 10);
          const cand = candidates[idx];
          if (!cand) return;
          const isUsb = Boolean(cand.is_usb || cand.type === 'usb_hid' || cand.mode === 'usb_hid');
          const isApc = !isUsb && (cand.type === 'apcupsd' || cand.type === 'apcupsd_client' || cand.port === 3551);
          const isNut = !isUsb && (cand.type === 'nut' || cand.type === 'nut_client' || cand.port === 3493);
          const targetMode = isUsb ? 'usb_hid' : (cand.mode || (isApc ? 'apcupsd_client' : (isNut ? 'nut_client' : 'auto')));
          const radio = document.querySelector(`input[name="ups-mode"][value="${targetMode}"]`);
          if (radio) radio.checked = true;
          const hostEl = document.getElementById('ups-cfg-host');
          const portEl = document.getElementById('ups-cfg-port');
          const nameEl = document.getElementById('ups-cfg-name');
          if (isUsb) {
            if (hostEl) hostEl.value = '';
            if (portEl) portEl.value = '';
          } else {
            if (hostEl && cand.host) hostEl.value = cand.host;
            if (portEl) {
              if (cand.port && cand.port > 0) {
                portEl.value = cand.port;
              } else if (targetMode === 'apcupsd_client') {
                portEl.value = 3551;
              } else if (targetMode === 'nut_client') {
                portEl.value = 3493;
              }
            }
            if (nameEl && cand.ups_name) nameEl.value = cand.ups_name;
          }
          updateUpsConnCardState(targetMode);
          triggerImmediateSave();
          const displayTitle = cand.title || cand.label || (isUsb ? 'Direct USB HID' : (isApc ? 'APCUPSD' : (isNut ? 'NUT' : 'USB HID')));
          showToast(`Applied ${displayTitle} parameters!`, 'info');
        });
      });
    } catch (err) {
      showToast(`Auto-discovery failed: ${err.message}`, 'error');
    } finally {
      btnDiscover.disabled = false;
      btnDiscover.textContent = 'Scan Hardware';
    }
  });

  // Test Connection
  const btnTest = document.getElementById('btn-ups-test-conn');
  btnTest?.addEventListener('click', async () => {
    try {
      btnTest.disabled = true;
      btnTest.textContent = 'Testing...';
      const mode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
      const host = document.getElementById('ups-cfg-host')?.value.trim() || '127.0.0.1';
      const port = parseInt(document.getElementById('ups-cfg-port')?.value, 10) || 3551;
      const ups_name = document.getElementById('ups-cfg-name')?.value.trim() || 'ups';
      const username = document.getElementById('ups-cfg-user')?.value.trim() || '';
      const passwordRaw = document.getElementById('ups-cfg-pass')?.value || '';
      const password = passwordRaw.startsWith('••') ? '' : passwordRaw;
      const isUsbMode = (mode === 'usb_hid');

      const res = await api.post('/api/ups/test-connection', {
        mode,
        host: isUsbMode ? '' : host,
        port: isUsbMode ? 0 : port,
        ups_name: isUsbMode ? '' : ups_name,
        username: isUsbMode ? '' : username,
        password: isUsbMode ? '' : password
      });

      if (res && (res.connected || res.success)) {
        showToast(`Connection successful! (${res.model || res.status || 'ONLINE'})`, 'success');
        btnTest.textContent = '✓ Connected';
        setTimeout(() => { btnTest.textContent = '🔌 Test Connection'; }, 3000);
      } else {
        showToast(`Connection failed: ${res.error || 'UPS daemon unreachable'}`, 'error');
        btnTest.textContent = '✗ Failed';
        setTimeout(() => { btnTest.textContent = '🔌 Test Connection'; }, 3000);
      }
    } catch (err) {
      showToast(`Connection test error: ${err.message}`, 'error');
      btnTest.textContent = '✗ Error';
      setTimeout(() => { btnTest.textContent = '🔌 Test Connection'; }, 3000);
    } finally {
      btnTest.disabled = false;
    }
  });

  // Legacy save button handler fallback if still rendered in custom views
  const btnSave = document.getElementById('btn-save-ups-config');
  btnSave?.addEventListener('click', async () => {
    await saveUpsConfigFromDrawer();
    closeUpsDrawer();
  });

  // Battery Self-Test
  const btnSelfTest = document.getElementById('btn-run-ups-selftest');
  btnSelfTest?.addEventListener('click', () => {
    showConfirmToast(
      'Run Diagnostic Battery Self-Test?',
      'This commands the UPS inverter to perform a 10-second internal battery discharge test under active load.',
      async () => {
        try {
          showToast('Initiating battery self-test...', 'info');
          const res = await api.post('/api/ups/self-test');
          showToast(res.message || 'Battery self-test command sent successfully!', 'success');
          fetchAndRenderUpsTelemetry();
        } catch (err) {
          showToast(`Self-test failed: ${err.message}`, 'error');
        }
      },
      null,
      { okText: '🔋 Run Self-Test', cancelText: 'Cancel' }
    );
  });

  // Outage Simulation Drill
  const btnSimulate = document.getElementById('btn-ups-simulate');
  btnSimulate?.addEventListener('click', () => {
    showConfirmToast(
      'Simulate Power Outage Drill?',
      'This simulates a 15-second utility power failure drill to verify digital twin electron animations, emergency countdown banner, and event ledger logging. <strong>Host will NOT shut down.</strong>',
      async () => {
        try {
          showToast('Outage drill started (15s)...', 'warn');
          await api.post('/api/ups/simulate', { duration_sec: 15 });
          fetchAndRenderUpsTelemetry();
        } catch (err) {
          showToast(`Simulation failed: ${err.message}`, 'error');
        }
      },
      null,
      { okText: '⚠️ Start Drill', cancelText: 'Cancel' }
    );
  });
}
if (typeof window !== 'undefined') window.initUpsDrawerControls = initUpsDrawerControls;

export async function fetchAndRenderCopyHistory() {
  const tbody = document.getElementById('copy-history-tbody');
  if (!tbody) return;
  try {
    const history = await api.get('/api/copy/history?limit=30');
    if (!history || history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:16px;">No ingest operations recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = history.map((item) => {
      const d = new Date(item.ts * 1000);
      const timeStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const sizeMB = (item.total_bytes / (1024 * 1024)).toFixed(1);
      const durStr = item.duration_sec ? `${item.duration_sec.toFixed(1)}s` : '--';
      const isSuccess = item.status === 'success';
      const statusColor = isSuccess ? 'var(--ok2)' : item.status === 'aborted' ? 'var(--warn)' : 'var(--crit)';
      const checksumBadge = item.checksum_verified
        ? '<span class="checksum-badge">✓ SHA-256</span>'
        : '<span style="color:var(--muted); font-size:9px;">None</span>';
      const destName = item.dest ? item.dest.split('/').filter(Boolean).pop() || item.dest : '/';

      return `
        <tr>
          <td style="font-family:var(--font-mono, monospace); font-size:10px; color:var(--muted);">${timeStr}</td>
          <td><strong>${(item.source || 'sd').toUpperCase()}</strong></td>
          <td title="${escapeHtml(item.dest)}" style="max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(destName)}</td>
          <td>${item.files_count || 0}</td>
          <td>${sizeMB} MB</td>
          <td>${durStr}</td>
          <td>
            <span style="font-weight:700; color:${statusColor}; text-transform:uppercase; margin-right:6px;">${escapeHtml(item.status)}</span>
            ${checksumBadge}
          </td>
        </tr>
      `;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--crit); padding:16px;">Failed to load history: ${escapeHtml(e.message)}</td></tr>`;
  }
}

export async function fetchAndRenderReplication() {
  const tbody = document.getElementById('replication-jobs-tbody');
  const histTbody = document.getElementById('replication-history-tbody');
  if (!tbody) return;

  try {
    const [jobsRes, histRes] = await Promise.all([
      api.get('/api/storage/replication/jobs').catch(() => ({ jobs: [] })),
      api.get('/api/storage/replication/history').catch(() => ({ history: [] })),
    ]);

    const jobs = jobsRes.jobs || [];
    if (jobs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--muted); padding:20px;">No replication pipelines configured. Click '+ New Replication Pipeline' to create one.</td></tr>`;
    } else {
      tbody.innerHTML = jobs
        .map((j) => {
          const tgtDesc =
            j.target_type === 'local'
              ? `Local: ${escapeHtml(j.target_pool || 'default')}`
              : `${escapeHtml(j.target_host || 'remote')}:${escapeHtml(j.target_pool || '')} (${j.target_type})`;
          return `
          <tr>
            <td><strong>${escapeHtml(j.name || j.id)}</strong></td>
            <td><span class="badge" style="font-family:monospace;">${escapeHtml(j.source_pool)}/${escapeHtml(j.source_subvolume || '@')}</span></td>
            <td>${tgtDesc}</td>
            <td><span class="mgmt-app-pill" style="font-size:10px;">${escapeHtml(j.schedule || 'manual')}</span></td>
            <td>${j.bandwidth_limit_mbps ? `${j.bandwidth_limit_mbps} MB/s` : 'Unlimited'}</td>
            <td>${j.retention_count || 7} snaps</td>
            <td><span class="mgmt-app-pill ${j.enabled ? 'text-emerald' : 'text-muted'}">${j.enabled ? 'Active' : 'Disabled'}</span></td>
            <td style="text-align:right;">
              <button class="btn-pill-toggle btn-run-repl" data-id="${escapeHtml(j.id)}" style="font-size:10.5px; padding:2px 8px; margin-right:4px;" title="Execute Replication Now">▶ Run</button>
              <button class="btn-pill-toggle btn-del-repl" data-id="${escapeHtml(j.id)}" style="font-size:10.5px; padding:2px 8px; color:var(--crit);" title="Delete Pipeline">🗑️</button>
            </td>
          </tr>
        `;
        })
        .join('');

      tbody.querySelectorAll('.btn-run-repl').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.id;
          try {
            btn.disabled = true;
            btn.textContent = '⏳ Running...';
            await api.post(`/api/storage/replication/jobs/${encodeURIComponent(id)}/run`);
            showToast(`Replication pipeline '${id}' dispatched.`, 'success');
            setTimeout(fetchAndRenderReplication, 1000);
          } catch (e) {
            showToast(`Replication failed: ${e.message}`, 'error');
          } finally {
            btn.disabled = false;
            btn.textContent = '▶ Run';
          }
        });
      });

      tbody.querySelectorAll('.btn-del-repl').forEach((btn) => {
        btn.addEventListener('click', () => {
          const id = btn.dataset.id;
          showConfirmToast(
            t('storage.delete_repl_title', 'Delete Replication Pipeline'),
            `Delete replication pipeline '${id}'?`,
            async () => {
              try {
                await api.delete(`/api/storage/replication/jobs/${encodeURIComponent(id)}`);
                showToast(`Pipeline '${id}' deleted.`, 'success');
                fetchAndRenderReplication();
              } catch (e) {
                showToast(`Delete failed: ${e.message}`, 'error');
              }
            }
          );
        });
      });
    }

    if (histTbody) {
      const history = histRes.history || [];
      if (history.length === 0) {
        histTbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:16px;">No replication history recorded yet.</td></tr>`;
      } else {
        histTbody.innerHTML = history
          .slice(0, 20)
          .map((h) => {
            const dt = h.timestamp ? new Date(h.timestamp * 1000).toLocaleString() : '--';
            const isOk = h.status === 'success';
            return `
            <tr>
              <td>${escapeHtml(dt)}</td>
              <td><code>${escapeHtml(h.job_id || '--')}</code></td>
              <td>${escapeHtml(h.target || '--')}</td>
              <td>${h.bytes_transferred ? (h.bytes_transferred / (1024 * 1024)).toFixed(1) + ' MB' : '--'}</td>
              <td>${h.duration_seconds ? `${h.duration_seconds.toFixed(1)}s` : '--'}</td>
              <td><span class="mgmt-app-pill ${isOk ? 'text-emerald' : 'text-crimson'}">${isOk ? '✓ Success' : 'Failed'}</span></td>
            </tr>
          `;
          })
          .join('');
      }
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--crit); padding:16px;">Failed to load replication pipelines: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export function renderTailscalePeersTable(peers, filterQuery = '') {
  const tbody = document.getElementById('ts-peers-table-body');
  const countPill = document.getElementById('ts-peer-count-pill');
  if (!tbody) return;
  const q = (filterQuery || '').toLowerCase().trim();
  const peersArr = Array.isArray(peers) ? peers : [];
  const filtered = q
    ? peersArr.filter(
        p =>
          (p.name || p.hostname || '').toLowerCase().includes(q) ||
          (p.ip || '').includes(q) ||
          (p.os || '').toLowerCase().includes(q)
      )
    : peersArr;

  if (countPill) {
    const onlineCount = peersArr.filter(p => p.online).length;
    countPill.textContent = `${onlineCount} online / ${peersArr.length} total`;
  }

  if (filtered.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="6" style="text-align:center; padding:16px; color:var(--muted);">No peers match search query.</td></tr>';
    return;
  }

  tbody.innerHTML = filtered
    .map(p => {
      const osLower = (p.os || '').toLowerCase();
      let osLabel = `🌐 ${p.os || 'Unknown'}`;
      if (osLower.includes('ios')) osLabel = '📱 iOS';
      else if (osLower.includes('android')) osLabel = '🤖 Android';
      else if (osLower.includes('mac') || osLower.includes('darwin')) osLabel = '🍏 macOS';
      else if (osLower.includes('windows')) osLabel = '🪟 Windows';
      else if (osLower.includes('linux')) osLabel = '🐧 Linux';

      const routeBadge = p.cur_addr
        ? '<span style="color:#3bf58b; font-weight:600;">⚡ Direct P2P</span>'
        : p.relay
          ? `<span style="color:#f59e0b;">🌐 DERP (${escapeHtml(p.relay)})</span>`
          : '<span style="color:var(--muted);">--</span>';

      const statusPill = p.online
        ? '<span class="mgmt-app-pill" style="color:#3bf58b; background:rgba(59,245,139,0.12); font-size:10px; padding:2px 7px;">Online</span>'
        : '<span class="mgmt-app-pill" style="color:var(--muted); background:rgba(255,255,255,0.06); font-size:10px; padding:2px 7px;">Offline</span>';

      const safeIpId = (p.ip || 'no_ip').replace(/[^a-zA-Z0-9]/g, '_');

      return `
      <tr style="border-bottom:1px solid rgba(255,255,255,0.05); font-size:11.5px;">
        <td style="padding:8px 12px;">
          <div style="font-weight:700; color:#fff;">${escapeHtml(p.name || p.hostname || 'Unnamed')}</div>
          ${p.dns_name ? `<div style="font-size:10px; color:var(--muted);">${escapeHtml(p.dns_name)}</div>` : ''}
        </td>
        <td style="padding:8px 12px; color:var(--text-sub);">${osLabel}</td>
        <td style="padding:8px 12px;"><code style="color:#38bdf8; font-size:11px;">${escapeHtml(p.ip || '--')}</code></td>
        <td style="padding:8px 12px;">${routeBadge}</td>
        <td style="padding:8px 12px;">${statusPill}</td>
        <td style="padding:8px 12px; text-align:right;">
          <div style="display:inline-flex; align-items:center; gap:6px;">
            <span id="latency-${safeIpId}" style="font-size:10.5px; font-weight:700;"></span>
            <button class="btn-pill-toggle btn-ping-peer" data-peer-ip="${escapeHtml(p.ip || '')}" style="font-size:10px; padding:2px 8px;" ${!p.ip ? 'disabled' : ''}>⚡ Ping</button>
          </div>
        </td>
      </tr>
    `;
    })
    .join('');
}

export async function fetchAndRenderWireguard() {
  const ipFwdEl = document.getElementById('wg-ip-forward-status');
  const pubkeyEl = document.getElementById('wg-pubkey-display');
  const wgBadgeEl = document.getElementById('wg-tunnel-status-badge');
  const wgFwdPill = document.getElementById('wg-forwarding-pill');
  const previewEl = document.getElementById('wg-conf-preview');
  const dlBtn = document.getElementById('btn-download-wg-conf');
  const genBtn = document.getElementById('btn-wg-gen-client-config');
  const natBtn = document.getElementById('btn-toggle-wg-subnet-nat');
  const refreshBtn = document.getElementById('btn-refresh-wireguard');

  // Tailscale elements
  const tsBadgeEl = document.getElementById('tailscale-status-badge');
  const tsPillEl = document.getElementById('ts-connection-pill');
  const tsIpEl = document.getElementById('ts-ipv4-display');
  const tsCopyIpBtn = document.getElementById('btn-copy-ts-ip');
  const tsTailnetEl = document.getElementById('ts-tailnet-display');
  const tsHostEl = document.getElementById('ts-hostname-display');
  const tsPeersEl = document.getElementById('ts-peers-display');
  const tsConnectForm = document.getElementById('ts-connect-form');
  const tsConnectedView = document.getElementById('ts-connected-view');
  const tsFormIntro = document.getElementById('ts-form-intro');
  const tsAuthKeyInput = document.getElementById('ts-auth-key-input');
  const tsHostnameInput = document.getElementById('ts-hostname-input');
  const tsAcceptRoutesCb = document.getElementById('ts-accept-routes-input');
  const tsUpBtn = document.getElementById('btn-tailscale-up');
  const tsDownBtn = document.getElementById('btn-tailscale-down');
  const tsDeployBanner = document.getElementById('ts-deploy-banner');
  const tsDeployBtn = document.getElementById('btn-deploy-tailscale');
  const tsAuthPrompt = document.getElementById('ts-auth-prompt');
  const tsAuthLink = document.getElementById('ts-auth-link');
  const tsCopyAuthUrlBtn = document.getElementById('btn-copy-ts-auth-url');

  const tsExtContainer = document.getElementById('network-tailscale-extended');
  const tsPeersCard = document.getElementById('tailscale-peers-card');

  try {
    const meshData = await api.get('/api/network/mesh-vpn').catch(() => null);
    if (meshData && meshData.tailscale) {
      const ts = meshData.tailscale;
      if (!ts.installed) {
        if (tsBadgeEl) {
          tsBadgeEl.textContent = 'Not Installed';
          tsBadgeEl.style.color = 'var(--muted, #94a3b8)';
          tsBadgeEl.style.borderColor = 'rgba(255,255,255,0.1)';
        }
        if (tsPillEl) {
          tsPillEl.textContent = 'Daemon Not Found';
          tsPillEl.style.color = 'var(--muted, #94a3b8)';
          tsPillEl.style.background = 'rgba(255,255,255,0.06)';
        }
        if (tsDeployBanner) tsDeployBanner.style.display = 'block';
        if (tsFormIntro) {
          tsFormIntro.textContent = 'Deploy official Tailscale container or provide auth key to connect instantly:';
          tsFormIntro.style.color = '#f59e0b';
        }
        if (tsIpEl) tsIpEl.textContent = '--';
        if (tsCopyIpBtn) tsCopyIpBtn.style.display = 'none';
        if (tsTailnetEl) tsTailnetEl.textContent = '--';
        if (tsHostEl) tsHostEl.textContent = '--';
        if (tsPeersEl) tsPeersEl.textContent = '0 peers';
        if (tsConnectForm) tsConnectForm.style.display = 'flex';
        if (tsConnectedView) tsConnectedView.style.display = 'none';
        if (tsDownBtn) tsDownBtn.style.display = 'none';
        if (tsUpBtn) {
          tsUpBtn.textContent = '⚡ 1-Click Deploy Tailscale';
          tsUpBtn.dataset.mode = 'deploy';
        }
        if (tsExtContainer) {
          tsExtContainer.style.display = 'none';
          tsExtContainer.dataset.active = '0';
        }
        if (tsPeersCard) {
          tsPeersCard.style.display = 'none';
          tsPeersCard.dataset.active = '0';
        }
      } else if (ts.active) {
        if (tsBadgeEl) {
          tsBadgeEl.textContent = 'Active (Connected)';
          tsBadgeEl.style.color = 'var(--ok2, #3bf58b)';
          tsBadgeEl.style.borderColor = 'rgba(59,245,139,0.3)';
        }
        if (tsPillEl) {
          tsPillEl.textContent = 'Connected';
          tsPillEl.style.color = '#3bf58b';
          tsPillEl.style.background = 'rgba(59,245,139,0.12)';
        }
        if (tsDeployBanner) tsDeployBanner.style.display = 'none';
        if (tsAuthPrompt) tsAuthPrompt.style.display = 'none';
        if (window._tsAuthPollInterval) {
          clearInterval(window._tsAuthPollInterval);
          window._tsAuthPollInterval = null;
        }
        if (tsIpEl) tsIpEl.textContent = ts.ipv4 || '--';
        if (tsCopyIpBtn) tsCopyIpBtn.style.display = ts.ipv4 ? 'inline-block' : 'none';
        if (tsTailnetEl) tsTailnetEl.textContent = ts.tailnet || '--';
        if (tsHostEl) tsHostEl.textContent = ts.hostname || '--';
        if (tsPeersEl) tsPeersEl.textContent = `${ts.peers_count || 0} peer(s)`;
        if (tsConnectForm) tsConnectForm.style.display = 'none';
        if (tsConnectedView) tsConnectedView.style.display = 'flex';
        if (tsDownBtn) tsDownBtn.style.display = 'inline-block';
        if (tsUpBtn) {
          tsUpBtn.textContent = '🚀 Connect Tailscale';
          tsUpBtn.dataset.mode = 'connect';
        }

        // Show extended capability cards
        if (tsExtContainer) {
          tsExtContainer.style.display = 'grid';
          tsExtContainer.dataset.active = '1';
        }
        if (tsPeersCard) {
          tsPeersCard.style.display = 'block';
          tsPeersCard.dataset.active = '1';
        }

        // 7. Node Key Expiry & Re-Auth
        const keyExpiryDisplay = document.getElementById('ts-key-expiry-display');
        const reauthBtn = document.getElementById('btn-ts-reauth');
        if (keyExpiryDisplay) {
          if (ts.key_expiry_days !== null && ts.key_expiry_days !== undefined) {
            if (ts.key_expiry_days > 14) {
              const dt = ts.key_expiry ? ts.key_expiry.slice(0, 10) : '';
              keyExpiryDisplay.textContent = `Expires in ${ts.key_expiry_days} days (${dt})`;
              keyExpiryDisplay.style.color = 'var(--ok2, #3bf58b)';
            } else if (ts.key_expiry_days > 0) {
              keyExpiryDisplay.textContent = `⚠️ Expires in ${ts.key_expiry_days} days`;
              keyExpiryDisplay.style.color = '#fbbf24';
            } else {
              keyExpiryDisplay.textContent = '❌ Key Expired';
              keyExpiryDisplay.style.color = '#f87171';
            }
          } else {
            keyExpiryDisplay.textContent = 'Key Expiry Disabled';
            keyExpiryDisplay.style.color = 'var(--ok2, #3bf58b)';
          }
        }
        if (reauthBtn) reauthBtn.style.display = 'inline-block';

        // 1. Subnet Router Gateway
        const subnetToggle = document.getElementById('ts-subnet-router-toggle');
        const subnetInput = document.getElementById('ts-subnet-routes-input');
        if (subnetToggle) subnetToggle.checked = Boolean(ts.is_subnet_router);
        if (subnetInput && document.activeElement !== subnetInput) {
          const advRoutes = Array.isArray(ts.advertised_routes)
            ? ts.advertised_routes.filter(r => r !== '0.0.0.0/0' && r !== '::/0').join(', ')
            : (ts.advertised_routes || '');
          const detRoutes = Array.isArray(ts.detected_subnets)
            ? ts.detected_subnets.join(', ')
            : ts.detected_subnets || '';
          subnetInput.value = advRoutes || detRoutes;
          if (!advRoutes && detRoutes) {
            subnetInput.placeholder = detRoutes;
          }
        }

        // 2. Exit Node Gateway
        const exitNodeToggle = document.getElementById('ts-exit-node-toggle');
        const exitNodePill = document.getElementById('ts-exit-node-pill');
        const exitNodeHint = document.getElementById('ts-exit-node-approval-hint');
        if (exitNodeToggle) exitNodeToggle.checked = Boolean(ts.advertise_exit_node);
        if (exitNodePill) {
          if (ts.is_exit_node) {
            exitNodePill.textContent = 'Active (In Use)';
            exitNodePill.style.color = '#3bf58b';
            exitNodePill.style.background = 'rgba(59,245,139,0.15)';
            if (exitNodeHint) exitNodeHint.style.display = 'none';
          } else if (ts.exit_node_approved) {
            exitNodePill.textContent = 'Approved & Available';
            exitNodePill.style.color = '#3bf58b';
            exitNodePill.style.background = 'rgba(59,245,139,0.15)';
            if (exitNodeHint) {
              exitNodeHint.style.display = 'block';
              exitNodeHint.innerHTML = '✅ Approved in Tailscale. Other devices on your Tailnet can now select this NAS as their Exit Node.';
              exitNodeHint.style.color = 'var(--ok2, #3bf58b)';
              exitNodeHint.style.background = 'rgba(59,245,139,0.08)';
              exitNodeHint.style.borderColor = 'rgba(59,245,139,0.25)';
            }
          } else if (ts.advertise_exit_node) {
            exitNodePill.innerHTML = '<a href="https://login.tailscale.com/admin/machines" target="_blank" rel="noopener noreferrer" style="color:#38bdf8; text-decoration:underline;">Pending Admin Approval ↗</a>';
            exitNodePill.style.color = '#38bdf8';
            exitNodePill.style.background = 'rgba(56,189,248,0.15)';
            if (exitNodeHint) {
              exitNodeHint.style.display = 'block';
              exitNodeHint.innerHTML = '⚠️ Exit node is advertised. To allow other devices to route traffic through this NAS, approve it in your <a href="https://login.tailscale.com/admin/machines" target="_blank" rel="noopener noreferrer" style="color:#38bdf8; text-decoration:underline; font-weight:700;">Tailscale Admin Console ↗</a> (Machines → Edit route settings → Use as exit node).';
              exitNodeHint.style.color = '#fbbf24';
              exitNodeHint.style.background = 'rgba(245,158,11,0.08)';
              exitNodeHint.style.borderColor = 'rgba(245,158,11,0.25)';
            }
          } else {
            exitNodePill.textContent = 'Inactive';
            exitNodePill.style.color = 'var(--muted)';
            exitNodePill.style.background = 'rgba(255,255,255,0.06)';
            if (exitNodeHint) exitNodeHint.style.display = 'none';
          }
        }

        // 3. Tailscale SSH
        const sshToggle = document.getElementById('ts-ssh-toggle');
        const sshPill = document.getElementById('ts-ssh-pill');
        if (sshToggle) sshToggle.checked = Boolean(ts.ssh_enabled);
        if (sshPill) {
          sshPill.textContent = ts.ssh_enabled ? 'Enabled' : 'Disabled';
          sshPill.style.color = ts.ssh_enabled ? '#3bf58b' : 'var(--muted)';
          sshPill.style.background = ts.ssh_enabled
            ? 'rgba(59,245,139,0.15)'
            : 'rgba(255,255,255,0.06)';
        }

        // 4. Tailscale Serve & Funnel
        const serveToggle = document.getElementById('ts-serve-toggle');
        const servePill = document.getElementById('ts-serve-pill');
        const serveBox = document.getElementById('ts-serve-url-box');
        const serveLink = document.getElementById('ts-serve-url-link');
        const funnelToggle = document.getElementById('ts-funnel-toggle');
        const funnelPill = document.getElementById('ts-funnel-pill');
        if (serveToggle) serveToggle.checked = Boolean(ts.serve_enabled);
        if (servePill) {
          servePill.textContent = ts.serve_enabled ? 'Active' : 'Disabled';
          servePill.style.color = ts.serve_enabled ? '#3bf58b' : 'var(--muted)';
          servePill.style.background = ts.serve_enabled
            ? 'rgba(59,245,139,0.15)'
            : 'rgba(255,255,255,0.06)';
        }
        if (serveBox && serveLink) {
          if (ts.serve_enabled && ts.serve_url) {
            serveBox.style.display = 'flex';
            serveLink.href = ts.serve_url;
            serveLink.textContent = ts.serve_url;
          } else {
            serveBox.style.display = 'none';
          }
        }
        if (funnelToggle) funnelToggle.checked = Boolean(ts.funnel_enabled);
        if (funnelPill) {
          funnelPill.textContent = ts.funnel_enabled ? 'Active' : 'Off';
          funnelPill.style.color = ts.funnel_enabled ? '#f87171' : 'var(--muted)';
          funnelPill.style.background = ts.funnel_enabled
            ? 'rgba(239,68,68,0.15)'
            : 'rgba(255,255,255,0.06)';
        }

        // 5. Taildrop Inbox
        window._tsTaildropDir = ts.taildrop_dir || '/mnt/user/appdata/tailscale/taildrop';
        const taildropBadge = document.getElementById('ts-taildrop-badge');
        const taildropList = document.getElementById('ts-taildrop-list');
        const files = ts.taildrop_files || [];
        const filesCount = ts.taildrop_files_count !== undefined ? ts.taildrop_files_count : files.length;
        if (taildropBadge) taildropBadge.textContent = `${filesCount} file(s)`;
        if (taildropList) {
          if (files.length === 0) {
            taildropList.innerHTML =
              '<div style="color:var(--muted); font-size:11px; text-align:center; padding:12px 0;">No files in Taildrop inbox yet.</div>';
          } else {
            taildropList.innerHTML = files
              .map(
                f => `
              <div class="taildrop-file-item" data-path="${escapeHtml(f.path || '')}" style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,0.05); font-size:11px; cursor:pointer; border-radius:4px; transition:background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.05)'" onmouseout="this.style.background='transparent'" title="Click to view folder in Files">
                <span style="font-weight:600; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:60%;" title="${escapeHtml(f.name)}">📄 ${escapeHtml(f.name)}</span>
                <span style="color:var(--muted); font-size:10.5px;">${escapeHtml(f.size_formatted)} · ${escapeHtml(f.modified_at)}</span>
              </div>
            `
              )
              .join('');
          }
        }

        // 6. Interactive Mesh Peer Directory
        window._tsPeersList = ts.peers || [];
        renderTailscalePeersTable(window._tsPeersList);
      } else {
        const isNeedsLogin = ts.backend_state === 'NeedsLogin';
        if (tsBadgeEl) {
          tsBadgeEl.textContent = isNeedsLogin ? 'Needs Login' : 'Disconnected';
          tsBadgeEl.style.color = '#f59e0b';
          tsBadgeEl.style.borderColor = 'rgba(245,158,11,0.3)';
        }
        if (tsPillEl) {
          tsPillEl.textContent = isNeedsLogin ? 'Login Required' : 'Disconnected';
          tsPillEl.style.color = '#f59e0b';
          tsPillEl.style.background = 'rgba(245,158,11,0.12)';
        }
        if (tsDeployBanner) tsDeployBanner.style.display = 'none';
        if (tsFormIntro) {
          tsFormIntro.textContent = isNeedsLogin
            ? 'Node authentication required. Click below to log in and link to your Tailnet:'
            : 'Join your Zero-Trust Tailnet with a pre-authenticated auth key:';
          tsFormIntro.style.color = isNeedsLogin ? '#f59e0b' : 'var(--muted)';
        }
        if (tsIpEl) tsIpEl.textContent = '--';
        if (tsCopyIpBtn) tsCopyIpBtn.style.display = 'none';
        if (tsTailnetEl) tsTailnetEl.textContent = '--';
        if (tsHostEl) tsHostEl.textContent = '--';
        if (tsPeersEl) tsPeersEl.textContent = '0 peers';
        if (tsConnectForm) tsConnectForm.style.display = 'flex';
        if (tsConnectedView) tsConnectedView.style.display = 'none';
        if (tsDownBtn) tsDownBtn.style.display = 'none';
        if (tsExtContainer) {
          tsExtContainer.style.display = 'none';
          tsExtContainer.dataset.active = '0';
        }
        if (tsPeersCard) {
          tsPeersCard.style.display = 'none';
          tsPeersCard.dataset.active = '0';
        }

        if (isNeedsLogin) {
          if (ts.auth_url) {
            if (tsAuthPrompt) tsAuthPrompt.style.display = 'block';
            if (tsAuthLink) tsAuthLink.href = ts.auth_url;
            if (tsCopyAuthUrlBtn) {
              tsCopyAuthUrlBtn.onclick = () => {
                if (navigator.clipboard?.writeText) {
                  navigator.clipboard.writeText(ts.auth_url);
                  showToast('Authorization link copied to clipboard.', 'success');
                }
              };
            }
            startTailscaleAuthPolling();
          }
          if (tsUpBtn) {
            tsUpBtn.textContent = '🔗 Log in to Tailscale';
            tsUpBtn.dataset.mode = 'login';
            tsUpBtn.dataset.authUrl = ts.auth_url || '';
          }
        } else {
          if (tsAuthPrompt) tsAuthPrompt.style.display = 'none';
          if (tsUpBtn) {
            tsUpBtn.textContent = '🚀 Connect Tailscale';
            tsUpBtn.dataset.mode = 'connect';
            tsUpBtn.dataset.authUrl = '';
          }
        }
      }
    }
  } catch (err) {
    console.debug('[MeshVPN] Tailscale query error:', err);
  }

  try {
    const res = await api.get('/api/network/mesh-vpn/wireguard/subnet-routing').catch(() => null);
    if (res && ipFwdEl) {
      const isFwd = Boolean(res.ip_forwarding);
      ipFwdEl.textContent = isFwd ? 'Active (Forwarding Enabled)' : 'Disabled';
      ipFwdEl.style.color = isFwd ? 'var(--ok2, #3bf58b)' : 'var(--muted, #64748b)';
      if (wgBadgeEl) {
        wgBadgeEl.textContent = res.enabled ? 'NAT Routing Active' : 'Curve25519 Ready';
        wgBadgeEl.style.color = res.enabled ? '#3bf58b' : '#38bdf8';
      }
      if (wgFwdPill) {
        wgFwdPill.textContent = res.enabled ? 'NAT Active' : 'Curve25519 Ready';
        wgFwdPill.style.color = res.enabled ? '#3bf58b' : '#38bdf8';
      }
    }
  } catch (e) {}

  async function deployTailscaleContainer(btn) {
    const authKey = tsAuthKeyInput ? tsAuthKeyInput.value.trim() : '';
    const hostname = tsHostnameInput ? tsHostnameInput.value.trim() : '';
    const acceptRoutes = tsAcceptRoutesCb ? tsAcceptRoutesCb.checked : true;
    const origText = btn ? btn.textContent : '';
    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Deploying Container...';
      }
      showToast('Deploying official Tailscale container to Docker...', 'info');

      const res = await api.post('/api/network/mesh-vpn/tailscale/deploy', {
        auth_key: authKey || null,
        hostname: hostname || null,
        accept_routes: acceptRoutes,
      });

      if (res && res.auth_url) {
        try {
          window.open(res.auth_url, '_blank', 'noopener,noreferrer');
        } catch (e) {
          console.warn('Popup blocked, falling back to on-screen prompt:', e);
        }
        if (tsAuthPrompt) tsAuthPrompt.style.display = 'block';
        if (tsAuthLink) tsAuthLink.href = res.auth_url;
        if (tsUpBtn) {
          tsUpBtn.dataset.authUrl = res.auth_url;
          tsUpBtn.dataset.mode = 'login';
          tsUpBtn.textContent = '🔗 Log in to Tailscale';
        }
        if (tsCopyAuthUrlBtn) {
          tsCopyAuthUrlBtn.onclick = () => {
            if (navigator.clipboard?.writeText) {
              navigator.clipboard.writeText(res.auth_url);
              showToast('Authorization link copied to clipboard.', 'success');
            }
          };
        }
        showToast('Tailscale deployed! Opening authorization window...', 'info');
        startTailscaleAuthPolling();
      } else {
        showToast('Tailscale container deployed and connected!', 'success');
        if (tsAuthPrompt) tsAuthPrompt.style.display = 'none';
        fetchAndRenderWireguard();
      }
    } catch (err) {
      showToast(`Tailscale deployment failed: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        if (btn.dataset.mode === 'login') {
          btn.textContent = '🔗 Log in to Tailscale';
        } else {
          btn.textContent = origText;
        }
      }
    }
  }

  function startTailscaleAuthPolling() {
    if (window._tsAuthPollInterval) clearInterval(window._tsAuthPollInterval);
    window._tsAuthPollInterval = setInterval(async () => {
      try {
        const mesh = await api.get('/api/network/mesh-vpn').catch(() => null);
        if (mesh && mesh.tailscale && mesh.tailscale.active) {
          clearInterval(window._tsAuthPollInterval);
          window._tsAuthPollInterval = null;
          if (tsAuthPrompt) tsAuthPrompt.style.display = 'none';
          showToast('Tailscale node successfully authorized and connected!', 'success');
          fetchAndRenderWireguard();
        } else if (mesh && mesh.tailscale && mesh.tailscale.auth_url && tsAuthLink && tsAuthLink.href !== mesh.tailscale.auth_url) {
          tsAuthLink.href = mesh.tailscale.auth_url;
          if (tsUpBtn) tsUpBtn.dataset.authUrl = mesh.tailscale.auth_url;
        }
      } catch (_) {}
    }, 2500);
  }

  if (tsDeployBtn && !tsDeployBtn._bound) {
    tsDeployBtn._bound = true;
    tsDeployBtn.addEventListener('click', () => deployTailscaleContainer(tsDeployBtn));
  }

  // Tailscale Up handler (single unified button for Deploy, Login, or Connect)
  if (tsUpBtn && !tsUpBtn._bound) {
    tsUpBtn._bound = true;
    tsUpBtn.addEventListener('click', async () => {
      const mode = tsUpBtn.dataset.mode;
      if (mode === 'deploy') {
        return deployTailscaleContainer(tsUpBtn);
      }

      const authKey = tsAuthKeyInput ? tsAuthKeyInput.value.trim() : '';
      const hostname = tsHostnameInput ? tsHostnameInput.value.trim() : '';
      const acceptRoutes = tsAcceptRoutesCb ? tsAcceptRoutesCb.checked : true;

      // If user clicked 'Log in to Tailscale' and we already have an authUrl stored
      if (mode === 'login' && !authKey && tsUpBtn.dataset.authUrl) {
        try {
          window.open(tsUpBtn.dataset.authUrl, '_blank', 'noopener,noreferrer');
        } catch (_) {}
        startTailscaleAuthPolling();
        return;
      }

      const origText = tsUpBtn.textContent;
      try {
        tsUpBtn.disabled = true;
        tsUpBtn.textContent = mode === 'login' ? '🔗 Opening Login...' : '🚀 Connecting...';
        const res = await api.post('/api/network/mesh-vpn/tailscale/up', {
          auth_key: authKey || null,
          hostname: hostname || null,
          accept_routes: acceptRoutes,
        });

        if (res && res.auth_url) {
          try {
            window.open(res.auth_url, '_blank', 'noopener,noreferrer');
          } catch (e) {
            console.warn('Popup blocked, falling back to on-screen prompt:', e);
          }
          if (tsAuthPrompt) tsAuthPrompt.style.display = 'block';
          if (tsAuthLink) tsAuthLink.href = res.auth_url;
          tsUpBtn.dataset.authUrl = res.auth_url;
          tsUpBtn.dataset.mode = 'login';
          tsUpBtn.textContent = '🔗 Log in to Tailscale';
          if (tsCopyAuthUrlBtn) {
            tsCopyAuthUrlBtn.onclick = () => {
              if (navigator.clipboard?.writeText) {
                navigator.clipboard.writeText(res.auth_url);
                showToast('Authorization link copied to clipboard.', 'success');
              }
            };
          }
          showToast('Tailscale login opened! Complete authorization in your browser.', 'info');
          startTailscaleAuthPolling();
        } else {
          showToast('Connected host to Tailscale mesh network.', 'success');
          if (tsAuthKeyInput) tsAuthKeyInput.value = '';
          fetchAndRenderWireguard();
        }
      } catch (err) {
        showToast(`Tailscale connection failed: ${err.message || 'Daemon error'}`, 'error');
      } finally {
        tsUpBtn.disabled = false;
        if (tsUpBtn.dataset.mode === 'login') {
          tsUpBtn.textContent = '🔗 Log in to Tailscale';
        } else if (tsUpBtn.dataset.mode === 'deploy') {
          tsUpBtn.textContent = '⚡ 1-Click Deploy Tailscale';
        } else {
          tsUpBtn.textContent = '🚀 Connect Tailscale';
        }
      }
    });
  }

  // Tailscale Down handler
  if (tsDownBtn && !tsDownBtn._bound) {
    tsDownBtn._bound = true;
    tsDownBtn.addEventListener('click', async () => {
      try {
        tsDownBtn.disabled = true;
        await api.post('/api/network/mesh-vpn/tailscale/down');
        showToast('Disconnected from Tailscale mesh network.', 'info');
        fetchAndRenderWireguard();
      } catch (err) {
        showToast(`Tailscale disconnection failed: ${err.message || 'Daemon error'}`, 'error');
      } finally {
        tsDownBtn.disabled = false;
      }
    });
  }

  // Copy Tailscale IP
  if (tsCopyIpBtn && !tsCopyIpBtn._bound) {
    tsCopyIpBtn._bound = true;
    tsCopyIpBtn.addEventListener('click', () => {
      const ip = tsIpEl ? tsIpEl.textContent.trim() : '';
      if (ip && ip !== '--') {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(ip);
        }
        showToast(`Copied Tailscale IP: ${ip}`, 'success');
      }
    });
  }

  // 7. Node Key Re-Auth button
  const btnTsReauth = document.getElementById('btn-ts-reauth');
  if (btnTsReauth && !btnTsReauth._bound) {
    btnTsReauth._bound = true;
    btnTsReauth.addEventListener('click', async () => {
      try {
        btnTsReauth.disabled = true;
        btnTsReauth.textContent = '⏳ ...';
        const res = await api.post('/api/network/mesh-vpn/tailscale/reauth');
        if (res && res.auth_url) {
          try {
            window.open(res.auth_url, '_blank', 'noopener,noreferrer');
          } catch (_) {}
          showToast('Re-authentication initiated. Complete in your browser.', 'info');
          startTailscaleAuthPolling();
        } else {
          showToast('Tailscale node re-authenticated successfully.', 'success');
          fetchAndRenderWireguard();
        }
      } catch (err) {
        showToast(`Re-authentication failed: ${err.message}`, 'error');
      } finally {
        btnTsReauth.disabled = false;
        btnTsReauth.textContent = '⚡ Re-auth';
      }
    });
  }

  // 1. Subnet Router Save & Toggle
  const btnTsSaveRoutes = document.getElementById('btn-ts-save-routes');
  const tsSubnetRoutesInput = document.getElementById('ts-subnet-routes-input');
  const tsSubnetRouterToggle = document.getElementById('ts-subnet-router-toggle');
  async function saveSubnetRoutes() {
    if (!tsSubnetRoutesInput || !tsSubnetRouterToggle) return;
    const routes = tsSubnetRoutesInput.value.trim();
    const enabled = tsSubnetRouterToggle.checked;
    try {
      if (btnTsSaveRoutes) {
        btnTsSaveRoutes.disabled = true;
        btnTsSaveRoutes.textContent = '⏳ ...';
      }
      await api.post('/api/network/mesh-vpn/tailscale/set-routes', { routes, enabled });
      showToast(
        enabled ? `Subnet routes advertised: ${routes}` : 'Subnet routes withdrawn.',
        'success'
      );
      fetchAndRenderWireguard();
    } catch (e) {
      showToast(`Failed to update subnet routes: ${e.message}`, 'error');
    } finally {
      if (btnTsSaveRoutes) {
        btnTsSaveRoutes.disabled = false;
        btnTsSaveRoutes.textContent = 'Save Subnets';
      }
    }
  }
  if (btnTsSaveRoutes && !btnTsSaveRoutes._bound) {
    btnTsSaveRoutes._bound = true;
    btnTsSaveRoutes.addEventListener('click', saveSubnetRoutes);
  }
  if (tsSubnetRouterToggle && !tsSubnetRouterToggle._bound) {
    tsSubnetRouterToggle._bound = true;
    tsSubnetRouterToggle.addEventListener('change', saveSubnetRoutes);
  }

  // 2. Exit Node Toggle
  const tsExitNodeToggle = document.getElementById('ts-exit-node-toggle');
  if (tsExitNodeToggle && !tsExitNodeToggle._bound) {
    tsExitNodeToggle._bound = true;
    tsExitNodeToggle.addEventListener('change', async () => {
      const enabled = tsExitNodeToggle.checked;
      try {
        await api.post('/api/network/mesh-vpn/tailscale/set-exit-node', { enabled });
        showToast(
          enabled ? 'Node advertised as Exit Node.' : 'Exit Node advertising disabled.',
          'success'
        );
        fetchAndRenderWireguard();
      } catch (e) {
        showToast(`Failed to set exit node: ${e.message}`, 'error');
      }
    });
  }

  // 3. Tailscale SSH Toggle
  const tsSshToggle = document.getElementById('ts-ssh-toggle');
  if (tsSshToggle && !tsSshToggle._bound) {
    tsSshToggle._bound = true;
    tsSshToggle.addEventListener('change', async () => {
      const enabled = tsSshToggle.checked;
      try {
        await api.post('/api/network/mesh-vpn/tailscale/set-ssh', { enabled });
        showToast(enabled ? 'Tailscale SSH enabled.' : 'Tailscale SSH disabled.', 'success');
        fetchAndRenderWireguard();
      } catch (e) {
        showToast(`Failed to toggle SSH: ${e.message}`, 'error');
      }
    });
  }

  // 4. Tailscale Serve & Funnel Toggles
  const tsServeToggle = document.getElementById('ts-serve-toggle');
  const tsFunnelToggle = document.getElementById('ts-funnel-toggle');
  async function triggerServeFunnelUpdate() {
    const serve = tsServeToggle ? tsServeToggle.checked : false;
    let funnel = tsFunnelToggle ? tsFunnelToggle.checked : false;
    if (funnel && !serve) {
      if (tsServeToggle) tsServeToggle.checked = true;
    }
    try {
      const res = await api.post('/api/network/mesh-vpn/tailscale/set-serve', {
        serve: tsServeToggle ? tsServeToggle.checked : true,
        funnel,
        port: 8082,
      });
      if (res && res.status === 'needs_approval' && res.approval_url) {
        if (tsServeToggle) tsServeToggle.checked = Boolean(res.serve_enabled);
        if (tsFunnelToggle) tsFunnelToggle.checked = Boolean(res.funnel_enabled);
        try {
          window.open(res.approval_url, '_blank', 'noopener,noreferrer');
        } catch (_) {}
        const featName = res.feature === 'funnel' ? 'Funnel' : 'Serve';
        showConfirmToast(
          `Tailscale ${featName} Approval Required`,
          `Tailscale ${featName} is not yet authorized on your Tailnet. Please approve this node in the Tailscale Admin Console:<br><br><a href="${escapeHtml(res.approval_url)}" target="_blank" rel="noopener noreferrer" style="color:#38bdf8; text-decoration:underline; font-weight:bold; word-break:break-all;">${escapeHtml(res.approval_url)}</a><br><br>After clicking Approve in Tailscale, re-enable this toggle to activate.`,
          () => {
            window.open(res.approval_url, '_blank', 'noopener,noreferrer');
          },
          null,
          { confirmText: 'Open Approval Page', cancelText: 'Close' }
        );
      } else if (res && res.status === 'error') {
        if (tsServeToggle) tsServeToggle.checked = Boolean(res.serve_enabled);
        if (tsFunnelToggle) tsFunnelToggle.checked = Boolean(res.funnel_enabled);
        showToast(`Tailscale configuration error: ${res.error || 'Operation failed'}`, 'error');
      } else {
        if (serve && !res.serve_enabled) {
          if (tsServeToggle) tsServeToggle.checked = false;
          showToast('Tailscale Serve could not be activated. Check tailscaled daemon status.', 'warn');
        } else {
          showToast(
            serve
              ? 'Tailscale HTTPS Serve enabled on port 8082.'
              : 'Tailscale Serve disabled.',
            'success'
          );
        }
      }
      fetchAndRenderWireguard();
    } catch (e) {
      showToast(`Failed to configure Tailscale Serve: ${e.message}`, 'error');
      fetchAndRenderWireguard();
    }
  }
  if (tsServeToggle && !tsServeToggle._bound) {
    tsServeToggle._bound = true;
    tsServeToggle.addEventListener('change', triggerServeFunnelUpdate);
  }
  if (tsFunnelToggle && !tsFunnelToggle._bound) {
    tsFunnelToggle._bound = true;
    tsFunnelToggle.addEventListener('change', () => {
      if (tsFunnelToggle.checked) {
        showConfirmToast(
          t('net.tailscale_funnel_warning_title', 'Enable Public Internet Funnel'),
          'Warning: Enabling Public Internet Funnel exposes your ZettNAS desktop port 8082 to the public internet. Ensure your superadmin password and 2FA are strong. Do you want to proceed?',
          () => {
            triggerServeFunnelUpdate();
          },
          () => {
            tsFunnelToggle.checked = false;
          }
        );
      } else {
        triggerServeFunnelUpdate();
      }
    });
  }

  const btnCopyServeUrl = document.getElementById('btn-copy-ts-serve-url');
  if (btnCopyServeUrl && !btnCopyServeUrl._bound) {
    btnCopyServeUrl._bound = true;
    btnCopyServeUrl.addEventListener('click', () => {
      const link = document.getElementById('ts-serve-url-link');
      const url = link ? link.href : '';
      if (url && url !== '#') {
        if (navigator.clipboard?.writeText) {
          navigator.clipboard.writeText(url);
          showToast('Tailscale HTTPS URL copied to clipboard.', 'success');
        }
      }
    });
  }

  // 5. Taildrop Inbox Actions
  const btnTsTaildropFetch = document.getElementById('btn-ts-taildrop-fetch');
  if (btnTsTaildropFetch && !btnTsTaildropFetch._bound) {
    btnTsTaildropFetch._bound = true;
    btnTsTaildropFetch.addEventListener('click', async () => {
      try {
        btnTsTaildropFetch.disabled = true;
        btnTsTaildropFetch.textContent = '⏳ ...';
        const res = await api.post('/api/network/mesh-vpn/tailscale/taildrop/receive');
        showToast(
          `Taildrop check completed. ${res.count || 0} file(s) available in inbox.`,
          'success'
        );
        fetchAndRenderWireguard();
      } catch (e) {
        showToast(`Failed to fetch Taildrop files: ${e.message}`, 'error');
      } finally {
        btnTsTaildropFetch.disabled = false;
        btnTsTaildropFetch.textContent = '📥 Fetch';
      }
    });
  }
  const btnTsTaildropOpen = document.getElementById('btn-ts-taildrop-open');
  if (btnTsTaildropOpen && !btnTsTaildropOpen._bound) {
    btnTsTaildropOpen._bound = true;
    btnTsTaildropOpen.addEventListener('click', () => {
      const targetDir = window._tsTaildropDir || '/mnt/user/appdata/tailscale/taildrop';
      if (typeof window.openFileManager === 'function') {
        window.openFileManager(targetDir);
      } else if (typeof window.navigateToPath === 'function') {
        window.navigateToPath(targetDir);
      } else {
        ZettEventBus.emit('window:open', { id: 'file-manager-window', path: targetDir });
      }
    });
  }

  const taildropListEl = document.getElementById('ts-taildrop-list');
  if (taildropListEl && !taildropListEl._bound) {
    taildropListEl._bound = true;
    taildropListEl.addEventListener('click', e => {
      const item = e.target.closest('.taildrop-file-item');
      if (item) {
        const targetDir = window._tsTaildropDir || '/mnt/user/appdata/tailscale/taildrop';
        if (typeof window.openFileManager === 'function') {
          window.openFileManager(targetDir);
        } else if (typeof window.navigateToPath === 'function') {
          window.navigateToPath(targetDir);
        } else {
          ZettEventBus.emit('window:open', { id: 'file-manager-window', path: targetDir });
        }
      }
    });
  }

  // 6. Peer search and Ping handler
  const tsPeerSearch = document.getElementById('ts-peer-search');
  if (tsPeerSearch && !tsPeerSearch._bound) {
    tsPeerSearch._bound = true;
    tsPeerSearch.addEventListener('input', () => {
      renderTailscalePeersTable(window._tsPeersList || [], tsPeerSearch.value);
    });
  }
  const tsPeersTableBody = document.getElementById('ts-peers-table-body');
  if (tsPeersTableBody && !tsPeersTableBody._bound) {
    tsPeersTableBody._bound = true;
    tsPeersTableBody.addEventListener('click', async e => {
      const pingBtn = e.target.closest('.btn-ping-peer');
      if (!pingBtn) return;
      const ip = pingBtn.dataset.peerIp;
      if (!ip) return;
      const safeIpId = ip.replace(/[^a-zA-Z0-9]/g, '_');
      const resSpan = document.getElementById(`latency-${safeIpId}`);
      try {
        pingBtn.disabled = true;
        pingBtn.textContent = '⏳ ...';
        if (resSpan) {
          resSpan.textContent = 'pinging...';
          resSpan.style.color = 'var(--muted)';
        }
        const res = await api.post('/api/network/mesh-vpn/tailscale/ping', { peer: ip });
        if (res && res.status === 'success') {
          if (resSpan) {
            resSpan.textContent = `⚡ ${res.latency}`;
            resSpan.style.color = res.is_direct ? 'var(--ok2, #3bf58b)' : '#f59e0b';
          }
          showToast(`Pinged ${ip}: ${res.latency} (${res.route || 'direct'})`, 'success');
        } else {
          if (resSpan) {
            resSpan.textContent = '❌ Failed';
            resSpan.style.color = '#f87171';
          }
          showToast(`Ping ${ip} failed or timed out.`, 'warning');
        }
      } catch (err) {
        if (resSpan) {
          resSpan.textContent = '❌ Error';
          resSpan.style.color = '#f87171';
        }
      } finally {
        pingBtn.disabled = false;
        pingBtn.textContent = '⚡ Ping';
      }
    });
  }

  // Mesh Service Filter switcher
  const filterContainer = document.getElementById('mesh-service-filter');
  if (filterContainer && !filterContainer._bound) {
    filterContainer._bound = true;
    const filterBtns = filterContainer.querySelectorAll('button[data-mesh-filter]');
    const tsHeader = document.getElementById('section-header-tailscale');
    const tsContainer = document.getElementById('network-tailscale-container');
    const tsExtended = document.getElementById('network-tailscale-extended');
    const tsPeersBlock = document.getElementById('tailscale-peers-card');
    const wgHeader = document.getElementById('section-header-wireguard');
    const wgContainer = document.getElementById('network-wireguard-container');

    filterBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mode = btn.dataset.meshFilter;
        if (mode === 'tailscale') {
          if (tsHeader) tsHeader.style.display = 'flex';
          if (tsContainer) tsContainer.style.display = 'grid';
          if (tsExtended && tsExtended.dataset.active === '1') tsExtended.style.display = 'grid';
          if (tsPeersBlock && tsPeersBlock.dataset.active === '1') tsPeersBlock.style.display = 'block';
          if (wgHeader) wgHeader.style.display = 'none';
          if (wgContainer) wgContainer.style.display = 'none';
        } else if (mode === 'wireguard') {
          if (tsHeader) tsHeader.style.display = 'none';
          if (tsContainer) tsContainer.style.display = 'none';
          if (tsExtended) tsExtended.style.display = 'none';
          if (tsPeersBlock) tsPeersBlock.style.display = 'none';
          if (wgHeader) wgHeader.style.display = 'flex';
          if (wgContainer) wgContainer.style.display = 'grid';
        } else {
          if (tsHeader) tsHeader.style.display = 'flex';
          if (tsContainer) tsContainer.style.display = 'grid';
          if (tsExtended && tsExtended.dataset.active === '1') tsExtended.style.display = 'grid';
          if (tsPeersBlock && tsPeersBlock.dataset.active === '1') tsPeersBlock.style.display = 'block';
          if (wgHeader) wgHeader.style.display = 'flex';
          if (wgContainer) wgContainer.style.display = 'grid';
        }
      });
    });
  }

  // Refresh button
  if (refreshBtn && !refreshBtn._bound) {
    refreshBtn._bound = true;
    refreshBtn.addEventListener('click', () => {
      fetchAndRenderWireguard();
      showToast('Mesh VPN telemetry refreshed.', 'info');
    });
  }

  if (genBtn && !genBtn._bound) {
    genBtn._bound = true;
    genBtn.addEventListener('click', async () => {
      try {
        genBtn.disabled = true;
        genBtn.textContent = '🔑 Generating...';
        const cfg = await api.post('/api/network/mesh-vpn/wireguard/client-config', {
          server_endpoint: (window.location.hostname || '127.0.0.1') + ':51820',
          client_address: '10.100.0.2/24',
          allowed_ips: '0.0.0.0/0',
          persistent_keepalive: 25,
        });

        const confText = cfg.config_text || cfg.config_content || '';
        if (previewEl) {
          previewEl.textContent = confText || JSON.stringify(cfg, null, 2);
        }
        if (pubkeyEl && cfg.public_key) {
          pubkeyEl.textContent = cfg.public_key;
        }

        const copyBtn = document.getElementById('btn-copy-wg-conf');
        if (copyBtn && confText) {
          copyBtn.style.display = 'inline-block';
          copyBtn.onclick = async () => {
            await copyTextToClipboard(confText);
            showToast('WireGuard client config copied to clipboard.', 'success');
          };
        }

        if (dlBtn && confText) {
          dlBtn.style.display = 'inline-block';
          dlBtn.onclick = () => {
            const blob = new Blob([confText], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${cfg.client_name || 'zettnas-client'}.conf`;
            a.click();
            URL.revokeObjectURL(url);
            showToast('Downloaded WireGuard .conf profile.', 'info');
          };
        }

        // Render QR Code (inline thumbnail and interactive click to enlarge)
        const qrBox = document.getElementById('wg-qr-box');
        const qrCanvasWrap = document.getElementById('wg-qr-canvas-wrap');
        const modalQr = document.getElementById('modal-wg-qr');
        const modalQrWrap = document.getElementById('modal-wg-qr-wrap');
        const modalQrCloseBtn = document.getElementById('modal-wg-qr-close-btn');
        const modalQrCopyBtn = document.getElementById('modal-wg-qr-copy-btn');
        const modalQrDlBtn = document.getElementById('modal-wg-qr-dl-btn');

        if (qrBox && qrCanvasWrap && confText) {
          try {
            const svgString = await QRCode.toString(confText, {
              type: 'svg',
              margin: 1,
              width: 120,
              color: {
                dark: '#000000',
                light: '#ffffff',
              },
            });
            qrCanvasWrap.innerHTML = svgString;
            qrBox.style.display = 'flex';

            const openQrModal = async () => {
              if (!modalQr) return;
              if (modalQrWrap) {
                const largeSvg = await QRCode.toString(confText, {
                  type: 'svg',
                  margin: 2,
                  width: 240,
                  color: { dark: '#000000', light: '#ffffff' },
                });
                modalQrWrap.innerHTML = largeSvg;
              }
              const modalWin = modalQr.querySelector('.smart-modal-window');
              const modalHdr = modalQr.querySelector('.smart-modal-header');
              if (modalWin && modalHdr) makeDraggable(modalWin, modalHdr, 'modal-wg-qr');
              modalQr.style.display = 'flex';
              modalQr.classList.add('open');

              const closeQrModal = () => {
                modalQr.style.display = 'none';
                modalQr.classList.remove('open');
              };
              if (modalQrCloseBtn) modalQrCloseBtn.onclick = closeQrModal;
              modalQr.onclick = (e) => {
                if (e.target === modalQr) closeQrModal();
              };
              if (modalQrCopyBtn) {
                modalQrCopyBtn.onclick = async () => {
                  await copyTextToClipboard(confText);
                  showToast('Copied WireGuard config to clipboard.', 'success');
                };
              }
              if (modalQrDlBtn) {
                modalQrDlBtn.onclick = () => {
                  const blob = new Blob([confText], { type: 'text/plain' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `${cfg.client_name || 'zettnas-client'}.conf`;
                  a.click();
                  URL.revokeObjectURL(url);
                  showToast('Exported WireGuard .conf profile.', 'info');
                };
              }
            };

            qrCanvasWrap.onclick = openQrModal;
          } catch (qrErr) {
            console.warn('[WireGuard] QR generation error:', qrErr);
          }
        }

        showToast('WireGuard Curve25519 client profile generated.', 'success');
      } catch (err) {
        showToast(`Failed to generate WireGuard config: ${err.message}`, 'error');
      } finally {
        genBtn.disabled = false;
        genBtn.textContent = '🔑 Generate Client .conf';
      }
    });
  }

  if (natBtn && !natBtn._bound) {
    natBtn._bound = true;
    natBtn.addEventListener('click', async () => {
      try {
        natBtn.disabled = true;
        const curStatus = await api.get('/api/network/mesh-vpn/wireguard/subnet-routing');
        const nextState = !Boolean(curStatus.enabled);
        const res = await api.post('/api/network/mesh-vpn/wireguard/subnet-routing', {
          enabled: nextState,
          interface: 'wg0',
          out_interface: 'eth0',
        });
        showToast(`WireGuard subnet routing ${res.enabled ? 'enabled' : 'disabled'}.`, 'info');
        fetchAndRenderWireguard();
      } catch (err) {
        showToast(`Subnet routing toggle failed: ${err.message}`, 'error');
      } finally {
        natBtn.disabled = false;
      }
    });
  }
}

export async function fetchAndRenderNetworkTopology() {
  const switchFaceplate = document.getElementById('network-switch-faceplate');
  const physicalTbody = document.getElementById('network-physical-tbody');
  const bridgesContainer = document.getElementById('network-bridges-container');
  const dockerContainer = document.getElementById('network-docker-container');
  const activeBadge = document.getElementById('net-active-ports-badge');

  // KPI elements
  const kpiIp = document.getElementById('net-kpi-ip');
  const kpiIface = document.getElementById('net-kpi-iface');
  const kpiGw = document.getElementById('net-kpi-gw');
  const kpiDns = document.getElementById('net-kpi-dns');
  const kpiSpeed = document.getElementById('net-kpi-speed');
  const kpiCarrier = document.getElementById('net-kpi-carrier');
  const kpiDocker = document.getElementById('net-kpi-docker');
  const kpiContainers = document.getElementById('net-kpi-containers');

  function fmtBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
  }

  try {
    const topo = await api.get('/api/system/network-topology');
    if (!topo || topo.status !== 'ok') {
      if (physicalTbody) {
        physicalTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--crit); padding:16px;">Failed to load network topology: ${escapeHtml(topo?.message || 'Unknown error')}</td></tr>`;
      }
      return;
    }

    const summary = topo.summary || {};
    const physical = topo.physical_interfaces || [];
    const bonds = topo.bonds || [];
    const bridges = topo.bridges || [];
    const dockerNets = topo.docker_networks || [];

    // 1. Update KPIs
    if (kpiIp) kpiIp.textContent = summary.primary_ip || '--';
    if (kpiIface) kpiIface.textContent = `Via ${summary.primary_interface || 'eth0'}`;
    if (kpiGw) kpiGw.textContent = summary.default_gateway || '--';
    if (kpiDns) kpiDns.textContent = `DNS: ${(summary.dns_servers || []).join(', ') || 'Auto'}`;
    if (kpiSpeed) kpiSpeed.textContent = summary.max_speed || '--';
    if (kpiCarrier) kpiCarrier.textContent = `${summary.active_physical || 0} of ${summary.total_physical || 0} Ports Online`;
    if (kpiDocker) kpiDocker.textContent = `${summary.docker_networks_count || 0} Networks`;
    if (kpiContainers) kpiContainers.textContent = `${summary.docker_containers_count || 0} Containers Attached`;
    if (activeBadge) activeBadge.textContent = `${summary.active_physical || 0} Active`;

    // Check if a canary watchdog test is active on host
    if (summary.canary && summary.canary.is_active && summary.canary.expires_in > 0) {
      const canaryModal = document.getElementById('network-canary-overlay');
      if (canaryModal && canaryModal.style.display !== 'flex') {
        openCanaryModal(summary.canary);
      }
    }

    // 2. Render Hardware Switch Ports (Front-Panel Faceplate)
    if (switchFaceplate) {
      if (physical.length === 0) {
        switchFaceplate.innerHTML = `<div style="color:var(--muted); font-size:12px; padding:12px;">No physical network interfaces detected.</div>`;
      } else {
        switchFaceplate.innerHTML = physical.map((nic) => {
          const isUp = Boolean(nic.is_up);
          const is10G = (nic.speed_mbps || 0) >= 2500;
          const speedPillClass = isUp ? (is10G ? 'speed-10g' : '') : 'speed-down';
          const linkLedClass = isUp ? 'led-link-on' : '';
          const speedLedClass = isUp ? (is10G ? 'led-speed-10g' : 'led-speed-gig') : '';

          return `
            <div class="switch-port-jack ${isUp ? 'is-active' : ''} clickable" data-iface="${escapeHtml(nic.name)}" title="Configure ${escapeHtml(nic.name)}">
              <div class="switch-port-top">
                <div class="switch-port-id">
                  <svg style="width:12px; height:12px; fill:${isUp ? 'var(--ok2, #3bf58b)' : 'var(--muted, #64748b)'};"><circle cx="6" cy="6" r="4"/></svg>
                  ${escapeHtml(nic.name.toUpperCase())}
                  ${nic.alias ? `<span class="switch-port-alias-tag" title="${escapeHtml(nic.alias)}">${escapeHtml(nic.alias)}</span>` : ''}
                </div>
                <div class="switch-port-leds">
                  <div class="switch-led-group">
                    <span class="switch-led-lbl">LNK</span>
                    <span class="switch-led-dot ${linkLedClass}"></span>
                  </div>
                  <div class="switch-led-group">
                    <span class="switch-led-lbl">ACT</span>
                    <span class="switch-led-dot ${speedLedClass}"></span>
                  </div>
                </div>
              </div>
              <div class="switch-port-socket">
                <svg viewBox="0 0 24 24">
                  <rect x="3" y="5" width="18" height="14" rx="2" />
                  <path d="M7 15v-4h10v4M9 11V8h6v3" />
                </svg>
              </div>
              <div class="switch-port-badge-row">
                <span class="switch-speed-pill ${speedPillClass}">${escapeHtml(nic.speed_human || (isUp ? 'Connected' : 'Disconnected'))}</span>
                <span style="font-size:10px; color:var(--muted);">${nic.duplex === 'full' ? 'Full Duplex' : nic.duplex}</span>
              </div>
              <div class="switch-port-meta">
                <div>MAC: ${escapeHtml(nic.mac || 'N/A')}</div>
                ${nic.master ? `<div style="color:var(--accent-cyan);">Master: ${escapeHtml(nic.master)}</div>` : ''}
              </div>
            </div>
          `;
        }).join('');

        switchFaceplate.querySelectorAll('.switch-port-jack.clickable').forEach((jack) => {
          jack.addEventListener('click', () => {
            const iface = jack.dataset.iface;
            if (iface) openNetworkPortModal(iface);
          });
        });
      }
    }

    // 3. Render Physical Interfaces Detailed Table
    if (physicalTbody) {
      if (physical.length === 0) {
        physicalTbody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--muted); padding:16px;">No physical interfaces found.</td></tr>`;
      } else {
        physicalTbody.innerHTML = physical.map((nic) => {
          const isUp = Boolean(nic.is_up);
          const rxFmt = fmtBytes(nic.rx_bytes);
          const txFmt = fmtBytes(nic.tx_bytes);

          return `
            <tr>
              <td>
                <div style="display:flex; align-items:center; gap:6px; font-weight:700; font-family:var(--font-mono, monospace);">
                  <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${isUp ? 'var(--ok2, #3bf58b)' : 'var(--muted, #64748b)'};"></span>
                  ${escapeHtml(nic.name)}
                </div>
              </td>
              <td>
                ${nic.alias ? `<span class="switch-port-alias-tag" title="${escapeHtml(nic.alias)}">${escapeHtml(nic.alias)}</span>` : '<span style="color:var(--muted); font-size:11px;">--</span>'}
              </td>
              <td>
                <span class="switch-speed-pill ${isUp ? 'speed-10g' : 'speed-down'}">
                  ${isUp ? 'UP / CARRIER' : 'DOWN'}
                </span>
              </td>
              <td>
                <span style="font-weight:600; color:${isUp ? '#f8fafc' : 'var(--muted)'};">${escapeHtml(nic.speed_human)}</span>
                <span style="font-size:10px; color:var(--muted); margin-left:4px;">(${escapeHtml(nic.duplex)})</span>
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:11px;">${escapeHtml(nic.mac || '--')}</td>
              <td style="font-family:var(--font-mono, monospace);">${escapeHtml(String(nic.mtu || 1500))}</td>
              <td>
                ${nic.master ? `<span class="network-member-pill" style="color:var(--accent-cyan); border-color:rgba(56,189,248,0.3);">${escapeHtml(nic.master)}</span>` : '<span style="color:var(--muted);">Standalone</span>'}
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:11px;">
                <div>↓ ${rxFmt} <span style="font-size:9.5px; color:var(--muted);">(${nic.rx_packets?.toLocaleString() || 0} pkts)</span></div>
                <div>↑ ${txFmt} <span style="font-size:9.5px; color:var(--muted);">(${nic.tx_packets?.toLocaleString() || 0} pkts)</span></div>
              </td>
              <td style="font-size:11px; color:var(--muted);">
                <div>${escapeHtml(nic.driver || 'Generic')}</div>
                <div style="font-family:var(--font-mono, monospace); font-size:9.5px;">${escapeHtml(nic.pci_slot || '--')}</div>
              </td>
              <td style="text-align: right;">
                <button class="btn-pill-toggle btn-config-port" data-iface="${escapeHtml(nic.name)}" style="font-size:10px; padding:2px 8px; color:var(--accent-cyan, #38bdf8); border-color:rgba(56,189,248,0.3);">${t('net.configure_port', 'Configure')}</button>
              </td>
            </tr>
          `;
        }).join('');

        physicalTbody.querySelectorAll('.btn-config-port').forEach((btn) => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const iface = btn.dataset.iface;
            if (iface) openNetworkPortModal(iface);
          });
        });
      }
    }

    // 4. Render Virtual Switches, Bonds & Bridges
    if (bridgesContainer) {
      const items = [];
      // Bridges
      bridges.forEach((br) => {
        items.push(`
          <div class="network-bridge-card">
            <div class="network-bridge-header">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="network-bridge-name">Bridge: ${escapeHtml(br.name)}</span>
                <span class="switch-speed-pill ${br.stp ? 'speed-10g' : 'speed-down'}" style="font-size:9.5px; padding:2px 6px;">STP: ${br.stp ? 'ON' : 'OFF'}</span>
                <span style="font-size:10px; color:var(--muted); font-family:var(--font-mono, monospace);">FD: ${br.forward_delay || 0}s</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span class="network-bridge-ip">${escapeHtml(br.ip_address || 'Unassigned IP')}</span>
                <button class="btn-pill-toggle btn-config-bridge" data-bridge="${escapeHtml(br.name)}" style="font-size:10px; padding:2px 8px; color:var(--accent-cyan, #38bdf8); border-color:rgba(56,189,248,0.3);">${t('net.configure_bridge', 'Configure')}</button>
              </div>
            </div>
            <div style="font-size:11px; color:var(--muted);">Member Ports:</div>
            <div class="network-bridge-members">
              ${(br.interfaces || []).map((m) => `<span class="network-member-pill">${escapeHtml(m)}</span>`).join('') || '<span style="color:var(--muted); font-size:10px;">No members</span>'}
            </div>
          </div>
        `);
      });

      // Bonds
      bonds.forEach((b) => {
        items.push(`
          <div class="network-bridge-card">
            <div class="network-bridge-header">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="network-bridge-name">Bond: ${escapeHtml(b.name)}</span>
                <span class="switch-speed-pill speed-10g" title="${escapeHtml(b.mode_title || b.mode_name || b.mode)}">${escapeHtml(b.mode_title || b.mode_name || b.mode || 'Bonding')}</span>
                <span style="font-size:10px; color:var(--muted); font-family:var(--font-mono, monospace);">${b.miimon || 100}ms</span>
              </div>
              <button class="btn-pill-toggle btn-config-bond" data-bond="${escapeHtml(b.name)}" style="font-size:10px; padding:2px 8px; color:var(--accent-cyan, #38bdf8); border-color:rgba(56,189,248,0.3);">${t('net.configure_bond', 'Configure')}</button>
            </div>
            <div style="font-size:11px; color:var(--muted);">Active Slave: <strong style="color:var(--ok2, #3bf58b);">${escapeHtml(b.active_slave || 'None')}</strong></div>
            <div class="network-bridge-members">
              ${(b.slaves || []).map((s) => `<span class="network-member-pill ${s === b.active_slave ? 'active' : ''}">${escapeHtml(s)}</span>`).join('')}
            </div>
          </div>
        `);
      });

      bridgesContainer.innerHTML = items.length > 0 ? items.join('') : `<div style="color:var(--muted); font-size:12px; padding:12px;">No virtual bridges or bonds configured.</div>`;

      bridgesContainer.querySelectorAll('.btn-config-bridge').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const br = btn.dataset.bridge;
          if (br) openBridgeConfigModal(br);
        });
      });

      bridgesContainer.querySelectorAll('.btn-config-bond').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const bond = btn.dataset.bond;
          if (bond) openBondConfigModal(bond);
        });
      });
    }

    // 5. Render VLAN Sub-Interfaces (802.1Q)
    const vlanTbody = document.getElementById('network-vlan-tbody');
    const vlans = topo.vlans || [];
    if (vlanTbody) {
      if (vlans.length === 0) {
        vlanTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--muted); padding:16px;">No 802.1Q VLAN sub-interfaces created yet. Click "+ Add VLAN" to tag an interface.</td></tr>`;
      } else {
        vlanTbody.innerHTML = vlans
          .map((v) => {
            const isUp = Boolean(v.is_up);
            const rxFmt = fmtBytes(v.rx_bytes);
            const txFmt = fmtBytes(v.tx_bytes);

            return `
            <tr>
              <td>
                <div style="display:flex; align-items:center; gap:6px; font-weight:700; font-family:var(--font-mono, monospace);">
                  <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${isUp ? 'var(--ok2, #3bf58b)' : 'var(--muted, #64748b)'};"></span>
                  ${escapeHtml(v.name)}
                </div>
              </td>
              <td>
                <span class="network-member-pill">${escapeHtml(v.parent)}</span>
              </td>
              <td>
                <span class="network-member-pill" style="color:var(--accent-cyan, #38bdf8); border-color:rgba(56,189,248,0.4); font-weight:700;">VID ${escapeHtml(String(v.vlan_id))}</span>
              </td>
              <td>
                ${v.alias ? `<span class="switch-port-alias-tag" title="${escapeHtml(v.alias)}">${escapeHtml(v.alias)}</span>` : '<span style="color:var(--muted); font-size:11px;">--</span>'}
              </td>
              <td>
                <span class="switch-speed-pill ${isUp ? 'speed-10g' : 'speed-down'}">
                  ${isUp ? 'UP' : 'DOWN'}
                </span>
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:11px;">${escapeHtml(v.ip_address || '--')}</td>
              <td style="font-family:var(--font-mono, monospace); font-size:11px;">
                <div>↓ ${rxFmt} / ↑ ${txFmt}</div>
              </td>
              <td style="text-align: right;">
                <button class="btn-pill-toggle btn-delete-vlan" data-vlan="${escapeHtml(v.name)}" style="font-size:10px; padding:2px 8px; color:#f87171; border-color:rgba(248,113,113,0.3);" title="Delete VLAN">🗑</button>
              </td>
            </tr>
          `;
          })
          .join('');

        vlanTbody.querySelectorAll('.btn-delete-vlan').forEach((btn) => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const vlan = btn.dataset.vlan;
            if (vlan) deleteVlanSubinterface(vlan);
          });
        });
      }
    }

    // 5. Render Docker Networks & Containers
    if (dockerContainer) {
      if (dockerNets.length === 0) {
        dockerContainer.innerHTML = `<div style="color:var(--muted); font-size:12px; padding:12px;">No active Docker bridge networks found.</div>`;
      } else {
        dockerContainer.innerHTML = dockerNets.map((net) => {
          const containers = net.containers || [];
          return `
            <div class="network-docker-card">
              <div class="network-docker-top">
                <div class="network-docker-name" style="display:flex; align-items:center; gap:8px;">
                  <svg class="ic" style="width:14px; height:14px;"><use href="#i-chip"/></svg>
                  ${escapeHtml(net.name)}
                  <span class="network-docker-driver">${escapeHtml(net.driver)}</span>
                  ${net.is_custom ? `<button class="net-docker-delete-btn" data-net-id="${escapeHtml(net.id)}" data-net-name="${escapeHtml(net.name)}" title="Delete Network">🗑</button>` : ''}
                </div>
                <div class="network-docker-cidr">
                  ${net.subnet ? `Subnet: <strong>${escapeHtml(net.subnet)}</strong>` : ''}
                  ${net.gateway ? ` • Gateway: <strong>${escapeHtml(net.gateway)}</strong>` : ''}
                  ${net.bridge_device ? ` • Dev: <strong>${escapeHtml(net.bridge_device)}</strong>` : ''}
                </div>
              </div>
              <div class="network-docker-containers">
                ${containers.length === 0 ? '<span style="font-size:11px; color:var(--muted);">No containers attached</span>' : containers.map((c) => `
                  <div class="network-container-chip">
                    <span class="network-chip-dot"></span>
                    <span class="network-chip-name">${escapeHtml(c.name)}</span>
                    <span class="network-chip-ip">${escapeHtml(c.ipv4 || 'Host')}</span>
                    ${c.ports?.length ? `<span class="network-chip-ports">[${escapeHtml(c.ports.join(', '))}]</span>` : ''}
                  </div>
                `).join('')}
              </div>
            </div>
          `;
        }).join('');

        dockerContainer.querySelectorAll('.net-docker-delete-btn').forEach((btn) => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const netId = btn.dataset.netId;
            const netName = btn.dataset.netName;
            if (!netId) return;
            showConfirmToast(`${t('net.delete_docker_confirm', 'Are you sure you want to delete Docker network')} "${netName}"?`, async () => {
              try {
                await api.delete(`/api/network/docker/${encodeURIComponent(netId)}`);
                showToast(t('net.docker_deleted_toast', 'Docker network deleted successfully'), 'success');
                fetchAndRenderNetworkTopology();
              } catch (err) {
                showToast(err.message || 'Failed to delete Docker network', 'error');
              }
            });
          });
        });
      }
    }

    const createDockerBtn = document.getElementById('btn-create-docker-net');
    if (createDockerBtn && !createDockerBtn.dataset.bound) {
      createDockerBtn.dataset.bound = '1';
      createDockerBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openDockerNetworkCreateModal();
      });
    }

    const btnOpenVlan = document.getElementById('btn-open-create-vlan-modal');
    if (btnOpenVlan && !btnOpenVlan.dataset.bound) {
      btnOpenVlan.dataset.bound = '1';
      btnOpenVlan.addEventListener('click', (e) => {
        e.stopPropagation();
        openCreateVlanModal();
      });
    }

    const btnOpenHostIp = document.getElementById('btn-open-host-ip-modal');
    if (btnOpenHostIp && !btnOpenHostIp.dataset.bound) {
      btnOpenHostIp.dataset.bound = '1';
      btnOpenHostIp.addEventListener('click', (e) => {
        e.stopPropagation();
        openHostIpConfigModal();
      });
    }

    fetchAndRenderWireguard();
    initNetworkControls();
  } catch (err) {
    console.warn('[ZettNAS] Error fetching network topology:', err);
    if (physicalTbody) {
      physicalTbody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--crit); padding:16px;">Failed to load network topology: ${escapeHtml(err.message || String(err))}</td></tr>`;
    }
  }
}

let _currentPortIface = null;

export async function openNetworkPortModal(ifaceName) {
  _currentPortIface = ifaceName;
  const overlay = document.getElementById('network-port-config-overlay');
  if (!overlay) return;

  const titleIface = document.getElementById('net-port-cfg-iface');
  const dot = document.getElementById('net-port-cfg-dot');
  const aliasInput = document.getElementById('net-port-alias-input');
  const mtuInput = document.getElementById('net-port-mtu-input');
  const wolToggle = document.getElementById('net-port-wol-toggle');
  const wolDesc = document.getElementById('net-port-wol-desc');
  const speedSelect = document.getElementById('net-port-speed-select');
  const roMac = document.getElementById('net-port-ro-mac');
  const roDriver = document.getElementById('net-port-ro-driver');
  const roPci = document.getElementById('net-port-ro-pci');
  const roLink = document.getElementById('net-port-ro-link');

  if (titleIface) titleIface.textContent = ifaceName.toUpperCase();

  overlay.classList.add('open');
  overlay.style.display = 'flex';

  try {
    const data = await api.get(`/api/network/port/${encodeURIComponent(ifaceName)}`);
    const nic = data.interface || {};

    if (dot) {
      dot.style.background = nic.is_up ? 'var(--ok2, #3bf58b)' : 'var(--muted, #64748b)';
    }

    if (aliasInput) aliasInput.value = data.alias || '';
    const mtuVal = data.mtu || nic.mtu || 1500;
    if (mtuInput) mtuInput.value = mtuVal;

    document.querySelectorAll('.net-mtu-preset').forEach((btn) => {
      btn.classList.toggle('active', Number(btn.dataset.mtu) === Number(mtuVal));
    });

    if (wolToggle) {
      wolToggle.checked = Boolean(data.wol_enabled);
      wolToggle.disabled = !data.wol_supported;
    }
    if (wolDesc) {
      wolDesc.textContent = data.wol_supported
        ? t('net.wol_hint', 'Permit network magic packet wakeups from sleep/standby.')
        : 'Wake-on-LAN is not supported by this hardware NIC.';
    }

    if (speedSelect) {
      if (data.autoneg) {
        speedSelect.value = 'auto';
      } else if (data.speed) {
        speedSelect.value = String(data.speed);
      } else {
        speedSelect.value = 'auto';
      }
    }

    if (roMac) roMac.textContent = nic.mac || '--';
    const copyMacBtn = document.getElementById('btn-copy-port-mac');
    if (copyMacBtn) {
      copyMacBtn.onclick = () => {
        const mac = nic.mac || roMac?.textContent;
        if (mac && mac !== '--') {
          navigator.clipboard.writeText(mac);
          showToast(`MAC address ${mac} copied to clipboard!`, 'info');
        } else {
          showToast('No MAC address available to copy', 'warn');
        }
      };
    }
    if (roDriver) roDriver.textContent = nic.driver || 'Generic';
    if (roPci) roPci.textContent = nic.pci_slot || '--';
    if (roLink) roLink.textContent = nic.is_up ? `${nic.speed_human || 'Connected'} (${nic.duplex || 'full'})` : 'Down / Disconnected';
  } catch (err) {
    showToast(`Failed to load port config: ${err.message || err}`, 'error');
  }
}

export function closeNetworkPortModal() {
  const overlay = document.getElementById('network-port-config-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
  _currentPortIface = null;
}

export async function saveNetworkPortConfig() {
  if (!_currentPortIface) return;
  const aliasInput = document.getElementById('net-port-alias-input');
  const mtuInput = document.getElementById('net-port-mtu-input');
  const wolToggle = document.getElementById('net-port-wol-toggle');
  const speedSelect = document.getElementById('net-port-speed-select');
  const saveBtn = document.getElementById('net-port-cfg-save-btn');

  const alias = aliasInput ? aliasInput.value.trim() : '';
  const mtu = mtuInput ? parseInt(mtuInput.value, 10) : 1500;
  const wol_enabled = wolToggle ? wolToggle.checked : false;
  const speedVal = speedSelect ? speedSelect.value : 'auto';
  const autoneg = speedVal === 'auto';
  const speed = autoneg ? null : parseInt(speedVal, 10);

  if (isNaN(mtu) || mtu < 68 || mtu > 9216) {
    showToast('MTU must be an integer between 68 and 9216', 'error');
    return;
  }

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
  }

  try {
    await api.post(`/api/network/port/${encodeURIComponent(_currentPortIface)}`, {
      alias,
      mtu,
      wol_enabled,
      autoneg,
      speed,
      duplex: 'full'
    });
    showToast(t('net.port_saved_toast', 'Port configuration saved successfully'), 'success');
    closeNetworkPortModal();
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to save port config', 'error');
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = t('net.save_port_cfg', 'Save & Apply');
    }
  }
}

export function openDockerNetworkCreateModal() {
  const overlay = document.getElementById('network-docker-create-overlay');
  if (!overlay) return;

  const nameInput = document.getElementById('net-docker-name-input');
  const driverSelect = document.getElementById('net-docker-driver-select');
  const subnetInput = document.getElementById('net-docker-subnet-input');
  const gwInput = document.getElementById('net-docker-gateway-input');

  if (nameInput) nameInput.value = '';
  if (driverSelect) driverSelect.value = 'bridge';
  if (subnetInput) subnetInput.value = '';
  if (gwInput) gwInput.value = '';

  overlay.classList.add('open');
  overlay.style.display = 'flex';
}

export function closeDockerNetworkCreateModal() {
  const overlay = document.getElementById('network-docker-create-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
}

export async function submitDockerNetworkCreate() {
  const nameInput = document.getElementById('net-docker-name-input');
  const driverSelect = document.getElementById('net-docker-driver-select');
  const subnetInput = document.getElementById('net-docker-subnet-input');
  const gwInput = document.getElementById('net-docker-gateway-input');
  const submitBtn = document.getElementById('net-docker-create-submit-btn');

  const name = nameInput ? nameInput.value.trim() : '';
  const driver = driverSelect ? driverSelect.value : 'bridge';
  const subnet = subnetInput ? subnetInput.value.trim() : '';
  const gateway = gwInput ? gwInput.value.trim() : '';

  if (!name) {
    showToast('Please enter a network name', 'error');
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Creating...';
  }

  try {
    await api.post('/api/network/docker/create', { name, driver, subnet, gateway });
    showToast(t('net.docker_created_toast', 'Docker network created successfully'), 'success');
    closeDockerNetworkCreateModal();
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to create Docker network', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = t('net.create_btn', '+ Create Network');
    }
  }
}

let _canaryInterval = null;
let _currentCanaryId = null;

export async function openHostIpConfigModal() {
  const overlay = document.getElementById('network-host-config-overlay');
  if (!overlay) return;

  const btnStatic = document.getElementById('net-proto-btn-static');
  const btnDhcp = document.getElementById('net-proto-btn-dhcp');
  const ifaceSelect = document.getElementById('net-host-iface-select');
  const ipInput = document.getElementById('net-host-ip-input');
  const netmaskInput = document.getElementById('net-host-netmask-input');
  const gwInput = document.getElementById('net-host-gateway-input');
  const dns1Input = document.getElementById('net-host-dns1-input');
  const dns2Input = document.getElementById('net-host-dns2-input');
  const staticFields = document.getElementById('net-host-static-fields');

  try {
    const data = await api.get('/api/network/host/config');
    const isDhcp = data.mode === 'dhcp';

    if (btnStatic && btnDhcp) {
      btnStatic.classList.toggle('active', !isDhcp);
      btnDhcp.classList.toggle('active', isDhcp);
    }
    if (staticFields) {
      staticFields.style.opacity = isDhcp ? '0.4' : '1';
      staticFields.style.pointerEvents = isDhcp ? 'none' : 'auto';
    }

    if (ifaceSelect) {
      const ifaces = data.available_interfaces || ['br0', 'eth0'];
      ifaceSelect.innerHTML = ifaces
        .map((iface) => `<option value="${escapeHtml(iface)}" ${iface === data.interface ? 'selected' : ''}>${escapeHtml(iface.toUpperCase())}</option>`)
        .join('');
    }

    if (ipInput) ipInput.value = data.ip_address || '';
    if (netmaskInput) netmaskInput.value = data.netmask || '255.255.255.0';
    if (gwInput) gwInput.value = data.gateway || '';
    if (dns1Input) dns1Input.value = data.dns1 || (data.dns_servers && data.dns_servers[0]) || '';
    if (dns2Input) dns2Input.value = data.dns2 || (data.dns_servers && data.dns_servers[1]) || '';

    // Set active CIDR preset
    document.querySelectorAll('.net-cidr-preset').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.netmask === (data.netmask || '255.255.255.0'));
    });

    overlay.classList.add('open');
    overlay.style.display = 'flex';
  } catch (err) {
    showToast(`Failed to load host network config: ${err.message || err}`, 'error');
  }
}

export function closeHostIpConfigModal() {
  const overlay = document.getElementById('network-host-config-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
}

export async function applyHostIpConfig() {
  const btnStatic = document.getElementById('net-proto-btn-static');
  const isStatic = btnStatic ? btnStatic.classList.contains('active') : true;
  const mode = isStatic ? 'static' : 'dhcp';
  const ifaceSelect = document.getElementById('net-host-iface-select');
  const ipInput = document.getElementById('net-host-ip-input');
  const netmaskInput = document.getElementById('net-host-netmask-input');
  const gwInput = document.getElementById('net-host-gateway-input');
  const dns1Input = document.getElementById('net-host-dns1-input');
  const dns2Input = document.getElementById('net-host-dns2-input');
  const applyBtn = document.getElementById('net-host-cfg-apply-btn');

  const iface = ifaceSelect ? ifaceSelect.value : 'br0';
  const ip = ipInput ? ipInput.value.trim() : '';
  const netmask = netmaskInput ? netmaskInput.value.trim() : '255.255.255.0';
  const gateway = gwInput ? gwInput.value.trim() : '';
  const dns1 = dns1Input ? dns1Input.value.trim() : '';
  const dns2 = dns2Input ? dns2Input.value.trim() : '';

  if (mode === 'static' && !ip) {
    showToast('Please enter an IPv4 address', 'error');
    return;
  }

  if (applyBtn) {
    applyBtn.disabled = true;
    applyBtn.textContent = 'Arming Watchdog...';
  }

  try {
    const res = await api.post('/api/network/host/apply', {
      mode,
      interface: iface,
      ip_address: ip,
      netmask,
      gateway,
      dns1,
      dns2,
      timeout_sec: 60
    });

    closeHostIpConfigModal();
    openCanaryModal(res);
  } catch (err) {
    showToast(err.message || 'Failed to apply host network configuration', 'error');
  } finally {
    if (applyBtn) {
      applyBtn.disabled = false;
      applyBtn.textContent = t('net.apply_canary_btn', 'Test & Apply (60s Canary)');
    }
  }
}

export function openCanaryModal(canaryData) {
  const overlay = document.getElementById('network-canary-overlay');
  if (!overlay) return;

  _currentCanaryId = canaryData?.canary_id || null;
  let remaining = canaryData?.expires_in || 60;

  const digits = document.getElementById('net-canary-timer-digits');
  const circle = document.getElementById('net-canary-timer-circle');
  const targetUrlEl = document.getElementById('net-canary-target-url');
  const openLink = document.getElementById('net-canary-open-link');
  const revertingMsg = document.getElementById('net-canary-reverting-msg');
  const confirmBtn = document.getElementById('net-canary-confirm-btn');

  if (revertingMsg) revertingMsg.style.display = 'none';
  if (confirmBtn) confirmBtn.disabled = false;
  if (circle) circle.classList.remove('danger');
  if (digits) digits.textContent = String(remaining);

  const targetUrl = canaryData?.target_url || (canaryData?.target_ip ? `http://${canaryData.target_ip}:8082` : window.location.origin);
  if (targetUrlEl) targetUrlEl.textContent = targetUrl;
  if (openLink) openLink.href = targetUrl;

  overlay.classList.add('open');
  overlay.style.display = 'flex';

  if (_canaryInterval) {
    clearInterval(_canaryInterval);
    _canaryInterval = null;
  }

  _canaryInterval = setInterval(() => {
    remaining -= 1;
    if (digits) digits.textContent = String(Math.max(0, remaining));

    if (remaining <= 15 && circle) {
      circle.classList.add('danger');
    }

    if (remaining <= 0) {
      clearInterval(_canaryInterval);
      _canaryInterval = null;
      if (revertingMsg) revertingMsg.style.display = 'block';
      if (confirmBtn) confirmBtn.disabled = true;
      showToast(t('net.canary_reverted_toast', 'Host network settings reverted to previous configuration.'), 'info');
      setTimeout(() => {
        closeCanaryModal();
        fetchAndRenderNetworkTopology();
      }, 3500);
    }
  }, 1000);
}

export function closeCanaryModal() {
  if (_canaryInterval) {
    clearInterval(_canaryInterval);
    _canaryInterval = null;
  }
  const overlay = document.getElementById('network-canary-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
  _currentCanaryId = null;
}

export async function confirmCanaryConfig() {
  const confirmBtn = document.getElementById('net-canary-confirm-btn');
  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Confirming...';
  }

  try {
    await api.post('/api/network/host/confirm', { canary_id: _currentCanaryId });
    showToast(t('net.canary_confirmed_toast', 'Host network settings confirmed and permanently saved.'), 'success');
    closeCanaryModal();
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to confirm host network configuration', 'error');
  } finally {
    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = t('net.canary_confirm_btn', 'Confirm & Keep Settings');
    }
  }
}

export async function revertCanaryConfig() {
  const revertBtn = document.getElementById('net-canary-revert-btn');
  if (revertBtn) {
    revertBtn.disabled = true;
    revertBtn.textContent = 'Reverting...';
  }

  try {
    await api.post('/api/network/host/revert', { canary_id: _currentCanaryId });
    showToast(t('net.canary_reverted_toast', 'Host network settings reverted to previous configuration.'), 'info');
    closeCanaryModal();
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to revert host network configuration', 'error');
  } finally {
    if (revertBtn) {
      revertBtn.disabled = false;
      revertBtn.textContent = t('net.canary_revert_btn', 'Revert Changes Now');
    }
  }
}

let _currentBondName = null;
let _currentBridgeName = null;

export async function openBondConfigModal(bondName) {
  _currentBondName = bondName;
  const overlay = document.getElementById('network-bond-config-overlay');
  if (!overlay) return;

  const targetBadge = document.getElementById('net-bond-target-badge');
  const modeSelect = document.getElementById('net-bond-mode-select');
  const modeDesc = document.getElementById('net-bond-mode-desc');
  const slavesContainer = document.getElementById('net-bond-slaves-container');
  const miimonInput = document.getElementById('net-bond-miimon-input');

  if (targetBadge) targetBadge.textContent = bondName;

  try {
    const data = await api.get(`/api/network/bond/${encodeURIComponent(bondName)}`);
    if (modeSelect) {
      modeSelect.value = String(data.mode || '1');
      const activeMode = (data.available_modes || []).find((m) => String(m.code) === String(data.mode));
      if (modeDesc && activeMode) modeDesc.textContent = activeMode.description;
    }
    if (miimonInput) miimonInput.value = data.miimon || 100;

    if (slavesContainer) {
      const candidates = data.candidate_slaves || [];
      if (candidates.length === 0) {
        slavesContainer.innerHTML = '<div style="color:var(--muted); font-size:11px;">No physical Ethernet adapters detected.</div>';
      } else {
        slavesContainer.innerHTML = candidates
          .map((nic) => {
            const isChecked = Boolean(nic.is_slave);
            return `
            <label style="display:flex; align-items:center; gap:8px; font-size:11.5px; cursor:pointer; user-select:none;">
              <input type="checkbox" class="net-bond-slave-checkbox" value="${escapeHtml(nic.name)}" ${isChecked ? 'checked' : ''} style="cursor:pointer;" />
              <span style="font-family:var(--font-mono, monospace); font-weight:600; color:#f8fafc;">${escapeHtml(nic.name)}</span>
              ${nic.alias ? `<span class="switch-port-alias-tag">${escapeHtml(nic.alias)}</span>` : ''}
              <span style="font-size:10px; color:var(--muted); margin-left:auto;">${escapeHtml(nic.speed_human || (nic.is_up ? 'Connected' : 'Disconnected'))}</span>
            </label>
          `;
          })
          .join('');
      }
    }

    overlay.classList.add('open');
    overlay.style.display = 'flex';
  } catch (err) {
    showToast(`Failed to load bond configuration: ${err.message || err}`, 'error');
  }
}

export function closeBondConfigModal() {
  const overlay = document.getElementById('network-bond-config-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
  _currentBondName = null;
}

export async function saveBondConfig() {
  if (!_currentBondName) return;
  const modeSelect = document.getElementById('net-bond-mode-select');
  const miimonInput = document.getElementById('net-bond-miimon-input');
  const saveBtn = document.getElementById('net-bond-cfg-save-btn');

  const mode = modeSelect ? modeSelect.value : '1';
  const miimon = miimonInput ? parseInt(miimonInput.value, 10) : 100;

  const slaves = [];
  document.querySelectorAll('.net-bond-slave-checkbox:checked').forEach((cb) => {
    slaves.push(cb.value);
  });

  if (slaves.length === 0) {
    showToast('Please select at least one physical interface for the bond', 'error');
    return;
  }

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
  }

  try {
    await api.post(`/api/network/bond/${encodeURIComponent(_currentBondName)}`, {
      mode,
      slaves,
      miimon
    });
    showToast(t('net.bond_saved_toast', 'Bonding configuration saved successfully'), 'success');
    closeBondConfigModal();
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to save bond configuration', 'error');
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = t('net.save_bond_btn', 'Save Bonding Config');
    }
  }
}

export async function openBridgeConfigModal(brName) {
  _currentBridgeName = brName;
  const overlay = document.getElementById('network-bridge-config-overlay');
  if (!overlay) return;

  const targetBadge = document.getElementById('net-bridge-target-badge');
  const btnEnable = document.getElementById('net-stp-btn-enable');
  const btnDisable = document.getElementById('net-stp-btn-disable');
  const fdInput = document.getElementById('net-bridge-fd-input');
  const membersContainer = document.getElementById('net-bridge-members-container');

  if (targetBadge) targetBadge.textContent = brName;

  try {
    const data = await api.get(`/api/network/bridge/${encodeURIComponent(brName)}`);
    const stp = Boolean(data.stp);

    if (btnEnable && btnDisable) {
      btnEnable.classList.toggle('active', stp);
      btnDisable.classList.toggle('active', !stp);
    }
    if (fdInput) fdInput.value = data.forward_delay || 0;

    if (membersContainer) {
      const candidates = data.candidate_members || [];
      if (candidates.length === 0) {
        membersContainer.innerHTML = '<div style="color:var(--muted); font-size:11px;">No interfaces available to bridge.</div>';
      } else {
        membersContainer.innerHTML = candidates
          .map((cand) => {
            const isChecked = Boolean(cand.is_member);
            return `
            <label style="display:flex; align-items:center; gap:8px; font-size:11.5px; cursor:pointer; user-select:none;">
              <input type="checkbox" class="net-bridge-member-checkbox" value="${escapeHtml(cand.name)}" ${isChecked ? 'checked' : ''} style="cursor:pointer;" />
              <span style="font-family:var(--font-mono, monospace); font-weight:600; color:#f8fafc;">${escapeHtml(cand.name)}</span>
              <span class="network-member-pill" style="font-size:9px; padding:1px 5px;">${escapeHtml(cand.type || 'interface')}</span>
              ${cand.alias ? `<span class="switch-port-alias-tag">${escapeHtml(cand.alias)}</span>` : ''}
              <span style="font-size:10px; color:var(--muted); margin-left:auto;">${escapeHtml(cand.speed_human || (cand.is_up ? 'Connected' : 'Disconnected'))}</span>
            </label>
          `;
          })
          .join('');
      }
    }

    overlay.classList.add('open');
    overlay.style.display = 'flex';
  } catch (err) {
    showToast(`Failed to load bridge configuration: ${err.message || err}`, 'error');
  }
}

export function closeBridgeConfigModal() {
  const overlay = document.getElementById('network-bridge-config-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
  _currentBridgeName = null;
}

export async function saveBridgeConfig() {
  if (!_currentBridgeName) return;
  const btnEnable = document.getElementById('net-stp-btn-enable');
  const fdInput = document.getElementById('net-bridge-fd-input');
  const saveBtn = document.getElementById('net-bridge-cfg-save-btn');

  const stp = btnEnable ? btnEnable.classList.contains('active') : false;
  const forward_delay = fdInput ? parseInt(fdInput.value, 10) : 0;

  const members = [];
  document.querySelectorAll('.net-bridge-member-checkbox:checked').forEach((cb) => {
    members.push(cb.value);
  });

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
  }

  try {
    await api.post(`/api/network/bridge/${encodeURIComponent(_currentBridgeName)}`, {
      stp,
      forward_delay,
      members
    });
    showToast(t('net.bridge_saved_toast', 'Bridge configuration saved successfully'), 'success');
    closeBridgeConfigModal();
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to save bridge configuration', 'error');
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = t('net.save_bridge_btn', 'Save Bridge Config');
    }
  }
}

export async function openCreateVlanModal() {
  const overlay = document.getElementById('network-vlan-create-overlay');
  if (!overlay) return;

  const parentSelect = document.getElementById('net-vlan-parent-select');
  const idInput = document.getElementById('net-vlan-id-input');
  const aliasInput = document.getElementById('net-vlan-alias-input');

  if (idInput) idInput.value = '';
  if (aliasInput) aliasInput.value = '';

  overlay.classList.add('open');
  overlay.style.display = 'flex';

  try {
    const topo = await api.get('/api/system/network-topology');
    if (parentSelect && topo) {
      const parents = [];
      (topo.physical_interfaces || []).forEach((p) => parents.push({ name: p.name, type: 'Physical NIC' }));
      (topo.bonds || []).forEach((b) => parents.push({ name: b.name, type: 'Bonding Group' }));
      (topo.bridges || []).forEach((br) => parents.push({ name: br.name, type: 'Virtual Bridge' }));

      parentSelect.innerHTML = parents
        .map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} (${escapeHtml(item.type)})</option>`)
        .join('');
    }
  } catch (err) {
    showToast(`Failed to open VLAN creator: ${err.message || err}`, 'error');
  }
}

export function closeCreateVlanModal() {
  const overlay = document.getElementById('network-vlan-create-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
}

export async function submitCreateVlan() {
  const parentSelect = document.getElementById('net-vlan-parent-select');
  const idInput = document.getElementById('net-vlan-id-input');
  const aliasInput = document.getElementById('net-vlan-alias-input');
  const submitBtn = document.getElementById('net-vlan-create-submit-btn');

  const parent = parentSelect ? parentSelect.value : '';
  const vid = idInput ? parseInt(idInput.value, 10) : 0;
  const alias = aliasInput ? aliasInput.value.trim() : '';

  if (!parent) {
    showToast('Please select a parent trunk interface', 'error');
    return;
  }
  if (isNaN(vid) || vid < 1 || vid > 4094) {
    showToast('VLAN ID must be an integer between 1 and 4094', 'error');
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Creating...';
  }

  try {
    await api.post('/api/network/vlan/create', { parent, vlan_id: vid, alias });
    showToast(t('net.vlan_created_toast', 'VLAN sub-interface created successfully'), 'success');
    closeCreateVlanModal();
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to create VLAN sub-interface', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = t('net.create_vlan_btn', '+ Create VLAN Sub-Interface');
    }
  }
}

export async function deleteVlanSubinterface(vlanName) {
  showConfirmToast(
    t('net.delete_vlan_title', 'Delete VLAN Sub-Interface'),
    `${t('net.delete_vlan_confirm', 'Are you sure you want to delete VLAN sub-interface')} "${vlanName}"?`,
    async () => {
      try {
        await api.delete(`/api/network/vlan/${encodeURIComponent(vlanName)}`);
        showToast(t('net.vlan_deleted_toast', 'VLAN sub-interface removed successfully'), 'success');
        fetchAndRenderNetworkTopology();
      } catch (err) {
        showToast(err.message || 'Failed to delete VLAN sub-interface', 'error');
      }
    }
  );
}

export function initNetworkControls() {
  initNetworkPortsInspector();
  const portsBtn = document.querySelector('[data-tab-target="mgmt-pane-network-ports"]');
  if (portsBtn && !portsBtn.dataset.boundFetch) {
    portsBtn.dataset.boundFetch = '1';
    portsBtn.addEventListener('click', () => fetchListeningPorts());
  }
  const btnOpenHostIp = document.getElementById('btn-open-host-ip-modal');
  if (btnOpenHostIp && !btnOpenHostIp.dataset.bound) {
    btnOpenHostIp.dataset.bound = '1';
    btnOpenHostIp.addEventListener('click', (e) => {
      e.stopPropagation();
      openHostIpConfigModal();
    });
  }

  const kpiIpCard = document.getElementById('net-kpi-ip-card');
  if (kpiIpCard && !kpiIpCard.dataset.bound) {
    kpiIpCard.dataset.bound = '1';
    kpiIpCard.addEventListener('click', () => openHostIpConfigModal());
  }

  const hostIpClose = document.getElementById('net-host-cfg-close-btn');
  if (hostIpClose && !hostIpClose.dataset.bound) {
    hostIpClose.dataset.bound = '1';
    hostIpClose.addEventListener('click', closeHostIpConfigModal);
  }

  const hostIpCancel = document.getElementById('net-host-cfg-cancel-btn');
  if (hostIpCancel && !hostIpCancel.dataset.bound) {
    hostIpCancel.dataset.bound = '1';
    hostIpCancel.addEventListener('click', closeHostIpConfigModal);
  }

  const hostIpApply = document.getElementById('net-host-cfg-apply-btn');
  if (hostIpApply && !hostIpApply.dataset.bound) {
    hostIpApply.dataset.bound = '1';
    hostIpApply.addEventListener('click', applyHostIpConfig);
  }

  const btnStatic = document.getElementById('net-proto-btn-static');
  const btnDhcp = document.getElementById('net-proto-btn-dhcp');
  const staticFields = document.getElementById('net-host-static-fields');

  if (btnStatic && !btnStatic.dataset.bound) {
    btnStatic.dataset.bound = '1';
    btnStatic.addEventListener('click', () => {
      btnStatic.classList.add('active');
      if (btnDhcp) btnDhcp.classList.remove('active');
      if (staticFields) {
        staticFields.style.opacity = '1';
        staticFields.style.pointerEvents = 'auto';
      }
    });
  }

  if (btnDhcp && !btnDhcp.dataset.bound) {
    btnDhcp.dataset.bound = '1';
    btnDhcp.addEventListener('click', () => {
      btnDhcp.classList.add('active');
      if (btnStatic) btnStatic.classList.remove('active');
      if (staticFields) {
        staticFields.style.opacity = '0.4';
        staticFields.style.pointerEvents = 'none';
      }
    });
  }

  document.querySelectorAll('.net-cidr-preset').forEach((btn) => {
    if (!btn.dataset.bound) {
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => {
        const netmaskInput = document.getElementById('net-host-netmask-input');
        if (netmaskInput && btn.dataset.netmask) {
          netmaskInput.value = btn.dataset.netmask;
          document.querySelectorAll('.net-cidr-preset').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
        }
      });
    }
  });

  document.querySelectorAll('.net-dns-preset').forEach((btn) => {
    if (!btn.dataset.bound) {
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => {
        const dns1Input = document.getElementById('net-host-dns1-input');
        const dns2Input = document.getElementById('net-host-dns2-input');
        if (dns1Input && btn.dataset.dns1) dns1Input.value = btn.dataset.dns1;
        if (dns2Input && btn.dataset.dns2) dns2Input.value = btn.dataset.dns2;
        document.querySelectorAll('.net-dns-preset').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
      });
    }
  });

  const canaryConfirm = document.getElementById('net-canary-confirm-btn');
  if (canaryConfirm && !canaryConfirm.dataset.bound) {
    canaryConfirm.dataset.bound = '1';
    canaryConfirm.addEventListener('click', confirmCanaryConfig);
  }

  const canaryRevert = document.getElementById('net-canary-revert-btn');
  if (canaryRevert && !canaryRevert.dataset.bound) {
    canaryRevert.dataset.bound = '1';
    canaryRevert.addEventListener('click', revertCanaryConfig);
  }

  const portClose = document.getElementById('net-port-cfg-close-btn');
  if (portClose && !portClose.dataset.bound) {
    portClose.dataset.bound = '1';
    portClose.addEventListener('click', closeNetworkPortModal);
  }

  const portCancel = document.getElementById('net-port-cfg-cancel-btn');
  if (portCancel && !portCancel.dataset.bound) {
    portCancel.dataset.bound = '1';
    portCancel.addEventListener('click', closeNetworkPortModal);
  }

  const portSave = document.getElementById('net-port-cfg-save-btn');
  if (portSave && !portSave.dataset.bound) {
    portSave.dataset.bound = '1';
    portSave.addEventListener('click', saveNetworkPortConfig);
  }

  const mtuInput = document.getElementById('net-port-mtu-input');
  if (mtuInput && !mtuInput.dataset.bound) {
    mtuInput.dataset.bound = '1';
    mtuInput.addEventListener('input', () => {
      const val = Number(mtuInput.value);
      document.querySelectorAll('.net-mtu-preset').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.mtu) === val);
      });
    });
  }

  document.querySelectorAll('.net-mtu-preset').forEach((btn) => {
    if (!btn.dataset.bound) {
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => {
        const mtuVal = btn.dataset.mtu;
        if (mtuInput && mtuVal) {
          mtuInput.value = mtuVal;
          document.querySelectorAll('.net-mtu-preset').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
        }
      });
    }
  });

  const dockerClose = document.getElementById('net-docker-create-close-btn');
  if (dockerClose && !dockerClose.dataset.bound) {
    dockerClose.dataset.bound = '1';
    dockerClose.addEventListener('click', closeDockerNetworkCreateModal);
  }

  const dockerCancel = document.getElementById('net-docker-create-cancel-btn');
  if (dockerCancel && !dockerCancel.dataset.bound) {
    dockerCancel.dataset.bound = '1';
    dockerCancel.addEventListener('click', closeDockerNetworkCreateModal);
  }

  const dockerSubmit = document.getElementById('net-docker-create-submit-btn');
  if (dockerSubmit && !dockerSubmit.dataset.bound) {
    dockerSubmit.dataset.bound = '1';
    dockerSubmit.addEventListener('click', submitDockerNetworkCreate);
  }

  // Tier 3: Bonding Configuration Modal
  const bondClose = document.getElementById('net-bond-cfg-close-btn');
  if (bondClose && !bondClose.dataset.bound) {
    bondClose.dataset.bound = '1';
    bondClose.addEventListener('click', closeBondConfigModal);
  }

  const bondCancel = document.getElementById('net-bond-cfg-cancel-btn');
  if (bondCancel && !bondCancel.dataset.bound) {
    bondCancel.dataset.bound = '1';
    bondCancel.addEventListener('click', closeBondConfigModal);
  }

  const bondSave = document.getElementById('net-bond-cfg-save-btn');
  if (bondSave && !bondSave.dataset.bound) {
    bondSave.dataset.bound = '1';
    bondSave.addEventListener('click', saveBondConfig);
  }

  const bondModeSelect = document.getElementById('net-bond-mode-select');
  const bondModeDesc = document.getElementById('net-bond-mode-desc');
  if (bondModeSelect && !bondModeSelect.dataset.bound) {
    bondModeSelect.dataset.bound = '1';
    const modeDescriptions = {
      '0': t('net.bond_mode_desc_0', 'Round-robin policy: Transmit network packets sequentially from the first available slave through the last. Provides fault tolerance and load balancing across multiple links.'),
      '1': t('net.bond_mode_desc_1', 'Active-backup policy: Only one slave interface is active. Another slave becomes active only if the primary fails. Recommended for unmanaged switch environments.'),
      '2': t('net.bond_mode_desc_2', 'XOR balance policy: Transmits based on the selected transmit hash policy [(source MAC XOR dest MAC) modulo slave count]. Provides fault tolerance and load balancing.'),
      '4': t('net.bond_mode_desc_4', 'Dynamic Link Aggregation (IEEE 802.3ad LACP): Requires a switch that supports IEEE 802.3ad dynamic aggregation. Shares identical speed and duplex settings for maximum aggregate bandwidth and resilience.'),
      '6': t('net.bond_mode_desc_6', 'Adaptive Load Balancing (Balance-ALB): Includes balance-tlb plus receive load balancing (rlb) for IPv4 traffic. Does not require special switch support.')
    };
    bondModeSelect.addEventListener('change', () => {
      if (bondModeDesc) {
        bondModeDesc.textContent = modeDescriptions[bondModeSelect.value] || '';
      }
    });
  }

  // Tier 3: Bridge Configuration Modal
  const bridgeClose = document.getElementById('net-bridge-cfg-close-btn');
  if (bridgeClose && !bridgeClose.dataset.bound) {
    bridgeClose.dataset.bound = '1';
    bridgeClose.addEventListener('click', closeBridgeConfigModal);
  }

  const bridgeCancel = document.getElementById('net-bridge-cfg-cancel-btn');
  if (bridgeCancel && !bridgeCancel.dataset.bound) {
    bridgeCancel.dataset.bound = '1';
    bridgeCancel.addEventListener('click', closeBridgeConfigModal);
  }

  const bridgeSave = document.getElementById('net-bridge-cfg-save-btn');
  if (bridgeSave && !bridgeSave.dataset.bound) {
    bridgeSave.dataset.bound = '1';
    bridgeSave.addEventListener('click', saveBridgeConfig);
  }

  const btnStpEnable = document.getElementById('net-stp-btn-enable');
  const btnStpDisable = document.getElementById('net-stp-btn-disable');
  if (btnStpEnable && !btnStpEnable.dataset.bound) {
    btnStpEnable.dataset.bound = '1';
    btnStpEnable.addEventListener('click', () => {
      btnStpEnable.classList.add('active');
      if (btnStpDisable) btnStpDisable.classList.remove('active');
    });
  }
  if (btnStpDisable && !btnStpDisable.dataset.bound) {
    btnStpDisable.dataset.bound = '1';
    btnStpDisable.addEventListener('click', () => {
      btnStpDisable.classList.add('active');
      if (btnStpEnable) btnStpEnable.classList.remove('active');
    });
  }

  // Tier 3: 802.1Q VLAN Sub-Interface Modal
  const btnOpenVlan = document.getElementById('btn-open-create-vlan-modal');
  if (btnOpenVlan && !btnOpenVlan.dataset.bound) {
    btnOpenVlan.dataset.bound = '1';
    btnOpenVlan.addEventListener('click', () => openCreateVlanModal());
  }

  const vlanClose = document.getElementById('net-vlan-create-close-btn');
  if (vlanClose && !vlanClose.dataset.bound) {
    vlanClose.dataset.bound = '1';
    vlanClose.addEventListener('click', closeCreateVlanModal);
  }

  const vlanCancel = document.getElementById('net-vlan-create-cancel-btn');
  if (vlanCancel && !vlanCancel.dataset.bound) {
    vlanCancel.dataset.bound = '1';
    vlanCancel.addEventListener('click', closeCreateVlanModal);
  }

  const vlanSubmit = document.getElementById('net-vlan-create-submit-btn');
  if (vlanSubmit && !vlanSubmit.dataset.bound) {
    vlanSubmit.dataset.bound = '1';
    vlanSubmit.addEventListener('click', submitCreateVlan);
  }
}

export async function fetchAndRenderDisksInventory() {
  const tbody = document.getElementById('mgmt-disks-inventory-tbody');
  if (!tbody) return;

  try {
    const res = await api.request('/api/chassis/config');
    let disks = [];
    if (res.ok) {
      const data = await res.json();
      const hddDisks = (data.bays || []).map((b) => b.disk).filter(Boolean);
      const nvmeDisks = (data.nvme_slots || []).map((s) => s.disk).filter(Boolean);
      disks = [...hddDisks, ...nvmeDisks];
    } else {
      disks = state.latestStats?.disks || [];
    }

    if (disks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:20px;">No physical disks discovered.</td></tr>`;
      return;
    }

    if (tbody.firstElementChild && tbody.firstElementChild.querySelector('td[colspan]')) {
      tbody.innerHTML = '';
    }

    bindDiskTableEvents(tbody);

    reconcileKeyedTable(
      tbody,
      disks,
      (d) => d.dev || d.name || 'unknown',
      createDiskRow,
      updateDiskRow
    );
  } catch (err) {
    console.warn('[Management] Failed to fetch disks inventory:', err);
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--crit); padding:20px;">Failed to load disks inventory.</td></tr>`;
  }
}

function buildDiskRowInner(d) {
  const devName = d.dev || d.name || 'unknown';
  const isStandby = Boolean(d.standby || d.health === 'standby');
  const thermal = getThermalLevel(d.temp, isStandby);
  const modelStr = d.model || 'Generic Disk';
  const serialStr = d.serial && d.serial !== 'Unknown' ? d.serial : '--';
  const transportStr = (d.transport || (devName.startsWith('nvme') ? 'nvme' : 'sata')).toUpperCase();
  const driverStr = d.controller_driver || (devName.startsWith('nvme') ? 'nvme' : 'ahci');
  const sizeStr = d.size_formatted || d.size || '--';
  const healthStr = isStandby ? 'STANDBY' : (d.health ? String(d.health).toUpperCase() : 'OK');

  return `
    <td style="font-weight:700; color:#fff;">/dev/${escapeHtml(devName)}</td>
    <td>
      <div style="font-weight:600; color:#e2e8f0;">${escapeHtml(modelStr)}</div>
      <div style="font-size:10px; color:var(--muted);">SN: ${escapeHtml(serialStr)}</div>
    </td>
    <td>
      <span class="bay-sub-badge" style="background:rgba(255,255,255,0.06); padding:2px 6px; border-radius:4px;">${escapeHtml(transportStr)} • ${escapeHtml(driverStr)}</span>
    </td>
    <td class="disk-size-cell" style="font-weight:600; color:var(--accent-cyan,#00f0ff);">${escapeHtml(sizeStr)}</td>
    <td>
      <span class="bay-health-tag ${thermal.cls}">${escapeHtml(healthStr)}</span>
    </td>
    <td>
      <span class="bay-temp-pill" style="color:${thermal.color}; border-color:${thermal.color};">${thermal.text}</span>
    </td>
    <td style="text-align:right;">
      <div style="display:inline-flex; gap:6px; align-items:center;">
        <button class="btn-pill-toggle btn-locate-row" data-dev="${devName}" title="Locate Drive (Blink Bay LED)" style="padding:3px 8px; font-size:10.5px;">⚡ Locate</button>
        <button class="btn-pill-toggle btn-smart-row" data-dev="${devName}" title="View S.M.A.R.T. Diagnostics" style="padding:3px 8px; font-size:10.5px;">📊 S.M.A.R.T.</button>
        <button type="button" class="btn-pill-toggle btn-disk-more-sheet" data-dev="${devName}" title="More Actions" style="display:none; padding:3px 8px; font-size:12px;">···</button>
      </div>
    </td>
  `;
}

function createDiskRow(d) {
  const devName = d.dev || d.name || 'unknown';
  const tr = document.createElement('tr');
  tr.dataset.key = devName;
  tr.dataset.dev = devName;
  tr.innerHTML = buildDiskRowInner(d);
  return tr;
}

function updateDiskRow(row, d) {
  const isStandby = Boolean(d.standby || d.health === 'standby');
  const thermal = getThermalLevel(d.temp, isStandby);
  const healthStr = isStandby ? 'STANDBY' : (d.health ? String(d.health).toUpperCase() : 'OK');

  const healthTag = row.querySelector('.bay-health-tag');
  if (healthTag) {
    healthTag.className = `bay-health-tag ${thermal.cls}`;
    healthTag.textContent = healthStr;
  }
  const tempPill = row.querySelector('.bay-temp-pill');
  if (tempPill) {
    tempPill.style.color = thermal.color;
    tempPill.style.borderColor = thermal.color;
    tempPill.textContent = thermal.text;
  }
  const sizeTd = row.querySelector('.disk-size-cell') || row.children[3];
  if (sizeTd && (d.size_formatted || d.size)) {
    sizeTd.textContent = d.size_formatted || d.size;
  }
}

function bindDiskTableEvents(tbody) {
  if (tbody._diskEventsBound) return;
  tbody._diskEventsBound = true;

  tbody.addEventListener('click', (e) => {
    const moreBtn = e.target.closest('.btn-disk-more-sheet');
    if (moreBtn) {
      e.stopPropagation();
      const dev = moreBtn.dataset.dev;
      const row = moreBtn.closest('tr');
      const modelText = row?.children?.[1]?.firstElementChild?.textContent?.trim() || 'Physical Disk';
      const healthText = row?.querySelector('.bay-health-tag')?.textContent?.trim() || 'OK';
      showBottomSheet({
        title: `/dev/${dev}`,
        subtitle: `${modelText} • ${healthText}`,
        items: [
          {
            icon: '📊',
            label: 'View S.M.A.R.T. Diagnostics',
            onClick: () => row?.querySelector('.btn-smart-row')?.click(),
          },
          {
            icon: '⚡',
            label: 'Locate Drive (Blink Bay LED)',
            onClick: () => row?.querySelector('.btn-locate-row')?.click(),
          },
        ],
      });
      return;
    }

    const locateBtn = e.target.closest('.btn-locate-row');
    if (locateBtn) {
      const dev = locateBtn.dataset.dev;
      triggerLocateDisk(dev, locateBtn.closest('tr'));
      return;
    }

    const smartBtn = e.target.closest('.btn-smart-row');
    if (smartBtn) {
      const dev = smartBtn.dataset.dev;
      const row = smartBtn.closest('tr');
      const isStandby = row?.querySelector('.bay-health-tag')?.textContent?.trim() === 'STANDBY';
      if (isStandby) {
        showConfirmToast(
          'Drive in Standby Mode',
          `Disk /dev/${dev} is currently sleeping. Querying S.M.A.R.T. diagnostics will wake the drive, spinning up platters. Do you wish to wake it?`,
          () => {
            showToast(`Waking disk /dev/${dev}...`, 'info');
            ZettEventBus.emit('modal:smart:open', { dev, forceWake: true });
          }
        );
      } else {
        ZettEventBus.emit('modal:smart:open', dev);
      }
    }
  });
}

export function initManagement() {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) {
    return;
  }

  const overlay = document.getElementById('management-modal-overlay');
  const win = document.getElementById('management-window');
  const header = document.getElementById('management-window-header');
  const hubView = document.getElementById('management-hub-view');
  const detailContainer = document.getElementById('management-detail-container');
  const backBtn = document.getElementById('management-back-btn');
  const titleText = document.getElementById('management-header-title-text');
  const headerNav = document.getElementById('management-header-nav');
  const desktopIcon = document.getElementById('management-desktop-icon');
  const secBadge = document.getElementById('mgmt-hub-sec-badge');

  if (!overlay || !win) return;

  // Make Management window draggable by its header
  if (header) {
    makeDraggable(win, header, 'management');
  }

  win.addEventListener('pointerdown', () => {
    bringToFront(win);
    saveOpenWindowsState();
  }, { capture: true });

  win.addEventListener('mousedown', () => {
    bringToFront(win);
    saveOpenWindowsState();
  });

  // Minimize button
  const minBtn = document.getElementById('management-min');
  if (minBtn) {
    const handleMin = (e) => {
      if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
      stopDockerAutoRefresh();
      DockManager.minimize('management');
    };
    minBtn.addEventListener('click', handleMin);
    minBtn.addEventListener('touchend', handleMin);
  }

  // Maximize button
  const maxBtn = document.getElementById('management-max');
  let _isMaximized = false;
  let _preMaxBounds = null;
  let _lastMgmtTouchTs = 0;
  if (maxBtn) {
    const handleMax = (e) => {
      if (e) {
        if (e.type === 'click' && Date.now() - _lastMgmtTouchTs < 450) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        if (e.type === 'touchend') {
          _lastMgmtTouchTs = Date.now();
        }
        e.preventDefault();
        e.stopPropagation();
      }
      if (!_isMaximized) {
        _preMaxBounds = {
          left: win.style.left,
          top: win.style.top,
          transform: win.style.transform,
          width: win.style.width,
          height: win.style.height
        };
        win.style.left = '16px';
        win.style.top = '56px';
        win.style.transform = 'none';
        win.style.width = 'calc(100vw - 32px)';
        win.style.height = 'calc(100vh - 128px)';
        win.dataset.snapped = 'maximize';
        _isMaximized = true;
        saveWindowBounds('management', {
          left: 16,
          top: 56,
          width: window.innerWidth - 32,
          height: window.innerHeight - 128,
          snapped: 'maximize'
        });
        saveOpenWindowsState();
      } else {
        win.dataset.snapped = '';
        if (_preMaxBounds) {
          win.style.left = _preMaxBounds.left;
          win.style.top = _preMaxBounds.top;
          win.style.transform = _preMaxBounds.transform;
          win.style.width = _preMaxBounds.width;
          win.style.height = _preMaxBounds.height;
        } else {
          win.style.left = '50%';
          win.style.top = '50%';
          win.style.transform = 'translate(-50%, -50%)';
          win.style.width = '';
          win.style.height = '';
        }
        _isMaximized = false;
        saveWindowBounds('management', {
          left: Math.round(window.innerWidth / 2 - 450),
          top: Math.round(window.innerHeight / 2 - 300),
          width: 900,
          height: 600,
          snapped: ''
        });
        saveOpenWindowsState();
      }
    };
    maxBtn.addEventListener('click', handleMax);
    maxBtn.addEventListener('touchend', handleMax);
  }

  // Close button
  const closeBtn = document.getElementById('management-close');
  if (closeBtn) {
    const handleClose = (e) => {
      if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
      stopDockerAutoRefresh();
      overlay.classList.remove('open');
      overlay.style.setProperty('display', 'none', 'important');
      win.classList.remove('window-focus-pulse');
      win.classList.add('window-minimized');
      if (_unbindMgmtTrap) {
        _unbindMgmtTrap();
        _unbindMgmtTrap = null;
      }
      DockManager.unregister('management');
    };
    closeBtn.addEventListener('click', handleClose);
    closeBtn.addEventListener('touchend', handleClose);
  }

  function showHub() {
    const earlyStyle = document.getElementById('zettnas-mgmt-early-style');
    if (earlyStyle) earlyStyle.remove();
    if (hubView) hubView.style.display = 'grid';
    if (detailContainer) detailContainer.style.display = 'none';
    if (headerNav) headerNav.style.display = 'none';
    if (backBtn) backBtn.style.display = 'none';
    if (titleText) titleText.textContent = t('mgmt.title', 'Mission Control');
    document.querySelectorAll('.mgmt-category-tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.mgmt-sidebar-item').forEach((b) => {
      b.classList.toggle('active', b.dataset.mgmtTarget === 'management-hub-view');
    });
    document.querySelectorAll('.mgmt-detail-card').forEach((c) => (c.style.display = 'none'));
    saveOpenWindowsState();
  }

  


  function triggerActiveSubTab(parentId) {
    const parent = document.getElementById(parentId);
    if (!parent) return;
    const activeTabBtn = parent.querySelector('.mgmt-inner-tab.active');
    if (activeTabBtn) {
      const paneId = activeTabBtn.dataset.tabTarget;
      triggerSubTabLoad(paneId);
    }
  }

  function triggerSubTabLoad(paneId, subTabId = null) {
    if (paneId === 'mgmt-pane-widgets') {
      if (typeof syncWidgetSettingsUI === 'function') syncWidgetSettingsUI();
    } else if (paneId === 'mgmt-pane-dock') {
      if (typeof window.initDockSettingsControls === 'function') {
        window.initDockSettingsControls();
      }
    } else if (paneId === 'mgmt-pane-screensaver') {
      if (typeof window.initScreensaverSettingsControls === 'function') {
        window.initScreensaverSettingsControls();
      }
    } else if (paneId === 'mgmt-pane-theme') {
      if (typeof syncDesktopThemeUI === 'function') syncDesktopThemeUI();
    } else if (paneId === 'mgmt-pane-language') {
      const select = document.getElementById('mgmt-lang-select');
      if (select && typeof getLanguage === 'function') {
        select.value = getLanguage();
      }
    } else if (paneId === 'mgmt-pane-metrics') {
      setTimeout(fetchAndRenderMetrics, 50);
    } else if (paneId === 'mgmt-pane-copy') {
      fetchAndRenderCopyHistory();
    } else if (paneId === 'mgmt-pane-network' || paneId === 'mgmt-pane-network-physical') {
      fetchAndRenderNetworkTopology();
    } else if (paneId === 'mgmt-pane-network-wireguard') {
      fetchAndRenderWireguard();
    } else if (paneId === 'mgmt-pane-network-docker') {
      fetchAndRenderNetworkTopology();
    } else if (paneId === 'mgmt-pane-unraid') {
      if (state.lastStats) updateManagementTelemetry(state.lastStats);
    } else if (paneId === 'mgmt-pane-docker') {
      fetchAndRenderDockerContainers();
    } else if (paneId === 'mgmt-pane-chassis-twin') {
      const mount = document.getElementById('mgmt-chassis-twin-mount');
      if (mount) fetchAndRenderChassisTwin(mount);
    } else if (paneId === 'mgmt-pane-storage-topo') {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      if (mount) fetchAndRenderStorageTopology(mount);
    } else if (paneId === 'mgmt-pane-storage-shares') {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      if (mount) fetchAndRenderNetworkShares(mount);
    } else if (paneId === 'mgmt-pane-storage-remotes') {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      if (mount) fetchAndRenderRemoteStorage(mount);
    } else if (paneId === 'mgmt-pane-storage-disks') {
      fetchAndRenderDisksInventory();
    } else if (paneId === 'mgmt-pane-storage-replication') {
      fetchAndRenderReplication();
    } else if (paneId === 'mgmt-pane-backups' || paneId === 'mgmt-pane-system') {
      fetchAndRenderBackupJobs();
      fetchAndRenderSystemSnapshots();
      fetchAndRenderAppBackups();
    } else if (paneId === 'mgmt-pane-security') {
      if (typeof fetchAPITokens === 'function') fetchAPITokens();
      if (typeof renderApiTokens === 'function') renderApiTokens();
      fetchAndRenderSecurityPosture();
    } else if (paneId === 'mgmt-pane-notifications') {
      fetchAndRenderNotificationConfig();
    } else if (paneId === 'mgmt-pane-users') {
      import('./users.js').then((m) => m.loadUsersPane(subTabId || 'users-pane-list'));
    } else if (paneId === 'mgmt-pane-about') {
      fetchAndRenderSystemAbout();
    } else if (paneId === 'mgmt-pane-vms-list' || paneId === 'mgmt-pane-vms-create' || paneId === 'mgmt-pane-vms-kvm') {
      fetchAndRenderMgmtVms();
    } else if (paneId === 'mgmt-pane-hardware-ups') {
      if (typeof fetchAndRenderUpsTelemetry === 'function') fetchAndRenderUpsTelemetry();
    }
  }

  async function fetchAndRenderMgmtVms() {
    const grid = document.getElementById('mgmt-vms-grid');
    const empty = document.getElementById('mgmt-vms-empty');
    const strip = document.getElementById('mgmt-vms-summary-strip');
    const kvmBody = document.getElementById('mgmt-vms-kvm-body');
    if (!grid && !strip) return;

    try {
      const [tel, list] = await Promise.all([
        api.get('/api/vms/telemetry').catch(() => null),
        api.get('/api/vms').catch(() => []),
      ]);

      const vmsList = Array.isArray(list) ? list : [];
      const runningCount = vmsList.filter(v => v.state === 'running').length;
      const hubPill = document.getElementById('mgmt-hub-vms-pill');
      if (hubPill) hubPill.textContent = `${runningCount} Running`;
      const sideBadge = document.getElementById('mgmt-sidebar-vms-badge');
      if (sideBadge) {
        sideBadge.textContent = `${vmsList.length} VMs`;
        sideBadge.style.display = vmsList.length > 0 ? 'inline-block' : 'none';
      }

      if (strip) {
        const kvmActive = tel?.kvm?.state === 'active';
        const kvmColor = kvmActive ? 'var(--ok2, #25c2a0)' : (tel?.kvm?.state === 'restricted' ? 'var(--warn, #f5a623)' : 'var(--danger, #ff6b6b)');
        const kvmBadge = tel?.kvm?.badge || (kvmActive ? 'KVM Acceleration Active' : 'Software Emulation');
        const headroom = tel?.memory?.headroom_mb ? `${(tel.memory.headroom_mb / 1024).toFixed(1)} GB Safe Headroom` : 'Dynamic';
        const cpuRatio = tel?.cpu?.ratio ? `${tel.cpu.ratio}:1 Allocation` : 'Optimal';

        strip.innerHTML = `
          <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 10px 14px;">
            <div style="font-size: 10px; color: var(--muted); font-weight: 700; text-transform: uppercase;">HYPERVISOR ENGINE</div>
            <div style="font-size: 13px; font-weight: 700; color: ${kvmColor}; margin-top: 4px; display: flex; align-items: center; gap: 6px;">
              <span>⚡</span> <span>${escapeHtml(kvmBadge)}</span>
            </div>
          </div>
          <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 10px 14px;">
            <div style="font-size: 10px; color: var(--muted); font-weight: 700; text-transform: uppercase;">MEMORY CEILING</div>
            <div style="font-size: 13px; font-weight: 700; color: var(--accent-cyan, #0ea5e9); margin-top: 4px;">
              ${escapeHtml(headroom)}
            </div>
          </div>
          <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 10px 14px;">
            <div style="font-size: 10px; color: var(--muted); font-weight: 700; text-transform: uppercase;">vCPU OVERCOMMIT</div>
            <div style="font-size: 13px; font-weight: 700; color: #fff; margin-top: 4px;">
              ${escapeHtml(cpuRatio)}
            </div>
          </div>
        `;
      }

      if (grid) {
        if (vmsList.length === 0) {
          grid.innerHTML = '';
          if (empty) empty.style.display = 'block';
        } else {
          if (empty) empty.style.display = 'none';
          grid.innerHTML = vmsList.map((vm) => {
            const isRunning = vm.state === 'running';
            const isPaused = vm.state === 'paused';
            const statusColor = isRunning ? 'var(--ok2, #25c2a0)' : (isPaused ? 'var(--warn, #f5a623)' : 'var(--muted, #94a3b8)');
            const statusBg = isRunning ? 'rgba(37,194,160,0.15)' : (isPaused ? 'rgba(245,166,35,0.15)' : 'rgba(255,255,255,0.06)');

            const ramGb = vm.memory_mb ? (vm.memory_mb >= 1024 ? `${(vm.memory_mb / 1024).toFixed(0)} GB` : `${vm.memory_mb} MB`) : '1 GB';
            const cores = vm.cores || 1;
            const osType = vm.os_type || 'Linux';

            return `
              <div class="mgmt-vm-card" data-vm-id="${escapeHtml(vm.id)}" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 14px; display: flex; flex-direction: column; gap: 10px; transition: border-color 0.2s;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 18px;">🖥️</span>
                    <div>
                      <div style="font-weight: 700; font-size: 13px; color: #fff;">${escapeHtml(vm.name || vm.id)}</div>
                      <div style="font-size: 10px; color: var(--muted);">${escapeHtml(osType)} • ${cores} vCPU • ${ramGb} RAM</div>
                    </div>
                  </div>
                  <span style="padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; text-transform: uppercase; background: ${statusBg}; color: ${statusColor};">
                    ${escapeHtml(vm.state || 'stopped')}
                  </span>
                </div>
                <div style="display: flex; gap: 6px; margin-top: auto; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05);">
                  ${isRunning
                    ? `<button class="btn-pill-toggle btn-vm-action-stop" data-vm-id="${escapeHtml(vm.id)}" style="flex:1; font-size:11px; padding:4px 6px; color:#f87171;" title="Stop VM">⏹ Stop</button>`
                    : `<button class="btn-pill-toggle btn-vm-action-start" data-vm-id="${escapeHtml(vm.id)}" style="flex:1; font-size:11px; padding:4px 6px; color:var(--ok2);" title="Start VM">▶ Start</button>`
                  }
                  <button class="btn-pill-toggle btn-vm-action-console" data-vm-id="${escapeHtml(vm.id)}" data-vm-name="${escapeHtml(vm.name || vm.id)}" style="flex:1; font-size:11px; padding:4px 6px; color:var(--accent-cyan);" title="Open Web Console">📺 Console</button>
                  <button class="btn-pill-toggle btn-vm-action-edit" data-vm-id="${escapeHtml(vm.id)}" style="font-size:11px; padding:4px 8px;" title="Edit VM Config">⚙️</button>
                </div>
              </div>
            `;
          }).join('');

          grid.querySelectorAll('.btn-vm-action-start').forEach(btn => {
            btn.addEventListener('click', async () => {
              const id = btn.dataset.vmId;
              try {
                btn.disabled = true;
                btn.textContent = '...';
                await api.post(`/api/vms/${id}/action`, { action: 'start' });
                showToast('VM started successfully', 'success');
                fetchAndRenderMgmtVms();
              } catch (err) {
                showToast(`Failed to start VM: ${err.message}`, 'error');
                btn.disabled = false;
                btn.textContent = '▶ Start';
              }
            });
          });

          grid.querySelectorAll('.btn-vm-action-stop').forEach(btn => {
            btn.addEventListener('click', async () => {
              const id = btn.dataset.vmId;
              try {
                btn.disabled = true;
                btn.textContent = '...';
                await api.post(`/api/vms/${id}/action`, { action: 'stop' });
                showToast('VM stop signal sent', 'info');
                fetchAndRenderMgmtVms();
              } catch (err) {
                showToast(`Failed to stop VM: ${err.message}`, 'error');
                btn.disabled = false;
                btn.textContent = '⏹ Stop';
              }
            });
          });

          grid.querySelectorAll('.btn-vm-action-console').forEach(btn => {
            btn.addEventListener('click', () => {
              const id = btn.dataset.vmId;
              const name = btn.dataset.vmName;
              import('./vm-manager.js').then(m => {
                if (typeof m.openVmConsole === 'function') {
                  m.openVmConsole(id, name);
                }
              });
            });
          });

          grid.querySelectorAll('.btn-vm-action-edit').forEach(btn => {
            btn.addEventListener('click', () => {
              const id = btn.dataset.vmId;
              const vmObj = vmsList.find(v => v.id === id);
              import('./vm-manager.js').then(m => {
                if (typeof m.openVmEditModal === 'function') {
                  m.openVmEditModal(id, vmObj);
                }
              });
            });
          });
        }
      }

      if (kvmBody && tel?.kvm) {
        kvmBody.innerHTML = `
          <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; gap: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div style="font-weight: 700; font-size: 13px; color: #fff;">Hardware Virtualization Extension</div>
              <span style="padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; background: ${tel.kvm.state === 'active' ? 'rgba(37,194,160,0.15)' : 'rgba(239,68,68,0.15)'}; color: ${tel.kvm.state === 'active' ? 'var(--ok2)' : 'var(--danger)'};">
                ${escapeHtml(tel.kvm.badge || 'KVM')}
              </span>
            </div>
            <div style="font-size: 11.5px; color: var(--muted); line-height: 1.5;">
              ${escapeHtml(tel.kvm.details || 'Linux KVM hypervisor acceleration provides near bare-metal guest performance.')}
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-top: 6px;">
              <div style="background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px;">
                <div style="font-size: 10px; color: var(--muted);">CPU Host Threads</div>
                <div style="font-size: 14px; font-weight: 700; color: #fff; margin-top: 2px;">${tel.cpu?.host_threads || 8} Threads</div>
              </div>
              <div style="background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px;">
                <div style="font-size: 10px; color: var(--muted);">vhost-net Acceleration</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--ok2); margin-top: 2px;">Supported</div>
              </div>
              <div style="background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px;">
                <div style="font-size: 10px; color: var(--muted);">Default Network Bridge</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--accent-cyan); margin-top: 2px;">br0 / virbr0</div>
              </div>
            </div>
          </div>
        `;
      }
    } catch (err) {
      console.warn('Failed to load VM telemetry in Mission Control:', err);
    }
  }

  function showSection(targetId, specificPane = null, subTabId = null) {
    const earlyStyle = document.getElementById('zettnas-mgmt-early-style');
    if (earlyStyle) earlyStyle.remove();
    let desiredSubPane = specificPane;
    if (desiredSubPane === 'mgmt-pane-system') desiredSubPane = 'mgmt-pane-backups';
    if (!desiredSubPane && SUBPANE_MAP[targetId]) {
      desiredSubPane = SUBPANE_MAP[targetId].pane;
      targetId = SUBPANE_MAP[targetId].section;
    } else if (SUBPANE_MAP[targetId]) {
      targetId = SUBPANE_MAP[targetId].section;
    }

    if (hubView) hubView.style.display = 'none';
    if (detailContainer) detailContainer.style.display = 'block';
    if (headerNav) headerNav.style.display = 'flex';
    if (backBtn) backBtn.style.display = 'inline-flex';

    document.querySelectorAll('.mgmt-detail-card').forEach((c) => {
      if (c.id === targetId) {
        c.style.display = 'block';
      } else {
        c.style.display = 'none';
      }
    });

    const targetTab = document.querySelector(`.mgmt-category-tab[data-mgmt-target="${targetId}"]`);
    document.querySelectorAll('.mgmt-category-tab').forEach((t) => t.classList.remove('active'));
    if (targetTab) targetTab.classList.add('active');

    document.querySelectorAll('.mgmt-sidebar-item').forEach((b) => {
      const isActive = b.dataset.mgmtTarget === targetId;
      b.classList.toggle('active', isActive);
      if (isActive && typeof b.scrollIntoView === 'function') {
        try { b.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
      }
    });

    let sectionName = t('mgmt.title', 'Mission Control');
    if (targetId === 'mgmt-sec-wallpaper') {
      sectionName = t('mgmt.appearance_title', 'Appearance');
    } else if (targetId === 'mgmt-sec-activity') {
      sectionName = t('mgmt.activity_title', 'Dashboard & Telemetry');
    } else if (targetId === 'mgmt-sec-network') {
      sectionName = t('mgmt.network_sec_title', 'Network & Sharing');
      fetchAndRenderNetworkTopology();
    } else if (targetId === 'mgmt-sec-docker') {
      sectionName = t('mgmt.docker_title', 'Containers & Apps');
      fetchAndRenderDockerContainers();
      startDockerAutoRefresh();
    } else if (targetId === 'mgmt-sec-vms') {
      sectionName = t('mgmt.vms_title', 'Virtual Machines');
      stopDockerAutoRefresh();
      fetchAndRenderMgmtVms();
    } else {
      stopDockerAutoRefresh();
      if (targetId === 'mgmt-sec-hardware' || targetId === 'mgmt-sec-services') {
        sectionName = t('mgmt.hardware_title', 'Hardware & Profiles');
        if (state.lastStats || state.latestStats) updateManagementTelemetry(state.lastStats || state.latestStats);
      } else if (targetId === 'mgmt-sec-storage') {
        sectionName = t('mgmt.storage_title', 'Storage & Disks');
      } else if (targetId === 'mgmt-sec-ups') {
        sectionName = t('mgmt.sidebar_ups', 'Power & Battery');
        if (typeof fetchAndRenderUpsTelemetry === 'function') fetchAndRenderUpsTelemetry();
        else if (typeof fetchAndRenderUPS === 'function') fetchAndRenderUPS();
        if (typeof loadUpsConfigToDrawer === 'function') loadUpsConfigToDrawer();
      } else if (targetId === 'mgmt-sec-system-group') {
        sectionName = t('mgmt.system_title', 'System & Identity');
      }
    }

    if (titleText) titleText.textContent = sectionName;

    const parentCard = document.getElementById(targetId);
    if (parentCard) {
      if (desiredSubPane) {
        parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
          const isActive = t.dataset.tabTarget === desiredSubPane;
          t.classList.toggle('active', isActive);
          t.setAttribute('aria-selected', isActive ? 'true' : 'false');
          if (isActive && typeof t.scrollIntoView === 'function') {
            try { t.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
          }
        });
        parentCard.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
          p.style.display = p.id === desiredSubPane ? 'block' : 'none';
        });
        triggerSubTabLoad(desiredSubPane, subTabId);
      } else {
        let activeTabBtn = parentCard.querySelector('.mgmt-inner-tab.active');
        if (!activeTabBtn) {
          activeTabBtn = parentCard.querySelector('.mgmt-inner-tab');
          if (activeTabBtn) activeTabBtn.classList.add('active');
        }
        if (activeTabBtn) {
          const paneId = activeTabBtn.dataset.tabTarget;
          parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
            const isActive = t === activeTabBtn;
            t.classList.toggle('active', isActive);
            t.setAttribute('aria-selected', isActive ? 'true' : 'false');
          });
          parentCard.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
            p.style.display = p.id === paneId ? 'block' : 'none';
          });
          triggerSubTabLoad(paneId, subTabId);
        } else {
          const singlePane = parentCard.querySelector('.mgmt-tab-pane');
          if (singlePane) {
            singlePane.style.display = 'block';
            triggerSubTabLoad(singlePane.id, subTabId);
          }
        }
      }
    }
    saveOpenWindowsState();
  }

  // Left sidebar items click listener

  document.querySelectorAll('.mgmt-inner-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const parentCard = tab.closest('.mgmt-detail-card');
      if (!parentCard) return;
      
      // Update tab buttons
      parentCard.querySelectorAll('.mgmt-inner-tab').forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      if (typeof tab.scrollIntoView === 'function') {
        try { tab.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
      }
      
      // Update tab panes
      const targetPaneId = tab.dataset.tabTarget;
      parentCard.querySelectorAll('.mgmt-tab-pane').forEach(p => {
        if (p.id === targetPaneId) {
          p.style.display = 'block';
        } else {
          p.style.display = 'none';
        }
      });
      
      triggerSubTabLoad(targetPaneId);
      saveOpenWindowsState();
    });
  });

  document.querySelectorAll('.mgmt-sidebar-item').forEach((item) => {
    item.addEventListener('click', () => {
      if (typeof item.scrollIntoView === 'function') {
        try { item.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
      }
      const targetId = item.dataset.mgmtTarget;
      if (targetId === 'management-hub-view') {
        showHub();
      } else if (targetId) {
        showSection(targetId);
      }
      saveOpenWindowsState();
    });
  });

  // Hub cards click listener
  document.querySelectorAll('.mgmt-app-card').forEach((card) => {
    card.addEventListener('click', () => {
      const targetId = card.dataset.mgmtTarget;
      if (targetId) {
        showSection(targetId);
        saveOpenWindowsState();
      }
    });
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const targetId = card.dataset.mgmtTarget;
        if (targetId) {
          showSection(targetId);
          saveOpenWindowsState();
        }
      }
    });
  });

  // Header quick tabs click listener
  document.querySelectorAll('.mgmt-category-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.mgmtTarget;
      if (targetId) {
        showSection(targetId);
        saveOpenWindowsState();
      }
    });
  });

  // Back button click listener
  if (backBtn) {
    backBtn.addEventListener('click', () => {
      showHub();
      saveOpenWindowsState();
    });
  }

  // Global helper to open / focus Management window
  window.openManagementWindow = (sectionId = null, paneId = null, subTabId = null) => {
    if (sectionId) {
      showSection(sectionId, paneId, subTabId);
    } else {
      showHub();
    }

    if (!DockManager.windows['management']) {
      DockManager.register('management', overlay, '#i-management', 'Management');
    }
    if (DockManager.windows['management']) {
      DockManager.windows['management'].minimized = false;
      DockManager.windows['management'].closed = false;
    }
    DockManager.restore('management');
    overlay.style.removeProperty('display');
    overlay.style.display = 'flex';
    overlay.classList.add('open');
    win.classList.remove('window-minimized');
    win.style.removeProperty('display');

    if (state.latestStats) updateManagementTelemetry(state.latestStats);

    bringToFront(win);
    win.classList.remove('window-focus-pulse');
    void win.offsetWidth; // Reflow
    win.classList.add('window-focus-pulse');
    setTimeout(() => win.classList.remove('window-focus-pulse'), 850);

    if (_unbindMgmtTrap) { _unbindMgmtTrap(); }
    _unbindMgmtTrap = trapFocus(win, () => {
      const cBtn = document.getElementById('management-close');
      if (cBtn) cBtn.click();
    });

    if (window.DockManager) {
      window.DockManager.render();
    }
  };

  // Explicit helper for section and subpane deep-linking
  window.openManagementSection = (sectionId, paneId = null, subTabId = null) => {
    window.openManagementWindow(sectionId, paneId, subTabId);
  };

  // Support window:open event bus deep-linking
  ZettEventBus.on('window:open', (payload) => {
    if (payload && (payload.id === 'management' || payload.id === 'management-window')) {
      window.openManagementWindow(payload.section || payload.pane, payload.pane, payload.subtab);
    }
  });

  // Desktop icon click listener
  if (desktopIcon) {
    desktopIcon.addEventListener('click', () => {
      window.openManagementWindow();
    });
    desktopIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        window.openManagementWindow();
      }
    });
  }

  // Security Posture live check and badge rendering
  async function fetchAndRenderSecurityPosture() {
    const badge = document.getElementById('sec-advisor-score-badge');
    const container = document.getElementById('sec-advisor-items');
    if (!badge && !container) return;

    try {
      const data = await api.get('/api/system/security-posture');
      if (!data) return;

      if (badge) {
        badge.textContent = `Score: ${data.score}/100 (Grade ${data.grade})`;
        if (data.score >= 90) {
          badge.style.background = 'rgba(37,194,160,0.15)';
          badge.style.color = '#25c2a0';
          badge.style.borderColor = 'rgba(37,194,160,0.3)';
        } else if (data.score >= 75) {
          badge.style.background = 'rgba(56,189,248,0.15)';
          badge.style.color = '#38bdf8';
          badge.style.borderColor = 'rgba(56,189,248,0.3)';
        } else if (data.score >= 50) {
          badge.style.background = 'rgba(234,179,8,0.15)';
          badge.style.color = '#eab308';
          badge.style.borderColor = 'rgba(234,179,8,0.3)';
        } else {
          badge.style.background = 'rgba(239,68,68,0.15)';
          badge.style.color = '#ef4444';
          badge.style.borderColor = 'rgba(239,68,68,0.3)';
        }
      }

      if (container && Array.isArray(data.checks)) {
        container.innerHTML = data.checks.map(c => {
          const passIcon = c.passed ? '✔' : '✖';
          const passColor = c.passed ? '#22c55e' : '#ef4444';
          const badgeBg = c.passed ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)';
          return `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 10px; background:${badgeBg}; border:1px solid ${c.passed ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.3)'}; border-radius:6px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <span style="color:${passColor}; font-weight:800; font-size:12px;">${passIcon}</span>
                <div>
                  <div style="font-weight:600; color:#f8fafc;">${escapeHtml(c.name)}</div>
                  <div style="font-size:10.5px; color:${c.passed ? '#94a3b8' : '#fca5a5'};">${escapeHtml(c.details || '')}</div>
                </div>
              </div>
              <span style="font-size:10px; font-weight:700; color:${passColor}; text-transform:uppercase;">${c.passed ? 'PASSED' : 'NEEDS ACTION'}</span>
            </div>
          `;
        }).join('');
      }
    } catch (err) {
      console.warn('[SecurityPosture] Failed to fetch posture:', err);
    }
  }

  // Synchronize security alert badge on Security card and sidebar
  function syncSecurityBadge() {
    const defaultWarning = document.getElementById('sec-default-pwd-warning');
    const isWarning = defaultWarning && defaultWarning.style.display !== 'none';
    if (secBadge) {
      secBadge.style.display = isWarning ? 'flex' : 'none';
    }
    const sideSecBadge = document.getElementById('mgmt-sidebar-sec-badge');
    if (sideSecBadge) {
      sideSecBadge.style.display = isWarning ? 'inline-block' : 'none';
    }
  }

  const observer = new MutationObserver(syncSecurityBadge);
  const warnEl = document.getElementById('sec-default-pwd-warning');
  if (warnEl) {
    observer.observe(warnEl, { attributes: true, attributeFilter: ['style'] });
    syncSecurityBadge();
  }

  // Profile buttons listener and keyboard navigation
  const profileBtns = Array.from(document.querySelectorAll('.profile-btn'));
  profileBtns.forEach((btn, idx) => {
    btn.addEventListener('click', async () => {
      const p = btn.dataset.profile;
      if (!p) return;
      _activeProfile = p;
      profileBtns.forEach((b) => {
        const isAct = b === btn;
        b.classList.toggle('active', isAct);
        b.setAttribute('aria-checked', isAct ? 'true' : 'false');
      });
      const pill = document.getElementById('unraid-profile-current-pill');
      if (pill) {
        pill.textContent = `ACTIVE: ${p === 'auto' ? 'AUTO DYNAMIC' : p.toUpperCase()}`;
        pill.style.color = p === 'performance' ? 'var(--warn)' : 'var(--ok2)';
      }
      try {
        await api.post('/api/system/profile', { profile: p });
        showToast(`System profile switched to ${p === 'auto' ? 'AUTO DYNAMIC' : p.toUpperCase()}.`, 'success');
      } catch (err) {
        showToast(`Failed to switch profile: ${err.message}`, 'error');
      }
    });

    btn.addEventListener('keydown', (e) => {
      let targetBtn = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        targetBtn = profileBtns[(idx + 1) % profileBtns.length];
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        targetBtn = profileBtns[(idx - 1 + profileBtns.length) % profileBtns.length];
      }
      if (targetBtn) {
        targetBtn.focus();
        targetBtn.click();
      }
    });
  });

  // Copy history refresh button
  const refreshHistoryBtn = document.getElementById('btn-refresh-copy-history');
  if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener('click', () => {
      fetchAndRenderCopyHistory();
      showToast('Ingest history refreshed.', 'info');
    });
  }

  // Network topology refresh button & controls
  const refreshNetBtn = document.getElementById('btn-refresh-network-topology');
  if (refreshNetBtn) {
    refreshNetBtn.addEventListener('click', () => {
      fetchAndRenderNetworkTopology();
      showToast('Network topology refreshed.', 'info');
    });
  }
  initNetworkControls();

  // Docker containers refresh button
  const refreshDockerBtn = document.getElementById('btn-refresh-docker');
  if (refreshDockerBtn) {
    refreshDockerBtn.addEventListener('click', () => {
      fetchAndRenderDockerContainers();
      showToast('Docker containers refreshed.', 'info');
    });
  }

  // UPS telemetry refresh button & drawer controls
  const refreshUpsBtn = document.getElementById('btn-refresh-ups');
  if (refreshUpsBtn) {
    refreshUpsBtn.addEventListener('click', () => {
      fetchAndRenderUpsTelemetry();
      showToast('UPS telemetry refreshed.', 'info');
    });
  }
  initUpsDrawerControls();

  // Virtual Machines refresh, launch window & create wizard buttons
  const refreshVmBtn = document.getElementById('btn-mgmt-vm-refresh');
  if (refreshVmBtn) {
    refreshVmBtn.addEventListener('click', () => {
      fetchAndRenderMgmtVms();
      showToast('VM fleet refreshed.', 'info');
    });
  }

  const launchVmWinBtn = document.getElementById('btn-mgmt-vm-launch-window');
  if (launchVmWinBtn) {
    launchVmWinBtn.addEventListener('click', () => {
      if (typeof window.openVmManager === 'function') window.openVmManager();
    });
  }

  const launchDockerWinBtn = document.getElementById('btn-mgmt-docker-launch-window');
  if (launchDockerWinBtn) {
    launchDockerWinBtn.addEventListener('click', () => {
      if (typeof window.openContainersManager === 'function') {
        window.openContainersManager();
      } else if (typeof window.openContainersWindow === 'function') {
        window.openContainersWindow();
      }
    });
  }

  const wireVmCreate = (btnId) => {
    const btn = document.getElementById(btnId);
    if (btn) {
      btn.addEventListener('click', () => {
        import('./vm-manager.js').then((m) => {
          if (typeof m.openVmCreateModal === 'function') m.openVmCreateModal();
        });
      });
    }
  };
  wireVmCreate('btn-mgmt-vm-create');
  wireVmCreate('btn-mgmt-vm-create-empty');
  wireVmCreate('btn-mgmt-vm-start-wizard');

  // Hardware drawer shortcuts & cross-pillar navigators
  const btnOpenFans = document.getElementById('btn-open-fans-drawer');
  if (btnOpenFans) {
    btnOpenFans.addEventListener('click', () => {
      openDrawer('tab-fans');
    });
  }

  const btnOpenLed = document.getElementById('btn-open-led-drawer');
  if (btnOpenLed) {
    btnOpenLed.addEventListener('click', () => {
      openDrawer('tab-led');
    });
  }

  const btnOpenLcd = document.getElementById('btn-open-lcd-drawer');
  if (btnOpenLcd) {
    btnOpenLcd.addEventListener('click', () => {
      openDrawer('tab-layout');
    });
  }

  const btnOpenFullUps = document.getElementById('btn-open-full-ups-view');
  if (btnOpenFullUps) {
    btnOpenFullUps.addEventListener('click', () => {
      showSection('mgmt-sec-ups');
    });
  }

  const btnGotoShares = document.getElementById('btn-goto-storage-shares');
  if (btnGotoShares) {
    btnGotoShares.addEventListener('click', () => {
      showSection('mgmt-sec-storage', 'mgmt-pane-storage-shares');
    });
  }

  // Chassis digital twin refresh button
  const refreshChassisBtn = document.getElementById('btn-refresh-chassis');
  if (refreshChassisBtn) {
    refreshChassisBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-chassis-twin-mount');
      if (mount) fetchAndRenderChassisTwin(mount);
      showToast('Chassis digital twin refreshed.', 'info');
    });
  }

  // Storage pool topology refresh & create buttons
  const refreshTopoBtn = document.getElementById('btn-refresh-topo');
  if (refreshTopoBtn) {
    refreshTopoBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      if (mount) fetchAndRenderStorageTopology(mount);
      showToast('Storage topology refreshed.', 'info');
    });
  }

  const createPoolBtn = document.getElementById('btn-create-storage-pool');
  if (createPoolBtn) {
    createPoolBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      openCreateStoragePoolModal(() => {
        if (mount) fetchAndRenderStorageTopology(mount);
      });
    });
  }

  const manageSnapsBtn = document.getElementById('btn-manage-snapshots');
  if (manageSnapsBtn) {
    manageSnapsBtn.addEventListener('click', () => {
      openSnapshotsModal();
    });
  }

  // Network shares refresh & create buttons
  const refreshSharesBtn = document.getElementById('btn-refresh-shares');
  if (refreshSharesBtn) {
    refreshSharesBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      if (mount) fetchAndRenderNetworkShares(mount);
      showToast('Network shares refreshed.', 'info');
    });
  }

  const createShareBtn = document.getElementById('btn-create-network-share');
  if (createShareBtn) {
    createShareBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      openCreateNetworkShareModal(() => {
        if (mount) fetchAndRenderNetworkShares(mount);
      });
    });
  }

  // Remote & Cloud Storage refresh button
  const refreshRemotesBtn = document.getElementById('btn-refresh-remotes');
  if (refreshRemotesBtn) {
    refreshRemotesBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      if (mount) fetchAndRenderRemoteStorage(mount);
      showToast('Remote storage refreshed.', 'info');
    });
  }

  // Connect Cloud Remote button
  const addRemoteBtn = document.getElementById('btn-add-cloud-remote');
  if (addRemoteBtn) {
    addRemoteBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      openNewCloudRemoteModal(() => {
        if (mount) fetchAndRenderRemoteStorage(mount);
      });
    });
  }

  // Disks inventory refresh button
  const refreshDisksInvBtn = document.getElementById('btn-refresh-disks-inventory');

  if (refreshDisksInvBtn) {
    refreshDisksInvBtn.addEventListener('click', () => {
      fetchAndRenderDisksInventory();
      showToast('Disks inventory refreshed.', 'info');
    });
  }

  // Replication refresh and create pipeline buttons
  const refreshReplBtn = document.getElementById('btn-refresh-replication');
  if (refreshReplBtn) {
    refreshReplBtn.addEventListener('click', () => {
      fetchAndRenderReplication();
      showToast('Replication pipelines refreshed.', 'info');
    });
  }

  const createReplBtn = document.getElementById('btn-create-replication-job');
  const replModal = document.getElementById('modal-create-replication-pipeline');
  if (createReplBtn && replModal) {
    const replCloseBtn = document.getElementById('modal-repl-close-btn');
    const replCancelBtn = document.getElementById('modal-repl-cancel-btn');
    const replForm = document.getElementById('create-replication-pipeline-form');
    const replTargetType = document.getElementById('repl-target-type');
    const replRemoteFields = document.getElementById('repl-remote-fields');

    const closeReplModal = () => {
      replModal.classList.remove('open');
      replModal.style.display = 'none';
      if (replForm) replForm.reset();
      if (replRemoteFields) replRemoteFields.style.display = 'none';
    };

    if (replCloseBtn) replCloseBtn.onclick = closeReplModal;
    if (replCancelBtn) replCancelBtn.onclick = closeReplModal;

    if (replTargetType && replRemoteFields) {
      replTargetType.addEventListener('change', () => {
        replRemoteFields.style.display = replTargetType.value === 'local' ? 'none' : 'flex';
      });
    }

    const openReplModal = () => {
      replModal.style.removeProperty('display');
      replModal.style.display = 'flex';
      replModal.classList.add('open');
      bringToFront(replModal);
      const nameInput = document.getElementById('repl-job-name');
      if (nameInput) nameInput.focus();
    };

    createReplBtn.addEventListener('click', openReplModal);

    replModal.addEventListener('click', (e) => {
      if (e.target === replModal) closeReplModal();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && replModal.classList.contains('open')) {
        closeReplModal();
      }
    });

    if (replForm && !replForm._bound) {
      replForm._bound = true;
      replForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = document.getElementById('btn-submit-repl-pipeline');
        try {
          if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Saving...';
          }
          const tType = document.getElementById('repl-target-type')?.value || 'local';
          const payload = {
            name: document.getElementById('repl-job-name')?.value.trim(),
            source_pool: document.getElementById('repl-source-pool')?.value.trim(),
            source_dataset: document.getElementById('repl-source-dataset')?.value.trim(),
            target_type: tType,
            target_pool: document.getElementById('repl-target-pool')?.value.trim(),
            target_dataset: document.getElementById('repl-target-dataset')?.value.trim(),
            schedule: document.getElementById('repl-schedule')?.value || 'daily',
            retention_count: parseInt(document.getElementById('repl-retention')?.value || '14', 10),
          };
          if (tType !== 'local') {
            payload.target_host = document.getElementById('repl-target-host')?.value.trim() || undefined;
            payload.target_port = parseInt(document.getElementById('repl-target-port')?.value || '22', 10);
            payload.target_user = document.getElementById('repl-target-user')?.value.trim() || 'root';
          }
          await api.post('/api/storage/replication/jobs', payload);
          showToast(`Replication pipeline '${payload.name}' created.`, 'success');
          closeReplModal();
          fetchAndRenderReplication();
        } catch (err) {
          showToast(`Failed to create pipeline: ${err.message}`, 'error');
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Save Pipeline';
          }
        }
      });
    }
  }

  // WireGuard refresh button
  const refreshWgBtn = document.getElementById('btn-refresh-wireguard');
  if (refreshWgBtn) {
    refreshWgBtn.addEventListener('click', () => {
      fetchAndRenderWireguard();
      showToast('WireGuard mesh status refreshed.', 'info');
    });
  }

  // Check for updates and release channel toggles
  const checkUpdatesBtn = document.getElementById('btn-check-updates');
  if (checkUpdatesBtn) {
    checkUpdatesBtn.addEventListener('click', () => {
      fetchAndRenderSystemAbout(true);
    });
  }

  const btnChanStable = document.getElementById('btn-channel-stable');
  if (btnChanStable) {
    btnChanStable.addEventListener('click', () => {
      setUpdateChannel('stable');
    });
  }

  const btnChanEdge = document.getElementById('btn-channel-edge');
  if (btnChanEdge) {
    btnChanEdge.addEventListener('click', () => {
      setUpdateChannel('edge');
    });
  }

  const applyUpdateBtn = document.getElementById('btn-apply-system-update');
  if (applyUpdateBtn) {
    applyUpdateBtn.addEventListener('click', applySystemUpdate);
  }

  // Diagnostics bundle buttons
  const downloadDiagBtn = document.getElementById('btn-download-diagnostics');
  if (downloadDiagBtn) {
    downloadDiagBtn.addEventListener('click', downloadDiagnosticsBundle);
  }
  const previewDiagBtn = document.getElementById('btn-preview-diagnostics');
  if (previewDiagBtn) {
    previewDiagBtn.addEventListener('click', previewDiagnosticsSummary);
  }
  const copySupportMdBtn = document.getElementById('btn-copy-support-md');
  if (copySupportMdBtn) {
    copySupportMdBtn.addEventListener('click', copySupportMarkdown);
  }
  const closeDiagPreviewBtn = document.getElementById('diagnostics-preview-close');
  if (closeDiagPreviewBtn) {
    closeDiagPreviewBtn.addEventListener('click', closeDiagnosticsPreviewModal);
  }
  const closeDiagPreviewFooterBtn = document.getElementById('btn-diag-preview-close');
  if (closeDiagPreviewFooterBtn) {
    closeDiagPreviewFooterBtn.addEventListener('click', closeDiagnosticsPreviewModal);
  }
  const copyDiagPreviewBtn = document.getElementById('btn-diag-preview-copy');
  if (copyDiagPreviewBtn) {
    copyDiagPreviewBtn.addEventListener('click', copySupportMarkdown);
  }

  // Notification Center triggers
  const sendTestAlertBtn = document.getElementById('btn-send-test-alert');
  if (sendTestAlertBtn) {
    sendTestAlertBtn.addEventListener('click', testAllNotificationChannels);
  }
  const saveNotifBtn = document.getElementById('btn-save-notifications');
  if (saveNotifBtn) {
    saveNotifBtn.addEventListener('click', saveNotificationsConfig);
  }
  document.querySelectorAll('.notif-cfg-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      openChannelConfigModal(btn.dataset.channel);
    });
  });
  document.querySelectorAll('.notif-test-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      testSingleChannel(btn.dataset.channel);
    });
  });
  const saveChannelModalBtn = document.getElementById('btn-save-channel-modal');
  if (saveChannelModalBtn) {
    saveChannelModalBtn.addEventListener('click', saveCurrentChannelModal);
  }
  const closeChannelModalBtn = document.getElementById('btn-close-channel-modal');
  if (closeChannelModalBtn) {
    closeChannelModalBtn.addEventListener('click', () => {
      const m = document.getElementById('modal-notification-channel');
      if (m) m.style.display = 'none';
    });
  }

  // Hyper-Backup & Snapshots event bindings
  const btnOpenBackupJob = document.getElementById('btn-open-create-backup-job');
  const modalBackupJob = document.getElementById('modal-create-backup-job');
  const btnCloseBackupJob = document.getElementById('modal-backup-job-close-btn');
  const btnCancelBackupJob = document.getElementById('modal-backup-job-cancel-btn');
  const formBackupJob = document.getElementById('create-backup-job-form');
  const btnRefreshBackupJobs = document.getElementById('btn-refresh-backup-jobs');

  if (btnOpenBackupJob && modalBackupJob) {
    btnOpenBackupJob.addEventListener('click', () => {
      modalBackupJob.style.removeProperty('display');
      modalBackupJob.style.display = 'flex';
      modalBackupJob.classList.add('open');
      bringToFront(modalBackupJob);
      const nameInput = document.getElementById('backup-job-name');
      if (nameInput) nameInput.focus();
    });
    modalBackupJob.addEventListener('click', (e) => {
      if (e.target === modalBackupJob) closeBackupModal();
    });
  }
  const closeBackupModal = () => {
    if (modalBackupJob) {
      modalBackupJob.classList.remove('open');
      modalBackupJob.style.display = 'none';
    }
  };
  if (btnCloseBackupJob) btnCloseBackupJob.addEventListener('click', closeBackupModal);
  if (btnCancelBackupJob) btnCancelBackupJob.addEventListener('click', closeBackupModal);

  const destTypeSelect = document.getElementById('backup-job-dest-type');
  const remoteFieldsDiv = document.getElementById('backup-remote-fields');
  if (destTypeSelect && remoteFieldsDiv) {
    destTypeSelect.addEventListener('change', () => {
      remoteFieldsDiv.style.display = destTypeSelect.value === 'remote' ? 'flex' : 'none';
    });
  }

  if (formBackupJob) {
    formBackupJob.addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        name: document.getElementById('backup-job-name')?.value.trim() || 'Untitled Backup Task',
        source_subvolume: document.getElementById('backup-job-subvolume')?.value.trim() || '',
        destination_type: document.getElementById('backup-job-dest-type')?.value || 'remote',
        remote_name: document.getElementById('backup-job-remote-name')?.value.trim() || '',
        remote_path: document.getElementById('backup-job-remote-path')?.value.trim() || '',
        schedule: document.getElementById('backup-job-schedule')?.value || 'daily',
        retention_count: parseInt(document.getElementById('backup-job-retention')?.value, 10) || 7,
        enabled: !!document.getElementById('backup-job-enabled')?.checked,
      };

      try {
        await api.post('/api/backup/schedule', payload);
        showToast('Hyper-backup pipeline saved successfully!', 'success');
        closeBackupModal();
        formBackupJob.reset();
        fetchAndRenderBackupJobs();
      } catch (err) {
        showToast(`Failed to save backup job: ${err.message}`, 'error');
      }
    });
  }

  if (btnRefreshBackupJobs) {
    btnRefreshBackupJobs.addEventListener('click', () => fetchAndRenderBackupJobs());
  }

  // Snapshots modal & actions
  const btnOpenSnapshot = document.getElementById('btn-open-create-snapshot');
  const modalSnapshot = document.getElementById('modal-create-snapshot');
  const btnCloseSnapshot = document.getElementById('modal-create-snapshot-close-btn');
  const btnCancelSnapshot = document.getElementById('modal-create-snapshot-cancel-btn');
  const formSnapshot = document.getElementById('create-snapshot-form');
  const btnRefreshSnapshots = document.getElementById('btn-refresh-snapshots');

  if (btnOpenSnapshot && modalSnapshot) {
    btnOpenSnapshot.addEventListener('click', () => {
      modalSnapshot.style.removeProperty('display');
      modalSnapshot.style.display = 'flex';
      modalSnapshot.classList.add('open');
      bringToFront(modalSnapshot);
      const subvolInput = document.getElementById('snapshot-subvol-input');
      if (subvolInput) subvolInput.focus();
    });
    modalSnapshot.addEventListener('click', (e) => {
      if (e.target === modalSnapshot) closeSnapshotModal();
    });
  }
  const closeSnapshotModal = () => {
    if (modalSnapshot) {
      modalSnapshot.classList.remove('open');
      modalSnapshot.style.display = 'none';
    }
  };
  if (btnCloseSnapshot) btnCloseSnapshot.addEventListener('click', closeSnapshotModal);
  if (btnCancelSnapshot) btnCancelSnapshot.addEventListener('click', closeSnapshotModal);

  if (formSnapshot) {
    formSnapshot.addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        subvol_name: document.getElementById('snapshot-subvol-input')?.value.trim() || '',
        snapshot_name: document.getElementById('snapshot-custom-name-input')?.value.trim() || undefined,
        readonly: !!document.getElementById('snapshot-readonly-input')?.checked,
      };

      try {
        await api.post('/api/backup/snapshots', payload);
        showToast('Filesystem snapshot created successfully!', 'success');
        closeSnapshotModal();
        formSnapshot.reset();
        fetchAndRenderSystemSnapshots();
      } catch (err) {
        showToast(`Failed to create snapshot: ${err.message}`, 'error');
      }
    });
  }

  if (btnRefreshSnapshots) {
    btnRefreshSnapshots.addEventListener('click', () => fetchAndRenderSystemSnapshots());
  }

  // Application Backups event bindings
  const btnRefreshAppBackups = document.getElementById('btn-refresh-app-backups');
  if (btnRefreshAppBackups) {
    btnRefreshAppBackups.addEventListener('click', () => {
      const filterApp = document.getElementById('app-backups-filter-app')?.value || '';
      fetchAndRenderAppBackups(null, filterApp);
      showToast('Application backups refreshed.', 'info');
    });
  }

  const selectFilterAppBackups = document.getElementById('app-backups-filter-app');
  if (selectFilterAppBackups) {
    selectFilterAppBackups.addEventListener('change', () => {
      fetchAndRenderAppBackups(null, selectFilterAppBackups.value);
    });
  }

  // Language switch update
  window.addEventListener('zettnas:lang-changed', () => {
    const activeSection = Array.from(document.querySelectorAll('.mgmt-detail-card')).find((c) => c.style.display !== 'none');
    if (activeSection) {
      showSection(activeSection.id);
    } else if (hubView && hubView.style.display !== 'none') {
      showHub();
    }
  });

  // VM changes listener
  window.addEventListener('vm-updated', () => {
    fetchAndRenderMgmtVms();
  });
}

let _currentUpdateChannel = 'stable';
try {
  const saved = localStorage.getItem('zettnas_update_channel');
  if (saved === 'edge' || saved === 'stable') _currentUpdateChannel = saved;
} catch (e) {}

let _lastUpdateData = null;

export async function setUpdateChannel(channel) {
  _currentUpdateChannel = channel === 'edge' ? 'edge' : 'stable';
  try {
    localStorage.setItem('zettnas_update_channel', _currentUpdateChannel);
  } catch (e) {}
  syncUpdateChannelUI();
  return fetchAndRenderSystemAbout(true, _currentUpdateChannel);
}

function syncUpdateChannelUI() {
  const btnStable = document.getElementById('btn-channel-stable');
  const btnEdge = document.getElementById('btn-channel-edge');
  if (btnStable && btnEdge) {
    if (_currentUpdateChannel === 'edge') {
      btnStable.classList.remove('active');
      btnStable.style.background = 'transparent';
      btnStable.style.color = 'var(--muted)';
      btnEdge.classList.add('active');
      btnEdge.style.background = 'rgba(14, 165, 233, 0.25)';
      btnEdge.style.color = '#38bdf8';
    } else {
      btnEdge.classList.remove('active');
      btnEdge.style.background = 'transparent';
      btnEdge.style.color = 'var(--muted)';
      btnStable.classList.add('active');
      btnStable.style.background = 'rgba(37, 194, 160, 0.25)';
      btnStable.style.color = '#25c2a0';
    }
  }
}

export async function fetchAndRenderSystemAbout(force = false, channelOverride = null) {
  const versionBadge = document.getElementById('about-version-badge');
  const chassisEl = document.getElementById('about-chassis-model');
  const hostEl = document.getElementById('about-host-platform');
  const runtimeEl = document.getElementById('about-runtime-env');
  const uptimeEl = document.getElementById('about-system-uptime');

  const statusIcon = document.getElementById('update-status-icon');
  const statusTitle = document.getElementById('update-status-title');
  const statusDesc = document.getElementById('update-status-desc');
  const lastCheckedEl = document.getElementById('update-last-checked');
  const detailsBox = document.getElementById('update-details-box');
  const releaseTitle = document.getElementById('update-release-title');
  const releaseLink = document.getElementById('update-release-link');
  const releaseNotes = document.getElementById('update-release-notes');

  const btnCheck = document.getElementById('btn-check-updates');
  const btnIcon = document.getElementById('btn-check-updates-icon');
  const btnText = document.getElementById('btn-check-updates-text');

  // Lock button width to prevent horizontal layout shift, keeping Stable/Edge toggle static in place
  if (btnCheck && btnCheck.offsetWidth > 0) {
    btnCheck.style.minWidth = `${Math.max(152, btnCheck.offsetWidth)}px`;
  }

  const channel = channelOverride || _currentUpdateChannel || 'stable';
  syncUpdateChannelUI();

  if (btnIcon && btnText) {
    btnIcon.textContent = '⏳';
    btnText.textContent = 'Checking...';
  }
  if (btnCheck) {
    btnCheck.disabled = true;
  }

  // 1. Fetch system about telemetry
  try {
    const about = await api.get('/api/system/about');
    if (about) {
      const commitTag = about.commit ? ` (${about.commit})` : '';
      const channelLabel = channel === 'edge' ? 'Edge (Rolling)' : (about.release_channel || 'Stable');
      if (versionBadge) versionBadge.textContent = `${about.tag || 'v' + about.version}${commitTag} • ${channelLabel}`;
      if (chassisEl) chassisEl.textContent = about.chassis_model || 'Standard / DIY';
      if (hostEl) hostEl.textContent = `${about.hostname || 'NAS'} (${about.platform || 'Linux'})`;
      if (runtimeEl) runtimeEl.textContent = `${about.containerized ? 'Docker Container' : 'Native Host'} (Python ${about.python_version || '3.12'})`;
      if (uptimeEl && about.uptime_secs != null) {
        const d = Math.floor(about.uptime_secs / 86400);
        const h = Math.floor((about.uptime_secs % 86400) / 3600);
        const m = Math.floor((about.uptime_secs % 3600) / 60);
        uptimeEl.textContent = d > 0 ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
      }
    }
  } catch (err) {
    console.warn('[ZettNAS] Failed to fetch system about info:', err);
  }

  // 2. Fetch update status
  try {
    const data = await api.get(`/api/system/updates?channel=${channel}${force ? '&force=true' : ''}`);
    _lastUpdateData = data;
    if (data) {
      const isEdge = data.channel === 'edge';
      const applyBtn = document.getElementById('btn-apply-system-update');
      const applyText = document.getElementById('btn-apply-update-text');

      if (data.update_available) {
        if (statusIcon) statusIcon.textContent = '🚀';
        if (statusTitle) {
          statusTitle.textContent = isEdge
            ? `Update Available (Edge): ${data.latest_version}`
            : `Update Available: ${data.latest_tag || 'v' + data.latest_version}`;
          statusTitle.style.color = 'var(--warn, #f5a623)';
        }
        if (statusDesc) {
          statusDesc.textContent = isEdge
            ? `Newer commit features are available on the main branch.`
            : `A newer release of ZettNAS Workbench is available on GitHub.`;
        }
        if (detailsBox) detailsBox.style.display = 'block';
        if (releaseTitle) releaseTitle.textContent = data.release_name || `Release ${data.latest_tag}`;
        if (releaseLink) releaseLink.href = data.release_url || 'https://github.com/fr0styx/zettnas-toolkit/releases';
        if (releaseNotes) releaseNotes.textContent = data.release_notes || 'No release notes provided.';

        if (applyBtn && applyText) {
          applyBtn.style.display = 'flex';
          applyText.textContent = isEdge
            ? `Install Latest Commit (${data.latest_version})`
            : `Install Release ${data.latest_tag || 'v' + data.latest_version}`;
        }
      } else {
        if (statusIcon) statusIcon.textContent = '✅';
        if (statusTitle) {
          statusTitle.textContent = isEdge
            ? `ZettNAS Workbench is up to date with main`
            : `ZettNAS Workbench is up to date`;
          statusTitle.style.color = 'var(--ok2, #25c2a0)';
        }
        if (statusDesc) {
          statusDesc.textContent = isEdge
            ? `You are running the latest commit on the main branch (${data.latest_version || data.current_commit || 'latest'}).`
            : `You are running the latest stable release (${data.latest_tag || 'v' + data.current_version}).`;
        }
        if (detailsBox) detailsBox.style.display = 'none';
        if (applyBtn) applyBtn.style.display = 'none';
      }
      if (lastCheckedEl && data.checked_at) {
        const timeStr = new Date(data.checked_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        lastCheckedEl.textContent = `Checked: ${timeStr}`;
      }
    }
  } catch (err) {
    if (statusIcon) statusIcon.textContent = '⚠️';
    if (statusTitle) {
      statusTitle.textContent = 'Unable to check for updates';
      statusTitle.style.color = 'var(--crit, #ff6b6b)';
    }
    if (statusDesc) statusDesc.textContent = err.message || 'Offline or network request failed.';
  } finally {
    if (btnIcon && btnText) {
      btnIcon.textContent = '🔄';
      btnText.textContent = 'Check for Updates';
    }
    if (btnCheck) {
      btnCheck.disabled = false;
    }
  }
}

export async function applySystemUpdate() {
  const applyBtn = document.getElementById('btn-apply-system-update');
  const progressOverlay = document.getElementById('update-progress-overlay');
  const progressTitle = document.getElementById('update-progress-title');
  const progressDesc = document.getElementById('update-progress-desc');

  const channel = _currentUpdateChannel || 'stable';
  const targetTag = _lastUpdateData?.latest_tag || _lastUpdateData?.latest_version || 'latest';

  showConfirmToast(
    t('updates.confirm_title', 'Apply System Update'),
    t(
      'updates.confirm_msg',
      `Update ZettNAS Workbench to ${targetTag} now? The container will pull the updated image and restart. Your data and settings are safely preserved.`
    ),
    async () => {
      if (applyBtn) applyBtn.disabled = true;
      if (progressOverlay) progressOverlay.style.display = 'block';
      if (progressTitle) progressTitle.textContent = t('updates.installing', 'Downloading & Applying Update...');
      if (progressDesc) progressDesc.textContent = 'Pulling container image layers from GHCR...';

      try {
        const res = await api.post('/api/system/updates/apply', { channel });
        showToast(res?.message || 'Update initiated. Reconnecting...', 'info');

        if (progressDesc) progressDesc.textContent = res?.message || 'Restarting container and reconnecting...';

        // Poll health endpoint until back online
        let attempts = 0;
        const maxAttempts = 40;
        const interval = setInterval(async () => {
          attempts++;
          try {
            const h = await fetch('/api/health', { cache: 'no-store' });
            if (h.ok) {
              clearInterval(interval);
              if (progressTitle) progressTitle.textContent = '🎉 Update Complete!';
              if (progressDesc) progressDesc.textContent = 'Reloading ZettNAS Workbench...';
              showToast(t('updates.updated_success', 'ZettNAS updated successfully!'), 'success');
              setTimeout(() => window.location.reload(), 1200);
            }
          } catch (e) {
            if (attempts >= maxAttempts) {
              clearInterval(interval);
              if (progressDesc) progressDesc.textContent = 'Please refresh the page once the container has restarted.';
              if (applyBtn) applyBtn.disabled = false;
            }
          }
        }, 1500);
      } catch (err) {
        showToast(`Update failed: ${err.message}`, 'error');
        if (progressOverlay) progressOverlay.style.display = 'none';
        if (applyBtn) applyBtn.disabled = false;
      }
    },
    null,
    { isUpdate: true }
  );
}

export async function downloadDiagnosticsBundle() {
  const btn = document.getElementById('btn-download-diagnostics');
  const btnIcon = document.getElementById('btn-download-diagnostics-icon');
  const btnText = document.getElementById('btn-download-diagnostics-text');

  if (btn) btn.disabled = true;
  if (btnIcon) btnIcon.textContent = '⏳';
  if (btnText) btnText.textContent = t('diagnostics.generating', 'Generating Archive...');

  showToast(t('diagnostics.toast_generating', 'Generating diagnostics bundle (scrubbing secrets)...'), 'info');

  try {
    const clientEnv = collectClientEnvironment();
    const frontendLogs = getClientLogs();
    const payload = {
      client_environment: clientEnv,
      frontend_logs: frontendLogs,
    };

    let filename;
    try {
      filename = await api.downloadBlob('/api/system/diagnostics-bundle', 'zettnas_diagnostics.zip', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (postErr) {
      // Graceful fallback to GET if POST route is rejected by proxy
      filename = await api.downloadBlob('/api/system/diagnostics-bundle', 'zettnas_diagnostics.zip');
    }
    showToast(t('diagnostics.download_success', 'Diagnostics bundle downloaded successfully') + ` (${filename}).`, 'success');
  } catch (err) {
    showToast(t('diagnostics.download_failed', 'Failed to download diagnostics') + `: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (btnIcon) btnIcon.textContent = '📦';
    if (btnText) btnText.textContent = t('diagnostics.download_btn', 'Download Diagnostics Bundle');
  }
}

export function closeDiagnosticsPreviewModal() {
  const overlay = document.getElementById('diagnostics-preview-modal-overlay');
  if (overlay) overlay.style.display = 'none';
}

export function openDiagnosticsPreviewModal(data) {
  const overlay = document.getElementById('diagnostics-preview-modal-overlay');
  const banner = document.getElementById('diagnostics-preview-banner');
  const grid = document.getElementById('diagnostics-preview-grid');
  const mdEl = document.getElementById('diagnostics-preview-md');
  if (!overlay || !data) return;

  if (mdEl) {
    mdEl.textContent = data.support_markdown || 'No summary generated.';
  }

  if (banner) {
    const status = data.executive_status || 'HEALTHY';
    const alerts = Array.isArray(data.alerts) ? data.alerts : [];

    let borderColor = 'rgba(37, 194, 160, 0.3)';
    let bgColor = 'rgba(37, 194, 160, 0.08)';
    let badgeColor = 'var(--accent, #25c2a0)';
    let icon = '🟢';
    let title = t('diagnostics.status_healthy', 'SYSTEM HEALTHY');
    let desc = t('diagnostics.status_healthy_desc', 'All hardware parameters, storage arrays, and containers are operating normally.');

    if (status === 'CRITICAL') {
      borderColor = 'rgba(239, 68, 68, 0.5)';
      bgColor = 'rgba(239, 68, 68, 0.12)';
      badgeColor = '#ef4444';
      icon = '🚨';
      title = t('diagnostics.status_critical', 'CRITICAL ISSUES DETECTED');
      desc = t('diagnostics.status_critical_desc', 'Hardware failure, degraded drive arrays, or thermal clamp thresholds reached.');
    } else if (status === 'ATTENTION_REQUIRED') {
      borderColor = 'rgba(245, 158, 11, 0.4)';
      bgColor = 'rgba(245, 158, 11, 0.1)';
      badgeColor = '#f59e0b';
      icon = '⚠️';
      title = t('diagnostics.status_attention', 'ATTENTION REQUIRED');
      desc = t('diagnostics.status_attention_desc', 'Non-critical system warnings, restarting containers, or hardware bus notices.');
    }

    let alertItemsHtml = '';
    if (alerts.length > 0) {
      alertItemsHtml = `
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; flex-direction: column; gap: 4px;">
          ${alerts
            .map(
              (a) => `
            <div style="font-size: 11px; color: #f1f5f9; display: flex; align-items: flex-start; gap: 6px;">
              <span style="font-size: 10px; margin-top: 2px;">${a.level === 'critical' ? '🔴' : '🟡'}</span>
              <span>${escapeHtml(a.message || '')}</span>
            </div>
          `
            )
            .join('')}
        </div>
      `;
    }

    banner.innerHTML = `
      <div style="padding: 10px 14px; background: ${bgColor}; border: 1px solid ${borderColor}; border-radius: 8px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 14px;">${icon}</span>
            <span style="font-size: 12px; font-weight: 800; color: ${badgeColor}; letter-spacing: 0.5px;">${escapeHtml(title)}</span>
          </div>
          <span style="font-size: 10px; color: var(--muted); font-family: monospace;">ZettOS Kernel ${escapeHtml(data.platform || '')}</span>
        </div>
        <div style="font-size: 11px; color: var(--muted); margin-top: 3px;">${escapeHtml(desc)}</div>
        ${alertItemsHtml}
      </div>
    `;
    banner.style.display = 'block';
  }

  if (grid) {
    const memory = data.memory || {};
    const storage = data.storage || {};
    const docker = data.docker || {};
    const vms = data.vms || {};

    const memPct = memory.pct !== undefined ? memory.pct : (memory.used_percent || 0);
    const memTotalGb = memory.total_gb !== undefined ? memory.total_gb : Math.round((memory.total_bytes || 0) / (1024 ** 3));
    const memUsedGb = memory.used_gb !== undefined ? memory.used_gb : Math.round((memory.used_bytes || 0) / (1024 ** 3));

    grid.innerHTML = `
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; font-weight:700;">Host & OS</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${escapeHtml(data.chassis || 'Appliance')}</div>
        <div style="font-size:10px; color:var(--muted); margin-top:1px;">Uptime: ${data.uptime_hours || 0}h</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; font-weight:700;">Memory</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${memPct}% Used</div>
        <div style="font-size:10px; color:var(--muted); margin-top:1px;">${memUsedGb} / ${memTotalGb} GB RAM</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; font-weight:700;">Storage</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${storage.pools_count || 0} Pools</div>
        <div style="font-size:10px; color:${(storage.degraded_disks?.length || 0) > 0 ? 'var(--crit)' : 'var(--muted)'}; margin-top:1px;">${storage.disks_count || 0} Drives (${storage.standby_count || 0} standby)</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; font-weight:700;">Docker Fleet</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${docker.running || 0} / ${docker.total || 0} Running</div>
        <div style="font-size:10px; color:${(docker.restarting || 0) > 0 ? 'var(--crit)' : 'var(--muted)'}; margin-top:1px;">${docker.restarting || 0} Restarting, ${docker.dead || 0} Dead</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; font-weight:700;">Virtual Machines</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${vms.active_vm_count || 0} / ${vms.total_vm_count || 0} Active</div>
        <div style="font-size:10px; color:var(--muted); margin-top:1px;">Headroom: Safe</div>
      </div>
    `;
  }

  overlay.style.display = 'flex';
}

export async function previewDiagnosticsSummary() {
  try {
    const data = await api.get('/api/system/diagnostics-summary');
    openDiagnosticsPreviewModal(data);
  } catch (err) {
    showToast(`Failed to load diagnostics preview: ${err.message}`, 'error');
  }
}

export async function copySupportMarkdown() {
  try {
    const data = await api.get('/api/system/diagnostics-summary');
    const md = data?.support_markdown || '';
    if (!md) throw new Error('No support markdown generated');

    const copied = await copyTextToClipboard(md);
    if (copied) {
      showToast(t('diagnostics.copied', 'Support markdown copied to clipboard!'), 'success');
    } else {
      throw new Error('Clipboard copy failed');
    }
  } catch (err) {
    showToast(`Failed to copy support markdown: ${err.message}`, 'error');
  }
}

// ============================================================================
// Notifications & Alert Channels Subsystem
// ============================================================================
let _notificationConfig = null;

export async function fetchAndRenderNotificationConfig() {
  try {
    const res = await api.get('/api/notifications/config');
    _notificationConfig = res || {};
    renderNotificationConfigUI();
  } catch (err) {
    logger.error('Failed to load notification config:', err);
    showToast(t('notif.load_fail', 'Failed to load notification settings'), 'error');
  }
}

export function renderNotificationConfigUI() {
  if (!_notificationConfig) return;
  const cfg = _notificationConfig;

  // Master switch
  const masterSwitch = document.getElementById('notif-master-enabled');
  const masterBadge = document.getElementById('notif-master-status-badge');
  if (masterSwitch) masterSwitch.checked = !!cfg.enabled;
  if (masterBadge) {
    masterBadge.textContent = cfg.enabled ? t('notif.badge.active', 'Active') : t('notif.badge.disabled', 'Disabled');
    masterBadge.style.background = cfg.enabled ? 'rgba(37,194,160,0.15)' : 'rgba(255,255,255,0.06)';
    masterBadge.style.color = cfg.enabled ? 'var(--ok2)' : 'var(--muted)';
    masterBadge.style.border = cfg.enabled ? '1px solid rgba(37,194,160,0.4)' : '1px solid rgba(255,255,255,0.1)';
  }

  // Channel badges
  const updateBadge = (id, active, activeText = 'Active') => {
    const b = document.getElementById(id);
    if (!b) return;
    b.textContent = active ? activeText : 'Off';
    b.style.background = active ? 'rgba(37,194,160,0.15)' : 'rgba(255,255,255,0.06)';
    b.style.color = active ? 'var(--ok2)' : 'var(--muted)';
    b.style.border = active ? '1px solid rgba(37,194,160,0.4)' : '1px solid rgba(255,255,255,0.1)';
  };

  updateBadge('notif-badge-discord', !!(cfg.discord_enabled && cfg.discord_webhook_url));
  updateBadge('notif-badge-telegram', !!(cfg.telegram_enabled && cfg.telegram_bot_token && cfg.telegram_chat_id));
  updateBadge('notif-badge-email', !!(cfg.email_enabled && cfg.smtp_host));
  updateBadge('notif-badge-ntfy', !!(cfg.ntfy_enabled && cfg.ntfy_topic));
  updateBadge('notif-badge-webhook', !!(cfg.webhook_enabled && cfg.webhook_url));

  const rawCount = Array.isArray(cfg.apprise_urls) ? cfg.apprise_urls.length : 0;
  updateBadge('notif-badge-apprise', rawCount > 0, `${rawCount} URLs`);

  // Event trigger checkboxes
  const setChk = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.checked = val !== false;
  };
  setChk('notif-toggle-smart', cfg.notify_on_smart);
  setChk('notif-toggle-ups', cfg.notify_on_ups);
  setChk('notif-toggle-temp', cfg.notify_on_temp);
  setChk('notif-toggle-fan', cfg.notify_on_fan);
  setChk('notif-toggle-copy', cfg.notify_on_copy);
  setChk('notif-toggle-container', cfg.notify_on_container);
  setChk('notif-toggle-backup', cfg.notify_on_backup);

  // Thresholds
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined) el.value = val;
  };
  setVal('notif-input-hdd-temp', cfg.hdd_temp_threshold ?? 50);
  setVal('notif-input-cpu-temp', cfg.cpu_temp_threshold ?? 80);
  setVal('notif-input-cooldown', Math.round((cfg.cooldown_seconds ?? 1800) / 60));
}

export async function saveNotificationsConfig() {
  if (!_notificationConfig) _notificationConfig = {};
  const cfg = _notificationConfig;

  cfg.enabled = !!document.getElementById('notif-master-enabled')?.checked;
  cfg.notify_on_smart = !!document.getElementById('notif-toggle-smart')?.checked;
  cfg.notify_on_ups = !!document.getElementById('notif-toggle-ups')?.checked;
  cfg.notify_on_temp = !!document.getElementById('notif-toggle-temp')?.checked;
  cfg.notify_on_fan = !!document.getElementById('notif-toggle-fan')?.checked;
  cfg.notify_on_copy = !!document.getElementById('notif-toggle-copy')?.checked;
  cfg.notify_on_container = !!document.getElementById('notif-toggle-container')?.checked;
  cfg.notify_on_backup = !!document.getElementById('notif-toggle-backup')?.checked;

  const hdd = parseInt(document.getElementById('notif-input-hdd-temp')?.value, 10);
  if (!isNaN(hdd)) cfg.hdd_temp_threshold = Math.max(30, Math.min(80, hdd));

  const cpu = parseInt(document.getElementById('notif-input-cpu-temp')?.value, 10);
  if (!isNaN(cpu)) cfg.cpu_temp_threshold = Math.max(40, Math.min(105, cpu));

  const cd = parseInt(document.getElementById('notif-input-cooldown')?.value, 10);
  if (!isNaN(cd)) cfg.cooldown_seconds = Math.max(1, Math.min(1440, cd)) * 60;

  try {
    const res = await api.post('/api/notifications/config', cfg);
    _notificationConfig = res.config || cfg;
    renderNotificationConfigUI();
    showToast(t('notif.saved_ok', 'Notification settings saved successfully!'), 'success');
  } catch (err) {
    logger.error('Failed to save notification settings:', err);
    showToast(err.message || 'Failed to save notifications', 'error');
  }
}

export async function testAllNotificationChannels() {
  const btn = document.getElementById('btn-send-test-alert');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Testing...';
  }
  try {
    const res = await api.post('/api/notifications/test', {});
    const channels = res?.tested_channels || {};
    const successList = Object.keys(channels).filter(k => channels[k]);
    if (successList.length > 0) {
      showToast(`✓ Test alerts delivered to: ${successList.join(', ')}`, 'success');
    } else {
      showToast('No active channels succeeded. Check configuration and credentials.', 'warning');
    }
  } catch (err) {
    showToast(`Test failed: ${err.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `⚡ <span data-i18n="mgmt.notif_btn_test_all">Send Test Alert</span>`;
    }
  }
}

export async function testSingleChannel(channel) {
  const btn = document.querySelector(`.notif-test-btn[data-channel="${channel}"]`);
  const origText = btn ? btn.textContent : '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳';
  }
  try {
    const res = await api.post('/api/notifications/test-channel', {
      channel: channel,
      config: _notificationConfig || {}
    });
    if (res?.success) {
      showToast(`✓ ${channel.toUpperCase()}: Delivered in ${res.latency_ms}ms`, 'success');
    } else {
      showToast(`⚠️ ${channel.toUpperCase()}: ${res.message || 'Delivery failed'}`, 'error');
    }
  } catch (err) {
    showToast(`Test failed for ${channel}: ${err.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }
}

export function openChannelConfigModal(channel) {
  const modal = document.getElementById('modal-notification-channel');
  if (!modal) return;
  const cfg = _notificationConfig || {};

  const titleEl = document.getElementById('notif-modal-title');
  const bodyEl = document.getElementById('notif-modal-body');
  const enableChk = document.getElementById('notif-modal-channel-enable');

  if (titleEl) titleEl.textContent = `Configure ${channel.charAt(0).toUpperCase() + channel.slice(1)} Alerts`;

  let formHtml = '';
  if (channel === 'discord') {
    if (enableChk) enableChk.checked = !!cfg.discord_enabled;
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">DISCORD WEBHOOK URL</label>
        <input type="url" id="cfg-discord-url" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="https://discord.com/api/webhooks/..." value="${escapeHtml(cfg.discord_webhook_url || '')}">
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Paste the Webhook URL created in your Discord channel settings -> Integrations.</div>
      </div>
    `;
  } else if (channel === 'telegram') {
    if (enableChk) enableChk.checked = !!cfg.telegram_enabled;
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">TELEGRAM BOT TOKEN</label>
        <input type="password" id="cfg-telegram-token" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="123456789:ABCDefgh..." value="${escapeHtml(cfg.telegram_bot_token || '')}">
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">TELEGRAM CHAT ID</label>
        <input type="text" id="cfg-telegram-chat" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="-100123456789" value="${escapeHtml(cfg.telegram_chat_id || '')}">
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Obtained from @userinfobot or your Telegram channel/group chat ID.</div>
      </div>
    `;
  } else if (channel === 'email') {
    if (enableChk) enableChk.checked = !!cfg.email_enabled;
    formHtml = `
      <div style="display:grid; grid-template-columns: 2fr 1fr; gap:10px; margin-bottom:12px;">
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">SMTP HOST</label>
          <input type="text" id="cfg-smtp-host" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="smtp.gmail.com" value="${escapeHtml(cfg.smtp_host || '')}">
        </div>
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">PORT</label>
          <input type="number" id="cfg-smtp-port" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" value="${cfg.smtp_port || 587}">
        </div>
      </div>
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">SMTP USER</label>
          <input type="text" id="cfg-smtp-user" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="user@domain.com" value="${escapeHtml(cfg.smtp_user || '')}">
        </div>
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">SMTP PASSWORD</label>
          <input type="password" id="cfg-smtp-pass" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="••••••••" value="${escapeHtml(cfg.smtp_pass || '')}">
        </div>
      </div>
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">FROM EMAIL</label>
          <input type="email" id="cfg-email-from" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="nas@domain.com" value="${escapeHtml(cfg.email_from || '')}">
        </div>
        <div>
          <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">TO RECIPIENT(S)</label>
          <input type="email" id="cfg-email-to" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="admin@domain.com" value="${escapeHtml(cfg.email_to || '')}">
        </div>
      </div>
      <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-size:11px; color:#fff;">
        <input type="checkbox" id="cfg-smtp-tls" ${cfg.smtp_tls !== false ? 'checked' : ''}> Use TLS / STARTTLS Encryption
      </label>
    `;
  } else if (channel === 'ntfy') {
    if (enableChk) enableChk.checked = !!cfg.ntfy_enabled;
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">NTFY SERVER URL</label>
        <input type="url" id="cfg-ntfy-url" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="https://ntfy.sh" value="${escapeHtml(cfg.ntfy_url || 'https://ntfy.sh')}">
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">TOPIC NAME</label>
        <input type="text" id="cfg-ntfy-topic" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="my_nas_alerts" value="${escapeHtml(cfg.ntfy_topic || '')}">
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">ACCESS TOKEN (Optional)</label>
        <input type="password" id="cfg-ntfy-token" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="tk_••••••••" value="${escapeHtml(cfg.ntfy_token || '')}">
      </div>
    `;
  } else if (channel === 'webhook') {
    if (enableChk) enableChk.checked = !!cfg.webhook_enabled;
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">WEBHOOK URL</label>
        <input type="url" id="cfg-webhook-url" class="tz-select-input" style="width:100%; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="https://..." value="${escapeHtml(cfg.webhook_url || '')}">
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Receives POST requests with JSON payload: { event, title, message, level, timestamp }</div>
      </div>
    `;
  } else if (channel === 'apprise_raw') {
    const rawVal = Array.isArray(cfg.apprise_urls) ? cfg.apprise_urls.join('\n') : '';
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">APPRISE TARGET URLS (One per line)</label>
        <textarea id="cfg-apprise-raw" class="tz-select-input" style="width:100%; height:120px; font-family:monospace; font-size:11px; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="pover://userkey@token&#10;slack://TokenA/TokenB/TokenC&#10;gotify://gotify.server/token">${escapeHtml(rawVal)}</textarea>
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Apprise supports 100+ notification targets. See Apprise documentation for syntax.</div>
      </div>
    `;
  }

  if (bodyEl) bodyEl.innerHTML = formHtml;
  modal.dataset.currentChannel = channel;
  modal.style.display = 'flex';
}

export function saveCurrentChannelModal() {
  const modal = document.getElementById('modal-notification-channel');
  if (!modal) return;
  const channel = modal.dataset.currentChannel;
  if (!_notificationConfig) _notificationConfig = {};
  const cfg = _notificationConfig;
  const enabled = !!document.getElementById('notif-modal-channel-enable')?.checked;

  if (channel === 'discord') {
    cfg.discord_enabled = enabled;
    cfg.discord_webhook_url = document.getElementById('cfg-discord-url')?.value.trim() || '';
  } else if (channel === 'telegram') {
    cfg.telegram_enabled = enabled;
    const tok = document.getElementById('cfg-telegram-token')?.value.trim() || '';
    if (tok && tok !== '********') cfg.telegram_bot_token = tok;
    cfg.telegram_chat_id = document.getElementById('cfg-telegram-chat')?.value.trim() || '';
  } else if (channel === 'email') {
    cfg.email_enabled = enabled;
    cfg.smtp_host = document.getElementById('cfg-smtp-host')?.value.trim() || '';
    cfg.smtp_port = parseInt(document.getElementById('cfg-smtp-port')?.value, 10) || 587;
    cfg.smtp_user = document.getElementById('cfg-smtp-user')?.value.trim() || '';
    const pass = document.getElementById('cfg-smtp-pass')?.value || '';
    if (pass && pass !== '********') cfg.smtp_pass = pass;
    cfg.smtp_tls = !!document.getElementById('cfg-smtp-tls')?.checked;
    cfg.email_from = document.getElementById('cfg-email-from')?.value.trim() || '';
    cfg.email_to = document.getElementById('cfg-email-to')?.value.trim() || '';
  } else if (channel === 'ntfy') {
    cfg.ntfy_enabled = enabled;
    cfg.ntfy_url = document.getElementById('cfg-ntfy-url')?.value.trim() || 'https://ntfy.sh';
    cfg.ntfy_topic = document.getElementById('cfg-ntfy-topic')?.value.trim() || '';
    const tk = document.getElementById('cfg-ntfy-token')?.value.trim() || '';
    if (tk && tk !== '********') cfg.ntfy_token = tk;
  } else if (channel === 'webhook') {
    cfg.webhook_enabled = enabled;
    cfg.webhook_url = document.getElementById('cfg-webhook-url')?.value.trim() || '';
  } else if (channel === 'apprise_raw') {
    const rawLines = document.getElementById('cfg-apprise-raw')?.value.split('\n') || [];
    cfg.apprise_urls = rawLines.map(l => l.trim()).filter(Boolean);
  }

  saveNotificationsConfig();
  modal.style.display = 'none';
}


// =========================================================================
// Hyper-Backup Tasks & 3-2-1 Pipelines
// =========================================================================

export async function fetchAndRenderBackupJobs(mountEl) {
  const mount = mountEl || document.getElementById('backup-jobs-mount');
  if (!mount) return;

  try {
    const data = await api.get('/api/backup/schedule');
    const jobs = (data && data.jobs) || [];

    if (jobs.length === 0) {
      mount.innerHTML = `
        <div style="text-align: center; padding: 24px 16px; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px dashed rgba(255,255,255,0.1);">
          <div style="font-size: 24px; margin-bottom: 8px;">🛡️</div>
          <div style="font-size: 13px; font-weight: 700; color: #fff; margin-bottom: 4px;">No Backup Pipelines Configured</div>
          <div style="font-size: 11.5px; color: var(--muted); max-width: 400px; margin: 0 auto 12px; line-height: 1.4;">
            Automate snapshot rotation and offsite cloud backups to protect against drive failure, ransomware, or accidental deletion.
          </div>
          <button type="button" class="btn-rect primary" onclick="document.getElementById('btn-open-create-backup-job')?.click()" style="font-size: 11px; padding: 6px 14px;">
            Configure First Pipeline
          </button>
        </div>
      `;
      return;
    }

    const rowsHtml = jobs.map(job => {
      const isRemote = job.destination_type === 'remote';
      const destBadge = isRemote
        ? `<span class="badge" style="background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid rgba(14,165,233,0.3); font-size: 10px; padding: 2px 6px; border-radius: 4px;">☁️ ${escapeHtml(job.remote_name || 'Cloud')}:${escapeHtml(job.remote_path || '')}</span>`
        : `<span class="badge" style="background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); font-size: 10px; padding: 2px 6px; border-radius: 4px;">📸 Local Snapshot</span>`;

      const schedBadge = `<span class="badge" style="background: rgba(255,255,255,0.06); color: #cbd5e1; font-size: 10px; padding: 2px 6px; border-radius: 4px; text-transform: capitalize;">${escapeHtml(job.schedule || 'daily')}</span>`;
      
      let statusHtml = '';
      if (job.last_status === 'running') {
        statusHtml = `<span style="display:inline-flex; align-items:center; gap:4px; color: #38bdf8; font-size: 11px;"><span class="spinner-inline" style="width:10px; height:10px;"></span> Running...</span>`;
      } else if (job.last_status === 'success') {
        statusHtml = `<span style="color: #34d399; font-size: 11px; font-weight:600;">✓ Success</span>`;
      } else if (job.last_status === 'error') {
        statusHtml = `<span style="color: #f43f5e; font-size: 11px; font-weight:600;" title="${escapeHtml(job.last_error || '')}">⚠ Failed</span>`;
      } else {
        statusHtml = `<span style="color: var(--muted); font-size: 11px;">Idle</span>`;
      }

      const lastRunStr = job.last_run_at ? new Date(job.last_run_at * 1000).toLocaleString() : 'Never';

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11.5px;">
          <td style="padding: 10px 12px; font-weight: 600; color: #fff;">
            <div>${escapeHtml(job.name)}</div>
            <div style="font-size: 10px; color: var(--muted); font-weight: normal;">Subvolume: <code>${escapeHtml(job.source_subvolume || '@shares')}</code></div>
          </td>
          <td style="padding: 10px 12px;">${destBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
              ${schedBadge}
              <span style="font-size: 10px; color: var(--muted);">Keep ${job.retention_count || 7}</span>
            </div>
          </td>
          <td style="padding: 10px 12px;">
            <div>${statusHtml}</div>
            <div style="font-size: 10px; color: var(--muted);">${lastRunStr}</div>
          </td>
          <td style="padding: 10px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect primary btn-run-backup-job" data-job-id="${escapeHtml(job.id)}" title="Run Backup Job Now">
                ▶ Run
              </button>
              <button class="btn-rect danger btn-delete-backup-job" data-job-id="${escapeHtml(job.id)}" title="Delete Backup Job">
                🗑️
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    mount.innerHTML = `
      <div style="overflow-x: auto; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 10px; font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">Task & Target</th>
              <th style="padding: 8px 12px;">Pipeline</th>
              <th style="padding: 8px 12px;">Schedule & Retention</th>
              <th style="padding: 8px 12px;">Last Run</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    `;

    mount.querySelectorAll('.btn-run-backup-job').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.dataset.jobId;
        const origText = btn.innerHTML;
        try {
          btn.disabled = true;
          btn.innerHTML = `<span class="spinner-inline" style="width:8px; height:8px;"></span>`;
          showToast(`Triggering backup pipeline ${jobId}...`, 'info');
          await api.post(`/api/backup/schedule/${jobId}/run`);
          showToast(`Backup pipeline completed successfully!`, 'success');
          fetchAndRenderBackupJobs(mount);
        } catch (err) {
          showToast(`Backup run failed: ${err.message}`, 'error');
        } finally {
          btn.disabled = false;
          btn.innerHTML = origText;
        }
      });
    });

    mount.querySelectorAll('.btn-delete-backup-job').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.dataset.jobId;
        showConfirmToast(`Delete scheduled backup task "${jobId}"?`, async () => {
          try {
            await api.delete(`/api/backup/schedule/${jobId}`);
            showToast('Backup task removed.', 'success');
            fetchAndRenderBackupJobs(mount);
          } catch (err) {
            showToast(`Failed to delete job: ${err.message}`, 'error');
          }
        });
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: 12px;">Failed to load backup jobs: ${escapeHtml(err.message)}</div>`;
  }
}

// =========================================================================
// Storage Pool Snapshots & Revert
// =========================================================================

export async function fetchAndRenderSystemSnapshots(mountEl) {
  const mount = mountEl || document.getElementById('system-snapshots-mount');
  if (!mount) return;

  try {
    const data = await api.get('/api/backup/snapshots');
    const snaps = (data && data.snapshots) || [];

    if (snaps.length === 0) {
      mount.innerHTML = `
        <div style="text-align: center; padding: 20px; font-size: 12px; color: var(--muted);">
          No active filesystem snapshots found. Click "Take Snapshot" to create an atomic snapshot.
        </div>
      `;
      return;
    }

    const rowsHtml = snaps.map(s => {
      const createdDate = s.created_at ? new Date(s.created_at * 1000).toLocaleString() : 'N/A';
      const poolId = s.pool_id || 'default';
      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11.5px;">
          <td style="padding: 8px 12px; font-weight: 600; color: #fff;">
            <span style="font-family: monospace;">📸 ${escapeHtml(s.name)}</span>
          </td>
          <td style="padding: 8px 12px; color: var(--muted); font-size: 11px;">
            ${escapeHtml(s.path || '')}
          </td>
          <td style="padding: 8px 12px; color: var(--muted); font-size: 11px;">
            ${createdDate}
          </td>
          <td style="padding: 8px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect btn-sys-restore-snap" data-snap-name="${escapeHtml(s.name)}" data-pool-id="${escapeHtml(poolId)}" title="Rollback to this snapshot">
                ⏪ Restore
              </button>
              <button class="btn-rect danger btn-sys-delete-snap" data-snap-name="${escapeHtml(s.name)}" data-pool-id="${escapeHtml(poolId)}" title="Delete Snapshot">
                🗑️
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    mount.innerHTML = `
      <div style="overflow-x: auto; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 10px; font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">Snapshot Name</th>
              <th style="padding: 8px 12px;">Filesystem Path</th>
              <th style="padding: 8px 12px;">Created</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    `;

    mount.querySelectorAll('.btn-sys-restore-snap').forEach(btn => {
      btn.addEventListener('click', () => {
        const snapName = btn.dataset.snapName;
        const poolId = btn.dataset.poolId || 'default';
        showConfirmToast(`Roll back to snapshot "${snapName}"? Existing subvolume will be archived safely.`, async () => {
          try {
            showToast(`Restoring snapshot ${snapName}...`, 'info');
            await api.post('/api/backup/restore-snapshot', {
              pool_id: poolId,
              snapshot_name: snapName,
            });
            showToast(`Snapshot "${snapName}" successfully restored!`, 'success');
            fetchAndRenderSystemSnapshots(mount);
          } catch (err) {
            showToast(`Restore failed: ${err.message}`, 'error');
          }
        });
      });
    });

    mount.querySelectorAll('.btn-sys-delete-snap').forEach(btn => {
      btn.addEventListener('click', () => {
        const snapName = btn.dataset.snapName;
        const poolId = btn.dataset.poolId || 'default';
        showConfirmToast(`Delete snapshot "${snapName}"?`, async () => {
          try {
            await api.delete(`/api/backup/snapshots/${encodeURIComponent(poolId)}/${encodeURIComponent(snapName)}`);
            showToast(`Snapshot "${snapName}" deleted.`, 'success');
            fetchAndRenderSystemSnapshots(mount);
          } catch (err) {
            showToast(`Failed to delete snapshot: ${err.message}`, 'error');
          }
        });
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: 12px;">Failed to load snapshots: ${escapeHtml(err.message)}</div>`;
  }
}

// =========================================================================
// Application Backups & Recovery (Per-App & Box-Wide)
// =========================================================================

export async function fetchAndRenderAppBackups(mountEl, filterApp = '') {
  const mount = mountEl || document.getElementById('app-backups-mount');
  if (!mount) return;

  try {
    const url = `/api/backup/apps${filterApp ? `?app_name=${encodeURIComponent(filterApp)}` : ''}`;
    const data = await api.get(url);
    const backups = Array.isArray(data) ? data : (data?.backups || []);

    // Update filter dropdown options if element exists and not currently active
    const filterSelect = document.getElementById('app-backups-filter-app');
    if (filterSelect && (!filterApp || filterSelect.options.length <= 1)) {
      const currentVal = filterSelect.value || filterApp;
      const allData = filterApp ? await api.get('/api/backup/apps') : data;
      const allBackups = Array.isArray(allData) ? allData : (allData?.backups || []);
      const appNames = Array.from(new Set(allBackups.map(b => b.container_name).filter(Boolean))).sort();
      
      filterSelect.innerHTML = `<option value="">All Applications (Box-Wide)</option>` +
        appNames.map(name => `<option value="${escapeHtml(name)}" ${name === currentVal ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
    }

    if (backups.length === 0) {
      mount.innerHTML = `
        <div style="text-align: center; padding: 24px 16px; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px dashed rgba(255,255,255,0.1);">
          <div style="font-size: 24px; margin-bottom: 8px;">📦</div>
          <div style="font-size: 13px; font-weight: 700; color: #fff; margin-bottom: 4px;">No Application Backups Found</div>
          <div style="font-size: 11.5px; color: var(--muted); max-width: 440px; margin: 0 auto; line-height: 1.4;">
            ${filterApp ? `No backups recorded for "${escapeHtml(filterApp)}".` : 'Backups are automatically created whenever containers are uninstalled with archiving enabled, or on-demand via the Container Inspector.'}
          </div>
        </div>
      `;
      return;
    }

    const rowsHtml = backups.map(b => {
      const isUninstall = b.reason === 'uninstall';
      const reasonBadge = isUninstall
        ? `<span class="badge" style="background: rgba(239,68,68,0.15); color: #fca5a5; border: 1px solid rgba(239,68,68,0.3); font-size: 10px; padding: 2px 6px; border-radius: 4px;">⚠️ Auto-Archive (Uninstall)</span>`
        : `<span class="badge" style="background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.35); font-size: 10px; padding: 2px 6px; border-radius: 4px;">💾 On-Demand</span>`;

      const createdDate = b.created_at_epoch ? new Date(b.created_at_epoch * 1000).toLocaleString() : (b.created_at ? new Date(b.created_at).toLocaleString() : 'N/A');
      const sizeStr = b.archive_size_formatted || (b.archive_size_bytes ? `${(b.archive_size_bytes / (1024 * 1024)).toFixed(1)} MB` : '--');
      const stackHtml = b.stack ? `<span style="font-size:10px; color:var(--muted); margin-left:6px;">(Stack: <code>${escapeHtml(b.stack)}</code>)</span>` : '';
      const mountsCount = b.mounts_count || (b.mounts ? b.mounts.length : 0);

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11.5px;">
          <td style="padding: 10px 12px; font-weight: 600; color: #fff;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span>📦</span>
              <strong>${escapeHtml(b.container_name || b.id)}</strong>
              ${stackHtml}
            </div>
            <div style="font-size: 10px; color: var(--muted); font-weight: normal; margin-top:2px;">
              Image: <code style="font-size:9.5px; color:#cbd5e1;">${escapeHtml(b.image || 'N/A')}</code>
            </div>
          </td>
          <td style="padding: 10px 12px;">${reasonBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="font-family: var(--font-mono, monospace); font-size: 10.5px; color: #e2e8f0;">${escapeHtml(b.archive_file || b.id)}</div>
            <div style="font-size: 10px; color: var(--muted); margin-top: 2px;">
              ${sizeStr} • ${mountsCount} volume${mountsCount === 1 ? '' : 's'}
            </div>
          </td>
          <td style="padding: 10px 12px; color: var(--muted); font-size: 11px;">
            ${createdDate}
          </td>
          <td style="padding: 10px 12px; text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-rect btn-download-app-backup" data-backup-id="${escapeHtml(b.id)}" data-file="${escapeHtml(b.archive_file || 'app_backup.tar.gz')}" title="Download Archive (.tar.gz)">
                ⬇️ Download
              </button>
              <button class="btn-rect btn-restore-app-backup" data-backup-id="${escapeHtml(b.id)}" data-app-name="${escapeHtml(b.container_name || b.id)}" title="Restore Configuration & Data">
                🔄 Restore
              </button>
              <button class="btn-rect danger btn-delete-app-backup" data-backup-id="${escapeHtml(b.id)}" data-file="${escapeHtml(b.archive_file || b.id)}" title="Delete Backup Archive">
                🗑️
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    mount.innerHTML = `
      <div style="overflow-x: auto; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 10px; font-weight: 800; color: var(--muted); text-transform: uppercase;">
              <th style="padding: 8px 12px;">Application</th>
              <th style="padding: 8px 12px;">Trigger</th>
              <th style="padding: 8px 12px;">Archive File & Size</th>
              <th style="padding: 8px 12px;">Created</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    `;

    // Download action
    mount.querySelectorAll('.btn-download-app-backup').forEach(btn => {
      btn.addEventListener('click', async () => {
        const backupId = btn.dataset.backupId;
        const filename = btn.dataset.file;
        try {
          btn.disabled = true;
          showToast(`Downloading backup "${filename}"...`, 'info');
          await api.downloadBlob(`/api/backup/apps/${encodeURIComponent(backupId)}/download`, filename);
        } catch (err) {
          showToast(`Download failed: ${err.message}`, 'error');
        } finally {
          btn.disabled = false;
        }
      });
    });

    // Restore action
    mount.querySelectorAll('.btn-restore-app-backup').forEach(btn => {
      btn.addEventListener('click', () => {
        const backupId = btn.dataset.backupId;
        const appName = btn.dataset.appName;
        showConfirmToast(
          `Restore App Data for "${appName}"?`,
          `This will extract configurations and mount files back into the original host directories. Existing paths will be preserved in a <code>.pre_restore</code> backup.`,
          async () => {
            try {
              showToast(`Restoring ${appName}...`, 'info');
              const res = await api.post(`/api/backup/apps/${encodeURIComponent(backupId)}/restore`);
              showToast(`App "${appName}" successfully restored (${res.extracted_count || 'all'} paths restored)!`, 'success');
              fetchAndRenderAppBackups(mount, document.getElementById('app-backups-filter-app')?.value || '');
            } catch (err) {
              showToast(`Restore failed: ${err.message}`, 'error');
            }
          },
          null,
          { okText: '🔄 Restore App Data', cancelText: 'Cancel' }
        );
      });
    });

    // Delete action
    mount.querySelectorAll('.btn-delete-app-backup').forEach(btn => {
      btn.addEventListener('click', () => {
        const backupId = btn.dataset.backupId;
        const filename = btn.dataset.file;
        showConfirmToast(
          `Delete Backup Archive?`,
          `Are you sure you want to permanently delete backup archive <strong>${escapeHtml(filename)}</strong>? This cannot be undone.`,
          async () => {
            try {
              await api.delete(`/api/backup/apps/${encodeURIComponent(backupId)}`);
              showToast(`Backup "${filename}" deleted.`, 'success');
              fetchAndRenderAppBackups(mount, document.getElementById('app-backups-filter-app')?.value || '');
            } catch (err) {
              showToast(`Delete failed: ${err.message}`, 'error');
            }
          },
          null,
          { okText: '🗑 Delete Archive', cancelText: 'Cancel' }
        );
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: 12px;">Failed to load application backups: ${escapeHtml(err.message)}</div>`;
  }
}

export const initManagementWindow = initManagement;



