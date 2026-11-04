// NDOCK-1: after the last image the cleanup names what it is doing instead of "Removing image 10 of 10".
import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, auth: { getToken: () => '' }, ApiError: class extends Error {} }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

describe('docker cleanup phases (NDOCK-1)', () => {
  it.each([
    ['before', 'Measuring what the images use…'],
    ['remove', 'Removing image 10 of 10'],
    ['sweep', 'Clearing the layers those images used…'],
    ['after', 'Measuring the space freed…'],
  ])('phase %s', async (phase, text) => {
    const { renderPruneJob } = await import('../components/management.js');
    document.body.innerHTML = `<div id="dpm-progress" hidden><span id="dpm-progress-msg"></span><strong id="dpm-progress-pct"></strong>
      <div id="dpm-bar"><div id="dpm-bar-fill"></div></div><ul id="dpm-steps"></ul><div id="dpm-freed"></div></div>`;
    renderPruneJob({
      state: 'running', percent: 80, step: 'images', images_phase: phase, images_done: 10, images_total: 10, freed_human: '0 B',
      steps: [{ key: 'images', state: 'running', detail: '', freed_bytes: 0 }],
    });
    expect(document.getElementById('dpm-progress-msg').textContent).toBe(text);
  });
});
