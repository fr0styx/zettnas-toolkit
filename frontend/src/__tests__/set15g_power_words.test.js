import { describe, it, expect } from 'vitest';
import { renderUpsTelemetry } from '../components/management/ups.js';

describe('on battery is said, not only coloured (SET-15, Power B10)', () => {
  it('the Overview pill and the sidebar badge carry an icon and words', () => {
    document.body.innerHTML = '<span id="mgmt-hub-ups-pill"></span><span id="mgmt-sidebar-ups-badge"></span>';
    renderUpsTelemetry({ available: true, on_battery: true, status: 'OB', battery_charge_pct: 64, time_left_min: 20 });
    const pill = document.getElementById('mgmt-hub-ups-pill');
    expect(pill.textContent).toBe('⚡ 64%');
    expect(pill.getAttribute('aria-label')).toMatch(/^Power cut/);
    expect(document.getElementById('mgmt-sidebar-ups-badge').title).toMatch(/^Power cut/);
  });

  it('no UPS is "No UPS", not "Offline"', () => {
    document.body.innerHTML = '<span id="mgmt-hub-ups-pill"></span>';
    renderUpsTelemetry({ available: false });
    expect(document.getElementById('mgmt-hub-ups-pill').textContent).toBe('No UPS');
  });
});
