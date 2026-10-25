/**
 * Container Network Map: Docker networks on the left, containers on the right,
 * one line per attachment labelled with the container's IP on that network.
 * Containers that use another container's network stack (network_mode:
 * container:X) get a dashed line to that container instead.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

const NET_COLORS = ['#38bdf8', '#34d399', '#fbbf24', '#a78bfa', '#f472b6', '#2dd4bf', '#fb923c', '#f87171'];
const ROW = 30;
const PAD = 18;
const WIDTH = 680;
const NET_X = 12;
const NET_W = 170;
const CTR_X = 450;
const CTR_W = 218;

let _topology = null;
let _highlight = null;

function trimLabel(text, max) {
  const s = String(text || '');
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** Pure layout: node positions and edges for a topology from /api/docker/networks/topology. */
export function layoutNetworkMap(topo) {
  const networks = Array.isArray(topo?.networks) ? topo.networks : [];
  const all = Array.isArray(topo?.containers) ? topo.containers : [];
  const netIndex = new Map(networks.map((n, i) => [n.name, i]));
  const byName = new Map(all.map((c) => [c.name, c]));

  // Order containers by their first network so lines cross as little as possible;
  // a container sharing another's stack sorts right after that container.
  const firstNet = (c, depth = 0) => {
    const idx = (c.networks || []).map((a) => netIndex.get(a.network) ?? Infinity);
    if (idx.length) return Math.min(...idx);
    const target = c.shares_with && byName.get(c.shares_with);
    return target && depth < 4 ? firstNet(target, depth + 1) + 0.5 : Infinity;
  };
  const containers = [...all].sort((a, b) => firstNet(a) - firstNet(b) || a.name.localeCompare(b.name));

  const rows = Math.max(networks.length, containers.length, 1);
  const height = PAD * 2 + rows * ROW;
  const netStep = (height - PAD * 2) / Math.max(networks.length, 1);

  const netNodes = networks.map((n, i) => ({
    ...n,
    color: NET_COLORS[i % NET_COLORS.length],
    y: PAD + netStep * (i + 0.5),
  }));
  const netByName = new Map(netNodes.map((n) => [n.name, n]));
  const ctrNodes = containers.map((c, i) => ({ ...c, y: PAD + ROW * (i + 0.5) }));
  const ctrByName = new Map(ctrNodes.map((c) => [c.name, c]));

  const edges = [];
  for (const c of ctrNodes) {
    for (const a of c.networks || []) {
      const n = netByName.get(a.network);
      if (n) edges.push({ kind: 'net', network: n.name, container: c.name, y1: n.y, y2: c.y, color: n.color, ip: a.ip || '' });
    }
    const target = c.shares_with && ctrByName.get(c.shares_with);
    if (target) edges.push({ kind: 'shares', network: null, container: c.name, target: target.name, y1: target.y, y2: c.y });
  }
  return { width: WIDTH, height, networks: netNodes, containers: ctrNodes, edges };
}

function edgePath(e) {
  if (e.kind === 'shares') {
    const x = CTR_X + CTR_W;
    const bulge = x + 26 + Math.min(40, Math.abs(e.y2 - e.y1) / 6);
    return `M ${x} ${e.y1} C ${bulge} ${e.y1}, ${bulge} ${e.y2}, ${x} ${e.y2}`;
  }
  const x1 = NET_X + NET_W;
  const x2 = CTR_X;
  const mid = (x1 + x2) / 2;
  return `M ${x1} ${e.y1} C ${mid} ${e.y1}, ${mid} ${e.y2}, ${x2} ${e.y2}`;
}

