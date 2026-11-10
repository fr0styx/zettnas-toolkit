/** ARC-26: the metric detail window and the event detail window (modals.js). */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';

vi.mock('../components/dock.js', () => ({
  DockManager: { register: vi.fn(), restore: vi.fn(), unregister: vi.fn(), minimize: vi.fn() },
  bringToFront: vi.fn(),
  makeDraggable: vi.fn(),
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText: vi.fn(async () => {}) }));

const { DockManager } = await import('../components/dock.js');
const { showToast } = await import('../toast.js');
const { copyText } = await import('../utils.js');
const { ZettEventBus } = await import('../event-bus.js');

const byId = (id) => document.getElementById(id);
// stats_tick is coalesced to the next animation frame by emit(); dispatch it directly
const tick = (detail) => ZettEventBus.dispatchEvent(new CustomEvent('stats_tick', { detail }));
const DOM = `
  <div id="smart-modal-overlay"><div class="smart-modal-window">
    <h2 id="smart-modal-title"></h2><button id="smart-modal-close"></button><button id="smart-modal-min"></button>
    <button id="smart-modal-refresh"></button>
    <span id="smart-lbl-1"></span><span id="smart-lbl-2"></span><span id="smart-lbl-3"></span><span id="smart-lbl-4"></span>
    <span id="smart-meta-model"></span><span id="smart-meta-serial"></span><span id="smart-meta-health"></span><span id="smart-meta-hours"></span>
    <h3 id="smart-modal-raw-title"></h3><pre id="smart-raw-output"></pre>
    <div id="smart-actions-container"></div><div id="smart-nav-tabs"></div>
    <div id="smart-pane-health"></div><div id="smart-pane-selftest"></div><div id="smart-pane-raw"></div>
    <div class="smart-raw-toolbar"></div>
  </div></div>
  <div id="event-detail-modal-overlay"><div class="smart-modal-window">
    <div id="event-detail-header"><span id="event-detail-header-icon"></span></div>
    <button id="event-detail-close"></button><button id="event-detail-close-btn"></button>
    <span id="event-detail-badge"><span id="event-detail-badge-icon"></span><span id="event-detail-badge-text"></span></span>
    <span id="event-detail-subsystem"></span><span id="event-detail-reltime"></span>
    <h3 id="event-detail-event-title"></h3><p id="event-detail-event-message"></p>
    <span id="event-detail-localtime"></span><span id="event-detail-epoch"></span><pre id="event-detail-raw"></pre>
    <button id="event-detail-context-btn"></button>
    <button id="event-detail-copy-btn"><span id="event-detail-copy-icon"></span><span id="event-detail-copy-text"></span></button>
  </div></div>`;

const STATS = {
  name: 'nas', ip: '10.0.0.9', uptime: '3 days',
  storage: { used: '1 TB', total: '4 TB', pct: 95 }, disks: [{ dev: 'sda' }],
  cpu: { temp: 80, util: 12 },
  mem: { used_gb: 6, total_gb: 16, pct: 37 },
  fans: [900, 0, 1200],
  net: { tx: '1 MB/s', rx: '2 MB/s' },
};

