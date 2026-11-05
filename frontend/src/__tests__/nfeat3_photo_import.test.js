/** NFEAT-3: the "Bring photos home" dialog. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { openPhotoImport, foundText } = await import('../components/photo-import.js');

const q = (s) => document.querySelector(s);
const INFO = { kind: 'google', photos: 1200, videos: 1, bytes: 5 * 1024 ** 3, destination: '/mnt/user/Google Photos' };

describe('bring photos home (NFEAT-3)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('says what the export holds', () => {
    expect(foundText(INFO)).toMatch(/^A Google Photos export: 1,?200 photos and 1 video \(5 GB\)\.$/);
    expect(foundText({ kind: 'icloud', photos: 1, videos: 0, bytes: 10 })).toMatch(/^An iCloud Photos export: 1 photo and 0 videos/);
    expect(foundText({ kind: 'folder', photos: 2, videos: 2, bytes: 0 })).toMatch(/^A folder: 2 photos/);
    expect(foundText({ kind: 'folder', photos: 0, videos: 0 })).toBe('There are no photos or videos in it.');
  });

  it('inspects, offers the destination and starts the job', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(INFO);
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'started', job_id: 'job:1' });
    await openPhotoImport('/mnt/user/Downloads/takeout');
    expect(api.get).toHaveBeenCalledWith('/api/media/photo-import/inspect?path=%2Fmnt%2Fuser%2FDownloads%2Ftakeout');
    expect(q('#phi-found').textContent).toMatch(/^A Google Photos export/);
    expect(q('#phi-dest').value).toBe('/mnt/user/Google Photos');
    q('#phi-dest').value = '/mnt/user/Photos ';
    q('#phi-start').click();
    await vi.waitFor(() => expect(q('#modal-photo-import')).toBeNull());
    expect(post).toHaveBeenCalledWith('/api/media/photo-import', { source: '/mnt/user/Downloads/takeout', destination: '/mnt/user/Photos' });
    expect(showToast).toHaveBeenCalledWith('The import started. You can follow it in Jobs.', 'success');
  });

  it('cannot start on an empty export, says a failure and picks a folder', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ kind: 'folder', photos: 0, videos: 0, destination: '/x' });
    await openPhotoImport('/mnt/user/empty');
    expect(q('#phi-start').disabled).toBe(true);
    window.openFolderBrowser = vi.fn((start, cb) => cb('/mnt/user/Pictures'));
    q('#phi-browse').click();
    expect(q('#phi-dest').value).toBe('/mnt/user/Pictures');
    delete window.openFolderBrowser;
    q('#phi-close').click();
    expect(q('#modal-photo-import')).toBeNull();

    vi.spyOn(api, 'get').mockRejectedValue(new Error('Path is outside the allowed storage folders.'));
    await openPhotoImport('/etc');
    expect(q('#phi-found').textContent).toBe('Path is outside the allowed storage folders.');
    q('#modal-photo-import').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(q('#modal-photo-import')).toBeNull();
  });

  it('keeps the dialog open when the start fails', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(INFO);
    vi.spyOn(api, 'post').mockRejectedValue(new Error('Choose a destination outside the export.'));
    await openPhotoImport('/mnt/user/takeout.zip');
    q('#phi-start').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Choose a destination outside the export.', 'error'));
    expect(q('#phi-start').disabled).toBe(false);
  });
});
