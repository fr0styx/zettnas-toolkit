/** NUX-20 / ARC-26: the media organizer's preview and apply, in the reader's language. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showActionToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { setLanguage } = await import('../i18n.js');
const { openMediaOrganizerModal } = await import('../components/file-manager.js');

const byId = (id) => document.getElementById(id);
const ITEMS = [
  { media_type: 'tv', season: 2, episode: 5, title: 'Show', original_filename: 'show.s02e05.mkv', proposed_relative_path: 'TV/Show/S02E05.mkv', resolution: '720p', codec: 'h265' },
  { media_type: 'movie', year: 2020, original_filename: 'film.mkv', proposed_relative_path: 'Movies/Film (2020)/Film.mkv' },
];

describe('media organizer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="modal-media-organizer">
        <button id="modal-media-org-close-btn"></button><button id="modal-media-org-cancel-btn"></button>
        <input id="media-org-source-input"><input id="media-org-dest-input">
        <select id="media-org-mode-select"><option value="hardlink">h</option><option value="move">m</option></select>
        <button id="btn-media-org-preview"></button><div id="media-org-preview-wrap"></div><button id="btn-media-org-apply" disabled></button>
      </div>`;
  });
  afterEach(async () => {
    vi.restoreAllMocks();
    await setLanguage('en');
  });

  it('needs both folders', () => {
    openMediaOrganizerModal();
    expect(byId('media-org-source-input').value).toBe('/mnt/user/downloads');
    byId('media-org-dest-input').value = ' ';
    byId('btn-media-org-preview').click();
    expect(showToast.mock.calls.at(-1)[1]).toBe('warning');
  });

  it('previews what it would sort, then sorts it', async () => {
    openMediaOrganizerModal('/mnt/user/in');
    let release;
    const post = vi.spyOn(api, 'post').mockImplementationOnce(() => new Promise((r) => { release = r; }));
    byId('btn-media-org-preview').click();
    expect(byId('btn-media-org-preview').textContent).toBe('⏳ Analyzing...');
    expect(byId('media-org-preview-wrap').textContent).toContain('Reading the file names');
    release({ items: ITEMS });
    await vi.waitFor(() => expect(byId('btn-media-org-preview').disabled).toBe(false));
    const wrap = byId('media-org-preview-wrap').textContent;
    expect(wrap).toContain('2 files to sort:');
    expect(wrap).toContain('TV show · S02E05');
    expect(wrap).toContain('Movie (2020)');
    expect(byId('btn-media-org-preview').textContent).toBe('🔍 Scan & Preview Diff');
    expect(byId('btn-media-org-apply').disabled).toBe(false);

    post.mockResolvedValueOnce({ processed: 2 });
    byId('media-org-mode-select').value = 'move';
    byId('btn-media-org-apply').click();
    expect(byId('btn-media-org-apply').textContent).toBe('⏳ Organizing...');
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Media sorted: 2 files.', 'success'));
    expect(post.mock.calls.at(-1)[1]).toMatchObject({ action: 'move', hardlink: false });
    expect(byId('btn-media-org-apply').textContent).toBe('Execute Reorganization');
  });

  it('says when there is nothing to sort, and when it fails, in German too', async () => {
    await setLanguage('de');
    openMediaOrganizerModal('/mnt/user/in');
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ items: [] });
    byId('btn-media-org-preview').click();
    await vi.waitFor(() => expect(byId('media-org-preview-wrap').textContent).toContain('keine Videodateien'));
    expect(byId('btn-media-org-apply').disabled).toBe(true);
    post.mockRejectedValueOnce(new Error('kaputt'));
    byId('btn-media-org-preview').click();
    await vi.waitFor(() => expect(byId('media-org-preview-wrap').textContent).toContain('Fehlgeschlagen: kaputt'));

    post.mockResolvedValueOnce({ items: [ITEMS[0]] });
    byId('btn-media-org-preview').click();
    await vi.waitFor(() => expect(byId('media-org-preview-wrap').textContent).toContain('1 Datei zum Einsortieren:'));
    post.mockRejectedValueOnce(new Error('voll'));
    byId('btn-media-org-apply').click();
    await vi.waitFor(() => expect(showToast.mock.calls.at(-1)[1]).toBe('error'));
    post.mockResolvedValueOnce({});
    byId('btn-media-org-apply').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Medien einsortiert: 1 Datei.', 'success'));
  });

  it('closes with its buttons and the backdrop', () => {
    for (const close of [() => byId('modal-media-org-close-btn').click(), () => byId('modal-media-org-cancel-btn').click(), () => byId('modal-media-organizer').click()]) {
      openMediaOrganizerModal();
      close();
      expect(byId('modal-media-organizer').style.display).toBe('none');
    }
  });
});
