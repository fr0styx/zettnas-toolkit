/** NUX-20: the chassis view, pool view, shares, SFTP, WebDAV and cloud cards read in the person's language. */
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { setLanguage } from '../i18n.js';
import { api } from '../api.js';
import {
  renderChassisTwin,
  openChassisConfigModal,
  renderStructuredPoolsTopology,
  renderStorageTopologyTree,
  buildSftpCardHtml,
  fetchAndRenderNetworkShares,
  fetchAndRenderRemoteStorage,
  fetchAndRenderStorageTopology,
  openSftpUsersModal,
  getThermalLevel,
} from '../components/chassis-visualizer.js';

const box = () => document.body.appendChild(document.createElement('div'));
const routes = (map) => vi.spyOn(api, 'get').mockImplementation((url) => (url in map ? Promise.resolve(map[url]) : Promise.reject(new Error(`no ${url}`))));

describe('chassis and storage text in German (NUX-20)', () => {
  beforeAll(async () => { await setLanguage('de'); });
  afterAll(async () => { await setLanguage('en'); });
  afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks(); });

  it('names bays, empty trays and M.2 slots', () => {
    const c = box();
    renderChassisTwin(c, [{ name: 'sda', model: 'IronWolf 8TB', temp: 38 }, { name: 'nvme0n1', model: 'SN770', temp: 41, percentage_used: 3 }]);
    expect(c.querySelector('[data-bay="2"]').getAttribute('aria-label')).toBe('Einschub 2, leer');
    expect(c.textContent).toContain('Einschub 2 frei');
    expect(c.textContent).toContain('KEIN LAUFWERK');
    expect(c.querySelector('[data-bay="1"]').getAttribute('aria-label')).toMatch(/^Einschub 1: IronWolf 8TB, /);
    expect(c.querySelector('.bay-locate-btn').getAttribute('aria-label')).toBe('Laufwerk in Einschub 1 finden');
    expect(c.textContent).toContain('M.2-STECKPLATZ 1 • /dev/nvme0n1');
    expect(c.textContent).toContain('Verschleiß:');
    expect(c.textContent).toContain('EINSCHÜBE / ZUORDNUNG');
    expect(getThermalLevel(null).text).toBe('UNBEKANNT');
  });

  it('sets up bays with the icon kept out of the words', () => {
    openChassisConfigModal({ profile: 'custom', total_bays: 1, bays: [], available_drives: [] });
    const m = document.getElementById('chassis-config-modal-overlay');
    expect(m.textContent).toContain('GEHÄUSE UND EINSCHÜBE');
    expect(m.querySelector('#chassis-profile-select').selectedOptions[0].textContent).toBe('Eigenes Gehäuse');
    expect(m.querySelector('.slot-drive-select option').textContent).toBe('— Leerer Einschub —');
    const auto = m.querySelector('#chassis-auto-assign-btn');
    expect(auto.querySelector('[aria-hidden="true"]').textContent).toBe('⚡');
    expect(auto.textContent).toContain('Der Reihe nach zuweisen');
    expect(m.querySelector('#chassis-config-cancel-btn').textContent).toBe('Abbrechen');
    expect(m.querySelector('#chassis-config-save-btn').textContent).toBe('Zuordnung speichern');
  });

  it('labels a pool, its members and its actions', () => {
    const c = box();
    renderStructuredPoolsTopology(c, {
      is_observer_mode: false,
      pools: [{ id: 'tank', name: 'tank', fs_type: 'btrfs', parity_protected: true, used_bytes: 1e12, total_bytes: 4e12, free_bytes: 3e12, used_pct: 25, members: [] }],
    });
    expect(c.textContent).toContain('Durch Parität geschützt');
    expect(c.textContent).toContain('LAUFWERKE IM POOL (0)');
    expect(c.textContent).toContain('Keine Laufwerke zugewiesen');
    expect(c.querySelector('.btn-pool-scrub').textContent).toContain('Pool prüfen (Scrub)');
    expect(c.querySelector('.btn-pool-snaps').textContent).toContain('Snapshots');
    expect(c.querySelector('.btn-pool-destroy').textContent).toContain('Löschen');
    expect(c.querySelector('.topo-free-space').textContent).toMatch(/ frei$/);
  });

  it('counts the drives of a plain array with a plural', () => {
    const c = box();
    renderStorageTopologyTree(c, [{ dev: 'parity', role: 'os' }, { dev: 'sdb', role: 'data' }, { dev: 'nvme0n1', role: 'cache' }]);
    expect(c.textContent).toContain('SPEICHERPOOLS UND AUFBAU');
    expect(c.textContent).toContain('PARITÄTSSCHUTZ (1)');
    expect(c.textContent).toContain('DATEN-ARRAY (1 LAUFWERK)');
    expect(c.textContent).toContain('NVME-/SSD-CACHE-POOL (1)');
    renderStorageTopologyTree(c, []);
    expect(c.textContent).toContain('DATEN-ARRAY (0 LAUFWERKE)');
    expect(c.textContent).toContain('Keine aktiven Datenlaufwerke');
  });

  it('describes the SFTP card', () => {
    const html = buildSftpCardHtml({ running: false, port: 2222 }, 3, 'alice');
    expect(html).toContain('SFTP starten');
    expect(html).toContain('Benutzer verwalten (3)');
    expect(html).toContain('Chroot-Käfig (/home/%u)');
    expect(html).toContain('Nicht erlaubt (kein PTY)');
    expect(html).toContain('SSHFS-Einbindung (Linux/macOS)');
    expect(html).toContain('<span aria-hidden="true">📋</span> Kopieren');
  });

  it('shows SFTP users and the service state', async () => {
    document.body.innerHTML = `
      <div id="modal-sftp-users"><div id="sftp-status-text"></div><button id="btn-sftp-toggle-service"></button>
      <div id="sftp-users-list"></div></div>`;
    routes({ '/api/sftp/status': { running: true, port: 2022 }, '/api/sftp/users': [{ username: 'bob', read_only: true }] });
    await openSftpUsersModal();
    expect(document.getElementById('sftp-status-text').textContent).toBe('● Läuft auf Port 2022');
    expect(document.getElementById('btn-sftp-toggle-service').textContent).toBe('SFTP stoppen');
    const list = document.getElementById('sftp-users-list');
    expect(list.textContent).toContain('Chroot: /home/bob');
    expect(list.querySelector('.btn-delete-sftp-user').textContent.trim()).toBe('Löschen');

    routes({ '/api/sftp/status': { running: false, port: 2022 }, '/api/sftp/users': [] });
    await openSftpUsersModal();
    expect(document.getElementById('sftp-status-text').textContent).toBe('○ Gestoppt (Port 2022)');
    expect(list.textContent).toContain('Noch keine SFTP-Benutzer.');
  });

  it('shows a share with its cache, and says when shares could not be read', async () => {
    const c = box();
    routes({
      '/api/storage/shares': { is_observer_mode: false, shares: [{ name: 'media', mountpoint: '/mnt/user/media', cache_mode: 'yes', used_pct: 40, used_bytes: 4, total_bytes: 10, free_bytes: 6 }] },
      '/api/storage/platform': { platform: 'generic_linux', capabilities: { can_manage_shares: true } },
    });
    await fetchAndRenderNetworkShares(c);
    const tag = c.querySelector('.share-cache-tag');
    expect(tag.textContent).toBe('Cache: yes');
    expect(tag.getAttribute('title')).toBe('Cache-Stufe: yes');
    expect(c.querySelector('.share-free-text').textContent).toMatch(/^40 % belegt · .+ frei$/);
    expect(c.querySelector('.btn-share-reveal').textContent).toContain('Im Datei-Explorer öffnen');
    await fetchAndRenderNetworkShares(c); // the card is updated in place
    expect(c.querySelector('.share-free-text').textContent).toMatch(/^40 % belegt/);

    vi.restoreAllMocks();
    vi.spyOn(api, 'get').mockRejectedValue(new Error('boom'));
    await fetchAndRenderNetworkShares(c);
    expect(c.textContent).toContain('Netzwerkfreigaben konnten nicht gelesen werden: boom');
  });

  it('lists cloud drives and the WebDAV server', async () => {
    const c = box();
    routes({
      '/api/webdav/status': { running: true, port: 8084, root_path: '/mnt/user', read_only: false, quick_connect: {} },
      '/api/remotes': [{ name: 'photos', type: 'drive', is_mounted: false }],
    });
    await fetchAndRenderRemoteStorage(c);
    expect(c.textContent).toContain('WebDAV-Dateiserver');
    expect(c.textContent).toContain('Windows: Netzlaufwerk verbinden');
    expect(c.textContent).toContain('Stammordner:');
    expect(c.textContent).toContain('Verbundene Cloud-Laufwerke (1)');
    expect(c.querySelector('.btn-remote-mount').textContent).toContain('Einbinden');

    vi.restoreAllMocks();
    routes({ '/api/webdav/status': { running: false, port: 8084, root_path: '/mnt/user', quick_connect: {} }, '/api/remotes': [] });
    await fetchAndRenderRemoteStorage(c);
    expect(c.textContent).toContain('Keine Cloud-Laufwerke verbunden');
    expect(c.querySelector('.btn-trigger-new-remote').textContent).toContain('Cloud-Laufwerk');

    vi.restoreAllMocks();
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'));
    await fetchAndRenderRemoteStorage(c);
    expect(c.textContent).toContain('Cloud-Laufwerke konnten nicht geladen werden: offline');
  });

  it('offers to import an external pool', async () => {
    const c = box();
    routes({
      '/api/storage/pools': { pools: [], is_observer_mode: false },
      '/api/storage/platform': {},
      '/api/storage/pools/discover': { discovered_pools: [{ pool_id: 'backup', fs_type: 'zfs' }] },
    });
    await fetchAndRenderStorageTopology(c);
    expect(c.textContent).toContain('Externer Speicherpool gefunden:');
    expect(c.querySelector('.btn-import-external-pool').textContent).toContain('Pool importieren');
  });
});
