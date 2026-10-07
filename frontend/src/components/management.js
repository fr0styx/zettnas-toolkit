import { syncWidgetSettingsUI } from './widgets.js';
/**
 * ZettNAS Toolkit - System Management Window Controller
 * Manages the dedicated System Management desktop window, hub app grid,
 * category navigation, and card views (Wallpaper, Metrics, Events, Security).
 */
import { fetchAndRenderMetrics } from './metrics-chart.js';
import { bringToFront, DockManager, makeDraggable } from './dock.js';
import { state } from '../state.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { trapFocus, escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

let _activeProfile = 'balanced';
let _unbindMgmtTrap = null;

export function updateManagementTelemetry(stats) {
  if (!stats) return;
  const overlay = document.getElementById('management-modal-overlay');
  if (overlay && (!overlay.classList.contains('open') || overlay.classList.contains('window-minimized') || overlay.style.display === 'none')) {
    return;
  }
  const unraid = stats.unraid;
  if (unraid && unraid.available) {
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
    if (srvEl) srvEl.textContent = `${unraid.server_name || 'NAS'} (${unraid.model || stats.chassis?.model || 'D6U'})`;
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
  }

  // Update Docker pill in Hub and Left Sidebar
  if (stats.docker && Array.isArray(stats.docker)) {
    const runningCount = stats.docker.filter(c => c.state === 'running').length;
    const dockPill = document.getElementById('mgmt-hub-docker-pill');
    if (dockPill) dockPill.textContent = `${runningCount} Active`;
    const sideDockBadge = document.getElementById('mgmt-sidebar-docker-badge');
    if (sideDockBadge) sideDockBadge.textContent = `${runningCount} Active`;
  }

  // Update UPS pill, sidebar badge, and telemetry if active
  if (stats.ups) {
    const upsVal = stats.ups.battery_charge_pct != null ? `${stats.ups.battery_charge_pct}%` : (stats.ups.available ? 'Active' : 'Offline');
    const upsPill = document.getElementById('mgmt-hub-ups-pill');
    if (upsPill) upsPill.textContent = upsVal;
    const sideUpsBadge = document.getElementById('mgmt-sidebar-ups-badge');
    if (sideUpsBadge) sideUpsBadge.textContent = upsVal;

    const statusEl = document.getElementById('mgmt-ups-status');
    const modelEl = document.getElementById('mgmt-ups-model');
    const chargeEl = document.getElementById('mgmt-ups-charge');
    const runtimeEl = document.getElementById('mgmt-ups-runtime');
    const loadEl = document.getElementById('mgmt-ups-load');
    const linevEl = document.getElementById('mgmt-ups-linev');

    if (statusEl) {
      statusEl.textContent = stats.ups.status || (stats.ups.available ? 'ONLINE' : 'Offline');
      statusEl.style.color = stats.ups.available ? 'var(--ok2)' : 'var(--warn)';
    }
    if (modelEl) modelEl.textContent = stats.ups.model || 'Generic UPS';
    if (chargeEl) {
      chargeEl.textContent = stats.ups.battery_charge_pct != null ? `${stats.ups.battery_charge_pct}%` : 'N/A';
      chargeEl.style.color = (stats.ups.battery_charge_pct == null || stats.ups.battery_charge_pct > 30) ? 'var(--ok2)' : 'var(--crit)';
    }
    if (runtimeEl) runtimeEl.textContent = stats.ups.time_left_min != null ? `${stats.ups.time_left_min} min` : 'N/A';
    if (loadEl) loadEl.textContent = stats.ups.load_pct != null ? `${stats.ups.load_pct}%` : 'N/A';
    if (linevEl) linevEl.textContent = stats.ups.line_volts != null ? `${stats.ups.line_volts} V` : 'N/A';
  }

  if (stats.fan_control && stats.fan_control.profile) {
    const prof = stats.fan_control.profile.toLowerCase();
    if (['auto', 'quiet', 'balanced', 'performance'].includes(prof) && prof !== _activeProfile) {
      _activeProfile = prof;
      document.querySelectorAll('.profile-btn').forEach((b) => {
        b.classList.toggle('active', b.dataset.profile === prof);
      });
    }
    const currentPill = document.getElementById('unraid-profile-current-pill');
    if (currentPill) {
      currentPill.textContent = `ACTIVE: ${prof === 'auto' ? 'AUTO DYNAMIC' : prof.toUpperCase()}`;
      currentPill.style.color = prof === 'performance' ? 'var(--warn)' : 'var(--ok2)';
    }
  }
}

