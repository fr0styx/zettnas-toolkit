import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
const { api } = await import('../api.js');
const { setLanguage } = await import('../i18n.js');

describe('copy and replication history show numbers in the reader\'s language (UX-35)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(async () => {
    await setLanguage('en');
  });

  it('card copy history: size and duration, and -- for a copy with no duration', async () => {
    document.body.innerHTML = "<table><tbody id='copy-history-tbody'></tbody></table>";
    api.get.mockResolvedValue([
      { ts: 1767225600, source: 'sd', dest: '/mnt/user/photos', files_count: 3, total_bytes: 1.5 * 1024 * 1024, duration_sec: 2.25, status: 'success' },
      { ts: 1767225700, source: 'tf', dest: '/mnt/user/clips', files_count: 1, total_bytes: 0, status: 'aborted' },
    ]);
    const { fetchAndRenderCopyHistory } = await import('../components/management/network.js');
    await setLanguage('de');
    await fetchAndRenderCopyHistory();
    const rows = [...document.querySelectorAll('#copy-history-tbody tr')].map((r) => r.textContent.replace(/\s+/g, ' '));
    expect(rows[0]).toContain('1,5 MB');
    expect(rows[0]).toMatch(/2,[23]s/);
    expect(rows[1]).toContain('0,0 MB');
    expect(rows[1]).toContain('--');
  });

  it('replication history: transferred size and duration, -- when missing', async () => {
    document.body.innerHTML = "<table><tbody id='replication-jobs-tbody'></tbody></table><table><tbody id='replication-history-tbody'></tbody></table>";
    api.get.mockImplementation(async (url) =>
      url.endsWith('/jobs')
        ? { jobs: [] }
        : { history: [
          { timestamp: 1767225600, job_id: 'j1', target: 'backup', bytes_transferred: 2.5 * 1024 * 1024, duration_seconds: 12.5, status: 'success' },
          { timestamp: 1767225700, job_id: 'j2', target: 'backup', status: 'failed' },
        ] },
    );
    const { fetchAndRenderReplication } = await import('../components/management/network.js');
    await setLanguage('fr');
    await fetchAndRenderReplication();
    const rows = [...document.querySelectorAll('#replication-history-tbody tr')].map((r) => r.textContent.replace(/\s+/g, ' '));
    expect(rows[0]).toContain('2,5 MB');
    expect(rows[0]).toContain('12,5s');
    expect(rows[1].match(/--/g).length).toBeGreaterThanOrEqual(2);
  });
});
