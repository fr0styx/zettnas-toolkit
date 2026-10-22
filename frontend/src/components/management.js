import { syncWidgetSettingsUI } from './widgets.js';
import { syncDesktopThemeUI, openDrawer, restoreHardwareTabsToManagement } from './settings.js';
import { openContainerInspector, openContainerDeleteModal } from './container-modal.js';
import { openStackModal, openStackPickerModal } from './stack-modal.js';
import { ZettEventBus } from '../event-bus.js';
import {
  clearSelectedContainers,
  createContainerRow,
  getSelectedContainerIds,
  initSynchronizedTableScrollbars,
  isContainerSelected,
  runBulkContainerAction,
  selectAllContainers,
  toggleContainerSelected,
  updateContainerRow,
} from './docker-table.js';
import { fitMiniPreviewScale, syncMiniPreviewTelemetry } from './mini-preview.js';
import { fetchAndRenderChassisTwin, renderStorageTopologyTree, fetchAndRenderStorageTopology, fetchAndRenderNetworkShares, fetchAndRenderRemoteStorage, openNewCloudRemoteModal, openCreateStoragePoolModal, openCreateNetworkShareModal, openSnapshotsModal, triggerLocateDisk, getThermalLevel } from './chassis-visualizer.js';
/**
 * ZettNAS Toolkit - System Management Window Controller
 * Manages the dedicated System Management desktop window, hub app grid,
 * category navigation, and card views (Wallpaper, Metrics, Events, Security).
 */
import { fetchAndRenderMetrics } from './metrics-chart.js';
import { bringToFront, DockManager, makeDraggable, saveWindowBounds, saveOpenWindowsState, showDockToast } from './dock.js';
import { state } from '../state.js';
import { api, auth } from '../api.js';
import { initNetworkPortsInspector, fetchListeningPorts } from './network-manager.js';
import { showToast, showConfirmToast, showPromptToast, showBottomSheet } from '../toast.js';
import { trapFocus, escapeHtml, copyTextToClipboard, reconcileKeyedTable } from '../utils.js';
import { t, getLanguage } from '../i18n.js';
import { collectClientEnvironment, getClientLogs } from '../client-logger.js';
import { openFilePreviewModal } from './file-preview-modal.js';

import { formatBytes as formatSize, formatDateTime, formatNumber, formatTime } from '../format.js';
if (typeof window !== 'undefined') {
  window.openFilePreviewModal = openFilePreviewModal;
}

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
  'mgmt-pane-docker-catalog': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker-catalog' },
  'catalog': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker-catalog' },
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
  'mgmt-pane-hardware-copy': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-hardware-copy' },
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
  'mgmt-sec-calendar': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-calendar' },
  'mgmt-pane-calendar': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-calendar' },
  'calendar': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-calendar' },
  'mgmt-sec-language': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },
  'mgmt-pane-language': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },
  'timezone': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },
  'clock': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },
  'time': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },
  'language': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },
  'region': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-language' },

  // --- Pillar 8: AI Knowledge & Visual Search (ZettAI) ---
  'ai': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'chatbot': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'chat': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'rag': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-rag' },
  'zettai': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'ai-chat': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'mgmt-sec-ai': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'mgmt-sec-ai-rag': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-rag' },
  'mgmt-pane-ai-rag': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-rag' },
  'mgmt-pane-ai-chat': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'mgmt-pane-ai-visual': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-visual' },
  'mgmt-pane-ai-index': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-index' },
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

      case 'stack': {
        const stackA = (a.stack || (a.managed_by === 'unraid' ? 'Unraid' : 'Standalone')).toLowerCase();
        const stackB = (b.stack || (b.managed_by === 'unraid' ? 'Unraid' : 'Standalone')).toLowerCase();
        const cmp = stackA.localeCompare(stackB);
        if (cmp !== 0) return dir === 'desc' ? -cmp : cmp;
        const nameA = (a.name || a.id || '').toLowerCase();
        const nameB = (b.name || b.id || '').toLowerCase();
        return nameA.localeCompare(nameB);
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

export function updateDockerBulkBar() {
  const bar = document.getElementById('docker-bulk-bar');
  const countEl = document.getElementById('docker-bulk-count');
  const selectAll = document.getElementById('docker-select-all');
  const selectedIds = getSelectedContainerIds();
  const count = selectedIds.length;

  if (bar) {
    if (count > 0) {
      bar.style.display = 'flex';
      if (countEl) countEl.textContent = count;
    } else {
      bar.style.display = 'none';
    }
  }

  if (selectAll) {
    const totalVisible = _dockerContainersList.length;
    if (count === 0) {
      selectAll.checked = false;
      selectAll.indeterminate = false;
    } else if (count >= totalVisible && totalVisible > 0) {
      selectAll.checked = true;
      selectAll.indeterminate = false;
    } else {
      selectAll.checked = false;
      selectAll.indeterminate = true;
    }
  }
}

export async function executeBulkContainerAction(action) {
  return runBulkContainerAction(action, {
    rerender: renderDockerContainersTable,
    refresh: () => fetchAndRenderDockerContainers(),
    updateBar: updateDockerBulkBar,
  });
}

export function _resetDockerStateForTesting() {
  stopDockerAutoRefresh();
  clearSelectedContainers();
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
      const tabContainers = document.getElementById('docker-inner-tab-containers');
      const tabCatalog = document.getElementById('docker-inner-tab-catalog');
      if (tabContainers) {
        tabContainers.classList.add('active');
        tabContainers.setAttribute('aria-selected', 'true');
      }
      if (tabCatalog) {
        tabCatalog.classList.remove('active');
        tabCatalog.setAttribute('aria-selected', 'false');
      }
    };

    const showCatalogView = () => {
      btnCatalog.classList.add('active');
      btnContainers.style.display = 'inline-flex';
      btnContainers.textContent = '← Back to Containers';
      btnContainers.classList.remove('active');
      if (wrapContainers) wrapContainers.style.display = 'none';
      if (wrapCatalog) wrapCatalog.style.display = 'block';
      const tabContainers = document.getElementById('docker-inner-tab-containers');
      const tabCatalog = document.getElementById('docker-inner-tab-catalog');
      if (tabCatalog) {
        tabCatalog.classList.add('active');
        tabCatalog.setAttribute('aria-selected', 'true');
      }
      if (tabContainers) {
        tabContainers.classList.remove('active');
        tabContainers.setAttribute('aria-selected', 'false');
      }
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

    const tabContainers = document.getElementById('docker-inner-tab-containers');
    const tabCatalog = document.getElementById('docker-inner-tab-catalog');
    if (tabContainers && !tabContainers.dataset.bound) {
      tabContainers.dataset.bound = '1';
      tabContainers.addEventListener('click', showContainersView);
    }
    if (tabCatalog && !tabCatalog.dataset.bound) {
      tabCatalog.dataset.bound = '1';
      tabCatalog.addEventListener('click', showCatalogView);
    }
  }

  // Catalog category filter pills
  const catFilterParent = document.getElementById('mgmt-pane-docker-catalog') || containerPane;
  const catFilterBtns = catFilterParent ? catFilterParent.querySelectorAll('.catalog-filter-btn') : [];
  catFilterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      catFilterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _catalogCat = btn.dataset.cat || 'all';
      renderAppCatalogGrid();
    });
  });

  const btnRefreshCatalog = document.getElementById('btn-refresh-catalog');
  if (btnRefreshCatalog && !btnRefreshCatalog.dataset.bound) {
    btnRefreshCatalog.dataset.bound = '1';
    btnRefreshCatalog.addEventListener('click', () => {
      fetchAndRenderAppCatalog();
    });
  }

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
          showToast(t('toast.container_updates_available', 'Update check complete: {count} container update(s) available!', { count }), 'warn');
        } else {
          showToast(t('toast.all_containers_are_up_to_date', 'All containers are up to date!'), 'success');
        }
        await fetchAndRenderDockerContainers(false);
      } catch (err) {
        showToast(t('toast.update_check_failed', 'Update check failed: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.starting_batch_update_for_containers', 'Starting batch update for {count} containers...', { count: count }), 'info');
          try {
            const res = await api.post('/api/docker/updates/apply-all');
            const updatedCount = res.total_updated || (res.updated || []).length;
            showToast(t('toast.batch_update_complete_updated_failed', 'Batch update complete: {updatedCount} updated, {failed} failed.', { updatedCount: updatedCount, failed: (res.failed || []).length }), updatedCount > 0 ? 'success' : 'warn');
            await refreshDockerUpdatesStatus();
            await fetchAndRenderDockerContainers();
          } catch (err) {
            showToast(t('toast.batch_update_failed', 'Batch update failed: {error}', { error: err.message }), 'error');
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
          allowHtml: true,
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
          showToast(t('toast.no_active_compose_stacks_found', 'No active Compose stacks found.'), 'info');
          return;
        }
        openStackPickerModal(stacks);
      } catch (err) {
        showToast(t('toast.failed_loading_stacks', 'Failed loading stacks: {error}', { error: err.message }), 'error');
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

    th.addEventListener('click', (e) => {
      if (e.target.id === 'docker-select-all' || e.target.closest('#docker-select-all')) return;
      handleSort();
    });
    th.addEventListener('keydown', (e) => {
      if (e.target.id === 'docker-select-all' || e.target.closest('#docker-select-all')) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleSort();
      }
    });
  });

  // Select All Containers Checkbox
  const selectAll = document.getElementById('docker-select-all');
  if (selectAll && !selectAll._bound) {
    selectAll._bound = true;
    selectAll.addEventListener('change', (e) => {
      e.stopPropagation();
      const tbody = document.getElementById('docker-containers-tbody');
      if (!tbody) return;
      if (selectAll.checked) {
        const visibleIds = _dockerContainersList.map((c) => c.id).filter(Boolean);
        selectAllContainers(visibleIds);
      } else {
        clearSelectedContainers();
      }
      tbody.querySelectorAll('.docker-row-select').forEach((chk) => {
        const cid = chk.dataset.id;
        const isChecked = isContainerSelected(cid);
        chk.checked = isChecked;
        const tr = chk.closest('tr');
        if (tr) {
          if (isChecked) tr.classList.add('docker-row-selected');
          else tr.classList.remove('docker-row-selected');
        }
      });
      updateDockerBulkBar();
    });
  }

  // Floating Bulk Action Bar Buttons
  const bulkBar = document.getElementById('docker-bulk-bar');
  if (bulkBar && !bulkBar._bound) {
    bulkBar._bound = true;
    bulkBar.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-bulk-action');
      if (!btn) return;
      e.stopPropagation();
      const action = btn.dataset.bulk;
      if (action) {
        executeBulkContainerAction(action);
      }
    });
  }

  ZettEventBus.on('docker:containers-updated', () => {
    fetchAndRenderDockerContainers();
  });

  ZettEventBus.on('docker:containers:refresh', () => {
    fetchAndRenderDockerContainers();
    refreshDockerUpdatesStatus();
  });

  ZettEventBus.on('stats:updated', (stats) => {
    if (!stats || !Array.isArray(stats.docker)) return;
    const mgmtWin = document.getElementById('management-window');
    if (!mgmtWin) return;
    if (
      mgmtWin.style.display === 'none' ||
      mgmtWin.classList.contains('minimized') ||
      mgmtWin.classList.contains('window-minimized')
    ) {
      return;
    }
    const dockerSec = document.getElementById('mgmt-sec-docker');
    if (!dockerSec || dockerSec.style.display === 'none') return;
    _dockerContainersList = stats.docker;
    renderDockerContainersTable();
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
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:36px 20px;">
      <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px;">
        <div style="font-size:32px; opacity:0.8;">🐳</div>
        <div style="font-size:13.5px; font-weight:600; color:var(--text, #fff);">${t('mgmt.docker_none_title', 'No Docker Containers Deployed')}</div>
        <div style="font-size:12px; color:var(--muted, #94a3b8); max-width:420px; line-height:1.5;">${t('mgmt.docker_none', 'No Docker containers detected or socket not connected.')}</div>
        <button id="btn-empty-deploy-app" class="btn-pill-toggle" style="margin-top:6px; background:var(--brand, #0ea5e9); color:#fff; border-color:var(--brand, #0ea5e9); font-weight:600; padding:6px 16px; cursor:pointer;">
          🚀 ${t('mgmt.docker_open_catalog', 'Browse App Catalog')}
        </button>
      </div>
    </td></tr>`;
    const btnEmptyCatalog = tbody.querySelector('#btn-empty-deploy-app');
    if (btnEmptyCatalog) {
      btnEmptyCatalog.addEventListener('click', () => {
        const catBtn = document.getElementById('btn-view-docker-catalog') || document.getElementById('docker-inner-tab-catalog');
        if (catBtn) catBtn.click();
      });
    }
    updateDockerBulkBar();
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
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:20px;">${t('mgmt.docker_no_matching', 'No containers match your search or filter.')}</td></tr>`;
    const topScroll = document.getElementById('docker-table-top-scroll');
    const stickyScroll = document.getElementById('docker-table-sticky-scroll');
    if (topScroll) topScroll.style.display = 'none';
    if (stickyScroll) stickyScroll.style.display = 'none';
    updateDockerBulkBar();
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
    (c) => createContainerRow(c, currentHost, _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id]),
    (tr, c) => updateContainerRow(tr, c, currentHost, _dockerUpdatesCache?.containers?.[c.name] || _dockerUpdatesCache?.containers?.[c.id])
  );
  updateDockerBulkBar();

  const tableWrap = document.querySelector('.docker-table-container');
  const topScroll = document.getElementById('docker-table-top-scroll');
  const stickyScroll = document.getElementById('docker-table-sticky-scroll');
  if (tableWrap) {
    initSynchronizedTableScrollbars(tableWrap, topScroll, stickyScroll);
  }
}

