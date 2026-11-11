import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { fetchAndRenderUpsTelemetry } from '../components/management/ups.js';

afterEach(() => vi.restoreAllMocks());

const PANE = `<div id="mgmt-sec-ups"><div id="ups-status-line"><span id="ups-status-icon"></span><strong id="ups-status-sentence"></strong>
  <div id="ups-shutdown-line" hidden></div><div id="ups-restart-line" hidden></div><button id="ups-show-setup" hidden></button></div>
  <div id="ups-cockpit-config-section"></div></div>`;

describe('no UPS: one sentence and Set up a UPS (SET-15, Power B1)', () => {
  it('the pane says none and offers set-up; the button shows the rest', async () => {
    document.body.innerHTML = PANE;
    vi.spyOn(api, 'get').mockResolvedValue({ available: false });
    await fetchAndRenderUpsTelemetry();
    const pane = document.getElementById('mgmt-sec-ups');
    expect(pane.dataset.upsState).toBe('none');
    const btn = document.getElementById('ups-show-setup');
    expect(btn.hidden).toBe(false);
    btn.click();
    expect(pane.classList.contains('ups-show-all')).toBe(true);
    expect(btn.hidden).toBe(true);
  });

  it('with a UPS there is no set-up button', async () => {
    document.body.innerHTML = PANE;
    vi.spyOn(api, 'get').mockResolvedValue({ available: true, status: 'OL', battery_charge_pct: 90 });
    await fetchAndRenderUpsTelemetry();
    expect(document.getElementById('ups-show-setup').hidden).toBe(true);
  });
});
