import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const dup = await import('../components/management/duplicates.js');

const DATA = {
  total_groups: 2,
  wasted_bytes: 3_000_000,
  groups: [
    {
      kind: 'photo',
      wasted_bytes: 2_000_000,
      files: [
        { file_id: 1, path: '/mnt/user/photos/2024/beach.jpg', name: 'beach.jpg', size: 2_000_000 },
        { file_id: 2, path: '/mnt/user/backup/beach.jpg', name: 'beach.jpg', size: 2_000_000 },
      ],
    },
    {
      kind: 'file',
      wasted_bytes: 1_000_000,
      files: [
        { file_id: 3, path: '/mnt/user/docs/a.pdf', name: 'a.pdf', size: 500_000 },
        { file_id: 4, path: '/mnt/user/docs/old/a.pdf', name: 'a.pdf', size: 500_000 },
        { file_id: 5, path: '/mnt/user/docs/old2/a.pdf', name: 'a.pdf', size: 500_000 },
      ],
    },
  ],
};

describe('AI-35: the duplicate view', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dup._reset();
    document.body.innerHTML = '<div><select id="ai-search-sort-select"></select></div><div id="ai-doc-filters"></div>';
  });

  it('puts a button after the filters that says how much copies take', async () => {
    api.get.mockResolvedValue(DATA);
    await dup.installDuplicatesButton(document);
    const btn = document.getElementById('ai-duplicates-btn');
    expect(btn.previousElementSibling.id).toBe('ai-doc-filters');
    expect(btn.textContent).toContain('Duplicates');
    expect(btn.textContent).toMatch(/2\.9 MB/);
    await dup.installDuplicatesButton(document);
    expect(document.querySelectorAll('#ai-duplicates-btn').length).toBe(1);
  });

  it('lists each set with photo thumbnails and where every copy is', async () => {
    api.get.mockResolvedValue(DATA);
    const host = await dup.openDuplicates();
    expect(host.classList.contains('open')).toBe(true);
    expect(host.querySelector('.smart-modal-window .os-window-controls [data-close]')).not.toBeNull();
    expect(host.textContent).toContain('2 sets of copies');
    expect(host.textContent).toContain('Photos that look the same');
    expect(host.textContent).toContain('/mnt/user/backup');
    expect([...host.querySelectorAll('img.dup-thumb')].map((i) => i.getAttribute('src'))).toEqual(['/api/media/thumbnail/1', '/api/media/thumbnail/2']);
    expect(host.querySelectorAll('[data-dup-bin]').length).toBe(5);
  });

  it('moves a copy to the recycle bin after asking, and keeps the last copy', async () => {
    api.get.mockResolvedValue(DATA);
    api.post.mockResolvedValue({ status: 'ok' });
    const host = await dup.openDuplicates();
    host.querySelector('[data-dup-bin="/mnt/user/backup/beach.jpg"]').click();
    expect(toast.showConfirmToast).toHaveBeenCalledTimes(1);
    expect(api.post).not.toHaveBeenCalled();
    await toast.showConfirmToast.mock.calls[0][2]();
    expect(api.post).toHaveBeenCalledWith('/api/fs/delete', { path: '/mnt/user/backup/beach.jpg' });
    expect(host.textContent).not.toContain('Photos that look the same'); // one left: no longer a set
    expect(host.textContent).toContain('1 set of copies');
    expect(toast.showToast).toHaveBeenCalledWith('Moved to the recycle bin', 'success');
  });

  it('a set of three keeps two after one goes, and its waste shrinks', () => {
    const out = dup.dropFile(DATA, '/mnt/user/docs/old2/a.pdf');
    expect(out.groups[1].files.length).toBe(2);
    expect(out.groups[1].wasted_bytes).toBe(500_000);
    expect(out.total_groups).toBe(2);
    expect(dup.dropFile(null, 'x')).toBeNull();
  });

  it('says so when nothing is duplicated, and when loading fails', async () => {
    api.get.mockResolvedValue({ groups: [], total_groups: 0, wasted_bytes: 0 });
    let host = await dup.openDuplicates();
    expect(host.textContent).toContain('No duplicates found');
    api.get.mockRejectedValue(new Error('down'));
    host = await dup.openDuplicates();
    expect(host.textContent).toContain("Couldn't load the duplicates.");
  });

  it('tells you when a move fails and leaves the list as it was', async () => {
    api.get.mockResolvedValue(DATA);
    api.post.mockRejectedValue(new Error('read-only'));
    const host = await dup.openDuplicates();
    host.querySelector('[data-dup-bin]').click();
    await toast.showConfirmToast.mock.calls[0][2]();
    expect(toast.showToast).toHaveBeenCalledWith("Couldn't move it: read-only");
    expect(host.querySelectorAll('[data-dup-bin]').length).toBe(5);
    host.querySelector('[data-close]').click();
    expect(host.classList.contains('open')).toBe(false);
  });

  it('shows when only the largest sets are listed', () => {
    expect(String(dup.duplicatesHtml({ ...DATA, total_groups: 40 }))).toContain('Showing the 2 largest of 40.');
  });
});
