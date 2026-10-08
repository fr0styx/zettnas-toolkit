import { describe, it, expect, beforeEach } from 'vitest';
import { pctToY, yToPct, tempToX, xToTemp, updateFanCurveWorkstation, expandTo6Points, renderCurveLines } from '../components/fan-control.js';
import { state } from '../state.js';

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

  it('correctly maps granular temperatures (30°C to 60°C+) across the 5 positions', () => {
    // 5 positions across 30°C to 60°C+:
    // 30°C (start) -> X=38
    expect(tempToX(30)).toBe(38);
    // 37.5°C (quarter step) -> X=99.75 ~ 100
    expect(tempToX(37.5)).toBeCloseTo(99.75, 1);
    // 45°C (halfway) -> X=161.5 ~ 161
    expect(tempToX(45)).toBeCloseTo(161.5, 1);
    // 52.5°C (three-quarter step) -> X=223.25 ~ 223
    expect(tempToX(52.5)).toBeCloseTo(223.25, 1);
    // 60°C+ (max right edge) -> X=285
    expect(tempToX(60)).toBe(285);
    // Clamp checks
    expect(tempToX(75)).toBe(285);
    expect(tempToX(20)).toBe(38);
  });

  it('correctly maps 51°C CPU temperature to SVG X coordinates (X ~ 210.9)', () => {
    // 51°C must be at 38 + ((51-30)/30) * 247 = 210.9px (previously was bugged at ~132.3px)
    const cpuX = tempToX(51);
    expect(cpuX).toBeCloseTo(210.9, 1);
    expect(cpuX).toBeGreaterThan(tempToX(45));
    expect(cpuX).toBeLessThan(tempToX(52.5));
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
      <svg>
        <circle id="curve-dot-z1" cx="0" cy="0" />
        <circle id="curve-dot-z2" cx="0" cy="0" />
        <circle id="curve-dot-cpu" cx="0" cy="0" />
      </svg>
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

  it('positions SVG thermal dots (curve-dot-cpu, curve-dot-z1, curve-dot-z2) accurately using tempToX', () => {
    const telemetry = {
      fan_control: {
        zone1_temp: 36,
        zone1_pwm: 60,
        zone2_temp: 42,
        zone2_pwm: 110,
        cpu_temp: 51,
        cpu_pwm: 85,
        ctrl_cpu_fan: true,
        disk_hold_remaining: 0,
        cpu_hold_remaining: 0,
      }
    };

    updateFanCurveWorkstation(telemetry);

    const dotCpu = document.getElementById('curve-dot-cpu');
    const dotZ1 = document.getElementById('curve-dot-z1');
    const dotZ2 = document.getElementById('curve-dot-z2');

    // 51°C CPU temperature maps accurately to ~210.9px on the 30°C-60°C canvas
    expect(Number(dotCpu.getAttribute('cx'))).toBeCloseTo(tempToX(51), 1);
    expect(Number(dotCpu.getAttribute('cx'))).toBeCloseTo(210.9, 1);
    expect(Number(dotZ1.getAttribute('cx'))).toBeCloseTo(tempToX(36), 1);
    expect(Number(dotZ2.getAttribute('cx'))).toBeCloseTo(tempToX(42), 1);
  });
});

describe('6-Point Dynamic Fan Curve Handles & Expansion', () => {
  it('expands a 4-point curve into exactly 6 monotonic points without distorting geometry', () => {
    const original4 = [[30, 0], [38, 32], [51, 69], [60, 100]];
    const expanded6 = expandTo6Points(original4);

    expect(expanded6).toHaveLength(6);
    // Boundary anchors preserved
    expect(expanded6[0]).toEqual([30, 0]);
    expect(expanded6[5]).toEqual([60, 100]);

    // Strictly monotonic temperatures
    for (let i = 0; i < expanded6.length - 1; i++) {
      expect(expanded6[i + 1][0]).toBeGreaterThan(expanded6[i][0]);
      expect(expanded6[i + 1][1]).toBeGreaterThanOrEqual(expanded6[i][1]);
    }
  });

  it('keeps an existing 6-point curve unchanged', () => {
    const existing6 = [[30, 0], [36, 32], [42, 48], [48, 65], [54, 85], [60, 100]];
    const result = expandTo6Points(existing6);
    expect(result).toEqual(existing6);
  });

  it('positions all 6 SVG handles (ch-0 through ch-5) on the canvas', () => {
    document.body.innerHTML = `
      <svg class="fan-curve-svg">
        <path id="curve-svg-path" d="" />
        <path id="curve-area-path" d="" />
        <circle class="curve-handle" id="ch-0" cx="0" cy="0" />
        <circle class="curve-handle" id="ch-1" cx="0" cy="0" />
        <circle class="curve-handle" id="ch-2" cx="0" cy="0" />
        <circle class="curve-handle" id="ch-3" cx="0" cy="0" />
        <circle class="curve-handle" id="ch-4" cx="0" cy="0" />
        <circle class="curve-handle" id="ch-5" cx="0" cy="0" />
      </svg>
    `;

    const pts6 = [[30, 0], [36, 32], [42, 48], [48, 65], [54, 85], [60, 100]];
    state.setCurvePoints(pts6);
    renderCurveLines();

    for (let i = 0; i < 6; i++) {
      const handle = document.getElementById(`ch-${i}`);
      expect(handle).not.toBeNull();
      expect(handle.style.display).not.toBe('none');
      expect(Number(handle.getAttribute('cx'))).toBeCloseTo(tempToX(pts6[i][0]), 1);
      expect(Number(handle.getAttribute('cy'))).toBeCloseTo(pctToY(pts6[i][1]), 1);
    }
  });
});
