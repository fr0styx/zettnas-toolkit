import { describe, it, expect, afterEach } from 'vitest';
import { applyAdvancedEverywhere, isAdvancedRoute, isAdvancedSection, setPowerMatters } from '../advanced.js';

afterEach(() => setPowerMatters(false));

describe('Power shows with Advanced off when it matters (SET-15, Power decision 2)', () => {
  it('Power is advanced until a UPS is found or the power is out', () => {
    expect(isAdvancedRoute('power')).toBe(true);
    setPowerMatters(true);
    expect(isAdvancedRoute('power')).toBe(false);
    expect(isAdvancedSection('mgmt-sec-ups')).toBe(false);
    expect(isAdvancedRoute('vms')).toBe(true); // the others stay advanced
  });

  it('a hidden Power place comes back, and goes again when it no longer matters', () => {
    document.body.innerHTML = '<div data-advanced-section="mgmt-sec-ups" id="p"></div><div data-advanced-section="mgmt-sec-vms" id="v"></div>';
    applyAdvancedEverywhere(false);
    const p = document.getElementById('p');
    expect(p.hidden).toBe(true);
    setPowerMatters(true);
    applyAdvancedEverywhere(false);
    expect(p.hidden).toBe(false);
    expect(document.getElementById('v').hidden).toBe(true);
    setPowerMatters(false);
    applyAdvancedEverywhere(false);
    expect(p.hidden).toBe(true);
  });
});
