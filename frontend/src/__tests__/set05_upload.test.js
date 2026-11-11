/** SET-05: one upload path; a taken name is asked about, each time, with "for the rest of this upload". */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { uploadAll, uploadUrl, isNameTaken, askNameTaken, planDrop, sendOne, CHUNK_SIZE } from '../components/fm-upload.js';
import { api, ApiError } from '../api.js';
import { showToast } from '../toast.js';
import { transferCenter } from '../components/transfer-center.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
  showActionToast: vi.fn(),
}));

const DIR = '/mnt/user/Docs';
const file = (name, text = 'x') => new File([text], name);
const taken = () => new ApiError('A file named “a.txt” is already there.', { status: 409, error: 'name_taken' });
const ok = { ok: true };
const refused = (status, error, detail) => ({ ok: false, status, statusText: '', json: async () => ({ error, detail }) });
const urls = (spy) => spy.mock.calls.map((c) => c[0].replace('/api/fs/upload?path=%2Fmnt%2Fuser%2FDocs&filename=', ''));

describe('uploads into the File Explorer (SET-05)', () => {
  let postRaw;
  let job;
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    document.body.innerHTML = '';
    postRaw = vi.spyOn(api, 'postRaw').mockResolvedValue(ok);
    job = { progress: vi.fn(), finish: vi.fn() };
    vi.spyOn(transferCenter, 'startLocal').mockReturnValue(job);
  });

  it('asks the server first, so nothing is replaced by an upload', async () => {
    const res = await uploadAll([{ file: file('a.txt'), dir: DIR }]);
    expect(urls(postRaw)).toEqual(['a.txt&on_conflict=ask']);
    expect(res).toEqual({ uploaded: 1, skipped: 0, failed: 0, cancelled: false });
    expect(job.finish).toHaveBeenCalledWith('completed', null);
  });

  it('asks the person each time a name is taken, and sends the answer', async () => {
    postRaw
      .mockResolvedValueOnce(refused(409, 'name_taken', 'A file named “a.txt” is already there.')).mockResolvedValueOnce(ok)
      .mockResolvedValueOnce(refused(409, 'name_taken', 'A file named “b.txt” is already there.')).mockResolvedValueOnce(ok);
    const ask = vi.fn()
      .mockResolvedValueOnce({ choice: 'keep_both', forRest: false })
      .mockResolvedValueOnce({ choice: 'replace', forRest: false });
    const res = await uploadAll([{ file: file('a.txt'), dir: DIR }, { file: file('b.txt'), dir: DIR }], { ask });
    expect(ask.mock.calls).toEqual([['a.txt', DIR], ['b.txt', DIR]]);
    expect(urls(postRaw)).toEqual(['a.txt&on_conflict=ask', 'a.txt&on_conflict=keep_both', 'b.txt&on_conflict=ask', 'b.txt&on_conflict=replace']);
    expect(res.uploaded).toBe(2);
  });

  it('"for the rest of this upload" is asked once', async () => {
    postRaw.mockResolvedValueOnce(refused(409, 'name_taken', 'taken')).mockResolvedValue(ok);
    const ask = vi.fn().mockResolvedValue({ choice: 'replace', forRest: true });
    await uploadAll([{ file: file('a.txt'), dir: DIR }, { file: file('b.txt'), dir: DIR }, { file: file('c.txt'), dir: DIR }], { ask });
    expect(ask).toHaveBeenCalledTimes(1);
    expect(urls(postRaw)).toEqual(['a.txt&on_conflict=ask', 'a.txt&on_conflict=replace', 'b.txt&on_conflict=replace', 'c.txt&on_conflict=replace']);
  });

  it('Skip leaves the file that is there, and "skip the rest" skips only the taken names', async () => {
    postRaw
      .mockResolvedValueOnce(refused(409, 'name_taken', 'taken'))
      .mockResolvedValueOnce(ok)
      .mockResolvedValueOnce(refused(409, 'name_taken', 'taken'));
    const ask = vi.fn().mockResolvedValue({ choice: 'skip', forRest: true });
    const res = await uploadAll([{ file: file('a.txt'), dir: DIR }, { file: file('b.txt'), dir: DIR }, { file: file('c.txt'), dir: DIR }], { ask });
    expect(ask).toHaveBeenCalledTimes(1);
    expect(urls(postRaw)).toEqual(['a.txt&on_conflict=ask', 'b.txt&on_conflict=ask', 'c.txt&on_conflict=ask']);
    expect(res).toEqual({ uploaded: 1, skipped: 2, failed: 0, cancelled: false });
    expect(showToast).toHaveBeenCalledWith('2 files were skipped: their names were taken', 'info');
  });

  it('a failed file is said, and the others still go', async () => {
    postRaw.mockResolvedValueOnce(refused(507, 'error', 'Not enough free space for this file.')).mockResolvedValueOnce(ok);
    const res = await uploadAll([{ file: file('big.iso'), dir: DIR }, { file: file('b.txt'), dir: DIR }]);
    expect(res).toEqual({ uploaded: 1, skipped: 0, failed: 1, cancelled: false });
    expect(showToast.mock.calls[0][0]).toContain('1 file could not be uploaded: big.iso: Not enough free space');
    expect(showToast.mock.calls[0][1]).toBe('error');
    expect(job.finish.mock.calls[0][0]).toBe('completed');
    postRaw.mockResolvedValueOnce(refused(403, 'forbidden', 'No.'));
    await uploadAll([{ file: file('x.txt'), dir: DIR }]);
    expect(job.finish).toHaveBeenLastCalledWith('failed', expect.stringContaining('x.txt'));
  });

  it('Cancel stops after the file in hand', async () => {
    let cancel;
    transferCenter.startLocal.mockImplementation((o) => { cancel = o.cancel; return job; });
    postRaw.mockImplementation(async () => { cancel(); return ok; });
    const res = await uploadAll([{ file: file('a.txt'), dir: DIR }, { file: file('b.txt'), dir: DIR }]);
    expect(postRaw).toHaveBeenCalledTimes(1);
    expect(res.cancelled).toBe(true);
    expect(job.finish).toHaveBeenCalledWith('cancelled');
  });

  it('a large file says its choice when it starts, before any piece is sent', async () => {
    const big = { name: 'film.mkv', size: CHUNK_SIZE + 5, slice: (a, b) => ({ a, b }) };
    const post = vi.spyOn(api, 'post').mockRejectedValueOnce(taken());
    await expect(sendOne(big, DIR, 'ask', () => {}, () => false)).rejects.toSatisfy(isNameTaken);
    expect(postRaw).not.toHaveBeenCalled();
    post.mockResolvedValueOnce({ upload_id: 'u1' }).mockResolvedValueOnce({ status: 'ok' });
    const sent = [];
    await sendOne(big, DIR, 'keep_both', (n) => sent.push(n), () => false);
    expect(post).toHaveBeenCalledWith('/api/fs/upload/init', expect.objectContaining({ filename: 'film.mkv', destination_dir: DIR, on_conflict: 'keep_both' }));
    expect(postRaw).toHaveBeenCalledTimes(2);
    expect(sent).toEqual([CHUNK_SIZE, CHUNK_SIZE + 5]);
    expect(post).toHaveBeenLastCalledWith('/api/fs/upload/complete', { upload_id: 'u1' });
  });

  it('the question has three answers and a tick; Escape skips that one file', async () => {
    const asked = askNameTaken('a.txt', '/mnt/user/Docs/');
    const dialog = document.querySelector('.fm-upload-taken');
    expect(dialog.getAttribute('role')).toBe('dialog');
    expect(dialog.textContent).toContain('“a.txt” is already there');
    expect(dialog.textContent).toContain('already in “Docs”');
    expect([...dialog.querySelectorAll('[data-choice]')].map((b) => b.textContent)).toEqual(['Skip', 'Keep Both', 'Replace']);
    expect(document.activeElement.dataset.choice).toBe('keep_both');
    dialog.querySelector('.fm-upload-for-rest').checked = true;
    dialog.querySelector('[data-choice="replace"]').click();
    expect(await asked).toEqual({ choice: 'replace', forRest: true });
    expect(document.querySelector('.fm-upload-taken')).toBeNull();

    const again = askNameTaken('b.txt', DIR);
    document.querySelector('.fm-upload-taken').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(await again).toEqual({ choice: 'skip', forRest: false });
  });

  it('a dropped folder: its folders first, parents before children, then the files', () => {
    const plan = planDrop([
      { file: file('one.txt'), relPath: 'Trip/Day 1/one.txt' },
      { file: file('two.txt'), relPath: 'Trip/two.txt' },
      { file: file('loose.txt'), relPath: 'loose.txt' },
    ], '/mnt/user/Docs/');
    expect(plan.dirs).toEqual(['/mnt/user/Docs/Trip', '/mnt/user/Docs/Trip/Day 1']);
    expect(plan.items.map((i) => i.dir)).toEqual(['/mnt/user/Docs/Trip/Day 1', '/mnt/user/Docs/Trip', '/mnt/user/Docs']);
  });

  it('the address', () => {
    expect(uploadUrl('/a b', 'c&d')).toBe('/api/fs/upload?path=%2Fa%20b&filename=c%26d');
    expect(uploadUrl('/a', 'b', 'replace')).toBe('/api/fs/upload?path=%2Fa&filename=b&on_conflict=replace');
  });

  it('the File Explorer has one upload path and an Upload button', () => {
    const page = readFileSync(resolve(__dirname, '..', 'components/file-manager.js'), 'utf8');
    expect(page).not.toContain('_uploadFileChunked');
    expect(page.match(/await uploadAll\(/g)).toHaveLength(2);
    expect(page.match(/class="fm-tool-btn fm-upload-btn"/g)).toHaveLength(2);
    expect(page).toContain("this.uploadBtn?.addEventListener('click', () => /** @type {HTMLElement | null} */ (this.uploadInput)?.click());");
  });
});
