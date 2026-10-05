/**
 * ZettNAS Toolkit Telemetry Dashboard
 * Renders hardware gauges, disk trays, fan tachometers, and live telemetry badges.
 */
import { state } from '../state.js';
import { ZettEventBus } from '../event-bus.js';
import { showConfirmToast, showToast } from '../toast.js';
import { updateFanCurveWorkstation } from './fan-control.js';
import { syncMiniPreviewTelemetry } from './mini-preview.js';
import { renderEventLog } from './events.js';

const $ = (id) => document.getElementById(id);
const FAN_LABELS = ['D1', 'D2', 'CPU', 'SYS'];

export function getLocalClock(tz, fmt) {
  try {
    const formatter = new Intl.DateTimeFormat([], {
      timeZone: tz || 'America/New_York',
      hour: 'numeric',
      minute: '2-digit',
      hour12: fmt === '12'
    });
    return formatter.format(new Date());
  } catch (e) {
    const d = new Date();
    return d.toTimeString().slice(0, 5);
  }
}

export const lvlDisk = (t) => t == null ? 'ok' : t >= 60 ? 'crit' : t >= 50 ? 'warn' : 'ok';
export const lvlCpu = (t) => t == null ? 'ok' : t >= 85 ? 'crit' : t >= 70 ? 'warn' : 'ok';
export const lvlUtil = (u) => u >= 90 ? 'crit' : u >= 75 ? 'warn' : 'ok';
export const lvlFull = (p) => p >= 90 ? 'crit' : p >= 75 ? 'warn' : 'ok';
export const cssVar = (lvl) => lvl === 'crit' ? 'var(--crit)' : lvl === 'warn' ? 'var(--warn)' : 'var(--ok)';

export function setArc(el, pct, lvl) {
  if (!el) return;
  el.style.setProperty('--pct', Math.max(0, Math.min(100, pct)));
  el.style.setProperty('--c', cssVar(lvl));
}

export function renderFans(fans) {
  const rows = document.querySelectorAll('.fan-row');
  if (rows.length === 0) return;

  if (!fans || fans.length === 0) {
    rows.forEach((r) => {
      r.innerHTML = '<span class="fv" style="color:var(--muted);font-size:11px">n/a</span>';
    });
    return;
  }

  const max = Math.max(...fans, 1);
  const count = fans.length;

  rows.forEach((r) => {
    r.classList.toggle('three-fans', count >= 3);
    r.classList.toggle('four-fans', count >= 4);

    const existing = r.querySelectorAll('.fan');

    if (existing.length !== count) {
      const html = fans.map((rpm, i) => {
        const dur = rpm > 0 ? Math.max(0.25, 2.0 - (rpm / max) * 1.7).toFixed(2) : 0;
        const label = FAN_LABELS[i] || (`F${i + 1}`);
        return (
          `<div class="fan">` +
          `<svg class="fan-ic${rpm > 0 ? ' spin' : ''}" style="--dur:${dur}s"><use href="#i-fan"/></svg>` +
          `<span class="fv">${rpm}</span>` +
          `<span class="fl">${label}</span>` +
          `</div>`
        );
      }).join('');
      r.innerHTML = html;
    } else {
      fans.forEach((rpm, i) => {
        const fanEl = existing[i];
        if (!fanEl) return;
        const dur = rpm > 0 ? Math.max(0.25, 2.0 - (rpm / max) * 1.7).toFixed(2) : 0;
        const ic = fanEl.querySelector('.fan-ic');
        const fv = fanEl.querySelector('.fv');
        if (fv && fv.textContent !== String(rpm)) fv.textContent = rpm;
        if (ic) {
          const wantSpin = rpm > 0;
          const hasSpin = ic.classList.contains('spin');
          if (wantSpin !== hasSpin) ic.classList.toggle('spin', wantSpin);
          const curDur = parseFloat(ic.style.getPropertyValue('--dur') || '0');
          if (Math.abs(curDur - parseFloat(dur)) > 0.03) {
            ic.style.setProperty('--dur', `${dur}s`);
          }
        }
      });
    }
  });

  fans.forEach((rpm, i) => {
    const dur = rpm > 0 ? Math.max(0.25, 2.0 - (rpm / max) * 1.7).toFixed(2) : 0;
    const dfRpm = $(`df-rpm-${i}`);
    const dfIc = $(`df-ic-${i}`);
    if (dfRpm) dfRpm.textContent = rpm;
    if (dfIc) {
      dfIc.style.setProperty('--dur', `${dur}s`);
      dfIc.classList.toggle('spin', rpm > 0);
    }
  });
}

