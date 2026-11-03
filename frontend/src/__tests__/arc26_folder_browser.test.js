/** The folder picker: browsing inside the allowed roots, filtering, sorting, new folders and picking one. */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../components/dock.js', () => ({
  DockManager: { register: vi.fn(), unregister: vi.fn(), minimize: vi.fn() },
  bringToFront: vi.fn(),
}));

document.body.innerHTML = `
  <input id="btn-copy-dst" value="/mnt/user/media/">
  <button id="btn-browse-dst">Browse</button>
  <button id="btn-copy-save">Save</button>
  <div id="folder-browser-modal"><div class="smart-modal-window">
    <button id="fb-min"></button><button id="fb-close"></button>
    <div id="fb-current-path"></div>
    <input id="fb-search-bar"><button id="fb-sort-btn">A-Z</button>
    <input id="fb-new-folder-name"><button id="fb-create-folder">+ Create</button>
    <div id="fb-list"></div>
    <button id="fb-cancel"></button><button id="fb-select"></button>
  </div></div>`;

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { DockManager } = await import('../components/dock.js');
const { ZettEventBus } = await import('../event-bus.js');
const { setLanguage } = await import('../i18n.js');
await import('../folder-browser.js');

const $ = (id) => document.getElementById(id);
const rows = () => [...$('fb-list').children].map((d) => d.textContent);
const crumbs = () => [...$('fb-current-path').children];
const reply = (body, ok = true, status = 200) => ({ ok, status, json: async () => body });
const listing = (current, names, roots = ['/mnt/user']) => ({
  current,
  roots,
  dirs: names.map((n) => ({ name: n, path: n === '..' ? current.replace(/[^/]+\/$/, '') : current + n + '/' })),
});

let request;
beforeAll(() => window.dispatchEvent(new Event('DOMContentLoaded')));
beforeEach(() => {
  request = vi.spyOn(api, 'request').mockResolvedValue(reply(listing('/mnt/user/media/', ['..', 'Films', 'audio', 'Books'])));
});
afterEach(async () => {
  $('fb-cancel').click();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  await setLanguage('en');
});

async function open(path) {
  window.openFolderBrowser(path, null);
  await vi.waitFor(() => expect(rows().length).toBeGreaterThan(0));
}

