import { describe, it, expect, beforeEach } from 'vitest';
import { ZettEventBus } from '../event-bus.js';
import { initWidgets, loadWidgetConfig, saveWidgetConfig, applyWidgetConfig } from '../components/widgets.js';
import { ALL_TRANSLATIONS as TRANSLATIONS } from '../locales/all.js';

describe('AI Accelerator Desktop Widget (NPU + GPU Real-Time Gauges)', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="desktop-widgets-container" class="pos-top-right glass-standard scale-normal">
        <div class="desktop-widget" id="widget-clock"></div>
        <div class="desktop-widget" id="widget-ai-accelerator">
          <span class="widget-badge" id="w-ai-accel-badge">NPU + GPU</span>
          <path id="w-ai-npu-arc" stroke-dasharray="0, 100" />
          <div id="w-ai-npu-val">0%</div>
          <div id="w-ai-npu-freq">0 MHz</div>
          <span id="w-ai-npu-state" class="ai-metric-pill sleep">D3 Sleep</span>
          <path id="w-ai-gpu-arc" stroke-dasharray="0, 100" />
          <div id="w-ai-gpu-val">0%</div>
          <div id="w-ai-gpu-freq">0 MHz</div>
          <span id="w-ai-gpu-state" class="ai-metric-pill sleep">Standby</span>
          <div id="w-ai-engine-status"></div>
        </div>
      </div>
      <input type="checkbox" id="w-cfg-ai-accelerator" />
    `;
  });

  it('includes ai_accelerator enabled by default in widget configuration', () => {
    const config = loadWidgetConfig();
    expect(config.widgets.ai_accelerator).toBe(true);
    expect(config.order).toContain('ai_accelerator');
  });

  it('controls widget visibility via saveWidgetConfig', () => {
    const w = document.getElementById('widget-ai-accelerator');
    applyWidgetConfig();
    expect(w.style.display).not.toBe('none');

    saveWidgetConfig({ widgets: { ai_accelerator: false } });
    expect(w.style.display).toBe('none');

    saveWidgetConfig({ widgets: { ai_accelerator: true } });
    expect(w.style.display).toBe('block');
  });

  it('updates live SVG gauges, frequencies, and status badge on stats:updated event', async () => {
    initWidgets();

    ZettEventBus.emit('stats:updated', {
      npu: {
        present: true,
        vendor: 'Intel',
        model: 'Intel AI Boost NPU',
        cur_freq_mhz: 1400,
        max_freq_mhz: 1400,
        util_pct: 94.5,
        power_state: 'D0',
      },
      gpu: {
        present: true,
        vendor: 'Intel',
        model: 'Intel Arc Graphics',
        cur_freq_mhz: 2150,
        max_freq_mhz: 2200,
        util_pct: 42.0,
      },
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const npuVal = document.getElementById('w-ai-npu-val');
    const npuArc = document.getElementById('w-ai-npu-arc');
    const npuFreq = document.getElementById('w-ai-npu-freq');
    const npuState = document.getElementById('w-ai-npu-state');

    const gpuVal = document.getElementById('w-ai-gpu-val');
    const gpuArc = document.getElementById('w-ai-gpu-arc');
    const gpuFreq = document.getElementById('w-ai-gpu-freq');
    const gpuState = document.getElementById('w-ai-gpu-state');
    const aiBadge = document.getElementById('w-ai-accel-badge');
    const engineStatus = document.getElementById('w-ai-engine-status');

    expect(npuVal.textContent).toBe('95%');
    expect(npuArc.getAttribute('stroke-dasharray')).toBe('95, 100');
    expect(npuFreq.textContent).toBe('1400 MHz');
    expect(npuState.textContent).toBe('Active (3W)');
    expect(npuState.classList.contains('active-npu')).toBe(true);

    expect(gpuVal.textContent).toBe('42%');
    expect(gpuArc.getAttribute('stroke-dasharray')).toBe('42, 100');
    expect(gpuFreq.textContent).toBe('2150 MHz');
    expect(gpuState.textContent).toBe('Compute');
    expect(gpuState.classList.contains('active-gpu')).toBe(true);

    expect(aiBadge.textContent).toBe('DUAL RUN');
    expect(engineStatus.innerHTML).toContain('Intel AI Boost NPU Active');
  });

  it('dynamically reflects active compute when GPU clock frequency is boosted during inference', async () => {
    initWidgets();

    ZettEventBus.emit('stats:updated', {
      ai_active: true,
      ai_accelerator: 'gpu',
      npu: {
        present: true,
        cur_freq_mhz: 0,
        max_freq_mhz: 1400,
        util_pct: 0.0,
        power_state: 'D3hot',
      },
      gpu: {
        present: true,
        cur_freq_mhz: 2150,
        max_freq_mhz: 2200,
        util_pct: 0.0,
      },
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const gpuVal = document.getElementById('w-ai-gpu-val');
    const gpuState = document.getElementById('w-ai-gpu-state');
    const aiBadge = document.getElementById('w-ai-accel-badge');
    const engineStatus = document.getElementById('w-ai-engine-status');

    expect(parseInt(gpuVal.textContent)).toBeGreaterThan(0);
    expect(gpuState.textContent).toBe('Compute');
    expect(gpuState.classList.contains('active-gpu')).toBe(true);
    expect(aiBadge.textContent).toBe('GPU RUN');
    expect(engineStatus.innerHTML).toContain('Intel Arc GPU Active');
  });

  it('dynamically reflects active compute when NPU is in D0 active state during inference', async () => {
    initWidgets();

    ZettEventBus.emit('stats:updated', {
      ai_active: true,
      ai_accelerator: 'npu',
      npu: {
        present: true,
        cur_freq_mhz: 1400,
        max_freq_mhz: 1400,
        util_pct: 0.0,
        power_state: 'D0',
      },
      gpu: {
        present: true,
        cur_freq_mhz: 0,
        max_freq_mhz: 2200,
        util_pct: 0.0,
      },
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const npuVal = document.getElementById('w-ai-npu-val');
    const npuState = document.getElementById('w-ai-npu-state');
    const aiBadge = document.getElementById('w-ai-accel-badge');
    const engineStatus = document.getElementById('w-ai-engine-status');

    expect(parseInt(npuVal.textContent)).toBeGreaterThan(0);
    expect(npuState.textContent).toBe('Active (3W)');
    expect(npuState.classList.contains('active-npu')).toBe(true);
    expect(aiBadge.textContent).toBe('NPU RUN');
    expect(engineStatus.innerHTML).toContain('Intel AI Boost NPU Active');
  });

  it('contains multilingual translations across all 5 supported languages', () => {
    const langs = ['en', 'de', 'zh', 'fr', 'es'];
    langs.forEach((lang) => {
      expect(TRANSLATIONS[lang]['widget.ai_accelerator']).toBeDefined();
      expect(TRANSLATIONS[lang]['widget.ai_accelerator'].length).toBeGreaterThan(0);
      expect(TRANSLATIONS[lang]['widget.ai_accelerator_desc']).toBeDefined();
      expect(TRANSLATIONS[lang]['widget.ai_accelerator_desc'].length).toBeGreaterThan(0);
    });
  });
});
