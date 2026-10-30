/**
 * Drive Health: reports and the owner's details.
 *
 * A report is saved into a folder on the NAS from ZettNAS's own dialog (not the browser's
 * download): through the File Explorer's upload, so the person's folder rights and space limit
 * apply. Two kinds: every drive as a spreadsheet (.csv), or one drive in full as text, with its
 * findings, self-tests, history and the raw S.M.A.R.T. output a warranty claim asks for.
 *
 * The owner's details (when it was bought, until when the warranty runs, a note) are kept by
 * serial number on the server, so they follow the drive to another bay or device name.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { formatBytes, formatDateTime } from '../format.js';
import { showToast } from '../toast.js';

const LAST_DIR_PREF = 'zettnas_dh_report_dir';

// The server sends each text with a message key and its values; show it in the reader's language,
// with the server's English as the fallback
export const findingText = (f, part) => t(`dh.f.${f.key || f.code}.${part}`, f[part] || '', f.params || {});
export const labelText = (d) => (d.label_key ? t(`dh.label.${d.label_key}`, d.label || '') : d.label || '');
export const summaryText = (d) => (d.summary_key ? t(`dh.f.${d.summary_key}.title`, d.summary || '', d.summary_params || {}) : d.summary || '');

const today = () => new Date().toISOString().slice(0, 10);
const when = (ts) => (ts ? formatDateTime(ts * 1000, undefined, '') : '');

// --- the owner's details ---------------------------------------------------------------------

/** Months from `from` (a Date) to the date `until` ("YYYY-MM-DD"); negative once it has passed. */
export function monthsLeft(until, from = new Date()) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(until || ''));
  if (!m) return null;
  const end = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const months = (end.getFullYear() - from.getFullYear()) * 12 + (end.getMonth() - from.getMonth());
  return end.getDate() < from.getDate() ? months - 1 : months;
}

const endOf = (until) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(until || ''));
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 23, 59, 59) : null;
};

/** "Until 2027-05-01 (7 months left)", "Until 2026-11-15 (less than a month left)" or "Ended 2024-01-01". */
export function warrantyText(until, from = new Date()) {
  const end = endOf(until);
  if (!end) return '';
  if (end < from) return t('dh.warranty_ended', 'Ended {date}', { date: until });
  const left = monthsLeft(until, from);
  if (!left || left < 1) return t('dh.warranty_days', 'Until {date} (less than a month left)', { date: until });
  return t('dh.warranty_left', 'Until {date} ({n, plural, one {# month} other {# months}} left)', { date: until, n: left });
}

/** True while the warranty runs. */
export function underWarranty(notes, from = new Date()) {
  const end = endOf(notes && notes.warranty_until);
  return Boolean(end && end >= from);
}

/** Rows for "About this drive": bought, warranty, note (only those that are set). */
export function notesRows(notes) {
  if (!notes) return [];
  return [
    [t('dh.n_bought', 'Bought'), notes.bought || ''],
    [t('dh.n_warranty', 'Warranty'), notes.warranty_until ? warrantyText(notes.warranty_until) : ''],
    [t('dh.n_note', 'Note'), notes.note || ''],
  ].filter(([, v]) => v);
}

let _ids = 0;

/** A labelled control: `control` is the input itself, or a row holding it (then pass `input`). */
function field(text, control, input = control) {
  const box = document.createElement('div');
  box.className = 'dh-field';
  const label = document.createElement('label');
  input.id = input.id || `dh-field-${++_ids}`;
  label.htmlFor = input.id;
  label.textContent = text;
  box.append(label, control);
  return box;
}

function button(text, cls = 'btn-pill-toggle') {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = cls;
  b.textContent = text;
  return b;
}

/**
 * The form for a drive's details, built in place of `host`'s content. `onSaved(notes)` runs after
 * the server took them; Cancel puts the old content back.
 */
