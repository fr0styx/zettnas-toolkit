import { describe, it, expect, vi } from 'vitest';
import { compareTable, sortDrives } from '../components/drive-health-compare.js';

const drives = [
  { dev: 'sda', model: 'Alpha', verdict: 'ok', label_key: 'ok', temp: 31, power_on_hours: 8766, capacity_bytes: 4e12, serial: 'A' },
  { dev: 'sdb', model: 'Beta', verdict: 'soon', label_key: 'soon_replace', temp: 44, power_on_hours: 40000, capacity_bytes: 8e12, serial: 'B' },
  { dev: 'sdc', model: 'Gamma', verdict: 'watch', label_key: 'watch', temp: null, capacity_bytes: 2e12, serial: 'C' },
];
const notes = { A: { warranty_until: '2030-01-01' }, B: { warranty_until: '2027-01-01' } };
const names = (list) => list.map((d) => d.dev);

describe('Drive Health side by side', () => {
  it('sorts worst, hottest, oldest, biggest and soonest-ending first', () => {
    expect(names(sortDrives(drives, notes, 'health'))).toEqual(['sdb', 'sdc', 'sda']);
    expect(names(sortDrives(drives, notes, 'temp'))).toEqual(['sdb', 'sda', 'sdc']);
    expect(names(sortDrives(drives, notes, 'age'))).toEqual(['sdb', 'sda', 'sdc']);
    expect(names(sortDrives(drives, notes, 'size'))).toEqual(['sdb', 'sda', 'sdc']);
    expect(names(sortDrives(drives, notes, 'warranty'))).toEqual(['sdb', 'sda', 'sdc']);
    expect(names(sortDrives(drives, notes, 'name', true))).toEqual(['sdc', 'sdb', 'sda']);
    expect(names(sortDrives(drives, notes, 'nope'))).toEqual(['sdb', 'sdc', 'sda']);
  });

  it('draws the table, sorts on a header and opens a drive', () => {
    const host = document.createElement('div');
    const pick = vi.fn();
    host.append(compareTable(drives, notes, pick));
    const rows = () => [...host.querySelectorAll('tbody tr')].map((r) => r.querySelector('th').textContent);
    expect(rows()[0]).toBe('Beta (sdb)');
    expect(host.querySelector('th[aria-sort="ascending"]').textContent).toBe('Health');
    expect(host.textContent).toContain('Replace soon');
    expect(host.textContent).toContain('44 °C');
    const header = (text) => [...host.querySelectorAll('thead button')].find((b) => b.textContent === text);
    header('Drive').click();
    expect(rows()).toEqual(['Alpha (sda)', 'Beta (sdb)', 'Gamma (sdc)']);
    header('Drive').click();
    expect(host.querySelector('th[aria-sort="descending"]').textContent).toBe('Drive');
    expect(rows()[0]).toBe('Gamma (sdc)');
    host.querySelector('tbody th button').click();
    expect(pick).toHaveBeenCalledWith('sdc');
  });
});
