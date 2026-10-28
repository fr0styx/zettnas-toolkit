import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));

import { api } from '../api.js';
import { renderAiApps, appsHtml, resultHtml } from '../components/ai-apps-settings.js';

const DATA = {
  base_url: 'http://nas:8082/api/v1/ai/openai',
  apps: [
    { app: 'paperless', label: 'Paperless-ngx' },
    { app: 'other', label: 'Another app' },
  ],
  keys: [{ id: 't1', name: 'AI for Paperless-ngx', masked_key: 'zat_ab…', created: 1, last_used_at: null }],
};

describe('AI for apps settings (COMP-07)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('lists the address, the keys and the apps', () => {
    const html = appsHtml(DATA);
    expect(html).toContain('http://nas:8082/api/v1/ai/openai');
    expect(html).toContain('zat_ab…');
    expect(html).toContain('value="paperless"');
  });

  it('shows the filled-in settings once, escaped', () => {
    const html = resultHtml({ how: 'Add these', settings: { PAPERLESS_AI_LLM_API_KEY: 'zat_<x>' } });
    expect(html).toContain('PAPERLESS_AI_LLM_API_KEY=zat_&lt;x&gt;');
  });

  it('is hidden for people who are not administrators', async () => {
    const card = document.createElement('section');
    const mount = document.createElement('div');
    card.appendChild(mount);
    await renderAiApps(mount, false);
    expect(card.hidden).toBe(true);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('creates a key for the chosen app and shows its settings', async () => {
    api.get.mockResolvedValue(DATA);
    api.post.mockResolvedValue({ id: 't2', key: 'zat_new', how: 'Add these', settings: { OPENAI_API_KEY: 'zat_new' } });
    const card = document.createElement('section');
    const mount = document.createElement('div');
    card.appendChild(mount);
    document.body.appendChild(card);
    await renderAiApps(mount, true);
    mount.querySelector('select').value = 'other';
    mount.querySelector('[data-ai-app-create]').dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(mount.querySelector('[data-ai-app-result]').hidden).toBe(false));
    expect(api.post).toHaveBeenCalledWith('/api/ai/apps/keys', { app: 'other' });
    expect(mount.querySelector('.ai-apps-settings').textContent).toBe('OPENAI_API_KEY=zat_new');
    card.remove();
  });
});