export function notesForm(host, serial, notes, onSaved) {
  const old = Array.from(host.childNodes);
  const form = document.createElement('form');
  form.className = 'dh-notes-form';
  const bought = Object.assign(document.createElement('input'), { type: 'date', value: (notes && notes.bought) || '', name: 'bought' });
  const until = Object.assign(document.createElement('input'), { type: 'date', value: (notes && notes.warranty_until) || '', name: 'warranty_until' });
  const note = Object.assign(document.createElement('textarea'), { value: (notes && notes.note) || '', name: 'note', rows: 2, maxLength: 300 });
  note.placeholder = t('dh.n_note_hint', 'Where it sits, where it was bought, the order number…');
  const years = document.createElement('div');
  years.className = 'dh-years';
  for (const y of [2, 3, 5]) {
    const b = button(t('dh.n_years', '{n, plural, one {# year} other {# years}}', { n: y }), 'btn-pill-toggle is-small');
    b.addEventListener('click', () => {
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(bought.value);
      if (!m) return void bought.focus();
      until.value = `${Number(m[1]) + y}-${m[2]}-${m[3]}`;
    });
    years.append(b);
  }
  const save = button(t('dh.n_save', 'Save'), 'btn-pill-toggle is-primary');
  save.type = 'submit';
  const cancel = button(t('dh.n_cancel', 'Cancel'));
  cancel.addEventListener('click', () => host.replaceChildren(...old));
  const row = document.createElement('div');
  row.className = 'dh-test-buttons';
  row.append(save, cancel);
  form.append(
    field(t('dh.n_bought', 'Bought'), bought),
    field(t('dh.n_warranty_until', 'Warranty until'), until),
    years,
    field(t('dh.n_note', 'Note'), note),
    row,
  );
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      const res = await api.put('/api/drives/notes', { serial, bought: bought.value, warranty_until: until.value, note: note.value });
      showToast(t('dh.n_saved', 'Saved.'), 'success');
      onSaved(res && res.notes ? res.notes : null);
    } catch (err) {
      save.disabled = false;
      showToast(t('dh.n_failed', 'Could not save the details: {error}', { error: err?.message || '' }), 'error');
    }
  });
  host.replaceChildren(form);
  bought.focus();
  return form;
}

// --- the reports -----------------------------------------------------------------------------

// A cell that starts like a formula is kept as text by spreadsheets (CSV injection)
const csvCell = (v) => {
  let s = String(v ?? '');
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return `"${s.replace(/"/g, '""')}"`;
};

/** A CSV report of every drive: for your records or a warranty claim. */
export function reportCsv(drives, notesBySerial = {}) {
  const head = ['device', 'model', 'serial', 'role', 'verdict', 'summary', 'temperature_c', 'power_on_hours', 'size_bytes', 'asleep', 'findings', 'bought', 'warranty_until', 'note'];
  const rows = (drives || []).map((d) => {
    const n = (d.serial && notesBySerial[d.serial]) || {};
    return [
      d.dev, d.model, d.serial, d.role, labelText(d), summaryText(d), d.temp ?? '', d.power_on_hours ?? '', d.capacity_bytes ?? '', d.asleep ? 'yes' : 'no',
      (d.findings || []).filter((f) => f.severity !== 'ok').map((f) => findingText(f, 'title')).join('; '),
      n.bought || '', n.warranty_until || '', n.note || '',
    ];
  });
  return [head, ...rows].map((r) => r.map(csvCell).join(',')).join('\n') + '\n';
}

const line = (k, v) => (v === null || v === undefined || v === '' ? null : `${k}: ${v}`);

/** One drive in full, as plain text: what a warranty claim or a support forum asks for. */
export function driveReportText({ drive, detail, tests, history, notes, now = new Date(), counterName = (k) => k }) {
  const d = drive || {};
  const health = (detail && detail.drive_health) || d;
  const id = health.identity || {};
  const out = [];
  const rule = '-'.repeat(60);
  out.push(t('dh.rep_title', 'Drive Health report: {name}', { name: d.model || d.dev || '' }), t('dh.rep_made', 'Made by ZettNAS on {date}', { date: formatDateTime(now.getTime(), undefined, '') }), '');
  out.push(
    ...[
      line(t('dh.r_model', 'Model'), d.model || detail?.model),
      line(t('dh.r_serial', 'Serial number'), d.serial || detail?.serial),
      line(t('dh.a_firmware', 'Firmware'), id.firmware),
      line(t('dh.a_size', 'Size'), id.capacity_bytes || d.capacity_bytes ? formatBytes(id.capacity_bytes || d.capacity_bytes) : ''),
      line(t('dh.rep_device', 'Device'), [d.dev, d.role].filter(Boolean).join(', ')),
      line(t('dh.r_hours', 'Hours powered on'), detail?.power_on_hours ?? d.power_on_hours),
      line(t('dh.r_temp', 'Temperature'), d.temp != null ? `${d.temp} °C` : ''),
      line(t('dh.n_bought', 'Bought'), notes?.bought),
      line(t('dh.n_warranty', 'Warranty'), notes?.warranty_until ? warrantyText(notes.warranty_until, now) : ''),
      line(t('dh.n_note', 'Note'), notes?.note),
    ].filter(Boolean),
  );
  out.push('', rule, `${t('dh.verdict', 'What we found')}: ${labelText(health)}`, rule);
  const findings = (health.findings || []).filter((f) => f.severity !== 'ok');
  if (!findings.length) out.push(t('dh.all_good', 'No sign of trouble. Nothing to do.'));
  for (const f of findings) {
    out.push(`* ${findingText(f, 'title')}`, `  ${findingText(f, 'detail')}`, `  ${t('dh.what_to_do', 'What to do:')} ${findingText(f, 'action')}`);
  }
  out.push('', rule, t('dh.self_tests', 'Self-tests'), rule);
  const runs = (tests && tests.history) || [];
  if (!runs.length) out.push(t('dh.no_tests', 'No self-test has been run from ZettNAS yet.'));
  for (const r of runs) out.push(`${when(r.ts)}  ${r.test_type || ''}  ${r.status || (r.passed ? 'passed' : 'failed')}`);
  if (history && history.samples) {
    out.push('', rule, t('dh.history', 'History (30 days)'), rule);
    if (history.temp) out.push(t('dh.h_temp', 'Temperature: {min}–{max} °C, average {avg} °C', { min: Math.round(history.temp.min), max: Math.round(history.temp.max), avg: history.temp.avg }));
    for (const [key, c] of Object.entries(history.counters || {})) out.push(`${counterName(key)}: ${c.first} → ${c.last}`);
  }
  if (detail && detail.raw) out.push('', rule, t('dh.rep_raw', 'Full S.M.A.R.T. output'), rule, String(detail.raw).trimEnd());
  return out.join('\n') + '\n';
}