const ROLE_META = {
  data:  { label: 'DATA',  icon: '#i-disk', cls: 'r-data' },
  cache: { label: 'CACHE', icon: '#i-nvme', cls: 'r-cache' },
  os:    { label: 'OS',    icon: '#i-nvme', cls: 'r-os' },
};

export function diskTile(d) {
  const isStandby = Boolean(d.standby || d.health === 'standby');
  const lvl = isStandby ? 'standby' : (d.health || lvlDisk(d.temp));
  const t = d.temp;
  const meta = ROLE_META[d.role] || ROLE_META.data;
  const w = isStandby ? 0 : (t == null ? 0 : Math.max(8, Math.min(100, ((t - 20) / 40) * 100)));
  const el = document.createElement('div');
  el.className = 'disk ' + meta.cls + ' h-' + lvl + (d.active ? ' io-active' : '') + (isStandby ? ' disk-standby' : '');
  el.dataset.dev = d.dev || d.name;
  el.title = isStandby ? `${d.name} is in standby (spun-down)` : `Click to inspect S.M.A.R.T. health for ${d.name}`;

  const tempHtml = isStandby
    ? `<div class="dt s-standby"><span class="standby-badge">STANDBY</span></div>`
    : `<div class="dt ${'s-' + lvl}">${t == null ? '--' : t}<span class="u">°C</span></div>`;

  el.innerHTML =
    `<div class="dh"><svg class="disk-ic"><use href="${meta.icon}"/></svg>` +
    `<span class="dn">${d.name}</span>` +
    `<div class="disk-indicators">` +
      (isStandby ? `<span class="standby-zzz" title="Spun-down / Standby">zZz</span>` : `<span class="io-dot" title="Active I/O"></span>`) +
      `<span class="hdot ${'dot-' + lvl}"></span>` +
    `</div></div>` +
    tempHtml +
    `<div class="db"><i class="${'bg-' + lvl}" style="width:${w}%"></i></div>`;

  return el;
}

