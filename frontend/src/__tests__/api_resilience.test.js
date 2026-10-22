import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, auth, setSessionUserProvider } from '../api.js';
import { ZettEventBus } from '../event-bus.js';
import { isOffline } from '../connection.js';

const ok = (body = {}) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

describe('API client resilience (FE-16)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    setSessionUserProvider(null);
  });

  it('times out reads after 15 s', async () => {
    vi.useFakeTimers();
    vi.spyOn(window, 'fetch').mockImplementation((url, opts) => new Promise((_, reject) => {
      opts.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }));
    const p = api.get('/api/slow').catch((e) => e);
    await vi.advanceTimersByTimeAsync(15001);
    const err = await p;
    expect(err.error).toBe('timeout');
  });

  it('shows the offline state on network errors and clears it on the next success', async () => {
    vi.spyOn(window, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce(ok({ a: 1 }));
    await api.get('/api/x').catch(() => {});
    expect(isOffline()).toBe(true);
    expect(document.getElementById('zn-offline-banner').hidden).toBe(false);
    await api.get('/api/x');
    expect(isOffline()).toBe(false);
  });

  it('retries a write after the same user signs in again', async () => {
    auth.setToken('x');
    setSessionUserProvider(() => 'alice');
    const fetchSpy = vi.spyOn(window, 'fetch')
      .mockResolvedValueOnce(new Response('{}', { status: 401 }))
      .mockResolvedValueOnce(ok({ saved: true }));
    const p = api.post('/api/notes', { text: 'hi' });
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    auth.setToken('y'); // new sign-in
    ZettEventBus.emit('auth:login');
    await expect(p).resolves.toEqual({ saved: true });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('does not retry a write as a different user', async () => {
    auth.setToken('x');
    let who = 'alice';
    setSessionUserProvider(() => who);
    vi.spyOn(window, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }));
    const p = api.post('/api/notes', { text: 'hi' }).catch((e) => e);
    await new Promise((r) => setTimeout(r, 0));
    who = 'bob';
    auth.setToken('z');
    ZettEventBus.emit('auth:login');
    const err = await p;
    expect(err.status).toBe(401);
  });
});
