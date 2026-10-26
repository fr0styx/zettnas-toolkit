import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));
vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
}));
vi.mock('../components/dock.js', () => ({
  bringToFront: vi.fn(),
  makeDraggable: vi.fn(),
}));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { ZettEventBus } = await import('../event-bus.js');
const dh = await import('../components/drive-health.js');
const { statusHtml } = await import('../components/management/overview.js');

const flush = () => new Promise((r) => setTimeout(r, 0));

const FINDING_NOW = {
  code: 'unreadable_sectors',
  severity: 'now',
  kind: 'replace',
  title: '8 sectors could not be read',
  detail: 'The drive tried to read them and failed.',
  action: 'Copy what matters off this drive, then replace it.',
};
const DRIVES = {
  drives: [
    { dev: 'sdc', model: 'Old Disk', role: 'data', verdict: 'now', label: 'Replace now', summary: '8 sectors could not be read', findings: [FINDING_NOW], asleep: false, temp: 41 },
    { dev: 'sdb', model: 'Sleepy Disk', role: 'parity', verdict: 'ok', label: 'Healthy', summary: 'No sign of trouble.', findings: [], asleep: true, reading_ts: 1700000000 },
  ],
  counts: { now: 1, ok: 1 },
};

function routeGet(overrides = {}) {
  api.get.mockImplementation(async (url) => {
    if (url.startsWith('/api/drives/health')) return overrides.drives || DRIVES;
    if (url.startsWith('/api/disk/smart_tests')) return overrides.tests || { active_test: null, history: [] };
    if (url.startsWith('/api/disk_detail')) return overrides.detail || { model: 'Old Disk', serial: 'X1', is_standby: false, metrics: { pending: 8 }, raw: 'smartctl output' };
    throw new Error(`unexpected ${url}`);
  });
}

