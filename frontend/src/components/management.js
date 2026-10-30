import { syncWidgetSettingsUI } from './widgets.js';
import { syncDesktopThemeUI, openDrawer, restoreHardwareTabsToManagement } from './settings.js';
import { ZettEventBus } from '../event-bus.js';
import { fitMiniPreviewScale, syncMiniPreviewTelemetry } from './mini-preview.js';
import { fetchAndRenderChassisTwin, fetchAndRenderStorageTopology, fetchAndRenderNetworkShares, fetchAndRenderRemoteStorage, openNewCloudRemoteModal, openCreateStoragePoolModal, openCreateNetworkShareModal, openSnapshotsModal, getThermalLevel } from './chassis-visualizer.js';
import { fetchAndRenderMetrics } from './metrics-chart.js';
import { bringToFront, DockManager, makeDraggable, saveWindowBounds, saveOpenWindowsState } from './dock.js';
import { state } from '../state.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { trapFocus, escapeHtml, copyTextToClipboard } from '../utils.js';
import { t, getLanguage } from '../i18n.js';
import '../styles/management-lazy.css'; // Mission Control's own sheet loads with this code (ARC-12)
import { wireTablists, markCurrent } from './tab-a11y.js';
import { openFilePreviewModal } from './file-preview-modal.js';
import { fetchAndRenderAppCatalog, fetchAndRenderDockerContainers, presetCatalogSearch, refreshCatalogCountBadges, startDockerAutoRefresh, stopDockerAutoRefresh } from './management/docker.js';
import { fetchAndRenderUpsTelemetry, initUpsDrawerControls, loadUpsConfigToDrawer, renderUpsTelemetry } from './management/ups.js';
import { fetchAndRenderCopyHistory, fetchAndRenderNetworkTopology, fetchAndRenderReplication, fetchAndRenderWireguard, initNetworkControls } from './management/network.js';
import { fetchAndRenderDisksInventory } from './management/disks.js';
import { closeHttpsGuideModal, fetchAndRenderSecurityPosture, handleSecurityAdvisorClick } from './management/security.js';
import { applySystemUpdate, closeDiagnosticsPreviewModal, copySupportMarkdown, downloadDiagnosticsBundle, fetchAndRenderSystemAbout, previewDiagnosticsSummary, revertSystemUpdate, setUpdateChannel, syncBackupJobForm } from './management/system.js';
import { fetchAndRenderNotificationConfig, openChannelConfigModal, saveCurrentChannelModal, saveNotificationsConfig, testAllNotificationChannels, testSingleChannel } from './management/notifications.js';
import { fetchAndRenderAppBackups, fetchAndRenderBackupJobs, fetchAndRenderSystemSnapshots } from './management/backup.js';
import { installAdvancedSwitch, renderStatusSummary } from './management/overview.js';
import { installHealthSignal } from './management/health-signal.js';
import { _aiSelectedColor, _aiSelectedScene, _getActiveAiSearchQuery, _renderAiRagInitialEmptyState, fetchAndRenderAiStatus, initAiKnowledgeEngine, runAiVisualSearch, setAiVisualFiltersDrawerOpen } from './management/ai.js';

export * from './management/docker.js';
export * from './management/ups.js';
export * from './management/network.js';
export * from './management/disks.js';
export * from './management/security.js';
export * from './management/system.js';
export * from './management/notifications.js';
export * from './management/backup.js';
export * from './management/ai.js';

if (typeof window !== 'undefined') {
  window.openFilePreviewModal = openFilePreviewModal;
}

let _activeProfile = 'balanced';
let _unbindMgmtTrap = null;


