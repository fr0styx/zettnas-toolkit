/** NUX-20: the UPS panel's states, shutdown rule summary, discovery and drills read as translatable words. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  renderUpsTelemetry,
  fetchAndRenderUpsEvents,
  updateUpsPolicySummary,
  initUpsDrawerControls,
} from '../components/management/ups.js';
import { api } from '../api.js';
import { showConfirmToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const byId = (id) => document.getElementById(id);
const flush = () => new Promise((r) => setTimeout(r, 10));
const PANEL = `
  <span id="mgmt-hub-ups-pill"></span><span id="mgmt-ups-status"></span><span id="mgmt-ups-model"></span>
  <span id="mgmt-ups-policy"></span><div id="ups-twin-grid-status"></div>
  <div id="ups-emergency-banner"><span id="ups-emergency-countdown"></span></div>`;

describe('UPS panel words (NUX-20)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = PANEL;
  });
  afterEach(() => vi.restoreAllMocks());

  it('names each UPS state', () => {
    renderUpsTelemetry({ permission_error: true });
    expect(byId('mgmt-hub-ups-pill').textContent).toBe('Perm Req');
    expect(byId('mgmt-ups-status').textContent).toBe('Permission Required');

    renderUpsTelemetry({ available: true, on_battery: true, time_left_min: 12 });
    expect(byId('mgmt-hub-ups-pill').textContent).toBe('Active');
    expect(byId('mgmt-ups-status').textContent).toBe('ONLINE');
    expect(byId('mgmt-ups-model').textContent).toBe('Generic UPS');
    expect(byId('mgmt-ups-policy').textContent).toBe('Runtime < 5m');
    expect(byId('ups-twin-grid-status').textContent).toBe('AC Mains Disconnected');
    expect(byId('ups-emergency-countdown').textContent).toBe('~12m remaining');

    renderUpsTelemetry({ available: false, on_battery: true });
    expect(byId('mgmt-hub-ups-pill').textContent).toBe('Offline');
    expect(byId('mgmt-ups-status').textContent).toBe('Offline');
    expect(byId('ups-emergency-countdown').textContent).toBe('ON BATTERY');

    renderUpsTelemetry({ available: true, status: 'OL', battery_charge_pct: 90, model: 'Back-UPS', active_policy: 'battery_pct', line_freq_hz: 50 });
    expect(byId('mgmt-hub-ups-pill').textContent).toBe('90%');
    expect(byId('mgmt-ups-status').textContent).toBe('OL');
    expect(byId('mgmt-ups-policy').textContent).toBe('Policy: battery_pct');
    expect(byId('ups-twin-grid-status').textContent).toBe('50 Hz Nominal');
    renderUpsTelemetry({ available: true });
    expect(byId('ups-twin-grid-status').textContent).toBe('No reading'); // nothing reported: no invented 120 V / 60 Hz (SET-15)

    document.body.innerHTML = '';
    expect(() => renderUpsTelemetry({ available: true, on_battery: true })).not.toThrow();
  });

  it('says when no power events were recorded', async () => {
    document.body.innerHTML = '<table><tbody id="ups-events-tbody"></tbody></table>';
    vi.spyOn(api, 'get').mockResolvedValue({ events: [] });
    await fetchAndRenderUpsEvents();
    expect(byId('ups-events-tbody').textContent).toBe('No power events or brownouts recorded. All power lines normal.');
  });

  it('sums up the shutdown rule', () => {
    document.body.innerHTML = `
      <span id="ups-policy-summary-text"></span>
      <input type="radio" name="ups-policy" value="runtime_left" checked>
      <input type="radio" name="ups-policy" value="battery_pct">
      <input type="radio" name="ups-policy" value="timer">
      <input type="range" id="ups-slider-runtime" value="7"><input type="range" id="ups-slider-battery" value="25">
      <input type="range" id="ups-slider-timer" min="30" max="600" value="120"><input type="checkbox" id="ups-chk-docker">`;
    updateUpsPolicySummary();
    expect(byId('ups-policy-summary-text').textContent).toBe('Active: Estimated Runtime < 7 min');
    document.querySelector('[value="battery_pct"]').checked = true;
    byId('ups-chk-docker').checked = true;
    updateUpsPolicySummary();
    expect(byId('ups-policy-summary-text').textContent).toBe('Active: Battery Charge < 25% · Docker WAL flush');
    document.querySelector('[value="timer"]').checked = true;
    updateUpsPolicySummary();
    expect(byId('ups-policy-summary-text').textContent).toBe('Active: Time on Battery > 120s · Docker WAL flush');
  });

  it('labels discovery results and asks before a drill or self-test', async () => {
    document.body.innerHTML = `
      <button id="btn-ups-discover"></button><div id="ups-discover-candidates"></div>
      <button id="btn-ups-simulate"></button><button id="btn-run-ups-selftest"></button>`;
    vi.spyOn(api, 'get').mockResolvedValue({});
    const post = vi.spyOn(api, 'post').mockResolvedValue({ candidates: [] });
    await initUpsDrawerControls();
    byId('btn-ups-discover').click();
    await flush();
    expect(byId('ups-discover-candidates').textContent).toBe('No active UPS daemons or USB devices detected on local ports.');
    post.mockResolvedValue({ candidates: [{ type: 'nut', host: '10.0.0.5', port: 3493, title: 'Rack UPS' }] });
    byId('btn-ups-discover').click();
    await flush();
    expect(document.querySelector('.ups-discover-item button').textContent).toBe('Apply');

    byId('btn-ups-simulate').click();
    const [title, msg] = showConfirmToast.mock.calls.at(-1);
    expect(title).toBe('Simulate Power Outage Drill?');
    expect(msg).toBe('This pretends the power fails for 15 seconds, so you can see the power diagram, the countdown banner and the event log react. <strong>The server will not shut down.</strong>');
    byId('btn-run-ups-selftest').click();
    expect(showConfirmToast.mock.calls.at(-1)[4]).toMatchObject({ okText: '🔋 Run Self-Test', cancelText: 'Cancel' });
  });
});
