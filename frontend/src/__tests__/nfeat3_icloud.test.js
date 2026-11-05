/** NFEAT-3 / D14: the "Download from iCloud Photos" dialog. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { openICloudPhotos, lastDownloadText } = await import('../components/icloud-photos.js');

const q = (s) => document.querySelector(s);
const OUT = { signed_in: false, apple_id: '', needs_code: false, downloading: false, last_download: null, error: '' };
const READY = { ...OUT, signed_in: true, apple_id: 'ana@icloud.com' };

describe('download from iCloud Photos', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('signs in, takes the code and starts the download into the folder', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(OUT);
    const post = vi.spyOn(api, 'post').mockImplementation(async (url) => {
      if (url.endsWith('/sign-in')) return { ...OUT, apple_id: 'ana@icloud.com', needs_code: true };
      if (url.endsWith('/code')) return READY;
      return { status: 'started', job_id: 'job:1' };
    });
    await openICloudPhotos('/mnt/user/Photos');
    q('#ic-id').value = ' ana@icloud.com ';
    q('#ic-pw').value = 'secret';
    q('#ic-pw').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await vi.waitFor(() => expect(q('#ic-code')).toBeTruthy());
    expect(post).toHaveBeenCalledWith('/api/media/icloud/sign-in', { apple_id: 'ana@icloud.com', password: 'secret' });
    q('#ic-code').value = '123456';
    q('#ic-verify').click();
    await vi.waitFor(() => expect(q('#ic-start')).toBeTruthy());
    expect(q('.phi-found').textContent).toBe('Signed in as ana@icloud.com.');
    expect(q('#ic-dest').value).toBe('/mnt/user/Photos');
    q('#ic-start').click();
    await vi.waitFor(() => expect(q('#modal-photo-import')).toBeNull());
    expect(post).toHaveBeenLastCalledWith('/api/media/icloud/download', { destination: '/mnt/user/Photos' });
  });

  it('clears a refused password, says why, and asks again after Apple ends the session', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...OUT, apple_id: 'ana@icloud.com', error: 'Apple asks for a new sign-in.' });
    vi.spyOn(api, 'post').mockRejectedValue(new Error("Apple didn't accept that Apple ID and password."));
    await openICloudPhotos('/mnt/user/Photos');
    expect(q('.phi-found').textContent).toBe('Apple asks you to sign in again.');
    expect(q('#ic-id').value).toBe('ana@icloud.com');
    q('#ic-pw').value = 'wrong';
    q('#ic-sign-in').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Apple didn't accept that Apple ID and password.", 'error'));
    expect(q('#ic-pw').value).toBe('');
  });

  it('shows the last download, picks a folder, signs out', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...READY, downloading: true, last_download: { at: 1700000000, imported: 5, duplicates: 2 } });
    vi.spyOn(api, 'delete').mockResolvedValue(OUT);
    await openICloudPhotos('/mnt/user/Photos');
    expect(q('#ic-start').disabled).toBe(true);
    expect(q('#ic-last').textContent).toMatch(/: 5 brought home, 2 already there\.$/);
    window.openFolderBrowser = vi.fn((start, cb) => cb('/mnt/user/Pictures'));
    q('#ic-browse').click();
    expect(q('#ic-dest').value).toBe('/mnt/user/Pictures');
    delete window.openFolderBrowser;
    q('#ic-sign-out').click();
    await vi.waitFor(() => expect(q('#ic-id')).toBeTruthy());
    expect(lastDownloadText(null)).toBe('');
  });

  it('a wrong code keeps the code view; a failed load says why; Esc closes', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...OUT, needs_code: true });
    vi.spyOn(api, 'post').mockRejectedValue(new Error("That code didn't work."));
    await openICloudPhotos('/x');
    q('#ic-code').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("That code didn't work.", 'error'));
    expect(q('#ic-verify').disabled).toBe(false);
    q('#modal-photo-import').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(q('#modal-photo-import')).toBeNull();
    vi.spyOn(api, 'get').mockRejectedValue(new Error('Forbidden'));
    await openICloudPhotos('/x');
    expect(q('#ic-body').textContent).toBe('Forbidden');
    q('#ic-close').click();
    expect(q('#modal-photo-import')).toBeNull();
  });
});
