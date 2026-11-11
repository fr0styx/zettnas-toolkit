/** NUX-20: cloud sign-in, pool creation, share users, snapshots and pool renaming read in the person's language. */
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { setLanguage } from '../i18n.js';
import { api } from '../api.js';
import {
  openNewCloudRemoteModal,
  openCreateStoragePoolModal,
  openCreateNetworkShareModal,
  openRenameStoragePoolModal,
} from '../components/chassis-visualizer.js';

const tick = () => new Promise((r) => setTimeout(r, 20));

const REMOTE_MODAL = `
  <div id="modal-new-cloud-remote" class="smart-modal-backdrop" style="display: none;">
    <div class="smart-modal-window" id="cloud-remote-window"><div class="smart-modal-header" id="cloud-remote-window-header"></div>
      <form id="new-remote-form">
        <select id="new-remote-provider-select"></select><div id="new-remote-provider-desc"></div>
        <input type="text" id="new-remote-name" /><div id="new-remote-dynamic-fields"></div>
        <div id="new-remote-test-result"></div><button type="button" id="new-remote-test-btn"></button>
        <div id="new-remote-error-box"></div><button type="submit" id="new-remote-submit-btn">Save</button>
      </form>
    </div>
  </div>`;

const ONEDRIVE = [{
  type: 'onedrive', name: 'Microsoft OneDrive', category: 'Cloud Drives', authorize_cmd: 'rclone authorize "onedrive"',
  fields: [{ name: 'token', label: 'Token', type: 'textarea', required: true }],
}];

describe('storage dialogs in German (NUX-20)', () => {
  beforeAll(async () => { await setLanguage('de'); });
  afterAll(async () => { await setLanguage('en'); });
  afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks(); });

  it('walks the cloud sign-in in German, failures included', async () => {
    document.body.innerHTML = REMOTE_MODAL;
    vi.spyOn(api, 'get').mockImplementation((url) => (url === '/api/remotes/providers' ? Promise.resolve(ONEDRIVE) : Promise.resolve({ completed: false })));
    const post = vi.spyOn(api, 'post').mockRejectedValue(new Error('verweigert'));
    await openNewCloudRemoteModal();

    const card = document.querySelector('.oauth-assistant-card');
    expect(card.textContent).toContain('Microsoft OneDrive verbinden');
    expect(card.textContent).toContain('Hier anmelden, ohne Terminal');
    expect(card.textContent).toContain('Schritt 2:');
    expect(document.getElementById('btn-oauth-exchange').textContent).toContain('Anmeldung abschließen');
    expect(document.querySelector('.remote-copy-cmd-btn').textContent).toContain('Kopieren: rclone authorize');

    document.getElementById('btn-oauth-browser').click();
    await tick();
    const status = document.getElementById('oauth-assistant-status');
    expect(status.textContent).toBe('❌ Die Anmeldung konnte nicht gestartet werden: verweigert');
    expect(status.querySelector('[aria-hidden="true"]').textContent).toBe('❌');

    post.mockImplementation((url) => (url === '/api/remotes/oauth/start'
      ? Promise.resolve({ session_id: 's1', auth_url: 'https://login.example/' })
      : Promise.reject(new Error('abgelaufen'))));
    vi.spyOn(window, 'open').mockImplementation(() => null);
    document.getElementById('btn-oauth-browser').click();
    await tick();
    expect(status.textContent).toContain('Anmeldefenster geöffnet:');
    document.getElementById('oauth-redirect-url').value = 'http://localhost:53682/?code=x';
    document.getElementById('btn-oauth-exchange').click();
    await tick();
    expect(status.textContent).toContain('Die Anmeldung konnte nicht abgeschlossen werden: abgelaufen');
    expect(document.getElementById('btn-oauth-exchange').textContent).toContain('Anmeldung abschließen');
  });

  it('says why a connection test failed', async () => {
    document.body.innerHTML = REMOTE_MODAL;
    vi.spyOn(api, 'get').mockImplementation((url) => (url === '/api/remotes/providers' ? Promise.resolve(ONEDRIVE) : Promise.resolve({})));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: false });
    await openNewCloudRemoteModal();
    const testBtn = document.getElementById('new-remote-test-btn');
    const result = document.getElementById('new-remote-test-result');
    expect(testBtn.textContent).toContain('Verbindung testen');

    testBtn.click();
    await tick();
    expect(result.textContent).toBe('❌ Verbindung fehlgeschlagen: Die Anmeldung wurde abgelehnt');

    post.mockRejectedValue(new Error(''));
    testBtn.click();
    await tick();
    expect(result.textContent).toBe('❌ Verbindung fehlgeschlagen: Keine Antwort vom NAS');

    post.mockResolvedValue({ success: true, items_sample: ['a.txt', 'b.txt'] });
    testBtn.click();
    await tick();
    expect(result.textContent).toContain('Die Verbindung funktioniert.');
    expect(result.textContent).toContain('Gefundene Dateien: a.txt, b.txt.');
  });

  it('offers pool layouts and says when no drive is free', async () => {
    document.body.innerHTML = `
      <div id="modal-create-storage-pool"><form id="create-pool-form">
        <select id="create-pool-fs"><option value="btrfs">btrfs</option><option value="zfs">zfs</option><option value="ext4">ext4</option></select>
        <select id="create-pool-profile"></select><div id="create-pool-disks-container"></div>
      </form></div>`;
    vi.spyOn(api, 'get').mockResolvedValue([]);
    await openCreateStoragePoolModal();
    expect(document.getElementById('create-pool-disks-container').textContent).toBe('Keine freien Laufwerke.');
    const fs = document.getElementById('create-pool-fs');
    const profile = document.getElementById('create-pool-profile');
    fs.value = 'btrfs';
    fs.dispatchEvent(new Event('change'));
    expect(profile.textContent).toContain('RAID 1 (Spiegel, ab 2 Laufwerken)');
    fs.value = 'zfs';
    fs.dispatchEvent(new Event('change'));
    expect(profile.textContent).toContain('RAIDZ2 (zwei Paritätslaufwerke, ab 4 Laufwerken, empfohlen)');
    fs.value = 'ext4';
    fs.dispatchEvent(new Event('change'));
    expect(profile.textContent).toContain('Einzelnes Volume (ein Laufwerk)');
  });

  it('asks no address that does not exist for the people of a new share', async () => {
    // the people list called /api/auth/users, which the server does not have, and never loaded (SET-14)
    const get = vi.spyOn(api, 'get').mockResolvedValue([]);
    document.body.innerHTML = '<div id="modal-create-network-share"><form id="create-share-form"></form></div>';
    openCreateNetworkShareModal();
    expect(get).not.toHaveBeenCalledWith('/api/auth/users');
  });

  it('says when a pool could not be renamed', async () => {
    document.body.innerHTML = `
      <div id="modal-rename-storage-pool"><form id="rename-pool-form">
        <input id="rename-pool-current-name" /><input id="rename-pool-new-name" />
        <div id="rename-pool-error-box"></div><button type="submit" id="rename-pool-submit-btn">OK</button>
      </form></div>`;
    vi.spyOn(api, 'post').mockRejectedValue(new Error(''));
    openRenameStoragePoolModal('tank', 'Tank', () => {});
    document.getElementById('rename-pool-new-name').value = 'vault';
    document.getElementById('rename-pool-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    expect(document.getElementById('rename-pool-error-box').textContent).toBe('Der Speicherpool konnte nicht umbenannt werden');
  });
});
