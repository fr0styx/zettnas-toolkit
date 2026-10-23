/**
 * @file ai_conversation_history.test.js
 * Comprehensive Vitest suite for ZettAI Multi-Turn Conversation History & Persistence UI.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('ZettAI Conversation History & Dual-Pane UI Suite', () => {
  let managementModule;
  let apiModule;

  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();

    document.body.innerHTML = `
      <div id="mgmt-pane-ai-chat" class="mgmt-tab-pane">
        <div id="ai-chat-dual-container" class="ai-chat-dual-container">
          <aside id="ai-chat-sidebar" class="ai-chat-sidebar">
            <button id="btn-ai-chat-new" class="btn-ai-new-chat">+ New Chat</button>
            <button id="btn-ai-chat-sidebar-toggle" class="btn-ai-icon-toggle">◀</button>
            <input id="ai-chat-search-input" class="ai-search-input" />
            <div id="ai-chat-threads-list" class="ai-chat-threads-scroll"></div>
            <span id="ai-chat-thread-count">0 chats</span>
            <button id="btn-ai-chat-clear-all" class="btn-ai-clear-all">Clear All</button>
          </aside>
          <main id="ai-chat-main-stage" class="ai-chat-main-stage">
            <button id="btn-ai-chat-sidebar-open" style="display:none;">▶</button>
            <span id="ai-chat-active-title">New Conversation</span>
            <button id="btn-ai-chat-rename">✏️</button>
            <span id="ai-chat-active-model-badge">DeepSeek-R1</span>
            <button id="btn-ai-chat-export-toggle">Export</button>
            <div id="ai-chat-export-menu" style="display:none;">
              <button id="btn-ai-chat-export-md">Export MD</button>
              <button id="btn-ai-chat-export-json">Export JSON</button>
            </div>
            <button id="btn-ai-chat-clear">Clear Chat</button>
            <div id="ai-chat-messages-list"></div>
            <input id="ai-chat-input" value="" />
            <button id="btn-ai-chat-send">Ask Zetty</button>
          </main>
        </div>
      </div>
    `;

    apiModule = await import('../api.js');
    managementModule = await import('../components/management.js');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('toggles sidebar collapse state and persists to localStorage', () => {
    const sidebar = document.getElementById('ai-chat-sidebar');
    const openBtn = document.getElementById('btn-ai-chat-sidebar-open');

    expect(sidebar.classList.contains('collapsed')).toBe(false);

    managementModule.toggleAiSidebar();
    expect(sidebar.classList.contains('collapsed')).toBe(true);
    expect(openBtn.style.display).toBe('flex');
    expect(localStorage.getItem('zettnas_ai_sidebar_collapsed')).toBe('1');

    managementModule.toggleAiSidebar();
    expect(sidebar.classList.contains('collapsed')).toBe(false);
    expect(openBtn.style.display).toBe('none');
    expect(localStorage.getItem('zettnas_ai_sidebar_collapsed')).toBe('0');
  });

  it('fetches and renders conversations into chronological groups', async () => {
    const nowSec = Date.now() / 1000;
    const mockConvs = [
      { id: 'c1', title: 'Pinned Diagnostics', is_pinned: true, updated_at: nowSec },
      { id: 'c2', title: 'Today Task', is_pinned: false, updated_at: nowSec - 300 },
      { id: 'c3', title: 'Yesterday Scrub', is_pinned: false, updated_at: nowSec - 90000 },
    ];

    vi.spyOn(apiModule.api, 'get').mockImplementation(async (url) => {
      if (url.includes('/conversations/c1')) {
        return { status: 'ok', conversation: { id: 'c1', title: 'Pinned Diagnostics', messages: [] } };
      }
      return { status: 'ok', conversations: mockConvs };
    });

    await managementModule.fetchAndRenderAiConversations();

    const list = document.getElementById('ai-chat-threads-list');
    expect(list.innerHTML).toContain('Pinned Diagnostics');
    expect(list.innerHTML).toContain('Today Task');
    expect(list.innerHTML).toContain('Yesterday Scrub');

    const badge = document.getElementById('ai-chat-thread-count');
    expect(badge.textContent).toBe('3 chats');
  });

  it('selects conversation and renders message history', async () => {
    const mockFullConv = {
      id: 'c_test',
      title: 'Docker Inspection',
      model: 'qwen2.5:3b',
      messages: [
        { role: 'user', content: 'List running containers' },
        { role: 'assistant', content: 'Found 4 active containers: zettnas-toolkit, plex, traefik, nextcloud.' },
      ],
    };

    vi.spyOn(apiModule.api, 'get').mockResolvedValueOnce({
      status: 'ok',
      conversation: mockFullConv,
    });

    await managementModule.selectAiConversation('c_test');

    const titleEl = document.getElementById('ai-chat-active-title');
    expect(titleEl.textContent).toBe('Docker Inspection');

    const msgList = document.getElementById('ai-chat-messages-list');
    expect(msgList.innerHTML).toContain('List running containers');
    expect(msgList.innerHTML).toContain('Found 4 active containers');
  });

  it('creates new conversation thread and resets stage', async () => {
    vi.spyOn(apiModule.api, 'post').mockResolvedValueOnce({
      status: 'ok',
      conversation: { id: 'c_fresh', title: 'New Conversation' },
    });
    vi.spyOn(apiModule.api, 'get').mockResolvedValueOnce({
      status: 'ok',
      conversations: [{ id: 'c_fresh', title: 'New Conversation' }],
    });

    await managementModule.createNewAiConversation();

    const titleEl = document.getElementById('ai-chat-active-title');
    expect(titleEl.textContent).toBe('New Conversation');

    const msgList = document.getElementById('ai-chat-messages-list');
    expect(msgList.innerHTML).toBe('');
  });

  it('renames active conversation and updates UI header', async () => {
    vi.spyOn(apiModule.api, 'patch').mockResolvedValueOnce({
      status: 'ok',
      conversation: { id: 'c_ren', title: 'Custom Fan Profile' },
    });
    vi.spyOn(apiModule.api, 'get').mockImplementation(async (url) => {
      if (url.includes('/api/ai/conversations/c_ren')) {
        return {
          status: 'ok',
          conversation: { id: 'c_ren', title: 'Custom Fan Profile', messages: [] },
        };
      }
      return {
        status: 'ok',
        conversations: [{ id: 'c_ren', title: 'Custom Fan Profile' }],
      };
    });

    await managementModule.selectAiConversation('c_ren');
    await managementModule.renameAiConversation('c_ren', 'Custom Fan Profile');

    const titleEl = document.getElementById('ai-chat-active-title');
    expect(titleEl.textContent).toBe('Custom Fan Profile');
  });

  it('exports conversation to markdown and json formats without error', async () => {
    vi.spyOn(apiModule.api, 'get').mockResolvedValue({
      status: 'ok',
      conversation: {
        id: 'c_exp',
        title: 'Export Test',
        created_at: Date.now() / 1000,
        messages: [
          { role: 'user', content: 'Question' },
          { role: 'assistant', content: 'Answer' },
        ],
      },
    });

    const origCreateElement = document.createElement.bind(document);
    const clickMock = vi.fn();
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = origCreateElement(tag);
      if (tag === 'a') el.click = clickMock;
      return el;
    });

    // Set active conversation ID
    await managementModule.selectAiConversation('c_exp');

    await managementModule.exportActiveAiThread('markdown');
    await managementModule.exportActiveAiThread('json');

    expect(clickMock).toHaveBeenCalled();
  });

  it('sendAiChatMessage renders exactly ONE assistant response without duplicating bubbles (non-streaming)', async () => {
    vi.spyOn(apiModule.api, 'post').mockResolvedValueOnce({
      status: 'ok',
      reply: 'I was trained on a large dataset of text using a generative pre-trained transformer.',
      active_model: 'hf.co/ConwayResearch/Underdog-Bark-3.0-Pro',
      llm_telemetry: {
        active_model: 'hf.co/ConwayResearch/Underdog-Bark-3.0-Pro',
        tokens_per_sec: 12.6,
        elapsed_ms: 23067,
      },
    });

    await managementModule.sendAiChatMessage('When were you trained?');

    const msgList = document.getElementById('ai-chat-messages-list');
    const userMsgs = msgList.querySelectorAll('.ai-chat-msg-user');
    const botMsgs = msgList.querySelectorAll('.ai-chat-msg-assistant');

    expect(userMsgs.length).toBe(1);
    expect(botMsgs.length).toBe(1);
    expect(botMsgs[0].textContent).toContain('I was trained on a large dataset of text');
  });

  it('sendAiChatMessage renders exactly ONE assistant response when streaming (no duplicate bot bubbles)', async () => {
    const { ReadableStream } = await import('node:stream/web');
    window.ReadableStream = ReadableStream;
    window.__forceAiStreamingTest = true;

    const ssePayload = [
      'event: tool_done\ndata: {"tool":"browse_internet","summary":"5 web source(s) verified"}\n\n',
      'event: token\ndata: {"token":"I was trained on a large dataset."}\n\n',
      'event: done\ndata: {"status":"ok","reply":"I was trained on a large dataset.","tools_called":[{"tool":"browse_internet","summary":"5 web source(s) verified"}],"llm_telemetry":{"active_model":"hf.co/ConwayResearch/Underdog-Bark-3.0-Pro","tokens_per_sec":12.6,"elapsed_ms":23067}}\n\n'
    ].join('');

    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(ssePayload));
        controller.close();
      }
    });

    const origFetch = window.fetch;
    window.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: stream
    });

    try {
      const msgList = document.getElementById('ai-chat-messages-list');
      msgList.innerHTML = '';

      await managementModule.sendAiChatMessage('When were you trained?');

      const userMsgs = msgList.querySelectorAll('.ai-chat-msg-user');
      const botMsgs = msgList.querySelectorAll('.ai-chat-msg-assistant');

      expect(userMsgs.length).toBe(1);
      // MUST be exactly 1 assistant bubble, never 2!
      expect(botMsgs.length).toBe(1);
      expect(botMsgs[0].textContent).toContain('I was trained on a large dataset');
      expect(botMsgs[0].textContent).toContain('browse_internet: 5 web source(s) verified');
      expect(botMsgs[0].textContent).toContain("12.6 tok/s");
    } finally {
      delete window.__forceAiStreamingTest;
      window.fetch = origFetch;
    }
  });

  it('renders Deploy Stack button on compose YAML code blocks and opens stack modal with prefilled YAML', async () => {
    const yamlSnippet = [
      '```yaml',
      'services:',
      '  web:',
      '    image: nginx:alpine',
      '    container_name: test-nginx-copilot',
      '    ports:',
      '      - "8080:80"',
      '```'
    ].join('\n');

    vi.spyOn(apiModule.api, 'post').mockResolvedValue({
      status: 'ok',
      reply: `Here is the requested Compose stack:\n\n${yamlSnippet}`,
      active_model: 'qwen2.5:3b',
    });

    const stackModalModule = await import('../components/stack-modal.js');
    const openStackSpy = vi.spyOn(stackModalModule, 'openStackModal').mockImplementation(async () => {});

    await managementModule.sendAiChatMessage('Generate nginx compose');

    const msgList = document.getElementById('ai-chat-messages-list');
    const deployBtn = msgList.querySelector('.btn-deploy-stack-code');
    expect(deployBtn).not.toBeNull();
    expect(deployBtn.textContent).toContain('Deploy Stack');

    // Trigger deployment
    managementModule.deployComposeStackSnippet(yamlSnippet.replace(/```yaml\n|```/g, ''));
    expect(openStackSpy).toHaveBeenCalledWith('test-nginx-copilot', expect.stringContaining('image: nginx:alpine'));
  });

  it('renameAiConversation without customTitle uses showPromptToast modal instead of native prompt', async () => {
    vi.spyOn(apiModule.api, 'get').mockResolvedValue({
      status: 'ok',
      conversation: { id: 'c_prompt_test', title: 'Test Thread', messages: [] },
    });
    const toastModule = await import('../toast.js');
    const promptToastSpy = vi.spyOn(toastModule, 'showPromptToast');
    const nativePromptSpy = vi.spyOn(window, 'prompt');

    await managementModule.selectAiConversation('c_prompt_test');
    await managementModule.renameAiConversation('c_prompt_test');

    expect(nativePromptSpy).not.toHaveBeenCalled();
    expect(promptToastSpy).toHaveBeenCalled();
  });

  it('deleteAiConversation uses showConfirmToast modal instead of native confirm', async () => {
    const toastModule = await import('../toast.js');
    const confirmToastSpy = vi.spyOn(toastModule, 'showConfirmToast');
    const nativeConfirmSpy = vi.spyOn(window, 'confirm');

    await managementModule.deleteAiConversation('c_del_test');

    expect(nativeConfirmSpy).not.toHaveBeenCalled();
    expect(confirmToastSpy).toHaveBeenCalled();
  });

  it('clearAllAiConversations uses showConfirmToast modal instead of native confirm', async () => {
    const toastModule = await import('../toast.js');
    const confirmToastSpy = vi.spyOn(toastModule, 'showConfirmToast');
    const nativeConfirmSpy = vi.spyOn(window, 'confirm');

    await managementModule.clearAllAiConversations();

    expect(nativeConfirmSpy).not.toHaveBeenCalled();
    expect(confirmToastSpy).toHaveBeenCalled();
  });

  it('renders tool pills with distinct icons and badges for calculate, get_storage_status, and get_network_status', async () => {
    vi.spyOn(apiModule.api, 'post').mockResolvedValueOnce({
      status: 'ok',
      reply: 'Calculation: 67 + 20 = 87',
      active_model: 'hf.co/ConwayResearch/Underdog-Bark-3.0-Pro',
      tools_called: [
        { tool: 'calculate', summary: '67 + 20 = 87' },
        { tool: 'get_storage_status', summary: '4 pool(s): 7.7 TiB free' },
        { tool: 'get_network_status', summary: '1 interface(s), GW: 192.168.1.1' },
      ],
      llm_telemetry: {
        active_model: 'hf.co/ConwayResearch/Underdog-Bark-3.0-Pro',
        tokens_per_sec: 25.0,
        elapsed_ms: 120,
      },
    });

    await managementModule.sendAiChatMessage('Whats 67+20?');

    const msgList = document.getElementById('ai-chat-messages-list');
    const pills = msgList.querySelectorAll('.ai-chat-tool-pill');
    expect(pills.length).toBe(3);

    const calcPill = msgList.querySelector('.ai-chat-tool-pill[data-tool-name="calculate"]');
    expect(calcPill).not.toBeNull();
    expect(calcPill.textContent).toContain('🧮');
    expect(calcPill.textContent).toContain('67 + 20 = 87');

    const storPill = msgList.querySelector('.ai-chat-tool-pill[data-tool-name="get_storage_status"]');
    expect(storPill).not.toBeNull();
    expect(storPill.textContent).toContain('💽');

    const netPill = msgList.querySelector('.ai-chat-tool-pill[data-tool-name="get_network_status"]');
    expect(netPill).not.toBeNull();
    expect(netPill.textContent).toContain('🔌');
  });
});