function bindDockerTableEvents(tbody) {
  if (tbody._dockerTableEventsBound) return;
  tbody._dockerTableEventsBound = true;

  tbody.addEventListener('change', (e) => {
    if (e.target.classList.contains('docker-row-select')) {
      const cid = e.target.dataset.id;
      toggleContainerSelected(cid, e.target.checked);
      const tr = e.target.closest('tr');
      if (tr) {
        if (e.target.checked) tr.classList.add('docker-row-selected');
        else tr.classList.remove('docker-row-selected');
      }
      updateDockerBulkBar();
    }
  });

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
            showToast(t('toast.updating_to_latest_image', 'Updating "{cname}" to latest image...', { cname: cname }), 'info');
            try {
              await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/update-image`);
              showToast(t('toast.container_updated_and_restarted_successfully', 'Container "{cname}" updated and restarted successfully!', { cname: cname }), 'success');
              await refreshDockerUpdatesStatus();
              await fetchAndRenderDockerContainers();
            } catch (err) {
              showToast(t('toast.update_failed', 'Update failed: {error}', { error: err.message }), 'error');
              actBtn.disabled = false;
              actBtn.innerHTML = originalContent;
            }
          },
          null,
          {
            okText: '⬆️ Update Now',
            cancelText: 'Cancel',
            isUpdate: true,
            allowHtml: true,
          }
        );
        return;
      }

      if (act === 'backup') {
        actBtn.disabled = true;
        const originalContent = actBtn.innerHTML;
        actBtn.innerHTML = '⏳';
        showToast(t('toast.creating_backup_for_2', 'Creating backup for {cname}...', { cname: cname }), 'info');
        try {
          const res = await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/backup`);
          const archiveName = res?.backup?.archive_file || 'archive.tar.gz';
          const sizeStr = res?.backup?.archive_size_formatted || '';
          showToast(t('toast.app_backed_up', 'App "{name}" backed up ({archive}).', { name: cname, archive: sizeStr ? `${archiveName}, ${sizeStr}` : archiveName }), 'success');
        } catch (err) {
          showToast(t('toast.backup_failed', 'Backup failed: {error}', { error: err.message }), 'error');
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
      showToast(t('toast.request_sent_for', '{act} request sent for {cname}...', { act: act.toUpperCase(), cname: cname }), 'info');

      try {
        await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: act });
        showToast(t('toast.container_successfully_ed', 'Container "{cname}" successfully {act}ed.', { cname: cname, act: act }), 'success');
        await fetchAndRenderDockerContainers();
      } catch (err) {
        showToast(t('toast.failed_to_container', 'Failed to {act} container: {error}', { act: act, error: err.message }), 'error');
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

let _dockerLastSseAt = 0;
let _dockerSseBound = false;
const DOCKER_WATCHDOG_MS = 15000;
const DOCKER_SSE_STALE_MS = 10000;

function _dockerSectionVisible() {
  if (typeof document === 'undefined' || document.hidden) return false;
  const mgmtWin = document.getElementById('management-window');
  if (mgmtWin && (mgmtWin.style.display === 'none' || mgmtWin.classList.contains('minimized') || mgmtWin.classList.contains('window-minimized'))) {
    return false;
  }
  const dockerSec = document.getElementById('mgmt-sec-docker');
  if (!dockerSec || dockerSec.style.display === 'none') return false;
  const style = typeof window !== 'undefined' && window.getComputedStyle ? window.getComputedStyle(dockerSec) : null;
  return !(style && style.display === 'none');
}

// Mission Control's container table follows the live stats stream, like the Containers
// window; the timer only fetches when the stream has gone quiet (FE-12).
export function startDockerAutoRefresh() {
  if (!_dockerSseBound) {
    _dockerSseBound = true;
    ZettEventBus.on('stats:updated', (stats) => {
      if (!stats || !Array.isArray(stats.docker)) return;
      _dockerLastSseAt = Date.now();
      if (!_dockerAutoRefreshTimer || !_dockerSectionVisible()) return;
      _dockerContainersList = stats.docker;
      renderDockerContainersTable();
    });
  }
  if (_dockerAutoRefreshTimer) return;
  _dockerAutoRefreshTimer = setInterval(async () => {
    if (!_dockerSectionVisible()) return;
    if (_isDockerAutoRefreshing) return;
    _isDockerAutoRefreshing = true;
    try {
      _dockerAutoRefreshCount++;
      if (_dockerAutoRefreshCount % 4 === 0) {
        refreshDockerUpdatesStatus().catch(() => {});
      }
      if (Date.now() - _dockerLastSseAt > DOCKER_SSE_STALE_MS) {
        await fetchAndRenderDockerContainers(true);
      }
    } catch (e) {
      console.warn('Docker background auto-refresh poll error:', e);
    } finally {
      _isDockerAutoRefreshing = false;
    }
  }, DOCKER_WATCHDOG_MS);
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
      if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
      if (cwTbody) cwTbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
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
      ? `<img src="${escapeHtml(app.logo)}" alt="${escapeHtml(app.name)}" style="width:24px; height:24px; object-fit:contain; border-radius:4px; vertical-align:middle; flex-shrink:0;" data-img-fallback="hide-show-next:inline" /><span style="font-size:20px; line-height:1; display:none;">${icon}</span>`
      : `<span style="font-size:20px; line-height:1;">${icon}</span>`;

    const sourceBadge = app.source_name && app.source_name !== 'Built-in'
      ? `<span class="ci-badge" style="font-size:11px; background:rgba(14,165,233,0.15); color:#38bdf8; border:1px solid rgba(14,165,233,0.3); padding:1px 5px; border-radius:3px;">${escapeHtml(app.source_name)}</span>`
      : `<span class="ci-badge" style="font-size:11px; background:rgba(37,194,160,0.15); color:var(--accent, #25c2a0); border:1px solid rgba(37,194,160,0.3); padding:1px 5px; border-radius:3px;">Built-in</span>`;

    const typeBadge = app.type === 'stack'
      ? `<span class="ci-badge" style="font-size:11px; background:rgba(168,85,247,0.15); color:#c084fc; border:1px solid rgba(168,85,247,0.3); padding:1px 5px; border-radius:3px;">Stack</span>`
      : '';

    let securityBadge = '';
    if (app.security_rating === 'verified') {
      securityBadge = `<span class="ci-badge" title="Verified Safe Sandbox" style="font-size:11px; background:rgba(34,197,94,0.15); color:#4ade80; border:1px solid rgba(34,197,94,0.3); padding:1px 5px; border-radius:3px;">🛡️ Safe</span>`;
    } else if (app.security_rating === 'review_required') {
      securityBadge = `<span class="ci-badge" title="${escapeHtml((app.security_flags || []).join('; '))}" style="font-size:11px; background:rgba(234,179,8,0.15); color:#facc15; border:1px solid rgba(234,179,8,0.3); padding:1px 5px; border-radius:3px;">⚠️ Review</span>`;
    } else if (app.security_rating === 'elevated') {
      securityBadge = `<span class="ci-badge" title="${escapeHtml((app.security_flags || []).join('; '))}" style="font-size:11px; background:rgba(239,68,68,0.15); color:#f87171; border:1px solid rgba(239,68,68,0.3); padding:1px 5px; border-radius:3px;">🚨 Elevated</span>`;
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
                <code style="font-size:11px; color:var(--muted); font-family:var(--font-mono, monospace); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:block;">${escapeHtml(imageDisplay)}</code>
              </div>
            </div>
            <div style="display:flex; gap:4px; align-items:center; flex-shrink:0;">
              ${typeBadge}
              ${sourceBadge}
              ${securityBadge}
              <span class="ci-badge" style="font-size:11px; text-transform:uppercase; background:rgba(255,255,255,0.06); color:#cbd5e1; padding:2px 6px; border-radius:4px;">${escapeHtml(app.category)}</span>
            </div>
          </div>
          <p style="font-size:11px; color:#94a3b8; line-height:1.4; margin:0 0 6px 0; min-height:32px;">${escapeHtml(app.description)}</p>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid rgba(255,255,255,0.06); padding-top:8px;">
          <span style="font-size:11px; font-family:var(--font-mono, monospace); color:var(--accent-cyan, #00f0ff); background:rgba(0,240,255,0.08); padding:2px 6px; border-radius:4px;">Port :${app.default_port}</span>
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
                <span id="adm-existing-status-badge" style="font-size:11px; padding:2px 7px; border-radius:4px; background:rgba(255,255,255,0.08); font-family:var(--font-mono, monospace); font-weight:700;">Running</span>
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
                <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">CONTAINER NAME</label>
                <input type="text" id="adm-name-input" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px; font-family:var(--font-mono, monospace);">
              </div>
              <div>
                <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">HOST PORT MAPPING</label>
                <input type="number" id="adm-port-input" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px; font-family:var(--font-mono, monospace);">
              </div>
            </div>
            <div>
              <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">STORAGE ROOT DIRECTORY</label>
              <input type="text" id="adm-storage-input" value="/mnt/user/appdata" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11.5px; padding:6px 8px;">
            </div>
            <div>
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:11px; font-weight:700; color:var(--muted);">DOCKER COMPOSE DEFINITION</span>
                <div style="display:flex; gap:6px;">
                  <button class="btn-pill-toggle" id="adm-copy-btn">📋 Copy YAML</button>
                  <button class="btn-pill-toggle" id="adm-download-btn">⬇️ Download</button>
                </div>
              </div>
              <pre id="adm-compose-pre" style="margin:0; background:#080c14; border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:10px; max-height:200px; overflow:auto; font-family:var(--font-mono, monospace); font-size:11px; color:#e2e8f0; line-height:1.45;"></pre>
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
              <div style="font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px; text-transform:uppercase; letter-spacing:0.5px;">Deployment Console Log</div>
              <div id="adm-deploy-logs" style="background:#05080f; border:1px solid rgba(255,255,255,0.1); border-radius:6px; height:160px; overflow-y:auto; padding:10px; font-family:var(--font-mono, monospace); font-size:11px; line-height:1.5; color:#cbd5e1;">
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
        showToast(t('toast.deploying_in_background_click_dock_icon', 'Deploying {activeAppId} in background. Click Dock icon to restore.', { activeAppId: modal._activeAppId || 'app' }), 'info');
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
          showToast(t('toast.deploying_in_background_reopen_from_dock', `Deploying in background. Reopen from Dock anytime.`), 'info');
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
        showToast(t('toast.docker_compose_yaml_copied_to_clipboard', 'Docker Compose YAML copied to clipboard!'), 'success');
      } else {
        showToast(t('toast.failed_to_copy_to_clipboard', 'Failed to copy to clipboard'), 'warn');
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
    showToast(t('toast.downloaded_compose_yml_2', 'Downloaded {appId}-compose.yml', { appId: appId }), 'info');
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

      showToast(t('toast.stack_deployed_and_running', '{appId} stack deployed and running!', { appId: appId }), 'success');
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

      showToast(t('toast.deployment_failed', 'Deployment failed: {message}', { message: data.message }), 'error');
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
          showToast(t('toast.container_already_exists_please_rename_or', 'Container \'{cName}\' already exists. Please rename or select Replace.', { cName: cName }), 'warn');
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
          showToast(t('toast.port_is_already_in_use_please', 'Port {p} is already in use{inUse}. Please change the port.', { p: p, inUse: inUse }), 'warn');
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
                <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Images</div>
                <div id="dpm-df-images" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Containers</div>
                <div id="dpm-df-containers" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Volumes</div>
                <div id="dpm-df-volumes" style="font-size:12.5px; font-weight:700; color:#fff; margin-top:2px;">Loading...</div>
              </div>
              <div style="background:rgba(0,240,255,0.06); border:1px solid rgba(0,240,255,0.2); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:11px; color:var(--accent-cyan, #00f0ff); text-transform:uppercase; font-weight:700;">Reclaimable</div>
                <div id="dpm-df-reclaimable" style="font-size:12.5px; font-weight:800; color:var(--ok2, #25c2a0); margin-top:2px;">--</div>
              </div>
            </div>

            <!-- Prune Options -->
            <div style="background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:12px; display:flex; flex-direction:column; gap:10px;">
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-containers" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Stopped Containers</strong>
                  <div style="font-size:11px; color:var(--muted);">Deletes all exited, stopped, and dead containers.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-images" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Dangling Images</strong>
                  <div style="font-size:11px; color:var(--muted);">Removes untagged &lt;none&gt; build layers and intermediate images.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-all-images" style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune ALL Unused Images</strong>
                  <div style="font-size:11px; color:var(--muted);">Removes all images not currently referenced by at least one running container.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-volumes" style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Unused Local Volumes</strong>
                  <div style="font-size:11px; color:var(--warn, #f5a623);">Caution: Removes local anonymous volumes not mounted by containers.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:#e2e8f0; cursor:pointer;">
                <input type="checkbox" id="dpm-opt-buildcache" checked style="margin-top:2px; cursor:pointer;">
                <div>
                  <strong>Prune Build Cache & Unused Networks</strong>
                  <div style="font-size:11px; color:var(--muted);">Frees temporary Docker build cache layers and disconnected bridge networks.</div>
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
      showToast(t('toast.prune_failed', 'Prune failed: {error}', { error: err.message }), 'error');
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
                  <span class="ci-badge" style="font-size:11px; background:rgba(37,194,160,0.2); color:var(--accent);">790+ Apps</span>
                </div>
                <div style="font-size:11px; color:#94a3b8; margin-top:2px;">
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
                  <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:3px;">SOURCE NAME</label>
                  <input type="text" id="asm-input-name" placeholder="e.g. Community Apps" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:5px 8px;">
                </div>
                <div>
                  <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:3px;">TEMPLATE URL (JSON)</label>
                  <input type="url" id="asm-input-url" placeholder="https://example.com/templates.json" class="tz-text-input" style="width:100%; box-sizing:border-box; font-size:11px; padding:5px 8px;">
                </div>
                <div>
                  <button class="btn-pill-toggle" id="asm-btn-add-custom" style="background:linear-gradient(135deg, var(--brand, #0ea5e9), var(--ok2, #25c2a0)); color:#fff; border:none; padding:5px 14px; font-weight:700; font-size:11px; height:28px; white-space:nowrap; cursor:pointer;">
                    + Add & Sync
                  </button>
                </div>
              </div>
              <div id="asm-form-status" style="font-size:11px; display:none; padding:4px 6px; border-radius:4px;"></div>
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
          showToast(t('toast.lissy93_portainer_templates_added_790_apps', 'Lissy93 Portainer templates added (790+ apps)!'), 'success');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(t('toast.failed_to_add_lissy93_templates', 'Failed to add Lissy93 templates: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.added_template_source', 'Added template source "{name}"!', { name: name }), 'success');
          setTimeout(() => { statusEl.style.display = 'none'; }, 3000);
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          statusEl.style.background = 'rgba(239,68,68,0.15)';
          statusEl.style.color = '#fca5a5';
          statusEl.textContent = `Error: ${err.message}`;
          showToast(t('toast.failed_to_add_source', 'Failed to add source: {error}', { error: err.message }), 'error');
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
        ? `<span class="ci-badge" style="font-size:11px; background:rgba(37,194,160,0.15); color:var(--accent);">✓ Synced (${formatRelativeTime(src.last_synced)})</span>`
        : (src.status === 'error'
          ? `<span class="ci-badge" style="font-size:11px; background:rgba(239,68,68,0.15); color:#fca5a5;" title="${escapeHtml(src.error || 'Sync failed')}">⚠️ Error</span>`
          : `<span class="ci-badge" style="font-size:11px; background:rgba(14,165,233,0.15); color:#38bdf8;">🔄 ${escapeHtml(src.status || 'pending')}</span>`);

      const toggleBtnClass = isEnabled ? 'btn-pill-toggle active' : 'btn-pill-toggle';
      const toggleText = isEnabled ? 'Enabled' : 'Disabled';

      return `
        <div class="asm-source-card" data-sourceid="${escapeHtml(src.id)}" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px 12px; display:flex; justify-content:space-between; align-items:center; gap:10px;">
          <div style="overflow:hidden; flex:1;">
            <div style="display:flex; align-items:center; gap:8px;">
              <strong style="font-size:12px; color:#fff;">${escapeHtml(src.name)}</strong>
              <span class="ci-badge" style="font-size:11px; background:rgba(255,255,255,0.06); color:#cbd5e1;">${src.item_count || 0} apps</span>
              ${statusBadge}
            </div>
            <div style="font-size:11px; color:var(--muted); font-family:var(--font-mono, monospace); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px;">
              ${escapeHtml(src.url)}
            </div>
            ${src.error ? `<div style="font-size:11px; color:#fca5a5; margin-top:3px;">${escapeHtml(src.error)}</div>` : ''}
          </div>
          <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
            <button class="${toggleBtnClass} asm-btn-toggle" data-sourceid="${escapeHtml(src.id)}" data-enabled="${isEnabled ? 'true' : 'false'}" style="font-size:11px; padding:3px 8px; cursor:pointer;">
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
          showToast(!curEnabled ? t('toast.source_enabled', 'Source enabled.') : t('toast.source_disabled', 'Source disabled.'), 'info');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(t('toast.failed_to_toggle_source', 'Failed to toggle source: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.source_synced', 'Source synced ({count} apps).', { count: res.source ? res.source.item_count : 0 }), 'success');
          await refreshSourcesUI();
          fetchAndRenderAppCatalog();
        } catch (err) {
          showToast(t('toast.failed_to_sync_source', 'Failed to sync source: {error}', { error: err.message }), 'error');
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
              showToast(t('toast.source_deleted_successfully', 'Source deleted successfully.'), 'info');
              await refreshSourcesUI();
              fetchAndRenderAppCatalog();
            } catch (err) {
              showToast(t('toast.failed_to_delete_source', 'Failed to delete source: {error}', { error: err.message }), 'error');
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
        showToast(t('toast.please_provide_a_url_or_paste', 'Please provide a URL or paste manifest YAML/JSON.'), 'warning');
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
        showToast(t('toast.failed_to_inspect_manifest', 'Failed to inspect manifest: {error}', { error: err.message }), 'error');
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
      <span class="ci-badge" style="font-size:11px; background:${badgeBg}; color:${badgeColor}; border:1px solid ${badgeBorder}; padding:2px 8px; border-radius:4px;">${badgeText}</span>
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
  if (linevEl) linevEl.textContent = ups.line_volts != null ? `${ups.line_volts} V` : (ups.output_volts != null ? `${ups.output_volts} V` : 'N/A');
  if (protocolEl) {
    let protoLabel = ups.protocol || 'Auto / NIS';
    if (ups.is_usb && !protoLabel.toLowerCase().includes('usb')) {
      protoLabel = `${protoLabel} (USB)`;
    }
    protocolEl.textContent = protoLabel;
    const currentUpsMode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
    updateUpsConnCardState(currentUpsMode, ups);
  }
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

  if (twinLinev) twinLinev.textContent = ups.line_volts != null ? `${ups.line_volts} V` : (ups.output_volts != null ? `${ups.output_volts} V` : (ups.available ? '120.0 V' : '-- V'));
  if (twinGridStatus) {
    twinGridStatus.textContent = ups.on_battery ? 'AC Mains Disconnected' : (ups.line_freq_hz ? `${ups.line_freq_hz} Hz Nominal` : '120V / 60Hz Nominal');
  }
  if (twinWatts) twinWatts.textContent = ups.power_watts != null ? `${ups.power_watts} W` : (ups.load_pct != null ? `${Math.round(ups.load_pct * ((ups.nominal_power_watts || 900) / 100))} W` : '-- W');
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
      const dateStr = formatDateTime(ev.ts);
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
let isUpsConfigLoaded = false;

export function setUpsConfigLoaded(val = true) {
  isUpsConfigLoaded = Boolean(val);
}
if (typeof window !== 'undefined') window.setUpsConfigLoaded = setUpsConfigLoaded;

export function updateUpsConnCardState(mode, upsData) {
  const connCard = document.getElementById('ups-drawer-conn-card');
  const badge = document.getElementById('ups-conn-disabled-badge');
  const toggleContainer = document.getElementById('ups-toggle-params-container');
  const toggleBtn = document.getElementById('btn-toggle-ups-conn-params');
  if (!connCard) return;

  const currentMode = mode || document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
  const protocolText = (document.getElementById('mgmt-ups-protocol')?.textContent || '').toLowerCase().trim();
  const isUsbProtocol = protocolText.includes('usb') || protocolText.includes('hid');
  const isDirectUsb = (currentMode === 'usb_hid') ||
                      Boolean(upsData?.is_usb) ||
                      (upsData?.cable && String(upsData.cable).toLowerCase().includes('usb')) ||
                      (upsData?.driver && String(upsData.driver).toLowerCase().includes('usb')) ||
                      (currentMode === 'auto' && isUsbProtocol);

  if (isDirectUsb) {
    connCard.classList.add('disabled');
    connCard.setAttribute('aria-disabled', 'true');
    // Hide the connection parameters card when connected via USB or in Direct USB mode
    if (!connCard.dataset.manuallyExpanded) {
      connCard.style.display = 'none';
    } else {
      connCard.style.removeProperty('display');
    }
    if (badge) badge.style.display = 'inline-flex';
    if (toggleContainer) toggleContainer.style.display = 'flex';
    if (toggleBtn) {
      const toggleText = toggleBtn.querySelector('#ups-toggle-params-text');
      if (toggleText) {
        toggleText.textContent = connCard.dataset.manuallyExpanded
          ? t('mgmt.ups_hide_params', 'Hide Connection Parameters')
          : t('mgmt.ups_show_params', 'Show Connection Parameters');
      }
    }
  } else {
    delete connCard.dataset.manuallyExpanded;
    connCard.classList.remove('disabled');
    connCard.removeAttribute('aria-disabled');
    connCard.style.removeProperty('display');
    if (badge) badge.style.display = 'none';
    if (toggleContainer) toggleContainer.style.display = 'none';
  }
  const inputs = connCard.querySelectorAll('input, button');
  inputs.forEach(el => {
    el.disabled = isDirectUsb;
  });
}
if (typeof window !== 'undefined') window.updateUpsConnCardState = updateUpsConnCardState;

export function updateUpsPolicySliders(selectedPolicy) {
  const policy = selectedPolicy || document.querySelector('input[name="ups-policy"]:checked')?.value || 'runtime_left';
  const rtContainer = document.getElementById('ups-slider-runtime-container');
  const battContainer = document.getElementById('ups-slider-battery-container');
  const timerContainer = document.getElementById('ups-slider-timer-container');

  if (rtContainer) rtContainer.style.display = (policy === 'runtime_left') ? 'flex' : 'none';
  if (battContainer) battContainer.style.display = (policy === 'battery_pct') ? 'flex' : 'none';
  if (timerContainer) timerContainer.style.display = (policy === 'timer') ? 'flex' : 'none';

  updateUpsPolicySummary();
}
if (typeof window !== 'undefined') window.updateUpsPolicySliders = updateUpsPolicySliders;

export function updateUpsPolicySummary() {
  const summaryText = document.getElementById('ups-policy-summary-text');
  if (!summaryText) return;

  const policy = document.querySelector('input[name="ups-policy"]:checked')?.value || 'runtime_left';
  const rtVal = document.getElementById('ups-slider-runtime')?.value || 5;
  const battVal = document.getElementById('ups-slider-battery')?.value || 20;
  const timerVal = document.getElementById('ups-slider-timer')?.value || 300;
  const dockerChecked = document.getElementById('ups-chk-docker')?.checked;

  let policyDesc = '';
  if (policy === 'runtime_left') {
    policyDesc = `Estimated Runtime < ${rtVal} min`;
  } else if (policy === 'battery_pct') {
    policyDesc = `Battery Charge < ${battVal}%`;
  } else {
    policyDesc = `Time on Battery > ${timerVal}s`;
  }

  if (dockerChecked) {
    policyDesc += ' · Docker WAL flush';
  }
  summaryText.textContent = `Active: ${policyDesc}`;
}
if (typeof window !== 'undefined') window.updateUpsPolicySummary = updateUpsPolicySummary;

export async function saveUpsConfigFromDrawer() {
  if (isUpsLoadingConfig || !isUpsConfigLoaded) {
    console.debug('[UPS] Skipping auto-save: config loading or not yet loaded.');
    return;
  }
  try {
    const mode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
    const host = document.getElementById('ups-cfg-host')?.value.trim() || '127.0.0.1';
    let defaultPort = 3551;
    if (mode === 'nut_client') defaultPort = 3493;
    const port = parseInt(document.getElementById('ups-cfg-port')?.value, 10) || defaultPort;
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
    if (portEl) portEl.value = cfg.port || (mode === 'nut_client' ? 3493 : 3551);
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

    // Restore policy collapse state
    try {
      const isPolicyCollapsed = localStorage.getItem('zettnas_ups_policy_collapsed') === '1';
      const policyBody = document.getElementById('ups-policy-body');
      const policySummary = document.getElementById('ups-policy-summary');
      const toggleText = document.getElementById('ups-toggle-policy-text');
      if (policyBody && isPolicyCollapsed) {
        policyBody.style.display = 'none';
        if (policySummary) policySummary.style.display = 'flex';
        if (toggleText) toggleText.textContent = t('mgmt.ups_expand_policy', 'Configure Policy');
      }
    } catch (_) {}
    updateUpsPolicySliders(policy);

    isUpsConfigLoaded = true;
  } catch (err) {
    console.debug('Failed to load UPS config:', err);
  } finally {
    isUpsLoadingConfig = false;
  }
}

export function initUpsDrawerControls() {
  const loadPromise = loadUpsConfigToDrawer();
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
      showToast(t('toast.ups_telemetry_parameters_updated', 'UPS telemetry & parameters updated'), 'info');
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
    updateUpsPolicySummary();
    triggerDebouncedSave(200);
  });
  runtimeSlider?.addEventListener('change', () => {
    updateUpsPolicySummary();
    triggerImmediateSave();
  });

  const batterySlider = document.getElementById('ups-slider-battery');
  const batteryVal = document.getElementById('ups-val-battery');
  batterySlider?.addEventListener('input', () => {
    if (batteryVal) batteryVal.textContent = `${batterySlider.value} %`;
    updateUpsPolicySummary();
    triggerDebouncedSave(200);
  });
  batterySlider?.addEventListener('change', () => {
    updateUpsPolicySummary();
    triggerImmediateSave();
  });

  const timerSlider = document.getElementById('ups-slider-timer');
  const timerVal = document.getElementById('ups-val-timer');
  timerSlider?.addEventListener('input', () => {
    if (timerVal) timerVal.textContent = `${timerSlider.value} sec`;
    updateUpsPolicySummary();
    triggerDebouncedSave(200);
  });
  timerSlider?.addEventListener('change', () => {
    updateUpsPolicySummary();
    triggerImmediateSave();
  });

  // Policy radio auto-save + accordion slider collapse
  const policyRadios = document.querySelectorAll('input[name="ups-policy"]');
  policyRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      updateUpsPolicySliders(radio.value);
      triggerImmediateSave();
    });
  });

  // Toggle Safe Shutdown Policy Collapse/Expand
  const btnTogglePolicy = document.getElementById('btn-toggle-ups-policy');
  btnTogglePolicy?.addEventListener('click', () => {
    const policyBody = document.getElementById('ups-policy-body');
    const policySummary = document.getElementById('ups-policy-summary');
    const toggleText = document.getElementById('ups-toggle-policy-text');
    if (!policyBody) return;

    const isCollapsed = policyBody.style.display === 'none';
    if (isCollapsed) {
      policyBody.style.display = 'flex';
      if (policySummary) policySummary.style.display = 'none';
      if (toggleText) toggleText.textContent = t('mgmt.ups_collapse_policy', 'Collapse Policy');
      try { localStorage.setItem('zettnas_ups_policy_collapsed', '0'); } catch (_) {}
    } else {
      policyBody.style.display = 'none';
      if (policySummary) policySummary.style.display = 'flex';
      updateUpsPolicySummary();
      if (toggleText) toggleText.textContent = t('mgmt.ups_expand_policy', 'Configure Policy');
      try { localStorage.setItem('zettnas_ups_policy_collapsed', '1'); } catch (_) {}
    }
  });

  // Checkbox toggles auto-save
  const chkDocker = document.getElementById('ups-chk-docker');
  chkDocker?.addEventListener('change', () => {
    updateUpsPolicySummary();
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

  // Toggle Manual Parameters in Direct USB mode
  const btnToggleParams = document.getElementById('btn-toggle-ups-conn-params');
  btnToggleParams?.addEventListener('click', () => {
    const connCard = document.getElementById('ups-drawer-conn-card');
    if (!connCard) return;
    if (connCard.dataset.manuallyExpanded) {
      delete connCard.dataset.manuallyExpanded;
    } else {
      connCard.dataset.manuallyExpanded = '1';
    }
    const activeMode = document.querySelector('input[name="ups-mode"]:checked')?.value || 'auto';
    updateUpsConnCardState(activeMode);
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
          showToast(t('toast.applied_parameters', 'Applied {displayTitle} parameters!', { displayTitle: displayTitle }), 'info');
        });
      });
    } catch (err) {
      showToast(t('toast.auto_discovery_failed', 'Auto-discovery failed: {error}', { error: err.message }), 'error');
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
        showToast(t('toast.connection_successful', 'Connection successful! ({model})', { model: res.model || res.status || 'ONLINE' }), 'success');
        btnTest.textContent = '✓ Connected';
        setTimeout(() => { btnTest.textContent = '🔌 Test Connection'; }, 3000);
      } else {
        showToast(t('toast.connection_failed', 'Connection failed: {error}', { error: res.error || 'UPS daemon unreachable' }), 'error');
        btnTest.textContent = '✗ Failed';
        setTimeout(() => { btnTest.textContent = '🔌 Test Connection'; }, 3000);
      }
    } catch (err) {
      showToast(t('toast.connection_test_error', 'Connection test error: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.initiating_battery_self_test', 'Initiating battery self-test...'), 'info');
          const res = await api.post('/api/ups/self-test');
          showToast(res.message || 'Battery self-test command sent successfully!', 'success');
          fetchAndRenderUpsTelemetry();
        } catch (err) {
          showToast(t('toast.self_test_failed', 'Self-test failed: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.outage_drill_started_15s', 'Outage drill started (15s)...'), 'warn');
          await api.post('/api/ups/simulate', { duration_sec: 15 });
          fetchAndRenderUpsTelemetry();
        } catch (err) {
          showToast(t('toast.simulation_failed', 'Simulation failed: {error}', { error: err.message }), 'error');
        }
      },
      null,
      { okText: '⚠️ Start Drill', cancelText: 'Cancel', allowHtml: true }
    );
  });
  return loadPromise;
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
      const timeStr = formatDateTime(d);
      const sizeMB = (item.total_bytes / (1024 * 1024)).toFixed(1);
      const durStr = item.duration_sec ? `${item.duration_sec.toFixed(1)}s` : '--';
      const isSuccess = item.status === 'success';
      const statusColor = isSuccess ? 'var(--ok2)' : item.status === 'aborted' ? 'var(--warn)' : 'var(--crit)';
      const checksumBadge = item.checksum_verified
        ? '<span class="checksum-badge">✓ SHA-256</span>'
        : '<span style="color:var(--muted); font-size:11px;">None</span>';
      const destName = item.dest ? item.dest.split('/').filter(Boolean).pop() || item.dest : '/';

      return `
        <tr>
          <td style="font-family:var(--font-mono, monospace); font-size:11px; color:var(--muted);">${timeStr}</td>
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
            <td><span class="mgmt-app-pill" style="font-size:11px;">${escapeHtml(j.schedule || 'manual')}</span></td>
            <td>${j.bandwidth_limit_mbps ? `${j.bandwidth_limit_mbps} MB/s` : 'Unlimited'}</td>
            <td>${j.retention_count || 7} snaps</td>
            <td><span class="mgmt-app-pill ${j.enabled ? 'text-emerald' : 'text-muted'}">${j.enabled ? 'Active' : 'Disabled'}</span></td>
            <td style="text-align:right;">
              <button class="btn-pill-toggle btn-run-repl" data-id="${escapeHtml(j.id)}" style="font-size:11px; padding:2px 8px; margin-right:4px;" title="Execute Replication Now">▶ Run</button>
              <button class="btn-pill-toggle btn-del-repl" data-id="${escapeHtml(j.id)}" style="font-size:11px; padding:2px 8px; color:var(--crit);" title="Delete Pipeline">🗑️</button>
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
            showToast(t('toast.replication_pipeline_dispatched', 'Replication pipeline \'{id}\' dispatched.', { id: id }), 'success');
            setTimeout(fetchAndRenderReplication, 1000);
          } catch (e) {
            showToast(t('toast.replication_failed', 'Replication failed: {message}', { message: e.message }), 'error');
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
                showToast(t('toast.pipeline_deleted', 'Pipeline \'{id}\' deleted.', { id: id }), 'success');
                fetchAndRenderReplication();
              } catch (e) {
                showToast(t('toast.delete_failed_2', 'Delete failed: {message}', { message: e.message }), 'error');
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
            const dt = formatDateTime(h.timestamp);
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
        ? '<span class="mgmt-app-pill" style="color:#3bf58b; background:rgba(59,245,139,0.12); font-size:11px; padding:2px 7px;">Online</span>'
        : '<span class="mgmt-app-pill" style="color:var(--muted); background:rgba(255,255,255,0.06); font-size:11px; padding:2px 7px;">Offline</span>';

      const safeIpId = (p.ip || 'no_ip').replace(/[^a-zA-Z0-9]/g, '_');

      return `
      <tr style="border-bottom:1px solid rgba(255,255,255,0.05); font-size:11.5px;">
        <td style="padding:8px 12px;">
          <div style="font-weight:700; color:#fff;">${escapeHtml(p.name || p.hostname || 'Unnamed')}</div>
          ${p.dns_name ? `<div style="font-size:11px; color:var(--muted);">${escapeHtml(p.dns_name)}</div>` : ''}
        </td>
        <td style="padding:8px 12px; color:var(--text-sub);">${osLabel}</td>
        <td style="padding:8px 12px;"><code style="color:#38bdf8; font-size:11px;">${escapeHtml(p.ip || '--')}</code></td>
        <td style="padding:8px 12px;">${routeBadge}</td>
        <td style="padding:8px 12px;">${statusPill}</td>
        <td style="padding:8px 12px; text-align:right;">
          <div style="display:inline-flex; align-items:center; gap:6px;">
            <span id="latency-${safeIpId}" style="font-size:11px; font-weight:700;"></span>
            <button class="btn-pill-toggle btn-ping-peer" data-peer-ip="${escapeHtml(p.ip || '')}" style="font-size:11px; padding:2px 8px;" ${!p.ip ? 'disabled' : ''}>⚡ Ping</button>
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
              <div class="taildrop-file-item" data-path="${escapeHtml(f.path || '')}" style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,0.05); font-size:11px; cursor:pointer; border-radius:4px; transition:background 0.2s;" data-hover-bg title="Click to view folder in Files">
                <span style="font-weight:600; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:60%;" title="${escapeHtml(f.name)}">📄 ${escapeHtml(f.name)}</span>
                <span style="color:var(--muted); font-size:11px;">${escapeHtml(f.size_formatted)} · ${escapeHtml(f.modified_at)}</span>
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
                  showToast(t('toast.authorization_link_copied_to_clipboard', 'Authorization link copied to clipboard.'), 'success');
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
      showToast(t('toast.deploying_official_tailscale_container_to_docker', 'Deploying official Tailscale container to Docker...'), 'info');

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
              showToast(t('toast.authorization_link_copied_to_clipboard', 'Authorization link copied to clipboard.'), 'success');
            }
          };
        }
        showToast(t('toast.tailscale_deployed_opening_authorization_window', 'Tailscale deployed! Opening authorization window...'), 'info');
        startTailscaleAuthPolling();
      } else {
        showToast(t('toast.tailscale_container_deployed_and_connected', 'Tailscale container deployed and connected!'), 'success');
        if (tsAuthPrompt) tsAuthPrompt.style.display = 'none';
        fetchAndRenderWireguard();
      }
    } catch (err) {
      showToast(t('toast.tailscale_deployment_failed', 'Tailscale deployment failed: {error}', { error: err.message }), 'error');
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
          showToast(t('toast.tailscale_node_successfully_authorized_and_connected', 'Tailscale node successfully authorized and connected!'), 'success');
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
                showToast(t('toast.authorization_link_copied_to_clipboard', 'Authorization link copied to clipboard.'), 'success');
              }
            };
          }
          showToast(t('toast.tailscale_login_opened_complete_authorization_in', 'Tailscale login opened! Complete authorization in your browser.'), 'info');
          startTailscaleAuthPolling();
        } else {
          showToast(t('toast.connected_host_to_tailscale_mesh_network', 'Connected host to Tailscale mesh network.'), 'success');
          if (tsAuthKeyInput) tsAuthKeyInput.value = '';
          fetchAndRenderWireguard();
        }
      } catch (err) {
        showToast(t('toast.tailscale_connection_failed', 'Tailscale connection failed: {error}', { error: err.message || 'Daemon error' }), 'error');
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
        showToast(t('toast.disconnected_from_tailscale_mesh_network', 'Disconnected from Tailscale mesh network.'), 'info');
        fetchAndRenderWireguard();
      } catch (err) {
        showToast(t('toast.tailscale_disconnection_failed', 'Tailscale disconnection failed: {error}', { error: err.message || 'Daemon error' }), 'error');
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
        showToast(t('toast.copied_tailscale_ip', 'Copied Tailscale IP: {ip}', { ip: ip }), 'success');
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
          showToast(t('toast.re_authentication_initiated_complete_in_your', 'Re-authentication initiated. Complete in your browser.'), 'info');
          startTailscaleAuthPolling();
        } else {
          showToast(t('toast.tailscale_node_re_authenticated_successfully', 'Tailscale node re-authenticated successfully.'), 'success');
          fetchAndRenderWireguard();
        }
      } catch (err) {
        showToast(t('toast.re_authentication_failed', 'Re-authentication failed: {error}', { error: err.message }), 'error');
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
      showToast(t('toast.failed_to_update_subnet_routes', 'Failed to update subnet routes: {message}', { message: e.message }), 'error');
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
        showToast(t('toast.failed_to_set_exit_node', 'Failed to set exit node: {message}', { message: e.message }), 'error');
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
        showToast(t('toast.failed_to_toggle_ssh', 'Failed to toggle SSH: {message}', { message: e.message }), 'error');
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
          { confirmText: 'Open Approval Page', cancelText: 'Close', allowHtml: true }
        );
      } else if (res && res.status === 'error') {
        if (tsServeToggle) tsServeToggle.checked = Boolean(res.serve_enabled);
        if (tsFunnelToggle) tsFunnelToggle.checked = Boolean(res.funnel_enabled);
        showToast(t('toast.tailscale_configuration_error', 'Tailscale configuration error: {error}', { error: res.error || 'Operation failed' }), 'error');
      } else {
        if (serve && !res.serve_enabled) {
          if (tsServeToggle) tsServeToggle.checked = false;
          showToast(t('toast.tailscale_serve_could_not_be_activated', 'Tailscale Serve could not be activated. Check tailscaled daemon status.'), 'warn');
        } else if (serve && res.serve_url) {
          showServeLink(res.serve_url, Boolean(res.funnel_enabled));
        } else {
          showToast(
            serve
              ? t('toast.ts_serve_on', 'Tailscale HTTPS Serve enabled on port 8082.')
              : t('toast.ts_serve_off', 'Tailscale Serve disabled.'),
            'success'
          );
        }
      }
      fetchAndRenderWireguard();
    } catch (e) {
      showToast(t('toast.failed_to_configure_tailscale_serve', 'Failed to configure Tailscale Serve: {message}', { message: e.message }), 'error');
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
          showToast(t('toast.tailscale_https_url_copied_to_clipboard', 'Tailscale HTTPS URL copied to clipboard.'), 'success');
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
          t('toast.taildrop_check_completed_file_s_available', 'Taildrop check completed. {count} file(s) available in inbox.', { count: res.count || 0 }),
          'success'
        );
        fetchAndRenderWireguard();
      } catch (e) {
        showToast(t('toast.failed_to_fetch_taildrop_files', 'Failed to fetch Taildrop files: {message}', { message: e.message }), 'error');
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
          showToast(t('toast.pinged', 'Pinged {ip}: {latency} ({route})', { ip: ip, latency: res.latency, route: res.route || 'direct' }), 'success');
        } else {
          if (resSpan) {
            resSpan.textContent = '❌ Failed';
            resSpan.style.color = '#f87171';
          }
          showToast(t('toast.ping_failed_or_timed_out', 'Ping {ip} failed or timed out.', { ip: ip }), 'warning');
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
      showToast(t('toast.mesh_vpn_telemetry_refreshed', 'Mesh VPN telemetry refreshed.'), 'info');
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
            showToast(t('toast.wireguard_client_config_copied_to_clipboard', 'WireGuard client config copied to clipboard.'), 'success');
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
            showToast(t('toast.downloaded_wireguard_conf_profile', 'Downloaded WireGuard .conf profile.'), 'info');
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
            // the QR library loads only when a QR code is shown (FE-02)
            const { default: QRCode } = await import('qrcode');
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
                const { default: QRCode } = await import('qrcode');
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
                  showToast(t('toast.copied_wireguard_config_to_clipboard', 'Copied WireGuard config to clipboard.'), 'success');
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
                  showToast(t('toast.exported_wireguard_conf_profile', 'Exported WireGuard .conf profile.'), 'info');
                };
              }
            };

            qrCanvasWrap.onclick = openQrModal;
          } catch (qrErr) {
            console.warn('[WireGuard] QR generation error:', qrErr);
          }
        }

        showToast(t('toast.wireguard_curve25519_client_profile_generated', 'WireGuard Curve25519 client profile generated.'), 'success');
      } catch (err) {
        showToast(t('toast.failed_to_generate_wireguard_config', 'Failed to generate WireGuard config: {error}', { error: err.message }), 'error');
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
        const nextState = !curStatus.enabled;
        const res = await api.post('/api/network/mesh-vpn/wireguard/subnet-routing', {
          enabled: nextState,
          interface: 'wg0',
          out_interface: 'eth0',
        });
        showToast(res.enabled ? t('toast.wg_routing_enabled', 'WireGuard subnet routing enabled.') : t('toast.wg_routing_disabled', 'WireGuard subnet routing disabled.'), 'info');
        fetchAndRenderWireguard();
      } catch (err) {
        showToast(t('toast.subnet_routing_toggle_failed', 'Subnet routing toggle failed: {error}', { error: err.message }), 'error');
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

  const fmtBytes = (bytes) => formatSize(bytes);

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
                <span style="font-size:11px; color:var(--muted);">${nic.duplex === 'full' ? 'Full Duplex' : nic.duplex}</span>
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
                <span style="font-size:11px; color:var(--muted); margin-left:4px;">(${escapeHtml(nic.duplex)})</span>
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:11px;">${escapeHtml(nic.mac || '--')}</td>
              <td style="font-family:var(--font-mono, monospace);">${escapeHtml(String(nic.mtu || 1500))}</td>
              <td>
                ${nic.master ? `<span class="network-member-pill" style="color:var(--accent-cyan); border-color:rgba(56,189,248,0.3);">${escapeHtml(nic.master)}</span>` : '<span style="color:var(--muted);">Standalone</span>'}
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:11px;">
                <div>↓ ${rxFmt} <span style="font-size:11px; color:var(--muted);">(${formatNumber(nic.rx_packets || 0)} pkts)</span></div>
                <div>↑ ${txFmt} <span style="font-size:11px; color:var(--muted);">(${formatNumber(nic.tx_packets || 0)} pkts)</span></div>
              </td>
              <td style="font-size:11px; color:var(--muted);">
                <div>${escapeHtml(nic.driver || 'Generic')}</div>
                <div style="font-family:var(--font-mono, monospace); font-size:11px;">${escapeHtml(nic.pci_slot || '--')}</div>
              </td>
              <td style="text-align: right;">
                <button class="btn-pill-toggle btn-config-port" data-iface="${escapeHtml(nic.name)}" style="font-size:11px; padding:2px 8px; color:var(--accent-cyan, #38bdf8); border-color:rgba(56,189,248,0.3);">${t('net.configure_port', 'Configure')}</button>
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
                <span class="switch-speed-pill ${br.stp ? 'speed-10g' : 'speed-down'}" style="font-size:11px; padding:2px 6px;">STP: ${br.stp ? 'ON' : 'OFF'}</span>
                <span style="font-size:11px; color:var(--muted); font-family:var(--font-mono, monospace);">FD: ${br.forward_delay || 0}s</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span class="network-bridge-ip">${escapeHtml(br.ip_address || 'Unassigned IP')}</span>
                <button class="btn-pill-toggle btn-config-bridge" data-bridge="${escapeHtml(br.name)}" style="font-size:11px; padding:2px 8px; color:var(--accent-cyan, #38bdf8); border-color:rgba(56,189,248,0.3);">${t('net.configure_bridge', 'Configure')}</button>
              </div>
            </div>
            <div style="font-size:11px; color:var(--muted);">Member Ports:</div>
            <div class="network-bridge-members">
              ${(br.interfaces || []).map((m) => `<span class="network-member-pill">${escapeHtml(m)}</span>`).join('') || '<span style="color:var(--muted); font-size:11px;">No members</span>'}
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
                <span style="font-size:11px; color:var(--muted); font-family:var(--font-mono, monospace);">${b.miimon || 100}ms</span>
              </div>
              <button class="btn-pill-toggle btn-config-bond" data-bond="${escapeHtml(b.name)}" style="font-size:11px; padding:2px 8px; color:var(--accent-cyan, #38bdf8); border-color:rgba(56,189,248,0.3);">${t('net.configure_bond', 'Configure')}</button>
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
                <button class="btn-pill-toggle btn-delete-vlan" data-vlan="${escapeHtml(v.name)}" style="font-size:11px; padding:2px 8px; color:#f87171; border-color:rgba(248,113,113,0.3);" title="Delete VLAN">🗑</button>
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
          showToast(t('toast.mac_address_copied_to_clipboard', 'MAC address {mac} copied to clipboard!', { mac: mac }), 'info');
        } else {
          showToast(t('toast.no_mac_address_available_to_copy', 'No MAC address available to copy'), 'warn');
        }
      };
    }
    if (roDriver) roDriver.textContent = nic.driver || 'Generic';
    if (roPci) roPci.textContent = nic.pci_slot || '--';
    if (roLink) roLink.textContent = nic.is_up ? `${nic.speed_human || 'Connected'} (${nic.duplex || 'full'})` : 'Down / Disconnected';
  } catch (err) {
    showToast(t('toast.failed_to_load_port_config', 'Failed to load port config: {error}', { error: err.message || err }), 'error');
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
    showToast(t('toast.mtu_must_be_an_integer_between', 'MTU must be an integer between 68 and 9216'), 'error');
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
    showToast(t('toast.please_enter_a_network_name', 'Please enter a network name'), 'error');
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
    showToast(t('toast.failed_to_load_host_network_config', 'Failed to load host network config: {error}', { error: err.message || err }), 'error');
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
    showToast(t('toast.please_enter_an_ipv4_address', 'Please enter an IPv4 address'), 'error');
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
              <span style="font-size:11px; color:var(--muted); margin-left:auto;">${escapeHtml(nic.speed_human || (nic.is_up ? 'Connected' : 'Disconnected'))}</span>
            </label>
          `;
          })
          .join('');
      }
    }

    overlay.classList.add('open');
    overlay.style.display = 'flex';
  } catch (err) {
    showToast(t('toast.failed_to_load_bond_configuration', 'Failed to load bond configuration: {error}', { error: err.message || err }), 'error');
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
    showToast(t('toast.please_select_at_least_one_physical', 'Please select at least one physical interface for the bond'), 'error');
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
              <span class="network-member-pill" style="font-size:11px; padding:1px 5px;">${escapeHtml(cand.type || 'interface')}</span>
              ${cand.alias ? `<span class="switch-port-alias-tag">${escapeHtml(cand.alias)}</span>` : ''}
              <span style="font-size:11px; color:var(--muted); margin-left:auto;">${escapeHtml(cand.speed_human || (cand.is_up ? 'Connected' : 'Disconnected'))}</span>
            </label>
          `;
          })
          .join('');
      }
    }

    overlay.classList.add('open');
    overlay.style.display = 'flex';
  } catch (err) {
    showToast(t('toast.failed_to_load_bridge_configuration', 'Failed to load bridge configuration: {error}', { error: err.message || err }), 'error');
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
    showToast(t('toast.failed_to_open_vlan_creator', 'Failed to open VLAN creator: {error}', { error: err.message || err }), 'error');
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
    showToast(t('toast.please_select_a_parent_trunk_interface', 'Please select a parent trunk interface'), 'error');
    return;
  }
  if (isNaN(vid) || vid < 1 || vid > 4094) {
    showToast(t('toast.vlan_id_must_be_an_integer', 'VLAN ID must be an integer between 1 and 4094'), 'error');
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
      <div style="font-size:11px; color:var(--muted);">SN: ${escapeHtml(serialStr)}</div>
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
        <button class="btn-pill-toggle btn-locate-row" data-dev="${devName}" title="Locate Drive (Blink Bay LED)" style="padding:3px 8px; font-size:11px;">⚡ Locate</button>
        <button class="btn-pill-toggle btn-smart-row" data-dev="${devName}" title="View S.M.A.R.T. Diagnostics" style="padding:3px 8px; font-size:11px;">📊 S.M.A.R.T.</button>
        <button type="button" class="btn-pill-toggle btn-disk-more-sheet" data-dev="${devName}" title="More Actions" style="display:none; padding:3px 8px; font-size:12px;">···</button>
      </div>
    </td>
  `;
}

export function computeDiskRowSignature(d) {
  const devName = d.dev || d.name || 'unknown';
  const modelStr = d.model || 'Generic Disk';
  const serialStr = d.serial && d.serial !== 'Unknown' ? d.serial : '--';
  const transportStr = (d.transport || (devName.startsWith('nvme') ? 'nvme' : 'sata')).toUpperCase();
  const driverStr = d.controller_driver || (devName.startsWith('nvme') ? 'nvme' : 'ahci');
  const sizeStr = d.size_formatted || d.size || '--';
  return `${devName}|${modelStr}|${serialStr}|${transportStr}|${driverStr}|${sizeStr}`;
}

function createDiskRow(d) {
  const devName = d.dev || d.name || 'unknown';
  const tr = document.createElement('tr');
  tr.dataset.key = devName;
  tr.dataset.dev = devName;
  tr.dataset.rowSig = computeDiskRowSignature(d);
  tr.innerHTML = buildDiskRowInner(d);
  return tr;
}

function updateDiskRow(row, d) {
  const newSig = computeDiskRowSignature(d);
  if (row.dataset.rowSig !== newSig) {
    row.dataset.rowSig = newSig;
    row.innerHTML = buildDiskRowInner(d);
    return;
  }

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
            showToast(t('toast.waking_disk_dev_2', 'Waking disk /dev/{dev}...', { dev: dev }), 'info');
            ZettEventBus.emit('modal:smart:open', { dev, forceWake: true });
          }
        );
      } else {
        ZettEventBus.emit('modal:smart:open', dev);
      }
    }
  });
}

// =========================================================================
// Security Advisor Hardening Checklist & HTTPS Guidance Modal
// =========================================================================

export function openHttpsGuideModal() {
  const overlay = document.getElementById('modal-https-guide-overlay');
  if (!overlay) return;
  const statusBanner = document.getElementById('https-guide-status-banner');
  if (statusBanner) {
    const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
    if (isHttps) {
      statusBanner.style.background = 'rgba(34,197,94,0.15)';
      statusBanner.style.border = '1px solid rgba(34,197,94,0.35)';
      statusBanner.style.color = '#22c55e';
      statusBanner.innerHTML = `<span>🔒</span> <span>${t('sec.https_status_secure', 'Active Session is Encrypted via HTTPS (TLS)')}</span>`;
    } else {
      statusBanner.style.background = 'rgba(234,179,8,0.15)';
      statusBanner.style.border = '1px solid rgba(234,179,8,0.35)';
      statusBanner.style.color = '#eab308';
      statusBanner.innerHTML = `<span>⚠️</span> <span>${t('sec.https_status_insecure', 'Active Session is Plaintext HTTP (Unencrypted)')}</span>`;
    }
  }
  overlay.style.display = 'flex';
  overlay.classList.add('open');
  const win = overlay.querySelector('.smart-modal-window');
  if (win) bringToFront(win);
}

export function closeHttpsGuideModal() {
  const overlay = document.getElementById('modal-https-guide-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
}

export function handleSecurityAdvisorClick(checkId) {
  if (!checkId) return;

  switch (checkId) {
    case 'default_password':
    case 'sec_default_password': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-security');
      }
      setTimeout(() => {
        const newPwdInput = document.getElementById('sec-new-pwd');
        const confirmPwdInput = document.getElementById('sec-confirm-pwd');
        if (newPwdInput) {
          try {
            newPwdInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (_) {
            newPwdInput.scrollIntoView();
          }
          newPwdInput.focus();
          newPwdInput.classList.remove('element-focus-pulse');
          void newPwdInput.offsetWidth;
          newPwdInput.classList.add('element-focus-pulse');
          setTimeout(() => newPwdInput.classList.remove('element-focus-pulse'), 1500);
        }
        if (confirmPwdInput) {
          confirmPwdInput.classList.remove('element-focus-pulse');
          void confirmPwdInput.offsetWidth;
          confirmPwdInput.classList.add('element-focus-pulse');
          setTimeout(() => confirmPwdInput.classList.remove('element-focus-pulse'), 1500);
        }
        showToast(t('sec.toast_password_focus', 'Configure your new administrator password below.'), 'info');
      }, 100);
      break;
    }

    case 'admin_mfa':
    case 'sec_superadmin_mfa':
    case 'mfa_admins': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-users', 'users-pane-2fa');
      }
      setTimeout(() => {
        const mfaCard = document.getElementById('mfa-status-card') || document.getElementById('users-pane-2fa');
        if (mfaCard) {
          try {
            mfaCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (_) {
            mfaCard.scrollIntoView();
          }
          mfaCard.classList.remove('element-focus-pulse');
          void mfaCard.offsetWidth;
          mfaCard.classList.add('element-focus-pulse');
          setTimeout(() => mfaCard.classList.remove('element-focus-pulse'), 1500);
        }
      }, 150);
      break;
    }

    case 'https_transport': {
      openHttpsGuideModal();
      break;
    }

    case 'smb_guest_access': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-storage', 'mgmt-pane-storage-shares');
      }
      setTimeout(() => {
        const sharesMount = document.getElementById('mgmt-storage-shares-mount') || document.getElementById('mgmt-pane-storage-shares');
        if (sharesMount) {
          try {
            sharesMount.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } catch (_) {
            sharesMount.scrollIntoView();
          }
          sharesMount.classList.remove('element-focus-pulse');
          void sharesMount.offsetWidth;
          sharesMount.classList.add('element-focus-pulse');
          setTimeout(() => sharesMount.classList.remove('element-focus-pulse'), 1500);
        }
        showToast(t('sec.toast_shares_focus', 'Inspect and manage network share permissions and guest access settings.'), 'info');
      }, 150);
      break;
    }

    case 'stale_api_tokens': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-security');
      }
      setTimeout(() => {
        const tokensList = document.getElementById('api-tokens-list');
        const tokenNameInput = document.getElementById('new-token-name');
        if (tokenNameInput) {
          try {
            tokenNameInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (_) {
            tokenNameInput.scrollIntoView();
          }
          tokenNameInput.focus();
          tokenNameInput.classList.remove('element-focus-pulse');
          void tokenNameInput.offsetWidth;
          tokenNameInput.classList.add('element-focus-pulse');
          setTimeout(() => tokenNameInput.classList.remove('element-focus-pulse'), 1500);
        }
        if (tokensList) {
          tokensList.classList.remove('element-focus-pulse');
          void tokensList.offsetWidth;
          tokensList.classList.add('element-focus-pulse');
          setTimeout(() => tokensList.classList.remove('element-focus-pulse'), 1500);
        }
        showToast(t('sec.toast_tokens_focus', 'Manage and rotate active API integration tokens below.'), 'info');
      }, 100);
      break;
    }

    case 'sec_default_admin': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-security');
      }
      setTimeout(() => {
        const disableContainer = document.getElementById('sec-disable-admin-container');
        const disableBtn = document.getElementById('btn-disable-default-admin');
        if (disableContainer) {
          try {
            disableContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (_) {
            disableContainer.scrollIntoView();
          }
          disableContainer.classList.remove('element-focus-pulse');
          void disableContainer.offsetWidth;
          disableContainer.classList.add('element-focus-pulse');
          setTimeout(() => disableContainer.classList.remove('element-focus-pulse'), 1500);
        }
        if (disableBtn && !disableBtn.disabled) {
          disableBtn.focus();
        }
      }, 100);
      break;
    }

    case 'sec_superadmin_redundancy': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-users', 'users-pane-list');
      }
      setTimeout(() => {
        const btnAdd = document.getElementById('btn-add-user');
        if (btnAdd) {
          btnAdd.focus();
          btnAdd.classList.add('element-focus-pulse');
          setTimeout(() => btnAdd.classList.remove('element-focus-pulse'), 1500);
        }
      }, 150);
      break;
    }

    default:
      console.info('[SecurityAdvisor] Clicked check:', checkId);
      break;
  }
}

export async function fetchAndRenderSecurityPosture() {
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
        const badgeBg = c.passed ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)';
        const actionText = c.passed ? t('sec.action_review', 'Review ➔') : t('sec.action_configure', 'Configure ➔');
        return `
          <div class="sec-advisor-item ${c.passed ? 'passed' : 'needs-action'}" data-check-id="${escapeHtml(c.id)}" role="button" tabindex="0" title="${t('sec.click_to_configure', 'Click to configure')}" style="background:${badgeBg}; border:1px solid ${c.passed ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.3)'};">
            <div style="display:flex; align-items:center; gap:10px; flex:1; min-width:0;">
              <span class="sec-advisor-item-icon" style="color:${passColor}; font-weight:800; font-size:13px; line-height:1;">${passIcon}</span>
              <div style="min-width:0;">
                <div style="font-weight:600; color:#f8fafc; font-size:11.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(c.name)}</div>
                <div style="font-size:11px; color:${c.passed ? '#94a3b8' : '#fca5a5'}; margin-top:2px;">${escapeHtml(c.details || '')}</div>
              </div>
            </div>
            <div style="display:flex; align-items:center; gap:8px; flex-shrink:0;">
              <span class="sec-advisor-status-badge" style="font-size:11px; font-weight:700; color:${passColor}; text-transform:uppercase; letter-spacing:0.5px;">${c.passed ? 'PASSED' : 'NEEDS ACTION'}</span>
              <span class="sec-advisor-action-pill">${actionText}</span>
            </div>
          </div>
        `;
      }).join('');

      container.querySelectorAll('.sec-advisor-item').forEach(item => {
        const checkId = item.dataset.checkId;
        const trigger = () => handleSecurityAdvisorClick(checkId);
        item.addEventListener('click', trigger);
        item.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            trigger();
          }
        });
      });
    }
  } catch (err) {
    console.warn('[SecurityPosture] Failed to fetch posture:', err);
  }
}