export function renderDisks(disks) {
  const row = $('diskRow');
  if (!row) return;

  if (!row._hasDelegatedClicks) {
    row._hasDelegatedClicks = true;
    row.addEventListener('click', (e) => {
      const tile = e.target.closest('.disk');
      if (!tile) return;
      const dev = tile.dataset.dev;
      if (!dev) return;
      const isStandby = tile.classList.contains('disk-standby');
      const diskName = tile.querySelector('.dn')?.textContent || dev;
      if (isStandby) {
        showConfirmToast(
          'Drive in Standby Mode',
          `Disk ${diskName} is currently sleeping. Querying S.M.A.R.T. data will wake it up, causing mechanical wear and consuming power. Are you sure you want to wake it?`,
          () => ZettEventBus.emit('modal:smart:open', dev)
        );
      } else {
        ZettEventBus.emit('modal:smart:open', dev);
      }
    });
  }

  const total = disks.length || 1;
  row.classList.toggle('compact', total >= 7);

  const existingDevs = Array.from(row.querySelectorAll('[data-dev]')).map((el) => el.dataset.dev);
  const newDevs = disks.map((d) => d.dev || d.name);
  const existingSorted = [...existingDevs].sort().join(',');
  const newSorted = [...newDevs].sort().join(',');
  const structureChanged = existingSorted !== newSorted;

  if (structureChanged) {
    row.innerHTML = '';
    const order = ['os', 'data', 'cache'];
    const groups = order
      .map((r) => ({ role: r, items: disks.filter((d) => d.role === r) }))
      .filter((g) => g.items.length);
    const isYak = (state.currentTheme === 'yak');

    groups.forEach((g, gi) => {
      const meta = ROLE_META[g.role] || ROLE_META.data;
      const grp = document.createElement('div');
      grp.className = 'disk-group ' + meta.cls;
      grp.dataset.role = g.role;
      grp.style.setProperty('--n', g.items.length);

      const lab = document.createElement('div');
      lab.className = 'group-label';
      let roleLabel = meta.label;
      if (isYak) {
        if (g.role === 'data') roleLabel = 'PARCELS';
        else if (g.role === 'cache') roleLabel = 'EXPRESS';
        else if (g.role === 'os') roleLabel = 'LOGISTICS';
      }
      lab.innerHTML = `<svg class="grp-ic"><use href="${meta.icon}"/></svg>${roleLabel}`;
      grp.appendChild(lab);

      const tiles = document.createElement('div');
      tiles.className = 'group-tiles';
      tiles.style.setProperty('--n', g.items.length);
      g.items.forEach((d) => tiles.appendChild(diskTile(d)));
      grp.appendChild(tiles);

      row.appendChild(grp);
      if (gi < groups.length - 1) {
        const div = document.createElement('div');
        div.className = 'group-div';
        row.appendChild(div);
      }
    });
  } else {
    disks.forEach((d) => {
      const devId = d.dev || d.name;
      const tile = row.querySelector(`[data-dev="${devId}"]`);
      if (!tile) return;
      const isStandby = Boolean(d.standby || d.health === 'standby');
      const lvl = isStandby ? 'standby' : (d.health || lvlDisk(d.temp));
      const t = d.temp;
      const meta = ROLE_META[d.role] || ROLE_META.data;
      const w = isStandby ? 0 : (t == null ? 0 : Math.max(8, Math.min(100, ((t - 20) / 40) * 100)));

      tile.className = 'disk ' + meta.cls + ' h-' + lvl + (d.active ? ' io-active' : '') + (isStandby ? ' disk-standby' : '');
      tile.title = isStandby ? `${d.name} is in standby (spun-down)` : `Click to inspect S.M.A.R.T. health for ${d.name}`;

      const nameEl = tile.querySelector('.dn');
      if (nameEl) nameEl.textContent = d.name;

      const tempEl = tile.querySelector('.dt');
      if (tempEl) {
        tempEl.className = 'dt ' + (isStandby ? 's-standby' : 's-' + lvl);
        tempEl.innerHTML = isStandby
          ? `<span class="standby-badge">STANDBY</span>`
          : `${t == null ? '--' : t}<span class="u">°C</span>`;
      }

      const indEl = tile.querySelector('.disk-indicators');
      if (indEl) {
        indEl.innerHTML = (isStandby ? `<span class="standby-zzz" title="Spun-down / Standby">zZz</span>` : `<span class="io-dot" title="Active I/O"></span>`) +
          `<span class="hdot dot-${lvl}"></span>`;
      }

      const barEl = tile.querySelector('.db i');
      if (barEl) {
        barEl.className = 'bg-' + lvl;
        barEl.style.width = `${w}%`;
      }
    });
  }
}

export function updateRowTelemetryBadges(s) {
  if (!s) return;
  const stBadge = $('telemetry-badge-storage');
  const cpuBadge = $('telemetry-badge-cpu');
  const memBadge = $('telemetry-badge-mem');
  const fanBadge = $('telemetry-badge-fans');
  const netBadge = $('telemetry-badge-net');
  const dskBadge = $('telemetry-badge-disks');

  if (stBadge && s.storage) stBadge.textContent = `${s.storage.pct}% • ${s.storage.used}`;
  if (cpuBadge && s.cpu) cpuBadge.textContent = `${s.cpu.temp}°C • ${s.cpu.util}%`;
  if (memBadge && s.mem) memBadge.textContent = `${s.mem.pct}% • ${s.mem.used_gb}G`;
  if (fanBadge && s.fans && s.fans.length > 0) fanBadge.textContent = `${Math.max(...s.fans)} RPM`;
  if (netBadge && s.net) netBadge.textContent = `▲${s.net.tx} ▼${s.net.rx}`;
  if (dskBadge && s.disks) dskBadge.textContent = `${s.disks.length} Drives Active`;
}

export function updateChassisImageForTheme() {
  const chassisImg = $('chassis-hero-img');
  if (!chassisImg) return;

  if (state.currentTheme === 'yak') {
    chassisImg.src = 'img/yak.png';
  } else if (state.latestStats && state.latestStats.chassis) {
    const modelMap = {
      'd4': 'img/chassis-d4.png',
      'd8u': 'img/chassis-d8u.png',
      'd6u': 'img/chassis-d6u.png'
    };
    chassisImg.src = modelMap[state.latestStats.chassis] || 'img/chassis-d6u.png';
  }
}