describe('Drive Health', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
    dh._test.reset();
  });
  afterEach(() => dh._test.reset());

  it('sums up the drives, worst news first', () => {
    expect(dh.overallHtml({ drives: [], counts: {} })).toContain('No drives found');
    expect(dh.overallHtml(DRIVES)).toContain('1 drive needs action');
    expect(dh.overallHtml({ drives: DRIVES.drives, counts: { watch: 2 } })).toContain('2 are worth watching');
    expect(dh.overallHtml({ drives: DRIVES.drives, counts: { ok: 2 } })).toContain('All 2 drives are healthy');
  });

  it('shows each drive with its verdict and marks sleeping ones without waking them', () => {
    const card = dh.driveCardHtml(DRIVES.drives[1], false);
    expect(card).toContain('is-ok');
    expect(card).toContain('Asleep');
    expect(card).toContain('Healthy');
    expect(dh.driveCardHtml(DRIVES.drives[0], true)).toContain('aria-current="true"');
  });

  it('gives every finding a reason, what to do and a button that does it', () => {
    const html = dh.findingHtml(FINDING_NOW);
    expect(html).toContain('What to do:');
    expect(html).toContain('data-dh-test="long"');
    expect(dh.findingHtml({ ...FINDING_NOW, code: 'too_hot', kind: 'cooling' })).toContain('data-dh-open="fans"');
    expect(dh.findingHtml({ ...FINDING_NOW, code: 'cable_errors', kind: 'cable' })).toContain('data-dh-open="bays"');
    expect(dh.findingHtml({ ...FINDING_NOW, code: 'old_drive', kind: 'info' })).not.toContain('<button');
  });

  it('escapes text that comes from the drive', () => {
    const html = dh.driveCardHtml({ ...DRIVES.drives[0], model: '<img src=x onerror=alert(1)>' }, false);
    expect(html).not.toContain('<img');
  });

  it('opens on the worst drive, lists all of them and loads its details', async () => {
    routeGet();
    await dh.openDriveHealth();
    const win = document.getElementById('drive-health-window');
    expect(win.hidden).toBe(false);
    expect(win.querySelectorAll('[data-dh-dev]').length).toBe(2);
    expect(win.querySelector('#dh-overall').textContent).toContain('1 drive needs action');
    const detail = win.querySelector('#dh-detail');
    expect(detail.textContent).toContain('8 sectors could not be read');
    expect(detail.textContent).toContain('smartctl output');
    expect(api.get).toHaveBeenCalledWith('/api/disk_detail?dev=sdc');
  });

  it('shows a sleeping drive from its last reading and wakes it only on request', async () => {
    routeGet({ detail: { model: 'Sleepy Disk', is_standby: true, metrics: {} } });
    await dh.openDriveHealth('/dev/sdb');
    const win = document.getElementById('drive-health-window');
    expect(api.get).toHaveBeenCalledWith('/api/disk_detail?dev=sdb');
    expect(api.get.mock.calls.some(([u]) => u.includes('wake=true'))).toBe(false);
    expect(win.querySelector('.dh-note').textContent).toContain('it was not woken');
    win.querySelector('[data-dh-wake]').click();
    await flush();
    expect(api.get).toHaveBeenCalledWith('/api/disk_detail?dev=sdb&wake=true');
  });

  it('starts a long test from a finding and says it keeps running', async () => {
    routeGet();
    api.post.mockResolvedValue({ status: 'started' });
    await dh.openDriveHealth();
    document.querySelector('.dh-finding [data-dh-test="long"]').click();
    await flush();
    expect(api.post).toHaveBeenCalledWith('/api/disk/smart_test', { dev: 'sdc', test_type: 'long' });
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('keeps running'), 'success');
  });

  it('shows a running test with its progress and greys out the test buttons', async () => {
    routeGet({ tests: { active_test: { test_type: 'long', percent_remaining: 70 }, history: [
      { ts: 1700000000, status: 'Completed without error', test_type: 'short' },
      { ts: 1690000000, status: 'Completed: read failure', test_type: 'long', passed: 0 },
    ] } });
    await dh.openDriveHealth();
    const detail = document.getElementById('dh-detail');
    expect(detail.querySelector('.dh-progress').textContent).toContain('70% left');
    expect(detail.querySelector('.dh-test-buttons [data-dh-test="short"]').disabled).toBe(true);
    const rows = detail.querySelectorAll('.dh-tests .dh-test');
    expect(rows[0].className).toContain('is-ok');
    expect(rows[0].textContent).toContain('Passed');
    expect(rows[1].className).toContain('is-now');
    expect(rows[1].textContent).toContain('read failure');
  });

  it('says so when the drives cannot be read', async () => {
    api.get.mockRejectedValue(new Error('down'));
    await dh.openDriveHealth();
    expect(document.getElementById('dh-list').textContent).toContain('Could not read the drives');
  });

  it('opens from everything that opened the old S.M.A.R.T. window', async () => {
    routeGet();
    dh.initDriveHealth();
    ZettEventBus.emit('modal:smart:open', { dev: '/dev/sdc', forceWake: true });
    await flush();
    await flush();
    expect(api.get).toHaveBeenCalledWith('/api/disk_detail?dev=sdc');
  });

  it('closes and stops checking', async () => {
    routeGet();
    await dh.openDriveHealth();
    dh.closeDriveHealth();
    expect(document.getElementById('drive-health-window').hidden).toBe(true);
  });

  it('puts its verdicts on the Overview and the phone, opening Drive Health', () => {
    const html = statusHtml({ ok: false, items: [{ id: 'drive:sdc', level: 'warning', kind: 'drive_attention', subject: 'sdc', detail: 'The drive is too hot', open: 'drives' }] });
    expect(html).toContain('Drive sdc needs attention: The drive is too hot.');
    expect(html).toContain('data-ov-open="drives"');
  });

  it('has its own desktop icon that opens it', async () => {
    const { readFileSync } = await import('node:fs');
    const path = await import('node:path');
    const page = readFileSync(path.resolve(__dirname, '../../index.html'), 'utf8');
    const icon = page.match(/<div[^>]*id="dh-desktop-icon"[^>]*>/)?.[0] || '';
    expect(icon).toContain('data-action="open-drive-health"');
    expect(page).toContain('<use href="#i-disk"/>');
    const { installDomActions } = await import('../dom-actions.js');
    routeGet();
    dh.initDriveHealth();
    document.body.insertAdjacentHTML('beforeend', '<div id="dh-desktop-icon" data-action="open-drive-health"></div>');
    installDomActions();
    document.getElementById('dh-desktop-icon').click();
    await flush();
    await flush();
    expect(document.getElementById('drive-health-window')?.hidden).toBe(false);
  });

  it('takes a free spot on a desktop someone already arranged, moving none of their icons', async () => {
    const { initDraggableDesktopIcons } = await import('../components/dock/desktop-icons.js');
    const ids = ['management-desktop-icon', 'containers-desktop-icon', 'vm-desktop-icon', 'fm-desktop-icon', 'rb-desktop-icon', 'dh-desktop-icon', 'chassis-desktop-icon'];
    document.body.innerHTML = `<div id="desktop-icons-container">${ids.map((id) => `<div class="chassis-hero-box" id="${id}"><span class="icon-text">${id}</span></div>`).join('')}</div>`;
    const saved = {
      'management-desktop-icon': { left: 24, top: 77 },
      'containers-desktop-icon': { left: 24, top: 189 },
      'vm-desktop-icon': { left: 24, top: 301 },
      'fm-desktop-icon': { left: 24, top: 413 },
      'rb-desktop-icon': { left: 24, top: 525 },
      'chassis-desktop-icon': { left: 24, top: 637 },
    };
    localStorage.setItem('zettnas_desktop_icon_positions_v3', JSON.stringify(saved));
    Object.defineProperty(window, 'innerHeight', { value: 1200, configurable: true });
    Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true });
    initDraggableDesktopIcons();
    const pos = (id) => [document.getElementById(id).style.left, document.getElementById(id).style.top].join(',');
    expect(pos('chassis-desktop-icon')).toBe('24px,637px');
    expect(pos('dh-desktop-icon')).not.toBe('24px,637px');
    expect(new Set(ids.map(pos)).size).toBe(ids.length);
  });
});
