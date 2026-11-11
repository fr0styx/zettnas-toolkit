// SET-09: one rule for "warm" and "too hot", by the drive's kind, in every place that colours a temperature.
import { describe, it, expect } from 'vitest';
import { LIMITS, isNvmeDrive, tempLevel } from '../components/temp-rule.js';
import { getThermalLevel } from '../components/chassis-visualizer.js';

describe('the temperature rule', () => {
  it('uses the limits the alerts and the fans use', () => {
    expect(LIMITS).toEqual({ hdd: { warm: 50, hot: 55 }, nvme: { warm: 70, hot: 75 } });
    expect([49, 50, 54, 55].map((c) => tempLevel(c))).toEqual(['fine', 'warm', 'warm', 'hot']);
    expect([69, 70, 74, 75].map((c) => tempLevel(c, true))).toEqual(['fine', 'warm', 'warm', 'hot']);
    expect(tempLevel(null)).toBe('unknown');
    expect(tempLevel('x')).toBe('unknown');
  });

  it('knows an NVMe drive from any of the server\'s records', () => {
    expect(isNvmeDrive({ is_nvme: true })).toBe(true);
    expect(isNvmeDrive({ dev: 'nvme0n1' })).toBe(true);
    expect(isNvmeDrive({ name: 'nv0' })).toBe(true);
    expect(isNvmeDrive({ device: 'sda' })).toBe(false);
    expect(isNvmeDrive(null)).toBe(false);
  });

  it('the bay picture follows it: a hard drive at 48 °C is fine, an NVMe at 60 °C too', () => {
    expect(getThermalLevel(48).cls).toBe('ok'); // it was amber from 46 °C, for every drive
    expect(getThermalLevel(52).cls).toBe('warn');
    expect(getThermalLevel(55).cls).toBe('crit');
    expect(getThermalLevel(60, false, true).cls).toBe('ok'); // it was red from 53 °C
    expect(getThermalLevel(72, false, true).cls).toBe('warn');
    expect(getThermalLevel(76, false, true).cls).toBe('crit');
  });
});
