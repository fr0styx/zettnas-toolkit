import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { api } from '../api.js';
import { initAcousticCalibration } from '../components/fan-control.js';

describe('Acoustic Resonance Fan Calibration Frontend Suite', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="fan-card-acoustic" data-fan-card-id="fan-card-acoustic">
        <span id="acoustic-sweep-badge" class="suite-badge">READY</span>
        <button id="btn-start-acoustic-sweep" type="button">Start</button>
        <button id="btn-stop-acoustic-sweep" type="button" style="display:none;">Stop</button>
        <span id="acoustic-sweep-status">Idle</span>
        <span id="acoustic-current-step">Step --/--</span>
        <div id="acoustic-progress-bar-wrap" style="display:none;">
          <div id="acoustic-progress-bar" style="width:0%;"></div>
        </div>
        <svg id="acoustic-chart-svg">
          <path id="acoustic-rpm-path" d=""></path>
          <g id="acoustic-chart-points"></g>
        </svg>
        <div id="acoustic-results-summary">Idle</div>
      </div>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('initializes in ready state when no sweep is running', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      running: false,
      completed_at: null,
      results: [],
    });

    initAcousticCalibration();
    await new Promise((r) => setTimeout(r, 20));

    expect(document.getElementById('acoustic-sweep-badge').textContent).toBe('READY');
    expect(document.getElementById('btn-start-acoustic-sweep').style.display).not.toBe('none');
    expect(document.getElementById('btn-stop-acoustic-sweep').style.display).toBe('none');
  });

  it('starts sweep on start button click and transitions to running state', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({ running: false, results: [] });
    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ success: true });

    initAcousticCalibration();
    await new Promise((r) => setTimeout(r, 20));

    const startBtn = document.getElementById('btn-start-acoustic-sweep');
    startBtn.click();
    await new Promise((r) => setTimeout(r, 20));

    expect(postSpy).toHaveBeenCalledWith('/api/fans/calibrate/acoustic', {
      step_duration: 3.0,
      pwm_step: 25,
    });
    expect(document.getElementById('acoustic-sweep-badge').textContent).toBe('RUNNING');
    expect(document.getElementById('btn-stop-acoustic-sweep').style.display).toBe('inline-flex');
    expect(document.getElementById('btn-start-acoustic-sweep').style.display).toBe('none');
  });

  it('reverts to ready state if starting sweep fails', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({ running: false, results: [] });
    vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('Network error'));

    initAcousticCalibration();
    await new Promise((r) => setTimeout(r, 20));

    const startBtn = document.getElementById('btn-start-acoustic-sweep');
    startBtn.click();
    await new Promise((r) => setTimeout(r, 20));

    expect(document.getElementById('acoustic-sweep-badge').textContent).toBe('READY');
    expect(document.getElementById('btn-start-acoustic-sweep').style.display).not.toBe('none');
    expect(document.getElementById('btn-stop-acoustic-sweep').style.display).toBe('none');
  });

  it('renders SVG curve path and detects resonance when sweep data arrives', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      running: false,
      completed_at: 1720000000,
      results: [
        { pwm: 58, pct: 32, rpm_avg: 600, rpm_jitter: 15, resonance_detected: false },
        { pwm: 100, pct: 55, rpm_avg: 1200, rpm_jitter: 140, resonance_detected: true },
        { pwm: 183, pct: 100, rpm_avg: 1950, rpm_jitter: 25, resonance_detected: false },
      ],
    });

    initAcousticCalibration();
    await new Promise((r) => setTimeout(r, 20));

    const path = document.getElementById('acoustic-rpm-path');
    const pointsG = document.getElementById('acoustic-chart-points');
    const summary = document.getElementById('acoustic-results-summary');
    const badge = document.getElementById('acoustic-sweep-badge');

    expect(badge.textContent).toBe('COMPLETE');
    expect(path.getAttribute('d')).toContain('M');
    expect(path.getAttribute('d')).toContain('L');
    expect(pointsG.innerHTML).toContain('circle');
    expect(pointsG.innerHTML).toContain('#f43f5e'); // Resonance warning point
    expect(summary.textContent).toContain('resonance detected');
  });

  it('stops running sweep on stop button click', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      running: true,
      current_pwm: 83,
      step: 2,
      total_steps: 6,
      progress_pct: 33,
      results: [{ pwm: 58, pct: 32, rpm_avg: 600, rpm_jitter: 10, resonance_detected: false }],
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ success: true });

    initAcousticCalibration();
    await new Promise((r) => setTimeout(r, 20));

    const stopBtn = document.getElementById('btn-stop-acoustic-sweep');
    expect(stopBtn.style.display).toBe('inline-flex');

    stopBtn.click();
    await new Promise((r) => setTimeout(r, 20));

    expect(postSpy).toHaveBeenCalledWith('/api/fans/calibrate/acoustic/stop');
  });
});