if (typeof window !== 'undefined') {
  window.handleSecurityAdvisorClick = handleSecurityAdvisorClick;
  window.fetchAndRenderSecurityPosture = fetchAndRenderSecurityPosture;
  window.openHttpsGuideModal = openHttpsGuideModal;
  window.closeHttpsGuideModal = closeHttpsGuideModal;
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
    if (detailContainer) {
      detailContainer.classList.remove('ai-active');
    }
    const contentPane = document.getElementById('mgmt-content-pane');
    if (contentPane) {
      contentPane.classList.remove('ai-active');
      contentPane.classList.remove('has-subnav');
    }
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
      if (typeof window.initTimezoneControls === 'function') {
        window.initTimezoneControls();
      }
    } else if (paneId === 'mgmt-pane-calendar') {
      if (typeof window.initCalendarView === 'function') {
        window.initCalendarView();
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
    } else if (paneId === 'mgmt-pane-hardware-lcd') {
      if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
      setTimeout(() => {
        fitMiniPreviewScale();
        syncMiniPreviewTelemetry();
      }, 50);
    } else if (paneId === 'mgmt-pane-hardware-fans') {
      if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
    } else if (paneId === 'mgmt-pane-hardware-led') {
      if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
    } else if (paneId === 'mgmt-pane-hardware-copy') {
      if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
    } else if (paneId === 'mgmt-pane-docker') {
      const wrapContainers = document.getElementById('docker-view-containers-wrap');
      const wrapCatalog = document.getElementById('docker-view-catalog-wrap');
      const btnContainers = document.getElementById('btn-view-docker-containers');
      const btnCatalog = document.getElementById('btn-view-docker-catalog');
      const tabContainers = document.getElementById('docker-inner-tab-containers');
      const tabCatalog = document.getElementById('docker-inner-tab-catalog');
      if (wrapContainers) wrapContainers.style.display = 'block';
      if (wrapCatalog) wrapCatalog.style.display = 'none';
      if (btnContainers) {
        btnContainers.style.display = 'none';
        btnContainers.classList.remove('active');
      }
      if (btnCatalog) btnCatalog.classList.remove('active');
      if (tabContainers) {
        tabContainers.classList.add('active');
        tabContainers.setAttribute('aria-selected', 'true');
      }
      if (tabCatalog) {
        tabCatalog.classList.remove('active');
        tabCatalog.setAttribute('aria-selected', 'false');
      }
      fetchAndRenderDockerContainers();
    } else if (paneId === 'mgmt-pane-docker-catalog') {
      const wrapContainers = document.getElementById('docker-view-containers-wrap');
      const wrapCatalog = document.getElementById('docker-view-catalog-wrap');
      const btnContainers = document.getElementById('btn-view-docker-containers');
      const btnCatalog = document.getElementById('btn-view-docker-catalog');
      const tabContainers = document.getElementById('docker-inner-tab-containers');
      const tabCatalog = document.getElementById('docker-inner-tab-catalog');
      if (wrapContainers) wrapContainers.style.display = 'none';
      if (wrapCatalog) wrapCatalog.style.display = 'block';
      if (btnContainers) {
        btnContainers.style.display = 'inline-flex';
        btnContainers.textContent = '← Back to Containers';
        btnContainers.classList.remove('active');
      }
      if (btnCatalog) btnCatalog.classList.add('active');
      if (tabContainers) {
        tabContainers.classList.remove('active');
        tabContainers.setAttribute('aria-selected', 'false');
      }
      if (tabCatalog) {
        tabCatalog.classList.add('active');
        tabCatalog.setAttribute('aria-selected', 'true');
      }
      fetchAndRenderAppCatalog();
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
      import('./settings.js').then((m) => m.renderApiTokens && m.renderApiTokens()).catch(() => {});
      import('./guard-panel.js').then((m) => m.renderGuardPanel()).catch(() => {});
      import('./sso.js').then((m) => m.renderSsoPanel()).catch(() => {});
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
    } else if (paneId === 'mgmt-pane-ai-rag' || paneId === 'mgmt-pane-ai-chat' || paneId === 'mgmt-pane-ai-visual' || paneId === 'mgmt-pane-ai-index') {
      fetchAndRenderAiStatus();
      if (paneId === 'mgmt-pane-ai-rag' || paneId === 'mgmt-pane-ai-visual') {
        const q = _getActiveAiSearchQuery();
        if (q || _aiSelectedColor || _aiSelectedScene) {
          runAiVisualSearch(q);
        } else {
          _renderAiRagInitialEmptyState();
        }
      } else if (paneId === 'mgmt-pane-ai-chat') {
        const chatInput = document.getElementById('ai-chat-input');
        if (chatInput) setTimeout(() => chatInput.focus(), 50);
      }
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
            <div style="font-size: 11px; color: var(--muted); font-weight: 700; text-transform: uppercase;">HYPERVISOR ENGINE</div>
            <div style="font-size: 13px; font-weight: 700; color: ${kvmColor}; margin-top: 4px; display: flex; align-items: center; gap: 6px;">
              <span>⚡</span> <span>${escapeHtml(kvmBadge)}</span>
            </div>
          </div>
          <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 10px 14px;">
            <div style="font-size: 11px; color: var(--muted); font-weight: 700; text-transform: uppercase;">MEMORY CEILING</div>
            <div style="font-size: 13px; font-weight: 700; color: var(--accent-cyan, #0ea5e9); margin-top: 4px;">
              ${escapeHtml(headroom)}
            </div>
          </div>
          <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 10px 14px;">
            <div style="font-size: 11px; color: var(--muted); font-weight: 700; text-transform: uppercase;">vCPU OVERCOMMIT</div>
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

            const ramGb = vm.ram_gb ? `${vm.ram_gb} GB` : (vm.memory_mb ? (vm.memory_mb >= 1024 ? `${(vm.memory_mb / 1024).toFixed(0)} GB` : `${vm.memory_mb} MB`) : '1 GB');
            const cores = vm.vcpus || vm.cores || 1;
            const osType = vm.os_family ? (vm.os_family.charAt(0).toUpperCase() + vm.os_family.slice(1)) : (vm.os_type || 'Linux');

            return `
              <div class="mgmt-vm-card" data-vm-id="${escapeHtml(vm.id)}" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 14px; display: flex; flex-direction: column; gap: 10px; transition: border-color 0.2s;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 18px;">🖥️</span>
                    <div>
                      <div style="font-weight: 700; font-size: 13px; color: #fff;">${escapeHtml(vm.name || vm.id)}</div>
                      <div style="font-size: 11px; color: var(--muted);">${escapeHtml(osType)} • ${cores} vCPU • ${ramGb} RAM</div>
                    </div>
                  </div>
                  <span style="padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; background: ${statusBg}; color: ${statusColor};">
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
                showToast(t('toast.vm_started_successfully', 'VM started successfully'), 'success');
                fetchAndRenderMgmtVms();
              } catch (err) {
                showToast(t('toast.failed_to_start_vm', 'Failed to start VM: {error}', { error: err.message }), 'error');
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
                showToast(t('toast.vm_stop_signal_sent', 'VM stop signal sent'), 'info');
                fetchAndRenderMgmtVms();
              } catch (err) {
                showToast(t('toast.failed_to_stop_vm', 'Failed to stop VM: {error}', { error: err.message }), 'error');
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
                <div style="font-size: 11px; color: var(--muted);">CPU Host Threads</div>
                <div style="font-size: 14px; font-weight: 700; color: #fff; margin-top: 2px;">${tel.cpu?.host_threads || 8} Threads</div>
              </div>
              <div style="background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px;">
                <div style="font-size: 11px; color: var(--muted);">vhost-net Acceleration</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--ok2); margin-top: 2px;">Supported</div>
              </div>
              <div style="background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px;">
                <div style="font-size: 11px; color: var(--muted);">Default Network Bridge</div>
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
    if (desiredSubPane === 'mgmt-pane-ai-visual') {
      desiredSubPane = 'mgmt-pane-ai-rag';
      setAiVisualFiltersDrawerOpen(true);
    }

    if (hubView) hubView.style.display = 'none';
    const isAi = targetId === 'mgmt-sec-ai';
    if (detailContainer) {
      detailContainer.style.display = isAi ? 'flex' : 'block';
      detailContainer.style.flexDirection = isAi ? 'column' : '';
      detailContainer.style.height = isAi ? '100%' : '';
      detailContainer.classList.toggle('ai-active', isAi);
    }
    const contentPane = document.getElementById('mgmt-content-pane');
    if (contentPane) {
      contentPane.classList.toggle('ai-active', isAi);
      const activeCard = document.getElementById(targetId);
      const hasSubnav = activeCard ? !!activeCard.querySelector('.mgmt-sticky-subnav') : false;
      contentPane.classList.toggle('has-subnav', hasSubnav);
    }
    if (headerNav) headerNav.style.display = 'flex';
    if (backBtn) backBtn.style.display = 'inline-flex';

    document.querySelectorAll('.mgmt-detail-card').forEach((c) => {
      if (c.id === targetId) {
        c.style.display = c.id === 'mgmt-sec-ai' ? 'flex' : 'block';
        if (c.id === 'mgmt-sec-ai') {
          c.style.flexDirection = 'column';
          c.style.height = '100%';
        }
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
        if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
        if (state.lastStats || state.latestStats) updateManagementTelemetry(state.lastStats || state.latestStats);
      } else if (targetId === 'mgmt-sec-storage') {
        sectionName = t('mgmt.storage_title', 'Storage & Disks');
      } else if (targetId === 'mgmt-sec-ups') {
        sectionName = t('mgmt.sidebar_ups', 'Power & Battery');
        fetchAndRenderUpsTelemetry();
        if (typeof loadUpsConfigToDrawer === 'function') loadUpsConfigToDrawer();
      } else if (targetId === 'mgmt-sec-system-group') {
        sectionName = t('mgmt.system_title', 'System & Identity');
      } else if (targetId === 'mgmt-sec-ai') {
        sectionName = t('mgmt.sidebar_ai', 'AI & RAG Search');
        fetchAndRenderAiStatus();
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
            const tabsContainer = t.closest('.mgmt-inner-tabs');
            if (tabsContainer && tabsContainer.scrollWidth > tabsContainer.clientWidth) {
              try { t.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
            }
          }
        });
        parentCard.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
          const isMatch = p.id === desiredSubPane || (p.id === 'mgmt-pane-docker' && desiredSubPane === 'mgmt-pane-docker-catalog');
          p.style.display = isMatch ? (p.id === 'mgmt-pane-ai-chat' ? 'flex' : 'block') : 'none';
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
            const isMatch = p.id === paneId || (p.id === 'mgmt-pane-docker' && paneId === 'mgmt-pane-docker-catalog');
            p.style.display = isMatch ? (p.id === 'mgmt-pane-ai-chat' ? 'flex' : 'block') : 'none';
          });
          triggerSubTabLoad(paneId, subTabId);
        } else {
          const singlePane = parentCard.querySelector('.mgmt-tab-pane');
          if (singlePane) {
            singlePane.style.display = singlePane.id === 'mgmt-pane-ai-chat' ? 'flex' : 'block';
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
        const tabsContainer = tab.closest('.mgmt-inner-tabs');
        if (tabsContainer && tabsContainer.scrollWidth > tabsContainer.clientWidth) {
          try { tab.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
        }
      }
      
      // Update tab panes
      const targetPaneId = tab.dataset.tabTarget;
      parentCard.querySelectorAll('.mgmt-tab-pane').forEach(p => {
        const isMatch = p.id === targetPaneId || (p.id === 'mgmt-pane-docker' && targetPaneId === 'mgmt-pane-docker-catalog');
        if (isMatch) {
          p.style.display = p.id === 'mgmt-pane-ai-chat' ? 'flex' : 'block';
        } else {
          p.style.display = 'none';
        }
      });
      
      // Reset scroll position to top of pane when switching sub-tabs
      const contentPane = tab.closest('.mgmt-content-pane') || document.querySelector('.mgmt-content-pane');
      if (contentPane && contentPane.scrollTop > 0) {
        contentPane.scrollTop = 0;
      }

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
        showToast(t('toast.system_profile_switched', 'System profile switched to {profile}.', { profile: p === 'auto' ? t('toast.profile_auto', 'Automatic') : p.toUpperCase() }), 'success');
      } catch (err) {
        showToast(t('toast.failed_to_switch_profile', 'Failed to switch profile: {error}', { error: err.message }), 'error');
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
      showToast(t('toast.ingest_history_refreshed', 'Ingest history refreshed.'), 'info');
    });
  }

  // Network topology refresh button & controls
  const refreshNetBtn = document.getElementById('btn-refresh-network-topology');
  if (refreshNetBtn) {
    refreshNetBtn.addEventListener('click', () => {
      fetchAndRenderNetworkTopology();
      showToast(t('toast.network_topology_refreshed', 'Network topology refreshed.'), 'info');
    });
  }
  initNetworkControls();

  // Docker containers refresh button
  const refreshDockerBtn = document.getElementById('btn-refresh-docker');
  if (refreshDockerBtn) {
    refreshDockerBtn.addEventListener('click', () => {
      fetchAndRenderDockerContainers();
      showToast(t('toast.docker_containers_refreshed', 'Docker containers refreshed.'), 'info');
    });
  }

  // UPS telemetry refresh button & drawer controls
  const refreshUpsBtn = document.getElementById('btn-refresh-ups');
  if (refreshUpsBtn) {
    refreshUpsBtn.addEventListener('click', () => {
      fetchAndRenderUpsTelemetry();
      showToast(t('toast.ups_telemetry_refreshed', 'UPS telemetry refreshed.'), 'info');
    });
  }
  initUpsDrawerControls();

  // Virtual Machines refresh, launch window & create wizard buttons
  const refreshVmBtn = document.getElementById('btn-mgmt-vm-refresh');
  if (refreshVmBtn) {
    refreshVmBtn.addEventListener('click', () => {
      fetchAndRenderMgmtVms();
      showToast(t('toast.vm_fleet_refreshed', 'VM fleet refreshed.'), 'info');
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

  const btnIsoLibrary = document.getElementById('btn-mgmt-vm-iso-library');
  if (btnIsoLibrary && !btnIsoLibrary.dataset.bound) {
    btnIsoLibrary.dataset.bound = '1';
    btnIsoLibrary.addEventListener('click', async () => {
      const { openIsoManagerModal } = await import('./vm-manager.js');
      if (typeof openIsoManagerModal === 'function') {
        openIsoManagerModal('catalog');
      }
    });
  }

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

  const btnOpenCopy = document.getElementById('btn-open-copy-drawer');
  if (btnOpenCopy) {
    btnOpenCopy.addEventListener('click', () => {
      openDrawer('tab-buttons');
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
      showToast(t('toast.chassis_digital_twin_refreshed', 'Chassis digital twin refreshed.'), 'info');
    });
  }

  // Storage pool topology refresh & create buttons
  const refreshTopoBtn = document.getElementById('btn-refresh-topo');
  if (refreshTopoBtn) {
    refreshTopoBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      if (mount) fetchAndRenderStorageTopology(mount);
      showToast(t('toast.storage_topology_refreshed', 'Storage topology refreshed.'), 'info');
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
      showToast(t('toast.network_shares_refreshed', 'Network shares refreshed.'), 'info');
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

  // Quick Manage Protocols shortcut in Network Shares pane
  const quickManageProtocolsBtn = document.getElementById('btn-quick-manage-protocols');
  if (quickManageProtocolsBtn) {
    quickManageProtocolsBtn.addEventListener('click', () => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-network', 'mgmt-pane-network-services');
      }
    });
  }

  // Remote & Cloud Storage refresh button
  const refreshRemotesBtn = document.getElementById('btn-refresh-remotes');
  if (refreshRemotesBtn) {
    refreshRemotesBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      if (mount) fetchAndRenderRemoteStorage(mount);
      showToast(t('toast.remote_storage_refreshed', 'Remote storage refreshed.'), 'info');
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
      showToast(t('toast.disks_inventory_refreshed', 'Disks inventory refreshed.'), 'info');
    });
  }

  // Replication refresh and create pipeline buttons
  const refreshReplBtn = document.getElementById('btn-refresh-replication');
  if (refreshReplBtn) {
    refreshReplBtn.addEventListener('click', () => {
      fetchAndRenderReplication();
      showToast(t('toast.replication_pipelines_refreshed', 'Replication pipelines refreshed.'), 'info');
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
          showToast(t('toast.replication_pipeline_created', 'Replication pipeline \'{name}\' created.', { name: payload.name }), 'success');
          closeReplModal();
          fetchAndRenderReplication();
        } catch (err) {
          showToast(t('toast.failed_to_create_pipeline', 'Failed to create pipeline: {error}', { error: err.message }), 'error');
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
      showToast(t('toast.wireguard_mesh_status_refreshed', 'WireGuard mesh status refreshed.'), 'info');
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
  const revertUpdateBtn = document.getElementById('btn-revert-system-update');
  if (revertUpdateBtn) {
    revertUpdateBtn.addEventListener('click', revertSystemUpdate);
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
  const diagPreviewOverlay = document.getElementById('diagnostics-preview-modal-overlay');
  if (diagPreviewOverlay) {
    diagPreviewOverlay.addEventListener('click', (e) => {
      if (e.target === diagPreviewOverlay) {
        closeDiagnosticsPreviewModal();
      }
    });
    const diagWin = diagPreviewOverlay.querySelector('.smart-modal-window');
    const diagHeader = document.getElementById('diagnostics-preview-header');
    if (diagWin && diagHeader && typeof makeDraggable === 'function') {
      makeDraggable(diagWin, diagHeader, 'diagnostics-preview');
    }
  }

  // HTTPS Guidance Modal triggers
  const closeHttpsGuideBtn = document.getElementById('modal-https-guide-close');
  if (closeHttpsGuideBtn) {
    closeHttpsGuideBtn.addEventListener('click', closeHttpsGuideModal);
  }
  const closeHttpsGuideFooterBtn = document.getElementById('btn-modal-https-guide-close');
  if (closeHttpsGuideFooterBtn) {
    closeHttpsGuideFooterBtn.addEventListener('click', closeHttpsGuideModal);
  }
  const btnHttpsApps = document.getElementById('btn-https-guide-apps');
  if (btnHttpsApps) {
    btnHttpsApps.addEventListener('click', () => {
      closeHttpsGuideModal();
      window.openManagementWindow('mgmt-sec-docker', 'mgmt-pane-docker-catalog');
    });
  }
  const btnHttpsPorts = document.getElementById('btn-https-guide-ports');
  if (btnHttpsPorts) {
    btnHttpsPorts.addEventListener('click', () => {
      closeHttpsGuideModal();
      window.openManagementWindow('mgmt-sec-network', 'mgmt-pane-network-ports');
    });
  }
  const btnCopyTailscale = document.getElementById('btn-copy-tailscale-serve');
  if (btnCopyTailscale) {
    btnCopyTailscale.addEventListener('click', async () => {
      const ok = await copyTextToClipboard('tailscale serve --https=443 127.0.0.1:8082');
      if (ok) showToast(t('common.copied', 'Copied to clipboard!'), 'success');
    });
  }
  const httpsGuideOverlay = document.getElementById('modal-https-guide-overlay');
  if (httpsGuideOverlay) {
    httpsGuideOverlay.addEventListener('click', (e) => {
      if (e.target === httpsGuideOverlay) {
        closeHttpsGuideModal();
      }
    });
    const httpsWin = httpsGuideOverlay.querySelector('.smart-modal-window');
    const httpsHeader = document.getElementById('modal-https-guide-header');
    if (httpsWin && httpsHeader && typeof makeDraggable === 'function') {
      makeDraggable(httpsWin, httpsHeader, 'https-guide');
    }
  }

  // 2FA Quick Action button
  const btnJump2fa = document.getElementById('btn-jump-to-2fa');
  if (btnJump2fa && !btnJump2fa.dataset.bound) {
    btnJump2fa.dataset.bound = 'true';
    btnJump2fa.addEventListener('click', () => {
      handleSecurityAdvisorClick('admin_mfa');
    });
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
        showToast(t('toast.hyper_backup_pipeline_saved_successfully', 'Hyper-backup pipeline saved successfully!'), 'success');
        closeBackupModal();
        formBackupJob.reset();
        fetchAndRenderBackupJobs();
      } catch (err) {
        showToast(t('toast.failed_to_save_backup_job', 'Failed to save backup job: {error}', { error: err.message }), 'error');
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
        showToast(t('toast.filesystem_snapshot_created_successfully', 'Filesystem snapshot created successfully!'), 'success');
        closeSnapshotModal();
        formSnapshot.reset();
        fetchAndRenderSystemSnapshots();
      } catch (err) {
        showToast(t('toast.failed_to_create_snapshot', 'Failed to create snapshot: {error}', { error: err.message }), 'error');
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
      showToast(t('toast.application_backups_refreshed', 'Application backups refreshed.'), 'info');
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

  // ZettAI Multi-Modal RAG & Visual Search Engine
  initAiKnowledgeEngine();
  if (typeof restoreHardwareTabsToManagement === "function") restoreHardwareTabsToManagement();
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
    refreshPreviousVersions();
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
        const timeStr = formatTime(data.checked_at);
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

// The newest version this install can go back to (a pre-update snapshot whose image is still on the host).
let _previousVersion = null;

export async function refreshPreviousVersions() {
  const btn = document.getElementById('btn-revert-system-update');
  const label = document.getElementById('btn-revert-update-text');
  if (!btn) return null;
  try {
    const res = await api.get('/api/system/updates/previous');
    _previousVersion = (res?.previous || []).find((p) => p.image_available) || null;
  } catch (e) {
    _previousVersion = null;
  }
  btn.style.display = _previousVersion ? 'flex' : 'none';
  if (_previousVersion && label) {
    label.textContent = _previousVersion.version ? `Revert to v${_previousVersion.version}` : 'Revert to previous version';
  }
  return _previousVersion;
}

export async function revertSystemUpdate() {
  const prev = _previousVersion || (await refreshPreviousVersions());
  if (!prev) {
    showToast(t('toast.no_previous_version_is_available_on', 'No previous version is available on this host.'), 'error');
    return;
  }
  const name = prev.version ? `v${prev.version}` : 'the previous version';
  showPromptToast(
    'Revert to previous version',
    `Go back to ${name}? Settings, users and other data return to how they were before the last update, so changes made since then are lost (a snapshot of the current data is kept). Enter your password to confirm.`,
    '',
    async (password) => {
      if (!password) return;
      const overlay = document.getElementById('update-progress-overlay');
      const title = document.getElementById('update-progress-title');
      const desc = document.getElementById('update-progress-desc');
      try {
        const res = await api.post('/api/system/updates/revert', { snapshot_id: prev.id, current_password: password }, { confirmed: true });
        if (overlay) overlay.style.display = 'block';
        if (title) title.textContent = `Reverting to ${name}...`;
        if (desc) desc.textContent = res?.message || 'Restoring the previous version and reconnecting...';
        let attempts = 0;
        let wentDown = false;
        const timer = setInterval(async () => {
          attempts++;
          try {
            const h = await fetch('/api/health', { cache: 'no-store' });
            if (h.ok && (wentDown || attempts >= 8)) {
              clearInterval(timer);
              setTimeout(() => window.location.reload(), 1200);
            }
          } catch (e) {
            wentDown = true;
            if (attempts >= 80) {
              clearInterval(timer);
              if (desc) desc.textContent = 'Please refresh the page once ZettNAS has restarted.';
            }
          }
        }, 1500);
      } catch (err) {
        showToast(t('toast.revert_failed', 'Revert failed: {error}', { error: err.message }), 'error');
      }
    },
    null,
    { inputType: 'password', okText: 'Revert', placeholder: 'Your password' }
  );
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
        const targetImage = channel === 'edge'
          ? 'ghcr.io/fr0styx/zettnas-toolkit:edge'
          : 'ghcr.io/fr0styx/zettnas-toolkit:latest';
        const res = await api.post('/api/system/updates/apply', { channel, target_image: targetImage }, { confirmed: true });
        showToast(res?.message || 'Update initiated. Reconnecting...', 'info');

        if (res && res.auto_restarting === false) {
          if (progressTitle) progressTitle.textContent = '📦 Image Pulled';
          if (progressDesc) {
            progressDesc.innerHTML = `${escapeHtml(res.message || 'Latest image downloaded.')}<br><br><span style="color:var(--brand,#00f0ff);font-weight:600;">Please restart the container in Unraid or Docker to finalize.</span>`;
          }
          if (applyBtn) applyBtn.disabled = false;
          return;
        }

        if (progressDesc) progressDesc.textContent = res?.message || 'Restarting container and reconnecting...';

        // Poll health endpoint until back online
        let attempts = 0;
        let hasGoneDown = false;
        const maxAttempts = 60;
        const interval = setInterval(async () => {
          attempts++;
          try {
            const h = await fetch('/api/health', { cache: 'no-store' });
            // Only declare update complete after the old container has dropped offline, or after grace period
            if (h.ok && (hasGoneDown || attempts >= 8)) {
              clearInterval(interval);
              if (progressTitle) progressTitle.textContent = '🎉 Update Complete!';
              if (progressDesc) progressDesc.textContent = 'Reloading ZettNAS Workbench...';
              showToast(t('updates.updated_success', 'ZettNAS updated successfully!'), 'success');
              setTimeout(() => window.location.reload(), 1200);
            }
          } catch (e) {
            hasGoneDown = true;
            if (progressDesc) progressDesc.textContent = 'Container restarting with updated image...';
            if (attempts >= maxAttempts) {
              clearInterval(interval);
              if (progressDesc) progressDesc.textContent = 'Please refresh the page once the container has restarted.';
              if (applyBtn) applyBtn.disabled = false;
            }
          }
        }, 1500);
      } catch (err) {
        showToast(t('toast.update_failed', 'Update failed: {error}', { error: err.message }), 'error');
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
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
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
              <span style="font-size: 11px; margin-top: 2px;">${a.level === 'critical' ? '🔴' : '🟡'}</span>
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
          <span style="font-size: 11px; color: var(--muted); font-family: monospace;">ZettOS Kernel ${escapeHtml(data.platform || '')}</span>
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
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Host & OS</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${escapeHtml(data.chassis || 'Appliance')}</div>
        <div style="font-size:11px; color:var(--muted); margin-top:1px;">Uptime: ${data.uptime_hours || 0}h</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Memory</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${memPct}% Used</div>
        <div style="font-size:11px; color:var(--muted); margin-top:1px;">${memUsedGb} / ${memTotalGb} GB RAM</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Storage</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${storage.pools_count || 0} Pools</div>
        <div style="font-size:11px; color:${(storage.degraded_disks?.length || 0) > 0 ? 'var(--crit)' : 'var(--muted)'}; margin-top:1px;">${storage.disks_count || 0} Drives (${storage.standby_count || 0} standby)</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Docker Fleet</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${docker.running || 0} / ${docker.total || 0} Running</div>
        <div style="font-size:11px; color:${(docker.restarting || 0) > 0 ? 'var(--crit)' : 'var(--muted)'}; margin-top:1px;">${docker.restarting || 0} Restarting, ${docker.dead || 0} Dead</div>
      </div>
      <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:10px;">
        <div style="font-size:11px; color:var(--muted); text-transform:uppercase; font-weight:700;">Virtual Machines</div>
        <div style="font-size:12px; font-weight:800; color:#fff; margin-top:2px;">${vms.active_vm_count || 0} / ${vms.total_vm_count || 0} Active</div>
        <div style="font-size:11px; color:var(--muted); margin-top:1px;">Headroom: Safe</div>
      </div>
    `;
  }

  overlay.style.display = 'flex';
  overlay.classList.remove('window-minimized');
  overlay.classList.add('open');

  const win = overlay.querySelector('.smart-modal-window');
  if (win && typeof bringToFront === 'function') {
    bringToFront(win);
  }
}

export async function previewDiagnosticsSummary() {
  const btn = document.getElementById('btn-preview-diagnostics');
  const origHtml = btn ? btn.innerHTML : '';
  try {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span class="ci-spinner" style="display:inline-block; width:12px; height:12px; border:2px solid rgba(255,255,255,0.3); border-top-color:#fff; border-radius:50%; animation:spin 0.8s linear infinite;"></span> <span>${t('diagnostics.loading_preview', 'Loading Preview...')}</span>`;
    }
    const data = await api.get('/api/system/diagnostics-summary');
    openDiagnosticsPreviewModal(data);
  } catch (err) {
    showToast(t('toast.failed_to_load_diagnostics_preview', 'Failed to load diagnostics preview: {error}', { error: err.message }), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

export async function copySupportMarkdown() {
  const btn = document.getElementById('btn-copy-support-md');
  const previewCopyBtn = document.getElementById('btn-diag-preview-copy');
  const targetBtn = (previewCopyBtn && document.activeElement === previewCopyBtn) ? previewCopyBtn : btn;
  const origHtml = targetBtn ? targetBtn.innerHTML : '';
  try {
    const mdEl = document.getElementById('diagnostics-preview-md');
    let md = '';
    if (mdEl && mdEl.textContent && mdEl.textContent.trim().length > 0 && mdEl.textContent !== 'No summary generated.') {
      md = mdEl.textContent;
    } else {
      if (targetBtn) {
        targetBtn.disabled = true;
        targetBtn.innerHTML = `<span class="ci-spinner" style="display:inline-block; width:12px; height:12px; border:2px solid rgba(255,255,255,0.3); border-top-color:#fff; border-radius:50%; animation:spin 0.8s linear infinite;"></span> <span>${t('diagnostics.copying_md', 'Copying...')}</span>`;
      }
      const data = await api.get('/api/system/diagnostics-summary');
      md = data?.support_markdown || '';
    }
    if (!md) throw new Error('No support markdown generated');

    const copied = await copyTextToClipboard(md);
    if (copied) {
      showToast(t('diagnostics.copied', 'Support markdown copied to clipboard!'), 'success');
    } else {
      throw new Error('Clipboard copy failed');
    }
  } catch (err) {
    showToast(t('toast.failed_to_copy_support_markdown', 'Failed to copy support markdown: {error}', { error: err.message }), 'error');
  } finally {
    if (targetBtn) {
      targetBtn.disabled = false;
      targetBtn.innerHTML = origHtml;
    }
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
    console.error('Failed to load notification config:', err);
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
    console.error('Failed to save notification settings:', err);
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
      showToast(t('toast.test_alerts_delivered_to', '✓ Test alerts delivered to: {successList}', { successList: successList.join(', ') }), 'success');
    } else {
      showToast(t('toast.no_active_channels_succeeded_check_configuration', 'No active channels succeeded. Check configuration and credentials.'), 'warning');
    }
  } catch (err) {
    showToast(t('toast.test_failed', 'Test failed: {error}', { error: err.message }), 'error');
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
      showToast(t('toast.delivered_in_ms', '✓ {channel}: Delivered in {latency_ms}ms', { channel: channel.toUpperCase(), latency_ms: res.latency_ms }), 'success');
    } else {
      showToast(t('toast.message', '⚠️ {channel}: {message}', { channel: channel.toUpperCase(), message: res.message || 'Delivery failed' }), 'error');
    }
  } catch (err) {
    showToast(t('toast.test_failed_for', 'Test failed for {channel}: {error}', { channel: channel, error: err.message }), 'error');
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
        <div style="font-size:11px; color:var(--muted); margin-top:4px;">Paste the Webhook URL created in your Discord channel settings -> Integrations.</div>
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
        <div style="font-size:11px; color:var(--muted); margin-top:4px;">Obtained from @userinfobot or your Telegram channel/group chat ID.</div>
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
        <div style="font-size:11px; color:var(--muted); margin-top:4px;">Receives POST requests with JSON payload: { event, title, message, level, timestamp }</div>
      </div>
    `;
  } else if (channel === 'apprise_raw') {
    const rawVal = Array.isArray(cfg.apprise_urls) ? cfg.apprise_urls.join('\n') : '';
    formHtml = `
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:11px; font-weight:700; color:var(--muted); margin-bottom:4px;">APPRISE TARGET URLS (One per line)</label>
        <textarea id="cfg-apprise-raw" class="tz-select-input" style="width:100%; height:120px; font-family:monospace; font-size:11px; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.25); padding:8px 10px; color:#fff;" placeholder="pover://userkey@token&#10;slack://TokenA/TokenB/TokenC&#10;gotify://gotify.server/token">${escapeHtml(rawVal)}</textarea>
        <div style="font-size:11px; color:var(--muted); margin-top:4px;">Apprise supports 100+ notification targets. See Apprise documentation for syntax.</div>
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
          <button type="button" class="btn-rect primary" data-action="click-target" data-target="btn-open-create-backup-job" style="font-size: 11px; padding: 6px 14px;">
            Configure First Pipeline
          </button>
        </div>
      `;
      return;
    }

    const rowsHtml = jobs.map(job => {
      const isRemote = job.destination_type === 'remote';
      const destBadge = isRemote
        ? `<span class="badge" style="background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid rgba(14,165,233,0.3); font-size: 11px; padding: 2px 6px; border-radius: 4px;">☁️ ${escapeHtml(job.remote_name || 'Cloud')}:${escapeHtml(job.remote_path || '')}</span>`
        : `<span class="badge" style="background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); font-size: 11px; padding: 2px 6px; border-radius: 4px;">📸 Local Snapshot</span>`;

      const schedBadge = `<span class="badge" style="background: rgba(255,255,255,0.06); color: #cbd5e1; font-size: 11px; padding: 2px 6px; border-radius: 4px; text-transform: capitalize;">${escapeHtml(job.schedule || 'daily')}</span>`;
      
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

      const lastRunStr = formatDateTime(job.last_run_at, undefined, t('common.never', 'Never'));

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11.5px;">
          <td style="padding: 10px 12px; font-weight: 600; color: #fff;">
            <div>${escapeHtml(job.name)}</div>
            <div style="font-size: 11px; color: var(--muted); font-weight: normal;">Subvolume: <code>${escapeHtml(job.source_subvolume || '@shares')}</code></div>
          </td>
          <td style="padding: 10px 12px;">${destBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
              ${schedBadge}
              <span style="font-size: 11px; color: var(--muted);">Keep ${job.retention_count || 7}</span>
            </div>
          </td>
          <td style="padding: 10px 12px;">
            <div>${statusHtml}</div>
            <div style="font-size: 11px; color: var(--muted);">${lastRunStr}</div>
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
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 11px; font-weight: 800; color: var(--muted); text-transform: uppercase;">
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
          showToast(t('toast.triggering_backup_pipeline', 'Triggering backup pipeline {jobId}...', { jobId: jobId }), 'info');
          await api.post(`/api/backup/schedule/${jobId}/run`);
          showToast(t('toast.backup_pipeline_completed_successfully', `Backup pipeline completed successfully!`), 'success');
          fetchAndRenderBackupJobs(mount);
        } catch (err) {
          showToast(t('toast.backup_run_failed', 'Backup run failed: {error}', { error: err.message }), 'error');
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
            showToast(t('toast.backup_task_removed', 'Backup task removed.'), 'success');
            fetchAndRenderBackupJobs(mount);
          } catch (err) {
            showToast(t('toast.failed_to_delete_job', 'Failed to delete job: {error}', { error: err.message }), 'error');
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
      const createdDate = formatDateTime(s.created_at, undefined, 'N/A');
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
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 11px; font-weight: 800; color: var(--muted); text-transform: uppercase;">
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
            showToast(t('toast.restoring_snapshot', 'Restoring snapshot {snapName}...', { snapName: snapName }), 'info');
            await api.post('/api/backup/restore-snapshot', {
              pool_id: poolId,
              snapshot_name: snapName,
            });
            showToast(t('toast.snapshot_successfully_restored', 'Snapshot "{snapName}" successfully restored!', { snapName: snapName }), 'success');
            fetchAndRenderSystemSnapshots(mount);
          } catch (err) {
            showToast(t('toast.restore_failed', 'Restore failed: {error}', { error: err.message }), 'error');
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
            await api.delete(`/api/backup/snapshots/${encodeURIComponent(poolId)}/${encodeURIComponent(snapName)}`, { confirmed: true });
            showToast(t('toast.snapshot_deleted', 'Snapshot "{snapName}" deleted.', { snapName: snapName }), 'success');
            fetchAndRenderSystemSnapshots(mount);
          } catch (err) {
            showToast(t('toast.failed_to_delete_snapshot', 'Failed to delete snapshot: {error}', { error: err.message }), 'error');
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
        ? `<span class="badge" style="background: rgba(239,68,68,0.15); color: #fca5a5; border: 1px solid rgba(239,68,68,0.3); font-size: 11px; padding: 2px 6px; border-radius: 4px;">⚠️ Auto-Archive (Uninstall)</span>`
        : `<span class="badge" style="background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.35); font-size: 11px; padding: 2px 6px; border-radius: 4px;">💾 On-Demand</span>`;

      const createdDate = formatDateTime(b.created_at_epoch || b.created_at, undefined, 'N/A');
      const sizeStr = b.archive_size_formatted || (b.archive_size_bytes ? `${(b.archive_size_bytes / (1024 * 1024)).toFixed(1)} MB` : '--');
      const stackHtml = b.stack ? `<span style="font-size:11px; color:var(--muted); margin-left:6px;">(Stack: <code>${escapeHtml(b.stack)}</code>)</span>` : '';
      const mountsCount = b.mounts_count || (b.mounts ? b.mounts.length : 0);

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11.5px;">
          <td style="padding: 10px 12px; font-weight: 600; color: #fff;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span>📦</span>
              <strong>${escapeHtml(b.container_name || b.id)}</strong>
              ${stackHtml}
            </div>
            <div style="font-size: 11px; color: var(--muted); font-weight: normal; margin-top:2px;">
              Image: <code style="font-size:11px; color:#cbd5e1;">${escapeHtml(b.image || 'N/A')}</code>
            </div>
          </td>
          <td style="padding: 10px 12px;">${reasonBadge}</td>
          <td style="padding: 10px 12px;">
            <div style="font-family: var(--font-mono, monospace); font-size: 11px; color: #e2e8f0;">${escapeHtml(b.archive_file || b.id)}</div>
            <div style="font-size: 11px; color: var(--muted); margin-top: 2px;">
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
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 11px; font-weight: 800; color: var(--muted); text-transform: uppercase;">
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
          showToast(t('toast.downloading_backup', 'Downloading backup "{filename}"...', { filename: filename }), 'info');
          await api.downloadBlob(`/api/backup/apps/${encodeURIComponent(backupId)}/download`, filename);
        } catch (err) {
          showToast(t('toast.download_failed', 'Download failed: {error}', { error: err.message }), 'error');
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
              showToast(t('toast.restoring', 'Restoring {appName}...', { appName: appName }), 'info');
              const res = await api.post(`/api/backup/apps/${encodeURIComponent(backupId)}/restore`);
              showToast(t('toast.app_successfully_restored_paths_restored', 'App "{appName}" successfully restored ({extracted_count} paths restored)!', { appName: appName, extracted_count: res.extracted_count || 'all' }), 'success');
              fetchAndRenderAppBackups(mount, document.getElementById('app-backups-filter-app')?.value || '');
            } catch (err) {
              showToast(t('toast.restore_failed', 'Restore failed: {error}', { error: err.message }), 'error');
            }
          },
          null,
          { okText: '🔄 Restore App Data', cancelText: 'Cancel', allowHtml: true }
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
              await api.delete(`/api/backup/apps/${encodeURIComponent(backupId)}`, { confirmed: true });
              showToast(t('toast.backup_deleted', 'Backup "{filename}" deleted.', { filename: filename }), 'success');
              fetchAndRenderAppBackups(mount, document.getElementById('app-backups-filter-app')?.value || '');
            } catch (err) {
              showToast(t('toast.delete_failed', 'Delete failed: {error}', { error: err.message }), 'error');
            }
          },
          null,
          { okText: '🗑 Delete Archive', cancelText: 'Cancel', allowHtml: true }
        );
      });
    });

  } catch (err) {
    mount.innerHTML = `<div style="padding: 16px; color: #f43f5e; font-size: 12px;">Failed to load application backups: ${escapeHtml(err.message)}</div>`;
  }
}

export const initManagementWindow = initManagement;

// ============================================================================
// ZettAI — Multi-Modal Local RAG & Visual Search Engine Controller
// ============================================================================
let _aiSelectedColor = '';
let _aiSelectedScene = '';
let _aiSelectedFileType = 'all';
let _aiSelectedMatchTab = 'semantic';
let _aiSelectedSortBy = 'relevance';
let _aiWatchedPaths = ['/mnt/user'];
let _aiAvailableFolders = [];
let _aiSyncPollTimer = null;
let _aiLastResultsList = [];
let _aiSearchHistory = [];
try {
  const savedHist = JSON.parse(localStorage.getItem('zettnas_ai_search_history') || '[]');
  if (Array.isArray(savedHist)) _aiSearchHistory = savedHist.slice(0, 8);
} catch (_) {}

function _recordAiSearchHistory(query) {
  const clean = String(query || '').trim();
  if (!clean) return;
  _aiSearchHistory = [clean, ..._aiSearchHistory.filter((q) => q.toLowerCase() !== clean.toLowerCase())].slice(0, 8);
  try {
    localStorage.setItem('zettnas_ai_search_history', JSON.stringify(_aiSearchHistory));
  } catch (_) {}
  renderAiSearchHistory();
}

export function renderAiSearchHistory() {
  const bar = document.getElementById('ai-history-bar');
  const chipsContainer = document.getElementById('ai-history-chips');
  if (!bar || !chipsContainer) return;
  if (!_aiSearchHistory.length) {
    bar.style.display = 'none';
    chipsContainer.innerHTML = '';
    return;
  }
  bar.style.display = 'flex';
  chipsContainer.innerHTML = _aiSearchHistory.map((q) => `
    <button type="button" class="btn-pill-toggle ai-history-chip" data-query="${escapeHtml(q)}" style="font-size:11px; padding:2px 8px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.12); color:#cbd5e1; cursor:pointer;">
      ${escapeHtml(q)}
    </button>
  `).join('');
  chipsContainer.querySelectorAll('.ai-history-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const q = chip.dataset.query || '';
      const askInput = document.getElementById('ai-rag-query-input');
      if (askInput) askInput.value = q;
      const visInput = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
      if (visInput) visInput.value = q;
      runAiRagAsk(q, { unifiedMode: true });
      runAiVisualSearch(q);
    });
  });
}

