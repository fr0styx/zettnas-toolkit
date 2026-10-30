import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { prettyName, valueRows, valuesTable, takenOutBox } from '../components/drive-health-values.js';
import { notesRows } from '../components/drive-health-report.js';
import { forgetRetired, _test } from '../components/drive-health.js';

afterEach(() => {
  vi.restoreAllMocks();
  _test.reset();
});

const attrs = {
  '197': { name: 'Current_Pending_Sector', value: 100, worst: 100, thresh: 0, raw: 4, points: [[1, 0], [2, 4]], values: [] },
  '9': { name: 'Power_On_Hours', value: 80, worst: 80, thresh: 0, raw: 900, points: [[1, 900], [2, 900]], values: [] },
  '3': { name: 'Spin_Up_Time', value: 20, worst: 20, thresh: 21, raw: 0, points: [[1, 0]], values: [] },
  'nvme.media_errors': { name: 'media_errors', value: null, worst: null, thresh: null, raw: 0, points: [[1, 0]], values: [] },
};

describe('Drive Health: every value', () => {
  it('names and orders the values and marks what matters', () => {
    expect(prettyName('Current_Pending_Sector')).toBe('Current pending sector');
    expect(prettyName('')).toBe('');
    const rows = valueRows(attrs);
    expect(rows.map((r) => r.attr)).toEqual(['3', '9', '197', 'nvme.media_errors']);
    expect(rows.find((r) => r.attr === '197').rose).toBe(true);
    expect(rows.find((r) => r.attr === '9').moved).toBe(false);
    expect(rows.find((r) => r.attr === '3').low).toBe(true);
  });

  it('draws the table with a chart where a value moved', () => {
    const box = valuesTable(attrs);
    expect(box.querySelectorAll('tbody tr').length).toBe(4);
    expect(box.querySelectorAll('tr.is-rising').length).toBe(2);
    expect(box.querySelectorAll('svg').length).toBe(1);
    expect(box.textContent).toContain('Current pending sector');
    expect(valuesTable({}).textContent).toContain('read while awake');
  });
});

describe('Drive Health: drives taken out', () => {
  it('lists them with their record and forgets one', () => {
    const forget = vi.fn();
    const box = takenOutBox([{ serial: 'S1', model: 'Old Red', capacity_bytes: 2e12, label_key: 'watch', label: 'Keep an eye on it', last_seen: 1700000000 }], { S1: { warranty_until: '2020-01-01' } }, forget);
    expect(box.querySelector('summary').textContent).toBe('Taken out (1)');
    expect(box.textContent).toContain('Old Red');
    expect(box.textContent).toContain('Ended 2020-01-01');
    box.querySelector('button').click();
    expect(forget).toHaveBeenCalledWith('S1');
    expect(takenOutBox([], {}, forget).hidden).toBe(true);
  });

  it('asks the server to forget it', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ forgotten: true });
    await forgetRetired('S1');
    expect(post).toHaveBeenCalledWith('/api/drives/retired/forget', { serial: 'S1' });
    post.mockRejectedValue(new Error('no'));
    await expect(forgetRetired('S1')).resolves.toBeUndefined();
  });

  it("shows a drive's own temperature limit", () => {
    expect(notesRows({ temp_limit: 55 })).toEqual([['Warm above', '55 °C']]);
  });
});
