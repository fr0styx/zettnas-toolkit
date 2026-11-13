/**
 * Mission Control: Copy history, replication, VPNs, topology, ports, bonds, bridges, VLANs, host IP.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { applyNetCaps, canChange, portPayload, setNetCaps } from './net-host.js';
import { installNeedsTailscale } from './needs-tailscale.js';
import { api } from '../../api.js';
import { initNetworkPortsInspector, fetchListeningPorts } from '../network-manager.js';
import { showToast, showConfirmToast } from '../../toast.js';
import { escapeHtml, copyText } from '../../utils.js';
import { t } from '../../i18n.js';
import { stateBlock } from '../state-block.js';
import { showNetDialog, hideNetDialog } from './net-dialog.js';
import { renderHome, renderPortRows } from './network-home.js';

// An icon next to translated words: screen readers skip it and the words stay plain (UX-35)
const ico = (e) => `<span aria-hidden="true">${e}</span>`;
import { formatBytes as formatSize, formatDateTime, formatFixed } from '../../format.js';
import { setIconLabel } from '../../ui/primitives.js';

export async function fetchAndRenderCopyHistory() {
  const tbody = document.getElementById('copy-history-tbody');
  if (!tbody) return;
  try {
    const history = await api.get('/api/copy/history?limit=30');
    if (!history || history.length === 0) {
      tbody.innerHTML = '<tr><td class="nw-muted-center" colspan="7">' + t('net.no_imports', 'No imports recorded yet.') + '</td></tr>';
      return;
    }
    tbody.innerHTML = history.map((item) => {
      const d = new Date(item.ts * 1000);
      const timeStr = formatDateTime(d);
      const sizeMB = formatFixed(item.total_bytes / (1024 * 1024), 1);
      const durStr = item.duration_sec ? `${formatFixed(item.duration_sec, 1)}s` : '--';
      const isSuccess = item.status === 'success';
      const statusColor = isSuccess ? 'var(--ok2)' : item.status === 'aborted' ? 'var(--warn)' : 'var(--crit)';
      const checksumBadge = item.checksum_verified
        ? '<span class="checksum-badge">✓ SHA-256</span>'
        : '<span class="nw-xs-muted">' + t('ci.none', 'None') + '</span>';
      const destName = item.dest ? item.dest.split('/').filter(Boolean).pop() || item.dest : '/';

      return `
        <tr>
          <td class="nw-xs-muted-mono">${timeStr}</td>
          <td><strong>${(item.source || 'sd').toUpperCase()}</strong></td>
          <td class="nw-x" title="${escapeHtml(item.dest)}">${escapeHtml(destName)}</td>
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
    tbody.innerHTML = `<tr><td class="nw-crit-center" colspan="7">${escapeHtml(t('net.history_failed', 'Could not load the history: {error}', { error: e.message }))}</td></tr>`;
  }
}

let replicationTabChecked = false;

/** REL-5: the Replication tab shows only where this NAS can replicate its pools, or keeps jobs. */
export async function revealReplicationTab() {
  if (replicationTabChecked) return;
  replicationTabChecked = true;
  try {
    const res = await api.get('/api/storage/replication/jobs');
    const tab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-storage-replication"]');
    if (tab) tab.style.display = res.available || (res.jobs || []).length ? '' : 'none';
  } catch (_) {
    replicationTabChecked = false; // try again next time the storage section opens
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
    if (jobsRes.available === false && jobsRes.reason) {
      const cell = document.createElement('td');
      cell.colSpan = 8;
      cell.className = 'repl-note';
      cell.textContent = jobsRes.reason;
      const row = document.createElement('tr');
      row.appendChild(cell);
      tbody.replaceChildren(row);
    } else if (jobs.length === 0) {
      tbody.innerHTML = `<tr><td class="nw-muted-center-2" colspan="8">${t('net.no_repl', 'No replication jobs yet. Create one with the button above.')}</td></tr>`;
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
            <td><span class="badge nw-mono">${escapeHtml(j.source_pool)}/${escapeHtml(j.source_dataset || '')}</span></td>
            <td>${tgtDesc}</td>
            <td><span class="mgmt-app-pill nw-xs">${escapeHtml(j.schedule || 'manual')}</span></td>
            <td>${j.bandwidth_limit_kbps ? `${Math.round(j.bandwidth_limit_kbps / 1024)} MB/s` : 'Unlimited'}</td>
            <td>${j.retention_count || 14} snaps</td>
            <td><span class="mgmt-app-pill ${j.last_status === 'error' ? 'text-crit' : j.last_status === 'success' ? 'text-emerald' : 'text-muted'}" title="${escapeHtml(j.last_error || '')}">${escapeHtml(j.last_status || 'idle')}</span></td>
            <td class="nw-x-2">
              <button class="btn-pill-toggle btn-run-repl is-small nw-x-3" data-id="${escapeHtml(j.id)}" title="${t('ui.execute_replication_now', 'Execute Replication Now')}">${ico('▶')} ${t('ci.run', 'Run')}</button>
              <button class="btn-pill-toggle btn-del-repl is-danger is-small" data-id="${escapeHtml(j.id)}" title="${t('ui.delete_pipeline', 'Delete Pipeline')}">🗑️</button>
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
            setIconLabel(btn, '⏳', t('ui.running_2', 'Running...'));
            await api.post(`/api/storage/replication/jobs/${encodeURIComponent(id)}/run`);
            showToast(t('toast.replication_pipeline_dispatched', 'Replication pipeline \'{id}\' dispatched.', { id: id }), 'success');
            setTimeout(fetchAndRenderReplication, 1000);
          } catch (e) {
            showToast(t('toast.replication_failed', 'Replication failed: {message}', { message: e.message }), 'error');
          } finally {
            btn.disabled = false;
            setIconLabel(btn, '▶', t('ui.run', 'Run'));
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
        histTbody.innerHTML = `<tr><td class="nw-muted-center" colspan="6">${t('net.no_repl_history', 'No replication runs yet.')}</td></tr>`;
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
              <td>${h.bytes_transferred ? formatFixed(h.bytes_transferred / (1024 * 1024), 1) + ' MB' : '--'}</td>
              <td>${h.duration_seconds ? `${formatFixed(h.duration_seconds, 1)}s` : '--'}</td>
              <td><span class="mgmt-app-pill ${isOk ? 'text-emerald' : 'text-crimson'}">${isOk ? '✓ Success' : 'Failed'}</span></td>
            </tr>
          `;
          })
          .join('');
      }
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td class="nw-crit-center" colspan="8">${escapeHtml(t('net.repl_failed', 'Could not load the replication jobs: {error}', { error: err.message }))}</td></tr>`;
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
    countPill.textContent = t('net.peers_count', '{online} online / {total} total', { online: onlineCount, total: peersArr.length });
  }

  if (filtered.length === 0) {
    tbody.innerHTML =
      '<tr><td class="nw-muted-center-3" colspan="5">' + t('net.no_peer_match', 'No devices match the search.') + '</td></tr>';
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
        ? '<span style="color:var(--lt-t-3bf58bff, #3bf58b); font-weight:600;">' + ico('⚡') + ' ' + t('net.direct', 'Direct (P2P)') + '</span>'
        : p.relay
          ? `<span style="color:var(--lt-t-f59e0bff, #f59e0b);">🌐 DERP (${escapeHtml(p.relay)})</span>`
          : '<span class="nw-muted">--</span>';

      const statusPill = p.online
        ? '<span class="mgmt-app-pill" style="color:var(--lt-t-3bf58bff, #3bf58b); background:var(--lt-b-3bf58b1f, rgba(59,245,139,0.12)); font-size:var(--kb-fs-xs); padding:2px 7px;">' + t('net.online', 'Online') + '</span>'
        : '<span class="mgmt-app-pill nw-xs-muted-box">' + t('net.offline', 'Offline') + '</span>';

      return `
      <tr class="nw-xs-box">
        <td class="nw-x-4">
          <div class="nw-bold-strong">${escapeHtml(p.name || p.hostname || 'Unnamed')}</div>
          ${p.dns_name ? `<div class="nw-xs-muted-2">${escapeHtml(p.dns_name)}</div>` : ''}
        </td>
        <td class="nw-x-5">${osLabel}</td>
        <td class="nw-x-4"><code class="nw-xs-accent">${escapeHtml(p.ip || '--')}</code></td>
        <td class="nw-x-4">${routeBadge}</td>
        <td class="nw-x-4">${statusPill}</td>
      </tr>
    `;
    })
    .join('');
}