/** A file name without characters folders don't take. */
export function safeName(name) {
  return String(name || '').replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '-').replace(/\s+/g, ' ').trim().slice(0, 120);
}

/** `name`, or "name (2).ext" and so on when the folder has it already. */
export function freeName(name, taken) {
  const have = new Set((taken || []).map((n) => String(n).toLowerCase()));
  if (!have.has(name.toLowerCase())) return name;
  const dot = name.lastIndexOf('.');
  const [base, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ''];
  for (let i = 2; i < 1000; i++) {
    const next = `${base} (${i})${ext}`;
    if (!have.has(next.toLowerCase())) return next;
  }
  return `${base} (${Date.now()})${ext}`;
}

function lastDir() {
  try {
    return localStorage.getItem(LAST_DIR_PREF) || localStorage.getItem('zettnas_fm_last_path') || '/mnt/user';
  } catch (e) {
    return '/mnt/user';
  }
}

function rememberDir(dir) {
  try {
    localStorage.setItem(LAST_DIR_PREF, dir);
  } catch (e) {
    /* private window: the next save starts from the default */
  }
}

/**
 * Writes `text` into `dir` as `name` (or a free variant of it) through the File Explorer's upload.
 * Returns the full path it was saved at.
 */
export async function saveTextToNas(dir, name, text, type = 'text/plain') {
  const folder = String(dir || '').replace(/\/+$/, '') || '/';
  const listing = await api.get(`/api/browse?path=${encodeURIComponent(folder)}`);
  const taken = ((listing && listing.dirs) || []).map((e) => e.name);
  const file = freeName(safeName(name), taken);
  const res = await api.postRaw(`/api/fs/upload?path=${encodeURIComponent(folder)}&filename=${encodeURIComponent(file)}`, new Blob([text], { type }));
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || String(res.status));
  }
  return `${folder === '/' ? '' : folder}/${file}`;
}

/**
 * ZettNAS's "Save a report" dialog, inside `host` (the Drive Health window). `ctx()` gives
 * { drives, notes, current: {drive, detail, tests, history} | null } at the moment of saving.
 */
