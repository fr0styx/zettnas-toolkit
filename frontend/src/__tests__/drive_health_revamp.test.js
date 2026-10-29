import { describe, it, expect } from 'vitest';
import { fleetHtml, kindText, aboutHtml, historyBody, scheduleText, reportCsv } from '../components/drive-health.js';
import { scale, lineChart } from '../components/drive-charts.js';

describe('Drive Health revamp', () => {
  it('sums up the fleet', () => {
    const html = fleetHtml([
      { dev: 'sda', capacity_bytes: 4e12, temp: 36, power_on_hours: 17532 },
      { dev: 'sdb', capacity_bytes: 4e12, temp: 41, power_on_hours: 8766, asleep: true },
    ]);
    expect(html).toContain('warmest sdb at 41 °C');
    expect(html).toContain('oldest sda, 2 years on');
    expect(html).toContain('1 asleep');
    expect(fleetHtml([])).toBe('');
  });

  it('names the kind of drive', () => {
    expect(kindText({ protocol: 'nvme' })).toBe('NVMe SSD');
    expect(kindText({ protocol: 'ata', rotation_rpm: 0 })).toBe('SATA SSD');
    expect(kindText({ protocol: 'ata', rotation_rpm: 7200 })).toBe('Hard drive, 7200 rpm');
    expect(kindText({})).toBe('');
  });

  it('describes the drive and its outlook', () => {
    const about = aboutHtml({ protocol: 'nvme', capacity_bytes: 1e12, firmware: 'F1', power_cycles: 9 }, { age_years: 1.5, wear_pct: 12, years_left: 3.6 });
    expect(about).toContain('NVMe SSD');
    expect(about).toContain('F1');
    expect(about).toContain('about 3.6 years left');
    expect(aboutHtml({}, { age_years: 1, wear_pct: 5, years_left: null })).toContain('too little change yet');
    expect(aboutHtml({ rotation_rpm: 5400 }, { age_years: 6.2 })).toContain('five years');
    expect(aboutHtml({}, null)).toContain('read while awake');
  });

  it('draws the history', () => {
    const box = historyBody({
      samples: 3,
      temp: { points: [[1, 30], [2, 33], [3, 31]], min: 30, max: 33, avg: 31.3 },
      counters: { crc_errors: { points: [[1, 0], [2, 2], [3, 6]], first: 0, last: 6 }, pending_sectors: { points: [[1, 2], [3, 2]], first: 2, last: 2 } },
    });
    expect(box.querySelectorAll('svg').length).toBe(3);
    expect(box.textContent).toContain('Temperature: 30–33 °C');
    expect(box.textContent).toContain('Cable transfer errors: rose from 0 to 6');
    expect(box.querySelector('svg.is-rising title').textContent).toContain('rose');
    expect(historyBody({ samples: 2, temp: null, counters: {} }).textContent).toContain('No error counter');
    expect(historyBody(null).textContent).toContain('No readings stored yet');
  });

  it('scales and draws a line', () => {
    expect(scale([], 100, 50)).toEqual([]);
    const pts = scale([[0, 0], [10, 10]], 100, 50, 0);
    expect(pts[0]).toEqual([0, 50]);
    expect(pts[1]).toEqual([100, 0]);
    expect(scale([[5, 3]], 100, 50)[0][0]).toBe(50);
    expect(lineChart([[1, 1]]).querySelector('circle')).not.toBeNull();
    expect(lineChart([[1, 1], [2, 2]], { label: 'x' }).querySelector('path')).not.toBeNull();
  });

  it('says the schedule', () => {
    expect(scheduleText({ enabled: false })).toContain('off');
    expect(scheduleText({ short_test_interval: 'monthly', short_test_hour: 2, long_test_interval: 'disabled' })).toBe('Automatic tests: Short test every month, 02:00. Sleeping drives are skipped.');
    expect(scheduleText(null)).toBe('');
    expect(scheduleText({ short_test_interval: 'disabled', long_test_interval: 'disabled' })).toContain('off');
  });

  it('writes a CSV report', () => {
    const csv = reportCsv([{ dev: 'sda', model: 'WD "Red"', serial: 'S1', verdict: 'watch', label: 'Keep an eye on it', summary: 'x', temp: 35, findings: [{ severity: 'watch', title: 'Timeouts' }, { severity: 'ok', title: 'fine' }] }]);
    const lines = csv.trim().split('\n');
    expect(lines[0]).toContain('"device","model"');
    expect(lines[1]).toContain('"WD ""Red"""');
    expect(lines[1]).toContain('"Timeouts"');
    expect(lines[1]).not.toContain('fine');
  });
});