/** SVG markup for a layout; `highlight` is a network name whose lines stay bright. */
export function renderNetworkMapSvg(layout, highlight = null) {
  const dim = (net) => (highlight && net !== highlight ? 0.12 : 1);
  const ctrLit = new Set(highlight ? layout.edges.filter((e) => e.network === highlight).map((e) => e.container) : []);

  const edges = layout.edges
    .map((e) => {
      if (e.kind === 'shares') {
        const op = highlight ? (ctrLit.has(e.container) || ctrLit.has(e.target) ? 0.9 : 0.12) : 0.8;
        return `<path class="nm-edge nm-edge-shares" d="${edgePath(e)}" fill="none" stroke="#94a3b8" stroke-width="1.4" stroke-dasharray="4 3" opacity="${op}"><title>${escapeHtml(t('cw.netmap_shares', 'uses network of {name}', { name: e.target }))}</title></path>`;
      }
      const label = e.ip
        ? `<text x="${CTR_X - 6}" y="${e.y2 - 4}" text-anchor="end" font-size="9" fill="${e.color}" opacity="${dim(e.network)}" font-family="monospace">${escapeHtml(e.ip)}</text>`
        : '';
      return `<path class="nm-edge" data-net="${escapeHtml(e.network)}" d="${edgePath(e)}" fill="none" stroke="${e.color}" stroke-width="1.6" opacity="${0.85 * dim(e.network)}"/>${label}`;
    })
    .join('');

  const nets = layout.networks
    .map((n) => {
      const meta = [n.driver, n.subnet].filter(Boolean).join(' · ');
      const op = highlight && n.name !== highlight ? 0.45 : n.container_count ? 1 : 0.55;
      return `
      <g class="nm-net" data-net="${escapeHtml(n.name)}" style="cursor:pointer" opacity="${op}">
        <title>${escapeHtml([n.name, meta, n.gateway && `gw ${n.gateway}`].filter(Boolean).join('\n'))}</title>
        <rect x="${NET_X}" y="${n.y - 12}" width="${NET_W}" height="24" rx="6" fill="rgba(0,0,0,0.45)" stroke="${n.color}" stroke-width="${highlight === n.name ? 2.2 : 1.2}"/>
        <text x="${NET_X + 10}" y="${n.y + 1}" font-size="11" font-weight="700" fill="#fff">${escapeHtml(trimLabel(n.name, 20))}</text>
        <text x="${NET_X + NET_W - 8}" y="${n.y + 1}" font-size="9" text-anchor="end" fill="${n.color}">${n.container_count || escapeHtml(t('cw.netmap_unused', 'unused'))}</text>
        <text x="${NET_X + 10}" y="${n.y + 10}" font-size="7.5" fill="#94a3b8">${escapeHtml(trimLabel(meta, 30))}</text>
      </g>`;
    })
    .join('');

  const ctrs = layout.containers
    .map((c) => {
      const running = c.state === 'running';
      const op = highlight && !ctrLit.has(c.name) ? 0.35 : 1;
      const ports = (c.ports || []).filter((p) => p.public).map((p) => `${p.public}→${p.private}/${p.type}`);
      const tip = [c.name, c.state, c.compose_project && `stack ${c.compose_project}`, ports.length && `ports ${ports.join(', ')}`]
        .filter(Boolean)
        .join('\n');
      return `
      <g class="nm-ctr" data-ctr="${escapeHtml(c.name)}" opacity="${op}">
        <title>${escapeHtml(tip)}</title>
        <rect x="${CTR_X}" y="${c.y - 11}" width="${CTR_W}" height="22" rx="5" fill="rgba(18,26,38,0.85)" stroke="rgba(255,255,255,0.1)"/>
        <circle cx="${CTR_X + 10}" cy="${c.y}" r="3.5" fill="${running ? '#34d399' : '#64748b'}"/>
        <text x="${CTR_X + 20}" y="${c.y + 4}" font-size="11" fill="#e2e8f0">${escapeHtml(trimLabel(c.name, 24))}</text>
        ${ports.length ? `<text x="${CTR_X + CTR_W - 7}" y="${c.y + 4}" font-size="8.5" text-anchor="end" fill="#94a3b8">${escapeHtml(trimLabel(ports[0].split('→')[0], 6))}${ports.length > 1 ? '+' : ''}</text>` : ''}
      </g>`;
    })
    .join('');

  return `<svg class="nm-svg" viewBox="0 0 ${layout.width} ${layout.height}" width="100%" style="display:block; min-width:520px;" role="img" aria-label="${escapeHtml(t('cw.netmap_title', 'Container Network Map'))}">${edges}${nets}${ctrs}</svg>`;
}