/** How long until the NAS's Tailscale key needs a new sign-in, as a sentence and a tone. */
export function keyExpiryText(ts) {
  const days = ts?.key_expiry_days;
  if (days === null || days === undefined) return { text: t('net.ts_key_no_expiry', 'Never expires'), tone: 'ok' };
  if (days > 14) return { text: t('net.expiry_days', 'Expires in {count, plural, one {# day} other {# days}} ({date})', { count: days, date: (ts.key_expiry || '').slice(0, 10) }), tone: 'ok' };
  if (days > 0) return { text: t('net.expiry_soon', 'Expires in {count, plural, one {# day} other {# days}}', { count: days }), tone: 'warn' };
  return { text: t('net.ts_key_expired', 'Expired: sign in again'), tone: 'crit' };
}

/** The exit node's state in words (D5: "Use your home internet when away"). */
export function homeInternetText(ts) {
  if (ts?.is_exit_node) return t('net.ts_exit_in_use', 'In use');
  if (ts?.exit_node_approved) return t('net.ts_exit_ready', 'Ready: your devices can choose this NAS');
  if (ts?.advertise_exit_node) return t('net.pending_approval', 'Waiting for approval in the admin console');
  return t('net.ts_exit_off', 'Off');
}

let _tsPeers = [];

/**
 * The details under "Use from anywhere" (SET-16): this NAS on the tailnet, signing in again,
 * reaching other things at home, home internet when away, and the devices. Connecting and
 * disconnecting live in the card above; WireGuard, SSH, Serve, Taildrop and Ping were removed.
 */
