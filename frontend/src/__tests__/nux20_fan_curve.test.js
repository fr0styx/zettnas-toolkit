/** NUX-20: the fan curve window's standby reasons, zone filter and readouts read as plain, translatable words. */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { standbyReason, setZoneFilter, updateFanCurveWorkstation } from '../components/fan-control.js';
import { state } from '../state.js';

const FC = { zone1_temp: 38, zone1_pwm: 90, zone2_temp: 41, zone2_pwm: 100, cpu_temp: 52, cpu_pwm: 120 };

describe('fan curve words (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="curve-filter-instruction"></div><div id="curve-readout-text"></div>
      <span id="zero-rpm-badge-z1"></span><span id="zero-rpm-badge-z2"></span>`;
  });
  afterEach(() => {
    state.setZoneFilter('all');
  });

  it('says why a zone waits in standby', () => {
    expect(standbyReason({ storage_busy: true })).toBe('Storage busy');
    expect(standbyReason({ nvme_over_ceiling: true })).toBe('NVMe cooling');
    expect(standbyReason({}, 30)).toBe('Cooling down 30s');
    expect(standbyReason({}, 0)).toBe('Cooling down');
    expect(standbyReason({})).toBe('Cooling down');
    updateFanCurveWorkstation({ fan_control: { ...FC, zone1_standby: true, zone2_standby: true, storage_busy: true } });
    expect(document.getElementById('zero-rpm-badge-z1').textContent).toBe('Zone 1: Standby (Storage busy)');
    expect(document.getElementById('zero-rpm-badge-z2').textContent).toBe('Zone 2: Standby (Storage busy)');
  });

  it('names the zone the graph is filtered to and reads out its temperature', () => {
    const readout = () => document.getElementById('curve-readout-text').textContent;
    const note = () => document.getElementById('curve-filter-instruction').textContent;
    setZoneFilter('zone1');
    expect(note()).toBe('Showing Zone 1 (left bays) only. The other zones are hidden on the graph.');
    updateFanCurveWorkstation({ fan_control: FC });
    expect(readout()).toBe('Zone 1 only: 38°C (90 PWM)');
    setZoneFilter('zone2');
    updateFanCurveWorkstation({ fan_control: FC });
    expect(readout()).toBe('Zone 2 only: 41°C (100 PWM)');
    setZoneFilter('cpu');
    expect(note()).toContain('CPU package');
    updateFanCurveWorkstation({ fan_control: FC });
    expect(readout()).toBe('CPU only: 52°C (120 PWM)');
    updateFanCurveWorkstation({ fan_control: { ...FC, cpu_pwm: 0 } });
    expect(readout()).toBe('CPU only: 52°C (Auto PWM)');
    setZoneFilter('all');
    updateFanCurveWorkstation({ fan_control: FC });
    expect(readout()).toBe('All zones: hottest bay 41°C');
  });
});
