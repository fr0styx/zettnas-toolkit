import { escapeHtml } from '../utils.js';
/**
 * ZettNAS Toolkit Telemetry Dashboard
 * Renders hardware gauges, disk trays, fan tachometers, and live telemetry badges.
 */
import { state } from '../state.js';
import { api } from '../api.js';
import { ZettEventBus } from '../event-bus.js';
import { showConfirmToast, hideConfirmToast, showToast } from '../toast.js';
import { updateFanCurveWorkstation } from './fan-control.js';
import { syncMiniPreviewTelemetry, applyDashboardLayout } from './mini-preview.js';
import { renderEventLog } from './events.js';
import { checkAndTriggerSetupWizard } from './setup-wizard.js';
import { updateManagementTelemetry } from './management.js';
import { t } from '../i18n.js';

const $ = (id) => document.getElementById(id);
const FAN_LABELS = ['D1', 'D2', 'CPU', 'SYS'];

export function setText(el, text) {
  if (!el) return;
  const str = text == null ? '' : String(text);
  if (el.textContent !== str) {
    el.textContent = str;
  }
}

export function setHtml(el, html) {
  if (!el) return;
  const str = html == null ? '' : String(html);
  if (el.innerHTML !== str) {
    el.innerHTML = str;
  }
}

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
    `<span class="dn">${escapeHtml(d.name)}</span>` +
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
      const diskData = state.latestStats?.disks?.find((d) => (d.dev || d.name) === dev || d.name === dev || d.dev === dev);
      const isStandby = tile.classList.contains('disk-standby') || Boolean(diskData?.standby || diskData?.health === 'standby');
      const diskName = tile.querySelector('.dn')?.textContent || diskData?.name || dev;
      if (isStandby) {
        showConfirmToast(
          'Drive in Standby Mode',
          `Disk ${diskName} is currently sleeping. Querying S.M.A.R.T. data will wake it up, causing mechanical wear and consuming power. Are you sure you want to wake it?`,
          () => {
            showToast(`Waking disk ${diskName}...`, 'info');
            ZettEventBus.emit('modal:smart:open', dev);
          }
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
      } else {
        roleLabel = t(`console.role_${g.role}`, meta.label);
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

  const modelMap = {
    'd4': 'img/chassis-d4.webp',
    'd8u': 'img/chassis-d8u.webp',
    'd6u': 'img/chassis-d6u.webp'
  };
  const chassis = (state.latestStats && state.latestStats.chassis) ? state.latestStats.chassis : 'd6u';
  chassisImg.src = modelMap[chassis] || 'img/chassis-d6u.webp';
}

let _systemThemeMatcher = null;

export function applyTheme(themeName) {
  state.setTheme(themeName);

  document.body.classList.remove('theme-light', 'theme-yak', 'theme-amber', 'theme-emerald');

  if (themeName === 'auto' || themeName === 'system') {
    if (!_systemThemeMatcher && typeof window !== 'undefined' && window.matchMedia) {
      _systemThemeMatcher = window.matchMedia('(prefers-color-scheme: dark)');
      _systemThemeMatcher.addEventListener('change', () => {
        if (state.currentTheme === 'auto' || state.currentTheme === 'system') {
          applyTheme('auto');
        }
      });
    }
    const isDark = _systemThemeMatcher ? _systemThemeMatcher.matches : true;
    document.body.classList.toggle('theme-light', !isDark);
  } else if (themeName === 'amber') {
    document.body.classList.add('theme-amber');
  } else if (themeName === 'emerald') {
    document.body.classList.add('theme-emerald');
  } else if (themeName === 'yak') {
    document.body.classList.add('theme-yak');
  } else if (themeName === 'light') {
    document.body.classList.add('theme-light');
  }

  const isYak = (themeName === 'yak');
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
  if (badge) badge.textContent = isYak ? 'RELIABILITY CULT' : t('nav.toolkit', 'NAS WORKBENCH');
  if (engraved) engraved.textContent = isYak ? 'YAK EXPRESS • TOASTIE LOGISTICS LAB' : t('console.engraved_title', 'ZETTNAS • SYSTEM CONSOLE');
  if (drawerSub) drawerSub.textContent = isYak ? 'LOGISTICS LAB' : t('settings.drawer_badge', 'NAS WORKBENCH');
  if (icon) icon.innerHTML = isYak ? '<use href="#i-yak"/>' : '<use href="#i-chip"/>';

  if ($('lbl-module-storage')) $('lbl-module-storage').textContent = isYak ? 'Cargo Hold (Capacity & Donut)' : t('settings.mod_storage', 'Storage (Donut & Capacity)');
  if ($('lbl-module-cpu')) $('lbl-module-cpu').textContent = isYak ? 'YAK64 Toastie CPU' : t('settings.mod_cpu', 'CPU Gauge');
  if ($('lbl-module-fans')) $('lbl-module-fans').textContent = isYak ? 'Asthmatic Yak Airflow & Fans' : t('settings.mod_fans', 'Fans & Uptime');
  if ($('lbl-module-disks')) $('lbl-module-disks').textContent = isYak ? 'Yak Parcel Bays (OS, Data, Cache)' : t('settings.mod_disks', 'Drives Tray (OS, Data, Cache)');
  if ($('lbl-module-net')) $('lbl-module-net').textContent = isYak ? 'Transit Courier Throughput' : t('settings.mod_net', 'Network Throughput');

  const storageTitle = document.querySelector('.card-storage .card-title-txt');
  const cpuTitle = document.querySelector('.card-cpu .card-title-txt');
  const fansTitle = document.querySelector('.card-fans .card-title-txt');
  const netTitle = document.querySelector('.card-net .card-title-txt');
  if (storageTitle) storageTitle.textContent = isYak ? 'CARGO HOLD' : t('console.storage', 'STORAGE');
  if (cpuTitle) cpuTitle.textContent = isYak ? 'YAK64 CPU' : t('console.cpu', 'CPU');
  if (fansTitle) fansTitle.textContent = isYak ? 'YAK AIRFLOW' : t('console.fans', 'FANS');
  if (netTitle) netTitle.textContent = isYak ? 'TRANSIT I/O' : t('console.net', 'NETWORK I/O');

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

let _defaultPwdWarned = false;

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && state.latestStats) {
      applyStats(state.latestStats);
    }
  });
}