/** One load at a time: a second call while one runs gets the same answer (network report C4: the
 *  section and its tab each started one, so every open read the same things twice). */
export function sharedLoad(load) {
  let running = null;
  return () => {
    if (!running) running = Promise.resolve(load()).finally(() => (running = null));
    return running;
  };
}

export const fetchAndRenderTailscaleDetails = sharedLoad(loadTailscaleDetails);

async function loadTailscaleDetails() {
  const box = document.getElementById('ts-details');
  const mesh = await api.get('/api/network/mesh-vpn').catch(() => null);
  const ts = mesh?.tailscale || null;
  if (box) box.hidden = !(ts && ts.active);
  if (!ts || !ts.active) return;

  const set = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };
  set('ts-connection-pill', t('ldap.test_ok', 'Connected'));
  set('ts-ipv4-display', ts.ipv4 || '--');
  set('ts-tailnet-display', ts.tailnet || '--');
  set('ts-hostname-display', ts.hostname || '--');
  set('ts-peers-display', t('net.ts_devices_n', '{n, plural, one {# device} other {# devices}}', { n: ts.peers_count || 0 }));
  const copyIp = document.getElementById('btn-copy-ts-ip');
  if (copyIp) copyIp.style.display = ts.ipv4 ? '' : 'none';
  const expiry = keyExpiryText(ts);
  const expiryEl = document.getElementById('ts-key-expiry-display');
  if (expiryEl) {
    expiryEl.textContent = expiry.text;
    expiryEl.dataset.tone = expiry.tone;
  }
  const reauth = document.getElementById('btn-ts-reauth');
  if (reauth) reauth.style.display = '';

  const routesToggle = /** @type {HTMLInputElement | null} */ (document.getElementById('ts-subnet-router-toggle'));
  const routesInput = /** @type {HTMLInputElement | null} */ (document.getElementById('ts-subnet-routes-input'));
  if (routesToggle) routesToggle.checked = Boolean(ts.is_subnet_router);
  if (routesInput && document.activeElement !== routesInput) {
    const advertised = (ts.advertised_routes || []).filter((r) => r !== '0.0.0.0/0' && r !== '::/0').join(', ');
    const detected = (ts.detected_subnets || []).join(', ');
    routesInput.value = advertised || detected;
    if (!advertised && detected) routesInput.placeholder = detected;
  }
  const exitToggle = /** @type {HTMLInputElement | null} */ (document.getElementById('ts-exit-node-toggle'));
  if (exitToggle) exitToggle.checked = Boolean(ts.advertise_exit_node);
  set('ts-exit-node-pill', homeInternetText(ts));
  const hint = document.getElementById('ts-exit-node-approval-hint');
  if (hint) hint.style.display = ts.advertise_exit_node && !ts.exit_node_approved ? '' : 'none';

  _tsPeers = ts.peers || [];
  const search = /** @type {HTMLInputElement | null} */ (document.getElementById('ts-peer-search'));
  renderTailscalePeersTable(_tsPeers, search ? search.value : '');
  bindTailscaleDetails();
}

