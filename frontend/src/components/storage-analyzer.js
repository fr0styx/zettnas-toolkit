/**
 * Where a share's space goes (storage analyzer): a treemap of its folders you can click into, the
 * kinds of files, and the biggest files. The analysis runs on request, as a job (it reads the
 * share's folder listing); the last one is kept, so opening this again reads nothing.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';
import { formatBytes, formatDateTime, formatNumber } from '../format.js';
import { showToast } from '../toast.js';

const W = 600;
const r1 = (v) => Math.round(v * 10) / 10; // SVG coordinates to one decimal
const H = 260;
const KIND_NAMES = {
  video: () => t('space.kind_video', 'Videos'),
  photo: () => t('space.kind_photo', 'Photos'),
  audio: () => t('space.kind_audio', 'Music and audio'),
  document: () => t('space.kind_document', 'Documents'),
  archive: () => t('space.kind_archive', 'Archives'),
  disk_image: () => t('space.kind_disk_image', 'Disk images'),
  backup: () => t('space.kind_backup', 'Backups'),
  other: () => t('space.kind_other', 'Other'),
};

/** Squarified treemap: items [{bytes}] laid out in the rectangle; returns [{item, x, y, w, h}]. */
export function squarify(items, x = 0, y = 0, w = W, h = H) {
  const list = items.filter((i) => i.bytes > 0).sort((a, b) => b.bytes - a.bytes);
  const total = list.reduce((s, i) => s + i.bytes, 0);
  const out = [];
  if (!total) return out;
  const scale = (w * h) / total;
  let rest = list.map((item) => ({ item, area: item.bytes * scale }));
  let rx = x;
  let ry = y;
  let rw = w;
  let rh = h;
  const worst = (row, side) => {
    const sum = row.reduce((s, r) => s + r.area, 0);
    const max = Math.max(...row.map((r) => r.area));
    const min = Math.min(...row.map((r) => r.area));
    return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
  };
  while (rest.length) {
    const side = Math.min(rw, rh);
    let row = [rest[0]];
    let i = 1;
    while (i < rest.length && worst([...row, rest[i]], side) <= worst(row, side)) {
      row.push(rest[i]);
      i += 1;
    }
    rest = rest.slice(i);
    const sum = row.reduce((s, r) => s + r.area, 0);
    if (rw >= rh) {
      const cw = sum / rh;
      let cy = ry;
      for (const r of row) {
        const ch = r.area / cw;
        out.push({ item: r.item, x: rx, y: cy, w: cw, h: ch });
        cy += ch;
      }
      rx += cw;
      rw -= cw;
    } else {
      const ch = sum / rw;
      let cx = rx;
      for (const r of row) {
        const cw = r.area / ch;
        out.push({ item: r.item, x: cx, y: ry, w: cw, h: ch });
        cx += cw;
      }
      ry += ch;
      rh -= ch;
    }
  }
  return out;
}

/** The folders directly inside `prefix` ('' = the share), with what lies loose in it. */
export function childrenOf(result, prefix) {
  const depth = prefix ? prefix.split('/').length + 1 : 1;
  const kids = (result.folders || []).filter((f) => f.path.split('/').length === depth && (prefix ? f.path.startsWith(`${prefix}/`) : true));
  const parentBytes = prefix ? ((result.folders || []).find((f) => f.path === prefix)?.bytes ?? 0) : result.bytes || 0;
  const inKids = kids.reduce((s, f) => s + f.bytes, 0);
  const loose = parentBytes - inKids;
  return loose > 0 ? [...kids, { path: prefix, bytes: loose, loose: true }] : kids;
}