function _ensureAiSyncPoll(shouldPoll) {
  if (shouldPoll) {
    if (!_aiSyncPollTimer) {
      _aiSyncPollTimer = setInterval(() => {
        fetchAndRenderAiStatus().catch(() => {});
      }, 1500);
    }
  } else if (_aiSyncPollTimer) {
    clearInterval(_aiSyncPollTimer);
    _aiSyncPollTimer = null;
  }
}

export function setAiVisualFiltersDrawerOpen(forceOpen = null) {
  const drawer = document.getElementById('ai-visual-filters-drawer');
  const toggleBtn = document.getElementById('btn-ai-toggle-visual-filters');
  const caret = document.getElementById('ai-visual-filters-caret');
  if (!drawer) return false;
  const isCurrentlyOpen = drawer.style.display !== 'none';
  const nextOpen = forceOpen !== null ? Boolean(forceOpen) : !isCurrentlyOpen;
  drawer.style.display = nextOpen ? 'flex' : 'none';
  if (toggleBtn) {
    toggleBtn.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
    toggleBtn.style.borderColor = (nextOpen || _aiSelectedColor || _aiSelectedScene)
      ? 'rgba(56,189,248,0.55)'
      : 'rgba(56,189,248,0.3)';
  }
  if (caret) {
    caret.textContent = nextOpen ? '▴' : '▾';
  }
  return nextOpen;
}

function _updateAiVisualFilterBadge() {
  const badge = document.getElementById('ai-visual-filters-active-badge');
  if (!badge) return;
  const activeCount = (_aiSelectedColor ? 1 : 0) + (_aiSelectedScene ? 1 : 0);
  if (activeCount > 0) {
    const parts = [_aiSelectedColor, _aiSelectedScene].filter(Boolean);
    badge.style.display = 'inline-block';
    badge.textContent = parts.join(' + ');
  } else {
    badge.style.display = 'none';
    badge.textContent = '';
  }
}

let _aiLastLlmRecommendations = null;
let _aiLastActiveModel = ''; // the model the server reported; never a made-up default (FE-15)
let _aiActiveHfFilter = 'all';
let _aiModelsSortBy = 'date';
let _aiSortListenerAttached = false;

export function renderAiLlmRecommendations(recData = {}, activeModel = '') {
  if (recData && Array.isArray(recData.models)) {
    _aiLastLlmRecommendations = recData;
  }
  const headlineEl = document.getElementById('ai-llm-advisor-headline');
  const summaryEl = document.getElementById('ai-llm-advisor-summary');
  const gridEl = document.getElementById('ai-llm-recommendations-grid');
  const topSelect = document.getElementById('ai-top-model-select');
  const sortSelect = document.getElementById('ai-models-sort-select');

  if (sortSelect) {
    if (!_aiSortListenerAttached) {
      _aiSortListenerAttached = true;
      sortSelect.addEventListener('change', (e) => {
        _aiModelsSortBy = e.target.value || 'date';
        if (_aiLastLlmRecommendations) {
          renderAiLlmRecommendations(_aiLastLlmRecommendations, _aiLastActiveModel);
        }
      });
    }
    sortSelect.value = _aiModelsSortBy;
  }

  if (headlineEl && recData.headline) {
    headlineEl.textContent = recData.headline;
  }
  if (summaryEl && recData.hardware_summary) {
    summaryEl.textContent = recData.hardware_summary;
  }

  const allModelsRaw = Array.isArray(recData.models) ? recData.models : [];
  const currentActive = activeModel || recData.active_model || _aiLastActiveModel || '';
  _aiLastActiveModel = currentActive;

  // Filter out any models that do not fit the user's hardware from the catalog,
  // AND strictly filter out older models released before 2026 (2024, 2025, etc.)
  const allModels = allModelsRaw.filter((m) => {
    // Release year filter: strictly 2026 or newer
    const relStr = String(m.release_date_str || m.release_date || m.created_at || '').trim();
    const ts = Number(m.release_timestamp || 0);
    if (ts > 0 && ts < 1767225600.0) return false;
    if (/\b(20[0-2][0-5])\b/.test(relStr)) return false;

    const isAct = m.id === currentActive || Boolean(m.active);
    const isHfSearch = m.source === 'huggingface_hub' && !m.pulled_from_hf;
    const hasWarn = m.fits_hardware === false || Boolean(m.hardware_warning) || m.fit_status === 'insufficient_ram' || m.fit_status === 'insufficient_vram';
    return !hasWarn || isAct || isHfSearch;
  });

  // Sort models by chosen sort option (Release Date, Recommended, Downloads, Size)
  allModels.sort((a, b) => {
    if (_aiModelsSortBy === 'date') {
      const tsA = Number(a.release_timestamp || 0);
      const tsB = Number(b.release_timestamp || 0);
      if (tsB !== tsA) return tsB - tsA;
      return Number(b.downloads || 0) - Number(a.downloads || 0);
    }
    if (_aiModelsSortBy === 'recommended') {
      const recA = a.recommended ? 1 : 0;
      const recB = b.recommended ? 1 : 0;
      if (recB !== recA) return recB - recA;
      return Number(b.release_timestamp || 0) - Number(a.release_timestamp || 0);
    }
    if (_aiModelsSortBy === 'downloads') {
      return Number(b.downloads || 0) - Number(a.downloads || 0);
    }
    if (_aiModelsSortBy === 'size_asc') {
      const szA = Number(a.vram_or_ram_gb ?? a.est_ram_gb ?? 0);
      const szB = Number(b.vram_or_ram_gb ?? b.est_ram_gb ?? 0);
      return szA - szB;
    }
    if (_aiModelsSortBy === 'size_desc') {
      const szA = Number(a.vram_or_ram_gb ?? a.est_ram_gb ?? 0);
      const szB = Number(b.vram_or_ram_gb ?? b.est_ram_gb ?? 0);
      return szB - szA;
    }
    return 0;
  });

  const activeLlmLabel = document.getElementById('ai-active-llm-label');
  const activeLlmPill = document.getElementById('ai-active-llm-pill');
  if (activeLlmLabel) {
    activeLlmLabel.textContent = currentActive;
  }
  if (activeLlmPill) {
    activeLlmPill.title = `Active Local LLM: ${currentActive} — Leveraged by RAG Synthesis & NAS Copilot Chatbot`;
  }
  const chatModelBadge = document.getElementById('ai-chat-active-model-badge');
  if (chatModelBadge) {
    const activeObj = allModels.find((m) => m.id === currentActive || m.active);
    const rawDev = activeObj?.target_device ? String(activeObj.target_device) : 'NPU Tier 1';
    const devLabel = rawDev.replace(/\s*\([^)]*\)?/g, '').split('/')[0].trim() || 'NPU Tier 1';
    chatModelBadge.textContent = `🤖 ${currentActive} (${devLabel})`;
  }

  // Update filter pill counts if present - hide the warning pill since all shown models fit
  const filterBtns = document.querySelectorAll('.ai-hf-filter-btn');
  const warnBtn = document.querySelector('.ai-hf-filter-btn[data-hf-filter="warning"]');
  if (warnBtn) {
    warnBtn.style.display = 'none';
  }
  if (filterBtns.length > 0 && allModels.length > 0) {
    filterBtns.forEach((btn) => {
      const fType = btn.dataset.hfFilter || 'all';
      btn.classList.toggle('active', fType === 'all' || fType === 'compatible');
      if (fType === 'all') {
        btn.textContent = `2026+ Releases (${allModels.length})`;
      } else if (fType === 'compatible') {
        btn.textContent = `✅ Fits Hardware (${allModels.length})`;
      }
    });
  }

  if (topSelect && allModels.length > 0) {
    topSelect.innerHTML = allModels.map((m) => {
      const isAct = m.id === currentActive || Boolean(m.active);
      const prefix = m.recommended ? '★ ' : '✓ ';
      return `<option value="${escapeHtml(m.id)}" ${isAct ? 'selected' : ''}>${prefix}${escapeHtml(m.name)} (${escapeHtml(m.quantization || 'INT4')})</option>`;
    }).join('');
    topSelect.value = currentActive;
  }

  if (!gridEl || allModels.length === 0) return;

  const filteredModels = allModels;

  if (filteredModels.length === 0) {
    gridEl.innerHTML = `<div style="grid-column:1 / -1; padding:14px; text-align:center; color:var(--muted,#94a3b8); font-size:11.5px; border:1px dashed rgba(255,255,255,0.12); border-radius:8px;">No models match the selected hardware filter.</div>`;
    return;
  }

  gridEl.innerHTML = filteredModels.map((m) => {
    const isAct = m.id === currentActive || Boolean(m.active);
    const isRec = Boolean(m.recommended);
    const hasWarn = m.fits_hardware === false || Boolean(m.hardware_warning) || m.fit_status === 'insufficient_ram' || m.fit_status === 'insufficient_vram';
    const isCritical = m.warning_severity === 'critical' || m.fit_status === 'insufficient_ram';
    const hfRepo = m.hf_repo || m.id || '';
    const hfUrl = m.hf_url || (hfRepo.includes('/') ? `https://huggingface.co/${hfRepo}` : 'https://huggingface.co/models');
    const isLiveHfResult = m.source === 'huggingface_hub' && !m.pulled_from_hf;
    const releaseDateText = m.release_date_str || m.release_date || 'Recent';

    const borderCol = isAct
      ? 'rgba(52,211,153,0.65)'
      : hasWarn
        ? (isCritical ? 'rgba(239,68,68,0.62)' : 'rgba(245,158,11,0.62)')
        : isRec
          ? 'rgba(56,189,248,0.45)'
          : 'rgba(255,255,255,0.09)';
    const bgCol = isAct
      ? 'rgba(16,185,129,0.09)'
      : hasWarn
        ? (isCritical ? 'rgba(239,68,68,0.07)' : 'rgba(245,158,11,0.07)')
        : isRec
          ? 'rgba(14,165,233,0.07)'
          : 'rgba(255,255,255,0.025)';
    const badgeBg = hasWarn
      ? (isCritical ? 'rgba(239,68,68,0.22)' : 'rgba(245,158,11,0.22)')
      : isRec
        ? 'rgba(56,189,248,0.18)'
        : 'rgba(16,185,129,0.15)';
    const badgeColor = hasWarn
      ? (isCritical ? '#fca5a5' : '#fcd34d')
      : isRec
        ? '#38bdf8'
        : '#6ee7b7';
    const warningText = m.warning_message || m.fit_reason || 'Warning: This model exceeds your NAS hardware memory/VRAM capacity.';

    return `
      <div class="ai-llm-rec-card ${hasWarn ? 'ai-llm-hw-warning' : 'ai-llm-hw-ok'}" data-model-id="${escapeHtml(m.id)}" data-hf-repo="${escapeHtml(hfRepo)}" data-recommended="${isRec ? '1' : '0'}" data-active="${isAct ? '1' : '0'}" data-fits-hardware="${hasWarn ? '0' : '1'}" data-hardware-warning="${hasWarn ? '1' : '0'}" style="background:${bgCol}; border:1px solid ${borderCol}; border-radius:9px; padding:10px 12px; display:flex; flex-direction:column; gap:6px;">
        <div style="display:flex; flex-direction:column; gap:4px;">
          <div style="font-weight:800; font-size:12.5px; color:#fff; word-break:break-word; line-height:1.35;" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</div>
          <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; flex-wrap:wrap;">
            <div style="font-size:11px; color:var(--muted,#94a3b8); display:flex; align-items:center; gap:5px; flex-wrap:wrap;">
              <span>${escapeHtml(m.family || m.category || 'Hugging Face')} • ${escapeHtml(m.params || '')} • ${escapeHtml(m.quantization || '')}</span>
              ${hfRepo ? `<a href="${escapeHtml(hfUrl)}" target="_blank" rel="noopener noreferrer" style="color:#fde047; text-decoration:none; font-family:monospace; font-size:11px;" title="View on https://huggingface.co">🤗 ${escapeHtml(hfRepo)} ↗</a>` : ''}
            </div>
            <span class="ai-model-fit-badge" style="font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px; background:${badgeBg}; color:${badgeColor}; white-space:nowrap; display:inline-flex; align-items:center; gap:3px;">
              ${escapeHtml(m.fit_badge || (hasWarn ? "⚠️ Doesn't Fit Hardware" : (isRec ? '★ Recommended' : '✓ Fits Hardware')))}
            </span>
          </div>
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:5px; font-size:11px;">
          <span style="padding:1px 6px; border-radius:4px; background:rgba(0,0,0,0.3); color:${hasWarn ? '#fca5a5' : '#6ee7b7'};">⚡ ${escapeHtml(m.target_device || 'NPU / GPU')}</span>
          <span style="padding:1px 6px; border-radius:4px; background:rgba(0,0,0,0.3); color:${hasWarn ? '#fdba74' : '#bae6fd'};">💾 ~${m.vram_or_ram_gb ?? m.est_ram_gb ?? 2.0} GB Model${m.min_ram_gb ? ` (${m.min_ram_gb}GB+ Host)` : ''}</span>
          <span style="padding:1px 6px; border-radius:4px; background:rgba(0,0,0,0.3); color:#f8fafc;" title="Hugging Face Release Date: ${escapeHtml(releaseDateText)}">📅 ${escapeHtml(releaseDateText)}</span>
          <span style="padding:1px 6px; border-radius:4px; background:rgba(0,0,0,0.3); color:#fde68a;">🚀 ${escapeHtml(m.estimated_speed || '')}</span>
        </div>
        ${hasWarn ? `
          <div class="ai-model-hw-warning-banner" style="padding:6px 8px; border-radius:6px; background:${isCritical ? 'rgba(239,68,68,0.16)' : 'rgba(245,158,11,0.15)'}; border:1px solid ${isCritical ? 'rgba(248,113,113,0.45)' : 'rgba(251,191,36,0.45)'}; color:${isCritical ? '#fecaca' : '#fef08a'}; font-size:11px; line-height:1.35; display:flex; align-items:flex-start; gap:6px;">
            <span style="font-size:12px; line-height:1; flex-shrink:0;">⚠️</span>
            <span>${escapeHtml(warningText)}</span>
          </div>
        ` : `
          <div style="font-size:11px; color:#cbd5e1; line-height:1.35; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;" title="${escapeHtml(m.why_recommended || m.use_case || '')}">
            ${escapeHtml(m.use_case || '')}${m.why_recommended ? ` — ${escapeHtml(m.why_recommended)}` : ''}
          </div>
        `}
        <div style="margin-top:auto; padding-top:5px; border-top:1px solid rgba(255,255,255,0.06); display:flex; justify-content:space-between; align-items:center; gap:6px;">
          <span style="font-size:11px; color:#94a3b8;">🔋 ${escapeHtml(m.power_profile || 'Low Power')} • 📅 ${escapeHtml(releaseDateText)}</span>
          <div style="display:flex; align-items:center; gap:5px;">
            ${isAct
              ? `<span style="font-size:11px; font-weight:800; color:${hasWarn ? '#fbbf24' : '#34d399'}; padding:2px 8px; border-radius:6px; background:${hasWarn ? 'rgba(245,158,11,0.18)' : 'rgba(16,185,129,0.18)'}; border:1px solid ${hasWarn ? 'rgba(245,158,11,0.45)' : 'rgba(16,185,129,0.4)'};">${hasWarn ? '⚠️ Active (Exceeds HW)' : '✓ Active'}</span>`
              : (m.installed === false && m.ollama_tag && m.ollama_tag !== 'builtin-npu')
                ? `<button type="button" class="btn-pill-toggle btn-ai-install-model" data-model-id="${escapeHtml(m.id)}" data-model-tag="${escapeHtml(m.ollama_tag)}" title="${escapeHtml(t('ai.install_model_title', 'Download this model into Ollama'))}" style="font-size:11px; font-weight:700; padding:2px 9px; background:rgba(250,204,21,0.18); border:1px solid rgba(250,204,21,0.48); color:#fde047; cursor:pointer;">⬇️ ${escapeHtml(t('ai.install_model', 'Install'))}</button>`
              : isLiveHfResult
                ? `<button type="button" class="btn-pill-toggle btn-ai-pull-hf-card" data-hf-repo="${escapeHtml(hfRepo)}" style="font-size:11px; font-weight:700; padding:2px 9px; background:${hasWarn ? 'rgba(245,158,11,0.18)' : 'rgba(250,204,21,0.18)'}; border:1px solid ${hasWarn ? 'rgba(245,158,11,0.5)' : 'rgba(250,204,21,0.48)'}; color:${hasWarn ? '#fbbf24' : '#fde047'}; cursor:pointer;">${hasWarn ? '⚠️ Pull Anyway (Unfit)' : '⬇️ Pull from HF'}</button>`
                : `<button type="button" class="btn-pill-toggle btn-ai-activate-model" data-model-id="${escapeHtml(m.id)}" style="font-size:11px; font-weight:700; padding:2px 9px; background:${hasWarn ? 'rgba(245,158,11,0.16)' : 'rgba(14,165,233,0.18)'}; border:1px solid ${hasWarn ? 'rgba(245,158,11,0.45)' : 'rgba(14,165,233,0.45)'}; color:${hasWarn ? '#fbbf24' : '#38bdf8'}; cursor:pointer;">${hasWarn ? '⚠️ Activate Anyway' : '⚡ Activate'}</button>`
            }
            <button type="button" class="btn-pill-toggle btn-ai-remove-model" data-model-id="${escapeHtml(m.id)}" data-model-name="${escapeHtml(m.name)}" title="Remove model from catalog and disk" aria-label="Remove model ${escapeHtml(m.name)}" style="font-size:11px; font-weight:700; padding:2px 7px; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.35); color:#fca5a5; cursor:pointer;">🗑️</button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  gridEl.querySelectorAll('.btn-ai-activate-model').forEach((btn) => {
    btn.addEventListener('click', () => {
      const mId = btn.dataset.modelId;
      if (mId) selectAiRecommendedModel(mId);
    });
  });

  gridEl.querySelectorAll('.btn-ai-install-model').forEach((btn) => {
    btn.addEventListener('click', () => installAiModel(btn.dataset.modelTag, btn, btn.dataset.modelId));
  });

  gridEl.querySelectorAll('.btn-ai-pull-hf-card').forEach((btn) => {
    btn.addEventListener('click', () => {
      const repo = btn.dataset.hfRepo;
      if (repo) pullHuggingFaceModel(repo, true);
    });
  });

  gridEl.querySelectorAll('.btn-ai-remove-model').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const mId = btn.dataset.modelId;
      const mName = btn.dataset.modelName || mId;
      if (!mId) return;
      const confirmTitle = t('ai.remove_model_title', 'Remove Model from Catalog');
      const confirmMsg = t(
        'ai.remove_model_confirm',
        `Are you sure you want to remove model "${mName}" from your ZettAI catalog?`
      ).replace('{name}', mName);
      showConfirmToast(
        confirmTitle,
        confirmMsg,
        async () => {
          await removeAiModel(mId);
        }
      );
    });
  });
}

/** Downloads a model into Ollama and shows progress on the button; then offers Activate (AI-03). */
export async function installAiModel(tag, btn = null, modelId = null, { pollMs = 1000 } = {}) {
  if (!tag) return null;
  const label = (txt) => { if (btn) btn.textContent = txt; };
  try {
    if (btn) btn.disabled = true;
    let job = await api.post('/api/ai/models/install', { model: tag });
    while (job && ['starting', 'downloading', 'verifying'].includes(job.state)) {
      label(job.state === 'verifying' ? t('ai.install_verifying', 'Checking…') : `⬇️ ${Math.floor(job.percent || 0)}%`);
      await new Promise((r) => setTimeout(r, pollMs));
      job = await api.get(`/api/ai/models/install/${encodeURIComponent(job.id)}`);
    }
    if (job?.state === 'done') {
      showToast(t('ai.install_done', '{model} installed.', { model: tag }), 'success');
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('btn-ai-install-model');
        btn.textContent = `⚡ ${t('ai.activate', 'Activate')}`;
        btn.onclick = () => selectAiRecommendedModel(modelId || tag);
      }
    } else {
      throw new Error(job?.error || job?.status || 'Install failed');
    }
    return job;
  } catch (err) {
    showToast(t('toast.ai_install_failed', 'Could not install model: {error}', { error: err.message }), 'error');
    if (btn) { btn.disabled = false; label(`⬇️ ${t('ai.install_model', 'Install')}`); }
    return null;
  }
}

export async function removeAiModel(modelId) {
  const cleanId = String(modelId || '').trim();
  if (!cleanId) return null;
  try {
    let res = null;
    try {
      res = await api.post('/api/media/models/remove', { model: cleanId, model_id: cleanId });
    } catch (postErr) {
      try {
        res = await api.post('/api/ai/models/remove', { model: cleanId, model_id: cleanId });
      } catch {
        res = await api.delete(`/api/media/models/${encodeURIComponent(cleanId)}`);
      }
    }
    if (res) {
      const recs = res.llm_recommendations || res.recommendations;
      if (recs) {
        renderAiLlmRecommendations(recs, res.active_model);
      }
      showToast(t('ai.model_removed_toast', `Model "${cleanId}" removed from catalog`), 'success');
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_remove_model', 'Failed to remove model: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function selectAiRecommendedModel(modelId) {
  const cleanId = String(modelId || '').trim();
  if (!cleanId) return null;
  try {
    const res = await api.post('/api/media/models/select', { model: cleanId, model_id: cleanId });
    if (res) {
      const recs = res.llm_recommendations || res.recommendations;
      if (recs) {
        renderAiLlmRecommendations(recs, res.active_model || cleanId);
      }
      if (res.hardware_warning && res.warning_message) {
        showToast(t('toast.message_2', '⚠️ {warning_message}', { warning_message: res.warning_message }), 'warn');
      } else {
        showToast(t('ai.model_selected_toast', 'Active ZettAI model switched to {model}', { model: cleanId }), 'success');
      }
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_select_model', 'Failed to select model: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function searchHuggingFaceModels(query = '') {
  const statusEl = document.getElementById('ai-hf-search-status');
  const resetBtn = document.getElementById('btn-ai-hf-reset');
  const cleanQ = String(query || '').trim();
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.textContent = `🤗 Searching https://huggingface.co release models${cleanQ ? ` for "${cleanQ}"` : ''}...`;
  }
  try {
    const res = await api.get(`/api/media/models/huggingface/search?q=${encodeURIComponent(cleanQ)}&limit=18`);
    if (res && Array.isArray(res.models)) {
      const warnCount = res.models.filter((m) => m.fits_hardware === false || m.hardware_warning).length;
      if (statusEl) {
        statusEl.textContent = `🤗 Showing ${res.models.length} Hugging Face release models (${res.models.length - warnCount} fit your hardware, ${warnCount} flagged with hardware warning).`;
      }
      if (resetBtn) {
        resetBtn.style.display = 'inline-block';
      }
      renderAiLlmRecommendations(
        {
          headline: _aiLastLlmRecommendations?.headline || 'Hugging Face Hub Search',
          hardware_summary: _aiLastLlmRecommendations?.hardware_summary || '',
          active_model: _aiLastActiveModel,
          models: res.models,
        },
        _aiLastActiveModel
      );
    }
    return res;
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = `⚠️ Hugging Face Hub search error: ${err.message}`;
    }
    showToast(t('toast.hugging_face_search_failed', 'Hugging Face search failed: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function pullHuggingFaceModel(repoId, activate = true) {
  const cleanRepo = String(repoId || '').trim();
  if (!cleanRepo) {
    showToast(t('toast.enter_a_hugging_face_model_repo', 'Enter a Hugging Face model repo or URL (e.g. Qwen/Qwen2.5-7B-Instruct-GGUF)'), 'warn');
    return null;
  }
  const statusEl = document.getElementById('ai-hf-search-status');
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.textContent = `⬇️ Pulling release model metadata from https://huggingface.co/${cleanRepo.replace(/^https?:\/\/huggingface\.co\//i, '')}...`;
  }
  try {
    const res = await api.post('/api/media/models/huggingface/pull', {
      repo_id: cleanRepo,
      activate: Boolean(activate),
    });
    if (res) {
      if (res.llm_recommendations) {
        renderAiLlmRecommendations(res.llm_recommendations, res.active_model || res.model?.id);
      }
      if (res.hardware_warning && res.warning_message) {
        if (statusEl) {
          statusEl.textContent = `⚠️ Pulled ${res.model?.hf_repo || cleanRepo} — ${res.warning_message}`;
        }
        showToast(t('toast.hf_pulled_warning', '⚠️ Added {model}: {warning}', { model: res.model?.name || cleanRepo, warning: res.warning_message }), 'warn');
      } else {
        if (statusEl) {
          statusEl.textContent = `✅ Pulled ${res.model?.hf_repo || cleanRepo} from Hugging Face (Fits your hardware).`;
        }
        showToast(t('toast.hf_pulled', '🤗 Added and selected {model} from Hugging Face', { model: res.model?.name || cleanRepo }), 'success');
      }
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = `⚠️ Failed to pull from Hugging Face: ${err.message}`;
    }
    showToast(t('toast.failed_to_pull_model_from_hugging', 'Failed to pull model from Hugging Face: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function updateAiServiceConfig(partialConfig = {}) {
  try {
    const res = await api.put('/api/media/config', partialConfig);
    await fetchAndRenderAiStatus();
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_update_zettai_configuration', 'Failed to update ZettAI configuration: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function openAiLearningResults() {
  const panel = document.getElementById('ai-learning-results-panel');
  const indexTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-ai-index"]');
  if (indexTab && !indexTab.classList.contains('active')) {
    indexTab.click();
  }
  if (panel) {
    panel.style.display = 'block';
  }
  try {
    const res = await api.get('/api/media/learning/results');
    if (res) {
      renderAiLearningResultsData(res);
    }
    return res;
  } catch (err) {
    return null;
  }
}

export function renderAiLearningResultsData(data = {}) {
  const succEl = document.getElementById('ai-learn-succeeded-count');
  const failEl = document.getElementById('ai-learn-failed-count');
  const defEl = document.getElementById('ai-learn-deferred-count');
  const listEl = document.getElementById('ai-learn-failed-list');

  if (succEl) succEl.textContent = String(data.succeeded_count ?? 0);
  if (failEl) failEl.textContent = String(data.failed_count ?? 0);
  if (defEl) defEl.textContent = String(data.deferred_standby_count ?? 0);

  if (listEl) {
    const failedFiles = Array.isArray(data.failed_files) ? data.failed_files : [];
    if (failedFiles.length === 0) {
      listEl.innerHTML = `<div style="padding:8px 10px; border-radius:6px; background:rgba(34,197,94,0.08); color:#86efac;">✓ All learned files succeeded with 0 errors.</div>`;
    } else {
      listEl.innerHTML = failedFiles.map((f) => `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,0.06);">
          <span style="font-family:monospace; color:#fca5a5;">${escapeHtml(f.file_path || f.file_name || '')}</span>
          <span style="color:#94a3b8; font-size:11px;">${escapeHtml(f.error || 'Failed to parse')}</span>
        </div>
      `).join('');
    }
  }
}

export async function relearnAiFailedFiles() {
  try {
    const res = await api.post('/api/media/learning/relearn-failed', {});
    if (res) {
      showToast(t('toast.relearned', 'Relearned {count} file(s) ({remaining} remaining).', { count: res.relearned ?? 0, remaining: res.still_failed ?? 0 }), 'success');
      await openAiLearningResults();
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    showToast(t('toast.relearn_failed', 'Relearn failed: {error}', { error: err.message }), 'error');
    return null;
  }
}

export function updateAiSyncProgressUi(syncProg = {}, standbyGuard = {}, zettaiStatus = '') {
  const state = String(syncProg.state || 'idle').toLowerCase();
  const isRunning = state === 'running' || Boolean(syncProg.is_scanning);
  const isPaused = state === 'paused' || Boolean(syncProg.is_paused);
  const isStopped = state === 'stopped';
  const isDisabled = String(zettaiStatus || '').toLowerCase() === 'disabled' || syncProg.enabled === false;
  const isComplete = !isRunning && !isPaused && !isStopped && !isDisabled && (
    state === 'completed' ||
    Number(syncProg.indexed_files || 0) > 0 ||
    Number(syncProg.skipped_unchanged || 0) > 0 ||
    String(syncProg.last_message || '').toLowerCase().includes('synced') ||
    String(syncProg.last_message || '').toLowerCase().includes('complete')
  );

  const stateBadge = document.getElementById('ai-sync-state-badge');
  const stateDot = document.getElementById('ai-sync-state-dot');
  const stateText = document.getElementById('ai-sync-state-text');
  if (stateDot && stateText && stateBadge) {
    if (isDisabled) {
      stateDot.style.background = '#64748b';
      stateText.textContent = t('ai.sync_state_disabled', 'Status: Disabled');
      stateBadge.style.borderColor = 'rgba(100,116,139,0.4)';
      stateBadge.style.color = '#94a3b8';
    } else if (isPaused) {
      stateDot.style.background = '#fbbf24';
      stateText.textContent = t('ai.sync_state_paused', 'Sync: Paused');
      stateBadge.style.borderColor = 'rgba(245,158,11,0.45)';
      stateBadge.style.color = '#fde68a';
    } else if (isRunning) {
      stateDot.style.background = '#34d399';
      stateText.textContent = t('ai.sync_state_running', 'Sync: Learning');
      stateBadge.style.borderColor = 'rgba(52,211,153,0.45)';
      stateBadge.style.color = '#6ee7b7';
    } else if (isStopped) {
      stateDot.style.background = '#f87171';
      stateText.textContent = t('ai.sync_state_stopped', 'Sync: Stopped');
      stateBadge.style.borderColor = 'rgba(248,113,113,0.45)';
      stateBadge.style.color = '#fca5a5';
    } else if (isComplete) {
      stateDot.style.background = '#10b981';
      stateText.textContent = t('ai.sync_state_complete', 'Sync: Complete (Up to Date)');
      stateBadge.style.borderColor = 'rgba(16,185,129,0.45)';
      stateBadge.style.color = '#6ee7b7';
    } else {
      stateDot.style.background = '#94a3b8';
      stateText.textContent = t('ai.sync_state_idle', 'Sync: Idle');
      stateBadge.style.borderColor = 'rgba(148,163,184,0.28)';
      stateBadge.style.color = '#cbd5e1';
    }
  }

  // Ribbon transport buttons
  const ribPause = document.getElementById('btn-ai-sync-pause');
  const ribResume = document.getElementById('btn-ai-sync-resume');
  const ribStop = document.getElementById('btn-ai-sync-stop');
  if (ribPause) ribPause.style.display = (isRunning && !isPaused) ? 'inline-flex' : 'none';
  if (ribResume) ribResume.style.display = isPaused ? 'inline-flex' : 'none';
  if (ribStop) ribStop.style.display = (isRunning || isPaused) ? 'inline-flex' : 'none';

  // Indexer pane transport buttons
  const idxPause = document.getElementById('btn-ai-index-pause');
  const idxResume = document.getElementById('btn-ai-index-resume');
  const idxStop = document.getElementById('btn-ai-index-stop');
  if (idxPause) {
    idxPause.disabled = !(isRunning && !isPaused);
    idxPause.style.opacity = (isRunning && !isPaused) ? '1' : '0.45';
  }
  if (idxResume) {
    idxResume.disabled = !isPaused;
    idxResume.style.opacity = isPaused ? '1' : '0.45';
  }
  if (idxStop) {
    idxStop.disabled = !(isRunning || isPaused);
    idxStop.style.opacity = (isRunning || isPaused) ? '1' : '0.45';
  }

  // Progress banner
  const statePill = document.getElementById('ai-index-sync-state-pill');
  if (statePill) {
    const pillLabel = isDisabled
      ? 'DISABLED'
      : isPaused
        ? 'PAUSED'
        : isRunning
          ? 'LEARNING'
          : isStopped
            ? 'STOPPED'
            : isComplete
              ? 'COMPLETE'
              : (zettaiStatus ? String(zettaiStatus).toUpperCase() : 'IDLE');
    statePill.textContent = pillLabel;
    statePill.style.background = isPaused
      ? 'rgba(245,158,11,0.22)'
      : isRunning
        ? 'rgba(37,194,160,0.22)'
        : isStopped
          ? 'rgba(239,68,68,0.22)'
          : isComplete
            ? 'rgba(16,185,129,0.22)'
            : 'rgba(148,163,184,0.18)';
    statePill.style.color = isPaused ? '#fbbf24' : isRunning ? '#34d399' : isStopped ? '#f87171' : isComplete ? '#34d399' : '#e2e8f0';
  }

  const curPathEl = document.getElementById('ai-index-current-path');
  if (curPathEl) {
    let msg = syncProg.last_message || syncProg.current_path || 'Ready — Waiting for sync command (Sleeping drives protected)';
    if (syncProg.updated_at && (!syncProg.state || syncProg.state === 'idle' || syncProg.state === 'completed')) {
      try {
        const timeStr = formatTime(syncProg.updated_at, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        if (!msg.includes('Finished at') && !msg.includes('Completed at')) {
          msg += ` (Finished at ${timeStr})`;
        }
      } catch (_) {}
    }
    curPathEl.textContent = msg;
  }

  const progIdx = document.getElementById('ai-prog-indexed');
  const progUnch = document.getElementById('ai-prog-unchanged');
  const progDef = document.getElementById('ai-prog-deferred');
  if (progIdx) progIdx.textContent = String(syncProg.indexed_files ?? 0);
  if (progUnch) progUnch.textContent = String(syncProg.skipped_unchanged ?? 0);
  if (progDef) progDef.textContent = String(syncProg.deferred_standby ?? 0);

  const guardText = document.getElementById('ai-standby-guard-text');
  const guardBadge = document.getElementById('ai-standby-guard-badge');
  if (guardText && standbyGuard) {
    const sleepCnt = Number(standbyGuard.sleeping_disks_count || 0);
    const runCnt = Number(standbyGuard.running_disks_count || 0);
    if (sleepCnt > 0 || runCnt > 0) {
      guardText.textContent = `Standby Guard (${runCnt} Active, ${sleepCnt} Sleeping)`;
      if (guardBadge) {
        guardBadge.title = `Standby Guard: Active (0 Wakeups • ${runCnt} Running, ${sleepCnt} Sleeping)`;
      }
    }
  }

  _ensureAiSyncPoll(isRunning || isPaused);
}

export function setAiWatchedFoldersDropdownOpen(forceOpen = null) {
  const menu = document.getElementById('ai-watched-folders-dropdown-menu');
  const btn = document.getElementById('btn-ai-watched-folders-dropdown');
  const caret = document.getElementById('ai-watched-dropdown-caret');
  if (!menu) return false;
  const isCurrentlyOpen = menu.style.display !== 'none';
  const nextOpen = forceOpen !== null ? Boolean(forceOpen) : !isCurrentlyOpen;
  menu.style.display = nextOpen ? 'block' : 'none';
  if (btn) {
    btn.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
    btn.style.borderColor = nextOpen ? 'rgba(56,189,248,0.75)' : 'rgba(56,189,248,0.4)';
  }
  if (caret) {
    caret.textContent = nextOpen ? '▴' : '▾';
  }
  return nextOpen;
}

/** Deletes what the index learned from a folder and stops learning it (AI-20). The server asks to confirm. */
export async function forgetAiFolder(folderPath) {
  try {
    const res = await api.post('/api/ai/index/forget', { path: folderPath });
    _aiWatchedPaths = _aiWatchedPaths.filter((p) => p !== folderPath);
    renderAiWatchedFoldersAndShares();
    const n = res?.removed?.files ?? 0;
    showToast(t('ai.forget_folder_done', "Forgot {count} file(s) from {folder}. It won't be learned again.", { count: n, folder: folderPath }), 'success');
    return res;
  } catch (err) {
    if (err?.error !== 'cancelled') showToast(t('toast.ai_forget_failed', 'Could not forget folder: {error}', { error: err.message }), 'error');
    return null;
  }
}

export function renderAiWatchedFoldersAndShares(watchedPaths = null, availableFolders = null) {
  if (Array.isArray(watchedPaths)) {
    _aiWatchedPaths = watchedPaths;
  }
  if (Array.isArray(availableFolders)) {
    _aiAvailableFolders = availableFolders;
  }

  const folderMap = new Map(_aiAvailableFolders.map((f) => [f.path, f]));
  const mergedFolders = [..._aiAvailableFolders];
  _aiWatchedPaths.forEach((fp) => {
    if (fp && !folderMap.has(fp)) {
      const customEntry = { path: fp, in_standby: false, backing_dev: '' };
      folderMap.set(fp, customEntry);
      mergedFolders.push(customEntry);
    }
  });

  // Update dropdown trigger summary & checked count badge
  const summaryEl = document.getElementById('ai-watched-dropdown-summary');
  const countBadgeEl = document.getElementById('ai-watched-dropdown-count-badge');
  if (summaryEl) {
    summaryEl.textContent = _aiWatchedPaths.length > 0
      ? _aiWatchedPaths.join(', ')
      : 'No folders checked — click to select folders for RAG';
  }
  if (countBadgeEl) {
    countBadgeEl.textContent = `${_aiWatchedPaths.length} Checked`;
  }

  // Render compact checked chips below dropdown
  const watchedContainer = document.getElementById('ai-watched-folders-list');
  if (watchedContainer) {
    watchedContainer.innerHTML = _aiWatchedPaths.map((fp) => {
      const info = folderMap.get(fp);
      const inStandby = Boolean(info?.in_standby);
      const dev = info?.backing_dev || '';
      return `
        <div class="ai-watched-folder-chip" data-folder-path="${escapeHtml(fp)}" style="display:inline-flex; align-items:center; gap:7px; padding:4px 9px; border-radius:8px; background:rgba(14,165,233,0.14); border:1px solid rgba(14,165,233,0.38); font-size:11px; color:#f8fafc;">
          <span>☑</span>
          <span style="font-family:monospace; font-weight:700;">${escapeHtml(fp)}</span>
          <span style="font-size:11px; padding:1px 6px; border-radius:999px; background:${inStandby ? 'rgba(245,158,11,0.18)' : 'rgba(37,194,160,0.18)'}; color:${inStandby ? '#fbbf24' : '#34d399'};">
            ${inStandby ? `💤 Standby${dev ? ` (${escapeHtml(dev)})` : ''}` : `🟢 Running${dev ? ` (${escapeHtml(dev)})` : ''}`}
          </span>
          <button type="button" class="btn-ai-sync-single-folder" data-folder-path="${escapeHtml(fp)}" title="Sync this folder now (Standby Safe)" style="background:transparent; border:none; color:#38bdf8; cursor:pointer; font-size:11px; padding:0 2px;">🔄</button>
          <button type="button" class="btn-ai-remove-watched-folder" data-folder-path="${escapeHtml(fp)}" title="Uncheck folder from RAG watched list" style="background:transparent; border:none; color:#f87171; cursor:pointer; font-size:11px; font-weight:800; padding:0 2px;">✕</button>
          <button type="button" class="btn-ai-forget-folder" data-folder-path="${escapeHtml(fp)}" title="${escapeHtml(t('ai.forget_folder_title', 'Forget: delete everything the AI learned from this folder'))}" aria-label="${escapeHtml(t('ai.forget_folder_title', 'Forget: delete everything the AI learned from this folder'))}" style="background:transparent; border:none; color:#fca5a5; cursor:pointer; font-size:11px; padding:0 2px;">🗑</button>
        </div>
      `;
    }).join('');

    watchedContainer.querySelectorAll('.btn-ai-sync-single-folder').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fp = btn.dataset.folderPath;
        const respectCb = document.getElementById('ai-index-respect-standby') || document.getElementById('ai-respect-standby-cb');
        if (fp) {
          const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
          if (pathIn) pathIn.value = fp;
          runAiPathIndex(fp, respectCb ? Boolean(respectCb.checked) : true);
        }
      });
    });

    watchedContainer.querySelectorAll('.btn-ai-forget-folder').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fp = btn.dataset.folderPath;
        if (fp) forgetAiFolder(fp);
      });
    });

    watchedContainer.querySelectorAll('.btn-ai-remove-watched-folder').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fp = btn.dataset.folderPath;
        if (fp) removeAiWatchedFolder(fp);
      });
    });
  }

  // Render dropdown multi-select checklist of all available folders
  const sharesContainer = document.getElementById('ai-discovered-shares-list');
  if (sharesContainer) {
    if (mergedFolders.length === 0) {
      sharesContainer.innerHTML = `<span style="font-size:11px; color:var(--muted); padding:6px 8px;">No NAS folders discovered yet. Use Browse or Add Folder below.</span>`;
    } else {
      sharesContainer.innerHTML = mergedFolders.map((f) => {
        const isWatched = _aiWatchedPaths.includes(f.path);
        const inStandby = Boolean(f.in_standby);
        const dev = f.backing_dev || '';
        return `
          <div role="option" aria-selected="${isWatched ? 'true' : 'false'}" class="btn-pill-toggle ai-discovered-share-pill ai-watched-dropdown-item ${isWatched ? 'active' : ''}" data-folder-path="${escapeHtml(f.path)}" data-watched="${isWatched ? '1' : '0'}" style="display:flex; align-items:center; justify-content:space-between; gap:8px; width:100%; box-sizing:border-box; font-size:11.5px; padding:7px 10px; border-radius:8px; background:${isWatched ? 'rgba(37,194,160,0.16)' : 'rgba(255,255,255,0.03)'}; border:1px solid ${isWatched ? 'rgba(37,194,160,0.48)' : 'rgba(255,255,255,0.08)'}; color:${isWatched ? '#fff' : '#cbd5e1'}; cursor:pointer; text-align:left;" title="${inStandby ? `Backing disk (${dev}) is in STANDBY — will only sync when disk is running` : `Backing disk (${dev || 'NVMe/Pool'}) is RUNNING — click to check/uncheck for RAG`}">
            <div style="display:flex; align-items:center; gap:8px; min-width:0; flex:1;">
              <span class="ai-folder-checkbox-icon" style="display:inline-flex; align-items:center; justify-content:center; width:16px; height:16px; border-radius:4px; background:${isWatched ? '#10b981' : 'rgba(255,255,255,0.08)'}; border:1px solid ${isWatched ? '#34d399' : 'rgba(255,255,255,0.28)'}; color:#042f2e; font-size:11px; font-weight:900; flex-shrink:0;">${isWatched ? '✓' : ''}</span>
              <span>📁</span>
              <span style="font-family:monospace; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(f.path)}</span>
            </div>
            <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
              <span style="font-size:11px; padding:1px 7px; border-radius:999px; background:${inStandby ? 'rgba(245,158,11,0.16)' : 'rgba(37,194,160,0.16)'}; color:${inStandby ? '#fbbf24' : '#34d399'};">
                ${inStandby ? `💤 ${escapeHtml(dev || 'Standby')}` : `🟢 ${escapeHtml(dev || 'Running')}`}
              </span>
              <span style="font-size:11px; font-weight:700; padding:1px 6px; border-radius:6px; background:${isWatched ? 'rgba(16,185,129,0.22)' : 'rgba(255,255,255,0.06)'}; color:${isWatched ? '#6ee7b7' : '#94a3b8'};">
                ${isWatched ? 'RAG Checked' : 'Click to Add'}
              </span>
            </div>
          </div>
        `;
      }).join('');

      sharesContainer.querySelectorAll('.ai-discovered-share-pill').forEach((pill) => {
        pill.addEventListener('click', (e) => {
          e.stopPropagation();
          const fp = pill.dataset.folderPath;
          const isWatched = pill.dataset.watched === '1';
          if (!fp) return;
          if (isWatched) {
            removeAiWatchedFolder(fp);
          } else {
            addAiWatchedFolder(fp);
          }
        });
      });
    }
  }
}