let modals;
describe('detail windows (modals.js)', () => {
  beforeAll(async () => {
    document.body.innerHTML = DOM;
    modals = await import('../modals.js');
    window.dispatchEvent(new Event('DOMContentLoaded'));
  });
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it('opens each metric window and keeps it live', () => {
    ZettEventBus.emit('modal:metric:open', 'cpu'); // no stats yet: stays shut
    expect(byId('smart-modal-overlay').classList.contains('open')).toBe(false);
    tick(STATS);

    ZettEventBus.emit('modal:metric:open', 'storage');
    expect(byId('smart-modal-overlay').style.display).toBe('flex');
    expect(DockManager.register).toHaveBeenCalled();
    expect(byId('smart-meta-health').textContent).toBe('95%');
    expect(byId('smart-meta-health').style.color).toBe('var(--crit)');

    ZettEventBus.emit('modal:metric:open', 'cpu');
    expect(byId('smart-meta-health').textContent).toBe('High');
    expect(byId('smart-modal-raw-title').textContent).toBe('Processor details');
    expect(byId('smart-raw-output').textContent).toContain('IP: 10.0.0.9');
    ZettEventBus.emit('modal:metric:open', 'mem');
    expect(byId('smart-meta-hours').textContent).toBe('10.0 GB');
    tick({ ...STATS, cpu: { temp: 40, util: 5 } });
    ZettEventBus.emit('modal:metric:open', 'cpu');
    expect(byId('smart-meta-health').textContent).toBe('Normal');
    ZettEventBus.emit('modal:metric:open', 'mem');
    tick(STATS);
    ZettEventBus.emit('modal:metric:open', 'fans');
    expect(byId('smart-meta-serial').textContent).toBe('N/A');
    expect(byId('smart-meta-health').textContent).toBe('1200 RPM');
    expect(byId('smart-raw-output').textContent).toContain('Fan 2 (disks): 0 RPM');
    ZettEventBus.emit('modal:metric:open', 'net');
    expect(byId('smart-meta-model').textContent).toBe('1 MB/s');

    tick({ ...STATS, net: null });
    expect(byId('smart-meta-model').textContent).toBe('0 KB/s');
    expect(byId('smart-raw-output').textContent).toContain('Sending: 0 KB/s');
    expect(byId('smart-meta-health').textContent).toBe('Connected');
    byId('smart-modal-refresh').click();
    expect(byId('smart-lbl-4').textContent).toBe('IP address');
    window.dispatchEvent(new Event('kiboto:lang-changed'));
    expect(byId('smart-lbl-1').textContent).toBe('Sending now');
  });

  it('closes, minimises and ignores clicks inside', () => {
    ZettEventBus.emit('modal:metric:open', 'cpu');
    byId('smart-modal-min').click();
    expect(DockManager.minimize).toHaveBeenCalledWith('smart');
    byId('smart-modal-min').dispatchEvent(new Event('touchend', { cancelable: true }));
    byId('smart-modal-title').click();
    expect(byId('smart-modal-overlay').classList.contains('open')).toBe(true);
    byId('smart-modal-overlay').click();
    expect(byId('smart-modal-overlay').classList.contains('open')).toBe(false);
    ZettEventBus.emit('modal:metric:open', 'mem');
    byId('smart-modal-close').dispatchEvent(new Event('touchend', { cancelable: true }));
    expect(byId('smart-modal-overlay').style.display).toBe('none');
    ZettEventBus.emit('modal:metric:open', 'mem');
    ZettEventBus.emit('modal:smart:close');
    expect(DockManager.unregister).toHaveBeenCalledWith('smart');
  });

  const CASES = [
    ['SD card inserted', 'MEDIA & INGEST', 'drawer', 'tab-buttons'],
    ['Night mode on the LED lightbar', 'ARGB LIGHTBAR', 'drawer', 'tab-led'],
    ['Fan curve changed', 'THERMAL & FANS', 'drawer', 'tab-fans'],
    ['Dashboard layout saved', 'DASHBOARD LAYOUT', 'drawer', 'tab-layout'],
    ['Failed login for bob', 'SECURITY & ACCESS', 'mgmt', 'mgmt-pane-security'],
    ['UPS on battery', 'POWER & UPS', 'mgmt', 'mgmt-sec-ups'],
    ['Docker container exited', 'DOCKER CONTAINERS', 'mgmt', 'mgmt-pane-docker'],
    ['Parity check finished', 'UNRAID OS & ARRAY', 'mgmt', 'mgmt-pane-unraid'],
    ['Wallpaper changed', 'APPEARANCE & THEME', 'mgmt', 'mgmt-pane-wallpaper'],
    ['Metrics history trimmed', 'SYSTEM METRICS', 'mgmt', 'mgmt-pane-metrics'],
    ['Nightly job done', 'SYSTEM LOG', 'mgmt', 'mgmt-pane-events'],
  ];

  it.each(CASES)('"%s" belongs to %s and opens the right place', (title, subsystem, kind, target) => {
    window.openDrawer = vi.fn();
    window.openManagementWindow = vi.fn();
    modals.openEventDetailModal({ title, level: 'info', ts: Math.floor(Date.now() / 1000) });
    expect(byId('event-detail-subsystem').textContent).toBe(subsystem);
    byId('event-detail-context-btn').click();
    expect(byId('event-detail-modal-overlay').style.display).toBe('none');
    const fn = kind === 'drawer' ? window.openDrawer : window.openManagementWindow;
    expect(fn).toHaveBeenCalledWith(target);
    delete window.openDrawer;
    delete window.openManagementWindow;
  });

  it('without the drawer opener, clicks the drawer button and its tab', () => {
    document.body.insertAdjacentHTML('beforeend',
      '<button id="drawer-toggle-btn"></button>' +
      ['tab-buttons', 'tab-led', 'tab-fans', 'tab-layout'].map((t) => `<button class="drawer-tab-btn" data-tab="${t}"></button>`).join(''));
    const clicks = [];
    document.querySelectorAll('#drawer-toggle-btn, .drawer-tab-btn').forEach((b) => b.addEventListener('click', () => clicks.push(b.dataset.tab || 'drawer')));
    for (const title of ['SD card inserted', 'LED off', 'Fan stopped', 'Widget added']) {
      modals.openEventDetailModal({ title });
      byId('event-detail-context-btn').click();
    }
    expect(clicks).toEqual(['drawer', 'tab-buttons', 'drawer', 'tab-led', 'drawer', 'tab-fans', 'drawer', 'tab-layout']);
  });

  it('files, the recycle bin, drives and the console', () => {
    const opened = vi.fn();
    ZettEventBus.on('window:open', opened);
    modals.openEventDetailModal({ title: 'File uploaded' });
    byId('event-detail-context-btn').click();
    expect(opened.mock.calls[0][0]).toEqual({ id: 'file-manager-window' });
    window.openRecycleBin = vi.fn();
    modals.openEventDetailModal({ title: 'Moved to the Recycle Bin' });
    byId('event-detail-context-btn').click();
    expect(window.openRecycleBin).toHaveBeenCalled();
    delete window.openRecycleBin;

    const smart = vi.fn();
    ZettEventBus.on('modal:smart:open', smart);
    modals.openEventDetailModal({ title: 'Drive health', message: 'sdb has reallocated sectors' });
    byId('event-detail-context-btn').click();
    modals.openEventDetailModal({ title: 'NVMe wear', details: { dev: 'nvme0n1' } });
    byId('event-detail-context-btn').click();
    expect(smart.mock.calls.map((c) => c[0])).toEqual(['sdb', 'nvme0n1']);

    window.openConsoleWindow = vi.fn();
    modals.openEventDetailModal({ title: 'Shell session ended' });
    byId('event-detail-context-btn').click();
    expect(window.openConsoleWindow).toHaveBeenCalled();
    delete window.openConsoleWindow;
  });

  it('shows the level, the time and the raw event', () => {
    const now = Math.floor(Date.now() / 1000);
    for (const [level, icon] of [['error', '❌'], ['warning', '⚠️'], ['success', '✅'], [undefined, 'ℹ️']]) {
      modals.openEventDetailModal({ title: 'x', level, ts: now });
      expect(byId('event-detail-badge-icon').textContent).toBe(icon);
    }
    expect(byId('event-detail-reltime').textContent).toBe('Just now');
    modals.openEventDetailModal({ ts: now - 120 });
    expect(byId('event-detail-reltime').textContent).toBe('2m ago');
    expect(byId('event-detail-event-title').textContent).toBe('System Notification');
    expect(byId('event-detail-event-message').textContent).toBe('--');
    modals.openEventDetailModal({ ts: now - 7200 });
    expect(byId('event-detail-reltime').textContent).toBe('2h ago');
    modals.openEventDetailModal({ ts: now - 3 * 86400, details: { report_markdown: '# Report' } });
    expect(byId('event-detail-reltime').textContent).toBe('3d ago');
    expect(byId('event-detail-raw').textContent).toBe('# Report');
    modals.openEventDetailModal(null);
    window.dispatchEvent(new Event('kiboto:lang-changed'));
    expect(byId('event-detail-raw').textContent).toBe('# Report');
  });

  it('copies the event details', async () => {
    vi.useFakeTimers();
    modals.openEventDetailModal({ title: 'Disk report', details: { report_markdown: '# Disk' } });
    byId('event-detail-copy-btn').click();
    await vi.advanceTimersByTimeAsync(0);
    expect(copyText).toHaveBeenCalledWith('# Disk');
    expect(byId('event-detail-copy-text').textContent).toBe('Copied!');
    expect(showToast).toHaveBeenCalledWith('Event details copied to clipboard', 'info');
    await vi.advanceTimersByTimeAsync(2000);
    expect(byId('event-detail-copy-text').textContent).toBe('Copy Details');

    modals.openEventDetailModal({ title: 'Plain', level: 'info' });
    copyText.mockRejectedValueOnce(new Error('denied'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    byId('event-detail-copy-btn').click();
    await vi.advanceTimersByTimeAsync(0);
    expect(JSON.parse(copyText.mock.calls.at(-1)[0]).title).toBe('Plain');
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();

    const label = byId('event-detail-copy-text');
    label.remove(); // a window without the label still copies
    byId('event-detail-copy-btn').click();
    await vi.advanceTimersByTimeAsync(2000);
    expect(copyText).toHaveBeenCalledTimes(3);
    byId('event-detail-copy-btn').append(label);
  });

  it('closes with its buttons, the backdrop and the event bus', () => {
    for (const close of [
      () => byId('event-detail-close').click(),
      () => byId('event-detail-close-btn').click(),
      () => byId('event-detail-modal-overlay').click(),
      () => ZettEventBus.emit('modal:event-detail:close'),
    ]) {
      ZettEventBus.emit('modal:event-detail:open', { title: 'x' });
      expect(byId('event-detail-modal-overlay').classList.contains('open')).toBe(true);
      close();
      expect(byId('event-detail-modal-overlay').classList.contains('open')).toBe(false);
    }
  });
});
