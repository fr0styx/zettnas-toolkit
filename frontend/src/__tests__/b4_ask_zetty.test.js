import { describe, it, expect, vi } from 'vitest';
import { setAiChatFocus, aiChatFocus, askZettyAbout } from '../components/management/ai.js';

describe('Ask Zetty about this (missing feature 6)', () => {
  it('shows what the questions are about and can drop it', () => {
    document.body.innerHTML = '<div><input id="ai-chat-input" /></div>';
    setAiChatFocus('/mnt/user/docs/plan.txt');
    expect(aiChatFocus()).toEqual({ path: '/mnt/user/docs/plan.txt', name: 'plan.txt' });
    const chip = document.getElementById('ai-chat-focus');
    expect(chip.textContent).toContain('plan.txt');
    chip.querySelector('button').click();
    expect(aiChatFocus()).toBeNull();
    expect(document.getElementById('ai-chat-focus')).toBeNull();
  });

  it('opens the chat with the file in focus', async () => {
    vi.useFakeTimers();
    document.body.innerHTML = '<div><input id="ai-chat-input" /></div>';
    window.openManagementSection = vi.fn();
    askZettyAbout('/mnt/user/docs/plan.txt', 'plan.txt');
    vi.advanceTimersByTime(400);
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-sec-ai', 'mgmt-pane-ai-chat');
    expect(document.getElementById('ai-chat-input').placeholder).toContain('plan.txt');
    expect(window.askZettyAbout).toBe(askZettyAbout);
    vi.useRealTimers();
    setAiChatFocus(null);
  });
});

describe('the chat request carries the file in focus', () => {
  it('sends focus_path with the question', async () => {
    const { api } = await import('../api.js');
    const { sendAiChatMessage } = await import('../components/management/ai.js');
    document.body.innerHTML = '<div><input id="ai-chat-input" /></div><div id="ai-chat-messages-list"></div><button id="btn-ai-chat-send"></button>';
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ reply: 'It says 42.', tools_called: [] });
    setAiChatFocus('/mnt/user/docs/plan.txt');
    await sendAiChatMessage('What is the budget?');
    expect(post).toHaveBeenCalledWith('/api/media/chat', expect.objectContaining({ message: 'What is the budget?', focus_path: '/mnt/user/docs/plan.txt' }));
    post.mockRestore();
    setAiChatFocus(null);
  });
});