export function applyTheme(themeName) {
  state.setTheme(themeName);
  const isYak = (themeName === 'yak');

  document.body.classList.toggle('theme-yak', isYak);

  const yakEggBtn = $('yak-easter-egg-btn');
  if (yakEggBtn) {
    yakEggBtn.title = isYak ? 'Yak Express Active! [Press Y or click to toggle]' : 'Trust in the Yak [Easter Egg Hot-key: Y]';
  }

  const title = $('suite-brand-title');
  const badge = $('suite-brand-badge');
  const engraved = $('chassis-panel-engraved');
  const drawerSub = $('drawer-sub-badge');
  const icon = $('suite-brand-icon');

  if (title) title.textContent = isYak ? 'YAK EXPRESS' : 'ZETTNAS';
  if (badge) badge.textContent = isYak ? 'RELIABILITY CULT' : 'HARDWARE TOOLKIT';
  if (engraved) engraved.textContent = isYak ? 'YAK EXPRESS • TOASTIE LOGISTICS LAB' : 'ZETTNAS • SYSTEM CONSOLE';
  if (drawerSub) drawerSub.textContent = isYak ? 'LOGISTICS LAB' : 'HARDWARE TOOLKIT';
  if (icon) icon.innerHTML = isYak ? '<use href="#i-yak"/>' : '<use href="#i-chip"/>';

  if ($('lbl-module-storage')) $('lbl-module-storage').textContent = isYak ? 'Cargo Hold (Capacity & Donut)' : 'Storage (Donut & Capacity)';
  if ($('lbl-module-cpu')) $('lbl-module-cpu').textContent = isYak ? 'YAK64 Toastie CPU' : 'CPU Gauge';
  if ($('lbl-module-fans')) $('lbl-module-fans').textContent = isYak ? 'Asthmatic Yak Airflow & Fans' : 'Fans & Uptime';
  if ($('lbl-module-disks')) $('lbl-module-disks').textContent = isYak ? 'Yak Parcel Bays (OS, Data, Cache)' : 'Drives Tray (OS, Data, Cache)';
  if ($('lbl-module-net')) $('lbl-module-net').textContent = isYak ? 'Transit Courier Throughput' : 'Network Throughput';

  const storageTitle = document.querySelector('.card-storage .card-title-txt');
  const cpuTitle = document.querySelector('.card-cpu .card-title-txt');
  const fansTitle = document.querySelector('.card-fans .card-title-txt');
  const netTitle = document.querySelector('.card-net .card-title-txt');
  if (storageTitle) storageTitle.textContent = isYak ? 'CARGO HOLD' : 'STORAGE';
  if (cpuTitle) cpuTitle.textContent = isYak ? 'YAK64 CPU' : 'CPU';
  if (fansTitle) fansTitle.textContent = isYak ? 'YAK AIRFLOW' : 'FANS';
  if (netTitle) netTitle.textContent = isYak ? 'TRANSIT I/O' : 'NETWORK I/O';

  if (state.latestStats && state.latestStats.disks) {
    renderDisks(state.latestStats.disks);
  }

  updateChassisImageForTheme();

  if (isYak) {
    const stageGlow = $('virtual-chassis-lightbar');
    if (stageGlow) {
      stageGlow.style.background = 'linear-gradient(90deg, #1b68b8 0%, #e07a38 50%, #1b68b8 100%)';
      stageGlow.style.boxShadow = '0 0 16px rgba(224, 122, 56, 0.5)';
    }
  }
}