export function openReportDialog(host, ctx, preset = 'all') {
  host.querySelector('.dh-dialog-wrap')?.remove();
  const state = ctx();
  const wrap = document.createElement('div');
  wrap.className = 'dh-dialog-wrap';
  const box = document.createElement('div');
  box.className = 'dh-dialog';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
  box.setAttribute('aria-labelledby', 'dh-dialog-title');
  const title = document.createElement('h3');
  title.id = 'dh-dialog-title';
  title.textContent = t('dh.export', 'Save a report');
  const current = state.current && state.current.drive;

  const choice = (value, text, hint, disabled) => {
    const label = document.createElement('label');
    label.className = 'dh-choice';
    const input = Object.assign(document.createElement('input'), { type: 'radio', name: 'dh-kind', value, disabled: Boolean(disabled) });
    const span = document.createElement('span');
    const strong = document.createElement('strong');
    strong.textContent = text;
    const small = document.createElement('small');
    small.textContent = hint;
    span.append(strong, small);
    label.append(input, span);
    return { label, input };
  };
  const all = choice('all', t('dh.rep_all', 'All drives, as a spreadsheet (.csv)'), t('dh.rep_all_hint', 'One row per drive: health, temperature, age, findings, warranty.'));
  const one = choice(
    'drive',
    current ? t('dh.rep_one', '{name} in full (.txt)', { name: current.model || current.dev }) : t('dh.rep_one_none', 'One drive in full (.txt)'),
    t('dh.rep_one_hint', 'Findings, self-tests, history and the full S.M.A.R.T. output: what a warranty claim asks for.'),
    !current,
  );
  (preset === 'drive' && current ? one : all).input.checked = true;

  const defaultName = (kind) => {
    if (kind === 'drive' && current) return safeName(`drive-${current.model || current.dev}-${current.serial || current.dev}-${today()}.txt`);
    return `drive-health-${today()}.csv`;
  };
  const dir = Object.assign(document.createElement('input'), { type: 'text', value: lastDir(), name: 'dir', spellcheck: false });
  const choose = button(t('dh.rep_choose', 'Choose…'), 'btn-pill-toggle is-small');
  choose.addEventListener('click', () => {
    const open = /** @type {any} */ (window).openFolderBrowser;
    if (typeof open === 'function') open(dir.value || '/mnt/user', (picked) => { dir.value = picked; });
  });
  const dirRow = document.createElement('div');
  dirRow.className = 'dh-dir-row';
  dirRow.append(dir, choose);
  const name = Object.assign(document.createElement('input'), { type: 'text', value: defaultName((preset === 'drive' && current) ? 'drive' : 'all'), name: 'name', spellcheck: false });
  for (const c of [all, one]) c.input.addEventListener('change', () => { name.value = defaultName(c.input.value); });

  const status = document.createElement('p');
  status.className = 'dh-hint';
  status.setAttribute('role', 'status');
  const save = button(t('dh.n_save', 'Save'), 'btn-pill-toggle is-primary');
  const cancel = button(t('dh.n_cancel', 'Cancel'));
  const actions = document.createElement('div');
  actions.className = 'dh-test-buttons';
  actions.append(save, cancel);

  const close = () => {
    wrap.remove();
    host.removeEventListener('keydown', onKey, true);
  };
  const onKey = (e) => {
    if (e.key === 'Escape' && host.contains(wrap)) {
      e.stopPropagation();
      close();
    }
  };
  host.addEventListener('keydown', onKey, true);
  cancel.addEventListener('click', close);
  wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });

  save.addEventListener('click', async () => {
    const kind = one.input.checked ? 'drive' : 'all';
    const now = ctx();
    const text = kind === 'drive' && now.current
      ? driveReportText({ ...now.current, notes: now.notes[now.current.drive?.serial] })
      : reportCsv(now.drives, now.notes);
    save.disabled = true;
    status.textContent = t('dh.rep_saving', 'Saving…');
    try {
      const path = await saveTextToNas(dir.value.trim(), name.value.trim() || defaultName(kind), text, kind === 'drive' ? 'text/plain' : 'text/csv');
      rememberDir(dir.value.trim());
      status.textContent = t('dh.rep_saved', 'Saved as {path}', { path });
      const show = button(t('dh.rep_show', 'Show in File Explorer'), 'btn-pill-toggle is-primary');
      show.addEventListener('click', () => {
        const fm = /** @type {any} */ (window).openFileManager;
        if (typeof fm === 'function') fm(path.slice(0, path.lastIndexOf('/')) || '/');
        close();
      });
      const done = button(t('dh.rep_close', 'Close'));
      done.addEventListener('click', close);
      actions.replaceChildren(show, done);
      show.focus();
    } catch (err) {
      save.disabled = false;
      // "Cancel" on waking a sleeping folder's disk: nothing was saved
      status.textContent = err?.error === 'cancelled'
        ? t('dh.rep_cancelled', 'Not saved: that folder\'s disk is asleep.')
        : t('dh.rep_failed', 'Could not save the report: {error}', { error: err?.message || '' });
    }
  });

  box.append(
    title,
    all.label,
    one.label,
    field(t('dh.rep_folder', 'Folder on the NAS'), dirRow, dir),
    field(t('dh.rep_name', 'File name'), name),
    status,
    actions,
  );
  wrap.append(box);
  host.append(wrap);
  save.focus();
  return wrap;
}
