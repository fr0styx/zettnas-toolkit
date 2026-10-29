import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), request: vi.fn() } }));

import { api } from '../api.js';
import { packHtml, stateText, readInstall, renderAiPack } from '../components/ai-pack-settings.js';

const BASE = {
  box: { ram_gb: 31.2, gpu: true, npu: true },
  recommendation: { preset: 'standard', why: '31 GB of memory and an Intel GPU' },
};

describe('AI pack settings (AI-40)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('offers the recommended preset when nothing is installed', () => {
    const html = packHtml({ ...BASE, installed: false, state: 'absent' });
    expect(html).toContain('31.2 GB · Intel GPU · NPU');
    expect(html).toContain('value="standard" selected');
    expect(html).toContain('data-ai-pack-install');
  });

  it('shows the warm-up, then offers to use it, then says it is in use', () => {
    expect(stateText({ state: 'warming', phase: 'downloading OpenVINO/Qwen3-4B-int4-ov' })).toContain('downloading OpenVINO/Qwen3-4B-int4-ov');
    const ready = packHtml({ ...BASE, installed: true, state: 'ready', in_use: false });
    expect(ready).toContain('data-ai-pack-use');
    expect(ready).not.toContain('data-ai-pack-install');
    expect(packHtml({ ...BASE, installed: true, state: 'ready', in_use: true })).not.toContain('data-ai-pack-use');
  });

  it("never offers to install over someone's own container", () => {
    const html = packHtml({ ...BASE, installed: false, state: 'not-ours' });
    expect(html).not.toContain('data-ai-pack-install');
    expect(html).toContain('left alone');
  });

  it('reads the last event of the install stream', async () => {
    const last = await readInstall('{"step":"pull"}\n{"step":"done","message":"starting"}\n');
    expect(last).toEqual({ step: 'done', message: 'starting' });
  });

  it('is hidden for people who are not administrators', async () => {
    const card = document.createElement('section');
    const mount = document.createElement('div');
    card.appendChild(mount);
    await renderAiPack(mount, false);
    expect(card.hidden).toBe(true);
    expect(api.get).not.toHaveBeenCalled();
  });
});