export function applyStats(s) {
  try {
    const changed = state.setStats(s);
    if (typeof document !== 'undefined' && document.hidden && !state.isLcdDirect) {
      return;
    }
    // Always refresh the clock to keep time accurate to the minute
    setText($('clock'), getLocalClock(state.currentTimezone, state.clockFormat));

    // If telemetry hasn't changed and this isn't the first render, skip heavy DOM updates
    if (!changed && state.latestStats) {
      return;
    }
    if (s.events) renderEventLog(s.events);

    if (s.security && s.security.is_default_password) {
      const warnEl = document.getElementById('sec-default-pwd-warning');
      if (warnEl) warnEl.style.display = 'block';
      if (!_defaultPwdWarned) {
        _defaultPwdWarned = true;
        showToast(t('toast.default_pwd_alert', "Security Warning: Default password 'admin' is active! Please change it in Settings."), 'error');
      }
      checkAndTriggerSetupWizard(s);
    }

    setText($('nasName'), s.name);
    setText($('drawer-nas-name'), s.name ? s.name.toUpperCase() : '');

    if ($('statusText')) {
      const statusVal = (state.currentTheme === 'yak' && !s.status.includes('ALERT') && !s.status.includes('WARN'))
        ? 'YAK OK'
        : s.status;
      setText($('statusText'), statusVal);
    }

    setText($('clock'), getLocalClock(state.currentTimezone, state.clockFormat));
    setText($('ip'), s.ip);

    updateChassisImageForTheme();

    const stLvl = lvlFull(s.storage.pct);
    setText($('storagePct'), s.storage.pct + '%');
    setText($('stUsed'), s.storage.used);
    setText($('stTotal'), s.storage.total);
    const donut = $('donut');
    if (donut) {
      donut.style.setProperty('--pct', s.storage.pct);
      donut.style.setProperty('--c', cssVar(stLvl));
    }

    const cpuLvl = lvlCpu(s.cpu.temp);
    const utilLvl = lvlUtil(s.cpu.util);
    setText($('cpuTemp'), s.cpu.temp);
    if ($('cpuTemp') && $('cpuTemp').parentElement) $('cpuTemp').parentElement.className = 'arc-val ' + 's-' + cpuLvl;
    if ($('cpuUtil')) {
      setText($('cpuUtil'), s.cpu.util + '%');
      $('cpuUtil').className = 'val s-' + utilLvl;
    }
    if ($('cpuArc')) setArc($('cpuArc'), (s.cpu.temp / 100) * 100, cpuLvl);

    const memLvl = lvlUtil(s.mem.pct);
    setText($('memPct'), s.mem.pct);
    if ($('memPct') && $('memPct').parentElement) $('memPct').parentElement.className = 'arc-val s-' + memLvl;
    setText($('memUsed'), s.mem.used_gb.toFixed(1) + 'G');
    setText($('memTotal'), '/' + s.mem.total_gb.toFixed(0) + 'G');
    if ($('memArc')) setArc($('memArc'), s.mem.pct, memLvl);

    renderFans(s.fans);
    renderDisks(s.disks);
    setText($('uptime'), 'up ' + s.uptime);

    if (s.net) {
      setText($('netTx'), s.net.tx);
      setText($('netRx'), s.net.rx);
    }

    if (s.layout && s.layout.version && s.layout.version !== state.activeLayoutVersion) {
      state.activeLayoutVersion = s.layout.version;
      if (s.layout.order) state.dashOrder = s.layout.order;
      if (s.layout.vis) state.dashVis = s.layout.vis;
      if (s.layout.sizes) state.dashSizes = s.layout.sizes;
      if (s.layout.clock_format) state.clockFormat = s.layout.clock_format;
      if (s.layout.timezone) state.currentTimezone = s.layout.timezone;
      applyDashboardLayout();
    }

    updateMediaSlots(s.media_slots);
    if (!state.isLcdDirect) {
      updateCopyToast(s.copy_state);
    }

    updateUnraidTelemetry(s.unraid);
    updateLcdPages(s);

    if (!state.isLcdDirect) {
      updateManagementTelemetry(s);
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

let _currentLcdPageIndex = 0;
let _lcdDotsInitialized = false;
let _netPeakRx = 0.0;
let _netPeakTx = 0.0;

export function updateUnraidTelemetry(unraid) {
  const arrayPill = $('unraid-array-pill');
  const parityPill = $('unraid-parity-pill');
  const moverPill = $('unraid-mover-pill');
  const storageBadge = $('unraid-storage-badge');
  const storageText = $('unraid-storage-text');
  const storageDot = $('unraid-storage-dot');
  const parityBox = $('unraid-parity-box');
  const parityBar = $('unraid-parity-bar');
  const parityTxt = $('unraid-parity-txt');

  if (!unraid || !unraid.available) {
    if (arrayPill) arrayPill.classList.add('hidden');
    if (parityPill) parityPill.classList.add('hidden');
    if (moverPill) moverPill.classList.add('hidden');
    if (storageBadge) storageBadge.classList.add('hidden');
    if (parityBox) parityBox.classList.add('hidden');
    return;
  }

  // Navbar Array Pill
  if (arrayPill) {
    arrayPill.classList.remove('hidden');
    const statusEl = $('unraid-array-status');
    const dotEl = $('unraid-array-dot');
    if (statusEl) statusEl.textContent = unraid.state || 'STARTED';
    if (dotEl) {
      dotEl.style.background = unraid.is_healthy ? 'var(--ok2)' : unraid.color?.startsWith('yellow') ? 'var(--warn)' : 'var(--crit)';
    }
  }

  // Navbar Parity Pill
  if (parityPill) {
    const p = unraid.parity_check || {};
    if (p.active) {
      parityPill.classList.remove('hidden');
      const pStatus = $('unraid-parity-status');
      if (pStatus) pStatus.textContent = `${p.progress_pct || 0}%`;
    } else {
      parityPill.classList.add('hidden');
    }
  }

  // Navbar Mover Pill
  if (moverPill) {
    const m = unraid.mover || {};
    if (m.active) {
      moverPill.classList.remove('hidden');
      const mStatus = $('unraid-mover-status');
      if (mStatus) mStatus.textContent = m.remain_files ? `${m.remain_files} left` : 'Active';
    } else {
      moverPill.classList.add('hidden');
    }
  }

  // Storage Card Badges
  if (storageBadge && storageText) {
    storageBadge.classList.remove('hidden');
    storageText.textContent = `UNRAID: ${unraid.state || 'STARTED'}`;
    if (storageDot) {
      storageDot.style.background = unraid.is_healthy ? 'var(--ok2)' : 'var(--warn)';
    }
  }

  if (parityBox && parityBar && parityTxt) {
    const p = unraid.parity_check || {};
    if (p.active) {
      parityBox.classList.remove('hidden');
      parityBar.style.width = `${p.progress_pct || 0}%`;
      parityTxt.textContent = `Parity: ${p.progress_pct || 0}% (${p.errors || 0} err)`;
    } else {
      parityBox.classList.add('hidden');
    }
  }
}

export function switchLcdPage(targetIndex, pushToServer = true) {
  _currentLcdPageIndex = targetIndex;
  document.querySelectorAll('.lcd-page').forEach((p) => {
    p.classList.toggle('active', parseInt(p.dataset.pageIndex, 10) === targetIndex);
  });
  document.querySelectorAll('#lcd-page-dots .lcd-dot').forEach((d) => {
    d.classList.toggle('active', parseInt(d.dataset.page, 10) === targetIndex);
  });
  if (pushToServer) {
    api.post('/api/lcd/page', { page: targetIndex }).catch(() => {});
  }
}

if (typeof window !== 'undefined') {
  window.switchLcdPage = switchLcdPage;
}

export function initLcdPageDots() {
  if (_lcdDotsInitialized) return;
  _lcdDotsInitialized = true;
  document.querySelectorAll('#lcd-page-dots .lcd-dot').forEach((dot) => {
    dot.addEventListener('click', (e) => {
      e.stopPropagation();
      const pIdx = parseInt(dot.dataset.page, 10);
      switchLcdPage(pIdx, true);
    });
  });
}

export function updateLcdPages(s) {
  initLcdPageDots();
  if (typeof window !== 'undefined') window.updateLcdPages = updateLcdPages;

  // Skip DOM reconstruction if console window is minimized or closed (unless in lcd-direct hardware mode)
  if (!state.isLcdDirect) {
    const consoleOverlay = $('console-modal-overlay');
    const isVisible = consoleOverlay && consoleOverlay.classList.contains('open') && !consoleOverlay.classList.contains('window-minimized') && consoleOverlay.style.display !== 'none';
    if (!isVisible) return;
  }

  // Sync active page from server if changed
  if (s.lcd && typeof s.lcd.page === 'number' && s.lcd.page !== _currentLcdPageIndex) {
    switchLcdPage(s.lcd.page, false);
  }

  // Page 1: Drive Bay & S.M.A.R.T. Matrix
  const bayGrid = $('lcd-bay-matrix-grid');
  if (bayGrid && s.disks) {
    const disks = s.disks;
    const numBays = Math.max(6, disks.length);
    let matrixHtml = '';
    for (let i = 0; i < numBays; i++) {
      const d = disks[i];
      if (!d) {
        matrixHtml += `
          <div class="bay-matrix-card empty">
            <span class="bmc-num">BAY ${i + 1}</span>
            <svg class="bmc-icon" style="opacity:0.3;"><use href="#i-disk"/></svg>
            <span class="bmc-dev">EMPTY</span>
            <div class="bmc-pills">
              <span class="bmc-health standby">EMPTY</span>
            </div>
          </div>
        `;
      } else {
        const isStandby = !!d.standby;
        const temp = isStandby ? '--' : (d.temp != null ? `${d.temp}°` : '--');
        const hClass = isStandby ? 'standby' : (d.health || 'ok');
        const hText = isStandby ? 'STBY' : (d.health ? d.health.toUpperCase() : 'OK');
        const devName = d.name || d.dev || `sd${String.fromCharCode(97 + i)}`;
        const modelStr = d.model ? d.model.slice(0, 10) : devName;

        matrixHtml += `
          <div class="bay-matrix-card ${hClass}">
            <span class="bmc-num">BAY ${i + 1}</span>
            <svg class="bmc-icon"><use href="#i-disk"/></svg>
            <span class="bmc-dev" title="${escapeHtml(d.model || devName)}">${escapeHtml(modelStr)}</span>
            <div class="bmc-pills">
              <span class="bmc-temp">${temp}</span>
              <span class="bmc-health ${hClass}">${hText}</span>
            </div>
          </div>
        `;
      }
    }
    bayGrid.innerHTML = matrixHtml;

    const summaryEl = $('lcd-matrix-summary');
    if (summaryEl) {
      const critCount = disks.filter((d) => d.health === 'crit').length;
      const warnCount = disks.filter((d) => d.health === 'warn').length;
      if (critCount > 0) {
        summaryEl.textContent = `${critCount} CRITICAL ALERT`;
        summaryEl.style.color = 'var(--crit)';
      } else if (warnCount > 0) {
        summaryEl.textContent = `${warnCount} WARNING`;
        summaryEl.style.color = 'var(--warn)';
      } else {
        summaryEl.textContent = 'ALL DRIVES HEALTHY';
        summaryEl.style.color = 'var(--ok2)';
      }
    }
  }

  // Page 2: Network & IO Telemetry
  if (s.net) {
    const rxStr = s.net.rx || '0 B/s';
    const txStr = s.net.tx || '0 B/s';
    if ($('lcd-nio-rx')) $('lcd-nio-rx').textContent = rxStr;
    if ($('lcd-nio-tx')) $('lcd-nio-tx').textContent = txStr;

    const parseRateVal = (r) => {
      if (!r) return 0;
      const num = parseFloat(r);
      if (r.includes('GB/s')) return num * 1024;
      if (r.includes('MB/s')) return num;
      if (r.includes('KB/s')) return num / 1024;
      return num / 1024 / 1024;
    };

    const rxMB = parseRateVal(rxStr);
    const txMB = parseRateVal(txStr);
    if (rxMB > _netPeakRx) _netPeakRx = rxMB;
    if (txMB > _netPeakTx) _netPeakTx = txMB;

    if ($('lcd-nio-rx-peak')) $('lcd-nio-rx-peak').textContent = `Peak: ${_netPeakRx.toFixed(1)} MB/s`;
    if ($('lcd-nio-tx-peak')) $('lcd-nio-tx-peak').textContent = `Peak: ${_netPeakTx.toFixed(1)} MB/s`;
    if ($('lcd-nio-ip')) $('lcd-nio-ip').textContent = `IP: ${s.ip || '0.0.0.0'}`;
    if ($('lcd-nio-uptime')) $('lcd-nio-uptime').textContent = `up ${s.uptime || '--'}`;

    const rxPct = Math.min(100, Math.round((rxMB / 125.0) * 100));
    const txPct = Math.min(100, Math.round((txMB / 125.0) * 100));
    if ($('lcd-nio-rx-bar')) $('lcd-nio-rx-bar').style.width = `${rxPct}%`;
    if ($('lcd-nio-tx-bar')) $('lcd-nio-tx-bar').style.width = `${txPct}%`;

    // Disk total IO rate
    let totalDiskRate = 0.0;
    if (s.disks) {
      s.disks.forEach((d) => {
        if (d.io_rate) totalDiskRate += parseRateVal(d.io_rate);
      });
    }
    if ($('lcd-nio-disk-total')) $('lcd-nio-disk-total').textContent = `${totalDiskRate.toFixed(1)} MB/s`;
    const ioPct = Math.min(100, Math.round((totalDiskRate / 200.0) * 100));
    if ($('lcd-nio-io-bar')) $('lcd-nio-io-bar').style.width = `${ioPct}%`;
  }

  // Page 3: Unraid Array & Copy Hub
  const unraid = s.unraid || {};
  if ($('lcd-uc-array-badge')) {
    $('lcd-uc-array-badge').textContent = unraid.available ? (unraid.state || 'STARTED') : 'STANDALONE';
    $('lcd-uc-array-badge').style.background = unraid.is_healthy ? 'rgba(37,194,160,0.15)' : 'rgba(240,85,59,0.15)';
    $('lcd-uc-array-badge').style.color = unraid.is_healthy ? 'var(--ok2)' : 'var(--crit)';
  }
  if ($('lcd-unraid-headline')) {
    $('lcd-unraid-headline').textContent = unraid.available ? `UNRAID ${unraid.version || ''}` : 'STANDALONE OS';
  }
  if ($('lcd-uc-disks-stat') && unraid.disks) {
    const d = unraid.disks;
    $('lcd-uc-disks-stat').textContent = `Disks: ${d.total || 0} Assigned • ${d.disabled || 0} Disabled • ${d.missing || 0} Missing`;
  }
  if (unraid.parity_check) {
    const p = unraid.parity_check;
    if ($('lcd-uc-parity-action')) $('lcd-uc-parity-action').textContent = p.active ? (p.action || 'Parity Sync') : 'Parity Check';
    if ($('lcd-uc-parity-pct')) $('lcd-uc-parity-pct').textContent = p.active ? `${p.progress_pct}%` : 'Idle';
    if ($('lcd-uc-parity-bar')) $('lcd-uc-parity-bar').style.width = p.active ? `${p.progress_pct}%` : '0%';
  }

  // Media slots & Copy in Page 3
  if ($('lcd-uc-media-slots') && s.media_slots) {
    const sd = s.media_slots.sd || {};
    const tf = s.media_slots.tf || {};
    const sdStr = sd.size ? `${(sd.size / 1e9).toFixed(0)} GB` : 'Empty';
    const tfStr = tf.size ? `${(tf.size / 1e9).toFixed(0)} GB` : 'Empty';
    $('lcd-uc-media-slots').textContent = `SD: ${sdStr} • TF: ${tfStr}`;
  }
  const copyState = s.copy_state || {};
  if ($('lcd-uc-copy-badge')) {
    $('lcd-uc-copy-badge').textContent = (copyState.status || 'IDLE').toUpperCase();
  }
  if (copyState.progress) {
    const prog = copyState.progress;
    const total = prog.total || 0;
    const copied = prog.copied || 0;
    const pct = total > 0 ? Math.min(100, Math.round((copied / total) * 100)) : (copyState.status === 'success' ? 100 : 0);
    if ($('lcd-uc-copy-file')) $('lcd-uc-copy-file').textContent = prog.file || (copyState.status === 'success' ? 'Transfer complete' : 'No active transfer');
    if ($('lcd-uc-copy-pct')) $('lcd-uc-copy-pct').textContent = copyState.active ? `${pct}%` : (copyState.status === 'success' ? '100%' : '--');
    if ($('lcd-uc-copy-bar')) $('lcd-uc-copy-bar').style.width = `${pct}%`;
  }
}

let copyToastMinimized = false;
let copyToastInitialized = false;

const confirmCopy = async (action) => {
  try {
    const actionsDiv = $('copy-toast-actions');
    if (actionsDiv) {
      actionsDiv.style.opacity = '0.5';
      actionsDiv.style.pointerEvents = 'none';
    }
    await api.post('/api/copy/confirm', { action });
  } catch (e) {
    console.warn('Confirm copy failed', e);
  }
};

const abortCopyConfirm = async (yes) => {
  const abortDiv = $('copy-toast-abort-actions');
  if (yes) {
    if (abortDiv) {
      abortDiv.style.opacity = '0.5';
      abortDiv.style.pointerEvents = 'none';
    }
    try {
      await api.post('/api/copy/cancel');
    } catch (e) {
      console.warn('Cancel copy failed', e);
    }
  } else {
    if (abortDiv) abortDiv.style.display = 'none';
  }
};

function initCopyToastControls() {
  if (copyToastInitialized) return;
  copyToastInitialized = true;

  const btnPause = $('copy-toast-pause');
  if (btnPause) {
    btnPause.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const isPaused = btnPause.textContent === '▶';
      const endpoint = isPaused ? '/api/copy/resume' : '/api/copy/pause';
      try {
        await api.post(endpoint);
        btnPause.textContent = isPaused ? '⏸' : '▶';
      } catch (err) {
        console.warn('Toggle copy pause failed', err);
      }
    });
  }

  const btnCancel = $('copy-toast-cancel');
  if (btnCancel) {
    btnCancel.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const statusText = ($('copy-toast-status')?.textContent || '').toUpperCase();
      if (statusText === 'FAILED!' || statusText === 'SUCCESS!' || statusText === 'ERROR!' || statusText === 'DONE!') {
        const toast = $('copy-toast');
        if (toast) {
          toast.style.opacity = '0';
          toast.style.pointerEvents = 'none';
        }
        api.post('/api/copy/cancel').catch(() => {});
        return;
      }

      let abortDiv = $('copy-toast-abort-actions');
      if (!abortDiv) {
        abortDiv = document.createElement('div');
        abortDiv.id = 'copy-toast-abort-actions';
        abortDiv.style.cssText = 'margin-top:10px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.05);';
        abortDiv.innerHTML = `
          <div style="font-size:11px; color:#cbd5e1; margin-bottom:8px; font-weight:500;">Are you sure you want to completely abort the transfer? All incomplete files will be deleted.</div>
          <div style="display:flex; gap:8px;">
            <button id="copy-abort-btn-yes" class="btn-save-preset" style="flex:1; padding:6px; border-color:rgba(240,85,59,0.5); color:var(--crit);">Yes, Abort</button>
            <button id="copy-abort-btn-no" class="btn-save-preset" style="flex:1; padding:6px;">Resume</button>
          </div>
        `;
        abortDiv.querySelector('#copy-abort-btn-yes')?.addEventListener('click', () => abortCopyConfirm(true));
        abortDiv.querySelector('#copy-abort-btn-no')?.addEventListener('click', () => abortCopyConfirm(false));
        $('copy-toast')?.querySelector('.smart-modal-body')?.appendChild(abortDiv);
      } else {
        abortDiv.style.display = 'block';
        abortDiv.style.opacity = '1';
        abortDiv.style.pointerEvents = 'auto';
      }
    });
  }

  const btnMin = $('copy-toast-min');
  if (btnMin) {
    btnMin.addEventListener('click', () => {
      copyToastMinimized = !copyToastMinimized;
      btnMin.textContent = copyToastMinimized ? '□' : '–';
      const toast = $('copy-toast');
      if (toast) toast.style.transform = copyToastMinimized ? 'translateY(160px)' : 'translateY(0)';
    });
  }
}

