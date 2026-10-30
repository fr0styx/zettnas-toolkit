import { describe, it, expect, vi } from 'vitest';

vi.mock('../i18n.js', () => ({
  t: (key, fallback, params = {}) => String(fallback)
    .replace(/\{(\w+), plural, one \{([^}]*)\} other \{([^}]*)\}\}/g, (m, k, one, other) => (params[k] === 1 ? one : other).replace('#', params[k]))
    .replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)),
}));
const confirm = vi.fn();
vi.mock('../toast.js', () => ({ showConfirmToast: (...a) => confirm(...a), showToast: vi.fn() }));
vi.mock('../api.js', () => ({ api: { get: vi.fn(), delete: vi.fn(async () => ({})), post: vi.fn(), put: vi.fn() } }));

const { previewText, deletionsList } = await import('../components/two-way-sync.js');

describe('two-way sync approval (NUX-23)', () => {
  it('reads the first run as one sentence', () => {
    expect(previewText({ ok: true, first_run: true, to_remote: 2, to_local: 0 })).toBe('First run, copies only: 2 files to the cloud · 0 files to this NAS');
  });

  it('lists the files a run would delete, each side named', () => {
    const box = deletionsList({ delete_remote: 3, delete_local: 1, files: { delete_remote: ['a.txt', 'b.txt'], delete_local: ['c.txt'] } });
    expect(box.querySelector('summary').textContent).toBe('Show what would be deleted (4 files)');
    const items = [...box.querySelectorAll('li')].map((li) => li.textContent);
    expect(items).toEqual(['In the cloud: a.txt', 'In the cloud: b.txt', 'On this NAS: c.txt', '…and 1 more']);
    expect(deletionsList({ files: {} })).toBeNull();
    expect(deletionsList(null)).toBeNull();
  });
});
