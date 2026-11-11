/** SET-04: Kib's Configuration tab is for people who manage Kib; "Connect my Immich" is for everyone. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { mayManageKib, kibPaneFor, loadKibExtras } from '../components/management/kib-access.js';
import { renderImmichSettings } from '../components/immich-settings.js';
import { renderAiApps } from '../components/ai-apps-settings.js';
import { renderAiPack } from '../components/ai-pack-settings.js';

vi.mock('../components/immich-settings.js', () => ({ renderImmichSettings: vi.fn() }));
vi.mock('../components/ai-apps-settings.js', () => ({ renderAiApps: vi.fn() }));
vi.mock('../components/ai-pack-settings.js', () => ({ renderAiPack: vi.fn() }));

const html = readFileSync(resolve(__dirname, '..', 'windows/management-window.html'), 'utf8');
const owner = { scopes: ['*'] };
const storageAdmin = { scopes: ['storage:admin', 'system:view'] };
const family = { scopes: ['shares:read', 'shares:user_write', 'system:view'] };
const flush = () => new Promise((r) => setTimeout(r, 0));
const tab = () => document.getElementById('mgmt-tab-ai-index');
const pane = () => document.getElementById('mgmt-pane-ai-index');

describe('who sees Kib’s Configuration (SET-04)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <button id="mgmt-tab-ai-chat"></button><button id="mgmt-tab-ai-index"></button>
      <div id="mgmt-pane-ai-rag"><div id="immich-settings-mount"></div></div>
      <div id="mgmt-pane-ai-index"><div id="ai-apps-mount"></div><div id="ai-pack-mount"></div></div>`;
  });

  it('knows who may change Kib by the rights the settings route asks for', () => {
    expect(mayManageKib(owner)).toBe(true);
    expect(mayManageKib(storageAdmin)).toBe(true);
    expect(mayManageKib(family)).toBe(false);
    expect(mayManageKib({ scopes: [] })).toBe(false);
    expect(mayManageKib(null)).toBe(true); // nobody known yet: nothing is taken away
  });

  it('a family member has no Configuration tab, and asking for it gives Ask Kib', () => {
    expect(kibPaneFor('mgmt-pane-ai-index', family)).toBe('mgmt-pane-ai-chat');
    expect(tab().hidden).toBe(true);
    expect(pane().hidden).toBe(true);
    expect(kibPaneFor('mgmt-pane-ai-rag', family)).toBe('mgmt-pane-ai-rag');
    expect(tab().hidden).toBe(true);
  });

  it('a person who manages Kib keeps it, and it comes back after a family member', () => {
    kibPaneFor('mgmt-pane-ai-chat', family);
    expect(kibPaneFor('mgmt-pane-ai-index', owner)).toBe('mgmt-pane-ai-index');
    expect(tab().hidden).toBe(false);
    expect(pane().hidden).toBe(false);
  });

  it('each person’s Immich loads with AI search, for a family member too', async () => {
    loadKibExtras('mgmt-pane-ai-rag', family);
    await flush();
    expect(renderImmichSettings).toHaveBeenCalledWith(document.getElementById('immich-settings-mount'), false);
    expect(renderAiApps).not.toHaveBeenCalled();
    expect(renderAiPack).not.toHaveBeenCalled();
  });

  it('"AI for apps" and the AI pack load with Configuration', async () => {
    loadKibExtras('mgmt-pane-ai-index', owner);
    await flush();
    expect(renderAiApps).toHaveBeenCalledWith(document.getElementById('ai-apps-mount'), true);
    expect(renderAiPack).toHaveBeenCalledWith(document.getElementById('ai-pack-mount'), true);
    expect(renderImmichSettings).not.toHaveBeenCalled();
  });

  it('the Immich card sits in the search pane of the real page, once', () => {
    const rag = html.slice(html.indexOf('id="mgmt-pane-ai-rag"'), html.indexOf('id="mgmt-pane-ai-index"'));
    expect(rag).toContain('id="immich-settings-mount"');
    expect(html.split('id="immich-settings-mount"').length).toBe(2);
  });
});