let _activeIngestPromptTs = null;
let _dismissedIngestTs = null;
let _ejectedSlots = new Set();

export function setSlotEjected(slot) {
  if (slot) _ejectedSlots.add(slot);
  if (_activeIngestPromptTs !== null) {
    hideConfirmToast();
    _activeIngestPromptTs = null;
  }
}

export function clearSlotEjected(slot) {
  if (slot) {
    _ejectedSlots.delete(slot);
  } else {
    _ejectedSlots.clear();
  }
}

export function handlePendingIngest(pendingIngest) {
  if (!pendingIngest || !pendingIngest.slot) {
    if (_activeIngestPromptTs !== null) {
      hideConfirmToast();
      _activeIngestPromptTs = null;
    }
    _dismissedIngestTs = null;
    return;
  }

  // If slot was ejected by the user and card has not been physically removed, do NOT re-prompt
  if (_ejectedSlots.has(pendingIngest.slot)) {
    if (_activeIngestPromptTs !== null) {
      hideConfirmToast();
      _activeIngestPromptTs = null;
    }
    return;
  }

  // If already showing this prompt or if user already dismissed it
  if (pendingIngest.ts === _activeIngestPromptTs || pendingIngest.ts === _dismissedIngestTs) {
    return;
  }

  _activeIngestPromptTs = pendingIngest.ts;
  const slotName = pendingIngest.slot === 'sd' ? 'SD Card' : 'TF (MicroSD) Card';
  const sizeGb = pendingIngest.size ? (pendingIngest.size / 1e9).toFixed(1) + ' GB' : '';
  const devStr = pendingIngest.dev ? `/dev/${pendingIngest.dev}` : pendingIngest.slot.toUpperCase();
  const destPath = pendingIngest.dest || '/mnt/user/';

  const title = t('media.ingest_prompt_title', 'Media Card Ingest');
  const sizeBadge = sizeGb ? ` (${sizeGb})` : '';
  const msg = `<div style="display:flex; flex-direction:column; gap:10px;">
    <div>${t('media.ingest_prompt_detected', 'Detected')} <strong>${escapeHtml(slotName)}</strong>${escapeHtml(sizeBadge)} on <code>${escapeHtml(devStr)}</code>.</div>
    <div style="font-size:12px; color:var(--muted);">${t('media.ingest_prompt_dest', 'Target Destination:')} <code style="color:var(--ok2);">${escapeHtml(destPath)}</code></div>
    <div>${t('media.ingest_prompt_confirm_q', 'Would you like to import and organize photos into dated folders now?')}</div>
  </div>`;

  showConfirmToast(
    title,
    msg,
    async () => {
      _activeIngestPromptTs = null;
      try {
        await api.post('/api/copy/start', { source: pendingIngest.slot, dest: destPath });
        showToast(t('media.ingest_started', `Importing media from ${slotName}...`), 'info');
      } catch (err) {
        showToast(`Failed to start ingest: ${err.message || err}`, 'error');
      }
    },
    async () => {
      _dismissedIngestTs = pendingIngest.ts;
      _activeIngestPromptTs = null;
      try {
        await api.post('/api/copy/dismiss-ingest');
      } catch (e) {
        // ignore
      }
    },
    {
      isMedia: true,
      okText: t('media.btn_start_ingest', '📥 Start Ingest'),
      cancelText: t('media.btn_dismiss', 'Dismiss'),
      ejectText: t('media.btn_eject', '⏏ Eject'),
      onEject: async () => {
        _ejectedSlots.add(pendingIngest.slot);
        _activeIngestPromptTs = null;
        _dismissedIngestTs = null;
        try {
          await api.post('/api/copy/eject', { slot: pendingIngest.slot });
          showToast(t('media.ejected', 'Card safely unmounted and ejected. You can now remove it.'), 'info');
        } catch (err) {
          showToast(`Eject failed: ${err.message || err}`, 'error');
        }
      }
    }
  );
}

