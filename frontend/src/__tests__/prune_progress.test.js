import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, auth: { getToken: () => '' }, ApiError: class extends Error {} }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

describe('docker cleanup progress', () => {
  it('shows the bar, the step list and the image count', async () => {
    const { renderPruneJob } = await import('../components/management.js');
    document.body.innerHTML = `<div id="dpm-progress" hidden><span id="dpm-progress-msg"></span><strong id="dpm-progress-pct"></strong>
      <div id="dpm-bar"><div id="dpm-bar-fill"></div></div><ul id="dpm-steps"></ul><div id="dpm-freed"></div></div>`;
    renderPruneJob({
      state: 'running', percent: 42, step: 'images', images_done: 33, images_total: 133, freed_human: '1.2 GB',
      steps: [
        { key: 'containers', state: 'done', detail: '2 removed', freed_bytes: 1048576 },
        { key: 'images', state: 'running', detail: '', freed_bytes: 0 },
        { key: 'volumes', state: 'pending', detail: '', freed_bytes: 0 },
      ],
    });
    expect(document.getElementById('dpm-progress').hidden).toBe(false);
    expect(document.getElementById('dpm-bar-fill').style.width).toBe('42%');
    expect(document.getElementById('dpm-bar').getAttribute('aria-valuenow')).toBe('42');
    expect(document.getElementById('dpm-progress-msg').textContent).toBe('Removing image 34 of 133');
    const steps = [...document.querySelectorAll('#dpm-steps li')].map((li) => li.textContent);
    expect(steps[0]).toContain('Stopped containers');
    expect(steps[0]).toContain('2 removed');
    expect(steps[1]).toContain('33 / 133');
    expect(document.getElementById('dpm-freed').textContent).toBe('1.2 GB freed so far');
  });
});
