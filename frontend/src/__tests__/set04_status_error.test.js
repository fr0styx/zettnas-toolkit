/** SET-04: no stand-in values when the status cannot be loaded; a chat without "+ New Chat" is saved. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const html = readFileSync(resolve(__dirname, '..', 'windows/management-window.html'), 'utf8');
const text = (id) => document.getElementById(id).textContent.trim();

describe('the Kib page when its status cannot be loaded (SET-04)', () => {
  let ai;
  let api;
  beforeEach(async () => {
    vi.resetModules(); // a fresh page: no status has been loaded yet
    ({ api } = await import('../api.js'));
    ai = await import('../components/management/ai.js');
    document.body.innerHTML = `
      <div id="mgmt-sec-ai">
        <div id="ai-status-error" class="kb-alert kb-alert--danger" role="alert" hidden></div>
        <span id="ai-chat-active-model-badge">🤖 Active LLM: DeepSeek-R1-Distill-Qwen-1.5B • ⚡ Tier 1 NPU</span>
        <span id="ai-accel-active-label" data-sample>Tier 1: NPU ➔ GPU ➔ CPU</span>
        <span id="ai-active-llm-label">qwen2.5:3b</span>
        <span id="ai-standby-guard-text" data-i18n="ai.standby_guard_active">Standby Guard: Active</span>
        <span id="ai-watched-dropdown-count-badge" data-sample>1 Checked</span>
        <div id="ai-hw-tier1-status" data-sample>Probing NPU...</div>
        <input id="ai-some-input" data-sample value="kept" />
      </div>`;
  });
  afterEach(() => vi.restoreAllMocks());

  it('says so, with the reason and a way to try again', async () => {
    const get = vi.spyOn(api, 'get').mockRejectedValue(new Error('the server did not answer'));
    await ai.fetchAndRenderAiStatus();
    const box = document.getElementById('ai-status-error');
    expect(box.hidden).toBe(false);
    expect(box.textContent).toContain('Kib’s status could not be loaded: the server did not answer');
    get.mockClear();
    box.querySelector('button').click();
    expect(get).toHaveBeenCalledWith('/api/media/status');
  });

  it('shows a dash where the markup had a made-up value', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'));
    await ai.fetchAndRenderAiStatus();
    for (const id of ['ai-chat-active-model-badge', 'ai-accel-active-label', 'ai-active-llm-label', 'ai-standby-guard-text', 'ai-watched-dropdown-count-badge', 'ai-hw-tier1-status']) {
      expect(text(id), id).toBe('—');
    }
    expect(document.getElementById('ai-standby-guard-text').hasAttribute('data-i18n')).toBe(false);
    expect(document.getElementById('ai-some-input').value).toBe('kept');
  });

  it('keeps what a good answer showed when a later one fails, and takes the alert away on the next good one', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ active_model: 'gemma3:4b', hardware: { tier_number: 3 } });
    await ai.fetchAndRenderAiStatus();
    expect(text('ai-active-llm-label')).not.toBe('qwen2.5:3b');
    const shown = text('ai-active-llm-label');
    get.mockRejectedValueOnce(new Error('offline'));
    await ai.fetchAndRenderAiStatus();
    expect(document.getElementById('ai-status-error').hidden).toBe(false);
    expect(text('ai-active-llm-label')).toBe(shown);
    await ai.fetchAndRenderAiStatus();
    expect(document.getElementById('ai-status-error').hidden).toBe(true);
  });

  it('the real page has the alert, hidden, in the Kib section', () => {
    const section = html.slice(html.indexOf('id="mgmt-sec-ai"'), html.indexOf('id="mgmt-pane-ai-chat"'));
    expect(section).toMatch(/<div id="ai-status-error"[^>]*role="alert"[^>]*hidden>/);
  });
});

describe('a chat typed without "+ New Chat" (SET-04)', () => {
  it('asks for a conversation, and adopts the one the server started', async () => {
    vi.resetModules();
    const { api } = await import('../api.js');
    const ai = await import('../components/management/ai.js');
    document.body.innerHTML = `
      <input id="ai-chat-input" /><button id="btn-ai-chat-send"></button>
      <div id="ai-chat-messages-list"></div><div id="ai-chat-threads-list"></div>`;
    vi.spyOn(api, 'get').mockResolvedValue({ conversations: [] });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', reply: 'hi', conversation_id: 'conv_new' });
    await ai.sendAiChatMessage('first words');
    expect(post).toHaveBeenLastCalledWith('/api/media/chat', expect.objectContaining({ conversation_id: null, new_conversation: true }));
    await ai.sendAiChatMessage('second words');
    expect(post).toHaveBeenLastCalledWith('/api/media/chat', expect.objectContaining({ conversation_id: 'conv_new', new_conversation: false }));
    expect(api.get).toHaveBeenCalledWith('/api/ai/conversations', {}); // the list is drawn again: the chat is in it
  });
});
