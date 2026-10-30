/**
 * Drive Health: every drive with one verdict, the reason in words and what to do, its
 * self-tests and, for whoever wants them, all the readings. It replaces the S.M.A.R.T. window:
 * everything that opened that one (the dashboard, the drive bays, the storage list, Spotlight)
 * opens this. A sleeping drive is shown from its last reading and is only woken when someone
 * presses "Read now". The rules live in backend/services/drive_health.py.
 *
 * Also: the fleet at a glance, each drive's make-up, age and wear outlook, 30 days of
 * temperature and error counters from the stored readings (no drive is woken for them), the
 * self-test schedule, and a report to save (Drive Health revamp).
 *
 * Reports are saved into a NAS folder from ZettNAS's own dialog, and each drive can carry when it
 * was bought, its warranty and a note (drive-health-report.js).
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { formatBytes, formatDateTime } from '../format.js';
import { lineChart } from './drive-charts.js';
import { t } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { bringToFront, makeDraggable } from './dock.js';
import { showToast } from '../toast.js';
import { announceChange } from '../a11y.js';
import { findingText, labelText, summaryText, reportCsv, openReportDialog, notesRows, notesForm, underWarranty } from './drive-health-report.js';

export { labelText, summaryText, reportCsv };

const DOCK_ID = 'drive-health';
const LIST_POLL_MS = 60000;
const TEST_POLL_MS = 5000;

let _win = null;
let _drives = [];
let _selected = null;
let _listTimer = null;
let _testTimer = null;
let _notes = {}; // serial -> {bought, warranty_until, note}
let _current = null; // the chosen drive as last read: {drive, detail, tests, history, identity, life}

const VERDICT_CLASS = { ok: 'is-ok', watch: 'is-watch', soon: 'is-soon', now: 'is-now', unknown: 'is-unknown' };
const verdictClass = (v) => VERDICT_CLASS[v] || 'is-unknown';


function when(ts) {
  return ts ? formatDateTime(ts * 1000, undefined, '') : '';
}

export function driveCardHtml(d, selected) {
  const name = d.model || d.dev;
  const bits = [d.dev, d.role, d.temp != null ? `${Math.round(d.temp)} °C` : ''].filter(Boolean).join(' · ');
  const asleep = d.asleep ? `<span class="dh-asleep">${escapeHtml(t('dh.asleep', 'Asleep'))}</span>` : '';
  const testing = d.active_test ? `<span class="dh-asleep">${escapeHtml(t('dh.testing', 'Testing'))}</span>` : '';
  return `<li><button type="button" class="dh-card ${verdictClass(d.verdict)}${selected ? ' is-selected' : ''}" data-dh-dev="${escapeHtml(d.dev)}"${selected ? ' aria-current="true"' : ''}>
    <span class="dh-dot" aria-hidden="true"></span>
    <span class="dh-card-main">
      <span class="dh-card-name">${escapeHtml(name)}</span>
      <span class="dh-card-meta">${escapeHtml(bits)}${asleep}${testing}</span>
      <span class="dh-card-summary">${escapeHtml(summaryText(d))}</span>
    </span>
    <span class="dh-pill">${escapeHtml(labelText(d))}</span>
  </button></li>`;
}

export function overallHtml(data) {
  const c = (data && data.counts) || {};
  const bad = (c.now || 0) + (c.soon || 0);
  const watch = c.watch || 0;
  const total = ((data && data.drives) || []).length;
  if (!total) return `<p class="dh-overall">${escapeHtml(t('dh.no_drives', 'No drives found.'))}</p>`;
  if (bad) {
    return `<p class="dh-overall is-soon">${escapeHtml(t('dh.overall_bad', '{n, plural, one {# drive needs action} other {# drives need action}}', { n: bad }))}</p>`;
  }
  if (watch) {
    return `<p class="dh-overall is-watch">${escapeHtml(t('dh.overall_watch', 'All drives work; {n, plural, one {# is worth watching} other {# are worth watching}}.', { n: watch }))}</p>`;
  }
  return `<p class="dh-overall is-ok">${escapeHtml(t('dh.overall_ok', 'All {n} drives are healthy.', { n: total }))}</p>`;
}

// What a finding's button does, by the kind of advice it gives
function findingButton(f) {
  if (['unreadable_sectors', 'reallocated_growing', 'reallocated_stable', 'reallocated_many', 'no_recent_test'].includes(f.code)) {
    return `<button type="button" class="btn-pill-toggle is-small" data-dh-test="long">${escapeHtml(t('dh.run_long', 'Run a long test'))}</button>`;
  }
  if (f.kind === 'cooling') {
    return `<button type="button" class="btn-pill-toggle is-small" data-dh-open="fans">${escapeHtml(t('dh.open_fans', 'Open fans'))}</button>`;
  }
  if (f.kind === 'cable') {
    return `<button type="button" class="btn-pill-toggle is-small" data-dh-open="bays">${escapeHtml(t('dh.open_bays', 'Show its bay'))}</button>`;
  }
  return '';
}

export function findingHtml(f) {
  return `<li class="dh-finding ${verdictClass(f.severity)}">
    <div class="dh-finding-title">${escapeHtml(findingText(f, 'title'))}</div>
    <div class="dh-finding-detail">${escapeHtml(findingText(f, 'detail'))}</div>
    <div class="dh-finding-action"><strong>${escapeHtml(t('dh.what_to_do', 'What to do:'))}</strong> ${escapeHtml(findingText(f, 'action'))} ${findingButton(f)}</div>
  </li>`;
}

function testRowsHtml(history) {
  if (!history || !history.length) return `<li class="dh-empty">${escapeHtml(t('dh.no_tests', 'No self-test has been run from ZettNAS yet.'))}</li>`;
  return history
    .slice(0, 6)
    .map((h) => {
      // the stored pass flag; smartctl's normal pass text is "Completed without error"
      const status = String(h.status || '');
      const ok = h.passed != null ? Boolean(h.passed) : /pass|without error/i.test(status) || (/complet/i.test(status) && !/fail|error/i.test(status));
      const kind = /long|extended/i.test(String(h.test_type || '')) ? t('dh.test_long', 'Long test') : t('dh.test_short', 'Short test');
      return `<li class="dh-test ${ok ? 'is-ok' : 'is-now'}"><span>${escapeHtml(kind)}</span><span>${escapeHtml(ok ? t('dh.test_passed', 'Passed') : status || t('dh.test_failed', 'Failed'))}</span><span class="dh-when">${escapeHtml(when(h.ts))}</span></li>`;
    })
    .join('');
}

function readingsHtml(detail) {
  const m = (detail && detail.metrics) || {};
  const rows = [
    [t('dh.r_model', 'Model'), detail?.model],
    [t('dh.r_serial', 'Serial number'), detail?.serial],
    [t('dh.r_hours', 'Hours powered on'), detail?.power_on_hours],
    [t('dh.r_temp', 'Temperature'), detail?.temp != null ? `${detail.temp} °C` : null],
    [t('dh.r_realloc', 'Replaced sectors'), m.realloc],
    [t('dh.r_pending', 'Sectors waiting to be replaced'), m.pending],
    [t('dh.r_offline', 'Unreadable sectors'), m.offline],
    [t('dh.r_crc', 'Cable transfer errors'), m.crc],
    [t('dh.r_wear', 'Rated writes used'), m.nvme_used != null ? `${m.nvme_used}%` : null],
    [t('dh.r_spare', 'Spare blocks left'), m.nvme_spare != null ? `${m.nvme_spare}%` : null],
    [t('dh.r_media', 'Media errors'), m.nvme_media_err || null],
    [t('dh.r_written', 'Data written'), m.tbw_tb != null ? `${m.tbw_tb} TB` : null],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');
  const table = rows.map(([k, v]) => `<tr><th scope="row">${escapeHtml(k)}</th><td>${escapeHtml(String(v))}</td></tr>`).join('');
  return `<table class="dh-readings">${table}</table>${detail?.raw ? `<pre class="dh-raw" data-no-icons>${escapeHtml(detail.raw)}</pre>` : ''}`;
}

export function detailHtml(drive, detail, tests) {
  if (!drive) return `<p class="dh-empty">${escapeHtml(t('dh.pick', 'Choose a drive.'))}</p>`;
  const health = (detail && detail.drive_health) || drive;
  const findings = (health.findings || []).filter((f) => f.severity !== 'ok' || f.kind === 'test');
  const info = (health.findings || []).filter((f) => f.severity === 'ok' && f.kind !== 'test');
  const asleep = detail ? detail.is_standby : drive.asleep;
  const sleepNote = asleep
    ? `<div class="dh-note">${escapeHtml(
        health.reading_ts
          ? t('dh.asleep_note', 'This drive is asleep. What you see is from its last reading ({when}); it was not woken.', { when: when(health.reading_ts) })
          : t('dh.asleep_never', 'This drive is asleep and has not been read yet; it was not woken.'),
      )} <button type="button" class="btn-pill-toggle is-small" data-dh-wake>${escapeHtml(t('dh.read_now', 'Read now (wakes it)'))}</button></div>`
    : '';
  const active = (tests && tests.active_test) || drive.active_test;
  const progress = active
    ? `<div class="dh-progress" role="status">${escapeHtml(/long|extended/i.test(String(active.test_type || active.type || '')) ? t('dh.running_long', 'A long test is running') : t('dh.running_short', 'A short test is running'))}${
        active.percent_remaining != null ? ` · ${escapeHtml(t('dh.left', '{p}% left', { p: active.percent_remaining }))}` : ''
      }</div>`
    : '';
  const serial = (detail && detail.serial) || drive.serial || '';
  const notes = _notes[serial] || null;
  const claim =
    ['soon', 'now'].includes(health.verdict) && underWarranty(notes)
      ? `<div class="dh-note">${escapeHtml(t('dh.claim', 'It is still under warranty until {date}: the maker may replace it. Save a full report for the claim.', { date: notes.warranty_until }))} <button type="button" class="btn-pill-toggle is-small" data-dh-report="drive">${escapeHtml(t('dh.export', 'Save a report'))}</button></div>`
      : '';
  return `
    <div class="dh-head">
      <div>
        <h3 class="dh-title">${escapeHtml(drive.model || drive.dev)}</h3>
        <div class="dh-sub">${escapeHtml([drive.dev, drive.role, drive.serial].filter(Boolean).join(' · '))}</div>
      </div>
      <span class="dh-pill ${verdictClass(health.verdict)}">${escapeHtml(labelText(health))}</span>
    </div>
    ${sleepNote}${claim}
    <section class="dh-section">
      <h4>${escapeHtml(t('dh.verdict', 'What we found'))}</h4>
      ${
        findings.length
          ? `<ul class="dh-findings">${findings.map(findingHtml).join('')}</ul>`
          : `<p class="dh-allgood">${escapeHtml(t('dh.all_good', 'No sign of trouble. Nothing to do.'))}</p>`
      }
      ${info.length ? `<ul class="dh-findings is-info">${info.map(findingHtml).join('')}</ul>` : ''}
    </section>
    <section class="dh-section">
      <h4>${escapeHtml(t('dh.self_tests', 'Self-tests'))}</h4>
      <p class="dh-hint">${escapeHtml(t('dh.tests_hint', 'A short test takes about two minutes; a long one reads the whole drive and can take hours. The drive stays usable meanwhile.'))}</p>
      ${progress}
      <div class="dh-test-buttons">
        <button type="button" class="btn-pill-toggle" data-dh-test="short"${active ? ' disabled' : ''}>${escapeHtml(t('dh.run_short', 'Run a short test'))}</button>
        <button type="button" class="btn-pill-toggle" data-dh-test="long"${active ? ' disabled' : ''}>${escapeHtml(t('dh.run_long', 'Run a long test'))}</button>
      </div>
      <ul class="dh-tests">${testRowsHtml(tests && tests.history)}</ul>
    </section>
    <div class="dh-schedule" id="dh-schedule"></div>
    <section class="dh-section" id="dh-about">${aboutSectionHtml((health && health.identity) || {}, null, serial)}</section>
    <details class="dh-section dh-more" id="dh-history">
      <summary>${escapeHtml(t('dh.history', 'History (30 days)'))}</summary>
      <div class="dh-history-body"><p class="dh-hint">${escapeHtml(t('dh.loading', 'Loading…'))}</p></div>
    </details>
    <details class="dh-section dh-more">
      <summary>${escapeHtml(t('dh.all_readings', 'All readings'))}</summary>
      ${detail ? readingsHtml(detail) : `<p class="dh-hint">${escapeHtml(t('dh.loading', 'Loading…'))}</p>`}
    </details>`;
}

function renderList() {
  if (!_win) return;
  const list = _win.querySelector('#dh-list');
  const overall = _win.querySelector('#dh-overall');
  if (overall) {
    overall.innerHTML = overallHtml({ drives: _drives, counts: _counts() });
    announceChange('drive-health', overall.textContent.trim()); // UX-28: only when it changes
  }
  if (list) list.innerHTML = _drives.map((d) => driveCardHtml(d, d.dev === _selected)).join('');
  const fleet = _win.querySelector('#dh-fleet');
  if (fleet) fleet.innerHTML = fleetHtml(_drives);
}

function _counts() {
  const c = {};
  for (const d of _drives) c[d.verdict] = (c[d.verdict] || 0) + 1;
  return c;
}

export async function loadDrives(refresh = false) {
  try {
    const [data, notes] = await Promise.all([
      api.get(`/api/drives/health${refresh ? '?refresh=1' : ''}`),
      api.get('/api/drives/notes').catch(() => null),
    ]);
    if (notes && notes.notes) _notes = notes.notes;
    _drives = (data && data.drives) || [];
    if (!_selected || !_drives.some((d) => d.dev === _selected)) _selected = _drives[0]?.dev || null;
    renderList();
    // Shown at once from the last readings; the fresh read already running updates the list.
    if (data && data.stale && !refresh) loadDrives(true);
    return data;
  } catch (e) {
    const list = _win?.querySelector('#dh-list');
    if (list) list.innerHTML = emptyHtml(t('dh.load_failed', 'Could not read the drives.'), 'li');
    return null;
  }
}

async function loadDetail(dev, wake = false) {
  const pane = _win?.querySelector('#dh-detail');
  const drive = _drives.find((d) => d.dev === dev);
  if (!pane) return;
  pane.innerHTML = detailHtml(drive, null, null);
  try {
    const [detail, tests] = await Promise.all([
      api.get(`/api/disk_detail?dev=${encodeURIComponent(dev)}${wake ? '&wake=true' : ''}`),
      api.get(`/api/disk/smart_tests?dev=${encodeURIComponent(dev)}&limit=10`).catch(() => null),
    ]);
    if (_selected !== dev) return; // another drive was chosen meanwhile
    _current = { drive: drive || { dev }, detail, tests, history: null, life: null, identity: {}, serial: (detail && detail.serial) || drive?.serial || '' };
    pane.innerHTML = detailHtml(drive || { dev }, detail, tests);
    loadExtras(dev, (detail && detail.drive_health && detail.drive_health.identity) || {});
    clearInterval(_testTimer);
    if (tests && tests.active_test) _testTimer = setInterval(() => refreshTests(dev), TEST_POLL_MS);
  } catch (e) {
    // Waking a sleeping drive is confirmed first; "Cancel" leaves it asleep and shows its last reading.
    if (wake && e?.error === 'cancelled') return loadDetail(dev);
    pane.innerHTML = detailHtml(drive, null, null) + emptyHtml(t('dh.detail_failed', 'Could not read this drive.'));
  }
}

async function refreshTests(dev) {
  try {
    const tests = await api.get(`/api/disk/smart_tests?dev=${encodeURIComponent(dev)}&limit=10`);
    if (!tests || !tests.active_test) {
      clearInterval(_testTimer);
      await loadDrives(true);
      if (_selected === dev) loadDetail(dev);
    }
  } catch (e) {
    clearInterval(_testTimer);
  }
}

export function selectDrive(dev) {
  _selected = dev;
  renderList();
  return loadDetail(dev);
}

async function runTest(kind) {
  const dev = _selected;
  if (!dev) return;
  try {
    await api.post('/api/disk/smart_test', { dev, test_type: kind });
    showToast(
      kind === 'long'
        ? t('dh.long_started', 'Long test started on {dev}. You can close this window; it keeps running.', { dev })
        : t('dh.short_started', 'Short test started on {dev}.', { dev }),
      'success',
    );
    loadDetail(dev);
  } catch (e) {
    if (e?.error === 'cancelled') return; // the person chose not to wake the sleeping drive
    showToast(t('dh.test_failed_start', 'Could not start the test: {error}', { error: e?.message || '' }), 'error');
  }
}

const emptyHtml = (text, tag = 'p') => `<${tag} class="dh-empty">${escapeHtml(text)}</${tag}>`;

function windowHtml() {
  return `
    <div class="os-window-header">
      <div class="os-window-title" id="drive-health-title">${escapeHtml(t('dh.title', 'Drive Health'))}</div>
      <div class="os-window-controls">
        <button class="win-btn refresh-btn" id="drive-health-export" title="${escapeHtml(t('dh.export', 'Save a report'))}" aria-label="${escapeHtml(t('dh.export', 'Save a report'))}">⤓</button>
        <button class="win-btn refresh-btn" id="drive-health-refresh" title="${escapeHtml(t('dh.refresh', 'Check again'))}" aria-label="${escapeHtml(t('dh.refresh', 'Check again'))}">↻</button>
        <button class="win-btn min-btn" id="drive-health-min" title="${escapeHtml(t('window.minimize', 'Minimize'))}" aria-label="${escapeHtml(t('window.minimize', 'Minimize'))}"></button>
        <button class="win-btn close-btn" id="drive-health-close" title="${escapeHtml(t('window.close', 'Close'))}" aria-label="${escapeHtml(t('window.close', 'Close'))}"></button>
      </div>
    </div>
    <div class="dh-body">
      <aside class="dh-side">
        <div id="dh-overall"></div>
        <div id="dh-fleet" class="dh-fleet"></div>
        <ul id="dh-list" class="dh-list" aria-label="${escapeHtml(t('dh.drives', 'Drives'))}"></ul>
      </aside>
      <section id="dh-detail" class="dh-detail" aria-live="polite"></section>
    </div>`;
}

function ensureWindow() {
  if (_win) return _win;
  const el = document.createElement('div');
  el.id = 'drive-health-window';
  el.className = 'os-window drive-health-window';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-labelledby', 'drive-health-title');
  el.hidden = true;
  el.innerHTML = windowHtml();
  document.body.appendChild(el);
  _win = el;
  const on = (sel, fn) =>
    el.querySelector(sel)?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      fn();
    });
  on('#drive-health-close', closeDriveHealth);
  on('#drive-health-min', () => window.DockManager?.minimize?.(DOCK_ID));
  on('#drive-health-export', () => openReport('all'));
  on('#drive-health-refresh', async () => {
    await loadDrives(true);
    if (_selected) loadDetail(_selected);
  });
  el.addEventListener('click', (e) => {
    const target = /** @type {HTMLElement} */ (e.target);
    const win = /** @type {any} */ (window);
    const card = /** @type {HTMLElement | null} */ (target.closest('[data-dh-dev]'));
    if (card) return void selectDrive(card.dataset.dhDev);
    const test = /** @type {HTMLElement | null} */ (target.closest('[data-dh-test]'));
    if (test) return void runTest(test.dataset.dhTest);
    if (target.closest('[data-dh-wake]')) return void loadDetail(_selected, true);
    if (target.closest('[data-dh-report]')) return void openReport('drive');
    if (target.closest('[data-dh-notes]')) return void editNotes();
    const open = /** @type {HTMLElement | null} */ (target.closest('[data-dh-open]'));
    if (open?.dataset.dhOpen === 'fans') win.openDrawer?.('tab-fans');
    if (open?.dataset.dhOpen === 'bays') win.openManagementSection?.('mgmt-sec-storage');
  });
  try {
    makeDraggable(el, el.querySelector('.os-window-header'));
  } catch (e) {
    /* the window manager is not there in tests */
  }
  return el;
}

