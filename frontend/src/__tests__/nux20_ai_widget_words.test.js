/** NUX-20: the desktop AI accelerator widget names each state in translatable words. */
import { describe, it, expect, beforeEach } from 'vitest';
import { ZettEventBus } from '../event-bus.js';
import { initWidgets } from '../components/widgets.js';

const tick = () => new Promise((r) => setTimeout(r, 30));
const badge = () => document.getElementById('w-ai-accel-badge').textContent;
const engine = () => document.getElementById('w-ai-engine-status').textContent.trim();

describe('AI accelerator widget words (NUX-20)', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="desktop-widgets-container"><div class="desktop-widget" id="widget-ai-accelerator">
        <span id="w-ai-accel-badge"></span><span id="w-ai-npu-state"></span><span id="w-ai-gpu-state"></span>
        <div id="w-ai-engine-status"></div></div></div>`;
    initWidgets();
  });

  it('says which chip is busy, or which are ready', async () => {
    const cases = [
      [{ npu: { present: true, util_pct: 50 }, gpu: { present: true, util_pct: 30 } }, 'DUAL RUN', 'Intel AI Boost NPU Active'],
      [{ npu: { present: true, util_pct: 50 }, gpu: { present: false } }, 'NPU RUN', 'Intel AI Boost NPU Active'],
      [{ npu: { present: false }, gpu: { present: true, util_pct: 30 } }, 'GPU RUN', 'Intel Arc GPU Active'],
      [{ npu: { present: true }, gpu: { present: true } }, 'NPU + GPU', 'Hybrid Dual Silicon (NPU + GPU Ready)'],
      [{ npu: { present: false }, gpu: { present: false } }, 'CPU ONLY', 'Neural Engine Ready'],
    ];
    for (const [stats, b, e] of cases) {
      ZettEventBus.emit('stats:updated', stats);
      await tick();
      expect(badge()).toBe(b);
      expect(engine().replace(/\s+/g, ' ')).toBe(e);
    }
  });
});