export async function controlAiSync(action) {
  const cleanAction = String(action || '').trim().toLowerCase();
  if (!cleanAction) return null;
  if (cleanAction === 'flush' || cleanAction === 'clear') {
    return flushAiIndex();
  }
  const feedbackEl = document.getElementById('ai-index-run-feedback');
  try {
    const res = await api.post('/api/media/index/control', { action: cleanAction });
    if (res) {
      await fetchAndRenderAiStatus();
      updateAiSyncProgressUi(res.sync_progress || { state: res.sync_state || cleanAction });
      const label = cleanAction === 'pause'
        ? t('ai.sync_paused_toast', 'Indexing sync paused.')
        : cleanAction === 'resume'
          ? t('ai.sync_resumed_toast', 'Indexing sync resumed (standby disks protected).')
          : t('ai.sync_stopped_toast', 'Indexing sync stopped.');
      if (feedbackEl) feedbackEl.textContent = `ℹ️ ${label}`;
      showToast(label, cleanAction === 'stop' ? 'warn' : 'info');
    }
    return res;
  } catch (err) {
    showToast(t('toast.sync_control_failed', 'Sync control ({cleanAction}) failed: {error}', { cleanAction: cleanAction, error: err.message }), 'error');
    return null;
  }
}

export async function flushAiIndex() {
  showConfirmToast(
    t('ai.flush_index_confirm_title', 'Flush RAG Index & Start Fresh?'),
    t(
      'ai.flush_index_confirm_desc',
      'Are you sure you want to flush the existing RAG knowledge base? This will wipe all indexed documents, code files, recipes, photos, vector embeddings, and cached search manifests from rag_index.db so you can perform a clean fresh sync.'
    ),
    async () => {
      const feedbackEl = document.getElementById('ai-index-run-feedback');
      if (feedbackEl) feedbackEl.textContent = '⏳ Flushing RAG index database...';
      showToast(t('toast.flushing_rag_index_database', 'Flushing RAG index database...'), 'info');
      try {
        const res = await api.post('/api/ai/index/flush');
        await fetchAndRenderAiStatus();
        if (feedbackEl) feedbackEl.textContent = '✓ RAG database flushed clean. Ready for fresh sync.';
        showToast(
          t('ai.flush_index_success_toast', 'RAG index database successfully flushed clean. Ready for fresh sync.'),
          'success'
        );
        return res;
      } catch (err) {
        if (feedbackEl) feedbackEl.textContent = `✕ Flush failed: ${err.message}`;
        showToast(t('toast.failed_to_flush_rag_index', 'Failed to flush RAG index: {error}', { error: err.message }), 'error');
        return null;
      }
    },
    null,
    {
      okText: '🗑️ Flush & Reset',
      cancelText: 'Cancel',
      isDanger: true,
    }
  );
}

