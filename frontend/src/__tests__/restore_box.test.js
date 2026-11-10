import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }, auth: {} }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { kitHtml, planHtml, waitForRestart, openRestoreBox } = await import('../components/restore-box.js');

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const click = (el) => el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
const REPO = { id: 'usb-disk', name: 'USB disk', location: '/mnt/disks/usb/kiboto' };
const VERSIONS = [{ id: 'abcd1234', time: '2026-11-09T02:00:00Z', paths: ['/mnt/user/family'] }];
const COPIES = [{ id: 'ffff0000', time: '2026-11-09T02:01:00Z' }];

describe('restore a whole box from its recovery kit (RES-7)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('asks for the kit, then shows settings first and files second', () => {
    expect(kitHtml()).toContain('restorebox-kit');
    const plan = planHtml({ repo: REPO, versions: VERSIONS, settings: COPIES });
    expect(plan).toContain('USB disk');
    expect(plan).toContain('/mnt/user/family');
    expect(plan).not.toContain('disabled');
    const old = planHtml({ repo: { id: 'x' }, versions: [], settings: [] });
    expect(old).toContain('made before Kiboto 2.0');
    expect(old).toContain('no versions yet');
    expect(old.match(/disabled/g)).toHaveLength(2);
  });

  it('reloads once Kiboto went down and came back', async () => {
    const answers = [true, false, false, true];
    const fetchImpl = vi.fn(async () => {
      const ok = answers.shift();
      if (ok === false) throw new Error('down');
      return { ok };
    });
    const reload = vi.fn();
    expect(await waitForRestart({ fetchImpl, reload, sleep: async () => {}, tries: 10 })).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(await waitForRestart({ fetchImpl: async () => ({ ok: true }), reload, sleep: async () => {}, tries: 3 })).toBe(false);
  });

  it('connects a pasted kit, brings back the settings and waits for the restart', async () => {
    const done = vi.fn();
    const dlg = await openRestoreBox(null, done);
    /** @type {HTMLTextAreaElement} */ (dlg.querySelector('#restorebox-kit')).value = 'Kiboto off-site backup: recovery kit';
    api.post.mockResolvedValueOnce({ repo: REPO, versions: VERSIONS, settings: COPIES });
    click(dlg.querySelector('[data-rb="connect"]'));
    await tick();
    expect(api.post).toHaveBeenCalledWith('/api/offsite/connect-kit', { kit: 'Kiboto off-site backup: recovery kit' });
    expect(done).toHaveBeenCalled();
    api.post.mockResolvedValueOnce({ restarting: false });
    click(dlg.querySelector('[data-rb="settings"]'));
    await tick();
    expect(api.post).toHaveBeenLastCalledWith('/api/offsite/repos/usb-disk/restore-settings', { snapshot: 'latest' });
    expect(dlg.textContent).toContain('Restart the Kiboto container');
  });

  it('says that Kiboto restarts by itself when Docker brings it back', async () => {
    vi.useFakeTimers();
    try {
      const dlg = await openRestoreBox(null);
      /** @type {HTMLTextAreaElement} */ (dlg.querySelector('#restorebox-kit')).value = 'kit';
      api.post.mockResolvedValueOnce({ repo: REPO, versions: VERSIONS, settings: COPIES });
      click(dlg.querySelector('[data-rb="connect"]'));
      await vi.runOnlyPendingTimersAsync();
      api.post.mockResolvedValueOnce({ restarting: true });
      click(dlg.querySelector('[data-rb="settings"]'));
      await vi.advanceTimersByTimeAsync(0);
      expect(dlg.textContent).toContain('this page reloads by itself');
    } finally {
      vi.useRealTimers();
    }
  });

  it('reads a chosen kit file into the box', async () => {
    const dlg = await openRestoreBox(null);
    const input = /** @type {HTMLInputElement} */ (dlg.querySelector('#restorebox-file'));
    const file = new File(['Backup location: /x'], 'kit.txt', { type: 'text/plain' });
    Object.defineProperty(input, 'files', { value: [file] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 20));
    expect(/** @type {HTMLTextAreaElement} */ (dlg.querySelector('#restorebox-kit')).value).toBe('Backup location: /x');
  });

  it('opens on a connected backup and starts the files restore', async () => {
    api.get.mockImplementation(async (url) => {
      if (url === '/api/offsite') return { repos: [REPO] };
      if (url.endsWith('/snapshots')) return { snapshots: VERSIONS };
      return { copies: COPIES };
    });
    const dlg = await openRestoreBox('usb-disk');
    expect(dlg.textContent).toContain('USB disk');
    api.post.mockResolvedValueOnce({ paths: ['/mnt/user/family', '/mnt/user/photos'] });
    click(dlg.querySelector('[data-rb="files"]'));
    await tick();
    expect(api.post).toHaveBeenCalledWith('/api/offsite/repos/usb-disk/restore-all', { snapshot: 'latest' });
    expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('2 folders'), 'info');
  });

  it('shows what went wrong', async () => {
    api.get.mockRejectedValue(new Error('restic is not installed'));
    const dlg = await openRestoreBox('gone');
    expect(dlg.textContent).toContain('restic is not installed');
    const fresh = await openRestoreBox(null);
    api.post.mockRejectedValueOnce(new Error('This is not a Kiboto recovery kit'));
    click(fresh.querySelector('[data-rb="connect"]'));
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('This is not a Kiboto recovery kit', 'error');
    click(fresh.querySelector('[data-close]'));
  });
});

describe('where the restore starts', () => {
  beforeEach(() => vi.clearAllMocks());

  it('the off-site page offers to connect a kit', async () => {
    const { connectKitHtml } = await import('../components/offsite-backup.js');
    expect(connectKitHtml()).toContain('data-off="connect"');
  });

  it('the setup wizard shows the note and opens the restore after setup', async () => {
    document.body.innerHTML = '<div id="setup-restore-note" hidden></div>';
    const { showRestoreNote, openRestoreAfterSetup } = await import('../components/setup-wizard.js');
    showRestoreNote();
    expect(document.getElementById('setup-restore-note').hidden).toBe(false);
    await openRestoreAfterSetup();
    expect(document.getElementById('restore-box')).not.toBeNull();
  });
});
