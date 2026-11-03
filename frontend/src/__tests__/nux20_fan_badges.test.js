/** NUX-20: the fan window's zone PWM, hold and driver badges read as translatable words. */
import { describe, it, expect, beforeEach } from 'vitest';
import { updateFanCurveWorkstation } from '../components/fan-control.js';

const text = (id) => document.getElementById(id).textContent;
const FC = { zone1_temp: 35, zone1_pwm: 0, zone2_temp: 36, zone2_pwm: 90, cpu_temp: 50, cpu_pwm: 100 };

describe('fan badges (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = ['zp-z1-pwm', 'zp-z2-pwm', 'zp-cpu-pwm', 'hysteresis-badge', 'fan-status-badge'].map((id) => `<span id="${id}"></span>`).join('');
  });

  it('names passive zones, BIOS control, holds and the driver', () => {
    updateFanCurveWorkstation({ fan_control: { ...FC, zone2_pwm: 0, disk_hold_remaining: 30, driver_mode: 'mmio' } });
    expect(text('zp-z1-pwm')).toBe('PWM: 0 (PASSIVE)');
    expect(text('zp-z2-pwm')).toBe('PWM: 0 (PASSIVE)');
    expect(text('zp-cpu-pwm')).toBe('BIOS Auto');
    expect(text('hysteresis-badge')).toBe('HOLD: ACTIVE (30s)');
    expect(text('fan-status-badge')).toBe('MMIO FALLBACK');
    updateFanCurveWorkstation({ fan_control: { ...FC, ctrl_cpu_fan: true, cpu_hold_remaining: 12, driver_mode: 'hwmon' } });
    expect(text('zp-cpu-pwm')).toBe('PWM: 100');
    expect(text('hysteresis-badge')).toBe('CPU HOLD (12s)');
    expect(text('fan-status-badge')).toBe('KERNEL HWMON');
    updateFanCurveWorkstation({ fan_control: FC });
    expect(text('hysteresis-badge')).toBe('HOLD: READY');
  });
});