/** Opens Drive Health, on `dev` when given (otherwise the drive that needs attention most). */
export async function openDriveHealth(dev = null) {
  const win = ensureWindow();
  win.hidden = false;
  win.classList.remove('window-minimized');
  win.style.display = 'flex';
  try {
    window.DockManager?.register?.(DOCK_ID, win, '#i-disk', t('dh.title', 'Drive Health'));
    if (window.DockManager?.windows?.[DOCK_ID]) window.DockManager.windows[DOCK_ID].onClose = closeDriveHealth;
    bringToFront(win);
  } catch (e) {
    /* tests */
  }
  if (dev) _selected = String(dev).replace(/^\/dev\//, '');
  await loadDrives();
  if (_selected) await loadDetail(_selected);
  clearInterval(_listTimer);
  _listTimer = setInterval(() => {
    if (_win && !_win.hidden && _win.style.display !== 'none') loadDrives();
  }, LIST_POLL_MS);
}

export function closeDriveHealth() {
  if (_win) {
    _win.hidden = true;
    _win.style.setProperty('display', 'none', 'important');
  }
  clearInterval(_listTimer);
  clearInterval(_testTimer);
  try {
    window.DockManager?.unregister?.(DOCK_ID);
  } catch (e) {
    /* optional */
  }
}

export function initDriveHealth() {
  if (typeof window === 'undefined') return;
  // everything that opened the old S.M.A.R.T. window (the event, with a drive or null) opens this
  ZettEventBus.addEventListener('modal:smart:open', (e) => {
    const d = e.detail;
    openDriveHealth(d && typeof d === 'object' ? d.dev : d);
  });
}

// --- the fleet, a drive's make-up and outlook, its history, the schedule, the report ---

const years = (hours) => (hours ? Math.round((hours / 8766) * 10) / 10 : null);

/** One line about all drives: space, the hottest one now, the oldest one, how many sleep. */
export function fleetHtml(drives) {
  if (!drives || !drives.length) return '';
  const bits = [];
  const space = drives.reduce((a, d) => a + (Number(d.capacity_bytes) || 0), 0);
  if (space) bits.push(t('dh.fleet_space', '{size} in all', { size: formatBytes(space) }));
  const warm = drives.filter((d) => d.temp != null).sort((a, b) => b.temp - a.temp)[0];
  if (warm) bits.push(t('dh.fleet_hottest', 'warmest {name} at {temp} °C', { name: warm.dev, temp: Math.round(warm.temp) }));
  const old = drives.filter((d) => d.power_on_hours).sort((a, b) => b.power_on_hours - a.power_on_hours)[0];
  if (old) bits.push(t('dh.fleet_oldest', 'oldest {name}, {y, plural, one {# year} other {# years}} on', { name: old.dev, y: years(old.power_on_hours) }));
  const asleep = drives.filter((d) => d.asleep).length;
  if (asleep) bits.push(t('dh.fleet_asleep', '{n, plural, one {# asleep} other {# asleep}}', { n: asleep }));
  return bits.length ? `<p class="dh-fleet-line">${escapeHtml(bits.join(' · '))}</p>` : '';
}

/** What kind of drive it is, in words. */
export function kindText(id) {
  if (id.protocol === 'nvme') return t('dh.kind_nvme', 'NVMe SSD');
  if (id.rotation_rpm === 0) return t('dh.kind_ssd', 'SATA SSD');
  if (id.rotation_rpm > 0) return t('dh.kind_hdd', 'Hard drive, {rpm} rpm', { rpm: id.rotation_rpm });
  return '';
}

/** "About this drive": make-up from the live reading, age and wear from the stored history. */
export function aboutHtml(id, life, notes = null) {
  const rows = [
    [t('dh.a_kind', 'Type'), kindText(id || {})],
    [t('dh.a_size', 'Size'), id && id.capacity_bytes ? formatBytes(id.capacity_bytes) : ''],
    [t('dh.a_link', 'Connection'), id && id.link],
    [t('dh.a_form', 'Form factor'), id && id.form_factor],
    [t('dh.a_firmware', 'Firmware'), id && id.firmware],
    [t('dh.a_cycles', 'Times switched on'), id && id.power_cycles != null ? String(id.power_cycles) : ''],
    [t('dh.a_written', 'Written over its life'), id && id.written_bytes ? formatBytes(id.written_bytes) : ''],
    [t('dh.a_age', 'Powered on'), life && life.age_years != null ? t('dh.a_years', '{y, plural, one {# year} other {# years}}', { y: life.age_years }) : ''],
  ].filter(([, v]) => v);
  rows.push(...notesRows(notes));
  const lines = [];
  if (life && life.wear_pct != null) {
    lines.push(
      life.years_left != null
        ? t('dh.wear_rate', '{p}% of its rated writes used; at the pace of the last weeks, about {y, plural, one {# year} other {# years}} left.', { p: life.wear_pct, y: life.years_left })
        : t('dh.wear_flat', '{p}% of its rated writes used; too little change yet to say how long it lasts.', { p: life.wear_pct }),
    );
  }
  if (life && life.age_years >= 5 && id && id.rotation_rpm > 0) {
    lines.push(t('dh.old_hdd', 'Older than the five years most hard drives are built for. It may run for years, but keep its backup current.'));
  }
  if (!rows.length && !lines.length) return `<p class="dh-hint">${escapeHtml(t('dh.about_later', 'Shown after the drive has been read while awake.'))}</p>`;
  const table = rows.map(([k, v]) => `<tr><th scope="row">${escapeHtml(k)}</th><td>${escapeHtml(String(v))}</td></tr>`).join('');
  return `<table class="dh-readings">${table}</table>${lines.map((n) => `<p class="dh-life">${escapeHtml(n)}</p>`).join('')}`;
}

const COUNTER_NAMES = {
  reallocated_sectors: () => t('dh.r_realloc', 'Replaced sectors'),
  pending_sectors: () => t('dh.r_pending', 'Sectors waiting to be replaced'),
  offline_uncorrectable: () => t('dh.r_offline', 'Unreadable sectors'),
  crc_errors: () => t('dh.r_crc', 'Cable transfer errors'),
  command_timeouts: () => t('dh.r_timeouts', 'Command timeouts'),
  spin_retries: () => t('dh.r_spin', 'Spin-up retries'),
  nvme_media_errors: () => t('dh.r_media', 'Media errors'),
};

/** The History body: temperature line and one line per error counter that ever moved. */
export function historyBody(h) {
  const box = document.createElement('div');
  if (!h || !h.samples) {
    const p = document.createElement('p');
    p.className = 'dh-hint';
    p.textContent = t('dh.history_none', 'No readings stored yet; they build up over the next days.');
    box.append(p);
    return box;
  }
  const head = (text) => {
    const p = document.createElement('p');
    p.className = 'dh-chart-label';
    p.textContent = text;
    return p;
  };
  if (h.temp) {
    const label = t('dh.h_temp', 'Temperature: {min}–{max} °C, average {avg} °C', { min: Math.round(h.temp.min), max: Math.round(h.temp.max), avg: h.temp.avg });
    box.append(head(label), lineChart(h.temp.points, { label, className: 'is-temp' }));
  }
  const names = Object.keys(h.counters || {});
  for (const key of names) {
    const c = h.counters[key];
    const name = (COUNTER_NAMES[key] || (() => key))();
    const label = c.last > c.first
      ? t('dh.h_rose', '{name}: rose from {a} to {b}', { name, a: c.first, b: c.last })
      : t('dh.h_steady', '{name}: steady at {b}', { name, b: c.last });
    box.append(head(label), lineChart(c.points, { label, height: 48, className: c.last > c.first ? 'is-rising' : '' }));
  }
  if (!names.length) {
    const p = document.createElement('p');
    p.className = 'dh-allgood';
    p.textContent = t('dh.h_clean', 'No error counter has moved in this time.');
    box.append(p);
  }
  return box;
}

export function aboutSectionHtml(id, life, serial = '') {
  const notes = serial ? _notes[serial] || null : null;
  const edit = serial
    ? `<button type="button" class="btn-pill-toggle is-small dh-notes-edit" data-dh-notes>${escapeHtml(notes ? t('dh.n_edit', 'Edit purchase and warranty') : t('dh.n_add', 'Add purchase and warranty'))}</button>`
    : '';
  return `<h4>${escapeHtml(t('dh.about', 'About this drive'))}</h4>${aboutHtml(id, life, notes)}${edit}`;
}

/** The report dialog, with what is on screen now. */
function openReport(preset) {
  if (!_win) return;
  openReportDialog(_win, () => ({ drives: _drives, notes: _notes, current: _current && _current.drive?.dev === _selected ? { ..._current, counterName: (k) => (COUNTER_NAMES[k] || (() => k))() } : null }), preset);
}

/** The purchase and warranty form in place of "About this drive". */
function editNotes() {
  const about = _win?.querySelector('#dh-about');
  const serial = _current?.serial;
  if (!about || !serial) return;
  notesForm(about, serial, _notes[serial] || null, (saved) => {
    if (saved) _notes[serial] = saved;
    else delete _notes[serial];
    about.innerHTML = aboutSectionHtml(_current?.identity || {}, _current?.life || null, serial);
    if (_selected) loadDetail(_selected); // the warranty note under the verdict
  });
}

/** "Automatic tests: …" from /api/smart/schedule. */
export function scheduleText(cfg) {
  if (!cfg) return '';
  if (cfg.enabled === false) return t('dh.sched_off', 'Automatic self-tests are off.');
  const part = (kind) => {
    const every = cfg[`${kind}_test_interval`];
    if (!every || every === 'disabled') return null;
    const name = kind === 'long' ? t('dh.test_long', 'Long test') : t('dh.test_short', 'Short test');
    const freq = { daily: t('dh.every_day', 'every day'), weekly: t('dh.every_week', 'every week'), monthly: t('dh.every_month', 'every month') }[every] || every;
    return `${name} ${freq}, ${String(cfg[`${kind}_test_hour`] ?? 2).padStart(2, '0')}:00`;
  };
  const parts = [part('short'), part('long')].filter(Boolean);
  return parts.length ? t('dh.sched', 'Automatic tests: {list}. Sleeping drives are skipped.', { list: parts.join(' · ') }) : t('dh.sched_off', 'Automatic self-tests are off.');
}

let _schedule = null;

async function loadExtras(dev, id) {
  const pane = _win?.querySelector('#dh-detail');
  if (!pane) return;
  try {
    if (!_schedule) _schedule = await api.get('/api/smart/schedule').catch(() => ({}));
    const sched = pane.querySelector('#dh-schedule');
    if (sched) sched.textContent = scheduleText(_schedule);
    const data = await api.get(`/api/drives/history?dev=${encodeURIComponent(dev)}&days=30`);
    if (_selected !== dev) return;
    const about = pane.querySelector('#dh-about');
    if (_current && _current.drive?.dev === dev) Object.assign(_current, { history: data.history, life: data.life, identity: id });
    if (about) about.innerHTML = aboutSectionHtml(id, data.life, _current?.serial || '');
    const body = pane.querySelector('#dh-history .dh-history-body');
    if (body) body.replaceChildren(historyBody(data.history));
  } catch (e) {
    const body = pane.querySelector('#dh-history .dh-history-body');
    if (body) body.textContent = t('dh.history_failed', 'Could not load the history.');
  }
}

export const _test = {
  reset() {
    _win?.remove();
    _win = null;
    _drives = [];
    _selected = null;
    _schedule = null;
    _notes = {};
    _current = null;
    clearInterval(_listTimer);
    clearInterval(_testTimer);
  },
};