export async function fetchAndRenderDockerContainers() {
  const tbody = document.getElementById('docker-containers-tbody');
  if (!tbody) return;
  try {
    const list = await api.get('/api/docker/containers');
    if (!list || list.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:16px;">No Docker containers detected or socket not connected.</td></tr>';
      return;
    }
    const runningCount = list.filter(c => c.state === 'running').length;
    const pill = document.getElementById('mgmt-hub-docker-pill');
    if (pill) pill.textContent = `${runningCount} Active`;
    const sideBadge = document.getElementById('mgmt-sidebar-docker-badge');
    if (sideBadge) sideBadge.textContent = `${runningCount} Active`;

    tbody.innerHTML = list.map((c) => {
      const isRunning = c.state === 'running';
      const badgeColor = isRunning ? 'var(--ok2)' : 'var(--muted)';
      const badgeBg = isRunning ? 'rgba(37, 194, 160, 0.15)' : 'rgba(255, 255, 255, 0.05)';
      const actions = isRunning
        ? `
          <button class="btn-container-act btn-docker-restart" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="restart" title="Restart ${escapeHtml(c.name)}">🔄</button>
          <button class="btn-container-act btn-docker-stop" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="stop" title="Stop ${escapeHtml(c.name)}">⏹</button>
        `
        : `
          <button class="btn-container-act btn-docker-start" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}" data-action="start" title="Start ${escapeHtml(c.name)}">▶</button>
        `;

      const idShort = c.id ? c.id.slice(0, 12) : '';
      return `
        <tr>
          <td>
            <strong style="color:#fff; display:block; font-size:11.5px;">${escapeHtml(c.name)}</strong>
            <code style="font-size:9.5px; color:var(--muted); font-family:var(--font-mono, monospace);">${escapeHtml(idShort)}</code>
          </td>
          <td style="color:var(--muted); font-size:10px; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.image)}">${escapeHtml(c.image)}</td>
          <td><span style="display:inline-block; padding:2px 6px; border-radius:4px; font-size:9.5px; font-weight:700; background:${badgeBg}; color:${badgeColor}; text-transform:uppercase;">${escapeHtml(c.state)}</span></td>
          <td style="font-size:10.5px; color:#cbd5e1; max-width:130px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(c.status)}">${escapeHtml(c.status)}</td>
          <td style="text-align:right; white-space:nowrap;">${actions}</td>
        </tr>
      `;
    }).join('');

    tbody.querySelectorAll('.btn-container-act').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const cid = btn.dataset.id;
        const cname = btn.dataset.name;
        const act = btn.dataset.action;
        if (!cid || !act) return;

        btn.disabled = true;
        btn.style.opacity = '0.5';
        showToast(`${act.toUpperCase()} request sent for ${cname}...`, 'info');

        try {
          await api.post(`/api/docker/containers/${encodeURIComponent(cid)}/action`, { action: act });
          showToast(`Container "${cname}" successfully ${act}ed.`, 'success');
          await fetchAndRenderDockerContainers();
        } catch (err) {
          showToast(`Failed to ${act} container: ${err.message}`, 'error');
          btn.disabled = false;
          btn.style.opacity = '1';
        }
      });
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--crit); padding:16px;">Failed to load containers: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export async function fetchAndRenderUpsTelemetry() {
  try {
    const ups = await api.get('/api/ups');
    if (!ups) return;
    const statusEl = document.getElementById('mgmt-ups-status');
    const modelEl = document.getElementById('mgmt-ups-model');
    const chargeEl = document.getElementById('mgmt-ups-charge');
    const runtimeEl = document.getElementById('mgmt-ups-runtime');
    const loadEl = document.getElementById('mgmt-ups-load');
    const linevEl = document.getElementById('mgmt-ups-linev');
    const pill = document.getElementById('mgmt-hub-ups-pill');

    if (statusEl) {
      statusEl.textContent = ups.status || (ups.available ? 'ONLINE' : 'Offline');
      statusEl.style.color = ups.available ? 'var(--ok2)' : 'var(--warn)';
    }
    if (pill) {
      pill.textContent = ups.battery_charge_pct != null ? `${ups.battery_charge_pct}%` : (ups.available ? 'Active' : 'Offline');
    }
    if (modelEl) modelEl.textContent = ups.model || 'Generic UPS';
    if (chargeEl) {
      chargeEl.textContent = ups.battery_charge_pct != null ? `${ups.battery_charge_pct}%` : 'N/A';
      chargeEl.style.color = (ups.battery_charge_pct == null || ups.battery_charge_pct > 30) ? 'var(--ok2)' : 'var(--crit)';
    }
    if (runtimeEl) runtimeEl.textContent = ups.time_left_min != null ? `${ups.time_left_min} min` : 'N/A';
    if (loadEl) loadEl.textContent = ups.load_pct != null ? `${ups.load_pct}%` : 'N/A';
    if (linevEl) linevEl.textContent = ups.line_volts != null ? `${ups.line_volts} V` : 'N/A';
  } catch (err) {
    console.debug('Failed to fetch UPS telemetry:', err);
  }
}

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

  // Minimize button
  const minBtn = document.getElementById('management-min');
  if (minBtn) {
    const handleMin = (e) => {
      if (e && e.type === 'touchend') { e.preventDefault(); e.stopPropagation(); }
      DockManager.minimize('management');
    };
    minBtn.addEventListener('click', handleMin);
    minBtn.addEventListener('touchend', handleMin);
  }

  // Maximize button
  const maxBtn = document.getElementById('management-max');
  let _isMaximized = false;
  let _preMaxBounds = null;
  if (maxBtn) {
    const handleMax = (e) => {
      if (e) { e.preventDefault(); e.stopPropagation(); }
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
        _isMaximized = true;
      } else {
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
    if (hubView) hubView.style.display = 'grid';
    if (detailContainer) detailContainer.style.display = 'none';
    if (headerNav) headerNav.style.display = 'none';
    if (backBtn) backBtn.style.display = 'none';
    if (titleText) titleText.textContent = t('mgmt.title', 'System Management');
    document.querySelectorAll('.mgmt-category-tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.mgmt-sidebar-item').forEach((b) => {
      b.classList.toggle('active', b.dataset.mgmtTarget === 'management-hub-view');
    });
    document.querySelectorAll('.mgmt-detail-card').forEach((c) => (c.style.display = 'none'));
  }

  
  const SUBPANE_MAP = {
    'mgmt-pane-wallpaper': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
    'mgmt-pane-widgets': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-widgets' },
    'mgmt-sec-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
    'mgmt-pane-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
    'mgmt-sec-copy': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-copy' },
    'mgmt-pane-copy': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-copy' },
    'mgmt-sec-unraid': { section: 'mgmt-sec-services', pane: 'mgmt-pane-unraid' },
    'mgmt-pane-unraid': { section: 'mgmt-sec-services', pane: 'mgmt-pane-unraid' },
    'mgmt-sec-docker': { section: 'mgmt-sec-services', pane: 'mgmt-pane-docker' },
    'mgmt-pane-docker': { section: 'mgmt-sec-services', pane: 'mgmt-pane-docker' },
    'mgmt-sec-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
    'mgmt-pane-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
    'mgmt-sec-events': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-events' },
    'mgmt-pane-events': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-events' },
    'mgmt-sec-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-system' },
    'mgmt-pane-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-system' },
  };

  function triggerActiveSubTab(parentId) {
    const parent = document.getElementById(parentId);
    if (!parent) return;
    const activeTabBtn = parent.querySelector('.mgmt-inner-tab.active');
    if (activeTabBtn) {
      const paneId = activeTabBtn.dataset.tabTarget;
      triggerSubTabLoad(paneId);
    }
  }

  function triggerSubTabLoad(paneId) {
    if (paneId === 'mgmt-pane-widgets') {
      if (typeof syncWidgetSettingsUI === 'function') syncWidgetSettingsUI();
    } else if (paneId === 'mgmt-pane-metrics') {
      setTimeout(fetchAndRenderMetrics, 50);
    } else if (paneId === 'mgmt-pane-copy') {
      fetchAndRenderCopyHistory();
    } else if (paneId === 'mgmt-pane-unraid') {
      if (state.lastStats) updateManagementTelemetry(state.lastStats);
    } else if (paneId === 'mgmt-pane-docker') {
      fetchAndRenderDockerContainers();
    } else if (paneId === 'mgmt-pane-system') {
      fetchAPITokens();
    }
  }

  function showSection(targetId) {
    let desiredSubPane = null;
    if (SUBPANE_MAP[targetId]) {
      desiredSubPane = SUBPANE_MAP[targetId].pane;
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
      b.classList.toggle('active', b.dataset.mgmtTarget === targetId);
    });

    let sectionName = t('mgmt.title', 'System Management');
    if (targetId === 'mgmt-sec-wallpaper') {
      sectionName = t('mgmt.appearance_title', 'Appearance');
      triggerActiveSubTab(targetId);
    } else if (targetId === 'mgmt-sec-activity') {
      sectionName = t('mgmt.activity_title', 'Activity Monitor');
    } else if (targetId === 'mgmt-sec-services') {
      sectionName = t('mgmt.services_title', 'Services');
    } else if (targetId === 'mgmt-sec-ups') {
      sectionName = t('mgmt.sidebar_ups', 'UPS & Power');
      if (typeof fetchAndRenderUpsTelemetry === 'function') fetchAndRenderUpsTelemetry();
      else if (typeof fetchAndRenderUPS === 'function') fetchAndRenderUPS();
    } else if (targetId === 'mgmt-sec-system-group') {
      sectionName = t('mgmt.system_title', 'System');
    }

    if (titleText) titleText.textContent = sectionName;

    if (desiredSubPane) {
      const parentCard = document.getElementById(targetId);
      if (parentCard) {
        parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
          t.classList.toggle('active', t.dataset.tabTarget === desiredSubPane);
        });
        parentCard.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
          p.style.display = p.id === desiredSubPane ? 'block' : 'none';
        });
        triggerSubTabLoad(desiredSubPane);
      }
    } else {
      triggerActiveSubTab(targetId);
    }
  }

  // Left sidebar items click listener

  document.querySelectorAll('.mgmt-inner-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const parentCard = tab.closest('.mgmt-detail-card');
      if (!parentCard) return;
      
      // Update tab buttons
      parentCard.querySelectorAll('.mgmt-inner-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      
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
    });
  });

  document.querySelectorAll('.mgmt-sidebar-item').forEach((item) => {
    item.addEventListener('click', () => {
      const targetId = item.dataset.mgmtTarget;
      if (targetId === 'management-hub-view') {
        showHub();
      } else if (targetId) {
        showSection(targetId);
      }
    });
  });

  // Hub cards click listener
  document.querySelectorAll('.mgmt-app-card').forEach((card) => {
    card.addEventListener('click', () => {
      const targetId = card.dataset.mgmtTarget;
      if (targetId) showSection(targetId);
    });
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const targetId = card.dataset.mgmtTarget;
        if (targetId) showSection(targetId);
      }
    });
  });

  // Header quick tabs click listener
  document.querySelectorAll('.mgmt-category-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.mgmtTarget;
      if (targetId) showSection(targetId);
    });
  });

  // Back button click listener
  if (backBtn) {
    backBtn.addEventListener('click', showHub);
  }

  // Global helper to open / focus Management window
  window.openManagementWindow = (sectionId = null) => {
    if (!DockManager.windows['management']) {
      DockManager.register('management', overlay, '#i-management', 'Management');
    }
    if (DockManager.windows['management']?.minimized || overlay.style.display === 'none' || !overlay.classList.contains('open')) {
      DockManager.restore('management');
      overlay.style.removeProperty('display');
      overlay.classList.add('open');
      win.classList.remove('window-minimized');
      if (state.latestStats) updateManagementTelemetry(state.latestStats);
    }
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

    if (sectionId) {
      showSection(sectionId);
    } else {
      showHub();
    }
  };

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

  // Profile buttons listener
  document.querySelectorAll('.profile-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const p = btn.dataset.profile;
      if (!p) return;
      _activeProfile = p;
      document.querySelectorAll('.profile-btn').forEach((b) => b.classList.toggle('active', b === btn));
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
  });

  // Copy history refresh button
  const refreshHistoryBtn = document.getElementById('btn-refresh-copy-history');
  if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener('click', () => {
      fetchAndRenderCopyHistory();
      showToast('Ingest history refreshed.', 'info');
    });
  }

  // Docker containers refresh button
  const refreshDockerBtn = document.getElementById('btn-refresh-docker');
  if (refreshDockerBtn) {
    refreshDockerBtn.addEventListener('click', () => {
      fetchAndRenderDockerContainers();
      showToast('Docker containers refreshed.', 'info');
    });
  }

  // UPS telemetry refresh button
  const refreshUpsBtn = document.getElementById('btn-refresh-ups');
  if (refreshUpsBtn) {
    refreshUpsBtn.addEventListener('click', () => {
      fetchAndRenderUpsTelemetry();
      showToast('UPS telemetry refreshed.', 'info');
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
}

