import { describe, it, expect, beforeEach } from 'vitest';
import { pctToY, yToPct, tempToX, xToTemp, updateFanCurveWorkstation } from '../components/fan-control.js';

describe('Fan Curve Coordinate & Deadband Math', () => {
  it('correctly maps percentages to Y coordinates on the SVG canvas', () => {
    // Canvas runs from Y=20 (100%) to Y=104 (0% / Zero RPM base)
    expect(pctToY(100)).toBeCloseTo(20, 1);
    expect(pctToY(0)).toBeCloseTo(104, 1);
    // 32% minimum reliable spin floor
    expect(pctToY(32)).toBeCloseTo(77.12, 1);
  });

  it('correctly snaps deadband percentages from Y coordinates', () => {
    // Y=20 -> 100%
    expect(yToPct(20)).toBe(100);

    // Y=104 -> 0%
    expect(yToPct(104)).toBe(0);

    // Y=77 -> ~32%
    expect(yToPct(77)).toBe(32);

    // Values in deadband (1% to 31%):
    // < 16% snaps to 0% (Zero RPM)
    // >= 16% snaps to 32% (Minimum reliable spin)
    // At Y=95 -> raw pct ~11% -> snaps to 0
    expect(yToPct(95)).toBe(0);
    // At Y=84 -> raw pct ~24% -> snaps to 32
    expect(yToPct(84)).toBe(32);
  });

  it('correctly maps temperatures between 30°C and 60°C to X coordinates', () => {
    expect(tempToX(30)).toBe(38);
    expect(tempToX(60)).toBe(285);
    expect(xToTemp(38)).toBe(30);
    expect(xToTemp(285)).toBe(60);
  });
});

describe('Zero RPM Workstation UI Badges & Readouts', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="zp-z1-temp"></div>
      <div id="zp-z1-pwm"></div>
      <div id="zp-z2-temp"></div>
      <div id="zp-z2-pwm"></div>
      <div id="zp-cpu-temp"></div>
      <div id="zp-cpu-pwm"></div>
      <div id="hysteresis-badge"></div>
      <div id="zero-rpm-badge-z1"></div>
      <div id="zero-rpm-badge-z2"></div>
    `;
  });

  it('displays PASSIVE badge and 0 PWM when fan is stopped in Zero RPM mode', () => {
    const telemetry = {
      fan_control: {
        zone1_temp: 31,
        zone1_pwm: 0,
        zone1_zero_rpm: true,
        zone1_standby: true,
        zone2_temp: 32,
        zone2_pwm: 0,
        zone2_zero_rpm: true,
        zone2_standby: true,
        cpu_temp: 45,
        cpu_pwm: 67,
        ctrl_cpu_fan: true,
        disk_hold_remaining: 0,
        cpu_hold_remaining: 0,
      }
    };

    updateFanCurveWorkstation(telemetry);

    const pwmZ1 = document.getElementById('zp-z1-pwm');
    const badgeZ1 = document.getElementById('zero-rpm-badge-z1');

    expect(pwmZ1.textContent).toBe('PWM: 0 (PASSIVE)');
    expect(badgeZ1.textContent).toBe('Zone 1: PASSIVE (0 RPM)');
  });

  it('displays Active Spinning when disks are active', () => {
    const telemetry = {
      fan_control: {
        zone1_temp: 39,
        zone1_pwm: 75,
        zone1_zero_rpm: false,
        zone1_standby: false,
        zone2_temp: 40,
        zone2_pwm: 80,
        zone2_zero_rpm: false,
        zone2_standby: false,
        cpu_temp: 48,
        cpu_pwm: 85,
        ctrl_cpu_fan: true,
        disk_hold_remaining: 0,
        cpu_hold_remaining: 0,
      }
    };

    updateFanCurveWorkstation(telemetry);

    const pwmZ1 = document.getElementById('zp-z1-pwm');
    const badgeZ1 = document.getElementById('zero-rpm-badge-z1');

    expect(pwmZ1.textContent).toBe('PWM: 75');
    expect(badgeZ1.textContent).toBe('Zone 1: Active Spinning');
  });

  it('displays Standby cooling down during the 180s anti-flutter window', () => {
    const telemetry = {
      fan_control: {
        zone1_temp: 33,
        zone1_pwm: 58,
        zone1_zero_rpm: false,
        zone1_standby: true,
        zone2_temp: 34,
        zone2_pwm: 58,
        zone2_zero_rpm: false,
        zone2_standby: true,
        cpu_temp: 46,
        cpu_pwm: 67,
        ctrl_cpu_fan: true,
        disk_hold_remaining: 0,
        cpu_hold_remaining: 0,
      }
    };

    updateFanCurveWorkstation(telemetry);

    const badgeZ1 = document.getElementById('zero-rpm-badge-z1');
    expect(badgeZ1.textContent).toBe('Zone 1: Standby (Cooling down)');
  });
});
