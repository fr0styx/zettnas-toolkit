import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { findingHtml, serialOf, ackFinding, _test } from '../components/drive-health.js';
import { driveReportText } from '../components/drive-health-report.js';

afterEach(() => {
  vi.restoreAllMocks();
  _test.reset();
});

const watch = { code: 'crc_errors', severity: 'watch', title: 'Cable errors', detail: '3 errors', action: 'Check the cable', params: { n: 3 } };

describe('Drive Health acknowledgements', () => {
  it('offers "I know about this" only on findings to watch or plan for', () => {
    expect(findingHtml(watch, true)).toContain('data-dh-ack="crc_errors"');
    expect(findingHtml(watch, false)).not.toContain('data-dh-ack');
    expect(findingHtml({ ...watch, severity: 'now' }, true)).not.toContain('data-dh-ack');
  });

  it('shows what was acknowledged, with its undo', () => {
    const html = findingHtml({ ...watch, severity: 'ok', acknowledged: { at: 1700000000, severity: 'watch' } }, true);
    expect(html).toContain('is-acked');
    expect(html).toContain('You acknowledged this on');
    expect(html).toContain('data-dh-unack="crc_errors"');
    expect(html).not.toContain('data-dh-ack=');
  });

  it('knows a sleeping drive by its listed serial', () => {
    expect(serialOf({ serial: 'S1' }, { serial: 'Hidden while in standby' })).toBe('S1');
    expect(serialOf({ serial: 'S1' }, { serial: 'S2' })).toBe('S2');
    expect(serialOf({}, null)).toBe('');
  });

  it('sends the finding and reloads', async () => {
    _test.setCurrent({ serial: 'S1', drive: { dev: 'sdb', findings: [watch] }, detail: null });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ fingerprint: 'x' });
    const get = vi.spyOn(api, 'get').mockResolvedValue({ drives: [], notes: {} });
    await ackFinding('crc_errors', true);
    expect(post).toHaveBeenCalledWith('/api/drives/acks', { serial: 'S1', code: 'crc_errors', params: { n: 3 }, severity: 'watch', title: 'Cable errors' });
    expect(get).toHaveBeenCalledWith('/api/drives/health');
    await ackFinding('crc_errors', false);
    expect(post).toHaveBeenLastCalledWith('/api/drives/acks/forget', { serial: 'S1', code: 'crc_errors' });
    await ackFinding('nothing', true);
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('says so when it fails', async () => {
    _test.setCurrent({ serial: 'S1', drive: { dev: 'sdb', findings: [watch] }, detail: null });
    vi.spyOn(api, 'post').mockRejectedValue(new Error('denied'));
    await expect(ackFinding('crc_errors', true)).resolves.toBeUndefined();
  });

  it('lists acknowledged findings in the full report', () => {
    const text = driveReportText({ drive: { dev: 'sdb' }, detail: { drive_health: { verdict: 'ok', findings: [{ ...watch, severity: 'ok', acknowledged: { at: 1700000000 } }] } } });
    expect(text).toContain('Cable errors (acknowledged');
  });
});