function treemapSvg(result, prefix) {
  const cells = squarify(childrenOf(result, prefix));
  if (!cells.length) return `<p class="immich-note">${escapeHtml(t('space.empty', 'Nothing in here takes space.'))}</p>`;
  const rects = cells.map(({ item, x, y, w, h }, i) => {
    const name = item.loose ? t('space.loose', 'Files here') : item.path.split('/').pop();
    const label = `${name} · ${formatBytes(item.bytes)}`;
    const text = w > 70 && h > 22 ? `<text x="${r1(x + 6)}" y="${r1(y + 16)}" class="space-cell-label">${escapeHtml(name.length > w / 7 ? `${name.slice(0, Math.max(3, Math.floor(w / 7) - 1))}…` : name)}</text>` : '';
    const drill = item.loose || !(result.folders || []).some((f) => f.path.startsWith(`${item.path}/`)) ? '' : ` data-space-open="${escapeHtml(item.path)}" role="button" tabindex="0"`;
    return `<g class="space-cell${drill ? ' is-open' : ''}"${drill}><rect x="${r1(x)}" y="${r1(y)}" width="${r1(Math.max(0, w - 2))}" height="${r1(Math.max(0, h - 2))}" rx="3" class="space-cell-rect space-tone-${i % 6}"><title>${escapeHtml(label)}</title></rect>${text}</g>`;
  });
  return `<svg class="space-treemap" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(t('space.folders', 'Biggest folders'))}">${rects.join('')}</svg>`;
}

function kindsSvg(result) {
  const total = result.bytes || 0;
  if (!total) return '';
  let x = 0;
  const bars = [];
  const legend = [];
  for (const [kind, v] of Object.entries(result.kinds || {})) {
    const w = (v.bytes / total) * W;
    const tone = `space-kind-${KIND_NAMES[kind] ? kind : 'other'}`;
    const name = (KIND_NAMES[kind] || KIND_NAMES.other)();
    bars.push(`<rect x="${r1(x)}" y="0" width="${r1(w)}" height="14" class="${tone}"><title>${escapeHtml(`${name}: ${formatBytes(v.bytes)}`)}</title></rect>`);
    legend.push(`<li><svg class="space-swatch" viewBox="0 0 10 10" aria-hidden="true"><rect width="10" height="10" rx="2" class="${tone}"/></svg>${escapeHtml(name)} <span class="immich-note">${escapeHtml(formatBytes(v.bytes))}</span></li>`);
    x += w;
  }
  return `<svg class="space-kinds" viewBox="0 0 ${W} 14" preserveAspectRatio="none" aria-hidden="true">${bars.join('')}</svg><ul class="space-legend">${legend.join('')}</ul>`;
}

export function analysisHtml(share, data, prefix = '') {
  const r = data?.result;
  const button = data?.running
    ? `<p class="immich-note" data-space-running>${escapeHtml(t('space.running', 'Adding up… It carries on in Jobs if you close this.'))}</p>`
    : `<button type="button" class="btn-pill-toggle is-primary" data-space-start>${escapeHtml(r ? t('space.again', 'Analyse again') : t('space.start', 'Analyse'))}</button>`;
  if (!r) {
    return `<p class="immich-note">${escapeHtml(t('space.none', "Kiboto hasn't looked at this share yet. Analysing reads its folder listing, not the files themselves; its disks wake up if they are asleep."))}</p>${button}`;
  }
  const crumbs = prefix
    ? `<p class="space-crumbs"><button type="button" class="btn-pill-toggle is-small" data-space-up>${escapeHtml(t('space.up', 'Up'))}</button> <strong>${escapeHtml(`${share}/${prefix}`)}</strong></p>`
    : '';
  const largest = (r.largest || []).slice(0, 20).map((f) => `<li><span class="space-path">${escapeHtml(f.path)}</span><span class="immich-note">${escapeHtml(formatBytes(f.bytes))}</span><button type="button" class="btn-pill-toggle is-small" data-space-show="${escapeHtml(f.path)}">${escapeHtml(t('space.show', 'Show'))}</button></li>`).join('');
  return `<p class="immich-note">${escapeHtml(t('space.summary', '{files} files, {size}, analysed {when}', { files: formatNumber(r.files || 0), size: formatBytes(r.bytes || 0), when: formatDateTime((r.scanned_at || 0) * 1000) }))}</p>
    ${r.complete === false ? `<p class="immich-note">${escapeHtml(t('space.incomplete', 'Stopped before the end: these numbers are for part of the share.'))}</p>` : ''}
    <h4>${escapeHtml(t('space.kinds', 'Kinds of files'))}</h4>${kindsSvg(r)}
    <h4>${escapeHtml(t('space.folders', 'Biggest folders'))}</h4>${crumbs}<div data-space-map>${treemapSvg(r, prefix)}</div>
    <h4>${escapeHtml(t('space.largest', 'Biggest files'))}</h4><ul class="space-largest">${largest}</ul>
    <div class="space-actions">${button}<button type="button" class="btn-pill-toggle" data-space-dups>${escapeHtml(t('space.duplicates', 'Find duplicates'))}</button></div>`;
}

