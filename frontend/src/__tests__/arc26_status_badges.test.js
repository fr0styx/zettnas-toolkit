/** NUX-20: the layout preset badge and the fan's manual label in the reader's language. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(async (url) => (url === '/api/fans' ? { profile: 'manual', manual_pct: 70 } : {})), post: vi.fn(async () => ({})) } }));

const { setLanguage } = await import('../i18n.js');
const { state, defaultVis } = await import('../state.js');
const { evaluateActivePreset } = await import('../components/mini-preview.js');
const { initFanControl } = await import('../components/fan-control.js');

describe('status badges', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('names the layout preset, or Custom', async () => {
    document.body.innerHTML = '<span id="preset-state-badge"></span>';
    state.dashVis = { ...defaultVis };
    evaluateActivePreset();
    expect(document.getElementById('preset-state-badge').textContent).toBe('DEFAULT');
    state.dashVis = { 'metric-storage': false, 'metric-cpu': true, 'metric-mem': false, 'metric-fans': true, 'metric-net': false, 'metric-disks': true };
    evaluateActivePreset();
    expect(document.getElementById('preset-state-badge').textContent).toBe('THERMAL');
    state.dashVis = { ...defaultVis, 'metric-cpu': !defaultVis['metric-cpu'], 'metric-net': !defaultVis['metric-net'] };
    await setLanguage('de');
    evaluateActivePreset();
    expect(document.getElementById('preset-state-badge').textContent).toBe('EIGENE');
  });

  it('shows the manual fan speed', async () => {
    document.body.innerHTML = '<span id="fan-pwm-val-display"></span>';
    initFanControl();
    await vi.waitFor(() => expect(document.getElementById('fan-pwm-val-display').textContent).toBe('70% (Manual Active)'));
  });
});
