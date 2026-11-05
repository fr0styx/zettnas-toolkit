/** ARC-26: choosing and uploading wallpapers (wallpapers.js). */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../management-dom.js', () => ({ onManagementDom: (fn) => fn() }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showPromptToast: vi.fn(), showConfirmToast: vi.fn() }));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const W = await import('../components/wallpapers.js');
const P = await import('../components/wallpaper-pane.js'); // the gallery, loaded with the pane (NUX-15)

const lastToast = () => showToast.mock.calls.at(-1);
const image = (name = 'sky.png', type = 'image/png', size = 10) => {
  const f = new File(['x'.repeat(size)], name, { type });
  return f;
};

describe('wallpapers', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="desktop-wallpaper"></div>
      <select id="wallpaper-select"><option value="">-</option><option value="sky.png">sky</option></select>
      <input id="wallpaper-upload" type="file"><button id="wallpaper-default-btn"></button><button id="wallpaper-clear-btn"></button>
      <button id="wallpaper-rename-btn"></button><div id="wallpaper-gallery-grid"></div>
      <button class="wallpaper-cat-pill active" data-cat="all"></button><button class="wallpaper-cat-pill" data-cat="nature"></button>`;
    vi.spyOn(api, 'get').mockResolvedValue({ wallpapers: [], active: null });
  });

  it('chooses a wallpaper and the theme gradient, and says when saving fails', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    await P.selectWallpaper('sky.png');
    expect(post).toHaveBeenCalledWith('/api/wallpapers/select', { filename: 'sky.png' });
    expect(document.getElementById('wallpaper-select').value).toBe('sky.png');
    expect(lastToast()).toEqual(['Active wallpaper: sky.png', 'success']);
    await P.selectWallpaper('');
    expect(post).toHaveBeenLastCalledWith('/api/wallpapers/select', { filename: null });
    expect(lastToast()[1]).toBe('info');
    post.mockRejectedValue(new Error('x'));
    await P.selectWallpaper('sky.png');
    expect(lastToast()[1]).toBe('error');
    await P.selectWallpaper(null);
    expect(lastToast()[1]).toBe('error');
  });

  it('refuses images that are too big or not images', async () => {
    expect(await P.uploadAndApplyWallpaper(null)).toBe(false);
    const big = image();
    Object.defineProperty(big, 'size', { value: 16 * 1024 * 1024 });
    expect(await P.uploadAndApplyWallpaper(big)).toBe(false);
    expect(lastToast()[0]).toContain('15MB');
    expect(await P.uploadAndApplyWallpaper(image('a.pdf', 'application/pdf'))).toBe(false);
    expect(lastToast()[0]).toContain('Unsupported');
  });

  it('uploads, applies and remembers a new wallpaper', async () => {
    const post = vi.spyOn(api, 'post').mockImplementation(async (url) => (url.endsWith('/upload') ? { success: true, filename: 'sky.png' } : {}));
    const data = await P.uploadAndApplyWallpaper(image());
    expect(data.filename).toBe('sky.png');
    expect(post.mock.calls[0][1].image).toMatch(/^data:image\/png;base64,/);
    expect(localStorage.getItem('zettnas_active_wallpaper')).toBe('sky.png');
    expect(lastToast()).toEqual(['Wallpaper uploaded & applied: sky.png', 'success']);
  });

  it('says why an upload failed', async () => {
    vi.spyOn(api, 'post').mockResolvedValueOnce({ success: false, error: 'disk full' });
    await expect(P.uploadAndApplyWallpaper(image())).rejects.toThrow('disk full');
    expect(lastToast()[0]).toBe('Upload failed: disk full');
    vi.spyOn(api, 'post').mockResolvedValueOnce(null);
    await expect(P.uploadAndApplyWallpaper(image())).rejects.toThrow('Upload error');
    vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('offline'));
    await expect(P.uploadAndApplyWallpaper(image())).rejects.toThrow('offline');
    expect(lastToast()[0]).toBe('Upload failed: offline');
  });

  it('the pane: default, choose from the list, category pills, file picker and drop', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, filename: 'drop.png' });
    W.initWallpapers(); // binds the pane once its module is loaded
    await vi.waitFor(() => {
      document.getElementById('wallpaper-default-btn').click();
      expect(post).toHaveBeenCalledWith('/api/wallpapers/select', { filename: null });
    });

    const sel = document.getElementById('wallpaper-select');
    sel.value = 'sky.png';
    sel.dispatchEvent(new Event('change'));
    sel.value = '';
    sel.dispatchEvent(new Event('change'));
    document.getElementById('wallpaper-clear-btn').click();

    const pills = document.querySelectorAll('.wallpaper-cat-pill');
    pills[1].click();
    expect(pills[1].classList.contains('active')).toBe(true);
    expect(pills[0].classList.contains('active')).toBe(false);

    const grid = document.getElementById('wallpaper-gallery-grid');
    grid.dispatchEvent(new Event('dragover', { cancelable: true }));
    expect(grid.classList.contains('dragover')).toBe(true);
    grid.dispatchEvent(new Event('dragleave'));
    expect(grid.classList.contains('dragover')).toBe(false);
    const drop = new Event('drop', { cancelable: true });
    drop.dataTransfer = { files: [image('drop.png')] };
    grid.dispatchEvent(drop);
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/wallpapers/upload', expect.objectContaining({ filename: 'drop.png' })));

    const input = document.getElementById('wallpaper-upload');
    Object.defineProperty(input, 'files', { value: [image('pick.png')] });
    input.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/wallpapers/upload', expect.objectContaining({ filename: 'pick.png' })));
  });
});