// The deploy button: a soft tint of the accent with a thin border, like the dialog's other controls.
export function setDeployButtonTone(btn, tone) {
  const color = tone === 'danger' ? 'var(--err, #eb5757)' : 'var(--brand, #0ea5e9)';
  btn.style.background = `color-mix(in srgb, ${color} 22%, transparent)`;
  btn.style.border = `1px solid color-mix(in srgb, ${color} 55%, transparent)`;
  btn.style.color = 'var(--text, #e5e7eb)';
}

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
        moverEl.textContent = t('ui.idle', 'Idle');
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
        gpuCodecsEl.innerHTML = `<span class="gpu-codec-tag" style="color:var(--muted); border-color:var(--zn-line-10);">CPU Decode Only</span>`;
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
              `<span class="gpu-codec-tag" style="background:rgba(168,85,247,0.12); color:var(--zn-text-ai); border-color:rgba(168,85,247,0.25);">${escapeHtml(f)}</span>`
          )
          .join('');
      } else {
        npuFrameworksEl.innerHTML = `<span class="gpu-codec-tag" style="color:var(--muted); border-color:var(--zn-line-10);">CPU Fallback</span>`;
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

export function initManagement() {
  window.__updateManagementTelemetry = updateManagementTelemetry;
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
    renderStatusSummary(); // UX-1: what needs attention comes first
    if (hubView) hubView.style.display = 'grid';
    if (detailContainer) detailContainer.style.display = 'none';
    if (headerNav) headerNav.style.display = 'none';
    if (backBtn) backBtn.style.display = 'none';
    if (titleText) titleText.textContent = t('mgmt.title', 'Settings');
    document.querySelectorAll('.mgmt-category-tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.mgmt-sidebar-item').forEach((b) => {
      b.classList.toggle('active', b.dataset.mgmtTarget === 'management-hub-view');
    });
    markCurrent(document.querySelectorAll('.mgmt-sidebar-item'), (b) => b.dataset.mgmtTarget === 'management-hub-view');
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
      // COMP-01: the guided "Use from anywhere" card above the Tailscale details
      import('./remote-access.js').then((m) => m.installRemoteAccess(document.getElementById('remote-access-mount'))).catch(() => {});
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
      refreshCatalogCountBadges();
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
        btnContainers.textContent = t('ui.back_to_containers', '← Back to Containers');
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
      import('./management/network.js').then((n) => n.revealReplicationTab()).catch(() => {});
    } else if (paneId === 'mgmt-pane-storage-topo') {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      if (mount) fetchAndRenderStorageTopology(mount);
    } else if (paneId === 'mgmt-pane-storage-shares') {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      if (mount) fetchAndRenderNetworkShares(mount);
      const ef = document.getElementById('encrypted-folders-mount');
      if (ef) import('./encrypted-folders.js').then((m) => m.renderEncryptedFolders(ef)); // FEAT-13
    } else if (paneId === 'mgmt-pane-storage-remotes') {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      if (mount) fetchAndRenderRemoteStorage(mount);
    } else if (paneId === 'mgmt-pane-storage-disks') {
      fetchAndRenderDisksInventory();
    } else if (paneId === 'mgmt-pane-storage-replication') {
      fetchAndRenderReplication();
    } else if (paneId === 'mgmt-pane-backups' || paneId === 'mgmt-pane-system') {
      if (paneId === 'mgmt-pane-backups') {
        // phone backup sits with the other backups (UX-26)
        import('./phone-backup.js').then((p) => p.installPhoneBackup(document.getElementById('phone-backup-mount'))).catch(() => {});
        import('./management/protection.js').then((p) => p.installProtectionJobs(document.getElementById('protection-jobs-mount'))).catch(() => {});
      }
      fetchAndRenderBackupJobs();
      fetchAndRenderSystemSnapshots();
      fetchAndRenderAppBackups();
    } else if (paneId === 'mgmt-pane-security') {
      import('./settings.js').then((m) => m.renderApiTokens && m.renderApiTokens()).catch(() => {});
      import('./guard-panel.js').then((m) => m.renderGuardPanel()).catch(() => {});
      import('./file-activity.js').then((m) => m.renderFileActivity()).catch(() => {}); // FEAT-12
      import('./sso.js').then((m) => { m.renderSsoPanel(); m.renderLdapPanel(); }).catch(() => {});
      import('./management/user-data.js').then((m) => m.installMyData()).catch(() => {}); // your data (B8)
      fetchAndRenderSecurityPosture();
    } else if (paneId === 'mgmt-pane-notifications') {
      fetchAndRenderNotificationConfig();
      import('./push-card.js').then((m) => m.renderPushCard()).catch(() => {});
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
      if (paneId === 'mgmt-pane-ai-index') {
        Promise.all([import('./immich-settings.js'), import('./session.js'), import('./ai-apps-settings.js'), import('./ai-pack-settings.js')])
          .then(([m, u, apps, pack]) => {
            const scopes = (u.getCurrentUser() || {}).scopes || [];
            const isAdmin = scopes.includes('*') || scopes.includes('system:config');
            m.renderImmichSettings(document.getElementById('immich-settings-mount'), isAdmin);
            apps.renderAiApps(document.getElementById('ai-apps-mount'), isAdmin); // COMP-07
            pack.renderAiPack(document.getElementById('ai-pack-mount'), isAdmin); // AI-40
          })
          .catch(() => {});
      }
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
          <div style="background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 10px 14px;">
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); font-weight: 700; text-transform: uppercase;">HYPERVISOR ENGINE</div>
            <div style="font-size: 13px; font-weight: 700; color: ${kvmColor}; margin-top: 4px; display: flex; align-items: center; gap: 6px;">
              <span aria-hidden="true">⚡</span> <span>${escapeHtml(kvmBadge)}</span>
            </div>
          </div>
          <div style="background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 10px 14px;">
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); font-weight: 700; text-transform: uppercase;">MEMORY CEILING</div>
            <div style="font-size: 13px; font-weight: 700; color: var(--lt-ink-brand, var(--accent-cyan, #0ea5e9)); margin-top: 4px;">
              ${escapeHtml(headroom)}
            </div>
          </div>
          <div style="background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 8px; padding: 10px 14px;">
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); font-weight: 700; text-transform: uppercase;">vCPU OVERCOMMIT</div>
            <div style="font-size: 13px; font-weight: 700; color: var(--zn-text-strong); margin-top: 4px;">
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
              <div class="mgmt-vm-card" data-vm-id="${escapeHtml(vm.id)}" style="background: var(--zn-glaze-3); border: 1px solid var(--zn-line-7); border-radius: 8px; padding: 14px; display: flex; flex-direction: column; gap: 10px; transition: border-color 0.2s;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 18px;">🖥️</span>
                    <div>
                      <div style="font-weight: 700; font-size: 13px; color: var(--zn-text-strong);">${escapeHtml(vm.name || vm.id)}</div>
                      <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${escapeHtml(osType)} • ${cores} vCPU • ${ramGb} RAM</div>
                    </div>
                  </div>
                  <span style="padding: 2px 8px; border-radius: 4px; font-size: var(--zn-fs-xs); font-weight: 700; text-transform: uppercase; background: ${statusBg}; color: ${statusColor};">
                    ${escapeHtml(vm.state || 'stopped')}
                  </span>
                </div>
                <div style="display: flex; gap: 6px; margin-top: auto; padding-top: 8px; border-top: 1px solid var(--zn-line-5);">
                  ${isRunning
                    ? `<button class="btn-pill-toggle btn-vm-action-stop is-danger" data-vm-id="${escapeHtml(vm.id)}" style="flex: 1;" title="${t('ui.stop_vm', 'Stop VM')}">⏹ Stop</button>`
                    : `<button class="btn-pill-toggle btn-vm-action-start" data-vm-id="${escapeHtml(vm.id)}" style="flex: 1; color: var(--ok2);" title="${t('ui.start_vm', 'Start VM')}">▶ Start</button>`
                  }
                  <button class="btn-pill-toggle btn-vm-action-console" data-vm-id="${escapeHtml(vm.id)}" data-vm-name="${escapeHtml(vm.name || vm.id)}" style="flex: 1; color: var(--lt-ink-brand, var(--accent-cyan));" title="${t('ui.open_web_console', 'Open Web Console')}">📺 Console</button>
                  <button class="btn-pill-toggle btn-vm-action-edit" data-vm-id="${escapeHtml(vm.id)}" title="${t('ui.edit_vm_config', 'Edit VM Config')}">⚙️</button>
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
                btn.textContent = t('ui.start', '▶ Start');
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
                btn.textContent = t('ui.stop', '⏹ Stop');
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
          <div style="background: var(--zn-glaze-3); border: 1px solid var(--zn-line-8); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; gap: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div style="font-weight: 700; font-size: 13px; color: var(--zn-text-strong);">Hardware Virtualization Extension</div>
              <span style="padding: 3px 8px; border-radius: 4px; font-size: var(--zn-fs-xs); font-weight: 700; background: ${tel.kvm.state === 'active' ? 'rgba(37,194,160,0.15)' : 'rgba(239,68,68,0.15)'}; color: ${tel.kvm.state === 'active' ? 'var(--ok2)' : 'var(--danger)'};">
                ${escapeHtml(tel.kvm.badge || 'KVM')}
              </span>
            </div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); line-height: 1.5;">
              ${escapeHtml(tel.kvm.details || 'Linux KVM hypervisor acceleration provides near bare-metal guest performance.')}
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-top: 6px;">
              <div style="background: var(--zn-shade-20); padding: 8px 12px; border-radius: 6px;">
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">CPU Host Threads</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--zn-text-strong); margin-top: 2px;">${tel.cpu?.host_threads || 8} Threads</div>
              </div>
              <div style="background: var(--zn-shade-20); padding: 8px 12px; border-radius: 6px;">
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">vhost-net Acceleration</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--ok2); margin-top: 2px;">Supported</div>
              </div>
              <div style="background: var(--zn-shade-20); padding: 8px 12px; border-radius: 6px;">
                <div style="font-size: var(--zn-fs-xs); color: var(--muted);">Default Network Bridge</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--lt-ink-brand, var(--accent-cyan)); margin-top: 2px;">br0 / virbr0</div>
              </div>
            </div>
          </div>
        `;
      }
    } catch (err) {
      console.warn('Failed to load VM telemetry in Settings:', err);
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
    if (targetId === 'mgmt-sec-docker' && typeof window.openContainersManager === 'function') {
      // Apps live in one place, the Apps window (UX-4)
      window.openContainersManager({ view: desiredSubPane === 'mgmt-pane-docker-catalog' ? 'catalog' : 'installed' });
      return;
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

    const sidebarItems = document.querySelectorAll('.mgmt-sidebar-item');
    const paneItem = desiredSubPane && Array.from(sidebarItems).find((b) => b.dataset.mgmtPane === desiredSubPane);
    const isCurrentItem = (b) => (paneItem ? b === paneItem : b.dataset.mgmtTarget === targetId && !b.dataset.mgmtPane);
    markCurrent(sidebarItems, isCurrentItem);
    document.querySelectorAll('.mgmt-sidebar-item').forEach((b) => {
      const isActive = isCurrentItem(b);
      b.classList.toggle('active', isActive);
      if (isActive && typeof b.scrollIntoView === 'function') {
        try { b.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
      }
    });

    let sectionName = t('mgmt.title', 'Settings');
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

  wireTablists(document.getElementById('management-window') || document);

  document.querySelectorAll('.mgmt-sidebar-item').forEach((item) => {
    item.addEventListener('click', () => {
      if (typeof item.scrollIntoView === 'function') {
        try { item.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); } catch (_) {}
      }
      const targetId = item.dataset.mgmtTarget;
      if (item.dataset.mgmtAction === 'files') {
        if (typeof window.openFileManager === 'function') window.openFileManager();
        return;
      }
      if (targetId === 'management-hub-view') {
        showHub();
      } else if (targetId) {
        showSection(targetId, item.dataset.mgmtPane || null);
      }
      saveOpenWindowsState();
    });
  });

  installAdvancedSwitch(); // UX-2: the everyday places, with the rest behind Advanced
  installHealthSignal(); // the opt-in anonymous weekly report, under Software Updates

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
    // a window, not a modal: Tab may leave it; Esc closes it (UX-30)
    _unbindMgmtTrap = trapFocus(win, () => {
      const cBtn = document.getElementById('management-close');
      if (cBtn) cBtn.click();
    }, { trap: false });

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
      showToast(t('toast.ingest_history_refreshed', 'Card copies refreshed.'), 'info');
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
      showToast(t('toast.ups_telemetry_refreshed', 'UPS readings refreshed.'), 'info');
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
      showToast(t('toast.chassis_digital_twin_refreshed', 'Drive bays refreshed.'), 'info');
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
            submitBtn.textContent = t('ui.saving', 'Saving...');
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
            submitBtn.textContent = t('ui.save_pipeline', 'Save Pipeline');
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

  const btnChanBeta = document.getElementById('btn-channel-beta');
  if (btnChanBeta) {
    btnChanBeta.addEventListener('click', () => {
      setUpdateChannel('beta');
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
      presetCatalogSearch('reverse proxy');
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

  // Backup jobs & snapshots event bindings
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
    destTypeSelect.addEventListener('change', () => syncBackupJobForm());
  }
  const kindSelect = document.getElementById('backup-job-kind');
  if (kindSelect) kindSelect.addEventListener('change', () => syncBackupJobForm());

  if (formBackupJob) {
    formBackupJob.addEventListener('submit', async (e) => {
      e.preventDefault();
      const kind = document.getElementById('backup-job-kind')?.value || 'data';
      const payload = {
        name: document.getElementById('backup-job-name')?.value.trim() || 'Untitled Backup Task',
        kind,
        local_path: document.getElementById('backup-job-local-path')?.value.trim() || '',
        source_subvolume: kind === 'config' ? '' : document.getElementById('backup-job-subvolume')?.value.trim() || '',
        destination_type: document.getElementById('backup-job-dest-type')?.value || 'remote',
        remote_name: document.getElementById('backup-job-remote-name')?.value.trim() || '',
        remote_path: document.getElementById('backup-job-remote-path')?.value.trim() || '',
        schedule: document.getElementById('backup-job-schedule')?.value || 'daily',
        retention_count: parseInt(document.getElementById('backup-job-retention')?.value, 10) || 7,
        enabled: !!document.getElementById('backup-job-enabled')?.checked,
      };
      const passphrase = document.getElementById('backup-job-passphrase')?.value || '';
      if (kind === 'config' && passphrase) payload.encryption_password = passphrase;

      try {
        await api.post('/api/backup/schedule', payload);
        showToast(t('toast.hyper_backup_pipeline_saved_successfully', 'Backup job saved.'), 'success');
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

export const initManagementWindow = initManagement;
