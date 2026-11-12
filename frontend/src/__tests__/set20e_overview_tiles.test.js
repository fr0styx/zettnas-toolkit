/** SET-20 (Overview 5): the status box, three tiles and Getting started. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('../api.js', () => ({ api: { get: vi.fn() } }));
const { api } = await import('../api.js');
const { ZettEventBus } = await import('../event-bus.js');
const { state } = await import('../state.js');
const tiles = await import('../components/management/overview-tiles.js');
const overview = await import('../components/management/overview.js');
const gs = await import('../components/getting-started.js');
window.gettingStartedHtml = gs.checklistHtml;

const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');
const HUB = `<div id="management-hub-view"><h2 class="mgmt-hub-heading">Overview</h2>
  <span id="mgmt-hub-storage-line"></span><span id="mgmt-hub-apps-line"></span><span id="mgmt-hub-backup-line"></span>
  <section id="mgmt-hub-getting-started" hidden></section></div>`;

describe('the Overview (SET-20, Overview 5)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete globalThis.kibotoUser;
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('has a heading, three tiles and no old cards', () => {
    const hub = html.slice(html.indexOf('id="management-hub-view"'), html.indexOf('<!-- DETAIL CONTAINER'));
    expect(hub).toContain('class="mgmt-hub-heading"');
    expect((hub.match(/mgmt-hub-tile"/g) || []).length).toBe(3);
    for (const target of ['mgmt-sec-storage', 'mgmt-sec-docker', 'mgmt-pane-backups']) expect(hub).toContain(`data-mgmt-target="${target}"`);
    for (const gone of ['mgmt-sec-vms', 'mgmt-sec-network', 'mgmt-sec-wallpaper', 'mgmt-sec-system-group', 'mgmt-app-pill']) expect(hub).not.toContain(gone);
  });

  it('says what storage, apps and backup hold, in words', () => {
    const two = { storage: { used: '1.2 TB', total: '4 TB' }, disks: [{ health: 'OK' }, { health: 'standby' }] };
    expect(tiles.storageLine(two, 0)).toBe('1.2 TB of 4 TB used · 2 drives, all healthy');
    expect(tiles.storageLine(two, null)).toBe('1.2 TB of 4 TB used · 2 drives'); // no verdict yet: no "healthy"
    expect(tiles.storageLine(two, 1)).toBe('1.2 TB of 4 TB used · 1 drive needs a look'); // the status box's warning wins
    expect(tiles.storageLine({ disks: [{ health: 'FAILING' }] }, 0)).toBe('1 drive needs a look');
    expect(tiles.storageLine({}, null)).toBe('');
    expect(tiles.driveIssues({ items: [{ kind: 'drive_warning' }, { kind: 'drive_attention' }, { kind: 'ups' }] })).toBe(2);
    expect(tiles.driveIssues(null)).toBeNull();
    expect(tiles.appsLine({ docker: [{ name: 'kiboto', state: 'running' }, { name: 'jellyfin', state: 'running' }, { name: 'plex', state: 'exited' }] })).toBe('2 apps, 1 running · 1 stopped');
    expect(tiles.appsLine({ docker: [{ name: 'immich', state: 'running' }] })).toBe('1 app, 1 running');
    expect(tiles.appsLine({})).toBe('');
    expect(tiles.backupLine({ level: 'none' })).toBe('No copy outside this NAS yet');
    expect(tiles.backupLine({ level: 'good' })).toBe('Copies outside this NAS');
    expect(tiles.backupLine({ level: 'good', last_good: 1700000000 })).toContain('Newest copy outside: ');
    expect(tiles.backupLine(null)).toBe('');
  });

  it('fills the tiles now and with every live reading', async () => {
    document.body.innerHTML = HUB;
    state.lastStats = { docker: [{ name: 'a', state: 'running' }] };
    tiles.installHubTiles();
    expect(document.getElementById('mgmt-hub-apps-line').textContent).toBe('1 app, 1 running');
    ZettEventBus.emit('stats:updated', { docker: [{ name: 'a', state: 'running' }, { name: 'b', state: 'running' }] });
    await vi.waitFor(() => expect(document.getElementById('mgmt-hub-apps-line').textContent).toBe('2 apps, 2 running')); // the bus batches readings per frame
    tiles.updateHubTiles(null);
    state.lastStats = null;
  });

  it('shows Getting started to whoever sets the NAS up, while steps are open', async () => {
    document.body.innerHTML = HUB;
    api.get.mockResolvedValue({ items: [{ id: 'backup', open: 'mgmt-pane-backups', done: false }], done: 0, total: 1, complete: false });
    state.lastStats = { disks: [{ health: 'OK' }] };
    await tiles.renderHubExtras(document, { level: 'none' }, { items: [{ kind: 'drive_warning' }] });
    expect(document.getElementById('mgmt-hub-storage-line').textContent).toBe('1 drive needs a look');
    state.lastStats = null;
    const box = document.getElementById('mgmt-hub-getting-started');
    expect(box.hidden).toBe(false);
    expect(box.querySelector('#gs-hub-heading')).not.toBeNull();
    expect(box.querySelector('[data-gs-hide]')).toBeNull();
    expect(document.getElementById('mgmt-hub-backup-line').textContent).toBe('No copy outside this NAS yet');
    window.openManagementSection = vi.fn();
    /** @type {HTMLElement} */ (box.querySelector('[data-gs-open]')).click();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-backups');
    delete window.openManagementSection;
    api.get.mockResolvedValue({ items: [], complete: true });
    await tiles.renderHubExtras(document, null);
    expect(box.hidden).toBe(true);
  });

  it('a family member gets no Getting started here', async () => {
    document.body.innerHTML = HUB;
    globalThis.kibotoUser = { scopes: ['shares:read'] };
    expect(tiles.setsUp()).toBe(false);
    await tiles.renderHubExtras(document, null);
    expect(api.get).not.toHaveBeenCalled();
    expect(document.getElementById('mgmt-hub-getting-started').hidden).toBe(true);
    expect(tiles.setsUp({ scopes: ['system:config'] })).toBe(true);
    document.body.innerHTML = '<div id="management-hub-view"></div>';
    await tiles.renderHubExtras(document, null);
  });

  it('the status box goes under the heading', async () => {
    document.body.innerHTML = HUB;
    api.get.mockRejectedValue(new Error('offline'));
    await overview.renderStatusSummary(document);
    await vi.waitFor(() => expect(document.getElementById('mgmt-hub-storage-line')).not.toBeNull());
    const hub = document.getElementById('management-hub-view');
    expect(hub.firstElementChild.className).toBe('mgmt-hub-heading');
    expect(hub.children[1].id).toBe('mgmt-status-summary');
  });

  it('getting-started.js hands the Overview its list builder', () => {
    vi.useFakeTimers();
    delete window.gettingStartedHtml;
    gs.initGettingStarted();
    expect(window.gettingStartedHtml).toBe(gs.checklistHtml);
    expect(typeof window.openGettingStarted).toBe('function');
    vi.clearAllTimers();
    vi.useRealTimers();
  });
});
