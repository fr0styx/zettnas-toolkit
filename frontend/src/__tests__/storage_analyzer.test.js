import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const { squarify, childrenOf, analysisHtml, openStorageAnalyzer } = await import('../components/storage-analyzer.js');

const RESULT = {
  files: 4, bytes: 8710, complete: true, scanned_at: 1762700000,
  folders: [{ path: 'Movies', bytes: 8000, files: 2 }, { path: 'Movies/Old', bytes: 3000, files: 1 }, { path: 'Photos', bytes: 700, files: 1 }],
  largest: [{ path: 'Movies/a.mkv', bytes: 5000 }],
  kinds: { video: { bytes: 8000, files: 2 }, photo: { bytes: 700, files: 1 }, mystery: { bytes: 10, files: 1 } },
};
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('Storage analyzer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('lays the treemap out to fill the space, biggest first', () => {
    const cells = squarify([{ bytes: 6 }, { bytes: 3 }, { bytes: 1 }, { bytes: 0 }], 0, 0, 100, 100);
    expect(cells).toHaveLength(3);
    const area = cells.reduce((s, c) => s + c.w * c.h, 0);
    expect(Math.round(area)).toBe(10000);
    expect(Math.round(cells[0].w * cells[0].h)).toBe(6000);
    expect(squarify([])).toEqual([]);
  });

  it('shows a folder\'s children and what lies loose beside them', () => {
    expect(childrenOf(RESULT, '').map((c) => c.path)).toEqual(['Movies', 'Photos', '']);
    const movies = childrenOf(RESULT, 'Movies');
    expect(movies.map((c) => [c.path, c.bytes, !!c.loose])).toEqual([['Movies/Old', 3000, false], ['Movies', 5000, true]]);
  });

  it('offers to analyse a share it has not seen, and says when one is running', () => {
    expect(analysisHtml('media', { result: null, running: false })).toContain('data-space-start');
    expect(analysisHtml('media', { result: RESULT, running: true })).toContain('data-space-running');
    const html = analysisHtml('media', { result: { ...RESULT, complete: false }, running: false }, 'Movies');
    expect(html).toContain('Stopped before the end');
    expect(html).toContain('data-space-up');
    expect(html).toContain('Movies/a.mkv');
    expect(html).toContain('space-kind-other'); // an unknown kind is drawn as Other
  });

  it('opens, starts an analysis, drills in and out', async () => {
    api.get.mockResolvedValue({ share: 'media', running: false, result: RESULT });
    await openStorageAnalyzer('media', '/mnt/user/media');
    const modal = document.getElementById('space-modal');
    expect(modal.textContent).toContain('Biggest folders');
    modal.querySelector('[data-space-open="Movies"]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(modal.querySelector('[data-space-up]')).not.toBeNull();
    modal.querySelector('[data-space-up]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(modal.querySelector('[data-space-up]')).toBeNull();
    api.post.mockResolvedValue({ job_id: 'job:1' });
    modal.querySelector('[data-space-start]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(api.post).toHaveBeenCalledWith('/api/storage/analysis', { share: 'media' });
    expect(modal.querySelector('[data-space-running]')).not.toBeNull();
    modal.querySelector('[data-space-close]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(document.getElementById('space-modal')).toBeNull();
  });
});
