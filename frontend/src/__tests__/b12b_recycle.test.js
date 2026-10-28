import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn() } }));
const ov = await import('../components/management/overview.js');

describe('B12b (REL-15): the Overview says what the Recycle Bins hold', () => {
  it('shows their size under the protection status, and nothing when they are empty', () => {
    const full = String(ov.protectionHtml({ level: 'good', copies: 1, last_good: 1793091600, recycle_bytes: 5 * 1024 ** 3 }));
    expect(full).toContain('The Recycle Bins hold 5');
    expect(full).toContain('after 30 days');
    expect(String(ov.protectionHtml({ level: 'good', copies: 1, last_good: 1793091600, recycle_bytes: 0 }))).not.toContain('Recycle Bins');
  });
});