function ensureOverlay() {
  let overlay = document.getElementById('netmap-overlay');
  if (overlay) return overlay;
  overlay = document.createElement('div');
  overlay.id = 'netmap-overlay';
  overlay.className = 'smart-modal-backdrop';
  overlay.style.cssText = 'display:none; z-index:10020;';
  overlay.innerHTML = `
    <div class="smart-modal-window" style="width:760px; max-width:95vw; max-height:88vh; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 25px 70px rgba(0,0,0,0.85);">
      <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-size:16px;">🕸️</span>
          <span style="font-weight:700; color:var(--lt-t-ffffffff, #fff); font-size:13.5px;" data-i18n="cw.netmap_title">${escapeHtml(t('cw.netmap_title', 'Container Network Map'))}</span>
          <span id="netmap-summary" style="font-size:var(--zn-fs-xs); color:var(--muted);"></span>
        </div>
        <div class="os-window-controls">
          <button class="win-btn close-btn" id="netmap-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
        </div>
      </div>
      <div style="padding:8px 16px; font-size:var(--zn-fs-xs); color:var(--muted); border-bottom:1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06));" data-i18n="cw.netmap_hint">${escapeHtml(t('cw.netmap_hint', 'Click a network to highlight its containers.'))}</div>
      <div id="netmap-body" style="flex:1; overflow:auto; padding:10px 12px;"></div>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => {
    overlay.style.display = 'none';
    overlay.classList.remove('open');
  };
  overlay.querySelector('#netmap-close-btn').addEventListener('click', close);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && overlay.style.display !== 'none') close();
  });
  overlay.querySelector('#netmap-body').addEventListener('click', (e) => {
    const net = e.target.closest?.('.nm-net');
    if (!net || !_topology) return;
    _highlight = _highlight === net.dataset.net ? null : net.dataset.net;
    renderBody(overlay);
  });
  return overlay;
}

function renderBody(overlay) {
  const body = overlay.querySelector('#netmap-body');
  const summary = overlay.querySelector('#netmap-summary');
  const layout = layoutNetworkMap(_topology);
  if (!layout.networks.length && !layout.containers.length) {
    body.innerHTML = `<div class="netmap-empty" style="padding:24px; text-align:center; color:var(--muted); font-size:var(--zn-fs-xs);">${escapeHtml(t('cw.netmap_empty', 'No Docker networks found.'))}</div>`;
    summary.textContent = '';
    return;
  }
  summary.textContent = t('cw.netmap_summary', '{networks} networks · {containers} containers', {
    networks: layout.networks.length,
    containers: layout.containers.length,
  });
  body.innerHTML = renderNetworkMapSvg(layout, _highlight);
}

export async function openNetworkMap() {
  const overlay = ensureOverlay();
  const body = overlay.querySelector('#netmap-body');
  overlay.style.display = 'flex';
  overlay.classList.add('open');
  _highlight = null;
  body.innerHTML = `<div style="padding:24px; text-align:center; color:var(--muted); font-size:var(--zn-fs-xs);">${escapeHtml(t('cw.netmap_loading', 'Loading networks...'))}</div>`;
  try {
    _topology = await api.get('/api/docker/networks/topology');
    renderBody(overlay);
  } catch {
    _topology = null;
    body.innerHTML = `<div class="netmap-error" style="padding:24px; text-align:center; color:var(--lt-t-f87171ff, #f87171); font-size:var(--zn-fs-xs);">${escapeHtml(t('cw.netmap_failed', 'Could not load Docker networks.'))}</div>`;
  }
}
