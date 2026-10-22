/**
 * ZettNAS Toolkit - Network Manager & Ports Inspector
 * Modular controller for host network adapters, virtual switching, and listening socket inspection.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';

let _cachedPorts = [];
let _portsBound = false;

export async function fetchListeningPorts() {
  try {
    const res = await api.get('/api/network/ports/listening');
    _cachedPorts = (res && res.ports) ? res.ports : [];
    renderListeningPortsTable(_cachedPorts);
    return _cachedPorts;
  } catch (err) {
    console.debug('[NetworkManager] Error fetching listening ports:', err);
    const tbody = document.getElementById('net-listening-ports-tbody');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--crit); padding: 18px;">Failed to load listening ports: ${err.message || err}</td></tr>`;
    }
    return [];
  }
}

export function renderListeningPortsTable(ports, filter = '') {
  const tbody = document.getElementById('net-listening-ports-tbody');
  if (!tbody) return;

  const q = (filter || '').toLowerCase().trim();
  const filtered = (ports || []).filter(p => {
    if (!q) return true;
    return (
      String(p.port).includes(q) ||
      (p.protocol || '').toLowerCase().includes(q) ||
      (p.bind_address || '').toLowerCase().includes(q) ||
      (p.service || '').toLowerCase().includes(q) ||
      (p.container || '').toLowerCase().includes(q)
    );
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 24px;">No listening ports found matching filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(p => {
    const isUdp = (p.protocol || '').toLowerCase() === 'udp';
    const protoBadge = isUdp
      ? `<span class="ci-badge" style="background: rgba(245,158,11,0.15); color: #f59e0b; border: 1px solid rgba(245,158,11,0.3); font-size: 11px; font-weight: 700;">UDP</span>`
      : `<span class="ci-badge" style="background: rgba(37,194,160,0.15); color: var(--ok2); border: 1px solid rgba(37,194,160,0.3); font-size: 11px; font-weight: 700;">TCP</span>`;

    const stateBadge = isUdp
      ? `<span class="ci-badge" style="background: rgba(59,130,246,0.15); color: #3b82f6; border: 1px solid rgba(59,130,246,0.3); font-size: 11px;">ACTIVE</span>`
      : `<span class="ci-badge" style="background: rgba(37,194,160,0.15); color: var(--ok2); border: 1px solid rgba(37,194,160,0.3); font-size: 11px;">LISTEN</span>`;

    const containerCol = p.container
      ? `<div style="display:flex; align-items:center; gap:6px;">
           <span style="font-size: 12px;">🐳</span>
           <span style="color: #60a5fa; font-weight: 600;">${escapeHtml(p.container)}</span>
         </div>`
      : `<span style="color: var(--muted); font-size: 11px;">Host System / Kernel</span>`;

    return `
      <tr data-port="${escapeHtml(String(p.port))}" data-proto="${escapeHtml(String(p.protocol))}">
        <td><strong style="font-family: monospace; font-size: 13px; color: #fff;">:${escapeHtml(String(p.port))}</strong></td>
        <td>${protoBadge}</td>
        <td><code style="font-size: 11px; color: var(--muted);">${escapeHtml(String(p.bind_address))}</code></td>
        <td><span style="font-weight: 600; color: #e2e8f0;">${escapeHtml(String(p.service || 'Unknown'))}</span></td>
        <td>${containerCol}</td>
        <td style="text-align: right;">${stateBadge}</td>
      </tr>
    `;
  }).join('');
}

export function initNetworkPortsInspector() {
  if (_portsBound) return;
  _portsBound = true;

  const btnRefresh = document.getElementById('btn-refresh-net-ports');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => fetchListeningPorts());
  }

  const searchInput = document.getElementById('net-ports-search');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      renderListeningPortsTable(_cachedPorts, e.target.value);
    });
  }
}