export function applyStats(s) {
  try {
    state.setStats(s);
    if (s.events) renderEventLog(s.events);

    if (s.security && s.security.is_default_password) {
      const warnEl = document.getElementById('sec-default-pwd-warning');
      if (warnEl) warnEl.style.display = 'block';
      if (!window._defaultPwdWarned) {
        window._defaultPwdWarned = true;
        showToast("⚠️ Security Warning: Default password 'admin' is active! Please change it in Settings.", 'error');
      }
    }

    if ($('nasName')) $('nasName').textContent = s.name;
    if ($('drawer-nas-name')) $('drawer-nas-name').textContent = s.name.toUpperCase();

    if ($('statusText')) {
      if (state.currentTheme === 'yak' && !s.status.includes('ALERT') && !s.status.includes('WARN')) {
        $('statusText').textContent = 'YAK OK';
      } else {
        $('statusText').textContent = s.status;
      }
    }

    if ($('clock')) $('clock').textContent = getLocalClock(state.currentTimezone, state.clockFormat);
    if ($('ip')) $('ip').textContent = s.ip;

    updateChassisImageForTheme();

    const stLvl = lvlFull(s.storage.pct);
    if ($('storagePct')) $('storagePct').textContent = s.storage.pct + '%';
    if ($('stUsed')) $('stUsed').textContent = s.storage.used;
    if ($('stTotal')) $('stTotal').textContent = s.storage.total;
    const donut = $('donut');
    if (donut) {
      donut.style.setProperty('--pct', s.storage.pct);
      donut.style.setProperty('--c', cssVar(stLvl));
    }

    const cpuLvl = lvlCpu(s.cpu.temp);
    const utilLvl = lvlUtil(s.cpu.util);
    if ($('cpuTemp')) $('cpuTemp').textContent = s.cpu.temp;
    if ($('cpuTemp') && $('cpuTemp').parentElement) $('cpuTemp').parentElement.className = 'arc-val ' + 's-' + cpuLvl;
    if ($('cpuUtil')) {
      $('cpuUtil').textContent = s.cpu.util + '%';
      $('cpuUtil').className = 'val s-' + utilLvl;
    }
    if ($('cpuArc')) setArc($('cpuArc'), (s.cpu.temp / 100) * 100, cpuLvl);

    const memLvl = lvlUtil(s.mem.pct);
    if ($('memPct')) $('memPct').textContent = s.mem.pct;
    if ($('memPct') && $('memPct').parentElement) $('memPct').parentElement.className = 'arc-val s-' + memLvl;
    if ($('memUsed')) $('memUsed').textContent = s.mem.used_gb.toFixed(1) + 'G';
    if ($('memTotal')) $('memTotal').textContent = '/' + s.mem.total_gb.toFixed(0) + 'G';
    if ($('memArc')) setArc($('memArc'), s.mem.pct, memLvl);

    renderFans(s.fans);
    renderDisks(s.disks);
    if ($('uptime')) $('uptime').textContent = 'up ' + s.uptime;

    if (s.net) {
      if ($('netTx')) $('netTx').textContent = s.net.tx;
      if ($('netRx')) $('netRx').textContent = s.net.rx;
    }

    if (!state.isLcdDirect) {
      ZettEventBus.emit('stats_tick', s);
      updateRowTelemetryBadges(s);
      updateFanCurveWorkstation(s);
      if (document.body.classList.contains('drawer-is-open')) {
        syncMiniPreviewTelemetry();
      }
    }

    let anyWarn = [stLvl, cpuLvl, utilLvl, memLvl].includes('crit') ||
      s.disks.some((d) => (d.health || lvlDisk(d.temp)) !== 'ok');
    if ($('statusPill')) $('statusPill').className = 'pill' + (anyWarn ? ' warn' : '');

  } catch (e) {
    console.error('Error applying stats:', e);
  }
}

export function initDashboardClicks() {
  const screen = $('screen');
  if (!screen) return;
  screen.querySelectorAll('.card-storage').forEach((el) => el.addEventListener('click', () => ZettEventBus.emit('modal:metric:open', 'storage')));
  screen.querySelectorAll('.card-cpu').forEach((el) => el.addEventListener('click', () => ZettEventBus.emit('modal:metric:open', 'cpu')));
  screen.querySelectorAll('.card-mem').forEach((el) => el.addEventListener('click', () => ZettEventBus.emit('modal:metric:open', 'mem')));
  screen.querySelectorAll('.card-fans').forEach((el) => el.addEventListener('click', () => ZettEventBus.emit('modal:metric:open', 'fans')));
  screen.querySelectorAll('.card-net').forEach((el) => el.addEventListener('click', () => ZettEventBus.emit('modal:metric:open', 'net')));
}
