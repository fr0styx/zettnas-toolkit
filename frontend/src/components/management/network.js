/**
 * Mission Control: Copy history, replication, VPNs, topology, ports, bonds, bridges, VLANs, host IP.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { ZettEventBus } from '../../event-bus.js';
import { makeDraggable } from '../dock.js';
import { api } from '../../api.js';
import { initNetworkPortsInspector, fetchListeningPorts } from '../network-manager.js';
import { showToast, showConfirmToast } from '../../toast.js';
import { escapeHtml, copyTextToClipboard, copyText } from '../../utils.js';
import { t } from '../../i18n.js';
import { formatBytes as formatSize, formatDateTime, formatNumber } from '../../format.js';
import { showServeLink } from './ai.js';

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
        : '<span style="color:var(--muted); font-size:var(--zn-fs-xs);">None</span>';
      const destName = item.dest ? item.dest.split('/').filter(Boolean).pop() || item.dest : '/';

      return `
        <tr>
          <td style="font-family:var(--font-mono, monospace); font-size:var(--zn-fs-xs); color:var(--muted);">${timeStr}</td>
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
            <td><span class="mgmt-app-pill" style="font-size:var(--zn-fs-xs);">${escapeHtml(j.schedule || 'manual')}</span></td>
            <td>${j.bandwidth_limit_mbps ? `${j.bandwidth_limit_mbps} MB/s` : 'Unlimited'}</td>
            <td>${j.retention_count || 7} snaps</td>
            <td><span class="mgmt-app-pill ${j.enabled ? 'text-emerald' : 'text-muted'}">${j.enabled ? 'Active' : 'Disabled'}</span></td>
            <td style="text-align:right;">
              <button class="btn-pill-toggle btn-run-repl is-small" data-id="${escapeHtml(j.id)}" style="margin-right: 4px;" title="${t('ui.execute_replication_now', 'Execute Replication Now')}">▶ Run</button>
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
            btn.textContent = t('ui.running_2', '⏳ Running...');
            await api.post(`/api/storage/replication/jobs/${encodeURIComponent(id)}/run`);
            showToast(t('toast.replication_pipeline_dispatched', 'Replication pipeline \'{id}\' dispatched.', { id: id }), 'success');
            setTimeout(fetchAndRenderReplication, 1000);
          } catch (e) {
            showToast(t('toast.replication_failed', 'Replication failed: {message}', { message: e.message }), 'error');
          } finally {
            btn.disabled = false;
            btn.textContent = t('ui.run', '▶ Run');
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
        ? '<span style="color:var(--lt-t-3bf58bff, #3bf58b); font-weight:600;">⚡ Direct P2P</span>'
        : p.relay
          ? `<span style="color:var(--lt-t-f59e0bff, #f59e0b);">🌐 DERP (${escapeHtml(p.relay)})</span>`
          : '<span style="color:var(--muted);">--</span>';

      const statusPill = p.online
        ? '<span class="mgmt-app-pill" style="color:var(--lt-t-3bf58bff, #3bf58b); background:var(--lt-b-3bf58b1f, rgba(59,245,139,0.12)); font-size:var(--zn-fs-xs); padding:2px 7px;">Online</span>'
        : '<span class="mgmt-app-pill" style="color:var(--muted); background:var(--zn-glaze-6); font-size:var(--zn-fs-xs); padding:2px 7px;">Offline</span>';

      const safeIpId = (p.ip || 'no_ip').replace(/[^a-zA-Z0-9]/g, '_');

      return `
      <tr style="border-bottom:1px solid var(--zn-line-5); font-size:var(--zn-fs-xs);">
        <td style="padding:8px 12px;">
          <div style="font-weight:700; color:var(--zn-text-strong);">${escapeHtml(p.name || p.hostname || 'Unnamed')}</div>
          ${p.dns_name ? `<div style="font-size:var(--zn-fs-xs); color:var(--muted);">${escapeHtml(p.dns_name)}</div>` : ''}
        </td>
        <td style="padding:8px 12px; color:var(--text-sub);">${osLabel}</td>
        <td style="padding:8px 12px;"><code style="color:var(--zn-text-accent); font-size:var(--zn-fs-xs);">${escapeHtml(p.ip || '--')}</code></td>
        <td style="padding:8px 12px;">${routeBadge}</td>
        <td style="padding:8px 12px;">${statusPill}</td>
        <td style="padding:8px 12px; text-align:right;">
          <div style="display:inline-flex; align-items:center; gap:6px;">
            <span id="latency-${safeIpId}" style="font-size:var(--zn-fs-xs); font-weight:700;"></span>
            <button class="btn-pill-toggle btn-ping-peer" data-peer-ip="${escapeHtml(p.ip || '')}" style="font-size:var(--zn-fs-xs); padding:2px 8px;" ${!p.ip ? `disabled title="${escapeHtml(t('net.why_no_peer_ip', 'This device has no address to ping yet'))}"` : ''}>⚡ Ping</button>
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
          tsBadgeEl.textContent = t('ui.not_installed', 'Not Installed');
          tsBadgeEl.style.color = 'var(--muted, #94a3b8)';
          tsBadgeEl.style.borderColor = 'rgba(255,255,255,0.1)';
        }
        if (tsPillEl) {
          tsPillEl.textContent = t('ui.daemon_not_found', 'App service not found');
          tsPillEl.style.color = 'var(--muted, #94a3b8)';
          tsPillEl.style.background = 'rgba(255,255,255,0.06)';
        }
        if (tsDeployBanner) tsDeployBanner.style.display = 'block';
        if (tsFormIntro) {
          tsFormIntro.textContent = t('ui.deploy_official_tailscale_container_or', 'Deploy official Tailscale container or provide auth key to connect instantly:');
          tsFormIntro.style.color = '#f59e0b';
        }
        if (tsIpEl) tsIpEl.textContent = '--';
        if (tsCopyIpBtn) tsCopyIpBtn.style.display = 'none';
        if (tsTailnetEl) tsTailnetEl.textContent = '--';
        if (tsHostEl) tsHostEl.textContent = '--';
        if (tsPeersEl) tsPeersEl.textContent = t('ui.0_peers', '0 peers');
        if (tsConnectForm) tsConnectForm.style.display = 'flex';
        if (tsConnectedView) tsConnectedView.style.display = 'none';
        if (tsDownBtn) tsDownBtn.style.display = 'none';
        if (tsUpBtn) {
          tsUpBtn.textContent = t('net.tailscale_deploy_btn', '⚡ 1-Click Deploy Tailscale');
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
          tsBadgeEl.textContent = t('ui.active_connected', 'Active (Connected)');
          tsBadgeEl.style.color = 'var(--ok2, #3bf58b)';
          tsBadgeEl.style.borderColor = 'rgba(59,245,139,0.3)';
        }
        if (tsPillEl) {
          tsPillEl.textContent = t('ldap.test_ok', 'Connected');
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
          tsUpBtn.textContent = t('ui.connect_tailscale', '🚀 Connect Tailscale');
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
              keyExpiryDisplay.textContent = t('ui.key_expired', '❌ Key Expired');
              keyExpiryDisplay.style.color = '#f87171';
            }
          } else {
            keyExpiryDisplay.textContent = t('ui.key_expiry_disabled', 'Key Expiry Disabled');
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
            exitNodePill.textContent = t('ui.active_in_use', 'Active (In Use)');
            exitNodePill.style.color = '#3bf58b';
            exitNodePill.style.background = 'rgba(59,245,139,0.15)';
            if (exitNodeHint) exitNodeHint.style.display = 'none';
          } else if (ts.exit_node_approved) {
            exitNodePill.textContent = t('ui.approved_available', 'Approved & Available');
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
            exitNodePill.innerHTML = '<a href="https://login.tailscale.com/admin/machines" target="_blank" rel="noopener noreferrer" style="color:var(--zn-text-accent); text-decoration:underline;">Pending Admin Approval ↗</a>';
            exitNodePill.style.color = '#38bdf8';
            exitNodePill.style.background = 'rgba(56,189,248,0.15)';
            if (exitNodeHint) {
              exitNodeHint.style.display = 'block';
              exitNodeHint.innerHTML = '⚠️ Exit node is advertised. To allow other devices to route traffic through this NAS, approve it in your <a href="https://login.tailscale.com/admin/machines" target="_blank" rel="noopener noreferrer" style="color:var(--zn-text-accent); text-decoration:underline; font-weight:700;">Tailscale Admin Console ↗</a> (Machines → Edit route settings → Use as exit node).';
              exitNodeHint.style.color = '#fbbf24';
              exitNodeHint.style.background = 'rgba(245,158,11,0.08)';
              exitNodeHint.style.borderColor = 'rgba(245,158,11,0.25)';
            }
          } else {
            exitNodePill.textContent = t('ui.inactive', 'Inactive');
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
              '<div style="color:var(--muted); font-size:var(--zn-fs-xs); text-align:center; padding:12px 0;">No files in Taildrop inbox yet.</div>';
          } else {
            taildropList.innerHTML = files
              .map(
                f => `
              <div class="taildrop-file-item" data-path="${escapeHtml(f.path || '')}" style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid var(--zn-line-5); font-size:var(--zn-fs-xs); cursor:pointer; border-radius:4px; transition:background 0.2s;" data-hover-bg title="${t('ui.click_to_view_folder_in', 'Click to view folder in Files')}">
                <span style="font-weight:600; color:var(--zn-text-strong); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:60%;" title="${escapeHtml(f.name)}">📄 ${escapeHtml(f.name)}</span>
                <span style="color:var(--muted); font-size:var(--zn-fs-xs);">${escapeHtml(f.size_formatted)} · ${escapeHtml(f.modified_at)}</span>
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
        if (tsPeersEl) tsPeersEl.textContent = t('ui.0_peers', '0 peers');
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
                copyText(ts.auth_url)
                  .then(() => showToast(t('toast.authorization_link_copied_to_clipboard', 'Authorization link copied to clipboard.'), 'success'))
                  .catch(() => showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error'));
              };
            }
            startTailscaleAuthPolling();
          }
          if (tsUpBtn) {
            tsUpBtn.textContent = t('ui.log_in_to_tailscale', '🔗 Log in to Tailscale');
            tsUpBtn.dataset.mode = 'login';
            tsUpBtn.dataset.authUrl = ts.auth_url || '';
          }
        } else {
          if (tsAuthPrompt) tsAuthPrompt.style.display = 'none';
          if (tsUpBtn) {
            tsUpBtn.textContent = t('ui.connect_tailscale', '🚀 Connect Tailscale');
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
        btn.textContent = t('net.tailscale_deploying', '⏳ Deploying Container...');
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
          tsUpBtn.textContent = t('ui.log_in_to_tailscale', '🔗 Log in to Tailscale');
        }
        if (tsCopyAuthUrlBtn) {
          tsCopyAuthUrlBtn.onclick = () => {
            copyText(res.auth_url)
              .then(() => showToast(t('toast.authorization_link_copied_to_clipboard', 'Authorization link copied to clipboard.'), 'success'))
              .catch(() => showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error'));
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
          btn.textContent = t('ui.log_in_to_tailscale', '🔗 Log in to Tailscale');
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
          tsUpBtn.textContent = t('ui.log_in_to_tailscale', '🔗 Log in to Tailscale');
          if (tsCopyAuthUrlBtn) {
            tsCopyAuthUrlBtn.onclick = () => {
              copyText(res.auth_url)
                .then(() => showToast(t('toast.authorization_link_copied_to_clipboard', 'Authorization link copied to clipboard.'), 'success'))
                .catch(() => showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error'));
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
          tsUpBtn.textContent = t('ui.log_in_to_tailscale', '🔗 Log in to Tailscale');
        } else if (tsUpBtn.dataset.mode === 'deploy') {
          tsUpBtn.textContent = t('net.tailscale_deploy_btn', '⚡ 1-Click Deploy Tailscale');
        } else {
          tsUpBtn.textContent = t('ui.connect_tailscale', '🚀 Connect Tailscale');
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
        copyText(ip)
          .then(() => showToast(t('toast.copied_tailscale_ip', 'Copied Tailscale IP: {ip}', { ip: ip }), 'success'))
          .catch(() => showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error'));
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
        btnTsReauth.textContent = t('net.tailscale_reauth_btn', '⚡ Re-auth');
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
        btnTsSaveRoutes.textContent = t('net.tailscale_save_routes', 'Save Subnets');
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
          `Tailscale ${featName} is not yet authorized on your Tailnet. Please approve this node in the Tailscale Admin Console:<br><br><a href="${escapeHtml(res.approval_url)}" target="_blank" rel="noopener noreferrer" style="color:var(--zn-text-accent); text-decoration:underline; font-weight:bold; word-break:break-all;">${escapeHtml(res.approval_url)}</a><br><br>After clicking Approve in Tailscale, re-enable this toggle to activate.`,
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
        copyText(url)
          .then(() => showToast(t('toast.tailscale_https_url_copied_to_clipboard', 'Tailscale HTTPS URL copied to clipboard.'), 'success'))
          .catch(() => showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error'));
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
        btnTsTaildropFetch.textContent = t('net.tailscale_taildrop_fetch', '📥 Fetch');
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
            resSpan.textContent = t('ui.failed_2', '❌ Failed');
            resSpan.style.color = '#f87171';
          }
          showToast(t('toast.ping_failed_or_timed_out', 'Ping {ip} failed or timed out.', { ip: ip }), 'warning');
        }
      } catch (err) {
        if (resSpan) {
          resSpan.textContent = t('ui.error_3', '❌ Error');
          resSpan.style.color = '#f87171';
        }
      } finally {
        pingBtn.disabled = false;
        pingBtn.textContent = t('ui.ping', '⚡ Ping');
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
      showToast(t('toast.mesh_vpn_telemetry_refreshed', 'Remote access status refreshed.'), 'info');
    });
  }

  if (genBtn && !genBtn._bound) {
    genBtn._bound = true;
    genBtn.addEventListener('click', async () => {
      try {
        genBtn.disabled = true;
        genBtn.textContent = t('ui.generating_2', '🔑 Generating...');
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
        genBtn.textContent = t('ui.generate_client_conf', '🔑 Generate Client .conf');
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
        switchFaceplate.innerHTML = `<div style="color:var(--muted); font-size:var(--zn-fs-xs); padding:12px;">No physical network interfaces detected.</div>`;
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
                <span style="font-size:var(--zn-fs-xs); color:var(--muted);">${nic.duplex === 'full' ? 'Full Duplex' : nic.duplex}</span>
              </div>
              <div class="switch-port-meta">
                <div>MAC: ${escapeHtml(nic.mac || 'N/A')}</div>
                ${nic.master ? `<div style="color:var(--lt-ink-brand, var(--accent-cyan));">Master: ${escapeHtml(nic.master)}</div>` : ''}
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
                ${nic.alias ? `<span class="switch-port-alias-tag" title="${escapeHtml(nic.alias)}">${escapeHtml(nic.alias)}</span>` : '<span style="color:var(--muted); font-size:var(--zn-fs-xs);">--</span>'}
              </td>
              <td>
                <span class="switch-speed-pill ${isUp ? 'speed-10g' : 'speed-down'}">
                  ${isUp ? 'UP / CARRIER' : 'DOWN'}
                </span>
              </td>
              <td>
                <span style="font-weight:600; color:${isUp ? '#f8fafc' : 'var(--muted)'};">${escapeHtml(nic.speed_human)}</span>
                <span style="font-size:var(--zn-fs-xs); color:var(--muted); margin-left:4px;">(${escapeHtml(nic.duplex)})</span>
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:var(--zn-fs-xs);">${escapeHtml(nic.mac || '--')}</td>
              <td style="font-family:var(--font-mono, monospace);">${escapeHtml(String(nic.mtu || 1500))}</td>
              <td>
                ${nic.master ? `<span class="network-member-pill" style="color:var(--lt-ink-brand, var(--accent-cyan)); border-color:rgba(56,189,248,0.3);">${escapeHtml(nic.master)}</span>` : '<span style="color:var(--muted);">Standalone</span>'}
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:var(--zn-fs-xs);">
                <div>↓ ${rxFmt} <span style="font-size:var(--zn-fs-xs); color:var(--muted);">(${formatNumber(nic.rx_packets || 0)} pkts)</span></div>
                <div>↑ ${txFmt} <span style="font-size:var(--zn-fs-xs); color:var(--muted);">(${formatNumber(nic.tx_packets || 0)} pkts)</span></div>
              </td>
              <td style="font-size:var(--zn-fs-xs); color:var(--muted);">
                <div>${escapeHtml(nic.driver || 'Generic')}</div>
                <div style="font-family:var(--font-mono, monospace); font-size:var(--zn-fs-xs);">${escapeHtml(nic.pci_slot || '--')}</div>
              </td>
              <td style="text-align: right;">
                <button class="btn-pill-toggle btn-config-port is-small" data-iface="${escapeHtml(nic.name)}" style="color: var(--lt-ink-brand, var(--accent-cyan, #38bdf8)); border-color: rgba(56,189,248,0.3);">${t('net.configure_port', 'Configure')}</button>
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
                <span class="switch-speed-pill ${br.stp ? 'speed-10g' : 'speed-down'}" style="font-size:var(--zn-fs-xs); padding:2px 6px;">STP: ${br.stp ? 'ON' : 'OFF'}</span>
                <span style="font-size:var(--zn-fs-xs); color:var(--muted); font-family:var(--font-mono, monospace);">FD: ${br.forward_delay || 0}s</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span class="network-bridge-ip">${escapeHtml(br.ip_address || 'Unassigned IP')}</span>
                <button class="btn-pill-toggle btn-config-bridge is-small" data-bridge="${escapeHtml(br.name)}" style="color: var(--lt-ink-brand, var(--accent-cyan, #38bdf8)); border-color: rgba(56,189,248,0.3);">${t('net.configure_bridge', 'Configure')}</button>
              </div>
            </div>
            <div style="font-size:var(--zn-fs-xs); color:var(--muted);">Member Ports:</div>
            <div class="network-bridge-members">
              ${(br.interfaces || []).map((m) => `<span class="network-member-pill">${escapeHtml(m)}</span>`).join('') || '<span style="color:var(--muted); font-size:var(--zn-fs-xs);">No members</span>'}
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
                <span style="font-size:var(--zn-fs-xs); color:var(--muted); font-family:var(--font-mono, monospace);">${b.miimon || 100}ms</span>
              </div>
              <button class="btn-pill-toggle btn-config-bond is-small" data-bond="${escapeHtml(b.name)}" style="color: var(--lt-ink-brand, var(--accent-cyan, #38bdf8)); border-color: rgba(56,189,248,0.3);">${t('net.configure_bond', 'Configure')}</button>
            </div>
            <div style="font-size:var(--zn-fs-xs); color:var(--muted);">Active Slave: <strong style="color:var(--ok2, #3bf58b);">${escapeHtml(b.active_slave || 'None')}</strong></div>
            <div class="network-bridge-members">
              ${(b.slaves || []).map((s) => `<span class="network-member-pill ${s === b.active_slave ? 'active' : ''}">${escapeHtml(s)}</span>`).join('')}
            </div>
          </div>
        `);
      });

      bridgesContainer.innerHTML = items.length > 0 ? items.join('') : `<div style="color:var(--muted); font-size:var(--zn-fs-xs); padding:12px;">No virtual bridges or bonds configured.</div>`;

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
                <span class="network-member-pill" style="color:var(--lt-ink-brand, var(--accent-cyan, #38bdf8)); border-color:rgba(56,189,248,0.4); font-weight:700;">VID ${escapeHtml(String(v.vlan_id))}</span>
              </td>
              <td>
                ${v.alias ? `<span class="switch-port-alias-tag" title="${escapeHtml(v.alias)}">${escapeHtml(v.alias)}</span>` : '<span style="color:var(--muted); font-size:var(--zn-fs-xs);">--</span>'}
              </td>
              <td>
                <span class="switch-speed-pill ${isUp ? 'speed-10g' : 'speed-down'}">
                  ${isUp ? 'UP' : 'DOWN'}
                </span>
              </td>
              <td style="font-family:var(--font-mono, monospace); font-size:var(--zn-fs-xs);">${escapeHtml(v.ip_address || '--')}</td>
              <td style="font-family:var(--font-mono, monospace); font-size:var(--zn-fs-xs);">
                <div>↓ ${rxFmt} / ↑ ${txFmt}</div>
              </td>
              <td style="text-align: right;">
                <button class="btn-pill-toggle btn-delete-vlan is-danger is-small" data-vlan="${escapeHtml(v.name)}" title="${t('ui.delete_vlan', 'Delete VLAN')}">🗑</button>
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
        dockerContainer.innerHTML = `<div style="color:var(--muted); font-size:var(--zn-fs-xs); padding:12px;">No active Docker bridge networks found.</div>`;
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
                  ${net.is_custom ? `<button class="net-docker-delete-btn" data-net-id="${escapeHtml(net.id)}" data-net-name="${escapeHtml(net.name)}" title="${t('ui.delete_network', 'Delete Network')}">🗑</button>` : ''}
                </div>
                <div class="network-docker-cidr">
                  ${net.subnet ? `Subnet: <strong>${escapeHtml(net.subnet)}</strong>` : ''}
                  ${net.gateway ? ` • Gateway: <strong>${escapeHtml(net.gateway)}</strong>` : ''}
                  ${net.bridge_device ? ` • Dev: <strong>${escapeHtml(net.bridge_device)}</strong>` : ''}
                </div>
              </div>
              <div class="network-docker-containers">
                ${containers.length === 0 ? '<span style="font-size:var(--zn-fs-xs); color:var(--muted);">No containers attached</span>' : containers.map((c) => `
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
          copyText(mac)
            .then(() => showToast(t('toast.mac_address_copied_to_clipboard', 'MAC address {mac} copied to clipboard!', { mac: mac }), 'info'))
            .catch(() => showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error'));
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
    saveBtn.textContent = t('ui.saving', 'Saving...');
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
    applyBtn.textContent = t('ui.arming_watchdog', 'Arming Watchdog...');
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
    confirmBtn.textContent = t('ui.confirming', 'Confirming...');
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
    revertBtn.textContent = t('ui.reverting', 'Reverting...');
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
        slavesContainer.innerHTML = '<div style="color:var(--muted); font-size:var(--zn-fs-xs);">No physical Ethernet adapters detected.</div>';
      } else {
        slavesContainer.innerHTML = candidates
          .map((nic) => {
            const isChecked = Boolean(nic.is_slave);
            return `
            <label style="display:flex; align-items:center; gap:8px; font-size:var(--zn-fs-xs); cursor:pointer; user-select:none;">
              <input type="checkbox" class="net-bond-slave-checkbox" value="${escapeHtml(nic.name)}" ${isChecked ? 'checked' : ''} style="cursor:pointer;" />
              <span style="font-family:var(--font-mono, monospace); font-weight:600; color:var(--lt-t-f8fafcff, #f8fafc);">${escapeHtml(nic.name)}</span>
              ${nic.alias ? `<span class="switch-port-alias-tag">${escapeHtml(nic.alias)}</span>` : ''}
              <span style="font-size:var(--zn-fs-xs); color:var(--muted); margin-left:auto;">${escapeHtml(nic.speed_human || (nic.is_up ? 'Connected' : 'Disconnected'))}</span>
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
        membersContainer.innerHTML = '<div style="color:var(--muted); font-size:var(--zn-fs-xs);">No interfaces available to bridge.</div>';
      } else {
        membersContainer.innerHTML = candidates
          .map((cand) => {
            const isChecked = Boolean(cand.is_member);
            return `
            <label style="display:flex; align-items:center; gap:8px; font-size:var(--zn-fs-xs); cursor:pointer; user-select:none;">
              <input type="checkbox" class="net-bridge-member-checkbox" value="${escapeHtml(cand.name)}" ${isChecked ? 'checked' : ''} style="cursor:pointer;" />
              <span style="font-family:var(--font-mono, monospace); font-weight:600; color:var(--lt-t-f8fafcff, #f8fafc);">${escapeHtml(cand.name)}</span>
              <span class="network-member-pill" style="font-size:var(--zn-fs-xs); padding:1px 5px;">${escapeHtml(cand.type || 'interface')}</span>
              ${cand.alias ? `<span class="switch-port-alias-tag">${escapeHtml(cand.alias)}</span>` : ''}
              <span style="font-size:var(--zn-fs-xs); color:var(--muted); margin-left:auto;">${escapeHtml(cand.speed_human || (cand.is_up ? 'Connected' : 'Disconnected'))}</span>
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