export async function openStorageAnalyzer(share, root = '') {
  document.getElementById('space-modal')?.remove();
  const backdrop = document.createElement('div');
  backdrop.id = 'space-modal';
  backdrop.className = 'smart-modal-backdrop open';
  backdrop.innerHTML = `<div class="smart-modal-window space-window" role="dialog" aria-modal="true" aria-labelledby="space-title">
      <div class="smart-modal-header"><span class="smart-modal-title" id="space-title">${escapeHtml(t('space.title', 'Space in {share}', { share }))}</span>
        <div class="os-window-controls"><button type="button" class="win-btn close-btn" data-space-close aria-label="${escapeHtml(t('diagnostics.close_btn', 'Close'))}"></button></div></div>
      <div class="smart-modal-body" data-space-body><p class="immich-note">…</p></div></div>`;
  document.body.appendChild(backdrop);
  const body = backdrop.querySelector('[data-space-body]');
  let data = null;
  let prefix = '';
  let timer = null;
  const close = () => {
    clearTimeout(timer);
    backdrop.remove();
  };
  const render = () => {
    body.innerHTML = analysisHtml(share, data, prefix);
  };
  const load = async () => {
    try {
      data = await api.get(`/api/storage/analysis/${encodeURIComponent(share)}`);
    } catch (err) {
      body.innerHTML = `<p class="immich-note">${escapeHtml(err?.message || '')}</p>`;
      return;
    }
    render();
    clearTimeout(timer);
    if (data?.running && document.body.contains(backdrop)) timer = setTimeout(load, 2000);
  };
  backdrop.addEventListener('click', async (e) => {
    const target = /** @type {Element} */ (e.target);
    if (target === backdrop || target.closest('[data-space-close]')) return close();
    if (target.closest('[data-space-start]')) {
      try {
        await api.post('/api/storage/analysis', { share });
        data = { ...(data || {}), running: true };
        render();
        timer = setTimeout(load, 1500);
      } catch (err) {
        showToast(t('space.failed', "Couldn't start: {error}", { error: err?.message || '' }), 'error');
      }
      return;
    }
    const open = target.closest('[data-space-open]');
    if (open) {
      prefix = open.getAttribute('data-space-open') || '';
      return render();
    }
    if (target.closest('[data-space-up]')) {
      prefix = prefix.includes('/') ? prefix.slice(0, prefix.lastIndexOf('/')) : '';
      return render();
    }
    const show = target.closest('[data-space-show]');
    if (show && root) {
      const rel = show.getAttribute('data-space-show') || '';
      const folder = rel.includes('/') ? `${root}/${rel.slice(0, rel.lastIndexOf('/'))}` : root;
      const { ZettEventBus } = await import('../event-bus.js');
      ZettEventBus.emit('window:open', { id: 'file-manager-window', path: folder });
      return;
    }
    if (target.closest('[data-space-dups]')) {
      import('./management/duplicates.js').then((m) => m.openDuplicates()).catch(() => {});
    }
  });
  await load();
}