export async function addAiWatchedFolder(folderPath) {
  const fp = String(folderPath || '').trim();
  if (!fp) {
    showToast(t('ai.enter_folder_path', 'Please enter or browse a folder path to add.'), 'warn');
    return null;
  }
  try {
    const res = await api.post('/api/media/folders', { action: 'add', path: fp });
    if (res) {
      renderAiWatchedFoldersAndShares(res.watched_paths || [], res.available_folders || _aiAvailableFolders);
      if (res.sync_progress) {
        updateAiSyncProgressUi(res.sync_progress);
      }
      const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
      if (pathIn) pathIn.value = fp;
      showToast(t('toast.added_watched_folder', 'Added watched folder: {fp}', { fp: fp }), 'success');
    }
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_add_folder', 'Failed to add folder: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function removeAiWatchedFolder(folderPath) {
  const fp = String(folderPath || '').trim();
  if (!fp) return null;
  try {
    const res = await api.post('/api/media/folders', { action: 'remove', path: fp });
    if (res) {
      renderAiWatchedFoldersAndShares(res.watched_paths || [], res.available_folders || _aiAvailableFolders);
      if (res.sync_progress) {
        updateAiSyncProgressUi(res.sync_progress);
      }
      showToast(t('toast.removed_watched_folder', 'Removed watched folder: {fp}', { fp: fp }), 'info');
    }
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_remove_folder', 'Failed to remove folder: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function syncAiWatchedFolders(respectStandby = true, background = true) {
  const feedbackEl = document.getElementById('ai-index-run-feedback');
  const pathsToSync = Array.isArray(_aiWatchedPaths) && _aiWatchedPaths.length > 0 ? _aiWatchedPaths : ['/mnt/user'];
  if (feedbackEl) {
    feedbackEl.textContent = `⏳ Starting spindown-safe sync across ${pathsToSync.length} watched folder(s)...`;
  }
  try {
    const res = await api.post('/api/media/index', {
      paths: pathsToSync,
      respect_standby: Boolean(respectStandby),
      recursive: true,
      background: Boolean(background),
    });
    if (res) {
      if (res.sync_progress) {
        updateAiSyncProgressUi(res.sync_progress);
      }
      if (res.status === 'started') {
        const msg = `Sync started on ${pathsToSync.join(', ')} (Active disks only — sleeping drives protected).`;
        if (feedbackEl) feedbackEl.textContent = `🔄 ${msg}`;
        showToast(msg, 'info');
        _ensureAiSyncPoll(true);
      } else {
        const indexedCount = res.indexed ?? res.indexed_files ?? 0;
        const skippedCount = res.skipped_unchanged ?? 0;
        const deferredCount = res.deferred_standby ?? 0;
        const msg = deferredCount > 0
          ? `Indexed ${indexedCount} file(s), ${skippedCount} unchanged (${deferredCount} deferred to protect sleeping drives).`
          : `Indexed ${indexedCount} file(s) (${skippedCount} unchanged).`;
        if (feedbackEl) feedbackEl.textContent = `✓ ${msg}`;
        showToast(msg, 'success');
      }
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    if (feedbackEl) feedbackEl.textContent = `⚠️ Sync failed: ${err.message}`;
    showToast(t('toast.sync_failed', 'Sync failed: {error}', { error: err.message }), 'error');
    return null;
  }
}

function _getActiveAiSearchQuery() {
  const visInput = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
  if (visInput && visInput.value.trim()) return visInput.value.trim();
  const askInput = document.getElementById('ai-rag-query-input');
  return askInput ? askInput.value.trim() : '';
}

export function initAiKnowledgeEngine() {
  renderAiSearchHistory();

  const topbarPill = document.getElementById('topbar-ai-accel-pill');
  if (topbarPill && !topbarPill.dataset.bound) {
    topbarPill.dataset.bound = '1';
    topbarPill.addEventListener('click', () => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-index');
      }
    });
  }

  // Collapsible Color & Scene Visual Filters Drawer toggle (#btn-ai-toggle-visual-filters)
  const toggleFiltersBtn = document.getElementById('btn-ai-toggle-visual-filters');
  if (toggleFiltersBtn && !toggleFiltersBtn.dataset.bound) {
    toggleFiltersBtn.dataset.bound = '1';
    toggleFiltersBtn.addEventListener('click', () => {
      setAiVisualFiltersDrawerOpen();
    });
  }

  // ZettAI Master Switch (#ai-master-enable-toggle)
  const masterToggle = document.getElementById('ai-master-enable-toggle');
  if (masterToggle && !masterToggle.dataset.bound) {
    masterToggle.dataset.bound = '1';
    masterToggle.addEventListener('change', async () => {
      const enabled = Boolean(masterToggle.checked);
      await updateAiServiceConfig({ enabled });
      showToast(
        enabled
          ? t('ai.service_enabled_toast', 'ZettAI service enabled — AI learning & search active.')
          : t('ai.service_disabled_toast', 'ZettAI service disabled — unfinished learning tasks paused.'),
        enabled ? 'success' : 'warn'
      );
    });
  }

  // Model Selector (#ai-top-model-select)
  const topModelSelect = document.getElementById('ai-top-model-select');
  if (topModelSelect && !topModelSelect.dataset.bound) {
    topModelSelect.dataset.bound = '1';
    topModelSelect.addEventListener('change', () => {
      if (topModelSelect.value) {
        selectAiRecommendedModel(topModelSelect.value);
      }
    });
  }

  // Hugging Face Hub Search, Pull & Hardware Filter Pills
  const hfSearchInput = document.getElementById('ai-hf-search-input');
  const hfSearchBtn = document.getElementById('btn-ai-hf-search');
  const hfPullBtn = document.getElementById('btn-ai-hf-pull');
  const hfResetBtn = document.getElementById('btn-ai-hf-reset');

  if (hfSearchBtn && !hfSearchBtn.dataset.bound) {
    hfSearchBtn.dataset.bound = '1';
    hfSearchBtn.addEventListener('click', () => {
      searchHuggingFaceModels(hfSearchInput ? hfSearchInput.value : '');
    });
  }
  if (hfPullBtn && !hfPullBtn.dataset.bound) {
    hfPullBtn.dataset.bound = '1';
    hfPullBtn.addEventListener('click', () => {
      pullHuggingFaceModel(hfSearchInput ? hfSearchInput.value : '', true);
    });
  }
  if (hfSearchInput && !hfSearchInput.dataset.bound) {
    hfSearchInput.dataset.bound = '1';
    hfSearchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        searchHuggingFaceModels(hfSearchInput.value);
      }
    });
  }
  if (hfResetBtn && !hfResetBtn.dataset.bound) {
    hfResetBtn.dataset.bound = '1';
    hfResetBtn.addEventListener('click', () => {
      if (hfSearchInput) hfSearchInput.value = '';
      hfResetBtn.style.display = 'none';
      const statusEl = document.getElementById('ai-hf-search-status');
      if (statusEl) statusEl.style.display = 'none';
      _aiActiveHfFilter = 'all';
      fetchAndRenderAiStatus();
    });
  }
  document.querySelectorAll('.ai-hf-filter-btn').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => {
      _aiActiveHfFilter = btn.dataset.hfFilter || 'all';
      if (_aiLastLlmRecommendations) {
        renderAiLlmRecommendations(_aiLastLlmRecommendations, _aiLastActiveModel);
      }
    });
  });

  // Learning Results button (#btn-ai-learning-results), Close & Relearn Failed
  const learnResBtn = document.getElementById('btn-ai-learning-results');
  if (learnResBtn && !learnResBtn.dataset.bound) {
    learnResBtn.dataset.bound = '1';
    learnResBtn.addEventListener('click', () => {
      openAiLearningResults();
    });
  }
  const closeLearnResBtn = document.getElementById('btn-ai-close-learning-results');
  if (closeLearnResBtn && !closeLearnResBtn.dataset.bound) {
    closeLearnResBtn.dataset.bound = '1';
    closeLearnResBtn.addEventListener('click', () => {
      const panel = document.getElementById('ai-learning-results-panel');
      if (panel) panel.style.display = 'none';
    });
  }
  const relearnBtn = document.getElementById('btn-ai-relearn-failed');
  if (relearnBtn && !relearnBtn.dataset.bound) {
    relearnBtn.dataset.bound = '1';
    relearnBtn.addEventListener('click', () => {
      relearnAiFailedFiles();
    });
  }

  // Learning Scope Mode (#ai-learning-scope-mode) & Scheduled Learning Window
  const scopeModeSelect = document.getElementById('ai-learning-scope-mode');
  if (scopeModeSelect && !scopeModeSelect.dataset.bound) {
    scopeModeSelect.dataset.bound = '1';
    scopeModeSelect.addEventListener('change', async () => {
      await updateAiServiceConfig({ scope_mode: scopeModeSelect.value });
      showToast(t('toast.learning_scope_updated', 'Learning scope: {scope}', { scope: scopeModeSelect.options[scopeModeSelect.selectedIndex]?.text || scopeModeSelect.value }), 'info');
    });
  }

  const saveSchedBtn = document.getElementById('btn-ai-save-schedule');
  const schedToggle = document.getElementById('ai-schedule-enabled-toggle');
  const saveScheduleHandler = async () => {
    const schedule_enabled = Boolean(document.getElementById('ai-schedule-enabled-toggle')?.checked);
    const schedule_start = document.getElementById('ai-schedule-start-input')?.value || '01:00';
    const schedule_end = document.getElementById('ai-schedule-end-input')?.value || '06:00';
    await updateAiServiceConfig({ schedule_enabled, schedule_start, schedule_end });
    showToast(
      schedule_enabled
        ? `Scheduled AI learning active (${schedule_start} – ${schedule_end}).`
        : 'Scheduled AI learning window disabled (real-time learning active).',
      'success'
    );
  };
  if (saveSchedBtn && !saveSchedBtn.dataset.bound) {
    saveSchedBtn.dataset.bound = '1';
    saveSchedBtn.addEventListener('click', saveScheduleHandler);
  }
  if (schedToggle && !schedToggle.dataset.bound) {
    schedToggle.dataset.bound = '1';
    schedToggle.addEventListener('change', saveScheduleHandler);
  }

  // Clear Search History (#btn-ai-clear-history)
  const clearHistBtn = document.getElementById('btn-ai-clear-history');
  if (clearHistBtn && !clearHistBtn.dataset.bound) {
    clearHistBtn.dataset.bound = '1';
    clearHistBtn.addEventListener('click', () => {
      _aiSearchHistory = [];
      try { localStorage.removeItem('zettnas_ai_search_history'); } catch (_) {}
      renderAiSearchHistory();
    });
  }

  const refreshBtn = document.getElementById('btn-ai-refresh-status');
  if (refreshBtn && !refreshBtn.dataset.bound) {
    refreshBtn.dataset.bound = '1';
    refreshBtn.addEventListener('click', () => {
      fetchAndRenderAiStatus();
      showToast(t('ai.status_refreshed', 'AI engine telemetry refreshed.'), 'info');
    });
  }

  const syncIndexBtn = document.getElementById('btn-ai-sync-index');
  if (syncIndexBtn && !syncIndexBtn.dataset.bound) {
    syncIndexBtn.dataset.bound = '1';
    syncIndexBtn.addEventListener('click', () => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-index');
      }
    });
  }

  // Quick Sync Active Shares button in ribbon (#btn-ai-quick-sync) & Indexer Sync Watched button (#btn-ai-sync-watched)
  document.querySelectorAll('#btn-ai-quick-sync, #btn-ai-sync-watched').forEach((syncBtn) => {
    if (syncBtn.dataset.bound) return;
    syncBtn.dataset.bound = '1';
    syncBtn.addEventListener('click', async () => {
      const respectCb = document.getElementById('ai-index-respect-standby') || document.getElementById('ai-respect-standby-cb');
      const respect = respectCb ? Boolean(respectCb.checked) : true;
      syncBtn.disabled = true;
      const origHtml = syncBtn.innerHTML;
      syncBtn.innerHTML = '<span>⏳</span> <span>Syncing Shares...</span>';
      try {
        await syncAiWatchedFolders(respect, true);
      } finally {
        syncBtn.disabled = false;
        syncBtn.innerHTML = origHtml;
      }
    });
  });

  // Pause / Resume / Stop Sync buttons (both ribbon and Indexer pane)
  document.querySelectorAll('#btn-ai-sync-pause, #btn-ai-index-pause').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => controlAiSync('pause'));
  });
  document.querySelectorAll('#btn-ai-sync-resume, #btn-ai-index-resume').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => controlAiSync('resume'));
  });
  document.querySelectorAll('#btn-ai-sync-stop, #btn-ai-index-stop').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => controlAiSync('stop'));
  });
  document.querySelectorAll('#btn-ai-flush-index, #btn-ai-flush-index-link').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => flushAiIndex());
  });

  // Watched Folders Multi-Select Dropdown (#btn-ai-watched-folders-dropdown)
  const watchedDropdownBtn = document.getElementById('btn-ai-watched-folders-dropdown');
  if (watchedDropdownBtn && !watchedDropdownBtn.dataset.bound) {
    watchedDropdownBtn.dataset.bound = '1';
    watchedDropdownBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      setAiWatchedFoldersDropdownOpen();
    });
  }
  if (!document.body.dataset.aiWatchedDropdownOutsideBound) {
    document.body.dataset.aiWatchedDropdownOutsideBound = '1';
    document.addEventListener('click', (e) => {
      const container = document.getElementById('ai-watched-folders-dropdown-container');
      const menu = document.getElementById('ai-watched-folders-dropdown-menu');
      if (menu && menu.style.display !== 'none' && container && !container.contains(e.target)) {
        setAiWatchedFoldersDropdownOpen(false);
      }
    });
  }

  // Browse Folder button (#btn-ai-browse-folder)
  const browseBtn = document.getElementById('btn-ai-browse-folder');
  if (browseBtn && !browseBtn.dataset.bound) {
    browseBtn.dataset.bound = '1';
    browseBtn.addEventListener('click', () => {
      const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
      const startPath = (pathIn && pathIn.value.trim()) ? pathIn.value.trim() : '/mnt/user/';
      if (typeof window.openFolderBrowser === 'function') {
        window.openFolderBrowser(startPath, (selectedPath) => {
          const clean = String(selectedPath || '').replace(/\/+$/, '') || '/mnt/user';
          if (pathIn) pathIn.value = clean;
          addAiWatchedFolder(clean);
        });
      }
    });
  }

  // Add Folder to Watched List (#btn-ai-add-watched-folder)
  const addFolderBtn = document.getElementById('btn-ai-add-watched-folder');
  if (addFolderBtn && !addFolderBtn.dataset.bound) {
    addFolderBtn.dataset.bound = '1';
    addFolderBtn.addEventListener('click', () => {
      const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
      if (pathIn && pathIn.value.trim()) {
        addAiWatchedFolder(pathIn.value.trim());
      }
    });
  }

  // Unified Omni-Search & RAG Ask handlers
  const askInput = document.getElementById('ai-rag-query-input');
  const askBtn = document.getElementById('btn-ai-rag-ask');
  const executeUnifiedOmniSearch = (rawQuery) => {
    const q = String(rawQuery || '').trim();
    const visInputEl = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
    if (visInputEl) visInputEl.value = q;
    runAiRagAsk(q, { unifiedMode: true });
    if (document.getElementById('ai-visual-results-grid')) {
      runAiVisualSearch(q);
    }
  };
  if (askBtn && !askBtn.dataset.bound) {
    askBtn.dataset.bound = '1';
    askBtn.addEventListener('click', () => {
      if (askInput) executeUnifiedOmniSearch(askInput.value);
    });
  }
  if (askInput && !askInput.dataset.bound) {
    askInput.dataset.bound = '1';
    askInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        executeUnifiedOmniSearch(askInput.value);
      }
    });
  }

  // Starter / Quick Prompt Chips (.ai-starter-chip and .ai-quick-prompt-chip)
  document.querySelectorAll('.ai-starter-chip, .ai-quick-prompt-chip').forEach((chip) => {
    if (chip.dataset.bound) return;
    chip.dataset.bound = '1';
    chip.addEventListener('click', () => {
      const q = (chip.dataset.query || '').trim();
      const isVisual = chip.dataset.switchVisual === '1' || chip.dataset.mode === 'visual';
      const currentAskIn = document.getElementById('ai-rag-query-input');
      if (currentAskIn) currentAskIn.value = q;
      const visIn = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
      if (visIn) visIn.value = q;
      if (isVisual) {
        const visualTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-ai-visual"]');
        if (visualTab) visualTab.click();
        const answerCard = document.getElementById('ai-rag-answer-card');
        if (answerCard) answerCard.style.display = 'none';
        runAiVisualSearch(q);
      } else {
        executeUnifiedOmniSearch(q);
      }
    });
  });

  // Visual Search Input, Search Button & Clear Button
  const visInput = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
  const visBtn = document.getElementById('btn-ai-visual-search');
  if (visBtn && !visBtn.dataset.bound) {
    visBtn.dataset.bound = '1';
    visBtn.addEventListener('click', () => {
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  }
  if (visInput && !visInput.dataset.bound) {
    visInput.dataset.bound = '1';
    visInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        runAiVisualSearch(visInput.value);
      }
    });
  }

  // File Type Filter Chips (#ai-search-filetype-bar .ai-filetype-chip)
  document.querySelectorAll('#ai-search-filetype-bar .ai-filetype-chip').forEach((chip) => {
    if (chip.dataset.bound) return;
    chip.dataset.bound = '1';
    chip.addEventListener('click', () => {
      _aiSelectedFileType = chip.dataset.filetype || 'all';
      document.querySelectorAll('#ai-search-filetype-bar .ai-filetype-chip').forEach((c) => {
        const isAct = c === chip;
        c.classList.toggle('active', isAct);
        c.style.borderColor = isAct ? '#38bdf8' : '';
      });
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  });

  // Result Matching Mode Tabs (Semantic / Keyword / Audio)
  document.querySelectorAll('#ai-search-match-tabs .ai-match-tab').forEach((tabBtn) => {
    if (tabBtn.dataset.bound) return;
    tabBtn.dataset.bound = '1';
    tabBtn.addEventListener('click', () => {
      _aiSelectedMatchTab = tabBtn.dataset.matchTab || 'semantic';
      document.querySelectorAll('#ai-search-match-tabs .ai-match-tab').forEach((b) => {
        const isAct = b === tabBtn;
        b.classList.toggle('active', isAct);
        b.style.background = isAct ? 'rgba(14,165,233,0.28)' : 'transparent';
        b.style.color = isAct ? '#fff' : '#94a3b8';
      });
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  });

  // Sort Selector (#ai-search-sort-select)
  const sortSelect = document.getElementById('ai-search-sort-select');
  if (sortSelect && !sortSelect.dataset.bound) {
    sortSelect.dataset.bound = '1';
    sortSelect.addEventListener('change', () => {
      _aiSelectedSortBy = sortSelect.value || 'relevance';
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  }

  const visClearBtn = document.getElementById('btn-ai-visual-clear');
  if (visClearBtn && !visClearBtn.dataset.bound) {
    visClearBtn.dataset.bound = '1';
    visClearBtn.addEventListener('click', () => {
      _aiSelectedColor = '';
      _aiSelectedScene = '';
      _aiSelectedFileType = 'all';
      _aiSelectedMatchTab = 'semantic';
      _aiSelectedSortBy = 'relevance';
      const activeVisInput = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
      if (activeVisInput) activeVisInput.value = '';
      const activeAskInput = document.getElementById('ai-rag-query-input');
      if (activeAskInput) activeAskInput.value = '';
      const answerCard = document.getElementById('ai-rag-answer-card');
      if (answerCard) answerCard.style.display = 'none';
      document.querySelectorAll('#ai-color-filter-bar .ai-color-chip, #ai-color-swatch-bar .ai-color-swatch').forEach((s) => {
        s.classList.remove('active');
        s.style.border = '';
        s.style.boxShadow = '';
      });
      document.querySelectorAll('#ai-scene-filter-bar .ai-scene-chip, #ai-scene-pill-bar .ai-scene-pill').forEach((p) => {
        p.classList.remove('active');
        p.style.background = '';
        p.style.borderColor = '';
        p.style.color = '';
      });
      document.querySelectorAll('#ai-search-filetype-bar .ai-filetype-chip').forEach((c) => {
        const isAll = c.dataset.filetype === 'all';
        c.classList.toggle('active', isAll);
        c.style.borderColor = isAll ? '#38bdf8' : '';
      });
      _updateAiVisualFilterBadge();
      const banner = document.getElementById('ai-visual-intent-banner');
      if (banner) banner.style.display = 'none';
      const inspector = document.getElementById('ai-preview-inspector-pane');
      const splitLayout = document.getElementById('ai-search-split-layout');
      if (inspector) inspector.style.display = 'none';
      if (splitLayout) splitLayout.style.gridTemplateColumns = 'minmax(0, 1fr)';
      runAiVisualSearch('');
    });
  }

  // 12-Color Swatch Chips (#ai-color-filter-bar .ai-color-chip and #ai-color-swatch-bar .ai-color-swatch)
  document.querySelectorAll('#ai-color-filter-bar .ai-color-chip, #ai-color-swatch-bar .ai-color-swatch').forEach((swatch) => {
    if (swatch.dataset.bound) return;
    swatch.dataset.bound = '1';
    swatch.addEventListener('click', () => {
      const clickedColor = swatch.dataset.color || '';
      _aiSelectedColor = (_aiSelectedColor === clickedColor && clickedColor !== '') ? '' : clickedColor;
      document.querySelectorAll('#ai-color-filter-bar .ai-color-chip, #ai-color-swatch-bar .ai-color-swatch').forEach((s) => {
        const active = (s.dataset.color || '') === _aiSelectedColor && (_aiSelectedColor !== '' || s === swatch);
        s.classList.toggle('active', active);
        s.style.border = active ? '2px solid #00f0ff' : '';
        s.style.boxShadow = active ? '0 0 8px rgba(0,240,255,0.35)' : '';
      });
      _updateAiVisualFilterBadge();
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  });

  // Scene & Object Filter Pills (#ai-scene-filter-bar .ai-scene-chip and #ai-scene-pill-bar .ai-scene-pill)
  document.querySelectorAll('#ai-scene-filter-bar .ai-scene-chip, #ai-scene-pill-bar .ai-scene-pill').forEach((pill) => {
    if (pill.dataset.bound) return;
    pill.dataset.bound = '1';
    pill.addEventListener('click', () => {
      const clickedScene = pill.dataset.scene || '';
      _aiSelectedScene = (_aiSelectedScene === clickedScene && clickedScene !== '') ? '' : clickedScene;
      document.querySelectorAll('#ai-scene-filter-bar .ai-scene-chip, #ai-scene-pill-bar .ai-scene-pill').forEach((p) => {
        const active = (p.dataset.scene || '') === _aiSelectedScene && (_aiSelectedScene !== '' || p === pill);
        p.classList.toggle('active', active);
        p.style.background = active ? 'rgba(56,189,248,0.22)' : '';
        p.style.borderColor = active ? 'rgba(56,189,248,0.55)' : '';
        p.style.color = active ? '#38bdf8' : '';
      });
      _updateAiVisualFilterBadge();
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  });

  // Index Path Execution (#btn-ai-run-index and #btn-ai-run-index-path)
  document.querySelectorAll('#btn-ai-run-index, #btn-ai-run-index-path').forEach((runIdxBtn) => {
    if (runIdxBtn.dataset.bound) return;
    runIdxBtn.dataset.bound = '1';
    runIdxBtn.addEventListener('click', () => {
      const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
      const respectCb = document.getElementById('ai-index-respect-standby') || document.getElementById('ai-respect-standby-cb');
      const explicitPath = (pathIn && pathIn.value && pathIn.value.trim()) ? pathIn.value.trim() : null;
      runAiPathIndex(
        explicitPath,
        respectCb ? Boolean(respectCb.checked) : true
      );
    });
  });

  // Merged Standby-Safe Auto-Learn checkbox (#ai-index-respect-standby)
  const respectStandbyCb = document.getElementById('ai-index-respect-standby');
  if (respectStandbyCb && !respectStandbyCb.dataset.bound) {
    respectStandbyCb.dataset.bound = '1';
    respectStandbyCb.addEventListener('change', async () => {
      const enabled = Boolean(respectStandbyCb.checked);
      await updateAiServiceConfig({
        respect_standby: enabled,
        auto_learn_on_spinup: enabled,
      });
      showToast(
        enabled
          ? t('ai.auto_learn_spinup_on', '⚡ Standby-Safe Auto-Learn enabled — sleeping drives are protected and automatically sync when they spin up.')
          : t('ai.auto_learn_spinup_off', 'Standby-Safe Auto-Learn disabled.'),
        'info'
      );
    });
  }
  const autoLearnSpinupCb = document.getElementById('ai-auto-learn-spinup');
  if (autoLearnSpinupCb && !autoLearnSpinupCb.dataset.bound) {
    autoLearnSpinupCb.dataset.bound = '1';
    autoLearnSpinupCb.addEventListener('change', async () => {
      const auto_learn_on_spinup = Boolean(autoLearnSpinupCb.checked);
      await updateAiServiceConfig({
        respect_standby: auto_learn_on_spinup,
        auto_learn_on_spinup,
      });
    });
  }

  // Active LLM Pill click -> jumps to AI Chatbot & NAS Copilot tab
  const activeLlmPill = document.getElementById('ai-active-llm-pill');
  if (activeLlmPill && !activeLlmPill.dataset.bound) {
    activeLlmPill.dataset.bound = '1';
    activeLlmPill.style.cursor = 'pointer';
    activeLlmPill.addEventListener('click', () => {
      const chatTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-ai-chat"]');
      if (chatTab) chatTab.click();
    });
  }

  // AI Chatbot & NAS Copilot Controls (#mgmt-pane-ai-chat)
  const chatSendBtn = document.getElementById('btn-ai-chat-send');
  const chatInput = document.getElementById('ai-chat-input');
  const chatClearBtn = document.getElementById('btn-ai-chat-clear');
  const chatStopBtn = document.getElementById('btn-ai-chat-stop');
  if (chatStopBtn && !chatStopBtn.dataset.bound) {
    chatStopBtn.dataset.bound = '1';
    chatStopBtn.addEventListener('click', () => stopAiChatGeneration());
  }
  if (chatSendBtn && !chatSendBtn.dataset.bound) {
    chatSendBtn.dataset.bound = '1';
    chatSendBtn.addEventListener('click', () => {
      sendAiChatMessage(chatInput ? chatInput.value : '');
    });
  }
  if (chatInput && !chatInput.dataset.bound) {
    chatInput.dataset.bound = '1';
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendAiChatMessage(chatInput.value);
      }
    });
  }
    initAiConversationControls();
  if (chatClearBtn && !chatClearBtn.dataset.bound) {
    chatClearBtn.dataset.bound = '1';
    chatClearBtn.addEventListener('click', () => {
      clearAiChatHistory();
    });
  }
  document.querySelectorAll('.ai-chat-starter-chip').forEach((chip) => {
    if (chip.dataset.bound) return;
    chip.dataset.bound = '1';
    chip.addEventListener('click', () => {
      const prompt = (chip.dataset.chatPrompt || '').trim();
      if (prompt) {
        if (chatInput) chatInput.value = prompt;
        sendAiChatMessage(prompt);
      }
    });
  });

  // Initial background status fetch to populate topbar NPU/GPU pill and 3-tier hardware cards
  setTimeout(() => {
    fetchAndRenderAiStatus().catch(() => {});
  }, 300);
}

export async function fetchAndRenderAiStatus() {
  try {
    const res = await api.get('/api/media/status');
    if (!res) return null;

    const hw = res.hardware || res.acceleration || {};
    const stats = res.index_stats || {};
    const cats = res.categories || {};
    const cfg = res.config || {};
    const tierNum = Number(hw.tier_number || hw.active_tier || (hw.has_npu ? 1 : (hw.has_igpu || hw.has_cuda || hw.has_rocm ? 2 : 3)));
    const tierBadge = tierNum === 1 ? 'NPU TIER 1' : tierNum === 2 ? 'GPU TIER 2' : 'CPU TIER 3';
    const tierShort = tierNum === 1 ? 'NPU' : tierNum === 2 ? 'GPU' : 'CPU';
    const hwName = hw.name || hw.device_label || (tierNum === 1 ? 'Intel AI Boost NPU (/dev/accel/accel0)' : tierBadge);
    const totalFiles = stats.total_files ?? res.indexed_count ?? 0;
    const totalVideos = stats.total_videos ?? cats.videos ?? 0;
    const totalDocs = stats.total_docs ?? stats.total_documents ?? cats.documents ?? 0;
    const totalRecipes = stats.total_recipes ?? cats.recipes ?? 0;
    const totalPhotos = stats.total_photos ?? cats.photos ?? 0;
    const totalChunks = stats.total_chunks ?? cats.chunks ?? 0;

    // Sync ZettAI Master Switch & Learning Scope/Schedule inputs
    const masterToggle = document.getElementById('ai-master-enable-toggle');
    if (masterToggle && res.enabled !== undefined) {
      masterToggle.checked = Boolean(res.enabled);
    }
    const scopeModeSelect = document.getElementById('ai-learning-scope-mode');
    if (scopeModeSelect && (res.scope_mode || cfg.scope_mode)) {
      scopeModeSelect.value = res.scope_mode || cfg.scope_mode || 'include';
    }
    const schedToggle = document.getElementById('ai-schedule-enabled-toggle');
    if (schedToggle && cfg.schedule_enabled !== undefined) {
      schedToggle.checked = Boolean(cfg.schedule_enabled);
    }
    const schedStart = document.getElementById('ai-schedule-start-input');
    if (schedStart && cfg.schedule_start) schedStart.value = cfg.schedule_start;
    const schedEnd = document.getElementById('ai-schedule-end-input');
    if (schedEnd && cfg.schedule_end) schedEnd.value = cfg.schedule_end;
    if (typeof window !== 'undefined' && window.initGlassTimePickers) {
      window.initGlassTimePickers(document.getElementById('mgmt-sec-ai') || document);
    }
    const respectCbEl = document.getElementById('ai-index-respect-standby');
    if (respectCbEl && (cfg.respect_standby !== undefined || res.standby_guard?.respect_standby !== undefined)) {
      respectCbEl.checked = Boolean(cfg.respect_standby ?? res.standby_guard?.respect_standby ?? true);
    }
    const autoSpinupCbEl = document.getElementById('ai-auto-learn-spinup');
    if (autoSpinupCbEl && (cfg.auto_learn_on_spinup !== undefined || res.standby_guard?.auto_learn_on_spinup !== undefined)) {
      autoSpinupCbEl.checked = Boolean(cfg.auto_learn_on_spinup ?? res.standby_guard?.auto_learn_on_spinup ?? true);
    }

    const retentionSel = document.getElementById('ai-conversation-retention-select');
    if (retentionSel) {
      retentionSel.value = String(cfg.conversation_retention_days ?? 0);
      if (!retentionSel.dataset.bound) {
        retentionSel.dataset.bound = '1';
        retentionSel.addEventListener('change', async (e) => {
          try {
            await api.post('/api/ai/config', { conversation_retention_days: parseInt(e.target.value, 10) || 0 });
            showToast(t('ai.retention_saved', 'Chat retention saved'), 'success');
          } catch (err) {
            showToast(t('toast.ai_retention_failed', 'Could not save chat retention: {error}', { error: err.message }), 'error');
          }
        });
      }
    }

    // Photo captions (AI-14)
    const visionSel = document.getElementById('ai-vision-captions-select');
    if (visionSel) {
      visionSel.value = cfg.vision_captions === 'off' ? 'off' : 'auto';
      if (!visionSel.dataset.bound) {
        visionSel.dataset.bound = '1';
        visionSel.addEventListener('change', async (e) => {
          try {
            await api.post('/api/ai/config', { vision_captions: e.target.value });
            showToast(t('ai.vision_saved', 'Photo captioning setting saved'), 'success');
            refreshVisionStatus();
          } catch (err) {
            showToast(t('toast.ai_vision_failed', 'Could not save the photo captioning setting: {error}', { error: err.message }), 'error');
          }
        });
      }
      refreshVisionStatus();
    }

    // Hydrate Embedding Model & MRL Dimension selectors
    const embModelSelect = document.getElementById('ai-embedding-model-select');
    if (embModelSelect && (cfg.embedding_model || res.embedding_model)) {
      const embVal = cfg.embedding_model || res.embedding_model || 'embeddinggemma';
      // older installs saved the name "google/embeddinggemma-2" for the same model
      embModelSelect.value = /embeddinggemma/i.test(embVal) ? 'embeddinggemma' : embVal;
    }
    const mrlDimSelect = document.getElementById('ai-mrl-dimension-select');
    if (mrlDimSelect && (cfg.embedding_dim !== undefined || res.embedding_dim !== undefined)) {
      mrlDimSelect.value = String(cfg.embedding_dim ?? res.embedding_dim ?? 768);
    }

    if (embModelSelect && !embModelSelect.dataset.bound) {
      embModelSelect.dataset.bound = '1';
      embModelSelect.addEventListener('change', async (e) => {
        const val = e.target.value;
        try {
          await api.post('/api/ai/config', { embedding_model: val });
          showToast(t('ai.embedding_model_saved', 'Embedding model updated'), 'success');
        } catch (err) {
          showToast(t('toast.failed_update_embedding_model', 'Failed to update embedding model: {error}', { error: err.message }), 'error');
        }
      });
    }

    if (mrlDimSelect && !mrlDimSelect.dataset.bound) {
      mrlDimSelect.dataset.bound = '1';
      mrlDimSelect.addEventListener('change', async (e) => {
        const val = parseInt(e.target.value, 10);
        try {
          await api.post('/api/ai/config', { embedding_dim: val });
          showToast(t('ai.mrl_dim_saved', 'Vector size updated'), 'success');
        } catch (err) {
          showToast(t('toast.failed_update_vector_size', 'Failed to update vector size: {error}', { error: err.message }), 'error');
        }
      });
    }

    const btnBenchmark = document.getElementById('btn-ai-run-benchmark');
    if (btnBenchmark && !btnBenchmark.dataset.bound) {
      btnBenchmark.dataset.bound = '1';
      btnBenchmark.addEventListener('click', async () => {
        btnBenchmark.disabled = true;
        const origHtml = btnBenchmark.innerHTML;
        btnBenchmark.innerHTML = `<span>⏳</span> <span>${t('ai.benchmark_running') || 'Benchmarking Hardware...'}</span>`;
        try {
          const bRes = await api.post('/api/ai/benchmark');
          if (bRes && bRes.status === 'ok') {
            const card = document.getElementById('ai-benchmark-results-card');
            if (card) card.style.display = 'grid';
            const latEl = document.getElementById('bm-latency');
            if (latEl) latEl.textContent = `${bRes.latency_ms} ms`;
            const tpEl = document.getElementById('bm-throughput');
            if (tpEl) tpEl.textContent = `${bRes.throughput_chunks_sec} chunks/s`;
            const tokEl = document.getElementById('bm-tokens');
            if (tokEl) tokEl.textContent = `${bRes.tokens_per_sec} tok/s`;
            const accelEl = document.getElementById('bm-accel');
            if (accelEl) accelEl.textContent = bRes.accelerator || 'CPU';
            showToast(t('toast.ai_benchmark_completed_successfully', 'AI benchmark completed successfully'), 'success');
          }
        } catch (err) {
          showToast(t('toast.benchmark_failed', 'Benchmark failed: {error}', { error: err.message }), 'error');
        } finally {
          btnBenchmark.disabled = false;
          btnBenchmark.innerHTML = origHtml;
        }
      });
    }

    // Bind In-Place Re-index buttons
    const bindReindexBtn = (btnId) => {
      const b = document.getElementById(btnId);
      if (b && !b.dataset.bound) {
        b.dataset.bound = '1';
        b.addEventListener('click', async () => {
          b.disabled = true;
          try {
            await triggerInPlaceReindex();
          } finally {
            setTimeout(() => { b.disabled = false; }, 2000);
          }
        });
      }
    };
    bindReindexBtn('btn-ai-trigger-reindex');
    bindReindexBtn('btn-ai-in-place-reindex');

    // Check if in-place re-index is actively running
    const reindexStatus = res && res.reindex_status;
    if (reindexStatus && reindexStatus.status === 'running') {
      try {
        updateAiReindexProgress(reindexStatus);
        _pollReindexProgress();
      } catch (_) {}
    }

    // Render NPU & GPU LLM Recommendations
    const activeModelId = res.active_model || cfg.llm_model || _aiLastActiveModel || '';
    _aiLastActiveModel = activeModelId;
    const activeLlmLabel = document.getElementById('ai-active-llm-label');
    const activeLlmPill = document.getElementById('ai-active-llm-pill');
    if (activeLlmLabel) {
      activeLlmLabel.textContent = activeModelId || '—';
    }
    if (activeLlmPill) {
      activeLlmPill.title = `Active Local LLM: ${activeModelId} on ${hwName} — Leveraged by RAG Synthesis & NAS Copilot Chatbot`;
    }
    const chatModelBadge = document.getElementById('ai-chat-active-model-badge');
    if (chatModelBadge) {
      chatModelBadge.textContent = activeModelId ? `🤖 ${activeModelId} (${tierShort} Tier ${tierNum})` : '🤖 —';
    }
    if (res.llm_recommendations) {
      renderAiLlmRecommendations(res.llm_recommendations, activeModelId);
    }

    // Render Learning Results if present
    if (res.learning_results) {
      renderAiLearningResultsData(res.learning_results);
    }

    // Topbar Pill (#topbar-ai-accel-text in index.html & #topbar-ai-accel-label in unit tests)
    const topText = document.getElementById('topbar-ai-accel-text');
    const topLabel = document.getElementById('topbar-ai-accel-label');
    const topDot = document.getElementById('topbar-ai-accel-dot');
    const topPill = document.getElementById('topbar-ai-accel-pill');
    const isReindexing = Boolean(reindexStatus && reindexStatus.status === 'running');
    if (topText && !isReindexing) topText.textContent = cfg.respect_standby === false ? tierShort : `${tierShort} • Standby Safe`;
    if (topLabel) topLabel.textContent = `AI: ${tierShort}`;
    if (topDot && !isReindexing) {
      topDot.style.background = tierNum === 1 ? '#3bf58b' : tierNum === 2 ? '#38bdf8' : '#a78bfa';
      topDot.style.boxShadow = tierNum === 1 ? '0 0 6px #3bf58b' : tierNum === 2 ? '0 0 6px #38bdf8' : '0 0 6px #a78bfa';
    }
    if (topPill) {
      topPill.title = `ZettAI Active Accelerator: ${hwName} (NPU → GPU → CPU Priority) • ${totalFiles} Indexed Files`;
    }

    // Sidebar & Hub Badges
    const sideBadge = document.getElementById('mgmt-sidebar-ai-badge');
    if (sideBadge && !isReindexing) sideBadge.textContent = tierShort;
    const hubPill = document.getElementById('mgmt-hub-ai-pill');
    if (hubPill) {
      hubPill.textContent = `${tierBadge} • ${totalFiles} Files`;
    }

    // Section Telemetry Ribbon (#ai-accel-active-label in index.html & #ai-active-tier-pill in tests)
    const activeLabel = document.getElementById('ai-accel-active-label');
    const accelChainPill = document.getElementById('ai-accel-chain-pill');
    if (activeLabel) {
      const compactHwName = String(hwName).replace(/\s*\([^)]*\)/g, '').trim() || tierShort;
      activeLabel.textContent = `Tier ${tierNum}: ${compactHwName}`;
      if (accelChainPill) {
        accelChainPill.title = `Tier ${tierNum}: ${tierShort} Active (${hwName})`;
      }
    }
    const tierPill = document.getElementById('ai-active-tier-pill');
    if (tierPill) {
      tierPill.textContent = `⚡ ${tierBadge}: ${hwName}`;
    }
    const devLabel = document.getElementById('ai-accel-device-label');
    if (devLabel) {
      devLabel.textContent = `${hwName} (${hw.execution_provider || 'OpenVINOExecutionProvider'})`;
    }

    // Stats counters (both index.html and test IDs)
    const statFilesPill = document.getElementById('ai-stat-total-files');
    if (statFilesPill) statFilesPill.textContent = String(totalFiles);
    const statVideos = document.getElementById('ai-stat-total-videos');
    if (statVideos) statVideos.textContent = String(totalVideos);
    const statDocs = document.getElementById('ai-stat-total-docs');
    if (statDocs) statDocs.textContent = String(totalDocs);
    const statRecipes = document.getElementById('ai-stat-total-recipes');
    if (statRecipes) statRecipes.textContent = String(totalRecipes);
    const statRecipesSeg = document.getElementById('ai-stat-recipes-segment');
    if (statRecipesSeg) {
      statRecipesSeg.style.display = totalRecipes > 0 ? 'inline' : 'none';
    }
    const statTotalPhotos = document.getElementById('ai-stat-total-photos');
    if (statTotalPhotos) statTotalPhotos.textContent = String(totalPhotos);

    const statFiles = document.getElementById('ai-stat-files');
    if (statFiles) statFiles.textContent = String(totalFiles);
    const statChunks = document.getElementById('ai-stat-chunks');
    if (statChunks) statChunks.textContent = String(totalChunks);
    const statPhotos = document.getElementById('ai-stat-photos');
    if (statPhotos) statPhotos.textContent = String(totalPhotos);

    // 3-Tier Cards in Indexer Tab (#ai-hw-tier1..3-status in index.html & #ai-tier1..3-status in tests)
    const t1List = [document.getElementById('ai-hw-tier1-status'), document.getElementById('ai-tier1-status')].filter(Boolean);
    const t2List = [document.getElementById('ai-hw-tier2-status'), document.getElementById('ai-tier2-status')].filter(Boolean);
    const t3List = [document.getElementById('ai-hw-tier3-status'), document.getElementById('ai-tier3-status')].filter(Boolean);

    t1List.forEach((t1) => {
      t1.textContent = tierNum === 1
        ? `✓ ACTIVE: ${hwName}`
        : 'Standby / Not Detected — Automatically promoted when /dev/accel/accel0, /dev/rknpu, or /dev/hailo0 is present.';
      t1.style.color = tierNum === 1 ? '#3bf58b' : 'var(--muted)';
    });

    const secGpuLabel = hw.secondary_gpu || (hw.has_igpu ? 'Intel Arc / QuickSync iGPU (/dev/dri/renderD128)' : '');
    t2List.forEach((t2) => {
      t2.textContent = tierNum === 2
        ? `✓ ACTIVE: ${hwName}`
        : tierNum === 1
          ? `✓ Ready as Secondary Fallback${secGpuLabel ? `: ${secGpuLabel}` : ' (Tier 1 NPU currently active)'}`
          : 'Standby / Not Detected — Automatically promoted when /dev/nvidia0 or /dev/dri/renderD128 is present.';
      t2.style.color = (tierNum === 2 || (tierNum === 1 && secGpuLabel)) ? '#38bdf8' : 'var(--muted)';
    });

    t3List.forEach((t3) => {
      const dimFallback = stats.actual_embedding_dim || stats.embedding_dim || 768;
      t3.textContent = tierNum === 3
        ? `✓ ACTIVE: ${hwName} (${hw.execution_provider || 'CPUExecutionProvider'})`
        : `✓ Ready as Universal Fallback (${dimFallback}-d EmbeddingGemma 2 MRL Engine)`;
      t3.style.color = tierNum === 3 ? '#c4b5fd' : 'var(--ok2, #25c2a0)';
    });

    const dbSummary = document.getElementById('ai-index-db-summary');
    if (dbSummary) {
      const sizeKb = stats.db_size_bytes ? (stats.db_size_bytes / 1024).toFixed(1) : '0.0';
      const defItems = res.standby_guard?.deferred_queue || res.sync_progress?.deferred_queue || [];
      const defCount = stats.deferred_queue_count ?? defItems.length ?? 0;
      const defDetail = defItems.length > 0
        ? ` <span style="color:#fbbf24;">(${defItems.map((d) => `${escapeHtml(d.path)}${d.backing_dev ? ` [${escapeHtml(d.backing_dev)}]` : ''}`).join(', ')} — ⚡ auto-learns on spin-up)</span>`
        : (defCount > 0 ? ' <span style="color:#6ee7b7;">(⚡ auto-learns on spin-up)</span>' : '');
      const dimLabel = stats.actual_embedding_dim || stats.embedding_dim || 768;
      const modelRaw = stats.actual_embedding_model || stats.embedding_model || 'EmbeddingGemma 2';
      const modelDisplayName = modelRaw.includes('embeddinggemma') ? 'EmbeddingGemma 2 MRL' : modelRaw;
      const totalVideos = stats.total_videos || 0;
      const videoDetail = totalVideos > 0 ? `, ${totalVideos} videos` : '';
      dbSummary.innerHTML = `
        <div>• <strong>Indexed Files:</strong> ${totalFiles} (${totalDocs} documents/recipes, ${totalPhotos} photos${videoDetail})</div>
        <div>• <strong>Semantic Chunks &amp; Vectors:</strong> ${totalChunks} (${dimLabel}-d ${escapeHtml(modelDisplayName)} + FTS5 BM25)</div>
        <div>• <strong>Deferred Standby Queue:</strong> ${defCount} path(s) waiting for drive wake${defDetail}</div>
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
          <span>• <strong>NVMe Index Footprint:</strong> ${sizeKb} KB (<code>${escapeHtml(stats.db_path || '/app/data/rag_index.db')}</code>)</span>
          ${totalFiles > 0 || totalChunks > 0 ? `<button type="button" id="btn-ai-flush-index-link" class="btn-pill-toggle" style="padding:2px 8px; font-size:11px; font-weight:700; color:#fca5a5; border:1px solid rgba(239,68,68,0.35); background:rgba(239,68,68,0.12); border-radius:6px; cursor:pointer;" title="Flush existing RAG index, vector embeddings, and search catalog to start fresh"><span>🗑️</span> <span>Flush &amp; Start Fresh</span></button>` : ''}
        </div>
      `;
      const flushLink = dbSummary.querySelector('#btn-ai-flush-index-link');
      if (flushLink) {
        flushLink.addEventListener('click', () => flushAiIndex());
      }
    }

    // Update Sync Progress & Transport Controls
    const syncProg = res.sync_progress || stats.sync_progress || {
      state: res.sync_state || (res.is_paused ? 'paused' : (res.is_scanning ? 'running' : 'idle')),
      is_scanning: Boolean(res.is_scanning),
      is_paused: Boolean(res.is_paused),
      enabled: res.enabled,
    };
    updateAiSyncProgressUi(syncProg, res.standby_guard || {}, res.zettai_status || '');

    // Update Watched Folders & Discovered Shares
    const watchedList = res.watched_paths || res.config?.watched_paths || stats.watched_paths || ['/mnt/user'];
    const availFolders = res.available_folders || [];
    renderAiWatchedFoldersAndShares(watchedList, availFolders);

    return res;
  } catch (err) {
    return null;
  }
}

function renderStructuredCardHtml(card) {
  if (!card) return '';
  const cType = card.type || card.card_type || '';
  if (cType === 'recipe') {
    const ings = (card.ingredients || []).slice(0, 12).map((i) => `<li>${escapeHtml(i)}</li>`).join('');
    const steps = (card.steps || card.steps_summary || []).slice(0, 6).map((s) => `<li>${escapeHtml(s)}</li>`).join('');
    return `
      <div class="ai-structured-recipe-card" style="background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.28); border-radius: 10px; padding: 14px; display: flex; flex-direction: column; gap: 10px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 18px;">🍳</span>
            <span style="font-weight: 800; font-size: 13.5px; color: #fff;">${escapeHtml(card.title || 'Structured Recipe Card')}</span>
          </div>
          <div style="display: flex; gap: 6px; font-size: 11px;">
            ${card.prep_time ? `<span style="padding: 2px 8px; border-radius: 999px; background: rgba(0,0,0,0.3); color: #6ee7b7;">⏱ Prep: ${escapeHtml(card.prep_time)}</span>` : ''}
            ${card.cook_time ? `<span style="padding: 2px 8px; border-radius: 999px; background: rgba(0,0,0,0.3); color: #fde68a;">🔥 Cook: ${escapeHtml(card.cook_time)}</span>` : ''}
            ${card.servings ? `<span style="padding: 2px 8px; border-radius: 999px; background: rgba(0,0,0,0.3); color: #bae6fd;">🍽 Serves: ${escapeHtml(card.servings)}</span>` : ''}
          </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; font-size: 11.5px;">
          ${ings ? `<div><div style="font-weight: 700; color: #6ee7b7; margin-bottom: 4px; text-transform: uppercase; font-size: 11px;">Ingredients</div><ul style="margin: 0; padding-left: 16px; color: #e2e8f0; line-height: 1.5;">${ings}</ul></div>` : ''}
          ${steps ? `<div><div style="font-weight: 700; color: #93c5fd; margin-bottom: 4px; text-transform: uppercase; font-size: 11px;">Instructions</div><ol style="margin: 0; padding-left: 16px; color: #e2e8f0; line-height: 1.5;">${steps}</ol></div>` : ''}
        </div>
      </div>
    `;
  }
  return '';
}

export async function runAiRagAsk(rawQuestion, options = {}) {
  const askInput = document.getElementById('ai-rag-query-input');
  const q = (rawQuestion !== undefined && rawQuestion !== null ? String(rawQuestion) : (askInput ? askInput.value : '')).trim();
  if (!q) {
    showToast(t('ai.enter_question', 'Please enter a question or search query.'), 'warn');
    return null;
  }

  _recordAiSearchHistory(q);

  const scopeSelect = document.getElementById('ai-rag-scope-select');
  const scope = scopeSelect ? scopeSelect.value : 'all';

  const outTest = document.getElementById('ai-rag-answer-container');
  const emptyState = document.getElementById('ai-rag-empty-state');
  const answerCard = document.getElementById('ai-rag-answer-card');
  const structuredCardEl = document.getElementById('ai-rag-structured-card');
  const citationsGrid = document.getElementById('ai-rag-citations-grid');
  const askBtn = document.getElementById('btn-ai-rag-ask');
  const hasUnifiedVisualGrid = Boolean(document.getElementById('ai-visual-results-grid'));

  if (askBtn) {
    askBtn.disabled = true;
    askBtn.innerHTML = '<span>⏳</span> <span>Thinking...</span>';
  }
  const loadingHtml = `
    <div style="padding: 16px; text-align: center; color: var(--muted); font-size: 12px;">
      ✨ Searching local vector &amp; FTS5 index (Zero Disk Spindown Wake)...
    </div>
  `;
  if (outTest) outTest.innerHTML = loadingHtml;
  if (emptyState) emptyState.style.display = 'none';
  if (answerCard && !options.unifiedMode) {
    answerCard.style.display = 'block';
    answerCard.innerHTML = loadingHtml;
  }
  if (structuredCardEl) structuredCardEl.style.display = 'none';
  if (citationsGrid) citationsGrid.innerHTML = '';

  try {
    const res = await api.post('/api/media/ask', { query: q, scope, limit: 8 });
    if (!res) return null;

    const citations = res.citations || [];
    const photos = res.photos || res.visual_matches || [];
    const cards = res.structured_cards || (res.structured_card ? [res.structured_card] : []);

    const cardsHtml = cards.map((c) => renderStructuredCardHtml(c)).join('');

    const citationCardsListHtml = citations.map((c, idx) => {
      const cIdx = c.index || c.citation_index || (idx + 1);
      const fPath = c.file_path || c.path || '';
      const fName = c.file_name || c.name || 'Document';
      const secTitle = c.section_title || c.breadcrumb || fPath;
      const cleanExcerpt = String(c.excerpt || '').replace(/\s+/g, ' ').trim();
      return `
        <div class="ai-citation-card" data-path="${escapeHtml(fPath)}" data-name="${escapeHtml(fName)}" data-file-id="${c.file_id}" data-excerpt="${escapeHtml(cleanExcerpt)}" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.09); border-radius: 8px; padding: 10px 12px; cursor: pointer; transition: border-color 0.2s;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">
            <span style="font-weight: 700; font-size: 11.5px; color: #38bdf8;">[${cIdx}] 📄 ${escapeHtml(fName)}</span>
            <span style="font-size: 11px; padding: 1px 6px; border-radius: 4px; background: rgba(16,185,129,0.12); color: #6ee7b7;">💤 Cached</span>
          </div>
          <div style="font-size: 11px; color: var(--muted); font-family: monospace; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(secTitle)}</div>
          <div style="font-size: 11px; color: #cbd5e1; margin-top: 6px; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">
            ${escapeHtml(cleanExcerpt)}
          </div>
        </div>
      `;
    }).join('');

    const citationsHtml = citations.length > 0
      ? `
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: 11px; font-weight: 800; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;">
            Grounded Document Citations (${citations.length})
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px;">
            ${citationCardsListHtml}
          </div>
        </div>
      `
      : '';

    const photosHtml = (photos.length > 0 && !(options.unifiedMode && hasUnifiedVisualGrid))
      ? `
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: 11px; font-weight: 800; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;">
            Matching Visual Assets (${photos.length})
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(175px, 1fr)); gap: 10px;">
            ${photos.map((p) => buildVisualPhotoCardHtml(p)).join('')}
          </div>
        </div>
      `
      : '';

    const rawAnswerLines = String(res.answer || res.answer_markdown || 'No matching grounded context found.')
      .split('\n')
      .map((line) => line.replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    const answerFormatted = escapeHtml(rawAnswerLines.join('\n'))
      .replace(/\[\^(\d+):\s*([^\]]+)\]/g, '<span style="color:#38bdf8; font-weight:700;">[$1]</span> <strong>$2</strong> —')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\[(\d+)\]/g, '<span style="color:#38bdf8; font-weight:700;">[$1]</span>')
      .replace(/\n/g, '<br/>');

    const hwTierLabel = res.hardware?.tier_code || res.hardware?.tier || res.hardware?.active_tier_name || '—';
    const llmTel = res.llm_telemetry || {};
    const activeLlmId = llmTel.active_model || _aiLastActiveModel || '—';
    const tokPerSec = llmTel.tokens_per_sec || null;
    const combinedHtml = `
      <div class="ai-rag-synthesis-box" style="background: rgba(15,23,42,0.65); border: 1px solid rgba(56,189,248,0.28); border-radius: 10px; padding: 12px 15px; display: flex; flex-direction: column; gap: 10px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 15px;">🧠</span>
            <span style="font-weight: 800; font-size: 12.5px; color: #fff;">ZettAI Grounded Synthesis</span>
            <span class="ai-llm-proof-badge" style="font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: rgba(168,85,247,0.16); border: 1px solid rgba(192,132,252,0.45); color: #e9d5ff;" title="${escapeHtml(llmTel.runtime_mode || 'No AI model (built-in tools only)')}">🤖 ${escapeHtml(activeLlmId)}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--muted);">
            <span style="color: #3bf58b; font-weight: 700;">⚡ ${escapeHtml(hwTierLabel)}</span>
            <span>•</span>
            ${tokPerSec ? `<span style="color: #fde68a;">🚀 ${tokPerSec} tok/s</span>` : ''}
            <span>•</span>
            <span>${res.elapsed_ms || llmTel.elapsed_ms || 0} ms</span>
            <span>•</span>
            <span style="color: #6ee7b7;">💤 Standby Safe</span>
            <button type="button" class="btn-ai-dismiss-synthesis btn-pill-toggle" style="font-size: 11px; padding: 2px 7px; margin-left: 4px; cursor: pointer;" title="Hide synthesis card">✕</button>
          </div>
        </div>
        <div style="font-size: 12px; color: #f1f5f9; line-height: 1.55; max-height: 150px; overflow-y: auto;">
          ${answerFormatted}
        </div>
        ${cardsHtml}
        ${citationsHtml}
        ${photosHtml}
      </div>
    `;

    if (outTest) {
      outTest.innerHTML = combinedHtml;
      bindAiResultCardClicks(outTest);
    }
    if (answerCard) {
      const hasRecipeCard = cards.some((c) => (c.type || c.card_type) === 'recipe');
      const hasGroundedDocs = citations.length > 0 || hasRecipeCard;
      const isPhotoModality = res.parsed_intent?.modality_hint === 'photos'
        || _aiSelectedFileType === 'photos'
        || _aiSelectedFileType === 'videos'
        || _aiSelectedFileType === 'folders'
        || Boolean(_aiSelectedColor)
        || Boolean(_aiSelectedScene);
      if (options.unifiedMode && hasUnifiedVisualGrid && (!hasGroundedDocs || (isPhotoModality && !hasRecipeCard))) {
        answerCard.style.display = 'none';
        answerCard.innerHTML = '';
      } else {
        answerCard.style.display = 'block';
        answerCard.innerHTML = combinedHtml;
        bindAiResultCardClicks(answerCard);
        const dismissBtn = answerCard.querySelector('.btn-ai-dismiss-synthesis');
        if (dismissBtn) {
          dismissBtn.addEventListener('click', () => {
            answerCard.style.display = 'none';
          });
        }
      }
    }

    return res;
  } catch (err) {
    const errHtml = `<div style="padding: 16px; color: var(--crit, #ff5c5c); font-size: 12px;">RAG Query Error: ${escapeHtml(err.message || String(err))}</div>`;
    if (outTest) outTest.innerHTML = errHtml;
    if (answerCard && !options.unifiedMode) {
      answerCard.style.display = 'block';
      answerCard.innerHTML = errHtml;
    }
    return null;
  } finally {
    if (askBtn) {
      askBtn.disabled = false;
      askBtn.innerHTML = `<span>✨</span> <span data-i18n="ai.ask_btn">${escapeHtml(t('ai.ask_btn', 'Search & Ask'))}</span>`;
    }
  }
}

function buildVisualPhotoCardHtml(item) {
  const fId = item.file_id || item.id;
  const fPath = item.file_path || item.path || '';
  const fName = item.file_name || item.name || 'File';
  const fCat = item.file_category || 'photos';
  const isPhoto = fCat === 'photos' || (item.mime_type && String(item.mime_type).startsWith('image/'));
  const thumbUrl = item.thumbnail_url || `/api/media/thumbnail/${fId}`;
  const scenes = (item.scene_tags || []).slice(0, 4);
  const colors = (item.object_colors && item.object_colors.length ? item.object_colors : (item.dominant_colors || [])).slice(0, 3);
  const matchReason = item.match_reason || (isPhoto ? 'Visual + Semantic Match' : 'Semantic Match');
  const catIcon = fCat === 'videos' ? '🎬' : fCat === 'audio' ? '🎵' : fCat === 'documents' || fCat === 'recipes' ? '📄' : fCat === 'folders' ? '📁' : '📷';
  const isFav = Boolean(item.is_favorite);

  return `
    <div class="ai-visual-photo-card" data-path="${escapeHtml(fPath)}" data-name="${escapeHtml(fName)}" data-file-id="${fId}" data-category="${escapeHtml(fCat)}" data-favorite="${isFav ? '1' : '0'}" data-excerpt="${escapeHtml(item.excerpt || '')}" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.09); border-radius: 9px; overflow: hidden; cursor: pointer; display: flex; flex-direction: column; transition: transform 0.15s, border-color 0.15s;">
      <div style="height: 125px; background: rgba(0,0,0,0.4); position: relative; display: flex; align-items: center; justify-content: center; overflow: hidden;">
        ${isPhoto
          ? `<img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(fName)}" loading="lazy" style="width: 100%; height: 100%; object-fit: cover;" data-img-fallback="hide" />`
          : `<div style="display:flex; flex-direction:column; align-items:center; gap:6px; padding:10px; text-align:center;">
               <span style="font-size:30px;">${catIcon}</span>
               <span style="font-size:11px; color:#94a3b8; max-height:42px; overflow:hidden;">${escapeHtml((item.excerpt || fPath).slice(0, 75))}</span>
             </div>`
        }
        <span title="${escapeHtml(matchReason)}" style="position: absolute; top: 6px; left: 6px; max-width: calc(100% - 82px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: rgba(15,23,42,0.85); color: #38bdf8;">${catIcon} ${escapeHtml(matchReason)}</span>
        <span style="position: absolute; top: 6px; right: 6px; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: rgba(0,0,0,0.72); color: #6ee7b7; white-space: nowrap;">${isFav ? '⭐ ' : ''}💤 Cached</span>
      </div>
      <div style="padding: 8px 10px; display: flex; flex-direction: column; gap: 4px;">
        <div style="font-weight: 700; font-size: 11.5px; color: #fff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(fName)}">${escapeHtml(fName)}</div>
        <div style="font-size: 11px; color: var(--muted,#94a3b8); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(fPath)}</div>
        <div style="display: flex; flex-wrap: wrap; gap: 4px;">
          ${colors.map((c) => `<span style="font-size: 11px; padding: 1px 5px; border-radius: 4px; background: rgba(56,189,248,0.14); color: #38bdf8; font-weight: 700; text-transform: capitalize;">🎨 ${escapeHtml(c)}</span>`).join('')}
          ${scenes.map((s) => `<span style="font-size: 11px; padding: 1px 5px; border-radius: 4px; background: rgba(255,255,255,0.07); color: #cbd5e1;">#${escapeHtml(s)}</span>`).join('')}
        </div>
      </div>
    </div>
  `;
}

export function renderAiPreviewInspector(item) {
  const pane = document.getElementById('ai-preview-inspector-pane');
  const splitLayout = document.getElementById('ai-search-split-layout');
  if (!pane || !item) return;

  const fId = item.file_id || item.id;
  const fPath = item.file_path || item.path || '';
  const fName = item.file_name || item.name || 'File';
  const fCat = item.file_category || 'photos';
  const isPhoto = fCat === 'photos';
  const thumbUrl = item.thumbnail_url || `/api/media/thumbnail/${fId}`;
  const parentDir = fPath.includes('/') ? (fPath.substring(0, fPath.lastIndexOf('/')) || '/') : '/mnt/user';
  const isFav = Boolean(item.is_favorite);

  pane.style.display = 'block';
  if (splitLayout) {
    splitLayout.style.gridTemplateColumns = 'minmax(0, 1fr) 320px';
  }

  pane.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:10px;">
      <div style="font-weight:800; font-size:12.5px; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(fName)}">
        ${escapeHtml(fName)}
      </div>
      <button type="button" id="btn-ai-inspector-close" class="btn-pill-toggle" style="font-size:11px; padding:2px 7px; cursor:pointer;">✕</button>
    </div>
    ${isPhoto
      ? `<div style="height:170px; border-radius:8px; background:rgba(0,0,0,0.45); overflow:hidden; margin-bottom:10px; display:flex; align-items:center; justify-content:center;">
           <img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(fName)}" style="width:100%; height:100%; object-fit:cover;" data-img-fallback="hide" />
         </div>`
      : ''
    }
    <div style="font-size:11px; color:#cbd5e1; margin-bottom:10px; display:flex; flex-direction:column; gap:4px;">
      <div><strong style="color:#94a3b8;">Location:</strong> <code style="font-size:11px; color:#38bdf8; word-break:break-all;">${escapeHtml(fPath)}</code></div>
      <div><strong style="color:#94a3b8;">Match Mode:</strong> <span style="color:#6ee7b7;">${escapeHtml(item.match_reason || 'Semantic Vector')}</span></div>
      ${item.excerpt ? `<div style="margin-top:4px; padding:8px; border-radius:6px; background:rgba(0,0,0,0.3); font-size:11px; color:#e2e8f0; max-height:90px; overflow-y:auto;">${escapeHtml(item.excerpt)}</div>` : ''}
    </div>
    <!-- 5 Official ZettAI File Actions (#apps/zettai/search) -->
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
      <button type="button" id="btn-ai-inspector-open" class="btn-pill-toggle" style="font-size:11px; padding:6px 8px; font-weight:700; background:rgba(14,165,233,0.22); border:1px solid rgba(14,165,233,0.5); color:#fff; cursor:pointer;">
        👁️ Open File
      </button>
      <button type="button" id="btn-ai-inspector-location" class="btn-pill-toggle" style="font-size:11px; padding:6px 8px; font-weight:700; background:rgba(37,194,160,0.18); border:1px solid rgba(37,194,160,0.45); color:#6ee7b7; cursor:pointer;" title="Open parent folder in File Manager">
        📂 Open Location
      </button>
      <button type="button" id="btn-ai-inspector-download" class="btn-pill-toggle" style="font-size:11px; padding:6px 8px; cursor:pointer;">
        ⬇️ Download
      </button>
      <button type="button" id="btn-ai-inspector-favorite" class="btn-pill-toggle" style="font-size:11px; padding:6px 8px; cursor:pointer; color:${isFav ? '#fbbf24' : '#cbd5e1'};">
        ${isFav ? '⭐ Favorited' : '☆ Favorite'}
      </button>
      <button type="button" id="btn-ai-inspector-share" class="btn-pill-toggle" style="grid-column:1 / -1; font-size:11px; padding:6px 8px; cursor:pointer;">
        🔗 Share File Path / Link
      </button>
    </div>
  `;

  const closeBtn = document.getElementById('btn-ai-inspector-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      pane.style.display = 'none';
      if (splitLayout) splitLayout.style.gridTemplateColumns = 'minmax(0, 1fr)';
    });
  }

  const openBtn = document.getElementById('btn-ai-inspector-open');
  if (openBtn) {
    openBtn.addEventListener('click', () => {
      if (typeof window.openFilePreviewModal === 'function') {
        window.openFilePreviewModal(fPath, fName, {
          standbySafe: true,
          fileId: fId,
          excerpt: item.excerpt || '',
          thumbnailUrl: fId ? `/api/media/thumbnail/${fId}` : null,
        });
      }
    });
  }

  const locBtn = document.getElementById('btn-ai-inspector-location');
  if (locBtn) {
    locBtn.addEventListener('click', () => {
      if (typeof window.openFileManager === 'function') {
        window.openFileManager(parentDir);
      } else {
        ZettEventBus.emit('window:open', { id: 'files', path: parentDir });
      }
      showToast(t('toast.opened_folder_location', 'Opened folder location: {parentDir}', { parentDir: parentDir }), 'info');
    });
  }

  const dlBtn = document.getElementById('btn-ai-inspector-download');
  if (dlBtn) {
    dlBtn.addEventListener('click', () => {
      const a = document.createElement('a');
      a.href = `/api/files/download?path=${encodeURIComponent(fPath)}`;
      a.download = fName;
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
  }

  const favBtn = document.getElementById('btn-ai-inspector-favorite');
  if (favBtn) {
    favBtn.addEventListener('click', async () => {
      try {
        const favRes = await api.post('/api/media/favorites', { file_path: fPath });
        if (favRes) {
          item.is_favorite = Boolean(favRes.is_favorite);
          renderAiPreviewInspector(item);
          showToast(item.is_favorite ? `Added "${fName}" to ZettAI Favorites ⭐` : `Removed "${fName}" from Favorites`, 'success');
        }
      } catch (err) {
        showToast(t('toast.failed_to_toggle_favorite', 'Failed to toggle favorite: {error}', { error: err.message }), 'error');
      }
    });
  }

  const shareBtn = document.getElementById('btn-ai-inspector-share');
  if (shareBtn) {
    shareBtn.addEventListener('click', async () => {
      const shareUrl = `${window.location.origin}/api/files/download?path=${encodeURIComponent(fPath)}`;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(shareUrl);
        }
        showToast(t('toast.copied_share_link_for_to_clipboard', 'Copied share link for {fName} to clipboard!', { fName: fName }), 'success');
      } catch (_) {
        showToast(t('toast.share_path', 'Share path: {fPath}', { fPath: fPath }), 'info');
      }
    });
  }
}

function bindAiResultCardClicks(container) {
  if (!container) return;
  container.querySelectorAll('.ai-citation-card, .ai-visual-photo-card').forEach((card) => {
    if (card.dataset.boundClick) return;
    card.dataset.boundClick = '1';
    card.addEventListener('click', () => {
      const filePath = card.dataset.path;
      const fileName = card.dataset.name;
      const fileId = card.dataset.fileId;
      const excerpt = card.dataset.excerpt;
      const matchedItem = _aiLastResultsList.find((r) => String(r.file_path || r.path) === String(filePath)) || {
        file_id: fileId,
        file_path: filePath,
        file_name: fileName,
        file_category: card.dataset.category || 'photos',
        excerpt,
        is_favorite: card.dataset.favorite === '1',
      };
      // Update split-pane preview inspector if inside the AI Visual/File Search tab
      if (card.closest('#ai-visual-results-grid')) {
        renderAiPreviewInspector(matchedItem);
      }
      if (typeof window.openFilePreviewModal === 'function') {
        window.openFilePreviewModal(filePath, fileName, {
          standbySafe: true,
          fileId,
          excerpt,
          thumbnailUrl: fileId ? `/api/media/thumbnail/${fileId}` : null,
        });
      }
    });
  });
}

