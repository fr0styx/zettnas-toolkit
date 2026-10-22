import { describe, it, expect, vi, afterEach } from 'vitest';
import { sendAiChatMessage, stopAiChatGeneration } from '../components/management.js';

// A streamed reply that sends one token, then hangs until the request is aborted.
function hangingStream(signal, firstChunk) {
  const enc = new TextEncoder();
  let sent = false;
  return {
    getReader() {
      return {
        read() {
          if (!sent) {
            sent = true;
            return Promise.resolve({ value: enc.encode(firstChunk), done: false });
          }
          return new Promise((_, reject) => {
            signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
          });
        },
        cancel() {},
      };
    },
  };
}

describe('AI chat streaming and Stop', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete window.__forceAiStreamingTest;
    document.body.innerHTML = '';
  });

  it('Stop keeps the partial answer and never re-sends the question', async () => {
    document.body.innerHTML = `
      <textarea id="ai-chat-input"></textarea>
      <button id="btn-ai-chat-send"></button>
      <button id="btn-ai-chat-stop" hidden></button>
      <div id="ai-chat-messages-list"></div>`;
    window.__forceAiStreamingTest = true;
    const fetchSpy = vi.spyOn(window, 'fetch').mockImplementation((url, opts) =>
      Promise.resolve({
        ok: true,
        status: 200,
        body: hangingStream(opts.signal, 'event: token\ndata: {"token":"Partial answer"}\n\n'),
      }),
    );

    const pending = sendAiChatMessage('tell me a story');
    await new Promise((r) => setTimeout(r, 20));
    expect(document.getElementById('btn-ai-chat-stop').hidden).toBe(false);
    expect(document.getElementById('ai-chat-messages-list').textContent).toContain('Partial answer');
    expect(stopAiChatGeneration()).toBe(true);
    const res = await pending;

    expect(res.stopped).toBe(true);
    expect(res.reply).toContain('Partial answer');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/media/chat/stream');
    expect(document.getElementById('btn-ai-chat-stop').hidden).toBe(true);
  });
});