function bindTailscaleDetails() {
  const once = (id, event, fn) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.bound) return;
    el.dataset.bound = '1';
    el.addEventListener(event, fn);
  };
  once('btn-copy-ts-ip', 'click', () => {
    const ip = document.getElementById('ts-ipv4-display')?.textContent?.trim() || '';
    if (!ip || ip === '--') return;
    copyText(ip)
      .then(() => showToast(t('toast.copied_tailscale_ip', 'Copied Tailscale IP: {ip}', { ip }), 'success'))
      .catch(() => showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error'));
  });
  once('btn-ts-reauth', 'click', async () => {
    try {
      const res = await api.post('/api/network/mesh-vpn/tailscale/reauth');
      if (res?.auth_url) {
        window.open(res.auth_url, '_blank', 'noopener,noreferrer');
        showToast(t('toast.re_authentication_initiated_complete_in_your', 'Re-authentication initiated. Complete in your browser.'), 'info');
      } else {
        showToast(t('toast.tailscale_node_re_authenticated_successfully', 'Tailscale node re-authenticated successfully.'), 'success');
      }
      fetchAndRenderTailscaleDetails();
    } catch (err) {
      showToast(t('toast.re_authentication_failed', 'Re-authentication failed: {error}', { error: err.message }), 'error');
    }
  });
  const saveRoutes = async () => {
    const routes = /** @type {HTMLInputElement | null} */ (document.getElementById('ts-subnet-routes-input'))?.value.trim() || '';
    const enabled = Boolean(/** @type {HTMLInputElement | null} */ (document.getElementById('ts-subnet-router-toggle'))?.checked);
    try {
      await api.post('/api/network/mesh-vpn/tailscale/set-routes', { routes, enabled });
      showToast(enabled ? t('net.ts_reach_home_on', 'Your devices can now reach {routes} through this NAS.', { routes }) : t('net.ts_reach_home_off', 'Reaching things at home is off.'), 'success');
      fetchAndRenderTailscaleDetails();
    } catch (e) {
      showToast(t('toast.failed_to_update_subnet_routes', 'Failed to update subnet routes: {message}', { message: e.message }), 'error');
    }
  };
  once('btn-ts-save-routes', 'click', saveRoutes);
  once('ts-subnet-router-toggle', 'change', saveRoutes);
  once('ts-exit-node-toggle', 'change', async (e) => {
    const enabled = Boolean(/** @type {HTMLInputElement} */ (e.currentTarget).checked);
    try {
      await api.post('/api/network/mesh-vpn/tailscale/set-exit-node', { enabled });
      showToast(enabled ? t('net.ts_home_internet_on', 'This NAS now offers your home internet to your devices.') : t('net.ts_home_internet_off', 'Home internet when away is off.'), 'success');
      fetchAndRenderTailscaleDetails();
    } catch (err) {
      showToast(t('toast.failed_to_set_exit_node', 'Failed to set exit node: {message}', { message: err.message }), 'error');
    }
  });
  once('ts-peer-search', 'input', (e) => renderTailscalePeersTable(_tsPeers, /** @type {HTMLInputElement} */ (e.currentTarget).value));
  once('btn-refresh-wireguard', 'click', () => fetchAndRenderTailscaleDetails());
}

export const fetchAndRenderNetworkTopology = sharedLoad(loadNetworkTopology);