function extractCategoryCount(groupObj) {
  if (Array.isArray(groupObj)) return groupObj.length;
  if (groupObj && typeof groupObj === 'object') {
    if (typeof groupObj.count === 'number') return groupObj.count;
    if (Array.isArray(groupObj.items)) return groupObj.items.length;
  }
  return Number(groupObj) || 0;
}

function renderAiCategorySummaryCards(groups = {}) {
  const entries = [
    { key: 'photos', mapGroup: 'images', icon: '📷', label: 'Images', count: extractCategoryCount(groups.images ?? groups.photos) },
    { key: 'videos', mapGroup: 'videos', icon: '🎬', label: 'Videos', count: extractCategoryCount(groups.videos) },
    { key: 'audio', mapGroup: 'audio', icon: '🎵', label: 'Audio', count: extractCategoryCount(groups.audio) },
    { key: 'documents', mapGroup: 'documents', icon: '📄', label: 'Documents', count: extractCategoryCount(groups.documents) },
    { key: 'folders', mapGroup: 'folders', icon: '📁', label: 'Folders', count: extractCategoryCount(groups.folders) },
  ];

  // Update live category counts directly inside the unified #ai-search-filetype-bar chips
  const countByType = new Map(entries.map((e) => [e.key, e]));
  document.querySelectorAll('#ai-search-filetype-bar .ai-filetype-chip').forEach((chip) => {
    const ft = chip.dataset.filetype;
    const entry = countByType.get(ft);
    if (entry) {
      chip.innerHTML = `${entry.icon} ${entry.label} <span style="opacity:0.75; font-size:11px; margin-left:2px;">(${entry.count})</span>`;
    }
  });

  const container = document.getElementById('ai-category-summary-cards');
  if (!container) return;
  // Keep #ai-category-summary-cards hidden in the unified omni-search layout since counts live in the Type pills
  container.style.display = 'none';
  container.innerHTML = '';
}

export function renderAiRagInitialEmptyState() {
  _aiSelectedColor = '';
  _aiSelectedScene = '';
  const grid = document.getElementById('ai-visual-results-grid');
  if (grid) {
    grid.innerHTML = `
      <div class="ai-rag-initial-placeholder" style="grid-column: 1 / -1; text-align: center; padding: 48px 20px; color: var(--muted, #94a3b8);">
        <div style="font-size: 32px; margin-bottom: 10px; opacity: 0.85;">🔍</div>
        <div style="font-size: 14px; font-weight: 600; color: #e2e8f0; margin-bottom: 6px;" data-i18n="ai.search_placeholder_prompt">${escapeHtml(t('ai.search_placeholder_prompt', 'Search Your NAS Knowledge & Media'))}</div>
        <div style="font-size: 12px; color: var(--muted, #94a3b8); max-width: 480px; margin: 0 auto; line-height: 1.5;" data-i18n="ai.search_placeholder_sub">${escapeHtml(t('ai.search_placeholder_sub', 'Type a query above to search documents, recipes, photos, or audio, or ask Zetty a question. Results will appear here once you search.'))}</div>
      </div>
    `;
  }
  const banner = document.getElementById('ai-visual-intent-banner');
  if (banner) banner.style.display = 'none';
  const inspector = document.getElementById('ai-preview-inspector-pane');
  if (inspector) inspector.style.display = 'none';
  const splitLayout = document.getElementById('ai-search-split-layout');
  if (splitLayout) splitLayout.style.gridTemplateColumns = 'minmax(0, 1fr)';
  const answerCard = document.getElementById('ai-rag-answer-card');
  if (answerCard) answerCard.style.display = 'none';
  const structuredCard = document.getElementById('ai-rag-structured-card');
  if (structuredCard) structuredCard.style.display = 'none';
  const citationsGrid = document.getElementById('ai-rag-citations-grid');
  if (citationsGrid) citationsGrid.style.display = 'none';
  _aiLastResultsList = [];
}
export const _renderAiRagInitialEmptyState = renderAiRagInitialEmptyState;

export async function runAiVisualSearch(rawQuery = null) {
  const visInput = document.getElementById('ai-visual-search-input')
    || document.getElementById('ai-visual-query-input')
    || document.getElementById('ai-rag-query-input');
  const q = (rawQuery !== null ? rawQuery : (visInput ? visInput.value : '')).trim();
  const grid = document.getElementById('ai-visual-results-grid');
  if (!grid) return null;

  if (!q && !_aiSelectedColor && !_aiSelectedScene) {
    renderAiRagInitialEmptyState();
    return { status: 'ok', results: [] };
  }

  if (q) _recordAiSearchHistory(q);

  grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 24px; color: var(--muted); font-size: 12px;">🔍 Searching visual &amp; multi-modal index...</div>`;

  const modalityParam = _aiSelectedFileType === 'all' ? 'photo' : _aiSelectedFileType;

  try {
    const res = await api.post('/api/media/search', {
      query: q,
      modality: modalityParam,
      file_type: _aiSelectedFileType || 'all',
      match_tab: _aiSelectedMatchTab || 'semantic',
      sort_by: _aiSelectedSortBy || 'relevance',
      color: _aiSelectedColor || null,
      scene: _aiSelectedScene || null,
      limit: 24,
    });

    if (res?.category_groups) {
      renderAiCategorySummaryCards(res.category_groups);
    }

    const intentBanner = document.getElementById('ai-visual-intent-banner');
    if (intentBanner) {
      const autoColors = res?.parsed_intent?.auto_colors || (_aiSelectedColor ? [_aiSelectedColor] : []);
      const autoScenes = res?.parsed_intent?.auto_scenes || (_aiSelectedScene ? [_aiSelectedScene] : []);
      if (autoColors.length || autoScenes.length || q) {
        intentBanner.style.display = 'block';
        intentBanner.innerHTML = `
          <strong>🧠 Parsed Visual Intent:</strong>
          ${autoColors.length ? `<span style="margin-left:6px; color:#38bdf8;">🎨 Color: <b>${escapeHtml(autoColors.join(', '))}</b></span>` : ''}
          ${autoScenes.length ? `<span style="margin-left:8px; color:#6ee7b7;">🏷️ Scene: <b>${escapeHtml(autoScenes.join(', '))}</b></span>` : ''}
          <span style="margin-left:8px; color:#c7d2fe;">⚡ Mode: <b>${escapeHtml((_aiSelectedMatchTab || 'semantic').toUpperCase())}</b></span>
          <span style="margin-left:8px; color:var(--muted);">• 🛡️💤 Zero Disk Wakeups</span>
        `;
      } else {
        intentBanner.style.display = 'none';
      }
    }

    const results = res?.results || res?.photo_results || res?.items || [];
    _aiLastResultsList = results;
    if (results.length === 0) {
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 28px; color: var(--muted); font-size: 12px;">
          No matching files found for <strong>${escapeHtml(q || _aiSelectedColor || _aiSelectedScene || 'current filter')}</strong>. Click <strong>Sync Shares</strong> above or configure folders in the <em>⚙️ AI Configuration</em> tab.
        </div>
      `;
      return res;
    }

    grid.innerHTML = results.map((item) => buildVisualPhotoCardHtml(item)).join('');
    bindAiResultCardClicks(grid);
    return res;
  } catch (err) {
    grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 20px; color: var(--crit, #ff5c5c); font-size: 12px;">Visual search failed: ${escapeHtml(err.message || String(err))}</div>`;
    return null;
  }
}

export async function runAiPathIndex(targetPath = null, respectStandby = true) {
  const runBtns = [document.getElementById('btn-ai-run-index'), document.getElementById('btn-ai-run-index-path')].filter(Boolean);
  const feedbackEl = document.getElementById('ai-index-run-feedback');
  runBtns.forEach((b) => {
    b.disabled = true;
    b.innerHTML = '<span>⏳</span> <span>Indexing...</span>';
  });

  let targets = [];
  if (Array.isArray(targetPath) && targetPath.length > 0) {
    targets = targetPath.filter(Boolean);
  } else if (typeof targetPath === 'string' && targetPath.trim()) {
    targets = [targetPath.trim()];
  } else if (_aiWatchedPaths && _aiWatchedPaths.length > 0) {
    targets = [..._aiWatchedPaths];
  } else {
    targets = ['/mnt/user'];
  }

  const displayTarget = targets.length === 1 ? targets[0] : `${targets.length} watched folder(s)`;
  if (feedbackEl) {
    feedbackEl.textContent = `⏳ Scanning ${displayTarget} (Spindown-Safe Incremental Indexer)...`;
  }
  try {
    const res = await api.post('/api/media/index', {
      path: targets[0] || '/mnt/user',
      paths: targets,
      respect_standby: Boolean(respectStandby),
      recursive: true,
    });
    if (res) {
      const indexedCount = res.indexed ?? res.indexed_files ?? 0;
      const skippedCount = res.skipped_unchanged ?? 0;
      const deferredCount = res.deferred_standby ?? 0;
      const targetLabel = targets.length === 1 ? (res.path || targets[0]) : `${targets.length} watched folder(s)`;
      const msg = deferredCount > 0
        ? `Indexed ${indexedCount} file(s), ${skippedCount} unchanged (${deferredCount} deferred to protect sleeping drives).`
        : `Indexed ${indexedCount} file(s) (${skippedCount} unchanged) on ${targetLabel}.`;
      if (feedbackEl) {
        feedbackEl.textContent = `✓ ${msg}`;
      }
      showToast(msg, 'success');
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    if (feedbackEl) {
      feedbackEl.textContent = `⚠️ Indexing failed: ${err.message}`;
    }
    showToast(t('toast.indexing_failed', 'Indexing failed: {error}', { error: err.message }), 'error');
    return null;
  } finally {
    runBtns.forEach((b) => {
      b.disabled = false;
      b.innerHTML = `<span>🚀</span> <span data-i18n="ai.run_index_btn">${escapeHtml(t('ai.run_index_btn', 'Index Path Now'))}</span>`;
    });
  }
}


// ZettAI proposes actions that change the system; they run only on this click (AI-01).
let _aiConfirmHandlerBound = false;
function _bindAiConfirmHandler() {
  if (_aiConfirmHandlerBound || typeof document === 'undefined') return;
  _aiConfirmHandlerBound = true;
  document.addEventListener('click', async (e) => {
    const btn = e.target?.closest?.('.ai-chat-confirm-action');
    if (!btn || btn.disabled) return;
    const actionId = btn.dataset.actionId;
    const row = btn.closest('.ai-chat-action-proposal');
    const status = row?.querySelector('.ai-chat-action-status');
    row?.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    if (btn.dataset.decision === 'cancel') {
      if (status) status.textContent = 'Cancelled';
      return;
    }
    if (status) status.textContent = 'Running...';
    try {
      const out = await api.post(`/api/ai/actions/${encodeURIComponent(actionId)}/confirm`, {});
      const ok = out && out.status === 'ok';
      if (status) status.textContent = ok ? `Done: ${out.message || out.summary || 'OK'}` : `Not run: ${out?.error || out?.status || 'unknown error'}`;
      showToast(ok ? `${out.summary || 'Action'} done` : `${out?.summary || 'Action'} failed: ${out?.error || ''}`, ok ? 'success' : 'error');
    } catch (err) {
      if (status) status.textContent = `Not run: ${err.message}`;
      showToast(t('toast.action_failed_2', 'Action failed: {error}', { error: err.message }), 'error');
    }
  });
}

function _buildAiActionProposalsHtml(toolsCalled) {
  const proposals = toolsCalled.filter((tc) => tc && tc.action_id && tc.status === 'confirmation_required');
  if (!proposals.length) return '';
  _bindAiConfirmHandler();
  return proposals.map((tc) => `
      <div class="ai-chat-action-proposal" style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:8px 10px; border-radius:8px; background:rgba(245,158,11,0.10); border:1px solid rgba(251,191,36,0.38);">
        <span style="font-size:12px; font-weight:700; color:#fde68a;">⏸️ ${escapeHtml(tc.action_summary || tc.tool)}</span>
        <button type="button" class="btn ai-chat-confirm-action" data-action-id="${escapeHtml(tc.action_id)}" data-decision="confirm" style="font-size:11px; padding:3px 10px;">Confirm</button>
        <button type="button" class="btn ai-chat-confirm-action" data-action-id="${escapeHtml(tc.action_id)}" data-decision="cancel" style="font-size:11px; padding:3px 10px; opacity:0.8;">Cancel</button>
        <span class="ai-chat-action-status" style="font-size:11px; color:#cbd5e1;"></span>
      </div>`).join('');
}

function _buildAiExternalNoteHtml(res) {
  const ext = Array.isArray(res?.external_services) ? res.external_services : [];
  if (!ext.length) return '';
  return `<div class="ai-chat-external-note" style="font-size:11px; color:#fbbf24; padding-top:2px;" title="This answer used services outside your NAS">🌐 Data left this device: ${escapeHtml(ext.join(', '))}</div>`;
}

// Remember the Web toggle per browser (a convenience; the server default is off).
function _initAiWebToggle() {
  const el = document.getElementById('ai-chat-web-toggle');
  if (!el || el.dataset.bound) return;
  el.dataset.bound = '1';
  try {
    el.checked = localStorage.getItem('zettnas_ai_web') === '1';
  } catch (e) { /* storage blocked */ }
  el.addEventListener('change', () => {
    try {
      localStorage.setItem('zettnas_ai_web', el.checked ? '1' : '0');
    } catch (e) { /* storage blocked */ }
  });
}
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _initAiWebToggle);
  else _initAiWebToggle();
}

function _buildAiAssistantMessageHtml(res, defaultModel) {
  const replyMd = res.reply || res.answer || 'No response generated.';
  const llmTel = res.llm_telemetry || {};
  const toolsCalled = Array.isArray(res.tools_called) ? res.tools_called : [];
  const webSources = Array.isArray(res.web_sources) ? res.web_sources : [];
  const citations = Array.isArray(res.citations) ? res.citations : [];
  const photos = Array.isArray(res.photos) ? res.photos : [];
  const folderPath = res.folder_path || '';
  const folderManifest = res.folder_manifest || null;
  const groundingScore = res.grounding_confidence_score != null ? res.grounding_confidence_score : null;
  const cragGrade = res.crag_grade || '';
  const usedModel = llmTel.active_model || res.active_model || defaultModel;
  const accelLabel = llmTel.accelerator_label || '—';
  const runtimeMode = llmTel.runtime_mode || 'No AI model (built-in tools only)';
  const tokSec = llmTel.tokens_per_sec || null;
  const elapsedMs = res.elapsed_ms || llmTel.elapsed_ms || 0;

  const toolsBadgesHtml = toolsCalled.length > 0
    ? `
      <div class="ai-chat-tools-trace" style="display: flex; flex-wrap: wrap; gap: 5px; padding-top: 2px;">
        ${toolsCalled.map((tc) => {
          const isWeb = tc.tool === 'browse_internet';
          const isRag = tc.tool === 'search_nas_knowledge';
          const isCalc = tc.tool === 'calculate';
          const isStorage = tc.tool === 'get_storage_status';
          const isNet = tc.tool === 'get_network_status';
          const isWeather = tc.tool === 'get_weather';
          const bg = isCalc ? 'rgba(245,158,11,0.16)' : (isWeather ? 'rgba(14,165,233,0.18)' : (isWeb ? 'rgba(56,189,248,0.16)' : (isRag ? 'rgba(168,85,247,0.16)' : (isNet ? 'rgba(14,165,233,0.16)' : 'rgba(16,185,129,0.16)'))));
          const border = isCalc ? 'rgba(251,191,36,0.42)' : (isWeather ? 'rgba(56,189,248,0.45)' : (isWeb ? 'rgba(56,189,248,0.42)' : (isRag ? 'rgba(168,85,247,0.42)' : (isNet ? 'rgba(56,189,248,0.42)' : 'rgba(52,211,153,0.42)'))));
          const color = isCalc ? '#fde68a' : (isWeather ? '#38bdf8' : (isWeb ? '#7dd3fc' : (isRag ? '#d8b4fe' : (isNet ? '#7dd3fc' : '#6ee7b7'))));
          const icon = isCalc ? '🧮' : (isWeather ? '⛅' : (isWeb ? '🌐' : (isRag ? '📁' : (isStorage ? '💽' : (isNet ? '🔌' : '🛠️')))));
          return `<span class="ai-chat-tool-pill" data-tool-name="${escapeHtml(tc.tool)}" style="font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: ${bg}; border: 1px solid ${border}; color: ${color};" title="${escapeHtml(tc.summary || tc.tool)}">${icon} ${escapeHtml(tc.tool)}: ${escapeHtml(tc.summary || 'OK')}</span>`;
        }).join('')}
      </div>
    `
    : '';

  const folderBannerHtml = folderPath
    ? `
      <div class="ai-chat-folder-banner" style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; padding: 6px 10px; border-radius: 8px; background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.28); margin-bottom: 2px;">
        <div style="display: flex; align-items: center; gap: 6px; font-size: 11px;">
          <span>📁</span>
          <span style="font-weight: 700; color: #7dd3fc;">Folder Scope:</span>
          <code style="color: #e0f2fe; font-size: 11px; background: rgba(0,0,0,0.25); padding: 1px 5px; border-radius: 4px;">${escapeHtml(folderPath)}</code>
          ${folderManifest && folderManifest.total_files ? `<span style="font-size: 11px; color: #94a3b8;">(${folderManifest.total_files} files)</span>` : ''}
        </div>
        ${groundingScore !== null ? `
          <div style="display: flex; align-items: center; gap: 5px;">
            <span style="font-size: 11px; font-weight: 800; color: ${groundingScore >= 80 ? '#34d399' : (groundingScore >= 50 ? '#fbbf24' : '#f87171')}; background: ${groundingScore >= 80 ? 'rgba(52,211,153,0.14)' : 'rgba(251,191,36,0.14)'}; border: 1px solid ${groundingScore >= 80 ? 'rgba(52,211,153,0.35)' : 'rgba(251,191,36,0.35)'}; padding: 1px 7px; border-radius: 999px;">
              🎯 ${groundingScore}% Grounded (${escapeHtml(cragGrade.toUpperCase() || 'HIGH')})
            </span>
          </div>
        ` : ''}
      </div>
    `
    : '';

  const docCitationsHtml = citations.length > 0
    ? `
      <details class="ai-chat-doc-citations" style="margin-top: 4px; font-size: 11px;">
        <summary style="cursor: pointer; color: #38bdf8; font-weight: 700; display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; border-radius: 6px; background: rgba(56,189,248,0.12); border: 1px solid rgba(56,189,248,0.32); width: fit-content; user-select: none;">
          <span>📚 Verified Citations (${citations.length})</span>
        </summary>
        <div style="margin-top: 8px; display: flex; flex-direction: column; gap: 6px;">
          ${citations.map((c, idx) => {
            const cname = c.name || (c.path ? c.path.split('/').pop() : 'Document');
            const bcrumb = c.breadcrumb ? ` > ${c.breadcrumb}` : '';
            const scorePct = Math.round(Number(c.score || 0.9) * 100);
            const escPath = escapeHtml(c.path || '');
            const escName = escapeHtml(cname);
            return `
              <div class="ai-citation-card" style="padding: 7px 10px; border-radius: 7px; background: rgba(15,23,42,0.85); border: 1px solid rgba(56,189,248,0.22); font-size: 11px;">
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-bottom: 3px;">
                  <button type="button" class="btn-preview-citation" data-action="open-file-preview" data-path="${escPath}" data-name="${escName}" style="background: none; border: none; padding: 0; color: #38bdf8; font-weight: 700; cursor: pointer; text-decoration: underline; text-align: left; font-size: 11.5px;">
                    📄 [${idx + 1}] ${escName}<span style="color: #94a3b8; font-weight: 400; text-decoration: none;">${escapeHtml(bcrumb)}</span> 👁️
                  </button>
                  <span style="font-size: 11px; color: #a7f3d0; background: rgba(16,185,129,0.14); padding: 1px 6px; border-radius: 999px;">${scorePct}% match</span>
                </div>
                ${c.excerpt ? `<div style="color: #cbd5e1; font-size: 11px; line-height: 1.45; font-style: italic; background: rgba(0,0,0,0.25); padding: 5px 8px; border-radius: 5px; border-left: 2px solid #38bdf8;">"${escapeHtml(c.excerpt)}"</div>` : ''}
              </div>
            `;
          }).join('')}
        </div>
      </details>
    `
    : '';

  const photosHtml = photos.length > 0
    ? `
      <div class="ai-chat-photos-grid" style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px;">
        ${photos.map((p) => {
          const escP = escapeHtml(p.path || '');
          const escN = escapeHtml(p.name || 'Photo');
          const thumb = p.thumbnail_url || (p.file_id ? `/api/media/thumbnail/${p.file_id}` : '');
          return `
            <div class="ai-chat-photo-card" data-action="open-file-preview" data-path="${escP}" data-name="${escN}" style="cursor: pointer; width: 85px; border-radius: 6px; overflow: hidden; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); transition: transform 0.15s ease;" title="${escN}">
              ${thumb ? `<img src="${escapeHtml(thumb)}" alt="${escN}" style="width: 100%; height: 60px; object-fit: cover;" />` : `<div style="height: 60px; display: flex; align-items: center; justify-content: center; font-size: 20px;">🖼️</div>`}
              <div style="font-size: 11px; color: #cbd5e1; padding: 2px 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escN}</div>
            </div>
          `;
        }).join('')}
      </div>
    `
    : '';

  const webSourcesHtml = webSources.length > 0
    ? `
      <details class="ai-chat-web-sources" style="margin-top: 2px; font-size: 11px;">
        <summary style="cursor: pointer; color: #94a3b8; font-weight: 600; display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border-radius: 6px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); width: fit-content; user-select: none;">
          <span>🌐 Sources (${webSources.length})</span>
        </summary>
        <div style="margin-top: 6px; display: flex; flex-wrap: wrap; gap: 5px; padding-left: 2px;">
          ${webSources.slice(0, 5).map((ws) => `<a href="${escapeHtml(ws.url)}" target="_blank" rel="noopener noreferrer" style="padding: 2px 8px; border-radius: 6px; background: rgba(56,189,248,0.12); border: 1px solid rgba(56,189,248,0.32); color: #38bdf8; text-decoration: none; font-weight: 600; font-size: 11px;">${escapeHtml(ws.title || ws.source || 'Source')} ↗</a>`).join('')}
        </div>
      </details>
    `
    : '';

  return `
    <div class="ai-chat-llm-proof-bar" style="display: flex; justify-content: space-between; align-items: center; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 5px;">
      <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
        <span class="ai-chat-model-pill" style="font-size: 11px; font-weight: 800; color: #e9d5ff; padding: 1px 8px; border-radius: 999px; background: rgba(168,85,247,0.18); border: 1px solid rgba(192,132,252,0.45);">🤖 ${escapeHtml(usedModel)}</span>
        <span style="font-size: 11px; font-weight: 700; color: #3bf58b;">⚡ ${escapeHtml(accelLabel)}</span>
        <span style="font-size: 11px; color: #94a3b8;">(${escapeHtml(runtimeMode)})</span>
      </div>
      <div style="display: flex; align-items: center; gap: 6px; font-size: 11px; color: #94a3b8;">
        ${!folderPath && groundingScore !== null ? `<span style="font-size: 11px; font-weight: 700; color: #34d399; padding: 0 5px; border-radius: 999px; background: rgba(52,211,153,0.12); border: 1px solid rgba(52,211,153,0.3);">🎯 ${groundingScore}% Grounded</span><span>•</span>` : ''}
        ${tokSec ? `<span style="color: #fde68a;">🚀 ${tokSec} tok/s</span>` : ''}
        <span>•</span>
        <span>${elapsedMs} ms</span>
      </div>
    </div>
    ${toolsBadgesHtml}
    ${_buildAiExternalNoteHtml(res)}
    ${_buildAiActionProposalsHtml(toolsCalled)}
    ${folderBannerHtml}
    <div class="ai-chat-reply-body" style="font-size: 12px; color: #f1f5f9; line-height: 1.55;">
      ${_formatChatMarkdown(replyMd)}
    </div>
    ${docCitationsHtml}
    ${photosHtml}
    ${webSourcesHtml}
  `;
}

let _activeConversationId = null;
let _activeConversationTitle = 'New Conversation';
let _aiConversations = [];
let _aiActiveAbortController = null;
let _aiActiveRequestId = 0;
let _aiStopRequested = false;

function _groupConversationsChronologically(convs) {
  const now = Date.now();
  const oneDayMs = 24 * 60 * 60 * 1000;
  const groups = {
    pinned: [],
    today: [],
    yesterday: [],
    prev7Days: [],
    older: [],
  };

  convs.forEach((c) => {
    if (c.is_pinned) {
      groups.pinned.push(c);
      return;
    }
    const updatedMs = (c.updated_at || c.created_at || (now / 1000)) * 1000;
    const diffMs = now - updatedMs;
    const diffDays = Math.floor(diffMs / oneDayMs);

    if (diffDays === 0) {
      groups.today.push(c);
    } else if (diffDays === 1) {
      groups.yesterday.push(c);
    } else if (diffDays <= 7) {
      groups.prev7Days.push(c);
    } else {
      groups.older.push(c);
    }
  });

  return groups;
}

export async function fetchAndRenderAiConversations(searchQuery = '') {
  const listContainer = document.getElementById('ai-chat-threads-list');
  const countBadge = document.getElementById('ai-chat-thread-count');
  if (!listContainer) return;

  try {
    const res = await api.get('/api/ai/conversations', searchQuery ? { search: searchQuery } : {});
    const convs = (res && res.conversations) ? res.conversations : [];
    _aiConversations = convs;

    if (countBadge) {
      countBadge.textContent = `${convs.length} ${convs.length === 1 ? 'chat' : 'chats'}`;
    }

    if (convs.length === 0) {
      listContainer.innerHTML = `<div class="ai-empty-threads">${escapeHtml(t('ai.no_chats', 'No conversations yet'))}</div>`;
      return;
    }

    const groups = _groupConversationsChronologically(convs);
    let html = '';

    const renderGroup = (labelKey, defaultLabel, items, icon) => {
      if (!items || items.length === 0) return '';
      let gHtml = `<div class="ai-thread-group-header"><span>${icon}</span> <span>${escapeHtml(t(labelKey, defaultLabel))}</span></div>`;
      items.forEach((c) => {
        const isActive = c.id === _activeConversationId;
        const pinIcon = c.is_pinned ? '📌' : '📍';
        const pinTitle = c.is_pinned ? 'Unpin' : 'Pin';
        gHtml += `
          <div class="ai-thread-item ${isActive ? 'active' : ''}" data-conv-id="${escapeHtml(c.id)}">
            <span class="ai-thread-title-text" title="${escapeHtml(c.title || 'New Conversation')}">${escapeHtml(c.title || 'New Conversation')}</span>
            <div class="ai-thread-actions">
              <button type="button" class="btn-ai-thread-action btn-ai-thread-pin" data-conv-id="${escapeHtml(c.id)}" data-pinned="${c.is_pinned ? '1' : '0'}" title="${pinTitle}">${pinIcon}</button>
              <button type="button" class="btn-ai-thread-action btn-ai-thread-rename" data-conv-id="${escapeHtml(c.id)}" title="Rename">✏️</button>
              <button type="button" class="btn-ai-thread-action btn-ai-thread-del" data-conv-id="${escapeHtml(c.id)}" title="Delete">🗑️</button>
            </div>
          </div>
        `;
      });
      return gHtml;
    };

    html += renderGroup('ai.pinned', 'Pinned', groups.pinned, '📌');
    html += renderGroup('ai.today', 'Today', groups.today, '📅');
    html += renderGroup('ai.yesterday', 'Yesterday', groups.yesterday, '⏳');
    html += renderGroup('ai.prev_7_days', 'Previous 7 Days', groups.prev7Days, '📆');
    html += renderGroup('ai.older', 'Older', groups.older, '🗄️');

    listContainer.innerHTML = html;

    listContainer.querySelectorAll('.ai-thread-item').forEach((item) => {
      const cid = item.dataset.convId;
      item.addEventListener('click', (e) => {
        if (e.target.closest('.ai-thread-actions')) return;
        selectAiConversation(cid);
      });
    });

    listContainer.querySelectorAll('.btn-ai-thread-pin').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const cid = btn.dataset.convId;
        const isPinned = btn.dataset.pinned === '1';
        try {
          await api.patch(`/api/ai/conversations/${cid}`, { is_pinned: !isPinned });
          await fetchAndRenderAiConversations(searchQuery);
        } catch (err) {
          showToast(t('toast.pin_failed', 'Pin failed: {error}', { error: err.message }), 'error');
        }
      });
    });

    listContainer.querySelectorAll('.btn-ai-thread-rename').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        renameAiConversation(btn.dataset.convId);
      });
    });

    listContainer.querySelectorAll('.btn-ai-thread-del').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteAiConversation(btn.dataset.convId);
      });
    });

    if (!_activeConversationId && convs.length > 0) {
      selectAiConversation(convs[0].id);
    }
  } catch (err) {
    console.debug('[ZettAI] Failed loading conversations:', err);
  }
}

export async function selectAiConversation(convId) {
  if (!convId) return;
  if (_aiActiveAbortController) {
    _aiActiveAbortController.abort();
    _aiActiveAbortController = null;
  }
  _activeConversationId = convId;

  document.querySelectorAll('.ai-thread-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.convId === convId);
  });

  const listEl = document.getElementById('ai-chat-messages-list');
  const titleEl = document.getElementById('ai-chat-active-title');

  try {
    const res = await api.get(`/api/ai/conversations/${convId}`);
    if (!res || !res.conversation) return;
    const conv = res.conversation;
    _activeConversationTitle = conv.title || 'New Conversation';
    if (titleEl) titleEl.textContent = _activeConversationTitle;

    if (!listEl) return;
    listEl.innerHTML = '';
    _aiChatHistory = [];

    const msgs = conv.messages || [];
    msgs.forEach((m) => {
      _aiChatHistory.push({ role: m.role, content: m.content });
      if (m.role === 'user') {
        const userMsgEl = document.createElement('div');
        userMsgEl.className = 'ai-chat-msg ai-chat-msg-user';
        userMsgEl.dataset.convId = convId;
        userMsgEl.style.cssText = 'align-self: flex-end; max-width: 85%; padding: 9px 13px; border-radius: 10px; background: rgba(14, 165, 233, 0.22); border: 1px solid rgba(56, 189, 248, 0.45); color: #f8fafc; font-size: 12px; line-height: 1.45;';
        userMsgEl.innerHTML = `<div style="font-size:11px; font-weight:700; color:#7dd3fc; margin-bottom:3px;">🧑 You</div><div>${escapeHtml(m.content)}</div>`;
        listEl.appendChild(userMsgEl);
      } else if (m.role === 'assistant') {
        const botMsgEl = document.createElement('div');
        botMsgEl.className = 'ai-chat-msg ai-chat-msg-assistant';
        botMsgEl.dataset.convId = convId;
        const modelName = m.telemetry?.active_model || conv.model || '—';
        botMsgEl.innerHTML = _buildAiAssistantMessageHtml({
          reply: m.content,
          llm_telemetry: m.telemetry,
          tools_called: m.tools_called,
          web_sources: m.web_sources,
          citations: m.citations,
          photos: m.photos,
        }, modelName);
        listEl.appendChild(botMsgEl);
      }
    });

    listEl.scrollTop = listEl.scrollHeight;
  } catch (err) {
    console.debug('[ZettAI] Failed selecting conversation:', err);
  }
}

export async function createNewAiConversation() {
  if (_aiActiveAbortController) {
    _aiActiveAbortController.abort();
    _aiActiveAbortController = null;
  }
  try {
    const res = await api.post('/api/ai/conversations', { title: 'New Conversation' });
    if (res && res.conversation) {
      _activeConversationId = res.conversation.id;
      _activeConversationTitle = res.conversation.title || 'New Conversation';
      const titleEl = document.getElementById('ai-chat-active-title');
      if (titleEl) titleEl.textContent = _activeConversationTitle;
      const listEl = document.getElementById('ai-chat-messages-list');
      if (listEl) listEl.innerHTML = '';
      _aiChatHistory = [];
      await fetchAndRenderAiConversations();
      const inputEl = document.getElementById('ai-chat-input');
      if (inputEl) inputEl.focus();
    }
  } catch (err) {
    showToast(t('toast.could_not_start_new_chat', 'Could not start new chat: {error}', { error: err.message }), 'error');
  }
}

export async function renameAiConversation(convId, customTitle = null) {
  const targetId = convId || _activeConversationId;
  if (!targetId) return;

  let currentTitle = _activeConversationTitle;
  const match = _aiConversations.find((c) => c.id === targetId);
  if (match && match.title) currentTitle = match.title;

  const performRename = async (titleToSet) => {
    if (!titleToSet || !titleToSet.trim()) return;
    try {
      await api.patch(`/api/ai/conversations/${targetId}`, { title: titleToSet.trim() });
      if (targetId === _activeConversationId) {
        _activeConversationTitle = titleToSet.trim();
        const titleEl = document.getElementById('ai-chat-active-title');
        if (titleEl) titleEl.textContent = _activeConversationTitle;
      }
      await fetchAndRenderAiConversations();
      showToast(t('ai.chat_renamed', 'Conversation renamed.'), 'success');
    } catch (err) {
      showToast(t('toast.rename_failed', 'Rename failed: {error}', { error: err.message }), 'error');
    }
  };

  if (customTitle !== null) {
    await performRename(customTitle);
    return;
  }

  showPromptToast(
    t('ai.rename_chat', 'Rename Chat'),
    t('ai.rename_chat_prompt', 'Enter a new title for this conversation:'),
    currentTitle,
    async (val) => {
      await performRename(val);
    },
    null,
    {
      okText: t('common.save', 'Save'),
      cancelText: t('common.cancel', 'Cancel'),
      icon: '✏️',
    }
  );
}

export async function deleteAiConversation(convId) {
  const targetId = convId || _activeConversationId;
  if (!targetId) return;

  showConfirmToast(
    t('ai.delete_chat', 'Delete Conversation'),
    t('ai.confirm_delete_chat', 'Are you sure you want to delete this conversation?'),
    async () => {
      try {
        await api.delete(`/api/ai/conversations/${targetId}`);
        showToast(t('ai.chat_deleted', 'Conversation deleted.'), 'success');
        if (targetId === _activeConversationId) {
          _activeConversationId = null;
          _activeConversationTitle = 'New Conversation';
          const titleEl = document.getElementById('ai-chat-active-title');
          if (titleEl) titleEl.textContent = 'New Conversation';
          const listEl = document.getElementById('ai-chat-messages-list');
          if (listEl) listEl.innerHTML = '';
          _aiChatHistory = [];
        }
        await fetchAndRenderAiConversations();
        if (!_activeConversationId && _aiConversations.length > 0) {
          selectAiConversation(_aiConversations[0].id);
        } else if (!_activeConversationId) {
          await createNewAiConversation();
        }
      } catch (err) {
        showToast(t('toast.delete_failed', 'Delete failed: {error}', { error: err.message }), 'error');
      }
    }
  );
}

export async function clearAllAiConversations() {
  showConfirmToast(
    t('ai.clear_all', 'Clear All Conversations'),
    t('ai.confirm_clear_all', 'Are you sure you want to delete all conversation history?'),
    async () => {
      try {
        await api.delete('/api/ai/conversations');
        _activeConversationId = null;
        _activeConversationTitle = 'New Conversation';
        _aiConversations = [];
        _aiChatHistory = [];
        const listEl = document.getElementById('ai-chat-messages-list');
        if (listEl) listEl.innerHTML = '';
        showToast(t('ai.all_cleared', 'All conversations cleared.'), 'success');
        await createNewAiConversation();
      } catch (err) {
        showToast(t('toast.clear_all_failed', 'Clear all failed: {error}', { error: err.message }), 'error');
      }
    }
  );
}

