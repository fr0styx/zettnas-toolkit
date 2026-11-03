/** The AI search result inspector: the photo shows, and its buttons open, download, favourite and share. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showActionToast: vi.fn() }));
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText: vi.fn(async () => {}) }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { copyText } = await import('../utils.js');
const { renderAiPreviewInspector } = await import('../components/management/ai.js');

const byId = (id) => document.getElementById(id);
const PHOTO = { file_id: 7, file_path: '/mnt/user/Photos/beach.jpg', file_name: 'beach.jpg', file_category: 'photos', excerpt: 'sand', also_at: ['/mnt/user/Backup/beach.jpg'] };

describe('AI search inspector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="ai-search-split-layout"></div><div id="ai-preview-inspector-pane"></div>';
  });
  afterEach(() => vi.restoreAllMocks());

  it('shows the photo, where it is, and the other copies', () => {
    renderAiPreviewInspector(PHOTO);
    const img = byId('ai-preview-inspector-pane').querySelector('img');
    expect(img).toBeTruthy();
    expect(img.getAttribute('src')).toBe('/api/media/thumbnail/7');
    expect(byId('ai-preview-inspector-pane').textContent).toContain('/mnt/user/Backup/beach.jpg');
    expect(byId('ai-search-split-layout').style.gridTemplateColumns).toBe('minmax(0, 1fr) 320px');
    byId('btn-ai-inspector-close').click();
    expect(byId('ai-preview-inspector-pane').style.display).toBe('none');
  });

  it('a document has no picture', () => {
    renderAiPreviewInspector({ ...PHOTO, file_category: 'documents', file_name: 'a.pdf' });
    expect(byId('ai-preview-inspector-pane').querySelector('img')).toBeNull();
    renderAiPreviewInspector(null);
  });

  it('downloads and shares through the real download address', async () => {
    renderAiPreviewInspector(PHOTO);
    let href = '';
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () { href = this.getAttribute('href'); });
    byId('btn-ai-inspector-download').click();
    expect(href).toBe('/api/fs/download?path=%2Fmnt%2Fuser%2FPhotos%2Fbeach.jpg');
    byId('btn-ai-inspector-share').click();
    await vi.waitFor(() => expect(copyText).toHaveBeenCalledWith(`${window.location.origin}/api/fs/download?path=%2Fmnt%2Fuser%2FPhotos%2Fbeach.jpg`));
    copyText.mockRejectedValueOnce(new Error('denied'));
    byId('btn-ai-inspector-share').click();
    await vi.waitFor(() => expect(showToast.mock.calls.at(-1)[1]).toBe('info'));
  });

  it('opens the file and its folder', () => {
    window.openFilePreviewModal = vi.fn();
    window.openFileManager = vi.fn();
    renderAiPreviewInspector(PHOTO);
    byId('btn-ai-inspector-open').click();
    expect(window.openFilePreviewModal).toHaveBeenCalledWith('/mnt/user/Photos/beach.jpg', 'beach.jpg', expect.objectContaining({ fileId: 7 }));
    byId('btn-ai-inspector-location').click();
    expect(window.openFileManager).toHaveBeenCalledWith('/mnt/user/Photos');
    delete window.openFilePreviewModal;
    delete window.openFileManager;
  });

  it('favourites and un-favourites, in words', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ is_favorite: true });
    renderAiPreviewInspector({ ...PHOTO });
    byId('btn-ai-inspector-favorite').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Added "beach.jpg" to favorites', 'success'));
    expect(byId('btn-ai-inspector-favorite').textContent).toContain('Favorited');
    post.mockResolvedValueOnce({ is_favorite: false });
    byId('btn-ai-inspector-favorite').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Removed "beach.jpg" from favorites', 'success'));
    post.mockRejectedValueOnce(new Error('offline'));
    byId('btn-ai-inspector-favorite').click();
    await vi.waitFor(() => expect(showToast.mock.calls.at(-1)[1]).toBe('error'));
  });
});