describe('folder picker', () => {
  it('opens on the copy destination and lists its folders with the way up first', async () => {
    $('btn-browse-dst').click();
    await vi.waitFor(() => expect(rows().length).toBe(4));
    expect(request).toHaveBeenCalledWith('/api/browse?path=%2Fmnt%2Fuser%2Fmedia%2F');
    expect(rows()).toEqual(['⤴️..', '📁Films', '📁audio', '📁Books']);
    expect($('folder-browser-modal').classList.contains('open')).toBe(true);
    expect(DockManager.register).toHaveBeenCalledWith('fb', $('folder-browser-modal'), '#i-storage', 'Folder Browser');
  });

  it('only the parts of the path inside a root can be clicked', async () => {
    await open('/mnt/user/media/');
    expect(crumbs().map((c) => c.textContent).join('')).toBe('/mnt/user/media');
    const [, mnt, , user, , media] = crumbs();
    expect(mnt.onclick).toBeNull();
    expect(user.onclick).toBeTypeOf('function');
    media.onmouseover();
    expect(media.style.background).not.toBe('transparent');
    media.onmouseout();
    expect(media.style.background).toBe('transparent');
    user.onclick();
    expect(request).toHaveBeenLastCalledWith('/api/browse?path=%2Fmnt%2Fuser%2F');
  });

  it('filters by name without the way up, and sorts backwards', async () => {
    await open('/mnt/user/media/');
    $('fb-search-bar').value = 'O';
    $('fb-search-bar').dispatchEvent(new Event('input'));
    expect(rows()).toEqual(['📁audio', '📁Books']);
    $('fb-search-bar').value = 'zzz';
    $('fb-search-bar').dispatchEvent(new Event('input'));
    expect(rows()).toEqual(['No folders found.']);
    $('fb-search-bar').value = '';
    $('fb-sort-btn').click();
    expect($('fb-sort-btn').textContent).toBe('Z-A');
    expect(rows()).toEqual(['⤴️..', '📁Books', '📁audio', '📁Films']);
    $('fb-sort-btn').click();
    expect($('fb-sort-btn').textContent).toBe('A-Z');
  });

  it('clicking a folder opens it and clears the filter', async () => {
    await open('/mnt/user/media/');
    const films = $('fb-list').children[1];
    films.onmouseover();
    films.onmouseout();
    $('fb-search-bar').value = 'fil';
    films.click();
    expect($('fb-search-bar').value).toBe('');
    expect(request).toHaveBeenLastCalledWith('/api/browse?path=%2Fmnt%2Fuser%2Fmedia%2FFilms%2F');
  });

  it('a folder it may not open falls back to the default root, then reports', async () => {
    request.mockResolvedValueOnce(reply({}, false, 403)).mockResolvedValueOnce(reply(listing('/mnt/user/', ['a'])));
    window.openFolderBrowser('/etc/');
    await vi.waitFor(() => expect(rows()).toEqual(['📁a']));
    expect(request.mock.calls.map((c) => c[0])).toEqual(['/api/browse?path=%2Fetc%2F', '/api/browse?path=']);

    request.mockReset();
    request.mockResolvedValueOnce(reply({}, false, 404)).mockResolvedValueOnce(reply({ detail: 'No pools' }, false, 500));
    window.openFolderBrowser('/gone/');
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Failed to load folder: No pools', 'error'));

    request.mockReset();
    request.mockResolvedValueOnce(reply({}, false, 404)).mockResolvedValueOnce({ ok: false, status: 502, json: async () => { throw new Error('html'); } });
    window.openFolderBrowser('/gone/');
    await vi.waitFor(() => expect(showToast).toHaveBeenLastCalledWith('Failed to load folder: 502', 'error'));

    request.mockReset();
    request.mockRejectedValueOnce(new Error('offline'));
    window.openFolderBrowser('');
    await vi.waitFor(() => expect(showToast).toHaveBeenLastCalledWith('Failed to load folder: Error: offline', 'error'));
  });

  it('picking a folder fills the copy destination and says saved', async () => {
    vi.useFakeTimers();
    try {
      window.openFolderBrowser('/mnt/user/media/');
      await vi.waitFor(() => expect(rows().length).toBe(4));
      const seen = vi.fn();
      ZettEventBus.addEventListener('folder_selected', seen);
      $('fb-select').click();
      ZettEventBus.removeEventListener('folder_selected', seen);
      expect($('btn-copy-dst').value).toBe('/mnt/user/media/');
      expect(seen.mock.calls[0][0].detail).toBe('/mnt/user/media/');
      expect($('folder-browser-modal').classList.contains('open')).toBe(false);
      expect(DockManager.unregister).toHaveBeenCalledWith('fb');
      expect($('btn-copy-save').textContent).toBe('Saved!');
      vi.advanceTimersByTime(2000);
      expect($('btn-copy-save').textContent).toMatch(/Save/);
    } finally {
      vi.useRealTimers();
    }
  });

  it('a caller with its own callback gets the folder instead', async () => {
    const picked = vi.fn(() => { throw new Error('caller bug'); });
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    $('btn-copy-dst').value = '/mnt/user/keep/';
    window.openFolderBrowser('/mnt/user/media/', picked);
    await vi.waitFor(() => expect(rows().length).toBe(4));
    $('fb-select').click();
    expect(picked).toHaveBeenCalledWith('/mnt/user/media/');
    expect(err).toHaveBeenCalled();
    expect($('btn-copy-dst').value).toBe('/mnt/user/keep/');
  });

  it('makes a new folder, refusing names with slashes or dots', async () => {
    await open('/mnt/user/media');
    request.mockResolvedValue(reply(listing('/mnt/user/media', ['new'])));
    const name = $('fb-new-folder-name');
    for (const bad of ['  ', 'a/b', '..x']) {
      name.value = bad;
      $('fb-create-folder').click();
    }
    expect(request).not.toHaveBeenCalledWith('/api/mkdir', expect.anything());
    request.mockResolvedValueOnce(reply({ ok: true }));
    name.value = ' Holiday ';
    name.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    name.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }));
    await vi.waitFor(() => expect($('fb-create-folder').textContent).toBe('+ Create'));
    expect(request).toHaveBeenCalledWith('/api/mkdir', expect.objectContaining({ method: 'POST', body: { path: '/mnt/user/media/Holiday' } }));
    expect(name.value).toBe('');
    expect(name.placeholder).toBe('New folder name...');
  });

  it('says why a new folder failed, in the reader\'s language', async () => {
    await open('/mnt/user/media/');
    const name = $('fb-new-folder-name');
    request.mockResolvedValueOnce(reply({ detail: 'Exists' }, false, 409));
    name.value = 'x';
    $('fb-create-folder').click();
    await vi.waitFor(() => expect(name.placeholder).toBe('Could not create the folder: Exists'));

    request.mockResolvedValueOnce({ ok: false, status: 507, json: async () => { throw new Error(); } });
    name.value = 'y';
    $('fb-create-folder').click();
    await vi.waitFor(() => expect(name.placeholder).toBe('Could not create the folder: 507'));

    request.mockRejectedValueOnce(new Error('down'));
    name.value = 'z';
    $('fb-create-folder').click();
    await vi.waitFor(() => expect(name.placeholder).toBe('Network Error'));

    await setLanguage('de');
    request.mockResolvedValueOnce(reply({ error: 'Voll' }, false, 507));
    name.value = 'w';
    $('fb-create-folder').click();
    await vi.waitFor(() => expect(name.placeholder).toBe('Der Ordner konnte nicht erstellt werden: Voll'));
  });

  it('closes from cancel, the close button, a touch or the backdrop, and minimizes to the dock', async () => {
    const isOpen = () => $('folder-browser-modal').classList.contains('open');
    const touch = (el) => el.dispatchEvent(new Event('touchend', { cancelable: true }));
    await open('/mnt/user/');
    $('fb-close').click();
    expect(isOpen()).toBe(false);
    expect($('folder-browser-modal').style.getPropertyValue('display')).toBe('none');
    await open('/mnt/user/');
    touch($('fb-close'));
    expect(isOpen()).toBe(false);
    await open('/mnt/user/');
    touch($('fb-cancel'));
    expect(isOpen()).toBe(false);
    await open('/mnt/user/');
    $('folder-browser-modal').querySelector('.smart-modal-window').click();
    expect(isOpen()).toBe(true);
    $('folder-browser-modal').click();
    expect(isOpen()).toBe(false);
    await open('/mnt/user/');
    window.openFolderBrowser('/mnt/user/');
    $('fb-min').click();
    touch($('fb-min'));
    expect(DockManager.minimize).toHaveBeenCalledTimes(2);
    touch($('btn-browse-dst'));
    $('btn-copy-dst').value = '';
    $('btn-browse-dst').click();
    expect(request).toHaveBeenLastCalledWith('/api/browse?path=%2Fmnt%2Fuser%2F');
  });
});
