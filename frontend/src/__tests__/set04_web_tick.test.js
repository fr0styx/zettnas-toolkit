/** SET-04 (decision S13): Web is chosen per chat and never remembered. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  sendAiChatMessage,
  createNewAiConversation,
  selectAiConversation,
  clearAiChatHistory,
} from '../components/management/ai.js';
import { ZettEventBus } from '../event-bus.js';
import { api } from '../api.js';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const box = () => document.getElementById('ai-chat-web-toggle');
const tick = () => { box().checked = true; };

describe('the Web tick in Ask Kib (SET-04)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <input type="checkbox" id="ai-chat-web-toggle" />
      <input id="ai-chat-input" /><button id="btn-ai-chat-send"></button>
      <div id="ai-chat-messages-list"><div class="ai-chat-msg">an earlier answer</div></div>
      <span id="ai-chat-active-title"></span><div id="ai-conversations-list"></div>`;
    vi.spyOn(api, 'get').mockResolvedValue({ conversations: [], messages: [] });
  });
  afterEach(() => vi.restoreAllMocks());

  it('is sent with the chat it was ticked for', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', answer: 'hi' });
    tick();
    await sendAiChatMessage('what is new in zfs');
    expect(post).toHaveBeenCalledWith('/api/media/chat', expect.objectContaining({ allow_web_search: true }));
  });

  it('is off again in a new chat', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ conversation: { id: 'c2', title: 'New Conversation' } });
    tick();
    await createNewAiConversation();
    expect(box().checked).toBe(false);
  });

  it('is off again when another chat is opened, and stays when the same one is opened', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ conversation: { id: 'c3', title: 'New Conversation' } });
    await createNewAiConversation();
    tick();
    await selectAiConversation('c3');
    expect(box().checked).toBe(true);
    await selectAiConversation('c4');
    expect(box().checked).toBe(false);
  });

  it('is off again when the chat is cleared', () => {
    tick();
    clearAiChatHistory();
    expect(box().checked).toBe(false);
  });

  it('is off, and the chat is gone from the window, after signing out', () => {
    tick();
    ZettEventBus.emit('auth:logout');
    expect(box().checked).toBe(false);
    expect(document.getElementById('ai-chat-messages-list').textContent).toBe('');
  });

  it('is not kept in the browser', () => {
    const src = readFileSync(resolve(__dirname, '..', 'components/management/ai.js'), 'utf8');
    expect(src).not.toContain("localStorage.setItem('kiboto_ai_web'");
    expect(src).not.toContain("localStorage.getItem('kiboto_ai_web'");
    expect(src).toContain("localStorage.removeItem('kiboto_ai_web')");
  });
});