export function updateCopyToast(copyState) {
  handlePendingIngest(copyState ? copyState.pending_ingest : null);

  const toast = $('copy-toast');
  const backdrop = $('copy-toast-backdrop');
  if (!toast) return;

  initCopyToastControls();

  const active = copyState && (copyState.active || (copyState.status && copyState.status !== 'idle'));
  if (active) {
    toast.style.opacity = '1';
    toast.style.pointerEvents = 'auto';
    toast.style.transform = copyToastMinimized ? 'translateY(160px)' : 'translateY(0)';
    if (backdrop && !copyToastMinimized && copyState.status === 'awaiting_confirmation') {
      backdrop.style.opacity = '1';
      backdrop.style.pointerEvents = 'auto';
    } else if (backdrop) {
      backdrop.style.opacity = '0';
      backdrop.style.pointerEvents = 'none';
    }

    const prog = copyState.progress || {};
    const total = prog.total || 0;
    const copied = prog.copied || 0;
    const pct = total > 0 ? Math.min(100, Math.round((copied / total) * 100)) : (copyState.status === 'success' ? 100 : 0);

    if ($('copy-toast-pct')) $('copy-toast-pct').textContent = copyState.status === 'awaiting_confirmation' ? 'WAIT' : `${pct}%`;
    if ($('copy-toast-bar')) $('copy-toast-bar').style.width = `${pct}%`;
    if ($('copy-toast-file')) $('copy-toast-file').textContent = prog.file || 'Preparing files...';

    let statusText = 'COPYING...';
    let barColor = 'var(--ok2)';
    if (copyState.status === 'copying') {
      statusText = 'COPYING...';
      barColor = 'var(--ok2)';
      if ($('copy-toast-pause')) $('copy-toast-pause').textContent = '⏸';
    } else if (copyState.status === 'paused') {
      statusText = 'PAUSED';
      barColor = 'var(--warn)';
      if ($('copy-toast-pause')) $('copy-toast-pause').textContent = '▶';
    } else if (copyState.status === 'awaiting_confirmation') {
      statusText = 'WAITING CONFIRMATION';
      barColor = 'var(--warn)';
    } else if (copyState.status === 'success') {
      statusText = 'SUCCESS!';
      barColor = 'var(--ok)';
      if ($('copy-toast-bar')) $('copy-toast-bar').style.width = '100%';
      if ($('copy-toast-pct')) $('copy-toast-pct').textContent = '100%';
    } else if (copyState.status === 'error') {
      statusText = 'FAILED!';
      barColor = 'var(--crit)';
    }

    if ($('copy-toast-status')) $('copy-toast-status').textContent = statusText;
    if ($('copy-toast-bar')) $('copy-toast-bar').style.background = barColor;

    if (copyState.status === 'copying' && total > 0 && prog.start > 0) {
      const elapsed = (Date.now() / 1000) - prog.start;
      if (elapsed > 2 && copied > 0) {
        const rate = copied / elapsed;
        const remaining = Math.max(0, total - copied) / rate;
        const mins = Math.floor(remaining / 60);
        const secs = Math.floor(remaining % 60);
        const mbps = (rate / 1024 / 1024).toFixed(1);
        let filesLeftStr = '';
        if (prog.files_total) {
          const left = Math.max(0, prog.files_total - (prog.files_done || 0));
          filesLeftStr = `${left} file${left === 1 ? '' : 's'} left • `;
        }
        if ($('copy-toast-time')) $('copy-toast-time').textContent = `${filesLeftStr}${mbps} MB/s • ~${mins}m ${secs}s`;
      } else {
        if ($('copy-toast-time')) $('copy-toast-time').textContent = 'Estimating time...';
      }
    } else {
      if ($('copy-toast-time')) $('copy-toast-time').textContent = '';
    }

    if (copyState.status === 'awaiting_confirmation') {
      let actionsDiv = $('copy-toast-actions');
      if (!actionsDiv) {
        actionsDiv = document.createElement('div');
        actionsDiv.id = 'copy-toast-actions';
        actionsDiv.style.cssText = 'display:flex; gap:8px; margin-top:10px;';
        actionsDiv.innerHTML = `
          <button class="btn-save-preset" style="flex:1; padding:6px; font-size:11px;" id="copy-btn-skip">Skip</button>
          <button class="btn-save-preset" style="flex:1; padding:6px; font-size:11px;" id="copy-btn-overwrite">Overwrite</button>
          <button class="btn-save-preset" style="flex:1; padding:6px; font-size:11px; border-color:rgba(240,85,59,0.5); color:var(--crit);" id="copy-btn-cancel">Cancel</button>
        `;
        toast.querySelector('.smart-modal-body')?.appendChild(actionsDiv);

        $('copy-btn-skip')?.addEventListener('click', () => confirmCopy('skip'));
        $('copy-btn-overwrite')?.addEventListener('click', () => confirmCopy('overwrite'));
        $('copy-btn-cancel')?.addEventListener('click', () => confirmCopy('cancel'));
      }
      actionsDiv.style.display = 'flex';
      actionsDiv.style.opacity = '1';
      actionsDiv.style.pointerEvents = 'auto';
    } else {
      const actionsDiv = $('copy-toast-actions');
      if (actionsDiv) actionsDiv.style.display = 'none';
    }
  } else {
    toast.style.opacity = '0';
    toast.style.pointerEvents = 'none';
    toast.style.transform = 'translateY(20px)';
    if (backdrop) {
      backdrop.style.opacity = '0';
      backdrop.style.pointerEvents = 'none';
    }
    copyToastMinimized = false;
  }
}