async function loadNetworkTopology() {
  const homeBox = document.getElementById('net-home');
  const portRows = document.getElementById('net-port-rows');
  const bridgesContainer = document.getElementById('network-bridges-container');
  const dockerContainer = document.getElementById('network-docker-container');

  const fmtBytes = (bytes) => formatSize(bytes);

  try {
    const topo = await api.get('/api/system/network-topology');
    if (!topo || topo.status !== 'ok') {
      showTopologyFailed(topo?.message || t('toast.unknown_error', 'Unknown error'));
      return;
    }

    setNetCaps(topo.host); // what this host lets Kiboto change (SET-16, D2)
    const summary = topo.summary || {};
    const physical = topo.physical_interfaces || [];
    const bonds = topo.bonds || [];
    const bridges = topo.bridges || [];
    const dockerNets = topo.docker_networks || [];

    // 1. This NAS at home, 2. one row per port (SET-24 m)
    renderHome(homeBox, summary);
    renderPortRows(portRows, physical, openNetworkPortModal);

    // 4. Render Virtual Switches, Bonds & Bridges
    if (bridgesContainer) {
      const items = [];
      // Bridges
      bridges.forEach((br) => {
        items.push(`
          <div class="network-bridge-card">
            <div class="network-bridge-header">
              <div class="nw-row-2">
                <span class="network-bridge-name">${escapeHtml(t('net.bridge', 'Bridge: {name}', { name: br.name }))}</span>
                <span class="switch-speed-pill ${br.stp ? 'speed-10g' : 'speed-down'} nw-xs-3">STP: ${br.stp ? 'ON' : 'OFF'}</span>
                <span class="nw-xs-muted-mono-2">${t('net.fd', 'Forward delay: {secs} s', { secs: br.forward_delay || 0 })}</span>
              </div>
              <div class="nw-row-3">
                <span class="network-bridge-ip">${escapeHtml(br.ip_address || 'Unassigned IP')}</span>
                <button class="btn-pill-toggle btn-config-bridge is-small" data-bridge="${escapeHtml(br.name)}" style="color: var(--lt-ink-brand, var(--accent-cyan-hi, #4fd8c4)); border-color: rgba(79,216,196,0.3);">${t('net.configure_bridge', 'Configure')}</button>
              </div>
            </div>
            <div class="nw-xs-muted-2">${t('net.members', 'Member ports:')}</div>
            <div class="network-bridge-members">
              ${(br.interfaces || []).map((m) => `<span class="network-member-pill">${escapeHtml(m)}</span>`).join('') || `<span class="nw-xs-muted">${t('net.no_members', 'No members')}</span>`}
            </div>
          </div>
        `);
      });

      // Bonds
      bonds.forEach((b) => {
        items.push(`
          <div class="network-bridge-card">
            <div class="network-bridge-header">
              <div class="nw-row-2">
                <span class="network-bridge-name">${escapeHtml(t('net.bond', 'Bond: {name}', { name: b.name }))}</span>
                <span class="switch-speed-pill speed-10g" title="${escapeHtml(b.mode_title || b.mode_name || b.mode)}">${escapeHtml(b.mode_title || b.mode_name || b.mode || 'Bonding')}</span>
                <span class="nw-xs-muted-mono-2">${b.miimon || 100}ms</span>
              </div>
              <button class="btn-pill-toggle btn-config-bond is-small" data-bond="${escapeHtml(b.name)}" style="color: var(--lt-ink-brand, var(--accent-cyan-hi, #4fd8c4)); border-color: rgba(79,216,196,0.3);">${t('net.configure_bond', 'Configure')}</button>
            </div>
            <div class="nw-xs-muted-2">${t('net.active_port', 'Active port:')} <strong style="color:var(--ok2, #3bf58b);">${escapeHtml(b.active_slave || t('ci.none', 'None'))}</strong></div>
            <div class="network-bridge-members">
              ${(b.slaves || []).map((s) => `<span class="network-member-pill ${s === b.active_slave ? 'active' : ''}">${escapeHtml(s)}</span>`).join('')}
            </div>
          </div>
        `);
      });

      bridgesContainer.innerHTML = items.length > 0 ? items.join('') : `<div class="nw-xs-muted-3">${t('net.no_bridges', 'No virtual bridges or bonds yet.')}</div>`;

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
        vlanTbody.innerHTML = `<tr><td class="nw-muted-center" colspan="8">${t('net.no_vlans', 'No VLANs yet. Add one to tag a port.')}</td></tr>`;
      } else {
        vlanTbody.innerHTML = vlans
          .map((v) => {
            const isUp = Boolean(v.is_up);
            const rxFmt = fmtBytes(v.rx_bytes);
            const txFmt = fmtBytes(v.tx_bytes);

            return `
            <tr>
              <td>
                <div class="nw-row-bold-mono">
                  <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${isUp ? 'var(--ok2, #3bf58b)' : 'var(--muted, #6c8084)'};"></span>
                  ${escapeHtml(v.name)}
                </div>
              </td>
              <td>
                <span class="network-member-pill">${escapeHtml(v.parent)}</span>
              </td>
              <td>
                <span class="network-member-pill" style="color:var(--lt-ink-brand, var(--accent-cyan-hi, #4fd8c4)); border-color:rgba(79,216,196,0.4); font-weight:700;">VID ${escapeHtml(String(v.vlan_id))}</span>
              </td>
              <td>
                ${v.alias ? `<span class="switch-port-alias-tag" title="${escapeHtml(v.alias)}">${escapeHtml(v.alias)}</span>` : '<span class="nw-xs-muted">--</span>'}
              </td>
              <td>
                <span class="switch-speed-pill ${isUp ? 'speed-10g' : 'speed-down'}">
                  ${isUp ? 'UP' : 'DOWN'}
                </span>
              </td>
              <td class="nw-xs-mono">${escapeHtml(v.ip_address || '--')}</td>
              <td class="nw-xs-mono">
                <div>↓ ${rxFmt} / ↑ ${txFmt}</div>
              </td>
              <td class="nw-x-2">
                <button class="btn-pill-toggle btn-delete-vlan is-danger is-small" data-net-edit="vlan" data-vlan="${escapeHtml(v.name)}" title="${t('ui.delete_vlan', 'Delete VLAN')}">🗑</button>
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
        dockerContainer.innerHTML = `<div class="nw-xs-muted-3">${t('net.no_docker_nets', 'No Docker bridge networks in use.')}</div>`;
      } else {
        dockerContainer.innerHTML = dockerNets.map((net) => {
          const containers = net.containers || [];
          return `
            <div class="network-docker-card">
              <div class="network-docker-top">
                <div class="network-docker-name nw-row-2">
                  <svg class="ic nw-size"><use href="#i-chip"/></svg>
                  ${escapeHtml(net.name)}
                  <span class="network-docker-driver">${escapeHtml(net.driver)}</span>
                  ${net.is_custom ? `<button class="net-docker-delete-btn" data-net-id="${escapeHtml(net.id)}" data-net-name="${escapeHtml(net.name)}" title="${t('ui.delete_network', 'Delete Network')}">🗑</button>` : ''}
                </div>
                <div class="network-docker-cidr">
                  ${net.subnet ? `${t('net.subnet', 'Subnet:')} <strong>${escapeHtml(net.subnet)}</strong>` : ''}
                  ${net.gateway ? ` • ${t('net.gateway', 'Gateway:')} <strong>${escapeHtml(net.gateway)}</strong>` : ''}
                  ${net.bridge_device ? ` • ${t('net.device', 'Device:')} <strong>${escapeHtml(net.bridge_device)}</strong>` : ''}
                </div>
              </div>
              <div class="network-docker-containers">
                ${containers.length === 0 ? `<span class="nw-xs-muted-2">${t('net.no_containers', 'No containers attached')}</span>` : containers.map((c) => `
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

    applyNetCaps(document);
    initNetworkControls(); // the Tailscale details load with their own tab, not with every layout read (C4)
  } catch (err) {
    console.warn('[Kiboto] Error fetching network topology:', err);
    showTopologyFailed(err?.message || String(err));
  }
}

const TOPO_PARTS = ['net-port-rows', 'network-bridges-container', 'network-docker-container'];

/** Every part of the Network page says the layout could not be read, with Try again: only the
 *  table did, while the tiles kept "--" and the other parts "Loading…" (network report F1). */
export function showTopologyFailed(error) {
  const home = document.getElementById('net-home');
  if (home) home.textContent = t('net.topo_failed', 'Could not load the network layout: {error}', { error });
  for (const id of TOPO_PARTS) {
    const part = document.getElementById(id);
    if (!part) continue;
    const block = stateBlock('failed', { detail: error, retry: () => fetchAndRenderNetworkTopology() });
    if (part.tagName === 'UL') {
      const item = document.createElement('li'); // a list holds only items
      item.append(block);
      part.replaceChildren(item);
    } else part.replaceChildren(block);
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

  showNetDialog(overlay, closeNetworkPortModal);

  try {
    const data = await api.get(`/api/network/port/${encodeURIComponent(ifaceName)}`);
    const nic = data.interface || {};

    if (dot) {
      dot.style.background = nic.is_up ? 'var(--ok2, #3bf58b)' : 'var(--muted, #6c8084)';
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
        : t('net.no_wol', 'This network card can’t wake the NAS (no Wake-on-LAN).');
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
          copyText(mac)
            .then(() => showToast(t('toast.mac_address_copied_to_clipboard', 'MAC address {mac} copied to clipboard!', { mac: mac }), 'info'))
            .catch(() => showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error'));
        } else {
          showToast(t('toast.no_mac_address_available_to_copy', 'No MAC address available to copy'), 'warn');
        }
      };
    }
    if (roDriver) roDriver.textContent = nic.driver || t('net.generic', 'Generic');
    if (roPci) roPci.textContent = nic.pci_slot || '--';
    if (roLink) roLink.textContent = nic.is_up ? `${nic.speed_human || t('net.connected', 'Connected')} (${nic.duplex || 'full'})` : t('net.down', 'Down (disconnected)');
  } catch (err) {
    showToast(t('toast.failed_to_load_port_config', 'Failed to load port config: {error}', { error: err.message || err }), 'error');
  }
  applyNetCaps(overlay);
  const save = document.getElementById('net-port-cfg-save-btn');
  const wiring = canChange('mtu') || canChange('speed') || canChange('wake_on_lan');
  if (save) save.textContent = wiring ? t('net.save_port_cfg', 'Save & Apply') : t('net.save_nickname', 'Save nickname');
}

export function closeNetworkPortModal() {
  const overlay = document.getElementById('network-port-config-overlay');
  if (overlay) {
    hideNetDialog(overlay);
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

  if (canChange('mtu') && (isNaN(mtu) || mtu < 68 || mtu > 9216)) {
    showToast(t('toast.mtu_must_be_an_integer_between', 'MTU must be an integer between 68 and 9216'), 'error');
    return;
  }

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = t('ui.saving', 'Saving...');
  }

  try {
    // the nickname always; packet size, speed and Wake-on-LAN only where this host lets Kiboto change them
    await api.post(`/api/network/port/${encodeURIComponent(_currentPortIface)}`, portPayload({ alias, mtu, wol_enabled, autoneg, speed }));
    showToast(t('net.port_saved_toast', 'Port configuration saved successfully'), 'success');
    closeNetworkPortModal();
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to save port config', 'error');
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = canChange('mtu') || canChange('speed') || canChange('wake_on_lan') ? t('net.save_port_cfg', 'Save & Apply') : t('net.save_nickname', 'Save nickname');
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

  showNetDialog(overlay, closeDockerNetworkCreateModal);
}

export function closeDockerNetworkCreateModal() {
  const overlay = document.getElementById('network-docker-create-overlay');
  if (overlay) {
    hideNetDialog(overlay);
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
    submitBtn.textContent = t('ui.creating', 'Creating...');
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

    showNetDialog(overlay, closeHostIpConfigModal);
  } catch (err) {
    showToast(t('toast.failed_to_load_host_network_config', 'Failed to load host network config: {error}', { error: err.message || err }), 'error');
  }
  applyNetCaps(document.getElementById('network-host-config-overlay'));
}

export function closeHostIpConfigModal() {
  const overlay = document.getElementById('network-host-config-overlay');
  if (overlay) {
    hideNetDialog(overlay);
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
    applyBtn.textContent = t('ui.saving', 'Saving...');
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
    });

    // only a host Kiboto manages takes the change (SET-16, D2); elsewhere the server says where to make it
    closeHostIpConfigModal();
    showToast(res?.message || t('ui.saved', 'Saved!'), 'success');
    fetchAndRenderNetworkTopology();
  } catch (err) {
    showToast(err.message || 'Failed to apply host network configuration', 'error');
  } finally {
    if (applyBtn) {
      applyBtn.disabled = false;
      applyBtn.textContent = t('net.apply_address', 'Apply');
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
        slavesContainer.innerHTML = '<div class="nw-xs-muted">' + t('net.no_adapters', 'No Ethernet adapters found.') + '</div>';
      } else {
        slavesContainer.innerHTML = candidates
          .map((nic) => {
            const isChecked = Boolean(nic.is_slave);
            return `
            <label class="nw-row-xs">
              <input type="checkbox" class="net-bond-slave-checkbox nw-x-7" value="${escapeHtml(nic.name)}" ${isChecked ? 'checked' : ''} />
              <span style="font-family:var(--font-mono, monospace); font-weight:600; color:var(--lt-t-f5f9f9ff, #f5f9f9);">${escapeHtml(nic.name)}</span>
              ${nic.alias ? `<span class="switch-port-alias-tag">${escapeHtml(nic.alias)}</span>` : ''}
              <span class="nw-xs-muted-5">${escapeHtml(nic.speed_human || (nic.is_up ? t('net.connected', 'Connected') : t('net.disconnected', 'Disconnected')))}</span>
            </label>
          `;
          })
          .join('');
      }
    }

    showNetDialog(overlay, closeBondConfigModal);
  } catch (err) {
    showToast(t('toast.failed_to_load_bond_configuration', 'Failed to load bond configuration: {error}', { error: err.message || err }), 'error');
  }
  applyNetCaps(document.getElementById('network-bond-config-overlay'));
}

export function closeBondConfigModal() {
  const overlay = document.getElementById('network-bond-config-overlay');
  if (overlay) {
    hideNetDialog(overlay);
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
    saveBtn.textContent = t('ui.saving', 'Saving...');
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
        membersContainer.innerHTML = '<div class="nw-xs-muted">' + t('net.nothing_to_bridge', 'No ports available to bridge.') + '</div>';
      } else {
        membersContainer.innerHTML = candidates
          .map((cand) => {
            const isChecked = Boolean(cand.is_member);
            return `
            <label class="nw-row-xs">
              <input type="checkbox" class="net-bridge-member-checkbox nw-x-7" value="${escapeHtml(cand.name)}" ${isChecked ? 'checked' : ''} />
              <span style="font-family:var(--font-mono, monospace); font-weight:600; color:var(--lt-t-f5f9f9ff, #f5f9f9);">${escapeHtml(cand.name)}</span>
              <span class="network-member-pill nw-xs-4">${escapeHtml(cand.type || 'interface')}</span>
              ${cand.alias ? `<span class="switch-port-alias-tag">${escapeHtml(cand.alias)}</span>` : ''}
              <span class="nw-xs-muted-5">${escapeHtml(cand.speed_human || (cand.is_up ? 'Connected' : 'Disconnected'))}</span>
            </label>
          `;
          })
          .join('');
      }
    }

    showNetDialog(overlay, closeBridgeConfigModal);
  } catch (err) {
    showToast(t('toast.failed_to_load_bridge_configuration', 'Failed to load bridge configuration: {error}', { error: err.message || err }), 'error');
  }
  applyNetCaps(document.getElementById('network-bridge-config-overlay'));
}

export function closeBridgeConfigModal() {
  const overlay = document.getElementById('network-bridge-config-overlay');
  if (overlay) {
    hideNetDialog(overlay);
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
    saveBtn.textContent = t('ui.saving', 'Saving...');
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

  showNetDialog(overlay, closeCreateVlanModal);

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
    hideNetDialog(overlay);
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
    submitBtn.textContent = t('ui.creating', 'Creating...');
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

/** Network is one page (SET-24): the layout, the name card (NFEAT-8) and what answers load
 *  together; each loaded with its own tab before. */
export function loadNetworkPage() {
  fetchAndRenderNetworkTopology();
  import('./nas-name.js').then((m) => m.loadNasNameCard()).catch(() => {});
  fetchListeningPorts();
}

export function initNetworkControls() {
  installNeedsTailscale();
  initNetworkPortsInspector();
  const btnOpenHostIp = document.getElementById('btn-open-host-ip-modal');
  if (btnOpenHostIp && !btnOpenHostIp.dataset.bound) {
    btnOpenHostIp.dataset.bound = '1';
    btnOpenHostIp.addEventListener('click', (e) => {
      e.stopPropagation();
      openHostIpConfigModal();
    });
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
