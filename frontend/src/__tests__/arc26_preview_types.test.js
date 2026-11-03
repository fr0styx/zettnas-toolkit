/** The preview window for each kind of file, with its line in the reader's language. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const { setLanguage } = await import('../i18n.js');
const { openFilePreviewModal, closeFilePreviewModal } = await import('../components/file-preview-modal.js');

const q = (s) => document.querySelector(s);
const meta = () => q('#quicklook-meta').textContent;
async function open(name, reply) {
  vi.spyOn(api, 'get').mockImplementation(async () => (reply instanceof Error ? Promise.reject(reply) : { status: 'ok', name, size: 2048, ...reply }));
  await openFilePreviewModal(`/mnt/user/docs/${name}`, name);
  await vi.waitFor(() => expect(meta()).not.toMatch(/^Loading/));
}

describe('preview by file type', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  afterEach(async () => {
    closeFilePreviewModal();
    vi.restoreAllMocks();
    await setLanguage('en');
  });

  it('plain text with its line count, also cut off', async () => {
    await open('notes.txt', { type: 'text', content: '<b>hi</b>', lines_count: 1 });
    expect(meta()).toMatch(/^1 line/);
    expect(q('.quicklook-code').textContent).toBe('<b>hi</b>');
    closeFilePreviewModal();
    await open('big.log', { type: 'text', content: 'x', lines_count: 1200, truncated: true });
    expect(meta()).toMatch(/^1,?200 lines.*\(first 64 KB\)$/);
  });

  it('counts lines in German', async () => {
    await setLanguage('de');
    await open('notiz.txt', { type: 'text', content: 'a\nb', lines_count: 2 });
    expect(meta()).toMatch(/^2 Zeilen/);
  });

  it('Markdown is rendered, PDF framed, hex dumped, others explained', async () => {
    await open('readme.md', { type: 'text', content: '# Title\n\n<script>x()</script>', lines_count: 3 });
    expect(q('.quicklook-markdown h1').textContent).toBe('Title');
    expect(q('.quicklook-markdown script')).toBeNull();
    closeFilePreviewModal();
    await open('manual.pdf', { type: 'pdf' });
    expect(q('#quicklook-body iframe').getAttribute('src')).toBe('/api/fs/download?path=%2Fmnt%2Fuser%2Fdocs%2Fmanual.pdf');
    closeFilePreviewModal();
    await open('blob.bin', { type: 'hex', hex_dump: ['00 01', '02 03'] });
    expect(q('.quicklook-hex').textContent).toBe('00 01\n02 03');
    closeFilePreviewModal();
    await open('archive.xyz', { type: 'binary' });
    expect(q('#quicklook-body').textContent).toContain('There is no preview for this kind of file.');
  });

  it('says why a preview failed', async () => {
    await open('gone.txt', new Error('File not found'));
    expect(meta()).toBe('Preview error');
    expect(q('#quicklook-body').textContent).toContain('File not found');
  });

  it('audio and video say what they are', async () => {
    await open('song.mp3', { type: 'media', ext: '.mp3' });
    expect(meta()).toMatch(/^Audio/);
    expect(q('.quicklook-audio')).toBeTruthy();
    closeFilePreviewModal();
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.includes('info') || url.includes('probe') || url.includes('media')
        ? { video: { width: 1920, height: 1080, codec: 'h264' }, container: 'mp4', duration: 90 }
        : { status: 'ok', type: 'media', ext: '.mp4', name: 'clip.mp4', size: 2048 },
    );
    await openFilePreviewModal('/mnt/user/docs/clip.mp4', 'clip.mp4');
    await vi.waitFor(() => expect(meta()).toMatch(/^Video.*1920×1080/));
    await setLanguage('de');
    closeFilePreviewModal();
    await openFilePreviewModal('/mnt/user/docs/clip.mp4', 'clip.mp4');
    await vi.waitFor(() => expect(meta()).toMatch(/^Video.*1920×1080/));
  });
});