let _prevClientMediaSlots = { sd: null, tf: null };

export function updateMediaSlots(mediaSlots) {
  if (!mediaSlots) return;
  const srcSelect = $('btn-copy-src');
  const sd = mediaSlots.sd || {};
  const tf = mediaSlots.tf || {};
  const sdSize = sd.size || 0;
  const tfSize = tf.size || 0;

  // Clear ejected state if the card was physically removed (size dropped to 0)
  if (sdSize === 0) {
    _ejectedSlots.delete('sd');
  } else if (sd.ejected) {
    _ejectedSlots.add('sd');
  }

  if (tfSize === 0) {
    _ejectedSlots.delete('tf');
  } else if (tf.ejected) {
    _ejectedSlots.add('tf');
  }

  const sdEjected = _ejectedSlots.has('sd');
  const tfEjected = _ejectedSlots.has('tf');

  // Surface toast on card insertion (0 -> >0 transition) ONLY if not in ejected state
  if (_prevClientMediaSlots.sd !== null && _prevClientMediaSlots.sd === 0 && sdSize > 0 && !sdEjected) {
    showToast(`📷 SD Card Detected (${(sdSize / 1e9).toFixed(1)} GB): Ready for import`, 'info');
  }
  if (_prevClientMediaSlots.tf !== null && _prevClientMediaSlots.tf === 0 && tfSize > 0 && !tfEjected) {
    showToast(`📷 TF (MicroSD) Detected (${(tfSize / 1e9).toFixed(1)} GB): Ready for import`, 'info');
  }
  _prevClientMediaSlots.sd = sdSize;
  _prevClientMediaSlots.tf = tfSize;

  let sdText = 'SD 4.0 Slot';
  if (sdSize > 0) {
    sdText += ` [${(sdSize / 1e9).toFixed(1)} GB${sdEjected ? ' - Ejected' : ''}]`;
  } else {
    sdText += ' [Empty]';
  }

  let tfText = 'TF 4.0 Slot (MicroSD)';
  if (tfSize > 0) {
    tfText += ` [${(tfSize / 1e9).toFixed(1)} GB${tfEjected ? ' - Ejected' : ''}]`;
  } else {
    tfText += ' [Empty]';
  }

  if (srcSelect) {
    for (let i = 0; i < srcSelect.options.length; i++) {
      const opt = srcSelect.options[i];
      if (opt.value === 'sd' && opt.text !== sdText) opt.text = sdText;
      if (opt.value === 'tf' && opt.text !== tfText) opt.text = tfText;
    }
  }

  const slotBadge = $('media-slot-info-badge');
  if (slotBadge) {
    if (sdSize > 0) {
      slotBadge.textContent = `SD: ${(sdSize / 1e9).toFixed(1)} GB${sdEjected ? ' (EJECTED)' : ''}`;
      if (sdEjected) {
        slotBadge.style.background = 'rgba(234, 179, 8, 0.15)';
        slotBadge.style.color = '#eab308';
        slotBadge.style.borderColor = 'rgba(234, 179, 8, 0.35)';
      } else {
        slotBadge.style.background = 'rgba(37,194,160,0.15)';
        slotBadge.style.color = 'var(--ok2)';
        slotBadge.style.borderColor = 'rgba(37,194,160,0.35)';
      }
    } else if (tfSize > 0) {
      slotBadge.textContent = `TF: ${(tfSize / 1e9).toFixed(1)} GB${tfEjected ? ' (EJECTED)' : ''}`;
      if (tfEjected) {
        slotBadge.style.background = 'rgba(234, 179, 8, 0.15)';
        slotBadge.style.color = '#eab308';
        slotBadge.style.borderColor = 'rgba(234, 179, 8, 0.35)';
      } else {
        slotBadge.style.background = 'rgba(37,194,160,0.15)';
        slotBadge.style.color = 'var(--ok2)';
        slotBadge.style.borderColor = 'rgba(37,194,160,0.35)';
      }
    } else {
      slotBadge.textContent = 'SLOTS EMPTY';
      slotBadge.style.background = 'rgba(255,255,255,0.05)';
      slotBadge.style.color = 'var(--muted)';
      slotBadge.style.borderColor = 'rgba(255,255,255,0.1)';
    }
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

window.addEventListener('zettnas:lang-changed', () => {
  applyTheme(state.currentTheme);
  if (state.latestStats && state.latestStats.disks) {
    renderDisks(state.latestStats.disks);
  }
});

// Sync ejected and scan events from other components
ZettEventBus.on('media:slot_ejected', (slot) => {
  setSlotEjected(slot);
});

ZettEventBus.on('media:slots_rescanned', () => {
  clearSlotEjected();
});