export async function exportActiveAiThread(format = 'markdown') {
  if (!_activeConversationId) {
    showToast(t('ai.no_active_conversation', 'No active conversation to export.'), 'warn');
    return;
  }
  try {
    const res = await api.get(`/api/ai/conversations/${_activeConversationId}`);
    if (!res || !res.conversation) return;
    const conv = res.conversation;
    const title = conv.title || 'Conversation';
    const dateStr = formatDateTime(conv.created_at || Date.now());

    let content = '';
    let mimeType = 'text/plain';
    let ext = 'txt';

    if (format === 'markdown') {
      mimeType = 'text/markdown';
      ext = 'md';
      content = `# ${title}\n*Exported from ZettAI on ${dateStr}*\n\n---\n\n`;
      (conv.messages || []).forEach((m) => {
        if (m.role === 'user') {
          content += `### 🧑 User:\n${m.content}\n\n`;
        } else if (m.role === 'assistant') {
          content += `### 🤖 ZettAI:\n${m.content}\n\n`;
        }
      });
    } else {
      mimeType = 'application/json';
      ext = 'json';
      content = JSON.stringify(conv, null, 2);
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const cleanFileName = title.toLowerCase().replace(/[^a-z0-9_-]/g, '_').slice(0, 40) || 'chat';
    a.download = `zettai_${cleanFileName}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast(t('toast.exported_conversation_as', 'Exported conversation as {ext}', { ext: ext.toUpperCase() }), 'success');
  } catch (err) {
    showToast(t('toast.export_failed', 'Export failed: {error}', { error: err.message }), 'error');
  }
}

export function toggleAiSidebar() {
  const sidebar = document.getElementById('ai-chat-sidebar');
  const openBtn = document.getElementById('btn-ai-chat-sidebar-open');
  if (!sidebar) return;
  const isCollapsed = sidebar.classList.toggle('collapsed');
  if (openBtn) {
    openBtn.style.display = isCollapsed ? 'flex' : 'none';
  }
  try {
    localStorage.setItem('zettnas_ai_sidebar_collapsed', isCollapsed ? '1' : '0');
  } catch (_) {}
}

export function initAiConversationControls() {
  const btnNew = document.getElementById('btn-ai-chat-new');
  if (btnNew && !btnNew.dataset.bound) {
    btnNew.dataset.bound = '1';
    btnNew.addEventListener('click', () => createNewAiConversation());
  }

  const btnToggle = document.getElementById('btn-ai-chat-sidebar-toggle');
  if (btnToggle && !btnToggle.dataset.bound) {
    btnToggle.dataset.bound = '1';
    btnToggle.addEventListener('click', () => toggleAiSidebar());
  }

  const btnOpen = document.getElementById('btn-ai-chat-sidebar-open');
  if (btnOpen && !btnOpen.dataset.bound) {
    btnOpen.dataset.bound = '1';
    btnOpen.addEventListener('click', () => toggleAiSidebar());
  }

  const searchInput = document.getElementById('ai-chat-search-input');
  if (searchInput && !searchInput.dataset.bound) {
    searchInput.dataset.bound = '1';
    let debounceTimer = null;
    searchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        fetchAndRenderAiConversations(searchInput.value.trim());
      }, 200);
    });
  }

  const btnClearAll = document.getElementById('btn-ai-chat-clear-all');
  if (btnClearAll && !btnClearAll.dataset.bound) {
    btnClearAll.dataset.bound = '1';
    btnClearAll.addEventListener('click', () => clearAllAiConversations());
  }

  const btnRename = document.getElementById('btn-ai-chat-rename');
  if (btnRename && !btnRename.dataset.bound) {
    btnRename.dataset.bound = '1';
    btnRename.addEventListener('click', () => renameAiConversation(_activeConversationId));
  }

  const titleEl = document.getElementById('ai-chat-active-title');
  if (titleEl && !titleEl.dataset.bound) {
    titleEl.dataset.bound = '1';
    titleEl.addEventListener('dblclick', () => renameAiConversation(_activeConversationId));
  }

  const exportToggle = document.getElementById('btn-ai-chat-export-toggle');
  const exportMenu = document.getElementById('ai-chat-export-menu');
  if (exportToggle && exportMenu && !exportToggle.dataset.bound) {
    exportToggle.dataset.bound = '1';
    exportToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      exportMenu.style.display = exportMenu.style.display === 'none' ? 'block' : 'none';
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#ai-chat-export-menu') && !e.target.closest('#btn-ai-chat-export-toggle')) {
        exportMenu.style.display = 'none';
      }
    });
  }

  const btnExportMd = document.getElementById('btn-ai-chat-export-md');
  if (btnExportMd && !btnExportMd.dataset.bound) {
    btnExportMd.dataset.bound = '1';
    btnExportMd.addEventListener('click', () => {
      if (exportMenu) exportMenu.style.display = 'none';
      exportActiveAiThread('markdown');
    });
  }

  const btnExportJson = document.getElementById('btn-ai-chat-export-json');
  if (btnExportJson && !btnExportJson.dataset.bound) {
    btnExportJson.dataset.bound = '1';
    btnExportJson.addEventListener('click', () => {
      if (exportMenu) exportMenu.style.display = 'none';
      exportActiveAiThread('json');
    });
  }

  try {
    if (localStorage.getItem('zettnas_ai_sidebar_collapsed') === '1') {
      const sidebar = document.getElementById('ai-chat-sidebar');
      if (sidebar) sidebar.classList.add('collapsed');
      if (btnOpen) btnOpen.style.display = 'flex';
    }
  } catch (_) {}

  fetchAndRenderAiConversations().catch(() => {});
}

let _aiChatHistory = [];

export function isAiThinkingModel(modelName) {
  const m = String(modelName || '').toLowerCase();
  return m.includes('r1') ||
         m.includes('qwq') ||
         m.includes('reason') ||
         m.includes('thinking') ||
         m.includes('saluki') ||
         m.includes('cot') ||
         m.includes('deepseek');
}

function _formatChatMarkdown(rawText) {
  let text = String(rawText || '');
  // Strip out any trailing verbose "Verified Web Sources" section
  text = text.replace(/#{2,4}\s*🌐?\s*Verified\s+Web\s+Sources[\s\S]*$/i, '').trim();
  // Strip out duplicate trailing text-based "Sources:\n[1] ... \n[2] ..." list
  text = text.replace(/(?:\r?\n)+\s*(?:\*\*)?Sources:?(?:\*\*)?\s*(?:\r?\n)+(?:\s*\[\d+\][^\n]*\r?\n?)+$/i, '').trim();

  // Extract <think>...</think> if present
  let thoughtHtml = '';
  const thinkMatch = text.match(/<think>([\s\S]*?)<\/think>/i);
  if (thinkMatch) {
    const thoughtContent = escapeHtml(thinkMatch[1].trim());
    text = text.replace(/<think>[\s\S]*?<\/think>/i, '').trim();
    thoughtHtml = `
      <details class="ai-thought-disclosure" style="margin: 4px 0 10px; border-radius: 8px; background: rgba(147, 51, 234, 0.08); border: 1px solid rgba(168, 85, 247, 0.28); padding: 7px 10px; font-size: 11px;">
        <summary style="cursor: pointer; font-weight: 700; color: #c084fc; display: inline-flex; align-items: center; gap: 6px; user-select: none;">
          <span>🧠 Thought Process</span>
          <span style="font-size: 11px; color: #94a3b8; font-weight: 400;">(click to view chain of thought)</span>
        </summary>
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(168, 85, 247, 0.2); color: #cbd5e1; font-size: 11px; line-height: 1.5; font-style: italic;">
          ${thoughtContent.replace(/\n/g, '<br/>')}
        </div>
      </details>
    `;
    if (!text.trim()) {
      text = '*(Thought process completed. No concluding response was emitted by the model.)*';
    }
  }

  // Handle fenced code blocks before escaping HTML
  const codeBlocks = [];
  text = text.replace(/```([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)```/g, (match, lang, code) => {
    const idx = codeBlocks.length;
    const cleanLang = (lang || 'code').trim();
    codeBlocks.push({
      lang: cleanLang,
      code: code.trim(),
    });
    return `___CODE_BLOCK_${idx}___`;
  });

  let escaped = escapeHtml(text);

  // Restore code blocks with glassmorphic container and copy/deploy buttons
  escaped = escaped.replace(/___CODE_BLOCK_(\d+)___/g, (match, idxStr) => {
    const item = codeBlocks[parseInt(idxStr, 10)];
    if (!item) return match;
    const escapedCode = escapeHtml(item.code);
    const isComposeYaml =
      item.lang === 'yaml' ||
      item.lang === 'yml' ||
      item.lang === 'compose' ||
      item.lang === 'docker-compose' ||
      (item.code.includes('services:') && (item.code.includes('image:') || item.code.includes('build:') || item.code.includes('ports:')));

    const deployBtnHtml = isComposeYaml
      ? `<button type="button" class="btn-deploy-stack-code" data-action="deploy-compose-code" style="background: rgba(16, 185, 129, 0.22); border: 1px solid rgba(52, 211, 153, 0.45); border-radius: 4px; color: #6ee7b7; font-size: 11px; font-weight: 700; padding: 2px 8px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; margin-right: 6px;">🚀 Deploy Stack</button>`
      : '';

    return `<div class="ai-chat-code-block" style="margin: 8px 0; border-radius: 8px; background: rgba(2, 6, 23, 0.88); border: 1px solid rgba(56, 189, 248, 0.3); overflow: hidden;">
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 4px 10px; background: rgba(15, 23, 42, 0.95); border-bottom: 1px solid rgba(255, 255, 255, 0.08); font-size: 11px; color: #94a3b8; font-family: monospace;">
        <span style="font-weight: 700; color: #7dd3fc;">${escapeHtml(item.lang)}</span>
        <div style="display: flex; align-items: center;">
          ${deployBtnHtml}
          <button type="button" class="btn-copy-code" data-action="copy-code" style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.18); border-radius: 4px; color: #cbd5e1; font-size: 11px; padding: 2px 7px; cursor: pointer;">Copy</button>
        </div>
      </div>
      <pre style="margin: 0; padding: 10px 12px; overflow-x: auto; font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; line-height: 1.5; color: #e2e8f0;"><code>${escapedCode}</code></pre>
    </div>`;
  });

  const formatted = escaped
    .replace(/^####\s+(.+)$/gm, '<div style="font-size:12px; font-weight:800; color:#7dd3fc; margin:8px 0 3px;">$1</div>')
    .replace(/^###\s+(.+)$/gm, '<div style="font-size:12.5px; font-weight:800; color:#38bdf8; margin:8px 0 4px;">$1</div>')
    .replace(/^&gt;\s?(.*)$/gm, '<div style="border-left:2px solid rgba(168,85,247,0.55); padding-left:8px; margin:3px 0; color:#cbd5e1; font-size:11px; background:rgba(168,85,247,0.07); border-radius:0 4px 4px 0;">$1</div>')
    .replace(/^[-*]\s+(.+)$/gm, '<div style="display:flex; align-items:flex-start; gap:6px; margin:3px 0 3px 4px;"><span style="color:#38bdf8; font-size:11px; line-height:1.5;">•</span><div style="flex:1;">$1</div></div>')
    .replace(/^(\d+)\.\s+(.+)$/gm, '<div style="display:flex; align-items:flex-start; gap:6px; margin:3px 0 3px 4px;"><span style="color:#c084fc; font-weight:700; font-size:11px; line-height:1.5;">$1.</span><div style="flex:1;">$2</div></div>')
    .replace(/\*\*(.+?)\*\*/g, '<strong style="color:#fff;">$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.38); padding:1px 5px; border-radius:4px; color:#bae6fd; font-family:monospace; font-size:11px;">$1</code>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" style="color:#38bdf8; text-decoration:underline;">$1 ↗</a>')
    .replace(/\[\^(\d+):\s*([^#\]]+)(?:#L?(\d+))?\]/g, (match, idx, path, line) => {
      const escP = escapeHtml(path.trim());
      const escN = escapeHtml(path.trim().split('/').pop() || 'File');
      const lineStr = line ? ` (L${line})` : '';
      return `<button type="button" class="ai-citation-inline-pill" data-action="open-file-preview" data-path="${escP}" data-name="${escN}" style="display:inline-flex; align-items:center; gap:3px; background:rgba(56,189,248,0.15); border:1px solid rgba(56,189,248,0.38); border-radius:999px; padding:1px 7px; color:#7dd3fc; font-size:11px; font-weight:700; cursor:pointer; vertical-align:baseline; margin:0 2px;"><span>📄 [${idx}] ${escN}${lineStr}</span><span style="font-size:11px;">👁️</span></button>`;
    })
    .replace(/\[(\d+)\]/g, '<span style="display:inline-flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; color:#38bdf8; background:rgba(56,189,248,0.16); border:1px solid rgba(56,189,248,0.35); border-radius:999px; padding:0 5px; margin:0 2px; vertical-align:baseline; line-height:1.3;">[$1]</span>')
    .replace(/\n\n+/g, '<div style="height:6px;"></div>')
    .replace(/\n/g, '<br/>');

  return (thoughtHtml ? thoughtHtml : '') + formatted;
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
  showToast(t('docker.stack_template_loaded', 'Stack template loaded into Compose editor.'), 'success');
}

if (typeof window !== 'undefined') {
  window.deployComposeStackSnippet = deployComposeStackSnippet;
}

export function clearAiChatHistory() {
  _aiChatHistory = [];
  const listEl = document.getElementById('ai-chat-messages-list');
  if (!listEl) return;
  listEl.innerHTML = '';
}

/** Stops the answer being generated; the server stops the model when the stream closes (AI-12). */
export function stopAiChatGeneration() {
  if (!_aiActiveAbortController) return false;
  _aiStopRequested = true;
  _aiActiveAbortController.abort();
  _aiActiveAbortController = null;
  return true;
}

export async function sendAiChatMessage(rawMessage = null) {
  const inputEl = document.getElementById('ai-chat-input');
  const sendBtn = document.getElementById('btn-ai-chat-send');
  const listEl = document.getElementById('ai-chat-messages-list');

  const msg = (rawMessage !== null && rawMessage !== undefined ? String(rawMessage) : (inputEl ? inputEl.value : '')).trim();
  if (!msg) {
    showToast(t('ai.enter_question', 'Please enter a question or command for the NAS Copilot.'), 'warn');
    return null;
  }

  if (inputEl) inputEl.value = '';
  if (sendBtn) {
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span><span class="ai-typing-dot" style="width:5px;height:5px;margin-right:3px;"></span></span> <span>Generating...</span>';
  }

  // Web search and weather send the question outside the NAS: only when the user turns it on (AI-06).
  const allowWeb = !!document.getElementById('ai-chat-web-toggle')?.checked;
  const allowTools = true;
  const activeModel = _aiLastActiveModel || '—';
  const isThinking = isAiThinkingModel(activeModel);
  let streamBotMsgEl = null;

  if (listEl) {
    const userMsgEl = document.createElement('div');
    userMsgEl.className = 'ai-chat-msg ai-chat-msg-user';
    userMsgEl.style.cssText = 'align-self: flex-end; max-width: 85%; padding: 9px 13px; border-radius: 10px; background: rgba(14, 165, 233, 0.22); border: 1px solid rgba(56, 189, 248, 0.45); color: #f8fafc; font-size: 12px; line-height: 1.45;';
    userMsgEl.innerHTML = `<div style="font-size:11px; font-weight:700; color:#7dd3fc; margin-bottom:3px;">🧑 You</div><div>${escapeHtml(msg)}</div>`;
    listEl.appendChild(userMsgEl);

    const pendingEl = document.createElement('div');
    pendingEl.className = 'ai-chat-msg ai-chat-msg-pending';
    pendingEl.dataset.isThinking = isThinking ? '1' : '0';
    if (isThinking) {
      pendingEl.style.cssText = 'align-self: flex-start; max-width: 85%; padding: 10px 14px; border-radius: 10px; background: rgba(30, 20, 50, 0.75); border: 1px solid rgba(192, 132, 252, 0.4); display: flex; align-items: center; gap: 8px; box-shadow: 0 4px 14px rgba(168, 85, 247, 0.15);';
      pendingEl.innerHTML = `
        <span class="ai-thinking-brain" style="font-size: 15px;">🧠</span>
        <span style="font-size: 12px; font-weight: 700; color: #e9d5ff;">Thinking</span>
        <span class="ai-thinking-dots" style="color: #c084fc; font-weight: 800; letter-spacing: 2px;">
          <span class="ai-dot-1">.</span><span class="ai-dot-2">.</span><span class="ai-dot-3">.</span>
        </span>
        <span style="font-size: 11px; color: #d8b4fe; margin-left: 6px; padding: 1px 7px; border-radius: 999px; background: rgba(168, 85, 247, 0.2); border: 1px solid rgba(192, 132, 252, 0.35);">${escapeHtml(activeModel)}</span>
      `;
    } else {
      pendingEl.style.cssText = 'align-self: flex-start; max-width: 85%; padding: 10px 14px; border-radius: 10px; background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(56, 189, 248, 0.35); display: flex; align-items: center; gap: 9px; box-shadow: 0 4px 14px rgba(14, 165, 233, 0.12);';
      pendingEl.innerHTML = `
        <div class="ai-typing-indicator" style="display: inline-flex; align-items: center; gap: 4px;">
          <span class="ai-typing-dot"></span>
          <span class="ai-typing-dot"></span>
          <span class="ai-typing-dot"></span>
        </div>
        <span style="font-size: 11px; color: #cbd5e1;">Processing with <strong style="color: #38bdf8;">${escapeHtml(activeModel)}</strong>...</span>
      `;
    }
    listEl.appendChild(pendingEl);
    listEl.scrollTop = listEl.scrollHeight;
  }


  try {
    const isTestEnv = window.__forceAiStreamingTest
      ? false
      : (typeof vi !== 'undefined' ||
         typeof vitest !== 'undefined' ||
         (typeof process !== 'undefined' && process?.env?.NODE_ENV === 'test') ||
         typeof window === 'undefined' ||
         !window.fetch ||
         !window.ReadableStream);

    let res = null;

    if (isTestEnv) {
      res = await api.post('/api/media/chat', {
        message: msg,
        history: _aiChatHistory.slice(-10),
        allow_web_search: allowWeb,
        allow_nas_tools: allowTools,
        conversation_id: _activeConversationId,
      });
      if (res && res.conversation_title && _activeConversationId) {
        _activeConversationTitle = res.conversation_title;
        const titleEl = document.getElementById('ai-chat-active-title');
        if (titleEl) titleEl.textContent = res.conversation_title;
      }
    } else {
      // Production browser runtime: consume SSE stream from /api/media/chat/stream
      let partialReply = '';
      let partialTools = [];
      const stopBtn = document.getElementById('btn-ai-chat-stop');
      _aiStopRequested = false;
      try {
        if (stopBtn) stopBtn.hidden = false;
        const streamHeaders = {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        };
        const token = auth.getToken();
        if (token) streamHeaders['Authorization'] = `Bearer ${token}`;

        if (_aiActiveAbortController) {
          _aiActiveAbortController.abort();
          _aiActiveAbortController = null;
        }
        _aiActiveAbortController = new AbortController();
        const currentConvId = _activeConversationId;
        const currentReqId = ++_aiActiveRequestId;

        const streamRes = await window.fetch('/api/media/chat/stream', {
          method: 'POST',
          headers: streamHeaders,
          body: JSON.stringify({
            message: msg,
            history: _aiChatHistory.slice(-10),
            allow_web_search: allowWeb,
            allow_nas_tools: allowTools,
            conversation_id: currentConvId,
          }),
          signal: _aiActiveAbortController.signal,
        });

        if (!streamRes.ok) {
          throw new Error(`HTTP ${streamRes.status}`);
        }

        const reader = streamRes.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let streamBuffer = '';
        let currentEvent = 'message';
        let donePayload = null;
        let toolsCollected = [];
        let streamedThinking = '';
        let streamedTokens = '';

        streamBotMsgEl = null;
        let replyBodyEl = null;
        let thoughtDetailsEl = null;
        let thoughtBodyEl = null;
        let toolsTraceEl = null;

        const setupStreamBotEl = () => {
          if (streamBotMsgEl || !listEl) return;
          const pending = listEl.querySelector('.ai-chat-msg-pending');
          if (pending) pending.remove();

          streamBotMsgEl = document.createElement('div');
          streamBotMsgEl.className = 'ai-chat-msg ai-chat-msg-assistant';
          if (currentConvId) streamBotMsgEl.dataset.convId = currentConvId;
          streamBotMsgEl.dataset.activeModel = activeModel;
          streamBotMsgEl.dataset.isStreaming = '1';
          streamBotMsgEl.style.cssText = 'display: flex; flex-direction: column; gap: 7px; padding: 11px 14px; border-radius: 10px; background: rgba(15, 23, 42, 0.78); border: 1px solid rgba(56, 189, 248, 0.28);';

          streamBotMsgEl.innerHTML = `
            <div class="ai-chat-llm-proof-bar" style="display: flex; justify-content: space-between; align-items: center; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 5px;">
              <div style="display: flex; align-items: center; gap: 6px;">
                <span class="ai-chat-model-pill" style="font-size: 11px; font-weight: 800; color: #e9d5ff; padding: 1px 8px; border-radius: 999px; background: rgba(168,85,247,0.18); border: 1px solid rgba(192,132,252,0.45);">🤖 ${escapeHtml(activeModel)}</span>
                <span style="font-size: 11px; font-weight: 700; color: #38bdf8; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="ai-typing-dot" style="width: 5px; height: 5px;"></span> Streaming
                </span>
              </div>
            </div>
            <div class="ai-chat-tools-trace" style="display: flex; flex-wrap: wrap; gap: 5px; padding-top: 2px;"></div>
            <div class="ai-chat-reply-body" style="font-size: 12px; color: #f1f5f9; line-height: 1.55;"></div>
          `;
          listEl.appendChild(streamBotMsgEl);
          toolsTraceEl = streamBotMsgEl.querySelector('.ai-chat-tools-trace');
          replyBodyEl = streamBotMsgEl.querySelector('.ai-chat-reply-body');
          listEl.scrollTop = listEl.scrollHeight;
        };

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          streamBuffer += decoder.decode(value, { stream: true });
          const lines = streamBuffer.split(/\r?\n/);
          streamBuffer = lines.pop();

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) {
              currentEvent = 'message';
              continue;
            }
            if (trimmed.startsWith('event:')) {
              currentEvent = trimmed.slice(6).trim();
              continue;
            }
            if (trimmed.startsWith('data:')) {
              const dataStr = trimmed.slice(5).trim();
              let parsed = null;
              try { parsed = JSON.parse(dataStr); } catch (_) { parsed = dataStr; }

              if (currentConvId && (_activeConversationId !== currentConvId || _aiActiveRequestId !== currentReqId)) {
                try { reader.cancel(); } catch (_) {}
                return null;
              }

              if (currentEvent === 'conversation_title') {
                if (parsed?.title && currentConvId === _activeConversationId) {
                  _activeConversationTitle = parsed.title;
                  const titleEl = document.getElementById('ai-chat-active-title');
                  if (titleEl) titleEl.textContent = parsed.title;
                  const tItem = document.querySelector(`.ai-thread-item[data-conv-id="${currentConvId}"] .ai-thread-title-text`);
                  if (tItem) tItem.textContent = parsed.title;
                }
              } else if (currentEvent === 'tool_start') {
                setupStreamBotEl();
                const toolName = parsed?.tool || 'tool';
                if (toolsTraceEl) {
                  const pill = document.createElement('span');
                  pill.className = 'ai-chat-tool-pill ai-chat-tool-running';
                  pill.dataset.toolName = toolName;
                  pill.style.cssText = 'font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: rgba(56,189,248,0.16); border: 1px solid rgba(56,189,248,0.42); color: #7dd3fc;';
                  pill.textContent = `⚡ Running ${toolName}...`;
                  toolsTraceEl.appendChild(pill);
                }
              } else if (currentEvent === 'tool_done') {
                setupStreamBotEl();
                toolsCollected.push(parsed);
                partialTools = toolsCollected;
                if (toolsTraceEl) {
                  const existingPill = toolsTraceEl.querySelector(`.ai-chat-tool-pill[data-tool-name="${parsed?.tool}"]`);
                  const isWeb = parsed?.tool === 'browse_internet';
                  const isRag = parsed?.tool === 'search_nas_knowledge';
                  const isCalc = parsed?.tool === 'calculate';
                  const isStorage = parsed?.tool === 'get_storage_status';
                  const isNet = parsed?.tool === 'get_network_status';
                  const isWeather = parsed?.tool === 'get_weather';
                  const bg = isCalc ? 'rgba(245,158,11,0.16)' : (isWeather ? 'rgba(14,165,233,0.18)' : (isWeb ? 'rgba(56,189,248,0.16)' : (isRag ? 'rgba(168,85,247,0.16)' : (isNet ? 'rgba(14,165,233,0.16)' : 'rgba(16,185,129,0.16)'))));
                  const border = isCalc ? 'rgba(251,191,36,0.42)' : (isWeather ? 'rgba(56,189,248,0.45)' : (isWeb ? 'rgba(56,189,248,0.42)' : (isRag ? 'rgba(168,85,247,0.42)' : (isNet ? 'rgba(56,189,248,0.42)' : 'rgba(52,211,153,0.42)'))));
                  const color = isCalc ? '#fde68a' : (isWeather ? '#38bdf8' : (isWeb ? '#7dd3fc' : (isRag ? '#d8b4fe' : (isNet ? '#7dd3fc' : '#6ee7b7'))));
                  const icon = isCalc ? '🧮' : (isWeather ? '⛅' : (isWeb ? '🌐' : (isRag ? '📁' : (isStorage ? '💽' : (isNet ? '🔌' : '🛠️')))));
                  const pillHtml = `${icon} ${escapeHtml(parsed?.tool || 'tool')}: ${escapeHtml(parsed?.summary || 'OK')}`;
                  if (existingPill) {
                    existingPill.className = 'ai-chat-tool-pill';
                    existingPill.style.background = bg;
                    existingPill.style.border = `1px solid ${border}`;
                    existingPill.style.color = color;
                    existingPill.innerHTML = pillHtml;
                  } else {
                    const newPill = document.createElement('span');
                    newPill.className = 'ai-chat-tool-pill';
                    newPill.dataset.toolName = parsed?.tool || 'tool';
                    newPill.style.cssText = `font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: ${bg}; border: 1px solid ${border}; color: ${color};`;
                    newPill.innerHTML = pillHtml;
                    toolsTraceEl.appendChild(newPill);
                  }
                }
              } else if (currentEvent === 'think') {
                setupStreamBotEl();
                const tok = parsed?.token || '';
                streamedThinking += tok;
                if (!thoughtDetailsEl && streamBotMsgEl) {
                  thoughtDetailsEl = document.createElement('details');
                  thoughtDetailsEl.className = 'ai-thought-disclosure';
                  thoughtDetailsEl.open = true;
                  thoughtDetailsEl.style.cssText = 'margin: 4px 0 10px; border-radius: 8px; background: rgba(147, 51, 234, 0.08); border: 1px solid rgba(168, 85, 247, 0.28); padding: 7px 10px; font-size: 11px;';
                  thoughtDetailsEl.innerHTML = `
                    <summary style="cursor: pointer; font-weight: 700; color: #c084fc; display: inline-flex; align-items: center; gap: 6px; user-select: none;">
                      <span>🧠 Thought Process</span>
                      <span style="font-size: 11px; color: #94a3b8; font-weight: 400;">(reasoning in real time...)</span>
                    </summary>
                    <div class="ai-thought-content" style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(168, 85, 247, 0.2); color: #cbd5e1; font-size: 11px; line-height: 1.5; font-style: italic;"></div>
                  `;
                  if (replyBodyEl) streamBotMsgEl.insertBefore(thoughtDetailsEl, replyBodyEl);
                  thoughtBodyEl = thoughtDetailsEl.querySelector('.ai-thought-content');
                }
                if (thoughtBodyEl) {
                  thoughtBodyEl.innerHTML = escapeHtml(streamedThinking).replace(/\n/g, '<br/>');
                }
                listEl.scrollTop = listEl.scrollHeight;
              } else if (currentEvent === 'reset') {
                // The model chose to use tools: what it streamed so far wasn't the answer.
                streamedTokens = '';
                partialReply = '';
                if (replyBodyEl) replyBodyEl.innerHTML = '';
              } else if (currentEvent === 'token') {
                setupStreamBotEl();
                const tok = parsed?.token || '';
                streamedTokens += tok;
                partialReply = streamedTokens;
                if (replyBodyEl) {
                  replyBodyEl.innerHTML = _formatChatMarkdown(streamedTokens);
                }
                listEl.scrollTop = listEl.scrollHeight;
              } else if (currentEvent === 'done') {
                donePayload = parsed;
              } else if (currentEvent === 'error') {
                throw new Error(parsed?.error || 'Streaming error');
              }
            }
          }
        }

        if (donePayload) {
          res = donePayload;
          if (streamBotMsgEl) {
            delete streamBotMsgEl.dataset.isStreaming;
            streamBotMsgEl.innerHTML = _buildAiAssistantMessageHtml(res, activeModel);
          }
        } else if (streamedTokens) {
          res = {
            status: 'ok',
            reply: streamedTokens,
            tools_called: toolsCollected,
            active_model: activeModel,
          };
        }
      } catch (streamErr) {
        if (streamErr && streamErr.name === 'AbortError') {
          // Stopped by the user (or replaced by a newer request): never re-send the question.
          if (!_aiStopRequested) return null;
          res = {
            status: 'ok',
            stopped: true,
            reply: `${partialReply}${partialReply ? '\n\n' : ''}_${t('ai.stopped', 'Stopped.')}_`,
            tools_called: partialTools,
            active_model: activeModel,
          };
          if (streamBotMsgEl) {
            delete streamBotMsgEl.dataset.isStreaming;
            streamBotMsgEl.innerHTML = _buildAiAssistantMessageHtml(res, activeModel);
          }
        } else {
        console.warn('[ZettAI] Streaming fell back to standard POST:', streamErr);
        if (streamBotMsgEl) {
          streamBotMsgEl.remove();
          streamBotMsgEl = null;
        }
        res = await api.post('/api/media/chat', {
          message: msg,
          history: _aiChatHistory.slice(-10),
          allow_web_search: allowWeb,
          allow_nas_tools: allowTools,
          conversation_id: _activeConversationId,
        });
        }
      } finally {
        if (stopBtn) stopBtn.hidden = true;
      }
    }

    if (listEl) {
      const pending = listEl.querySelector('.ai-chat-msg-pending');
      if (pending) pending.remove();
    }

    if (!res) return null;

    const replyMd = res.reply || res.answer || 'No response generated.';
    const llmTel = res.llm_telemetry || {};
    const usedModel = llmTel.active_model || res.active_model || activeModel;

    _aiChatHistory.push({ role: 'user', content: msg });
    _aiChatHistory.push({ role: 'assistant', content: replyMd });

    if (listEl) {
      if (streamBotMsgEl) {
        // Streamed message bubble was already created and populated in listEl during the stream.
        // Update model and conversation tracking dataset attributes without appending a duplicate element!
        streamBotMsgEl.dataset.activeModel = usedModel;
        if (_activeConversationId) streamBotMsgEl.dataset.convId = _activeConversationId;
      } else {
        // Non-streaming fallback (e.g. test environment or network fallback where streaming was bypassed)
        const botMsgEl = document.createElement('div');
        botMsgEl.className = 'ai-chat-msg ai-chat-msg-assistant';
        botMsgEl.dataset.activeModel = usedModel;
        if (_activeConversationId) botMsgEl.dataset.convId = _activeConversationId;
        botMsgEl.style.cssText = 'display: flex; flex-direction: column; gap: 7px; padding: 11px 14px; border-radius: 10px; background: rgba(15, 23, 42, 0.78); border: 1px solid rgba(56, 189, 248, 0.28);';
        botMsgEl.innerHTML = _buildAiAssistantMessageHtml(res, activeModel);
        listEl.appendChild(botMsgEl);
      }
      listEl.scrollTop = listEl.scrollHeight;
    }

    return res;
  } catch (err) {
    if (listEl) {
      const pending = listEl.querySelector('.ai-chat-msg-pending');
      if (pending) pending.remove();
      const errEl = document.createElement('div');
      errEl.className = 'ai-chat-msg ai-chat-msg-error';
      errEl.style.cssText = 'padding: 10px 14px; border-radius: 10px; background: rgba(239, 68, 68, 0.14); border: 1px solid rgba(248, 113, 113, 0.45); color: #fecaca; font-size: 12px;';
      errEl.textContent = `⚠️ Chatbot error: ${err.message || String(err)}`;
      listEl.appendChild(errEl);
      listEl.scrollTop = listEl.scrollHeight;
    }
    return null;
  } finally {
    if (sendBtn) {
      sendBtn.disabled = false;
      sendBtn.innerHTML = `<span>🚀</span> <span data-i18n="ai.chat_send_btn">${escapeHtml(t('ai.chat_send_btn', 'Ask Zetty'))}</span>`;
    }
  }
}

export function updateAiReindexProgress(data) {
  const container = document.getElementById('ai-reindex-progress-container');
  const topBanner = document.getElementById('ai-reindex-top-banner');
  const univStrip = document.getElementById('ai-reindex-universal-strip');
  const sidebarBadge = document.getElementById('mgmt-sidebar-ai-badge');
  const topText = document.getElementById('topbar-ai-accel-text');

  if (!data || data.status === 'idle' || data.type === 'complete' || (data.total > 0 && data.completed >= data.total)) {
    if (container) container.style.display = 'none';
    if (topBanner) topBanner.style.display = 'none';
    if (univStrip) univStrip.style.display = 'none';
    if (sidebarBadge && sidebarBadge.dataset.reindexing) {
      sidebarBadge.textContent = 'NPU/GPU';
      sidebarBadge.style.background = 'rgba(14,165,233,0.18)';
      sidebarBadge.style.color = 'var(--accent-cyan,#00f0ff)';
      delete sidebarBadge.dataset.reindexing;
    }
    return;
  }

  const pct = data.percentage ?? (data.total > 0 ? Math.round((data.completed / data.total) * 100) : 0);
  const completed = data.completed ?? 0;
  const total = data.total ?? 0;
  const speed = data.speed !== undefined ? data.speed : 0;
  const etaSec = data.eta_sec !== undefined ? data.eta_sec : 0;

  let etaText = 'ETA: --';
  if (etaSec > 0) {
    if (etaSec < 60) {
      etaText = `ETA: ${Math.round(etaSec)}s`;
    } else if (etaSec < 3600) {
      const mins = Math.floor(etaSec / 60);
      const secs = Math.round(etaSec % 60);
      etaText = `ETA: ${mins}m ${secs}s`;
    } else {
      const hrs = Math.floor(etaSec / 3600);
      const mins = Math.round((etaSec % 3600) / 60);
      etaText = `ETA: ${hrs}h ${mins}m`;
    }
  }

  if (sidebarBadge) {
    sidebarBadge.dataset.reindexing = '1';
    sidebarBadge.textContent = `${pct}% Re-index`;
    sidebarBadge.style.background = 'rgba(234, 179, 8, 0.2)';
    sidebarBadge.style.color = '#fbbf24';
  }

  if (topText) {
    topText.textContent = `Re-indexing ${pct}% • ${etaText}`;
  }

  // Update top banner
  if (topBanner) {
    topBanner.style.display = 'block';
    const topBar = document.getElementById('ai-reindex-top-progress-bar');
    if (topBar) topBar.style.width = `${pct}%`;
    const topPct = document.getElementById('ai-reindex-top-pct-label');
    if (topPct) topPct.textContent = `${pct}%`;
    const topChunks = document.getElementById('ai-reindex-top-chunks-label');
    if (topChunks) topChunks.textContent = `${formatNumber(completed)} / ${formatNumber(total)} chunks`;
    const topSpeed = document.getElementById('ai-reindex-top-speed-label');
    if (topSpeed) topSpeed.textContent = `${speed} chunks/s`;
    const topEta = document.getElementById('ai-reindex-top-eta-label');
    if (topEta) topEta.textContent = etaText;
  }

  // Update universal strip (visible across all tabs: Chatbot, RAG, Configuration)
  if (univStrip) {
    univStrip.style.display = 'block';
    const uBar = document.getElementById('ai-reindex-univ-bar');
    if (uBar) uBar.style.width = `${pct}%`;
    const uPct = document.getElementById('ai-reindex-univ-pct');
    if (uPct) uPct.textContent = `${pct}%`;
    const uChunks = document.getElementById('ai-reindex-univ-chunks');
    if (uChunks) uChunks.textContent = `${formatNumber(completed)} / ${formatNumber(total)} chunks`;
    const uSpeed = document.getElementById('ai-reindex-univ-speed');
    if (uSpeed) uSpeed.textContent = `${speed} chunks/s`;
    const uEta = document.getElementById('ai-reindex-univ-eta');
    if (uEta) uEta.textContent = etaText;
  }

  // Update bottom container in MRL card
  if (container) {
    container.style.display = 'block';
    const bar = document.getElementById('ai-reindex-progress-bar');
    if (bar) bar.style.width = `${pct}%`;
    const pctLabel = document.getElementById('ai-reindex-pct-label');
    if (pctLabel) pctLabel.textContent = `${pct}%`;
    const speedLabel = document.getElementById('ai-reindex-speed-label');
    if (speedLabel) speedLabel.textContent = `${speed} chunks/s`;
    const etaLabel = document.getElementById('ai-reindex-eta-label');
    if (etaLabel) etaLabel.textContent = etaText;
  }
}

let _reindexPollTimer = null;
export function _pollReindexProgress() {
  if (_reindexPollTimer) return;
  _reindexPollTimer = setInterval(async () => {
    try {
      const st = await api.get('/api/ai/reindex/status');
      if (st) {
        updateAiReindexProgress(st);
        if (st.status !== 'running') {
          clearInterval(_reindexPollTimer);
          _reindexPollTimer = null;
          if (st.percentage >= 100 || (st.total > 0 && st.completed >= st.total)) {
            showToast(t('ai.reindex_completed', '✓ In-place re-indexing completed successfully!'), 'success');
          }
        }
      }
    } catch {
      clearInterval(_reindexPollTimer);
      _reindexPollTimer = null;
    }
  }, 1500);
}

export async function triggerInPlaceReindex() {
  const container = document.getElementById('ai-reindex-progress-container');
  if (container) container.style.display = 'block';
  try {
    const resp = await api.post('/api/ai/reindex');
    if (resp && (resp.status === 'ok' || resp.status === 'in_progress')) {
      showToast(t('ai.reindex_started', 'In-place re-indexing started in background'), 'success');
      _pollReindexProgress();
    }
  } catch (err) {
    showToast(t('toast.failed_trigger_reindex', 'Failed to start re-indexing: {error}', { error: err.message }), 'error');
  }
}



/** Shows how many photos the vision model has described (AI-14). */
export async function refreshVisionStatus() {
  const el = document.getElementById('ai-vision-status');
  if (!el) return;
  try {
    const st = await api.get('/api/ai/vision/status');
    if (st.mode === 'off') {
      el.textContent = '';
    } else if (st.state === 'no-model') {
      el.textContent = t('ai.vision_no_model', 'Install a vision model (for example gemma3 or qwen2.5vl) under AI → Models.');
    } else {
      el.textContent = t('ai.vision_progress', '{done} of {total} photos described', { done: st.captioned, total: st.photos });
    }
  } catch {
    el.textContent = '';
  }
}


/** After Tailscale Serve is on: the address to open on a phone, with a QR code (M2). */
export async function showServeLink(url, funnel = false) {
  let qr = '';
  try {
    const { default: QRCode } = await import('qrcode');
    qr = await QRCode.toDataURL(url, { margin: 1, width: 180 });
  } catch (e) {
    console.warn('QR code unavailable', e);
  }
  const how = funnel
    ? t('ts.serve_how_funnel', 'Funnel is on: this address works from any browser on the internet, so keep strong passwords and 2FA.')
    : t('ts.serve_how', 'On your phone, install the Tailscale app and sign in to the same tailnet. Then open this address, on Wi-Fi or mobile data. Add it to your home screen to use ZettNAS like an app.');
  showConfirmToast(
    t('ts.serve_ready', 'ZettNAS is reachable through Tailscale'),
    `${qr ? `<img src="${qr}" alt="${escapeHtml(t('ts.serve_qr_alt', 'QR code for {url}', { url }))}" width="180" height="180" style="display:block;margin:0 auto 10px;border-radius:8px;background:#fff;">` : ''}<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" style="color:#38bdf8;font-weight:700;word-break:break-all;">${escapeHtml(url)}</a><br><br>${escapeHtml(how)}`,
    () => {
      if (navigator.clipboard) navigator.clipboard.writeText(url).catch(() => {});
    },
    null,
    { confirmText: t('ts.serve_copy', 'Copy address'), cancelText: t('common.close', 'Close'), allowHtml: true }
  );
}
